"""Build the local, audio-driven vector pilot. No LLM, Vast, or paid API calls.

Requires the already-created pilot/audio/scene-01..03.mp3, plus pip install
-r requirements.txt pocketsphinx, npm ci in render/, Chromium and FFmpeg.
Pocketsphinx *estimates* word boundaries from the recorded waveform; these are
not provider-supplied exact timestamps. Reject unknown words rather than
silently distributing captions evenly.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.config import Config
from bot.subtitles import build_srt, words_to_karaoke_ass, write_srt
from bot.utils import resolve_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / 'pilot'
RENDER = ROOT / 'render'
FPS = 24
PRE_ROLL_FRAMES = 12  # 0.5s for the transition before speech
SCENES = [
    ('stellar_equilibrium', 'Inside a massive star, gravity pulls every layer inward. Heat from fusion pushes outward. For millions of years, these opposing forces hold the star in balance.'),
    ('stellar_collapse', 'But fuel does not last forever. As fusion slows, outward pressure weakens, and gravity compresses the core. Under the right conditions, collapse can leave a black hole.'),
    ('horizon_boundary', 'Its event horizon is not a solid surface. It marks a boundary beyond which light cannot escape. Outside it, light may bend along the curved paths of spacetime.'),
]


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def align(audio: Path, text: str, ffmpeg: str) -> tuple[list[dict], float]:
    from pocketsphinx import Config as PSConfig, Decoder, get_model_path

    pcm = run([ffmpeg, '-loglevel', 'error', '-i', str(audio), '-ar', '16000',
               '-ac', '1', '-f', 's16le', '-']).stdout
    duration = len(pcm) / 32000.0
    if duration < 1:
        raise ValueError(f'No usable audio in {audio}')
    model = Path(get_model_path()) / 'en-us'
    decoder = Decoder(PSConfig(hmm=str(model / 'en-us'), dict=str(model / 'cmudict-en-us.dict'),
                               samprate=16000, loglevel='ERROR'))
    # The bundled dictionary has space and time, but not their compound.
    decoder.add_word('spacetime', f"{decoder.lookup_word('space')} {decoder.lookup_word('time')}", False)
    tokens = re.findall(r"[a-z']+", text.lower())
    decoder.set_align_text(' '.join(tokens))
    decoder.start_utt()
    decoder.process_raw(pcm, full_utt=True)
    decoder.end_utt()
    segments = [s for s in decoder.seg() if not s.word.startswith('<')]
    observed = [re.sub(r'\(\d+\)$', '', s.word) for s in segments]
    if tokens != observed:
        raise ValueError(f'Alignment did not cover script in {audio.name}: {observed!r}')
    words = [{'w': token, 's': round(max(0, seg.start_frame / 100), 3),
              'e': round(min(duration, seg.end_frame / 100), 3)}
             for token, seg in zip(text.split(), segments)]
    if len(words) != len(tokens) or any(w['e'] <= w['s'] for w in words):
        raise ValueError(f'Invalid timing for {audio.name}')
    return words, duration


def metadata(ffmpeg: str) -> tuple[dict, list[dict]]:
    cfg = Config({'subtitles': {'words_per_line': 4, 'max_chars_per_line': 42}})
    word_dir = PILOT / '.cache' / 'words'
    word_dir.mkdir(parents=True, exist_ok=True)
    frame = 0
    scenes = []
    for i, (shot, script) in enumerate(SCENES, 1):
        sid = f's{i:02d}'
        audio = PILOT / 'audio' / f'scene-{i:02d}.mp3'
        if not audio.is_file():
            raise FileNotFoundError(f'Missing narration: {audio}')
        words, audio_seconds = align(audio, script, ffmpeg)
        # Add >= 0.5s of tail room, rounded to whole frames.
        length = math.ceil((audio_seconds + 1) * FPS)
        start = frame / FPS
        pad = PRE_ROLL_FRAMES / FPS
        scene = {'id': sid, 'shot': shot, 'narration': script,
                 'start_frame': frame, 'duration_frames': length,
                 'start': start, 'end': (frame + length) / FPS,
                 'duration': length / FPS, 'speech_pad_before': pad,
                 'audio': f'audio/scene-{i:02d}.mp3',
                 'word_timings': [{'w': w['w'], 'start': round(start+pad+w['s'], 3),
                                   'end': round(start+pad+w['e'], 3)} for w in words]}
        if scene['word_timings'][-1]['end'] > scene['end'] - .35:
            raise ValueError(f'No tail room for {sid}')
        scenes.append(scene)
        (word_dir / f'{sid}.json').write_text(json.dumps({'words': words}), encoding='utf-8')
        frame += length
    # Cue the shader cut on the spoken word "Outside" (frame-quantized).
    cue = next(w for w in scenes[-1]['word_timings'] if w['w'].lower().strip('.,') == 'outside')
    shader_frame = round(cue['start'] * FPS)
    result = {'fps': FPS, 'width': 1280, 'height': 720,
              'duration_frames': frame,
              'shader_start_frame': shader_frame, 'shader_cue_word': 'Outside',
              'timing_source': 'Pocketsphinx forced alignment (estimated, not TTS word boundaries)',
              'scenes': scenes}
    (RENDER / 'src' / 'narrated-timing.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    cues = build_srt(scenes, cfg)
    write_srt(cues, PILOT / 'narrated-pilot.srt')
    ass = words_to_karaoke_ass(scenes, word_dir, PILOT / 'narrated-pilot.ass',
                              {'font_size': 52, 'outline': 3, 'shadow': 1,
                               'highlight_colour': '&H0000C8FF'},
                              play_w=1280, play_h=720)
    if ass is None:
        raise ValueError('No word-level alignment available')
    return result, scenes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-executable', help='Path to locally installed Chromium/Chrome')
    parser.add_argument('--gl', default='swangle', choices=['swangle', 'angle-egl', 'angle'],
                        help='Remotion browser graphics backend (default: CPU SwiftShader)')
    parser.add_argument('--metadata-only', action='store_true', help='Regenerate timing and subtitles without rendering')
    args = parser.parse_args()
    ffmpeg = resolve_ffmpeg('ffmpeg')
    timing, scenes = metadata(ffmpeg)
    print(f"Aligned {sum(len(s['word_timings']) for s in scenes)} words; "
          f"total {timing['duration_frames']/FPS:.2f}s (estimated forced alignment)")
    if args.metadata_only:
        return
    remotion = RENDER / 'node_modules' / '.bin' / 'remotion'
    if not remotion.is_file():
        raise FileNotFoundError('Run npm ci in render/ before building this test')
    silent = PILOT / '.cache' / 'narrated-silent.mp4'
    silent.parent.mkdir(exist_ok=True)
    cmd = [str(remotion), 'render', 'src/index.ts', 'NarratedPilot', str(silent),
           '--codec', 'h264', '--crf', '22', '--concurrency', '1', '--gl', args.gl, '--log', 'error']
    if args.browser_executable:
        cmd += ['--browser-executable', args.browser_executable]
    print('Rendering the Remotion timeline...', flush=True)
    subprocess.run(cmd, cwd=RENDER, check=True)
    # Audio inputs begin exactly on each scene's recorded-speech onset.
    inputs = [str(PILOT / sc['audio']) for sc in scenes]
    filters = []
    for i, sc in enumerate(scenes, 1):
        delay = round((sc['start'] + sc['speech_pad_before']) * 1000)
        filters.append(f'[{i}:a]adelay={delay}:all=1,aresample=48000[a{i}]')
    total = timing['duration_frames'] / FPS
    filters.append(''.join(f'[a{i}]' for i in range(1, len(scenes)+1)) +
                   f'amix=inputs={len(scenes)}:duration=longest:normalize=0,'
                   f'apad,atrim=duration={total:.6f}[mix]')
    # cwd=PILOT means no fragile path quoting in the libass filter argument.
    filters.insert(0, '[0:v]ass=narrated-pilot.ass[v]')
    command = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(silent)]
    for audio in inputs:
        command += ['-i', audio]
    command += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[mix]',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '160k', '-t', f'{total:.6f}', '-movflags', '+faststart',
                str(PILOT / 'narrated-pilot.mp4')]
    print('Burning word-timed captions and mixing narration...', flush=True)
    subprocess.run(command, cwd=PILOT, check=True)
    print(f"Done: {PILOT / 'narrated-pilot.mp4'}")


if __name__ == '__main__':
    main()
