"""Vast edge challenges are different from bad keys; no live API calls."""
import os
import unittest
from unittest.mock import patch

from bot.config import Config
from bot.providers.image_vast import VastChallengeError, VastProvider


class Response:
    def __init__(self, code, payload):
        self.status_code = code
        self.payload = payload
        self.text = str(payload)

    def json(self):
        return self.payload


class VastChallengeTests(unittest.TestCase):
    def provider(self):
        return VastProvider(Config({'image': {'vast': {
            'api_key_env': 'VAST_API_KEY', 'mode': 'search'}}}), None)

    def test_uses_documented_console_endpoint_first(self):
        with patch.dict(os.environ, {'VAST_API_KEY': 'not-a-real-key'}), \
             patch('requests.request', return_value=Response(200, {'credit': 1})) as req:
            self.provider().healthcheck()
            self.assertTrue(req.call_args.args[1].startswith('https://console.vast.ai/api/v0/'))

    def test_get_challenge_tries_only_other_first_party_endpoint(self):
        challenge = {'error': {'code': 'challenge', 'message': 'browser challenge', 'id': 'bom1::test'}}
        urls = []
        def request(method, url, **kwargs):
            urls.append(url)
            return (Response(403, challenge) if 'console.vast.ai' in url
                    else Response(200, {'credit': 2}))
        with patch.dict(os.environ, {'VAST_API_KEY': 'do-not-log-me'}), \
             patch('requests.request', side_effect=request):
            good, message = self.provider().healthcheck()
        self.assertTrue(good, message)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[1].startswith('https://cloud.vast.ai/api/v0/'))
        self.assertNotIn('do-not-log-me', message)

    def test_both_challenged_returns_actionable_message_not_bad_key(self):
        challenge = {'error': {'code': 'challenge', 'id': 'bom1::test'}}
        with patch.dict(os.environ, {'VAST_API_KEY': 'do-not-log-me'}), \
             patch('requests.request', return_value=Response(403, challenge)) as req:
            good, message = self.provider().healthcheck()
        self.assertFalse(good)
        self.assertEqual(req.call_count, 2)
        self.assertIn('bom1::test', message)
        self.assertIn('not prove your key is wrong', message)
        self.assertNotIn('do-not-log-me', message)

    def test_mutation_is_not_replayed_after_challenge(self):
        challenge = {'error': {'code': 'challenge', 'id': 'bom1::test'}}
        with patch.dict(os.environ, {'VAST_API_KEY': 'do-not-log-me'}), \
             patch('requests.request', return_value=Response(403, challenge)) as req:
            with self.assertRaises(VastChallengeError):
                self.provider()._api('PUT', '/asks/123/', {'bundle_id': 123})
        req.assert_called_once()


if __name__ == '__main__':
    unittest.main()

class FallbackTests(unittest.TestCase):
    def test_fallback_network_failure_keeps_original_challenge(self):
        import requests
        cfg = Config({'image': {'vast': {'api_key_env':'VAST_API_KEY'}}})
        def req(method,url,**kwargs):
            if 'console.vast.ai' in url:
                return Response(403, {'error': {'code': 'challenge', 'id': 'bom1::retry'}})
            raise requests.ConnectionError('fallback unavailable')
        with patch.dict(os.environ, {'VAST_API_KEY':'not-a-real-key'}), \
             patch('requests.request',side_effect=req):
            good,msg=VastProvider(cfg,None).healthcheck()
        self.assertFalse(good)
        self.assertIn('bom1::retry',msg)
