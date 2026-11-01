"""天天基金历史净值 lsjz 分页适配器准备。"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

import requests

from backend.app.providers.base import InvalidResponseError, MarketDataAdapter
from backend.app.schemas.records import FundNavRecord
from backend.app.services.normalization import normalize_fund_nav, parse_date
from backend.app.services.quality import quality_from_issues
from backend.app.services.validation import validate_fund_nav


PageLoader = Callable[[int], list[dict[str, Any]]]


def map_lsjz_item(item: dict[str, Any]) -> dict[str, Any]:
    """把 lsjz 返回项映射为基金净值标准键名。字段语义待真实响应确认。"""
    return {
        "nav_date": item.get("FSRQ"),
        "unit_nav": item.get("DWJZ"),
        "accumulated_nav": item.get("LJJZ"),
    }


def collect_pages(
    load_page: PageLoader,
    page_size: int = 20,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    """分页收集，遇空页停止，按 FSRQ 去重，并设置最大页数保护。"""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        batch = load_page(page) or []
        if not batch:
            break
        for item in batch:
            key = item.get("FSRQ")
            if key is None or key in seen:
                continue
            seen.add(str(key))
            rows.append(item)
        if len(batch) < page_size:
            break
    return rows


def _lsjz_page(
    code: str,
    page: int,
    start,
    end,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"
        ),
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html",
    }
    params = {
        "fundCode": code,
        "pageIndex": str(page),
        "pageSize": str(page_size),
        "startDate": start.strftime("%Y-%m-%d") if start else "",
        "endDate": end.strftime("%Y-%m-%d") if end else "",
        "_": round(time.time() * 1000),
    }
    response = requests.get(url, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise InvalidResponseError(f"lsjz 响应不是 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidResponseError("lsjz 响应不是对象")
    data = payload.get("Data") or {}
    if not isinstance(data, dict):
        raise InvalidResponseError("lsjz Data 字段结构异常")
    rows = data.get("LSJZList") or []
    if not isinstance(rows, list):
        raise InvalidResponseError("lsjz LSJZList 字段不是列表")
    try:
        total = int(payload.get("TotalCount") or 0)
    except (TypeError, ValueError):
        total = 0
    return rows, total


def eastmoney_lsjz_fetcher(
    code: str,
    start,
    end,
    page_size: int = 20,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    """按日期区间拉取天天基金历史净值，按 FSRQ 去重并做分页保护。"""

    def load_page(page: int) -> list[dict[str, Any]]:
        rows, _ = _lsjz_page(code, page, start, end, page_size)
        return rows

    return collect_pages(load_page, page_size=page_size, max_pages=max_pages)


class LsjzFundAdapter(MarketDataAdapter):
    name = "eastmoney_fund_lsjz"
    asset_type = "open_fund"
    supports_date_range = True

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        mapped = map_lsjz_item(raw)
        return normalize_fund_nav(mapped)

    def _validate(self, canonical):
        return validate_fund_nav(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return FundNavRecord(
            asset_id=asset_id,
            nav_date=parse_date(canonical["nav_date"]),
            unit_nav=float(canonical["unit_nav"]),
            accumulated_nav=(
                float(canonical["accumulated_nav"])
                if canonical.get("accumulated_nav") is not None
                else None
            ),
            provider=self.name,
            fetched_at=fetched_at,
            quality_status=quality_from_issues(issues),
        )
