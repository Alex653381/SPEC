# 真实数据源评估（阶段 3D-1）

本阶段只做评估与确定性适配器验证，不执行真实行情请求，不写入正式数据库。

## 1. 股票日线数据源对比

| 数据源 | 接口 | 覆盖 | 字段可用性 | 历史与更新 | 认证/限制 | 许可状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 新浪财经 | `stock_zh_a_daily`（AKShare 封装） | A 股股票 | OHLC、成交量、成交额，支持 `qfq/hfq` | 支持日期区间 | 无密钥，但存在限流风险 | 新浪协议限个人、非商业，未确认再分发 |
| 腾讯财经 | `stock_zh_a_hist_tx`（AKShare 封装） | A 股股票 | OHLC、成交量、成交额，支持 `qfq/hfq` | 支持日期区间 | 无密钥 | 腾讯自选股限个人、非商业，未确认 |
| 东方财富 | `stock_zh_a_hist`（AKShare 封装） | A 股股票 | OHLC、成交量、成交额、振幅、换手率等 | 支持日期区间 | 本地曾出现 push2 限流 | 东方财富协议限制复制/提供，未确认 |

结论：首个股股票日线候选保持新浪 `stock_zh_a_daily(qfq)`，因为它已有完整实测、支持日期区间且字段口径明确；但授权边界仍未确认，不用于对外展示。

## 2. 授权信息来源

- 新浪《新浪财经用户协议》：个人、不可转让、非商业使用，未经书面许可不得复制和对外展示。
- 腾讯自选股软件许可协议：个人、不可转让、非商业。
- 东方财富《东方财富用户服务协议》：未经交易所书面同意不得复制或提供行情数据。
- AKShare 官方声明：数据仅限学术研究，不可商业使用。

以上均已在 `docs/data-source-audit.md` 记录。未取得书面授权前，不把数据用于向他人展示。

## 3. 标准字段映射

新浪股票原始字段到项目标准字段：

| 原始字段 | 标准字段 | 说明 |
| --- | --- | --- |
| `date` | `trade_date` | 业务日期，ISO `YYYY-MM-DD` |
| `open/high/low/close` | `open/high/low/close` | 前复权价格，口径记录为 `qfq` |
| `volume` | `volume` | 单位：股 |
| `amount` | `turnover` | 单位：元 |
| 无 | `adjustment_mode` | 固定 `qfq` |
| 无 | `provider` | 固定 `sina` |
| 请求时间 | `fetched_at` | UTC ISO 时间 |

## 4. 适配器边界

供应商原始响应 → `SinaStockAdapter` → `DailyBarRecord` → 阶段 3A 质量检查 → `synthetic_import` 事务管线 → 写后核验。

适配器只负责映射和标准化，不复刻质量规则、不绕开事务与幂等导入逻辑。

## 5. 未解决风险

- 三方的公开展示与再分发授权均未确认。
- 限流阈值和恢复时间未验证。
- 前复权历史可能随公司行为修订。
- 真实网络验证尚未执行，当前只有固定响应夹具。

## 6. SinaStockAdapter 离线复核（阶段 3D-2）

本阶段未执行真实网络请求，以下结论均来自现有代码与 `docs/data-source-audit.md` 的实测记录。

| 复核项 | 结论 | 依据 |
| --- | --- | --- |
| 标准字段与单位 | `date→trade_date`；`open/high/low/close` 原样映射；`volume` 单位为股；`amount→turnover` 单位为元 | `docs/data-source-audit.md` 第 4.1 节，`normalize_daily_bar` 的别名与转换 |
| 前复权口径 | `SinaStockAdapter.adjustment_mode = "qfq"`，价格口径固定前复权，不与不复权/后复权混合 | `backend/app/providers/sina.py`；审计报告对比 `adjust=""`、`qfq`、`hfq` 的实测值 |
| 网络获取与纯转换分离 | 是。适配器构造时注入 `fetcher`，`_map`/`_validate`/`_build` 均为无网络副作用的纯转换；固定响应夹具可直接注入测试 | `backend/app/providers/base.py` 的 `Fetcher` 协议与 `fetch_history` |
| 只读验证工具不写库 | `scripts/validate_live_adapters.py` 仅构造摘要 JSON，可选写入 `data/samples/`；不调用 `init_db`、`insert_*`、`import_batch` 或任何 Repository 写函数 | 脚本主体只调用 `adapter.fetch_history` 与 `json.dump` |
| 是否需要最小改动 | 不需要。现有映射、`qfq` 标记、注入式 fetcher 与只读验证脚本均满足要求 | `backend/tests/test_adapters.py`、`backend/tests/test_adapter_pipeline.py` 已覆盖映射、错误处理、质量检查与临时库导入 |

离线测试现状：`test_adapters.py` 覆盖股票字段映射、`qfq` 元数据、`amount→turnover`、非有限成交额、字段变化、重复日期与范围外过滤；`test_adapter_pipeline.py` 用临时 SQLite 验证新浪固定响应可进入质量检查和幂等导入。

## 7. 股票数据源决策表

| 维度 | 新浪 `stock_zh_a_daily(qfq)`（首选） | 腾讯 `stock_zh_a_hist_tx`（备选） | 东方财富 `stock_zh_a_hist`（降级） |
| --- | --- | --- | --- |
| 证据充分程度 | 高：多轮实测字段、单位、日期区间和复权口径 | 中：有实测，但前复权存在负价与周末占位记录 | 中：实测受 push2 限流影响，未完整完成 |
| 许可状态 | 未确认 | 未确认 | 未确认 |
| 技术可行性 | 高 | 中，暂不作为主候选 | 低，需限流退避 |
| 预期维护成本 | 中 | 中 | 高 |
| 是否适合进入真实只读验证 | 许可确认后优先 | 暂不 | 仅作降级验证，不排前 |
| 还需回答的关键问题 | 授权边界；限流阈值与恢复时间 | 前复权异常可否排除后再评估 | push2 限流恢复条件与稳定性 |

结论：股票日线继续保留新浪 `stock_zh_a_daily(qfq)` 作为唯一已启动候选，腾讯与东方财富不改变现有降级/备选定位；任何候选在授权确认前都不进入真实只读验证。
