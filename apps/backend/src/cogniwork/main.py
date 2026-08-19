"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1 import build_v1_router
from .auth.service import AuthService
from .auth.store import InMemoryAccountStore, PostgresAccountStore
from .consent.registry import get_registry
from .consent.service import build_consent_service
from .consent.store import InMemoryConsentStore, PostgresConsentStore
from .core.config import get_settings
from .core.db import open_pool
from .core.errors import AppError, InvalidRequest, NotFound
from .core.ids import new_trace_id
from .core.redis import open_redis
from .memory.embed import build_embedding_provider
from .memory.service import MemoryService
from .memory.settings import InMemorySettingsStore, PostgresSettingsStore
from .memory.store import InMemoryMemoryStore, PostgresMemoryStore
from .profile.service import ProfileService
from .profile.store import InMemoryProfileStore, PostgresProfileStore
from .runtime.approvals import ApprovalService, InMemoryApprovalStore, PostgresApprovalStore
from .runtime.digest import InMemoryAuditLog, PostgresAuditLog
from .runtime.engine import TaskEngine
from .runtime.events import InMemoryEventBroker, RedisEventBroker
from .runtime.store import InMemoryTaskStore, PostgresTaskStore
from .runtime.tools.registry import build_runtime_registry
from .tools.executor import McpExecutor
from .tools.http import StubTransport
from .tools.service import ToolService
from .tools.store import InMemoryToolStore, PostgresToolStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动即校验 Scope 注册表，不通过就不要起来。

    一个元数据不全的 Scope 宁可让服务起不来，也不能带着空的
    degraded_behavior 跑到用户面前 —— 那正是硬约束 6 要防的事。
    快速失败比带病运行好：配置错误在启动时暴露，代价是一次部署失败；
    在运行时暴露，代价是用户看到一张说不清「不开启会怎样」的授权卡片。
    """
    settings = get_settings()
    app.state.scope_registry = get_registry()
    app.state.idempotency = {}
    if settings.store_backend == "memory":
        app.state.db_pool = None
        app.state.redis = None
        app.state.consent_store = InMemoryConsentStore()
        app.state.account_store = InMemoryAccountStore()
        app.state.memory_store = InMemoryMemoryStore()
        app.state.settings_store = InMemorySettingsStore()
        app.state.approval_store = InMemoryApprovalStore()
        app.state.profile_store = InMemoryProfileStore()
        app.state.tool_store = InMemoryToolStore()
    elif settings.store_backend == "postgres":
        pool = open_pool(settings)
        redis = open_redis(settings)
        app.state.db_pool = pool
        app.state.redis = redis
        app.state.consent_store = PostgresConsentStore(pool, redis)
        app.state.account_store = PostgresAccountStore(pool)
        app.state.memory_store = PostgresMemoryStore(pool)
        app.state.settings_store = PostgresSettingsStore(pool)
        app.state.approval_store = PostgresApprovalStore(pool)
        app.state.profile_store = PostgresProfileStore(pool)
        app.state.tool_store = PostgresToolStore(pool)
    else:
        raise RuntimeError(f"unknown store_backend: {settings.store_backend!r}")
    app.state.auth_service = AuthService(app.state.account_store)
    app.state.consent_service = build_consent_service(
        app.state.consent_store, app.state.scope_registry
    )
    _wire_memory(app)
    _wire_profile(app)
    _wire_tools(app)
    _wire_runtime(app)
    yield
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        redis.close()
    pool = getattr(app.state, "db_pool", None)
    if pool is not None:
        pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="CogniWork API", version="0.0.1", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-trace-id", "x-artifact-filename"],
    )

    @application.middleware("http")
    async def _trace_id(request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response

    @application.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
        return JSONResponse(status_code=exc.status_code, content=exc.to_body(trace_id))

    @application.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
        errors = []
        for err in exc.errors():
            loc = err.get("loc", ())
            # 密码不得出现在错误详情里（硬约束 9）
            if any(part == "password" for part in loc):
                errors.append({"loc": list(loc), "msg": err.get("msg"), "type": err.get("type")})
            else:
                errors.append({"loc": list(loc), "msg": err.get("msg"), "type": err.get("type")})
        return JSONResponse(
            status_code=400,
            content=InvalidRequest(
                "The request is not valid.",
                details={"errors": errors},
            ).to_body(trace_id),
        )

    @application.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
        if exc.status_code == 404:
            err: AppError = NotFound("Not found.")
        else:
            err = InvalidRequest(str(exc.detail), status_code=exc.status_code)
        return JSONResponse(status_code=err.status_code, content=err.to_body(trace_id))

    application.include_router(build_v1_router(), prefix=settings.api_prefix)
    return application


def _wire_runtime(app: FastAPI) -> None:
    settings = get_settings()
    memory_events = InMemoryEventBroker()
    if settings.store_backend == "memory":
        app.state.task_store = InMemoryTaskStore()
        app.state.audit_log = InMemoryAuditLog()
        app.state.event_broker = memory_events
    else:
        app.state.task_store = PostgresTaskStore(app.state.db_pool)
        app.state.audit_log = PostgresAuditLog(app.state.db_pool)
        redis = app.state.redis
        app.state.event_broker = RedisEventBroker(redis, memory_events) if redis else memory_events
    app.state.tools.audit = app.state.audit_log
    app.state.task_engine = TaskEngine(
        store=app.state.task_store,
        events=app.state.event_broker,
        consent=app.state.consent_service,
        audit=app.state.audit_log,
        settings=settings,
        memory=app.state.memory,
        approvals=app.state.approvals,
        profile=app.state.profile,
        tools=build_runtime_registry(app.state.mcp_executor),
    )


def _wire_memory(app: FastAPI) -> None:
    settings = get_settings()
    embeddings = build_embedding_provider(openai_api_key=settings.openai_api_key)
    app.state.memory = MemoryService(
        store=app.state.memory_store,
        embeddings=embeddings,
        consent_store=app.state.consent_store,
        budget_tokens=settings.memory_budget_tokens,
    )
    app.state.approvals = ApprovalService(app.state.approval_store)


def _wire_profile(app: FastAPI) -> None:
    app.state.profile = ProfileService(app.state.profile_store, redis=app.state.redis)


def _wire_tools(app: FastAPI) -> None:
    settings = get_settings()
    transport = StubTransport() if settings.oauth_stub else None
    app.state.tools = ToolService(
        app.state.tool_store,
        settings=settings,
        transport=transport,
        consent=app.state.consent_service,
    )
    app.state.mcp_executor = McpExecutor(app.state.tools, transport=app.state.tools.transport)


app = create_app()
