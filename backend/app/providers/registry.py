"""资产类别到适配器的注册表。"""

from __future__ import annotations

from backend.app.core.quality import AssetType
from backend.app.providers.base import MarketDataAdapter
from backend.app.providers.eastmoney import EastmoneyFundAdapter
from backend.app.providers.sina import SinaETFAdapter, SinaIndexAdapter, SinaStockAdapter


ADAPTER_REGISTRY: dict[str, type[MarketDataAdapter]] = {
    AssetType.STOCK: SinaStockAdapter,
    AssetType.INDEX: SinaIndexAdapter,
    AssetType.ETF: SinaETFAdapter,
    AssetType.OPEN_FUND: EastmoneyFundAdapter,
}


def get_adapter_class(asset_type: str) -> type[MarketDataAdapter] | None:
    return ADAPTER_REGISTRY.get(asset_type)
