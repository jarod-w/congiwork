# P0-01 个人画像（Personal Profile）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付） |
| 对应规划 | `ai_platform_plan.md` §4.1、§3（Memory OS-P0） |
| 依赖 | `P0-02 Memory OS`（共用存储）、`P0-03 Agent Runtime`（访谈由 Agent 驱动） |
| 被依赖 | `P0-03`（上下文注入）、`P0-04`（onboarding 界面）、`P0-06`（Skill 生成时的背景） |
| 目标用户 | **市场 / 运营**（`P0-open-questions.md` A1 已确认），海外英语市场（A2） |
| 文档状态 | Draft |

---

## 1. 背景与目标

计划中 Personal Profile 是「AI 主动访谈用户，收集角色、公司背景、业务目标、常用工具、工作偏好」。它解决的是**冷启动阶段的个性化空窗**：在用户还没有积累任何任务历史时，Profile 是唯一能让第一次对话就显得「懂我」的信息源，直接服务于 §2.4 的冷启动信任问题。

目标：

- **G1** 新用户在 3 分钟内完成核心画像采集，且过程本身就展示产品价值（不是一张枯燥表单）。
- **G2** Profile 能稳定注入到每一次任务的上下文中，让输出在第一次使用时就有可感知的个性化。
- **G3** Profile 全程可见、可改、可删，不产生「AI 悄悄记了什么」的不安感。

非目标：

- 不做心理测评、性格建模、绩效画像。
- 不从外部数据源（LinkedIn、企业目录）抓取用户信息。
- 不做组织级画像（Phase 3 企业化再议）。

---

## 2. 范围

### 2.1 In Scope

访谈式采集、Profile 数据模型、查看/编辑界面、对话中的增量更新、上下文注入、导出与删除。

### 2.2 Out of Scope

- 从聊天记录做无确认的隐式推断写入（Phase 2，且需走 `telemetry` Scope）。
- 多语言画像（Phase 1 仅中英）。

---

## 3. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| PF-1 | 访谈式采集 | 新用户注册后由 Agent 发起结构化访谈，分轮进行，可随时跳过 | 完成率 ≥ 70%，中位耗时 ≤ 3 分钟 |
| PF-2 | Profile 数据模型 | 受控字段 + 自由扩展字段，带来源与置信度 | 见 §4 |
| PF-3 | Profile 查看与编辑 | 用户可查看全部字段、手动增删改 | 每个字段可溯源到「谁在什么时候写的」 |
| PF-4 | 增量更新 | 对话中发现新事实 → 生成候选 → 用户确认后入库 | 候选不经确认绝不生效 |
| PF-5 | 上下文注入 | 渲染为紧凑 Profile Card 注入 system prompt | ≤ 600 tokens，命中缓存 P99 < 5ms |
| PF-6 | 导出与删除 | 一键导出 JSON，一键清空 | 删除后 24h 内从备份中失效 |
| PF-7 | 冷启动即用 | 用户跳过全部访谈也能正常使用产品 | 见 `00-conventions.md` §5 |

---

## 4. 数据模型

Profile 与 Memory 共用一套存储（PostgreSQL），但**逻辑上是两类东西，边界必须清晰**：

| | Personal Profile | Memory Item（`P0-02`） |
|---|---|---|
| 数量级 | 数十条 | 数百至数万条 |
| 变更频率 | 低（月级） | 高（任务级） |
| 使用方式 | **全量注入**每次对话 | **按需检索** top-k |
| 来源 | 访谈 / 用户手填 / 确认过的候选 | 任务过程抽取 |

> 设计取舍：不把 Profile 做成 Memory 的一个 `type`，而是独立表。原因是注入策略完全不同——Profile 走「全量、稳定、可缓存」，Memory 走「检索、动态、按 token 预算截断」。混在一起会让检索层被迫特判。

```sql
CREATE TABLE profile (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL,
  org_id      uuid NULL,
  version     int  NOT NULL DEFAULT 1,      -- 每次生效变更 +1，用于缓存失效
  completed   boolean NOT NULL DEFAULT false, -- 是否完成过一次访谈
  archived_at timestamptz NULL,             -- B7：非空即已归档，不再注入
  archive_reason text NULL,                 -- 用户自填，如"换公司"
  created_at  timestamptz NOT NULL,
  updated_at  timestamptz NOT NULL
);

-- 一个用户同时只能有一个生效 Profile，但可以有任意多个已归档的
CREATE UNIQUE INDEX ON profile (user_id) WHERE archived_at IS NULL;

CREATE TABLE profile_field (
  id          uuid PRIMARY KEY,
  profile_id  uuid NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  user_id     uuid NOT NULL,
  key         text NOT NULL,               -- 见 §4.1 受控词表
  value       jsonb NOT NULL,              -- 标量或数组，按 key 的 schema
  source      text NOT NULL CHECK (source IN ('interview','manual','extracted')),
  confidence  real NOT NULL DEFAULT 1.0,
  status      text NOT NULL CHECK (status IN ('pending','active','rejected','stale')),
  evidence    jsonb NULL,                  -- {task_id, message_id, quote} 溯源
  created_at  timestamptz NOT NULL,
  updated_at  timestamptz NOT NULL
);

CREATE UNIQUE INDEX ON profile_field (profile_id, key) WHERE status = 'active';
CREATE INDEX ON profile_field (user_id, status);
```

`status` 状态机：

```text
extracted ──▶ pending ──user confirm──▶ active ──user edit──▶ active(new version)
                 │                         │
            user reject                user delete
                 ▼                         ▼
             rejected                    (physically deleted)
```

`extracted` 来源的字段**必须**先落 `pending`，绝不直接 `active`（PF-4 验收项）。

### 4.1 受控字段词表

| key | 类型 | 示例 | 注入权重 |
|---|---|---|---|
| `role` | string | `"Marketing Director"` | 高 |
| `industry` | string | `"B2B SaaS"` | 高 |
| `company_context` | string[] | `["50人团队","主要客户是中小电商"]` | 高 |
| `business_goals` | string[] | `["Q3 把 MQL 提升 30%"]` | 高 |
| `tools` | string[] | `["Slack","Notion","HubSpot"]` | 中（同时用于连接器推荐） |
| `recurring_deliverables` | string[] | `["周报","季度渠道复盘","内容排期"]` | 中（同时用于 Skill 推荐） |
| `preferences.writing_tone` | string | `"简洁、少形容词"` | 高 |
| `preferences.output_format` | string | `"优先用表格"` | 高 |
| `preferences.language` | string | `"en-US"` | 高 |
| `working_hours` | object | `{"tz":"America/Los_Angeles","start":"09:00"}` | 低 |
| `custom.*` | any | 自由扩展 | 低 |

未在词表内的 key 一律落到 `custom.*` 命名空间，不阻塞采集。

`recurring_deliverables` 是按 A1（市场 / 运营）新增的一项。加它的理由不是「多采一个字段」，而是它同时是 `P0-06` keyword trigger 的最佳种子：用户说「我每周要交渠道周报」，就等于告诉了系统第一个该被沉淀成 Skill 的流程。没有它，Phase 1 的退出条件「自发创建 ≥3 个 Skill」只能靠用户自己想起来。

`preferences.language` 与 `working_hours` 的示例值按 A2（海外优先）给。默认值取决于 A8（产品文案语言基线，待确认）——实现上默认值必须从配置读，不得硬编码。

---

## 5. 关键流程

### 5.1 访谈流程（PF-1）

访谈不是表单，是一段**由 Agent 驱动的对话**，但受服务端状态机约束，避免 LLM 自由发挥导致漏采或超时。

```text
注册完成
   │
   ▼
Round 1（必答，≤3 问）：你的角色 / 公司在做什么 / 最近想让 AI 帮什么忙
   │        ← 第 3 问的答案直接触发一次真实任务（见 §5.2）
   ▼
Round 2（可跳过，≤4 问）：常用工具 / 输出偏好 / 语气偏好
   │
   ▼
Round 3（可跳过，按需）：针对 Round 1 答案的追问（如"你说的客户主要是哪类"）
   │
   ▼
生成 Profile 摘要卡片 → 用户确认/修改 → completed = true
```

设计要点：

1. **每轮问题由服务端从题库选择，LLM 只负责措辞和追问**。题库定义在 `interview_question.yaml`，含 `key`、`round`、`required`、`prompt_hint`、`options_hint`、`extractor_schema`、`follow_up_when`。这样保证 Profile 字段可控，同时保留对话感。初始题库见 §5.1.1。
2. **抽取用结构化输出**：每轮结束后调一次 LLM，输入是本轮对话，输出严格匹配 `extractor_schema`（走 tool-use 强制 schema），失败重试 1 次后降级为「跳过该字段」而非阻塞流程。
3. **随时可退出**：任何时刻用户说「先不聊了 / 直接帮我干活」，立刻结束访谈进入工作区，已采集部分正常保存。

### 5.1.1 初始题库（按 A1 = 市场 / 运营 落实）

题库以**语义 key** 定义，实际问句由 LLM 按用户语言生成，因此下表的中文问法是**语义说明而非最终文案**——交付文案为 **en-US**（A8 已确认）。`options_hint` 是给 LLM 的候选项提示，会渲染成可点选项 + 自由输入，降低打字成本。

| 轮 | key | 问什么（语义） | options_hint | 抽取字段 | 必答 |
|---|---|---|---|---|---|
| 1 | `role` | 你现在主要负责哪一块 | 内容 / 活动 / 增长投放 / 用户运营 / 品牌 / 综合市场 | `role`、`custom.sub_function` | ✅ |
| 1 | `company` | 你们公司做什么业务，主要卖给谁 | — | `industry`、`company_context` | ✅ |
| 1 | `first_task` | 最近有什么事，如果能有人替你做，你最想交出去 | — | **直接触发首个真实任务**（§5.2），同时落 `business_goals` 候选 | ✅ |
| 2 | `recurring_deliverables` | 每周或每月你固定要交的东西有哪些 | 周报 / 月报 / 季度复盘 / 内容排期 / 活动方案 / 数据看板 | `recurring_deliverables` | ⬜ |
| 2 | `tools` | 这些活主要在哪几个工具里干 | 表格（Excel / Google Sheets）/ 文档（Docs / Notion）/ 邮箱 / Slack / CRM / 数据分析 / 广告后台 | `tools` | ⬜ |
| 2 | `output_format` | 我把东西交给你时，你更想看到哪种形式 | 表格优先 / 要点清单 / 完整成稿 | `preferences.output_format` | ⬜ |
| 2 | `writing_tone` | 三段示例文案，哪一段最像你平时对外写的 | 三段真实例句 | `preferences.writing_tone` | ⬜ |
| 3 | `followup_metric` | 你说的增长／投放，主要看哪几个指标 | `follow_up_when: role in [增长投放, 综合市场]` | `business_goals` | ⬜ |
| 3 | `followup_customer` | 客户主要是哪一类，规模大概多大 | `follow_up_when: company_context 过短或含糊` | `company_context` | ⬜ |
| 3 | `followup_report` | 你那份周报／复盘里通常有哪几块内容 | `follow_up_when: recurring_deliverables 非空` | `custom.report_outline` | ⬜ |

`followup_report` 的产出直接喂给 `P0-06`：它是「预置示例 Skill 该长什么样」的第一手输入，也是 keyword trigger 的种子。

**措辞四条原则**（题库评审的检查项）：

1. 用「你想让我帮什么」代替「请填写你的岗位职责」。前者是服务，后者是入职表——同样的信息，两种感受在授权意愿上的差别是决定性的（同 §5.2 的理由）。
2. **不问考核类信息**：KPI 数值、职级、汇报关系、薪资、绩效。这些对输出质量没有增益，却会立刻触发防御心理。这是题库的硬边界，不是措辞偏好。
3. 偏好类问题**给例子选，不让用户描述抽象风格**。用户说不出「我的语气是什么」，但能一眼认出哪段像自己写的——`writing_tone` 因此设计为三选一而非开放问答。
4. 每个可跳过问题都带显式「跳过」，且**跳过后不追问原因**。

### 5.2 访谈与首次任务合一（G1 的关键设计）

Round 1 的第 3 问是「最近想让我帮你做什么」。用户的回答**直接作为第一个真实 Task 发起**，而不是先答完所有问题再开始用。

理由：这直接服务计划 §10.2 的冷启动钩子——「用户第一次使用就要能看到价值」。把访谈嵌进第一次真实交付里，用户感受到的是「它在问清楚需求」，而不是「它在收集我的信息」。这两种感受在授权意愿上的差别是决定性的。

```text
用户答"帮我把这份客户名单整理成周报"
        │
        ├──▶ 立即创建 Task 并开始执行（L1，无需任何授权）
        │
        └──▶ 同时后台把 role/company_context 落 pending
                     │
              任务出结果后，用一张卡片一次性确认：
              "为了下次做得更好，我记住了这几点，对吗？"
```

### 5.3 增量更新（PF-4）

Task 结束时，Runtime 发出 `memory.candidate` 事件（见 `00-conventions.md` §7）。归属判定规则：

- 命中受控词表且属于「稳定属性」 → Profile 候选（`profile_field.pending`）
- 其他 → Memory 候选（走 `P0-02`）

确认 UI 收敛到一个位置：任务结果卡片下方的「顺手记住」区域，**最多展示 3 条**，一键全部确认或逐条处理。超过 3 条的候选沉到 Memory Browser 的待确认队列，不打断当前任务。

### 5.4 上下文注入（PF-5）

```text
active profile_field
      │
      ▼
渲染模板（按注入权重排序，截断到 600 tokens）
      ▼
Redis 缓存 key = profile:{user_id}:v{version}
      ▼
Agent Runtime 组装 system prompt 时读取
```

渲染示例：

```text
<user_profile>
角色：Marketing Director（B2B SaaS）
公司背景：50 人团队；主要客户是中小电商
当前目标：Q3 把 MQL 提升 30%
固定交付物：每周渠道周报、季度复盘
常用工具：Slack、Notion、HubSpot
输出偏好：简洁、少形容词；优先用表格；en-US
</user_profile>
```

缓存失效：`profile.version` 变更即换 key，无需主动删除（旧 key 自然 TTL 过期，TTL = 7d）。

---

## 6. 接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/profile` | 获取完整 Profile（含 pending 候选） |
| `PATCH` | `/api/v1/profile/fields/{key}` | 修改单个字段，写入即 `active`，version+1 |
| `DELETE` | `/api/v1/profile/fields/{key}` | 物理删除该字段 |
| `POST` | `/api/v1/profile/fields/{id}/confirm` | 确认候选：`{action: "accept"｜"reject"｜"edit", value?}` |
| `POST` | `/api/v1/profile/interview/start` | 开始/继续访谈，返回当前轮问题 |
| `POST` | `/api/v1/profile/interview/answer` | 提交本轮回答，返回下一轮或结束 |
| `POST` | `/api/v1/profile/interview/skip` | 跳过当前轮或整个访谈 |
| `GET` | `/api/v1/profile/export` | 导出 JSON |
| `DELETE` | `/api/v1/profile` | 清空全部画像 |

内部接口（供 Runtime 调用，非 HTTP）：

```python
class ProfileService:
    def render_card(self, user_id: UUID, max_tokens: int = 600) -> str: ...
    def propose(self, user_id: UUID, key: str, value: Any, evidence: dict) -> UUID: ...
```

---

## 7. 前端设计要点

- **Onboarding 页**：单列对话式，不用多步表单。右侧实时显示「已了解到的信息」卡片，每采到一条就渐显一条——让采集过程本身可见，是信任建设的一部分。
- **Profile 页**（`Memory Browser` 的一个 Tab）：按分组展示字段，每个字段带来源徽标（`访谈` / `你手动填写` / `从任务中学到`）与「查看依据」链接。
- **跳过路径必须显眼**：「跳过，直接开始工作」按钮与「继续」同级，不做成灰色小字。

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 访谈被当成注册障碍，流失率上升 | 高 | 首个真实任务与访谈合一（§5.2）；全程可跳过；跳过后产品完整可用 |
| LLM 抽取错误写进 Profile 并持续污染输出 | 中 | 抽取结果强制走 `pending`；每个字段可溯源；提供一键回滚到上一版本 |
| Profile 过大挤占上下文预算 | 中 | 硬上限 600 tokens，按权重截断；超限时在 Profile 页提示用户精简 |
| 用户填了敏感信息（如客户名单）到 company_context | 中 | 字段值长度上限 200 字符；超长引导改为上传文件走 Memory；Profile 页明示「这里适合放长期不变的背景，不要放具体客户数据」 |

---

## 9. 验收标准

1. 新用户从注册到拿到第一个任务结果，中位耗时 ≤ 5 分钟。
2. 访谈完成率（至少完成 Round 1）≥ 70%。
3. 跳过全部访谈的用户，可以正常完成一次文件整理任务并拿到结果（自愿性检查项）。
4. 任意 `extracted` 字段在未经用户确认时，不出现在注入的 Profile Card 中——用自动化测试覆盖。
5. `DELETE /profile` 后，重新发起任务时上下文中不含任何画像信息。

---

## 10. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | 数据模型 + CRUD API + Profile 页 | 3d |
| M2 | 访谈状态机 + 题库 + 结构化抽取 | 5d |
| M3 | 上下文注入 + 缓存 | 2d |
| M4 | 增量候选与确认 UI（依赖 `P0-04` 任务结果卡片） | 3d |
| M5 | 导出/删除 + 自愿性验收测试 | 2d |

---

## 11. 待决问题

1. ~~题库的初始内容需要产品/用研输入~~ → **已决（A1 = 市场 / 运营）**：初始题库见 §5.1.1。仍需在 `P0-07` §11 前置实验中验证**措辞**（不是验证问哪些字段），重点测 `writing_tone` 的三段例句是否可辨识、`first_task` 的问法是否能问出足够具体的任务。
2. ~~用户切换公司/角色时，旧 Profile 如何处理？~~ → **已决（B7，2026-08-18 确认默认做法）**：**归档 + 新建，Phase 1 只做手动触发，不做自动检测。**
   - **数据模型已同步**（§4 `profile` 表）：`user_id` 的 `UNIQUE` 约束改为**部分唯一索引** `WHERE archived_at IS NULL`。这是本条决策的硬性连带——原约束是 `user_id NOT NULL UNIQUE`，一个用户只能有一行 profile，**归档就等于删除**，与「归档 + 新建」直接冲突。新增 `archived_at` / `archive_reason` 两列。
   - **归档语义**：已归档 Profile 不再注入任何任务上下文（`profile:{user_id}:v{version}` 缓存 key 立即失效），但**保留可读可导出**——用户换公司不等于要销毁过去的自己。真正的删除仍走 §隐私的物理删除路径。
   - **不做自动检测的理由**：能触发「你是不是换工作了」这种猜测的信号（邮箱域名变化、`company` 字段被改），全都来自我们本不该拿来做这类推断的数据。猜错的代价是把用户既有画像判为过期，收益却只是省一次手动点击。这条与 `P0-07` 的自愿模型同向。
   - **入口**：Profile 设置页的显式操作「我换了公司 / 换了岗位」，二次确认后归档旧的、开启新一轮访谈（§5 冷启动流程原样复用，不需要单独设计）。
3. ~~题库与 Profile Card 的文案语言~~ → **已决（A8）**：交付文案 en-US，中文为可选语言。实现上语言从配置读取、不硬编码。仓库级约定已在 `CLAUDE.md` 同步修改。
