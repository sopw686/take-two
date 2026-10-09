"""A take's report as one self-contained HTML file, to send to an advisor or keep.

Inline CSS, the 16 kHz WAV embedded as a data URI, every tooltip's text printed under
its line (there is no hover on paper or in an email preview), and a few lines of inline
script so clicking a line plays it. Nothing is fetched when it opens, so it works
offline. The status glyphs are the app's.
"""

from __future__ import annotations

import base64
import html

from take_two import takes
from take_two.marks import format_budget

GLYPH = {"met": "✓", "near": "~", "diverged": "✗", "unknown": "–"}
TONE = {"met": "met", "defined": "met", "ok": "met", "near": "near", "short": "near", "under": "near",
        "diverged": "diverged", "missing": "diverged", "over": "diverged", "undefined": "diverged", "never_spoken": "diverged"}
WORD = {"met": "met your mark", "near": "close to your mark", "diverged": "diverged from your mark", "short": "shorter than your mark",
        "missing": "no pause found", "unmeasurable": "not measured", "not_found": "not found", "over": "over budget",
        "under": "under budget", "no_budget": "no budget set", "unknown": "not measured", "defined": "defined",
        "undefined": "not defined before first use", "never_spoken": "never spoken", "no_lines": "no script lines"}


def _e(x: object) -> str:
    return html.escape(str(x), quote=True)


def _t(s: float | None) -> str:
    if s is None:
        return "–"
    return format_budget(s) if s >= 60 else f"{s:.1f} s"


def _n(x: float | None, places: int) -> str:
    return "–" if x is None else f"{x:.{places}f}"


def _chip(status: str, label: str) -> str:
    tone = TONE.get(status, "unknown")
    return f'<span class="mark st-{tone}"><span aria-hidden="true">{GLYPH[tone]}</span> {_e(label)}</span>'


def _key_tip(k: dict) -> str:
    if k["status"] == "not_found":
        return "Not found in this take, so not measured."
    pct = k.get("wpm_vs_median_pct")
    rate = (f"{abs(pct):.0f}% {'slower' if pct < 0 else 'faster'} than the median ({k.get('median_wpm') or 0:.0f} wpm)"
            if pct is not None else (k.get("rate_note") or "rate not compared"))
    p = k.get("pause_after_s")
    return (f"Rate: {rate}; the mark asks for at least {k['slower_target_pct']:.0f}% slower ({WORD.get(k['rate_status'], k['rate_status'])}). "
            f"Pause after: {('%.2f s' % p) if p is not None else '–'} against {k['pause_after_target_s']} s "
            f"({WORD.get(k['pause_status'], k['pause_status'])}).")


def _emphasis_tip(e: dict) -> str:
    parts = []
    if e.get("delta_db") is not None:
        parts.append(f"{e['delta_db']:+.1f} dB against the rest of its line")
    if e.get("word_f0") and e.get("line_median_f0"):
        parts.append(f"pitch {e['word_f0']:.0f} Hz against the line's {e['line_median_f0']:.0f} Hz")
    return (", ".join(parts) or "not measured") + f" ({WORD.get(e.get('status', 'unknown'), e.get('status', 'unknown'))})."


CSS = """
:root { --ink:#1f1d1a; --muted:#6f6a62; --rule:#e4ded4; --paper:#fffdf9; --bg:#faf8f4; --met:#2e7d5b; --met-bg:#e3f2ea;
  --near:#a86b12; --near-bg:#fbeedc; --div:#a8323e; --div-bg:#f8e3e5; --unk:#7a756d; --unk-bg:#eeeae3; --accent:#3b4f8a; }
body { margin: 0 auto; max-width: 860px; padding: 24px; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; }
h1, h2, h3 { font-family: Georgia, serif; font-weight: 500; }
.muted { color: var(--muted); } .small { font-size: 13px; }
.card { background: var(--paper); border: 1px solid var(--rule); border-radius: 12px; padding: 14px 18px; margin: 0 0 14px; }
.mark { display: inline-block; font: 12px/1.4 ui-monospace, Consolas, monospace; padding: 1px 7px; border-radius: 999px; margin-right: 6px; }
.st-met { background: var(--met-bg); color: var(--met); } .st-near { background: var(--near-bg); color: var(--near); }
.st-diverged { background: var(--div-bg); color: var(--div); } .st-unknown { background: var(--unk-bg); color: var(--unk); }
.line { padding: 6px 10px; margin: 0 -10px; border-radius: 8px; font: 18px/1.7 Georgia, serif; }
.line[data-start] { cursor: pointer; } .line[data-start]:hover { background: #f3efe7; } .line.nf { opacity: 0.6; }
.tips { font: 13px/1.45 -apple-system, "Segoe UI", sans-serif; color: var(--muted); margin: 2px 0 0; padding-left: 18px; }
.section { color: var(--accent); margin: 18px 0 4px; }
.transcript span[data-start] { cursor: pointer; }
audio { width: 100%; }
@media print { audio, .hear { display: none; } .card { break-inside: avoid; } }
"""

JS = """
document.querySelectorAll('[data-start]').forEach(function (el) {
  el.addEventListener('click', function () {
    var a = document.getElementById('take');
    if (!a) return;
    a.currentTime = Math.max(0, parseFloat(el.dataset.start) - 0.15);
    a.play();
  });
});
"""


def _audio_b64(take_id: str) -> str:
    wav = takes.take_path(take_id) / "audio.wav"
    return base64.b64encode(wav.read_bytes()).decode("ascii") if wav.exists() else ""


def estimate_bytes(take_id: str) -> int:
    """Size of the export: the page without its audio, plus the audio as base64."""
    wav = takes.take_path(take_id) / "audio.wav"
    size = wav.stat().st_size if wav.exists() else 0
    return len(report_html(take_id, audio_placeholder=True).encode("utf-8")) + (size + 2) // 3 * 4


def report_html(take_id: str, audio_placeholder: bool = False) -> str:
    """The report page. Raises ValueError for a take with no analysis or an Improvise take.
    audio_placeholder: leave the audio's base64 out but keep everything around it (for the size estimate)."""
    a = takes.load_take(take_id)
    if a is None:
        raise ValueError("this take has not been analyzed")
    if a.get("mode") == "improv":
        raise ValueError("export covers script takes; an Improvise report has no script to print")
    has_audio = (takes.take_path(take_id) / "audio.wav").exists()
    b64 = "" if audio_placeholder or not has_audio else _audio_b64(take_id)
    out: list[str] = []
    w = out.append
    w(f"<h1>{_e(a.get('label') or 'Take')}</h1>")
    if a.get("kind") == "example":
        w('<p class="small"><strong>Example take (synthetic voice):</strong> a text-to-speech recording shipped with the app, not a person.</p>')
    w(f'<p class="muted small">{_e(a.get("created_at", ""))} · {_t(a.get("duration_s"))} · transcribed with '
      f'{_e(a.get("stt", {}).get("model", ""))}; pauses measured with {_e(a.get("silence_method", ""))}. '
      "No score: every mark was set by the speaker, and each says whether it was met, close or diverged.</p>")
    if has_audio:
        w(f'<audio id="take" controls preload="auto" src="data:audio/wav;base64,{b64}"></audio>')
        w('<p class="muted small hear">Click any line or transcript word to hear it.</p>')
    if a.get("drill_summary"):
        w('<section class="card"><h2>This drill</h2><ul>' + "".join(f"<li>{_e(s)}</li>" for s in a["drill_summary"]) + "</ul></section>")
    w('<section class="card"><h2>Summary</h2><ul>' + "".join(f"<li>{_e(s)}</li>" for s in a.get("summary", [])) + "</ul>")
    b = a.get("baseline", {})
    med = b.get("median_wpm")
    w(f'<p class="muted small">Median {f"{med:.0f}" if med else "–"} wpm ({_e(b.get("median_source") or "this take")}); '
      f'median pause {b.get("median_pause_s") if b.get("median_pause_s") is not None else "–"} s.</p>')
    over = a.get("settings_from_script") or {}
    if over:
        w('<p class="muted small">From the script\'s settings line: '
          + _e(", ".join(f"{k} {('on' if v else 'off') if isinstance(v, bool) else v}" for k, v in over.items()))
          + ". Every other threshold is from the speaker's Settings.</p>")
    w("</section>")
    f = a.get("focus")
    if f:
        items = "".join(f"<li>{_chip(i['status'], i['kind'])}{_e(i['text'])}</li>" for i in f.get("items", []))
        w('<section class="card"><h2>Focus for the next take</h2>'
          + (f"<ol>{items}</ol>" if items else f"<p>{_e(f.get('note') or '')}</p>")
          + '<p class="muted small">Written by the app from the numbers, no model involved.</p></section>')
    w('<section class="card"><h2>Sections</h2><ul>')
    ft = a.get("fit_total") or {}
    if ft.get("status") == "over" and ft.get("cut") and a.get("kind") != "drill":
        w(f"<li>{_chip('over', 'whole talk')}{_e(ft['cut']['text'])}</li>")
    for s in a.get("sections", []):
        label = ("not found" if s["status"] == "not_found" else "no script lines, nothing to time" if s["status"] == "no_lines" else
                 f"{s['duration_label']} spoken" + (f" of {s['budget_label']} budget, {s['delta_label']}" if s.get("budget_s") is not None else ", no budget"))
        cut = f" {_e(s['cut']['text'])}" if s.get("cut") else ""
        w(f"<li>{_chip(s['status'], s['name'])}{_e(label)}.{cut}</li>")
    w("</ul></section>")
    c = a.get("conventions") or {}
    if c.get("enabled") and c.get("status") != "not_implemented":
        band = c.get("wpm_band") or [None, None]
        w('<section class="card"><h2>Conference conventions (a preset the speaker switched on)</h2><ul>'
          f"<li>Overall pace {_n(c.get('overall_wpm'), 0)} wpm against the {band[0]}–{band[1]} wpm band: "
          f"{_e(WORD.get(c.get('wpm_status') or 'unknown', c.get('wpm_status')))}.</li>"
          f"<li>Filler words: {c.get('filler_count') or 0} in {c.get('words') or 0} words ({_n(c.get('filler_per_100'), 1)} per 100, "
          f"target at most {c.get('filler_target_per_100')}): {_e(WORD.get(c.get('filler_status') or 'unknown', c.get('filler_status')))}.</li></ul>"
          '<p class="muted small">Whisper often drops fillers, so the count is a lower bound.</p></section>')
    w('<section class="card"><h2>The script, mark by mark</h2>')
    pauses, defines, sections = a.get("pauses", []), a.get("defines", []), a.get("sections", [])
    emphasis = a.get("emphasis") or []
    current = None
    for ln in a.get("lines", []):
        sec = sections[ln["section"]] if ln["section"] < len(sections) else None
        if sec and sec["index"] != current:
            current = sec["index"]
            w(f'<h3 class="section">{_e(sec["name"])} <span class="muted small">{_e(sec.get("budget_label") or "")}</span></h3>')
        chips, tips = [], []
        if ln.get("key"):
            chips.append(_chip(ln["key"]["status"], "KEY"))
            tips.append("KEY: " + _key_tip(ln["key"]))
        for d in (d for d in defines if d["line"] == ln["index"]):
            chips.append(_chip(d["status"], f"DEFINE: {d['term']}"))
            ev = d.get("evidence") or {}
            tips.append(f"DEFINE “{d['term']}”: {WORD.get(d['status'], d['status'])}"
                        + (f", evidence “{ev.get('quote', '')}” at {_t(ev.get('start'))}" if d["status"] == "defined" and ev.get("quote") else "")
                        + f" ({d.get('method', '')} check).")
        for p in (p for p in pauses if p["line"] == ln["index"]):
            chips.append(_chip(p["status"], p["kind"]))
            gap = f" Whisper's own gap: {p['whisper_gap_s']:.2f} s." if p.get("whisper_gap_s") is not None else ""
            tips.append(f"{p['kind']} between “{p.get('before') or ''}” and “{p.get('after') or ''}”: "
                        + (f"{p['measured_s']:.2f} s of silence against {p['target_s']} s, {WORD.get(p['status'], p['status'])}.{gap}"
                           if p.get("measured_s") is not None else f"{p.get('note') or 'not measured'}."))
        for e in (e for e in emphasis if e.get("line") == ln["index"]):
            chips.append(_chip(e.get("status", "unknown"), f"*{e.get('word', '')}*"))
            tips.append(f"Emphasis on “{e.get('word', '')}” (experimental): {_emphasis_tip(e)}")
        if ln["status"] == "paraphrased" and ln.get("said"):
            tips.append(f"Paraphrased (timed, not rate-checked). Said: “{ln['said']['text']}”")
        cov = ln.get("coverage")
        meta = ("not found in this take" if ln["status"] == "not_found" else
                f"{_t(ln.get('start'))} – {_t(ln.get('end'))}" + (f" · {ln['wpm']:.0f} wpm" if ln.get("wpm") else "")
                + (f" · {cov * 100:.0f}% of words matched" if cov is not None and cov < 1 and ln["status"] == "ok" else ""))
        start = ln.get("start")
        attr = f' data-start="{start}"' if start is not None and has_audio else ""
        cls = "line nf" if ln["status"] == "not_found" else "line"
        tip_html = "".join(f"<li>{_e(t)}</li>" for t in tips)
        w(f'<div class="{cls}"{attr}>{"".join(chips)}{_e(ln["text"])}'
          f'<div class="muted small">{_e(meta)}</div>' + (f'<ul class="tips">{tip_html}</ul>' if tip_html else "") + "</div>")
    w("</section>")
    c = a.get("coaching")
    if c and c.get("suggestions"):
        w('<section class="card"><h2>Suggestions based on the measurements</h2><ul>'
          + "".join(f"<li>{_e(s['text'])}" + (f' <span class="muted small">({_e(s["metric"])})</span>' if s.get("metric") else "") + "</li>"
                    for s in c["suggestions"])
          + f'</ul><p class="muted small">Written by {_e(c.get("model") or "a language model")} from the numbers above; '
            "it never heard the audio.</p></section>")
    words = a.get("transcript", {}).get("words", [])
    span = (lambda x: f'<span data-start="{x["start"]}">{_e(x["text"])}</span>') if has_audio else (lambda x: _e(x["text"]))
    w('<section class="card transcript"><h2>Transcript</h2><p>' + " ".join(span(x) for x in words) + "</p>")
    w('<p class="muted small">Exported from Take Two. Every number above comes from the word timestamps and the '
      "voice-activity detector's silences in this recording.</p></section>")
    title = _e(a.get("label") or "Take")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title} · Take Two report</title><style>{CSS}</style></head><body>{''.join(out)}<script>{JS}</script></body></html>")
