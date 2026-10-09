"""Words worth checking before you say them: names, loanwords, acronyms, rare terms.

Flagging needs no model: capitalisation inside a sentence (a name), all capitals (an
acronym), letters outside English (a loanword), and length plus rarity, where rarity is
read from the speech recognizer's own vocabulary: a word Whisper's tokenizer has to
split into three or more pieces is uncommon in the text it learned from. The tokenizer
is already on disk once the local speech model has been downloaded; without it that
rule is skipped and the list says so.

Proposing how a word is said needs a model (with ANTHROPIC_API_KEY). The model can be
wrong, especially about names, so every proposal is labelled "proposed pronunciation:
confirm it", the speaker can edit it, and code checks it: the word must be in the
script, the respelling is letters, hyphens and apostrophes, and the list is capped.
Without a key nothing is proposed: the speaker types how they say it. A confirmed
pronunciation becomes a [SAY: word = respelling | ipa] mark in the script.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from pydantic import BaseModel, Field

from take_two.marks import Script, normalize_word

MAX_WORDS = 12
RESPELL_RE = re.compile(r"^[A-Za-z][A-Za-z' -]{0,39}$")
IPA_MAX = 40
RARE_PIECES = 3
RARE_MIN_CHARS = 7


@lru_cache(maxsize=1)
def _tokenizer():
    try:
        from huggingface_hub import try_to_load_from_cache
        from tokenizers import Tokenizer

        from take_two import config
        repo = config.STT_MODEL if "/" in config.STT_MODEL else f"Systran/faster-whisper-{config.STT_MODEL}"
        path = try_to_load_from_cache(repo, "tokenizer.json")
        return Tokenizer.from_file(path) if isinstance(path, str) else None
    except Exception:
        return None


def rarity_pieces(word: str) -> int | None:
    """How many pieces the recognizer's tokenizer splits " word" into, or None without the tokenizer."""
    tok = _tokenizer()
    if tok is None:
        return None
    return len(tok.encode(" " + word.lower(), add_special_tokens=False).ids)


def _bare(w: str) -> str:
    w = w.strip(".,;:!?\"'()[]{}…“”‘’*")
    return re.sub(r"['’]s$", "", w)  # Maya's is Maya


_NOT_NAMES = {"i", "i'm", "i'll", "i've", "i'd", "dr", "mr", "mrs", "ms", "prof", "st", "a", "an", "and", "the", "to",
              "but", "or", "so", "if", "while", "when", "then", "we", "you", "he", "she", "it", "they", "my", "our",
              "your", "this", "that", "in", "on", "at", "for", "of", "with", "as", "yes", "no", "thank", "please"}
_TITLES = {"dr", "mr", "mrs", "ms", "prof", "st"}
_END = re.compile(r"[.!?:;]['\"”’)]*$")


def _name_runs(words: list[str]) -> list[tuple[int, int]]:
    """Runs of capitalised words that look like a name: never across a sentence end, and a capital that only
    marks the start of a sentence (or a common word like "And", "Dr") does not count."""
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(words):
        w = _bare(words[i])
        start = i == 0 or (bool(_END.search(words[i - 1])) and _bare(words[i - 1]).lower() not in _TITLES)
        start = start and not re.search(r"['’]s\W*$", words[i])  # "Maya's" is a name even first in a sentence
        if not w[:1].isupper() or w.lower() in _NOT_NAMES or (start and not (
                i + 1 < len(words) and not _END.search(words[i]) and _bare(words[i + 1])[:1].isupper()
                and _bare(words[i + 1]).lower() not in _NOT_NAMES)):
            i += 1
            continue
        j = i
        while j + 1 < len(words) and not _END.search(words[j]) and _bare(words[j + 1])[:1].isupper()                 and _bare(words[j + 1]).lower() not in _NOT_NAMES:
            j += 1
        if not (len(re.sub(r"[^A-Za-z]", "", w)) >= 2 and re.sub(r"[^A-Za-z]", "", w).isupper() and j == i):
            runs.append((i, j))
        i = j + 1
    return runs


def flag_words(script: Script, pieces=rarity_pieces) -> tuple[list[dict], str | None]:
    """(flagged words in script order with reasons, a note if the rarity rule could not run). Pure given `pieces`."""
    out: dict[str, dict] = {}
    lex = script.lexicon
    rarity_ok = True

    def add(w: str, line: int, reasons: list[str]) -> None:
        key = " ".join(normalize_word(w))
        if not key:
            return
        if key in lex:
            reasons = reasons or ["has your [SAY] mark"]
        row = out.setdefault(key, {"word": w, "key": key, "line": line, "reasons": [], "count": 0})
        row["count"] += 1
        row["reasons"] = list(dict.fromkeys(row["reasons"] + reasons))

    for ln in script.lines:
        words = [t.text for t in ln.tokens]
        in_name: set[int] = set()
        for a, b in _name_runs(words):
            name = " ".join(_bare(x) for x in words[a:b + 1])
            foreign = any(unicodedata.category(c).startswith("L") and ord(c) > 127 for c in name)
            add(name, ln.index, ["a name"] + (["letters from another language"] if foreign else []))
            in_name.update(range(a, b + 1))
        for i, raw in enumerate(words):
            w = _bare(raw)
            if i in in_name or not w or not re.search(r"[A-Za-zÀ-ÿ]", w):
                continue
            reasons: list[str] = []
            letters = re.sub(r"[^A-Za-z]", "", w)
            if len(letters) >= 2 and letters.isupper():
                reasons.append("an acronym: letters or a word?")
            if any(unicodedata.category(c).startswith("L") and ord(c) > 127 for c in w):
                reasons.append("letters from another language")
            if len(w) >= RARE_MIN_CHARS and w.islower():
                n = pieces(w)
                if n is None:
                    rarity_ok = False
                elif n >= RARE_PIECES:
                    reasons.append("an uncommon word")
            if reasons or " ".join(normalize_word(w)) in lex:
                add(w, ln.index, reasons)
    rows = list(out.values())[:MAX_WORDS]
    for r in rows:
        m = lex.get(r["key"])
        r.update({"respelling": m.respelling if m else None, "ipa": m.ipa if m else None,
                  "source": "your [SAY] mark" if m else None, "confirmed": bool(m)})
    note = None if rarity_ok else ("The speech model's vocabulary is not on this computer yet, so uncommon words are "
                                   "not flagged; names, acronyms and loanwords still are.")
    return rows, note


class ProposedSaying(BaseModel):
    word: str = Field(description="The word exactly as written in the script.")
    respelling: str = Field(description="Plain respelling with hyphens between syllables and the stressed syllable in "
                                        "capitals, e.g. KOH-ral, zhah-VAY.")
    ipa: str = Field(default="", description="IPA without slashes, with a stress mark; empty if unsure.")


class SayingsOutput(BaseModel):
    words: list[ProposedSaying]


SYSTEM = """You help a speaker say the hard words in their speech. You receive words from their script (names, loanwords, acronyms, rare terms) with the line each appears in. For each, propose how it is most likely said in this context: a plain respelling with hyphens between syllables and the stressed syllable in capitals, and IPA with a stress mark when you are confident. For an acronym said as letters, respell it letter by letter (EN-ess-AY). Names vary by person and place: give the most common pronunciation and do not claim it is the only one."""


def build_user_prompt(script: Script, flagged: list[dict]) -> str:
    return "\n".join(f"- {r['word']}  (line: {script.lines[r['line']].text})" for r in flagged)


def validate_sayings(out: SayingsOutput, flagged: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """({key: {respelling, ipa}}, dropped reasons). Only flagged words, plausible respellings, capped."""
    keys = {r["key"] for r in flagged}
    kept: dict[str, dict] = {}
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for p in out.words:
        key = " ".join(normalize_word(_bare(p.word)))
        resp = " ".join(p.respelling.split())
        ipa = p.ipa.strip().strip("/[]")
        if key not in keys:
            drop("word not in the list")
        elif key in kept:
            drop("duplicate")
        elif not RESPELL_RE.match(resp):
            drop("respelling is not plain letters and hyphens")
        elif len(kept) >= MAX_WORDS:
            drop(f"more than {MAX_WORDS} words")
        else:
            kept[key] = {"respelling": resp, "ipa": ipa if ipa and len(ipa) <= IPA_MAX and "[" not in ipa else None}
    return kept, [{"reason": k, "count": v} for k, v in dropped.items()]


def propose(script: Script, llm) -> dict:
    flagged, note = flag_words(script)
    llm_ok = bool(getattr(llm, "available", False))
    fake = "fake" in getattr(llm, "name", "")
    provider = (llm.name if fake else f"{llm.name} ({getattr(llm, 'model', '')})") if llm_ok else None
    dropped: list[dict] = []
    todo = [r for r in flagged if not r["confirmed"]]
    if llm_ok and todo:
        out = llm.complete_structured(SYSTEM, build_user_prompt(script, todo), SayingsOutput, max_tokens=4000)
        if out is not None:
            kept, dropped = validate_sayings(out, todo)
            for r in todo:
                if r["key"] in kept:
                    r.update(kept[r["key"]], source=f"proposed by {provider}: confirm it")
    return {"words": flagged, "note": note, "dropped": dropped, "provider": provider,
            "reason": None if llm_ok else "Without an ANTHROPIC_API_KEY nothing is proposed: type how you say each word, "
                                          "then Confirm. Hear it uses what you confirm."}
