/** When has the speaker finished answering? A pure detector over microphone level samples (dBFS), so the
 *  rule is tested without a microphone: nothing stops before any speech; after speech, a silence longer than
 *  the speaker's threshold ends the answer; the maximum length always does. Speech is a level some margin
 *  above the room's own floor, measured in the first moments of real signal (a newly opened microphone
 *  first reports digital silence, which says nothing about the room). */

export interface SilenceOptions {
  silenceS: number;      // the speaker's setting: this much quiet after speaking ends the answer
  maxS: number;          // the answer's maximum length
  marginDb?: number;     // speech is this much louder than the room
  floorS?: number;       // the first stretch of real signal sets the room's level
  minSpeechS?: number;   // this much continuous speech counts as having started
}

export type Verdict = "listening" | "silence" | "max";

export interface Detector {
  feed(tS: number, db: number): Verdict;
  readonly spoke: boolean;
}

const DIGITAL_SILENCE_DB = -100;  // below any real room; the meter reports about -140 for all-zero frames

export function silenceDetector(o: SilenceOptions): Detector {
  const margin = o.marginDb ?? 12;
  const floorS = o.floorS ?? 0.4;
  const minSpeech = o.minSpeechS ?? 0.25;
  let floor = Infinity;
  const room: number[] = [];  // levels heard while the floor is measured
  let floorFrom: number | null = null;  // when the first real (not digitally silent) frame arrived
  let speechSince: number | null = null;
  let quietSince: number | null = null;
  let spoke = false;
  return {
    get spoke() { return spoke; },
    feed(t: number, db: number): Verdict {
      if (t >= o.maxS) return "max";
      if (floorFrom === null) {
        if (db < DIGITAL_SILENCE_DB) return "listening";
        floorFrom = t;
      }
      if (t < floorFrom + floorS) {
        if (db >= DIGITAL_SILENCE_DB) room.push(db);
        return "listening";
      }
      // A low percentile, not the minimum: the first real frames are part zeros (the analyser's window is still
      // filling) and read several dB below the room; speech starting early sits above it.
      if (room.length) { room.sort((a, b) => a - b); floor = room[Math.floor(room.length * 0.2)]; room.length = 0; }
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
