"""投资研究分析纯函数。所有函数不修改数据库、不发起网络请求。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date


PERIODS_PER_YEAR = 252


@dataclass(frozen=True)
class AnalysisPoint:
    date: date
    value: float


@dataclass(frozen=True)
class Drawdown:
    peak_date: str
    trough_date: str
    drawdown: float


@dataclass(frozen=True)
class MetricResult:
    metric: str
    first_date: str | None
    last_date: str | None
    count: int
    cumulative_return: float | None
    annualized_return: float | None
    annualized_volatility: float | None
    return_risk_ratio: float | None
    max_drawdown: Drawdown | None
    return_series: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def _finite_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def sanitize_points(points: list[AnalysisPoint]) -> tuple[list[AnalysisPoint], list[str]]:
    notes: list[str] = []
    seen: set[date] = set()
    cleaned: list[AnalysisPoint] = []
    for point in points:
        if not _finite_positive(point.value):
            notes.append(f"{point.date.isoformat()}: 无效数值已忽略")
            continue
        if point.date in seen:
            notes.append(f"{point.date.isoformat()}: 重复日期已忽略")
            continue
        seen.add(point.date)
        cleaned.append(point)
    cleaned.sort(key=lambda item: item.date)
    return cleaned, notes


def simple_returns(points: list[AnalysisPoint]) -> list[tuple[date, float]]:
    cleaned, _ = sanitize_points(points)
    returns = []
    for previous, current in zip(cleaned, cleaned[1:]):
        returns.append((current.date, current.value / previous.value - 1.0))
    return returns


def cumulative_return(points: list[AnalysisPoint]) -> float | None:
    cleaned, _ = sanitize_points(points)
    if len(cleaned) < 2:
        return None
    first, last = cleaned[0], cleaned[-1]
    if first.value <= 0:
        return None
    return last.value / first.value - 1.0


def annualized_return(points: list[AnalysisPoint]) -> float | None:
    cleaned, _ = sanitize_points(points)
    if len(cleaned) < 2:
        return None
    first, last = cleaned[0], cleaned[-1]
    span_days = (last.date - first.date).days
    if span_days <= 0 or first.value <= 0 or last.value <= 0:
        return None
    return (last.value / first.value) ** (365.0 / span_days) - 1.0


def annualized_volatility(points: list[AnalysisPoint]) -> float | None:
    returns = [ret for _, ret in simple_returns(points)]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(PERIODS_PER_YEAR)


def max_drawdown(points: list[AnalysisPoint]) -> Drawdown | None:
    cleaned, _ = sanitize_points(points)
    if len(cleaned) < 2:
        return None
    peak = cleaned[0]
    worst = Drawdown(
        peak_date=peak.date.isoformat(),
        trough_date=peak.date.isoformat(),
        drawdown=0.0,
    )
    for point in cleaned:
        if point.value > peak.value:
            peak = point
        drawdown = point.value / peak.value - 1.0
        if drawdown < worst.drawdown:
            worst = Drawdown(
                peak_date=peak.date.isoformat(),
                trough_date=point.date.isoformat(),
                drawdown=drawdown,
            )
    return worst


def return_risk_ratio(points: list[AnalysisPoint]) -> float | None:
    annualized = annualized_return(points)
    volatility = annualized_volatility(points)
    if annualized is None or volatility is None or volatility <= 0:
        return None
    return annualized / volatility


def build_metrics(metric: str, points: list[AnalysisPoint]) -> MetricResult:
    cleaned, notes = sanitize_points(points)
    if len(cleaned) == 0:
        return MetricResult(
            metric=metric,
            first_date=None,
            last_date=None,
            count=0,
            cumulative_return=None,
            annualized_return=None,
            annualized_volatility=None,
            return_risk_ratio=None,
            max_drawdown=None,
            notes=notes,
            error="区间内无有效观测",
        )
    returns = simple_returns(cleaned)
    running = 1.0
    return_series = [{"date": cleaned[0].date.isoformat(), "cumulative_return": 0.0}]
    for return_date, ret in returns:
        running *= 1.0 + ret
        return_series.append({"date": return_date.isoformat(), "cumulative_return": running - 1.0})

    span_days = (cleaned[-1].date - cleaned[0].date).days
    if span_days > 0 and span_days < 365:
        notes.append("区间不足一年，年化收益结果可能不稳定")

    return MetricResult(
        metric=metric,
        first_date=cleaned[0].date.isoformat(),
        last_date=cleaned[-1].date.isoformat(),
        count=len(cleaned),
        cumulative_return=cumulative_return(cleaned),
        annualized_return=annualized_return(cleaned),
        annualized_volatility=annualized_volatility(cleaned),
        return_risk_ratio=return_risk_ratio(cleaned),
        max_drawdown=max_drawdown(cleaned),
        return_series=return_series,
        notes=notes,
        error=None,
    )


def compare_series(
    asset_points: list[AnalysisPoint],
    benchmark_points: list[AnalysisPoint],
) -> dict:
    asset_clean, _ = sanitize_points(asset_points)
    benchmark_clean, _ = sanitize_points(benchmark_points)
    benchmark_index = {point.date: point.value for point in benchmark_clean}
    common = [point for point in asset_clean if point.date in benchmark_index]
    if len(common) < 2:
        return {
            "count": 0,
            "start_date": None,
            "end_date": None,
            "asset_cumulative_return": None,
            "benchmark_cumulative_return": None,
            "excess_return": None,
            "normalized": {"asset": [], "benchmark": []},
            "error": "交集有效观测不足，无法比较",
        }

    base_asset = common[0].value
    base_benchmark = benchmark_index[common[0].date]
    asset_cum = common[-1].value / base_asset - 1.0
    benchmark_cum = benchmark_index[common[-1].date] / base_benchmark - 1.0
    normalized_asset = [
        {"date": point.date.isoformat(), "value": point.value / base_asset * 100.0}
        for point in common
    ]
    normalized_benchmark = [
        {"date": point.date.isoformat(), "value": benchmark_index[point.date] / base_benchmark * 100.0}
        for point in common
    ]
    return {
        "count": len(common),
        "start_date": common[0].date.isoformat(),
        "end_date": common[-1].date.isoformat(),
        "asset_cumulative_return": asset_cum,
        "benchmark_cumulative_return": benchmark_cum,
        "excess_return": asset_cum - benchmark_cum,
        "normalized": {"asset": normalized_asset, "benchmark": normalized_benchmark},
        "error": None,
    }


def validate_weights(weights: list[float]) -> list[str]:
    errors = []
    if not weights:
        return ["组合不能为空"]
    if any((not math.isfinite(weight)) or weight < 0 for weight in weights):
        errors.append("权重必须是非负有限数值")
    total = sum(weights)
    if abs(total - 1.0) > 1e-6:
        errors.append("权重合计必须为 100%")
    return errors


def portfolio_analysis(
    items: list[dict],
) -> dict:
    """items 每项含 asset_id、weight、points。采用日期交集日收益率加权。"""
    weights = [float(item["weight"]) for item in items]
    errors = validate_weights(weights)
    if errors:
        return {"error": "；".join(errors), "count": 0, "cumulative_return": None}

    return_series_by_asset = []
    for item in items:
        returns = simple_returns(item["points"])
        index = {return_date: ret for return_date, ret in returns}
        return_series_by_asset.append((item["asset_id"], index))

    common_dates = set(return_series_by_asset[0][1].keys())
    for _, index in return_series_by_asset[1:]:
        common_dates &= set(index.keys())
    common_dates = sorted(common_dates)
    if len(common_dates) < 2:
        return {
            "count": 0,
            "cumulative_return": None,
            "max_drawdown": None,
            "annualized_volatility": None,
            "contributions": [],
            "curve": [],
            "error": "资产交集有效观测不足，无法计算组合",
        }

    curve = []
    running = 1.0
    portfolio_returns = []
    contributions_running = {item["asset_id"]: 0.0 for item in items}
    for return_date in common_dates:
        daily = 0.0
        for item, (asset_id, index) in zip(items, return_series_by_asset):
            ret = index[return_date]
            daily += item["weight"] * ret
        running *= 1.0 + daily
        portfolio_returns.append(daily)
        curve.append(
            {
                "date": return_date.isoformat(),
                "cumulative_return": running - 1.0,
            }
        )

    portfolio_points = [
        AnalysisPoint(date=date.fromisoformat(entry["date"]), value=1.0 + entry["cumulative_return"])
        for entry in curve
    ]
    volatility = None
    if len(portfolio_returns) >= 2:
        mean = sum(portfolio_returns) / len(portfolio_returns)
        variance = sum((ret - mean) ** 2 for ret in portfolio_returns) / (len(portfolio_returns) - 1)
        volatility = math.sqrt(variance) * math.sqrt(PERIODS_PER_YEAR)

    contributions = []
    for item, (asset_id, index) in zip(items, return_series_by_asset):
        asset_running = 1.0
        for return_date in common_dates:
            asset_running *= 1.0 + index[return_date]
        contribution = item["weight"] * (asset_running - 1.0)
        contributions.append({"asset_id": asset_id, "contribution": contribution})

    return {
        "count": len(common_dates),
        "start_date": common_dates[0].isoformat(),
        "end_date": common_dates[-1].isoformat(),
        "cumulative_return": curve[-1]["cumulative_return"],
        "max_drawdown": _drawdown_dict(max_drawdown(portfolio_points)),
        "annualized_volatility": volatility,
        "contributions": contributions,
        "curve": curve,
        "error": None,
    }


def _drawdown_dict(drawdown: Drawdown | None) -> dict | None:
    if drawdown is None:
        return None
    return {
        "peak_date": drawdown.peak_date,
        "trough_date": drawdown.trough_date,
        "drawdown": drawdown.drawdown,
    }
