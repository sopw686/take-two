/** A one-minute first-run tour of the Script tab: it marks a [KEY] line and a line with a / pause in the
 *  editor itself, explains each in the side column, and is remembered as seen once dismissed. */
import { h } from "./dom";
import { blankComments, isSectionHeader } from "./scriptinfo";
import { state } from "./state";

const KEY = "taketwo.tour";

function seen(): boolean {
  try { return localStorage.getItem(KEY) === "done"; } catch { return false; }
}
function markSeen(): void {
  try { localStorage.setItem(KEY, "done"); } catch { /* storage may be unavailable */ }
}

const KEY_LINE = /^\s*\[KEY\]/i;
const PAUSE_LINE = /(^|\s)\/(\s|$)/;

/** Raw line numbers of the first [KEY] line and the first line with a single / (not //). Comments are blanked
 *  (keeping their newlines, so numbers still match the editor) because the sample's help comment shows a / too. */
function targets(text: string): [number, number] {
  const lines = blankComments(text).split(/\r?\n/).map((l) => (isSectionHeader(l) ? "" : l));
  return [lines.findIndex((l) => KEY_LINE.test(l)), lines.findIndex((l) => PAUSE_LINE.test(l))];
}

export interface Tour { el: HTMLElement; apply(): void; restart(): void }

export function scriptTour(ta: HTMLTextAreaElement, code: HTMLElement, loadSample: () => Promise<void>): Tour {
  let step = seen() ? -1 : 0;
  const el = h("section", { class: "tour", "aria-live": "polite" });

  const finish = () => {
    markSeen();
    step = -1;
    render();
    apply();
  };
  const go = (n: number) => {
    step = n;
    render();
    apply();
  };

  function render(): void {
    el.replaceChildren();
    el.hidden = step < 0;
    if (step < 0) return;
    const st = state.effectiveSettings();
    const [keyAt, pauseAt] = targets(ta.value);
    const missing = (step === 0 && keyAt < 0) || (step === 1 && pauseAt < 0);
    const steps: [string, string][] = [
      ["A key line", `[KEY] at the start of a line marks a sentence that has to land. The report checks that you said it at least ${st.key_slower_pct}% slower than your own median rate, then paused ${st.key_pause_after_s} s. You choose both numbers in Settings.`],
      ["A pause", `A / between words asks for a short pause of at least ${st.short_pause_s} s; // asks for a long one (${st.long_pause_s} s). The report measures the real silence at that spot in your recording.`],
      ["Then record", "Rehearse shows this script as a teleprompter. Each mark comes back as met, close or diverged from what you set. There is no score. Click any mark in the report to hear that moment."],
    ];
    const [title, body] = steps[step];
    el.append(
      h("p", { class: "tour-step small muted" }, `Tour · ${step + 1} of ${steps.length}`),
      h("h3", {}, step < 2 ? h("span", { class: "tour-num" }, String(step + 1)) : null, title),
      h("p", { class: "small" }, body),
      missing ? h("p", { class: "small muted" }, "Your script has no such line yet. ",
        h("button", { class: "linklike small", type: "button", onClick: async () => { await loadSample(); go(step); } }, "Load the sample script"),
        " to see one.") : "",
      h("div", { class: "tour-actions" },
        step > 0 ? h("button", { class: "ghost-btn small", type: "button", onClick: () => go(step - 1) }, "Back") : null,
        step < steps.length - 1
          ? h("button", { class: "primary small", type: "button", onClick: () => go(step + 1) }, "Next")
          : h("button", { class: "primary small", type: "button", onClick: finish }, "Done"),
        h("span", { class: "spacer" }),
        step < steps.length - 1 ? h("button", { class: "linklike small", type: "button", onClick: finish }, "Skip the tour") : null),
    );
  }

  /** Mark the line this step is about in the editor's highlight layer, and scroll the editor to it. */
  function apply(): void {
    code.querySelectorAll(".hl-ln.tour-target").forEach((x) => {
      x.classList.remove("tour-target");
      x.removeAttribute("data-tour");
    });
    if (step < 0 || step > 1) return;
    const line = targets(ta.value)[step];
    if (line < 0) return;
    const span = code.querySelector<HTMLElement>(`.hl-ln[data-ln="${line}"]`);
    if (!span) return;
    span.classList.add("tour-target");
    span.dataset.tour = String(step + 1);
    // Both rectangles scroll together, so their difference is the line's place in the text.
    const top = span.getBoundingClientRect().top - code.getBoundingClientRect().top - 40;
    if (top < ta.scrollTop || top > ta.scrollTop + ta.clientHeight - 120) ta.scrollTop = Math.max(0, top);
  }

  render();
  return { el, apply, restart: () => go(0) };
}
