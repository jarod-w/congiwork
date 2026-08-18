# 00 — 跨模块公共约定（Conventions）

> 所有 P0/P1 设计文档共用的命名、模型与接口约定。任何模块文档与本文冲突时，以本文为准；需要变更约定的，先改本文再改模块文档。

---

## 1. 术语表

| 术语 | 含义 | 备注 |
|---|---|---|
| User | 单个自然人账号 | Phase 1 以个人用户为单位，不引入组织多租户 |
| Org | 组织/企业 | Phase 1 仅预留字段（`org_id` 可空），不实现企业管理后台 |
| Task | 一次可被追踪的工作请求，从用户发起到产出结果 | Agent Runtime 的调度单元 |
| Step | Task 内的一个执行环节（LLM 推理 / 工具调用 / 审批） | 可视化与审计的最小粒度 |
| Skill | 结构化、可复用的工作流程定义 | 见 `P0-06` |
| Memory Item | 一条长期记忆 | 见 `P0-02` |
| Scope | 一条可授权的能力范围标识 | 见本文 §3 |
| Surface | 用户接触面：`web` / `desktop` / `browser_ext` | 事件与审计需标注来源 |
| Adapter | 桌面端针对某个本地应用的自动化适配实现 | 见 `P0-08` |

---

## 2. 标识与基础字段约定

- 所有主键使用 **UUIDv7**（时间有序，便于分页与冷热分离），数据库类型 `uuid`。
- 所有时间字段使用 `timestamptz`，统一存 UTC，命名 `*_at`。
- 所有面向用户的资源表必须包含：`user_id`、`created_at`、`updated_at`。
- 软删除统一用 `deleted_at timestamptz NULL`；**但隐私相关的用户删除请求必须物理删除**（见 `P0-07` §6）。
- 枚举一律用 `text` + `CHECK` 约束，不用 PG enum 类型（避免迁移成本）。
- 金额/成本用 `numeric(12,6)`，单位统一为 USD。

---

## 3. 授权 Scope 命名规范（核心约定）

所有需要用户授权的能力，必须声明一个 Scope，格式：

```
<domain>:<target>:<capability>
```

| domain | 含义 | 示例 |
|---|---|---|
| `tool` | 外部 SaaS 工具（MCP 连接器） | `tool:slack:read` / `tool:slack:send` |
| `desktop` | 桌面端本地应用操作 | `desktop:excel:automate` / `desktop:mail:automate` |
| `browser` | 浏览器自动化 | `browser:web:automate` |
| `file` | 本地/上传文件访问 | `file:upload:read` |
| `telemetry` | 结构化操作日志采集 | `telemetry:desktop_excel:collect` |
| `memory` | 记忆自动写入 | `memory:preference:auto_write` |
| `llm` | 把内容发往用户自配的模型服务 | `llm:custom:route` |

capability 的受控词表：`read` / `write` / `send` / `automate` / `collect` / `auto_write` / `route`。

> 示例统一用 Phase 1 实际会实现的 Scope。**不要拿 `tool:gmail:*` 当示例**——Gmail 已按 `P0-open-questions.md` B3 移出 Phase 1，用它举例会让人以为要建这个连接器。

**规则：**

1. Scope 是授权与审计的唯一凭据，任何绕过 Scope 的能力调用视为缺陷。
2. Scope 粒度必须做到「授权 A 不等于授权 B」：`desktop:excel:automate` 与 `desktop:mail:automate` 是两个独立开关。
3. 每个 Scope 必须在注册表中声明四项元数据，缺一不可：
   - `display_name`：给用户看的名字
   - `collects`：会读取/产生什么数据（面向用户的自然语言，非技术描述）
   - `risk`：`read` | `write` | `irreversible`
   - `degraded_behavior`：**未授权时该功能的降级行为**（见 §5 自愿性检查）
4. `risk = irreversible` 的 Scope（对外发信、删除数据、支付类操作）即使已授权，运行时仍强制逐次审批。

### 3.1 与信任爬坡层级的映射

| 信任层 | 对应 Scope 类型 | 授权时机 |
|---|---|---|
| L1 单次任务代劳 | 无需 Scope | 注册即可用 |
| L2 只读工具 | `tool:*:read` | 连接器授权流程 |
| L3 执行类工具 / 本地应用操作 | `tool:*:send`、`tool:*:write`、`desktop:*:automate`、`browser:web:automate` | 逐项开启 + 逐次审批 |
| L4 结构化日志采集 | `telemetry:*:collect` | 逐场景开启（Phase 2） |

---

## 4. 统一执行与审批模型

所有具备副作用的能力（MCP 工具、桌面 Adapter、浏览器自动化、Skill 内步骤）走同一条执行管线：

```text
调用方
   │  ToolCall{ scope, action, args }
   ▼
ConsentService.check(user_id, scope, risk)
   │
   ├── deny            → 返回 PermissionDenied，Runtime 转为向用户解释并给出降级方案
   ├── require_approval → Task 挂起为 waiting_approval，推送 ApprovalRequest
   └── allow           → 执行
   ▼
ExecutionAudit.record(...)   ← 无论成功失败都必须落审计
```

`ApprovalRequest` 统一结构：

```json
{
  "approval_id": "uuid",
  "task_id": "uuid",
  "step_id": "uuid",
  "scope": "desktop:mail:automate",
  "risk": "irreversible",
  "title": "发送邮件给 3 位收件人",
  "preview": { "type": "email|table|diff|text", "data": {} },
  "editable_fields": ["subject", "body", "to"],
  "expires_at": "2026-08-16T10:00:00Z"
}
```

用户可选动作固定为四种：`approve` / `edit_and_approve` / `reject` / `always_allow_this_scope`（最后一项对 `irreversible` 不可用）。

---

## 5. 「自愿性」设计评审检查项（强制）

来源：`ai_platform_plan.md` §2.1 —— 「这一点要写进设计评审的检查项，而不只是写进文档」。

任何引入新 Scope 或修改现有 Scope 的 PR，必须在描述中填写下表，评审人逐项确认，缺项直接拒绝合并：

| 检查项 | 要求 |
|---|---|
| Scope 声明 | 新增/变更的 Scope 已在注册表中登记，四项元数据齐全 |
| 降级行为 | 明确写出「用户不开启此 Scope 时，本功能表现为什么」，且该表现**不得是功能不可用**，除非该功能本身就是该 Scope 的直接产物 |
| 核心路径无依赖 | 确认新 Scope 不出现在「注册 → 发起任务 → 得到结果」这条核心路径上 |
| 文案审查 | 授权说明文案不含诱导性表述（如「开启后才能获得完整体验」） |
| 撤销可用 | 该 Scope 可在设置中一键关闭，关闭后相关已采集数据可查看和删除 |

> 判定基线：**不开启任何可选 Scope 的用户，必须能完整走通 L1 单次任务代劳，并获得真实价值。** 这是产品设计约束，不是免责声明。

---

## 6. API 约定

- REST 风格，前缀 `/api/v1`，认证用 Bearer JWT。
- 长任务与流式输出统一走 **SSE**（`text/event-stream`），不引入 WebSocket（Phase 1 无双向低延时需求）。
- 错误响应统一：

```json
{ "error": { "code": "permission_denied", "message": "...", "details": {}, "trace_id": "..." } }
```

- 错误码受控词表：`invalid_request` / `unauthorized` / `permission_denied` / `not_found` / `conflict` / `rate_limited` / `upstream_error` / `internal_error`。
- 幂等：所有 `POST` 创建类接口支持 `Idempotency-Key` 头。

---

## 7. 事件流约定（SSE）

Task 执行期间的事件类型（前后端共用，定义在 `packages/shared-types`）：

| event | 说明 |
|---|---|
| `task.created` | 任务创建 |
| `task.status` | 状态变更 |
| `plan.updated` | 计划/待办列表更新 |
| `step.started` / `step.finished` | 步骤起止 |
| `tool.call` / `tool.result` | 工具调用与返回（含脱敏后的参数摘要） |
| `message.delta` | LLM 流式文本增量 |
| `approval.requested` / `approval.resolved` | 审批请求与结果 |
| `artifact.created` | 产物生成 |
| `memory.candidate` | 产生了待确认的记忆候选 |
| `task.finished` | 终态（含 `succeeded`/`failed`/`cancelled`/`timeout`） |

所有事件包含公共字段：`event`、`task_id`、`ts`、`seq`（单调递增，用于断线重连补发）。

---

## 8. 技术栈基线（不重复论证，见 `ai_platform_plan.md` §7–8）

| 层 | 选型 | Phase 1 约束 |
|---|---|---|
| Web | React + TS + Tailwind + shadcn/ui | 组件沉淀在 `packages/shared-ui`，桌面端复用 |
| Desktop | Electron + React + 本地 Python Agent | 见 `P0-08` |
| Backend | Python 3.12 + FastAPI + PostgreSQL 16 + Redis | 单体服务，不拆微服务 |
| Agent | LangGraph | 不自研 Runtime（计划 §7.5） |
| 向量 | pgvector（HNSW） | 不引入独立向量库，不引入 Neo4j |
| 工具 | MCP | 见 `P0-05` |

**明确不做（Phase 1）**：Neo4j、独立 Event Store、Rust 组件、微服务拆分、企业管理后台、多租户隔离。

---

## 9. 文档索引

见 [README.md](README.md)。
