"""Network-free safeguards: incomplete topic scripts must not reach paid images."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline
from bot.script import generate_script


class LongScriptSafetyTests(unittest.TestCase):
    def cfg(self):
        return Config({'visual': {'engine': 'images'},
                       'llm': {'provider': 'fake', 'scenes': {'target_seconds_per_scene': 9}},
                       'image': {'provider': 'vast'}})

    def test_600_seconds_is_written_in_five_bounded_chapters(self):
        class LLM:
            provider_name = 'fake'
            def __init__(self): self.calls = []
            def chat(self, messages, **kw):
                self.calls.append(messages[1]['content'])
                scenes = []
                for i in range(12):
                    scenes.append({'start': i * 10, 'end': (i + 1) * 10,
                                   'narration': ('An original story about stars and light ' * 4).strip(),
                                   'image_prompt': 'A black hole bending light in space'})
                return json.dumps({'title': 'A Long Film', 'scenes': scenes})
        llm = LLM()
        out = generate_script(llm, self.cfg(), topic='black holes', duration=600,
                              reference_context='frame stats and transcript')
        self.assertEqual(len(llm.calls), 5)
        self.assertTrue(all('TARGET TOTAL LENGTH\n120 seconds' in x for x in llm.calls))
        self.assertEqual(len(out['scenes']), 60)
        self.assertEqual(out['total_duration'], 600)
        self.assertEqual([out['scenes'][i]['target_start'] for i in (0, 12, 24)],
                         [0, 120, 240])
        self.assertEqual(out['scenes'][-1]['id'], 's60')

    def test_sparse_90_second_reply_for_600_seconds_fails_before_gpu_and_save(self):
        class BadLLM:
            provider_name = 'fake'
            def healthcheck(self): return True, 'available'
            def chat(self, *args, **kwargs):
                return json.dumps({'scenes': [{'start': i * 9, 'end': (i + 1) * 9,
                                              'narration': 'Tiny line'} for i in range(10)]})
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(self.cfg(), Project(Path(tmp), 'bad'))
            with patch.object(p, 'provider', return_value=BadLLM()), \
                 patch('bot.reference.study_reference', return_value={
                     'video_id': 'dQw4w9WgXcQ', 'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                     'title': 'Ref', 'transcript': 'Content', 'duration': 30,
                     'visual_metrics': 'Blue', 'visual_style': '',
                     'has_captions': True, 'vision_analyzed': False}):
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    p.stage_script(topic='black holes', duration=600,
                                   reference_video='https://www.youtube.com/watch?v=dQw4w9WgXcQ')
            self.assertFalse(p.project.script_file.exists())
            self.assertFalse(p.manifest.stage_done('script'))
            self.assertNotIn('image:vast', p._providers)


if __name__ == '__main__':
    unittest.main()
