"""数据质量状态与资产类型常量。"""

from __future__ import annotations


class AssetType:
    STOCK = "stock"
    INDEX = "index"
    ETF = "etf"
    OPEN_FUND = "open_fund"

    ALL = (STOCK, INDEX, ETF, OPEN_FUND)


class AdjustmentMode:
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class QualityStatus:
    """数据质量状态，值稳定并写入数据库。"""

    NORMAL = "normal"
    MISSING_PENDING = "missing_pending"
    SOURCE_ANOMALY = "source_anomaly"
    REFETCH_NEEDED = "refetch_needed"
    REVISED_PENDING = "revised_pending"

    ALL = (
        NORMAL,
        MISSING_PENDING,
        SOURCE_ANOMALY,
        REFETCH_NEEDED,
        REVISED_PENDING,
    )


class GapStatus:
    OPEN = "open"
    REVIEWED = "reviewed"
