"""Improvise mode: unscripted speech on a topic, against a time goal.

There are no marks to compare against, so every measure here is checked
against a reference band from Settings (improv_*), which the user can edit.
Code measures; nothing here needs a model. Each row carries start/end times so
the report can play the moment back.

Groups:
  goal        spoken time vs the time goal
  pace        overall words per minute, and per 15-second window
  fillers     um / uh / "you know" ... (Whisper drops some: a lower bound)
  hesitation  long silences inside a sentence, restarts ("I I", "th-")
  hedges      softeners such as "I think", "maybe", "kind of"
  tone        statements that end rising (uptalk) or fading (trailing off)
  clarity     words the recognizer was unsure of: a proxy for mumbling, not a
              pronunciation score
  engagement  pitch range, loudness variation, pace variation, pauses between
              sentences, and the energy of the opening
"""

from __future__ import annotations

import re
from statistics import median, pstdev

import numpy as np

from marked import prosody
from marked.audio import Silence
from marked.config import Settings
from marked.conventions import find_fillers
from marked.marks import format_budget, normalize_word
from marked.stt.base import Word

TERMINAL_RE = re.compile(r"[.?!…]+[\"'”’)\]]*$")
QUESTION_RE = re.compile(r"\?[\"'”’)\]]*$")

# Fillers that are not hedges. "kind of" / "sort of" are counted as hedges instead.
IMPROV_FILLER_PAIRS = {("you", "know"), ("i", "mean")}

HEDGES: list[list[str]] = sorted([
    ["i", "think"], ["i", "guess"], ["i", "suppose"], ["i", "feel", "like"], ["i", "dont", "know"],
    ["i", "would", "say"], ["maybe"], ["perhaps"], ["probably"], ["possibly"], ["somewhat"],
    ["kind", "of"], ["sort", "of"], ["kinda"], ["sorta"], ["or", "something"], ["or", "whatever"],
    ["and", "stuff"], ["more", "or", "less"],
], key=len, reverse=True)
# "a kind of tree" is a noun phrase, not a hedge.
_NOUN_LEFT = {"a", "an", "the", "what", "this", "that", "every", "some", "any", "one", "which", "same",
              "different", "each", "no", "another", "these", "those", "favorite", "favourite", "my", "your"}
# Words people repeat on purpose.
_REPEAT_OK = {"very", "really", "so", "no", "yes", "bye", "ha", "had", "that", "ok", "okay", "hey", "go",
              "now", "well", "more", "many", "far", "long", "again", "over", "round", "around", "back"}

WINDOW_S = 15.0
OPENING_S = 10.0
PURPOSEFUL_MAX_S = 3.0


def _tok(w: Word) -> str:
    n = normalize_word(w.text)
    return n[0] if n else ""


def split_sentences(words: list[Word]) -> list[tuple[int, int]]:
    """[a, b) word ranges, split after words that carry terminal punctuation."""
    out: list[tuple[int, int]] = []
    a = 0
    for i, w in enumerate(words):
        if TERMINAL_RE.search(w.text.strip()):
            out.append((a, i + 1))
            a = i + 1
    if a < len(words):
        out.append((a, len(words)))
    return out


def find_hedges(words: list[Word]) -> list[dict]:
    norm: list[str] = []
    widx: list[int] = []
    for i, w in enumerate(words):
        for n in normalize_word(w.text):
            norm.append(n)
            widx.append(i)
    out: list[dict] = []
    k = 0
    while k < len(norm):
        hit = None
        for h in HEDGES:
            if norm[k:k + len(h)] == h:
                if h[0] in ("kind", "sort") and k > 0 and norm[k - 1] in _NOUN_LEFT:
                    continue
                hit = h
                break
        if hit is None:
            k += 1
            continue
        a, b = widx[k], widx[k + len(hit) - 1]
        out.append({"text": " ".join(w.text for w in words[a:b + 1]), "phrase": " ".join(hit),
                    "start": words[a].start, "end": words[b].end, "i": a, "j": b})
        k += len(hit)
    return out


def find_restarts(words: list[Word], skip: set[int]) -> list[dict]:
    out: list[dict] = []
    for i, w in enumerate(words):
        if i in skip:
            continue
        raw = w.text.strip()
        if len(raw) > 1 and raw.endswith("-"):
            out.append({"text": raw, "kind": "fragment", "start": w.start, "end": w.end, "i": i, "j": i})
            continue
        if i == 0 or (i - 1) in skip:
            continue
        a, b = _tok(words[i - 1]), _tok(w)
        if a and a == b and a not in _REPEAT_OK and not TERMINAL_RE.search(words[i - 1].text.strip()):
            out.append({"text": f"{words[i - 1].text} {w.text}", "kind": "repeat",
                        "start": words[i - 1].start, "end": w.end, "i": i - 1, "j": i})
    return out


def _at_most(value: float | None, target: float) -> str:
    if value is None:
        return "unmeasurable"
    if value <= target:
        return "met"
    if value <= max(target * 1.5, target + 0.5):
        return "near"
    return "diverged"


def _at_least(value: float | None, floor: float) -> str:
    if value is None:
        return "unmeasurable"
    if value >= floor:
        return "met"
    if value >= floor * 0.75:
        return "near"
    return "diverged"


def _band(value: float | None, lo: float, hi: float) -> str:
    if value is None:
        return "unmeasurable"
    if lo <= value <= hi:
        return "met"
    edge = lo if value < lo else hi
    return "near" if abs(value - edge) <= 0.1 * max(hi - lo, 10.0) else "diverged"


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def _prev_word(words: list[Word], t: float) -> int:
    """Index of the last word starting before t, or -1."""
    lo, hi = 0, len(words)
    while lo < hi:
        mid = (lo + hi) // 2
        if words[mid].start < t:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def analyze_improv(words: list[Word], silences: list[Silence], audio: np.ndarray | None, sr: int,
                   settings: Settings, topic: str = "", goal_s: float | None = None,
                   duration_s: float = 0.0) -> dict:
    st = settings
    n = len(words)
    track, pitch_backend = (prosody.f0_track_with_backend(audio, sr) if audio is not None and len(audio)
                            else (None, None))
    span = [words[0].start, words[-1].end] if n else [None, None]
    spoken_s = (span[1] - span[0]) if n else 0.0
    minutes = spoken_s / 60.0 if spoken_s > 0 else None

    # ---- time goal --------------------------------------------------------------
    goal: dict = {"goal_s": goal_s, "spoken_s": _r(spoken_s, 2), "delta_s": None, "tolerance_s": None,
                  "status": "no_goal" if not goal_s else "unmeasurable"}
    if goal_s and n:
        tol = max(goal_s * st.improv_goal_tolerance_pct / 100.0, 5.0)
        delta = spoken_s - goal_s
        goal.update({"delta_s": _r(delta, 1), "tolerance_s": _r(tol, 1),
                     "status": "met" if abs(delta) <= tol else ("over" if delta > 0 else "under")})

    # ---- fillers, hedges, restarts -------------------------------------------------
    hedges = find_hedges(words)
    hedge_idx = {k for h in hedges for k in range(h["i"], h["j"] + 1)}
    fillers = [f for f in find_fillers(words, IMPROV_FILLER_PAIRS)
               if not any(k in hedge_idx for k in range(f["i"], f["j"] + 1))]
    filler_idx = {k for f in fillers for k in range(f["i"], f["j"] + 1)}
    restarts = find_restarts(words, filler_idx)
    per100 = (lambda c: round(c / n * 100.0, 2) if n else None)

    # ---- pace ---------------------------------------------------------------------
    overall = n / minutes if minutes else None
    windows: list[dict] = []
    if n and spoken_s >= WINDOW_S:
        t = span[0]
        while t + WINDOW_S <= span[1] + 0.5:
            c = sum(1 for w in words if t <= w.start < t + WINDOW_S)
            windows.append({"start": _r(t, 2), "end": _r(t + WINDOW_S, 2), "wpm": round(c * 60.0 / WINDOW_S, 1)})
            t += WINDOW_S
    wpms = [w["wpm"] for w in windows]
    pace_var = (pstdev(wpms) / (sum(wpms) / len(wpms)) * 100.0) if len(wpms) >= 3 and sum(wpms) > 0 else None

    # ---- pauses: hesitations inside sentences, purposeful ones between them ---------
    hes_pauses: list[dict] = []
    purposeful: list[dict] = []
    if n:
        for s in silences:
            if not (span[0] < s.mid < span[1]) or s.duration < min(st.short_pause_s, st.improv_hesitation_pause_s):
                continue
            p = _prev_word(words, s.mid)
            if p < 0 or p + 1 >= n:
                continue
            row = {"start": _r(s.start, 3), "end": _r(s.end, 3), "duration_s": _r(s.duration, 2),
                   "after_i": p, "before": words[p].text, "after": words[p + 1].text}
            boundary = bool(TERMINAL_RE.search(words[p].text.strip()))
            if boundary and s.duration <= PURPOSEFUL_MAX_S:
                if s.duration >= st.short_pause_s:
                    purposeful.append(row)
            elif s.duration >= st.improv_hesitation_pause_s:
                row["kind"] = "between sentences" if boundary else ("after a filler" if p in filler_idx else "mid-sentence")
                hes_pauses.append(row)
    hes_count = len(hes_pauses) + len(restarts)
    hes_per_min = round(hes_count / minutes, 2) if minutes else None

    # ---- tone: uptalk and trailing off -------------------------------------------------
    sentences = split_sentences(words)
    uptalk: list[dict] = []
    trail: list[dict] = []
    up_measured = trail_measured = 0
    word_dbs = [prosody.word_db(audio, sr, w.start, w.end) if audio is not None and w.end - w.start >= 0.08 else None
                for w in words]
    for a, b in sentences:
        if b - a < 3:
            continue
        last = words[b - 1]
        is_q = bool(QUESTION_RE.search(last.text.strip()))
        if track is not None and not is_q:
            rise = prosody.final_rise_st(track, last.start, last.end)
            if rise is not None:
                up_measured += 1
                if rise >= st.improv_uptalk_st:
                    uptalk.append({"i": b - 1, "word": last.text, "start": last.start, "end": last.end,
                                   "rise_st": _r(rise), "sentence_start": words[a].start})
        if b - a >= 4 and word_dbs[b - 1] is not None:
            body = [d for d in word_dbs[a:b - 1] if d is not None]
            if len(body) >= 3:
                trail_measured += 1
                drop = median(body) - word_dbs[b - 1]
                if drop >= st.improv_trail_db:
                    trail.append({"i": b - 1, "word": last.text, "start": last.start, "end": last.end,
                                  "drop_db": _r(drop), "sentence_start": words[a].start})
    up_share = round(len(uptalk) / up_measured * 100.0, 1) if up_measured else None
    trail_share = round(len(trail) / trail_measured * 100.0, 1) if trail_measured else None

    # ---- clarity (proxy) --------------------------------------------------------------
    has_prob = any(w.prob < 0.999 for w in words)
    unclear = [{"i": i, "text": w.text, "prob": round(w.prob, 2), "start": w.start, "end": w.end}
               for i, w in enumerate(words) if has_prob and i not in filler_idx and w.prob < st.improv_clarity_prob]
    unclear_pct = round(len(unclear) / n * 100.0, 1) if n and has_prob else None

    # ---- engagement -------------------------------------------------------------------
    p_range = prosody.pitch_range_st(track, span[0], span[1]) if n and track is not None else None
    loud = [d for i, d in enumerate(word_dbs) if d is not None and i not in filler_idx]
    loud_var = pstdev(loud) if len(loud) >= 8 else None
    opening: dict = {"status": "unmeasurable", "db_delta": None, "f0_delta_pct": None, "range_st": None}
    if n and spoken_s >= 2 * OPENING_S:
        cut = span[0] + OPENING_S
        o_db = [d for i, d in enumerate(word_dbs) if d is not None and words[i].start < cut and i not in filler_idx]
        r_db = [d for i, d in enumerate(word_dbs) if d is not None and words[i].start >= cut and i not in filler_idx]
        if len(o_db) >= 3 and len(r_db) >= 3:
            dd = median(o_db) - median(r_db)
            opening["db_delta"] = _r(dd)
            opening["status"] = "met" if dd >= -1.0 else ("near" if dd >= -3.0 else "diverged")
        if track is not None:
            of, rf = prosody.median_f0(track, span[0], cut), prosody.median_f0(track, cut, span[1])
            if of and rf:
                opening["f0_delta_pct"] = _r((of - rf) / rf * 100.0)
            opening["range_st"] = _r(prosody.pitch_range_st(track, span[0], cut))
    purposeful_per_min = round(len(purposeful) / minutes, 2) if minutes else None

    rep = {
        "topic": topic,
        "goal_s": goal_s,
        "span": span,
        "spoken_s": _r(spoken_s, 2),
        "words": n,
        "goal": goal,
        "pace": {"overall_wpm": _r(overall), "band": [st.improv_wpm_min, st.improv_wpm_max],
                 "status": _band(overall, st.improv_wpm_min, st.improv_wpm_max), "windows": windows},
        "fillers": {"count": len(fillers), "per_100": per100(len(fillers)), "target_per_100": st.improv_filler_per_100,
                    "status": _at_most(per100(len(fillers)), st.improv_filler_per_100), "items": fillers,
                    "note": "Whisper often drops um/uh even when asked to keep them; this count is a lower bound."},
        "hesitation": {"pauses": hes_pauses, "restarts": restarts, "count": hes_count, "per_min": hes_per_min,
                       "threshold_s": st.improv_hesitation_pause_s, "target_per_min": st.improv_hesitations_per_min,
                       "status": _at_most(hes_per_min, st.improv_hesitations_per_min)},
        "hedges": {"count": len(hedges), "per_100": per100(len(hedges)), "target_per_100": st.improv_hedge_per_100,
                   "status": _at_most(per100(len(hedges)), st.improv_hedge_per_100), "items": hedges},
        "tone": {"pitch_available": track is not None,
                 "uptalk": uptalk, "uptalk_measured": up_measured, "uptalk_share_pct": up_share,
                 "uptalk_threshold_st": st.improv_uptalk_st,
                 "uptalk_status": _at_most(up_share, st.improv_tone_share_pct),
                 "trail_off": trail, "trail_measured": trail_measured, "trail_share_pct": trail_share,
                 "trail_threshold_db": st.improv_trail_db,
                 "trail_status": _at_most(trail_share, st.improv_tone_share_pct),
                 "share_target_pct": st.improv_tone_share_pct},
        "clarity": {"available": has_prob, "unclear": unclear, "unclear_pct": unclear_pct,
                    "prob_threshold": st.improv_clarity_prob, "target_pct": st.improv_unclear_pct,
                    "status": _at_most(unclear_pct, st.improv_unclear_pct) if has_prob else "unmeasurable",
                    "note": ("A proxy, not a pronunciation score: words the recognizer was unsure of, which often "
                             "means mumbled, swallowed or rushed." if has_prob else
                             "This transcriber does not report per-word confidence.")},
        "engagement": {
            "pitch_backend": pitch_backend,
            "pitch_range_st": _r(p_range), "pitch_floor_st": st.improv_pitch_range_st,
            "pitch_status": _at_least(p_range, st.improv_pitch_range_st),
            "loudness_var_db": _r(loud_var), "loudness_target_db": st.improv_loudness_var_db,
            "loudness_status": _at_least(loud_var, st.improv_loudness_var_db),
            "pace_var_pct": _r(pace_var), "pace_var_target_pct": st.improv_pace_var_pct,
            "pace_var_status": _at_least(pace_var, st.improv_pace_var_pct),
            "purposeful_pauses": purposeful, "purposeful_per_min": purposeful_per_min,
            "opening": opening,
            "contour": prosody.contour(track, span[0], span[1]) if n and track is not None else [],
        },
        "sentences": [[a, b] for a, b in sentences],
    }
    rep["summary"] = improv_summary(rep)
    rep["drills"] = drills(rep, st)
    return rep


def improv_summary(r: dict) -> list[str]:
    out: list[str] = []
    if not r["words"]:
        return ["No speech was recognized in this take."]
    g = r["goal"]
    if g["goal_s"]:
        s = f"You spoke for {format_budget(r['spoken_s'])} against a {format_budget(g['goal_s'])} goal"
        if g["status"] == "met":
            s += " (within your tolerance)."
        else:
            s += f" ({abs(g['delta_s']):.0f} s {'over' if g['status'] == 'over' else 'under'})."
        out.append(s)
    p = r["pace"]
    if p["overall_wpm"]:
        out.append(f"Pace {p['overall_wpm']:.0f} words per minute against your {p['band'][0]:.0f}–{p['band'][1]:.0f} band.")
    f, h = r["fillers"], r["hedges"]
    out.append(f"{f['count']} filler{'s' if f['count'] != 1 else ''} ({f['per_100']} per 100 words) and "
               f"{h['count']} hedge{'s' if h['count'] != 1 else ''}"
               + (f" such as “{h['items'][0]['phrase']}”." if h["items"] else "."))
    t = r["tone"]
    if t["uptalk_measured"]:
        out.append(f"{len(t['uptalk'])} of {t['uptalk_measured']} statements ended with a rising pitch.")
    e = r["engagement"]
    if e["pitch_range_st"] is not None:
        out.append(f"Pitch range {e['pitch_range_st']} semitones (your floor is {e['pitch_floor_st']}).")
    return out


def drills(r: dict, st: Settings) -> list[dict]:
    """Up to three code-written practice suggestions for the measures furthest from their band.

    Each cites the measured number. Written by code, not a model, so they are
    available without a key.
    """
    if not r["words"]:
        return []
    f, h, hs, t, e, p, c, g = (r["fillers"], r["hedges"], r["hesitation"], r["tone"], r["engagement"], r["pace"],
                               r["clarity"], r["goal"])
    cands: list[tuple[str, str, str]] = []  # (status, focus, text)

    def ex(items: list[dict], key: str = "text") -> str:
        return f" (e.g. “{items[0][key]}”)" if items else ""

    cands.append((f["status"], "fillers",
                  f"{f['count']} fillers, {f['per_100']} per 100 words against your {f['target_per_100']}{ex(f['items'])}. "
                  "When you feel one coming, close your mouth and pause instead: a silent beat sounds deliberate, a filler sounds unsure."))
    cands.append((h["status"], "confidence",
                  f"{h['count']} hedges, {h['per_100']} per 100 words{ex(h['items'], 'phrase')}. "
                  "Say the claim without the softener (“Trees cool a street by several degrees”, not “I think trees kind of cool…”). "
                  "Keep a hedge only where you are genuinely unsure."))
    if t["uptalk_measured"]:
        cands.append((t["uptalk_status"], "confidence",
                      f"{len(t['uptalk'])} of {t['uptalk_measured']} statements ended rising by {t['uptalk_threshold_st']}+ semitones{ex(t['uptalk'], 'word')}. "
                      "Re-say those sentences and let the pitch drop on the last word, like setting down a full stop."))
    cands.append((hs["status"], "hesitation",
                  f"{len(hs['pauses'])} pauses of {hs['threshold_s']} s or more inside or between sentences and {len(hs['restarts'])} restarts "
                  f"({hs['per_min']} per minute). Before starting a sentence, know where it ends; pause between ideas, not in the middle of one."))
    cands.append((e["pitch_status"], "engagement",
                  f"Pitch range {e['pitch_range_st']} semitones against your floor of {e['pitch_floor_st']}. "
                  "Pick the key word of each sentence and say it higher and slower, as if revealing a twist; flat pitch is what makes a talk sound read."))
    if p["status"] in ("near", "diverged") and p["overall_wpm"]:
        fast = p["overall_wpm"] > p["band"][1]
        cands.append((p["status"], "pace",
                      f"{p['overall_wpm']:.0f} words per minute, {'above' if fast else 'below'} your {p['band'][0]:.0f}–{p['band'][1]:.0f} band. "
                      + ("Slow down on the sentences that carry your point; let the background go quicker." if fast else
                         "Tighten the connecting phrases and keep moving; save slow delivery for the line you want remembered.")))
    op = e["opening"]
    if op["db_delta"] is not None:
        cands.append((op["status"], "engagement",
                      f"Your first {OPENING_S:.0f} s were {abs(op['db_delta'])} dB {'quieter' if op['db_delta'] < 0 else 'louder'} than the rest. "
                      "Open with your strongest line (a question, a surprising fact, or “Here’s the thing about…”) at full voice; the first seconds decide whether people keep listening."))
    if t["trail_measured"]:
        cands.append((t["trail_status"], "confidence",
                      f"{len(t['trail_off'])} of {t['trail_measured']} sentences faded on the last word by {t['trail_threshold_db']}+ dB{ex(t['trail_off'], 'word')}. "
                      "Aim the last word at the back of the room; the end of a sentence usually carries its point."))
    if e["purposeful_per_min"] is not None and r["spoken_s"] >= 30:
        cands.append(("near" if e["purposeful_per_min"] < 1 else "met", "engagement",
                      f"{len(e['purposeful_pauses'])} deliberate pauses of {st.short_pause_s}+ s between sentences ({e['purposeful_per_min']} per minute). "
                      "After your most surprising sentence, stop for a full second before explaining; the silence builds anticipation."))
    cands.append((e["loudness_status"], "engagement",
                  f"Loudness varied by {e['loudness_var_db']} dB across words against your {e['loudness_target_db']}. "
                  "Drop your voice for the setup and lift it for the payoff."))
    cands.append((e["pace_var_status"], "engagement",
                  f"Pace varied by {e['pace_var_pct']} % across 15-second stretches against your {e['pace_var_target_pct']} %. "
                  "Speed through background, then slow right down for the line that matters: contrast is what creates suspense."))
    if c["available"]:
        cands.append((c["status"], "clarity",
                      f"{len(c['unclear'])} words ({c['unclear_pct']} %) were hard for the recognizer to catch{ex(c['unclear'])}. "
                      "Open your mouth more on stressed syllables and finish the consonants at word ends."))
    if g["status"] in ("over", "under"):
        cands.append(("diverged" if abs(g["delta_s"]) > 2 * g["tolerance_s"] else "near", "time",
                      f"{abs(g['delta_s']):.0f} s {g['status']} your {format_budget(g['goal_s'])} goal. "
                      + ("Decide your closing line before you start so you can land it on time." if g["status"] == "over" else
                         "Have one extra example ready; when you run short, tell it as a short story.")))
    out: list[dict] = []
    for want in ("diverged", "near"):
        for status, focus, text in cands:
            if status == want and len(out) < 3:
                out.append({"focus": focus, "status": status, "text": text})
    return out
