"""FastAPI 应用工厂。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from backend.app.api.admin import router as admin_router
from backend.app.api.analysis import router as analysis_router
from backend.app.api.routes import router
from backend.app.api.status import router as status_router
from backend.app.core.config import AppSettings, load_settings
from backend.app.services.analysis_access import AnalysisAccess, SourceDb
from backend.app.services.update_service import UpdateJobManager


def create_app(
    settings: AppSettings | None = None,
    dashboard_config_path: str | Path | None = None,
    analysis_sources: dict[str, list[SourceDb]] | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    root = Path(__file__).resolve().parents[3]
    if dashboard_config_path is None:
        dashboard_config_path = root / "config" / "default-dashboard.json"

    app = FastAPI(title="Market Research API", debug=False)
    app.state.settings = app_settings
    app.state.database_path = app_settings.database_path
    app.state.dashboard_config_path = str(dashboard_config_path)
    app.state.update_jobs = UpdateJobManager()
    app.state.analysis_access = AnalysisAccess(
        analysis_sources
        if analysis_sources is not None
        else _default_analysis_sources(root, app_settings.database_path)
    )
    app.include_router(router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1/analysis")
    app.include_router(status_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1/admin")
    return app


def _default_analysis_sources(root: Path, primary_db: str) -> dict[str, list[SourceDb]]:
    primary = SourceDb(path=primary_db, label="primary")
    live_stock = SourceDb(path=str(root / "data" / "live-pilot.db"), label="live_stock")
    live_fund = SourceDb(path=str(root / "data" / "live-fund-pilot.db"), label="live_fund")
    live_benchmark = SourceDb(path=str(root / "data" / "live-benchmark.db"), label="live_benchmark")
    live_etf = SourceDb(path=str(root / "data" / "live-etf-pilot.db"), label="live_etf")
    return {
        "stock": [live_stock, primary],
        "index": [live_benchmark, primary],
        "etf": [live_etf, primary],
        "open_fund": [live_fund, primary],
    }
