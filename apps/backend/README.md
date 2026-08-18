# CogniWork Backend

Python 3.12 + FastAPI 单体服务（不拆微服务，见 `docs/design/00-conventions.md` §8）。

## 起步

```bash
cd apps/backend
uv venv --python 3.12
uv pip install -e ".[dev]"

.venv/bin/python -m pytest -q          # 含 tests/guards/；默认 memory store
.venv/bin/python -m uvicorn cogniwork.main:app --reload
```

无 Postgres 时把 `COGNIWORK_STORE_BACKEND=memory`（单测 conftest 也会这么设）。
生产路径是 Postgres + Redis：

```bash
docker compose up -d
# 仓库根目录的 .env 里 COGNIWORK_STORE_BACKEND=postgres
.venv/bin/python -m cogniwork.migrate
```

CI 在跑测试之前会执行迁移。

## 目录

| 路径 | 内容 |
|---|---|
| `src/cogniwork/core/` | 跨模块基础：配置、错误模型、UUIDv7、时间、DB/Redis |
| `src/cogniwork/auth/` | 注册/登录、Bearer JWT |
| `src/cogniwork/consent/` | **Scope 注册表 + ConsentService（权限检查的唯一检查点）+ Postgres/Redis store** |
| `src/cogniwork/api/v1/` | REST：`/health` `/auth/*` `/scopes` `/consent` |
| `src/cogniwork/migrate.py` | SQL 迁移工具（`python -m cogniwork.migrate`） |
| `migrations/` | SQL 迁移 |
| `tests/guards/` | **硬约束的可执行形式，见下** |

## tests/guards/ 是什么

不是普通单元测试。每一条对应 `CLAUDE.md` 里的一条硬约束，注释里写明是哪条。

| 文件 | 守护什么 |
|---|---|
| `test_scope_metadata.py` | Scope 六项元数据齐全、`degraded_behavior` 不得为空/占位符/「功能不可用」、文案不得诱导、读写必须分离、未上线连接器不得注册 |
| `test_consent_invariants.py` | `irreversible` 永远逐次审批（即使 `always_allow`）、默认全部 DENY、撤销即失效、授权互不牵连 |
| `test_no_bypass.py` | 权限检查点唯一（静态扫描）、语言不得硬编码、主键不得用 uuid4、时间不得用 naive utcnow |
| `test_cross_language_contracts.py` | 后端与 `packages/shared-types` 的错误码/风险等级词表一致；前端不得复制 Scope 列表 |

**这些测试挂了不是「测试写得不好」，是违反了硬约束。** 改测试之前先改硬约束，反过来不行。

### 为什么先写守护再写功能

`docs/design/P0-07-consent-and-audit.md` §14 把 M6（CI 守护 + E2E 套件）排在最后。
实际实施时提到了最前，理由是这些检查**约束的是别人的代码**：

- 「权限检查无旁路」如果等 Executor 写完再加，那时权限判断已渗进各处，
  检查一开就是全面飘红，修法是把散落的判断收回唯一检查点 —— 先违反再修。
- 「零授权 E2E」如果后加，中间必然会长出对授权的依赖，因为没有任何东西在拦。

守护先于被守护的代码存在，才有意义。

## 发版检查项

标了 `@pytest.mark.release` 的测试**默认不跑**（`pyproject.toml` 的 `addopts` 排除了）。
开发期新增 Scope 时文案必然是待审状态，那时挡住合并没有意义。

```bash
.venv/bin/python -m pytest -q -m release
```

目前只有一条：授权说明文案的英文母语审校（A8 落实要求 ②）。
审校通过后把 `config/scopes.yaml` 对应条目的 `review_status` 改为 `approved`。
