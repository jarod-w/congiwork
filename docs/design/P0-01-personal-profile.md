# P0-01 个人画像（Personal Profile）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付） |
| 对应规划 | `ai_platform_plan.md` §4.1、§3（Memory OS-P0） |
| 依赖 | `P0-02 Memory OS`（共用存储）、`P0-03 Agent Runtime`（访谈由 Agent 驱动） |
| 被依赖 | `P0-03`（上下文注入）、`P0-04`（onboarding 界面）、`P0-06`（Skill 生成时的背景） |
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
  user_id     uuid NOT NULL UNIQUE,
  org_id      uuid NULL,
  version     int  NOT NULL DEFAULT 1,      -- 每次生效变更 +1，用于缓存失效
  completed   boolean NOT NULL DEFAULT false, -- 是否完成过一次访谈
  created_at  timestamptz NOT NULL,
  updated_at  timestamptz NOT NULL
);

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
| `preferences.writing_tone` | string | `"简洁、少形容词"` | 高 |
| `preferences.output_format` | string | `"优先用表格"` | 高 |
| `preferences.language` | string | `"zh-CN"` | 高 |
| `working_hours` | object | `{"tz":"Asia/Shanghai","start":"09:30"}` | 低 |
| `custom.*` | any | 自由扩展 | 低 |

未在词表内的 key 一律落到 `custom.*` 命名空间，不阻塞采集。

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

1. **每轮问题由服务端从题库选择，LLM 只负责措辞和追问**。题库定义在 `interview_question.yaml`，含 `key`、`prompt_hint`、`required`、`extractor_schema`。这样保证 Profile 字段可控，同时保留对话感。
2. **抽取用结构化输出**：每轮结束后调一次 LLM，输入是本轮对话，输出严格匹配 `extractor_schema`（走 tool-use 强制 schema），失败重试 1 次后降级为「跳过该字段」而非阻塞流程。
3. **随时可退出**：任何时刻用户说「先不聊了 / 直接帮我干活」，立刻结束访谈进入工作区，已采集部分正常保存。

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
常用工具：Slack、Notion、HubSpot
输出偏好：简洁、少形容词；优先用表格；中文
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

1. 题库的初始内容需要产品/用研输入，当前设计只定了结构。建议在 §2.1 的 5–10 人前置实验中一并测试问题措辞。
2. 用户切换公司/角色时，旧 Profile 如何处理？倾向做「归档 + 新建」而非覆盖，但需要确认是否值得在 Phase 1 投入。
