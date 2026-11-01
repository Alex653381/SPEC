"""只读数据状态接口。不初始化、不迁移、不写业务记录。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.app.api.routes import _connect_ro, _find_asset, _merged_assets
from backend.app.db import repository
from backend.app.quality.checker import check_records
from backend.app.schemas.records import is_ohlc_asset_type


router = APIRouter()


def _status_for(request: Request, asset) -> dict:
    found = _find_asset(request, asset.id)
    if found is None:
        return {"asset_id": asset.id, "error": "资产不在任何可读数据源中"}
    _, source_path = found
    conn = _connect_ro(source_path)
    try:
        if is_ohlc_asset_type(asset.asset_type):
            records = repository.query_daily_bars(conn, asset.id)
            dates = [record.trade_date for record in records]
            data_class = "daily_bar"
        else:
            records = repository.query_fund_navs(conn, asset.id)
            dates = [record.nav_date for record in records]
            data_class = "fund_nav"
    finally:
        conn.close()

    duplicates = sorted({day.isoformat() for day in dates if dates.count(day) > 1})
    first = min(dates).isoformat() if dates else None
    last = max(dates).isoformat() if dates else None
    calendar_days = (max(dates) - min(dates)).days + 1 if dates else 0
    messages = []
    if duplicates:
        messages.append("存在重复业务日期，应人工检查")
    if dates and calendar_days > len(set(dates)):
        messages.append("覆盖区间内存在自然日间隔，可能是周末、节假日或基金披露频率所致，不视为缺失")

    if data_class == "daily_bar":
        quality = check_records(records, [], {asset.id: asset.asset_type})
    else:
        quality = check_records([], records, {asset.id: "open_fund"})
    if not records:
        quality_status = "empty"
    elif quality.by_severity.get("error", 0):
        quality_status = "error"
    elif quality.by_severity.get("warning", 0):
        quality_status = "warning"
    else:
        quality_status = "normal"

    return {
        "asset_id": asset.id,
        "asset_type": asset.asset_type,
        "provider": asset.provider,
        "source": source_path,
        "data_class": data_class,
        "record_count": len(records),
        "first_date": first,
        "last_date": last,
        "duplicate_dates": duplicates,
        "calendar_days": calendar_days,
        "assessment": "empty" if not records else "ok",
        "quality_status": quality_status,
        "quality_issue_count": quality.issue_count,
        "quality_by_severity": quality.by_severity,
        "messages": messages,
    }


@router.get("/data-status")
def list_status(request: Request):
    assets = _merged_assets(request)
    return {"items": [_status_for(request, asset) for asset in assets]}


@router.get("/data-status/{asset_id}")
def asset_status(asset_id: str, request: Request):
    found = _find_asset(request, asset_id)
    if found is None:
        return JSONResponse(status_code=404, content={"error": {"code": "ASSET_NOT_FOUND", "message": "资产不存在"}})
    return _status_for(request, found[0])
