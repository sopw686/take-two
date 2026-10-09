/** When has the speaker finished answering? A pure detector over microphone level samples (dBFS), so the
 *  rule is tested without a microphone: nothing stops before any speech; after speech, a silence longer than
 *  the speaker's threshold ends the answer; the maximum length always does. Speech is a level some margin
 *  above the room's own floor, measured in the first moments of the recording. */

export interface SilenceOptions {
  silenceS: number;      // the speaker's setting: this much quiet after speaking ends the answer
  maxS: number;          // the answer's maximum length
  marginDb?: number;     // speech is this much louder than the room
  floorS?: number;       // the first stretch of the recording sets the room's level
  minSpeechS?: number;   // this much continuous speech counts as having started
}

export type Verdict = "listening" | "silence" | "max";

export interface Detector {
  feed(tS: number, db: number): Verdict;
  readonly spoke: boolean;
}

export function silenceDetector(o: SilenceOptions): Detector {
  const margin = o.marginDb ?? 12;
  const floorS = o.floorS ?? 0.4;
  const minSpeech = o.minSpeechS ?? 0.25;
  let floor = Infinity;
  let speechSince: number | null = null;
  let quietSince: number | null = null;
  let spoke = false;
  return {
    get spoke() { return spoke; },
    feed(t: number, db: number): Verdict {
      if (t >= o.maxS) return "max";
      if (t < floorS) {
        floor = Math.min(floor, db);
        return "listening";
      }
      // A room never measured (or measured as digital silence) still needs a sensible floor.
      const threshold = Math.max(Number.isFinite(floor) ? floor : -70, -70) + margin;
      const loud = db >= threshold;
      if (loud) {
        quietSince = null;
        speechSince = speechSince ?? t;
        if (t - speechSince >= minSpeech) spoke = true;
        return "listening";
      }
      speechSince = null;
      if (!spoke) return "listening";
      quietSince = quietSince ?? t;
      return t - quietSince >= o.silenceS ? "silence" : "listening";
    },
  };
}
