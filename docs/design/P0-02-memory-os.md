# P0-02 记忆系统（Memory OS）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付，★★★★★） |
| 对应规划 | `ai_platform_plan.md` §4.2、§7.7、§9 |
| 依赖 | `P0-07 隐私授权与审计`（自动写入需 Scope）、`P0-03 Agent Runtime`（写入触发点） |
| 被依赖 | `P0-03`、`P0-04`、`P0-06`、`P1-02` |
| 文档状态 | Draft |

---

## 1. 背景与目标

Memory OS 是「越用越懂你」的物理载体，也是计划 §11 三条壁垒中的一条。但它同时是最容易过度设计的模块——计划已经明确要求 MVP 阶段**只用 PostgreSQL + pgvector 一套存储**，不引入 Event Store、不引入 Neo4j。本文严格遵守该约束。

目标：

- **G1** 一套存储承载三类记忆（Semantic / Episodic / Preference），检索接口统一。
- **G2** 记忆的写入对用户**可见、可控、可撤销**——这是 §5 信任爬坡的基础设施，不是纯技术模块。
- **G3** 检索质量足够支撑「上次你说过 X，这次我按 X 做」的可感知效果，而不是把无关记忆塞进上下文制造噪声。

非目标（明确不做）：

- 知识图谱 / 实体关系推理（Phase 3）
- 跨用户、跨组织的记忆共享（Phase 3）
- 记忆的自动遗忘与重要性衰减学习（Phase 2 再评估，Phase 1 用简单规则）

---

## 2. 三类记忆的职责边界

| 类型 | 存什么 | 典型来源 | 检索方式 | 生命周期 |
|---|---|---|---|---|
| **Semantic** | 关于用户业务世界的事实：公司、产品、客户、业务规则、KPI | 用户上传文件、对话中陈述、任务过程 | 向量 + 关键词 | 长期，可被新事实取代 |
| **Episodic** | 做过什么任务、做出了什么决策、结果如何 | Task 执行结束自动落库 | 结构化查询为主 + 向量辅助 | 长期，只增不改 |
| **Preference** | 写作风格、输出格式、工作习惯 | 用户明示、审批时的修改行为 | 全量或按任务类型过滤 | 长期，可被覆盖 |

> 关键设计：**Episodic 是自动写入的（任务历史本来就是系统事实），Semantic 和 Preference 的自动写入需要用户确认或 Scope 授权。** 这条边界决定了隐私模型能不能落地——把「系统记录自己做过什么」和「AI 记录关于你的事」分开，前者不需要授权，后者需要。

---

## 3. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| MEM-1 | 统一数据模型 | 三类记忆一张主表 + Episodic 结构化附表 | 见 §4 |
| MEM-2 | 写入通道 | 显式写入 / 候选确认 / 自动写入（受 Scope 控制） | 未授权时不产生自动写入 |
| MEM-3 | 混合检索 | 向量 + 全文 + 时间新鲜度加权 | 见 §5.2 评测标准 |
| MEM-4 | 上下文组装 | 按 token 预算分配三类记忆配额 | 总预算可配置，默认 2000 tokens |
| MEM-5 | Memory Browser | 列表/搜索/编辑/删除/来源追溯 | 每条记忆可回答「你为什么知道这个」 |
| MEM-6 | 冲突与时效 | 新事实覆盖旧事实，保留历史链 | 覆盖后旧记忆不再被检索到 |
| MEM-7 | 隐私对接 | 导出、物理删除、按 Scope 批量删除 | 见 `P0-07` |
| MEM-8 | 文件摄取 | 上传文档 → 切片 → 向量化 → Semantic Memory | 支持 pdf/docx/xlsx/md/txt/csv |

---

## 4. 数据模型

```sql
CREATE TABLE memory_item (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  type          text NOT NULL CHECK (type IN ('semantic','episodic','preference')),
  subtype       text NULL,               -- 如 'customer','product','writing_style'
  content       text NOT NULL,           -- 面向 LLM 的完整表述，单条建议 ≤ 500 字
  summary       text NULL,               -- 面向用户的一行摘要，UI 列表用
  embedding     vector(1024) NULL,       -- 见 §6 模型选型
  tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,

  importance    smallint NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
  confidence    real NOT NULL DEFAULT 1.0,

  source_type   text NOT NULL CHECK (source_type IN ('user_explicit','task_extracted','file_ingest','approval_edit')),
  source_ref    jsonb NULL,              -- {task_id, message_id, file_id, quote, page}
  scope_key     text NULL,               -- 若由某 Scope 授权产生，记录之，便于按 Scope 批量删除

  status        text NOT NULL CHECK (status IN ('pending','active','superseded','rejected')),
  superseded_by uuid NULL REFERENCES memory_item(id),

  valid_from    timestamptz NOT NULL DEFAULT now(),
  valid_to      timestamptz NULL,
  last_used_at  timestamptz NULL,
  use_count     int NOT NULL DEFAULT 0,

  created_at    timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL
);

CREATE INDEX ON memory_item USING hnsw (embedding vector_cosine_ops)
  WHERE status = 'active';
CREATE INDEX ON memory_item USING gin (tsv) WHERE status = 'active';
CREATE INDEX ON memory_item (user_id, type, status, updated_at DESC);
CREATE INDEX ON memory_item (user_id, scope_key) WHERE scope_key IS NOT NULL;
```

Episodic 的结构化附表（便于「上次那个季度报告怎么做的」这类查询）：

```sql
CREATE TABLE episodic_record (
  id            uuid PRIMARY KEY,
  memory_id     uuid NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
  user_id       uuid NOT NULL,
  task_id       uuid NOT NULL,
  title         text NOT NULL,
  intent        text NULL,               -- 归一化的任务意图标签
  tools_used    text[] NOT NULL DEFAULT '{}',
  skill_id      uuid NULL,
  outcome       text NOT NULL CHECK (outcome IN ('succeeded','failed','cancelled','partial')),
  decisions     jsonb NOT NULL DEFAULT '[]',  -- [{question, chosen, rejected, reason}]
  user_edits    jsonb NOT NULL DEFAULT '[]',  -- 用户在审批时改了什么，Preference 的重要来源
  duration_ms   int NULL,
  started_at    timestamptz NOT NULL,
  ended_at      timestamptz NULL
);
```

> `user_edits` 这个字段值得单独说明：用户在审批环节把「Dear Sir」改成「Hi」，这是关于偏好的**最高质量信号**——它是行为而非陈述。Phase 1 先把它记下来并作为 Preference 候选提示给用户；Phase 2 的半自动学习会大量依赖它。

**不建 `memory_link` 表**：关系型记忆是知识图谱的雏形，计划已明确延后到 Phase 3。Phase 1 若需表达关联，用 `source_ref` 和 `superseded_by` 已足够。

---

## 5. 关键流程

### 5.1 写入通道（MEM-2）

三条通道，权限要求不同：

```text
① 显式写入（用户主动说"记住：我们的定价是 $99/月"）
      → source_type=user_explicit, status=active
      → 无需授权（用户明示即同意）

② 候选确认（任务过程中 AI 抽取出疑似事实）
      → status=pending → 在任务结果卡片或 Memory Browser 待确认队列
      → 用户 accept 才转 active
      → 无需授权（因为不确认就不生效）

③ 自动写入（低风险偏好，如"用户连续 3 次把输出改成表格"）
      → 需要 Scope: memory:preference:auto_write
      → 未授权时降级为通道 ②（变成候选，等确认）
```

第 ③ 条的降级行为就是 `00-conventions.md` §5 要求的 `degraded_behavior`：不授权不是「功能没了」，而是「多点一次确认」。

**抽取时机**：Task 进入终态时异步触发，不阻塞用户拿结果。抽取 prompt 输出结构化数组，每条含 `type`、`content`、`summary`、`evidence_quote`、`importance`。单次任务最多产出 5 条候选，超出按 importance 截断——防止记忆库被垃圾淹没。

### 5.2 混合检索（MEM-3）

```text
query（当前任务描述 + 最近 2 轮对话）
   │
   ├── 向量召回：cosine top-30（按 type 分别召回，避免某类淹没其他类）
   ├── 全文召回：ts_rank top-20
   └── 结构化召回：Episodic 中同 intent / 同 skill 的最近 5 条
   │
   ▼ 合并去重
score = 0.55 * norm(cosine)
      + 0.25 * norm(bm25)
      + 0.10 * recency_decay(updated_at, half_life=90d)
      + 0.10 * (importance / 5)
   │
   ▼ 阈值过滤 score < 0.35 直接丢弃   ← 宁可不给，不给错的
   ▼ 取 top-8 → 按 §5.3 装配
```

**明确不做 cross-encoder rerank**：Phase 1 记忆量级（单用户数百到数千条）下收益有限，增加一次模型调用的延迟与成本不划算。留作 Phase 2 在检索质量成为瓶颈时的优化项。

评测方法（避免"感觉还行"式验收）：

- 构造 50 条 golden query（真实用户任务 + 人工标注应召回的记忆）
- 指标：`recall@8 ≥ 0.8`、`precision@8 ≥ 0.5`
- 每次检索逻辑变更跑一次，结果记入 `docs/eval/memory-retrieval.md`

### 5.3 上下文组装（MEM-4）

固定 token 预算分配，防止任一类记忆挤占：

| 类型 | 默认预算 | 装配策略 |
|---|---|---|
| Preference | 400 | 全量（数量本来就少），超限按 importance 截断 |
| Semantic | 1100 | 检索结果按 score 排序填充 |
| Episodic | 500 | 优先同 intent 的最近 2 条，压缩为「上次做 X 时你选了 Y」 |

装配后的块：

```text
<memory>
  <preferences>邮件用简洁语气，不用敬语套话；数据结论优先给表格。</preferences>
  <facts>
  - 主力产品是 CogniWork，定价 $99/月/席位（来源：你在 8/2 说过）
  - 主要竞品是 WorkBuddy（来源：竞品分析.pdf p3）
  </facts>
  <past>上次做季度报告时，你选择了按渠道拆分而不是按地区。</past>
</memory>
```

**每条记忆带来源**，不只是为了可解释——它让 LLM 在记忆之间冲突时有判断依据，也让用户在结果里看到「它凭什么这么说」。

### 5.4 冲突与时效（MEM-6）

写入 `active` 记忆前做一次冲突检测：

```text
新记忆 N
   │
   ▼ 向量检索同 type 中 cosine > 0.88 的已有记忆
   │
   ├── 无命中 → 直接 active
   └── 有命中 M → LLM 判定关系：
         ├── duplicate   → 丢弃 N，M.updated_at 刷新
         ├── supersedes  → M.status=superseded, M.superseded_by=N.id, N active
         ├── conflict    → 两者都保留但标记，在 Memory Browser 提示用户裁决
         └── unrelated   → N active
```

`superseded` 的记忆不再进检索，但保留在库中，用户可在 Memory Browser 的「历史」里看到「这条在 8/10 被更新过」。

### 5.5 文件摄取（MEM-8）

```text
上传 → 类型识别 → 文本抽取（pdf: pymupdf / docx: python-docx / xlsx: openpyxl）
     → 分块（语义分块，目标 500 tokens，重叠 80）
     → 生成 chunk 级 summary（用小模型，控成本）
     → 向量化 → memory_item(type=semantic, source_type=file_ingest)
```

约束：

- 单文件上限 20MB、200 页；超限提示用户拆分。
- 摄取是**显式动作**——用户上传文件到某个任务时，默认只用于本次任务（临时上下文）；「存入长期记忆」是一个额外的按钮。这个区分很重要：上传≠授权长期保存。

---

## 6. 技术选型与取舍

| 决策点 | 选择 | 理由 |
|---|---|---|
| 向量库 | pgvector HNSW，`vector(1024)` | 计划 §7.7 明确；单用户数千条量级下 pgvector 性能充裕，省一套运维 |
| Embedding 模型 | 单一供应商的 1024 维模型，通过 `EmbeddingProvider` 接口隔离 | 维度写死在 schema 里换模型代价高，故用接口隔离 + 版本字段预留重算路径 |
| 重算策略 | `memory_item` 增加 `embed_model text` 字段，换模型时后台批量重算 | 避免新旧向量混在同一索引里 |
| 全文检索 | PG `tsvector`，config 用 `simple` | 中英混合场景下 `simple` + 前置分词比 `chinese` 配置更可控；中文分词在应用层做 |
| 分块 | 语义分块（按标题/段落），非固定长度 | 固定长度切断表格和列表，对办公文档伤害大 |

> 注：`tsv` 用 `simple` 配置意味着中文需要应用层预分词后再入库。若初期想省事，可先只对英文内容建全文索引，中文完全依赖向量召回，检索质量影响在评测集上验证后再决定是否投入分词。

---

## 7. 接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/memories` | 列表，支持 `type`/`status`/`q`/分页 |
| `POST` | `/api/v1/memories` | 显式写入 |
| `PATCH` | `/api/v1/memories/{id}` | 编辑内容/重要度 |
| `DELETE` | `/api/v1/memories/{id}` | 物理删除 |
| `POST` | `/api/v1/memories/{id}/confirm` | 确认候选 `{action, content?}` |
| `GET` | `/api/v1/memories/pending` | 待确认队列 |
| `POST` | `/api/v1/memories/search` | 调试用检索接口，返回 score 明细 |
| `GET` | `/api/v1/memories/export` | 导出全部（JSON + 附件清单） |
| `DELETE` | `/api/v1/memories?scope_key=` | 按 Scope 批量删除（供 `P0-07` 撤销授权时调用） |

内部服务接口：

```python
class MemoryService:
    def retrieve(self, user_id: UUID, query: str, budget_tokens: int = 2000) -> MemoryBundle: ...
    def propose(self, user_id: UUID, items: list[MemoryDraft], source: SourceRef) -> list[UUID]: ...
    def record_episode(self, task: Task) -> UUID: ...   # 无需授权，系统事实
    def purge_by_scope(self, user_id: UUID, scope_key: str) -> int: ...
```

---

## 8. Memory Browser（MEM-5）前端要点

这是产品里**最重要的信任界面**，不是一个后台管理页：

- 三个 Tab：`事实` / `偏好` / `任务历史`，加一个 `待确认` 徽标。
- 每条记忆卡片必须展示：摘要、来源徽标、写入时间、「用过 N 次」、「查看依据」。
- 「查看依据」跳转到原始任务对话的具体位置或文件的具体页码——**能追溯到原文，用户才会相信删除是真的删除**。
- 支持批量选择删除，以及一个显眼的「清空全部记忆」入口。
- 空状态文案要说明「这里会记录什么、不会记录什么」。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 记忆库被低质量候选污染，检索精度下降 | 高 | 单任务候选上限 5 条；score 阈值 0.35 硬过滤；提供「这条记忆没用」反馈按钮，命中即降 importance |
| 用户看到 AI 记住了自己没意识到说过的话，产生反感 | 高 | 全部 `task_extracted` 走 pending；候选卡片用原话引用（`evidence_quote`）而不是 AI 改写后的表述 |
| 记忆导致输出被旧信息带偏 | 中 | `supersedes` 机制 + 检索时展示时间；冲突记忆强制提示用户裁决而非静默选一个 |
| Embedding 模型切换成本 | 中 | `embed_model` 字段 + 后台重算任务，切换时双写过渡 |
| 文件摄取把大量无关内容变成记忆 | 中 | 上传≠长期记忆，需显式点「存入记忆」；摄取后给出「共 N 个片段，预览前 5 条」的确认步骤 |

---

## 10. 验收标准

1. golden query 集上 `recall@8 ≥ 0.8`、`precision@8 ≥ 0.5`。
2. 检索 P95 延迟 ≤ 200ms（1 万条记忆规模）。
3. 未授权 `memory:preference:auto_write` 的账号，运行 20 个任务后 `status=active` 的 `task_extracted` 记忆条数为 0。
4. 任意一条记忆可在 UI 上追溯到原始出处。
5. 删除一条记忆后，同一 query 的检索结果中不再出现该条，且数据库中物理不存在。
6. 走完 5 个真实任务后，第 6 个任务的输出中可观察到至少一处由记忆带来的个性化差异（人工评估，5 个样本中至少 4 个成立）。

---

## 11. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | 数据模型 + 迁移 + 基础 CRUD | 3d |
| M2 | Embedding 接入 + 混合检索 + 评测集与评测脚本 | 5d |
| M3 | 上下文组装 + 与 Runtime 集成 | 3d |
| M4 | 抽取候选 + 确认流程 | 4d |
| M5 | Memory Browser 前端 | 5d |
| M6 | 文件摄取管线 | 4d |
| M7 | 冲突检测 + 导出/删除/按 Scope 清理 | 3d |

---

## 12. 待决问题

1. ~~中文全文检索是否在 Phase 1 投入分词（jieba/pg_jieba）？~~ → **已决（2026-08-22）：Phase 1 不投入。**
   - **测量结果**：lexical 分量按空白切词，中文一句话是一个 token。`_lexical_overlap("席位价格", "标准席位价格是…")` **= 0** —— 即使查询串是记忆正文的子串也不得分。也就是说中文检索的混合权重里，`0.25 * lexical` 那一项恒为 0，全部由向量召回承担。这条测量由 `tests/test_memory_eval.py::test_chinese_queries_get_no_lexical_signal_without_a_tokenizer` 钉住。
   - **不投入的理由**：A2 的目标市场是海外英语市场（en-US 为交付基线），中文检索质量不影响 Phase 1 退出条件。
   - **代价一侧**：`pg_jieba` 是 PostgreSQL 扩展，官方 `postgres:16` 镜像没有，引入它会把 CI 与生产镜像绑到自定义构建 —— 与 `README.md` 偏离 10「不把 CI 绑到 pgvector」是同一条理由。应用层 jieba 可行，但要把 lexical 检索从 SQL（`tsv @@ plainto_tsquery`）挪到应用层，是检索路径的结构性改动，不是加个依赖。
   - **Phase 2 若开放中文市场**：先评估 **CJK 字符 bigram**（不需要词典、不需要 PG 扩展、可直接进 `_lexical_tokens`），再考虑分词。推翻本条之前先看那条测量是否还是 0。
   - 已登记为 `docs/design/README.md` 偏离 13。
2. ~~Episodic 记忆的保留期限~~ → **已决（B6，2026-08-18 确认默认做法）**：**Phase 1 永久保留**（量级不大），设置中**预留**「自动清理 N 个月前的任务历史」开关，**Phase 2 默认开启**。
   - **「预留开关」必须在 Phase 1 就出现在设置界面上，默认关闭**——不能只留在代码里。理由不是完备性：Phase 2 把它改为默认开启时，如果用户在 Phase 1 从没见过这个开关，那次改动对他们就是「我的历史被无声删掉了」。一个从一开始就在那儿、只是没打开的开关，语义完全不同。
   - 保留期永久不等于不可删。用户主动删除仍走 M7 的「导出 / 删除 / 按 Scope 清理」，且按仓库硬约束**物理删除**，不做软删。
   - Phase 2 改默认值时按新老用户区分：老用户需要一次明确告知与确认，不能靠版本说明带过。
