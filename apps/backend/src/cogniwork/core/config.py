"""应用配置。

A8 落实要求 ①：**语言从配置读取，不硬编码默认值。**
因此 default_locale 是一个配置项，代码里任何地方都不许写死 "en-US" 或 "zh-CN"。
需要语言时从 settings 取。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COGNIWORK_",
        env_file=".env",
        extra="ignore",
    )

    # ── 语言（A8）──
    # 交付基线 en-US，zh-CN 为可选语言。两者都从这里读，不在代码里写死。
    default_locale: str = "en-US"
    fallback_locale: str = "en-US"
    supported_locales: tuple[str, ...] = ("en-US", "zh-CN")

    # ── 服务 ──
    api_prefix: str = "/api/v1"
    debug: bool = False

    # ── 数据 ──
    # memory：进程内实现，给单测与无基础设施的本地启动。
    # postgres：生产路径。Redis 是授权态缓存，写时失效；未命中回落 consent_current。
    store_backend: str = "postgres"
    database_url: str = "postgresql://localhost:5432/cogniwork"
    redis_url: str = "redis://localhost:6379/0"

    # ── 认证（00-conventions.md §6：Bearer JWT）──
    jwt_secret: str = "dev-only-change-me-not-for-production!!"
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 60 * 60 * 24 * 7

    # IP 入 consent_record 前先哈希，不存原文（硬约束 8）
    ip_hash_pepper: str = "dev-only-change-me"

    # ── 前端 ──
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    # ── Agent / LLM（P0-03 §7）──
    # auto：有密钥走内置供应商，没有则 stub。单测与零授权 E2E 不依赖外网。
    llm_provider: str = "auto"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    max_upload_bytes: int = 20 * 1024 * 1024
    task_step_limit: int = 25
    task_cost_usd_limit: float = 0.50
    daily_cost_usd_limit: float = 5.00
    model_routes_path: str = ""
    memory_budget_tokens: int = 2000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
