/** Report for an Improvise take: drills, measures grouped by what a listener hears, and the transcript
 *  annotated in place (fillers, hedges, hesitations, rising or fading endings, unclear words). */

import { api } from "./api";
import { clear, fmtClock, fmtTime, h } from "./dom";
import { play, player } from "./player";
import { state } from "./state";
import { statusChip } from "./status";
import type { ImprovAnalysis, ImprovReport, Question } from "./types";


function word(s: string): string {
  return ({ met: "within your band", near: "close to your band", diverged: "outside your band", unmeasurable: "not measurable",
    over: "over your goal", under: "under your goal", no_goal: "no goal set" } as Record<string, string>)[s] ?? s;
}

function chip(status: string, text?: string): HTMLElement {
  return statusChip(status, text ?? word(status), { word: word(status) });
}

const FOCUS: Record<string, string> = { fillers: "Fillers", confidence: "Confidence", hesitation: "Hesitation", engagement: "Engagement",
  pace: "Pace", clarity: "Clarity", time: "Time" };

function goalBar(r: ImprovReport): HTMLElement | null {
  const g = r.goal;
  if (!g.goal_s) return null;
  const maxS = Math.max(g.goal_s, g.spoken_s) * 1.05;
  const label = `${fmtClock(Math.round(g.spoken_s))} spoken of a ${fmtClock(g.goal_s)} goal${g.delta_s !== null ? ` (${g.delta_s >= 0 ? "+" : "−"}${Math.abs(g.delta_s).toFixed(0)} s)` : ""}`;
  return h("section", { class: "card" },
    h("div", { class: "section-bar-head" }, h("strong", {}, "Time goal"), h("span", { class: "muted small" }, label, " ", chip(g.status))),
    h("div", { class: "bar-track" },
      h("div", { class: "bar-budget", style: `width:${(g.goal_s / maxS) * 100}%` }),
      h("div", { class: `bar-actual st-${g.status}`, style: `width:${(g.spoken_s / maxS) * 100}%` })));
}

function row(label: string, value: string, status: string, onClick?: () => void, extra?: HTMLElement | null): HTMLElement {
  return h("div", { class: `metric${onClick ? " clickable" : ""}`, onClick },
    h("div", { class: "metric-head" }, h("span", { class: "metric-label" }, label), chip(status)),
    h("div", { class: "metric-value" }, value),
    extra ?? null);
}

function counts(items: { text?: string; phrase?: string }[], key: "text" | "phrase"): string {
  const m = new Map<string, number>();
  for (const it of items) {
    const k = (it[key] ?? "").toLowerCase().replace(/[.,!?]/g, "");
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, n]) => `“${k}” ×${n}`).join(", ");
}

function sparkWindows(r: ImprovReport): HTMLElement | null {
  const w = r.pace.windows;
  if (w.length < 2) return null;
  const max = Math.max(...w.map((x) => x.wpm), r.pace.band[1]) * 1.1;
  const [lo, hi] = r.pace.band;
  const svg = `<svg viewBox="0 0 ${w.length * 14} 40" preserveAspectRatio="none" class="spark" role="img" aria-label="words per minute per 15 seconds">
    <rect x="0" y="${40 - (hi / max) * 40}" width="${w.length * 14}" height="${((hi - lo) / max) * 40}" class="spark-band"/>
    ${w.map((x, i) => `<rect x="${i * 14 + 2}" y="${40 - (x.wpm / max) * 40}" width="10" height="${(x.wpm / max) * 40}" class="spark-bar"><title>${fmtClock(x.start)}: ${x.wpm.toFixed(0)} wpm</title></rect>`).join("")}
  </svg>`;
  return h("div", { class: "spark-wrap", style: `max-width:${w.length * 36}px`, html: svg });
}

function pitchStrip(r: ImprovReport): HTMLElement | null {
  const c = r.engagement.contour.filter((p) => p[1] !== null) as [number, number][];
  if (c.length < 5) return null;
  const t0 = r.engagement.contour[0][0];
  const t1 = r.engagement.contour[r.engagement.contour.length - 1][0] || t0 + 1;
  const st = c.map(([, f]) => 12 * Math.log2(f / 100));
  const lo = Math.min(...st) - 1;
  const hi = Math.max(...st) + 1;
  const W = 600;
  const pts = c.map(([t], i) => `${(((t - t0) / (t1 - t0)) * W).toFixed(1)},${(40 - ((st[i] - lo) / (hi - lo)) * 40).toFixed(1)}`);
  const svg = `<svg viewBox="0 0 ${W} 40" preserveAspectRatio="none" class="spark pitch" role="img" aria-label="pitch over the take"><polyline points="${pts.join(" ")}" class="pitch-line"/></svg>`;
  const el = h("div", { class: "spark-wrap", html: svg, title: "Pitch over the take (click to hear that moment)" });
  el.addEventListener("click", (e) => {
    const rect = el.getBoundingClientRect();
    play(t0 + ((e.clientX - rect.left) / rect.width) * (t1 - t0));
  });
  return el;
}

function metrics(a: ImprovAnalysis): HTMLElement {
  const r = a.improv;
  const { pace: p, fillers: f, hesitation: hs, hedges: hd, tone: t, clarity: c, engagement: e } = r;
  const pitchNote = e.pitch_backend ? null : h("p", { class: "muted small" }, "No pitch backend is installed, so pitch measures are not available.");
  const n = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? "–" : x.toFixed(d));
  return h("div", { class: "metric-grid" },
    h("section", { class: "card" }, h("h3", {}, "Pace"),
      row("Overall", `${n(p.overall_wpm, 0)} words per minute; your band is ${p.band[0]}–${p.band[1]}.`, p.status, undefined, sparkWindows(r))),
    h("section", { class: "card" }, h("h3", {}, "Fillers and hesitation"),
      row("Fillers", `${f.count} in ${r.words} words (${n(f.per_100)} per 100; your band ≤ ${f.target_per_100}).${f.items.length ? " " + counts(f.items, "text") : ""}`, f.status),
      row("Hesitation", `${hs.pauses.length} pauses of ${hs.threshold_s}+ s and ${hs.restarts.length} restarts: ${n(hs.per_min)} per minute (your band ≤ ${hs.target_per_min}).`, hs.status),
      h("p", { class: "muted small" }, f.note)),
    h("section", { class: "card" }, h("h3", {}, "Confidence"),
      row("Hedges", `${hd.count} (${n(hd.per_100)} per 100 words; your band ≤ ${hd.target_per_100}).${hd.items.length ? " " + counts(hd.items, "phrase") : ""}`, hd.status),
      t.pitch_available
        ? row("Rising endings", `${t.uptalk.length} of ${t.uptalk_measured} statements rose by ${t.uptalk_threshold_st}+ semitones on the last word (uptalk can make statements sound like questions). Your band ≤ ${t.share_target_pct}%.`, t.uptalk_status,
          t.uptalk[0] ? () => play(t.uptalk[0].sentence_start) : undefined)
        : row("Rising endings", "Pitch not available.", "unmeasurable"),
      row("Fading endings", `${t.trail_off.length} of ${t.trail_measured} sentences dropped ${t.trail_threshold_db}+ dB on the last word. Your band ≤ ${t.share_target_pct}%.`, t.trail_status,
        t.trail_off[0] ? () => play(t.trail_off[0].sentence_start) : undefined)),
    h("section", { class: "card" }, h("h3", {}, "Clarity ", h("span", { class: "muted small" }, "(proxy)")),
      row("Hard to catch", c.available ? `${c.unclear.length} words (${n(c.unclear_pct)}%; your band ≤ ${c.target_pct}%).${c.unclear.length ? " " + c.unclear.slice(0, 6).map((u) => `“${u.text.trim()}”`).join(", ") : ""}` : "Not available with this transcriber.", c.status),
      h("p", { class: "muted small" }, c.note)),
    h("section", { class: "card wide" }, h("h3", {}, "Engagement"),
      h("div", { class: "metric-cols" },
        row("Pitch range", `${n(e.pitch_range_st)} semitones (your floor ${e.pitch_floor_st}). Narrow range sounds flat or read-aloud.`, e.pitch_status, undefined, pitchStrip(r)),
        row("Loudness variation", `${n(e.loudness_var_db)} dB spread across words (your floor ${e.loudness_target_db}).`, e.loudness_status),
        row("Pace variation", e.pace_var_pct === null ? "Needs at least 45 s of speech (three 15-second stretches)."
          : `${n(e.pace_var_pct, 0)}% across 15-second stretches (your floor ${e.pace_var_target_pct}%).`, e.pace_var_status),
        row("Pauses between sentences", `${e.purposeful_pauses.length} deliberate pauses (${n(e.purposeful_per_min)} per minute). Silence before a key line builds suspense.`,
          e.purposeful_pauses.length ? "met" : "near", e.purposeful_pauses[0] ? () => play(e.purposeful_pauses[0].start - 1.5) : undefined),
        row("Opening energy", e.opening.db_delta === null ? "Needs at least 20 s of speech."
          : `First 10 s were ${Math.abs(e.opening.db_delta).toFixed(1)} dB ${e.opening.db_delta < 0 ? "quieter" : "louder"} than the rest${e.opening.f0_delta_pct !== null ? `, pitch ${e.opening.f0_delta_pct >= 0 ? "+" : ""}${e.opening.f0_delta_pct.toFixed(0)}%` : ""}.`,
          e.opening.status, () => play(r.span[0] ?? 0))),
      pitchNote),
  );
}

interface Ann { cls: Set<string>; tips: string[]; after: HTMLElement[] }

function transcriptCard(a: ImprovAnalysis): HTMLElement {
  const r = a.improv;
  const words = a.transcript.words;
  const ann: Ann[] = words.map(() => ({ cls: new Set<string>(), tips: [], after: [] }));
  const mark = (i: number, cls: string, tip: string) => { if (ann[i]) { ann[i].cls.add(cls); ann[i].tips.push(tip); } };
  const after = (i: number, el: HTMLElement) => { if (ann[i]) ann[i].after.push(el); };
  for (const f of r.fillers.items) for (let k = f.i; k <= f.j; k++) mark(k, "a-filler", "Filler");
  for (const x of r.hedges.items) for (let k = x.i; k <= x.j; k++) mark(k, "a-hedge", `Hedge: “${x.phrase}”`);
  for (const x of r.hesitation.restarts) for (let k = x.i; k <= x.j; k++) mark(k, "a-restart", x.kind === "fragment" ? "Cut-off word" : "Repeated word (restart)");
  for (const u of r.clarity.unclear) mark(u.i, "a-unclear", `Hard to catch (recognizer confidence ${(u.prob * 100).toFixed(0)}%)`);
  for (const u of r.tone.uptalk) after(u.i, statusChip("near", "↗", { word: "rising ending", tip: `Statement ended rising ${u.rise_st} semitones. Click to hear the sentence.`,
    onClick: (e) => { e.stopPropagation(); play(u.sentence_start); } }));
  for (const u of r.tone.trail_off) after(u.i, statusChip("near", "↘", { word: "fading ending", tip: `Last word ${u.drop_db} dB quieter than the rest of the sentence. Click to hear the sentence.`,
    onClick: (e) => { e.stopPropagation(); play(u.sentence_start); } }));
  for (const p of r.hesitation.pauses) after(p.after_i, statusChip("diverged", `⏸ ${p.duration_s.toFixed(1)}s`, { word: "hesitation", extraClass: "pause",
    tip: `${p.duration_s.toFixed(1)} s silence ${p.kind ?? ""} between “${p.before}” and “${p.after}”.`,
    onClick: (e) => { e.stopPropagation(); play(p.start - 1); } }));
  for (const p of r.engagement.purposeful_pauses) after(p.after_i, statusChip("met", `${p.duration_s.toFixed(1)}s`, { word: "deliberate pause", extraClass: "pause",
    tip: `${p.duration_s.toFixed(1)} s pause between sentences: lets the previous line land.`,
    onClick: (e) => { e.stopPropagation(); play(p.start - 1); } }));

  const body = h("p", { class: "transcript annotated" }, ...words.flatMap((w, i) => {
    const x = ann[i];
    const tip = x.tips.join(" · ");
    const span = h("span", { class: `w ${[...x.cls].join(" ")}${tip ? " tip" : ""}`, "data-i": i, "data-tip": tip || undefined,
      onClick: () => play(w.start) }, w.text.trim());
    return [span, " ", ...x.after.flatMap((el) => [el, " "])];
  }));
  const legend = h("div", { class: "legend muted small" },
    h("span", { class: "w a-filler" }, "filler"), h("span", { class: "w a-hedge" }, "hedge"), h("span", { class: "w a-restart" }, "restart"),
    h("span", { class: "w a-unclear" }, "hard to catch"), statusChip("near", "↗ rising"), statusChip("near", "↘ fading"),
    statusChip("diverged", "⏸ hesitation", { extraClass: "pause" }), statusChip("met", "deliberate pause", { extraClass: "pause" }),
    " · click any word to hear it");
  return h("section", { class: "card" }, h("h3", {}, "What you said"), legend, r.words ? body : h("p", { class: "muted" }, "No speech was recognized."));
}

function drillsCard(r: ImprovReport): HTMLElement {
  return h("section", { class: "card drills" }, h("h3", {}, "What to practise next"),
    r.drills.length
      ? h("ol", {}, ...r.drills.map((d) => h("li", {}, statusChip(d.status, FOCUS[d.focus] ?? d.focus, { word: word(d.status) }), d.text)))
      : h("p", {}, "Every measure is within your bands. Try a longer goal or a harder topic."),
    h("p", { class: "muted small" }, "Written by the app from your numbers, no model involved."));
}

function coachCard(a: ImprovAnalysis, rerender: () => void, autoContent: boolean): HTMLElement {
  const llm = state.health?.llm;
  if (!llm?.available) {
    return h("section", { class: "card muted small" }, "Model coaching and the content review need an ANTHROPIC_API_KEY on the server. The drills above are always available.");
  }
  const run = async (content: boolean) => {
    btn.setAttribute("disabled", "");
    btnContent.setAttribute("disabled", "");
    status.textContent = content ? "Reading your measurements and transcript…" : "Reading your measurements…";
    try {
      state.setImprov(await api.coachImprov(a.take_id, content));
      rerender();
    } catch (err) {
      status.textContent = `Failed: ${(err as Error).message}`;
      btn.removeAttribute("disabled");
      btnContent.removeAttribute("disabled");
    }
  };
  const status = h("p", { class: "muted small", role: "status" }, "");
  const btn = h("button", { class: "ghost-btn", type: "button", onClick: () => void run(false) }, a.coaching ? "Refresh delivery coaching" : "Coach my delivery") as HTMLButtonElement;
  const btnContent = h("button", { class: "ghost-btn", type: "button", onClick: () => void run(true) }, a.content_review ? "Refresh with content review" : "Coach delivery + review content") as HTMLButtonElement;
  const c = a.coaching;
  const cr = a.content_review;
  // The user chose "Delivery + content" before recording: fetch it without another click.
  if (autoContent) queueMicrotask(() => void run(true));
  const verdictCls = (v: string) => (v === "strong" || v === "present" ? "met" : v === "weak" ? "near" : "diverged");
  return h("section", { class: "card" },
    h("h3", {}, `Coaching from ${llm.provider}`),
    c ? (c.suggestions.length ? h("ul", {}, ...c.suggestions.map((s) => h("li", {}, s.text, s.metric ? h("span", { class: "muted small" }, ` (${s.metric})`) : null)))
      : h("p", { class: "muted small" }, c.reason ?? "No suggestions.")) : null,
    cr ? h("div", { class: "content-review" },
      h("h3", {}, "Content"),
      cr.items.length ? h("ul", {}, ...cr.items.map((it) => h("li", {},
        statusChip(verdictCls(it.verdict), `${it.label}: ${it.verdict}`, { word: it.verdict }), it.note,
        it.evidence ? h("button", { class: "quote linklike", type: "button", onClick: () => play(it.evidence?.start) }, `“${it.evidence.quote}”`) : null)))
        : h("p", { class: "muted small" }, cr.reason ?? "No review."),
      cr.dropped?.length ? h("p", { class: "muted small" }, `Not shown because the quoted words could not be found in your transcript: ${cr.dropped.join(", ")}.`) : null,
      cr.rewrite_opening ? h("p", { class: "rewrite" }, h("span", { class: "muted small" }, "Try opening with: "), cr.rewrite_opening) : null) : null,
    !c && !cr ? h("p", { class: "muted small" }, "At most three suggestions, each citing a measured number. The model sees numbers and, for the content review, the transcript text; never audio.") : null,
    h("div", { class: "dialog-actions" }, btn, btnContent),
    status);
}

function trendCard(a: ImprovAnalysis): HTMLElement | null {
  const hist = a.history ?? [];
  if (!hist.length) return null;
  const r = a.improv;
  const rows = [...hist, { take_id: a.take_id, created_at: a.created_at, topic: a.topic, wpm: r.pace.overall_wpm,
    fillers_per_100: r.fillers.per_100, hedges_per_100: r.hedges.per_100, hesitations_per_min: r.hesitation.per_min,
    pitch_range_st: r.engagement.pitch_range_st }];
  const v = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? "–" : x.toFixed(d));
  return h("section", { class: "card" }, h("h3", {}, "Your recent Improvise takes"),
    h("div", { class: "cmp-wrap" }, h("table", { class: "cmp" },
      h("thead", {}, h("tr", {}, ...["When", "Topic", "wpm", "fillers /100", "hedges /100", "hesitations /min", "pitch range (st)"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...rows.map((x) => h("tr", { class: x.take_id === a.take_id ? "current" : "" },
        h("td", {}, x.take_id === a.take_id ? "this take" : new Date(x.created_at ?? "").toLocaleDateString()),
        h("td", {}, x.topic ?? ""), h("td", {}, v(x.wpm, 0)), h("td", {}, v(x.fillers_per_100)), h("td", {}, v(x.hedges_per_100)),
        h("td", {}, v(x.hesitations_per_min)), h("td", {}, v(x.pitch_range_st))))))));
}

export function renderImprovReport(root: HTMLElement, again: (topic: string, question?: Question | null) => void): void {
  clear(root);
  const a = state.improv;
  if (!a) return;
  const p = player();
  if (!p.src.endsWith(a.audio_url)) p.src = a.audio_url;
  const rerender = () => renderImprovReport(root, again);
  const headStatus = h("p", { class: "small warn", role: "status" });
  const reBtn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    reBtn.setAttribute("disabled", "");
    headStatus.textContent = "";
    try {
      state.setImprov(await api.reanalyzeImprov(a.take_id, state.effectiveSettings()));
      rerender();
    } catch (err) {
      headStatus.textContent = `Re-analysis failed: ${(err as Error).message}`;
      reBtn.removeAttribute("disabled");
    }
  } }, "Re-analyze with current settings") as HTMLButtonElement;

  root.append(
    h("div", { class: "report-head" },
      h("div", {}, h("h2", {}, h("span", { class: "mode-badge" }, a.question ? "Question" : "Improvise"), " ", a.topic),
        a.question?.line_index !== undefined && a.question?.line_index !== null
          ? h("p", { class: "muted small" }, `${a.question.tag ? a.question.tag[0].toUpperCase() + a.question.tag.slice(1) + " question" : "Question"} about line ${a.question.line_index + 1}: “${a.question.line_text ?? ""}”`) : null,
        h("span", { class: "muted small" }, `${a.label ? a.label + " · " : ""}${new Date(a.created_at).toLocaleString()} · ${fmtTime(a.duration_s)}`)),
      h("div", { class: "head-actions" },
        h("button", { class: "ghost-btn", type: "button", onClick: () => again(a.topic, a.question) }, a.question ? "Answer it again" : "Try this topic again"),
        reBtn)),
    headStatus,
    h("section", { class: "summary" }, h("ul", {}, ...a.summary.map((s) => h("li", {}, s))),
      h("p", { class: "muted small" }, `Transcribed ${a.stt.local ? "on this computer" : "by a cloud service"} with ${a.stt.model}; pauses from ${a.silence_method}; pitch from ${a.improv.engagement.pitch_backend ?? "nothing (not installed)"}. Bands are yours to change in Settings.`)),
    goalBar(a.improv) ?? "",
    drillsCard(a.improv),
    metrics(a),
    transcriptCard(a),
    coachCard(a, rerender, a.content && !a.content_review),
    trendCard(a) ?? "",
    h("p", { class: "muted small" }, "Full measurements: ", h("a", { href: `/api/takes/${a.take_id}`, target: "_blank" }, `/api/takes/${a.take_id}`)),
  );

  const spans = root.querySelectorAll<HTMLElement>(".annotated .w");
  p.ontimeupdate = () => {
    const t = p.currentTime;
    spans.forEach((el) => {
      const w = a.transcript.words[parseInt(el.dataset.i ?? "-1", 10)];
      el.classList.toggle("playing", !!w && t >= w.start - 0.05 && t <= w.end + 0.05);
    });
  };
}
