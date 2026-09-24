"""
bot/utils.py
=============
Small helper functions used everywhere in the bot.
Nothing in here talks to the internet - these are pure utilities.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

try:
    from rich.console import Console
except Exception:                                  # pragma: no cover
    Console = None                                 # type: ignore[assignment]

_console = None


def _get_console():
    """
    A rich Console that ALWAYS writes to whatever sys.stdout is right now.

    WHY THIS IS NOT JUST `console = Console()`
    ------------------------------------------
    rich grabs sys.stdout when the Console is created, and keeps that reference
    forever. That breaks two things we care about:

      * the web UI captures a build's output by swapping sys.stdout for a
        writer object. A console built at import time kept printing to the
        real terminal, so the browser's log would have been mysteriously
        empty of stage banners.
      * redirect_stdout() around a chatty library call (used to keep a
        "missing API key" essay out of the middle of a successful build)
        would not have silenced rich either.

    Rebuilding the console ONLY when the output stream changes gives us both,
    and costs nothing in the normal case.
    """
    global _console
    if Console is None:
        return None
    if _console is None or getattr(_console, "file", None) is not sys.stdout:
        try:
            # soft_wrap keeps long paths from being reflowed oddly in a browser
            _console = Console(file=sys.stdout, soft_wrap=False)
        except Exception:                          # pragma: no cover
            return None
    return _console


# kept for anything that imports `console` directly (older code/plugins)
class _ConsoleProxy:
    """Forwards attribute access to the live console (or to print)."""

    def __getattr__(self, item):
        c = _get_console()
        if c is None:
            raise AttributeError(item)
        return getattr(c, item)

    def print(self, *args, **kwargs):
        c = _get_console()
        if c is not None:
            return c.print(*args, **kwargs)
        return print(*args)


console = _ConsoleProxy()


# ---------------------------------------------------------------------------
# THE PROJECT LOG FILE  (workspace/projects/<name>/logs/run.log)
# ---------------------------------------------------------------------------
#   Every run is ALSO written to a text file inside the project folder, so that
#   when something goes wrong you can open one file and read the whole story -
#   or send it to someone - instead of scrolling a terminal that has already
#   been closed. The terminal output is untouched: we write to both at once.
#
#   This is a "tee": sys.stdout (and sys.stderr) are wrapped in an object that
#   forwards everything to the real stream AND to the open log file.
# ---------------------------------------------------------------------------
class _Tee:
    """Forwards write() to the real stream and to the project's run.log."""

    def __init__(self, stream, handle):
        self._stream = stream
        self._handle = handle

    # -- the important bits -------------------------------------------
    def write(self, data):
        if isinstance(data, bytes):                # paranoia: keep it text
            data = data.decode("utf-8", "replace")
        try:
            self._stream.write(data)
        except Exception:                          # pragma: no cover
            pass
        try:
            self._handle.write(data)
        except Exception:                          # pragma: no cover
            pass
        return len(data)

    def flush(self):
        for target in (self._stream, self._handle):
            try:
                target.flush()
            except Exception:                      # pragma: no cover
                pass

    def isatty(self):
        return False

    def writable(self):
        return True

    def readable(self):
        return False

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8") or "utf-8"

    @property
    def errors(self):
        return getattr(self._stream, "errors", "replace")

    @property
    def log_path(self):
        return getattr(self._handle, "name", "")

    def fileno(self):                              # subprocess(...) may ask
        return self._stream.fileno()

    def __getattr__(self, item):                   # delegate anything else
        return getattr(self._stream, item)


_run_log_handle = None


def attach_run_log(path) -> bool:
    """
    Start copying all console output into `path` (the project's run.log).

    Safe to call more than once, and safe to call from the web UI (where
    sys.stdout is already a capture object - the tee simply sits on top of it).
    Returns True when the log is being written.
    """
    global _run_log_handle
    import atexit
    from pathlib import Path as _Path

    p = _Path(path)
    try:
        ensure_dir(p.parent)
        already = isinstance(sys.stdout, _Tee) and str(getattr(sys.stdout, "log_path", "")) == str(p)
        handle = sys.stdout._handle if already else open(p, "a", encoding="utf-8", errors="replace")
    except Exception as e:                         # pragma: no cover
        try:
            print(f"(could not open the run log: {e})")
        except Exception:
            pass
        return False

    if already:
        return True

    if _run_log_handle is not None and _run_log_handle is not handle:
        try:
            _run_log_handle.close()
        except Exception:                          # pragma: no cover
            pass
    _run_log_handle = handle

    handle.write(
        "\n"
        + "=" * 78 + "\n"
        + f"  AutoVideoBot run log  -  {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        + f"  project: {p.parent.parent.name}\n"
        + "  (this file is appended to on every run - send it if you need help)\n"
        + "=" * 78 + "\n"
    )
    try:
        sys.stdout = _Tee(sys.stdout, handle)
        sys.stderr = _Tee(sys.stderr, handle)
    except Exception:                              # pragma: no cover
        return False

    def _close():                                  # runs at interpreter exit
        try:
            handle.flush()
            handle.close()
        except Exception:                          # pragma: no cover
            pass

    atexit.register(_close)
    return True


# ---------------------------------------------------------------------------
# PRETTY TERMINAL OUTPUT
# ---------------------------------------------------------------------------
def log(msg: str, style: str = "") -> None:
    """Print a message. Uses rich colours when available."""
    c = _get_console()
    if c is not None:
        try:
            c.print(msg, style=style or None, highlight=False)
            return
        except Exception:                          # pragma: no cover
            pass
    print(re.sub(r"\[/?[a-zA-Z0-9 _=#\.\-]+\]", "", str(msg)))


def step(title: str) -> None:
    log(f"\n[bold cyan]{'=' * 72}[/]\n[bold cyan]  {title}[/]\n[bold cyan]{'=' * 72}[/]")


def info(msg: str) -> None:
    log(f"[dim]  ·[/] {msg}")


def ok(msg: str) -> None:
    log(f"[green]  ✔[/] {msg}")


def warn(msg: str) -> None:
    log(f"[yellow]  ![/] [yellow]{msg}[/]")


def fail(msg: str) -> None:
    log(f"[bold red]  ✖ {msg}[/]")


def die(msg: str, code: int = 1) -> None:
    fail(msg)
    sys.exit(code)


def debug(msg: str) -> None:
    if os.environ.get("AVB_DEBUG") == "1":
        log(f"[dim]    DEBUG {msg}[/]")


# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
def ensure_dir(p: Path | str) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def file_fingerprint(path: Path | str) -> str:
    """
    A short hash of a file's CONTENT (16 hex chars), or "" if unreadable.

    WHY THIS EXISTS - the "fixed my images but the video did not change" trap
    -----------------------------------------------------------------------
    The bot decides whether a step can be skipped by hashing the *inputs* of
    that step. If the fingerprint of an image were just its file name
    ("s01.jpg"), then replacing a placeholder card with the real artwork -
    the exact thing you do after getting internet back - would look like
    "nothing changed", and the final video would still contain the placeholder.

    Hashing the bytes instead means: change the picture and the clip, the
    crossfade join and the final render all notice, and only they redo their
    work. Files under 64 MB are hashed whole (a 3 MB clip takes ~5 ms); bigger
    ones are sampled from both ends, which is plenty to spot a change.
    """
    p = Path(path)
    try:
        size = p.stat().st_size
        h = hashlib.sha1()
        h.update(f"{size}:".encode())
        with open(p, "rb") as f:
            if size <= 64 * 1024 * 1024:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            else:
                h.update(f.read(1 << 20))
                f.seek(-(1 << 20), os.SEEK_END)
                h.update(f.read())
        return h.hexdigest()[:16]
    except Exception:
        return ""


def slugify(text: str, max_len: int = 48) -> str:
    """Turn any string into a safe folder / file name."""
    text = (text or "untitled").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return (text[:max_len].rstrip("-")) or "untitled"


# ---------------------------------------------------------------------------
# HASHING / CACHING
# ---------------------------------------------------------------------------
def stable_hash(obj: Any) -> str:
    """
    Deterministic hash of any JSON-able object.
    Used to decide "have I already generated this exact thing?".
    """
    blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# TIME FORMATTING
# ---------------------------------------------------------------------------
def fmt_time(seconds: float) -> str:
    """125.4 -> '2m 05s'"""
    seconds = max(0.0, float(seconds))
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return (f"{h}h " if h else "") + (f"{m:02d}m " if (h or m) else "") + f"{s:02d}s"


def seconds_to_srt_time(seconds: float) -> str:
    """12.345 -> '00:00:12,345'  (SRT / ASS timestamp format)"""
    if seconds < 0:
        seconds = 0.0
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if ms == 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_timestamp(value: Any) -> float | None:
    """
    Accept almost anything a human would type and return seconds as a float.
      90            -> 90.0
      "90"          -> 90.0
      "1:30"        -> 90.0
      "00:01:30"    -> 90.0
      "01:30.500"   -> 90.5
      "90s"         -> 90.0
      "1m30s"       -> 90.0
      None / ""     -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower().rstrip(".")
    if not s or s in {"none", "null", "-"}:
        return None
    s = s.replace("min", "m").replace("sec", "s")

    # "1m30s" style
    m = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s?)?", s)
    if m and any(m.groups()):
        h, mi, se = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0)

    # "hh:mm:ss.ms" style
    if ":" in s:
        parts = s.split(":")
        try:
            parts = [float(p) for p in parts]
        except ValueError:
            return None
        total = 0.0
        for p in parts:
            total = total * 60 + p
        return total

    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# SUBPROCESS (running ffmpeg and friends)
# ---------------------------------------------------------------------------
def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    capture: bool = True,
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess:
    """
    Run a shell command safely.
    Returns a CompletedProcess. Raises RuntimeError if it fails and check=True.
    """
    printable = " ".join(str(c) if " " not in str(c) else f'"{c}"' for c in cmd)
    if not quiet:
        debug(f"CMD {printable[:400]}")
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
            capture_output=capture,
            text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Command not found: {cmd[0]}\n"
            f"Install it, or set its full path in config.yaml -> system section."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out after {timeout}s: {printable[:200]}") from e

    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2500:]
        rc = proc.returncode
        hint = ""
        # -9 == SIGKILL, which on a desktop almost always means the kernel's
        # out-of-memory killer stepped in. That is by far the most confusing
        # failure a beginner hits, so explain it instead of showing a number.
        if rc in (-9, 137) or "Killed" in tail:
            hint = (
                "\n\nDIAGNOSIS: the process was KILLED by the operating system, "
                "which nearly always means it ran out of RAM.\n"
                "FIXES, easiest first:\n"
                "  1. config.yaml -> motion.supersample: auto   (the bot will pick a size your RAM can hold)\n"
                "  2. config.yaml -> motion.supersample: 2    (forces the cheapest setting)\n"
                "  3. config.yaml -> system.parallel_scenes: 1 (render one scene at a time)\n"
                "  4. config.yaml -> video.preset: ultrafast   (x264 uses far less memory)\n"
                "  5. close other programs / lower video.width and video.height\n"
            )
        elif rc == -11 or "Segmentation" in tail:
            hint = "\n\nDIAGNOSIS: ffmpeg crashed (segfault). Usually a broken filter argument or a damaged input file."
        raise RuntimeError(
            f"Command failed (exit {rc}):\n{printable[:600]}\n\n--- output ---\n{tail}{hint}"
        )
    return proc


def which(binary: str) -> str | None:
    return shutil.which(binary)


# ---------------------------------------------------------------------------
# FFMPEG DISCOVERY
# ---------------------------------------------------------------------------
def resolve_ffmpeg(configured: str | None = None, fallback: str | None = "ffmpeg") -> str:
    """
    Find a usable ffmpeg, in this order:

      1. the exact path in config.yaml  (system.ffmpeg_bin)
      2. whatever is on your PATH
      3. the ffmpeg that the 'imageio-ffmpeg' pip package downloads for you

    Step 3 is what saves beginners: `pip install imageio-ffmpeg` puts a real
    ffmpeg binary inside your virtual environment, so the bot works even if
    you never installed ffmpeg system-wide (this is what the Windows installer
    does for you automatically).

    Returns the path (or the plain name, which fails later with a clear error).
    """
    candidates: list[str] = []
    if configured and str(configured).strip():
        candidates.append(str(configured).strip())
    candidates.append("ffmpeg")
    if fallback and fallback not in candidates:
        candidates.append(str(fallback))

    for cand in candidates:
        if os.path.sep in cand or (os.path.altsep and os.path.altsep in cand):
            if Path(cand).exists():
                return cand
            continue
        found = shutil.which(cand)
        if found:
            return found

    # ---- bundled copy from the imageio-ffmpeg package -------------------
    try:
        import imageio_ffmpeg                                  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass

    return str(configured or "ffmpeg")


def resolve_ffprobe(configured: str | None = None) -> str | None:
    """
    ffprobe is a *separate* program that ships next to ffmpeg.

    IMPORTANT: it is very common to have ffmpeg but NOT ffprobe (the pip
    imageio-ffmpeg package only bundles ffmpeg). The bot therefore never
    requires it - probe_duration() falls back to parsing `ffmpeg -i` output,
    which reports the same duration. This function just tries to be nice.
    """
    if configured and str(configured).strip():
        cand = str(configured).strip()
        if Path(cand).exists():
            return cand
        found = shutil.which(cand)
        if found:
            return found
    found = shutil.which("ffprobe")
    if found:
        return found
    # maybe it sits next to the ffmpeg we found
    try:
        ff = resolve_ffmpeg(None, None)
        beside = Path(ff).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
        if beside.exists():
            return str(beside)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# JSON HELPERS
# ---------------------------------------------------------------------------
def extract_json(text: str) -> Any:
    """
    LLMs love to wrap JSON in markdown fences or add chatty sentences.
    This pulls the real JSON object/array out of whatever they returned.
    """
    if not text:
        raise ValueError("Empty response from the LLM")

    t = text.strip()

    # 1. remove ```json ... ``` fences
    fence = re.search(r"```(?:json|JSON)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()

    # 2. try direct parse
    try:
        return json.loads(t)
    except Exception:
        pass

    # 3. grab the biggest balanced { ... } or [ ... ] block
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start != -1 and end > start:
            candidate = t[start:end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                # 4. last resort: strip trailing commas (a very common LLM bug)
                cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
                try:
                    return json.loads(cleaned)
                except Exception:
                    continue
    raise ValueError(f"Could not find valid JSON in LLM response. First 500 chars:\n{t[:500]}")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(Path(path).parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def read_json(path: Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# MISC
# ---------------------------------------------------------------------------
def chunk_words(text: str, max_words: int = 4, max_chars: int = 42) -> list[str]:
    """Split narration into readable subtitle chunks."""
    words = re.findall(r"\S+", (text or "").strip())
    if not words:
        return []
    out, cur = [], []
    cur_len = 0
    for w in words:
        projected = cur_len + len(w) + (1 if cur else 0)
        if cur and (len(cur) >= max_words or projected > max_chars):
            out.append(" ".join(cur))
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len = projected
    if cur:
        out.append(" ".join(cur))
    return out


def retry(fn, *, attempts: int = 3, delay: float = 2.0, what: str = "operation",
          backoff: float = 2.0, on_fail=None):
    """Run fn() up to `attempts` times with exponential backoff."""
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:                     # noqa: BLE001
            last = e
            if i < attempts:
                warn(f"{what} failed (attempt {i}/{attempts}): {str(e)[:160]}")
                time.sleep(delay * (backoff ** (i - 1)))
            else:
                fail(f"{what} failed after {attempts} attempts: {str(e)[:300]}")
    if on_fail is not None:
        return on_fail(last)
    raise RuntimeError(f"{what} failed: {last}")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def flatten(d: dict, parent: str = "", sep: str = ".") -> dict:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{parent}{sep}{k}" if parent else str(k)
        if isinstance(v, dict):
            out.update(flatten(v, key, sep))
        else:
            out[key] = v
    return out


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` on top of `base` (override wins)."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def first_existing(paths: Iterable[Path]) -> Path | None:
    for p in paths:
        if p and Path(p).exists():
            return Path(p)
    return None


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
