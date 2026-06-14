import unittest

import pandas as pd

from server.services.analysis_service import AnalysisService


class AnalysisServiceTest(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(
            {
                "feature": [1, 2, 3, 4, 5, 6, 7, 8],
                "target_num": [2, 4, 6, 8, 10, 12, 14, 16],
                "category": ["a", "b", "a", "b", "a", "b", "a", "b"],
                "class_target": [0, 1, 0, 1, 0, 1, 0, 1],
            }
        )

    def test_correlation_returns_coefficient_and_grouped_trend(self):
        result = AnalysisService.correlation(self.df, "feature", "target_num")

        self.assertAlmostEqual(result["coefficient"], 1.0)
        self.assertEqual(result["rows_used"], 8)
        self.assertEqual(result["trend"]["kind"], "grouped")
        self.assertEqual(len(result["trend"]["points"]), 8)
        self.assertTrue(all("count" in point for point in result["trend"]["points"]))
        self.assertTrue(result["insights"])

    def test_correlation_bins_continuous_pairs_for_readability(self):
        df = pd.DataFrame(
            {
                "feature": list(range(60)),
                "target_num": [value * 1.5 for value in range(60)],
            }
        )

        result = AnalysisService.correlation(df, "feature", "target_num")

        self.assertEqual(result["trend"]["kind"], "binned")
        self.assertLessEqual(len(result["trend"]["points"]), AnalysisService.TREND_BIN_LIMIT)
        self.assertEqual(sum(point["count"] for point in result["trend"]["points"]), 60)
        self.assertTrue(result["insights"])

    def test_linear_regression_returns_trend_for_visualization(self):
        result = AnalysisService.linear_regression(self.df, "feature", "target_num")

        self.assertAlmostEqual(result["slope"], 2.0)
        self.assertAlmostEqual(result["intercept"], 0.0)
        self.assertEqual(result["trend"]["kind"], "grouped")
        self.assertTrue(result["trend"]["points"])
        self.assertTrue(result["insights"])

    def test_detect_outliers_handles_constant_columns(self):
        df = pd.DataFrame({"constant": [5, 5, 5, 5]})

        result = AnalysisService.detect_outliers(df, "constant")

        self.assertEqual(result["outliers_count"], 0)
        self.assertEqual(result["outliers"], [])

    def test_compare_models_returns_metrics_and_feature_importance(self):
        df = pd.DataFrame(
            {
                "age": list(range(20, 60)),
                "bmi": [20 + (index % 8) for index in range(40)],
                "smoker": ["yes" if index % 2 else "no" for index in range(40)],
                "target": [index % 2 for index in range(40)],
            }
        )

        result = AnalysisService.compare_models(df, "target")

        self.assertEqual(len(result["models"]), 2)
        self.assertGreater(result["rows_train"], 0)
        self.assertGreater(result["rows_test"], 0)
        self.assertTrue(result["feature_importance"])
        self.assertTrue(result["insights"])

    def test_compare_models_rejects_continuous_targets(self):
        df = pd.DataFrame(
            {
                "feature": list(range(40)),
                "target": [value * 0.5 for value in range(40)],
            }
        )

        with self.assertRaisesRegex(ValueError, "categorical"):
            AnalysisService.compare_models(df, "target")

    def test_compare_models_supports_regression_and_imputes_feature_missing_values(self):
        df = pd.DataFrame(
            {
                "area": [80, 95, 110, 140, 160, 190, 210, 240, 260, 300],
                "rooms": [2, 2, None, 3, 3, 4, 4, 5, 5, 6],
                "district": ["a", "a", "a", "b", "b", None, "c", "c", "d", "d"],
                "price": [100, 115, 128, 150, 170, 205, 230, 260, 280, 320],
            }
        )

        result = AnalysisService.compare_models(
            df,
            "price",
            task_type="regression",
            feature_columns=["area", "rooms", "district"],
        )

        self.assertEqual(result["task_type"], "regression")
        self.assertEqual(len(result["models"]), 2)
        self.assertTrue(result["preprocessing"]["missing_actions"])
        self.assertIn("rmse", result["models"][0])

    def test_correlation_rejects_unknown_method(self):
        with self.assertRaisesRegex(ValueError, "Unknown correlation method"):
            AnalysisService.correlation(self.df, "feature", "target_num", method="kendall")

    def test_correlation_rejects_insufficient_numeric_rows(self):
        df = pd.DataFrame({"x": [None, 1], "y": [None, None]})

        with self.assertRaisesRegex(ValueError, "Not enough numeric rows"):
            AnalysisService.correlation(df, "x", "y")

    def test_histogram_returns_numeric_bins(self):
        result = AnalysisService.histogram(self.df, "feature", bins=4)

        self.assertEqual(result["kind"], "numeric")
        self.assertEqual(len(result["counts"]), 4)
        self.assertEqual(len(result["edges"]), 5)

    def test_histogram_returns_categorical_counts(self):
        result = AnalysisService.histogram(self.df, "category", bins=2)

        self.assertEqual(result["kind"], "categorical")
        self.assertEqual(result["labels"], ["a", "b"])
        self.assertEqual(result["counts"], [4, 4])

    def test_missing_values_are_sorted_by_count(self):
        df = pd.DataFrame({"a": [1, None, None], "b": [None, 2, 3]})

        result = AnalysisService.missing_values(df)

        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["items"][0]["column"], "a")
        self.assertEqual(result["items"][0]["missing_count"], 2)

    def test_feature_correlation_with_target_returns_ranked_items(self):
        result = AnalysisService.feature_correlation_with_target(self.df, "target_num")

        self.assertEqual(result["target"], "target_num")
        self.assertEqual(result["items"][0]["feature"], "feature")
        self.assertEqual(result["items"][0]["rows_used"], 8)
        self.assertTrue(result["insights"])

    def test_feature_correlation_uses_pairwise_rows_with_missing_values(self):
        df = pd.DataFrame(
            {
                "target": [1, 2, 3, 4, 5],
                "feature": [1, 2, None, 4, None],
                "empty": [None, None, None, None, None],
            }
        )

        result = AnalysisService.feature_correlation_with_target(df, "target")

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["feature"], "feature")
        self.assertEqual(result["items"][0]["rows_used"], 3)

    def test_feature_correlation_rejects_non_numeric_target(self):
        with self.assertRaisesRegex(ValueError, "must be numeric"):
            AnalysisService.feature_correlation_with_target(self.df, "category")

    def test_detect_outliers_returns_summary_statistics(self):
        df = pd.DataFrame({"value": [1, 2, 3, 4, 100]})

        result = AnalysisService.detect_outliers(df, "value", threshold=1.5)

        self.assertIn("summary", result)
        self.assertIn("median", result["summary"])
        self.assertGreaterEqual(result["outliers_count"], 1)

    def test_compare_models_uses_only_selected_features(self):
        df = pd.DataFrame(
            {
                "signal": list(range(40)),
                "noise": ["x" if index % 2 else "y" for index in range(40)],
                "target": [index % 2 for index in range(40)],
            }
        )

        result = AnalysisService.compare_models(df, "target", feature_columns=["signal"])

        self.assertEqual(result["preprocessing"]["selected_features"], ["signal"])
        self.assertTrue(result["feature_importance"])

    def test_compare_models_rejects_empty_feature_selection(self):
        with self.assertRaisesRegex(ValueError, "No feature columns selected"):
            AnalysisService.compare_models(self.df, "class_target", feature_columns=[])

    def test_compare_models_rejects_single_class_target(self):
        df = pd.DataFrame({"feature": [1, 2, 3, 4, 5], "target": [1, 1, 1, 1, 1]})

        with self.assertRaisesRegex(ValueError, "at least two classes"):
            AnalysisService.compare_models(df, "target")

    def test_regression_rejects_non_numeric_target_values(self):
        df = pd.DataFrame({"feature": [1, 2, 3, 4, 5], "target": ["a", "b", "c", "d", "e"]})

        with self.assertRaisesRegex(ValueError, "Regression target has no numeric values"):
            AnalysisService.compare_models(df, "target", task_type="regression")

    def test_compare_models_aggregates_categorical_feature_importance_to_source_column(self):
        df = pd.DataFrame(
            {
                "segment": ["a", "b", "a", "b", "c", "c", "a", "b", "c", "a", "b", "c"],
                "target": [0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1],
            }
        )

        result = AnalysisService.compare_models(df, "target", feature_columns=["segment"])

        self.assertEqual(result["feature_importance"][0]["feature"], "segment")


if __name__ == "__main__":
    unittest.main()
