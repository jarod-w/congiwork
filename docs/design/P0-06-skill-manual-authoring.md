# P0-06 手动 Skill 创建与执行设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付，★★★★） |
| 对应规划 | `ai_platform_plan.md` §4.3（手动创建 Skill）、§7.9 |
| 依赖 | `P0-03 Agent Runtime`、`P0-05 MCP`、`P0-02 Memory OS` |
| 被依赖 | `P1-02 半自动 Skill 生成`、`P1-03 Skill Engine 演进` |
| 文档状态 | Draft |

---

## 1. 背景与目标

计划把 Skill Engine 整体列为 P1，但**手动 Skill 创建属于 P0 §4.3**，且是 Phase 1 的退出条件之一：「用户自发创建 ≥3 个手动 Skill 并复用」。

本文只覆盖 P0 部分：Skill 的数据模型、手动创建、执行、复用。P1 的半自动生成、版本灰度、成功率优化见 `P1-02` / `P1-03`。

目标：

- **G1** 用户能把「上次那个流程」变成可重复调用的东西，且创建成本低于自己重新描述一遍。
- **G2** Skill 执行走同一个 Agent Runtime，不引入第二套执行引擎。
- **G3** Skill 结构为 Phase 2 的半自动生成预留好落点——生成的产物形状和手动创建完全一致。

非目标：

- 不自研工作流 DSL 与解释器（见 §5 的关键取舍）。
- 不做 Skill 分享/市场（Phase 3）。
- 不做定时触发（Phase 2）。

---

## 2. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| SK-1 | Skill 数据模型 | 基于计划 §7.9 扩展 | 见 §4 |
| SK-2 | 自然语言创建 | 用户描述流程 → AI 结构化为草稿 → 用户确认 | ≤3 分钟完成一个 Skill |
| SK-3 | 从任务创建 | 任务结束后「存为技能」，预填已执行步骤 | 见 `P0-04` §4.4 |
| SK-4 | Skill 编辑器 | 查看/编辑步骤、参数、所需权限 | 非技术用户可理解 |
| SK-5 | 触发与执行 | 手动选择 / 关键词匹配触发，参数收集后执行 | 走 `P0-03` Runtime |
| SK-6 | Skill Library | 列表、搜索、使用次数、成功率 | |
| SK-7 | 权限预检 | 执行前检查所需 Scope，缺失时一次性引导 | 不在执行中途反复打断 |
| SK-8 | 试运行 | dry-run 模式，只预览不产生副作用 | 所有 write/irreversible 步骤被拦截并展示计划 |

---

## 3. 关键取舍：Skill 是「结构化提示」还是「可执行程序」

这是本模块最重要的设计决策。

| 方案 | 描述 | 优 | 劣 |
|---|---|---|---|
| A. 纯提示词模板 | Skill = 一段带变量的 prompt | 实现极简；LLM 灵活应变 | 不可控、不可审计、步骤不可见、成功率无法归因 |
| B. 自研 DSL + 解释器 | Skill = 严格的工作流程序 | 可控、可复现 | 工程量大；用户需要"编程"；应对变化能力差 |
| **C. 结构化步骤 + LLM 执行（选定）** | Skill = 有序步骤列表，每步声明类型与意图，由 Runtime 逐步驱动 LLM 执行 | 步骤可见可审计可编辑；保留 LLM 应变能力；不需要写解释器 | 执行确定性弱于 B |

**选 C**。理由：Phase 1 的核心目标是验证「用户愿意沉淀流程」，不是追求 100% 确定性执行。C 方案下 Skill 的每一步都是可视、可审批、可统计成功率的，这些正是 Phase 2 优化所需要的数据基础；而 B 方案的确定性收益，在需求尚未验证时不值得投入。

具体地：`workflow` 是有序步骤数组，Runtime 把「当前步骤的意图 + 可用工具 + 上下文」交给 LLM 执行，执行完进入下一步。这不是"照着脚本跑"，也不是"完全自由发挥"，而是**受约束的自由**。

---

## 4. 数据模型

在计划 §7.9 的基础上扩展（保留原字段名）：

```sql
CREATE TABLE skill (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  name          text NOT NULL,
  description   text NOT NULL,           -- 什么时候该用它，给用户和 LLM 看
  trigger       jsonb NOT NULL,           -- 见 §4.1
  input_schema  jsonb NOT NULL,           -- JSON Schema
  workflow      jsonb NOT NULL,           -- 见 §4.2
  tools         text[] NOT NULL DEFAULT '{}',       -- 冗余，便于筛选
  required_scopes text[] NOT NULL DEFAULT '{}',     -- 由 workflow 推导，用于预检
  source        text NOT NULL CHECK (source IN ('manual','from_task','semi_auto')),
  source_ref    jsonb NULL,               -- {task_id} 若从任务创建
  version       int NOT NULL DEFAULT 1,
  status        text NOT NULL CHECK (status IN ('draft','active','archived')),
  run_count     int NOT NULL DEFAULT 0,
  success_count int NOT NULL DEFAULT 0,
  last_run_at   timestamptz NULL,
  created_at    timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL
);
CREATE INDEX ON skill (user_id, status);

CREATE TABLE skill_version (
  skill_id      uuid NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
  version       int NOT NULL,
  snapshot      jsonb NOT NULL,
  changed_by    text NOT NULL CHECK (changed_by IN ('user','system')),
  change_note   text NULL,
  created_at    timestamptz NOT NULL,
  PRIMARY KEY (skill_id, version)
);
```

`success_rate` 在计划 §7.9 中是一个字段，这里改为由 `success_count / run_count` 派生——避免存储可推导值造成不一致。

### 4.1 trigger

```json
{ "type": "manual" }                                  // 用户从 Library 手动调用
{ "type": "keyword", "patterns": ["周报", "渠道复盘"] }  // 对话中匹配则推荐（不自动执行）
```

**关键约束：Phase 1 的 keyword 触发只做「推荐」，不做「自动执行」。** 界面上表现为对话框上方出现一条建议：`看起来像「季度渠道复盘」，用这个技能？[使用]`。自动执行在用户尚未充分信任 Skill 质量时会造成失控感。

### 4.2 workflow 步骤结构

```json
{
  "workflow": [
    {
      "id": "s1",
      "type": "collect_input",
      "title": "确认要复盘的季度和渠道范围",
      "fields": ["quarter", "channels"]
    },
    {
      "id": "s2",
      "type": "tool",
      "title": "从 HubSpot 拉取该季度各渠道转化数据",
      "tool": "hubspot.query_deals",
      "args_hint": { "quarter": "{{quarter}}" },
      "on_error": "ask_user"
    },
    {
      "id": "s3",
      "type": "llm",
      "title": "按渠道汇总并找出环比变化最大的三个",
      "instruction": "输出表格，列：渠道/线索数/转化率/环比。突出变化最大的三项并给出可能原因。",
      "uses_memory": true
    },
    {
      "id": "s4",
      "type": "approval",
      "title": "让我确认报告内容",
      "preview_from": "s3"
    },
    {
      "id": "s5",
      "type": "tool",
      "title": "发到 #marketing 频道",
      "tool": "slack.post_message",
      "on_error": "stop"
    }
  ]
}
```

步骤类型（受控词表）：

| type | 说明 | 可否由用户在编辑器中增删 |
|---|---|---|
| `collect_input` | 向用户收集参数 | ✅ |
| `llm` | 纯推理/写作步骤 | ✅ |
| `tool` | 调用一个工具 | ✅ |
| `approval` | 显式审批点 | ✅ |
| `skill` | 调用另一个 Skill（Phase 1 仅支持 1 层嵌套） | ✅ |

`on_error`：`stop`（默认）/ `ask_user` / `skip` / `retry`。`irreversible` 步骤不允许 `retry`（与 `P0-05` §6 一致）。

`args_hint` 是**提示而非绑定**：Runtime 把它作为参考交给 LLM 组装实际参数，而不是机械模板替换。这保留了应变能力（比如 HubSpot 的字段名变了，LLM 能自行调整）。

---

## 5. 关键流程

### 5.1 自然语言创建（SK-2）

```text
用户描述："每个季度末，我要从 HubSpot 拉各渠道数据，
          做成表格找出变化最大的渠道，然后发到 #marketing"
        │
        ▼
LLM 结构化（强制 schema 输出）→ Skill 草稿
        │  同时输出：
        │  - 识别出的参数（quarter, channels）
        │  - 所需工具与 Scope（tool:hubspot:read, tool:slack:send）
        │  - 未识别清楚的地方（标记为 needs_clarification）
        ▼
用户在编辑器中确认/修改
        │
        ▼
权限预检：列出缺失的 Scope，一次性引导授权（可跳过，执行时再问）
        │
        ▼
试运行（可选，强烈建议）→ status=active
```

结构化 prompt 的关键要求：

- 步骤 `title` 必须是用户自己的语言，不能是工具名。
- 工具选择只能从**该用户已连接或可连接**的工具集中选，不能凭空捏造。
- 识别不出对应工具的步骤，降级为 `llm` 步骤并标记 `needs_clarification`，不要瞎猜。

### 5.2 从任务创建（SK-3）

用户在任务结束后点「存为技能」，系统把 `task_step` 序列作为输入：

```text
task_step 序列
   │
   ▼ 规范化：合并连续 llm 步骤、剔除失败重试、剔除澄清往返
   ▼ 参数化：识别哪些具体值应该变成变量
   │      候选来源：collect_input 的输入、工具参数中的字面量、日期/数量
   ▼ LLM 生成草稿 + 参数候选（标注"这个值下次可能会变吗？"）
   ▼ 用户在编辑器中逐个确认哪些是变量
   ▼ Skill 草稿
```

参数化是这里的难点，也是 `P1-02` 半自动生成的核心难点。Phase 1 的做法是**把判断交给用户**：AI 给出候选并标注，用户点选确认。不追求自动判断准确率。

### 5.3 执行（SK-5）

```text
用户选择 Skill / 接受推荐
   │
   ▼ 权限预检（SK-7）：一次性列出所有缺失 Scope
   │     缺失时：一张卡片列出全部所需权限，用户可全部开启 / 部分开启 / 跳过相关步骤
   ▼ 参数收集：按 input_schema 生成表单，已知值（来自对话/记忆）预填
   ▼ 创建 Task（task.skill_id = skill.id）
   ▼ Runtime 按 workflow 顺序驱动
   │     每步：注入该步 title/instruction + 该步允许的工具 → LLM 执行
   ▼ 完成 → 更新 run_count / success_count
```

**权限一次性预检**（SK-7）是重要的体验设计：如果在执行到第 4 步时才问「要不要授权 Slack」，用户已经等了一分钟，体验很差且容易放弃。预检把所有权限问题前置到执行前的一张卡片。

### 5.4 试运行（SK-8）

dry-run 模式下：

- `read` 工具正常执行（无副作用，且能让预览真实）
- `write` / `irreversible` 工具**不执行**，改为让 LLM 生成"将会做什么"的描述与参数预览
- 产出一份「执行预演报告」：每步会做什么、会用到什么权限、会产生什么产物

这是用户敢把 Skill 用在真实工作上的前提。

---

## 6. Skill 编辑器（SK-4）前端要点

面向非技术用户，不是流程图工具：

```text
技能：季度渠道复盘                              [试运行] [保存]
描述：每季度末汇总各渠道转化并同步到 Slack

需要的参数
  · 季度  （执行时问我）
  · 渠道范围（执行时问我，默认：全部）

步骤
  1. ▸ 从 HubSpot 拉取该季度各渠道转化数据      🔧 HubSpot  🔓 读取
  2. ▸ 按渠道汇总，找出环比变化最大的三个         🤖 AI 分析
  3. ⏸ 让我确认报告内容
  4. ▸ 发到 #marketing 频道                    🔧 Slack   ⚠ 发送
                                              [+ 添加步骤]
需要的权限（3）
  ✓ 读取 HubSpot 数据      已授权
  ✓ AI 分析                无需授权
  ⚠ 替我发 Slack 消息      未授权 [去开启]
```

- 步骤用列表而非画布——Phase 1 不支持分支和并行，列表足够且更易懂。
- 权限区块常驻可见，让用户在编辑阶段就知道这个 Skill 需要什么。
- 每个步骤可拖动排序、删除、在其后插入。

---

## 7. 接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/skills` | 列表，支持搜索/排序 |
| `POST` | `/api/v1/skills/draft` | 从自然语言或 `task_id` 生成草稿 |
| `POST` | `/api/v1/skills` | 保存 |
| `PATCH` | `/api/v1/skills/{id}` | 更新（version+1，写 snapshot） |
| `DELETE` | `/api/v1/skills/{id}` | 归档（软删）/ 彻底删除 |
| `GET` | `/api/v1/skills/{id}/versions` | 版本历史，支持回滚 |
| `POST` | `/api/v1/skills/{id}/precheck` | 权限预检，返回缺失 Scope 列表 |
| `POST` | `/api/v1/skills/{id}/run` | 执行，`{inputs, dry_run: bool}` → `task_id` |
| `POST` | `/api/v1/skills/suggest` | 根据当前对话推荐 Skill（keyword trigger） |

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 用户不知道该创建什么 Skill，创建量为 0（Phase 1 退出条件不达标） | 极高 | 主动识别：同一用户 7 天内做过 ≥2 次相似任务时，在结果卡片主动建议「要不要存成技能」；提供 3–5 个预置示例 Skill 可一键复制修改 |
| LLM 结构化出的 Skill 质量差，执行失败率高，用户失去信心 | 高 | 强制试运行引导；`needs_clarification` 标记不允许在 `active` 状态存在；首次执行失败后主动提示「要一起改改这个技能吗」 |
| 步骤执行的确定性不足（方案 C 的固有代价） | 中 | 统计每个步骤的成功率，暴露在编辑器中；失败率高的步骤提示用户加更明确的 instruction |
| Skill 携带过多权限，成为权限放大器 | 高 | `required_scopes` 由 workflow 推导而非用户填写，不可绕过；执行时逐 Scope 检查，`irreversible` 步骤仍逐次审批 |
| 用户改了外部系统（如 Slack 频道改名），Skill 静默失效 | 中 | `on_error: ask_user` 作为工具步骤的推荐默认；失败后在 Library 中标红并给出修复建议 |

---

## 9. 验收标准

1. 用户从「描述流程」到「保存一个可执行 Skill」中位耗时 ≤ 3 分钟。
2. 从已完成任务创建 Skill，≤3 次点击完成。
3. dry-run 模式下，注入一个会发邮件的 Skill，验证无任何外部副作用产生（用 mock 上游断言零写调用）。
4. 权限预检在执行前一次性给出全部缺失 Scope，执行过程中不再出现新的授权中断（除 `irreversible` 的逐次审批外）。
5. `required_scopes` 与 workflow 中实际用到的工具 Scope 严格一致（自动化校验）。
6. Phase 1 退出条件支撑：能统计「自发创建 ≥3 个 Skill 并复用」的用户数。

---

## 10. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | 数据模型 + CRUD + 版本快照 | 3d |
| M2 | 自然语言 → Skill 草稿（结构化输出 + 校验） | 4d |
| M3 | Runtime 集成：按 workflow 驱动执行 | 5d |
| M4 | 权限预检 + 参数收集表单 | 3d |
| M5 | Skill 编辑器前端 | 5d |
| M6 | 试运行（dry-run） | 3d |
| M7 | 从任务创建（规范化 + 参数化候选） | 4d |
| M8 | Library + 推荐（keyword trigger）+ 预置示例 | 3d |

---

## 11. 待决问题

1. 预置示例 Skill 的内容依赖 §10.1 目标用户定位，需产品输入。
2. Skill 嵌套调用（`type: skill`）Phase 1 是否真的需要？倾向先实现但限制 1 层，若用研显示无需求可延后以省 3d。
