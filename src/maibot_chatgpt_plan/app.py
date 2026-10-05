"""Local, single-user ChatGPT plan bridge. OAuth tokens use Windows DPAPI."""
import asyncio
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import secrets
import time
import uuid

import aiohttp
from aiohttp import web
import jwt
import tomlkit
from .storage import protect_write, protected_read, secure_directory
from .protocol import normalize_request
from .adapter import add_model_option
from .auth import validate_id_token

DEFAULT_PORT = 8776
AUTH = 'https://auth.openai.com/api/accounts'
RESOURCE = 'https://api.openai.com/v1'
PROVIDER = 'MaiBot-ChatGPT-Plan'
MODEL_NAME = 'chatgpt-plan-local'

class Bridge:
    def __init__(self, state_dir=None, config_path=None, port=DEFAULT_PORT):
        if state_dir is None:
            state_dir = Path(os.environ['LOCALAPPDATA']) / 'MaiBotChatGPTPlan'
        state_dir = Path(state_dir)
        self.port = port
        self.origin = f'http://127.0.0.1:{port}'
        self.callback_uri = self.origin + '/auth/callback'
        secure_directory(state_dir)
        self.state_dir = state_dir
        self.config_path = Path(config_path).resolve() if config_path else None
        state_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_path = state_dir / 'runtime.dpapi'
        self.credentials_path = state_dir / 'credentials.dpapi'
        self.runtime = protected_read(self.runtime_path) or {
            'host_id': 'urn:uuid:' + str(uuid.uuid4()), 'key': secrets.token_urlsafe(32)}
        protect_write(self.runtime_path, self.runtime)
        if self.config_path is None and self.runtime.get('config_path'):
            self.config_path = Path(self.runtime['config_path'])
        self.credentials = protected_read(self.credentials_path)
        self.pending = None
        self.csrf = secrets.token_urlsafe(32)
        self.refresh_lock = asyncio.Lock()
        self.models_lock = asyncio.Lock()
        self.activation_lock = asyncio.Lock()
        self.models = []
        self.message = '请选择 MaiBot 配置，再登录 ChatGPT 并授权。'
        self.last_tested_model = None
        self.session = None

    async def start(self, app):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180), trust_env=True)

    async def stop(self, app):
        await self.session.close()

    def save_credentials(self, value):
        protect_write(self.credentials_path, value)
        self.credentials = value

    def control_allowed(self, request):
        return (request.headers.get('Origin') == self.origin and
                secrets.compare_digest(request.cookies.get('bridge_csrf', ''), self.csrf))

    async def token(self):
        async with self.refresh_lock:
            c = self.credentials
            if not c or 'chatgpt.tokens.use.direct' not in c.get('scopes', []):
                raise web.HTTPUnauthorized(text='请先登录并授权使用 ChatGPT 订阅额度。')
            if c['expires_at'] > time.time() + 90:
                return c['access_token']
            async with self.session.post(AUTH + '/oauth/token', data={
                'grant_type': 'refresh_token', 'client_id': c['client_id'],
                'refresh_token': c['refresh_token'], 'resource': RESOURCE}) as r:
                if r.status != 200:
                    raise web.HTTPUnauthorized(text='订阅授权刷新失败，请重新登录。')
                tokens = await r.json()
            updated = dict(c)
            for key in ('access_token', 'refresh_token', 'id_token', 'token_type'):
                if key in tokens:
                    updated[key] = tokens[key]
            if 'scope' in tokens:
                updated['scopes'] = tokens['scope'].split()
            updated['expires_at'] = time.time() + tokens.get('expires_in', 3600)
            self.save_credentials(updated)
            if 'chatgpt.tokens.use.direct' not in updated['scopes']:
                raise web.HTTPUnauthorized(text='未获得使用订阅额度的权限。')
            return updated['access_token']

    async def page(self, request):
        if self.credentials and not self.models:
            try:
                await self.load_models()
            except Exception:
                self.message = '无法获取可用模型，请检查网络、额度或重新登录。'
        account = html.escape((self.credentials or {}).get('email', '尚未连接'))
        config_display = html.escape(str(self.config_path or ''), quote=True)
        options = ''.join(f'<option value="{html.escape(m["slug"], quote=True)}">{html.escape(m.get("display_name", m["slug"]))}</option>' for m in self.models)
        body = f'''<!doctype html><meta charset="utf-8"><title>MaiBot ChatGPT Plus</title>
        <style>body{{font:16px system-ui;max-width:720px;margin:60px auto;padding:20px;background:#f7f8fa}}button,select{{font:inherit;padding:12px;margin:8px 0}}article{{background:white;padding:28px;border-radius:16px}}</style>
        <article><h1>MaiBot · ChatGPT Plan</h1><p>账号：{account}</p><p>{html.escape(self.message)}</p>
        <form method="post" action="/settings"><label>MaiBot 的 model_config.toml 路径</label><br><input name="config_path" value="{config_display}" style="width:95%;padding:10px" required><br><button>保存配置位置</button></form>
        <form method="post" action="/login"><button>Continue with ChatGPT</button></form>
        <form method="post" action="/activate"><select name="model">{options}</select><br><label><input type="checkbox" name="personal_use" required> 我确认仅用于自己的请求，并授权个人自动化使用订阅额度。</label><br><button {'disabled' if not options else ''}>测试并添加 GPT 可选模型</button></form>
        <p>授权后使用 ChatGPT 订阅额度。测试会发送一句简短问候；成功后添加 GPT 模型供你选择，当前各任务的模型设置保持不变。</p>
        <p>公开版当前支持文本请求。各应用共享账号额度，不增加可用额度。授权凭据使用 Windows DPAPI 加密保存，输入将发送给 OpenAI。本程序不记录聊天内容。</p>
        <p><a href="/privacy">隐私说明</a> · <a href="https://openai.com/policies/sign-in-with-chatgpt-terms/" target="_blank" rel="noreferrer">使用条款</a></p>
        <p><a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer">Manage usage · 查看额度</a></p>
        <form method="post" action="/logout"><button>断开订阅授权</button></form></article>'''
        response = web.Response(text=body, content_type='text/html')
        response.set_cookie('bridge_csrf', self.csrf, httponly=True, samesite='Strict')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://auth.openai.com; frame-ancestors 'none'"
        return response

    async def login(self, request):
        if not self.control_allowed(request):
            raise web.HTTPForbidden(text='页面会话已过期或浏览器未发送本地 Cookie，请刷新本地页面后重试。')
        from urllib.parse import urlencode
        if self.config_path is None:
            self.message = '请先保存 MaiBot 配置位置。'
            raise web.HTTPFound('/')
        verifier = secrets.token_urlsafe(48)
        self.pending = {'state': secrets.token_urlsafe(32), 'nonce': secrets.token_urlsafe(32),
                        'verifier': verifier, 'created': time.time(), 'client_id': (self.credentials or {}).get('client_id')}
        p = self.pending
        params = {'client_id': p['client_id'] or 'dynamic_agent_client',
                  'ext_agent_host_id': self.runtime['host_id'], 'response_type': 'code',
                  'redirect_uri': self.callback_uri, 'scope': 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',
                  'resource': RESOURCE, 'state': p['state'], 'nonce': p['nonce'],
                  'code_challenge_method': 'S256',
                  'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
        if not p['client_id']:
            params['agent_name_hint'] = 'MaiBot ChatGPT Plan'
        elif self.credentials.get('id_token'):
            params['id_token_hint'] = self.credentials['id_token']
        raise web.HTTPFound(AUTH + '/authorize?' + urlencode(params))

    async def callback(self, request):
        p = self.pending
        if not p or time.time() - p['created'] > 600 or not secrets.compare_digest(request.query.get('state', ''), p['state']):
            raise web.HTTPBadRequest(text='授权请求无效或已过期，请重新登录。')
        self.pending = None
        try:
            if request.query.get('error'):
                raise ValueError('授权被取消，请重新登录并允许使用订阅额度。')
            client_id = request.query.get('client_id') or p['client_id']
            if not client_id or client_id == 'dynamic_agent_client' or (p['client_id'] and client_id != p['client_id']):
                raise ValueError('授权返回的客户端身份不匹配。')
            async with self.session.post(AUTH + '/oauth/token', data={
                'grant_type': 'authorization_code', 'client_id': client_id, 'code': request.query['code'],
                'code_verifier': p['verifier'], 'redirect_uri': self.callback_uri, 'resource': RESOURCE}) as r:
                if r.status != 200:
                    raise ValueError(f'授权交换失败（HTTP {r.status}），请重新登录。')
                tokens = await r.json()
            async with self.session.get('https://auth.openai.com/.well-known/openid-configuration') as r:
                r.raise_for_status()
                oidc = await r.json()
            if oidc['issuer'] != 'https://auth.openai.com':
                raise ValueError('身份服务 issuer 不匹配。')
            async with self.session.get(oidc['jwks_uri']) as r:
                r.raise_for_status()
                jwks = await r.json()
            claims = validate_id_token(tokens['id_token'], jwks, client_id, p['nonce'])
            if p['client_id'] and claims['sub'] != self.credentials['subject']:
                raise ValueError('登录账号与原授权账号不匹配。')
            scopes = tokens.get('scope', '').split()
            if 'chatgpt.tokens.use.direct' not in scopes:
                raise ValueError('没有获得使用 ChatGPT 订阅额度的权限。')
            self.save_credentials({**tokens, 'client_id': client_id, 'subject': claims['sub'],
                                   'email': claims.get('email', ''), 'scopes': scopes,
                                   'expires_at': time.time() + tokens.get('expires_in', 3600)})
            await self.load_models()
            self.message = '已授权。请选择模型，测试后添加可选模型。'
        except Exception as e:
            # Do not expose OAuth responses, URLs or exception values containing credentials.
            self.message = str(e) if isinstance(e, ValueError) and not isinstance(e, jwt.PyJWTError) else '授权未完成或模型列表获取失败，请重试。'
        raise web.HTTPFound('/')

    async def load_models(self):
        token = await self.token()
        async with self.session.get(RESOURCE + '/models', headers={'Authorization': 'Bearer ' + token}) as r:
            r.raise_for_status()
            data = await r.json()
        self.models = [m for m in data.get('models', []) if m.get('visibility') == 'list' and m.get('slug')]
        if not self.models:
            raise ValueError('账号没有返回可用订阅模型，请检查授权和账号资格。')

    async def activate(self, request):
        if not self.control_allowed(request):
            raise web.HTTPForbidden()
        form = await request.post()
        if form.get('personal_use') != 'on':
            raise web.HTTPBadRequest(text='请确认个人使用并授权自动化。')
        model = form.get('model')
        if model not in [m['slug'] for m in self.models]:
            raise web.HTTPBadRequest(text='请先登录并选择可用模型。')
        async with self.activation_lock:
            try:
                token = await self.token()
                completed = False
                async with self.session.post(RESOURCE + '/responses', headers={'Authorization': 'Bearer ' + token},
                    json={'model': model, 'input': [{'role': 'user', 'content': '请只回复：连接成功'}], 'store': False, 'stream': True}) as r:
                    if r.status != 200:
                        detail = await self.error_detail(r)
                        raise ValueError(f'测试请求失败（HTTP {r.status}）：{detail}。没有添加模型。')
                    async for raw in r.content:
                        if raw.startswith(b'data: '):
                            data = raw[6:].strip()
                            if data == b'[DONE]':
                                continue
                            event = json.loads(data)
                            if event.get('type') == 'response.completed':
                                completed = True
                            elif event.get('type') in ('response.failed', 'response.incomplete', 'error'):
                                raise ValueError('测试未完成，请检查订阅额度；没有添加模型。')
                if not completed:
                    raise ValueError('测试连接提前结束，没有添加模型。')
                self.configure(model)
                self.last_tested_model = model
                self.message = '测试成功，已添加 chatgpt-plan-local 可选模型。当前任务模型保持不变，你可以在 MaiBot 模型设置中自行选择 GPT。'
            except Exception as e:
                self.message = str(e) if type(e) is ValueError else '测试或保存配置失败，未确认添加成功。'
        raise web.HTTPFound('/')

    async def error_detail(self, response):
        try:
            payload = await response.json()
            error = payload.get('error') or {}
            detail = payload.get('detail') or payload.get('message') or (error.get('message') if isinstance(error, dict) else error)
            if not isinstance(detail, str):
                return '上游未提供具体错误'
            for key in ('access_token', 'refresh_token', 'id_token'):
                value = (self.credentials or {}).get(key)
                if value:
                    detail = detail.replace(value, '[redacted]')
            return detail.replace(self.runtime['key'], '[redacted]')[:240]
        except Exception:
            return '上游未返回可解析的错误信息'

    def configure(self, model):
        if self.config_path is None:
            raise ValueError('请先保存 MaiBot 配置位置。')
        add_model_option(self.config_path, self.state_dir, model, self.origin,
                         self.runtime['key'], PROVIDER, MODEL_NAME)
        self.runtime.update(config_path=str(self.config_path), allowed_model=model,
                            personal_use_authorized_at=time.time())
        protect_write(self.runtime_path, self.runtime)

    async def settings(self, request):
        if not self.control_allowed(request):
            raise web.HTTPForbidden()
        form = await request.post()
        path = Path(form.get('config_path', '')).expanduser()
        if path.name != 'model_config.toml' or not path.is_file():
            self.message = '请选择已有的 MaiBot model_config.toml 文件。'
        else:
            try:
                doc = tomlkit.parse(path.read_text(encoding='utf-8-sig'))
                if not all(k in doc for k in ('api_providers', 'models', 'model_task_config')):
                    raise ValueError()
                if self.config_path and path.resolve() != self.config_path:
                    self.runtime.pop('allowed_model', None)
                    self.runtime.pop('personal_use_authorized_at', None)
                self.config_path = path.resolve()
                self.runtime['config_path'] = str(self.config_path)
                protect_write(self.runtime_path, self.runtime)
                self.message = '配置位置已保存；模型与任务配置尚未改变。'
            except Exception:
                self.message = '配置文件格式不符合 MaiBot 要求。'
        raise web.HTTPFound('/')

    async def privacy(self, request):
        return web.Response(text='本工具只服务你连接的 MaiBot。账号邮箱、OAuth 令牌、客户端标识和本地连接密钥保存在你控制的本机目录，使用 Windows DPAPI 加密。聊天输入经 HTTPS 发送给 OpenAI；程序不记录输入或输出，不发送遥测。完整配置备份也加密保存。订阅调用受 OpenAI 条款和额度限制；不得用于满足他人请求或转租额度。断开授权会撤销会话并清除本地令牌。', content_type='text/plain')

    async def logout(self, request):
        if not self.control_allowed(request):
            raise web.HTTPForbidden()
        async with self.activation_lock, self.refresh_lock:
            c = self.credentials
            revoked = not c
            try:
                if c:
                    async with self.session.get('https://auth.openai.com/.well-known/openid-configuration') as r:
                        r.raise_for_status()
                        metadata = await r.json()
                    async with self.session.post(metadata['revocation_endpoint'], data={
                        'token': c['refresh_token'], 'token_type_hint': 'refresh_token', 'client_id': c['client_id']}) as r:
                        revoked = r.status == 200
            except Exception:
                pass
            self.credentials = None
            self.models = []
            self.pending = None
            self.credentials_path.unlink(missing_ok=True)
            self.runtime.pop('personal_use_authorized_at', None)
            protect_write(self.runtime_path, self.runtime)
            self.message = '已断开授权。' if revoked else '已清除本地授权；远程撤销未确认，请在 ChatGPT 设置中断开本应用。'
        raise web.HTTPFound('/')

    async def api(self, request):
        expected = 'Bearer ' + self.runtime['key']
        if not secrets.compare_digest(request.headers.get('Authorization', ''), expected):
            return web.json_response({'error': {'message': 'Invalid local API key', 'type': 'authentication_error'}}, status=401)
        token = await self.token()
        if request.method == 'GET':
            async with self.session.get(RESOURCE + '/models', headers={'Authorization': 'Bearer ' + token}) as r:
                data = await r.json()
                if r.status != 200:
                    return web.json_response({'error': {'message': 'Model discovery failed'}}, status=r.status)
            return web.json_response({'object': 'list', 'data': [{'id': m['slug'], 'object': 'model'} for m in data.get('models', []) if m.get('visibility') == 'list']})
        if not self.runtime.get('personal_use_authorized_at'):
            return web.json_response({'error': {'message': 'Confirm personal automation in the local setup page first'}}, status=403)
        body = await request.json()
        if body.get('model') != self.runtime.get('allowed_model'):
            return web.json_response({'error': {'message': 'Select and test this model in the MaiBot setup page first'}}, status=403)
        try:
            body = normalize_request(body)
        except ValueError as e:
            return web.json_response({'error': {'message': str(e)}}, status=400)
        if body.get('stream') is not True or body.get('store') is not False:
            return web.json_response({'error': {'message': 'Require stream=true and store=false'}}, status=400)
        async with self.session.post(RESOURCE + '/responses', headers={'Authorization': 'Bearer ' + token}, json=body) as r:
            if r.status != 200:
                # Upstream error bodies may contain request content; do not log them.
                detail = await self.error_detail(r)
                return web.json_response({'error': {'message': detail, 'type': 'upstream_error'}}, status=r.status)
            response = web.StreamResponse(headers={'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store'})
            await response.prepare(request)
            try:
                async for chunk in r.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            return response

    async def health(self, request):
        return web.json_response({'service': 'MaiBot ChatGPT Plan', 'authorized': bool(self.credentials), 'port': self.port})

    def app(self):
        @web.middleware
        async def local_only(request, handler):
            if request.headers.get('Host') != f'127.0.0.1:{self.port}':
                raise web.HTTPForbidden(text='Use the local loopback address.')
            try:
                return await handler(request)
            except web.HTTPException:
                raise
            except Exception:
                return web.json_response({'error': {'message': 'Local bridge request failed; reconnect or check network.'}}, status=502)
        app = web.Application(middlewares=[local_only], client_max_size=16 * 1024 * 1024)
        app.on_startup.append(self.start)
        app.on_cleanup.append(self.stop)
        app.router.add_get('/', self.page)
        app.router.add_post('/login', self.login)
        app.router.add_get('/auth/callback', self.callback)
        app.router.add_post('/activate', self.activate)
        app.router.add_post('/logout', self.logout)
        app.router.add_get('/health', self.health)
        app.router.add_post('/settings', self.settings)
        app.router.add_get('/privacy', self.privacy)
        app.router.add_get('/v1/models', self.api)
        app.router.add_post('/v1/responses', self.api)
        return app
