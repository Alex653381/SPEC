# 采集服务设计

`backend/app/services/ingestion.py` 把适配器、校验、合并和 Repository 串联起来。当前只支持 Mock fetcher，不包含真实网络抓取。

## 1. 处理流程

1. 按 `asset_id` 读取资产；不存在则 `failed`。
2. 从 `backend/app/providers/registry.py` 按 `asset_type` 选择适配器；无适配器则 `failed`。
3. 调用 `fetch_history`；`AdapterError` 整批失败转 `failed`。
4. 空响应转 `empty`，不写入。
5. 基金资产要求提供交易日历；未提供时 `not_ready`，拒绝写入。
6. 基金记录经 `partition_fund_nav` 隔离周末占位行，占位行计入 `skipped_rows`。
7. 有记录时在单事务中写入 Repository；写入异常转 `failed`，事务回滚。

## 2. 状态定义

| 状态 | 含义 |
| --- | --- |
| `success` | 获取到记录，无行级跳过 |
| `partial_success` | 部分行写入，部分行被跳过或隔离 |
| `empty` | 数据源返回空表，不视为完整更新成功 |
| `failed` | 资产/适配器缺失、整批失败或全部行无效 |
| `not_ready` | 缺少基金交易日历等前置规则，安全拒绝入库 |

## 3. 摘要字段

`IngestionResult` 返回 `asset_id`、`adapter`、`status`、`fetched_rows`、`valid_rows`、`anomaly_rows`、`written_rows`、`skipped_rows`、`errors`、`completed_at`。

## 4. 事务与失败策略

- 写入使用 `with conn:` 单事务；异常回滚，不留半批次。
- Repository 写入默认 `INSERT OR IGNORE`，重复执行幂等。
- 异常或不完整行不覆盖已有有效数据。
- 非有限数值不写入；`turnover` 非有限值转 `None` 并标记异常。

## 5. 基金日历限制

- 基金入库必须提供可靠交易日历；没有日历就 `not_ready`，不静默写入。
- 周末占位行由 `partition_fund_nav` 隔离，不在采集服务中按“周末一律删除”猜测。

## 6. 当前局限

- 同一业务日期、同复权口径但数值不同的冲突目前由 `INSERT OR IGNORE` 静默保留旧值，未逐条报告冲突；值级冲突审计留待后续阶段。
- 历史缺口检测和回补不在本阶段实现。
