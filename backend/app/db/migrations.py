"""可重复执行的数据库迁移。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


MIGRATIONS = (
    Migration(
        version=1,
        name="initial_schema",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL CHECK (asset_type IN ('stock','index','etf','open_fund')),
                market TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                provider TEXT NOT NULL,
                provider_symbol TEXT NOT NULL,
                adjustment_mode TEXT,
                price_semantics TEXT NOT NULL,
                volume_unit TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (market, symbol, asset_type)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_bars (
                asset_id TEXT NOT NULL REFERENCES assets(id),
                trade_date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                turnover REAL,
                adjustment_mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                validated_at TEXT,
                quality_status TEXT NOT NULL,
                PRIMARY KEY (asset_id, trade_date, adjustment_mode)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_daily_bars_asset_date
            ON daily_bars (asset_id, trade_date)
            """,
            """
            CREATE TABLE IF NOT EXISTS fund_nav (
                asset_id TEXT NOT NULL REFERENCES assets(id),
                nav_date TEXT NOT NULL,
                unit_nav REAL NOT NULL,
                accumulated_nav REAL,
                provider TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                validated_at TEXT,
                quality_status TEXT NOT NULL,
                PRIMARY KEY (asset_id, nav_date)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_fund_nav_asset_date
            ON fund_nav (asset_id, nav_date)
            """,
            """
            CREATE TABLE IF NOT EXISTS asset_update_state (
                asset_id TEXT PRIMARY KEY REFERENCES assets(id),
                last_attempt_at TEXT,
                last_success_at TEXT,
                latest_data_date TEXT,
                status TEXT NOT NULL,
                last_error_code TEXT,
                last_error_summary TEXT,
                retry_after TEXT,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS data_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL REFERENCES assets(id),
                record_kind TEXT NOT NULL CHECK (record_kind IN ('daily_bar','fund_nav')),
                gap_start TEXT NOT NULL,
                gap_end TEXT NOT NULL,
                status TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                reviewed_at TEXT,
                note TEXT,
                UNIQUE (asset_id, record_kind, gap_start, gap_end)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_data_gaps_asset
            ON data_gaps (asset_id, gap_start)
            """,
            """
            CREATE TABLE IF NOT EXISTS data_quality_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL REFERENCES assets(id),
                record_kind TEXT NOT NULL CHECK (record_kind IN ('daily_bar','fund_nav')),
                business_date TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                reason TEXT NOT NULL,
                changed_at TEXT NOT NULL
            )
            """,
        ),
    ),
    Migration(
        version=2,
        name="add_jobs_table",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending','running','success','failed')),
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                processed_records INTEGER NOT NULL DEFAULT 0,
                succeeded_records INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                error_summary TEXT,
                execution_summary TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)
            """,
        ),
    ),
    Migration(
        version=3,
        name="add_daily_bar_revisions_table",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS daily_bar_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL REFERENCES assets(id),
                trade_date TEXT NOT NULL,
                adjustment_mode TEXT NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                reason TEXT NOT NULL,
                revised_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_daily_bar_revisions_asset_date
            ON daily_bar_revisions (asset_id, trade_date)
            """,
        ),
    ),
)


def apply_migrations(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        with conn:
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, _now_iso()),
            )
