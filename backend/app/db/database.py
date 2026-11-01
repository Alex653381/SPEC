"""SQLite 连接、初始化与备份。"""

from __future__ import annotations

import sqlite3

from backend.app.db.migrations import apply_migrations


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str) -> sqlite3.Connection:
    conn = connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    apply_migrations(conn)
    return conn


def backup_database(conn: sqlite3.Connection, destination: str) -> None:
    """使用 SQLite 在线备份 API 生成一致性快照。"""
    dest = sqlite3.connect(destination)
    try:
        with dest:
            conn.backup(dest)
    finally:
        dest.close()
