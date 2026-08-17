# P0-05 工具集成层（MCP Tool Integration）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付） |
| 对应规划 | `ai_platform_plan.md` §4.3、§7.10 |
| 依赖 | `P0-07 隐私授权与审计`、`P0-03 Agent Runtime` |
| 被依赖 | `P0-04`、`P0-06`、`P1-04` |
| 文档状态 | Draft |

---

## 1. 背景与目标

计划 §7.10：「统一走 MCP 协议，优先支持浏览器可达的 SaaS（Slack、Notion、Gmail、GitHub），Desktop MCP 延后」。

这一层是信任爬坡 L2→L3 的物理载体：L2 是只读连接，L3 是执行类操作。因此它不只是「接 API」，而是**权限分级的执行入口**。

目标：

- **G1** 统一走 MCP，Runtime 侧不为每个 SaaS 写特化代码。
- **G2** 读写能力严格分离——连接 Gmail 只读，绝不隐含发送能力。
- **G3** 凭据安全存储，用户可随时断开并撤销。

非目标：

- 不做自建连接器市场（Phase 3 Agent Marketplace）。
- 不做 Desktop MCP（计划明确延后；桌面能力见 `P0-08`）。
- 不做工具的自动发现与自动安装（Phase 2 再议）。

---

## 2. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| TL-1 | MCP Client 接入层 | 支持 stdio / streamable-http 两种传输，连接生命周期管理 | 断连自动重连，不影响进行中任务 |
| TL-2 | Tool Registry | 把 MCP tools 映射为 `ToolSpec`，注入 scope 与 risk | 见 §4 |
| TL-3 | 连接与凭据管理 | OAuth 授权流、token 加密存储与刷新、断开 | 凭据不落明文，撤销后立即失效 |
| TL-4 | 能力分级 | 每个工具标注 read/write/irreversible 并映射 Scope | 见 §4.2，人工评审表 |
| TL-5 | 首批连接器 | Gmail、Google Calendar、Slack、Notion、GitHub | 只读能力先上，写能力逐个评审后开放 |
| TL-6 | 韧性 | 超时、重试、限流、熔断 | 单连接器故障不影响其他 |
| TL-7 | 审计 | 每次调用落审计日志 | 见 `P0-07` |
| TL-8 | 连接管理 UI | 已连接工具、权限明细、断开、调用记录 | 每个连接可查「它替我做过什么」 |

---

## 3. 架构

```text
Agent Runtime
      │  ToolCall{name, args}
      ▼
┌──────────────────────────────────────────┐
│            Tool Registry                  │  ← 统一 ToolSpec，见 P0-03 §5
│  builtin / mcp / desktop / browser       │
└───────────────┬──────────────────────────┘
                │ provider = mcp
                ▼
┌──────────────────────────────────────────┐
│         MCP Connection Manager            │
│  - 每个 (user, server) 一个逻辑连接        │
│  - 连接池 / 健康检查 / 重连               │
│  - 凭据注入（从 Credential Vault 取）      │
└───────────────┬──────────────────────────┘
                ▼
      ┌─────────┴──────────┐
      ▼                    ▼
 stdio server        streamable-http server
 （自托管连接器）      （远端托管连接器）
```

### 3.1 托管形态决策

| 形态 | 用途 | Phase 1 |
|---|---|---|
| 自托管 stdio 连接器（进程内子进程） | 我们自己实现或封装的连接器 | ✅ 主力 |
| 远端 streamable-http MCP server | 第三方官方提供的 MCP 服务 | ✅ 支持接入，按需 |
| 用户自带 MCP server | 高级用户自定义 | ❌ Phase 2 |

自托管连接器统一放在 `packages/mcp-connectors`，每个连接器是一个独立的 MCP server 实现。

**隔离要求**：stdio 连接器以独立进程运行，`user_id` 通过环境注入，进程不共享用户凭据。连接器进程崩溃只影响该用户该连接。

---

## 4. 能力分级与 Scope 映射（TL-4，核心设计）

这是本模块最重要的部分——它把 MCP 的「一堆 tools」变成「用户能理解的权限」。

### 4.1 分级规则

| risk | 定义 | 授权要求 | 运行时 |
|---|---|---|---|
| `read` | 只读取，不改变外部系统状态 | L2 Scope | 授权后直接执行 |
| `write` | 改变外部状态但可撤销/可修复（建草稿、创建任务、加评论） | L3 Scope | 首次审批，可选「始终允许」 |
| `irreversible` | 对外发送、删除、支付、不可撤销的状态变更 | L3 Scope | **每次强制审批**，无「始终允许」 |

判定原则：**「这个动作出错后，用户能自己收拾干净吗？」** 不能 → `irreversible`。发邮件不可撤销（收件人已看到），删文件不可撤销，发 Slack 消息不可撤销。

### 4.2 首批连接器映射表

| 连接器 | 工具 | risk | Scope |
|---|---|---|---|
| **Gmail** | `search_messages` / `get_message` / `list_threads` | read | `tool:gmail:read` |
| | `create_draft` | write | `tool:gmail:write` |
| | `send_message` / `trash_message` | irreversible | `tool:gmail:send` |
| **Google Calendar** | `list_events` / `get_event` / `find_free_slots` | read | `tool:gcal:read` |
| | `create_event` / `update_event` | write | `tool:gcal:write` |
| | `delete_event` / `send_invites` | irreversible | `tool:gcal:write` |
| **Slack** | `search_messages` / `list_channels` / `get_thread` | read | `tool:slack:read` |
| | `post_message` / `reply_thread` | irreversible | `tool:slack:send` |
| **Notion** | `search` / `get_page` / `query_database` | read | `tool:notion:read` |
| | `create_page` / `update_page` / `append_block` | write | `tool:notion:write` |
| | `delete_block` | irreversible | `tool:notion:write` |
| **GitHub** | `search_code` / `get_issue` / `list_prs` | read | `tool:github:read` |
| | `create_issue` / `comment` | write | `tool:github:write` |
| | `merge_pr` / `close_issue` / `push` | irreversible | `tool:github:write` |

> 注意 Scope 数量少于工具数量：Scope 是**用户能理解的粒度**（「读我的邮件」/「替我发邮件」），不是工具粒度。一个 Scope 覆盖多个同级工具，但 `irreversible` 工具即使共享 Scope 也逐次审批。

### 4.3 分级评审流程（强制）

新增任何工具必须填写并通过评审：

```yaml
- tool: gmail.send_message
  risk: irreversible
  scope: tool:gmail:send
  rationale: "邮件发出后无法撤回，收件人已可见"
  preview_renderer: email
  degraded_behavior: "未授权时，AI 生成邮件草稿文本，用户自行复制发送"
  oauth_scopes: ["https://www.googleapis.com/auth/gmail.send"]
```

`degraded_behavior` 一栏是 `00-conventions.md` §5 的落地点，缺失则评审不通过。

**OAuth scope 最小化**：申请的第三方 OAuth scope 必须与我们的 Scope 一一对应。连接「Gmail 只读」时只申请 `gmail.readonly`，不为了将来方便一次性申请全权限。这条要在代码评审中检查。

---

## 5. 凭据管理（TL-3）

```sql
CREATE TABLE tool_connection (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  provider      text NOT NULL,               -- 'gmail','slack',...
  account_label text NULL,                   -- 'work@company.com'，给用户看
  granted_scopes text[] NOT NULL,            -- 我们的 Scope，非 OAuth scope
  oauth_scopes  text[] NOT NULL,
  status        text NOT NULL CHECK (status IN ('active','expired','revoked','error')),
  last_used_at  timestamptz NULL,
  last_error    jsonb NULL,
  created_at    timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL
);
CREATE UNIQUE INDEX ON tool_connection (user_id, provider, account_label)
  WHERE status <> 'revoked';

CREATE TABLE tool_credential (
  connection_id uuid PRIMARY KEY REFERENCES tool_connection(id) ON DELETE CASCADE,
  ciphertext    bytea NOT NULL,              -- 信封加密后的 token bundle
  dek_wrapped   bytea NOT NULL,              -- 被 KMS 主密钥包裹的数据密钥
  key_version   int NOT NULL,
  expires_at    timestamptz NULL,
  updated_at    timestamptz NOT NULL
);
```

要点：

- **信封加密**：每条凭据一个 DEK，DEK 由 KMS 主密钥包裹。主密钥轮换只需重新包裹 DEK，不必重新加密全部凭据。
- 明文 token **只在内存中存在于单次调用期间**，不写日志、不进 trace、不落 `input_digest`。
- refresh token 失效 → `status=expired`，UI 提示重连，进行中任务转 `permission_denied` 并给出重连引导（走 `P0-04` §4.3 内联授权）。
- 用户断开连接：立即 `revoked` + 物理删除 `tool_credential` 行 + 调用第三方 revoke 端点 + 触发 `P0-07` 的 Scope 撤销流程。

---

## 6. 韧性设计（TL-6）

| 机制 | 参数 | 说明 |
|---|---|---|
| 超时 | 默认 30s，`ToolSpec.timeout_s` 可覆盖 | 超时算一次失败 |
| 重试 | 仅对 `read` 与幂等 `write`；指数退避，最多 2 次 | **`irreversible` 绝不自动重试** |
| 限流 | 每 (user, provider) 令牌桶，默认 10 req/s | 超限排队，不直接失败 |
| 熔断 | 连续 5 次上游 5xx → 该 provider 熔断 60s | 熔断期间该工具从可用集移除并告知 LLM |
| 降级 | 熔断/失败时，Runtime 收到结构化错误，转为向用户说明 | 见 `P0-03` §9 |

**`irreversible` 不自动重试**是硬约束：网络超时后重试可能导致重复发送邮件。做法是超时即失败并明确告知「不确定是否已发送，请你确认」，把不确定性交给用户而不是自作主张。

---

## 7. 接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/tools/providers` | 可连接的工具列表及其 Scope 说明 |
| `POST` | `/api/v1/tools/connections` | 发起连接，返回 OAuth 授权 URL |
| `GET` | `/api/v1/tools/oauth/callback` | OAuth 回调 |
| `GET` | `/api/v1/tools/connections` | 已连接列表（含状态、最近使用、已授 Scope） |
| `PATCH` | `/api/v1/tools/connections/{id}` | 增减 Scope（升级到写权限时重新走 OAuth） |
| `DELETE` | `/api/v1/tools/connections/{id}` | 断开并撤销 |
| `GET` | `/api/v1/tools/connections/{id}/activity` | 该连接的调用记录（供 TL-8） |

---

## 8. 连接管理 UI（TL-8）

每个连接卡片展示：

```text
┌──────────────────────────────────────────────┐
│ ✉ Gmail — work@company.com          ● 已连接 │
├──────────────────────────────────────────────┤
│ 当前权限                                       │
│   ✓ 读取邮件        最近使用：2 小时前          │
│   ○ 创建草稿        [开启]                     │
│   ○ 替我发送邮件    [开启] ⚠ 每次都会先问你     │
├──────────────────────────────────────────────┤
│ 最近替你做过（12 条） ▸                        │
│ [断开连接]                                    │
└──────────────────────────────────────────────┘
```

- 权限是**可分别开关的**，不是一个连接一把梭。
- 「最近替你做过」是审计日志的用户视图——这是让用户敢于开放写权限的关键，比任何隐私条款都有效。
- 断开时明确告知：会撤销令牌、删除凭据；已产生的任务历史保留（用户可另行删除）。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| OAuth 应用审核周期长（Gmail 敏感 scope 需 Google 验证） | 高，可能阻塞 Phase 1 | **立即启动**：Gmail/Calendar 的受限 scope 审核需数周，应在 M1 就提交；审核期间用测试用户白名单（100 人上限）跑早期验证 |
| MCP 生态成熟度不足，第三方 server 质量参差 | 中 | 首批 5 个连接器全部自己实现，不依赖第三方 server；把 MCP 当接口规范用，不当供应链用 |
| 凭据泄露 | 极高 | 信封加密 + KMS；明文不落盘不落日志；渗透测试作为 Phase 1 后期验收项（计划 §7.11） |
| 工具误分级导致不可撤销操作被静默执行 | 极高 | §4.3 强制评审；自动化测试断言所有 `irreversible` 工具在 `always_allow` 下仍触发审批 |
| 上游 API 变更导致连接器批量失效 | 中 | 每个连接器有契约测试（对真实 API 的 smoke test），每日跑一次 |

---

## 10. 验收标准

1. 五个连接器的只读能力全部可用，端到端跑通「连接 → 任务中调用 → 审计可见 → 断开」。
2. 断开连接后，第三方端点 revoke 调用成功，且 `tool_credential` 行物理删除。
3. 自动化测试：所有 `irreversible` 工具在任何配置下都产生 `ApprovalRequest`。
4. 自动化测试：申请的 OAuth scope 集合 ⊆ 已开启 Scope 映射的 OAuth scope 集合（无超额申请）。
5. 单个 provider 熔断时，其他 provider 的任务不受影响。
6. 凭据在应用日志、错误上报、trace 中均无明文出现（用扫描脚本验证）。

---

## 11. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M0 | **提交 Google/Slack OAuth 应用审核**（阻塞项，最先做） | 1d + 等待 |
| M1 | MCP Client 接入层 + Tool Registry + ToolSpec 映射 | 5d |
| M2 | Credential Vault（信封加密）+ OAuth 流程 | 4d |
| M3 | Gmail + Calendar 连接器（只读） | 4d |
| M4 | Slack + Notion + GitHub 连接器（只读） | 5d |
| M5 | 写/不可撤销能力 + 与审批链路联调 | 4d |
| M6 | 韧性（重试/限流/熔断）+ 契约测试 | 3d |
| M7 | 连接管理 UI + 活动记录 | 4d |

---

## 12. 待决问题

1. Gmail 受限 scope 的 Google 审核（含安全评估）成本较高，若周期不可控，Phase 1 是否先用「用户粘贴邮件内容」的降级路径验证需求？建议 M0 立刻提交，同时准备降级路径。
2. Slack 需要用户所在工作区管理员安装应用——个人用户可能没有权限。需在用研中确认目标用户是否具备安装权限，否则 Slack 连接器优先级应下调。
