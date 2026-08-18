"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .consent.registry import get_registry
from .core.config import get_settings
from .core.errors import AppError
from .core.ids import new_trace_id

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动即校验 Scope 注册表，不通过就不要起来。

    一个元数据不全的 Scope 宁可让服务起不来，也不能带着空的
    degraded_behavior 跑到用户面前 —— 那正是硬约束 6 要防的事。
    快速失败比带病运行好：配置错误在启动时暴露，代价是一次部署失败；
    在运行时暴露，代价是用户看到一张说不清「不开启会怎样」的授权卡片。
    """
    app.state.scope_registry = get_registry()
    yield


app = FastAPI(title="CogniWork API", version="0.0.1", lifespan=lifespan)


@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    return JSONResponse(status_code=exc.status_code, content=exc.to_body(trace_id))


@app.get(f"{settings.api_prefix}/health")
def health() -> dict[str, object]:
    registry = get_registry()
    return {
        "status": "ok",
        "version": app.version,
        "scopes_registered": len(registry),
        "default_locale": settings.default_locale,
    }
