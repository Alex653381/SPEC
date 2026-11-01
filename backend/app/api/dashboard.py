"""默认看板配置读取。配置文件为 JSON，便于无额外依赖解析。"""

from __future__ import annotations

import json
from pathlib import Path


def load_dashboard_config(path: str | Path) -> dict | None:
    config_path = Path(path)
    if not config_path.exists():
        return None
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError("dashboard config must be a JSON object with an assets list")
    return data
