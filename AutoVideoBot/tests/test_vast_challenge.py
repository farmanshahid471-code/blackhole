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

class VastSearchTests(unittest.TestCase):
    def provider(self):
        return VastProvider(Config({'image': {'vast': {
            'api_key_env': 'VAST_API_KEY', 'mode': 'search',
            'search': {'gpu_type': 'RTX 4090', 'min_vram_gb': 24,
                       'max_price_per_hour': 0.45, 'disk_gb': 45,
                       'min_direct_ports': 1}}}}), None)

    def test_flat_json_post_offer_search_and_no_rental(self):
        offer = {'id': 567, 'gpu_name': 'RTX 4090', 'dph_total': 0.40,
                 'cuda_max_good': 12.5, 'inet_down': 500, 'reliability2': 0.99}
        with patch.dict(os.environ, {'VAST_API_KEY': 'fake-key'}), \
             patch('requests.request', return_value=Response(200, {'offers': [offer]})) as req:
            selected = self.provider()._search_offer()
        self.assertEqual(selected['id'], 567)
        req.assert_called_once()
        args, kw = req.call_args
        self.assertEqual(args, ('POST', 'https://console.vast.ai/api/v0/bundles/'))
        self.assertEqual(kw['headers']['Authorization'], 'Bearer fake-key')
        self.assertFalse(kw['allow_redirects'])
        self.assertEqual(kw['json'], {
            'gpu_name': {'eq': 'RTX 4090'}, 'gpu_ram': {'gte': 24576},
            'dph_total': {'lte': 0.45}, 'disk_space': {'gte': 45},
            'direct_port_count': {'gte': 1}, 'num_gpus': {'eq': 1},
            'rentable': {'eq': True}, 'rented': {'eq': False},
            'verified': {'eq': True}, 'order': [['dph_total', 'asc']],
            'type': 'on-demand', 'limit': 100,
        })

    def test_http_400_stops_without_rental_or_repeated_search(self):
        with patch.dict(os.environ, {'VAST_API_KEY': 'fake-key'}), \
             patch('requests.request', return_value=Response(400, {
                 'error': 'invalid_request', 'msg': 'Invalid json body'})) as req:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 400'):
                self.provider()._search_offer()
        req.assert_called_once()

    def test_creation_body_uses_ssh_direct_and_offer_in_url(self):
        p = self.provider()
        with patch.object(p, '_api', return_value={'new_contract': 123}) as api:
            p._create_instance({'id': 567})
        method, path, body = api.call_args.args
        self.assertEqual((method, path), ('PUT', '/asks/567/'))
        self.assertEqual(body['runtype'], 'ssh_direct')
        self.assertNotIn('env', body)  # the image server is SSH-tunnel-only
        self.assertNotIn('bundle_id', body)
        self.assertTrue(p._owns_instance)

    def test_create_instance_network_failure_is_never_replayed(self):
        import requests
        with patch.dict(os.environ, {'VAST_API_KEY': 'fake-key'}), \
             patch('requests.request', side_effect=requests.Timeout('unknown outcome')) as req:
            with self.assertRaisesRegex(RuntimeError, 'network problem'):
                self.provider()._api('PUT', '/asks/567/', {'runtype': 'ssh_direct'})
        req.assert_called_once()

    def test_create_http_500_is_not_replayed_to_other_host(self):
        with patch.dict(os.environ, {'VAST_API_KEY': 'fake-key'}), \
             patch('requests.request', return_value=Response(500, {'error': 'server error'})) as req:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 500'):
                self.provider()._api('PUT', '/asks/567/', {'runtype': 'ssh_direct'})
        req.assert_called_once()

    def test_search_challenge_can_try_other_first_party_host(self):
        offer = {'id': 567, 'gpu_name': 'RTX 4090', 'dph_total': 0.4}
        def reply(method, url, **kwargs):
            if 'console.vast.ai' in url:
                return Response(403, {'error': {'code': 'challenge', 'id': 'test-id'}})
            return Response(200, {'offers': [offer]})
        with patch.dict(os.environ, {'VAST_API_KEY': 'fake-key'}), \
             patch('requests.request', side_effect=reply) as req:
            self.assertEqual(self.provider()._search_offer()['id'], 567)
        self.assertEqual(req.call_count, 2)
        self.assertTrue(all(call.args[0] == 'POST' for call in req.call_args_list))

    def test_upload_starts_inside_nested_scp_directory(self):
        p = self.provider()
        p._ssh = {'host': 'example.com', 'port': 22, 'user': 'root'}
        with patch('bot.providers.image_vast.run_cmd') as cmd:
            remote = p._upload_server()
        self.assertEqual(remote, '/workspace/image_server/server')
        self.assertEqual(cmd.call_count, 2)
        self.assertIn('/workspace/image_server', cmd.call_args.args[0][-1])


if __name__ == '__main__':
    unittest.main()
