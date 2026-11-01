# 适配器离线代码审查

审查范围：`backend/app/providers/base.py`、`sina.py`、`eastmoney.py` 及被复用的 `normalization/validation/merge/quality` 模块。全程离线，未调用真实行情接口。

## 1. 审查范围

- 成交额与成交量语义。
- 价格口径与复权标记。
- 日期、范围过滤和重复处理。
- 网络/空响应/字段异常/非法数值处理。
- 数据质量与数据库安全。
- 适配器与 API、数据库的边界。

## 2. 已确认正确的部分

- 股票、指数、ETF 共用日线模型，基金使用独立净值模型。
- 新浪股票 `amount→turnover` 有 `docs/data-source-audit.md` 第 4.1 节的实测依据，单位为元；成交量单独保留。
- 新浪指数强制 `turnover=None`，不推算成交额。
- 新浪 ETF 原始日线 `amount→turnover`，`adjustment_mode="none"`。
- 股票固定 `adjustment_mode="qfq"`，未把成交量或成交额乘复权因子。
- 阻断性校验失败的行被跳过并记录 `VALIDATION_BLOCKING`；OHLC 关系异常保留并标记 `source_anomaly`。
- 同批重复日期只保留首条，支持日期区间的股票适配器过滤范围外记录。
- 基金适配器只输出净值，不生成 OHLC 或成交量。
- 适配器不自动挂接只读 API，未新增抓取或管理接口。

## 3. 发现的问题及严重程度

| 级别 | 问题 | 依据 |
| --- | --- | --- |
| 中 | 非有限 `turnover`（NaN/Inf）可能被直接写入数据库 | `build_daily_record` 只判空，未判有限；`docs/data-model.md` 要求数值字段为有限数值 |
| 低 | 不支持日期区间的适配器仍把调用方传入的 `start/end` 透传给 fetcher | `base.py` 未按 `supports_date_range` 收敛参数 |

## 4. 已修复问题与对应测试

- 非有限 `turnover` 在 `build_daily_record` 中被转为 `None`，行仍保留并标记 `source_anomaly`。回归测试：`test_non_finite_turnover_is_dropped_and_marked`。
- 非区间适配器在调用 fetcher 时显式传 `None`。回归测试：`test_non_range_adapter_passes_none_dates_to_fetcher`。

## 5. 尚未解决的风险

- 基金周末占位行尚未在适配器层自动隔离；当前依赖入库层使用交易日历 `partition_fund_nav`。真实接入前必须把该隔离纳入入库流程。
- 指数成交额来源尚未验证，继续保持 `None`。
- 股票历史缺口原因未确认，不能推断为停牌。
- 真实 fetcher 尚未实现，适配器只经过 Mock 测试。

## 6. 真实数据接入前必须验证

- 对照 `docs/data-source-audit.md` 逐源复核字段名、单位和日期格式。
- 确认新浪指数、ETF 和天天基金的真实返回与当前映射一致。
- 确认基金单位净值与累计净值是否需要按日期合并，以及累计净值为空的规则。
- 确认交易日历来源，并在入库前隔离基金周末占位行。
- 确认数据许可边界，未确认前不向他人展示真实行情。
