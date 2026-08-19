# CLAUDE.md

CogniWork（AI Coworker OS）。本文件给在此仓库工作的 Claude Code 使用。

## 仓库当前状态

**零授权闭环已通。** 待办与顺序见 [`TODO.md`](TODO.md)，那是唯一的进度事实来源。

```
config/scopes.yaml        ✅ Scope 注册表（授权与审计的唯一事实来源）
config/model_routes.yaml  ✅ Model Router 配置表
apps/backend/             ✅ core/ + consent/ + auth/ + runtime/ + api/v1
  src/cogniwork/core/       配置、错误模型、UUIDv7、UTC 时间、DB/Redis
  src/cogniwork/consent/    Scope 注册表 + ConsentService + Postgres/Redis store
  src/cogniwork/auth/       注册/登录、Bearer JWT
  src/cogniwork/runtime/    TaskEngine 门面、LangGraph、builtin 工具、SSE、LLM 路由
  src/cogniwork/migrate.py  SQL 迁移工具
  migrations/               0001_consent.sql + 0002_account.sql + 0003_task.sql
  tests/guards/           ✅ 硬约束的可执行形式，见下
  tests/e2e/              ✅ 零授权核心路径（P0-07 §8.3）
packages/shared-types/    ✅ 错误码、SSE 事件、审批动作
packages/shared-ui/       ✅ 工作台展示组件（无网络/路由）
apps/web/                 ✅ 任务工作台（三栏 + SSE + 上传/产物）
apps/desktop-shell/       ⬜ 未创建
packages/mcp-connectors/  ⬜ 空目录
```

本地桌面自动化 Agent 在**独立仓库** `cogniwork-desktop-agent`（独立版本、签名、分发节奏）。

### 跑起来

```bash
cd apps/backend
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q                    # 含 tests/guards 与零授权 E2E
.venv/bin/python -m pytest -q -m release         # 发版检查项（默认不跑）
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format .
.venv/bin/python -m uvicorn cogniwork.main:app --reload

# 工作台（另开终端）
pnpm install
pnpm --filter @cogniwork/web dev
```

### `tests/guards/` 是什么

**不是普通单元测试，是硬约束的可执行形式。** 每条对应下面「硬约束」里的一条，注释写明是哪条。

| 文件 | 守护 |
|---|---|
| `test_scope_metadata.py` | 六项元数据齐全、`degraded_behavior` 非空/非占位符/非「不可用」、文案不诱导、读写分离、未上线连接器不得注册 |
| `test_consent_invariants.py` | `irreversible` 永远逐次审批、默认全部 DENY、撤销即失效、授权互不牵连 |
| `test_no_bypass.py` | 检查点唯一（静态扫描）、语言不硬编码、主键不用 uuid4、时间不用 naive utcnow |
| `test_cross_language_contracts.py` | 后端与 `shared-types` 的错误码/风险词表一致、前端不得复制 Scope 列表 |

**这些挂了不是「测试写得不好」，是违反了硬约束。改测试之前先改硬约束，反过来不行。**

守护先于被守护的代码存在才有意义 —— 这是 `P0-07` §14 把 M6 排在最后、实施时提到最前的原因。

## 文档地图

| 路径 | 内容 | 何时读 |
|---|---|---|
| `docs/ai_platform_plan.md` | 产品规划 v3——做什么、为什么、优先级、路线 | 涉及范围/优先级/取舍时 |
| `docs/design/README.md` | 设计文档索引、依赖图、交付顺序、**相对规划的偏离清单** | 开始任何模块工作前 |
| `docs/design/00-conventions.md` | 跨模块公共约定 | **写任何代码前必读** |
| `docs/design/P0-*.md` | Phase 1 必交模块设计 | 实现对应模块时 |
| `docs/design/P1-*.md` | Phase 2 模块设计与研究计划 | 同上 |
| `docs/design/P0-open-questions.md` | **决策留痕**（A1–A10 / B1–B11）+ 执行清单 | 想知道「为什么是这样定的」时；**已全部确认，无待决问题** |
| `TODO.md` | **开发待办与顺序**，每条标明出处文档与章节 | 决定下一步做什么时 |
| `config/README.md` | 怎么加一个 Scope、不要做什么 | 动 `scopes.yaml` 前 |

冲突时的优先级：`00-conventions.md` > `ai_platform_plan.md` > 各模块设计文档。约定要变更时，先改 `00-conventions.md` 再改模块文档。

## 硬约束（不要绕过）

这些不是风格偏好，是产品能否成立的前提。详见 `docs/design/P0-07-consent-and-audit.md`。

1. **默认关闭一切采集。** 任何数据采集、任何有副作用的能力，默认关闭，由用户本人开启（不支持管理员代开启）。
2. **每个能力必须有 Scope。** 命名格式 `<domain>:<target>:<capability>`，在 [`config/scopes.yaml`](config/scopes.yaml) 注册，六项元数据齐全（`trust_level` / `risk` / `display_name` / `collects` / `retention` / `degraded_behavior`）。绕过 Scope 的能力调用是缺陷。**注册表是运行时读取的：不要登记还没实现的连接器的 Scope**，那等于给用户展示一个点不开的授权项。
3. **权限检查点唯一。** 只在 Agent Runtime 的工具调用链上检查（`ConsentService.check`），各 Executor 内部不做也不能做权限判断。
4. **`risk: irreversible` 永远逐次审批**，即使用户已授权、已选「始终允许」。发邮件、删除、支付、对外发送都属此类。
5. **不开启任何可选 Scope 的用户，必须能完整走通核心路径并获得真实价值。** 核心路径 = 「注册 → 跳过访谈 → 上传 xlsx → 发起任务 → 拿到产物 → 下载」。有一个专门的零授权 E2E 测试守护这条（`P0-07` §8.3），它挂了等同 P0 缺陷。**推论：核心路径上的能力不许加 Scope** —— 加了那条测试当场挂。
6. **每个新 Scope 必须声明 `degraded_behavior`**（不授权时功能表现为什么），且不得是「功能不可用」。
7. **明确不采集**：屏幕录制、截图流、键盘按键、鼠标轨迹、剪贴板。这是产品边界，不是「以后再做」。
8. **审计日志只记「做了什么」，不记「内容是什么」。** 全字段脱敏摘要，禁止明文。
9. **凭据不落明文**，不进日志、不进 trace、不进错误上报。

## Phase 1 技术基线

| 层 | 选型 |
|---|---|
| Web / Desktop UI | React + TypeScript + TailwindCSS + shadcn/ui |
| Desktop | Electron + 本地 Python Agent |
| Backend | Python 3.12 + FastAPI + PostgreSQL 16 + Redis（单体，不拆微服务） |
| Agent | LangGraph（不自研 Runtime） |
| 向量 | pgvector HNSW |
| 工具 | MCP |
| 浏览器自动化 | Playwright |
| 桌面自动化 | 分层降级：原生 API（COM/AppleScript/CDP/Graph）→ Accessibility → PyAutoGUI 兜底 |

**Phase 1 已定的关键决策**（全部见 `docs/design/P0-open-questions.md`，那里有推翻记录，不要凭印象）：

| | 结论 |
|---|---|
| 目标用户 / 市场 | 市场 / 运营岗；海外英语市场，美国为主（A1 / A2）|
| 首批连接器 | **Gmail + Google Calendar + Notion + GitHub**（4 个）。**Slack 已移出首批** —— 2026-08-18 改定，推翻了此前的 B3 / A7 |
| 桌面平台 | Windows + macOS 双平台；门禁按「适配器 × 平台」逐格判定（A4）|
| 桌面邮件 | **只做 Graph API 一条**（B5）。Outlook COM 触发式补做，Mail.app 不做 |
| LLM | Anthropic + OpenAI 两家内置 + 用户自定义 provider（A6）|
| 周期 / 人力 | 3.5 个月 × 5 人，约 302 人日，**余量约 2 人日**（A9 / A10）|
| 退出条件 | 6 个真实用户进 L3；**允许 Gmail 未上线就达成**（A3 / A10）|

**Phase 1 明确不做**：Neo4j、独立 Event Store、Rust 组件、微服务拆分、企业管理后台、多租户隔离、Desktop MCP、Slack 连接器。提议引入这些时，先确认对应的延后决策是否已被推翻。

## 代码约定

已有实现的，用现成的，不要另写一份：

| 要做的事 | 用什么 |
|---|---|
| 生成主键 | `core.ids.new_id()`（UUIDv7）。**不要直接 `uuid4()`**，有守护拦 |
| 生成 trace_id | `core.ids.new_trace_id()` |
| 取当前时间 | `core.clock.now()`（UTC + tzinfo）。**不要 `utcnow()`**，有守护拦 |
| 抛对外错误 | `core.errors` 里的 `AppError` 子类，错误码取自 `ErrorCode` 受控词表 |
| 读语言 / 配置 | `core.config.get_settings()`。**不要硬编码 `"en-US"`**，有守护拦（A8 落实要求 ①）|
| 判断权限 | `ConsentService.check()`，**且只在 Runtime 工具调用链上调**。Executor 内部不许出现 `ConsentDecision`，有守护拦 |
| 查 Scope 元数据 | `consent.registry.get_registry()`。前端从 `GET /api/v1/scopes` 拉，**不要在 TS 里复制一份** |

数据与接口：

- 主键 UUIDv7；时间 `timestamptz` 存 UTC，字段名 `*_at`。
- 枚举用 `text` + `CHECK`，不用 PG enum。
- 隐私相关的用户删除请求必须**物理删除**，不能软删。
- REST 前缀 `/api/v1`；长任务与流式输出走 SSE，不用 WebSocket。
- 错误响应统一 `{"error": {"code", "message", "details", "trace_id"}}`，错误码取自受控词表。
- 前端共享组件放 `packages/shared-ui`，只放与运行环境无关的展示组件；网络、路由、存储由宿主注入。

**注释写「为什么」，不写「是什么」。** 现有代码里的注释密度是基线 —— 硬约束相关的地方注释多（要说清为什么不能改成别的样子），普通逻辑不注释。

## 写文档时

- 设计文档统一结构：背景与目标 / 范围 / 需求拆分表 / 数据模型 / 关键流程 / 接口 / 风险与对策 / 验收标准 / 交付拆分 / 待决问题。
- 验收标准要可测量，不写「体验良好」这类无法验证的表述。
- **偏离规划时，必须在 `docs/design/README.md` 的「相对规划的设计偏离」表中登记**，写清原文、调整、理由。
- 待决问题不要藏着——写进「待决问题」章节，标明需要谁来定。

## 语言

- **文档**用中文（规划和设计文档均为中文）。
- **代码标识符、API 字段、错误码**用英文。
- **面向用户的产品文案默认英文（en-US）**，中文作为可选语言保留。

> 最后一条在 2026-08-18 从「以中文为主」改过来，依据是 `docs/design/P0-open-questions.md` 的 A2（目标市场为海外英语市场）与 A8。理由不只是市场——`P0-07` 的隐私模型建立在「用户读懂了授权说明才点同意」上，用非母语读一段「我们会采集什么」，信任建设直接打折。
>
> 落实要求：① 语言从配置读取，**不硬编码默认值**；② 授权说明类文案（`config/scopes.yaml` 的 `collects` / `retention` / `degraded_behavior`）必须过英文母语审校，这是发版检查项；③ 设计文档里的界面示意仍用中文书写以便评审，交付时翻译，且布局需容纳英文文案约 30% 的长度增长。
