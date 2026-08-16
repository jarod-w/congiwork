# CogniWork（AI Coworker OS）产品规划 v3 —— 桌面深度集成 + 简化版隐私模型

> 在 v2（优先级重排版）基础上，根据两个明确决策更新：
> 1. 桌面端第一版对标竞品的「深度系统集成」层面（操作本地应用/Computer Use），而非轻壳套版
> 2. 隐私合规模型简化为「员工自行开启 + 员工认可」，不采用面向欧盟的三层合规模型（因产品不面向欧盟市场）

---

## 0. 本版改动说明（相对 v2）

| 改动 | 原因 |
|---|---|
| 桌面端从"轻壳"升级为"含 Computer Use 能力的完整客户端" | 明确要在深度系统集成层面对标 WorkBuddy 等竞品，轻壳套版无法满足 |
| Desktop Computer Use 从"Phase 2 视验证结果决定"提前到 Phase 1 | 竞争定位要求 Phase 1 就要有本地应用操作能力，不能再延后 |
| 桌面自动化脆弱性（原 2.3）从"待评估风险"变为"Phase 1 必须承担并管理的已知成本" | 深度系统集成意味着这个风险从 Day 1 就存在，需要专门的工程量和缓冲预留 |
| 隐私合规模型（原 2.1）简化为"员工自行开启 + 认可"单层模型 | 产品不做欧盟市场，采用更轻量的合规路径；同时标注该模型的适用边界和已知限制 |
| 支持应用范围从"通用操作任意本地应用"收窄为"限定的高频办公应用白名单" | 用范围换风险：深度集成的攻击面/合规面很大，先在可控范围内验证，而非一开始就通用化 |

> v2 中「风险与假设」「信任爬坡」「商业化与冷启动」等章节结构保留，本版仅更新与桌面端、隐私模型相关的具体内容。

### 0.1 产品交付形态（v3 明确结论）

| 形态 | 是否提供 | 说明 |
|---|---|---|
| Web SaaS | ✅ 提供，主入口 | 零安装门槛，承担获客和信任爬坡前两层 |
| Desktop App | ✅ 同时提供，Phase 1 | 不是轻壳套版，而是含本地应用 Computer Use 能力的完整客户端，用于对标 WorkBuddy 等竞品的深度系统集成 |
| 浏览器插件 | 视需要补充 | 用于浏览器内自动化场景（Playwright 相关） |

两端共享同一套账号体系、Memory、Skill 库——用户在 Web 上积累的记忆和 Skill，切换到 Desktop 后可以继续使用，不是两套割裂的产品。

---

## 1. 产品定位（不变）

> 一个会理解用户、学习用户工作方式、沉淀工作经验，并逐渐承担更多工作的 AI 工作伙伴。

对外表述（调整）：

> The AI coworker that learns how you work, remembers your business, and takes the busywork off your plate.

对内战略目标（不变）：

> 从"AI回答问题"进化到"AI理解工作 → AI学习工作 → AI执行工作 → AI优化工作"。

---

## 2. 风险与关键假设（新增，最优先讨论）

在投入任何工程资源前，以下假设必须被验证，否则后续规划都建立在流沙上：

### 2.1 隐私合规风险 —— 采用简化模型（员工自行开启 + 认可），Phase 1 即生效

**决策**：产品不面向欧盟市场，因此不采用面向企业/欧盟劳动法的三层合规模型，改用更轻量的模型：

```text
默认关闭
    ↓
员工个人自行选择开启（不是企业管理员代为开启）
    ↓
开启前有明确的采集范围说明，员工点击认可
    ↓
员工可随时在设置中关闭 / 查看已采集内容 / 删除
```

**这个模型的适用边界，需要明确写清楚（不是免责声明，是产品设计约束）：**

- **"自愿"必须是真实的、可验证的**：产品设计上，不开启该功能时，核心功能仍然完整可用，不能让用户感到"不开启就没法正常用"。如果某个功能变相强制员工开启采集才能使用，那就不是真正的自愿，这一点要写进设计评审的检查项，而不只是写进文档。
- **目标市场边界要清晰**：本模型适用于当前明确不做欧盟、且以美国/其他对"员工自行同意"接受度较高的市场为主的场景。如果未来扩展到中国大陆（PIPL 对员工个人信息、尤其敏感信息有独立于"同意"之外的企业合规义务）或欧盟，需要重新评估这一节，不能直接套用。
- **企业客户场景需要单独说明**：如果产品未来卖给企业（而非仅面向个人用户），即便功能是"员工自行开启"，企业作为购买方/部署方，仍可能需要对外部（如客户数据涉及第三方隐私）承担说明义务，这个属于企业自身合规范畴，产品只负责提供"哪些人在什么时间开启了什么采集范围"的可审计记录，不代替企业做合规判断。

**验证方式不变**：找 5-10 个真实目标用户，展示采集范围和用途说明，看他们是否愿意主动开启。这是 Phase 1 必须跑的前置小实验。

### 2.2 自动工作流挖掘的技术可行性 —— ★★★★ 需先小范围验证

- 从行为日志中自动发现"可复用工作流"并生成可靠 Skill，目前业界（含 Anthropic、OpenAI 的 Computer Use 方向）都还处于早期阶段，3-6 个月做出稳定可用的版本偏乐观。
- **对策**：先做"人工标注 + AI 辅助总结"的半自动 Skill 生成，即用户手动确认"这是一个可重复流程"后，AI 再帮忙把这段操作历史整理成结构化 Skill。全自动挖掘作为 Phase 2 的探索方向，不作为承诺交付物。

### 2.3 桌面深度系统集成（Computer Use）—— ★★★★★ Phase 1 必须承担的已知成本

**决策**：桌面端第一版对标竞品的深度系统集成层面，即支持操作本地应用（类似 WorkBuddy）。这意味着原 v2 中"延后评估"的风险，现在要在 Phase 1 直接管理，而不是回避：

- **技术脆弱性**：PyAutoGUI + Accessibility API 方案对目标应用 UI 变化敏感，维护成本高，跨平台（Win/macOS）行为差异大。**对策**：不追求"通用操作任意本地应用"，第一版限定支持 3-5 个高频办公应用的白名单（如 Excel、浏览器、邮件客户端），每个应用单独适配和维护，出问题时影响范围可控。
- **隐私/权限颗粒度**：操作本地应用通常需要读屏幕内容、模拟点击等更高侵入性权限，比"结构化操作日志"更敏感。**对策**：采用 2.1 节的"默认关闭 + 员工自行开启 + 逐应用授权"模型，且每个应用的授权是独立的开关（比如授权操作 Excel 不等于授权操作邮件客户端）。
- **工程量预留**：这部分应作为 Phase 1 的独立高风险模块管理，预留专门的验收时间和缓冲，不要和其他常规功能混在一起排期，避免因为它的不确定性拖累整体 Phase 1 交付。

### 2.4 冷启动信任问题 —— ★★★★★ 决定产品是否能起步

- 一个"越用越懂你"的产品，在没有积累数据前很难体现差异化价值，用户没有理由留下来"喂"它数据。
- **对策**：见第 8 节「信任爬坡设计」。

---

## 3. 产品总体架构（保留，标注优先级）

```text
                    AI Coworker OS

                         |
 --------------------------------------------------
 |              |              |                  |
Memory OS   Skill Engine   Agent Runtime   Workspace
 (P0)          (P1)           (P0)           (P0)

 |              |              |                  |

用户画像      技能整理       任务执行        工作空间
（手动为主）  （半自动）     （核心能力）    （信任载体）

                         |

              Computer + SaaS Tools (浏览器优先)
```

---

## 4. 核心功能模块（重排优先级）

### P0（Phase 1 必须做）

#### 4.1 Personal Profile（个人画像）—— 不变
AI 主动访谈用户，收集角色、公司背景、业务目标、常用工具、工作偏好。

```json
{
  "role": "Marketing Director",
  "company_context": [],
  "business_goals": [],
  "tools": [],
  "preferences": []
}
```

#### 4.2 Memory System（长期记忆）—— 保留三类记忆，简化实现
- **Semantic Memory**（公司/产品/客户/业务规则/KPI）
- **Episodic Memory**（历史任务、决策记录）
- **Preference Memory**（写作风格、输出格式、工作习惯）

MVP 阶段：Semantic + Preference 用同一个 PostgreSQL + pgvector 存储即可，Episodic Memory 先用普通结构化表记录任务历史，不单独引入 Event Store 或图数据库。

#### 4.3 Task Execution + Chat Workspace —— 提升为最高优先级
这是原方案中被低估的部分。在 Workflow Mining 有意义之前，必须先有一个让用户愿意每天用来"派活"的界面：
- 任务发起、执行过程展示、结果审核
- MCP 工具连接（Slack、Notion、Gmail 等，优先浏览器可达的 SaaS）
- 手动创建 Skill（用户自己描述一个可复用流程，AI 帮忙结构化）

**这里才是积累"真实工作数据"的入口，Workflow Mining 依赖这一步先跑起来。**

#### 4.4 Desktop App + 本地应用 Computer Use（提升为 Phase 1，v3 新增）
桌面端不再是 Web 的轻壳套版，而是承担深度系统集成能力，对标 WorkBuddy 等竞品：

- **支持范围**：第一版限定 3-5 个高频办公应用白名单（如 Excel、浏览器、邮件客户端），不追求"通用操作任意本地应用"
- **每应用独立授权**：员工自行开启，逐应用授权（授权操作 Excel 不代表授权操作邮件客户端），默认全部关闭
- **技术方案**：PyAutoGUI / Accessibility API，针对白名单内应用单独适配，出问题时影响范围可控
- **管理方式**：作为独立高风险模块管理，单独预留工程量和验收缓冲，不与常规功能混排

---

### P1（Phase 2 探索，非承诺交付）

#### 4.5 Workflow Recorder（重新设计，仅采集结构化操作）
不采集屏幕/键鼠原始流。只记录：应用内的结构化操作事件（工具名、动作类型、输入输出摘要），并且默认关闭，按场景显式授权开启。

#### 4.6 半自动 Skill 生成
```text
用户手动标记"这是一个可重复流程"
        ↓
AI 整理该流程的操作历史
        ↓
生成结构化 Skill 草稿
        ↓
用户确认/修改
        ↓
纳入 Skill 库，可复用
```

全自动 Workflow Mining（无需用户标记、AI 主动发现重复模式）作为探索方向，视 Phase 2 中期的技术验证结果决定是否投入。

扩展 Computer Use 应用白名单范围（超出 Phase 1 的 3-5 个应用）也放在这一阶段，视 Phase 1 验收结果决定扩展节奏。

---

### P2（Phase 3，企业化阶段）

#### 4.7 Multi Agent Team
在个人助手验证有效后，再扩展到多 Agent 协作（Research / Marketing / Sales / Finance 等角色 Agent）。

---

## 5. 信任爬坡设计（新增，第8节核心内容前移到此）

产品能否成立，取决于用户是否愿意持续授权采集其工作数据。这不是靠隐私条款一次性解决的，需要产品层面的渐进式设计：

```text
第一层：单次任务代劳（无需长期授权）
  用户粘贴文本/上传文件，AI 完成一次性任务
        ↓ 建立初步信任
第二层：连接只读工具（Gmail只读、日历只读）
  AI 能看到，但不能替用户操作
        ↓ 看到价值后
第三层：授权执行类工具（发邮件、建任务）/ 授权桌面端操作指定本地应用
  每次执行前有明确的审核/确认环节；本地应用操作按应用逐一开启，默认全部关闭
        ↓ 长期使用后
第四层：授权结构化操作日志采集
  用户明确知道采集范围、可随时关闭、可查看/删除已采集内容
```

每一层都应该让用户清楚看到"多授权一点，AI 能多做什么"，而不是一次性要求全量权限。

> v3 说明：桌面端 Computer Use 提前到 Phase 1，但授权仍然走信任爬坡第三层的逻辑——员工需要逐应用主动开启，不是安装桌面端就默认获得全部本地应用操作权限。

---

## 6. 产品开发路线（重排）

### Phase 1：AI Personal Assistant + 信任基础设施 + 桌面 Computer Use（0-3个月，v3 范围扩大）

功能：
- **Web SaaS**（主入口，Chat Workspace，零安装门槛）
- **Desktop App**（同时提供，含本地应用 Computer Use，白名单 3-5 个应用）
- Memory System（Semantic + Preference，PostgreSQL+pgvector）
- 文件理解、MCP 工具连接（优先只读权限）
- Task 执行 + 人工审核环节
- 手动 Skill 创建
- **隐私授权机制（员工自行开启 + 认可，逐应用/逐场景授权）**

验证目标（明确的退出条件，而非只是功能清单）：
- 至少 N 个真实用户愿意进入信任爬坡第三层（授权执行类操作 / 授权桌面本地应用操作）
- 用户自发创建 ≥ 3 个手动 Skill 并复用
- **桌面 Computer Use 白名单应用的操作成功率达到可用阈值（建议 ≥ 90%），作为该模块的独立验收标准**

> 风险提示：桌面 Computer Use 提前到 Phase 1，会占用原本分配给 Chat Workspace / Memory System 的一部分工程资源，建议将其作为独立子团队/独立里程碑管理，避免拖累核心 SaaS 体验的交付时间。

### Phase 2：Workflow Learning + Computer Use 范围扩展（3-6个月，视 Phase 1 验证结果决定投入规模）

新增：
- 结构化操作日志采集（非录屏，默认关闭，逐场景授权）
- 半自动 Skill 生成（用户标记 + AI 整理）
- 浏览器自动化（Playwright）
- 桌面 Computer Use 应用白名单扩展（视 Phase 1 稳定性验收结果决定扩展节奏）
- 探索：自动发现重复模式（不承诺，作为研究方向）

### Phase 3：AI Employee OS（6-12个月）

新增：
- Multi Agent Team
- Agent Marketplace
- 企业知识库、企业 Workflow 自动化
- 桌面 Computer Use 从白名单模式扩展为更通用的本地应用支持（视前序阶段验证结果决定）

---

## 7. 技术实现方案（v3 更新：Web + Desktop 双端并行）

### 7.1 总体技术架构

```text
                 AI Coworker OS

              Web UI          Desktop UI（Electron 壳 + 本地 Agent）
                 |                       |
              Agent Orchestration Layer
                         |
 ------------------------------------------------
 |              |                                |
Memory OS   Skill Engine                    Task Runtime
                         |
              Tool Execution Layer
                         |
   浏览器 Automation / SaaS Connector / File System
                         |
        本地 Computer Use（仅 Desktop 客户端，白名单应用）
```

### 7.2 Client（Web + Desktop 并行）

**Web SaaS**（主入口）：
```text
React + TypeScript + TailwindCSS
```

**Desktop App**（同时提供，含 Computer Use 能力）：
```text
Electron + React + TypeScript
+ 本地 Agent 进程（Python，负责 PyAutoGUI / Accessibility API 调用）
```

两端共享同一套前端组件和后端 API，Desktop 端在此基础上额外增加：
- 本地 Agent 进程，负责白名单应用的操作执行
- 逐应用授权管理界面（权限开关、审计日志查看）
- 系统托盘、开机自启等桌面集成

Rust 目前不引入：白名单应用的自动化用 Python 生态（PyAutoGUI/Accessibility API）已够用，只有明确遇到性能瓶颈或需要更底层系统权限时才评估引入，避免过早增加语言栈维护成本。

### 7.3 Frontend
```text
React + TypeScript + TailwindCSS + shadcn/ui
```
页面：AI Home / Task Workspace / Memory Browser / Skill Library

### 7.4 Backend
```text
Python + FastAPI + PostgreSQL + Redis
```

### 7.5 Agent Runtime
Phase 1 使用 LangGraph（状态机 Agent、长任务、Human Approval）。是否自研，视 Phase 2 需求复杂度再评估，不在 MVP 阶段投入。

### 7.6 LLM Layer
Model Router：按任务类型分发到不同模型（无需一开始接入所有模型商，先支持 1-2 家跑通，再扩展）。

### 7.7 Memory OS（简化为两件套）
```text
Semantic + Preference Memory: PostgreSQL + pgvector
Episodic Memory: PostgreSQL 结构化表（暂不引入独立 Event Store）
```
知识图谱（Neo4j）延后到 Phase 3，企业级知识管理需求明确后再引入，避免 MVP 阶段维护三套异构存储。

### 7.8 Workflow Learning（Phase 2）
采集应用级结构化事件（非屏幕/键鼠原始流）：

```text
Structured App Event Stream
        ↓
用户标记可复用流程
        ↓
AI 辅助整理 → Skill 草稿
        ↓
用户确认 → 纳入 Skill 库
```

### 7.9 Skill Engine
Skill 对象结构不变：
```json
{
  "name": "",
  "description": "",
  "trigger": "",
  "input_schema": "",
  "workflow": "",
  "tools": "",
  "success_rate": ""
}
```

### 7.10 Tool Integration
统一走 MCP 协议，优先支持浏览器可达的 SaaS（Slack、Notion、Gmail、GitHub），Desktop MCP 延后。

### 7.11 安全架构
- Local First：敏感数据加密存储在用户设备（SQLite + SQLCipher）
- **采集范围最小化**：默认关闭全部采集，逐场景显式授权，用户可随时查看/删除已采集数据
- 明确列出合规目标（GDPR、CCPA、SOC2）作为 Phase 1 后期的验收项，而非可选项

---

## 8. MVP 技术组合（v3：Web + Desktop 并行）

| 类别 | 技术 |
|---|---|
| Web Client | React / TypeScript / TailwindCSS |
| Desktop Client | Electron + React / TypeScript + 本地 Agent（Python） |
| Backend | Python / FastAPI / PostgreSQL / Redis |
| AI | LangGraph / Claude API / MCP |
| Memory | PostgreSQL + pgvector（Neo4j 延后） |
| Automation | Playwright（浏览器）+ PyAutoGUI/Accessibility API（桌面白名单应用，Phase 1 提前投入） |

---

## 9. 开发优先级（v3 重排）

| 能力 | 优先级 | 说明 |
|---|---|---|
| Task Execution + Chat Workspace（Web） | ★★★★★ | 数据积累入口，必须先做好，且是零门槛获客的主战场 |
| Memory OS（简化版） | ★★★★★ | 个性化的基础 |
| 隐私授权机制（员工自行开启+认可） | ★★★★★ | 决定产品能否起步的前提，Phase 1 即需完整落地 |
| **桌面 Computer Use（白名单应用）** | **★★★★★** | **v3 提前到 Phase 1，用于对标竞品的深度系统集成能力，需独立里程碑管理** |
| 手动/半自动 Skill 生成 | ★★★★ | 比全自动挖掘更现实 |
| 浏览器 Computer Use | ★★★★ | 与桌面 Computer Use 并行，覆盖 SaaS 场景 |
| Workflow Recorder（结构化日志） | ★★★ | 需先验证用户授权意愿 |
| 全自动 Workflow Mining | ★★ | 探索方向，非承诺交付 |
| Multi Agent | ★★ | Phase 3 再投入 |
| Computer Use 应用白名单扩展 | ★★ | Phase 2，视 Phase 1 稳定性验收结果决定 |
| 知识图谱（Neo4j） | ★ | 延后到企业级需求明确后 |

---

## 10. 商业化与冷启动（新增）

原方案缺失这一部分，是导致技术规划无法落地验证的主要原因之一。

### 10.1 目标用户（需明确，建议先聚焦一类）
- 优先建议：个人知识工作者中，任务重复度高、单次任务价值明确的角色（如销售、运营、市场），而非泛化的"所有人"。

### 10.2 冷启动策略
- 用「单次任务代劳」而非「长期学习」作为获客钩子——用户第一次使用就要能看到价值，不需要等待"AI学会我的工作方式"。
- 典型场景：一次性文件整理、一次性报告生成、一次性邮件起草，先证明"这次任务省了我多少时间"，再引导进入信任爬坡的下一层。

### 10.3 定价方向（待验证，不做最终结论）
- 按任务量/按 Agent 席位/按企业席位三种模式需要通过用户访谈和早期付费测试来验证，本轮规划不下定论。

---

## 11. 核心竞争壁垒（保留，补充前提条件）

真正的壁垒仍然是：

1. **工作数据**——但前提是用户愿意持续授权，这依赖第5节的信任爬坡设计能否成立
2. **Skill 资产**——但需要先验证半自动生成路径的可用性，而非依赖尚未成熟的全自动挖掘
3. **Personal Memory**——长期理解用户和企业
4. **Workflow Automation**——从辅助走向承担更多工作，但应逐步扩大范围，而非一步到位替代用户

> 真正的护城河不是 Agent 数量，而是对用户工作方式的理解，以及在用户充分信任、明确授权基础上不断积累的数字化工作经验。

---

## 12. 最终产品形态（保留，表述微调）

```text
AI理解工作
    ↓
AI学习工作（在用户明确授权范围内）
    ↓
AI执行工作（保留审核环节，逐步扩大自动化范围）
    ↓
AI优化工作
```

> 每个人、每家公司，都拥有一个理解自己工作方式、可信赖、可逐步放权的 AI 工作伙伴。
