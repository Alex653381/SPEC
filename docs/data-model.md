# 数据模型与口径

阶段 1A 的数据标准。股票、指数、场内 ETF 统一为日线记录；场外基金独立为净值记录，不生成 OHLC、成交量或 K 线。

## 1. 资产元数据

每项资产使用 `AssetRecord`，字段与 `assets` 表一致：`id`、`symbol`、`name`、`asset_type`、`market`、`currency`、`provider`、`provider_symbol`、`adjustment_mode`、`price_semantics`、`volume_unit`、`is_active`、`created_at`、`updated_at`。

说明：

- `id` 是系统内部稳定唯一标识，不直接使用外部代码。
- `market + symbol + asset_type` 具有唯一性，解决 `000001` 同时对应平安银行、上证指数和华夏成长的歧义。
- `volume_unit` 与 `price_semantics` 明确数值的语义，避免把成交量误认为成交额。

## 2. 日线模型（股票、指数、ETF）

`DailyBarRecord` 字段：

| 字段 | 类型 | 必须 | 语义 |
| --- | --- | --- | --- |
| `asset_id` | text | 是 | 指向 `assets.id` |
| `trade_date` | date | 是 | 交易日期，不是抓取时间 |
| `open` / `high` / `low` / `close` | float | 是 | 价格或指数点位 |
| `volume` | float | 是 | 成交量，单位由资产 `volume_unit` 定义（股/手） |
| `turnover` | float \| null | 否 | 成交额，单位统一为元；数据源确实提供且口径明确时才保存 |
| `adjustment_mode` | text | 是 | `qfq`/`hfq`/`none` |
| `provider` | text | 是 | 数据来源 |
| `fetched_at` | datetime | 是 | 数据抓取时间 |
| `validated_at` | datetime \| null | 否 | 最近一次校验时间 |
| `quality_status` | text | 是 | 质量状态，见下文 |

口径约束：

- 股票首版固定前复权 `qfq`；前复权历史可能因公司行为被修订，不能视为永久不变。
- 指数与 ETF 不应用股票复权逻辑；ETF 使用数据源原始日线。
- 成交量不随价格复权调整。
- 指数在无已验证成交额时，`turnover` 必须为空，不得推算或填造。
- 不同资产类别的可用字段可能不同；适配器按本模型返回，缺失字段保持为空。

## 3. 基金净值模型

`FundNavRecord` 字段：

| 字段 | 类型 | 必须 | 语义 |
| --- | --- | --- | --- |
| `asset_id` | text | 是 | 指向 `assets.id` |
| `nav_date` | date | 是 | 净值业务日期 |
| `unit_nav` | float | 是 | 单位净值，必须为正数 |
| `accumulated_nav` | float \| null | 否 | 累计净值，仅数据源提供时保存 |
| `provider` | text | 是 | 数据来源 |
| `fetched_at` | datetime | 是 | 抓取时间，与净值日期分开 |
| `validated_at` | datetime \| null | 否 | 最近一次校验时间 |
| `quality_status` | text | 是 | 质量状态 |

约束：

- 不生成伪造的 OHLC、成交量或 K 线。
- 当天没有公布新净值不算抓取失败；不用 0 填补缺失净值。
- 季末/年末落在周末的占位行不得进入正常净值序列，按交易日历隔离。

## 4. 质量状态

| 状态 | 含义 |
| --- | --- |
| `normal` | 正常记录 |
| `missing_pending` | 缺失待核验，不能仅凭缺失判定为停牌 |
| `source_anomaly` | 来源数据异常，例如 OHLC 关系错误 |
| `refetch_needed` | 需要重新获取，例如来源返回空结果 |
| `revised_pending` | 数据已修订或待复核 |

写入规则：

- 缺失字段、非法日期、负成交量、非正单位净值等阻断性问题不写入数据表，改为记录审计或缺口。
- OHLC 关系错误等可保留的异常，写入时标记 `source_anomaly`。
- 异常新数据默认不覆盖已有有效数据；覆盖必须显式指定策略。
