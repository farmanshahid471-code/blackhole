"""Stage 4 must not retry a failed paid batch per scene or publish placeholders."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline
from bot.providers.image_vast import VastProvider


class VastImagePipelineTests(unittest.TestCase):
    def setup_pipeline(self, directory):
        p = Pipeline(Config({'visual': {'engine': 'images'},
                             'image': {'provider': 'vast'},
                             'system': {'on_error': 'continue'}}),
                     Project(Path(directory), 'my-video'))
        p.scenes = [{'id': f's{i:02d}', 'image_prompt': 'a nebula'} for i in range(1, 5)]
        p.script.data['scenes'] = p.scenes
        p.script.save()
        img = Mock(supports_batch=True, batch_error_fatal=True,
                   healthcheck=Mock(return_value=(True, 'ready')))
        p._providers['image:vast'] = img
        return p, img

    def test_persisted_short_topic_script_cannot_rent_on_stage_four_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, img = self.setup_pipeline(tmp)
            p.scenes = [{'id': f's{i:02d}', 'narration': 'Tiny line',
                         'image_prompt': 'A nebula', 'target_start': i * 9,
                         'target_end': (i + 1) * 9, 'duration': 9}
                        for i in range(10)]
            p.script.data.update({'scenes': p.scenes, 'source': 'topic',
                                  'requested_duration': 600, 'total_duration': 90})
            p.script.save()
            with self.assertRaisesRegex(ValueError, 'requested 600s, received 90s'):
                p.stage_images()
            img.healthcheck.assert_not_called()
            img.generate_many.assert_not_called()
            self.assertFalse(p.manifest.stage_done('images'))

    def test_old_capped_timing_blocks_paid_images_before_provider_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, img = self.setup_pipeline(tmp)
            p.scenes = [{'id': f's{i:02d}', 'narration': 'a detailed star story ' * 6,
                         'image_prompt': 'a nebula', 'target_start': (i - 1) * 10,
                         'target_end': i * 10, 'duration': 10}
                        for i in range(1, 61)]
            p.script.data.update({'scenes': p.scenes, 'source': 'topic',
                                  'requested_duration': 600, 'total_duration': 600})
            p.script.save()
            p.manifest.finish_stage('timing')
            (p.project.audio_dir / 's38_fit.json').write_text(
                '{"capped": true, "requested_tempo": 1.67, "tempo": 1.35}')
            with self.assertRaisesRegex(RuntimeError, 's38'):
                p.stage_images()
            # Also reject a clipped persisted scene when its fit report has
            # disappeared but the scene still records its fitted audio length.
            (p.project.audio_dir / 's38_fit.json').unlink()
            p.scenes[37]['audio_duration'] = 12
            with self.assertRaisesRegex(RuntimeError, 's38'):
                p.stage_images()
            img.healthcheck.assert_not_called()
            img.generate_many.assert_not_called()

    def test_failed_batch_aborts_once_with_no_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, img = self.setup_pipeline(tmp)
            img.generate_many.side_effect = RuntimeError('HTTP 400: Invalid json body')
            with self.assertRaisesRegex(RuntimeError, 'HTTP 400'):
                p.stage_images()
            img.healthcheck.assert_called_once()
            img.generate_many.assert_called_once()
            img.generate.assert_not_called()
            img.teardown.assert_called_once()
            self.assertFalse(p.manifest.stage_done('images'))
            self.assertFalse(any(p.project.images_dir.glob('*.jpg')))

    def test_unhealthy_provider_aborts_before_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, img = self.setup_pipeline(tmp)
            img.healthcheck.return_value = (False, 'challenge')
            with self.assertRaisesRegex(RuntimeError, 'challenge'):
                p.stage_images()
            img.generate_many.assert_not_called()

    def test_missing_batch_result_does_not_call_single_image_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, img = self.setup_pipeline(tmp)
            img.generate_many.return_value = [None] * 4
            with self.assertRaisesRegex(RuntimeError, 'no image for s01'):
                p.stage_images()
            img.generate.assert_not_called()
            img.teardown.assert_called_once()

    def test_missing_ssh_aborts_pipeline_before_vast_api_or_rental(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, _ = self.setup_pipeline(tmp)
            p._providers['image:vast'] = VastProvider(p.cfg, p.project)
            with patch('bot.providers.image_vast.find_openssh_tool',
                       side_effect=RuntimeError('OpenSSH ssh.exe missing')), \
                 patch('requests.request') as req:
                with self.assertRaisesRegex(RuntimeError, 'OpenSSH ssh.exe missing'):
                    p.stage_images()
            req.assert_not_called()
            self.assertFalse(p.manifest.stage_done('images'))
            self.assertFalse(any(p.project.images_dir.glob('*.jpg')))

    def test_already_cached_scenes_need_no_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, img = self.setup_pipeline(tmp)
            for scene in p.scenes:
                out = p.project.scene_image(scene['id'], 'jpg')
                out.write_bytes(b'cached')
                key = p._cache_key('image', scene['id'], {
                    'provider': 'vast', 'prompt': 'a nebula', 'w': 1920,
                    'h': 1080, 'steps': 30, 'cfg': 7.0, 'negative': '', 'model': ''})
                p.manifest.mark(key, out)
            p.stage_images()
            img.healthcheck.assert_not_called()
            img.generate_many.assert_not_called()
