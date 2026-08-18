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
- **G2** 读写能力严格分离——连接 Gmail 只读，绝不隐含发送能力。这条在本版权重上升：Gmail 的读与发分属不同 Google scope 档位（§2.1.1），分离既是隐私要求也是排期手段。
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
| TL-5 | 首批连接器 | **Gmail + Google Calendar + Notion + GitHub（4 个）**，见 §2.1（决策者 2026-08-18 改定，推翻 B3 / A7，Slack 移出） | 只读能力先上，写能力逐个评审后开放 |
| TL-6 | 韧性 | 超时、重试、限流、熔断 | 单连接器故障不影响其他 |
| TL-7 | 审计 | 每次调用落审计日志 | 见 `P0-07` |
| TL-8 | 连接管理 UI | 已连接工具、权限明细、断开、调用记录 | 每个连接可查「它替我做过什么」 |

### 2.1 首批连接器复核（决策者 2026-08-18 改定）

**首批 = Gmail + Google Calendar + Notion + GitHub（4 个）。**

本结论**推翻了 B3（Gmail 移出）与 A7（Calendar 移出）**，并把原在首批的 Slack 移出。相对上一版（Slack + Notion + GitHub）的逐项变化：

| 连接器 | 上一版 | 本版 | 变化理由 |
|---|---|---|---|
| **Gmail** | ❌ 按 B3 移出 | ✅ **回到首批** | 决策者改定。邮件是 A1 三类高频任务之一（对外文案与邮件起草），上一版把它整个推给桌面端与粘贴降级，代价是 **Web 端用户完全没有邮件能力**——而 Web 是 Phase 1 的主形态 |
| **Google Calendar** | ❌ 按 A7 移出 | ✅ **回到首批** | 决策者改定。与 Gmail 共用同一套 Google OAuth 接入、同一份验证材料、同一个已验证应用，边际成本明显低于独立接一个新平台 |
| **Notion** | ✅ 保留 | ✅ 保留 | 内容与活动运营的文档落脚点；OAuth 门槛低，是本批唯一不依赖外部审核的写入类连接器 |
| **GitHub** | ✅ 保留 | ✅ 保留 | 定位不变，见下方「GitHub 的定位」 |
| **Slack** | ✅ 保留 | ❌ **移出首批** | 转入 §2.2 候选池。连带效果：**B4（工作区管理员安装权限）在 Phase 1 不再成立**，随 Slack 一起推迟到候选池排期时重新评估 |

规划 §7.10 原文是「Slack、Notion、Gmail、GitHub」，因此本版有两处偏离原文：**Slack 移出**（原文有）与 **Calendar 加入**（原文无）。已在 `README.md` 偏离表第 7 条改写登记。

**这个改动的代价高度集中在一处**：Google 应用验证重新成为 Phase 1 的头号排期风险，且比 B3 之前更重——现在有两个连接器同时依赖它。下面单列。

#### 2.1.1 Google OAuth 验证：本版最大的外部依赖

Google 的 scope 分三档，三档的成本差一个量级，**不能笼统当成「都要审核」**：

| 档位 | 审核要求 | 周期 | 费用 | 本批涉及 |
|---|---|---|---|---|
| 非敏感 | 无 | — | 无 | — |
| **sensitive** | 应用验证（表单 + demo 视频 + 域名验证） | 数周 | 免费 | `calendar.readonly`、`calendar.events` |
| **restricted** | 应用验证 **+ 第三方安全评估（CASA）** | 数周到数月 | **付费，且需按年复评** | `gmail.readonly`、`gmail.modify`、`gmail.compose` |

> ⚠️ **本表的 scope 分档必须在 M0 第一周向 Google 官方文档核实一次再据此排期。** Google 的 scope 分级与 CASA 政策历年调整过多次，此处写下的是设计期认知，不是可直接执行的依据。**尤其要核实 `gmail.send` 归 sensitive 还是 restricted**——它直接决定下方降级预案是否成立。

**提交前置条件**（缺一项就无法提交，必须在 M0 之前备齐）：公司实体、公开的隐私政策页、已验证的域名、应用首页、demo 视频。其中**隐私政策页与 `P0-07` §10 的市场边界声明是同一份产出**，合并做，不要重复投入。

**A10 已确认（2026-08-18）：Phase 1 退出条件允许 Gmail 未上线就达成。** 这条结论改变了 CASA 的风险定级——它从**产品级阻塞**降为**功能风险**，下面的降级预案因此不是应急措施，而是一条被认可的终态路径。落实到排期上有三个直接后果：

1. **Gmail 从关键路径上挪下来**。§11 的「M3 按 Calendar + Notion 先做、Gmail 最后做」从建议变成要求。
2. **不为等 CASA 而阻塞任何其他里程碑**。G2 未过就按降级预案继续走，不进入等待状态。
3. **但「退出条件不要求」不等于「用户不需要」**。Gmail 不上线时，Gmail 用户的邮件能力只剩粘贴——因为 `P0-08` 的桌面 MailAdapter 按 B5 只做 Graph API，而 Graph 覆盖的是 M365 用户，与 Gmail 用户**不重叠**。这个暴露面见 `P0-08` §2.1 的触发表。

**必须设的 Go/No-Go 检查点**：CASA 周期不由我们控制，而 Phase 1 只有 3.5 个月（A9）。没有检查点就等于把一个外部不可控项放在关键路径上不管。

| 检查点 | 时间 | 判据 | 未达标时的动作 |
|---|---|---|---|
| **G1** | 立项第 1 周末 | 材料是否已提交 Google | 未提交即视为排期风险已发生，当周上报，不等到月末复核 |
| **G2** | 第 2 个月末 | restricted scope 是否已获批 | 启用下方**降级预案** |

**降级预案（Gmail 只发不读）**：若 CASA 到 G2 仍未通过，Gmail 连接器降级为「只写不读」——只申请起草与发送所需的 scope，放弃读取收件箱。此时：

- **用户侧表现**：AI 能替你起草并发送邮件，但**不能替你读收件箱**。需要读的场景走 `degraded_behavior`（用户粘贴）或桌面 MailAdapter（`P0-08`）。
- **成立前提**是 `gmail.send` 确属 sensitive 档（见上方 ⚠️）。**若它也是 restricted，本预案不成立**，Gmail 必须整体推迟到候选池，届时回退到上一版结论——邮件由桌面 MailAdapter 与粘贴降级独担（即 `P0-08` §2.1 已写好的那套路径，不需要重新设计）。
- 两套 scope 清单要在 **M0 就同时备好**，不要等到 G2 才开始拆。届时只剩一个月，没有拆分的余地。

**Calendar 不受此预案影响**：它只涉及 sensitive scope，走普通应用验证，与 Gmail 的 CASA 解耦。因此 G2 未过时，Calendar 仍可正常上线。

**GitHub 的定位（不变）**：它保留的理由不在目标用户——市场 / 运营确实不用它——而在别处：

> **GitHub 是 §4 能力分级与审批链路的最佳测试载体。** 它是唯一一个三个 risk 等级齐全、都好测、且出错代价低的连接器：`search_code` 是 read，`create_issue` 是 write，`merge_pr` 是 irreversible。用它端到端验证审批链路不需要真实客户数据，出错也收拾得干净——相比之下，用 Gmail 测 irreversible 就是真的把邮件发出去，测试环境很难造得像。
>
> 所以 GitHub 在 Phase 1 承担两个角色：① §4.3 分级评审机制与 §10 验收标准 3（所有 irreversible 工具必然产生审批）的验证载体；② 覆盖技术型种子用户。它**不进入冷启动模板（`P0-04` §4.5）与预置示例 Skill（`P0-06` §5.5）**——那两处严格按 A1 走。

落到实现上：GitHub 连接器优先做「三个 risk 等级各一个代表工具」，不追求工具覆盖面完整。它的 3 人日主要买的是机制验证，不是功能。

#### 2.1.2 邮件能力在 Phase 1 的实际路径（本版变化点）

Gmail 回到首批后，邮件从「桌面端独担」变回「双路径」：

| 路径 | 覆盖 | 依赖 | 本版变化 |
|---|---|---|---|
| **Gmail 连接器**（本文档） | Gmail / Google Workspace 用户，Web + 桌面都可用 | **Google CASA 审核**（外部不可控） | 新增（B3 翻转） |
| **桌面 MailAdapter**（`P0-08`） | **仅 M365 / Outlook.com（Graph API）**——B5 已决只做这一条 | 无外部审核依赖 | 定位调整，见下 |
| 用户粘贴 | 全部 | 无 | 不变，零授权降级路径 |

**B5 已决后，两条路径的关系是「互补」而不是「互为备份」**（`P0-08` §2.1 已同步）：

| | Gmail 连接器 | 桌面 MailAdapter（Graph） |
|---|---|---|
| 覆盖 | Gmail / Google Workspace | Microsoft 365 / Outlook.com |
| 依赖 | **CASA 审核** | 无 |
| 能否互相兜底 | **不能** | **不能**——两者覆盖的用户群不重叠 |

这一点容易被误读，所以写明：桌面端曾经是 CASA 的对冲（Outlook COM / Mail.app 能操作本机配置的任意账户，包括 Gmail），但 B5 决定只做 Graph 之后**这个对冲消失了**。剩下的暴露面是「CASA 未过 × Gmail 用户 = 只剩粘贴」，已由 A10 显式接受，并在 `P0-08` §2.1 配了触发式补做（G2 未过 + 实验显示 Gmail 占比高 → 补 Outlook COM，3d）。

#### 2.1.3 工程量变化

| 项 | 上一版 | 本版 | 差 |
|---|---|---|---|
| M0 Google 审核材料准备与对接 | 0（已取消） | **3d** | +3d |
| M3 只读连接器 | 4d（Slack + Notion） | **6d**（Gmail + Calendar + Notion） | +2d |
| M4 GitHub | 3d | 3d | — |
| **P0-05 合计** | 27 人日 | **约 32 人日** | **+5d** |

M0 的 3d 是**我们这边的人日**（材料准备、隐私政策页对接、demo 视频、验证问答往返、CASA 整改配合），不含 Google 侧的等待周期——等待不占人日，但占日历时间，这正是需要 G1/G2 检查点的原因。

⚠️ **这 +5d 落在一个没有余量的排期上**：`README.md` 排期前提原本是「需求 303 人日 / 有效容量 304 人日 / 余量 1 人日」。加上本次 +5d 变成缺口 4 人日。

> **但同日的 B5 决策（`P0-08` MailAdapter 只做 Graph）省了 6d**，两者相抵后总需求为 **约 302 人日**，乐观假设下恢复约 2 人日余量，保守假设（25%）下仍缺约 17 人日。A10 已确认不砍范围、靠 A9.1 的触发式预案兜底。**这不是「问题解决了」——2 人日的余量与零余量没有实质区别**，第 3 周末的容量复核仍是硬要求。

### 2.2 后续连接器候选池（Phase 1 不排期）

首批四个已定，本节是**下一个连接器的候选池**，按「对 A1 三类高频任务的贡献 × 落地门槛」排。其中**落地门槛的第一变量是 OAuth 审核等级**，不是 API 复杂度：

| 候选 | 贡献的任务 | OAuth 审核门槛 | 工程量 | 评级 |
|---|---|---|---|---|
| **HubSpot** | 数据整理（漏斗 / 渠道线索）、报告 | 低——开发者应用自助，无人工审核 | 3d | **★★★★★** |
| **Mailchimp / Klaviyo** | 对外文案（直接落成 campaign 草稿） | 低 | 3d | **★★★★★** |
| **Google Sheets + Drive** | 数据整理（替代手动上传文件） | **低—中**，见下方说明 2 | 3d | **★★★★★**（本版升级） |
| **Slack**（本版从首批移出后落到这里） | 协同（结论分发、频道内检索） | 低（OAuth 自助），但**受 B4 制约**——需工作区管理员安装 | 3d | ★★★★ |
| **Airtable** | 数据整理、内容排期 | 低 | 2d | ★★★★ |
| **GA4（Data API）** | 数据整理（流量与转化） | sensitive，**且可复用已验证应用**（说明 2） | 3d | ★★★★（本版升级） |
| Google Docs | 对外文案 | 同上 | 2d | ★★★（本版升级） |
| Meta Ads / Google Ads | 数据整理（投放） | **高**——Meta 需 App Review + 商业验证；Google Ads 需 developer token 审批 | 8d+ | ★★（Phase 2） |
| Buffer / Later、Webflow / WordPress | 内容分发 | 低到中 | 3–5d | ★★（Phase 2） |
| Asana / Trello / Linear | 无（对三类任务贡献低） | 低 | — | ★ |
| **LinkedIn** | 对外文案（B2B 主场） | **不可行**——发布类 API 需 Marketing Developer Platform 审批，小公司基本拿不到 | — | ✗ |
| X / Twitter | 内容分发 | API 已收费且昂贵 | — | ✗ |

三条关键说明：

1. **Slack 的降级不是「它不重要」。** 它移出首批是本次改定的连带结果（首批已有 4 个，再加就超容量），不是评估分下降。它排在候选池第 4 位而非更靠前，唯一原因是 **B4 的管理员安装权限**——`P0-07` §11 前置实验会问「你有权在你们公司的 Slack 里安装应用吗」，有权限者比例决定它在候选池里的真实位置。这题在实验问卷中**必须保留**（`P0-open-questions.md` §3）。

2. **Google 系候选的门槛因本次改定而整体下降，这是新增的连带收益。** Gmail + Calendar 进首批意味着 Phase 1 必然要完成一次 Google 应用验证并维护一个已验证应用。此后再加 `analytics.readonly`、`spreadsheets.readonly`、`documents.readonly` 这类 *sensitive* scope，是**在已验证应用上增量申请**，比首次验证轻得多（仍需对新增 scope 走验证流程，但公司实体、域名、隐私政策页、demo 视频这些一次性材料已经就位）。因此本表把 Sheets / GA4 / Docs 的评级各上调一档。
   更关键的是 **`drive.file` 属于非敏感 scope**：它只能访问用户通过 Google Picker 明确选中的文件，因此「Google Sheets + Drive」可以设计成 **Picker 选文件 + `drive.file` + Sheets 读取**，完全绕开审核。若要做 Google 系，优先走这条。
   ⚠️ 但这条收益**以 §2.1.1 的 CASA 通过为前提**。若 G2 检查点未过、Gmail 走了降级预案，「已验证应用」这个资产是否成立取决于当时实际拿到了哪些 scope，本条需重新评估。

3. **每个候选都必须能填出非空的 `degraded_behavior`**（`00-conventions.md` §5 硬约束）。HubSpot →「导出 CSV 给我」；Mailchimp →「我生成正文，你粘贴到 Mailchimp」；Sheets →「下载后上传给我」；Slack →「把消息粘贴给我 / 我生成内容你自己发」。填不出来的候选直接淘汰，不进候选池。

**本节的建议是：Phase 1 不再加第五个连接器。**

理由比上一版更强了。一是容量——首批从 3 个变 4 个已经让 P0-05 增加 5 人日，把本就为零的排期余量吃成了缺口（§2.1.3、`P0-open-questions.md` A10），此时再加连接器是反向操作。二是**该决定它的数据两周后就有了**：`P0-07` §11 的前置实验会问 8–10 个真实用户「你平时的活主要在哪几个工具里干」（也是 `P0-01` §5.1.1 题库的 `tools` 项）。在那之前任何选择都是猜测，猜错一个连接器的代价是 3–4 人日加一次返工。

做法：本表按用户实际提及频次排序后，作为 Phase 1 后期余力或 Phase 2 的第一批输入。若实验显示提及最多的是投放平台（Meta / Google Ads），那么正确结论可能是「不做那个连接器，用文件上传覆盖」——高审核门槛的 API 不值得为验证期的产品啃下来。

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

首批四个连接器（§2.1）的完整映射：

| 连接器 | 工具 | risk | Scope | Google 档位 |
|---|---|---|---|---|
| **Gmail** | `search_messages` / `get_message` / `list_threads` | read | `tool:gmail:read` | **restricted**（CASA） |
| | `create_draft` | write | `tool:gmail:write` | **restricted**（`gmail.compose`） |
| | `send_message` / `trash_message` | irreversible | `tool:gmail:send` | 待核实，见 §2.1.1 ⚠️ |
| **Google Calendar** | `list_events` / `get_event` / `find_free_slots` | read | `tool:gcal:read` | sensitive |
| | `create_event` / `update_event` | write | `tool:gcal:write` | sensitive |
| | `delete_event` / `send_invites` | irreversible | `tool:gcal:write` | sensitive |
| **Notion** | `search` / `get_page` / `query_database` | read | `tool:notion:read` | — |
| | `create_page` / `update_page` / `append_block` | write | `tool:notion:write` | — |
| | `delete_block` | irreversible | `tool:notion:write` | — |
| **GitHub** | `search_code` / `get_issue` / `list_prs` | read | `tool:github:read` | — |
| | `create_issue` / `comment` | write | `tool:github:write` | — |
| | `merge_pr` / `close_issue` / `push` | irreversible | `tool:github:write` | — |

> 注意 Scope 数量少于工具数量：Scope 是**用户能理解的粒度**（「读我的邮件」/「替我发邮件」），不是工具粒度。一个 Scope 覆盖多个同级工具，但 `irreversible` 工具即使共享 Scope 也逐次审批。

**「Google 档位」列是本版新增，它不是注释而是排期依据。** 它让一件事在表上直接可见：`tool:gmail:read` 与 `tool:gmail:write` 都压在 CASA 上，而 `tool:gcal:*` 不压。§2.1.1 的降级预案能成立，正是因为这张表里 Gmail 的三行分属不同档位——**保持读写分离（§1 G2）在本版不只是隐私要求，也是排期手段**：读写不分离的话，一个 CASA 卡住会连带整个 Google 侧全部不可用。

**已移出首批的连接器**（分级结论保留，不裁剪）：

| 连接器 | 工具 | risk | Scope |
|---|---|---|---|
| ~~**Slack**~~（本版移出，转入 §2.2 候选池） | `search_messages` / `list_channels` / `get_thread` | read | `tool:slack:read` |
| | `post_message` / `reply_thread` | irreversible | `tool:slack:send` |

保留而不删除的理由：分级结论本身有复用价值，Slack 在候选池中排第 4（§2.2），上线时可直接沿用这两行，不需要重走 §4.3 评审。**但 `config/scopes.yaml` 中不得注册未上线连接器的 Scope**——注册表是运行时的单一事实来源（`P0-07` §3），里面出现一个没有实现的 Scope，等于给用户展示一个点不开的授权项。

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
| **Google restricted scope 的 CASA 评估周期不可控** | **极高——本版头号排期风险**。它是外部依赖，我们无法通过加人或加班压缩 | ①**立项第 1 周即提交**（§2.1.1 G1）；② 第 2 个月末 G2 检查点；③ 未过则启用「Gmail 只发不读」降级预案；④ 预案的两套 scope 清单在 M0 同时备好。**这是 B3 当初拒掉 Gmail 的理由，本版改定后它原样回来了，且因两个 Google 连接器同时依赖而更重** |
| CASA 需按年复评，且需付费 | 中——影响的是 Phase 1 之后 | 立项时就把年度复评列入运维事项与预算，不要当成一次性投入。此项需与法务/财务确认（与 `P0-07` B1 的法务确认合并做） |
| `gmail.send` 的档位判断若有误，降级预案整体失效 | 高 | §2.1.1 已标注必须在 M0 第一周向 Google 官方文档核实。**核实结果要回写本文档**，不要只留在个人笔记里。若确为 restricted，Gmail 整体推迟到候选池，邮件回退为桌面端独担（`P0-08` §2.1 那套路径无需重新设计） |
| ~~Slack 需工作区管理员安装，个人用户无权限（B4）~~ | ~~中高~~ | **本版不再适用**：Slack 已移出首批（§2.1）。B4 随之推迟到候选池排期时重新评估，但 `P0-07` §11 前置实验中的对应问题**仍需保留**——它是候选池排序的输入 |
| MCP 生态成熟度不足，第三方 server 质量参差 | 中 | 首批连接器全部自己实现，不依赖第三方 server；把 MCP 当接口规范用，不当供应链用 |
| 凭据泄露 | 极高 | 信封加密 + KMS；明文不落盘不落日志；渗透测试作为 Phase 1 后期验收项（计划 §7.11） |
| 工具误分级导致不可撤销操作被静默执行 | 极高 | §4.3 强制评审；自动化测试断言所有 `irreversible` 工具在 `always_allow` 下仍触发审批 |
| 上游 API 变更导致连接器批量失效 | 中 | 每个连接器有契约测试（对真实 API 的 smoke test），每日跑一次 |

---

## 10. 验收标准

1. §2.1 确定的全部首批连接器（**4 个：Gmail / Google Calendar / Notion / GitHub**）只读能力可用，各自端到端跑通「连接 → 任务中调用 → 审计可见 → 断开」。
   - **若 §2.1.1 的 G2 检查点触发降级预案**，Gmail 的验收改为「起草与发送可用，读取不可用且在 UI 中明示原因」，其余三个不变。这条不是放宽标准，是把预案的验收口径提前写死，避免届时临时商量。
2. 断开连接后，第三方端点 revoke 调用成功，且 `tool_credential` 行物理删除。
3. 自动化测试：所有 `irreversible` 工具在任何配置下都产生 `ApprovalRequest`。
4. 自动化测试：申请的 OAuth scope 集合 ⊆ 已开启 Scope 映射的 OAuth scope 集合（无超额申请）。
5. 单个 provider 熔断时，其他 provider 的任务不受影响。
6. 凭据在应用日志、错误上报、trace 中均无明文出现（用扫描脚本验证）。

---

## 11. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| **M0** | **提交 Google 应用验证 + CASA**（材料准备、隐私政策页、demo 视频、域名验证、验证问答往返、整改配合）。**必须在立项第 1 周完成提交**，见 §2.1.1 G1 | **3d + 不可控等待** |
| M1 | MCP Client 接入层 + Tool Registry + ToolSpec 映射 | 5d |
| M2 | Credential Vault（信封加密）+ OAuth 流程 | 4d |
| M3 | Gmail + Google Calendar + Notion 连接器（只读） | **6d** |
| M4 | GitHub 连接器（read / write / irreversible 各一个代表工具，作为审批链路验证载体） | 3d |
| M5 | 写/不可撤销能力 + 与审批链路联调 | 4d |
| M6 | 韧性（重试/限流/熔断）+ 契约测试 | 3d |
| M7 | 连接管理 UI + 活动记录 | 4d |
| — | **合计** | **约 32 人日**（上一版 27，差额见 §2.1.3） |

**M0 与其他里程碑的关系需要特别说明**：M0 的 3 人日很小，但它是唯一一个**其产出时间不由我们决定**的里程碑。因此排期上 M0 不占用关键路径的人力，却定义了关键路径的形状——M1–M2 可以在等待期并行推进（它们不依赖 Google 审核结果），M3 的 Gmail 部分则必须等 G2 有结论。**M3 要按「Calendar + Notion 先做，Gmail 最后做」的顺序拆**，这样 G2 若触发降级预案，受影响的只是 M3 的尾部而不是整个里程碑。

---

## 12. 待决问题

1. ~~首批连接器最终清单~~ → **已决（决策者 2026-08-18 改定）**：**Gmail + Google Calendar + Notion + GitHub**。推翻 B3（Gmail 移出）与 A7（Calendar 移出），Slack 移出首批转入 §2.2 候选池。详见 §2.1。
2. ~~Gmail 受限 scope 的 Google 审核成本~~ → **不再是「是否要做」的问题，而是「怎么控风险」的问题**。方案已写入 §2.1.1（三档 scope、G1/G2 检查点、只发不读降级预案）。**但其中两项仍需确认，见下方 3、4。**
3. **`gmail.send` 属 sensitive 还是 restricted？** —— 决定 §2.1.1 降级预案是否成立，是本文档当前最关键的未核实事实。**需在 M0 第一周向 Google 官方文档核实并回写本节。** 需要谁定：工程负责人（核实即可，不需要决策）。
4. **CASA 的费用与年度复评成本** → **处理方式已定（B3-新 ②，2026-08-18 采纳建议）**：与 `P0-07` B1 的法务确认**合并为同一个前置事项**推进，由同一负责人对接——两件事都指向「公司实体 + 隐私政策页 + 美国市场合规」这套材料，分开做会重复两遍。
   ⚠️ **但「合并处理」定的是流程，不是结果**：预算是否实际批准、年度复评成本是多少，仍需回填。**年度复评容易被漏**——它不是一次性投入而是持续运维成本，要进的是长期预算不是项目预算。
5. ~~Slack 的工作区管理员安装权限（B4）~~ → **本版不再阻塞 Phase 1**（Slack 已移出首批）。但 `P0-07` §11 前置实验中的对应问题要保留，用作 §2.2 候选池的排序输入。
6. ~~P0-05 增加的 5 人日如何吸收？~~ → **已决（A10，2026-08-18）**：**不砍范围**，靠 A9.1 的触发式预案兜底；同日 B5 省的 6d 已把这 5d 基本抵掉（见 §2.1.3）。**且退出条件已确认不要求 Gmail 上线**，CASA 从产品级阻塞降为功能风险。
