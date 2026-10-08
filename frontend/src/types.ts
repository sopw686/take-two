export interface Settings {
  short_pause_s: number;
  long_pause_s: number;
  pause_near_ratio: number;
  key_slower_pct: number;
  key_pause_after_s: number;
  line_min_coverage: number;
  baseline_min_words: number;
  section_tolerance_pct: number;
  min_silence_s: number;
  conventions_enabled: boolean;
  conventions_wpm_min: number;
  conventions_wpm_max: number;
  conventions_filler_per_100: number;
  emphasis_enabled: boolean;
}

export interface Health {
  stt: { backend: string; model: string; device: string; loaded: boolean; local: boolean };
  audio_leaves_machine: boolean;
  llm: { available: boolean; provider: string; model: string | null; reason: string | null };
  defaults: Settings;
}

export type Status = "met" | "near" | "diverged" | "short" | "missing" | "unmeasurable" | "not_found" | "over" | "under" | "no_budget" | "ok" | "unknown";

export interface WordRow { index: number; text: string; start: number | null; end: number | null }

export interface KeyInfo {
  status: Status;
  rate_status: Status;
  pause_status: Status;
  wpm: number | null;
  median_wpm: number | null;
  wpm_vs_median_pct: number | null;
  pause_after_s: number | null;
  pause_after_target_s: number;
  slower_target_pct: number;
  pause_window: [number, number] | null;
}

export interface LineRow {
  index: number;
  section: number;
  text: string;
  is_key: boolean;
  word_count: number;
  matched_words: number;
  span_words: number;
  coverage: number;
  start: number | null;
  end: number | null;
  duration_s: number | null;
  wpm: number | null;
  status: "ok" | "not_found";
  words: WordRow[];
  key?: KeyInfo;
}

export interface SectionRow {
  index: number;
  name: string;
  budget_s: number | null;
  budget_label: string;
  start: number | null;
  end: number | null;
  duration_s: number | null;
  duration_label: string;
  delta_s: number | null;
  delta_label: string;
  status: Status;
  line_start: number;
  line_end: number;
  words: number;
}

export interface PauseRow {
  line: number;
  word_index: number;
  kind: "/" | "//";
  target_s: number;
  measured_s: number | null;
  whisper_gap_s: number | null;
  at_time: number | null;
  window: [number, number] | null;
  status: Status;
  before: string | null;
  after: string | null;
}

export interface DefineRow {
  term: string;
  line: number;
  section: number;
  status: string;
  method: string;
  first_spoken_at?: number | null;
  defined?: boolean | null;
  evidence?: { quote: string; start: number | null; end: number | null } | null;
  note?: string;
}

export interface Analysis {
  take_id: string;
  created_at: string;
  label: string;
  duration_s: number;
  settings: Settings;
  stt: { backend: string; model: string; device: string; local: boolean };
  silence_method: string;
  baseline: { median_wpm: number | null; lines_used: number; min_words_per_line: number; median_pause_s: number | null; pauses_counted: number };
  sections: SectionRow[];
  lines: LineRow[];
  pauses: PauseRow[];
  defines: DefineRow[];
  summary: string[];
  transcript: { text: string; words: { i: number; text: string; start: number; end: number }[] };
  audio_url: string;
  timing: { decode_s?: number; stt_s?: number };
  conventions?: ConventionsReport;
  emphasis?: EmphasisRow[];
  coaching?: CoachingReport;
}

export interface ConventionsReport {
  enabled: boolean;
  status?: string;
  overall_wpm?: number | null;
  wpm_band?: [number, number];
  wpm_status?: Status;
  filler_count?: number;
  filler_per_100?: number | null;
  filler_target_per_100?: number;
  filler_status?: Status;
  fillers?: { text: string; start: number; end: number }[];
  words?: number;
}

export interface EmphasisRow {
  line: number;
  word_index: number;
  word: string;
  start: number | null;
  end: number | null;
  word_db: number | null;
  line_median_db: number | null;
  delta_db: number | null;
  word_f0: number | null;
  line_median_f0: number | null;
  status: Status;
}

export interface CoachingReport {
  available: boolean;
  reason?: string;
  suggestions: { text: string; mark?: string; metric?: string }[];
  all_met?: boolean;
}

export interface TakeSummary {
  take_id: string;
  created_at: string;
  duration_s: number;
  summary: string[];
  label: string;
  stt: { backend: string; model: string };
}

export interface Suggestion {
  id: number;
  type: "key" | "pause" | "long_pause" | "define" | "section";
  line_index: number;
  raw_line_no: number;
  word_index: number | null;
  term: string | null;
  name: string | null;
  budget_s: number | null;
  budget_label: string | null;
  budget_estimated?: boolean;
  reason: string;
  preview: string;
}

export interface SuggestResponse {
  available: boolean;
  reason?: string;
  suggestions: Suggestion[];
  dropped: { reason: string; count: number }[];
  rate_wpm: number;
  rate_source: string;
  lines: { index: number; raw_line_no: number; text: string }[];
}
