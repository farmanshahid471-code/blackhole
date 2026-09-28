"""A one-scene image smoke test must not call the other 61 scenes cached."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline


class OnlyImageTests(unittest.TestCase):
    def test_unselected_scenes_are_not_called_cached_or_placeholder_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(Config({'visual': {'engine': 'images'},
                                 'image': {'provider': 'pollinations'},
                                 'video': {'width': 640, 'height': 360}}),
                         Project(Path(tmp), 'single'))
            p.scenes = [{'id': f's{i:02d}', 'image_prompt': 'a nebula'} for i in range(1, 4)]
            p.script.data = {'scenes': p.scenes}
            p.script.save()
            p.only = {'s01'}
            def generate(prompt, out_path, **kwargs):
                out_path.write_bytes(b'image')
                return out_path
            image = Mock(supports_batch=False, supports_parallel=False,
                         batch_error_fatal=False,
                         healthcheck=Mock(return_value=(True, 'ready')),
                         generate=Mock(side_effect=generate))
            p._providers['image:pollinations'] = image
            with patch('bot.pipeline.info') as info, patch('bot.pipeline.warn') as warn:
                p.stage_images()
            image.generate.assert_called_once()
            self.assertTrue(p.project.scene_image('s01', 'jpg').exists())
            self.assertFalse(p.project.scene_image('s02', 'jpg').exists())
            self.assertIsNone(p.scenes[1]['image_path'])
            self.assertFalse(p.manifest.stage_done('images'))
            self.assertTrue(any('2 skipped by --only' in str(call) for call in info.call_args_list))
            warn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
