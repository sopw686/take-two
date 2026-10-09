import { api } from "./api";
import { clear, fmtTime, h } from "./dom";
import { drillButton, openDrill, stopDrill } from "./drill";
import { closeHear, hearButton, sayWord } from "./hearit";
import { parseScript, sayings } from "./scriptinfo";
import { describeOverrides } from "./editor";
import { play as playAt, player } from "./player";
import { state } from "./state";
import { glyphParts, statusChip, statusGlyph, statusTone } from "./status";
import { exampleButton, exportReport } from "./takes";
import { timelineStrip } from "./timeline";
import type { Analysis, ClarityWord, DefineRow, KeyInfo, LineRow, PauseRow, SectionRow } from "./types";

const DIFF_KEY = "taketwo.report.diff";

// The recording this report belongs to: every click plays it, even if a drill or a comparison loaded another.
let reportUrl = "";
const play = (at: number | null | undefined) => playAt(at, reportUrl);

function showDiff(): boolean {
  try { return localStorage.getItem(DIFF_KEY) === "1"; } catch { return false; }
}
function setShowDiff(on: boolean): void {
  try { localStorage.setItem(DIFF_KEY, on ? "1" : "0"); } catch { /* storage may be unavailable */ }
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
  if (k.rate_note) parts.push(k.rate_note);
  return parts.join(" ");
}

function pauseTip(p: PauseRow): string {
  if (p.status === "unmeasurable") return "Could not locate the words around this mark in the take.";
  return `Measured ${p.measured_s?.toFixed(2)} s of silence between “${p.before}” and “${p.after}” (target ≥ ${p.target_s} s): ${word(p.status)}. Whisper's own gap: ${p.whisper_gap_s?.toFixed(2)} s.`;
}

function word(s: string): string {
  return ({ met: "met your mark", near: "close to your mark", diverged: "diverged from your mark", short: "shorter than your mark",
    missing: "no pause found", unmeasurable: "not measurable", not_found: "not found", over: "over budget", under: "under budget",
    no_budget: "no budget set", no_lines: "no script lines", unknown: "unknown", ok: "ok" } as Record<string, string>)[s] ?? s;
}

function sectionBars(a: Analysis): HTMLElement {
  const maxS = Math.max(...a.sections.map((s) => Math.max(s.budget_s ?? 0, s.duration_s ?? 0)), 1);
  const total = a.fit_total;
  return h("div", { class: "section-bars" },
    total?.status === "over" && total.cut && a.kind !== "drill" ? h("p", { class: "fit-total" }, ...glyphParts("over", "over budget"), total.cut.text) : null,
    ...a.sections.map((s: SectionRow) => {
      const budgetW = s.budget_s ? (s.budget_s / maxS) * 100 : 0;
      const actualW = s.duration_s ? (s.duration_s / maxS) * 100 : 0;
      const label = s.status === "not_found" ? "not found in this take"
        : s.status === "no_lines" ? "no script lines, so nothing to time"
        : s.status === "no_budget" ? `${s.duration_label} spoken, no budget set`
        : `${s.duration_label} spoken of ${s.budget_label} budget · ${s.delta_label} · ${word(s.status)}`;
      return h("div", { class: "section-bar", onClick: () => play(s.start) },
        h("div", { class: "section-bar-head" }, h("strong", {}, s.name),
          h("span", { class: "muted small" }, s.status !== "no_budget" && s.status !== "no_lines" ? glyphParts(s.status, word(s.status)) : null, label)),
        h("div", { class: "bar-track" },
          h("div", { class: "bar-budget", style: `width:${budgetW}%` }),
          h("div", { class: `bar-actual st-${s.status}`, style: `width:${actualW}%` })),
        s.cut ? h("p", { class: "cut small", title: "Speaking time only: cutting lines also removes their pauses, so this errs high." }, s.cut.text) : null);
    }));
}

function lineEl(a: Analysis, line: LineRow, diff: boolean): HTMLElement {
  let el: HTMLElement = h("div");  // replaced below; the Drill button needs a reference to the finished line
  const pauses = a.pauses.filter((p) => p.line === line.index);
  const defines = a.defines.filter((d) => d.line === line.index);
  const emph = (a.emphasis ?? []).filter((e) => e.line === line.index);
  const adlibsAt = (wi: number) => (diff ? (line.adlibs ?? []).filter((x) => x.word_index === wi) : []);
  const parts: (HTMLElement | string)[] = [];
  if (line.is_key && line.key) parts.push(statusChip(line.key.status, "KEY", { tip: keyTip(line.key), extraClass: "key" }));
  if (line.is_key && canDrill(a)) parts.push(drillButton(a, "line", line.index, `line ${line.index + 1}`, () => el));
  if (line.is_key && a.kind !== "drill") parts.push(hearButton(hearOpts(a, line.index, () => el), () => el));
  for (const d of defines) parts.push(defineChip(d));
  const pauseAt = (wi: number) => pauses.filter((p) => p.word_index === wi);
  const adlib = (x: { text: string; start: number; repeat: boolean }) => h("span", { class: "adlib", "data-start": String(x.start),
    title: x.repeat ? "Said twice (a restart); not in the script" : "Said, but not in the script" }, x.text);
  line.words.forEach((w, i) => {
    for (const x of adlibsAt(i)) parts.push(adlib(x), " ");
    for (const p of pauseAt(i)) parts.push(pauseChip(p));
    const e = emph.find((x) => x.word_index === i);
    const dropped = diff && w.dropped;
    const misheard = diff && w.heard;
    const cls = ["w", e ? `emph st-${statusTone(e.status)} tip` : "", dropped ? "dropped" : "", misheard ? "misheard" : ""].filter(Boolean).join(" ");
    const attrs: Record<string, string> = { class: cls };
    if (e) {
      attrs["data-tip"] = `Emphasis (experimental): ${e.delta_db !== null ? `${e.delta_db >= 0 ? "+" : ""}${e.delta_db.toFixed(1)} dB vs the line's median` : "no measurement"}${e.word_f0 && e.line_median_f0 ? `, pitch ${e.word_f0.toFixed(0)} Hz vs ${e.line_median_f0.toFixed(0)} Hz` : ""}.`;
      attrs.tabindex = "0";
      attrs["aria-label"] = `${w.text}, emphasis: ${attrs["data-tip"]}`;
    }
    if (dropped) attrs.title = "In the script, not heard in this take";
    if (misheard) attrs.title = `Heard as “${w.heard}” and matched as a likely mishearing`;
    if (w.start !== null) attrs["data-start"] = String(w.start);
    parts.push(h("span", attrs, w.text, e ? h("span", { class: "glyph", "aria-hidden": "true" }, statusGlyph(e.status)) : null), " ");
  });
  for (const x of adlibsAt(line.words.length)) parts.push(adlib(x), " ");
  for (const p of pauseAt(line.words.length)) parts.push(pauseChip(p));

  const differ = diff && line.words_differ ? ` · ${line.words_differ} word${line.words_differ === 1 ? "" : "s"} differ` : "";
  const meta = line.status === "not_found"
    ? "not found in this take"
    : line.status === "paraphrased"
      ? `${fmtTime(line.start)} – ${fmtTime(line.end)} · paraphrased: timed, not rate-checked`
      : `${fmtTime(line.start)} – ${fmtTime(line.end)} · ${line.wpm?.toFixed(0) ?? "–"} wpm` + (line.coverage < 1 ? ` · ${Math.round(line.coverage * 100)}% of words matched` : "") + differ;
  const saidEl = line.status === "paraphrased" && line.said
    ? h("div", { class: "said small", "data-start": String(line.said.start),
      title: "Too few words matched the script to compare this line's rate with your median; its time still counts toward its section." },
      h("span", { class: "muted" }, "You said: "), `“${line.said.text}”`)
    : null;
  el = h("div", { class: `line ${line.status === "not_found" ? "not-found" : line.status === "paraphrased" ? "paraphrased" : ""} ${line.is_key ? "is-key" : ""}`, "data-line": String(line.index), "data-start": line.start !== null ? String(line.start) : "" },
    h("div", { class: "line-text" }, ...parts),
    saidEl,
    h("div", { class: "line-meta muted small" }, meta));
  el.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    const ws = t.closest("[data-start]") as HTMLElement | null;
    const start = ws?.dataset.start ? parseFloat(ws.dataset.start) : line.start;
    play(start);
  });
  return el;
}

/** Hear it for a line of this take: its own script and median; Try it opens that line's drill. Accepting the coach's
 *  marks writes them into the Script tab's script only when that script is this take's script. */
function hearOpts(a: Analysis, lineIndex: number, anchor: () => HTMLElement) {
  const same = () => {
    const mine = parseScript(state.scriptText).lines;
    return mine.length === a.lines.length && mine.every((l, i) => l.parts.filter((p) => p.kind === "word").length === a.lines[i].word_count);
  };
  return {
    lineIndex, script: () => null, takeId: a.take_id,
    tryIt: canDrill(a) ? () => openDrill(a, "line", lineIndex, `line ${lineIndex + 1}`, anchor()) : "A try is judged against one of your own full takes; the example is a synthetic voice.",
    onScriptChange: same() ? (text: string) => state.setScript(text) : undefined,
  };
}

/** Words the recognizer was unsure of, or heard as another word: measured, with what to do about each. */
function clarityCard(a: Analysis): HTMLElement | null {
  const c = a.clarity;
  if (!c || a.kind === "drill") return null;
  const list = h("ul", { class: "clarity-list" });
  const status = h("p", { class: "small muted", role: "status" });
  const row = (w: ClarityWord): HTMLElement => {
    let li: HTMLElement = h("li");
    const resp = sayings(state.scriptText).get(w.word.toLowerCase()) ?? null;
    li = h("li", {},
      h("button", { class: "linklike", type: "button", title: "Hear this moment of your take", onClick: () => play(w.start) }, fmtTime(w.start)),
      " ", w.text, " ",
      h("button", { class: "ghost-btn small", type: "button", title: resp ? `Said as ${resp} (your [SAY] mark), slowly, then at an ordinary pace` : "The word said slowly, then at an ordinary pace",
        onClick: () => sayWord(w.word, resp, (m) => { status.textContent = m; }) }, "Hear it"),
      canDrill(a) ? drillButton(a, "word", w.line, `“${w.word}”`, () => li, w.word_index, "Drill this word") : null,
      h("button", { class: "linklike small", type: "button", title: "Leave this word out of later reports",
        onClick: async () => {
          try {
            await api.dismissClarity(w.word);
            li.replaceChildren(h("span", { class: "muted small" }, `“${w.word}”: you said it fine. It is left out from now on. `),
              h("button", { class: "linklike small", type: "button", onClick: async () => { await api.dismissClarity(w.word, false); li.replaceWith(row(w)); } }, "Undo"));
          } catch (err) {
            status.textContent = `Could not save that: ${(err as Error).message}`;
          }
        } }, "I said it fine"));
    return li;
  };
  if (c.words.length) list.append(...c.words.map(row));
  return h("section", { class: "card clarity" },
    h("h3", {}, "Words that may not have been clear"),
    c.words.length ? list : h("p", {}, "The recognizer was sure of every script word it matched in this take."),
    h("p", { class: "muted small" }, `Listed: script words the recognizer heard as another word, or was less than ${c.threshold} confident of`
      + (c.context_words ? ` (unless the ${c.context_words} words on each side matched at high confidence)` : "") + ". "
      + c.note + (c.dismissed_skipped ? ` ${c.dismissed_skipped} word${c.dismissed_skipped === 1 ? "" : "s"} you said were fine ${c.dismissed_skipped === 1 ? "is" : "are"} left out.` : "")
      + " The threshold is in Settings."),
    status);
}

/** Drills record one line or section of one of your own full script takes. */
function canDrill(a: Analysis): boolean {
  return (a.kind ?? "take") === "take";
}

/** For a drill: what it was compared with, and one sentence per mark. */
function drillCard(a: Analysis, openParent: (id: string) => void): HTMLElement | null {
  if (a.kind !== "drill" || !a.drill) return null;
  return h("section", { class: "card drill-card" },
    h("h3", {}, `Drill: ${a.drill.what}`),
    h("ul", {}, ...(a.drill_summary ?? []).map((t) => h("li", {}, t))),
    h("p", { class: "muted small" }, a.drill.parent_median_wpm
      ? `Rates are compared with the median of the full take this drill came from (${a.drill.parent_median_wpm.toFixed(0)} wpm), because one line has no median of its own. The pause after the last line is measured to the end of the recording. `
      : "The full take this drill came from has no median, so rates are not compared. ",
      a.drill_of ? h("button", { class: "linklike small", type: "button", onClick: () => openParent(a.drill_of as string) }, "Open the full take") : null));
}

function pauseChip(p: PauseRow): HTMLElement {
  return statusChip(p.status, p.kind, { tip: pauseTip(p), extraClass: "pause", onClick: (e) => { e.stopPropagation(); play(p.at_time); } });
}

function defineChip(d: DefineRow): HTMLElement {
  const st = d.status;
  let tip = "";
  if (st === "not_checked") tip = "Definition check not run.";
  else if (st === "never_spoken") tip = `“${d.term}” was never spoken in this take.`;
  else if (st === "defined") tip = `Defined (${d.method}): “${d.evidence?.quote ?? ""}” at ${fmtTime(d.evidence?.start ?? null)}. First spoken at ${fmtTime(d.first_spoken_at ?? null)}.`;
  else if (st === "undefined") tip = `“${d.term}” was first spoken at ${fmtTime(d.first_spoken_at ?? null)} and no definition was found at or before that point (${d.method} check).${d.note ? " " + d.note : ""}`;
  else tip = d.note ?? st;
  return statusChip(st, `DEFINE: ${d.term}${d.method === "heuristic" ? " (heuristic)" : d.method === "llm" ? " (LLM)" : ""}`, {
    tip, extraClass: "define", word: st === "defined" ? "defined" : st === "undefined" ? "not defined first" : st === "never_spoken" ? "never spoken" : undefined,
    onClick: (e) => { e.stopPropagation(); play(d.evidence?.start ?? d.first_spoken_at ?? null); } });
}

function summaryCard(a: Analysis): HTMLElement {
  const items = a.summary.length ? a.summary : ["Nothing to report: no marks were found in the script."];
  return h("section", { class: "summary" },
    h("ul", {}, ...items.map((s) => h("li", {}, s))),
    h("p", { class: "muted small" },
      a.baseline.median_source && a.baseline.median_source !== "this take"
        ? `Median from ${a.baseline.median_source}: ${a.baseline.median_wpm?.toFixed(0) ?? "none"} wpm (a drill has no median of its own); median pause in this recording ${a.baseline.median_pause_s?.toFixed(2) ?? "–"} s. `
        : `Your median this take: ${a.baseline.median_wpm?.toFixed(0) ?? "–"} wpm over ${a.baseline.lines_used} lines of ${a.baseline.min_words_per_line}+ words; median pause ${a.baseline.median_pause_s?.toFixed(2) ?? "–"} s. `,
      `Transcribed ${a.stt.local ? "on this computer" : "by a cloud service"} with ${a.stt.model} (${a.stt.device}); pauses measured with ${a.silence_method}. Click any line or mark to hear it.`),
    a.settings_from_script && Object.keys(a.settings_from_script).length
      ? h("p", { class: "muted small" }, `From the script's settings line: ${describeOverrides(a.settings_from_script)}. Every other threshold is from Settings.`)
      : null);
}

/** How a repeated miss is described, by mark kind, as in the take comparison. */
function repeatVerb(kind: string): string {
  return kind === "/" || kind === "//" ? "Came up short" : kind === "section" ? "Went off budget"
    : kind === "DEFINE" ? "Went undefined" : "Missed this mark";
}

/** Up to three marks to work on next, written by code from the measurements (no model). */
function focusCard(a: Analysis): HTMLElement | null {
  const f = a.focus;
  if (!f) return null;
  return h("section", { class: "card focus" },
    h("h3", {}, "Focus for the next take"),
    f.items.length
      ? h("ol", {}, ...f.items.map((it) => h("li", {}, statusChip(it.status, it.kind === "section" ? "section" : it.kind),
        it.text, it.repeat >= 2 ? h("span", { class: "muted small" }, ` ${repeatVerb(it.kind)} in ${it.repeat} of ${it.takes} takes of this script.`) : null)))
      : h("p", {}, f.note ?? ""),
    h("p", { class: "muted small" }, "Written by the app from your numbers, no model involved: marks missed in two or more takes first, then this take's largest divergences."));
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
  const status = h("p", { class: "muted small", role: "status" });
  const btn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    btn.setAttribute("disabled", "");
    status.textContent = "Reading your measurements…";
    try {
      state.setAnalysis(await api.coach(a.take_id));
      onRefresh();
    } catch (err) {
      status.textContent = `Failed: ${(err as Error).message}`;
      btn.removeAttribute("disabled");
    }
  } }, c ? "Refresh suggestions" : "Suggestions based on your measurements") as HTMLButtonElement;
  const llm = state.health?.llm;
  if (!llm?.available) {
    return h("section", { class: "card muted small" }, "Model-written suggestions need an ANTHROPIC_API_KEY on the server. The model would read only the measured numbers above, never the audio."
      + (a.focus ? " The focus list above needs no key." : ""));
  }
  const body = c
    ? (c.all_met && !c.suggestions.length
      ? h("p", {}, "Everything met its marks in this take. Nothing to suggest.")
      : h("ul", {}, ...c.suggestions.map((s) => h("li", {}, s.text, s.metric ? h("span", { class: "muted small" }, ` (${s.metric})`) : null))))
    : h("p", { class: "muted small" }, "At most three suggestions, each citing a measured number and the mark it concerns. No norms you did not choose.");
  return h("section", { class: "card" }, h("h3", {}, "Suggestions based on your measurements"), body, btn, status);
}

function transcriptCard(a: Analysis): HTMLElement {
  const det = h("details", { class: "card" }, h("summary", {}, "Transcript and raw timings"),
    h("p", { class: "transcript" }, ...a.transcript.words.map((w) => h("span", { class: "w", onClick: () => play(w.start), title: `${w.start.toFixed(2)}–${w.end.toFixed(2)} s` }, w.text + " "))),
    h("p", { class: "muted small" }, `${a.timing.stt_s !== undefined ? `Analysis took ${a.timing.stt_s} s of transcription.`
      : a.kind === "example" ? "No speech-to-text ran for this take: it uses the example's committed transcript."
      : "Transcription time was not recorded for this take."} Every number in this report comes from these timestamps; the full JSON is at `,
      h("a", { href: `/api/takes/${a.take_id}`, target: "_blank" }, `/api/takes/${a.take_id}`), "."));
  return det;
}

export function renderReport(root: HTMLElement): void {
  stopDrill();  // a redraw would orphan a drill recording in progress
  closeHear();
  clear(root);
  const a = state.analysis;
  if (!a) {
    const err = h("p", { class: "small warn", role: "status" });
    root.append(h("div", { class: "empty-state" },
      h("p", { class: "muted" }, "No take yet. Record one in Rehearse, open an earlier take from Takes, or load the example take to see what a report looks like."),
      exampleButton(() => renderReport(root), (msg) => { err.textContent = msg; }), err));
    return;
  }
  const p = player();
  reportUrl = a.audio_url;
  if (!p.src.endsWith(a.audio_url)) p.src = a.audio_url;

  const rerender = () => renderReport(root);
  const headStatus = h("p", { class: "small warn", role: "status" });
  const isDrill = a.kind === "drill";
  const reanalyzeBtn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    reanalyzeBtn.setAttribute("disabled", "");
    headStatus.textContent = "";
    try {
      // A drill keeps its own one-line script; only the settings change.
      state.setAnalysis(await api.reanalyze(a.take_id, isDrill ? null : state.scriptText, state.effectiveSettings()));
      rerender();
    } catch (err) {
      headStatus.textContent = `Re-analysis failed: ${(err as Error).message}`;
      reanalyzeBtn.removeAttribute("disabled");
    }
  } }, isDrill ? "Re-analyze with current settings" : "Re-analyze with current script and settings") as HTMLButtonElement;

  // Takes analyzed before the comparison existed have no ad-lib data: say so instead of implying nothing differs.
  const compared = a.lines.some((l) => l.words_differ !== undefined);
  const diff = compared && showDiff();
  const diffToggle = h("input", { type: "checkbox" }) as HTMLInputElement;
  diffToggle.checked = diff;
  diffToggle.addEventListener("change", () => {
    setShowDiff(diffToggle.checked);
    rerender();
    root.querySelector<HTMLInputElement>(".diff-toggle input")?.focus({ preventScroll: true });
  });
  const totalDiffer = a.lines.reduce((n, l) => n + (l.words_differ ?? 0), 0);

  const scriptEl = h("div", { class: "script-report" }, ...a.sections.flatMap((s) => {
    const head: HTMLElement = h("h2", { class: "section-head", onClick: () => play(s.start) }, s.name,
      h("span", { class: "muted small" }, s.status === "no_lines" ? " no script lines"
        : s.budget_label ? ` ${s.budget_label} budget · ${s.duration_label || "not found"} spoken` : ` ${s.duration_label || "not found"} spoken`),
      canDrill(a) && s.line_end > s.line_start ? drillButton(a, "section", s.index, `section ${s.name}`, () => head) : null);
    return [head, ...a.lines.filter((l) => l.section === s.index).map((l) => lineEl(a, l, diff))];
  }));

  const legend = h("div", { class: "legend muted small" },
    statusChip("met", "met your mark"), statusChip("near", "close"), statusChip("diverged", "diverged"), statusChip("unknown", "not measured"),
    " · hover, focus or click a mark for the numbers · click a line to hear it",
    compared ? h("label", { class: "diff-toggle" }, diffToggle, ` What you said vs. the script${totalDiffer ? ` (${totalDiffer} words differ)` : ""}`)
      : h("span", { class: "diff-toggle" }, "Re-analyze to compare what you said with the script (this take predates it)."));
  const diffLegend = diff ? h("p", { class: "legend muted small" },
    h("span", { class: "w dropped" }, "struck"), " = in the script, not heard · ", h("span", { class: "adlib" }, "boxed"), " = said, not in the script · ",
    h("span", { class: "w misheard" }, "dotted"), " = heard as a similar word (hover to see it)") : null;

  const tl = timelineStrip(a, (t) => play(t));
  root.append(
    h("div", { class: "report-head" },
      h("div", {}, h("h2", {}, a.kind === "example" ? h("span", { class: "mode-badge", title: "A text-to-speech recording shipped with the app, not a person" }, "Example · synthetic voice") : null,
        a.label || "Take", h("span", { class: "muted small" }, ` · ${new Date(a.created_at).toLocaleString()} · ${fmtTime(a.duration_s)}`))),
      h("div", { class: "take-actions" },
        h("button", { class: "ghost-btn", type: "button", title: "One HTML file with the recording inside: every number and tooltip printed, click a line to hear it. Works offline.",
          onClick: () => exportReport(a.take_id, (msg) => { headStatus.textContent = msg; }) }, "Export report"),
        reanalyzeBtn)),
    headStatus,
    h("section", { class: "card timeline-card" }, tl.el,
      h("p", { class: "muted small" }, "Top band: silences found by the voice-activity detector. Bars: when each script line was spoken (key lines coloured by status). Ticks: where each mark was measured. Click or use ←/→ to hear that moment.")),
    drillCard(a, async (id) => { state.setTake(await api.getAnyTake(id)); rerender(); }) ?? "",
    summaryCard(a),
    focusCard(a) ?? "",
    h("section", { class: "card" }, h("h3", {}, "Sections: budget vs. spoken"), sectionBars(a)),
    conventionsCard(a) ?? "",
    clarityCard(a) ?? "",
    legend,
    diffLegend ?? "",
    scriptEl,
    coachingCard(a, rerender),
    transcriptCard(a),
  );

  p.ontimeupdate = () => {
    if (!p.src.endsWith(a.audio_url)) return;  // another take is playing (a drill try, a comparison cell)
    const t = p.currentTime;
    tl.setTime(t);
    root.querySelectorAll<HTMLElement>(".line").forEach((el) => {
      const li = parseInt(el.dataset.line ?? "-1", 10);
      const row = a.lines[li];
      el.classList.toggle("playing", !!row && row.start !== null && row.end !== null && t >= row.start - 0.15 && t <= row.end + 0.2);
    });
  };
}
