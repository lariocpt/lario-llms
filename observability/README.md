# Local model observability

The existing awsplane Prometheus, Loki and Grafana stores on bigcachy collect
all three chat owners plus the four fixed Intel services and the RTX image runtime.
Inference services are neither restarted nor instrumented in-process.

- https://models.in.drlario.org redirects to the provisioned Local models dashboard.
- https://grafana.in.drlario.org provides metrics, logs and Explore.
- https://prometheus.in.drlario.org provides PromQL and existing read access.
- https://model-telemetry.in.drlario.org is POST ingestion only; it requires a
  separate private 64-character lowercase hex key. It is not a browser UI.

Prometheus stores numeric state and Loki stores sanitized operational events.
Grafana uses its already-provisioned `awsplane-prometheus` / `awsplane-loki` sources.
Retention remains seven days. Existing Caddy LAN/tailnet DNS and wildcard TLS apply;
no new Cloudflare DNS record, internet port or insecure TLS override is required.

## Owners and scope

| Owner | Model services |
| --- | --- |
| l-dev-ai | Geekom native llama-swap, optional admission gateway |
| cachyos-mini-mobile | 7900 XT rootless backend and admission gateway |
| bigcachy | RTX backend/admission, Intel embedding/ASR/translation/TTS, image runtime |

The read-only stdlib exporter binds localhost :9668. It reads `/budget` or legacy
`/running`, Intel health, sysfs AMD telemetry and a bounded NVIDIA query. It never
warms, switches, stops or sends inference. Resident names must be registered.
Unavailable metrics are omitted; unknown legacy occupancy is explicitly labelled.
GPU failure does not become an invented zero-temperature or zero-memory reading.
Intel health reflects its fixed configured CPU/GPU/NPU device, not measured NPU load.
No tokens/second or time-to-first-token is claimed from request duration.

Alloy 1.20.1 is pinned with the official archive SHA256 in `install.py`.
Each user collector reads only allowlisted model units from its own journal.
It emits known method/path/status/duration fields and fixed runtime event keywords.
Raw messages, prompts, generated text, headers, addresses, arbitrary URLs and
tracebacks are not shipped. Full diagnostics stay in the owner's journal.
The duplicate Podman journal stream is excluded. No session IDs are metric labels.
Log panels filter by host/unit; hardware filters apply to metric panels.
The image-runtime gauge reports ComfyUI availability, not whether its weights are
loaded; idle image generation is normally stopped.

Metrics have a 24-hour persistent remote-write WAL. Durable Loki WAL is currently
an **experimental Alloy component feature**, enabled explicitly for this collector
only; it does not change model promotion status. Log WAL segments expire after
24 hours. Offline collectors restart independently and retry when the central host
returns; data outside the configured retention window can be lost. Journal cursors
and WAL live under `~/.local/state/lario-model-alloy`, outside all repositories.

## Install or repair

Generate one dedicated push key privately on bigcachy; put its value in the
ignored `lario-home-infra/caddy/.env` as `MODEL_TELEMETRY_KEY` and install the same
value in each owner's `~/.config/lario-observability/push.key`, mode 0600.
Never distribute inference/backend/management keys to monitoring components.
The Caddy exact-key and format checks reject requests when the key is unset.

Download `alloy-linux-amd64.zip` from the official v1.20.1 release, then run on each
owner, from its synced source:

```sh
python3 observability/install.py --archive /path/to/alloy-linux-amd64.zip
systemctl --user status lario-model-exporter lario-model-alloy
curl -fsS http://127.0.0.1:9668/metrics
```

The installer verifies the archive, renders the host unit allowlist, validates
Alloy config, and enables only the two observability user services. Preserve user
lingering for reboot startup. The collectors can start in either host boot order.
The exporter is independent of inference readiness and the eGPU's presence.

Central changes live in awsplane's compose and provisioned dashboard. Reconcile
only Prometheus when adding its remote-write receiver; Grafana loads the dashboard
from its mounted directory. Apply the Caddy source through home-infra's normal
validation and file-bind-aware deployment procedure. Check `plane doctor` afterward.

## Verification

Check `lario_model_ready`, `lario_model_info`, GPU gauges, and
`time() - max_over_time(lario_exporter_last_success_unixtime[24h])` in Prometheus.
Check `{job="lario_models"}` in Loki/Grafana. A stopped owner should show unavailable;
an offline host's last observation ages rather than causing a model restart.
Anonymous ingestion, an incorrect key, other paths and GET ingestion must fail.
Prove records from each host, not just healthy monitoring containers.

Primary references:
[Alloy journal collection](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/),
[remote-write buffering](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/),
[Loki writer durability](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.write/),
[Prometheus exposition](https://prometheus.io/docs/instrumenting/exposition_formats/).
