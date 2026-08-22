# CLAUDE.md

CogniWork（AI Coworker OS）。本文件给在此仓库工作的 Claude Code 使用。

## 仓库当前状态

**SaaS 侧 Phase 1（P0-01～P0-07）已落地。** 零授权核心路径、Memory OS、审批/隐私、画像、四个连接器（含写能力）、Skill、Custom Provider 都在本仓库。待办与顺序见 [`TODO.md`](TODO.md)，那是唯一的进度事实来源。

**未做**：桌面 Computer Use（`P0-08`，独立子团队；本仓库没有 `apps/desktop-shell`）。阶段 0 的 Google 验证 / CASA / 用户实验招募仍在。

```
config/
  scopes.yaml             ✅ Scope 注册表（授权与审计的唯一事实来源；14 个 Scope）
  tool_catalog.yaml       ✅ MCP 工具 → Scope / risk 映射（不是第二份 Scope 列表）
  model_routes.yaml       ✅ Model Router
  skill_presets.yaml      ✅ 五个预置 Skill（四个零授权；定义文件不写连接器名）
  task_templates.yaml     ✅ 冷启动任务模板
  interview_question.yaml ✅ 画像访谈题库（按 A1 市场/运营锚定）
apps/backend/             ✅ FastAPI 单体
  src/cogniwork/core/       配置、错误模型、UUIDv7、UTC 时间、DB/Redis、路径查找
  src/cogniwork/consent/    Scope 注册表 + ConsentService + Postgres/Redis store
  src/cogniwork/auth/       注册/登录、Bearer JWT
  src/cogniwork/runtime/    TaskEngine、LangGraph、builtin 工具、SSE、LLM 路由、
                            治理、审批、审计摘要、Skill 驱动、运行态落库（state.py）、
                            产物预览（preview.py）
  src/cogniwork/memory/     Memory OS：混合检索、抽取确认、文件摄取、按 Scope 物理删除
  src/cogniwork/profile/    个人画像 + 访谈状态机 + 注入缓存 + 归档
  src/cogniwork/tools/      MCP Client、Vault、OAuth、连接器适配器、韧性
  src/cogniwork/skill/      Skill CRUD、草稿、预置示例、预检、嵌套限 1 层
  src/cogniwork/privacy/    导出 / 物理删除 / 账号删除（consent_record 匿名化保留）
  src/cogniwork/api/v1/     REST：auth / scopes / consent / tasks / files / memories /
                            privacy / profile / tools / skills / templates / llm / events
  src/cogniwork/migrate.py  SQL 迁移工具
  src/cogniwork/maintenance.py  运维任务：审计分区创建与 12 个月回收
  migrations/               0001–0008（consent / account / task / memory / profile /
                            tools / skill / runtime_state）。审计分区不在迁移里建，
                            见 maintenance.py
  tests/guards/           ✅ 硬约束的可执行形式，见下
  tests/e2e/              ✅ 零授权核心路径（P0-07 §8.3）
  tests/contracts/        ✅ 四个连接器的上游请求/响应契约清单（P0-05 M6）
packages/shared-types/    ✅ 错误码、SSE 事件、审批动作
packages/shared-ui/       ✅ 工作台展示组件（无网络/路由）：三栏壳、审批卡、授权卡、
                            Memory Browser、画像、连接管理、Skill 编辑器、隐私中心
apps/web/                 ✅ 任务工作台（SSE + 上传/产物 + 画像/连接/Skill/隐私）
apps/desktop-shell/       ⬜ 未创建（pnpm-workspace 预留了路径，不要在这里填空壳）
packages/mcp-connectors/  ✅ stdio 入口说明（实现在 backend tools/）
docs/eval/memory-retrieval.md  ✅ 记忆检索 golden query（P0-02）
```

本地桌面自动化 Agent 在**独立仓库** `cogniwork-desktop-agent`（独立版本、签名、分发节奏）。不要把桌面适配器实现写进本仓库。

### 跑起来

```bash
cd apps/backend
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q                    # 含 tests/guards 与零授权 E2E；默认 memory store
.venv/bin/python -m pytest -q -m release         # 发版检查项（默认不跑）
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format .
COGNIWORK_STORE_BACKEND=memory \
  .venv/bin/python -m uvicorn cogniwork.main:app --reload

# 工作台（另开终端，仓库根目录）
pnpm install
pnpm --filter @cogniwork/web dev                 # Vite 把 /api 代理到 :8000
```

有 Postgres + Redis 时走 postgres store（CI 也是这条）。本地起依赖用 `docker compose`，
**那只是开发便捷路径** —— 生产部署是主机 + pm2，见 [`docs/deploy.md`](docs/deploy.md) §6：

```bash
cd apps/backend
docker compose up -d          # 仅本地开发；生产用主机上的 PostgreSQL 16 / Redis 7
# 环境变量见 docs/deploy.md；最少需要：
#   COGNIWORK_STORE_BACKEND=postgres
#   COGNIWORK_DATABASE_URL / COGNIWORK_REDIS_URL / COGNIWORK_JWT_SECRET
.venv/bin/python -m cogniwork.migrate
.venv/bin/python -m cogniwork.maintenance audit-retention   # 审计分区，cron 里也要有
.venv/bin/python -m uvicorn cogniwork.main:app --reload
```

本地连连接器、不想真走 OAuth：`COGNIWORK_OAUTH_STUB=true`。无 LLM 密钥时 `llm_provider=auto` 走 stub，单测与零授权 E2E 不依赖外网。前端没有 `VITE_*` 基址，生产必须由反向代理把 `/api` 转到后端。

### `tests/guards/` 是什么

**不是普通单元测试，是硬约束的可执行形式。** 每条对应下面「硬约束」里的一条，注释写明是哪条。

| 文件 | 守护 |
|---|---|
| `test_scope_metadata.py` | 六项元数据齐全、`degraded_behavior` 非空/非占位符/非「不可用」、文案不诱导、读写分离、未上线连接器不得注册 |
| `test_consent_invariants.py` | `irreversible` 永远逐次审批、默认全部 DENY、撤销即失效、授权互不牵连 |
| `test_no_bypass.py` | 检查点唯一（静态扫描 + DENY 后 Executor 不得出网）、语言不硬编码、主键不用 uuid4、时间不用 naive utcnow |
| `test_cross_language_contracts.py` | 后端与 `shared-types` 的错误码/风险词表一致、前端不得复制 Scope 列表 |
| `test_no_credential_leak.py` | 凭据不进日志/trace/错误上报（硬约束 9） |
| `test_oauth_scope_minimization.py` | OAuth 请求范围不得超出已开启 Scope 对应的最小集合 |

`test_no_bypass.py` 里还有一条 `test_no_local_timezone_today`：`date.today()` / `datetime.now()`
都走本地时区，日额度会在服务器本地午夜翻页，与按 UTC 记账的 `daily_llm_usage` 对不上。
日期用 `core.clock.today()`。

**这些挂了不是「测试写得不好」，是违反了硬约束。改测试之前先改硬约束，反过来不行。**

守护先于被守护的代码存在才有意义 —— 这是 `P0-07` §14 把 M6 排在最后、实施时提到最前的原因。

## 实现时先看这里

代码已经把几条容易写错的边界钉死了。新功能往现成位置加，不要另开一条路。

### 权限：检查点唯一，写入不是第二条判定

```text
调用方 → ToolRouter.invoke → gate_tool_call（runtime/tools/hook.py）
                              └── ConsentService.check（唯一判定）
         Gate.PROCEED  → Executor.invoke（看不到 ConsentDecision）
         Gate.BLOCKED  → 降级文案，不出网
         Gate.NEEDS_APPROVAL → Runtime 建 ApprovalRequest，任务挂起
         人批准之后 → ToolRouter.execute_approved（不再过闸门）
```

- **判定**只发生在 `runtime/tools/hook.py`。`ConsentDecision` / `ConsentService.check` 不得出现在 Executor、`tools/providers.py`、Skill 驱动里。
- **写入**（`grant` / `revoke`）可以在授权 API 和 OAuth 完成时调用 —— 那是落记录，不是第二条 `check()`。`tools/service.py` 因此用 `consent: Any`，不要改成 import `ConsentService`，否则无旁路守护会红。
- `check()` 的 `risk` 是**这次工具调用**的风险，不是 Scope 上登记的风险。`tool:gcal:write` 可以覆盖 `delete_event`（irreversible）；用 Scope 的 risk 会让「始终允许」放过去删除。见 `consent/service.py` 注释。
- builtin 工具 `scope_key=None`，走 `ALLOW`。给上传或 `builtin.write_artifact` 加 Scope，零授权 E2E 当场挂（硬约束 5）。

### Scope 注册表 vs 工具目录

| 文件 | 职责 |
|---|---|
| `config/scopes.yaml` | 授权与审计的唯一事实来源。六项元数据、文案、`third_party_scopes` |
| `config/tool_catalog.yaml` | MCP 工具名 → `scope_key` / `risk` / schema。**不要在这里复制 display_name** |
| `runtime/tools/builtin.py` | L1 工具，不进 catalog |

加一个连接器工具：先有 Scope（或确认已有），再在 catalog 登记，实现放 `tools/providers.py`，
**并在 `tests/contracts/upstream_contracts.json` 录一份契约** —— 有一条测试断言 catalog 里
每个工具都有契约条目且真的有实现。未上线的 **tool 域**连接器不得进注册表（Slack 已移出）。`desktop:*` / `browser:*` 已在 yaml 里为 P0-08 占位，桌面壳未落地前不要在 Web 上做成「点得开但调不通」的授权项。

### 运行态与恢复（RT-5）

`waiting_approval` 可以等 24 小时（`approvals.APPROVAL_TTL`），期间重启后端不能丢上下文。

- **图状态**：`store_backend=postgres` 时 checkpointer 是 `langgraph.checkpoint.postgres.PostgresSaver`。
  它自带一套表（`checkpoints*`），由 `setup()` 在启动时建，**不进 `apps/backend/migrations`** ——
  那套结构属于 langgraph，抄过来只会在升级时打架。
- **运行态**：消息历史 / `used_memories` / `blocked_scopes` / `pending_calls` / `skill_cursors`
  落 `task_runtime_state`（`runtime/state.py`）。`TaskEngine` 上那五个属性仍是 dict 形状，
  但已经是**写穿存储的视图** —— 不要改回普通 dict。
- 列表是原地 `append` 的，视图接不到那次写，所以图的每个节点结束都 flush 一次
  （`graph._flushed`）。手工驱动节点的路径（`_continue_after_approval`）要自己 flush。
- `task.thread_id` **跟着 task 走**，不是每次 invoke 换新的 —— 换新的等于没有 checkpoint。
  显式 `resume()` 一个终态任务才换（图已在 END 上）。
- 任务进终态时 `state.finish()` 扔掉消息历史、留下「凭什么」面板要用的 `used_memories`。
- 启动时 `recover_interrupted()` 接回停在 `running` / `planning` 的任务。**假设单进程部署**。

### 存储与检索

- `COGNIWORK_STORE_BACKEND`：`memory`（单测 / 无基础设施本地）或 `postgres`（CI 与生产）。Redis 是授权缓存 + SSE 补发，不是主存储。
- **审计分区**：`execution_audit` 按月分区，保留 12 个月。执行者是 `cogniwork.maintenance`
  （`audit-retention`），不是手搓 SQL。`DEFAULT` 分区留着当安全网，代价是它里面的过期行
  只能 `DELETE`，不能 drop。
- Memory embedding 列是 `real[]`，余弦在应用层（`memory/embed.py`，维度 1024）。**不要引入独立向量库，也不要在 Phase 1 把 CI 绑到 pgvector** —— 官方 `postgres:16` 没有 `vector` 扩展。生产可后续迁 `vector(1024)` + HNSW，接口不用动。
- 配置文件用 `core.paths.find_config_file`，不要写死「往上走 N 层」。部署覆盖见 `docs/deploy.md`。

### 连接器传输（P0-05 §3）

`COGNIWORK_MCP_TRANSPORT` 默认 `stdio`：连接器跑在独立进程里，崩溃不带上 API，token 走
子进程环境所以不跨用户共享。`inprocess` 只给单测 —— 子进程拿不到测试注入的 `StubTransport`，
断言不到「发出了哪些请求」（`tests/conftest.py` 因此 setdefault 成 `inprocess`）。
填其它值**启动即报错**：静默回落等于悄悄把隔离要求取消掉，而外部看不出区别。
streamable-http 未实现，登记在偏离 11。

断开连接：先调第三方 revoke，再删本地凭据 —— 顺序反了就没 token 可撤了。Notion 没有
撤销端点，API 如实返回 `upstream_revoked: false`，不假装撤掉了。

### Skill / LLM

- 嵌套限 1 层，**运行时拒绝**（`skill/workflow.py` 的 `MAX_NESTING` + `runtime/skill_driver.py`）。其它功能不得依赖嵌套（A9.1 第三刀）。
- 工具步骤允许 `tool=None` 存草稿；激活前 `assert_ready_for_active` 才拦。
- irreversible 步骤禁止 `on_error=retry`。
- Custom provider：`runtime/llm/ssrf.py` 拒绝回环/私网/非 https/重定向；不支持 tool-use 就跳过并告知，**绝不静默降级成文本解析**。走这条路需要 `llm:custom:route`。

### 前端

- 展示组件只放 `packages/shared-ui`；`fetch` / 路由 / `sessionStorage` 在 `apps/web`。
- Scope 列表只从 `GET /api/v1/scopes` 拉，TS 里不得复制。
- 文案长度按英文 +30% 排布局（A8）。
- **搜索与预览都在服务端**：任务搜索走 `?q=`（本地只有已加载的那一页，前端过滤会漏历史）；
  产物预览走 `/artifacts/{id}/preview`（`<img src>` 带不了 Bearer header，截断也该在送出之前做）。
- 提交前跑 `pnpm --filter @cogniwork/web build`（含 `tsc --noEmit`）。

## 文档地图

| 路径 | 内容 | 何时读 |
|---|---|---|
| `docs/ai_platform_plan.md` | 产品规划 v3——做什么、为什么、优先级、路线 | 涉及范围/优先级/取舍时 |
| `docs/deploy.md` | 生产部署：环境变量、单进程限制、迁移、反向代理、备份 72h | 上线或搭生产环境时 |
| `docs/design/README.md` | 设计文档索引、依赖图、交付顺序、**相对规划的偏离清单** | 开始任何模块工作前 |
| `docs/design/00-conventions.md` | 跨模块公共约定 | **写任何代码前必读** |
| `docs/design/P0-*.md` | Phase 1 必交模块设计 | 实现对应模块时 |
| `docs/design/P1-*.md` | Phase 2 模块设计与研究计划 | 同上 |
| `docs/design/P0-open-questions.md` | **决策留痕**（A1–A10 / B1–B11）+ 执行清单 | 想知道「为什么是这样定的」时；**已全部确认，无待决问题**（模块级的 `P0-02` §12 待决 1 也已结清）|
| `docs/eval/memory-retrieval.md` | 记忆检索 golden query + 中文分词决策的测量 | 动 Memory 检索时 |
| `TODO.md` | **开发待办与顺序**，每条标明出处文档与章节 | 决定下一步做什么时 |
| `config/README.md` | 怎么加一个 Scope、不要做什么 | 动 `scopes.yaml` 前 |

冲突时的优先级：`00-conventions.md` > `ai_platform_plan.md` > 各模块设计文档。约定要变更时，先改 `00-conventions.md` 再改模块文档。

偏离清单在 `docs/design/README.md`。**偏离设计文档时必须登记**，13 条都在那张表里 ——
最近三条是 streamable-http 未实现（11）、`packages/mcp-connectors` 位置（12）、
中文分词 Phase 1 不投入（13）。

## 硬约束（不要绕过）

这些不是风格偏好，是产品能否成立的前提。详见 `docs/design/P0-07-consent-and-audit.md`。

1. **默认关闭一切采集。** 任何数据采集、任何有副作用的能力，默认关闭，由用户本人开启（不支持管理员代开启）。
2. **每个能力必须有 Scope。** 命名格式 `<domain>:<target>:<capability>`，在 [`config/scopes.yaml`](config/scopes.yaml) 注册，六项元数据齐全（`trust_level` / `risk` / `display_name` / `collects` / `retention` / `degraded_behavior`）。绕过 Scope 的能力调用是缺陷。**注册表是运行时读取的：不要登记还没实现的连接器的 Scope**，那等于给用户展示一个点不开的授权项。
3. **权限检查点唯一。** 只在 Agent Runtime 的工具调用链上检查（`ConsentService.check`），各 Executor 内部不做也不能做权限判断。
4. **`risk: irreversible` 永远逐次审批**，即使用户已授权、已选「始终允许」。发邮件、删除、支付、对外发送都属此类。
5. **不开启任何可选 Scope 的用户，必须能完整走通核心路径并获得真实价值。** 核心路径 = 「注册 → 跳过访谈 → 上传 xlsx → 发起任务 → 拿到产物 → 下载」。有一个专门的零授权 E2E 测试守护这条（`P0-07` §8.3），它挂了等同 P0 缺陷。**推论：核心路径上的能力不许加 Scope** —— 加了那条测试当场挂。
6. **每个新 Scope 必须声明 `degraded_behavior`**（不授权时功能表现为什么），且不得是「功能不可用」。
7. **明确不采集**：屏幕录制、截图流、键盘按键、鼠标轨迹、剪贴板。这是产品边界，不是「以后再做」。
8. **审计日志只记「做了什么」，不记「内容是什么」。** 全字段脱敏摘要，禁止明文。收件人存数量与哈希。
9. **凭据不落明文**，不进日志、不进 trace、不进错误上报。Vault 信封加密。

## Phase 1 技术基线

| 层 | 选型 |
|---|---|
| Web / Desktop UI | React + TypeScript + TailwindCSS + shadcn/ui |
| Desktop | Electron + 本地 Python Agent（独立仓库；本仓库未建壳） |
| Backend | Python 3.12 + FastAPI + PostgreSQL 16 + Redis（单体，不拆微服务） |
| Agent | LangGraph（不自研 Runtime） |
| 向量 | Phase 1：`real[]` + 应用层余弦。生产可迁 pgvector HNSW（偏离 10） |
| 工具 | MCP（进程内 + 可选 stdio） |
| 浏览器自动化 | Playwright（P1；Scope `browser:web:automate` 已登记） |
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
| 取当前日期 | `core.clock.today()`（UTC）。**不要 `date.today()` / `datetime.now()`**，有守护拦 |
| 抛对外错误 | `core.errors` 里的 `AppError` 子类，错误码取自 `ErrorCode` 受控词表 |
| 读语言 / 配置 | `core.config.get_settings()`。**不要硬编码 `"en-US"`**，有守护拦（A8 落实要求 ①）|
| 找 yaml / 迁移路径 | `core.paths.find_config_file` / `COGNIWORK_*_PATH` |
| 判断权限 | `ConsentService.check()`，**且只在 Runtime 工具调用链上调**。Executor 内部不许出现 `ConsentDecision`，有守护拦 |
| 查 Scope 元数据 | `consent.registry.get_registry()`。前端从 `GET /api/v1/scopes` 拉，**不要在 TS 里复制一份** |
| 加 MCP 工具 | `config/tool_catalog.yaml` + `tools/providers.py`；Scope 仍只写在 `scopes.yaml` |
| 加 L1 工具 | `runtime/tools/builtin.py`，`scope_key=None` |
| 记审计 | `runtime.digest`（脱敏摘要）。不要把参数原文写进 `execution_audit` |
| 跑迁移 | `python -m cogniwork.migrate`；新表用 `text` + `CHECK`，不用 PG enum |
| 跑运维任务 | `python -m cogniwork.maintenance audit-retention`（审计分区与 12 个月回收）|
| 存任务运行态 | `TaskEngine.state`（`runtime/state.py`）。**不要在 engine 上加新的进程内 dict** |
| 算成本 | `runtime.governance.cost_for_tokens(..., vendor=, model=)`。费率按模型分档，不要传单一费率 |

数据与接口：

- 主键 UUIDv7；时间 `timestamptz` 存 UTC，字段名 `*_at`。
- 枚举用 `text` + `CHECK`，不用 PG enum。
- 隐私相关的用户删除请求必须**物理删除**，不能软删。`consent_record` 匿名化保留（B1）。
- REST 前缀 `/api/v1`；长任务与流式输出走 SSE，不用 WebSocket。
- 错误响应统一 `{"error": {"code", "message", "details", "trace_id"}}`，错误码取自受控词表。
- 前端共享组件放 `packages/shared-ui`，只放与运行环境无关的展示组件；网络、路由、存储由宿主注入。
- 产品埋点走 `POST /api/v1/events`，允许的事件名是受控集合。L3 = 授权 L3 Scope **且此后有过成功执行**；`preset_copy` 不计入退出条件。

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
