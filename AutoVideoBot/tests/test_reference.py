"""Network-free tests for opt-in reference ingestion and prompt wiring."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline
from bot.reference import (canonical_url, captions_from_vtt, reference_context,
                           study_reference)
from bot.script import generate_script

VIDEO_ID = 'dQw4w9WgXcQ'
URL = 'https://www.youtube.com/watch?v=' + VIDEO_ID


class ReferenceTests(unittest.TestCase):
    def test_only_one_canonical_https_video_is_accepted(self):
        for value in [URL, 'https://youtu.be/' + VIDEO_ID + '?t=7',
                      'https://m.youtube.com/shorts/' + VIDEO_ID]:
            self.assertEqual(canonical_url(value), (URL, VIDEO_ID))
        for bad in ['http://www.youtube.com/watch?v=' + VIDEO_ID,
                    'https://youtube.com.evil.test/watch?v=' + VIDEO_ID,
                    'https://127.0.0.1/watch?v=' + VIDEO_ID,
                    'file:///etc/passwd',
                    URL + '&list=PL123',
                    'https://youtube.com/playlist?list=123',
                    'https://youtube.com:123/watch?v=' + VIDEO_ID,
                    'https://youtube.com:bad/watch?v=' + VIDEO_ID,
                    'https://user:pass@youtube.com/watch?v=' + VIDEO_ID]:
            # Playlist parameters on a watch URL are safe: canonicalize to
            # the single video and discard the playlist entirely.
            if bad == URL + '&list=PL123':
                self.assertEqual(canonical_url(bad), (URL, VIDEO_ID))
            else:
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    canonical_url(bad)

    def test_vtt_deduplicates_rolling_captions(self):
        text = ('WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n'
                '<c>Dark matter</c> bends light\n\n'
                '00:00:03.000 --> 00:00:05.000\n'
                'Dark matter bends light\n')
        self.assertEqual(captions_from_vtt(text).count('Dark matter bends light'), 1)
        self.assertIn('00:00:01.000', captions_from_vtt(text))

    def test_long_captions_include_story_ending(self):
        cues = ['WEBVTT']
        for i in range(200):
            stamp = f'00:{i // 60:02d}:{i % 60:02d}.000'
            cues.extend(['', f'{stamp} --> {stamp}', f'Beat {i} in the story.'])
        excerpt = captions_from_vtt('\n'.join(cues), limit=500)
        self.assertIn('Beat 0', excerpt)
        self.assertIn('Beat 199', excerpt)
        self.assertLessEqual(len(excerpt), 500)

    def test_study_downloads_bounded_media_and_caches_text_only(self):
        class FakeDownloader:
            calls = 0
            def __init__(self, options): self.options = options
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self, url, download=False):
                return {'id': VIDEO_ID, 'title': 'How gravity works', 'duration': 42}
            def download(self, urls):
                FakeDownloader.calls += 1
                scratch = Path(self.options['outtmpl']).parent
                (scratch / 'source.mp4').write_bytes(b'fake video')
                (scratch / 'source.en.vtt').write_text(
                    'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nA star bends light\n')
        def fake_ffmpeg(args, **kwargs):
            Image.new('RGB', (320, 180), (20, 30, 80)).save(args[-1])
            return Mock(returncode=0, stderr='')
        with tempfile.TemporaryDirectory() as tmp:
            project = Project(Path(tmp), 'video').create()
            downloader = types.SimpleNamespace(YoutubeDL=FakeDownloader)
            with patch.dict(sys.modules, {'yt_dlp': downloader}), \
                 patch('bot.reference.subprocess.run', side_effect=fake_ffmpeg) as ffmpeg, \
                 patch('bot.reference._vision', return_value='') as vision:
                report = study_reference(URL, project, Config({}))
                cached = study_reference(URL, project, Config({}))
            self.assertEqual(FakeDownloader.calls, 1)
            self.assertEqual(ffmpeg.call_count, 8)
            vision.assert_called_once()
            self.assertEqual(report, cached)
            self.assertTrue(report['has_captions'])
            self.assertFalse(report['vision_analyzed'])
            self.assertIn('star bends light', reference_context(report))
            self.assertFalse((project.tmp_dir / 'reference').exists())
            self.assertTrue((project.dir / 'reference.json').exists())

    def test_web_rejects_bad_reference_before_starting_a_job(self):
        try:
            from fastapi import HTTPException
        except ImportError:
            self.skipTest('FastAPI is optional in the minimal test environment')
        from webui.server import api_run
        with self.assertRaises(HTTPException) as err:
            api_run({'name': 'bad', 'mode': 'topic', 'topic': 'stars',
                     'reference_video': 'http://example.test/private'})
        self.assertEqual(err.exception.status_code, 400)
        with self.assertRaises(HTTPException) as err:
            api_run({'name': 'bad', 'mode': 'script', 'script_text': 'hello',
                     'reference_video': URL})
        self.assertEqual(err.exception.status_code, 400)

    def test_no_caption_and_no_vision_aborts_without_fake_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Project(Path(tmp), 'video').create()
            class FakeDownloader:
                def __init__(self, options): self.options = options
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def extract_info(self, url, download=False):
                    return {'id': VIDEO_ID, 'title': 'silent', 'duration': 20}
                def download(self, urls):
                    (Path(self.options['outtmpl']).parent / 'source.mp4').write_bytes(b'video')
            def fake_ffmpeg(args, **kwargs):
                Image.new('RGB', (320, 180)).save(args[-1])
                return Mock(returncode=0, stderr='')
            with patch.dict(sys.modules, {'yt_dlp': types.SimpleNamespace(YoutubeDL=FakeDownloader)}), \
                 patch('bot.reference.subprocess.run', side_effect=fake_ffmpeg):
                with self.assertRaisesRegex(RuntimeError, 'No usable captions'):
                    study_reference(URL, project, Config({}))
            self.assertFalse((project.dir / 'reference.json').exists())
            self.assertFalse((project.tmp_dir / 'reference').exists())

    def test_vision_only_when_explicitly_configured(self):
        from bot.reference import _vision
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / 'frame.jpg'
            Image.new('RGB', (10, 10)).save(frame)
            with patch('requests.post') as post:
                self.assertEqual(_vision([frame], Config({})), '')
                post.assert_not_called()
            response = Mock(status_code=200)
            response.json.return_value = {'choices': [{'message': {'content': 'blue animated diagrams'}}]}
            cfg = Config({'reference': {'vision': {'model': 'vision-model'}}})
            with patch.dict(os.environ, {'REFERENCE_VISION_BASE_URL': 'https://api.example.test/v1',
                                         'REFERENCE_VISION_API_KEY': 'not-real'}), \
                 patch('requests.post', return_value=response) as post:
                self.assertEqual(_vision([frame], cfg), 'blue animated diagrams')
            post.assert_called_once()
            self.assertEqual(post.call_args.args[0], 'https://api.example.test/v1/chat/completions')
            self.assertEqual(len(post.call_args.kwargs['json']['messages'][0]['content']), 2)

    def test_topic_pipeline_passes_reference_to_director_not_script_mode(self):
        class FakeLLM:
            provider_name = 'fake'
            def healthcheck(self): return True, 'ready'
            def chat(self, messages, **kwargs):
                self.prompt = messages[1]['content']
                return json.dumps({'title': 'New', 'scenes': [
                    {'narration': 'An original thought about gravity.',
                     'image_prompt': 'blue diagrams', 'start': 0, 'end': 10},
                    {'narration': 'A second original thought.',
                     'image_prompt': 'distant planet', 'start': 10, 'end': 20}]})
        report = {'url': URL, 'title': 'Reference', 'video_id': VIDEO_ID,
                  'duration': 30, 'transcript': 'opening then explanation',
                  'visual_metrics': 'blue hues', 'visual_style': 'animated blue graphics',
                  'has_captions': True, 'vision_analyzed': True}
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(Config({'llm': {'provider': 'fake'}, 'visual': {'engine': 'images'},
                                 'video': {'aspect': '16x9'}}), Project(Path(tmp), 'video'))
            llm = FakeLLM()
            with patch.object(p, 'provider', return_value=llm), \
                 patch('bot.reference.study_reference', return_value=report) as study:
                result = p.stage_script(topic='gravity', duration=20, reference_video=URL)
            study.assert_called_once()
            self.assertIn('opening then explanation', llm.prompt)
            self.assertIn('animated blue graphics', llm.prompt)
            self.assertEqual(result['reference_video']['url'], URL)
            with self.assertRaisesRegex(ValueError, 'only when writing from a topic'):
                p.stage_script(script_file=p.project.input_file, reference_video=URL)

    def test_without_reference_uses_no_reference_module(self):
        class LLM:
            provider_name = 'fake'
            def chat(self, messages, **kwargs):
                self.prompt = messages[1]['content']
                return json.dumps({'scenes': [{'narration': 'first', 'start': 0, 'end': 5},
                                               {'narration': 'second', 'start': 5, 'end': 10}]})
        llm = LLM()
        generate_script(llm, Config({}), topic='test', duration=10)
        self.assertNotIn('REFERENCE STUDY', llm.prompt)


if __name__ == '__main__':
    unittest.main()
