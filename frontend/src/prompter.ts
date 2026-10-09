/** Teleprompter for the Rehearse tab: the script in large type with its marks drawn, and a highlight
 *  that follows the *planned* position (each section's budget spread over its lines by word count).
 *  It never listens to the voice: Space and the arrow keys re-anchor the plan when the speaker is
 *  ahead or behind, and scrolling by hand pauses the auto-scroll for a few seconds. */

import { fmtClock, h } from "./dom";
import { parseScript, planLines, type ScriptLine } from "./scriptinfo";

const PREFS_KEY = "taketwo.prompter";
const PX = { min: 18, max: 48, step: 2, initial: 28 };
const MANUAL_PAUSE_MS = 4000;
const NEXT = new Set([" ", "ArrowDown", "ArrowRight", "PageDown"]);
const PREV = new Set(["ArrowUp", "ArrowLeft", "PageUp"]);
const SCROLL_KEYS = new Set(["Home", "End"]);

function loadPx(): number {
  try {
    const v = (JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") as { px?: number }).px;
    return typeof v === "number" ? Math.min(PX.max, Math.max(PX.min, v)) : PX.initial;
  } catch {
    return PX.initial;
  }
}
function savePx(px: number): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify({ px })); } catch { /* storage may be unavailable */ }
}

function isTextField(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return true;
  return el instanceof HTMLInputElement && !["checkbox", "radio", "button", "submit", "range", "file", "color"].includes(el.type);
}

function norm(w: string): string {
  return w.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

/** Words of a line with the first occurrence of each [DEFINE] term underlined; a term that is not in
 *  the line stays a chip where the tag was written. */
function renderLine(line: ScriptLine): HTMLElement {
  const words = line.parts.flatMap((p, i) => (p.kind === "word" ? [{ i, key: norm(p.text) }] : []));
  const underline = new Map<number, string>();
  const placed = new Set<number>();
  // Loose word equality as in define.py: exact, or a shared 5-letter stem with a short suffix difference.
  const same = (a: string, b: string) => a === b || (a.length >= 5 && b.length >= 5 && a.slice(0, 5) === b.slice(0, 5) && Math.abs(a.length - b.length) <= 3);
  line.parts.forEach((p, di) => {
    if (p.kind !== "define") return;
    const needle = p.term.split(/\s+/).map(norm).filter(Boolean);
    // An exact occurrence wins over an earlier loose one.
    for (const eq of [(a: string, b: string) => a === b, same]) {
      for (let k = 0; needle.length && k + needle.length <= words.length; k++) {
        if (needle.every((n, j) => eq(words[k + j].key, n))) {
          needle.forEach((_, j) => underline.set(words[k + j].i, p.term));
          placed.add(di);
          return;
        }
      }
    }
  });
  const el = h("p", { class: `pl${line.isKey ? " pl-key" : ""}`, "data-i": line.index });
  if (line.isKey) el.append(h("span", { class: "pl-tag", title: "[KEY]: slower than your median, then a pause" }, "KEY"), " ");
  line.parts.forEach((p, i) => {
    if (p.kind === "word") {
      const term = underline.get(i);
      const cls = [term ? "pl-define" : "", p.emph ? "pl-emph" : ""].filter(Boolean).join(" ");
      el.append(cls ? h("span", { class: cls, title: term ? `Define “${term}” aloud here` : undefined }, p.text) : p.text, " ");
    } else if (p.kind === "pause") {
      el.append(h("span", { class: `pl-gap ${p.long ? "long" : "short"}`, role: "img",
        "aria-label": p.long ? "long pause" : "short pause", title: p.long ? "// long pause" : "/ short pause" }, p.long ? "//" : "/"), " ");
    } else if (!placed.has(i)) {
      el.append(h("span", { class: "pl-define-chip", title: "Define this term aloud" }, `define: ${p.term}`), " ");
    }
  });
  return el;
}

export interface Prompter {
  el: HTMLElement;
  /** Recording started: highlight line 1 and, with budgets, follow the plan. */
  start(): void;
  stop(): void;
  /** Called with the elapsed recording time a few times a second. */
  tick(elapsed: number): void;
}

export function createPrompter(text: string, signal: AbortSignal): Prompter {
  const script = parseScript(text);
  const plan = planLines(script);
  const lineEls: HTMLElement[] = [];
  const scroller = h("div", { class: "prompter-scroll", tabindex: "0", "aria-label": "Script" });
  for (const s of script.sections) {
    if (s.name || s.budget_s !== null) {
      scroller.append(h("h3", { class: "pl-section" }, s.name || "Untitled",
        h("span", { class: "muted" }, s.budget_s !== null ? ` · ${fmtClock(s.budget_s)}` : " · no budget")));
    }
    for (const l of s.lines) {
      const el = renderLine(l);
      lineEls[l.index] = el;
      scroller.append(el);
    }
  }
  if (!script.lines.length) scroller.append(h("p", { class: "muted" }, "The script has no lines yet."));

  let px = loadPx();
  const root = h("div", { class: "prompter" });
  root.style.setProperty("--prompter-px", `${px}px`);
  const sizeLabel = h("span", { class: "muted small", "aria-live": "polite" }, `${px} px`);
  const setPx = (next: number) => {
    px = Math.min(PX.max, Math.max(PX.min, next));
    root.style.setProperty("--prompter-px", `${px}px`);
    sizeLabel.textContent = `${px} px`;
    savePx(px);
    if (active >= 0) scrollTo(active, "auto");
  };
  const smaller = h("button", { class: "ghost-btn small", type: "button", "aria-label": "Smaller text", onClick: () => setPx(px - PX.step) }, "A−");
  const larger = h("button", { class: "ghost-btn small", type: "button", "aria-label": "Larger text", onClick: () => setPx(px + PX.step) }, "A+");
  const basis = plan
    ? "Highlight follows your plan, not your voice: each section's budget spread over its lines. Space or ↓ moves it on, ↑ moves it back."
    : "No auto-scroll: give every section a budget (## Name [m:ss]) to have the highlight follow your plan. While recording, Space or ↓ moves it on, ↑ moves it back.";
  const note = h("span", { class: "muted small prompter-note" }, basis);
  root.append(h("div", { class: "prompter-bar" }, note, h("span", { class: "spacer" }), smaller, sizeLabel, larger), scroller);

  let recording = false;
  let active = -1;
  let offset = 0;           // seconds: plan time = elapsed - offset (moved by the keys)
  let lastElapsed = 0;
  let pausedUntil = 0;      // manual scroll pauses the auto-scroll until then
  let pausePending = false;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

  function scrollTo(i: number, behavior: ScrollBehavior = reduced ? "auto" : "smooth"): void {
    const el = lineEls[i];
    if (!el) return;
    scroller.scrollTo({ top: Math.max(0, el.offsetTop - scroller.clientHeight * 0.35), behavior });
  }
  function highlight(i: number, follow: boolean): void {
    if (i === active) return;
    lineEls[active]?.classList.remove("pl-now");
    lineEls[active]?.removeAttribute("aria-current");
    active = i;
    lineEls[i]?.classList.add("pl-now");
    lineEls[i]?.setAttribute("aria-current", "true");
    if (follow && performance.now() >= pausedUntil) scrollTo(i);
  }
  function planIndex(t: number): number {
    if (!plan) return active;
    let k = 0;
    while (k + 1 < plan.length && plan[k + 1].t0 <= t) k++;
    return k;
  }
  function showOffset(): void {
    // How far the line the speaker chose is from where the plan is now, in their own budget's terms.
    const s = Math.round(offset);
    const where = s === 0 ? "on" : `${fmtClock(Math.abs(s))} ${s > 0 ? "behind" : "ahead of"}`;
    const text = `Highlight follows your plan from the line you chose (${where} your plan), not your voice. Space or ↓ moves it on, ↑ moves it back.`;
    if (note.textContent !== text) note.textContent = text;
  }
  function move(d: number): void {
    if (!script.lines.length) return;
    let k = Math.min(script.lines.length - 1, Math.max(0, (active < 0 ? 0 : active) + d));
    // A line with no planned time (a [0:00] section) could never stay highlighted: step past it.
    while (plan && plan[k].t1 <= plan[k].t0 && k + d >= 0 && k + d < script.lines.length) k += d;
    if (plan) {
      offset = lastElapsed - plan[k].t0;
      showOffset();
    }
    pausedUntil = 0;
    pausePending = false;
    highlight(k, false);
    scrollTo(k);
  }
  const pauseAutoScroll = () => {
    if (!recording || !plan) return;  // without a plan there is no auto-scroll to pause
    pausedUntil = performance.now() + MANUAL_PAUSE_MS;
    pausePending = true;
  };
  for (const ev of ["wheel", "touchmove", "pointerdown"]) scroller.addEventListener(ev, pauseAutoScroll, { passive: true, signal });
  scroller.addEventListener("keydown", (e) => { if (SCROLL_KEYS.has(e.key)) pauseAutoScroll(); }, { signal });

  const onKey = (e: KeyboardEvent) => {
    if (!recording || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || isTextField(e.target)
      || (e.target as Element | null)?.closest?.("dialog")) return;
    const d = NEXT.has(e.key) ? 1 : PREV.has(e.key) ? -1 : 0;
    if (!d) return;
    // Both halves of the key press: a focused button would otherwise act on keyup (Space) and stop the take.
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "keydown") move(d);
  };
  window.addEventListener("keydown", onKey, { capture: true, signal });
  window.addEventListener("keyup", onKey, { capture: true, signal });

  return {
    el: root,
    start() {
      recording = true;
      offset = 0;
      lastElapsed = 0;
      pausedUntil = 0;
      root.classList.add("live");
      note.textContent = basis;
      highlight(0, true);
      scrollTo(0);
    },
    stop() {
      recording = false;
      root.classList.remove("live");
    },
    tick(elapsed: number) {
      lastElapsed = elapsed;
      if (!recording) return;
      if (pausePending && performance.now() >= pausedUntil) {
        pausePending = false;
        scrollTo(active);  // the manual-scroll pause ended: come back to where the plan is
      }
      if (plan) highlight(planIndex(elapsed - offset), true);
    },
  };
}
