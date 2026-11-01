"""投资研究分析纯函数的确定性测试。"""

from __future__ import annotations

import math
import unittest
from datetime import date, timedelta

from backend.app.services import analysis
from backend.app.services.analysis import AnalysisPoint


def pts(values):
    start = date(2024, 1, 1)
    return [AnalysisPoint(start + timedelta(days=i), value) for i, value in enumerate(values)]


class CumulativeReturnTest(unittest.TestCase):
    def test_positive_and_negative(self):
        self.assertAlmostEqual(0.1, analysis.cumulative_return(pts([10, 11])), places=10)
        self.assertAlmostEqual(-0.1, analysis.cumulative_return(pts([10, 9])), places=10)

    def test_single_point_returns_none(self):
        self.assertIsNone(analysis.cumulative_return(pts([10])))


class SanitizeTest(unittest.TestCase):
    def test_drops_invalid_and_duplicates(self):
        points = [
            AnalysisPoint(date(2024, 1, 1), 10),
            AnalysisPoint(date(2024, 1, 2), 0),
            AnalysisPoint(date(2024, 1, 3), -1),
            AnalysisPoint(date(2024, 1, 4), float("nan")),
            AnalysisPoint(date(2024, 1, 5), float("inf")),
            AnalysisPoint(date(2024, 1, 6), 11),
            AnalysisPoint(date(2024, 1, 6), 99),
        ]
        cleaned, notes = analysis.sanitize_points(points)
        self.assertEqual([10, 11], [point.value for point in cleaned])
        self.assertEqual(2, len(cleaned))
        self.assertTrue(notes)


class AnnualizedReturnTest(unittest.TestCase):
    def test_short_span_gain_is_compounded(self):
        start = date(2024, 1, 1)
        points = [AnalysisPoint(start, 10.0), AnalysisPoint(start + timedelta(days=30), 11.0)]
        self.assertGreater(analysis.annualized_return(points), 0.1)

    def test_short_span_loss_is_more_negative_than_cumulative(self):
        start = date(2024, 1, 1)
        points = [AnalysisPoint(start, 10.0), AnalysisPoint(start + timedelta(days=30), 9.0)]
        self.assertLess(analysis.annualized_return(points), -0.1)

    def test_one_year_is_exact_ratio_minus_one(self):
        start = date(2024, 1, 1)
        points = [AnalysisPoint(start, 10.0), AnalysisPoint(start + timedelta(days=365), 11.0)]
        self.assertAlmostEqual(0.1, analysis.annualized_return(points), places=10)

    def test_short_span_adds_instability_note(self):
        start = date(2024, 1, 1)
        points = [AnalysisPoint(start, 10.0), AnalysisPoint(start + timedelta(days=30), 11.0)]
        result = analysis.build_metrics("close", points)
        self.assertTrue(any("不稳定" in note for note in result.notes))


class MaxDrawdownTest(unittest.TestCase):
    def test_peak_and_trough_dates(self):
        points = [
            AnalysisPoint(date(2024, 1, 1), 10),
            AnalysisPoint(date(2024, 1, 2), 12),
            AnalysisPoint(date(2024, 1, 3), 9),
            AnalysisPoint(date(2024, 1, 4), 11),
        ]
        result = analysis.max_drawdown(points)
        self.assertEqual("2024-01-02", result.peak_date)
        self.assertEqual("2024-01-03", result.trough_date)
        self.assertAlmostEqual(-0.25, result.drawdown, places=10)


class VolatilityTest(unittest.TestCase):
    def test_constant_series_has_zero_volatility(self):
        values = [10.0 + i * 0 for i in range(40)]
        self.assertEqual(0.0, analysis.annualized_volatility(pts(values)))

    def test_two_moves_deterministic(self):
        points = pts([10, 11, 9.9])
        result = analysis.annualized_volatility(points)
        expected = math.sqrt(0.02) * math.sqrt(252)
        self.assertAlmostEqual(expected, result, places=10)


class ReturnRiskRatioTest(unittest.TestCase):
    def test_zero_volatility_returns_none(self):
        self.assertIsNone(analysis.return_risk_ratio(pts([10, 10, 10])))

    def test_positive_volatility_computes_ratio(self):
        start = date(2024, 1, 1)
        points = [
            AnalysisPoint(start, 10.0),
            AnalysisPoint(start + timedelta(days=15), 11.0),
            AnalysisPoint(start + timedelta(days=30), 9.9),
        ]
        ratio = analysis.return_risk_ratio(points)
        self.assertIsNotNone(ratio)
        self.assertTrue(math.isfinite(ratio))


class CompareTest(unittest.TestCase):
    def test_intersection_and_excess_return(self):
        asset_points = [
            AnalysisPoint(date(2024, 1, 1), 10),
            AnalysisPoint(date(2024, 1, 2), 11),
            AnalysisPoint(date(2024, 1, 4), 12),
        ]
        benchmark_points = [
            AnalysisPoint(date(2024, 1, 1), 100),
            AnalysisPoint(date(2024, 1, 2), 105),
            AnalysisPoint(date(2024, 1, 3), 106),
        ]
        result = analysis.compare_series(asset_points, benchmark_points)
        self.assertEqual(2, result["count"])
        self.assertEqual("2024-01-01", result["start_date"])
        self.assertEqual("2024-01-02", result["end_date"])
        self.assertAlmostEqual(0.1, result["asset_cumulative_return"], places=10)
        self.assertAlmostEqual(0.05, result["benchmark_cumulative_return"], places=10)
        self.assertAlmostEqual(0.05, result["excess_return"], places=10)

    def test_insufficient_intersection(self):
        result = analysis.compare_series(
            [AnalysisPoint(date(2024, 1, 1), 10)],
            [AnalysisPoint(date(2024, 1, 2), 10)],
        )
        self.assertIsNone(result["asset_cumulative_return"])
        self.assertIn("不足", result["error"])


class PortfolioTest(unittest.TestCase):
    def _items(self):
        return [
            {
                "asset_id": "a",
                "weight": 0.5,
                "points": [
                    AnalysisPoint(date(2024, 1, 1), 10),
                    AnalysisPoint(date(2024, 1, 2), 11),
                    AnalysisPoint(date(2024, 1, 3), 12),
                ],
            },
            {
                "asset_id": "b",
                "weight": 0.5,
                "points": [
                    AnalysisPoint(date(2024, 1, 1), 100),
                    AnalysisPoint(date(2024, 1, 2), 110),
                    AnalysisPoint(date(2024, 1, 3), 99),
                ],
            },
        ]

    def test_weight_validation(self):
        self.assertEqual(["权重合计必须为 100%"], analysis.validate_weights([0.4, 0.5]))
        self.assertTrue(analysis.validate_weights([-0.1, 1.1]))

    def test_aligned_portfolio(self):
        result = analysis.portfolio_analysis(self._items())
        self.assertEqual(2, result["count"])
        self.assertAlmostEqual(0.095, result["cumulative_return"], places=9)
        self.assertEqual(["a", "b"], [item["asset_id"] for item in result["contributions"]])
        self.assertAlmostEqual(0.1, result["contributions"][0]["contribution"], places=9)
        self.assertAlmostEqual(-0.005, result["contributions"][1]["contribution"], places=9)


if __name__ == "__main__":
    unittest.main()
