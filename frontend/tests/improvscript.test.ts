import assert from "node:assert/strict";
import { test } from "node:test";
import { improvToScript, type ImprovSource } from "../src/improvscript.js";

const words = (s: string) => s.split(" ").map((text) => ({ text: ` ${text}` }));
const src = (o: Partial<ImprovSource>): ImprovSource => ({ topic: "Why trees matter", goal_s: 60, words: [], sentences: [],
  fillers: [], restarts: [], deliberate: [], hesitations: [], ...o });
const body = (text: string) => text.split("\n").slice(2).filter(Boolean);

test("one line per sentence under a section named for the topic, budgeted by the goal", () => {
  const r = improvToScript(src({ words: words("Trees cool streets. They also clean air."), sentences: [[0, 3], [3, 7]] }), { longPauseS: 1.5, when: "14 Oct" });
  const lines = r.text.split("\n");
  assert.ok(/^<!-- From your Improvise take of 14 Oct\..*-->$/.test(lines[0]));
  assert.equal(lines[1], "## Why trees matter [1:00]");
  assert.deepEqual(body(r.text), ["Trees cool streets.", "They also clean air."]);
  assert.equal(r.lines, 2);
});

test("pauses stay where they fell: / or // by length, hesitations tagged, a pause between sentences trails its line", () => {
  const r = improvToScript(src({
    words: words("Trees cool streets. They also clean the air."), sentences: [[0, 3], [3, 8]],
    deliberate: [{ after_i: 2, duration_s: 1.8 }], hesitations: [{ after_i: 5, duration_s: 1.3 }],
  }), { longPauseS: 1.5 });
  assert.deepEqual(body(r.text), ["Trees cool streets. //", "They also clean / <!-- hesitation 1.3 s --> the air."]);
  assert.deepEqual([r.deliberate, r.hesitations], [1, 1]);
});

test("fillers and restarts are left out, the line is capitalised and keeps its full stop", () => {
  const r = improvToScript(src({
    words: words("Um, so I I think th- the trees, um."), sentences: [[0, 9]],
    fillers: [{ i: 0, j: 0 }, { i: 8, j: 8 }],
    restarts: [{ i: 2, j: 3, kind: "repeat" }, { i: 5, j: 5, kind: "fragment" }],
  }), { longPauseS: 1.5 });
  assert.deepEqual(body(r.text), ["So I think the trees."]);
  assert.deepEqual([r.fillersRemoved, r.restartsRemoved], [2, 2]);
});

test("a pause around a left-out word is one mark, and a sentence of only fillers hands its pause to the line before", () => {
  const r = improvToScript(src({
    words: words("Trees um matter. Uh."), sentences: [[0, 3], [3, 4]],
    fillers: [{ i: 1, j: 1 }, { i: 3, j: 3 }],
    deliberate: [{ after_i: 2, duration_s: 0.9 }],
    hesitations: [{ after_i: 0, duration_s: 1.2 }, { after_i: 1, duration_s: 1.6 }],
  }), { longPauseS: 1.5 });
  assert.deepEqual(body(r.text), ["Trees // <!-- hesitation 1.6 s --> matter. /"]);
  assert.deepEqual([r.lines, r.hesitations, r.deliberate], [1, 1, 1]);
});

test("no goal, no budget; a topic cannot close the intro comment early", () => {
  const r = improvToScript(src({ topic: "a --> b\nc", goal_s: null, words: words("Hi."), sentences: [[0, 1]] }), { longPauseS: 1.5 });
  assert.equal(r.text.split("\n")[1], "## a b c");
});
