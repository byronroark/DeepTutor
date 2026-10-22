import json
import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'learning'))
from luna_gateway import prepare, Handler
from weekly_budget import Ledger


class GatewayTests(unittest.TestCase):
    def request(self, **extra):
        return {'model': 'gpt-6-luna', 'messages': [{'role': 'user', 'content': 'Explain fractions'}], **extra}

    def test_paid_parameters_are_fixed_not_caller_controlled(self):
        wire, raw, bound = prepare(self.request(n=100, max_tokens=100000, service_tier='priority', store=True))
        self.assertEqual(wire['n'], 1)
        self.assertEqual(wire['max_completion_tokens'], 1024)
        self.assertEqual(wire['service_tier'], 'default')
        self.assertFalse(wire['store'])
        self.assertEqual(wire['reasoning_effort'], 'none')
        self.assertGreater(bound, len(raw))

    def test_stream_final_usage_requested(self):
        wire, _, _ = prepare(self.request(stream=True))
        self.assertEqual(wire['stream_options'], {'include_usage': True})

    def test_other_models_and_modalities_refused(self):
        with self.assertRaises(ValueError):
            prepare(self.request(model='gpt-6-astra'))
        with self.assertRaises(ValueError):
            prepare(self.request(messages=[{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.com'}}]}]))

    def test_hosted_paid_tools_refused(self):
        with self.assertRaises(ValueError):
            prepare(self.request(tools=[{'type': 'web_search'}]))

    def test_unicode_and_tool_definitions_included_in_cost_bound(self):
        wire, raw, bound = prepare(self.request(messages=[{'role': 'user', 'content': '数学' * 100}],
                                  tools=[{'type': 'function', 'function': {'name': 'quiz', 'description': 'x' * 10000}}]))
        self.assertGreater(bound, 10000)
        self.assertEqual(json.loads(raw)['tools'], wire['tools'])

    def test_huge_history_refused_before_provider(self):
        with self.assertRaises(ValueError):
            prepare(self.request(messages=[{'role': 'user', 'content': 'x' * 200000}]))
        with self.assertRaises(ValueError):
            prepare(self.request(messages=[{'role': 'user', 'content': 'x'}] * 65))

class RequestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        self.handler = object.__new__(Handler)
        h = self.handler
        h.config_root = root
        h.ledger = Ledger(root / 'ledger')
        for name, value in [('gateway-token', 'local-secret'), ('openai-api-key', 'synthetic-key')]:
            path = root / name
            path.write_text(value)
            path.chmod(0o600)
        h.client_address = ('172.30.60.2', 1234)
        h.path = '/v1/chat/completions'
        raw = json.dumps({'model': 'gpt-6-luna', 'messages': [{'role': 'user', 'content': 'Explain fractions'}]}).encode()
        h.headers = {'Authorization': 'Bearer local-secret', 'Content-Length': str(len(raw))}
        h.rfile = io.BytesIO(raw)
        h.wfile = io.BytesIO()
        h.connection = Mock()
        h.reply = Mock()
        h.send_response = Mock()
        h.send_header = Mock()
        h.end_headers = Mock()
        self.provider = Mock()
        self.response = self.provider.getresponse.return_value
        self.response.status = 200
        self.response.read.return_value = json.dumps({'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}).encode()
        self.upstream = patch('luna_gateway.http.client.HTTPSConnection', return_value=self.provider).start()
        self.addCleanup(patch.stopall)

    def ready(self):
        # Disposable test fixture only; never creates the deployment marker.
        (self.handler.config_root / 'child-api-ready').touch()

    def test_privacy_gate_prevents_upstream_and_charge(self):
        self.handler.do_POST()
        self.assertEqual(self.handler.reply.call_args.args[0], 403)
        self.upstream.assert_not_called()
        self.assertEqual(self.handler.ledger.status()['used_nanodollars'], 0)

    def test_wrong_client_or_bearer_cannot_spend(self):
        self.ready()
        for address, bearer in [('127.0.0.1', 'Bearer local-secret'), ('172.30.60.2', 'Bearer wrong')]:
            self.handler.client_address = (address, 1234)
            self.handler.headers['Authorization'] = bearer
            self.handler.do_POST()
            self.assertEqual(self.handler.reply.call_args.args[0], 403)
        self.upstream.assert_not_called()

    def test_budget_denial_happens_before_upstream(self):
        self.ready()
        self.handler.ledger = Ledger(pathlib.Path(self.temp.name) / 'tiny', limit=1)
        self.handler.do_POST()
        self.assertEqual(self.handler.reply.call_args.args[0], 429)
        self.upstream.assert_not_called()

    def test_charge_reserved_before_provider_then_reconciled(self):
        self.ready()
        def check_reserved(*args, **kwargs):
            self.assertGreater(self.handler.ledger.status()['used_nanodollars'], 20_000)
        self.provider.request.side_effect = check_reserved
        self.handler.do_POST()
        self.assertEqual(self.handler.reply.call_args.args[0], 200)
        self.assertEqual(self.handler.ledger.status()['used_nanodollars'], 20_000)
        self.assertEqual(self.provider.request.call_args.args[:2], ('POST', '/v1/chat/completions'))
        self.upstream.assert_called_once_with('api.openai.com', timeout=120)

    def test_missing_usage_and_upstream_failure_keep_reservation(self):
        self.ready()
        self.response.read.return_value = b'{"choices": []}'
        self.handler.do_POST()
        charged = self.handler.ledger.status()['used_nanodollars']
        self.assertGreater(charged, 512_000)
        self.handler.rfile.seek(0)
        self.provider.request.side_effect = OSError('ambiguous disconnect')
        self.handler.do_POST()
        self.assertEqual(self.handler.reply.call_args.args[0], 503)
        self.assertEqual(self.handler.ledger.status()['used_nanodollars'], charged * 2)

    def test_stream_requires_done_before_refund(self):
        self.ready()
        for done in [False, True]:
            raw = json.dumps({'model': 'gpt-6-luna', 'stream': True, 'messages': [{'role': 'user', 'content': 'Fractions'}]}).encode()
            self.handler.headers['Content-Length'] = str(len(raw))
            self.handler.rfile = io.BytesIO(raw)
            self.response.readline.side_effect = [b'data: {"usage":{"prompt_tokens":100,"completion_tokens":20}}\n', *([b'data: [DONE]\n'] if done else []), b'']
            before = self.handler.ledger.status()['used_nanodollars']
            self.handler.do_POST()
            change = self.handler.ledger.status()['used_nanodollars'] - before
            self.assertEqual(change, 20_000) if done else self.assertGreater(change, 512_000)

    def test_connect_cannot_bypass_budget_or_reach_lan(self):
        for target in ['api.openai.com:443', '192.168.1.138:443', 'example.com:443', 'auth.openai.com:80']:
            self.handler.path = target
            self.handler.do_CONNECT()
            self.assertEqual(self.handler.reply.call_args.args[0], 403)
        self.handler.path = 'auth.openai.com:443'
        with patch('luna_gateway.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('192.168.1.138', 443))]), patch('luna_gateway.socket.socket') as sock:
            self.handler.do_CONNECT()
            sock.assert_not_called()
        self.assertEqual(self.handler.reply.call_args.args[0], 502)

if __name__ == '__main__':
    unittest.main()
