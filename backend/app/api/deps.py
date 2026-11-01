"""FastAPI 依赖：数据库连接。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from backend.app.db.database import connect


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.database_path)
    try:
        yield conn
    finally:
        conn.close()
