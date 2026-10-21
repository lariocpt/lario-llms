"""Authenticated, owner-backed model control page. Never forwards management keys to browsers."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import re

import aiohttp
from aiohttp import web

WEB=Path(__file__).with_name('web')


def password_hash(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()


def create_panel(config,state_dir):
    directory=Path(state_dir);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/'sessions.sqlite3'
    fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, csrf TEXT, expires REAL)')
    app=web.Application(client_max_size=8192)
    app['config']=config;app['db']=db;app['snapshot']={'owners':{},'updated_at':None}
    failures={}
    origin=config.get('origin','https://models.in.drlario.org')
    secure=origin.startswith('https://')

    @web.middleware
    async def security(request,handler):
        if request.method=='POST' and request.headers.get('Origin')!=origin:
            raise web.HTTPForbidden(text='Origin mismatch')
        if request.path not in ('/login','/assets/style.css') and not request.path.startswith('/assets/'):
            token=request.cookies.get('lario_models','')
            row=db.execute('SELECT csrf,expires FROM sessions WHERE token=?',
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone() if token else None
            if not row or row[1]<time.time():
                if request.path.startswith('/api/'):
                    raise web.HTTPUnauthorized(text='Operator login required')
                raise web.HTTPFound('/login')
            request['session_hash']=hashlib.sha256(token.encode()).hexdigest()
            request['csrf']=row[0]
            if request.method=='POST' and not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),row[0]):
                raise web.HTTPForbidden(text='CSRF token required')
        response=await handler(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'same-origin',
            'Content-Security-Policy':"default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        return response
    app.middlewares.append(security)

    async def owner(hardware,path,body=None):
        entry=config['owners'].get(hardware)
        if entry is None:raise web.HTTPNotFound()
        async with app['http'].request('POST' if body is not None else 'GET',entry['url']+'/admin/v1/'+path,
                json=body,headers={'Authorization':'Bearer '+entry['management_key']},
                timeout=aiohttp.ClientTimeout(total=100 if body is not None else 8)) as response:
            try:data=await response.json()
            except ValueError:data={'error':{'message':'Owner returned an invalid response'}}
            return response.status,data

    async def poll():
        while True:
            async def inspect(hardware):
                now=time.time()
                try:
                    status,data=await owner(hardware,'state')
                    if status!=200:raise RuntimeError('owner unavailable')
                    cstatus,catalog=await owner(hardware,'catalog')
                    if cstatus!=200:raise RuntimeError('catalog unavailable')
                    return hardware,{'state':data,'catalog':catalog,'observed_at':now,'offline':False}
                except (aiohttp.ClientError,TimeoutError,RuntimeError):
                    previous=app['snapshot']['owners'].get(hardware,{})
                    return hardware,{**previous,'offline':True,'checked_at':now}
            values=await asyncio.gather(*(inspect(h) for h in config['owners']))
            app['snapshot']={'owners':dict(values),'updated_at':time.time()}
            await asyncio.sleep(2)

    async def lifecycle(app):
        async with aiohttp.ClientSession() as session:
            app['http']=session
            task=asyncio.create_task(poll())
            yield
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        db.close()
    app.cleanup_ctx.append(lifecycle)

    async def login(request):
        if request.method=='GET':return web.FileResponse(WEB/'login.html')
        identity=request.remote or 'unknown';now=time.time()
        attempts=[t for t in failures.get(identity,[]) if t>now-900]
        if len(attempts)>=5:raise web.HTTPTooManyRequests(text='Try again later')
        form=await request.post()
        digest=await asyncio.to_thread(password_hash,str(form.get('password','')),config['password_salt'])
        if not hmac.compare_digest(str(form.get('username','')),config['username']) or not hmac.compare_digest(digest,config['password_hash']):
            failures[identity]=attempts+[now]
            raise web.HTTPUnauthorized(text='Invalid operator credentials')
        failures.pop(identity,None)
        token,csrf=secrets.token_urlsafe(40),secrets.token_urlsafe(32)
        with db:
            db.execute('DELETE FROM sessions WHERE expires<?',(now,))
            db.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),csrf,now+43200))
        response=web.Response(status=302,headers={'Location':'/'})
        response.set_cookie('lario_models',token,secure=secure,httponly=True,samesite='Strict',max_age=43200,path='/')
        return response

    async def state(request):
        return web.json_response({**app['snapshot'],'csrf':request['csrf']})

    async def operation(request):
        hardware=request.match_info['hardware']
        try:body=await request.json()
        except ValueError:raise web.HTTPBadRequest(text='JSON required')
        if not isinstance(body,dict):raise web.HTTPBadRequest()
        try:status,data=await owner(hardware,'operations',body)
        except (aiohttp.ClientError,TimeoutError):
            return web.json_response({'error':{'message':'Owner outcome unconfirmed; refresh before retrying.'}},status=503)
        if status==200 and body.get('action') in ('cancel','cancel-all','cancel-and-off'):
            unique={}
            for run in data.get('cancelled_runs',[]):
                key=(run['client'],run.get('instance_id'),run.get('session_id'),run.get('run_id'))
                unique[key]=run
            outcomes=await asyncio.gather(*(interrupt(run) for run in unique.values()))
            data['agent_interruptions']=outcomes
            with db:
                db.execute('INSERT INTO audit VALUES (?,?,?,?)',
                    (time.time(),hardware,body['action'],json.dumps(outcomes)))
        return web.json_response(data,status=status)

    async def interrupt(run):
        client=config.get('clients',{}).get(run['client'])
        identity={k:run.get(k,'') for k in ('session_id','run_id','instance_id','location')}
        result={'client':run['client'],'session_id':identity['session_id']}
        if not client or not run.get('registered_client') or not all(identity.values()):
            return {**result,'status':'unsupported','detail':'Inference cancelled; runner identity/control unavailable.'}
        host=client['host']
        if not re.fullmatch(r'[a-zA-Z0-9@.:-]+',host):
            return {**result,'status':'unconfirmed'}
        try:
            process=await asyncio.create_subprocess_exec('ssh','-T','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                '-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8',
                '-o','UserKnownHostsFile='+config['ssh_known_hosts'],
                '-i',config['ssh_key'],host,'lario-model-control-v1',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            try:
                output,_=await asyncio.wait_for(process.communicate(json.dumps({'operation':'cancel',**identity}).encode()),timeout=55)
            except BaseException:
                if process.returncode is None:process.kill()
                await process.wait();raise
            parsed=json.loads(output)
            if process.returncode:raise RuntimeError('client unavailable')
            return {**result,'status':parsed['status'],'interrupted':parsed['interrupted']}
        except (OSError,ValueError,KeyError,RuntimeError,TimeoutError):
            return {**result,'status':'unconfirmed','detail':'Inference cancelled; client interruption could not be confirmed.'}

    async def events(request):
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream','Cache-Control':'no-store'})
        await response.prepare(request)
        try:
            while True:
                row=db.execute('SELECT expires FROM sessions WHERE token=?',(request['session_hash'],)).fetchone()
                if not row or row[0]<time.time():break
                await response.write(('data: '+json.dumps(app['snapshot'])+'\n\n').encode())
                await asyncio.sleep(2)
        except (ConnectionError,asyncio.CancelledError):pass
        return response

    async def logout(request):
        token=request.cookies.get('lario_models','')
        with db:db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),))
        response=web.json_response({'ok':True});response.del_cookie('lario_models');return response

    db.execute('CREATE TABLE IF NOT EXISTS audit (created REAL, hardware TEXT, action TEXT, outcome TEXT)')
    app.router.add_get('/login',login)
    app.router.add_post('/login',login)
    async def index(request):return web.FileResponse(WEB/'index.html')
    app.router.add_get('/',index)
    app.router.add_get('/api/state',state)
    app.router.add_get('/api/events',events)
    app.router.add_post('/api/operations/{hardware}',operation)
    app.router.add_post('/logout',logout)
    app.router.add_static('/assets/',WEB)
    return app


if __name__=='__main__':
    config=json.loads(Path(os.getenv('LARIO_PANEL_CONFIG','/config/panel.json')).read_text())
    web.run_app(create_panel(config,os.getenv('LARIO_PANEL_STATE','/state')),
                host='0.0.0.0',port=int(os.getenv('LARIO_PANEL_PORT','9670')),access_log=None)
