import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from web_platform_moderation import (BudgetExhausted, HTTPProvider, ModerationRequest, ModerationResult,
                                    OpenAIProvider, Pricing, ProviderError, SQLiteLedger, create_provider)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'ledger.sqlite'
        self.ledger = SQLiteLedger(self.path, Pricing(.1, .5))
        self.provider = OpenAIProvider(api_key='unit-test', model='configured-model', ledger=self.ledger,
                                       monthly_budget_usd=1, policy_id='test-policy')
        self.request = ModerationRequest('Technical question', {'page_title': 'An article'})

    def response(self, decision='keep'):
        return {'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 20},
                'output': [{'type': 'message', 'content': [{'type': 'output_text',
                            'text': json.dumps({'decision': decision, 'reason': 'Explanation'})}]}]}

    def test_configured_model_and_strict_stateless_contract(self):
        def post(endpoint, body, token, timeout):
            value = json.loads(body)
            self.assertEqual(value['model'], 'configured-model')
            self.assertFalse(value['store'])
            self.assertEqual(value['tools'], [])
            self.assertTrue(value['text']['format']['strict'])
            self.assertEqual(json.loads(value['input']), self.request.to_dict())
            return self.response()
        with patch('web_platform_moderation.providers._post', side_effect=post):
            result = self.provider.classify(self.request)
        self.assertEqual(result.decision, 'keep')
        self.assertEqual((result.provider, result.model, result.policy_id), ('openai', 'configured-model', 'test-policy'))

    def test_incomplete_refusal_and_malformed_output_have_no_decision(self):
        responses = [self.response(), self.response(), self.response(), self.response(), []]
        responses[0]['status'] = 'incomplete'
        responses[1]['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'Declined'}]
        responses[2]['output'][0]['content'][0]['text'] = '{"decision":"spam","reason":"x","delete":true}'
        responses[3]['output'][0]['content'][0]['text'] = '{"decision":"spam","reason":false}'
        for response in responses:
            with self.subTest(response=response), patch('web_platform_moderation.providers._post', return_value=response):
                with self.assertRaises(ProviderError): self.provider.classify(self.request)

    def test_failed_request_keeps_full_reservation_across_restart(self):
        self.provider.budget = .002
        with patch('web_platform_moderation.providers._post', side_effect=ProviderError('Transport failed')):
            with self.assertRaises(ProviderError): self.provider.classify(self.request)
        recovered = SQLiteLedger(self.path, Pricing(.1, .5))
        with self.assertRaises(BudgetExhausted): recovered.reserve(b'hello', .002, 1024)

    def test_existing_spending_rows_are_preserved(self):
        with self.ledger.connect() as db:
            db.execute('INSERT INTO spending(month,reserved) VALUES(?,?)',
                       (dt.datetime.now(dt.timezone.utc).strftime('%Y-%m'), 900000))
        recovered = SQLiteLedger(self.path, Pricing(.1, .5))
        with self.assertRaises(BudgetExhausted): recovered.reserve(b'x', .9, 1024)
        with recovered.connect() as db:
            self.assertEqual(db.execute('SELECT reserved,actual FROM spending').fetchall(), [(900000, None)])

    def test_concurrent_reservations_respect_one_budget(self):
        def reserve(_):
            try: return self.ledger.reserve(b'x', .002, 1024)
            except BudgetExhausted: return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            tickets = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(ticket is not None for ticket in tickets), 1)

    def test_invalid_usage_keeps_reservation(self):
        ticket = self.ledger.reserve(b'x', .002, 1024)
        for usage in ({}, {'input_tokens': True, 'output_tokens': 0}, {'input_tokens': -1, 'output_tokens': 1}):
            self.ledger.settle(ticket, usage)
            with self.assertRaises(BudgetExhausted): self.ledger.reserve(b'x', .002, 1024)
        self.ledger.settle(ticket, {'input_tokens': 10, 'output_tokens': 10})
        self.ledger.reserve(b'x', .002, 1024)

    def test_oversized_context_requires_review_without_cost(self):
        with patch('web_platform_moderation.providers._post') as post:
            result = self.provider.classify(ModerationRequest('x' * 40000))
        self.assertEqual(result.decision, 'review')
        post.assert_not_called()

    def test_disabled_provider_requires_no_openai_configuration(self):
        result = create_provider({}, self.path).classify(self.request)
        self.assertEqual((result.decision, result.provider), ('keep', 'none'))
        self.assertFalse(self.path.with_name('unused.sqlite').exists())

    def test_http_provider_accepts_a_different_service(self):
        request = self.request
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                captured.append((self.headers['Authorization'], json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'schema_version': 1, 'decision': 'review', 'reason': 'Custom rules',
                                            'provider': 'custom-service'}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        result = HTTPProvider(f'http://127.0.0.1:{server.server_port}/moderate', 'local-test').classify(request)
        self.assertEqual((result.decision, result.provider), ('review', 'custom-service'))
        self.assertEqual(captured, [('Bearer local-test', request.to_dict())])

    def test_http_contract_rejects_invalid_envelopes(self):
        for value in ({'schema_version': 2}, {'schema_version': True}, {'schema_version': 1},
                      {'schema_version': 1, 'decision': 'delete', 'reason': 'No'},
                      {'schema_version': 1, 'decision': 'spam', 'reason': 'Yes', 'extra': 1}):
            with patch('web_platform_moderation.providers._post', return_value=value):
                with self.assertRaises(ProviderError): HTTPProvider('https://moderation.example.com').classify(self.request)


if __name__ == '__main__': unittest.main()
