import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plainspoke  # noqa: E402
from plainspoke import (  # noqa: E402
    analyse,
    automated_readability_index,
    coleman_liau,
    count_syllables,
    ease_band,
    flesch_kincaid_grade,
    flesch_reading_ease,
    gate_failures,
    gunning_fog,
    main,
    mask_markdown,
    smog,
)

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "draft.md")


def run_cli(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class SyllableTests(unittest.TestCase):
    def test_short_words_are_one_syllable(self):
        self.assertEqual(count_syllables("cat"), 1)
        self.assertEqual(count_syllables("the"), 1)

    def test_silent_e_is_not_counted(self):
        self.assertEqual(count_syllables("make"), 1)

    def test_le_ending_keeps_its_vowel(self):
        self.assertEqual(count_syllables("table"), 2)

    def test_ed_ending_is_dropped_unless_t_or_d(self):
        self.assertEqual(count_syllables("walked"), 1)
        self.assertEqual(count_syllables("wanted"), 2)

    def test_longer_words(self):
        self.assertEqual(count_syllables("beautiful"), 3)
        self.assertEqual(count_syllables("education"), 4)


class FormulaTests(unittest.TestCase):
    def test_flesch_reading_ease(self):
        self.assertAlmostEqual(flesch_reading_ease(100, 5, 150), 59.635, places=6)

    def test_flesch_kincaid_grade(self):
        self.assertAlmostEqual(flesch_kincaid_grade(100, 5, 150), 9.91, places=6)

    def test_gunning_fog(self):
        self.assertAlmostEqual(gunning_fog(100, 5, 10), 12.0, places=6)

    def test_smog(self):
        self.assertAlmostEqual(smog(30, 9), 6.2581, places=4)

    def test_coleman_liau(self):
        self.assertAlmostEqual(coleman_liau(100, 5, 400), 6.24, places=6)

    def test_automated_readability_index(self):
        self.assertAlmostEqual(automated_readability_index(100, 5, 400), 7.41, places=6)

    def test_ease_band_labels(self):
        self.assertEqual(ease_band(95), "very easy")
        self.assertEqual(ease_band(65), "standard")
        self.assertEqual(ease_band(10), "very difficult")


class MarkdownTests(unittest.TestCase):
    def test_inline_code_and_urls_are_masked_and_keep_length(self):
        text = "Use `rm -rf` now. See https://example.com/a now."
        masked = mask_markdown(text)
        self.assertEqual(len(masked), len(text))
        self.assertNotIn("rm", masked)
        self.assertNotIn("example", masked)

    def test_fenced_code_blocks_are_ignored_in_markdown_mode(self):
        text = "Intro here.\n```\nfoo bar baz\n```\nOutro here."
        result = analyse(text, markdown=True)
        self.assertEqual(result["summary"]["words"], 4)
        self.assertEqual(result["summary"]["sentences"], 2)

    def test_plain_mode_counts_code_words(self):
        text = "Use `rm -rf` now."
        self.assertGreater(analyse(text)["summary"]["words"], 2)


class AnalysisTests(unittest.TestCase):
    def test_basic_counts(self):
        result = analyse("The cat sat. The dog ran.")
        self.assertEqual(result["summary"]["words"], 6)
        self.assertEqual(result["summary"]["sentences"], 2)
        self.assertEqual(result["summary"]["syllables"], 6)
        self.assertEqual(result["summary"]["paragraphs"], 1)

    def test_empty_text_raises(self):
        with self.assertRaises(ValueError):
            analyse("   \n\n  ")

    def test_long_sentence_flagged_with_line_number(self):
        text = "Short one.\n" + " ".join(["word"] * 30) + "."
        result = analyse(text, max_sentence_words=25)
        self.assertEqual(result["summary"]["long_sentence_count"], 1)
        self.assertEqual(result["long_sentences"][0]["line"], 2)
        self.assertEqual(result["long_sentences"][0]["words"], 30)

    def test_passive_voice_is_flagged(self):
        result = analyse("The file was saved quickly.")
        self.assertEqual(result["summary"]["passive_count"], 1)
        self.assertEqual(result["passive"][0]["text"], "was saved")

    def test_adjective_false_positive_is_excluded(self):
        result = analyse("The sky is red.")
        self.assertEqual(result["summary"]["passive_count"], 0)

    def test_filler_word_column_and_line(self):
        result = analyse("It is.\nIt is really good.")
        self.assertEqual(result["filler"], [{"line": 2, "col": 7, "word": "really"}])

    def test_paragraph_breakdown_lines(self):
        result = analyse("One two.\n\nThree four five.")
        self.assertEqual(len(result["paragraphs"]), 2)
        self.assertEqual(result["paragraphs"][0]["line"], 1)
        self.assertEqual(result["paragraphs"][1]["line"], 3)
        self.assertEqual(result["paragraphs"][1]["words"], 3)

    def test_small_sample_warning(self):
        result = analyse("The cat sat.")
        self.assertTrue(any("SMOG" in note for note in result["warnings"]))

    def test_gate_failures(self):
        result = analyse("The cat sat. The dog ran.")
        grade = result["summary"]["consensus_grade"]
        ease = result["summary"]["flesch_reading_ease"]
        self.assertEqual(len(gate_failures(result, max_grade=grade - 1)), 1)
        self.assertEqual(gate_failures(result, max_grade=grade + 1), [])
        self.assertEqual(len(gate_failures(result, min_ease=ease + 1)), 1)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_check_example_report_runs(self):
        code, out, _ = run_cli(["check", EXAMPLE, "--paragraphs"])
        self.assertEqual(code, 0)
        self.assertIn("Consensus grade", out)
        self.assertIn("Paragraphs", out)

    def test_check_json_output(self):
        path = self.write("a.txt", "The cat sat. The dog ran.")
        code, out, _ = run_cli(["check", path, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["summary"]["words"], 6)

    def test_failing_gate_returns_one(self):
        path = self.write("a.txt", "The cat sat. The dog ran.")
        code, _, err = run_cli(["check", path, "--max-grade", "-50"])
        self.assertEqual(code, 1)
        self.assertIn("gate failed", err)

    def test_markdown_extension_is_detected(self):
        path = self.write("a.md", "Intro here.\n```\nfoo bar baz\n```\n")
        code, out, _ = run_cli(["check", path, "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["markdown"])

    def test_compare_prints_table(self):
        old = self.write("old.txt", "The cat sat. The dog ran.")
        new = self.write("new.txt", "Cats sit. Dogs run fast.")
        code, out, _ = run_cli(["compare", old, new])
        self.assertEqual(code, 0)
        self.assertIn("Flesch reading ease", out)
        self.assertIn("change", out)

    def test_missing_file_returns_two(self):
        code, _, err = run_cli(["check", os.path.join(self.tmp.name, "nope.txt")])
        self.assertEqual(code, 2)
        self.assertIn("plainspoke:", err)

    def test_empty_file_returns_two(self):
        path = self.write("empty.txt", "   ")
        code, _, err = run_cli(["check", path])
        self.assertEqual(code, 2)
        self.assertIn("no words", err)


if __name__ == "__main__":
    unittest.main()
