"""只读 API 路由。任何路由都不触发抓取、回补、更新或配置修改。"""

from __future__ import annotations

import sqlite3
import os
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.app.api.dashboard import load_dashboard_config
from backend.app.api.schemas import AssetListOut, AssetOut, DashboardOut, HistoryOut
from backend.app.core import access
from backend.app.core.quality import AssetType
from backend.app.db import repository
from backend.app.db.database import connect
from backend.app.schemas.records import DailyBarRecord, FundNavRecord, is_ohlc_asset_type
router = APIRouter()

MAX_ASSET_LIMIT = 200
MAX_HISTORY_LIMIT = 2000


def _asset_out(asset) -> AssetOut:
    return AssetOut(
        id=asset.id,
        symbol=asset.symbol,
        name=asset.name,
        asset_type=asset.asset_type,
        market=asset.market,
        currency=asset.currency,
        provider=asset.provider,
        price_semantics=asset.price_semantics,
        volume_unit=asset.volume_unit,
        adjustment_mode=asset.adjustment_mode,
        is_active=asset.is_active,
    )


def _parse_api_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _connect_ro(path: str):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _merged_assets(request: Request) -> list:
    assets = []
    seen_ids = set()
    for asset in request.app.state.analysis_access.all_assets():
        if asset.id not in seen_ids:
            seen_ids.add(asset.id)
            assets.append(asset)

    primary = request.app.state.database_path
    if os.path.exists(primary):
        conn = _connect_ro(primary)
        try:
            for asset in repository.query_all_assets(conn):
                if asset.id not in seen_ids:
                    seen_ids.add(asset.id)
                    assets.append(asset)
        finally:
            conn.close()

    real_keys = {
        (asset.asset_type, asset.symbol)
        for asset in assets
        if asset.provider != "synthetic"
    }
    assets = [
        asset
        for asset in assets
        if not (asset.provider == "synthetic" and (asset.asset_type, asset.symbol) in real_keys)
    ]
    return sorted(assets, key=lambda asset: (asset.asset_type, asset.market, asset.symbol))


def _find_asset(request: Request, asset_id: str):
    found = request.app.state.analysis_access.find_asset(asset_id)
    if found is not None:
        return found
    primary = request.app.state.database_path
    if os.path.exists(primary):
        conn = _connect_ro(primary)
        try:
            asset = repository.get_asset(conn, asset_id)
            if asset is not None:
                return asset, primary
        finally:
            conn.close()
    return None


@router.get("/health")
def health(request: Request):
    database_ok = True
    try:
        conn = connect(request.app.state.database_path)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        database_ok = False
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={
            "status": "ok" if database_ok else "error",
            "app_mode": request.app.state.settings.app_mode,
            "database": "ok" if database_ok else "error",
            "authentication_implemented": access.AUTHENTICATION_IMPLEMENTED,
        },
    )


@router.get("/assets", response_model=AssetListOut)
def list_assets(
    request: Request,
    asset_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    if asset_type is not None and asset_type not in AssetType.ALL:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_ASSET_TYPE", "message": "未知资产类型"}})
    if limit < 1 or limit > MAX_ASSET_LIMIT:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_LIMIT", "message": f"limit 必须在 1-{MAX_ASSET_LIMIT}"}})
    if offset < 0:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_OFFSET", "message": "offset 不能为负"}})
    assets = _merged_assets(request)
    if asset_type is not None:
        assets = [asset for asset in assets if asset.asset_type == asset_type]
    if q:
        keyword = q.lower()
        assets = [
            asset
            for asset in assets
            if keyword in asset.symbol.lower() or keyword in asset.name.lower()
        ]
    items = assets[offset : offset + limit]
    return AssetListOut(
        items=[_asset_out(asset) for asset in items],
        total=len(assets),
        limit=limit,
        offset=offset,
    )


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, request: Request):
    found = _find_asset(request, asset_id)
    if found is None:
        return JSONResponse(status_code=404, content={"error": {"code": "ASSET_NOT_FOUND", "message": "资产不存在"}})
    return _asset_out(found[0])


@router.get("/assets/{asset_id}/history", response_model=HistoryOut)
def get_history(
    asset_id: str,
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 1000,
):
    found = _find_asset(request, asset_id)
    if found is None:
        return JSONResponse(status_code=404, content={"error": {"code": "ASSET_NOT_FOUND", "message": "资产不存在"}})
    asset, source_path = found
    if limit < 1 or limit > MAX_HISTORY_LIMIT:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_LIMIT", "message": f"limit 必须在 1-{MAX_HISTORY_LIMIT}"}})

    start = _parse_api_date(start_date) if start_date is not None else None
    end = _parse_api_date(end_date) if end_date is not None else None
    if (start_date is not None and start is None) or (end_date is not None and end is None):
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_DATE_RANGE", "message": "日期必须为 YYYY-MM-DD"}})
    if start is not None and end is not None and start > end:
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_DATE_RANGE", "message": "开始日期不能晚于结束日期"}})

    conn = _connect_ro(source_path)
    try:
        if is_ohlc_asset_type(asset.asset_type):
            records = repository.query_daily_bars(conn, asset_id, start, end, limit)
            items = [_daily_bar_out(record) for record in records]
            data_class = "daily_bar"
            latest = max((record.trade_date for record in records), default=None)
        else:
            records = repository.query_fund_navs(conn, asset_id, start, end, limit)
            items = [_fund_nav_out(record) for record in records]
            data_class = "fund_nav"
            latest = max((record.nav_date for record in records), default=None)
    finally:
        conn.close()

    return HistoryOut(
        asset_id=asset_id,
        asset_type=asset.asset_type,
        data_class=data_class,
        start_date=start.isoformat() if start else None,
        end_date=end.isoformat() if end else None,
        latest_business_date=latest.isoformat() if latest else None,
        count=len(items),
        records=items,
    )


@router.get("/dashboard/default", response_model=DashboardOut)
def default_dashboard(request: Request):
    try:
        data = load_dashboard_config(request.app.state.dashboard_config_path)
    except (OSError, ValueError):
        return JSONResponse(status_code=500, content={"error": {"code": "DASHBOARD_CONFIG_ERROR", "message": "默认看板配置不可读"}})
    if data is None:
        return DashboardOut(configured=False, assets=[])
    return DashboardOut(configured=True, assets=data.get("assets", []))


def _daily_bar_out(record: DailyBarRecord) -> dict:
    return {
        "date": record.trade_date.isoformat(),
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "volume": record.volume,
        "turnover": record.turnover,
        "adjustment_mode": record.adjustment_mode,
        "provider": record.provider,
        "quality_status": record.quality_status,
    }


def _fund_nav_out(record: FundNavRecord) -> dict:
    return {
        "date": record.nav_date.isoformat(),
        "unit_nav": record.unit_nav,
        "accumulated_nav": record.accumulated_nav,
        "provider": record.provider,
        "quality_status": record.quality_status,
    }
