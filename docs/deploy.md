# CogniWork 部署指南

运维手册。产品约束见 [`CLAUDE.md`](../CLAUDE.md) 与 [`docs/design/P0-07-consent-and-audit.md`](design/P0-07-consent-and-audit.md)；本地开发见 [`apps/backend/README.md`](../apps/backend/README.md) 与 [`apps/web/README.md`](../apps/web/README.md)。

本文覆盖 **Web SaaS + FastAPI 单体后端**。桌面 Computer Use Agent 在独立仓库 `cogniwork-desktop-agent`，不在此部署。

---

## 1. 范围与形态

Phase 1 是单体，不拆微服务（`00-conventions.md` §8）。生产路径：

```text
浏览器
  │  HTTPS
  ▼
反向代理（Nginx / Caddy）
  ├── /            → 静态工作台（apps/web 构建产物）
  └── /api         → uvicorn 上的 FastAPI（cogniwork.main:app）
                         │
                         ├── PostgreSQL 16     主存储（含上传文件 bytea）
                         ├── Redis 7           授权缓存 + SSE 断线补发
                         └── 出网               Anthropic / OpenAI / OAuth / MCP
```

| 组件 | 职责 | 不可替换为 |
|---|---|---|
| FastAPI 单体 | 认证、Consent、Runtime、Memory、连接器、Skill | 多进程拆服务（Phase 1 不做） |
| PostgreSQL 16 | 账号 / 授权 / 任务 / 记忆 / 画像 / 凭据密文 / 上传与产物 | 独立向量库、独立对象存储 |
| Redis 7 | `consent:{user_id}` 缓存；任务事件 Stream（保留 1 小时） | 用 memory store 顶生产 |
| 静态前端 | 工作台。请求一律相对路径 `/api/v1/...` | 把 API 基址写进前端代码 |

前端没有 `VITE_*` 配置。生产必须把 API 和页面放在**同一源**（或由反向代理把 `/api` 转到后端），否则浏览器请求打不到 API。

---

## 2. 前置依赖

| 软件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12 | `requires-python >= 3.12` |
| Node.js | 22 | 与 CI 一致 |
| pnpm | 10 | `packageManager` 锁定 `pnpm@10.28.2` |
| PostgreSQL | 16 | 官方镜像即可；`vector` 扩展**不是**启动前置（见 §8） |
| Redis | 7 | 不可用时授权检查回落 Postgres；SSE 跨连接补发会弱 |
| uv | 最新 | 后端依赖安装 |

外部账号（按实际上线的能力准备，缺密钥时 LLM 走 stub，连接器无法完成 OAuth）：

- Anthropic 和/或 OpenAI API key（任务推理；有 OpenAI key 时记忆 embedding 走 `text-embedding-3-small`，维度 1024）
- Google Cloud OAuth 客户端（Gmail / Calendar）
- Notion OAuth 客户端
- GitHub OAuth App

Google restricted scope（`gmail.*`）还需应用验证 / CASA，见 `P0-05` §2.1.1。那是上线 Gmail 的外部阻塞，不是本仓库进程起不来。

---

## 3. 运行时必须能找到的文件

后端**启动时**加载并校验 Scope 注册表，校验不过进程退出。不要把「能 import」当成「能服务」。

| 文件 | 默认定位 | 覆盖环境变量 |
|---|---|---|
| `config/scopes.yaml` | 从源码路径向上找 `config/scopes.yaml` | `COGNIWORK_SCOPES_PATH` |
| `config/model_routes.yaml` | 同上 | `COGNIWORK_MODEL_ROUTES_PATH` |
| `config/tool_catalog.yaml` | 同上 | `COGNIWORK_TOOL_CATALOG_PATH` |
| `config/skill_presets.yaml` | 同上 | `COGNIWORK_SKILL_PRESETS_PATH` |
| `config/task_templates.yaml` | 同上 | `COGNIWORK_TASK_TEMPLATES_PATH` |
| `config/interview_question.yaml` | 同上 | `COGNIWORK_INTERVIEW_PATH` |
| `apps/backend/migrations/*.sql` | 向上找含 `.sql` 的 `migrations/` | `COGNIWORK_MIGRATIONS_PATH` |

安装布局与 git 仓库不同时（例如只拷了 wheel、配置在 `/etc/cogniwork/`），**必须**用环境变量钉死路径。不要假设「往上走 N 层」。

`.env` 由 pydantic-settings 按**进程当前工作目录**读取（`env_file=".env"`）。生产优先用进程环境 / 密钥管理注入，不要把密钥文件打进镜像。

---

## 4. 环境变量

前缀一律 `COGNIWORK_`，对应 `apps/backend/src/cogniwork/core/config.py`。完整示例见仓库根目录 [`.env.example`](../.env.example)。

### 4.1 生产必改

这些默认值是开发用的，带着上线等于没有认证和没有保险箱。

| 变量 | 生产要求 |
|---|---|
| `COGNIWORK_STORE_BACKEND` | 必须 `postgres`。`memory` 只给单测和无基础设施的本地启动 |
| `COGNIWORK_DATABASE_URL` | `postgresql://user:pass@host:5432/cogniwork` |
| `COGNIWORK_REDIS_URL` | `redis://host:6379/0` |
| `COGNIWORK_JWT_SECRET` | 足够长的随机串（≥32 字节）。轮换会使已签发 token 全部失效 |
| `COGNIWORK_IP_HASH_PEPPER` | 独立随机串。入 `consent_record` 前哈希 IP 用；也用于账号删除时匿名化 `user_id`。**改了无法对上历史哈希** |
| `COGNIWORK_VAULT_MASTER_KEY` | 连接器凭据信封加密的主密钥。丢失则已存凭据无法解密，用户必须重连。轮换没有自动 rewrap |
| `COGNIWORK_PUBLIC_BASE_URL` | API 的公网根 URL，**无尾斜杠**。OAuth `redirect_uri` = `{该值}/api/v1/tools/oauth/callback` |
| `COGNIWORK_CORS_ORIGINS` | JSON 数组。OAuth 成功后重定向到**第一项** + `/?connected={provider}`。与页面实际源一致 |
| `COGNIWORK_OAUTH_STUB` | 必须 `false`（或不设）。`true` 时连接器用桩，不会打到真实供应商 |
| `COGNIWORK_DEBUG` | `false` |

生成密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 4.2 语言与前端源

| 变量 | 默认 | 说明 |
|---|---|---|
| `COGNIWORK_DEFAULT_LOCALE` | `en-US` | **不要在代码里写死语言**（A8）。前端从 `GET /api/v1/config` 读 |
| `COGNIWORK_FALLBACK_LOCALE` | `en-US` | |
| `COGNIWORK_SUPPORTED_LOCALES` | `["en-US","zh-CN"]` | JSON 数组 |
| `COGNIWORK_CORS_ORIGINS` | 本地 Vite | 生产写成 `["https://app.example.com"]` |

复杂类型（tuple / list）走 JSON，例如：

```bash
COGNIWORK_CORS_ORIGINS='["https://app.example.com"]'
```

### 4.3 LLM 与额度

| 变量 | 默认 | 说明 |
|---|---|---|
| `COGNIWORK_LLM_PROVIDER` | `auto` | `auto`：有密钥用内置供应商，没有则 stub。`stub` 强制桩；`anthropic` / `openai` 钉死一家 |
| `COGNIWORK_ANTHROPIC_API_KEY` | 空 | |
| `COGNIWORK_OPENAI_API_KEY` | 空 | 同时驱动 chat 回落与记忆 embedding |
| `COGNIWORK_MAX_UPLOAD_BYTES` | `20971520`（20 MiB） | 反向代理的 `client_max_body_size` 必须 ≥ 此值 |
| `COGNIWORK_TASK_STEP_LIMIT` | `25` | |
| `COGNIWORK_TASK_COST_USD_LIMIT` | `0.50` | 单任务 |
| `COGNIWORK_DAILY_COST_USD_LIMIT` | `5.00` | 单用户每日 |
| `COGNIWORK_MEMORY_BUDGET_TOKENS` | `2000` | 注入任务的记忆预算 |

无模型密钥时零授权路径（xlsx → 周报）仍能跑通，走 stub。那是开发/CI 能力，**不是**给真实用户的生产形态。

### 4.4 OAuth 客户端

| 变量 | 用于 |
|---|---|
| `COGNIWORK_GOOGLE_CLIENT_ID` / `COGNIWORK_GOOGLE_CLIENT_SECRET` | Gmail、Google Calendar |
| `COGNIWORK_NOTION_CLIENT_ID` / `COGNIWORK_NOTION_CLIENT_SECRET` | Notion |
| `COGNIWORK_GITHUB_CLIENT_ID` / `COGNIWORK_GITHUB_CLIENT_SECRET` | GitHub |

在各供应商控制台登记的回调 URL 必须与运行时拼出的 `redirect_uri` **逐字符相同**：

```text
{COGNIWORK_PUBLIC_BASE_URL}/api/v1/tools/oauth/callback
```

---

## 5. 进程模型（硬限制）

任务在 API 进程里用 **daemon 线程**跑 LangGraph；checkpointer 是进程内 `MemorySaver`；SSE 的 `subscribe` 走进程内 `InMemoryEventBroker`。Redis Stream 只用于**断线后补发**（TTL 1 小时，maxlen 约 10_000），不负责跨进程推直播事件。

因此 Phase 1 生产必须：

1. **uvicorn `workers=1`**（或等价的单进程）。多 worker 时，执行线程与 SSE 连接可能不在同一进程，直播事件丢失，重连也补不回正在发生的步骤。
2. 若前面有负载均衡，对 `/api/v1/tasks/{id}/events` 开 **sticky**，或根本不要把同一环境水平扩出多个 API 进程。
3. 进程重启会丢掉进行中的图状态。数据库里任务可能停在 `running`。重启窗口尽量短，并准备手工取消卡死任务。

水平扩容不在 Phase 1 范围。要加实例，先把 checkpointer 与事件总线迁出进程，那是另一次设计，不要在部署时「先多开几个 worker 试试」。

---

## 6. 部署步骤

以下假设一台 Linux 主机（或同等 VM），域名 `app.example.com`，TLS 终止在反向代理。

### 6.1 基础设施

本地对照环境（开发用账号，**不要**直接当生产）：

```bash
cd apps/backend
docker compose up -d
```

生产用托管 Postgres 16 + Redis 7，或自建。应用连接串指向它们。

上传文件和产物存在 `uploaded_file.content` / `artifact.content`（`bytea`），备份体积按用户文件增长，不是「只有结构化行」。

### 6.2 数据库迁移

在应用能连上的环境执行，**先于**启动 API：

```bash
cd apps/backend
uv venv --python 3.12
uv pip install -e ".[dev]"   # 生产镜像可只装主依赖，不含 [dev]
export COGNIWORK_DATABASE_URL=postgresql://...
.venv/bin/python -m cogniwork.migrate
```

迁移按文件名数字前缀顺序执行，记入 `schema_migrations`。一份 SQL 与写入迁移表在同一事务：失败整份回滚。当前版本：

| 文件 | 内容 |
|---|---|
| `0001_consent.sql` | `consent_record`、`consent_current`、按月分区的 `execution_audit` |
| `0002_account.sql` | 账号 |
| `0003_task.sql` | 会话 / 任务 / 上传 / 产物 |
| `0004_memory.sql` | Memory OS、审批、用户设置 |
| `0005_profile.sql` | 个人画像 |
| `0006_tools.sql` | 连接与保险箱 |
| `0007_skill.sql` | Skill |

`execution_audit` 迁移只建了 `DEFAULT` 分区。按月分区的创建与 12 个月回收是运维任务，见 §8.1。

### 6.3 启动 API

工作目录建议 `apps/backend`，保证能解析包与默认配置查找。

```bash
export COGNIWORK_STORE_BACKEND=postgres
# …其余 §4 变量
cd apps/backend
.venv/bin/python -m uvicorn cogniwork.main:app \
  --host 127.0.0.1 --port 8000 \
  --workers 1
```

不要 `--reload`。绑定 `127.0.0.1`，把 443 交给反向代理。

systemd 示例：

```ini
[Unit]
Description=CogniWork API
After=network.target postgresql.service redis.service

[Service]
User=cogniwork
WorkingDirectory=/opt/cogniwork/apps/backend
EnvironmentFile=/etc/cogniwork/env
ExecStart=/opt/cogniwork/apps/backend/.venv/bin/python -m uvicorn cogniwork.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
# 任务线程是 daemon：杀掉主进程即丢掉进行中的图。给足超时，避免滚动时硬杀。
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

`EnvironmentFile` 的权限必须仅服务账号可读（硬约束 9：凭据不落明文到大家都能看的地方）。

### 6.4 构建前端

在仓库根目录：

```bash
pnpm install
pnpm --filter @cogniwork/web build
```

产物在 `apps/web/dist/`。把该目录交给反向代理作静态根。

### 6.5 反向代理

前端用相对路径请求 `/api` 与 SSE。代理必须：

- 把 `/api/` 转到 uvicorn
- **关闭** SSE 缓冲（应用已发 `X-Accel-Buffering: no`，Nginx 仍需 `proxy_buffering off`）
- 读超时长于任务墙钟时间（步数上限 25，加 LLM，常见数分钟）
- `client_max_body_size` ≥ `COGNIWORK_MAX_UPLOAD_BYTES`

Nginx 示意：

```nginx
server {
    listen 443 ssl http2;
    server_name app.example.com;

    # tls 证书路径略

    root /var/www/cogniwork;
    index index.html;

    client_max_body_size 21m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

对应环境变量：

```bash
COGNIWORK_PUBLIC_BASE_URL=https://app.example.com
COGNIWORK_CORS_ORIGINS='["https://app.example.com"]'
```

---

## 7. 健康检查与发版门禁

```bash
curl -fsS https://app.example.com/api/v1/health
```

正常响应含 `status: "ok"`、`store: "postgres"`、`scopes_registered`（当前注册表条目数）、`default_locale`。启动失败常见原因：`scopes.yaml` 校验不通过、`store_backend` 拼写错误、Postgres 连不上。

Redis 在启动时 `PING` 失败会打 warning 并继续，授权回落 `consent_current`。不要把「进程起来了」当成 Redis 正常。

CI（`.github/workflows/ci.yml`）：

| 时机 | 做什么 |
|---|---|
| 每个 PR / `main` push | ruff、迁移、`pytest`（含 `tests/guards/` 与零授权 E2E） |
| git tag | 额外 `pytest -m release`：授权说明英文母语审校（A8 ②） |

打生产 tag 前：

```bash
cd apps/backend
.venv/bin/python -m pytest -q -m release
```

`config/scopes.yaml` 里对应条目 `review_status` 必须是 `approved`。未审校的 Scope 不能随发版到用户面前。

`scopes.yaml` 里 `collects` / `retention` 若**扩大采集范围**，必须 bump `consent_text_version`，并把存量用户该 Scope 置为 `expired` 后重新征求同意（`P0-07` §6.3）。仅措辞优化不必重签。这是发版人工检查项。

---

## 8. 数据面运维

### 8.1 `execution_audit` 分区

表按 `created_at` RANGE 分区，保留 12 个月，到期 drop 分区（`P0-07` §7）。迁移没有预写死月份。每月初建下月分区，并 drop 超过 12 个月的分区：

```sql
-- 例：2026-09
CREATE TABLE IF NOT EXISTS execution_audit_2026_09
    PARTITION OF execution_audit
    FOR VALUES FROM ('2026-09-01+00') TO ('2026-10-01+00');

-- 例：回收 2025-08
DROP TABLE IF EXISTS execution_audit_2025_08;
```

未建月分区时行进入 `execution_audit_default`，服务能写，但无法按月 drop，保留期承诺会破。

审计字段是脱敏摘要（硬约束 8）。不要在应用日志里补一份明文「方便排障」。

### 8.2 备份与账号删除（72 小时）

用户删除账号时，除 `consent_record` 外全部**物理删除**；`consent_record` 把 `user_id` 换成不可逆哈希后保留（B1）。产品承诺：**72 小时内含备份在内不可恢复**（`P0-07` §7 / 验收 5）。

运维含义：

1. 含用户数据的备份保留期 **≤ 72 小时**，或删除任务能从备份集里剔除并验证。
2. 备份本身不要把 Vault 明文、JWT 密钥、OAuth client secret 打进去的同时再复制一份到更长周期的磁带/对象存储而不加密、不设同样 TTL。
3. 定期做一次「删除 → 试图从备份恢复该用户 → 应失败」的演练。API 返回的 `backup_invalidation.status` 目前是 `scheduled`，真正失效靠这条运维流程，不靠应用自己去删你的快照。

`consent_record` 是授权证据链，永久保留；向用户说明它不含工作内容。

应用日志保留 30 天，**禁止记录用户内容与凭据**（硬约束 8、9）。

### 8.3 Redis 键

| 键 | 用途 | 失效 |
|---|---|---|
| `consent:{user_id}` | 授权当前态 hash | 授权/撤销时写失效；未命中读 `consent_current` |
| `task:{task_id}:events` | SSE 补发 Stream | TTL 1 小时 |

Redis 可丢。丢了之后：授权仍正确（回落 Postgres）；正在看的 SSE 若已连上还能继续；**重连**可能缺事件。不要把 Redis 当主存储。

### 8.4 向量列

`memory_item.embedding` 是 `real[]`，余弦在应用层算。官方 `postgres:16` 没有 `vector` 扩展，CI 也没有。生产若安装 pgvector，后续迁移可改 `vector(1024)` + HNSW，接口不用动。Phase 1 不装也能上。

---

## 9. 验收清单（部署当时）

可测量，不要用「感觉正常」代替。

- [ ] `GET /api/v1/health` 返回 `store=postgres` 且 `scopes_registered` > 0
- [ ] `COGNIWORK_JWT_SECRET` / `IP_HASH_PEPPER` / `VAULT_MASTER_KEY` 均非仓库默认值
- [ ] `COGNIWORK_OAUTH_STUB` 为 false；`COGNIWORK_STORE_BACKEND=postgres`
- [ ] 迁移 `already up to date`（0001–0007）
- [ ] 本月 `execution_audit` 月分区已创建
- [ ] 工作台能注册、跳过访谈、上传 xlsx、出产物、下载（零授权核心路径，硬约束 5）
- [ ] 有 LLM 密钥时任务走真实模型，而不是 stub 周报模板
- [ ] 反向代理下 SSE 有 `step.*` / `message.delta`，刷新页面能按 `from_seq` 补发
- [ ] 已配置的 OAuth 供应商能走完回调并回到 `/?connected=...`
- [ ] 隐私中心删除账号后，业务表查不到该用户；备份策略书面对齐 72 小时
- [ ] uvicorn 单 worker；日志抽样无 token / 密码 / 邮件正文

---

## 10. 常见故障

| 现象 | 先查 |
|---|---|
| 进程立刻退出，RegistryError | `scopes.yaml` 路径或六项元数据；设 `COGNIWORK_SCOPES_PATH` |
| 启动后第一次请求 500 / 连库失败 | `DATABASE_URL`、是否已 migrate、网络/SSL |
| 前端空白或全部 API 失败 | 是否同源 `/api` 代理；构建是否指到了旧 dist |
| 任务一直转圈、时间线不动 | 多 worker / 无 sticky；Nginx 缓冲了 SSE；`proxy_read_timeout` 太短 |
| 上传 413 | 代理 `client_max_body_size` |
| OAuth 回调 mismatch | `PUBLIC_BASE_URL` 与控制台登记不一致（http/https、尾斜杠、www） |
| 连上工具但 vault 报错 | `VAULT_MASTER_KEY` 与写入时不同 |
| 记忆检索质量断崖 | 无 `OPENAI_API_KEY` 时 embedding 是 stub-hash，换密钥后旧向量与新模型不在同一空间，需重算 |
| 授权「关了还在」超过数秒 | Redis 未失效又被读到旧 hash——正常路径写时会删缓存；查是否有旁路写了 `consent_record` |

---

## 11. 不在本文范围

| 项 | 原因 |
|---|---|
| 桌面壳 / 本地 Agent 签名分发 | 独立仓库与独立节奏（`P0-08`） |
| 多区域、多租户、企业管理后台 | Phase 1 明确不做 |
| Kubernetes 清单 / 官方容器镜像 | 仓库尚未提供；按 §5–§6 自行包装时保持单进程 |
| 把 `memory` store 当生产 | 进程一停数据全没，且零授权 E2E 以外的路径未按此容量设计 |
