"""Turn a parsed script, a word-timed transcript and silence regions into the
analysis JSON. Every number here is derived from timestamps that are also in
the JSON, so the UI can always show where a figure came from.

Wording rule for anything user-facing: "met your mark", "diverged from your
mark", "faster/slower than your median". Never a grade.
"""

from __future__ import annotations

import math
from statistics import median

from take_two.align import Alignment, TokenAlignment, adlib_spans, align
from take_two.audio import Silence, longest_silence_between
from take_two.clarity import clarity_report
from take_two.config import Settings
from take_two.marks import Script, Token, format_budget, normalize_word
from take_two.stt.base import Transcript


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


def _fmt_delta(seconds: float) -> str:
    sign = "over" if seconds > 0 else "under"
    return f"{format_budget(abs(seconds))} {sign}"


Anchors = dict[int, tuple[TokenAlignment, TokenAlignment]]


def _nearest_aligned_before(al: Alignment, line: int, word_index: int, ok_lines: set[int],
                            max_hops: int | None = None, anchors: Anchors | None = None) -> TokenAlignment | None:
    """Nearest aligned token at or before (line, word_index), only from lines that were found."""
    toks = al.line_tokens(line)
    if line in ok_lines:
        for t in reversed(toks[:word_index]):
            if t.aligned:
                return t
    hops = 0
    for ln in range(line - 1, -1, -1):
        hops += 1
        if max_hops is not None and hops > max_hops:
            break
        if anchors and ln in anchors:
            return anchors[ln][1]
        if ln not in ok_lines:
            continue
        t = al.last_aligned(ln)
        if t:
            return t
    return None


def _nearest_aligned_at_or_after(al: Alignment, line: int, word_index: int, n_lines: int, ok_lines: set[int],
                                 max_hops: int | None = None, anchors: Anchors | None = None) -> TokenAlignment | None:
    toks = al.line_tokens(line)
    if line in ok_lines:
        for t in toks[word_index:]:
            if t.aligned:
                return t
    hops = 0
    for ln in range(line + 1, n_lines):
        hops += 1
        if max_hops is not None and hops > max_hops:
            break
        if anchors and ln in anchors:
            return anchors[ln][0]
        if ln not in ok_lines:
            continue
        t = al.first_aligned(ln)
        if t:
            return t
    return None


_FILLERS = {"um", "uh", "umm", "uhh", "erm", "er", "hmm", "mm"}
# Common words that say nothing about which line was meant; they do not count as the line's own words.
_STOPWORDS = {"this", "that", "with", "from", "have", "were", "they", "them", "then", "than", "there", "their",
              "these", "those", "which", "what", "when", "where", "will", "would", "could", "should", "been",
              "into", "about", "also", "some", "more", "very", "just", "here", "only", "over", "such", "each",
              "like", "much", "most", "other", "because", "really", "going", "know", "think"}


def _paraphrased(script: Script, al: Alignment, transcript: Transcript, line_rows: list[dict],
                 settings: Settings, silences: list[Silence]) -> dict[int, tuple[int, int]]:
    """Lines said in other words: {line: (first, last transcript word)}.

    A line qualifies when it was not found verbatim, both neighbouring lines were found,
    the speech between them holds enough words (at least 2, and paraphrase_min_words_pct
    of the line), and at least one of the line's own content words was heard there. That
    last condition keeps an unrelated aside in place of a skipped line "not found". The
    span stops at a pause before the first and after the last of those words, so a
    neighbour's stray last word (and the pause after it) is not pulled into it. Two unfound
    lines in a row stay "not found": their words cannot be split honestly.
    """
    words = transcript.words
    brk = settings.short_pause_s * settings.pause_near_ratio  # a silence this long ends a stretch of speech
    out: dict[int, tuple[int, int]] = {}
    for i in range(1, len(script.lines) - 1):
        if line_rows[i]["status"] != "not_found" or not script.lines[i].tokens:
            continue
        if line_rows[i - 1]["status"] != "ok" or line_rows[i + 1]["status"] != "ok":
            continue
        before, after = al.last_aligned(i - 1), al.first_aligned(i + 1)
        if before is None or after is None:
            continue
        lo, hi = max(before.transcript_indexes), min(after.transcript_indexes)
        own_words = {n for t in script.lines[i].tokens for n in t.norm
                     if len(n) >= settings.fuzzy_min_chars and n not in _STOPWORDS}
        span = [w for w in range(lo + 1, hi)
                if (normalize_word(words[w].text) or [""])[0] not in _FILLERS]
        own_at = [k for k, w in enumerate(span) if own_words & set(normalize_word(words[w].text))]
        if not own_at:
            continue
        first, last = own_at[0], own_at[-1]
        while first > 0 and longest_silence_between(silences, words[span[first - 1]].end, words[span[first]].start) < brk:
            first -= 1
        while last < len(span) - 1 and longest_silence_between(silences, words[span[last]].end, words[span[last + 1]].start) < brk:
            last += 1
        span = span[first:last + 1]
        need = max(2, math.ceil(settings.paraphrase_min_words_pct / 100.0 * len(script.lines[i].tokens)))
        if len(span) >= need:
            out[i] = (span[0], span[-1])
    return out


def _about_words(raw: float) -> int:
    """A word count stated as an estimate: exact under 10, else to the nearest 5."""
    return int(round(raw)) if raw < 10 else int(5 * round(raw / 5))


def cut_to_fit(subject: str, over_s: float, median_wpm: float | None, budget_s: float | None = None) -> dict:
    """An overrun converted into words at the speaker's own median rate. Plain arithmetic."""
    out: dict = {"over_s": _r(over_s, 1), "words": None, "wpm": _r(median_wpm, 1)}
    ran = f"{subject} ran {format_budget(over_s)} over" + (f" its {format_budget(budget_s)} budget" if budget_s else "")
    if median_wpm:
        out["words"] = _about_words(over_s * median_wpm / 60.0)
        out["text"] = f"{ran}: about {out['words']} words at your {median_wpm:.0f} wpm."
    else:
        out["text"] = f"{ran}; there is no median in this take, so no word estimate."
    return out


def total_fit(section_rows: list[dict], spoken_start: float | None, spoken_end: float | None,
              median_wpm: float | None, settings: Settings) -> dict:
    """The whole talk against the sum of its budgets: only when every section with lines has a budget and was found."""
    with_lines = [s for s in section_rows if s["line_end"] > s["line_start"]]
    missing = [s["name"] for s in with_lines if s["budget_s"] is None]
    if not with_lines or missing:
        return {"status": "not_measurable", "reason": f"Section {missing[0]} has no budget." if missing else "No sections."}
    lost = [s["name"] for s in with_lines if s["status"] == "not_found"]
    if lost or spoken_start is None or spoken_end is None:
        return {"status": "not_measurable", "reason": f"Section {lost[0]} was not found in this take." if lost else "Nothing was found."}
    budget = sum(s["budget_s"] for s in with_lines)
    spoken = spoken_end - spoken_start
    delta = spoken - budget
    tol = max(budget * settings.section_tolerance_pct / 100.0, 3.0)
    out = {"budget_s": budget, "spoken_s": _r(spoken, 2), "delta_s": _r(delta, 2), "tolerance_s": _r(tol, 1),
           "status": "met" if abs(delta) <= tol else ("over" if delta > 0 else "under")}
    if out["status"] == "over":
        out["cut"] = cut_to_fit("The whole talk", delta, median_wpm, budget)
    return out


def analyze(script: Script, transcript: Transcript, silences: list[Silence], settings: Settings,
            audio_duration: float, baseline_override: dict | None = None, dismissed: frozenset[str] = frozenset()) -> dict:
    """baseline_override {"median_wpm", "source"}: judge rates against another take's median (a drill has none of its own).
    dismissed: words the speaker marked "I said it fine", left out of the clarity list."""
    al = align(script, transcript, settings)
    n_lines = len(script.lines)

    # ---- lines -------------------------------------------------------------
    line_rows: list[dict] = []
    for ln, lt in zip(script.lines, al.lines):
        ok = lt.total > 0 and lt.coverage >= settings.line_min_coverage and lt.matched >= 1
        line_rows.append({
            "index": ln.index, "section": ln.section, "text": ln.text, "is_key": ln.is_key,
            "word_count": lt.total, "matched_words": lt.matched, "span_words": lt.span_words,
            "coverage": _r(lt.coverage, 3),
            "start": _r(lt.start, 3) if ok else None, "end": _r(lt.end, 3) if ok else None,
            "duration_s": _r(lt.duration, 3) if ok else None,
            "wpm": _r(lt.wpm(), 1) if ok else None,
            "status": "ok" if ok else "not_found",
            "words": [{"index": t.token.index, "text": t.token.text, "start": _r(t.start, 3), "end": _r(t.end, 3),
                       **({"heard": t.heard} if t.fuzzy else {})}
                      for t in al.line_tokens(ln.index)],
        })

    ok_lines = {r["index"] for r in line_rows if r["status"] == "ok"}

    # ---- paraphrased lines: timed from the words between their neighbours, never rate-checked ----
    words = transcript.words
    anchors: Anchors = {}
    claimed: set[int] = set()
    for i, (w0, w1) in _paraphrased(script, al, transcript, line_rows, settings, silences).items():
        start, end = words[w0].start, words[w1].end
        line_rows[i].update({"status": "paraphrased", "start": _r(start, 3), "end": _r(end, 3),
                             "duration_s": _r(end - start, 3), "wpm": None,
                             "said": {"text": " ".join(w.text for w in words[w0:w1 + 1]), "start": _r(start, 3),
                                      "end": _r(end, 3), "words": [w0, w1]}})
        n_tok = len(script.lines[i].tokens)
        anchors[i] = (TokenAlignment(Token(line=i, index=0, text=words[w0].text, norm=[]), words[w0].start, words[w0].end, [w0]),
                      TokenAlignment(Token(line=i, index=n_tok - 1, text=words[w1].text, norm=[]), words[w1].start, words[w1].end, [w1]))
        claimed.update(range(w0, w1 + 1))
    timed = {"ok", "paraphrased"}

    # ---- what was said vs. the script ----------------------------------------
    spans = adlib_spans(al, transcript, ok_lines, frozenset(claimed))
    for ln, row in zip(script.lines, line_rows):
        if row["status"] != "ok":
            row["adlibs"], row["words_differ"] = [], None
            continue
        for w, t in zip(row["words"], ln.tokens):
            w["dropped"] = w["start"] is None and bool(t.norm)
        row["adlibs"] = spans.get(ln.index, [])
        row["words_differ"] = sum(1 for w in row["words"] if w["dropped"]) + sum(len(a["words"]) for a in row["adlibs"])

    # ---- baseline ---------------------------------------------------------
    base_wpms = [r["wpm"] for r, ln in zip(line_rows, script.lines)
                 if r["status"] == "ok" and r["wpm"] and ln.word_count >= settings.baseline_min_words]
    median_wpm = median(base_wpms) if base_wpms else None
    if baseline_override is not None:
        median_wpm = baseline_override.get("median_wpm")
    spoken_start = min((r["start"] for r in line_rows if r["start"] is not None), default=None)
    spoken_end = max((r["end"] for r in line_rows if r["end"] is not None), default=None)
    inner_pauses = [s.duration for s in silences
                    if spoken_start is not None and spoken_end is not None and spoken_start < s.mid < spoken_end]
    baseline = {
        "median_wpm": _r(median_wpm, 1),
        "lines_used": len(base_wpms),
        "min_words_per_line": settings.baseline_min_words,
        "median_pause_s": _r(median(inner_pauses), 2) if inner_pauses else None,
        "pauses_counted": len(inner_pauses),
        "median_source": baseline_override.get("source") if baseline_override else "this take",
    }

    # ---- sections ---------------------------------------------------------
    section_rows: list[dict] = []
    for sec in script.sections:
        rows = [line_rows[i] for i in range(sec.line_start, sec.line_end) if line_rows[i]["status"] in timed]
        start = min((r["start"] for r in rows), default=None)
        end = max((r["end"] for r in rows), default=None)
        dur = (end - start) if start is not None and end is not None else None
        # A section with no lines (a slide without notes) has nothing to time; that is not "not found".
        status = "no_lines" if sec.line_end <= sec.line_start else "not_found"
        delta = None
        if dur is not None:
            if sec.budget_s is None:
                status = "no_budget"
            else:
                delta = dur - sec.budget_s
                tol = max(sec.budget_s * settings.section_tolerance_pct / 100.0, 3.0)
                status = "met" if abs(delta) <= tol else ("over" if delta > 0 else "under")
        cut = None
        if status == "over" and delta is not None:
            cut = cut_to_fit(sec.name or "Untitled", delta, median_wpm)
        section_rows.append({
            "index": sec.index, "name": sec.name or "Untitled", "budget_s": sec.budget_s, "cut": cut,
            "budget_label": format_budget(sec.budget_s), "start": _r(start, 3), "end": _r(end, 3),
            "duration_s": _r(dur, 2), "duration_label": format_budget(dur) if dur is not None else "",
            "delta_s": _r(delta, 2), "delta_label": _fmt_delta(delta) if delta is not None else "",
            "status": status, "line_start": sec.line_start, "line_end": sec.line_end,
            "words": sum(script.lines[i].word_count for i in range(sec.line_start, sec.line_end)),
        })

    fit_total = total_fit(section_rows, spoken_start, spoken_end, median_wpm, settings)

    # ---- [KEY] lines -------------------------------------------------------
    for ln, row in zip(script.lines, line_rows):
        if not ln.is_key:
            continue
        key: dict = {"status": "not_found", "rate_status": "not_found", "pause_status": "not_found",
                     "met_rate": None, "met_pause": None,
                     "wpm": row["wpm"], "median_wpm": _r(median_wpm, 1), "wpm_vs_median_pct": None,
                     "pause_after_s": None, "pause_after_target_s": settings.key_pause_after_s,
                     "slower_target_pct": settings.key_slower_pct, "pause_window": None}
        paraphrased = row["status"] == "paraphrased"
        if (row["status"] == "ok" and row["wpm"]) or paraphrased:
            if median_wpm and not paraphrased:
                pct = (row["wpm"] - median_wpm) / median_wpm * 100.0
                key["wpm_vs_median_pct"] = _r(pct, 1)
                key["met_rate"] = pct <= -settings.key_slower_pct
            last = anchors[ln.index][1] if paraphrased else al.last_aligned(ln.index)
            nxt = _nearest_aligned_at_or_after(al, ln.index, len(ln.tokens), n_lines, ok_lines, anchors=anchors)
            if last is not None:
                t0 = last.start or 0.0
                t1 = nxt.end if nxt is not None and nxt.end is not None else audio_duration
                pause = longest_silence_between(silences, t0, t1)
                key["pause_after_s"] = _r(pause, 2)
                key["pause_window"] = [_r(last.end, 3), _r(nxt.start if nxt else audio_duration, 3)]
                key["met_pause"] = pause >= settings.key_pause_after_s
            pct = key["wpm_vs_median_pct"]
            if paraphrased:
                key["paraphrased"] = True
                key["rate_status"] = "unmeasurable"
                key["rate_note"] = ("This line was paraphrased: its words do not match the script closely enough "
                                    "for a words-per-minute rate, so it is not compared with your median.")
            elif pct is None:
                key["rate_status"] = "unknown"
                if baseline_override is not None:
                    key["rate_note"] = "The full take this drill came from has no median, so the rate is not compared."
            elif pct <= -settings.key_slower_pct:
                key["rate_status"] = "met"
            elif pct <= 0:
                key["rate_status"] = "near"
            else:
                key["rate_status"] = "diverged"
            p = key["pause_after_s"]
            if p is None:
                key["pause_status"] = "unknown"
            elif p >= settings.key_pause_after_s:
                key["pause_status"] = "met"
            elif p >= settings.key_pause_after_s * settings.pause_near_ratio:
                key["pause_status"] = "short"
            else:
                key["pause_status"] = "missing"
            if paraphrased:
                # Never "close": the rate was not measured, so only a missing pause can decide anything.
                key["status"] = "diverged" if key["pause_status"] == "missing" else "unmeasurable"
            elif key["rate_status"] == "met" and key["pause_status"] == "met":
                key["status"] = "met"
            elif key["rate_status"] == "diverged" or key["pause_status"] == "missing":
                key["status"] = "diverged"
            else:
                key["status"] = "near"
        row["key"] = key

    # ---- pause marks -------------------------------------------------------
    pause_rows: list[dict] = []
    for ln in script.lines:
        for pm in ln.pauses:
            target = settings.long_pause_s if pm.kind == "//" else settings.short_pause_s
            at_end = pm.word_index >= len(ln.tokens)
            if ln.index not in ok_lines and not (ln.index in anchors and at_end):
                pause_rows.append({"line": ln.index, "word_index": pm.word_index, "kind": pm.kind, "target_s": target,
                                   "measured_s": None, "whisper_gap_s": None, "at_time": None, "window": None,
                                   "status": "unmeasurable", "before": None, "after": None,
                                   "note": "line was paraphrased, so this mark cannot be placed among its words"
                                   if ln.index in anchors else "line not found in this take"})
                continue
            if ln.index in anchors:  # a mark at the end of a paraphrased line: from its last word to the next line
                prev = anchors[ln.index][1]
                nxt = _nearest_aligned_at_or_after(al, ln.index, pm.word_index, n_lines, ok_lines, max_hops=1, anchors=anchors)
            else:
                prev = _nearest_aligned_before(al, ln.index, pm.word_index, ok_lines, max_hops=1, anchors=anchors)
                nxt = _nearest_aligned_at_or_after(al, ln.index, pm.word_index, n_lines, ok_lines, max_hops=1, anchors=anchors)
            row = {"line": ln.index, "word_index": pm.word_index, "kind": pm.kind, "target_s": target,
                   "measured_s": None, "whisper_gap_s": None, "at_time": None, "window": None,
                   "status": "unmeasurable",
                   "before": prev.token.text if prev else None, "after": nxt.token.text if nxt else None}
            if prev is not None and (nxt is not None or pm.word_index >= len(ln.tokens)):
                t0 = prev.start or 0.0
                t1 = nxt.end if nxt is not None and nxt.end is not None else audio_duration
                measured = longest_silence_between(silences, t0, t1)
                gap = (nxt.start - prev.end) if nxt is not None and nxt.start is not None and prev.end is not None \
                    else audio_duration - (prev.end or 0.0)
                row.update({"measured_s": _r(measured, 2), "whisper_gap_s": _r(max(gap, 0.0), 2),
                            "at_time": _r(prev.end, 3), "window": [_r(prev.end, 3), _r(t1 if nxt is None else nxt.start, 3)]})
                if measured >= target:
                    row["status"] = "met"
                elif measured >= target * settings.pause_near_ratio:
                    row["status"] = "short"
                else:
                    row["status"] = "missing"
            pause_rows.append(row)

    # ---- summary -----------------------------------------------------------
    summary: list[str] = []
    keys = [r["key"] for r in line_rows if r.get("key")]
    found_keys = [k for k in keys if k["status"] != "not_found" and not k.get("paraphrased")]
    missing_keys = sum(1 for k in keys if k["status"] == "not_found")
    if found_keys:
        met = sum(1 for k in found_keys if k["status"] == "met")
        s = f"{met} of {len(found_keys)} key lines met your marks."
        if missing_keys:
            s += f" {missing_keys} not found in this take."
        summary.append(s)
    elif missing_keys:
        summary.append(f"{missing_keys} key line{'s' if missing_keys != 1 else ''} not found in this take.")
    if pause_rows:
        measurable = [p for p in pause_rows if p["status"] != "unmeasurable"]
        met = sum(1 for p in measurable if p["status"] == "met")
        short = sum(1 for p in measurable if p["status"] == "short")
        missing = sum(1 for p in measurable if p["status"] == "missing")
        parts = [f"{met} of {len(measurable)} pause marks met"]
        if short:
            parts.append(f"{short} short")
        if missing:
            parts.append(f"{missing} missing")
        summary.append(", ".join(parts) + ".")
    for sr in section_rows:
        if sr["status"] in ("over", "under"):
            summary.append(f"{sr['name']} ran {sr['delta_label']} budget.")
    para = [r for r in line_rows if r["status"] == "paraphrased"]
    if para:
        summary.append(f"{len(para)} line{'s' if len(para) != 1 else ''} paraphrased: timed, not rate-checked.")
    not_found = [r for r in line_rows if r["status"] == "not_found"]
    if not_found:
        summary.append(f"{len(not_found)} line{'s' if len(not_found) != 1 else ''} not found in this take.")

    return {
        "settings": settings.model_dump(),
        "duration_s": _r(audio_duration, 2),
        "baseline": baseline,
        "sections": section_rows,
        "fit_total": fit_total,
        "lines": line_rows,
        "pauses": pause_rows,
        "defines": [],
        "summary": summary,
        "clarity": clarity_report(script, al, transcript, ok_lines, settings, dismissed),
        "unmatched_transcript_words": len(transcript.words) - len(al.matched_transcript),
    }
