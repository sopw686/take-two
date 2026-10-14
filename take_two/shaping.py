"""Lay a cue plan onto speech a neural voice has already read naturally.

A neural voice reads a phrase with its own intonation, which is what makes it sound human, but it takes no
per-word instructions. So the plan is applied afterwards, to the spans of the reading each segment occupies,
with Praat's overlap-add resynthesis (parselmouth, already a dependency):

- pace: each span is stretched or compressed by its own factor (a duration tier);
- stress and softening: the span's pitch is raised or lowered by the plan's semitones, with soft edges;
- a contour: the end of the span's last word is bent to rise, fall or hold, only when the reading does not
  already do so, so a natural fall is kept as read;
- loudness: a gain envelope with short ramps.

Nothing runs when nothing would change. Every amount is bounded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

DUR_RANGE = (0.6, 1.8)       # a span is never stretched or compressed beyond this
PITCH_ST_RANGE = (-6.0, 6.0)
GAIN_DB_RANGE = (-20.0, 8.0)
CONTOUR_ST = {"rise": 3.0, "fall": -3.0, "hold": 0.0}
CONTOUR_OK = {"rise": lambda s: s >= 2.0, "fall": lambda s: s <= -2.0, "hold": lambda s: abs(s) <= 1.0}
CONTOUR_FROM = 0.35          # the end contour covers the last word from this fraction of it
EDGE_S = 0.03                # soft edges for pitch and loudness changes
PITCH_FLOOR, PITCH_CEILING = 60.0, 600.0


@dataclass
class Span:
    """Where one plan segment sits in the reading, in seconds: [start, end), and its last word."""
    start: float
    end: float
    last_word: tuple[float, float] | None = None


@dataclass
class Shape:
    """What to do to one span."""
    dur: float = 1.0           # duration factor (2.0 = twice as long)
    pitch_st: float = 0.0
    gain_db: float = 0.0
    contour: str = "none"      # rise | fall | hold | none


@dataclass
class Result:
    audio: np.ndarray
    starts: list[float]          # each span's new start, in seconds
    applied: list[str] = field(default_factory=list)  # what was changed, for the log and tests


def _clamp(x: float, lo_hi: tuple[float, float]) -> float:
    return min(max(float(x), lo_hi[0]), lo_hi[1])


def _ramp(t: np.ndarray, a: float, b: float, edge: float = EDGE_S) -> np.ndarray:
    """1 inside [a, b], 0 outside, with raised-cosine edges of `edge` seconds inside the span."""
    if b <= a:
        return np.zeros_like(t)
    e = min(edge, (b - a) / 2)
    up = np.clip((t - a) / e, 0, 1) if e > 0 else (t >= a).astype(float)
    down = np.clip((b - t) / e, 0, 1) if e > 0 else (t < b).astype(float)
    w = np.minimum(up, down)
    return 0.5 - 0.5 * np.cos(np.pi * w)


def end_slope_st(points: list[tuple[float, float]], a: float, b: float) -> float | None:
    """How the pitch moves over [a, b] in semitones: the median of its last third against its first third."""
    f = np.array([v for t, v in points if a <= t <= b and v > 0])
    if f.size < 4:
        return None
    k = max(1, f.size // 3)
    return float(12 * np.log2(np.median(f[-k:]) / np.median(f[:k])))


def time_map(dur_points: list[tuple[float, float]], total: float):
    """t -> resynthesized t for a duration tier (linear between points, constant outside), by integration."""
    if not dur_points:
        return lambda t: float(t)
    grid = np.linspace(0.0, total, max(2, int(total * 1000) + 1))
    ts, vs = zip(*sorted(dur_points))
    d = np.interp(grid, ts, vs)
    cum = np.concatenate([[0.0], np.cumsum((d[1:] + d[:-1]) / 2 * np.diff(grid))])
    return lambda t: float(np.interp(t, grid, cum))


def shape(audio: np.ndarray, sr: int, spans: list[Span], shapes: list[Shape]) -> Result:
    """The reading with each span shaped as asked. `spans` and `shapes` are parallel and in time order."""
    audio = np.asarray(audio, dtype=np.float32)
    total = len(audio) / sr
    applied: list[str] = []
    shapes = [Shape(_clamp(s.dur, DUR_RANGE), _clamp(s.pitch_st, PITCH_ST_RANGE), _clamp(s.gain_db, GAIN_DB_RANGE),
                    s.contour if s.contour in CONTOUR_ST else "none") for s in shapes]

    if any(abs(s.gain_db) > 0.05 for s in shapes):
        t = np.arange(len(audio)) / sr
        db = np.zeros_like(t)
        for sp, s in zip(spans, shapes):
            if abs(s.gain_db) > 0.05:
                db += s.gain_db * _ramp(t, sp.start, sp.end)
        audio = (audio * 10 ** (db / 20)).astype(np.float32)
        applied.append("gain")

    want_pitch = any(abs(s.pitch_st) > 0.05 or s.contour != "none" for s in shapes)
    dur_points: list[tuple[float, float]] = []
    if any(abs(s.dur - 1) > 0.02 for s in shapes):
        for sp, s in zip(spans, shapes):
            e = min(0.01, (sp.end - sp.start) / 4)
            dur_points += [(sp.start + e, s.dur), (sp.end - e, s.dur)]
    if not want_pitch and not dur_points:
        return Result(audio, [sp.start for sp in spans], applied)

    import parselmouth
    from parselmouth.praat import call

    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=sr)
    manip = call(snd, "To Manipulation", 0.01, PITCH_FLOOR, PITCH_CEILING)
    changed = False
    if want_pitch:
        tier = call(manip, "Extract pitch tier")
        n = int(call(tier, "Get number of points"))
        points = [(call(tier, "Get time from index", i), call(tier, "Get value at index", i)) for i in range(1, n + 1)]
        if points:
            pts_t = np.array([p[0] for p in points])
            st = np.zeros_like(pts_t)
            for sp, s in zip(spans, shapes):
                if abs(s.pitch_st) > 0.05:
                    st += s.pitch_st * _ramp(pts_t, sp.start, sp.end)
                if s.contour != "none" and sp.last_word:
                    a, b = sp.last_word
                    r0 = a + CONTOUR_FROM * (b - a)
                    slope = end_slope_st(points, r0, b)
                    if slope is None or CONTOUR_OK[s.contour](slope):
                        continue
                    x = np.clip((pts_t - r0) / max(b - r0, 1e-3), 0, 1) * ((pts_t >= r0) & (pts_t < sp.end + 0.05))
                    st += (CONTOUR_ST[s.contour] - slope) * x
                    applied.append(f"contour:{s.contour}")
            if np.any(np.abs(st) > 0.05):
                new = call("Create PitchTier", "shaped", 0.0, total)
                for (t, f), d in zip(points, st):
                    call(new, "Add point", t, f * 2 ** (d / 12))
                call([new, manip], "Replace pitch tier")
                changed = True
                if any(abs(s.pitch_st) > 0.05 for s in shapes):
                    applied.append("pitch")
    if dur_points:
        dt = call("Create DurationTier", "shaped", 0.0, total)
        for t, v in dur_points:
            call(dt, "Add point", t, v)
        call([dt, manip], "Replace duration tier")
        changed = True
        applied.append("pace")
    if not changed:
        return Result(audio, [sp.start for sp in spans], applied)
    out = call(manip, "Get resynthesis (overlap-add)")
    fwd = time_map(dur_points, total)
    return Result(np.asarray(out.values[0], dtype=np.float32), [fwd(sp.start) for sp in spans], applied)
