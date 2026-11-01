# 首选数据源适配器实现准备

生成时间：2026-10-31。本文件只记录离线实现准备，不执行真实请求，不把未确认字段写成已确认事实。

## 1. 股票：新浪 `stock_zh_a_daily(qfq)`

- 状态：`SinaStockAdapter` 已实现并测试。
- 字段：`date/open/high/low/close/volume/amount`。
- 单位：`volume`=股、`amount`=元；固定 `qfq` 前复权。
- 支持日期范围：是。
- 未验证事项：长期历史修订范围、限流阈值。

## 2. 指数：腾讯 `stock_zh_index_daily_tx`

- 状态：新增 `TencentIndexAdapter`，离线测试通过。
- 字段：`date/open/close/high/low/amount`。
- 关键口径：`amount` 实为成交量（手），映射到 `volume`，`turnover` 置空；`adjustment_mode="none"`。
- 支持日期范围：是。
- 未验证事项：`amount` 是否在所有指数代码上均为成交量、历史覆盖和限流规则。

## 3. 场内 ETF：东方财富 `fund_etf_hist_em`

- 状态：新增 `EastmoneyETFAdapter`，离线测试通过。
- 字段：按现有证据映射 `日期/开盘/收盘/最高/最低/成交量/成交额`。
- 单位：成交量单位为手、成交额为元的假设待真实响应确认。
- 支持日期范围：是。
- 未验证事项：精确字段名与单位；本地 IP 限流风险。

## 4. 场外基金：天天基金 `lsjz`

- 状态：新增 `LsjzFundAdapter` 与 `collect_pages`，离线测试通过。
- 字段：`FSRQ`→净值日期、`DWJZ`→单位净值、`LJJZ`→累计净值。
- 支持日期范围与分页：`startDate/endDate/pageSize`；分页遇空页停止、按 `FSRQ` 去重、有最大页数保护。
- 未验证事项：真实 JSON 字段名、分页上限、限流与空页行为。

## 5. 注册表策略

默认 `ADAPTER_REGISTRY` 仍指向已测全量适配器，未切换新适配器，避免破坏现有采集测试。待真实验证确认字段后，再按资产类别切换首选适配器。

## 6. 真实验证前置条件

- 数据许可确认。
- 对四个首选接口各做一次最小范围真实验证。
- 记录真实字段、单位、日期格式和错误行为，再回填 `_map` 中的待验证注释。
