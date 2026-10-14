"""The local neural voice for Hear it and the examiner: Kokoro-82M (ONNX), on this computer.

Kokoro reads a phrase the way a person would, which a browser voice cannot: one model call per phrase, so the
intonation runs across the words instead of restarting at every cue. The cue plan is then laid onto that
reading (shaping.py), not by chopping the line into utterances:

- a pause is real silence between phrases, exactly as long as the plan says;
- pace: Kokoro reads at its nearest speed, then each segment is stretched so the line takes as long as the
  plan's words per minute say, a slowed word relative to the rest;
- stress, softening, loudness: pitch and gain over the segment's own span, which Kokoro reports (it also gets
  a primary stress mark on a stressed word);
- a rising or held end: Kokoro ends nearly every phrase falling whatever the punctuation, so the end of the
  last word is bent; a falling end is kept as read;
- [SAY] with IPA: the IPA goes to the model as its phonemes; a respelling becomes one word, stressed where
  its capitals are.

The model (163 MB) and voices (28 MB) are downloaded once from the kokoro-onnx release on GitHub, checked
against their SHA-256, and kept in MODELS_DIR. Nothing about the speaker is sent anywhere: synthesis is local.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from take_two.config import MODELS_DIR
from take_two.shaping import Shape, Span, shape

log = logging.getLogger(__name__)

SR = 24000
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
# (file, bytes, sha256). fp16: the same speed as fp32 on CPU at half the download; int8 is ten times slower.
MODEL = ("kokoro-v1.0.fp16.onnx", 163_527_961, "f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96")
VOICES_FILE = ("voices-v1.0.bin", 28_214_398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d")
DOWNLOAD_MB = round((MODEL[1] + VOICES_FILE[1]) / 1e6)

# The English voices with the best grades in Kokoro's VOICES.md: (label, its own pace in words per minute at
# speed 1, measured here on four lines, used only to pick a starting speed; the plan's pace is then matched).
VOICES: dict[str, tuple[str, float]] = {
    "af_heart": ("Heart (American, female)", 200.0),
    "af_bella": ("Bella (American, female)", 194.0),
    "am_michael": ("Michael (American, male)", 177.0),
    "am_fenrir": ("Fenrir (American, male)", 196.0),
    "bf_emma": ("Emma (British, female)", 209.0),
    "bm_george": ("George (British, male)", 175.0),
}
DEFAULT_VOICE = {"coach": "af_heart", "examiner": "am_michael"}
SPEED_RANGE = (0.5, 2.0)
RESYNTH_OFF = 0.15        # read again at a corrected speed when the stretch needed is larger than this
MAX_PHONEMES = 480        # kokoro-onnx splits longer input itself; a phrase is kept below that
PUNCT = ".,!?;:…—"
VOWELS = set("AIOQWYaeiouæɑɒɔəɛɜɪʊʌᵻɐɚɝ")


def lang_of(voice: str) -> str:
    return "en-gb" if voice.startswith("b") else "en-us"


def words_of(text: str) -> int:
    return len(text.split())


# ---- phonemes -------------------------------------------------------------------------------------------------

def normalize_ipa(ipa: str) -> str:
    """The app's IPA as Kokoro's phonemes: no slashes or brackets, ASCII g and r as the IPA letters Kokoro
    knows, an apostrophe as the stress mark, no tie bars or syllable dots, one word."""
    s = re.sub(r"[/\[\]\s.]", "", ipa)
    s = s.replace("g", "ɡ").replace("r", "ɹ").replace("'", "ˈ").replace("͡", "").replace("͜", "")
    return s


def add_stress(ph: str) -> str:
    """A primary stress mark on a word that has none (misaki's +2): an unstressed word said as stressed."""
    if "ˈ" in ph:
        return ph
    if "ˌ" in ph:
        return ph.replace("ˌ", "ˈ", 1)
    i = next((j for j, c in enumerate(ph) if c in VOWELS), 0)
    return ph[:i] + "ˈ" + ph[i:]


def trailing_punct(text: str) -> str:
    m = re.search(rf"[{re.escape(PUNCT)}]+$", text.strip().strip("\"'”’)"))
    return m.group(0) if m else ""


def respelling_phonemes(respelling: str, phonemize) -> str:
    """KOH-ral -> one word, each syllable phonemized, stressed where the respelling has capitals."""
    sylls = [s for s in re.split(r"[-\s]+", respelling) if s]
    stressed = [s.isupper() and (len(sylls) == 1 or not respelling.isupper()) for s in sylls]
    if not any(stressed):
        stressed = [i == 0 for i in range(len(sylls))]
    out = []
    for syl, st in zip(sylls, stressed):
        ph = re.sub(rf"[ˈˌ\s{re.escape(PUNCT)}]", "", phonemize(syl.lower()))
        out.append(add_stress(ph) if st else ph)
    return "".join(out)


def segment_phonemes(seg: dict, phonemize) -> str:
    """One segment of the plan as Kokoro phonemes, words separated by single spaces."""
    text = str(seg.get("text") or "").strip()
    if seg.get("ipa"):
        ph = normalize_ipa(str(seg["ipa"])) + trailing_punct(text)
    elif seg.get("say_as"):
        ph = respelling_phonemes(str(seg["say_as"]), phonemize) + trailing_punct(text)
    else:
        ph = phonemize(text) if text else ""
    words = ph.split()
    if seg.get("stress"):
        words = [add_stress(w) for w in words]
    return " ".join(words)


# ---- phrases and spans ------------------------------------------------------------------------------------------

@dataclass
class Phrase:
    segs: list[int]          # indexes into plan["segments"]
    pause_after: float


def phrases(segments: list[dict]) -> list[Phrase]:
    """Runs of segments read in one breath: a new phrase after every pause. Empty segments keep their pause."""
    out: list[Phrase] = []
    cur: list[int] = []
    for i, s in enumerate(segments):
        if str(s.get("text") or "").strip():
            cur.append(i)
        pause = min(max(float(s.get("pause_after_s") or 0.0), 0.0), 10.0)
        if pause > 0:
            if cur:
                out.append(Phrase(cur, pause))
                cur = []
            elif out:
                out[-1].pause_after += pause
    if cur:
        out.append(Phrase(cur, 0.0))
    return out


def word_spans(timings, n_words: int) -> list[tuple[float, float]] | None:
    """(start, end) of each word from Kokoro's phoneme timings, spaces separating words; punctuation is not
    part of a word. None when the count does not come out as expected (then spans are estimated)."""
    spans: list[list[float]] = []
    cur: list[float] | None = None
    for t in timings:
        if t.phoneme == " ":
            if cur is not None:
                spans.append(cur)
                cur = None
            continue
        if t.phoneme in PUNCT + "\"()“”":
            continue
        cur = [t.start, t.end] if cur is None else [cur[0], t.end]
    if cur is not None:
        spans.append(cur)
    return [(a, b) for a, b in spans] if len(spans) == n_words else None


def segment_spans(counts: list[int], words: list[tuple[float, float]] | None, total: float) -> list[Span]:
    """Each segment's span in the phrase audio: from its first word to the next segment's first word."""
    n = sum(counts)
    if words is None:  # spread by word count over the phrase
        edges = np.concatenate([[0.0], np.cumsum(counts)]) / max(n, 1) * total
        return [Span(float(edges[i]), float(edges[i + 1]),
                     (float(edges[i + 1] - (edges[i + 1] - edges[i]) / max(c, 1)), float(edges[i + 1])) if c else None)
                for i, c in enumerate(counts)]
    out: list[Span] = []
    k = 0
    firsts = []
    for c in counts:
        firsts.append(words[k][0] if c and k < len(words) else None)
        k += c
    k = 0
    for i, c in enumerate(counts):
        start = firsts[i] if firsts[i] is not None else (out[-1].end if out else 0.0)
        if i == 0:
            start = 0.0
        nxt = next((f for f in firsts[i + 1:] if f is not None), None)
        end = nxt if nxt is not None else total
        last = words[k + c - 1] if c else None
        out.append(Span(start, max(start, end), last))
        k += c
    return out


def pace_factors(segments: list[dict], idx: list[int], spans: list[Span]) -> tuple[list[float], float]:
    """(duration factor per segment, the overall stretch g). The line takes as long as the plan's words per
    minute say, and each segment keeps its pace relative to the others. A segment without a pace (wpm 0) is
    left as read."""
    n = [words_of(str(segments[i].get("text") or "")) for i in idx]
    wpm = [float(segments[i].get("wpm") or 0.0) for i in idx]
    actual = [max(1e-3, sp.end - sp.start) for sp in spans]
    paced = [j for j in range(len(idx)) if wpm[j] > 0 and n[j] > 0]
    if not paced:
        return [1.0] * len(idx), 1.0
    target = sum(n[j] * 60.0 / wpm[j] for j in paced)
    mean = sum(n[j] for j in paced) / sum(n[j] / wpm[j] for j in paced)
    rel = {j: mean / wpm[j] for j in paced}
    g = target / sum(actual[j] * rel[j] for j in paced)
    return [g * rel[j] if j in rel else 1.0 for j in range(len(idx))], g


def mean_wpm(segments: list[dict], idx: list[int]) -> float | None:
    pairs = [(words_of(str(segments[i].get("text") or "")), float(segments[i].get("wpm") or 0.0)) for i in idx]
    pairs = [(n, w) for n, w in pairs if n and w > 0]
    if not pairs:
        return None
    return sum(n for n, _ in pairs) / sum(n / w for n, w in pairs)


def wav_bytes(audio: np.ndarray, sr: int = SR) -> bytes:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


# ---- the engine -------------------------------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Kokoro:
    """Loads once (downloading the files the first time), then renders plans. Thread-safe."""

    def __init__(self, models_dir: Path = MODELS_DIR):
        self.dir = Path(models_dir)
        self._k = None
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self.state = "not loaded"     # not loaded | downloading | loading | ready | failed
        self.progress = 0.0
        self.error: str | None = None

    def installed(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            return True
        except Exception:
            return False

    def files_present(self) -> bool:
        return all((self.dir / f).exists() and (self.dir / f).stat().st_size == size for f, size, _ in (MODEL, VOICES_FILE))

    def _download(self) -> None:
        import httpx
        self.dir.mkdir(parents=True, exist_ok=True)
        todo = [f for f in (MODEL, VOICES_FILE)
                if not ((self.dir / f[0]).exists() and (self.dir / f[0]).stat().st_size == f[1])]
        total = sum(f[1] for f in todo) or 1
        done = 0
        for name, size, sha in todo:
            part = self.dir / (name + ".part")
            with httpx.stream("GET", RELEASE + name, follow_redirects=True, timeout=60) as r:
                r.raise_for_status()
                with part.open("wb") as out:
                    for chunk in r.iter_bytes(1 << 20):
                        out.write(chunk)
                        done += len(chunk)
                        self.progress = min(done / total, 1.0)
            if part.stat().st_size != size or _sha256(part) != sha:
                part.unlink(missing_ok=True)
                raise RuntimeError(f"{name} did not match its published size and checksum")
            os.replace(part, self.dir / name)

    def load(self):
        """The loaded model; downloads and loads it on first use. Raises RuntimeError with a reason."""
        if self._k is not None:
            return self._k
        with self._load_lock:
            if self._k is not None:
                return self._k
            try:
                if not self.files_present():
                    self.state = "downloading"
                    log.info("Downloading the Kokoro voice model (%d MB) to %s", DOWNLOAD_MB, self.dir)
                    self._download()
                self.state = "loading"
                import onnxruntime as rt
                from kokoro_onnx import Kokoro as _Kokoro
                opts = rt.SessionOptions()
                opts.log_severity_level = 3  # the fp16 graph logs a warning per node it cannot constant-fold
                sess = rt.InferenceSession(str(self.dir / MODEL[0]), opts, providers=["CPUExecutionProvider"])
                self._k = _Kokoro.from_session(sess, str(self.dir / VOICES_FILE[0]))
                self.state, self.error = "ready", None
                log.info("Kokoro voice ready")
            except Exception as exc:
                self.state, self.error = "failed", f"{type(exc).__name__}: {exc}"
                log.warning("Kokoro voice unavailable: %s", self.error)
                raise RuntimeError(f"The natural voice could not be prepared ({self.error}).") from exc
        return self._k

    def render(self, plan: dict, voice: str) -> tuple[np.ndarray, list[float | None], list[str]]:
        """(audio at SR, each segment's start in seconds or None if not spoken, what was shaped)."""
        if voice not in VOICES:
            raise RuntimeError(f"no Kokoro voice called {voice}")
        k = self.load()
        segments = list(plan.get("segments") or [])
        lang = lang_of(voice)
        phon = lambda s: k.tokenizer.phonemize(s, lang)  # noqa: E731
        lead = min(max(float(plan.get("lead_pause_s") or 0.0), 0.0), 10.0)
        parts = [np.zeros(int(SR * lead), dtype=np.float32)]
        t = lead
        starts: list[float | None] = [None] * len(segments)
        applied: list[str] = []
        with self._run_lock:
            for ph in phrases(segments):
                for chunk in self._chunks(ph.segs, segments, phon):
                    audio, rel, did = self._phrase(k, voice, lang, segments, chunk, phon)
                    for i, s in zip(chunk, rel):
                        starts[i] = round(t + s, 3)
                    parts.append(audio)
                    t += len(audio) / SR
                    applied += did
                parts.append(np.zeros(int(SR * ph.pause_after), dtype=np.float32))
                t += ph.pause_after
        return np.concatenate(parts), starts, applied

    def _chunks(self, idx: list[int], segments: list[dict], phon) -> list[list[int]]:
        """A phrase split at segment boundaries so each model call stays under MAX_PHONEMES."""
        out: list[list[int]] = [[]]
        size = 0
        for i in idx:
            n = len(segment_phonemes(segments[i], phon)) + 1
            if out[-1] and size + n > MAX_PHONEMES:
                out.append([])
                size = 0
            out[-1].append(i)
            size += n
        return out

    def _phrase(self, k, voice: str, lang: str, segments: list[dict], idx: list[int], phon):
        seg_ph = [segment_phonemes(segments[i], phon) for i in idx]
        counts = [len(p.split()) for p in seg_ph]
        text = " ".join(p for p in seg_ph if p)
        if not text:
            return np.zeros(0, dtype=np.float32), [0.0] * len(idx), []
        want = mean_wpm(segments, idx)
        speed = min(max((want or VOICES[voice][1]) / VOICES[voice][1], SPEED_RANGE[0]), SPEED_RANGE[1])
        for attempt in range(2):
            audio, _, timings = k.create_timed(text, voice=voice, speed=speed, lang=lang, is_phonemes=True)
            audio = np.asarray(audio, dtype=np.float32)
            total = len(audio) / SR
            spans = segment_spans(counts, word_spans(timings, sum(counts)), total)
            factors, g = pace_factors(segments, idx, spans)
            if attempt == 0 and abs(g - 1) > RESYNTH_OFF and SPEED_RANGE[0] < speed < SPEED_RANGE[1]:
                speed = min(max(speed / g, SPEED_RANGE[0]), SPEED_RANGE[1])
                continue
            break
        shapes = [Shape(dur=f, pitch_st=float(segments[i].get("pitch_st") or 0.0),
                        gain_db=float(segments[i].get("volume_db") or 0.0),
                        contour=str(segments[i].get("contour") or "none")) for f, i in zip(factors, idx)]
        res = shape(audio, SR, spans, shapes)
        return res.audio, res.starts, res.applied


ENGINE = Kokoro()
