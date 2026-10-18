#!/usr/bin/env python3
"""Plainspoke: an offline prose readability checker.

Scores plain text or Markdown with six classic readability measures, flags
long sentences, passive-voice constructions and filler words with line and
column numbers, compares two drafts side by side, and can fail a CI run when
the text is harder to read than a limit you set. Standard library only.
"""

import argparse
import bisect
import json
import math
import re
import sys

WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
PIECE_RE = re.compile(r"[^.!?]*[.!?]+|[^.!?]+")
BLOCK_RE = re.compile(r"[^\n]*\S[^\n]*(?:\n(?=[^\n]*\S)[^\n]*)*")
BLANK_RE = re.compile(r"[^\n]")
PASSIVE_RE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(\w+(?:ed|en))\b",
    re.IGNORECASE,
)
FILLER_RE = re.compile(
    r"\b(very|really|just|quite|basically|actually|literally|simply|somewhat"
    r"|rather|pretty|totally|honestly|obviously|clearly)\b",
    re.IGNORECASE,
)

# Words that match the passive pattern but are adjectives or ordinary nouns.
PASSIVE_EXCLUDE = {
    "red", "bed", "need", "needed", "speed", "indeed", "seed", "shed", "feed",
    "embed", "hundred", "sacred", "naked", "wicked", "ragged", "aged", "open",
    "even", "when", "then", "often", "green", "ten", "seven", "kitchen",
    "garden", "children", "women",
}

# Markdown syntax that is not prose. Each pattern is blanked with spaces so
# that character offsets, and therefore line numbers, stay where they were.
MARKDOWN_PATTERNS = [
    re.compile(r"^(```|~~~)[^\n]*\n.*?^\1[ \t]*$", re.MULTILINE | re.DOTALL),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"https?://\S+"),
    re.compile(r"\]\([^)\n]*\)"),
    re.compile(r"^[ \t]*#{1,6}(?=[ \t])", re.MULTILINE),
    re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])(?=[ \t])", re.MULTILINE),
]

EASE_BANDS = [
    (90, "very easy"),
    (80, "easy"),
    (70, "fairly easy"),
    (60, "standard"),
    (50, "fairly difficult"),
    (30, "difficult"),
    (-math.inf, "very difficult"),
]

COMPARE_FIELDS = [
    ("Words", "words"),
    ("Sentences", "sentences"),
    ("Flesch reading ease", "flesch_reading_ease"),
    ("Flesch-Kincaid grade", "flesch_kincaid_grade"),
    ("Gunning fog", "gunning_fog"),
    ("SMOG", "smog"),
    ("Coleman-Liau", "coleman_liau"),
    ("Automated readability", "automated_readability_index"),
    ("Consensus grade", "consensus_grade"),
    ("Long sentences", "long_sentence_count"),
    ("Passive constructions", "passive_count"),
    ("Filler words", "filler_count"),
]


def count_syllables(word):
    """Estimate syllables with vowel groups, silent-e and -ed rules. Never below 1."""
    letters = re.sub(r"[^a-z]", "", word.lower())
    if len(letters) <= 3:
        return 1
    if letters.endswith("e") and not letters.endswith("le"):
        letters = letters[:-1]
    elif letters.endswith("ed") and not letters.endswith(("ted", "ded")):
        letters = letters[:-2]
    return max(1, len(re.findall(r"[aeiouy]+", letters)))


def flesch_reading_ease(words, sentences, syllables):
    return 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)


def flesch_kincaid_grade(words, sentences, syllables):
    return 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59


def gunning_fog(words, sentences, complex_words):
    return 0.4 * ((words / sentences) + 100 * (complex_words / words))


def smog(sentences, complex_words):
    return 1.043 * math.sqrt(complex_words * 30 / sentences) + 3.1291


def coleman_liau(words, sentences, letters):
    return 0.0588 * (letters / words * 100) - 0.296 * (sentences / words * 100) - 15.8


def automated_readability_index(words, sentences, letters):
    return 4.71 * (letters / words) + 0.5 * (words / sentences) - 21.43


def ease_band(score):
    for floor, label in EASE_BANDS:
        if score >= floor:
            return label
    return EASE_BANDS[-1][1]


def mask_markdown(text):
    """Blank out code, URLs, link targets and list/heading markers, keeping offsets."""
    for pattern in MARKDOWN_PATTERNS:
        text = pattern.sub(lambda match: BLANK_RE.sub(" ", match.group(0)), text)
    return text


def analyse(text, source="<text>", markdown=False, max_sentence_words=25):
    """Score a document and return a JSON-friendly dict. Raises ValueError with no words."""
    masked = mask_markdown(text) if markdown else text
    newlines = [i for i, ch in enumerate(masked) if ch == "\n"]

    def locate(offset):
        count = bisect.bisect_right(newlines, offset)
        line_start = newlines[count - 1] + 1 if count else 0
        return count + 1, offset - line_start + 1

    all_words = []
    sentences = []
    paragraphs = []
    for block in BLOCK_RE.finditer(masked):
        para = {"index": len(paragraphs) + 1, "line": locate(block.start())[0],
                "words": 0, "sentences": 0, "syllables": 0}
        for piece in PIECE_RE.finditer(block.group(0)):
            words = WORD_RE.findall(piece.group(0))
            if not words:
                continue
            first = WORD_RE.search(piece.group(0))
            offset = block.start() + piece.start() + first.start()
            sentences.append({
                "line": locate(offset)[0],
                "words": len(words),
                "text": " ".join(piece.group(0).split()),
            })
            para["words"] += len(words)
            para["sentences"] += 1
            para["syllables"] += sum(count_syllables(w) for w in words)
            all_words.extend(words)
        if para["words"]:
            paragraphs.append(para)

    word_count = len(all_words)
    if word_count == 0:
        raise ValueError(f"{source}: no words found to score")
    sentence_count = len(sentences)
    syllables = [count_syllables(w) for w in all_words]
    total_syllables = sum(syllables)
    complex_words = sum(1 for s in syllables if s >= 3)
    letters = sum(len(w.replace("'", "").replace("’", "")) for w in all_words)
    ly_adverbs = sum(1 for w in all_words if len(w) > 4 and w.lower().endswith("ly"))

    fre = flesch_reading_ease(word_count, sentence_count, total_syllables)
    fkgl = flesch_kincaid_grade(word_count, sentence_count, total_syllables)
    fog = gunning_fog(word_count, sentence_count, complex_words)
    smog_grade = smog(sentence_count, complex_words)
    cli = coleman_liau(word_count, sentence_count, letters)
    ari = automated_readability_index(word_count, sentence_count, letters)
    consensus = (fkgl + fog + smog_grade + cli + ari) / 5

    long_sentences = [
        {"line": s["line"], "words": s["words"], "text": s["text"]}
        for s in sentences if s["words"] > max_sentence_words
    ]
    passive = []
    for match in PASSIVE_RE.finditer(masked):
        if match.group(1).lower() in PASSIVE_EXCLUDE:
            continue
        line, col = locate(match.start())
        passive.append({"line": line, "col": col, "text": match.group(0)})
    filler = []
    for match in FILLER_RE.finditer(masked):
        line, col = locate(match.start())
        filler.append({"line": line, "col": col, "word": match.group(0).lower()})

    warnings = []
    if sentence_count < 30:
        warnings.append("SMOG is only reliable with 30 or more sentences; "
                        f"this text has {sentence_count}.")

    para_rows = [{
        "index": p["index"],
        "line": p["line"],
        "words": p["words"],
        "sentences": p["sentences"],
        "avg_sentence": round(p["words"] / p["sentences"], 2),
        "flesch_reading_ease": round(
            flesch_reading_ease(p["words"], p["sentences"], p["syllables"]), 2),
    } for p in paragraphs]

    summary = {
        "words": word_count,
        "sentences": sentence_count,
        "paragraphs": len(paragraphs),
        "syllables": total_syllables,
        "complex_words": complex_words,
        "ly_adverbs": ly_adverbs,
        "flesch_reading_ease": round(fre, 2),
        "flesch_kincaid_grade": round(fkgl, 2),
        "gunning_fog": round(fog, 2),
        "smog": round(smog_grade, 2),
        "coleman_liau": round(cli, 2),
        "automated_readability_index": round(ari, 2),
        "consensus_grade": round(consensus, 2),
        "long_sentence_count": len(long_sentences),
        "passive_count": len(passive),
        "filler_count": len(filler),
    }
    return {
        "source": source,
        "max_sentence_words": max_sentence_words,
        "markdown": markdown,
        "band": ease_band(fre),
        "summary": summary,
        "long_sentences": long_sentences,
        "passive": passive,
        "filler": filler,
        "paragraphs": para_rows,
        "warnings": warnings,
        "gate_failures": [],
    }


def gate_failures(result, max_grade=None, min_ease=None):
    failures = []
    summary = result["summary"]
    if max_grade is not None and summary["consensus_grade"] > max_grade:
        failures.append(f"consensus grade {summary['consensus_grade']} "
                        f"is above the limit of {max_grade}")
    if min_ease is not None and summary["flesch_reading_ease"] < min_ease:
        failures.append(f"Flesch reading ease {summary['flesch_reading_ease']} "
                        f"is below the minimum of {min_ease}")
    return failures


def _excerpt(text, limit=70):
    return text if len(text) <= limit else text[:limit - 3] + "..."


def format_report(result, show_paragraphs=False):
    s = result["summary"]
    avg_words = s["words"] / s["sentences"]
    complex_pct = 100 * s["complex_words"] / s["words"]
    out = [f"Plainspoke report: {result['source']}", "", "Text"]
    out.append(f"  {'Words':<22}{s['words']}")
    out.append(f"  {'Sentences':<22}{s['sentences']}  (avg {avg_words:.1f} words each)")
    out.append(f"  {'Paragraphs':<22}{s['paragraphs']}")
    out.append(f"  {'Syllables':<22}{s['syllables']}  "
               f"({s['syllables'] / s['words']:.2f} per word)")
    out.append(f"  {'Complex words':<22}{s['complex_words']}  "
               f"({complex_pct:.1f}%, three or more syllables)")
    out.append("")
    out.append("Scores")
    out.append(f"  {'Flesch reading ease':<26}{s['flesch_reading_ease']:>7.1f}  {result['band']}")
    out.append(f"  {'Flesch-Kincaid grade':<26}{s['flesch_kincaid_grade']:>7.1f}")
    out.append(f"  {'Gunning fog':<26}{s['gunning_fog']:>7.1f}")
    out.append(f"  {'SMOG':<26}{s['smog']:>7.1f}")
    out.append(f"  {'Coleman-Liau':<26}{s['coleman_liau']:>7.1f}")
    out.append(f"  {'Automated readability index':<26}{s['automated_readability_index']:>7.1f}")
    out.append(f"  {'Consensus grade':<26}{s['consensus_grade']:>7.1f}")
    out.append("")
    out.append("Flags")
    out.append(f"  Long sentences (over {result['max_sentence_words']} words): "
               f"{s['long_sentence_count']}")
    for item in result["long_sentences"]:
        out.append(f"    line {item['line']}: {item['words']} words: "
                   f"\"{_excerpt(item['text'])}\"")
    out.append(f"  Passive constructions: {s['passive_count']}")
    for item in result["passive"]:
        out.append(f"    line {item['line']}, col {item['col']}: \"{item['text']}\"")
    out.append(f"  Filler words: {s['filler_count']}")
    for item in result["filler"]:
        out.append(f"    line {item['line']}, col {item['col']}: \"{item['word']}\"")
    if show_paragraphs:
        out.append("")
        out.append("Paragraphs")
        out.append(f"  {'#':>3} {'line':>5} {'words':>6} {'sents':>6} {'avg':>6} {'FRE':>7}")
        for p in result["paragraphs"]:
            out.append(f"  {p['index']:>3} {p['line']:>5} {p['words']:>6} "
                       f"{p['sentences']:>6} {p['avg_sentence']:>6.1f} "
                       f"{p['flesch_reading_ease']:>7.1f}")
    for warning in result["warnings"]:
        out.append("")
        out.append(f"Note: {warning}")
    return "\n".join(out)


def format_compare(old, new):
    rows = [f"Plainspoke compare: {old['source']} -> {new['source']}", ""]
    rows.append(f"  {'Metric':<28}{'old':>10}{'new':>10}{'change':>10}")
    for label, key in COMPARE_FIELDS:
        before = old["summary"][key]
        after = new["summary"][key]
        change = after - before
        rows.append(f"  {label:<28}{before:>10.2f}{after:>10.2f}{change:>+10.2f}")
    return "\n".join(rows)


def read_source(path):
    if path == "-":
        return sys.stdin.read(), "<stdin>"
    with open(path, encoding="utf-8") as handle:
        return handle.read(), path


def want_markdown(args, path):
    if args.markdown:
        return True
    if args.text:
        return False
    return path.lower().endswith((".md", ".markdown"))


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_parser():
    parser = argparse.ArgumentParser(
        prog="plainspoke",
        description="Offline readability checker for plain text and Markdown.")
    sub = parser.add_subparsers(dest="command", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--markdown", action="store_true",
                        help="ignore code, URLs and markup (automatic for .md files)")
    shared.add_argument("--text", action="store_true",
                        help="treat the input as plain text even for .md files")
    shared.add_argument("--json", action="store_true", help="print JSON instead of a report")
    shared.add_argument("--max-sentence-words", type=positive_int, default=25,
                        help="flag sentences longer than this (default: 25)")

    check = sub.add_parser("check", parents=[shared], help="score one file")
    check.add_argument("path", help="file to read, or - for stdin")
    check.add_argument("--paragraphs", action="store_true",
                       help="include a per-paragraph breakdown")
    check.add_argument("--max-grade", type=float,
                       help="exit 1 if the consensus grade is above this")
    check.add_argument("--min-ease", type=float,
                       help="exit 1 if Flesch reading ease is below this")

    compare = sub.add_parser("compare", parents=[shared], help="compare two files")
    compare.add_argument("old", help="earlier draft")
    compare.add_argument("new", help="later draft")
    return parser


def run_check(args):
    text, source = read_source(args.path)
    result = analyse(text, source, want_markdown(args, args.path), args.max_sentence_words)
    result["gate_failures"] = gate_failures(result, args.max_grade, args.min_ease)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result, args.paragraphs))
    for failure in result["gate_failures"]:
        print(f"plainspoke: gate failed: {failure}", file=sys.stderr)
    return 1 if result["gate_failures"] else 0


def run_compare(args):
    old_text, old_name = read_source(args.old)
    new_text, new_name = read_source(args.new)
    old = analyse(old_text, old_name, want_markdown(args, args.old), args.max_sentence_words)
    new = analyse(new_text, new_name, want_markdown(args, args.new), args.max_sentence_words)
    if args.json:
        rows = [{"metric": label, "old": old["summary"][key],
                 "new": new["summary"][key],
                 "change": round(new["summary"][key] - old["summary"][key], 2)}
                for label, key in COMPARE_FIELDS]
        print(json.dumps({"old": old["source"], "new": new["source"], "rows": rows},
                         indent=2, ensure_ascii=False))
    else:
        print(format_compare(old, new))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return run_check(args)
        return run_compare(args)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"plainspoke: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
