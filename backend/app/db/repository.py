"""数据表读写。写入函数默认不覆盖已有有效记录，覆盖必须显式传入 replace=True。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Iterable

from backend.app.schemas.records import (
    AssetRecord,
    DailyBarRecord,
    FundNavRecord,
)


def _iso_date(value: date) -> str:
    return value.isoformat()


def _iso_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def insert_asset(conn: sqlite3.Connection, asset: AssetRecord) -> None:
    now = datetime.now(timezone.utc).isoformat()
    created = asset.created_at.isoformat() if asset.created_at else now
    updated = asset.updated_at.isoformat() if asset.updated_at else now
    conn.execute(
        """
        INSERT INTO assets (
            id, symbol, name, asset_type, market, currency, provider, provider_symbol,
            adjustment_mode, price_semantics, volume_unit, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset.id,
            asset.symbol,
            asset.name,
            asset.asset_type,
            asset.market,
            asset.currency,
            asset.provider,
            asset.provider_symbol,
            asset.adjustment_mode,
            asset.price_semantics,
            asset.volume_unit,
            int(asset.is_active),
            created,
            updated,
        ),
    )


def _asset_from_row(row) -> AssetRecord:
    return AssetRecord(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        market=row["market"],
        currency=row["currency"],
        provider=row["provider"],
        provider_symbol=row["provider_symbol"],
        adjustment_mode=row["adjustment_mode"],
        price_semantics=row["price_semantics"],
        volume_unit=row["volume_unit"],
        is_active=bool(row["is_active"]),
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def get_asset(conn: sqlite3.Connection, asset_id: str) -> AssetRecord | None:
    row = conn.execute(
        """
        SELECT id, symbol, name, asset_type, market, currency, provider, provider_symbol,
               adjustment_mode, price_semantics, volume_unit, is_active, created_at, updated_at
        FROM assets WHERE id = ?
        """,
        (asset_id,),
    ).fetchone()
    return _asset_from_row(row) if row else None


def list_assets(
    conn: sqlite3.Connection,
    asset_type: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AssetRecord], int]:
    where = []
    params: list = []
    if asset_type is not None:
        where.append("asset_type = ?")
        params.append(asset_type)
    if keyword:
        like = f"%{keyword}%"
        where.append("(symbol LIKE ? OR name LIKE ?)")
        params.extend([like, like])
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM assets{clause}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, symbol, name, asset_type, market, currency, provider, provider_symbol,
               adjustment_mode, price_semantics, volume_unit, is_active, created_at, updated_at
        FROM assets{clause}
        ORDER BY asset_type, market, symbol
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return [_asset_from_row(row) for row in rows], int(total)


def query_all_assets(conn: sqlite3.Connection) -> list[AssetRecord]:
    rows = conn.execute(
        """
        SELECT id, symbol, name, asset_type, market, currency, provider, provider_symbol,
               adjustment_mode, price_semantics, volume_unit, is_active, created_at, updated_at
        FROM assets
        ORDER BY asset_type, market, symbol
        """
    ).fetchall()
    return [_asset_from_row(row) for row in rows]


def _daily_bar_row(record: DailyBarRecord) -> tuple:
    return (
        record.asset_id,
        _iso_date(record.trade_date),
        record.open,
        record.high,
        record.low,
        record.close,
        record.volume,
        record.turnover,
        record.adjustment_mode,
        record.provider,
        record.fetched_at.isoformat(),
        _iso_dt(record.validated_at),
        record.quality_status,
    )


def insert_daily_bars(
    conn: sqlite3.Connection,
    records: Iterable[DailyBarRecord],
    replace: bool = False,
) -> int:
    mode = "REPLACE" if replace else "IGNORE"
    before = conn.total_changes
    conn.executemany(
        f"""
        INSERT OR {mode} INTO daily_bars (
            asset_id, trade_date, open, high, low, close, volume, turnover,
            adjustment_mode, provider, fetched_at, validated_at, quality_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (_daily_bar_row(record) for record in records),
    )
    return conn.total_changes - before


def query_daily_bars(
    conn: sqlite3.Connection,
    asset_id: str,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> list[DailyBarRecord]:
    sql = (
        "SELECT asset_id, trade_date, open, high, low, close, volume, turnover, "
        "adjustment_mode, provider, fetched_at, validated_at, quality_status "
        "FROM daily_bars WHERE asset_id = ?"
    )
    params: list = [asset_id]
    if start is not None:
        sql += " AND trade_date >= ?"
        params.append(_iso_date(start))
    if end is not None:
        sql += " AND trade_date <= ?"
        params.append(_iso_date(end))
    sql += " ORDER BY trade_date"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_daily_bar_from_row(row) for row in rows]


def query_all_daily_bars(conn: sqlite3.Connection) -> list[DailyBarRecord]:
    rows = conn.execute(
        """
        SELECT asset_id, trade_date, open, high, low, close, volume, turnover,
               adjustment_mode, provider, fetched_at, validated_at, quality_status
        FROM daily_bars
        ORDER BY asset_id, trade_date, adjustment_mode
        """
    ).fetchall()
    return [_daily_bar_from_row(row) for row in rows]


def _daily_bar_from_row(row) -> DailyBarRecord:
    return DailyBarRecord(
        asset_id=row["asset_id"],
        trade_date=date.fromisoformat(row["trade_date"]),
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        turnover=row["turnover"],
        adjustment_mode=row["adjustment_mode"],
        provider=row["provider"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        validated_at=datetime.fromisoformat(row["validated_at"]) if row["validated_at"] else None,
        quality_status=row["quality_status"],
    )


def _fund_nav_row(record: FundNavRecord) -> tuple:
    return (
        record.asset_id,
        _iso_date(record.nav_date),
        record.unit_nav,
        record.accumulated_nav,
        record.provider,
        record.fetched_at.isoformat(),
        _iso_dt(record.validated_at),
        record.quality_status,
    )


def insert_fund_navs(
    conn: sqlite3.Connection,
    records: Iterable[FundNavRecord],
    replace: bool = False,
) -> int:
    mode = "REPLACE" if replace else "IGNORE"
    before = conn.total_changes
    conn.executemany(
        f"""
        INSERT OR {mode} INTO fund_nav (
            asset_id, nav_date, unit_nav, accumulated_nav,
            provider, fetched_at, validated_at, quality_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (_fund_nav_row(record) for record in records),
    )
    return conn.total_changes - before


def query_fund_navs(
    conn: sqlite3.Connection,
    asset_id: str,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> list[FundNavRecord]:
    sql = (
        "SELECT asset_id, nav_date, unit_nav, accumulated_nav, provider, "
        "fetched_at, validated_at, quality_status FROM fund_nav WHERE asset_id = ?"
    )
    params: list = [asset_id]
    if start is not None:
        sql += " AND nav_date >= ?"
        params.append(_iso_date(start))
    if end is not None:
        sql += " AND nav_date <= ?"
        params.append(_iso_date(end))
    sql += " ORDER BY nav_date"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        result.append(
            FundNavRecord(
                asset_id=row["asset_id"],
                nav_date=date.fromisoformat(row["nav_date"]),
                unit_nav=row["unit_nav"],
                accumulated_nav=row["accumulated_nav"],
                provider=row["provider"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                validated_at=datetime.fromisoformat(row["validated_at"]) if row["validated_at"] else None,
                quality_status=row["quality_status"],
            )
        )
    return result


def query_all_fund_navs(conn: sqlite3.Connection) -> list[FundNavRecord]:
    rows = conn.execute(
        """
        SELECT asset_id, nav_date, unit_nav, accumulated_nav, provider,
               fetched_at, validated_at, quality_status
        FROM fund_nav
        ORDER BY asset_id, nav_date
        """
    ).fetchall()
    result = []
    for row in rows:
        result.append(
            FundNavRecord(
                asset_id=row["asset_id"],
                nav_date=date.fromisoformat(row["nav_date"]),
                unit_nav=row["unit_nav"],
                accumulated_nav=row["accumulated_nav"],
                provider=row["provider"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                validated_at=datetime.fromisoformat(row["validated_at"]) if row["validated_at"] else None,
                quality_status=row["quality_status"],
            )
        )
    return result


def record_gap(
    conn: sqlite3.Connection,
    asset_id: str,
    record_kind: str,
    gap_start: date,
    gap_end: date,
    status: str,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO data_gaps (
            asset_id, record_kind, gap_start, gap_end, status, detected_at, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (asset_id, record_kind, gap_start, gap_end)
        DO UPDATE SET status = excluded.status, note = excluded.note
        """,
        (
            asset_id,
            record_kind,
            _iso_date(gap_start),
            _iso_date(gap_end),
            status,
            datetime.now(timezone.utc).isoformat(),
            note,
        ),
    )


def record_quality_event(
    conn: sqlite3.Connection,
    asset_id: str,
    record_kind: str,
    business_date: date,
    new_status: str,
    reason: str,
    old_status: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO data_quality_audit (
            asset_id, record_kind, business_date, old_status, new_status, reason, changed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            record_kind,
            _iso_date(business_date),
            old_status,
            new_status,
            reason,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def record_daily_bar_revision(
    conn: sqlite3.Connection,
    asset_id: str,
    trade_date: date,
    adjustment_mode: str,
    field_name: str,
    old_value,
    new_value,
    reason: str,
) -> None:
    conn.execute(
        """
        INSERT INTO daily_bar_revisions (
            asset_id, trade_date, adjustment_mode, field_name,
            old_value, new_value, reason, revised_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            _iso_date(trade_date),
            adjustment_mode,
            field_name,
            json.dumps(old_value),
            json.dumps(new_value),
            reason,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def query_daily_bar_revisions(conn: sqlite3.Connection, asset_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT trade_date, adjustment_mode, field_name, old_value, new_value, reason, revised_at
        FROM daily_bar_revisions
        WHERE asset_id = ?
        ORDER BY id
        """,
        (asset_id,),
    ).fetchall()
    return [dict(row) for row in rows]
