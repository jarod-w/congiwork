# P0-08 桌面客户端与本地应用 Computer Use 设计文档

| 项 | 内容 |
|---|---|
| 优先级 | P0（Phase 1 必须交付，★★★★★，**独立高风险模块**） |
| 对应规划 | `ai_platform_plan.md` §2.3、§4.4、§6 Phase 1、§7.2 |
| 依赖 | `P0-07 隐私授权`、`P0-03 Agent Runtime`、`P0-04 工作台组件` |
| 被依赖 | `P1-01 Workflow Recorder`、`P1-05 白名单扩展` |
| 文档状态 | Draft |

---

## 1. 背景与目标

计划 §2.3 把这块定为「Phase 1 必须承担的已知成本」，且 §6 给了独立验收标准：**白名单应用操作成功率 ≥ 90%**。§231 行还提示要作为独立子团队/独立里程碑管理，避免拖累核心 SaaS 交付。

本文按此定位设计，并对计划中的技术方案提出一项**重要修正**（见 §4）。

目标：

- **G1** 桌面端提供 Web 端无法提供的能力：操作用户本机的应用与文件，对标竞品的深度系统集成。
- **G2** 白名单应用的操作成功率 ≥ 90%，且失败可解释、可恢复、可回滚。
- **G3** 权限颗粒度做到逐应用独立，且比 SaaS 工具更谨慎——因为侵入性更高。
- **G4** 桌面端不是第二个产品：账号、Memory、Skill 与 Web 完全共享（计划 §0.1）。

非目标（Phase 1）：

- 不做「通用操作任意本地应用」（计划 §0 明确用范围换风险）。
- 不做屏幕录制、键鼠原始流采集（这是 §4.5 明确排除的）。
- 不做 Desktop MCP（计划 §7.10 延后）。
- 不做 Linux 支持（Phase 1 仅 macOS + Windows）。

---

## 2. 需求拆分

| 编号 | 需求点 | 描述 | 验收 |
|---|---|---|---|
| DT-1 | Electron 壳与组件复用 | 复用 `packages/shared-ui`，桌面特有布局 | Web 组件改动自动同步 |
| DT-2 | 本地 Agent 进程 | Python 进程，负责应用自动化 | 崩溃自动重启，不影响 UI |
| DT-3 | 安全 IPC | Electron ↔ 本地 Agent 的受控通道 | 仅 loopback + 每次启动轮换 token |
| DT-4 | AppAdapter 抽象 | 统一的应用适配接口 | 新增应用不改 Agent 核心 |
| DT-5 | 首批适配 | Excel、浏览器、邮件客户端（3 个） | 各自 golden set 成功率 ≥90% |
| DT-6 | 逐应用授权 | 独立开关 + 系统权限引导 | 授权 Excel ≠ 授权邮件 |
| DT-7 | 执行可见与可控 | 执行前预览、执行中可中断、执行后可回滚 | 见 §7 |
| DT-8 | 稳定性策略 | 分层定位 + 重试 + 失败上报 | 见 §4 |
| DT-9 | 成功率度量 | golden task set + 每版回归 | 独立验收门禁 |
| DT-10 | 本地数据安全 | SQLite + SQLCipher，签名分发，自动更新 | 计划 §7.11 |
| DT-11 | 系统集成 | 托盘、通知、开机自启、全局快捷键 | |
| DT-12 | 观测与诊断 | 脱敏的失败上报，供适配维护 | 无用户内容外泄 |

---

## 3. 架构

```text
┌─────────────────────────── 用户机器 ───────────────────────────┐
│                                                               │
│  ┌────────────────────────┐                                   │
│  │  Electron 主进程        │  窗口/托盘/通知/更新/权限引导       │
│  │   ├─ Renderer (React)  │  复用 shared-ui                    │
│  │   └─ AgentSupervisor   │  启动/监控/重启本地 Agent           │
│  └──────────┬─────────────┘                                   │
│             │ HTTP over loopback (127.0.0.1:随机端口)          │
│             │ + 每次启动轮换的 Bearer token                     │
│  ┌──────────▼─────────────┐                                   │
│  │  本地 Agent（Python）   │                                   │
│  │   ├─ AdapterRegistry   │                                   │
│  │   ├─ ExcelAdapter      │──▶ COM / AppleScript / openpyxl    │
│  │   ├─ BrowserAdapter    │──▶ CDP (Chrome DevTools Protocol)  │
│  │   ├─ MailAdapter       │──▶ Graph API / AppleScript         │
│  │   ├─ FallbackDriver    │──▶ Accessibility API → PyAutoGUI   │
│  │   └─ LocalStore        │──▶ SQLite + SQLCipher              │
│  └────────────────────────┘                                   │
└───────────────────────────────┬───────────────────────────────┘
                                │ HTTPS
                    ┌───────────▼────────────┐
                    │  后端（同一套 API）      │
                    │  Runtime / Memory /     │
                    │  Skill / Consent        │
                    └─────────────────────────┘
```

**执行权归属**：Agent Runtime 仍在**服务端**。桌面本地 Agent 是一个「远程 Executor」——服务端 Runtime 决定要调用 `desktop.excel.write_range`，通过桌面客户端的长连接下发指令，本地 Agent 执行后回传结果。

这样设计的理由：

1. 权限检查、审批、审计全部在服务端统一，不需要在本地重实现一遍（避免 `P0-07` 的无旁路保证出现缺口）。
2. 桌面端与 Web 端共享同一个 Task 视图，用户在手机/网页上也能看到桌面任务的进度和审批请求。
3. 本地 Agent 保持"哑执行器"定位，攻击面小、可测试性好。

代价是需要一条服务端 → 客户端的下行通道。用客户端主动建立的 SSE 长连接 + 指令拉取，避免入站端口。

---

## 4. 【重要修正】自动化技术方案：分层降级而非 PyAutoGUI 优先

计划 §4.4/§7.2 写的是「PyAutoGUI / Accessibility API」。**本文建议修正为分层降级策略，把 PyAutoGUI 降为最后兜底。**

### 4.1 修正理由

计划 §2.3 自己已经指出：「PyAutoGUI + Accessibility API 方案对目标应用 UI 变化敏感，维护成本高，跨平台行为差异大」。而 §6 又要求成功率 ≥90%。这两者在纯 UI 自动化路径上是矛盾的——基于坐标和控件树的自动化在真实办公环境（不同分辨率、不同 Office 版本、弹窗遮挡、系统主题）下很难稳定到 90%。

而这三个白名单应用**恰好都有远比 UI 自动化稳定的编程接口**。不用它们而去点 UI，是在自找计划里已经预警的那个麻烦。

### 4.2 分层定位策略

每个动作按以下顺序尝试，前一层不可用才降级：

| 层 | 手段 | 稳定性 | 适用 |
|---|---|---|---|
| **L1 原生 API** | Excel: COM (Win) / AppleScript+ScriptingBridge (mac) / openpyxl（文件态）<br>浏览器: CDP<br>邮件: Graph API / AppleScript | 高（不受 UI 变化影响） | **首选，覆盖目标 ≥85% 的动作** |
| **L2 Accessibility 树** | Win: UIAutomation<br>mac: AXUIElement | 中（受版本影响，但有语义） | L1 不覆盖的动作（如某些对话框） |
| **L3 视觉/坐标** | PyAutoGUI + 模板匹配 | 低 | 最后兜底，且**仅在 L1/L2 都失败时使用，并向用户明示"我要用比较笨的方式点界面，可能不准" ** |

L3 的每次使用都记入指标。**如果某个适配器 L3 使用率 > 10%，视为该适配器设计不合格**，需要重新用 L1/L2 实现——这是防止团队图省事全用 L3 的量化门禁。

### 4.3 各适配器的具体路径

| 应用 | 平台 | 主路径 | 说明 |
|---|---|---|---|
| **Excel** | Windows | COM (`win32com`) | 完整对象模型，读写单元格、公式、图表、透视表都稳定 |
| | macOS | AppleScript / ScriptingBridge | 能力弱于 COM，复杂操作降级为「openpyxl 改文件 + 让 Excel 重新打开」 |
| | 两者 | openpyxl（文件态） | 应用未打开时直接改文件，最稳，优先采用 |
| **浏览器** | 两者 | CDP attach 到用户已开的 Chrome/Edge | 复用用户登录态；用 Playwright 的 `connect_over_cdp` |
| | | | 需用户以调试端口启动浏览器 → 由客户端引导并提供一键启动 |
| **邮件** | Windows | Outlook COM | 或 Microsoft Graph（若用户是 M365，走 Graph 更稳） |
| | macOS | AppleScript (Mail.app) / Graph | |

> 浏览器适配与 `P1-04` 浏览器自动化有重叠。边界：本模块负责「操作用户本机已打开的浏览器」（复用登录态），`P1-04` 负责「服务端托管浏览器执行任务」。两者共用一套动作原语，实现分开。

### 4.4 保留 PyAutoGUI 的场景

不是完全不用：系统级弹窗、文件选择对话框、应用未提供 API 的少数交互，仍需 L2/L3。因此 PyAutoGUI 仍在依赖中，只是不作为主路径。

---

## 5. AppAdapter 抽象（DT-4）

```python
class AppAdapter(ABC):
    app_id: str                    # 'excel'
    scope_key: str                 # 'desktop:excel:automate'
    platforms: set[str]            # {'darwin','win32'}

    @abstractmethod
    def probe(self) -> ProbeResult:
        """检测应用是否安装、版本、可用的接入层（L1/L2/L3）"""

    @abstractmethod
    def capabilities(self) -> list[ActionSpec]:
        """本适配器支持的动作，会被映射为 ToolSpec 暴露给 Runtime"""

    @abstractmethod
    def snapshot(self, ctx: Context) -> Snapshot:
        """执行前状态快照，用于预览与回滚"""

    @abstractmethod
    def execute(self, action: str, args: dict, ctx: Context) -> ActionResult:
        """执行动作，返回结果 + 实际使用的层级（L1/L2/L3）"""

    @abstractmethod
    def rollback(self, snapshot: Snapshot) -> bool:
        """尽力回滚；不可回滚的动作在 ActionSpec 中标记"""
```

`ActionSpec` 声明 `reversible: bool`，不可回滚的动作（发送邮件）在服务端映射为 `risk=irreversible`，走强制审批。

新增一个应用 = 实现一个 `AppAdapter` + 提供 golden task set，不改 Agent 核心。这是 `P1-05` 白名单扩展的基础。

---

## 6. 权限模型（DT-6）

三层权限，缺一不可：

```text
① 操作系统权限（macOS 辅助功能 / 自动化；Windows UIAccess）
      ↓ 由客户端引导用户在系统设置中授予，附带图文说明
② CogniWork Scope 授权（desktop:excel:automate）
      ↓ 走 P0-07 的四段式授权卡片，逐应用独立
③ 单次执行审批
      ↓ 走 P0-03 的审批链路
```

关键约束（对应计划 §2.3）：

- **逐应用独立**：`desktop:excel:automate` 与 `desktop:mail:automate` 是两个 Scope，两个开关，两次授权。
- **默认全部关闭**：安装桌面端不获得任何本地应用操作权限（计划 §5 明确）。
- **系统权限申请时机**：不在安装时申请，而在用户第一次开启某个应用授权时才引导。macOS 的「辅助功能」权限提示很吓人，提前申请会造成大量流失。
- **屏幕录制权限**：macOS 上 L3 视觉兜底需要「屏幕录制」权限。这个权限侵入性极高。**设计决策：Phase 1 不申请该权限，L3 兜底在 macOS 上退化为纯 Accessibility 定位。** 若某适配器确实需要，单独作为一个 Scope 申请并说明。

---

## 7. 执行可见与可控（DT-7，信任的关键）

```text
执行前                执行中                  执行后
─────────            ─────────              ─────────
状态快照              悬浮控制条              变更摘要
计划预览              · 当前动作              · 改了哪些单元格
"我将要…"             · [暂停] [停止]         · [撤销这次修改]
[开始] [取消]         · 每步高亮目标区域       · [查看详细记录]
```

要点：

1. **执行前预览必须具体**：不是「我要操作 Excel」，而是「我要在 Sheet1 的 D2:D50 填入计算后的转化率，覆盖现有内容」。这依赖 `snapshot()` 提供当前状态。
2. **执行中始终可中断**：屏幕上有一个常驻悬浮条，随时可停。这是用户敢开启的心理前提——AI 在操作我的电脑时，我必须能立刻叫停。
3. **执行后可回滚**：文件类操作在执行前复制一份到本地 SQLCipher 存储（保留 7 天），一键还原。不可回滚的动作提前标记并强制审批。
4. **鼠标接管提示**：L3 兜底会移动真实鼠标，执行前明确告知「接下来几秒我会控制鼠标，请不要操作」。

---

## 8. 成功率度量与验收（DT-9，独立验收门禁）

计划 §6 要求 ≥90% 成功率作为独立验收标准。需要可度量的定义。

### 8.1 Golden Task Set

每个适配器 **≥25 个任务用例**，覆盖：

| 类别 | 占比 | 例子（Excel） |
|---|---|---|
| 常规路径 | 60% | 读区域、写区域、加公式、排序、筛选、新建 sheet、透视表 |
| 边界情况 | 25% | 空表、10 万行大表、含合并单元格、含中文列名、只读文件 |
| 异常环境 | 15% | 应用未启动、文件被占用、有未保存修改、弹窗遮挡 |

### 8.2 成功的定义

一次执行判定为成功，需同时满足：

1. 动作完成且无异常；
2. **结果校验通过**——不是"没报错就算成功"，而是执行后读回目标状态并与预期比对（写 D2:D50 后读回验证数值正确）；
3. 未产生预期外的副作用（快照比对，未改动其他区域）。

结果校验必须由适配器实现，是 `ActionResult` 的一部分。这条是 90% 这个数字有意义的前提。

### 8.3 回归门禁

| 项 | 要求 |
|---|---|
| 频率 | 每次 PR 跑受影响适配器；每日全量跑一次 |
| 环境矩阵 | macOS 最新 + 前一版；Windows 11 + 10；Office 365 + Office 2021 |
| 门禁 | 单适配器成功率 < 90% → **阻止该适配器进入发布白名单**（而非阻止整个发版） |
| L3 使用率 | > 10% → 告警并作为技术债登记 |
| 报告 | 结果写入 `docs/eval/desktop-adapters.md`，含每个用例的历史趋势 |

「阻止该适配器进入白名单而非阻止整体发版」这个设计很重要：它让适配器可以按各自的成熟度独立上线，符合计划 §2.3「出问题时影响范围可控」的要求，也避免一个应用拖累整体交付。

---

## 9. 本地数据与分发安全（DT-10）

| 项 | 方案 |
|---|---|
| 本地存储 | SQLite + SQLCipher，密钥存 OS Keychain / Windows Credential Manager（计划 §7.11 Local First） |
| 存什么 | 待上传的执行记录、回滚快照、离线队列、设备级配置 |
| 不存什么 | **不缓存用户 Memory 全量、不缓存第三方凭据、不存屏幕截图（除非用户主动附加）** |
| 代码签名 | macOS: Developer ID + Notarization；Windows: EV code signing |
| 更新 | 自动更新（electron-updater），差分包，更新前校验签名 |
| 本地 Agent 完整性 | Electron 启动时校验 Agent 可执行文件签名，不匹配拒绝启动 |
| IPC 安全 | 仅监听 `127.0.0.1`，端口随机，Bearer token 每次启动轮换，token 仅通过进程启动参数传递 |
| 独立仓库 | 本地 Agent 单独仓库 + 独立签名与发布节奏（见 README「Repository Structure」） |

**IPC 是本模块最主要的本地攻击面**：本机上的任意进程如果能调用本地 Agent，就获得了操作用户 Excel/邮件的能力。除 loopback + 轮换 token 外，还需：请求带调用方进程校验（macOS 用 audit token，Windows 用 named pipe 的客户端 PID + 签名校验）。

---

## 10. 观测与诊断（DT-12）

适配器维护成本高（计划 §2.3），必须有数据支撑，否则只能靠用户投诉发现问题。

上报内容（**全部脱敏**，且受 `desktop:*:automate` Scope 覆盖，用户可关闭诊断上报）：

```json
{
  "adapter": "excel", "app_version": "16.89", "os": "darwin-14.5",
  "action": "write_range", "layer_used": "L1",
  "result": "failed", "error_class": "com_call_rejected",
  "duration_ms": 1840,
  "context_shape": {"range_cells": 49, "sheet_count": 3, "has_merged": true},
  "ui_tree_hash": "…"
}
```

- `context_shape` 只描述形状不含内容（49 个单元格，不含单元格里是什么）。
- `ui_tree_hash` 用于识别「应用更新导致控件树变化」——这是适配器批量失效的主要诱因，能提前预警。
- **绝不上报**：单元格内容、邮件正文、文件名、截图。

---

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 适配器脆弱性拖累 Phase 1 整体交付（计划 §231 明确预警） | 极高 | 独立里程碑 + 独立子团队；§8.3 的门禁按适配器粒度而非整体；**Phase 1 若只有 2 个适配器达标，就只上 2 个，不为凑数降低标准** |
| 纯 UI 自动化达不到 90% | 极高 | §4 分层策略，L1 原生 API 优先；L3 使用率作为质量指标 |
| macOS 权限申请造成流失 | 高 | 延迟到首次使用时申请；提供图文引导；不申请屏幕录制权限 |
| 本地 Agent 成为提权入口 | 极高 | §9 的 IPC 三重防护；本地 Agent 只执行白名单动作，不接受任意命令；安全评审作为发布前置 |
| 用户在 AI 操作时同时操作电脑，互相干扰 | 中 | L1 路径不受影响（不用鼠标）；L3 执行前明确提示并检测焦点变化，焦点丢失即中止 |
| Office 版本差异（365 vs 2021 vs WPS） | 高 | 环境矩阵回归；WPS **不在** Phase 1 白名单内，明确不支持 |
| CDP attach 需要用户以调试模式启动浏览器，体验差 | 中 | 客户端提供「用 CogniWork 打开浏览器」的一键入口（带调试端口启动）；不支持时降级为独立浏览器实例（走 `P1-04`） |
| 桌面端与 Web 端体验割裂 | 中 | 共享 `shared-ui`；桌面端不做独立的 UI 演进路线 |

---

## 12. 验收标准

1. **三个适配器各自的 golden set 成功率 ≥ 90%**（含结果校验，见 §8.2），在环境矩阵全部组合上达标。
2. L3（视觉/坐标）使用率 ≤ 10%。
3. 未开启任何 `desktop:*` Scope 的客户端，本地 Agent 不启动（进程不存在）。
4. 授权 Excel 后，尝试调用邮件适配器返回 `permission_denied` 且无任何邮件客户端进程交互。
5. 执行中点击「停止」，2 秒内实际停止；已完成的部分可回滚。
6. IPC 安全：从另一个未授权进程调用本地 Agent 端口，全部请求被拒。
7. 诊断上报中无任何用户内容（用真实任务跑一轮，人工审查全部上报字段）。
8. 桌面端登录后，Web 端创建的 Memory 与 Skill 立即可用（共享验证）。

---

## 13. 交付拆分（独立里程碑管理）

| 里程碑 | 内容 | 预估 | 备注 |
|---|---|---|---|
| D0 | 技术预研：三个应用的 L1 接口可行性验证 | 5d | **Go/No-Go 检查点**，若某应用 L1 不可行，重新评估是否纳入首批 |
| D1 | Electron 壳 + shared-ui 复用 + 登录态打通 | 5d | |
| D2 | 本地 Agent 骨架 + 安全 IPC + Supervisor | 5d | 含安全评审 |
| D3 | AppAdapter 抽象 + Runtime 远程 Executor 通道 | 5d | |
| D4 | ExcelAdapter（Win COM + mac + openpyxl） | 10d | 最复杂，先做 |
| D5 | golden set 框架 + 结果校验 + CI 环境矩阵 | 6d | 与 D4 并行 |
| D6 | BrowserAdapter（CDP） | 6d | |
| D7 | MailAdapter | 6d | |
| D8 | 逐应用授权 UI + 系统权限引导 | 5d | |
| D9 | 执行预览/中断/回滚 | 6d | |
| D10 | 本地加密存储 + 签名分发 + 自动更新 | 6d | |
| D11 | 观测上报 + 诊断 | 3d | |
| **缓冲** | **专门预留**（计划 §2.3 要求） | **10d** | 适配器不确定性专用，不得挪用 |

> 总量明显大于其他 P0 模块，这与计划 §231 的预警一致。建议按独立子团队排期，且**接受"Phase 1 只上线达标的适配器"这一结果**，而非通过降低标准凑齐 3 个。

---

## 14. 待决问题

1. D0 预研结论会影响首批应用选择。若 macOS 上 Excel 的 AppleScript 能力不足以支撑常见操作，是否先只在 Windows 上提供 Excel 适配？倾向可以——分平台上线比降低成功率标准好。
2. 邮件客户端具体选哪个（Outlook 桌面版 / Mail.app / 直接走 Graph API）需结合目标用户实际使用情况定，建议在 `P0-07` §11 的用户实验中一并调研。
3. 「本地 Agent 独立仓库」的边界：共享的 proto/schema 放在哪？倾向发布为版本化的包，由两边各自依赖。
