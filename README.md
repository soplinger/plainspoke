# Plainspoke

**An offline prose readability checker that tells you how hard your writing is to read, and where to fix it.**

Plainspoke scores plain text or Markdown with six classic readability measures, points at long sentences, passive constructions and filler words by line and column, compares two drafts, and can fail a CI job when the text gets too hard. It is a single Python file using only the standard library. Nothing leaves your machine.

## Features

- Six readability scores: Flesch reading ease, Flesch-Kincaid grade, Gunning fog, SMOG, Coleman-Liau and Automated Readability Index.
- A consensus grade that averages the five grade-level formulas (Flesch-Kincaid, Gunning fog, SMOG, Coleman-Liau and ARI), so one odd score does not decide the verdict.
- A plain-English reading band for Flesch reading ease, from "very easy" to "very difficult".
- Text statistics: words, sentences, paragraphs, syllables, complex words (three or more syllables) and `-ly` adverbs.
- Long-sentence flags with the line number and the sentence excerpt. The limit is set with `--max-sentence-words`, which defaults to 25.
- Passive-voice detection with line and column, using a heuristic that skips common adjectives such as "red" and "open".
- Filler-word detection (`really`, `very`, `just`, `basically` and others) with line and column.
- Markdown awareness: fenced and inline code, URLs, link targets, heading and list markers are ignored. This happens automatically for `.md` files, and `--markdown` or `--text` override it. Line numbers still match the original file.
- A per-paragraph breakdown (`--paragraphs`) with line, word count, average sentence length and reading ease for each paragraph.
- Side-by-side comparison of two drafts (`compare OLD NEW`) with the change in each metric.
- JSON output (`--json`) for dashboards and scripts.
- CI gates: `--max-grade` and `--min-ease` return exit code 1 when the text is too hard, and print the failed gate to stderr.
- Reads from standard input with `-`, so it fits into pipelines.
- Small-sample warning: SMOG needs 30 or more sentences, and Plainspoke says so when a text is shorter.

## Quick start

```sh
python3 plainspoke.py check examples/draft.md --paragraphs
```

This reads a short sample quarterly update. Because the file ends in `.md`, code and URLs are ignored automatically. The report has four parts:

1. **Text**: word, sentence, paragraph and syllable counts.
2. **Scores**: each readability formula, the reading band and the consensus grade.
3. **Flags**: every long sentence, passive construction and filler word, each with its line (and column where it applies).
4. **Paragraphs**: one row per paragraph, shown because of `--paragraphs`.

To see what an edit changed, compare the old and new drafts:

```sh
python3 plainspoke.py compare examples/draft.md examples/draft.md
```

## Usage

```text
plainspoke.py check FILE [--markdown | --text] [--json] [--paragraphs]
                         [--max-sentence-words N] [--max-grade G] [--min-ease E]
plainspoke.py compare OLD NEW [--markdown | --text] [--json] [--max-sentence-words N]
```

Exit codes: `0` on success, `1` when a gate fails, `2` on input errors such as a missing file, invalid UTF-8 or a file with no words.

Use it as a gate in CI:

```sh
python3 plainspoke.py check docs/guide.md --max-grade 9 --min-ease 50
```

## How the scores work

| Measure | Formula (words W, sentences S, syllables Sy) |
| --- | --- |
| Flesch reading ease | 206.835 − 1.015·(W/S) − 84.6·(Sy/W) |
| Flesch-Kincaid grade | 0.39·(W/S) + 11.8·(Sy/W) − 15.59 |
| Gunning fog | 0.4·((W/S) + 100·(complex/W)) |
| SMOG | 1.043·√(complex·30/S) + 3.1291 |
| Coleman-Liau | 0.0588·L − 0.296·Sn − 15.8, where L is letters per 100 words and Sn is sentences per 100 words |
| Automated Readability Index | 4.71·(letters/W) + 0.5·(W/S) − 21.43 |

Syllables come from a vowel-group heuristic with silent-e and `-ed` rules. It is fast and predictable, but it is an estimate: rare or unusual words may be counted one syllable off. The formulas are the published ones, so the scores are comparable to other tools that use them, within that margin.

## Limits

- Sentences are split on `.`, `!` and `?`. Abbreviations such as "e.g." and decimal numbers count as sentence ends.
- A line without punctuation, such as a heading or a bullet, joins the sentence that follows it when there is no blank line between them.
- Passive-voice detection is a pattern match for a form of "be" followed by a word ending in `-ed` or `-en`. It finds "was saved" and "was taken" but misses irregular participles such as "was sent" or "was built", and it can flag some adjectives that end in `-en` or `-ed`. Treat its hits as candidates to read, not as errors.
- Readability formulas measure sentence and word length. They do not judge clarity, tone or accuracy.

## Run

Requires Python 3.8 or newer. There are no dependencies to install.

```sh
python3 plainspoke.py check path/to/file.txt
python3 plainspoke.py check path/to/file.md --paragraphs --json
cat draft.txt | python3 plainspoke.py check - --max-grade 8
```

## Test

The tests use `unittest`, which ships with Python, so they run without installing anything:

```sh
python3 -m unittest discover -s tests -v
```

They also run under pytest if you have it installed:

```sh
python3 -m pytest tests -v
```

The suite covers syllable rules, each formula against hand-computed values, Markdown masking, sentence and paragraph line numbers, passive and filler detection, the gates, the JSON output and the exit codes of the command-line interface.

## Project layout

```text
plainspoke.py                  the whole tool: analysis, reports and CLI
examples/draft.md              a sample Markdown draft to try it on
tests/test_plainspoke.py       unit and command-line tests
```
