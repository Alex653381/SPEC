"""只读投资研究分析接口。不触发真实网络请求，不写行情表。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.app.api.analysis_schemas import CompareRequest, PortfolioRequest
from backend.app.core.quality import AssetType
from backend.app.services import analysis
from backend.app.services.analysis import AnalysisPoint


router = APIRouter()


def _error(code: str, message: str):
    return JSONResponse(status_code=400, content={"error": {"code": code, "message": message}})


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _resolve_asset(request: Request, asset_id: str):
    access = request.app.state.analysis_access
    for asset_type in AssetType.ALL:
        series = access.load_series(asset_type, asset_id, None, None)
        if series is not None:
            return series
    return None


def _resolve_history(request: Request, asset_id: str, start: date | None, end: date | None):
    access = request.app.state.analysis_access
    for asset_type in AssetType.ALL:
        series = access.load_series(asset_type, asset_id, start, end)
        if series is not None:
            return series
    return None


def _validated_range(start_date: str | None, end_date: str | None):
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if (start_date is not None and start is None) or (end_date is not None and end is None):
        return None, "INVALID_DATE_RANGE"
    if start is not None and end is not None and start > end:
        return None, "INVALID_DATE_RANGE"
    return (start, end), None


@router.get("/assets/{asset_id}/metrics")
def asset_metrics(
    asset_id: str,
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
):
    window, error_code = _validated_range(start_date, end_date)
    if error_code:
        return _error(error_code, "日期必须为 YYYY-MM-DD，且开始日期不能晚于结束日期")
    start, end = window
    series = _resolve_history(request, asset_id, start, end)
    if series is None:
        return JSONResponse(status_code=404, content={"error": {"code": "ASSET_NOT_FOUND", "message": "资产不存在"}})
    result = analysis.build_metrics(series.metric, series.points)
    return {
        "asset_id": series.asset_id,
        "asset_type": series.asset_type,
        "metric": result.metric,
        "price_semantics": series.price_semantics,
        "adjustment_mode": series.adjustment_mode,
        "provider": series.provider,
        "source": series.source_label,
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "first_date": result.first_date,
        "last_date": result.last_date,
        "count": result.count,
        "cumulative_return": result.cumulative_return,
        "annualized_return": result.annualized_return,
        "annualized_volatility": result.annualized_volatility,
        "return_risk_ratio": result.return_risk_ratio,
        "max_drawdown": _drawdown(result.max_drawdown),
        "return_series": result.return_series,
        "notes": result.notes,
        "error": result.error,
    }


@router.post("/compare")
def compare(request: Request, body: CompareRequest):
    window, error_code = _validated_range(body.start_date, body.end_date)
    if error_code:
        return _error(error_code, "日期必须为 YYYY-MM-DD，且开始日期不能晚于结束日期")
    start, end = window
    asset = _resolve_history(request, body.asset_id, start, end)
    benchmark = _resolve_history(request, body.benchmark_asset_id, start, end)
    if asset is None or benchmark is None:
        return JSONResponse(status_code=404, content={"error": {"code": "ASSET_NOT_FOUND", "message": "资产或基准不存在"}})
    result = analysis.compare_series(asset.points, benchmark.points)
    return {
        "asset_id": asset.asset_id,
        "benchmark_asset_id": benchmark.asset_id,
        "asset_metric": asset.metric,
        "benchmark_metric": benchmark.metric,
        "asset_source": asset.source_label,
        "benchmark_source": benchmark.source_label,
        **result,
    }


@router.post("/portfolio")
def portfolio(request: Request, body: PortfolioRequest):
    window, error_code = _validated_range(body.start_date, body.end_date)
    if error_code:
        return _error(error_code, "日期必须为 YYYY-MM-DD，且开始日期不能晚于结束日期")
    if not body.items or len(body.items) == 0:
        return _error("INVALID_PORTFOLIO", "组合不能为空")
    start, end = window
    items = []
    for entry in body.items:
        series = _resolve_history(request, entry.asset_id, start, end)
        if series is None:
            return JSONResponse(status_code=404, content={"error": {"code": "ASSET_NOT_FOUND", "message": f"资产不存在: {entry.asset_id}"}})
        items.append(
            {
                "asset_id": series.asset_id,
                "weight": entry.weight / 100.0,
                "points": series.points,
            }
        )
    result = analysis.portfolio_analysis(items)
    if result.get("error"):
        return _error("INVALID_PORTFOLIO", result["error"])
    return result


def _drawdown(drawdown) -> dict | None:
    if drawdown is None:
        return None
    return {
        "peak_date": drawdown.peak_date,
        "trough_date": drawdown.trough_date,
        "drawdown": drawdown.drawdown,
    }
