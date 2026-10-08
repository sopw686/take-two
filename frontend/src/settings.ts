import { h } from "./dom";
import { state } from "./state";
import type { Settings } from "./types";

type Field = { key: keyof Settings; label: string; step: number; min: number; max: number; help: string };

const FIELDS: Field[] = [
  { key: "short_pause_s", label: "Short pause / target (s)", step: 0.1, min: 0.1, max: 5, help: "A / mark is met when the measured silence is at least this long." },
  { key: "long_pause_s", label: "Long pause // target (s)", step: 0.1, min: 0.1, max: 10, help: "Same for //." },
  { key: "pause_near_ratio", label: "“Short” threshold (fraction of target)", step: 0.05, min: 0, max: 1, help: "Below target but above this fraction counts as short rather than missing." },
  { key: "key_slower_pct", label: "[KEY] must be slower than your median by (%)", step: 1, min: 0, max: 80, help: "Relative to the median of your own lines in the same take." },
  { key: "key_pause_after_s", label: "[KEY] pause after (s)", step: 0.1, min: 0, max: 10, help: "Silence required after a key line." },
  { key: "section_tolerance_pct", label: "Section budget tolerance (%)", step: 1, min: 0, max: 100, help: "Within this much of the budget counts as met (never below 3 s)." },
  { key: "line_min_coverage", label: "Minimum matched words per line (fraction)", step: 0.05, min: 0.1, max: 1, help: "Lines with fewer matched words are reported as not found rather than mis-scored." },
  { key: "baseline_min_words", label: "Minimum words for a line to count in your median", step: 1, min: 1, max: 20, help: "Very short lines distort the median rate." },
  { key: "min_silence_s", label: "Minimum silence to count as a pause (s)", step: 0.05, min: 0.05, max: 1, help: "Voice-activity detector granularity." },
];

export function openSettings(onChange: () => void): void {
  const cur = state.effectiveSettings();
  const inputs = new Map<keyof Settings, HTMLInputElement>();
  const row = (f: Field) => {
    const inp = h("input", { type: "number", step: String(f.step), min: String(f.min), max: String(f.max), value: String(cur[f.key]) }) as HTMLInputElement;
    inputs.set(f.key, inp);
    return h("label", { class: "setting" }, h("span", {}, f.label, h("small", { class: "muted" }, f.help)), inp);
  };
  const conv = h("input", { type: "checkbox" }) as HTMLInputElement;
  conv.checked = cur.conventions_enabled;
  const wpmMin = h("input", { type: "number", step: "5", min: "40", max: "400", value: String(cur.conventions_wpm_min) }) as HTMLInputElement;
  const wpmMax = h("input", { type: "number", step: "5", min: "40", max: "400", value: String(cur.conventions_wpm_max) }) as HTMLInputElement;
  const filler = h("input", { type: "number", step: "0.5", min: "0", max: "100", value: String(cur.conventions_filler_per_100) }) as HTMLInputElement;
  const emph = h("input", { type: "checkbox" }) as HTMLInputElement;
  emph.checked = cur.emphasis_enabled;

  const dlg = h("dialog", { class: "settings-dialog" }) as HTMLDialogElement;
  const save = () => {
    const next: Settings = { ...cur };
    for (const [k, inp] of inputs) (next as unknown as Record<string, number>)[k] = parseFloat(inp.value);
    next.conventions_enabled = conv.checked;
    next.conventions_wpm_min = parseFloat(wpmMin.value);
    next.conventions_wpm_max = parseFloat(wpmMax.value);
    next.conventions_filler_per_100 = parseFloat(filler.value);
    next.emphasis_enabled = emph.checked;
    state.setSettings(next);
    dlg.close();
    onChange();
  };
  const reset = () => {
    if (state.health) state.setSettings({ ...state.health.defaults });
    dlg.close();
    onChange();
  };
  dlg.append(
    h("h2", {}, "Settings"),
    h("p", { class: "muted small" }, "These are your targets. Change them freely; the report re-analyzes against whatever you choose."),
    h("div", { class: "settings-grid" }, ...FIELDS.map(row)),
    h("h3", {}, "Opt-in presets"),
    h("label", { class: "setting check" }, conv, h("span", {}, "Conference talk conventions", h("small", { class: "muted" }, "Off by default. Adds an overall pace band and a filler-word rate, like choosing to code-switch for a job talk. Your marks still come first."))),
    h("div", { class: "settings-grid sub" },
      h("label", { class: "setting" }, h("span", {}, "Pace band min (wpm)"), wpmMin),
      h("label", { class: "setting" }, h("span", {}, "Pace band max (wpm)"), wpmMax),
      h("label", { class: "setting" }, h("span", {}, "Fillers per 100 words, at most"), filler)),
    h("label", { class: "setting check" }, emph, h("span", {}, "Emphasis check for *word* (experimental)", h("small", { class: "muted" }, "Compares a word's loudness and pitch with the rest of its line. Unreliable on quiet microphones."))),
    h("div", { class: "dialog-actions" },
      h("button", { class: "ghost-btn", type: "button", onClick: reset }, "Reset to defaults"),
      h("span", { class: "spacer" }),
      h("button", { class: "ghost-btn", type: "button", onClick: () => dlg.close() }, "Cancel"),
      h("button", { class: "primary", type: "button", onClick: save }, "Save")),
  );
  document.body.append(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
}
