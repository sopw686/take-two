import { api } from "./api";
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
  { key: "fuzzy_match_ratio", label: "Misheard words: similarity to still match (0.6–1)", step: 0.05, min: 0.6, max: 1, help: "“leaching” for “bleaching” matches at 0.8. 1 means exact words only. Number words and un-/in- opposites never match loosely." },
  { key: "fuzzy_min_chars", label: "Misheard words: shortest word matched loosely", step: 1, min: 3, max: 10, help: "Shorter words must match exactly." },
  { key: "paraphrase_min_words_pct", label: "Paraphrased line: words spoken, at least (% of the line)", step: 5, min: 0, max: 100, help: "A line too reworded to align is still timed when this much speech, including one of its own words, sits between two found lines." },
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

const HEAR_FIELDS: Field[] = [
  { key: "hear_baseline_wpm", label: "Baseline pace before your first take (wpm)", step: 5, min: 80, max: 250, help: "Used only until you have a take of your own, and labelled as a baseline, never as your rate." },
  { key: "coach_slow_pct", label: "How much slower a slowed word is (%)", step: 5, min: 5, max: 60, help: "When the coach slows a word or phrase down." },
  { key: "coach_pause_s", label: "A pause the coach adds (s)", step: 0.1, min: 0.1, max: 3, help: "Never shorter than a pause you wrote: the coach only adds." },
];

const CLARITY_FIELDS: Field[] = [
  { key: "clarity_prob", label: "“May not have been clear” below recognizer confidence", step: 0.05, min: 0.05, max: 0.95, help: "Per-word confidence from the recognizer, plus words it heard as another word." },
  { key: "clarity_context_words", label: "Skip a word whose neighbours were all clear, this many on each side", step: 1, min: 0, max: 5, help: "A low-confidence word the recognizer still got right, between confidently matched words. 0 lists every one." },
];

/** Registers: a starting point you pick for the coach, off until you do. Never used to judge a take. */
export const REGISTERS: { id: Settings["hear_register"]; label: string; rules: string }[] = [
  { id: "none", label: "None (off)", rules: "No register: with an API key the coach decides from the line alone; without one, the coach's version is off." },
  { id: "technical", label: "Conversational / technical talk", rules: "Phrases of about 3–5 seconds; slow down for numbers, definitions and the main result; pause before and after the point; one or two stressed words per sentence at most; a falling end on statements." },
  { id: "celebratory", label: "Celebratory (toast, tribute)", rules: "Warmth over speed, slightly slower overall; a pause after the punchline for the room to react; lower and slower for the sincere line; the last line slowest, a clear falling end, then silence." },
  { id: "slam", label: "Performance poetry / slam", rules: "The line break is a breath; build pace and volume toward the turn, drop just before it; contrast; end lines on a held or falling note; the last line gets the longest pause." },
  { id: "pitch", label: "Pitch / interview", rules: "Lead with the claim; slow down on the number and the ask; no trailing off." },
];

const INTEGER = new Set(["baseline_min_words", "fuzzy_min_chars", "clarity_context_words"]);

export function openSettings(onChange: () => void): void {
  const cur = state.effectiveSettings();
  const inputs = new Map<keyof Settings, HTMLInputElement>();
  const row = (f: Field) => {
    const inp = h("input", { type: "number", step: String(f.step), min: String(f.min), max: String(f.max), value: String(cur[f.key]), "data-key": f.key }) as HTMLInputElement;
    inputs.set(f.key, inp);
    return h("label", { class: "setting", "data-setting": f.key }, h("span", {}, f.label, h("small", { class: "muted" }, f.help)), inp);
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
  const register = h("select", { class: "label-input" }, ...REGISTERS.map((r) => h("option", { value: r.id }, r.label))) as HTMLSelectElement;
  register.value = cur.hear_register ?? "none";
  const registerRules = h("small", { class: "muted" });
  const showRules = () => { registerRules.textContent = REGISTERS.find((r) => r.id === register.value)?.rules ?? ""; };
  register.addEventListener("change", showRules);
  showRules();

  const dlg = h("dialog", { class: "settings-dialog" }) as HTMLDialogElement;
  // A blank or out-of-range field must not reach the server: NaN serializes to null and every take would fail.
  const num = (inp: HTMLInputElement, fallback: number): number => {
    const v = parseFloat(inp.value);
    if (!Number.isFinite(v)) return fallback;
    const c = Math.min(parseFloat(inp.max), Math.max(parseFloat(inp.min), v));
    // Settings that count things (words, characters) must reach the server as whole numbers.
    return INTEGER.has(inp.dataset.key ?? "") ? Math.round(c) : c;
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
    next.hear_register = register.value as Settings["hear_register"];
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
    h("label", { class: "setting check", "data-setting": "conventions_enabled" }, conv, h("span", {}, "Conference talk conventions", h("small", { class: "muted" }, "Off by default. Adds an overall pace band and a filler-word rate, like choosing to code-switch for a job talk. Your marks still come first."))),
    h("div", { class: "settings-grid sub" },
      h("label", { class: "setting", "data-setting": "conventions_wpm_min" }, h("span", {}, "Pace band min (wpm)"), wpmMin),
      h("label", { class: "setting", "data-setting": "conventions_wpm_max" }, h("span", {}, "Pace band max (wpm)"), wpmMax),
      h("label", { class: "setting", "data-setting": "conventions_filler_per_100" }, h("span", {}, "Fillers per 100 words, at most"), filler)),
    h("label", { class: "setting check", "data-setting": "emphasis_enabled" }, emph, h("span", {}, "Emphasis check for *word* (experimental)", h("small", { class: "muted" }, "Compares a word's loudness and pitch with the rest of its line. Unreliable on quiet microphones."))),
    h("h3", {}, "Hear it"),
    h("p", { class: "muted small" }, "A synthetic voice demonstrates a line: as you marked it (your marks and the thresholds above), or the coach's way. A register tells the coach what landing it means for this speech. It is a starting point you choose, off until you pick one, and never used to judge a take."),
    h("label", { class: "setting", "data-setting": "hear_register" }, h("span", {}, "Register for the coach", registerRules), register),
    h("div", { class: "settings-grid" }, ...HEAR_FIELDS.map(row)),
    h("h3", {}, "Words that may not have been clear"),
    h("div", { class: "settings-grid" }, ...CLARITY_FIELDS.map(row)),
    h("h3", {}, "Improvise reference bands"),
    h("p", { class: "muted small" }, "Improvise has no marks, so it compares each take with these bands. They are starting points, not rules; set them to what you are practising for."),
    h("div", { class: "settings-grid" },
      h("label", { class: "setting", "data-setting": "improv_wpm_min" }, h("span", {}, "Pace band min (wpm)"), iwMin),
      h("label", { class: "setting", "data-setting": "improv_wpm_max" }, h("span", {}, "Pace band max (wpm)"), iwMax),
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
  // The script's settings line wins over these fields for takes of that script: say which, and with what value.
  if (state.scriptText.trim()) {
    api.scriptSettings(state.scriptText, cur).then((r) => {
      const intro = dlg.querySelector("p");
      if (r.error) {
        intro?.after(h("p", { class: "small warn" }, `Your script's settings line has a problem: ${r.error}.`));
        return;
      }
      const keys = Object.keys(r.from_script);
      if (!keys.length) return;
      intro?.after(h("p", { class: "small muted" }, `Your script's first line sets ${keys.length} of these; they are marked below and win over this dialog for takes of that script.`));
      for (const [k, v] of Object.entries(r.from_script)) {
        const span = dlg.querySelector(`[data-setting="${k}"] > span`);
        span?.append(h("small", { class: "script-badge" }, `Script sets ${typeof v === "boolean" ? (v ? "on" : "off") : v}`));
      }
    }).catch(() => { /* the badges are a convenience */ });
  }
}
