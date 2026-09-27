"""Regression checks for the standalone narrated vector-motion proof."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NarratedPilotTests(unittest.TestCase):
    def test_audio_driven_scene_and_word_windows(self):
        timing = json.loads((ROOT / 'render/src/narrated-timing.json').read_text())
        scenes = timing['scenes']
        fps = timing['fps']
        self.assertEqual([s['shot'] for s in scenes],
                         ['stellar_equilibrium', 'stellar_collapse', 'horizon_boundary'])
        self.assertTrue(30 <= timing['duration_frames'] / fps <= 45)
        end_frame = 0
        for scene in scenes:
            self.assertEqual(scene['start_frame'], end_frame)
            self.assertEqual(scene['start'], end_frame / fps)
            self.assertTrue((ROOT / 'pilot' / scene['audio']).is_file())
            self.assertEqual(len(scene['word_timings']), len(scene['narration'].split()))
            self.assertGreaterEqual(scene['word_timings'][0]['start'],
                                    scene['start'] + scene['speech_pad_before'])
            self.assertLess(scene['word_timings'][-1]['end'], scene['end'])
            for first, second in zip(scene['word_timings'], scene['word_timings'][1:]):
                self.assertLessEqual(first['start'], first['end'])
                self.assertLessEqual(first['end'], second['start'] + .02)
            end_frame += scene['duration_frames']
        self.assertEqual(timing['duration_frames'], end_frame)
        cue = next(w for w in scenes[-1]['word_timings'] if w['w'].lower().strip('.,') == 'outside')
        self.assertEqual(timing['shader_start_frame'], round(cue['start']*fps))
        self.assertIn('estimated', timing['timing_source'])

    def test_burned_caption_intervals_do_not_overlap(self):
        ass = (ROOT / 'pilot/narrated-pilot.ass').read_text()
        events = [line for line in ass.splitlines() if line.startswith('Dialogue:')]
        self.assertGreater(len(events), 10)
        def seconds(stamp: str) -> float:
            h, m, s = stamp.split(':')
            return int(h)*3600 + int(m)*60 + float(s)
        previous = 0.0
        for line in events:
            fields = line.split(',', 3)
            start, end = seconds(fields[1]), seconds(fields[2])
            self.assertGreaterEqual(start + .011, previous)
            self.assertGreater(end, start)
            previous = end
        self.assertEqual(ass.count(r'{\k'), 81)


if __name__ == '__main__':
    unittest.main()
