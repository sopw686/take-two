"""Words that may not have been clear, from what the recognizer measured.

Two signals, both already in the take: the recognizer's per-word confidence
(`Word.prob`) and the alignment's misheard matches (a script word paired with a
different word the recognizer heard). Nothing is guessed from the audio. A word
is listed when its confidence is below `clarity_prob` or it was heard as another
word. A low-confidence word that matched the script exactly is skipped when the
`clarity_context_words` words on each side also matched exactly at high
confidence: the recognizer got it right in the middle of a confident stretch.

The wording is measured and kind. A recognizer can miss a word because of an
accent, a noisy or distant microphone, a rare word or a quiet moment, so the list
says where it was unsure, never how the speaker speaks. A word the speaker
dismisses ("I said it fine") is remembered and left out of later reports.
"""

from __future__ import annotations

import json

from take_two import takes
from take_two.align import Alignment
from take_two.config import Settings
from take_two.marks import Script, normalize_word
from take_two.stt.base import Transcript

HIGH_CONFIDENCE = 0.9
DISMISSED_FILE = "clarity_dismissed.json"
NOTE = ("A recognizer can miss a word because of an accent, a noisy or distant microphone, a rare word or a quiet "
        "moment. This list says where it was unsure, not how you speak.")


def word_key(text: str) -> str:
    return " ".join(normalize_word(text))


def clarity_report(script: Script, al: Alignment, transcript: Transcript, ok_lines: set[int], settings: Settings,
                   dismissed: frozenset[str] | set[str] = frozenset()) -> dict:
    """Pure: the alignment and transcript in, the list of words out."""
    words = transcript.words
    toks = [t for t in al.tokens if t.token.norm]
    info = []
    for t in toks:
        prob = min((words[i].prob for i in t.transcript_indexes), default=None) if t.aligned else None
        info.append((t, prob))

    def confident(k: int) -> bool:
        t, p = info[k]
        return t.aligned and not t.fuzzy and p is not None and p >= HIGH_CONFIDENCE

    rows: list[dict] = []
    skipped_dismissed = 0
    n = settings.clarity_context_words
    for k, (t, prob) in enumerate(info):
        if t.token.line not in ok_lines or not t.aligned or prob is None:
            continue
        if not (t.fuzzy or prob < settings.clarity_prob):
            continue
        if not t.fuzzy and n > 0:
            around = list(range(max(0, k - n), k)) + list(range(k + 1, min(len(info), k + n + 1)))
            if len(around) == 2 * n and all(confident(j) for j in around):
                continue
        word = t.token.text.strip(".,;:!?\"'()[]{}…“”‘’")
        if word_key(word) in dismissed:
            skipped_dismissed += 1
            continue
        heard = (t.heard or "").strip(".,;:!?\"'()[]{}…“”‘’")
        text = (f"The script says “{word}”; the recognizer heard “{heard}” (confidence {prob:.2f})." if t.fuzzy
                else f"The recognizer was unsure of “{word}” (confidence {prob:.2f}).")
        rows.append({"line": t.token.line, "word_index": t.token.index, "word": word, "key": word_key(word),
                     "start": round(t.start, 3), "end": round(t.end, 3), "prob": round(prob, 2),
                     "heard": heard if t.fuzzy else None, "kind": "heard" if t.fuzzy else "unsure", "text": text})
    rows.sort(key=lambda r: r["start"])
    return {"threshold": settings.clarity_prob, "context_words": n, "words": rows,
            "dismissed_skipped": skipped_dismissed, "note": NOTE}


# ---- "I said it fine": remembered per word, next to the takes ---------------------------------------------------

def _path():
    return takes.takes_dir() / DISMISSED_FILE


def load_dismissed() -> set[str]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return {str(w) for w in data.get("words", [])}
    except (OSError, ValueError, AttributeError):
        return set()


def set_dismissed(word: str, dismissed: bool) -> set[str]:
    key = word_key(word)
    words = load_dismissed()
    if key:
        (words.add if dismissed else words.discard)(key)
        takes.save_json(_path(), {"words": sorted(words)})
    return words
