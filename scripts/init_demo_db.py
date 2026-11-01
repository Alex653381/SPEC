"""为浏览器联调初始化独立的合成 SQLite 数据库。

用法：
    python scripts/init_demo_db.py --path data/demo-synthetic.db --reset
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.db.database import init_db
from backend.tests import fixtures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=os.path.join(ROOT, "data", "demo-synthetic.db"))
    parser.add_argument("--reset", action="store_true", help="存在时删除并重建")
    args = parser.parse_args()

    path = args.path
    if os.path.exists(path) and not args.reset:
        print(f"数据库已存在，跳过：{path}。需要重建请加 --reset")
        return 0
    if os.path.exists(path):
        os.remove(path)

    conn = init_db(path)
    try:
        fixtures.seed_database(conn)
    finally:
        conn.close()
    print(f"已初始化合成数据库：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
