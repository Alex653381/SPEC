# 数据库设计

SQLite + WAL，使用标准库 `sqlite3`，不引入 ORM 或独立数据库服务。

## 1. 表结构与分表理由

| 表 | 用途 |
| --- | --- |
| `assets` | 资产元数据 |
| `daily_bars` | 股票、指数、场内 ETF 日线 |
| `fund_nav` | 场外基金净值 |
| `asset_update_state` | 每项资产的更新状态 |
| `data_gaps` | 历史缺口与待复核区间 |
| `data_quality_audit` | 质量状态变化审计 |
| `schema_migrations` | 已应用迁移版本 |

日线与基金净值分表，因为两类数据语义不同：日线有 OHLC 和成交量，基金只有净值，且两者的唯一键和索引不同。股票、指数、ETF 共用 `daily_bars`，通过 `asset_id` 关联 `assets.asset_type` 区分类别，避免为每个类别复制一张结构相同的表。

## 2. 唯一约束与索引

- `daily_bars` 主键 `(asset_id, trade_date, adjustment_mode)`，防止同一资产同一业务日期同一复权口径出现重复有效记录。
- `fund_nav` 主键 `(asset_id, nav_date)`。
- `assets` 唯一约束 `(market, symbol, asset_type)`。
- `data_gaps` 唯一约束 `(asset_id, record_kind, gap_start, gap_end)`。
- 日线与净值表均建 `(asset_id, date)` 索引，支撑历史区间查询。

## 3. 事务与写入保护

- 迁移在单个事务中应用，避免半迁移状态。
- 写入使用 `with conn:` 事务；失败自动回滚，不删除旧数据。
- 默认写入使用 `INSERT OR IGNORE`，增量重复导入不产生重复记录。
- 覆盖已有数据必须显式传入 `replace=True`；未明确优先级规则时不允许跨数据源覆盖。
- 数据源适配与数据库写入分离，未来可替换数据源而不重写业务规则。

## 4. 迁移策略

- `backend/app/db/migrations.py` 内按版本号登记迁移，`schema_migrations` 记录已应用版本。
- `init_db(path)` 可重复执行，已应用版本会跳过。
- 后续结构变更只新增迁移版本，不修改已发布迁移，保证既有环境可升级。

## 5. 备份

- SQLite 开启 WAL。备份使用 SQLite 在线备份 API（`sqlite3.Connection.backup`），保证包含 WAL 中已提交数据的一致性快照，而不是直接复制正在使用的主库文件。
- 数据库、日志和生产配置不放在 Web 静态目录。
