"""
Regression test suite asserting zero regressions against the frozen 146-page benchmark.
"""

import unittest
from evaluation.benchmark import run_benchmark, BASELINE_METRICS


class TestBaselineRegression(unittest.TestCase):
    def test_benchmark_matches_or_exceeds_baseline(self):
        """Asserts exact parity with the frozen 146-page baseline (95.21% page accuracy, 0 regressions)."""
        import tempfile, csv
        from pathlib import Path
        with open("data/canonical_labels.csv", "r", encoding="utf-8", errors="replace") as f_in:
            r = csv.reader(f_in)
            rows = [row[:13] for row in r]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f_out:
            w = csv.writer(f_out)
            w.writerows(rows)
            tmp_path = Path(f_out.name)
        res = run_benchmark(ground_truth_path=tmp_path, save_reports=False)

        self.assertEqual(res["total_pages"], BASELINE_METRICS["total_pages"])
        self.assertGreaterEqual(res["exact_match_pages"], BASELINE_METRICS["exact_match_pages"])
        self.assertGreaterEqual(res["page_level_accuracy"], BASELINE_METRICS["page_level_accuracy"])

        # Check field accuracies
        for field, target_acc in BASELINE_METRICS["field_accuracies"].items():
            actual_acc = res["field_accuracies"][field]["accuracy_percent"]
            self.assertGreaterEqual(
                actual_acc,
                target_acc,
                f"Field '{field}' regressed: {actual_acc}% < {target_acc}%",
            )

        # Assert zero new regressions
        self.assertTrue(
            res["is_regression_free"],
            f"New regressions detected: {res['new_regressions']}",
        )
        self.assertEqual(len(res["new_regressions"]), 0)


if __name__ == "__main__":
    unittest.main()
