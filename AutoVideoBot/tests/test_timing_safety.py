"""A capped spoken line must never be cut to fit an LLM timestamp."""
import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from bot.config import Config
from bot.paths import Project
from bot.pipeline import Pipeline, _safe_speech_target
from bot.utils import read_json


class TimingSafetyTests(unittest.TestCase):
    def test_safe_window_grows_only_when_speech_would_be_clipped(self):
        self.assertEqual(_safe_speech_target(10, 8, 1.35, .15), 10)
        self.assertGreaterEqual(_safe_speech_target(6, 9.72, 1.35, .15), 7.5)

    def test_fitted_speech_is_preserved_and_project_timeline_extends(self):
        cfg = Config({'visual': {'engine': 'images'},
                      'motion': {'engine': 'ffmpeg'},
                      'tts': {'audio_format': 'wav', 'head_silence_ms': 150},
                      'timing': {'fit_to_timestamps': True, 'max_speedup': 1.35,
                                 'max_slowdown': .85, 'overflow_strategy': 'pad_then_hold'},
                      'transitions': {'enabled': False}})
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(cfg, Project(Path(tmp), 'video'))
            scene = {'id': 's01', 'narration': 'This sentence is longer than one second.',
                     'duration': 1., 'target_start': 0., 'target_end': 1.}
            p.scenes = [scene]
            p.script.data = {'scenes': p.scenes, 'source': 'topic', 'requested_duration': 1}
            p.script.save()
            raw = p.project.scene_audio('s01', 'wav')
            rate = 8000
            with wave.open(str(raw), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
                w.writeframes(b''.join(struct.pack('<h', int(5000 * math.sin(i * .06)))
                                       for i in range(rate * 2)))
            p.stage_timing()
            self.assertGreater(scene['duration'], 1.6)
            self.assertAlmostEqual(p.script.data['total_duration'], scene['duration'])
            report = read_json(p.project.audio_dir / 's01_fit.json', {})
            self.assertFalse(report.get('capped'), report)
            self.assertGreaterEqual(scene['duration'] + .02,
                                    scene['audio_duration'] + .15)
            self.assertTrue(p.manifest.stage_done('timing'))


if __name__ == '__main__':
    unittest.main()
