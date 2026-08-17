# P1-01 Workflow Recorder（结构化操作日志采集）设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P1（Phase 2，★★★） |
| 对应规划 | `ai_platform_plan.md` §4.5、§7.8、§5（信任爬坡第四层） |
| 依赖 | `P0-07 隐私授权`、`P0-03 Agent Runtime`、`P0-08 Desktop` |
| 被依赖 | `P1-02 半自动 Skill 生成`、`P1-06 全自动挖掘探索` |
| 前置条件 | **Phase 1 需已验证用户授权意愿**（计划 §9：「需先验证用户授权意愿」） |
| 文档状态 | Draft |

---

## 1. 背景与目标

计划 §4.5 的定位非常克制：「**不采集屏幕/键鼠原始流**。只记录：应用内的结构化操作事件（工具名、动作类型、输入输出摘要），并且默认关闭，按场景显式授权开启。」

这是信任爬坡的第四层——也是最高一层。它的前提是用户已经在前三层建立了足够信任。因此本模块的成败**不主要取决于技术，而取决于 Phase 1 的信任积累是否成功**。

目标：

- **G1** 采集到足以支撑 `P1-02` 半自动 Skill 生成的结构化事件，且不多采一个字节。
- **G2** 采集范围对用户完全透明，且「先看后传」——用户能在数据离开设备前看到它。
- **G3** 逐场景授权，粒度细到「采集我在 Excel 里的操作」而非「采集我的工作」。

非目标（硬约束，不容妥协）：

- ❌ 屏幕录制、截图流
- ❌ 键盘按键记录
- ❌ 鼠标坐标轨迹
- ❌ 剪贴板内容
- ❌ 窗口标题的全量采集（可能含客户名、文件名）

这些不是「Phase 3 再做」，是**产品边界**。一旦越界，前面所有信任爬坡设计都白费。

---

## 2. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| WR-1 | 事件 Schema | 统一的结构化事件定义 | 见 §4 |
| WR-2 | 服务端采集点 | Runtime 内的工具调用天然结构化 | 零额外授权（是系统自身记录） |
| WR-3 | 桌面采集点 | Adapter 动作事件 | 需 `telemetry:desktop_*:collect` |
| WR-4 | 浏览器采集点 | 浏览器插件采集页面级操作 | 需 `telemetry:browser:collect`，Phase 2 后期 |
| WR-5 | 脱敏管道 | 内容摘要化、PII 检测与遮蔽 | 见 §5 |
| WR-6 | 本地缓冲与「先看后传」 | 本地暂存，用户可预览后上传 | 见 §6 |
| WR-7 | 逐场景授权 | 场景化 Scope 而非全局开关 | 见 §3 |
| WR-8 | 保留与删除 | 默认 90 天，可调，可批量删 | 见 §7 |
| WR-9 | 数据查看 | 用户能看到采集到的每一条 | 自然语言呈现 |

---

## 3. 场景化授权设计（WR-7）

计划要求「按场景显式授权开启」。场景的划分要**贴近用户的心智，而非系统的模块边界**：

| Scope | 用户看到的名字 | 采集什么 |
|---|---|---|
| `telemetry:desktop_excel:collect` | 记录我在 Excel 里的操作 | 由 CogniWork 执行的 Excel 动作序列 |
| `telemetry:desktop_mail:collect` | 记录我的邮件处理流程 | 邮件相关动作序列 |
| `telemetry:saas_tools:collect` | 记录我使用连接工具的流程 | MCP 工具调用序列 |
| `telemetry:browser:collect` | 记录我在浏览器里的工作流程 | 页面级操作（Phase 2 后期） |

**关键约束：只采集「CogniWork 参与的操作」，不采集用户自己独立完成的操作。**

这一条值得展开：如果要采集用户自己手动在 Excel 里做的事，就需要常驻监听——那就滑向了「监控软件」，与 §4.5 的克制定位相悖，也会让 §2.1 的自愿模型难以成立。所以采集边界是：**用户委托 AI 做的事被记录下来**，而不是**用户做的所有事被记录下来**。

代价是：能挖掘的模式仅限于用户已经在用 AI 做的事情，覆盖面窄于全量监控。这个代价是**刻意接受的**——它换来的是这个功能在信任模型下是可行的。若产品后续认为覆盖面不足，那是一个需要重新讨论产品定位的决策，不应该由本模块悄悄扩大边界来解决。

---

## 4. 事件 Schema（WR-1）

```json
{
  "event_id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",          // 一段连续工作，超过 15 分钟无事件则切分
  "task_id": "uuid|null",
  "seq": 12,
  "ts": "2026-08-16T10:00:00Z",

  "surface": "desktop|web|browser_ext",
  "app": "excel|gmail|notion|chrome|...",
  "action_type": "read|write|create|update|delete|send|navigate|transform",
  "action": "excel.write_range",

  "target": {                    // 结构，不含内容
    "kind": "range|message|page|record",
    "shape": {"rows": 49, "cols": 1, "sheet_index": 0}
  },
  "input_digest": {              // 摘要，见 §5
    "summary": "填入按渠道计算的转化率",
    "param_keys": ["range", "formula"],
    "value_types": {"range": "cell_range", "formula": "expression"}
  },
  "output_digest": {"status": "ok", "affected": 49},

  "duration_ms": 1840,
  "result": "success|failed|skipped",
  "scope_key": "telemetry:desktop_excel:collect"
}
```

设计要点：

- `target.shape` 而非 `target.value`：记录「改了 49 个单元格」，不记录「改成了什么」。
- `input_digest.summary` 是**一句自然语言**，由执行时已有的 step title 复用，不额外调 LLM。
- 每条事件带 `scope_key`——这样撤销某个 Scope 时能精确删除对应数据（`P0-07` §6.3）。

存储：

```sql
CREATE TABLE activity_event (
  event_id      uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  session_id    uuid NOT NULL,
  task_id       uuid NULL,
  seq           int NOT NULL,
  surface       text NOT NULL,
  app           text NOT NULL,
  action_type   text NOT NULL,
  action        text NOT NULL,
  target        jsonb NOT NULL,
  input_digest  jsonb NOT NULL,
  output_digest jsonb NOT NULL,
  duration_ms   int NULL,
  result        text NOT NULL,
  scope_key     text NOT NULL,
  ts            timestamptz NOT NULL,
  expires_at    timestamptz NOT NULL      -- 写入时即计算，便于自动清理
) PARTITION BY RANGE (ts);

CREATE INDEX ON activity_event (user_id, session_id, seq);
CREATE INDEX ON activity_event (user_id, app, ts DESC);
CREATE INDEX ON activity_event (user_id, scope_key);
```

---

## 5. 脱敏管道（WR-5）

事件在**离开产生它的进程之前**完成脱敏，服务端不做二次脱敏（避免明文曾经存在于网络或日志中）。

```text
原始动作参数
   │
   ▼ ① 白名单投影：只保留 Schema 中声明的字段，其余丢弃
   ▼ ② 值类型化：具体值 → 类型标签（"客户A@x.com" → email_address）
   ▼ ③ 形状提取：集合 → 计数与维度
   ▼ ④ PII 兜底扫描：对残留的自由文本做正则+规则检测
   │      命中（邮箱/电话/身份证/银行卡/长数字串）→ 整字段丢弃（不是打码，是丢弃）
   ▼ ⑤ 长度截断：summary ≤ 120 字符
   │
   ▼ 结构化事件
```

**第 ① 步「白名单投影」是最重要的**：默认丢弃一切未显式声明的字段。这比「黑名单过滤敏感字段」安全得多——新增一个包含敏感内容的参数时，白名单方案默认不采集，黑名单方案默认采集。

第 ④ 步命中时**整字段丢弃而非打码**：打码后的文本仍可能通过上下文还原，且给人「我们看过内容」的印象。

---

## 6. 本地缓冲与「先看后传」（WR-6）

桌面端采集的事件走这条路径：

```text
Adapter 产生事件
   │
   ▼ 本地 SQLCipher 队列（P0-08 §9）
   │
   ▼ 用户可在客户端「待上传数据」中预览（自然语言列表）
   │      "今天 14:20 在 Excel 里填入了 49 个单元格的转化率"
   │      [全部上传] [删掉这条] [全部删掉] [关闭采集]
   │
   ▼ 上传策略（用户可选）：
   │    · 自动上传（默认关闭）
   │    · 每天问我一次（默认）
   │    · 手动上传
   ▼ 服务端
```

「每天问我一次」作为默认值是刻意的：它让采集这件事**持续可见**，而不是开启一次后就消失在后台。这会降低采集量，但显著提高用户对这个功能的掌控感——而掌控感正是这一层能不能被开启的决定因素。

本地队列上限 10 万条 / 200MB，超限丢弃最旧数据并提示用户。

---

## 7. 保留与删除（WR-8）

| 项 | 默认 | 用户可调 |
|---|---|---|
| 保留期 | 90 天 | 30 / 90 / 180 天 / 直到我删除 |
| 自动清理 | 按 `expires_at` 每日 drop 过期分区 | — |
| 按场景删除 | 关闭某 Scope 时可选连带删除 | 见 `P0-07` §6.3 |
| 全部删除 | 隐私中心一键 | — |

删除是物理删除。`P1-02` 已经从事件生成的 Skill 不受影响（Skill 是独立对象），但要在删除确认中告知这一点。

---

## 8. 数据查看 UI（WR-9）

在隐私中心增加「活动记录」的一个 Tab，按会话分组，自然语言呈现：

```text
8月16日 · Excel 相关 · 12 条操作
  14:20  读取了 Q3渠道数据 的 A1:F200 区域
  14:20  计算并填入了 49 个单元格的转化率
  14:22  新建了工作表并生成透视表
                                  [删除这个会话的记录]
```

不展示原始 JSON——用户要能看懂。但提供「查看原始数据」的折叠入口，给关心细节的用户。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 授权率过低，采集量不足以支撑 `P1-02` | 高 | Phase 1 结束时先用 `telemetry:saas_tools:collect`（服务端已有数据，侵入感最低）验证意愿；不达标则 `P1-02` 退回纯「从单次任务创建 Skill」路径（`P0-06` §5.2 已支持） |
| 采集边界被逐步放宽（滑坡） | 极高 | §1 的四条「不采集」写入 `scopes.yaml` 与产品隐私页；任何扩大采集的 PR 强制走 `P0-07` §8.1 评审 + 重新征求同意 |
| 脱敏不彻底，事件中残留敏感内容 | 极高 | 白名单投影 + PII 兜底 + **自动化测试：构造含 PII 的动作，断言落库事件中零命中** |
| 「每天问一次」造成打扰 | 中 | 通知合并为一条；可改为自动或手动；连续 3 次忽略后降频 |
| 数据量增长过快 | 中 | 只采集 AI 参与的操作，量级天然可控（每用户每天数十到数百条）；分区 + 自动过期 |

---

## 10. 验收标准

1. 未授权任何 `telemetry:*` Scope 时，`activity_event` 表零写入（E2E 断言）。
2. 脱敏测试：构造 20 个含邮箱/电话/身份证/金额/客户名的动作，落库事件中 PII 扫描零命中。
3. 采集范围测试：验证不存在任何常驻监听（无屏幕、无键鼠、无剪贴板 API 调用）——用静态检查扫描桌面端依赖与 API 调用。
4. 关闭 Scope 并选择删除后，对应 `scope_key` 的事件物理清零。
5. 「待上传数据」预览中每条都能被用户看懂（可用性测试，5 人中 ≥4 人能正确复述该条记录的含义）。

---

## 11. 交付拆分

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M0 | **授权意愿验证**（用 `telemetry:saas_tools:collect` 做小范围测试） | 5d |
| M1 | 事件 Schema + 存储 + 分区 | 3d |
| M2 | 服务端采集点（Runtime 工具调用） | 3d |
| M3 | 脱敏管道 + PII 测试套件 | 5d |
| M4 | 桌面采集点 + 本地队列 + 先看后传 UI | 6d |
| M5 | 场景化授权 + 保留策略 + 删除链路 | 4d |
| M6 | 活动记录查看 UI | 4d |
| M7 | 浏览器插件采集（后期，视需要） | 6d |

---

## 12. 待决问题

1. `telemetry:browser:collect` 需要浏览器插件，插件本身的权限（读取所有网站内容）在商店审核和用户心理上都是高门槛。建议先不做，观察 `P1-02` 是否真的需要浏览器事件。
2. 保留期默认 90 天 vs 30 天——需在 M0 的意愿验证中一并测试哪个默认值更容易被接受。
