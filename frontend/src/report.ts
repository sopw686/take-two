import { api } from "./api";
import { clear, fmtTime, h } from "./dom";
import { state } from "./state";
import type { Analysis, DefineRow, KeyInfo, LineRow, PauseRow, SectionRow } from "./types";

const player = () => document.getElementById("player") as HTMLAudioElement;

function play(at: number | null): void {
  if (at === null) return;
  const p = player();
  p.currentTime = Math.max(0, at - 0.15);
  void p.play();
}

function pct(n: number | null): string {
  if (n === null) return "–";
  const a = Math.abs(n).toFixed(0);
  return n < 0 ? `${a}% slower than your median` : n > 0 ? `${a}% faster than your median` : "at your median";
}

function keyTip(k: KeyInfo): string {
  if (k.status === "not_found") return "This line was not found in the take, so it was not measured.";
  const parts: string[] = [];
  parts.push(`Rate: ${k.wpm?.toFixed(0) ?? "–"} wpm, ${pct(k.wpm_vs_median_pct)} (${k.median_wpm?.toFixed(0) ?? "–"} wpm). Your mark asks for at least ${k.slower_target_pct}% slower: ${word(k.rate_status)}.`);
  parts.push(`Pause after: ${k.pause_after_s?.toFixed(2) ?? "–"} s against your ${k.pause_after_target_s} s mark: ${word(k.pause_status)}.`);
  return parts.join(" ");
}

function pauseTip(p: PauseRow): string {
  if (p.status === "unmeasurable") return "Could not locate the words around this mark in the take.";
  return `Measured ${p.measured_s?.toFixed(2)} s of silence between “${p.before}” and “${p.after}” (target ≥ ${p.target_s} s): ${word(p.status)}. Whisper's own gap: ${p.whisper_gap_s?.toFixed(2)} s.`;
}

function word(s: string): string {
  return ({ met: "met your mark", near: "close to your mark", diverged: "diverged from your mark", short: "shorter than your mark",
    missing: "no pause found", unmeasurable: "not measurable", not_found: "not found", over: "over budget", under: "under budget",
    no_budget: "no budget set", unknown: "unknown", ok: "ok" } as Record<string, string>)[s] ?? s;
}

function sectionBars(a: Analysis): HTMLElement {
  const maxS = Math.max(...a.sections.map((s) => Math.max(s.budget_s ?? 0, s.duration_s ?? 0)), 1);
  return h("div", { class: "section-bars" }, ...a.sections.map((s: SectionRow) => {
    const budgetW = s.budget_s ? (s.budget_s / maxS) * 100 : 0;
    const actualW = s.duration_s ? (s.duration_s / maxS) * 100 : 0;
    const label = s.status === "not_found" ? "not found in this take"
      : s.status === "no_budget" ? `${s.duration_label} spoken, no budget set`
      : `${s.duration_label} spoken of ${s.budget_label} budget · ${s.delta_label} · ${word(s.status)}`;
    return h("div", { class: "section-bar", onClick: () => play(s.start) },
      h("div", { class: "section-bar-head" }, h("strong", {}, s.name), h("span", { class: "muted small" }, label)),
      h("div", { class: "bar-track" },
        h("div", { class: "bar-budget", style: `width:${budgetW}%` }),
        h("div", { class: `bar-actual st-${s.status}`, style: `width:${actualW}%` })));
  }));
}

function lineEl(a: Analysis, line: LineRow): HTMLElement {
  const pauses = a.pauses.filter((p) => p.line === line.index);
  const defines = a.defines.filter((d) => d.line === line.index);
  const emph = (a.emphasis ?? []).filter((e) => e.line === line.index);
  const parts: (HTMLElement | string)[] = [];
  if (line.is_key && line.key) {
    const k = line.key;
    parts.push(h("span", { class: `mark key st-${k.status} tip`, "data-tip": keyTip(k) }, "KEY"));
  }
  for (const d of defines) parts.push(defineChip(d));
  const pauseAt = (wi: number) => pauses.filter((p) => p.word_index === wi);
  line.words.forEach((w, i) => {
    for (const p of pauseAt(i)) parts.push(pauseChip(p));
    const e = emph.find((x) => x.word_index === i);
    const cls = e ? `w emph st-${e.status} tip` : "w";
    const attrs: Record<string, string> = { class: cls };
    if (e) attrs["data-tip"] = `Emphasis (experimental): ${e.delta_db !== null ? `${e.delta_db >= 0 ? "+" : ""}${e.delta_db.toFixed(1)} dB vs the line's median` : "no measurement"}${e.word_f0 && e.line_median_f0 ? `, pitch ${e.word_f0.toFixed(0)} Hz vs ${e.line_median_f0.toFixed(0)} Hz` : ""}.`;
    if (w.start !== null) attrs["data-start"] = String(w.start);
    parts.push(h("span", attrs, w.text), " ");
  });
  for (const p of pauseAt(line.words.length)) parts.push(pauseChip(p));

  const meta = line.status === "not_found"
    ? "not found in this take"
    : `${fmtTime(line.start)} – ${fmtTime(line.end)} · ${line.wpm?.toFixed(0) ?? "–"} wpm` + (line.coverage < 1 ? ` · ${Math.round(line.coverage * 100)}% of words matched` : "");
  const el = h("div", { class: `line ${line.status === "not_found" ? "not-found" : ""} ${line.is_key ? "is-key" : ""}`, "data-line": String(line.index), "data-start": line.start !== null ? String(line.start) : "" },
    h("div", { class: "line-text" }, ...parts),
    h("div", { class: "line-meta muted small" }, meta));
  el.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    const ws = t.closest("[data-start]") as HTMLElement | null;
    const start = ws?.dataset.start ? parseFloat(ws.dataset.start) : line.start;
    play(start);
  });
  return el;
}

function pauseChip(p: PauseRow): HTMLElement {
  return h("span", { class: `mark pause st-${p.status} tip`, "data-tip": pauseTip(p), onClick: (e) => { e.stopPropagation(); play(p.at_time); } }, p.kind);
}

function defineChip(d: DefineRow): HTMLElement {
  const st = d.status;
  let tip = "";
  if (st === "not_checked") tip = "Definition check not run.";
  else if (st === "never_spoken") tip = `“${d.term}” was never spoken in this take.`;
  else if (st === "defined") tip = `Defined (${d.method}): “${d.evidence?.quote ?? ""}” at ${fmtTime(d.evidence?.start ?? null)}. First spoken at ${fmtTime(d.first_spoken_at ?? null)}.`;
  else if (st === "undefined") tip = `“${d.term}” was first spoken at ${fmtTime(d.first_spoken_at ?? null)} and no definition was found at or before that point (${d.method} check).${d.note ? " " + d.note : ""}`;
  else tip = d.note ?? st;
  const cls = st === "defined" ? "met" : st === "undefined" || st === "never_spoken" ? "diverged" : "unknown";
  return h("span", { class: `mark define st-${cls} tip`, "data-tip": tip,
    onClick: (e) => { e.stopPropagation(); play(d.evidence?.start ?? d.first_spoken_at ?? null); } },
    `DEFINE: ${d.term}${d.method === "heuristic" ? " (heuristic)" : ""}`);
}

function summaryCard(a: Analysis): HTMLElement {
  const items = a.summary.length ? a.summary : ["Nothing to report: no marks were found in the script."];
  const defs = a.defines;
  const extra: string[] = [];
  for (const d of defs) {
    if (d.status === "never_spoken") extra.push(`“${d.term}” was never spoken.`);
    if (d.status === "undefined") extra.push(`“${d.term}” was not defined before its first use.`);
  }
  return h("section", { class: "summary" },
    h("ul", {}, ...[...items, ...extra].map((s) => h("li", {}, s))),
    h("p", { class: "muted small" },
      `Your median this take: ${a.baseline.median_wpm?.toFixed(0) ?? "–"} wpm over ${a.baseline.lines_used} lines of ${a.baseline.min_words_per_line}+ words; median pause ${a.baseline.median_pause_s?.toFixed(2) ?? "–"} s. `,
      `Transcribed ${a.stt.local ? "on this computer" : "by a cloud service"} with ${a.stt.model} (${a.stt.device}); pauses measured with ${a.silence_method}. Click any line or mark to hear it.`));
}

function conventionsCard(a: Analysis): HTMLElement | null {
  const c = a.conventions;
  if (!c || !c.enabled || c.status === "not_implemented") return null;
  return h("section", { class: "card" },
    h("h3", {}, "Conference conventions (preset you switched on)"),
    h("ul", {},
      h("li", {}, `Overall pace ${c.overall_wpm?.toFixed(0) ?? "–"} wpm against the ${c.wpm_band?.[0]}–${c.wpm_band?.[1]} wpm band you chose: ${word(c.wpm_status ?? "unknown")}.`),
      h("li", {}, `Filler words: ${c.filler_count ?? 0} in ${c.words ?? 0} words (${c.filler_per_100?.toFixed(1) ?? "–"} per 100, target ≤ ${c.filler_target_per_100}): ${word(c.filler_status ?? "unknown")}.`,
        c.fillers?.length ? h("span", { class: "muted small" }, " " + c.fillers.slice(0, 12).map((f) => `${f.text} @${fmtTime(f.start)}`).join(", ")) : null)),
    h("p", { class: "muted small" }, "Whisper often drops fillers; counts are a lower bound. Switch this off in Settings to return to your own marks only."));
}

function coachingCard(a: Analysis, onRefresh: () => void): HTMLElement {
  const c = a.coaching;
  const btn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    btn.setAttribute("disabled", "");
    btn.textContent = "Reading your measurements…";
    try {
      state.setAnalysis(await api.coach(a.take_id));
      onRefresh();
    } catch (err) {
      btn.textContent = `Failed: ${(err as Error).message}`;
    }
  } }, c ? "Refresh suggestions" : "Suggestions based on your measurements") as HTMLButtonElement;
  const llm = state.health?.llm;
  if (!llm?.available) {
    btn.setAttribute("disabled", "");
    return h("section", { class: "card muted small" }, "Post-take suggestions need an ANTHROPIC_API_KEY on the server. The model would read only the measured numbers above, never the audio.");
  }
  const body = c
    ? (c.all_met && !c.suggestions.length
      ? h("p", {}, "Everything met its marks in this take. Nothing to suggest.")
      : h("ul", {}, ...c.suggestions.map((s) => h("li", {}, s.text, s.metric ? h("span", { class: "muted small" }, ` (${s.metric})`) : null))))
    : h("p", { class: "muted small" }, "At most three suggestions, each citing a measured number and the mark it concerns. No norms you did not choose.");
  return h("section", { class: "card" }, h("h3", {}, "Suggestions based on your measurements"), body, btn);
}

function transcriptCard(a: Analysis): HTMLElement {
  const det = h("details", { class: "card" }, h("summary", {}, "Transcript and raw timings"),
    h("p", { class: "transcript" }, ...a.transcript.words.map((w) => h("span", { class: "w", onClick: () => play(w.start), title: `${w.start.toFixed(2)}–${w.end.toFixed(2)} s` }, w.text + " "))),
    h("p", { class: "muted small" }, `Analysis took ${a.timing.stt_s ?? "?"} s of transcription. Every number in this report comes from these timestamps; the full JSON is at `,
      h("a", { href: `/api/takes/${a.take_id}`, target: "_blank" }, `/api/takes/${a.take_id}`), "."));
  return det;
}

export function renderReport(root: HTMLElement): void {
  clear(root);
  const a = state.analysis;
  if (!a) {
    root.append(h("p", { class: "muted" }, "No take yet. Record one in Rehearse, or open an earlier take from Takes."));
    return;
  }
  const p = player();
  if (!p.src.endsWith(a.audio_url)) p.src = a.audio_url;

  const rerender = () => renderReport(root);
  const reanalyzeBtn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    reanalyzeBtn.setAttribute("disabled", "");
    try {
      state.setAnalysis(await api.reanalyze(a.take_id, state.scriptText, state.effectiveSettings()));
      rerender();
    } catch (err) {
      alert(`Re-analysis failed: ${(err as Error).message}`);
      reanalyzeBtn.removeAttribute("disabled");
    }
  } }, "Re-analyze with current script and settings") as HTMLButtonElement;

  const scriptEl = h("div", { class: "script-report" }, ...a.sections.flatMap((s) => [
    h("h2", { class: "section-head", onClick: () => play(s.start) }, s.name, h("span", { class: "muted small" }, s.budget_label ? ` ${s.budget_label} budget · ${s.duration_label || "not found"} spoken` : ` ${s.duration_label || "not found"} spoken`)),
    ...a.lines.filter((l) => l.section === s.index).map((l) => lineEl(a, l)),
  ]));

  const legend = h("div", { class: "legend muted small" },
    h("span", { class: "mark st-met" }, "met your mark"), h("span", { class: "mark st-near" }, "close"), h("span", { class: "mark st-diverged" }, "diverged"),
    h("span", { class: "mark st-unknown" }, "not measured"), " · hover a mark for the numbers · click a line to hear it");

  root.append(
    h("div", { class: "report-head" },
      h("div", {}, h("h2", {}, a.label || "Take", h("span", { class: "muted small" }, ` · ${new Date(a.created_at).toLocaleString()} · ${fmtTime(a.duration_s)}`))),
      reanalyzeBtn),
    summaryCard(a),
    h("section", { class: "card" }, h("h3", {}, "Sections: budget vs. spoken"), sectionBars(a)),
    conventionsCard(a) ?? "",
    legend,
    scriptEl,
    coachingCard(a, rerender),
    transcriptCard(a),
  );

  p.ontimeupdate = () => {
    const t = p.currentTime;
    root.querySelectorAll<HTMLElement>(".line").forEach((el) => {
      const li = parseInt(el.dataset.line ?? "-1", 10);
      const row = a.lines[li];
      el.classList.toggle("playing", !!row && row.start !== null && row.end !== null && t >= row.start - 0.15 && t <= row.end + 0.2);
    });
  };
}
