# P0-07 隐私授权与审计（Consent & Audit）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须完整落地，★★★★★） |
| 对应规划 | `ai_platform_plan.md` §2.1、§5、§7.11、§9 |
| 依赖 | 无（是其他模块的底座） |
| 被依赖 | `P0-02`、`P0-03`、`P0-05`、`P0-08`、`P1-01`、`P1-04` |
| 文档状态 | Draft |

---

## 1. 背景与目标

计划 §9 把这一项列为 ★★★★★：「决定产品能否起步的前提，Phase 1 即需完整落地」。

采用的是简化模型（§2.1）：**默认关闭 → 员工个人自行开启 → 开启前明确说明并认可 → 随时可关闭/查看/删除**。不采用面向欧盟的三层企业合规模型。

**目标市场已确认（A2）：海外英语市场，Phase 1 以美国为主，明确不面向中国大陆与欧盟。** 这一条直接决定本文成立：规划 §2.1 的隐私模型正是建立在这个前提上的，因此本文**无需按 PIPL 重做**，也不产生设计偏离。边界的产品内明示见 §10。

同时，计划 §2.1 明确要求把「自愿性」写成**设计评审的检查项而非文档声明**——本文 §8 给出可执行的机制。

目标：

- **G1** 任何数据采集与副作用操作，都有一条可追溯的授权记录支撑，无旁路。
- **G2** 用户随时能回答三个问题：**你在收集什么 / 你替我做过什么 / 我怎么撤销和删除**。
- **G3** 「不开启也能用」是可验证的产品约束，不是承诺。

非目标（且需明确标注边界，见 §10）：

- 不做 GDPR 的完整合规实现（产品不面向欧盟）。
- 不做企业管理员代员工开启的能力（这会直接破坏本模型的「自愿」前提）。
- 不做 DPIA、DPO 流程等企业合规工件。

---

## 2. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| CS-1 | Scope 注册表 | 集中定义全部 Scope 及其元数据 | 见 `00-conventions.md` §3 |
| CS-2 | Consent 记录 | 不可变的授权/撤销记录 | append-only，可重放出任意时刻的授权态 |
| CS-3 | 授权说明卡片 | 开启前展示：收集什么/为什么/存哪/多久/怎么删 | 每个 Scope 必备，非通用模板 |
| CS-4 | 运行时检查 SDK | `ConsentService.check()`，供 Runtime/Desktop 调用 | 无旁路，测试守护 |
| CS-5 | 审计日志 | 谁在何时开启了什么、执行了什么 | 见 §5 |
| CS-6 | 隐私中心 | 授权总览、活动记录、数据查看/导出/删除 | 三次点击内可关闭任意授权 |
| CS-7 | 自愿性评审机制 | PR 检查项 + 自动化守护 | 见 §8 |
| CS-8 | 前置用户实验 | 5–10 名真实用户验证开启意愿 | 计划 §2.1 明确要求，Phase 1 前置 |
| CS-9 | 数据保留与删除 | 保留期策略、删除的物理执行、备份失效 | 见 §7 |

---

## 3. Scope 注册表（CS-1）

单一事实来源：`config/scopes.yaml`，编译期加载为常量，运行时不可动态新增。

```yaml
- key: tool:gmail:read
  display_name: 读取你的邮件
  category: tool
  trust_level: L2
  risk: read
  collects: |
    我会按你每次任务的需要搜索并读取邮件内容。
    邮件正文只在处理这次任务时使用，不会长期保存。
  retention: 不保存邮件正文；只保存"在什么时间搜索了什么关键词"的操作记录，保留 90 天
  degraded_behavior: 你可以把需要处理的邮件内容直接粘贴给我
  revocable: true
  third_party_scopes: ["https://www.googleapis.com/auth/gmail.readonly"]

- key: tool:gmail:send
  display_name: 替你发送邮件
  category: tool
  trust_level: L3
  risk: irreversible
  collects: |
    你每次确认后，我会用你的邮箱把这封邮件发出去。
    每一封都会单独问你，不提供"以后不用再问"的选项。
  retention: 记录"什么时间发给了谁、主题是什么"，不保存正文，保留 90 天
  degraded_behavior: 我把邮件草稿写好给你，你自己复制到邮箱里发送
  revocable: true
  third_party_scopes: ["https://www.googleapis.com/auth/gmail.send"]

- key: desktop:excel:automate
  display_name: 替你操作 Excel
  category: desktop
  trust_level: L3
  risk: write
  collects: |
    我会读取当前 Excel 文件的内容和界面结构，并按你的要求修改表格。
    我不会截取整个屏幕，也不会记录你的键盘输入。
  retention: 操作记录（做了什么动作、改了哪些单元格）保留 30 天，用于你事后核对
  degraded_behavior: 你可以上传 Excel 文件，我处理完给你新文件
  revocable: true
  requires_os_permission: ["macos.accessibility", "windows.uia"]

- key: llm:custom:route
  display_name: 把任务内容发到你自己配置的模型服务
  category: llm
  trust_level: L3
  risk: write
  collects: |
    你开启后，任务内容（包括你上传的文件内容、你的画像与被检索到的记忆）
    会发送到你自己填写的那个服务地址。我们不控制那个地址，也无法保证它如何处理这些内容。
  retention: 我们只记录"某次任务用了哪个自定义服务、哪个模型名"，不记录发送的内容
  degraded_behavior: 不开启时使用平台默认模型，全部功能正常可用
  revocable: true
```

这两个 Gmail Scope 放在一起是**刻意的示范**：同一个连接器的读与发分属 L2 / L3、read / irreversible，`tool:gmail:send` 因 `risk: irreversible` **永远逐次审批**（硬约束 4），即使用户选了「始终允许」也不例外。它同时也是 `P0-05` §1 G2「读写严格分离」的落地样例——连接邮箱只读，绝不隐含发送能力。

> **本示例在 2026-08-18 换过一次。** 原本用 `tool:gmail:read` 作 L2 样例，B3 决定 Gmail 移出首批后改为 `tool:slack:read`，改定后又换回 Gmail。`tool:slack:read` 的定义本身没问题，Slack 排期时可直接沿用（`P0-05` §4.2 已保留），但**它不能留在本节**——本节是 `config/scopes.yaml` 的示例，而注册表是运行时的单一事实来源，出现一个没有实现的连接器的 Scope，等于给用户展示一个点不开的授权项。

`llm:custom:route` 是 A6（支持 custom provider）要求的新 Scope。它必须存在的理由：把用户数据发到一个**我们不控制的第三方端点**，是一次实质的数据外发，按硬约束「每个能力必须有 Scope」不能靠「用户自己填的所以不用问」绕过。设计要点见 `P0-03` §7.1。

字段 `collects` / `retention` / `degraded_behavior` 三项是**给用户看的自然语言**，由产品撰写并作为发版检查项，不允许用技术黑话或留空。

**语言（A8 已确认）**：交付文案为 **en-US**，本文示例用中文书写以便评审。这三段文案**必须过英文母语审校**，且这不是润色要求——§6.1 的四段式授权卡片是整个隐私模型的承重结构，用户是读完它才点同意的。一段翻译腔的英文说明会让「明确说明后认可」这件事在事实层面打折，而这正是 §10 边界第 1 条所依赖的前提。已列入 §13 验收 3。

---

## 4. Consent 数据模型（CS-2）

授权记录 **append-only**——撤销不是删除记录，而是追加一条 `revoked`。这样任意历史时刻的授权状态都可重放，是审计可信的基础。

```sql
CREATE TABLE consent_record (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  scope_key     text NOT NULL,
  action        text NOT NULL CHECK (action IN ('granted','revoked','expired')),
  always_allow  boolean NOT NULL DEFAULT false,  -- 是否免逐次审批
  surface       text NOT NULL,                   -- web/desktop
  consent_text_version text NOT NULL,            -- 用户当时看到的说明文案版本
  device_info   jsonb NULL,                      -- 桌面端记录设备标识
  ip_hash       text NULL,                       -- 哈希存储，不存原始 IP
  created_at    timestamptz NOT NULL
);
CREATE INDEX ON consent_record (user_id, scope_key, created_at DESC);

-- 当前状态的物化视图，供运行时高频查询
CREATE MATERIALIZED VIEW consent_current AS
SELECT DISTINCT ON (user_id, scope_key)
  user_id, scope_key, action, always_allow, created_at
FROM consent_record
ORDER BY user_id, scope_key, created_at DESC;
```

> `consent_text_version` 很重要：文案改版后，能证明用户当初同意的是哪一版说明。这是「明确说明后认可」这个模型的可验证性所在。文案变更时，涉及采集范围扩大的必须重新征求同意（见 §6.3）。

运行时状态从 Redis 读（`consent:{user_id}` hash，写时失效），未命中回落 `consent_current`。

---

## 5. 审计日志（CS-5）

两类日志，分表存储，用途不同：

### 5.1 授权变更日志

即 `consent_record` 本身，回答「谁在什么时间开启了什么」——这正是计划 §2.1 所说的「产品只负责提供可审计记录」。

### 5.2 执行审计日志

```sql
CREATE TABLE execution_audit (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  task_id       uuid NULL,
  step_id       uuid NULL,
  scope_key     text NULL,
  surface       text NOT NULL,
  action        text NOT NULL,              -- 'slack.post_message'
  target_digest jsonb NULL,                 -- 脱敏摘要：{"to_count":3,"subject_hash":"..."}
  result        text NOT NULL CHECK (result IN ('allowed','denied','approved','rejected','failed')),
  approval_id   uuid NULL,
  error_code    text NULL,
  duration_ms   int NULL,
  created_at    timestamptz NOT NULL
) PARTITION BY RANGE (created_at);
```

**脱敏原则**：审计日志记录「做了什么」，不记录「内容是什么」。收件人存数量与哈希，不存地址；邮件主题存哈希，不存明文。理由：审计日志本身若含敏感内容，就成了新的泄露面。用户要看具体内容时，去看任务对话记录（那是他自己的数据，且可删）。

按月分区，保留 12 个月，到期自动 drop 分区。

---

## 6. 关键流程

### 6.1 授权流程（CS-3）

授权说明卡片的强制结构（四段，缺一不可）：

```text
┌───────────────────────────────────────────────┐
│ 替你操作 Excel                                  │
├───────────────────────────────────────────────┤
│ 会做什么                                        │
│   读取当前 Excel 文件的内容和界面结构，          │
│   按你的要求修改表格                            │
│                                               │
│ 不会做什么                                      │
│   不截取整个屏幕 · 不记录键盘输入 ·              │
│   不操作 Excel 以外的应用                       │
│                                               │
│ 会留下什么                                      │
│   做了哪些动作、改了哪些单元格，保留 30 天       │
│   （方便你事后核对，随时可删）                   │
│                                               │
│ 不开启也可以                                    │
│   你可以上传 Excel 文件，我处理完给你新文件      │
├───────────────────────────────────────────────┤
│            [开启]      [先不用]                 │
└───────────────────────────────────────────────┘
```

设计约束：

1. **「不会做什么」是必填段**——只说会做什么的说明，用户无法判断边界。
2. **「不开启也可以」必须给出真实可用的替代路径**，且是这张卡片的固定组成部分。这是自愿性在界面上的体现。
3. 两个按钮**视觉权重相同**，「先不用」不做成灰色小字。
4. 不使用「获得完整体验」「解锁更多能力」这类诱导表述。

### 6.2 运行时检查（CS-4）

```python
class ConsentDecision(Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"

class ConsentService:
    def check(self, user_id: UUID, scope_key: str | None, risk: Risk) -> ConsentDecision:
        if scope_key is None:
            return ALLOW                      # builtin 只读工具
        state = self._current(user_id, scope_key)
        if state is None or state.action != "granted":
            return DENY
        if risk == Risk.IRREVERSIBLE:
            return REQUIRE_APPROVAL           # 已授权也逐次审批，无例外
        if not state.always_allow:
            return REQUIRE_APPROVAL
        return ALLOW
```

**无旁路保证**：检查点唯一地放在 `P0-03` §5 的工具调用链上，各 Executor 内部不做也不能做权限判断。测试守护见 §8.2。

### 6.3 撤销与文案变更

撤销：

```text
用户点关闭
   │
   ▼ 追加 consent_record(action=revoked)
   ▼ 失效 Redis 缓存
   ▼ 询问："要一起删除已产生的记录吗？"（**默认不删，让用户选** — B2 已确认）
   │     选删 → MemoryService.purge_by_scope() + execution_audit 标记删除
   ▼ 若有第三方连接，调用 revoke 端点 + 删除凭据（见 P0-05 §5）
   ▼ 进行中的任务在下次该 Scope 调用时收到 DENY，转为向用户说明
```

文案变更：`scopes.yaml` 中 `collects` / `retention` 的变更若**扩大了采集范围**，必须 bump `consent_text_version` 并将存量用户的该 Scope 状态置为 `expired`，下次使用时重新征求同意。仅措辞优化不需重新征求。这个判定作为发版检查项，由人工评审确认。

---

## 7. 数据保留与删除（CS-9）

| 数据 | 保留期 | 删除方式 |
|---|---|---|
| 任务对话与产物 | 用户自行管理，默认永久 | 用户删除即物理删除 |
| Memory | 用户自行管理 | 物理删除（见 `P0-02`） |
| `execution_audit` | 12 个月 | 分区自动 drop |
| `consent_record` | **永久** | 不删除（是授权的证据链） |
| 第三方凭据 | 随连接生命周期 | 断开即物理删除 |
| 结构化操作日志（Phase 2） | 默认 90 天，用户可调 | 见 `P1-01` |
| 后端应用日志 | 30 天 | 自动过期；**禁止记录用户内容** |

**账号删除**：用户删除账号时，除 `consent_record` 外全部物理删除；`consent_record` 匿名化（`user_id` 替换为不可逆哈希）后保留。承诺 72 小时内完成，含备份失效。

`consent_record` 保留的理由要对用户讲清楚：这是「你什么时候同意过什么」的记录，保留它是为了在任何争议中都能证明我们没有超范围采集，它不含你的工作内容。

---

## 8. 自愿性保障机制（CS-7，本文核心）

计划 §2.1 原文：「这一点要写进设计评审的检查项，而不只是写进文档」。下面是可执行的三层机制。

### 8.1 PR 模板检查项（人工）

见 `00-conventions.md` §5 的表格，作为 `.github/pull_request_template.md` 的一节。任何触及 `scopes.yaml` 或新增 `ToolSpec` 的 PR 必须填写，评审人逐项勾选。

### 8.2 自动化守护（CI，不依赖人的自觉）

| 检查 | 实现 | 失败即阻塞合并 |
|---|---|---|
| Scope 元数据完整性 | 校验 `scopes.yaml` 每个条目的 6 个必填字段非空 | ✅ |
| `degraded_behavior` 非空且非占位符 | 正则排除 `TODO`/`N/A`/`无` | ✅ |
| ToolSpec 必须有 Scope | 遍历注册表，非 builtin-read 工具断言 `scope_key` 非空 | ✅ |
| 权限检查无旁路 | 对每个 Executor 的集成测试：mock `ConsentService` 返回 `DENY`，断言无任何上游调用发生 | ✅ |
| `irreversible` 强制审批 | 参数化测试遍历所有 `irreversible` 工具，断言在 `always_allow=true` 下仍产生 `ApprovalRequest` | ✅ |
| OAuth scope 不超额 | 断言申请的第三方 scope ⊆ 已开启 Scope 映射集合 | ✅ |
| 文案无诱导词 | 对 `scopes.yaml` 与授权 UI 文案做禁用词扫描（"完整体验""解锁""才能""必须开启"） | ⚠ 告警 |

### 8.3 核心路径无授权测试（E2E，最关键的一条）

一个专门的 E2E 测试套件，用**零授权账号**跑通核心路径：

```text
注册 → 跳过全部访谈 → 上传 xlsx → 发起"整理成周报" → 拿到产物 → 下载
```

断言：全程 `consent_record` 表为空，任务成功完成。

**这条测试如果挂了，就是产品违背了自愿性承诺**，等同于 P0 缺陷。它是 §2.1「不开启也能正常用」从声明变成约束的唯一可靠手段。

---

## 9. 隐私中心 UI（CS-6）

```text
隐私与授权
├── 授权总览
│     按信任层分组，每项：状态 · 开启时间 · 最近使用 · [查看说明] [关闭]
│     顶部一个显眼的「全部关闭」
├── 活动记录
│     时间线："8/14 15:02 · 替你发送了 3 封邮件 · [查看任务]"
│     可按 Scope / 时间 / 结果筛选
├── 我的数据
│     记忆 N 条 [管理] · 任务 N 个 [管理] · 上传文件 N 个 [管理]
│     [导出全部数据]  [删除全部数据]
└── 账号
      [删除账号与全部数据]
```

要点：

- 「活动记录」用**自然语言**描述，不是日志表格。用户要能一眼看懂 AI 替他做了什么。
- 每条活动可跳转到对应任务，形成闭环追溯。
- 「关闭」路径不超过三次点击，且关闭时不做挽留式弹窗（挽留即诱导）。

---

## 10. 模型适用边界（必须在产品内明示）

计划 §2.1 明确要求写清边界。以下三条要落到**产品内的隐私说明页**，不只在内部文档：

1. **本模型适用于个人自愿开启场景。** 不支持企业管理员代员工开启——产品不提供该能力，这是设计约束不是暂未实现。
2. **市场边界（A2 已确认）。** Phase 1 目标市场为**海外英语市场，以美国为主**；**明确不面向中国大陆与欧盟**。理由不是市场偏好而是合规结构不同：PIPL 对员工个人信息（尤其敏感信息）有独立于「同意」之外的企业合规义务，GDPR 亦然，二者都不能靠「用户自己点了同意」来满足。进入这两个地区必须重新评估本文全文，不可直接套用。<br>落地要求：① 隐私说明页写明服务面向的地区；② **地域开放列为决策检查项**，任何「要不要放开某地区注册」的讨论必须回到本节；③ 若发现欧盟 / 中国大陆用户已实际注册，作为合规事件处理并评估，而不是默默继续服务。
3. **企业采购场景。** 即使功能是员工自行开启，企业作为部署方仍可能对第三方（如客户数据涉及的隐私）承担说明义务。产品只提供「哪些人在什么时间开启了什么采集范围」的可审计记录（即 §5.1），**不代替企业做合规判断**，也不提供合规结论。

---

## 11. 前置用户实验（CS-8）

计划 §2.1：「找 5-10 个真实目标用户，展示采集范围和用途说明，看他们是否愿意主动开启。这是 Phase 1 必须跑的前置小实验。」

设计：

| 项 | 内容 |
|---|---|
| 样本 | 8–10 人，**市场 / 运营岗（A1），来自海外英语市场（A2）**，非熟人 |
| 材料 | 真实的授权卡片原型（§6.1 四段式），覆盖 4 个代表性 Scope：`tool:gmail:read`（L2 / read）、**`tool:gmail:send`（L3 / irreversible）**、`desktop:excel:automate`（L3 / write）、`telemetry:*:collect`（L4）<br>※ 样本 Scope 于 2026-08-18 随连接器改定换回 Gmail（此前因 B3 临时改用 Slack，Slack 已移出首批）。**本版新增 `tool:gmail:send`**——它是唯一能测出「逐次审批会不会被用户当成骚扰」的样本，而这正是硬约束 4 的产品风险所在，其他三个 Scope 测不到 |
| 方法 | 先让用户完成一个真实的 L1 任务体验价值，再展示授权卡片；观察决策 + 半结构化访谈 |
| 记录 | 是否开启 · 犹豫点 · 追问的问题 · 拒绝理由的原话 |
| 判定 | L2 开启率 ≥ 60%、L3 ≥ 30% 视为模型可行；L3 < 15% 则需重新设计信任爬坡节奏，并把该结论回写到规划 |
| 时点 | **Phase 1 开发启动前或最迟 M2 完成**——结论会影响后续投入规模 |

访谈中要专门追问的一个问题：「如果不开启，你会继续用这个产品吗？」——回答「不会」的比例高，说明降级路径设计得不够真实。

同场实验一并调研（不额外安排用研，清单见 `P0-open-questions.md` §3）：B4 的 Slack 安装权限、B5 的邮件客户端、`P0-01` §5.1.1 的题库措辞、`P0-08` 的应用需求。

**与 Phase 1 退出条件的关系**（A3 已确认 N = 6）：本实验的 8–10 人是**开发前的意愿验证**，与退出条件的「≥ 6 个真实用户进入信任爬坡第三层」是两批人、两件事——前者看「愿不愿意开」，后者看「开了之后真的用了」。判定口径见 `P0-04` §9。N = 6 时样本很小，退出判定必须结合本节的定性访谈，不能只看比例。

**招募可行性风险（A2 的连带）**：团队以中文工作，而样本要求是海外英语市场的市场 / 运营岗非熟人。这批人的招募周期与成本显著高于国内同岗位，而本实验是三个「序 0」阻塞项之一——招募一旦拖期，整个 Phase 1 排期跟着塌。对策：① 立项即启动招募，不等设计完成；② 用付费用研平台（Respondent / User Interviews 一类）而非自然人脉；③ 预留双倍招募周期；④ 若两周内凑不满 8 人，**降到 5 人开跑**（规划 §2.1 的下限）而不是继续等。

---

## 12. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 授权率过低导致产品价值无法体现 | 极高 | §11 前置实验先验证；信任爬坡分层引导；每层授权都在用户看到价值之后再提出 |
| 「自愿」在实现中被悄悄侵蚀（某功能变相强制） | 极高 | §8.3 E2E 测试是硬约束；每个迭代评审复核核心路径 |
| 权限检查被绕过 | 极高 | §8.2 的旁路测试；检查点单一化 |
| 审计日志本身泄露敏感内容 | 高 | 全字段脱敏摘要，禁止存明文；扫描脚本检查 |
| 删除承诺无法兑现（备份中残留） | 高 | 备份保留期与删除承诺对齐（≤72h）；删除任务记录并可验证 |
| 未来进入欧盟/中国市场时模型不适用 | 中 | §10 明示边界；地域开放决策强制复核本文 |
| 海外样本招募拖期，阻塞三个「序 0」项之一 | 高 | §11 末段的四条对策；招募与设计并行启动，不串行 |

---

## 13. 验收标准

1. §8.2 全部 CI 检查项落地并阻塞合并。
2. §8.3 零授权 E2E 测试通过。
3. 每个 Scope 的授权卡片四段齐全，由产品逐项签字确认，**且 en-US 文案经英文母语审校签字**（A8）。缺任一项不得发版。
4. 撤销授权后 5 秒内运行时生效（缓存失效验证）。
5. 账号删除后 72 小时内，含备份在内的用户数据不可恢复（用恢复演练验证）。
6. §11 前置实验完成并产出结论文档。
7. 渗透测试与凭据泄露扫描通过（计划 §7.11 要求作为 Phase 1 后期验收项）。

---

## 14. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M0 | **前置用户实验（CS-8）** ← 最先做，结论影响后续设计 | 5d |
| M1 | Scope 注册表 + Consent 模型 + ConsentService | 4d |
| M2 | 授权卡片组件 + 内联授权流程（配合 `P0-04`） | 4d |
| M3 | 执行审计日志 + 分区 + 脱敏 | 3d |
| M4 | 隐私中心 UI | 5d |
| M5 | 撤销/导出/删除全链路 + 备份失效验证 | 4d |
| M6 | §8.2 CI 守护 + §8.3 E2E 套件 | 3d |

---

## 15. 待决问题

1. ~~`consent_record` 永久保留 vs 账号删除后匿名化保留~~ → **已决（B1）**：账号删除后**匿名化保留**（`user_id` 替换为不可逆哈希，保留时间 + scope + 动作），见 §7。<br>**剩余执行动作**：请法务确认该做法在美国（A2 目标市场）成立，尤其 CCPA/CPRA 的删除权与「保留去标识化记录」的边界。这是执行项不是待决项——若法务否决，退回全删并接受「无法举证曾取得授权」的代价。
2. ~~「关闭授权时是否连带删除已产生数据」默认值~~ → **已决（B2）**：**默认不删，明确询问用户**，见 §6.3。仍在 §11 实验中顺带验证用户预期（若多数用户预期「关掉就该删」，则改文案措辞，不改默认值）。
