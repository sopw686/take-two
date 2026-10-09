/** Status chips that do not rely on colour alone: every chip carries a glyph (met ✓, close ~,
 *  diverged ✗, not measured –) and a status word for screen readers. Tooltips show on hover,
 *  on keyboard focus, and stay pinned after a click until Esc or a click elsewhere. */

import { h } from "./dom";

export type Tone = "met" | "near" | "diverged" | "unknown";

const TONE: Record<string, Tone> = {
  met: "met", defined: "met", ok: "met",
  near: "near", short: "near", under: "near", close: "near", weak: "near",
  diverged: "diverged", missing: "diverged", over: "diverged", undefined: "diverged", never_spoken: "diverged",
};
const GLYPH: Record<Tone, string> = { met: "✓", near: "~", diverged: "✗", unknown: "–" };
const WORD: Record<Tone, string> = { met: "met", near: "close", diverged: "diverged", unknown: "not measured" };

export function statusTone(status: string): Tone {
  return TONE[status] ?? "unknown";
}

export function statusGlyph(status: string): string {
  return GLYPH[statusTone(status)];
}

/** The glyph, hidden from screen readers, plus the status in words for them. */
export function glyphParts(status: string, word = WORD[statusTone(status)]): HTMLElement[] {
  return [h("span", { class: "glyph", "aria-hidden": "true" }, statusGlyph(status)), h("span", { class: "sr-only" }, `${word}: `)];
}

let tipSeq = 0;

/** A status chip. With a tip it is a focusable button whose tip is its accessible description. */
export function statusChip(status: string, label: string, opts: { tip?: string; extraClass?: string; onClick?: (e: Event) => void; word?: string } = {}): HTMLElement {
  const cls = `mark st-${statusTone(status)}${opts.extraClass ? " " + opts.extraClass : ""}`;
  if (!opts.tip && !opts.onClick) return h("span", { class: cls }, ...glyphParts(status, opts.word), label);
  const id = `tip-${++tipSeq}`;
  return h("button", { type: "button", class: `${cls}${opts.tip ? " tip" : ""}`, "data-tip": opts.tip, "aria-describedby": opts.tip ? id : undefined, onClick: opts.onClick },
    ...glyphParts(status, opts.word), label, opts.tip ? h("span", { id, hidden: true }, opts.tip) : null);
}

/** Click pins a tooltip open (one at a time); Esc or a click elsewhere unpins. Installed once.
 *  Capture phase, because chips stop propagation of their own clicks (they play audio). */
export function installTipPinning(): void {
  const unpin = (except?: Element | null) => document.querySelectorAll(".tip.pinned").forEach((el) => { if (el !== except) el.classList.remove("pinned"); });
  document.addEventListener("click", (e) => {
    // Only status chips pin; other tooltips (such as suggested marks) already show their reason inline.
    const tip = (e.target as Element | null)?.closest?.("button.tip") ?? null;
    unpin(tip);
    tip?.classList.remove("tip-off");
    tip?.classList.toggle("pinned");
  }, { capture: true });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    unpin();
    // A tip shown by keyboard focus also goes away, until the chip loses focus.
    const a = document.activeElement;
    if (a?.classList.contains("tip")) {
      a.classList.add("tip-off");
      a.addEventListener("blur", () => a.classList.remove("tip-off"), { once: true });
    }
  });
}
