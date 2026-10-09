/** The spoken examiner's session as a pure state machine (import-free, tested under Node).
 *
 *  idle → asking → thinking → recording → analyzing → (follow-up: asking → thinking → recording → analyzing) → next … → done
 *
 *  Each question gets at most one follow-up; a follow-up's answer never gets another. Skip, repeat and
 *  abort work from any live phase. The runner (examiner.ts) performs the effects each phase implies: speak,
 *  count down, record, analyze. It never records while the examiner is speaking, because "recording" is only
 *  entered from "thinking", which is only entered once the question has been spoken. */

export type Phase = "idle" | "asking" | "thinking" | "recording" | "analyzing" | "done";

export interface SessionState {
  phase: Phase;
  index: number;           // the question being asked, 0-based
  total: number;
  followup: string | null; // the follow-up being asked or answered, if this round is one
  followupsAsked: number;
  answered: number;        // answers recorded and sent for analysis (questions and follow-ups)
  skipped: number;
  repeats: number;
  aborted: boolean;
}

export type SessionEvent =
  | { type: "start"; total: number }
  | { type: "spoken" }                 // the examiner finished speaking (speak() resolved)
  | { type: "thought" }                // thinking time is over
  | { type: "answered" }               // silence after speech, the maximum length, Space or Done
  | { type: "analyzed"; followup: string | null }   // the answer's analysis is back (null: no follow-up)
  | { type: "failed" }                 // the analysis failed; the take is kept for Retry and the session goes on
  | { type: "repeat" }                 // R: hear the question again
  | { type: "skip" }                   // S: move on without (or without keeping) an answer
  | { type: "abort" };                 // Esc: end the session; answers already recorded are kept

export function initial(): SessionState {
  return { phase: "idle", index: 0, total: 0, followup: null, followupsAsked: 0, answered: 0, skipped: 0, repeats: 0, aborted: false };
}

function next(s: SessionState): SessionState {
  const index = s.index + 1;
  return index < s.total ? { ...s, phase: "asking", index, followup: null } : { ...s, phase: "done", followup: null };
}

export function step(s: SessionState, e: SessionEvent): SessionState {
  if (e.type === "abort") return s.phase === "done" || s.phase === "idle" ? s : { ...s, phase: "done", aborted: true };
  switch (s.phase) {
    case "idle":
      return e.type === "start" && e.total > 0 ? { ...initial(), phase: "asking", total: e.total } : s;
    case "asking":
      if (e.type === "spoken") return { ...s, phase: "thinking" };
      if (e.type === "repeat") return { ...s, repeats: s.repeats + 1 };
      if (e.type === "skip") return { ...next(s), skipped: s.followup ? s.skipped : s.skipped + 1 };
      return s;
    case "thinking":
      if (e.type === "thought") return { ...s, phase: "recording" };
      if (e.type === "repeat") return { ...s, phase: "asking", repeats: s.repeats + 1 };
      if (e.type === "skip") return { ...next(s), skipped: s.followup ? s.skipped : s.skipped + 1 };
      return s;
    case "recording":
      if (e.type === "answered") return { ...s, phase: "analyzing", answered: s.answered + 1 };
      if (e.type === "skip") return { ...next(s), skipped: s.followup ? s.skipped : s.skipped + 1 };
      return s;
    case "analyzing":
      if (e.type === "analyzed") {
        // One follow-up per question, and never a follow-up to a follow-up.
        if (e.followup && !s.followup) return { ...s, phase: "asking", followup: e.followup, followupsAsked: s.followupsAsked + 1 };
        return next(s);
      }
      if (e.type === "failed") return next(s);
      return s;
    case "done":
      return s;
  }
}

/** What a screen reader hears on each change: "Question 2 of 4. Listening." */
export function announce(s: SessionState): string {
  const q = `${s.followup ? "Follow-up to question" : "Question"} ${s.index + 1} of ${s.total}.`;
  switch (s.phase) {
    case "idle": return "";
    case "asking": return `${q} The examiner is asking.`;
    case "thinking": return `${q} Thinking time.`;
    case "recording": return `${q} Listening.`;
    case "analyzing": return `${q} Measuring your answer.`;
    case "done": return s.aborted ? "Session ended." : "Session complete.";
  }
}
