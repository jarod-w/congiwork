# P0-03 Agent Runtime（任务执行内核）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付） |
| 对应规划 | `ai_platform_plan.md` §3（Agent Runtime-P0）、§7.5、§7.6 |
| 依赖 | `P0-07 隐私授权`（权限钩子）、`P0-02 Memory OS`（上下文）、`P0-05 MCP`（工具） |
| 被依赖 | `P0-04`、`P0-06`、`P0-08`、`P1-*` 全部 |
| 文档状态 | Draft |

---

## 1. 背景与目标

Agent Runtime 是所有「AI 执行工作」的统一内核。Web 聊天、Skill 执行、桌面 Computer Use、浏览器自动化，最终都是同一个 Runtime 在跑，区别只是可用的工具集不同。

把它做成统一内核而不是每个场景各写一套，直接决定了三件事能否成立：审批模型的一致性、审计的完整性、Episodic Memory 的自动落库。

目标：

- **G1** 一个 Task 从发起到终态全程可恢复——进程重启、用户关闭页面、审批等待 2 小时后再回来，都能继续。
- **G2** 任何有副作用的动作都必须经过统一的权限检查与审计，无旁路。
- **G3** 执行过程对用户可见且可干预——不是一个黑盒转圈。

非目标：

- 不自研 Agent 框架（计划 §7.5 明确用 LangGraph，是否自研留到 Phase 2 评估）。
- 不做多 Agent 协作编排（Phase 3）。
- 不做任务定时调度（Phase 2 随 Skill trigger 一起做）。

---

## 2. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| RT-1 | Task 生命周期 | 状态机定义与持久化 | 见 §3 |
| RT-2 | 执行图 | LangGraph 图定义：plan → act → observe → finish | 支持中断/恢复 |
| RT-3 | 工具抽象层 | 统一 ToolSpec / ToolCall，屏蔽 MCP / Desktop / Browser 差异 | 新增一类工具不改 Runtime |
| RT-4 | Human-in-the-loop | 中断、审批、编辑后继续 | 审批等待期间不占用计算资源 |
| RT-5 | 持久化与恢复 | Checkpointer 落 PostgreSQL | kill -9 后可从最后一个 checkpoint 恢复 |
| RT-6 | 事件流 | SSE 推送执行过程，支持断线重连补发 | 见 `00-conventions.md` §7 |
| RT-7 | Model Router | 按任务类型/上下文长度/能力需求路由模型 | 支持 ≥2 家供应商，切换无需改业务代码 |
| RT-8 | 资源治理 | 超时、重试、并发上限、成本上限 | 单任务成本超限自动暂停并询问用户 |
| RT-9 | 失败处理 | 分类错误、可读的失败说明、可重试 | 用户能看懂失败原因并知道下一步 |

---

## 3. Task 生命周期

```text
                 ┌──────────────────────────────────┐
                 │                                  │
created ──▶ planning ──▶ running ──▶ waiting_approval┘
   │            │           │              │
   │            │           │              └── reject ──┐
   │            │           ├── 成功 ──▶ succeeded      │
   │            │           ├── 失败 ──▶ failed         │
   │            │           └── 超时 ──▶ timed_out      │
   │            │                                       │
   └────────────┴───── 用户取消 ──▶ cancelled ◀─────────┘
```

```sql
CREATE TABLE task (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  conversation_id uuid NOT NULL,
  title         text NULL,                -- 首轮后由 LLM 生成
  intent        text NULL,                -- 归一化意图标签，供 Episodic 检索
  status        text NOT NULL,
  surface       text NOT NULL CHECK (surface IN ('web','desktop','browser_ext','api')),
  skill_id      uuid NULL,                -- 由 Skill 触发时记录
  input         jsonb NOT NULL,
  result        jsonb NULL,
  error         jsonb NULL,               -- {code, message, retryable, step_id}
  thread_id     text NOT NULL,            -- LangGraph checkpointer thread
  cost_usd      numeric(12,6) NOT NULL DEFAULT 0,
  token_in      int NOT NULL DEFAULT 0,
  token_out     int NOT NULL DEFAULT 0,
  started_at    timestamptz NULL,
  ended_at      timestamptz NULL,
  created_at    timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL
);

CREATE TABLE task_step (
  id            uuid PRIMARY KEY,
  task_id       uuid NOT NULL REFERENCES task(id) ON DELETE CASCADE,
  seq           int NOT NULL,
  type          text NOT NULL CHECK (type IN ('llm','tool','approval','skill','subtask')),
  title         text NOT NULL,            -- 面向用户的一句话描述
  status        text NOT NULL,
  scope_key     text NULL,
  input_digest  jsonb NULL,               -- 脱敏后的参数摘要，非全量
  output_digest jsonb NULL,
  error         jsonb NULL,
  duration_ms   int NULL,
  created_at    timestamptz NOT NULL
);
CREATE UNIQUE INDEX ON task_step (task_id, seq);
```

> `input_digest` / `output_digest` 而非全量存储：工具的输入输出可能包含邮件正文、客户名单等敏感内容。Step 表的定位是「执行轨迹」，不是「数据仓库」。全量内容留在对话消息里，由用户可见可删的路径管理。

---

## 4. 执行图设计（RT-2）

```text
        ┌────────────┐
   ───▶ │  prepare   │  组装上下文：Profile Card + Memory Bundle + 可用工具集
        └─────┬──────┘
              ▼
        ┌────────────┐
        │   plan     │  产出/更新待办列表（简单任务可直接跳过到 act）
        └─────┬──────┘
              ▼
        ┌────────────┐      需审批
        │    act     │ ──────────────▶ ┌──────────┐
        │ (LLM+tool) │                 │ interrupt│ ──▶ 持久化，等待用户
        └─────┬──────┘ ◀────────────── └──────────┘        resume
              ▼            批准/编辑后
        ┌────────────┐
        │  observe   │  工具结果入上下文，判断是否完成 / 是否需重规划
        └─────┬──────┘
              │ 未完成 ─▶ 回 act（或 plan）
              ▼ 完成
        ┌────────────┐
        │  finalize  │  产出结果、写 Episodic、生成记忆候选
        └────────────┘
```

设计要点：

1. **`plan` 是可选节点**。单步任务（「帮我改下这段文案」）直接进 `act`，避免为简单请求付出一次额外 LLM 调用。判定用一个轻量分类：请求是否涉及 ≥2 个工具或 ≥2 个明确子目标。
2. **`act` 的循环上限**：默认 25 步。达到上限不是直接失败，而是转 `waiting_approval` 问用户「已经做了 25 步还没完成，要继续吗」。这比静默失败或无限烧钱都好。
3. **`interrupt` 用 LangGraph 原生中断机制**，状态由 checkpointer 落 PostgreSQL，等待期间不持有任何内存或连接资源。

---

## 5. 工具抽象层（RT-3）

Runtime 不认识 MCP、不认识 PyAutoGUI，只认识 `ToolSpec`：

```python
@dataclass
class ToolSpec:
    name: str                    # 'gmail.send_email'
    provider: str                # 'mcp' | 'desktop' | 'browser' | 'builtin'
    description: str
    input_schema: dict           # JSON Schema，直接给 LLM 做 tool-use
    scope_key: str | None        # 'tool:gmail:send'
    risk: Literal['read','write','irreversible']
    preview_renderer: str | None # 审批卡片用哪个渲染器：'email'|'table'|'diff'|'text'
    timeout_s: int = 60
    retryable: bool = True
```

调用链：

```text
LLM 决定调用 tool
      ▼
ToolRouter.resolve(name) → ToolSpec + Executor
      ▼
ConsentService.check(user_id, spec.scope_key, spec.risk)
      │  见 00-conventions.md §4
      ├── deny → 返回结构化拒绝给 LLM，LLM 转为向用户解释并给替代方案
      ├── require_approval → 生成 ApprovalRequest，图中断
      └── allow → 继续
      ▼
Executor.invoke(args)   ← MCPExecutor / DesktopExecutor / BrowserExecutor / BuiltinExecutor
      ▼
ExecutionAudit.record(...)（成功失败都记）
      ▼
结果脱敏摘要 → task_step.output_digest；完整结果 → LLM 上下文
```

**权限检查放在 Runtime 而非各 Executor**，是为了保证无旁路：新增一类 Executor 天然继承检查逻辑，不会因为漏写而绕过。这一条应有测试守护：对每个注册的 ToolSpec 断言 `scope_key` 非空（除 `risk='read'` 的 builtin 工具外）。

内置工具（无需授权，L1 层）：

| 工具 | 说明 |
|---|---|
| `builtin.read_uploaded_file` | 读取本次任务上传的文件 |
| `builtin.write_artifact` | 产出文件/表格结果 |
| `builtin.search_memory` | 检索用户自己的记忆 |
| `builtin.ask_user` | 向用户提问澄清 |

`builtin.ask_user` 值得强调：它让「信息不足时主动问」成为一个显式动作而不是 LLM 自由发挥的文本，从而能被 UI 渲染成结构化提问卡片。

---

## 6. Human-in-the-loop（RT-4）

审批触发条件（任一命中）：

1. `ToolSpec.risk == 'irreversible'` —— 永远审批，即使已授权。
2. `ConsentService` 返回 `require_approval`（用户未选「始终允许」）。
3. Skill 定义中显式标记的 `approval` 步骤。
4. 单次任务累计成本超过阈值（默认 $0.50）。

审批卡片的 `preview` 必须是**结果预览而非参数罗列**——用户要看到「这封邮件长什么样」，不是 `{"to": [...], "subject": "..."}`。这由 `preview_renderer` 负责。

编辑后继续（`edit_and_approve`）的语义：用户修改后的参数直接替换原 args 执行，同时把「改了什么」写入 `episodic_record.user_edits`，作为 Preference Memory 的候选来源（见 `P0-02` §4）。

审批超时：默认 24 小时未响应，任务转 `timed_out`，但保留完整上下文，用户可一键重启并沿用已完成的步骤。

---

## 7. Model Router（RT-7）

```python
@dataclass
class RoutingRequest:
    task_intent: str | None
    context_tokens: int
    needs_vision: bool
    needs_tool_use: bool
    latency_class: Literal['interactive','background']
    cost_tier: Literal['economy','standard','premium']
```

路由规则用**配置表而非代码**（`config/model_routes.yaml`），便于不改代码调整：

```yaml
routes:
  - match: { needs_vision: true }
    model: primary.vision
  - match: { latency_class: interactive, cost_tier: economy }
    model: fast.small          # 意图分类、标题生成、记忆抽取
  - match: { context_tokens: ">200000" }
    model: primary.long_context
  - default: primary.standard

providers:
  primary:   { vendor: anthropic, ... }
  fallback:  { vendor: <second_vendor>, ... }
```

Phase 1 约束（计划 §7.6）：**先跑通 1–2 家**。故 `fallback` 只在 primary 连续失败时启用，不做智能负载分配。

模型能力差异由 `LLMClient` 抽象层吸收（tool-use 格式、流式协议、token 计数），业务层不感知 vendor。

---

## 8. 资源治理（RT-8）

| 维度 | 默认值 | 超限行为 |
|---|---|---|
| 单任务步数 | 25 | 转审批询问是否继续 |
| 单任务成本 | $0.50 | 转审批，展示已花费明细 |
| 单任务墙钟时长 | 30 min（不含审批等待） | `timed_out` |
| 单工具调用超时 | `ToolSpec.timeout_s` | 重试 1 次后作为 step 失败 |
| 用户并发任务数 | 3 | 排队 |
| 全局 LLM 并发 | 按配额配置 | 令牌桶限流，超限排队 |

成本记账：每次 LLM 调用后累加到 `task.cost_usd`，同时写日次聚合表供后续定价验证（计划 §10.3 需要这份数据）。

---

## 9. 失败处理（RT-9）

错误分类与用户可读表述：

| 分类 | 例子 | 呈现给用户 | 可重试 |
|---|---|---|---|
| `permission_denied` | 未授权 Gmail 发送 | 「我需要你授权发送邮件才能完成这步，也可以我把草稿给你自己发」 | 授权后是 |
| `upstream_error` | Notion API 503 | 「Notion 暂时没响应」 | 是 |
| `tool_failed` | Excel 适配器定位不到控件 | 「操作 Excel 时没找到目标位置」+ 截图 | 是 |
| `invalid_input` | 用户给的文件格式不支持 | 「这个格式我还读不了，支持这些：…」 | 否 |
| `budget_exceeded` | 成本超限 | 「这个任务比预期复杂，已花费 $X，继续吗」 | 是 |
| `internal_error` | 未分类异常 | 「出了点问题，我已经记录下来了」+ trace_id | 是 |

**部分成功必须如实呈现**：已完成 3 步、第 4 步失败时，结果里要写清楚哪些做了、哪些没做，绝不把部分完成描述成完成。这条要作为 prompt 约束 + `finalize` 节点的结构化输出约束双重保证。

---

## 10. 接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/tasks` | 创建任务，返回 `task_id` |
| `GET` | `/api/v1/tasks/{id}` | 任务详情（含 steps） |
| `GET` | `/api/v1/tasks/{id}/events?from_seq=` | SSE 事件流，支持断点续传 |
| `POST` | `/api/v1/tasks/{id}/cancel` | 取消 |
| `POST` | `/api/v1/tasks/{id}/resume` | 从失败/超时处恢复 |
| `POST` | `/api/v1/approvals/{id}/resolve` | `{action, edited_args?, reason?}` |
| `GET` | `/api/v1/approvals?status=pending` | 待办审批列表（桌面端托盘/通知用） |

SSE 断线重连：客户端携带 `from_seq`，服务端从 Redis Stream（保留 1h）补发，超出保留期则回退到 `GET /tasks/{id}` 全量拉取。

---

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| LangGraph 的中断/恢复语义与我们的审批模型不完全匹配，被框架绑架 | 高 | 在 LangGraph 之上包一层 `TaskEngine` 门面，业务代码只依赖门面；框架若不合用可替换实现而不改上层 |
| Agent 陷入无效循环烧钱 | 高 | 步数/成本/时长三重上限；重复工具调用检测（同 name+args 连续 3 次即中断） |
| 审批打断太频繁，用户嫌烦 | 高 | 「始终允许该 Scope」选项（`irreversible` 除外）；同类操作批量审批（一次确认 5 封邮件） |
| 长任务期间用户关页面导致上下文丢失 | 中 | checkpointer 落库，任务与连接解耦；桌面端/邮件通知完成 |
| 部分成功被描述成完成，损害信任 | 高 | `finalize` 输出结构化 `completed_steps` / `skipped_steps`，UI 强制展示后者 |

---

## 12. 验收标准

1. 任务在 `waiting_approval` 状态下重启后端进程，恢复后可正常继续。
2. 对所有注册工具的自动化断言：非 builtin-read 工具均有 `scope_key`，且调用链必过 `ConsentService`（用 mock 断言调用次数）。
3. `irreversible` 工具在「已授权 + 已选始终允许」的情况下仍触发审批。
4. SSE 断开 30s 后重连，事件无丢失无重复（`seq` 连续）。
5. 单任务成本超 $0.50 时暂停并展示明细。
6. 构造 10 个含失败步骤的任务，结果文案中 100% 明确列出未完成项。

---

## 13. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | Task 模型 + 状态机 + TaskEngine 门面 | 4d |
| M2 | LangGraph 图 + checkpointer + 基础 act 循环 | 5d |
| M3 | 工具抽象层 + builtin 工具 + 权限钩子 | 4d |
| M4 | 审批中断/恢复 + ApprovalRequest | 4d |
| M5 | SSE 事件流 + 断线补发 | 3d |
| M6 | Model Router + LLMClient 抽象 | 3d |
| M7 | 资源治理 + 错误分类 + finalize | 3d |

---

## 14. 待决问题

1. 是否需要「后台任务」形态（用户发起后关闭客户端，完成后通知）？技术上 checkpointer 已支持，主要是通知渠道（邮件/桌面通知）的产品决策。建议 Phase 1 做桌面通知，邮件通知延后。
2. 步数/成本默认阈值需要真实数据校准，当前是估值。上线后按 P90 任务的实际消耗调整。
