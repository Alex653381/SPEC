"""分析接口请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    asset_id: str
    benchmark_asset_id: str
    start_date: str | None = None
    end_date: str | None = None


class PortfolioItem(BaseModel):
    asset_id: str
    weight: float = Field(ge=0)


class PortfolioRequest(BaseModel):
    items: list[PortfolioItem]
    start_date: str | None = None
    end_date: str | None = None
