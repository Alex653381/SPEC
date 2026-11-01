"""本地数据管理接口。真实更新必须显式调用，并受本地来源与固定资产类型限制。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.services.asset_registration import expand_asset, register_asset
from backend.app.services.update_service import ALLOWED_ASSET_TYPES, build_plan


router = APIRouter()


class UpdateRequest(BaseModel):
    asset_type: str
    start_date: str | None = None
    end_date: str | None = None
    retries: int = Field(default=2, ge=0, le=3)
    backoff: float = Field(default=1.0, ge=0, le=10)


class RegisterAssetRequest(BaseModel):
    asset_type: str
    code: str
    name: str | None = None
    market: str | None = None
    start_date: str
    end_date: str
    confirm: bool = False


class ExpandAssetRequest(BaseModel):
    asset_type: str
    code: str
    start_date: str
    end_date: str
    confirm: bool = False


def _error(code: str, message: str, status_code: int = 400):
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _validate(body: UpdateRequest):
    if body.asset_type not in ALLOWED_ASSET_TYPES:
        return None, _error("INVALID_ASSET_TYPE", "未知资产类型")
    start = _parse_date(body.start_date)
    end = _parse_date(body.end_date)
    if (body.start_date is not None and start is None) or (body.end_date is not None and end is None):
        return None, _error("INVALID_DATE", "日期必须为 YYYY-MM-DD")
    if start is not None and end is not None and start > end:
        return None, _error("INVALID_DATE", "开始日期不能晚于结束日期")
    return (start, end), None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _local_request(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")


@router.post("/update/preflight")
def preflight(body: UpdateRequest, request: Request):
    del request
    window, error = _validate(body)
    if error:
        return error
    try:
        return build_plan(body.asset_type, window[0], window[1])
    except ValueError as exc:
        return _error("PREFLIGHT_FAILED", str(exc))


@router.post("/update/run")
def run_update(body: UpdateRequest, request: Request):
    if not _local_request(request):
        return _error("FORBIDDEN_ORIGIN", "拒绝非本机来源的更新请求", status_code=403)
    window, error = _validate(body)
    if error:
        return error
    if window[0] is None or window[1] is None:
        return _error("MISSING_RANGE", "真实更新必须显式指定 start_date 和 end_date")
    job = request.app.state.update_jobs.start(
        body.asset_type,
        window[0],
        window[1],
        retries=body.retries,
        backoff=body.backoff,
    )
    if "error" in job:
        return _error("ALREADY_RUNNING", f"{body.asset_type} 正在更新，请等待完成", status_code=409)
    return job


@router.get("/update/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    job = request.app.state.update_jobs.get(job_id)
    if job is None:
        return _error("JOB_NOT_FOUND", "任务不存在", status_code=404)
    return job


@router.post("/assets/register")
def register(body: RegisterAssetRequest, request: Request):
    if not _local_request(request):
        return _error("FORBIDDEN_ORIGIN", "拒绝非本机来源的注册请求", status_code=403)
    if not body.confirm:
        return _error("CONFIRM_REQUIRED", "必须显式确认注册")
    if body.asset_type not in ("stock", "etf", "index", "fund"):
        return _error("INVALID_ASSET_TYPE", "当前只支持 stock、etf、index 和 fund")
    start = _parse_date(body.start_date)
    end = _parse_date(body.end_date)
    if start is None or end is None:
        return _error("INVALID_DATE", "日期必须为 YYYY-MM-DD")
    if start > end:
        return _error("INVALID_DATE", "开始日期不能晚于结束日期")
    if (end - start).days > 31:
        return _error("INVALID_RANGE", "首次注册最多允许 31 个自然日")
    try:
        result = register_asset(
            body.asset_type,
            body.code,
            body.name,
            body.market,
            start,
            end,
            retries=1,
            backoff=1.0,
        )
    except ValueError as exc:
        return _error("REGISTER_FAILED", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error("REGISTER_FAILED", f"{type(exc).__name__}: {exc}", status_code=500)
    return result


@router.post("/assets/expand")
def expand(body: ExpandAssetRequest, request: Request):
    if not _local_request(request):
        return _error("FORBIDDEN_ORIGIN", "拒绝非本机来源的扩展请求", status_code=403)
    if not body.confirm:
        return _error("CONFIRM_REQUIRED", "必须显式确认扩展")
    if body.asset_type not in ("stock", "etf", "index", "fund"):
        return _error("INVALID_ASSET_TYPE", "当前只支持 stock、etf、index 和 fund")
    start = _parse_date(body.start_date)
    end = _parse_date(body.end_date)
    if start is None or end is None:
        return _error("INVALID_DATE", "日期必须为 YYYY-MM-DD")
    if start > end:
        return _error("INVALID_DATE", "开始日期不能晚于结束日期")
    if (end - start).days > 400:
        return _error("INVALID_RANGE", "单次扩展最多允许 400 个自然日")
    try:
        result = expand_asset(body.asset_type, body.code, start, end, retries=1, backoff=1.0)
    except ValueError as exc:
        return _error("EXPAND_FAILED", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error("EXPAND_FAILED", f"{type(exc).__name__}: {exc}", status_code=500)
    return result
