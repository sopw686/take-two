import assert from "node:assert/strict";
import { test } from "node:test";
import { announce, initial, step, type SessionEvent, type SessionState } from "../src/examinerMachine.js";
import { silenceDetector } from "../src/silence.js";

const run = (events: SessionEvent[], from: SessionState = initial()) => events.reduce(step, from);
const phases = (events: SessionEvent[]) => {
  const out: string[] = [];
  events.reduce((s, e) => { const n = step(s, e); out.push(n.phase); return n; }, initial());
  return out;
};
const round = (fu: string | null = null): SessionEvent[] => [{ type: "spoken" }, { type: "thought" }, { type: "answered" }, { type: "analyzed", followup: fu }];

test("a session walks asking → thinking → recording → analyzing for each question, then done", () => {
  assert.deepEqual(phases([{ type: "start", total: 2 }, ...round(), ...round()]),
    ["asking", "thinking", "recording", "analyzing", "asking", "thinking", "recording", "analyzing", "done"]);
  const s = run([{ type: "start", total: 2 }, ...round(), ...round()]);
  assert.equal(s.answered, 2);
  assert.equal(s.aborted, false);
});

test("recording is only reached after the question was spoken and the thinking time ended", () => {
  let s = run([{ type: "start", total: 3 }]);
  for (const e of [{ type: "thought" }, { type: "answered" }, { type: "analyzed", followup: null }] as SessionEvent[]) {
    s = step(s, e);
    assert.equal(s.phase, "asking");  // nothing skips the examiner's speech
  }
  s = step(s, { type: "spoken" });
  assert.equal(s.phase, "thinking");
  assert.equal(step(s, { type: "answered" }).phase, "thinking");
});

test("one follow-up per question, and none for a follow-up's answer", () => {
  let s = run([{ type: "start", total: 3 }, ...round("Compared with what?")]);
  assert.equal(s.phase, "asking");
  assert.equal(s.followup, "Compared with what?");
  assert.equal(s.index, 0);
  s = run(round("And then what?"), s);  // the follow-up's own analysis proposes another: ignored
  assert.equal(s.index, 1);
  assert.equal(s.followup, null);
  assert.equal(s.followupsAsked, 1);
});

test("skip, repeat and abort", () => {
  let s = run([{ type: "start", total: 3 }, { type: "repeat" }, { type: "repeat" }]);
  assert.equal(s.repeats, 2);
  assert.equal(s.phase, "asking");
  s = run([{ type: "spoken" }, { type: "repeat" }], s);
  assert.equal(s.phase, "asking");  // R during thinking asks again
  s = run([{ type: "skip" }], s);
  assert.deepEqual([s.index, s.skipped, s.phase], [1, 1, "asking"]);
  s = run([{ type: "spoken" }, { type: "thought" }, { type: "skip" }], s);
  assert.deepEqual([s.index, s.skipped], [2, 2]);
  s = run([{ type: "spoken" }, { type: "thought" }, { type: "answered" }, { type: "abort" }], s);
  assert.deepEqual([s.phase, s.aborted, s.answered], ["done", true, 1]);
  assert.equal(step(s, { type: "start", total: 3 }).phase, "done");
  assert.equal(step(initial(), { type: "abort" }).phase, "idle");
});

test("a failed analysis keeps the session going without a follow-up", () => {
  const s = run([{ type: "start", total: 2 }, { type: "spoken" }, { type: "thought" }, { type: "answered" }, { type: "failed" }]);
  assert.deepEqual([s.phase, s.index, s.followup], ["asking", 1, null]);
});

test("skipping a follow-up is not counted as skipping a question", () => {
  const s = run([{ type: "start", total: 3 }, ...round("Why?"), { type: "skip" }]);
  assert.deepEqual([s.index, s.skipped], [1, 0]);
});

test("state changes are announced in words", () => {
  let s = run([{ type: "start", total: 4 }, { type: "spoken" }, { type: "thought" }]);
  s = { ...s, index: 1 };
  assert.equal(announce(s), "Question 2 of 4. Listening.");
  assert.equal(announce({ ...s, followup: "x", phase: "asking" }), "Follow-up to question 2 of 4. The examiner is asking.");
  assert.equal(announce({ ...s, phase: "done", aborted: true }), "Session ended.");
});

const feed = (o: Parameters<typeof silenceDetector>[0], samples: [number, number][]) => {
  const d = silenceDetector(o);
  for (const [t, db] of samples) {
    const v = d.feed(t, db);
    if (v !== "listening") return { v, t };
  }
  return { v: "listening", t: null };
};
const series = (from: number, to: number, db: number, dt = 0.05): [number, number][] => {
  const out: [number, number][] = [];
  for (let t = from; t < to - 1e-9; t += dt) out.push([Math.round(t * 1000) / 1000, db]);
  return out;
};

test("silence after speech ends the answer after the speaker's threshold", () => {
  const r = feed({ silenceS: 3, maxS: 90 }, [...series(0, 0.5, -60), ...series(0.5, 4, -25), ...series(4, 10, -60)]);
  assert.equal(r.v, "silence");
  assert.ok(r.t !== null && r.t >= 7 && r.t < 7.1);
});

test("no stop before any speech, however long the quiet", () => {
  assert.deepEqual(feed({ silenceS: 2, maxS: 60 }, series(0, 30, -60)), { v: "listening", t: null });
});

test("a short pause in the middle of an answer does not end it", () => {
  const r = feed({ silenceS: 3, maxS: 90 }, [...series(0, 0.5, -60), ...series(0.5, 3, -25), ...series(3, 5, -60), ...series(5, 8, -25), ...series(8, 12, -60)]);
  assert.equal(r.v, "silence");
  assert.ok(r.t !== null && r.t >= 11 && r.t < 11.1);
});

test("the maximum length always stops", () => {
  assert.deepEqual(feed({ silenceS: 3, maxS: 5 }, series(0, 10, -25)), { v: "max", t: 5 });
});

test("a click is not speech", () => {
  const r = feed({ silenceS: 2, maxS: 60 }, [...series(0, 0.5, -60), [1, -20], ...series(1.05, 6, -60)]);
  assert.equal(r.v, "listening");
});
