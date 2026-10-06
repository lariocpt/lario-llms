#!/usr/bin/env python3
"""Authenticated streaming admission in front of one private hardware proxy."""
import argparse
import asyncio
from collections import Counter
import hashlib
import hmac
import json
import os
from pathlib import Path
import shlex
import sys
import time
from urllib.parse import urlparse, quote

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.modelctl import fleet_capacity, assert_device_ready, selection, effective_models, model_aliases

INFERENCE = {"/v1/chat/completions", "/v1/completions", "/v1/responses", "/v1/messages", "/completion"}
PUBLIC_READ = {"/health", "/v1/models", "/budget"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
               "trailer", "transfer-encoding", "upgrade", "content-length", "content-encoding"}


class Admission:
    def __init__(self, registry, upstream, keys, backend_key, probe=None, device_check=None):
        self.reg = registry
        self.upstream = upstream.rstrip("/")
        self.keys = keys
        self.backend_key = backend_key
        self.probe = probe
        self.device_check = device_check
        self.device_good_until = 0
        self.session = None
        self.lock = asyncio.Lock()
        self.active = Counter()
        self.rejections = Counter()
        self.draining = False
        # Reconcile backend occupancy after every process restart and uncertain end.
        self.uncertain = True
        self.started = time.time()

    async def json_get(self, url):
        async with self.session.get(url, headers={"Authorization": "Bearer " + self.backend_key},
                                    timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            return await response.json()

    async def inspect(self):
        if self.device_check and time.monotonic() >= self.device_good_until:
            await asyncio.to_thread(self.device_check, self.reg)
            self.device_good_until = time.monotonic() + 5
        if self.probe:
            state = await self.probe()
            state['agents'] = fleet_capacity(state['slots'],state['reserved'],state['context'])
            return state
        running = (await self.json_get(self.upstream + "/running")).get("running", [])
        ready = [m for m in running if m.get("state") == "ready"]
        if len(running) != 1 or len(ready) != 1 or ready[0]["model"] not in self.reg["models"]:
            raise RuntimeError("no single registered backend ready")
        item = ready[0]
        args = shlex.split(item["cmd"])
        slots = int(args[args.index("--parallel")+1])
        total = int(args[args.index("-c")+1])
        reserved = self.reg["models"][item["model"]]["reserved"]
        if slots < 1 or total % slots or total // slots < 4096 or not 0 <= reserved <= slots:
            raise RuntimeError("invalid live geometry")
        parsed = urlparse(item["proxy"])
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.scheme != "http":
            raise RuntimeError("unexpected private model endpoint")
        # All backend requests are authenticated. Private container server ports need
        # not be published: llama-swap exposes the resident server's read-only slots.
        if sum(self.active.values()):
            return {"model": item["model"], "slots": slots, "reserved": reserved,
                    "context": total//slots, "agents": fleet_capacity(slots,reserved,total//slots), "busy": sum(self.active.values()),
                    "generation": hashlib.sha256(item["cmd"].encode()).hexdigest()}
        live_slots = await self.json_get(self.upstream + "/upstream/" + quote(item["model"], safe="") + "/slots")
        if not isinstance(live_slots, list) or len(live_slots) != slots:
            raise RuntimeError("unknown backend occupancy")
        if any(type(s.get("is_processing")) is not bool for s in live_slots):
            raise RuntimeError("unknown slot state")
        busy = sum(s["is_processing"] for s in live_slots)
        return {"model": item["model"], "slots": slots, "reserved": reserved,
                "context": total // slots, "agents": fleet_capacity(slots,reserved,total//slots), "busy": busy,
                "generation": hashlib.sha256(item["cmd"].encode()).hexdigest()}

    def role(self, request):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token:
            raise web.HTTPUnauthorized(text='{"error":"credential_required"}', content_type="application/json")
        for role, key in self.keys.items():
            if hmac.compare_digest(token, key):
                return role
        raise web.HTTPUnauthorized(text='{"error":"unknown_credential"}', content_type="application/json")

    async def budget(self):
        async with self.lock:
            try:
                state = await self.inspect()
                if self.uncertain and not sum(self.active.values()) and state["busy"] == 0:
                    self.uncertain = False
                ready = not self.uncertain and not self.draining
                return {**state, "hardware": self.reg["aliases"][0], "ready": ready,
                        "agents": state["agents"] if ready else 0,
                        "active": dict(self.active), "rejections": dict(self.rejections),
                        "available": max(0, state["slots"]-sum(self.active.values())) if ready else 0,
                        "enforced": True, "draining": self.draining, "uncertain": self.uncertain}
            except Exception:
                return {"hardware": self.reg["aliases"][0], "ready": False, "agents": 0,
                        "available": 0, "enforced": True, "active": dict(self.active)}

    async def acquire(self, role, model):
        async with self.lock:
            try:
                state = await self.inspect()
            except Exception:
                raise web.HTTPServiceUnavailable(text='{"error":"backend_unavailable"}', content_type="application/json")
            if self.uncertain and not sum(self.active.values()) and state["busy"] == 0:
                self.uncertain = False
            if self.draining or self.uncertain:
                raise web.HTTPServiceUnavailable(text='{"error":"hardware_draining_or_reconciling"}',
                                                 headers={"Retry-After": "5"}, content_type="application/json")
            names = {state["model"], *self.reg["models"][state["model"]].get("aliases", [])}
            # Hardware aliases only resolve to the selected profile, which can differ
            # from a concrete ID loaded through the old API. Verify that selection.
            selected_file = ROOT / self.reg["state"]
            selected = selected_file.read_text().strip() if selected_file.exists() else None
            if selected == state["model"]:
                names.update(self.reg["aliases"])
                # A saved profile alone is insufficient: its actual running geometry
                # must match before accepting a request with that profile's limits.
                try:
                    _, preset = selection(self.reg)
                    spec = effective_models(self.reg, preset)[state["model"]]
                    if (spec["context"], spec["slots"], spec["reserved"]) == (
                            state["context"], state["slots"], state["reserved"]):
                        names.update(model_aliases(self.reg, state["model"], preset))
                except (OSError, ValueError, KeyError, RuntimeError):
                    pass
            if model not in names:
                self.rejections["swap"] += 1
                raise web.HTTPConflict(text='{"error":"model_not_resident","hint":"select an idle hardware profile with modelctl"}',
                                       content_type="application/json")
            if role not in ("interactive", "fleet", "auxiliary"):
                raise web.HTTPForbidden(text='{"error":"management_key_cannot_infer"}', content_type="application/json")
            # RTX has only auxiliary capacity. Other hardware allows interactive to
            # use idle unreserved slots, while fleet never borrows coding reservations.
            if (role in ("fleet", "auxiliary") and self.reg["aliases"][0] != "rtx5080" and
                    self.active["fleet"] + self.active["auxiliary"] >= state["agents"] or
                    self.reg["aliases"][0] == "rtx5080" and role != "auxiliary" or
                    sum(self.active.values()) >= state["slots"]):
                self.rejections[role] += 1
                raise web.HTTPTooManyRequests(text='{"error":"hardware_capacity_exhausted"}',
                                              headers={"Retry-After": "2"}, content_type="application/json")
            self.active[role] += 1
            return state

    async def release(self, role, clean):
        async with self.lock:
            self.active[role] -= 1
            if not clean:
                self.uncertain = True


def create_app(registry, upstream, keys, backend_key, probe=None, device_check=None):
    if set(keys) != {"interactive", "fleet", "auxiliary", "management"}:
        raise ValueError("four distinct class credentials required")
    if any(len(k) < 24 for k in [*keys.values(), backend_key]) or len(set(keys.values())) != 4 or backend_key in keys.values():
        raise ValueError("credentials must be distinct and at least 24 characters")
    admission = Admission(registry, upstream, keys, backend_key, probe, device_check)
    app = web.Application(client_max_size=50*1024*1024, handler_args={"handler_cancellation": True})
    app["admission"] = admission

    async def lifecycle(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=7200), auto_decompress=False) as session:
            admission.session = session
            yield
    app.cleanup_ctx.append(lifecycle)

    async def handler(request):
        if request.method == "GET" and request.path in ("/budget", "/health"):
            budget = await admission.budget()
            return web.json_response(budget, status=200 if request.path == "/budget" or budget["ready"] else 503)
        if request.path.startswith("/admin/"):
            if admission.role(request) != "management":
                raise web.HTTPForbidden()
            if request.method != "POST" or request.path not in ("/admin/drain", "/admin/resume"):
                raise web.HTTPNotFound()
            async with admission.lock:
                if request.path.endswith("drain"):
                    admission.draining = True
                else:
                    if sum(admission.active.values()):
                        raise web.HTTPConflict(text="active requests")
                    admission.uncertain = True
                    admission.draining = False
            return web.json_response(await admission.budget())
        if request.method == "GET" and request.path == "/v1/models":
            # Discovery never loads a model and does not reveal backend process args.
            async with admission.session.get(admission.upstream + request.path,
                    headers={"Authorization": "Bearer " + backend_key}) as response:
                return web.Response(body=await response.read(), status=response.status,
                                    content_type="application/json")
        if request.method != "POST" or request.path not in INFERENCE:
            raise web.HTTPNotFound()
        role = admission.role(request)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="invalid JSON")
        if not isinstance(body, dict) or not isinstance(body.get("model"), str):
            raise web.HTTPBadRequest(text="model is required")
        state = await admission.acquire(role, body["model"])
        # Forward the verified concrete resident ID, never an alias that could swap.
        body["model"] = state["model"]
        clean = False
        current_task = asyncio.current_task()

        async def watch_disconnect():
            while True:
                await asyncio.sleep(0.1)
                if request.transport is None or request.transport.is_closing():
                    current_task.cancel()
                    return
        watcher = asyncio.create_task(watch_disconnect())
        try:
            async with admission.session.post(admission.upstream + request.path, json=body,
                    headers={"Authorization": "Bearer " + backend_key}) as upstream_response:
                headers = {k:v for k,v in upstream_response.headers.items() if k.lower() not in HOP_HEADERS}
                response = web.StreamResponse(status=upstream_response.status, headers=headers)
                await response.prepare(request)
                terminal = not (request.path in ("/v1/chat/completions", "/v1/completions")
                                and body.get("stream") is True and upstream_response.status == 200)
                tail = b""
                async for data in upstream_response.content.iter_any():
                    tail = (tail + data)[-64:]
                    terminal = terminal or b"data: [DONE]" in tail
                    await response.write(data)
                await response.write_eof()
                clean = upstream_response.status < 500 and terminal
                return response
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
            raise web.HTTPBadGateway(text='{"error":"upstream_failed"}', content_type="application/json")
        finally:
            watcher.cancel()
            # Shield accounting from the request's cancellation. Uncertain work is
            # quarantined until the backend slots report idle, including after restart.
            await asyncio.shield(admission.release(role, clean))
            await asyncio.gather(watcher, return_exceptions=True)

    app.router.add_route("*", "/{tail:.*}", handler)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hardware", choices=["geekom", "7900xt", "rtx5080"])
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--listen", action="append", default=[])
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    registry = json.loads((ROOT / args.hardware / "models.json").read_text())
    keys = {role:os.environ["LARIO_"+role.upper()+"_KEY"] for role in ("interactive","fleet","auxiliary","management")}
    app = create_app(registry, args.upstream, keys, os.environ["LARIO_BACKEND_KEY"], device_check=assert_device_ready)
    web.run_app(app, host=args.listen or os.environ.get("LARIO_LISTEN", "127.0.0.1").split(","), port=args.port, access_log=None,
                handler_cancellation=True)


if __name__ == "__main__":
    main()
