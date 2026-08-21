# CogniWork Phase 1 待办

> **这是进度的唯一事实来源。** 决策的来龙去脉在 [`docs/design/P0-open-questions.md`](docs/design/P0-open-questions.md)，设计细节在各模块文档，本文件只回答「下一步做什么、按什么顺序」。
>
> 每条待办都标了**出处文档与章节**。动手前读那一节 —— 这里的一行字装不下设计意图，写在这里的估时也只是搬运，改动请回到出处文档改。

| 项 | 值 |
|---|---|
| 周期 | **3.5 个月**（约 76 工作日/人 × 5 人），A9 定案 |
| 需求量 | 约 **319 人日**（302 + 2026-08-21 核对补入 17），有效容量 304（20% 损耗）/ 285（25%） |
| 余量 | **约 −15 人日**。2026-08-22 已交付补齐项中的约 14 人日，但**余量不因此变好** —— 那 14 人日是花掉的，不是省下的。剩余待办见 §补齐项 |
| 更新方式 | 完成一项勾掉；范围有变先改出处文档，再改这里 |

**图例**：`⛔` 阻塞其他工作 · `🔒` 被外部因素卡住 · `⚡` 关键路径 · `🧪` 守护/验收测试

---

## 阶段 0 · 立项第 1 周（并行启动，不占开发主线）

三个「序 0」阻塞项 + 两个执行动作。**共同点是产出时间不由写代码的速度决定**，晚启动会在中后期造成排期塌方。

- [ ] ⛔🔒 **提交 Google 应用验证 + CASA** — `P0-05` §2.1.1、§11 M0 — 3d + 不可控等待
      - 前置：公司实体、隐私政策页、已验证域名、应用首页、demo 视频
      - **隐私政策页与 `P0-07` §10 的市场边界声明是同一份产出**，合并做
      - 这是唯一一个我们控制不了周期的前置项。它自身只 3 人日，却定义了关键路径的形状
- [ ] ⛔ **核实 `gmail.send` 属 sensitive 还是 restricted** — `P0-05` §2.1.1 ⚠️、§12.3 — 0.5d
      - 决定「只发不读」降级预案是否成立，而那是 A10 结论的支点
      - 若它也是 restricted，Gmail 整体推迟到候选池，邮件回退为桌面端独担
      - **核实结果要回写 `P0-05` §2.1.1**，不要只留在个人笔记里
- [ ] ⛔ **前置用户实验招募** — `P0-07` §11、`P0-open-questions.md` §3 — 与设计并行，不串行
      - 口径：8–10 名海外市场/运营岗、非熟人。招募难度高于国内同岗位
      - 两周凑不满 8 人就降到 5 人开跑（`P0-07` §11 末段）
- [ ] ⛔ **P0-08 D0 桌面 L1 接口预研** — `P0-08` §13 D0 — 8d（1 人独立）
      - Go/No-Go 检查点。含 macOS 上 openpyxl 对常见 Excel 操作的覆盖面盘点
- [ ] **CASA 预算 + B1 法务确认**（已定合并推进） — `P0-05` §12.4、`P0-07` §15.1
      - **年度复评容易被漏** —— 它是长期运维成本，不是项目一次性投入

### 实验里必须问到的问题

不额外安排用研，在同一场实验里问完（`P0-open-questions.md` §3）：

- [ ] 「你的工作邮箱是 Gmail / Google Workspace，还是 Outlook / Microsoft 365？」
      → **`P0-08` §2.1 触发表的唯一判据**。决定「CASA 不过」这个风险的实际规模
- [ ] 「你平时的活主要在哪几个工具里干？」 → `P0-05` §2.2 候选池排序的唯一合法数据来源
- [ ] 「你有权在你们公司的 Slack 里安装应用吗？」 → Slack 在候选池中的排位（B4）
- [ ] 授权卡片四段式能否被读懂（用**英文**原型测） — `P0-07` §6.1、A8
- [ ] 题库措辞：`writing_tone` 三段例句是否可辨识、`first_task` 能否问出具体任务 — `P0-01` §5.1.1

---

## 阶段 1 · 地基（第 1 周）

**部分已完成**，见文末「已完成」。剩下的：无。本阶段五项均已完成。

---

## 阶段 2 · 零授权闭环（第 2–3 周）⚡

**目标路径已跑通**（2026-08-18）：「注册 → 跳过访谈 → 上传 xlsx → 整理成周报 → 下载」，由 `tests/e2e/test_zero_auth_path.py` 守护。

2026-08-21 核对重新打开的三项已于 **2026-08-22 补齐**。

### 后端 · Agent Runtime

- [x] ⚡ **Task 模型 + 状态机 + TaskEngine 门面** — `P0-03` §11 M1 — 4d
- [x] ⚡ **LangGraph 图 + checkpointer + 基础 act 循环** — `P0-03` §11 M2 — 5d + 补齐 3d（2026-08-22）
      - 已交付：plan → act → observe → finish 图、act 循环、与状态机对接
      - **RT-5 已达**：`store_backend=postgres` 时 checkpointer 是 `PostgresSaver`（表由它自己的
        migration 建，不进 `cogniwork.migrate`）；`messages` / `used_memories` / `blocked_scopes` /
        `pending_calls` / `skill_cursors` 落 `task_runtime_state`（`runtime/state.py` + `0008`）
      - `thread_id` 跟着 task 走（原先每次 invoke 换新 id，等于没有 checkpoint）；
        显式 resume 换新 thread_id，否则图已在 END 上
      - 启动时 `recover_interrupted()` 把停在 `running` / `planning` 的任务接回去；
        `waiting_approval` 不自动推进（它在等人）
      - 🧪 `tests/test_runtime_recovery.py`：第二个 engine 代表重启后的进程，
        不共用任何进程内状态，必须仍能认出任务挂在哪个工具调用上并执行原参数
- [x] ⚡ **工具抽象层 + builtin 工具 + 权限钩子** — `P0-03` §11 M3 — 4d
      - 🧪 **权限钩子接好后，启用 `tests/guards/test_no_bypass.py` 里那条 skip 的动态测试**
        （mock `ConsentService` 返 DENY，断言无上游调用发生 — `P0-07` §8.2）
      - builtin 只读工具 `scope_key=None`，走 `ConsentDecision.ALLOW` 那一支
- [x] ⚡ **SSE 事件流 + 断线补发** — `P0-03` §11 M5 — 3d
      - 事件词表已在 `packages/shared-types/src/events.ts`，两边必须一致（有守护拦）
- [x] **Model Router + LLMClient 抽象（Anthropic + OpenAI）** — `P0-03` §11 M6 — 4d

### 前端 · 任务工作台

- [x] ⚡ **布局骨架 + 会话/任务列表 + 输入框** — `P0-04` §10 M1 — 4d + 补齐 1d（2026-08-22）
      - 三栏布局，右栏「凭什么」面板默认展开 — `P0-04` §3
      - ⚠️ **布局需容纳英文文案约 30% 的长度增长**（A8 落实要求 ③ / `P0-04` §5）
      - **WS-1 已达**：`GET /api/v1/tasks?q=` 匹配标题 + 原始请求正文，`TaskList` 带搜索框（250ms 去抖）。
        过滤在服务端 —— 本地只有已加载的那一页，在前端过滤会漏掉真正的历史
      - 顺手修了 `styles.css` 里一个坏掉的 `@media`（少了开头那行，整段响应式规则是死的），
        单列断点因此从来没生效过 —— 与 A8 落实要求 ③ 直接相关
- [x] ⚡ **SSE 接入 + 流式消息渲染 + 性能优化** — `P0-04` §10 M2 — 5d
- [x] ⚡ **文件上传 + 产物面板** — `P0-04` §10 M5 — 4d + 补齐 1d（2026-08-22）
      - ⚠️ **上传不加 Scope**。Web 上传是每次显式选择，属 L1 — `00-conventions.md` §3 注、`config/scopes.yaml` 末尾说明
      - **WS-5 已达**：`GET /api/v1/artifacts/{id}/preview` 返回四种 kind（table / markdown / text / image），
        xlsx/csv/md/docx/png 全覆盖。解析在服务端（`runtime/preview.py`）：解析器已经在这边、
        `<img src>` 带不了 Bearer header、截断要在送给浏览器之前做
      - 预览不加 Scope —— 读的就是用户刚拿到的那份产物
- [x] **执行时间线组件** — `P0-04` §10 M3 — 4d

### 验收

- [x] 🧪 **零授权 E2E 套件跑通且是绿的** — `P0-07` §8.3、§14 M6 — 2d
      - 断言：全程 `consent_record` 表为空，任务成功完成
      - **这条挂了等同 P0 缺陷**（硬约束 5）

---

## 阶段 3 · 记忆与工作台完善（第 4–7 周）

### Memory OS

- [x] **数据模型 + 迁移 + 基础 CRUD** — `P0-02` §11 M1 — 3d
- [x] **Embedding 接入 + 混合检索 + 评测集与评测脚本** — `P0-02` §11 M2 — 5d
      - 仍一套 PostgreSQL 存储、不引入独立向量库。CI 官方 `postgres:16` 无 `vector` 扩展，embedding 列用 `real[]`，余弦在应用层；生产可迁 pgvector HNSW
- [x] **上下文组装 + 与 Runtime 集成** — `P0-02` §11 M3 — 3d
- [x] **抽取候选 + 确认流程** — `P0-02` §11 M4 — 4d
- [x] **Memory Browser 前端** — `P0-02` §11 M5 — 5d
- [x] **文件摄取管线** — `P0-02` §11 M6 — 4d
- [x] **冲突检测 + 导出/删除/按 Scope 清理** — `P0-02` §11 M7 — 3d
      - **Episodic 记忆 Phase 1 永久保留**，但「自动清理 N 个月前」的开关**必须在设置界面上出现（默认关闭）** — B6、`P0-02` §12.2
      - 删除是**物理删除**，不是隐藏

### 审批与授权界面

- [x] **审批中断/恢复 + ApprovalRequest** — `P0-03` §11 M4 — 4d
      - 🧪 irreversible 在任何配置下都产生 ApprovalRequest，守护已就位
- [x] **审批卡片（email / table / diff 三种预览器）** — `P0-04` §10 M4 — 5d
- [x] **授权卡片组件 + 内联授权流程** — `P0-07` §14 M2 — 4d
      - 四段式结构缺一不可；两个按钮**视觉权重相同**，「先不用」不做成灰色小字 — `P0-07` §6.1
      - ⚠️ 可用连接器**从 Scope 注册表动态读取，不得硬编码** — `P0-04` §4.3 注
- [x] **内联授权引导 + 顺手沉淀卡片** — `P0-04` §10 M7 — 4d
- [x] **上下文透明面板** — `P0-04` §10 M6 — 3d

### 审计与隐私中心

- [x] **执行审计日志 + 分区 + 脱敏** — `P0-07` §14 M3 — 3d + 补齐 1d（2026-08-22）
      - 只记「做了什么」不记「内容是什么」；收件人存数量与哈希 — 硬约束 8
      - **执行者已就位**：`cogniwork.maintenance`（`audit-retention` 子命令）建未来分区 + drop 过期分区，
        cron 写进 `docs/deploy.md` §8.1；建分区那一半 API 启动时也跑一次（失败不阻塞启动）
      - 分区逻辑只有一份实现（Python，有单测），**不在迁移里写第二份 plpgsql**；
        DEFAULT 里落在区间内的行先挪走再 ATTACH，否则 PostgreSQL 拒绝创建
      - **DEFAULT 仍然留着**（安全网），所以它里面的过期行靠 `DELETE` 回收，不是 drop ——
        这是留 DEFAULT 的代价，不是漏掉的一步
- [x] **隐私中心 UI** — `P0-07` §14 M4 — 5d
- [x] **撤销/导出/删除全链路 + 备份失效验证** — `P0-07` §14 M5 — 4d
      - 账号删除 72 小时内完成含备份；`consent_record` 匿名化保留（B1）

---

## 阶段 4 · 画像与只读连接器（第 6–9 周）

信任爬坡 L1→L2。画像六项全部达标（`P0-01` §9 验收 3/4/5 各有测试）。工具集成层曾重开两项，已于 2026-08-22 补齐。

### 个人画像

- [x] **数据模型 + CRUD API + Profile 页** — `P0-01` §10 M1 — 3d
      - ⚠️ `profile.user_id` 用**部分唯一索引** `WHERE archived_at IS NULL`，不是 `UNIQUE`（B7 的硬性连带）— `P0-01` §4
- [x] **访谈状态机 + 题库 + 结构化抽取** — `P0-01` §10 M2 — 5d
      - 题库按 A1（市场/运营）锚定 — `P0-01` §5.1.1
      - 访谈三轮全做（A9 不砍范围）；缩到 2 轮是 A9.1 预案第四刀
- [x] **上下文注入 + 缓存** — `P0-01` §10 M3 — 2d
- [x] **增量候选与确认 UI** — `P0-01` §10 M4 — 3d（依赖 `P0-04` 任务结果卡片）
- [x] **导出/删除 + 自愿性验收测试** — `P0-01` §10 M5 — 2d
- [x] **归档 + 新建**（换公司/换岗位，仅手动触发） — B7、`P0-01` §11.2
      - 已归档 Profile 不再注入任何上下文，但保留可读可导出
      - **不做自动检测** —— 能触发这类猜测的信号都来自我们本不该拿来推断的数据

### 工具集成层

- [x] ⚡ **MCP Client 接入层 + Tool Registry + ToolSpec 映射** — `P0-05` §11 M1 — 5d + 补齐 2d（2026-08-22）
      - 已交付：JSON-RPC 子集（initialize / tools/list / tools/call）、Tool Registry、ToolSpec 映射、
        `python -m cogniwork.tools.mcp_server` 的 stdio 入口
      - **传输已接线**：`mcp_transport` 默认 `stdio`（连接器独立进程，崩溃不带上 API，
        token 走子进程环境所以不跨用户共享）；`inprocess` 只给单测 —— 子进程拿不到测试注入的 transport。
        填其它值**启动即报错**，静默回落等于悄悄取消隔离要求
      - 🧪 `tests/test_mcp_transport.py` 真起子进程走一遍，并覆盖崩溃 / 超时收成 ToolResult
      - streamable-http 仍未实现，已登记为 `docs/design/README.md` **偏离 11** ——
        「支持接入」这句话在文档里读起来像已经有了
- [x] **Credential Vault（信封加密）+ OAuth 流程** — `P0-05` §11 M2 — 4d + 补齐 1d（2026-08-22）
      - 🧪 凭据在日志、错误上报、trace 中均无明文（守护 `test_no_credential_leak.py` 已就位）— 硬约束 9、`P0-05` §10.6
      - 🧪 OAuth 请求范围不超出已开启 Scope 的最小集合（守护 `test_oauth_scope_minimization.py`）— `P0-05` §10.4
      - **§10 验收 2 已达**：`disconnect` 先调第三方 revoke（Google `oauth2/revoke`、
        GitHub `DELETE /applications/{id}/grant`）再删本地凭据 —— 顺序反了就没 token 可撤了。
        **Notion 没有 token 撤销端点**，API 如实返回 `upstream_revoked: false` +
        `provider_has_no_revoke_endpoint`，不假装撤掉了
      - 上游撤销失败仍删本地凭据并记 `last_error`：本地不留是我们能保证的那部分
      - 🧪 `tests/test_disconnect_revoke.py` 含一条顺序守护
- [x] 🔒 **Gmail + Google Calendar + Notion 连接器（只读）** — `P0-05` §11 M3 — 6d
      - ⚠️ **按「Calendar + Notion 先做、Gmail 最后做」拆序**（A10 落实要求 1）
        这样 G2 触发降级预案时，受影响的是里程碑尾部而不是整个 M3
- [x] **GitHub 连接器** — `P0-05` §11 M4 — 3d
      - 只做「三个 risk 等级各一个代表工具」，不追求覆盖面
      - 它是审批链路的验证载体，**不依赖任何外部审核** —— 这正是不能用 Gmail 替代它的原因
- [x] **连接管理 UI + 活动记录** — `P0-05` §11 M7 — 4d

---

## 阶段 5 · Skill 与写能力（第 8–12 周）

信任爬坡 L3（SaaS 侧）。Skill 八项与 Custom Provider、资源治理全部达标（B8 嵌套、dry-run、SSRF、`preset_copy` 排除各有测试）。`P0-05` M6 曾重开，已于 2026-08-22 补齐。

- [x] **Skill 数据模型 + CRUD + 版本快照** — `P0-06` §10 M1 — 3d
- [x] **自然语言 → Skill 草稿（结构化输出 + 校验）** — `P0-06` §10 M2 — 4d
- [x] **Runtime 集成：按 workflow 驱动执行** — `P0-06` §10 M3 — 5d
      - **嵌套限 1 层，且必须是运行时拒绝**，不能只写在文档里 — B8、`P0-06` §11.2
      - ⚠️ 其他功能不得依赖嵌套能力 —— 它是 A9.1 预案第三刀，被砍时不应连锁返工
- [x] **权限预检 + 参数收集表单** — `P0-06` §10 M4 — 3d
- [x] **Skill 编辑器前端** — `P0-06` §10 M5 — 5d
      - 编辑器必须能渲染「工具未定」状态，不强制先选工具才能存草稿 — `P0-06` §6
- [x] **试运行（dry-run）** — `P0-06` §10 M6 — 3d
- [x] **从任务创建（规范化 + 参数化候选）** — `P0-06` §10 M7 — 4d
- [x] **Library + 推荐 + 预置示例** — `P0-06` §10 M8 — 3d
      - 五个示例里四个零授权；`source='preset_copy'` **不计入退出条件** — `P0-06` §5.5
      - ⚠️ **预置示例的定义文件里不得出现具体连接器名** —— 发送工具在 Phase 1 有三种可能，写死了 CASA 一不过就得改内容重新发版
- [x] **写/不可撤销能力 + 与审批链路联调** — `P0-05` §11 M5 — 4d
- [x] **韧性（重试/限流/熔断）+ 契约测试** — `P0-05` §11 M6 — 3d + 补齐 1d（2026-08-22）
      - 韧性四件齐了：超时、read 重试 / irreversible 不重试、per-(user,provider) 令牌桶、按 provider 熔断
        （`tools/resilience.py`，`test_write_tools.py` 有对应用例）— `P0-05` §6
      - **契约测试就位**：`tests/contracts/upstream_contracts.json` 把 23 个工具「发什么、读哪些字段」
        写死成一份可审阅的清单，`test_provider_contracts.py` 压三条断言：请求形状逐字段比对、
        `depends_on` 声明的字段必须承重（去掉它结果要变，防清单腐烂）、catalog 与适配器不脱节
      - **能力边界写在测试文件的 docstring 里**：离线测试查不出上游今天改了字段 —— 没有任何离线
        测试能。它买到的是「上游发公告时改一个文件，然后由测试告诉你哪些适配器要动」
- [x] **Custom Provider**（SSRF 校验 + 能力探测 + `llm:custom:route`） — `P0-03` §11 M6b — 4d
      - 🧪 **SSRF 防护**：拒绝回环/私网/link-local（云元数据端点）/非 https/重定向，防 DNS rebinding — `P0-03` §7.1 ②
      - 🧪 **能力探测**：不支持 tool-use 强制 schema 就不路由并明确告知，**绝不静默降级成文本解析** — `P0-03` §7.1 ③
- [x] **资源治理 + 错误分类 + finalize** — `P0-03` §11 M7 — 3d
      - 步数 25 / 单任务 $0.50 转审批 / 日额 $5.00 降 `economy` / 墙钟 30min / 用户并发 3
        全部就位；`daily_llm_usage` 是 §8 要求的日次聚合表（定价验证要它）
      - 两个小缺陷进了 §补齐项：`date.today()` 用本地时区、降级到 economy 后没提示用户
- [x] **冷启动模板 + 空状态 + 埋点** — `P0-04` §10 M8 — 3d
      - 埋点口径：「进入 L3」= 授权 L3 Scope **且此后有过成功执行** — `P0-04` §9、A3

---

## 补齐项 · 2026-08-21 文档核对 → 2026-08-22 交付

逐份读 `docs/design/` 与已勾里程碑对账的结果。原计约 17 人日，**已交付约 14 人日**（2026-08-22），剩下的见下。

2026-08-22 交付后 `pytest -q` 是 **250 passed / 4 skipped**（skip 是没起 Postgres），
六个守护文件全绿；`pytest -m release` 如设计预期仍失败于文案审校那条。
前端 `tsc --noEmit` + `vite build` 从**原先就是红的**变绿（两处遗留类型错误顺手修了）。

### 重新打开的里程碑 —— 全部已补齐

| 项 | 缺口 | 补齐 | 状态 |
|---|---|---|---|
| `P0-03` M2 | Checkpointer 是 `MemorySaver`，图状态在进程内 | 3d | ✅ `PostgresSaver` + `task_runtime_state` + 稳定 thread_id + 启动恢复 |
| `P0-05` M1 | stdio 客户端未接线，§3 进程隔离要求未落地 | 2d | ✅ `mcp_transport` 默认 stdio；streamable-http 登记为偏离 11 |
| `P0-05` M2 | 断开连接不调第三方 revoke 端点（§10 验收 2） | 1d | ✅ Google / GitHub 真撤；Notion 无端点，如实告知 |
| `P0-05` M6 | 契约测试缺失 | 1d | ✅ 23 个工具的请求/响应契约 + 依赖字段承重断言 |
| `P0-04` M1 | 无历史任务搜索（WS-1） | 1d | ✅ 服务端 `?q=`，标题 + 原始请求正文 |
| `P0-04` M5 | 产物面板无预览（WS-5） | 1d | ✅ 服务端解析四种 kind，覆盖 xlsx/csv/md/docx/png |
| `P0-07` M3 | 只有 DEFAULT 分区，12 个月保留期无执行者 | 1d | ✅ `cogniwork.maintenance audit-retention` + cron |

**`P0-03` M2 的顺序风险已解除**。阶段 5 的审批链路、写工具、Skill 执行都建在进程内状态上，
每多接一个有副作用的工具返工面就扩大一圈 —— 所以它排在这批的第一个做，而不是按它在哪一阶段。

### 设计文档要求、此前没有任何条目承接的

- [ ] **通知渠道：桌面通知 + 站内消息落库** — B9、`P0-03` §14 待决 1 — 3d
      - **站内消息必须落库**（未读态、已读标记），不能只做前端瞬时提示 ——
        用户关掉客户端时收不到桌面通知，回来必须能看到发生过什么
      - 邮件通知延后。它需要一套独立的事务邮件基础设施（送达率、退信、退订、反垃圾合规），
        **与 Gmail 连接器无关** —— 用用户授权的 Gmail scope 发平台通知是对该授权用途的挪用
- [x] **`P0-07` §10 三条边界声明补全** — 0.5d（2026-08-22）
      - 三条都落在隐私中心顶部（`PrivacyCenter` 的 `cw-boundaries`），双语文案在 `i18n.ts`
      - 第 1 条「不支持企业管理员代员工开启，**这是设计约束不是暂未实现**」= `adminBoundary`
      - 第 3 条「只提供可审计记录，**不代替企业做合规判断**」= `complianceBoundary`
      - ⚠️ **隐私政策页那一份还没做**（与阶段 0 的 Google 验证材料合并做），本条只解决「产品内明示」
- [x] **结掉 `P0-02` §12 待决 1**（中文全文检索是否投入分词） — 0.5d（2026-08-22）
      - **结论：Phase 1 不投入。** 测量结果是中文 lexical 分量恒为 0（连子串都不得分），
        检索完全靠向量召回；`pg_jieba` 是 PG 扩展，引入会把 CI 与生产镜像绑到自定义构建（同偏离 10）
      - 回写到 `P0-02` §12、`docs/eval/memory-retrieval.md`、偏离 13；
        测量由 `test_chinese_queries_get_no_lexical_signal_without_a_tokenizer` 钉住
      - Phase 2 若开放中文市场，先评估 **CJK 字符 bigram**（不需要词典也不需要扩展），再谈分词
- [ ] 🧪 **Scope 交付文案英文母语审校** — `P0-07` §13 验收 3、A8 落实要求 ② — 发版门禁，不计开发工时
      - 14 个 Scope 的 `review_status` 全是 `pending`，`pytest -m release` 因此是红的（设计如此，不阻塞 PR）
      - 审校通过后逐条改 `approved`；**缺任一项不得发版**
- [ ] 🧪 **渗透测试** — `P0-07` §13 验收 7、计划 §7.11 — Phase 1 后期验收项，工时待估
      - 凭据泄露扫描已有守护；**渗透测试此前无承接**
- [ ] **`docs/eval/desktop-adapters.md`** — `README` 评测产出物表、`P0-08` D5 — 随 D5 交付，不另计

### 小缺陷与偏离 —— 全部已修（2026-08-22）

- [x] **`governance.py` 的 `date.today()` 走本地时区** — `00-conventions.md` §2、代码约定 — 0.5d
      - 改用新增的 `core.clock.today()`（UTC）。日额度的日界现在与 `daily_llm_usage` 的记账日界一致
      - 守护也补上了：`test_no_local_timezone_today` 同时拦 `date.today()` 与 `datetime.now()`
- [x] **日额度降级到 economy 后没有提示用户** — `P0-03` §8 — 0.5d
      - 转 economy 时发一条 `message.delta`（`DOWNGRADE_NOTICE`），一个任务只发一次
      - **不进 `messages`**：进了就可能被 `_last_assistant_text` 当成任务结论写进 `result.summary`
- [x] **成本估算是单一费率** — `P0-03` §8 — 0.5d
      - `TOKEN_RATES` 按 (vendor, model) 记，输入输出分开；认不出的模型（含自定义 provider）
        按最贵一档估 —— 低估会让任务在成本闸门前多走几步，而那道闸门是防跑飞的
- [x] **全局 LLM 并发令牌桶** — `P0-03` §8 末行 — 1d
      - `GlobalLlmConcurrency`（`COGNIWORK_LLM_GLOBAL_CONCURRENCY`，默认 16）。满了排队 120s，
        之后按限流失败 —— 与 §6 的限流同一个取舍：让步骤慢一点，别让任务死掉
- [x] **`packages/mcp-connectors` 位置偏离登记** — `P0-05` §3.1 — 0.5d
      - 登记为 `docs/design/README.md` **偏离 12**；根目录 `README.md` 的仓库树也改了

---

## 桌面 Computer Use（独立子团队，全程并行）

**107 人日，含 15d 专用缓冲（不得挪用）。** 详见 `P0-08` §13。

- [ ] D0 技术预研（见阶段 0） — 8d
- [ ] D1 Electron 壳 + shared-ui 复用 + 登录态打通 — 6d
- [ ] D2 本地 Agent 骨架 + 安全 IPC + Supervisor — 7d
- [ ] D3 AppAdapter 抽象 + Runtime 远程 Executor 通道 — 5d ← **依赖 `P0-03` M3**
- [ ] D4 ExcelAdapter（Win COM 8d + macOS openpyxl 8d） — 16d
- [ ] D5 golden set 框架 + 结果校验 + CI 环境矩阵 — 10d
      - 🧪 门禁按 **（适配器 × 平台）逐格判定**，不做跨平台平均 — `P0-08` §8.3、偏离 9
- [ ] D6 MailAdapter — **只做 Graph API** — 4d — B5、`P0-08` §2.1
      - Outlook COM 是触发式补做（G2 未过 + 实验显示 Gmail 占比高 → +3d）；Mail.app 不做
- [ ] D7 BrowserAdapter（CDP） — 8d
- [ ] D8 逐应用授权 UI + 系统权限引导 — 8d
- [ ] D9 执行预览/中断/回滚 — 7d
- [ ] D10 本地加密存储 + 签名分发 + 自动更新 — 9d
- [ ] D11 观测上报 + 诊断 — 4d
- [ ] **桌面 Agent schema 发布为版本化包** — B11、`P0-08` §14.3
      - schema 只允许**向后兼容**变更；破坏性变更走新消息类型
      - **握手交换版本号，对过旧 Agent 明确拒绝而非勉强兼容** —— 桌面端执行有副作用的操作，一次 schema 误解可能不可撤销

---

## 检查点（写进项目节奏，不要等到发现来不及了才讨论）

| 时点 | 检查什么 | 不达标怎么办 | 出处 |
|---|---|---|---|
| **第 1 周末** | **G1** — Google 验证材料是否已提交 | 当周上报，不等月末 | `P0-05` §2.1.1 |
| **第 3 周末** | **容量复核 + G1 合并成一次会**。判据：零授权闭环跑通了没有 + §补齐项的剩余项（B9 通知 3d + 渗透测试待估）怎么排 | 落后 >10% 立即启用预案第一刀 | A9.1、A10 |
| 第 1 个月末 | 第二次容量复核（burn-down） | 同上 | A9.1 |
| **第 2 个月末** | **G2** — Google restricted scope 是否已获批 | 启用「Gmail 只发不读」降级预案 | `P0-05` §2.1.1 |

**触发式预案**（按顺序，够了就停 — A9.1）：

1. macOS 侧只上 Excel（原估 18d，B5 后重算约 **15d**）—— **必须在前期砍**，拖到第三个月末已投入的 macOS 适配全废
2. B8 Skill 嵌套不做 — 3d
3. `P0-01` 访谈缩到 2 轮 — 3d

**不动**：`P0-07`（硬约束底座）、`P0-03` + `P0-04`（核心循环）、`P0-08` 的 15d 缓冲。

---

## 已知风险（不是待办，是要盯着的东西）

| 风险 | 现状 |
|---|---|
| **CASA 周期不可控** | 已从产品级阻塞降为功能风险（A10）。配 G1/G2 + 降级预案 |
| **CASA 未过 × Gmail 用户 = 只有粘贴** | A10 与 B5 叠加产生的盲区。桌面端只做 Graph，覆盖的是 M365 用户，**与 Gmail 用户不重叠，兜不了底**。规模取决于实验的邮箱分布数据 — `P0-08` §2.1 |
| **余量已转负（约 −15 人日）** | 2026-08-21 核对补入约 17 人日，其中约 14 已于 2026-08-22 交付 —— **但那是花掉的，不是省下的，缺口不变**。第 3 周末复核必须处理；预案第一刀（macOS 只上 Excel，约 15d）本来就要求在前期砍 |
| `gmail.send` 档位未核实 | 降级预案的支点。阶段 0 第 2 项 |
| ~~审批链路建在进程内状态上~~ | **已解除（2026-08-22）**：checkpointer 落 PostgreSQL，运行态落 `task_runtime_state`。仍在的约束是**单进程部署** —— SSE 事件总线还在进程内，且启动恢复假设只有一个进程在跑（`docs/deploy.md` §5）|
| **渗透测试仍无承接** | `P0-07` §13 验收 7 的要求。凭据泄露扫描有守护，渗透测试没有人也没有工时估算。Phase 1 后期验收项，越晚安排越可能变成发版前的阻塞 |

---

## 已完成（2026-08-18）

- [x] **Scope 注册表** `config/scopes.yaml` —— 14 个 Scope，六项元数据齐全，en-US / zh-CN 双语 — `P0-07` §3、`00-conventions.md` §3
- [x] **ConsentService.check** —— 权限检查的唯一检查点 — `P0-07` §6.2、硬约束 3
- [x] **注册表加载与校验** —— 启动即校验，不通过服务起不来 — `P0-07` §3
- [x] **CI 守护（静态部分）** —— 四个文件，硬约束 1/2/3/4/6 + A8 落实要求 ① 各有对应断言 — `P0-07` §8.2
- [x] **PR 模板自愿性检查表** — `P0-07` §8.1、`00-conventions.md` §5
- [x] **`core/`** —— 配置（语言不硬编码）、错误模型（受控词表）、UUIDv7、UTC 时间 — `00-conventions.md` §2、§6
- [x] **`packages/shared-types`** —— 错误码、SSE 事件、审批动作；与后端一致性有守护拦 — `00-conventions.md` §6、§7
- [x] **`0001_consent.sql`** —— `consent_record`（append-only）+ `consent_current` + `execution_audit`（按 `created_at` RANGE 分区）— `P0-07` §4、§5.2
- [x] **CI workflow** —— 守护测试与普通测试一起跑；发版检查项只在打 tag 时跑
- [x] 修 `00-conventions.md` 三处与新决策矛盾的地方（Gmail/Slack 示例对调、`file:upload:read` → `file:local:read`、「四项元数据」→ 六项）
- [x] **Consent 落库** —— `PostgresConsentStore`：Redis `consent:{user_id}` hash 优先，未命中回落 `consent_current`；写时失效 — `P0-07` §4
- [x] **`GET /api/v1/scopes`** —— 注册表按请求语言暴露，前端不得复制 — `P0-07` §3
- [x] **授权/撤销 API** —— `POST /api/v1/consent`、`DELETE /api/v1/consent/{scope}`；撤销 append `revoked`；`purge_data` 默认 false（B2）— `P0-07` §6.1、§6.3
- [x] **认证** —— `POST /api/v1/auth/register`、`/login`、`GET /auth/me`；Bearer JWT — `00-conventions.md` §6
- [x] **数据库迁移工具** —— `python -m cogniwork.migrate`；`0002_account.sql`；CI 在测试前跑迁移 — `00-conventions.md` §2
- [x] **TaskEngine + LangGraph act 循环** —— 任务状态机、builtin 工具、权限闸门、SSE 断线补发 — `P0-03` M1/M3/M5/M6
- [x] **零授权工作台** —— `apps/web` 三栏布局 + 上传/产物/时间线；上传不加 Scope — `P0-04` M2/M3
- [x] **零授权 E2E** —— `tests/e2e/test_zero_auth_path.py`：注册 → 上传 xlsx → 周报 → 下载，且 `consent_record` 为空 — `P0-07` §8.3
- [x] **动态无旁路守护** —— mock DENY 后 Executor 不得出网 — `P0-07` §8.2
- [x] **Memory OS** —— `memory_item` / `episodic_record`、混合检索、候选确认、文件摄取、按 Scope 物理删除 — `P0-02` M1–M7
- [x] **审批中断/恢复** —— `ApprovalRequest`；irreversible 在 always-skip-repeat 下仍出审批 — `P0-03` M4
- [x] **工作台完善** —— Memory Browser、审批卡、授权卡、顺手沉淀、上下文记忆、隐私中心 — `P0-04` M4/M6/M7、`P0-07` M2/M4/M5
- [x] **B6 清理开关** —— 设置页可见、默认关闭 — `P0-02` §12.2
- [x] **个人画像** —— Profile 表（部分唯一索引）、访谈状态机、注入缓存、归档+新建 — `P0-01` M1–M5、B7
- [x] **MCP 只读连接器** —— Calendar / Notion / Gmail 只读 + GitHub 三档代表工具、信封加密 Vault、连接管理 UI — `P0-05` M3/M4/M7
- [x] **Skill** —— 数据模型 / CRUD / 版本快照、自然语言与从任务草稿、workflow 驱动（嵌套限 1 层运行时拒绝）、预检、dry-run、Library + 五个预置示例（四个零授权、定义文件不写连接器名）— `P0-06` M1–M8
- [x] **写/不可撤销 + 韧性** —— Gmail / Calendar / Notion 写能力与审批联调；read 可重试、irreversible 不自动重试、按 provider 熔断 — `P0-05` M5
- [x] **Custom Provider** —— SSRF（https / 公网 / 钉死 IP / 不跟随重定向）+ tool-use 探测不静默降级 + `llm:custom:route` — `P0-03` M6b
- [x] **资源治理 + finalize** —— 步数/成本/日额度/并发；部分成功列出未完成项 — `P0-03` M7
- [x] **冷启动模板 + 埋点** —— 零授权任务模板；L3 = 授权且此后有成功执行；`preset_copy` 不计入退出条件 — `P0-04` M8

## 已完成（2026-08-22 · 补齐 2026-08-21 核对出的缺口）

- [x] **RT-5 持久化与恢复** —— `PostgresSaver` checkpointer + `task_runtime_state`（`0008`）+ 稳定 `thread_id` + 启动接回被打断的任务 — `P0-03` M2、§12 验收 1
- [x] **MCP stdio 传输接线** —— `mcp_transport` 默认 `stdio`，未知值启动即报错；崩溃 / 超时收成 ToolResult — `P0-05` M1、§3
- [x] **断开连接调第三方 revoke** —— Google / GitHub 真撤，Notion 无端点如实告知；先撤后删 — `P0-05` M2、§10 验收 2
- [x] **连接器契约测试** —— 23 个工具的请求/响应契约清单 + 依赖字段承重断言 + catalog/实现不脱节 — `P0-05` M6
- [x] **历史任务搜索** —— 服务端 `?q=`，匹配标题与原始请求正文 — `P0-04` M1、WS-1
- [x] **产物预览** —— 服务端解析 table / markdown / text / image，覆盖 xlsx/csv/md/docx/png — `P0-04` M5、WS-5
- [x] **审计分区回收执行者** —— `python -m cogniwork.maintenance audit-retention` + cron — `P0-07` M3、§7
- [x] **`P0-07` §10 三条边界在产品内明示** —— 隐私中心顶部，双语
- [x] **五个小缺陷** —— UTC 日界（含新守护）、economy 降级提示、按模型计费率、全局 LLM 并发桶、偏离登记（11 / 12 / 13）
- [x] **结掉 `P0-02` §12 待决 1** —— 中文分词 Phase 1 不投入，测量与理由已回写

**未完成的部分**：桌面 Computer Use（独立子团队）。阶段 0 的 Google 验证 / CASA / 用户实验招募仍在。
剩余补齐项：**B9 通知渠道（3d）**、Scope 文案英文母语审校（发版门禁）、渗透测试（待估）、`docs/eval/desktop-adapters.md`（随 D5）。

> 核对基线：`27d2733`（只改文档），代码状态基线 `ed4084c`。2026-08-22 的补齐以 `88eb980` 列出的缺口为清单。
