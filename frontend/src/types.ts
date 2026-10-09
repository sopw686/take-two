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
  improv_wpm_min: number;
  improv_wpm_max: number;
  improv_goal_tolerance_pct: number;
  improv_filler_per_100: number;
  improv_hedge_per_100: number;
  improv_hesitation_pause_s: number;
  improv_hesitations_per_min: number;
  improv_uptalk_st: number;
  improv_trail_db: number;
  improv_tone_share_pct: number;
  improv_clarity_prob: number;
  improv_unclear_pct: number;
  improv_pitch_range_st: number;
  improv_loudness_var_db: number;
  improv_pace_var_pct: number;
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
  mode?: "script" | "improv";
  topic?: string | null;
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

export interface CompareMark {
  kind: "KEY" | "/" | "//" | "section" | "DEFINE";
  line?: number;
  word_index?: number;
  name?: string;
  term?: string;
  text?: string;
  takes: number;
  statuses: string[];
  values: (number | null)[];
  met: number;
  latest: string | null;
}

export interface CompareResult {
  takes: number;
  take_ids: string[];
  takes_info: { take_id: string; created_at: string | null; label: string }[];
  marks: CompareMark[];
  summary: string[];
}

// ---- Improvise ----------------------------------------------------------------

export interface Span { start: number; end: number }
export interface WordSpan extends Span { text: string; i: number; j: number }
export interface PauseSpan extends Span { duration_s: number; after_i: number; before: string; after: string; kind?: string }
export interface ToneRow extends Span { i: number; word: string; sentence_start: number; rise_st?: number; drop_db?: number }

export interface ImprovReport {
  topic: string;
  goal_s: number | null;
  span: [number | null, number | null];
  spoken_s: number;
  words: number;
  goal: { goal_s: number | null; spoken_s: number; delta_s: number | null; tolerance_s: number | null; status: string };
  pace: { overall_wpm: number | null; band: [number, number]; status: string; windows: { start: number; end: number; wpm: number }[] };
  fillers: { count: number; per_100: number | null; target_per_100: number; status: string; items: WordSpan[]; note: string };
  hesitation: { pauses: PauseSpan[]; restarts: (WordSpan & { kind: string })[]; count: number; per_min: number | null; threshold_s: number; target_per_min: number; status: string };
  hedges: { count: number; per_100: number | null; target_per_100: number; status: string; items: (WordSpan & { phrase: string })[] };
  tone: {
    pitch_available: boolean;
    uptalk: ToneRow[]; uptalk_measured: number; uptalk_share_pct: number | null; uptalk_threshold_st: number; uptalk_status: string;
    trail_off: ToneRow[]; trail_measured: number; trail_share_pct: number | null; trail_threshold_db: number; trail_status: string;
    share_target_pct: number;
  };
  clarity: { available: boolean; unclear: { i: number; text: string; prob: number; start: number; end: number }[]; unclear_pct: number | null; prob_threshold: number; target_pct: number; status: string; note: string };
  engagement: {
    pitch_backend: string | null;
    pitch_range_st: number | null; pitch_floor_st: number; pitch_status: string;
    loudness_var_db: number | null; loudness_target_db: number; loudness_status: string;
    pace_var_pct: number | null; pace_var_target_pct: number; pace_var_status: string;
    purposeful_pauses: PauseSpan[]; purposeful_per_min: number | null;
    opening: { status: string; db_delta: number | null; f0_delta_pct: number | null; range_st: number | null };
    contour: [number, number | null][];
  };
  sentences: [number, number][];
  drills: { focus: string; status: string; text: string }[];
}

export interface ContentReviewReport {
  available: boolean;
  reason?: string;
  items: { key: string; label: string; verdict: string; note: string; evidence: { quote: string; start: number | null; end: number | null } | null }[];
  dropped?: string[];
  rewrite_opening?: string;
}

export interface ImprovHistoryRow {
  take_id: string; created_at: string | null; topic: string | null; goal_s: number | null; delta_s: number | null;
  wpm: number | null; fillers_per_100: number | null; hedges_per_100: number | null; hesitations_per_min: number | null; pitch_range_st: number | null;
}

export interface ImprovAnalysis {
  mode: "improv";
  take_id: string;
  created_at: string;
  label: string;
  topic: string;
  goal_s: number | null;
  content: boolean;
  settings: Settings;
  duration_s: number;
  summary: string[];
  improv: ImprovReport;
  stt: { backend: string; model: string; device: string; local: boolean };
  silence_method: string;
  transcript: { text: string; words: { i: number; text: string; start: number; end: number; prob?: number }[] };
  audio_url: string;
  timing: { decode_s?: number; stt_s?: number };
  history?: ImprovHistoryRow[];
  coaching?: { available: boolean; reason?: string; suggestions: { text: string; focus?: string; metric?: string }[] };
  content_review?: ContentReviewReport;
}

export interface Topic { text: string; category: string; level: "easy" | "medium" | "hard" }
