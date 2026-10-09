/** Timeline strip over the whole take: the voice-activity detector's silences, the time span of each
 *  script line, every mark at the moment it was measured, section boundaries, and a playhead. It shows
 *  where the report's numbers come from; click (or ←/→) to hear that moment. */

import { esc, fmtTime, h } from "./dom";
import { statusGlyph, statusTone } from "./status";
import type { Analysis } from "./types";

const H = 58;

export function timelineStrip(a: Analysis, seek: (t: number) => void): { el: HTMLElement; setTime: (t: number) => void } {
  const dur = Math.max(a.duration_s, 0.1);
  const x = (t: number) => `${Math.max(0, Math.min(100, (t / dur) * 100)).toFixed(3)}%`;
  const w = (t0: number, t1: number) => `${Math.max(0.15, ((t1 - t0) / dur) * 100).toFixed(3)}%`;
  const parts: string[] = [];
  const off = a.drill?.line_start ?? 0;  // a drill numbers its lines as in the full script
  for (const s of a.silences ?? []) {
    parts.push(`<rect class="tl-silence" x="${x(s.start)}" y="2" width="${w(s.start, s.end)}" height="10"><title>Silence ${fmtTime(s.start)}–${fmtTime(s.end)} (${(s.end - s.start).toFixed(2)} s, ${esc(a.silence_method)})</title></rect>`);
  }
  for (const sec of a.sections) {
    if (sec.start === null) continue;
    parts.push(`<line class="tl-section" x1="${x(sec.start)}" x2="${x(sec.start)}" y1="0" y2="${H}"><title>Section ${esc(sec.name)} starts at ${fmtTime(sec.start)}</title></line>`);
  }
  for (const l of a.lines) {
    if (l.start === null || l.end === null) continue;
    const st = l.key ? `st-${statusTone(l.key.status)}` : "";
    const what = l.key ? ` · KEY ${statusGlyph(l.key.status)}` : "";
    parts.push(`<rect class="tl-line ${st}" x="${x(l.start)}" y="18" width="${w(l.start, l.end)}" height="14" rx="2"><title>Line ${l.index + 1 + off}: ${fmtTime(l.start)}–${fmtTime(l.end)}${what} · “${esc(l.text.slice(0, 60))}”</title></rect>`);
  }
  const tick = (t: number | null | undefined, status: string, label: string) => {
    if (t === null || t === undefined) return;
    parts.push(`<rect class="tl-mark st-${statusTone(status)}" x="${x(t)}" y="38" width="4" height="14" rx="1"><title>${statusGlyph(status)} ${esc(label)} at ${fmtTime(t)}</title></rect>`);
  };
  for (const l of a.lines) if (l.key && l.key.pause_window) tick(l.key.pause_window[0], l.key.status, `KEY line ${l.index + 1 + off}`);
  for (const p of a.pauses) tick(p.at_time, p.status, `${p.kind} in line ${p.line + 1 + off}${p.measured_s !== null ? `: ${p.measured_s.toFixed(2)} s` : ""}`);
  for (const d of a.defines) tick(d.evidence?.start ?? d.first_spoken_at ?? null, d.status, `DEFINE: ${d.term}`);
  parts.push(`<line class="tl-playhead" x1="0%" x2="0%" y1="0" y2="${H}"/>`);

  const svg = `<svg class="tl-svg" width="100%" height="${H}" role="presentation">${parts.join("")}</svg>`;
  const wrap = h("div", { class: "timeline", tabindex: "0", role: "slider", "aria-label": "Take timeline: silences, lines and marks over time",
    "aria-valuemin": "0", "aria-valuemax": String(Math.round(dur)), "aria-valuenow": "0", "aria-valuetext": "0:00", html: svg });
  let now = 0;
  const go = (t: number) => {
    now = Math.max(0, Math.min(dur, t));
    seek(now);
  };
  wrap.addEventListener("click", (e) => {
    const r = wrap.getBoundingClientRect();
    go(((e.clientX - r.left) / r.width) * dur);
  });
  wrap.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      go(now + (e.key === "ArrowRight" ? 5 : -5));
    }
  });
  const playhead = wrap.querySelector(".tl-playhead") as SVGLineElement;
  return {
    el: wrap,
    setTime(t: number) {
      now = t;
      playhead.setAttribute("x1", x(t));
      playhead.setAttribute("x2", x(t));
      wrap.setAttribute("aria-valuenow", String(Math.round(t)));
      wrap.setAttribute("aria-valuetext", fmtTime(t));
    },
  };
}
