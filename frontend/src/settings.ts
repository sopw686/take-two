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

const IMPROV_FIELDS: Field[] = [
  { key: "improv_goal_tolerance_pct", label: "Time goal tolerance (%)", step: 1, min: 0, max: 100, help: "Within this much of the goal counts as met (never below 5 s)." },
  { key: "improv_filler_per_100", label: "Fillers per 100 words, at most", step: 0.5, min: 0, max: 100, help: "um, uh, “you know”, “I mean”, “like,”. A lower bound: the recognizer drops some." },
  { key: "improv_hedge_per_100", label: "Hedges per 100 words, at most", step: 0.5, min: 0, max: 100, help: "“I think”, “maybe”, “kind of”, “I guess”…" },
  { key: "improv_hesitation_pause_s", label: "Hesitation pause (s)", step: 0.1, min: 0.3, max: 10, help: "A silence this long inside a sentence (or over 3 s between sentences) counts as hesitation." },
  { key: "improv_hesitations_per_min", label: "Hesitations per minute, at most", step: 0.5, min: 0, max: 60, help: "Hesitation pauses plus restarts (“I I”, cut-off words)." },
  { key: "improv_uptalk_st", label: "Rising ending threshold (semitones)", step: 0.5, min: 0.5, max: 12, help: "A statement whose last word rises this much counts as a rising ending." },
  { key: "improv_trail_db", label: "Fading ending threshold (dB)", step: 0.5, min: 1, max: 30, help: "A last word this much quieter than its sentence counts as fading." },
  { key: "improv_tone_share_pct", label: "Rising / fading endings, at most (% of sentences)", step: 5, min: 0, max: 100, help: "Some are natural; this is how many you accept." },
  { key: "improv_clarity_prob", label: "“Hard to catch” below recognizer confidence", step: 0.05, min: 0.05, max: 0.95, help: "Per-word confidence from Whisper. A proxy for mumbling, not a pronunciation score." },
  { key: "improv_unclear_pct", label: "Hard-to-catch words, at most (%)", step: 0.5, min: 0, max: 100, help: "" },
  { key: "improv_pitch_range_st", label: "Pitch range, at least (semitones)", step: 0.5, min: 0.5, max: 24, help: "10th to 90th percentile of your pitch. Below this sounds flat." },
  { key: "improv_loudness_var_db", label: "Loudness variation, at least (dB)", step: 0.5, min: 0, max: 20, help: "Spread of word loudness." },
  { key: "improv_pace_var_pct", label: "Pace variation, at least (%)", step: 1, min: 0, max: 100, help: "How much your words per minute change across 15-second stretches." },
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
  const iwMin = h("input", { type: "number", step: "5", min: "40", max: "400", value: String(cur.improv_wpm_min) }) as HTMLInputElement;
  const iwMax = h("input", { type: "number", step: "5", min: "40", max: "400", value: String(cur.improv_wpm_max) }) as HTMLInputElement;
  const emph = h("input", { type: "checkbox" }) as HTMLInputElement;
  emph.checked = cur.emphasis_enabled;

  const dlg = h("dialog", { class: "settings-dialog" }) as HTMLDialogElement;
  // A blank or out-of-range field must not reach the server: NaN serializes to null and every take would fail.
  const num = (inp: HTMLInputElement, fallback: number): number => {
    const v = parseFloat(inp.value);
    return Number.isFinite(v) ? Math.min(parseFloat(inp.max), Math.max(parseFloat(inp.min), v)) : fallback;
  };
  const save = () => {
    const next: Settings = { ...cur };
    for (const [k, inp] of inputs) (next as unknown as Record<string, number>)[k] = num(inp, cur[k] as number);
    next.conventions_enabled = conv.checked;
    const lo = num(wpmMin, cur.conventions_wpm_min);
    const hi = num(wpmMax, cur.conventions_wpm_max);
    next.conventions_wpm_min = Math.min(lo, hi);
    next.conventions_wpm_max = Math.max(lo, hi);
    next.conventions_filler_per_100 = num(filler, cur.conventions_filler_per_100);
    next.emphasis_enabled = emph.checked;
    const ilo = num(iwMin, cur.improv_wpm_min);
    const ihi = num(iwMax, cur.improv_wpm_max);
    next.improv_wpm_min = Math.min(ilo, ihi);
    next.improv_wpm_max = Math.max(ilo, ihi);
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
    h("h3", {}, "Improvise reference bands"),
    h("p", { class: "muted small" }, "Improvise has no marks, so it compares each take with these bands. They are starting points, not rules; set them to what you are practising for."),
    h("div", { class: "settings-grid" },
      h("label", { class: "setting" }, h("span", {}, "Pace band min (wpm)"), iwMin),
      h("label", { class: "setting" }, h("span", {}, "Pace band max (wpm)"), iwMax),
      ...IMPROV_FIELDS.map(row)),
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
