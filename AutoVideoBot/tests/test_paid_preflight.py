"""No paid Remotion work may begin after a bad voice or unreachable SSH/API."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline
from bot.providers.render_vast import VastRemotionRenderer

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'vector-60s.json'


class PaidPreflightTests(unittest.TestCase):
    def pipeline(self, tmp: str) -> Pipeline:
        cfg = Config({'visual': {'engine': 'remotion', 'render_backend': 'vast'},
                      'tts': {'provider': 'edge', 'audio_format': 'wav'},
                      'motion': {'engine': 'ffmpeg'}})
        p = Pipeline(cfg, Project(Path(tmp), 'paid-test'))
        p.stage_script(script_file=EXAMPLE)
        return p

    def test_intermittent_voice_failure_aborts_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline(tmp)
            provider = Mock(healthcheck=Mock(return_value=(True, 'ok')),
                            synthesize=Mock(side_effect=OSError('voice network down')))
            p._providers['tts:edge'] = provider
            with self.assertRaisesRegex(RuntimeError, 'voice scene s01 failed'):
                p.stage_voice()
            self.assertFalse(p.manifest.stage_done('voice'))
            self.assertFalse(p.project.voice_track.exists())

    def test_short_edge_reply_is_retried_before_caching_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline(tmp)
            p.cfg.set('system.retry_attempts', 2)
            def incomplete(text, out, **kwargs):
                out.write_bytes(b'decodable but incomplete audio')
                return {'words': None}
            tts = Mock(healthcheck=Mock(return_value=(True, 'ok')),
                       synthesize=Mock(side_effect=incomplete))
            p._providers['tts:edge'] = tts
            p._providers['assembly:ffmpeg'] = Mock(probe_duration=Mock(return_value=.36))
            with patch('bot.utils.time.sleep'):
                with self.assertRaisesRegex(RuntimeError, 'voice scene s01 failed'):
                    p.stage_voice()
            self.assertEqual(tts.synthesize.call_count, 2)
            self.assertFalse(p.project.scene_audio('s01').exists())
            self.assertFalse(p.manifest.stage_done('voice'))

    def test_missing_or_broken_audio_cannot_become_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline(tmp)
            with self.assertRaisesRegex(RuntimeError, 'missing or unreadable narration audio'):
                p.stage_timing()
            self.assertFalse(p.manifest.stage_done('timing'))

    def test_decodable_but_truncated_speech_fails_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline(tmp)
            # Simulate an Edge reply whose audio contains only 0.36 seconds
            # for a 20-word narration. An existing, decodable file is not
            # sufficient evidence that TTS completed the sentence.
            p.project.scene_audio('s01').write_bytes(b'partial audio')
            p._providers['assembly:ffmpeg'] = Mock(probe_duration=Mock(return_value=.36))
            with self.assertRaisesRegex(RuntimeError, 'likely truncated TTS'):
                p.stage_timing()
            self.assertFalse(p.manifest.stage_done('timing'))

    def test_old_short_voice_track_blocks_paid_motion_before_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline(tmp)
            p.manifest.finish_stage('timing')
            p.project.voice_track.write_bytes(b'previous completed track')
            p.scenes[0]['natural_duration'] = .36
            with patch('requests.request') as api:
                with self.assertRaisesRegex(RuntimeError, 'no instance was rented'):
                    p.stage_shots()
            api.assert_not_called()

    def test_motion_without_finished_timing_never_contacts_vast(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline(tmp)
            with patch('requests.request') as api:
                with self.assertRaisesRegex(RuntimeError, 'no instance was rented'):
                    p.stage_shots()
            api.assert_not_called()

    def test_vast_doctor_checks_api_read_only(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict('os.environ', {'VAST_API_KEY': 'fake-test-key'}):
            cfg = Config({'visual': {'vast': {'api_key_env': 'VAST_API_KEY',
                                             'mode': 'search'}}})
            renderer = VastRemotionRenderer(cfg, Project(Path(tmp), 'doctor').create())
            with patch.object(renderer.vast, 'healthcheck', return_value=(False, 'challenge')) as check, \
                 patch.object(renderer.vast, '_create_instance') as create:
                with self.assertRaisesRegex(RuntimeError, 'challenge'):
                    renderer.healthcheck()
            check.assert_called_once()
            create.assert_not_called()

    def test_transient_ssh_proxy_retries_then_authenticates(self):
        with tempfile.TemporaryDirectory() as tmp:
            renderer = VastRemotionRenderer(
                Config({'visual': {'vast': {'ssh_ready_timeout': 60}}}),
                Project(Path(tmp), 'ssh').create())
            failures = [subprocess.CompletedProcess([], 255, '', 'banner exchange: connection closed'),
                        subprocess.CompletedProcess([], 0, '', '')]
            with patch.object(renderer, '_ssh', side_effect=failures) as ssh, \
                 patch('bot.providers.render_vast.time.sleep'):
                renderer._probe_render_ssh()
            self.assertEqual(ssh.call_count, 2)

    def test_bad_ssh_key_fails_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            renderer = VastRemotionRenderer(Config({'visual': {'vast': {'ssh_ready_timeout': 5}}}),
                                            Project(Path(tmp), 'ssh').create())
            with patch.object(renderer, '_ssh', return_value=subprocess.CompletedProcess(
                    [], 255, '', 'Permission denied (publickey)')) as ssh, \
                 patch('bot.providers.render_vast.time.sleep') as wait:
                with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
                    renderer._probe_render_ssh()
            ssh.assert_called_once()
            wait.assert_not_called()


if __name__ == '__main__':
    unittest.main()
