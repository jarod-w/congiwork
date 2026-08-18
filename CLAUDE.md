# CLAUDE.md

CogniWork（AI Coworker OS）。本文件给在此仓库工作的 Claude Code 使用。

## 仓库当前状态

**这是一个文档先行的仓库，目前还没有任何代码。** 只有 `README.md`、`LICENSE` 和 `docs/`。

计划中的 monorepo 结构（见 README「Repository Structure」，尚未创建）：

```
apps/web/            Web SaaS 前端
apps/desktop-shell/  Electron 壳 + 桌面 UI，复用 web 组件
apps/backend/        FastAPI 后端、Agent 编排、Memory OS
packages/shared-ui/  web 与 desktop 共享组件
packages/shared-types/ API 类型、Skill schema
packages/mcp-connectors/ SaaS 连接器
```

本地桌面自动化 Agent 在**独立仓库** `cogniwork-desktop-agent`（独立版本、签名、分发节奏）。

## 文档地图

| 路径 | 内容 | 何时读 |
|---|---|---|
| `docs/ai_platform_plan.md` | 产品规划 v3——做什么、为什么、优先级、路线 | 涉及范围/优先级/取舍时 |
| `docs/design/README.md` | 设计文档索引、依赖图、交付顺序、**相对规划的偏离清单** | 开始任何模块工作前 |
| `docs/design/00-conventions.md` | 跨模块公共约定 | **写任何代码前必读** |
| `docs/design/P0-*.md` | Phase 1 必交模块设计 | 实现对应模块时 |
| `docs/design/P1-*.md` | Phase 2 模块设计与研究计划 | 同上 |

冲突时的优先级：`00-conventions.md` > `ai_platform_plan.md` > 各模块设计文档。约定要变更时，先改 `00-conventions.md` 再改模块文档。

## 硬约束（不要绕过）

这些不是风格偏好，是产品能否成立的前提。详见 `docs/design/P0-07-consent-and-audit.md`。

1. **默认关闭一切采集。** 任何数据采集、任何有副作用的能力，默认关闭，由用户本人开启（不支持管理员代开启）。
2. **每个能力必须有 Scope。** 命名格式 `<domain>:<target>:<capability>`，在 `config/scopes.yaml` 注册，元数据六项齐全。绕过 Scope 的能力调用是缺陷。
3. **权限检查点唯一。** 只在 Agent Runtime 的工具调用链上检查（`ConsentService.check`），各 Executor 内部不做也不能做权限判断。
4. **`risk: irreversible` 永远逐次审批**，即使用户已授权、已选「始终允许」。发邮件、删除、支付、对外发送都属此类。
5. **不开启任何可选 Scope 的用户，必须能完整走通核心路径并获得真实价值。** 有一个专门的零授权 E2E 测试守护这条，它挂了等同 P0 缺陷。
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

**Phase 1 明确不做**：Neo4j、独立 Event Store、Rust 组件、微服务拆分、企业管理后台、多租户隔离、Desktop MCP。提议引入这些时，先确认规划中对应的延后决策是否已被推翻。

## 代码约定（代码落地后适用）

- 主键 UUIDv7；时间 `timestamptz` 存 UTC，字段名 `*_at`。
- 枚举用 `text` + `CHECK`，不用 PG enum。
- 隐私相关的用户删除请求必须**物理删除**，不能软删。
- REST 前缀 `/api/v1`；长任务与流式输出走 SSE，不用 WebSocket。
- 错误响应统一 `{"error": {"code", "message", "details", "trace_id"}}`，错误码取自受控词表。
- 前端共享组件放 `packages/shared-ui`，只放与运行环境无关的展示组件；网络、路由、存储由宿主注入。

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
