/** Hear it: a synthetic voice demonstrates one line, as you marked it or as the coach would say it,
 *  with the cue plan in words beside it, then Try it opens the line drill so you say it yourself and the
 *  report measures it against the same marks. Nothing plays until you press Hear it. */

import { api } from "./api";
import { h } from "./dom";
import { getSpeaker, onSegment, onVoicesChanged, stopAll, voicePicker, voicesReady } from "./speaker";
import { wordPlan } from "./schedule";
import { state } from "./state";
import type { CoachSuggestion, CuePlan } from "./types";

export const SYNTHETIC_NOTE = "Synthetic demonstration of your marks. It shows one way to do it, not the way.";
const COARSE_NOTE = "A browser voice gives coarse control of pace and pitch and none of tone: a rising or falling end is "
  + "approximated by saying the last word a little higher or lower.";

export interface HearOpts {
  lineIndex: number;
  /** The script the line belongs to; null means the script of takeId as it was recorded. */
  script: () => string | null;
  /** The take whose median is the reference pace (a report or a drill); else your latest take. */
  takeId?: string | null;
  /** Opens the line drill (hear → say → measured), or says why it cannot. */
  tryIt?: (() => void) | string;
  /** Writes accepted coach suggestions into the script; without it, Accept is not offered. */
  onScriptChange?: (text: string) => void;
}

let open: { panel: HTMLElement; close: () => void } | null = null;

/** Close the open Hear it panel and silence the voice. */
export function closeHear(): void {
  open?.close();
  open = null;
}

/** A small "Hear it" button that opens the panel right after `anchor`. */
export function hearButton(opts: HearOpts, anchor: () => HTMLElement, label = "Hear it"): HTMLElement {
  return h("button", { class: "ghost-btn small hear-btn", type: "button", title: "A synthetic voice says this line the way your marks ask, or the coach's way",
    onClick: (e) => {
      e.stopPropagation();
      const was = open?.panel;
      closeHear();
      if (was && was.previousElementSibling === anchor()) return;  // the same button toggles
      const p = hearPanel(opts);
      anchor().after(p);
      (p.querySelector("button.primary") as HTMLButtonElement | null)?.focus();
    } }, label);
}

export function hearPanel(opts: HearOpts): HTMLElement {
  closeHear();
  let version: "marked" | "coach" = "marked";
  const plans = new Map<string, CuePlan>();
  let speaking = false;

  const status = h("p", { class: "small muted", role: "status", "aria-live": "polite" });
  const textEl = h("p", { class: "hear-text" });
  const cuesEl = h("div", { class: "hear-cues" });
  const hearBtn = h("button", { class: "primary small", type: "button" }, "▶ Hear it") as HTMLButtonElement;
  const stopBtn = h("button", { class: "ghost-btn small", type: "button", disabled: true }, "■ Stop") as HTMLButtonElement;
  const group = `hear-version-${Math.random().toString(36).slice(2)}`;  // one name per panel: arrow keys move between the two
  const radios = (["marked", "coach"] as const).map((v) => {
    const r = h("input", { type: "radio", name: group, value: v }) as HTMLInputElement;
    r.checked = v === version;
    r.addEventListener("change", () => { if (r.checked) { version = v; stop(); void load(); } });
    return h("label", { class: "seg-opt" }, r, v === "marked" ? "As I marked it" : "Coach's version");
  });
  const tryBtn = typeof opts.tryIt === "function"
    ? h("button", { class: "ghost-btn small", type: "button", title: "Record your own try of this line; it is measured against the same marks",
      onClick: () => { stop(); (opts.tryIt as () => void)(); } }, "Try it")
    : h("button", { class: "ghost-btn small", type: "button", disabled: true, title: opts.tryIt ?? "" }, "Try it");

  const key = () => `${version}|${opts.script() ?? ""}|${JSON.stringify(state.effectiveSettings())}`;
  const load = async (): Promise<CuePlan | null> => {
    const k = key();
    const cached = plans.get(k);
    if (cached) { render(cached); return cached; }
    status.textContent = version === "coach" ? "Asking the coach…" : "";
    try {
      const plan = await api.hear(opts.script(), opts.lineIndex, version, state.effectiveSettings(), opts.takeId ?? null);
      plans.set(k, plan);
      render(plan);
      return plan;
    } catch (err) {
      status.textContent = `Could not build the plan: ${(err as Error).message}`;
      return null;
    }
  };

  const unsub = onSegment((i) => {
    textEl.querySelectorAll<HTMLElement>(".hear-seg").forEach((el) => {
      const on = parseInt(el.dataset.seg ?? "-1", 10) === i;
      el.classList.toggle("speaking", on);
      if (on) el.setAttribute("aria-current", "true"); else el.removeAttribute("aria-current");
    });
  });

  function render(plan: CuePlan): void {
    textEl.replaceChildren(...plan.segments.flatMap((s, i) => [
      h("span", { class: `hear-seg${s.stress ? " stress" : ""}${s.slow_word ? " slow" : ""}`, "data-seg": String(i),
        title: `${Math.round(s.wpm)} wpm${s.pitch_st ? `, pitch ${s.pitch_st > 0 ? "+" : ""}${s.pitch_st} st` : ""}${s.volume_db ? `, ${s.volume_db > 0 ? "+" : ""}${s.volume_db} dB` : ""}${s.contour !== "none" ? `, ${s.contour}ing end` : ""}${s.say_as ? `, said as ${s.say_as}` : ""}` },
        s.text, s.contour === "rise" ? " ↗" : s.contour === "fall" ? " ↘" : s.contour === "hold" ? " →" : ""),
      s.pause_after_s ? h("span", { class: "hear-gap", "aria-label": `pause ${s.pause_after_s} seconds` }, ` · ${s.pause_after_s} s · `) : " ",
    ]));
    const items: HTMLElement[] = [
      h("p", { class: "small muted" }, `Reference pace: ${plan.reference_source}.`),
    ];
    if (!plan.available) items.push(h("p", { class: "small warn" }, plan.reason ?? "The coach's version is unavailable."));
    if (plan.cues.length) {
      items.push(h("h4", {}, plan.version === "coach" ? "Your marks (kept)" : "Your marks"),
        h("ul", { class: "cue-list" }, ...plan.cues.map((c) => h("li", {}, c.text, " ",
          h("span", { class: `cue-badge ${c.checked ? "checked" : "demo"}` }, c.label)))));
    }
    if (plan.version === "coach" && plan.available) items.push(...coachPart(plan));
    for (const n of plan.notes) items.push(h("p", { class: "small muted" }, n));
    cuesEl.replaceChildren(...items);
    const voice = getSpeaker("coach");
    const ok = voice.available();
    hearBtn.disabled = !ok.ok || !plan.segments.length || !plan.available;
    status.textContent = ok.ok ? "" : ok.reason ?? "";
  }

  function coachPart(plan: CuePlan): HTMLElement[] {
    const sugg = plan.suggestions ?? [];
    const out: HTMLElement[] = [h("h4", {}, "Coach's suggestions ", h("small", { class: "muted" }, `(${plan.provider.label})`))];
    if (!sugg.length) return out;
    const picks = new Map<number, HTMLInputElement>();
    out.push(h("ul", { class: "cue-list" }, ...sugg.map((s: CoachSuggestion) => {
      const cb = s.accept ? h("input", { type: "checkbox", "aria-label": `Accept: ${s.cue}` }) as HTMLInputElement : null;
      if (cb) { cb.checked = true; picks.set(s.id, cb); }
      return h("li", {}, cb ?? "", s.cue, " ", h("span", { class: "cue-badge suggestion" }, s.label),
        h("br"), h("small", { class: "muted" }, s.reason));
    })));
    if (plan.dropped?.length) {
      out.push(h("p", { class: "small muted" }, `Dropped by code: ${plan.dropped.map((d) => `${d.count} ${d.reason}`).join("; ")}.`));
    }
    if (picks.size && opts.onScriptChange) {
      const msg = h("span", { class: "small muted", role: "status" });
      const btn = h("button", { class: "ghost-btn small", type: "button", onClick: async () => {
        const chosen = sugg.filter((s) => picks.get(s.id)?.checked);
        const text = opts.script();
        if (!chosen.length || text === null) return;
        try {
          const r = await api.hearAccept(text, plan.line_index, chosen);
          opts.onScriptChange?.(r.text);
          msg.textContent = ` Added ${r.applied} mark${r.applied === 1 ? "" : "s"} to your script; the next take checks them.`;
          btn.setAttribute("disabled", "");
        } catch (err) {
          msg.textContent = ` Could not add them: ${(err as Error).message}`;
        }
      } }, "Accept into script");
      out.push(h("p", {}, btn, msg),
        h("p", { class: "small muted" }, "Only pauses and stressed words have a mark; contours, slowed words and pace stay a demonstration."));
    }
    return out;
  }

  const stop = () => {
    getSpeaker("coach").stop();
    speaking = false;
    stopBtn.disabled = true;
  };
  hearBtn.addEventListener("click", async () => {
    const plan = await load();
    if (!plan || !plan.segments.length) return;
    const voice = getSpeaker("coach");
    stopBtn.disabled = false;
    speaking = true;
    status.textContent = `Playing: ${version === "marked" ? "as you marked it" : "the coach's version"}, ${voice.label}.`;
    try {
      await voice.speak(plan);
      if (speaking) status.textContent = "";
    } catch (err) {
      status.textContent = `The voice could not play: ${(err as Error).message}`;
    }
    speaking = false;
    stopBtn.disabled = true;
  });
  stopBtn.addEventListener("click", () => { stop(); status.textContent = "Stopped."; });

  const panel = h("div", { class: "hear-panel", role: "group", "aria-label": `Hear it: line ${opts.lineIndex + 1}`,
    onClick: (e) => e.stopPropagation(),
    onKeydown: (e) => { if ((e as KeyboardEvent).key === "Escape") { stop(); } } },
    h("div", { class: "hear-controls" }, hearBtn,
      h("div", { class: "seg-switch", role: "radiogroup", "aria-label": "Which version" }, ...radios),
      stopBtn, tryBtn, h("span", { class: "spacer" }),
      h("button", { class: "linklike small", type: "button", onClick: () => closeHear() }, "Close")),
    textEl, cuesEl, status,
    h("p", { class: "small muted hear-note" }, SYNTHETIC_NOTE, " ", COARSE_NOTE),
    voicePicker("coach", "Coach voice"));
  open = { panel, close: () => { stop(); unsub(); panel.remove(); } };
  // Browsers load their voices a moment after the page: enable Hear it when they arrive.
  onVoicesChanged(() => { const p = plans.get(key()); if (p && panel.isConnected) render(p); });
  void load();
  return panel;
}

/** Say one word slowly, syllable by syllable, then at an ordinary pace. */
export async function sayWord(word: string, respelling: string | null, onStatus: (msg: string) => void): Promise<void> {
  stopAll();
  await voicesReady();
  const voice = getSpeaker("coach");
  const ok = voice.available();
  if (!ok.ok) { onStatus(ok.reason ?? "No voice available."); return; }
  onStatus("");
  try {
    await voice.speak(wordPlan(word, respelling));
  } catch (err) {
    onStatus(`The voice could not play: ${(err as Error).message}`);
  }
}
