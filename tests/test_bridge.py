import asyncio
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web
import tomlkit

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from maibot_chatgpt_plan import app as module
ORIGIN = 'http://127.0.0.1:8777'
CALLBACK = ORIGIN + '/auth/callback'
class RefreshResponse:
    status = 200
    async def __aenter__(self):
        await asyncio.sleep(.01)
        return self
    async def __aexit__(self, *args):
        pass
    async def json(self):
        return {'access_token': 'new-access', 'refresh_token': 'new-refresh', 'expires_in': 3600}

class RefreshSession:
    calls = 0
    def post(self, *args, **kwargs):
        self.calls += 1
        assert kwargs['data']['client_id'] == 'issued-client'
        return RefreshResponse()

class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = root / 'model_config.toml'
        self.config.write_text('''[[api_providers]]
name="Old"
base_url="https://example.com"
api_key="test-only"
[[models]]
name="old-model"
model_identifier="old-id"
api_provider="Old"
[model_task_config.replyer]
model_list=["old-model"]
max_tokens=4096
[model_task_config.planner]
model_list=["old-model"]
''', encoding='utf-8')
        self.bridge = module.Bridge(root / 'state', self.config, port=8777)
        self.client = TestClient(TestServer(self.bridge.app()))
        await self.client.start_server()
        self.headers = {'Host': '127.0.0.1:8777'}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_local_access_and_csrf(self):
        r = await self.client.get('/health')
        self.assertEqual(r.status, 403)
        r = await self.client.get('/health', headers=self.headers)
        self.assertFalse((await r.json())['authorized'])
        r = await self.client.post('/login', headers=self.headers)
        self.assertEqual(r.status, 403)
        r = await self.client.get('/v1/models', headers=self.headers)
        self.assertEqual(r.status, 401)

    async def test_invalid_oauth_state(self):
        self.bridge.pending = {'state': 'expected', 'created': time.time()}
        r = await self.client.get('/auth/callback?state=wrong&code=unused', headers=self.headers)
        self.assertEqual(r.status, 400)
        self.assertIsNone(self.bridge.credentials)

    async def test_login_redirect_allowed_by_page_policy(self):
        from urllib.parse import urlparse, parse_qs
        r = await self.client.get('/', headers=self.headers)
        policy = r.headers['Content-Security-Policy']
        self.assertIn("form-action 'self' https://auth.openai.com", policy)
        headers = {**self.headers, 'Origin': ORIGIN,
                   'Cookie': 'bridge_csrf=' + self.bridge.csrf}
        r = await self.client.post('/login', headers=headers, allow_redirects=False)
        self.assertEqual(r.status, 302)
        target = urlparse(r.headers['Location'])
        self.assertEqual(target.scheme, 'https')
        self.assertEqual(target.netloc, 'auth.openai.com')
        query = parse_qs(target.query)
        self.assertEqual(query['client_id'], ['dynamic_agent_client'])
        self.assertEqual(query['redirect_uri'], [CALLBACK])
        self.assertIn('chatgpt.tokens.use.direct', query['scope'][0])
        self.assertEqual(query['state'], [self.bridge.pending['state']])

    async def test_dpapi_config_preserves_all_original_models_and_tasks(self):
        before = tomlkit.parse(self.config.read_text())
        self.bridge.configure('account-model')
        after = tomlkit.parse(self.config.read_text())
        self.assertEqual(before['model_task_config'], after['model_task_config'])
        self.assertEqual(before['models'][0], after['models'][0])
        self.assertEqual(before['api_providers'][0], after['api_providers'][0])
        entry = next(x for x in after['models'] if x['name'] == module.MODEL_NAME)
        self.assertTrue(entry['force_stream_mode'])
        self.assertFalse(entry['send_temperature'])
        self.assertTrue(list(self.bridge.state_dir.glob('model-config-backup-*.dpapi')))
        backup = next(self.bridge.state_dir.glob('model-config-backup-*.dpapi'))
        self.assertNotIn(b'test-only', backup.read_bytes())
        self.assertIn('test-only', module.protected_read(backup)['content'])
        runtime_bytes = self.bridge.runtime_path.read_bytes()
        self.assertNotIn(self.bridge.runtime['key'].encode(), runtime_bytes)
        self.bridge.configure('another-account-model')
        updated = tomlkit.parse(self.config.read_text())
        self.assertEqual(updated['model_task_config'], before['model_task_config'])
        self.assertEqual(len(updated['models']), 2)
        self.assertEqual(len(updated['api_providers']), 2)

    async def test_serialized_refresh_and_rotation(self):
        self.bridge.save_credentials({'client_id': 'issued-client', 'access_token': 'expired',
            'refresh_token': 'old-refresh', 'expires_at': 0, 'scopes': ['chatgpt.tokens.use.direct']})
        old_session = self.bridge.session
        fake = RefreshSession()
        self.bridge.session = fake
        try:
            results = await asyncio.gather(self.bridge.token(), self.bridge.token())
        finally:
            self.bridge.session = old_session
        self.assertEqual(results, ['new-access', 'new-access'])
        self.assertEqual(fake.calls, 1)
        saved = module.protected_read(self.bridge.credentials_path)
        self.assertEqual(saved['refresh_token'], 'new-refresh')
        self.assertNotIn(b'new-access', self.bridge.credentials_path.read_bytes())

    async def test_stream_forwarding_and_failed_activation(self):
        self.bridge.save_credentials({'client_id': 'issued-client', 'access_token': 'mock-token',
            'refresh_token': 'mock-refresh', 'expires_at': time.time() + 3600,
            'scopes': ['chatgpt.tokens.use.direct']})
        self.bridge.models = [{'slug': 'mock-model'}]
        self.bridge.runtime.update(allowed_model='mock-model', personal_use_authorized_at=time.time())
        received = []
        async def upstream(request):
            self.assertEqual(request.headers['Authorization'], 'Bearer mock-token')
            received.append(await request.json())
            return web.Response(text='event: response.failed\ndata: {"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded"}}}\n\n', content_type='text/event-stream')
        app = web.Application()
        app.router.add_post('/responses', upstream)
        server = TestServer(app)
        await server.start_server()
        old_resource = module.RESOURCE
        module.RESOURCE = str(server.make_url('')).rstrip('/')
        try:
            headers = {**self.headers, 'Authorization': 'Bearer ' + self.bridge.runtime['key']}
            r = await self.client.post('/v1/responses', headers=headers,
                json={'model': 'mock-model', 'input': 'mock input', 'store': False, 'stream': True})
            self.assertEqual(r.status, 200)
            self.assertIn('subscription_sharing_usage_limit_exceeded', await r.text())
            original = self.config.read_text()
            control = {**self.headers, 'Origin': ORIGIN,
                'Cookie': 'bridge_csrf=' + self.bridge.csrf}
            r = await self.client.post('/activate', headers=control, data={'model': 'mock-model', 'personal_use': 'on'}, allow_redirects=False)
            self.assertEqual(r.status, 302)
            self.assertEqual(self.config.read_text(), original)
            self.assertIn('没有添加模型', self.bridge.message)
            self.assertTrue(all(x['stream'] and x['store'] is False and isinstance(x['input'], list) for x in received))
        finally:
            module.RESOURCE = old_resource
            await server.close()

    async def test_successful_activation_adds_option_only(self):
        self.bridge.save_credentials({'client_id':'issued-client','access_token':'mock-token',
            'refresh_token':'mock-refresh','expires_at':time.time()+3600,
            'scopes':['chatgpt.tokens.use.direct']})
        self.bridge.models = [{'slug':'mock-model'}]
        original_tasks = tomlkit.parse(self.config.read_text())['model_task_config']
        async def upstream(request):
            body = await request.json()
            self.assertIsInstance(body['input'], list)
            return web.Response(text='data: {"type":"response.output_item.done","output_index":0,"item":{"type":"message","content":[{"type":"output_text","text":"连接成功"}]}}\n\ndata: {"type":"response.completed","response":{}}\n\n',content_type='text/event-stream')
        app = web.Application()
        app.router.add_post('/responses',upstream)
        server = TestServer(app)
        await server.start_server()
        original_resource = module.RESOURCE
        module.RESOURCE = str(server.make_url('')).rstrip('/')
        headers = {**self.headers,'Origin':ORIGIN,'Cookie':'bridge_csrf='+self.bridge.csrf}
        try:
            r = await self.client.post('/activate',headers=headers,data={'model':'mock-model'},allow_redirects=False)
            self.assertEqual(r.status,400)
            r = await self.client.post('/activate',headers=headers,
                data={'model':'mock-model','personal_use':'on'},allow_redirects=False)
            self.assertEqual(r.status,302)
            after = tomlkit.parse(self.config.read_text())
            self.assertEqual(original_tasks,after['model_task_config'])
            self.assertEqual(self.bridge.runtime['allowed_model'],'mock-model')
            self.assertIn('测试成功',self.bridge.message)
        finally:
            module.RESOURCE = original_resource
            await server.close()

    async def test_api_reconstructs_text_and_empty_activation_preserves_config(self):
        self.bridge.save_credentials({'client_id':'issued-client','access_token':'mock-token',
            'refresh_token':'mock-refresh','expires_at':time.time()+3600,
            'scopes':['chatgpt.tokens.use.direct']})
        self.bridge.models = [{'slug':'mock-model'}]
        self.bridge.runtime.update(allowed_model='mock-model', personal_use_authorized_at=time.time())
        empty = False
        async def upstream(request):
            body = 'data: {"type":"response.completed","response":{"output":[]}}\n\n'
            if not empty:
                body = 'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"message","content":[{"type":"output_text","text":"ok"}]}}\n\n' + body
            return web.Response(text=body,content_type='text/event-stream')
        app = web.Application()
        app.router.add_post('/responses',upstream)
        server = TestServer(app)
        await server.start_server()
        old_resource = module.RESOURCE
        module.RESOURCE = str(server.make_url('')).rstrip('/')
        try:
            headers = {**self.headers,'Authorization':'Bearer '+self.bridge.runtime['key']}
            r = await self.client.post('/v1/responses',headers=headers,
                json={'model':'mock-model','input':'hello','stream':True,'store':False})
            from maibot_chatgpt_plan.streaming import parse_event, has_text_output
            events = [parse_event(part.encode()+b'\n\n') for part in (await r.text()).split('\n\n') if part]
            self.assertTrue(has_text_output(events[-1]))
            empty = True
            original = self.config.read_bytes()
            runtime = self.bridge.runtime.copy()
            control = {**self.headers,'Origin':ORIGIN,'Cookie':'bridge_csrf='+self.bridge.csrf}
            r = await self.client.post('/activate',headers=control,
                data={'model':'mock-model','personal_use':'on'},allow_redirects=False)
            self.assertEqual(r.status,302)
            self.assertEqual(self.config.read_bytes(),original)
            self.assertEqual(self.bridge.runtime,runtime)
            self.assertIn('非空文本',self.bridge.message)
        finally:
            module.RESOURCE = old_resource
            await server.close()

if __name__ == '__main__':
    unittest.main()
