# CogniWork 部署指南

运维手册。产品约束见 [`CLAUDE.md`](../CLAUDE.md) 与 [`docs/design/P0-07-consent-and-audit.md`](design/P0-07-consent-and-audit.md)；本地开发见 [`apps/backend/README.md`](../apps/backend/README.md) 与 [`apps/web/README.md`](../apps/web/README.md)。

本文覆盖 **Web SaaS + FastAPI 单体后端**，部署形态是**主机 + pm2，不用容器**（理由见 §6.1）。桌面 Computer Use Agent 在独立仓库 `cogniwork-desktop-agent`，不在此部署。

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
| Node.js | 22 | 与 CI 一致。构建前端要用；生产主机用 pm2 托管进程时也要装（§6.4） |
| pnpm | 10 | `packageManager` 锁定 `pnpm@10.28.2` |
| PostgreSQL | 16 | 装在主机上或用托管实例（§6.2）。`vector` 扩展**不是**启动前置（见 §8.4） |
| Redis | 7 | 不可用时授权检查回落 Postgres；SSE 跨连接补发会弱 |
| uv | 最新 | 后端依赖安装 |
| pm2 | ≥ 5 | 进程托管（§6.4）。`sudo npm i -g pm2`。**只跑 fork 模式单实例**，见 §5 |

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

`.env` 由 pydantic-settings 按**进程当前工作目录**读取（`env_file=".env"`）。生产由启动包装脚本从 `/etc/cogniwork/env` 注入，或走密钥管理（§6.4）：文件放在部署目录之外（`/etc/cogniwork/env`）、权限仅服务账号可读。不要把密钥写进仓库里的 `.env` —— 那会跟着 `git pull` 到处走。

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
| `COGNIWORK_MCP_TRANSPORT` | 保持默认 `stdio`。连接器跑在独立进程里，崩溃不带上 API，凭据不跨用户共享（`P0-05` §3）。`inprocess` 只给单测 —— 子进程拿不到测试注入的 transport。填其它值**启动即报错**，不静默回落 |
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
| `COGNIWORK_LLM_GLOBAL_CONCURRENCY` | `16` | **全局**在飞 LLM 调用上限（`P0-03` §8）。per-(user, provider) 令牌桶管不到跨用户总量，而供应商的账号级限流是全局的。超限排队 120s，之后按限流失败返回 |

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

任务在 API 进程里用 **daemon 线程**跑 LangGraph。`store_backend=postgres` 时 checkpointer 是 **`langgraph.checkpoint.postgres.PostgresSaver`**，图状态与运行态（消息历史、挂起的工具调用、Skill 游标）都落库；SSE 的 `subscribe` 仍走进程内 `InMemoryEventBroker`，Redis Stream 只用于**断线后补发**（TTL 1 小时，maxlen 约 10_000），不负责跨进程推直播事件。

因此 Phase 1 生产必须：

1. **uvicorn `workers=1`**（或等价的单进程）。多 worker 时，执行线程与 SSE 连接可能不在同一进程，直播事件丢失，重连也补不回正在发生的步骤。**另外**：启动时的「接回被打断的任务」（`TaskEngine.recover_interrupted`）假设单进程 —— 多副本会让同一个任务被多个进程同时恢复。用 pm2 托管时同一条约束表现为 `exec_mode: fork` + `instances: 1`：**cluster 模式或 `instances: 'max'` 与多 worker 等价，一样违规**（§6.4）。
2. 若前面有负载均衡，对 `/api/v1/tasks/{id}/events` 开 **sticky**，或根本不要把同一环境水平扩出多个 API 进程。
3. 进程重启**不再丢**图状态：启动时停在 `running` / `planning` 的任务会从最后一个 checkpoint 接回去，`waiting_approval` 的任务保持等待（它在等人，不该被自动推进），用户回来点批准仍能继续。仍需盯的是：重启瞬间正在 stream 的直播事件会断，客户端靠 `from_seq` 补。

水平扩容不在 Phase 1 范围。要加实例，先把**事件总线**迁出进程（checkpointer 已经出去了），那是另一次设计，不要在部署时「先多开几个 worker 试试」。

---

## 6. 部署步骤

以下假设一台 Linux 主机（或同等 VM），域名 `app.example.com`，TLS 终止在反向代理。

### 6.1 主机准备

**不用容器部署。** 单进程约束（§5）下，容器编排真正解决的是水平扩容，而扩容不在 Phase 1 范围；换来的是多一层网络、生命周期和排障面。进程由 **pm2** 托管（§6.4），Postgres / Redis 用发行版包或托管实例。

仓库里的 `apps/backend/docker-compose.yml` 只为本地开发一键起依赖（见 [`apps/backend/README.md`](../apps/backend/README.md)），**不是部署路径** —— 里面的账号密码是写死的 `cogniwork`。

服务账号与目录（示例是 Debian/Ubuntu）：

```bash
sudo useradd --system --home /opt/cogniwork --shell /usr/sbin/nologin cogniwork
sudo install -d -o cogniwork -g cogniwork /opt/cogniwork /var/log/cogniwork
sudo install -d -o root -g root /opt/cogniwork/bin        # 启动脚本，服务账号只能执行
sudo install -d -m 750 -o root -g cogniwork /etc/cogniwork   # 环境文件放这里，服务账号只读
```

把仓库（或构建产物）放到 `/opt/cogniwork`，后端虚拟环境建在 `/opt/cogniwork/apps/backend/.venv` —— §6.3 的迁移命令和 §6.4 的 pm2 配置都按这个路径写。运行时工具链：

```bash
sudo apt-get install -y python3.12 python3.12-venv build-essential
# uv 装到系统路径：默认装进当前用户的 ~/.local/bin，服务账号（nologin）用不到
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh

# Node 22 + pm2：pm2 托管后端进程，Node 也用来构建前端（§6.5）
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm i -g pm2 pnpm
```

pm2 只是进程管理器，**不代表后端跑在 Node 上** —— 它 fork 的是 venv 里的 Python。

### 6.2 PostgreSQL 16 与 Redis 7

发行版自带的 PostgreSQL 未必是 16，用 PGDG 源钉住版本：

```bash
sudo apt-get install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt-get update && sudo apt-get install -y postgresql-16 redis-server

sudo systemctl enable --now postgresql redis-server
```

RHEL 系同理：加 PGDG 的 rpm 仓库、`dnf -qy module disable postgresql`、装 `postgresql16-server` 并用 `postgresql-16-setup initdb` 初始化，Redis 是 `dnf install redis`。用托管实例（RDS / ElastiCache 等）就整节跳过，只要连接串与 TLS 配好。

建库与角色：

```bash
sudo -u postgres createuser --pwprompt cogniwork
sudo -u postgres createdb --owner=cogniwork cogniwork
```

**这个角色必须是库的 owner（至少能建表）**：LangGraph 的 checkpointer 在 API 启动时自建 `checkpoints*` 表（§6.3），只给 DML 权限会在启动时失败。

Postgres 与 API 同机时保持默认只监听 `127.0.0.1`；分机部署才改 `listen_addresses` 与 `pg_hba.conf`，并要求 TLS（连接串带 `?sslmode=verify-full`）。

Redis 只放授权缓存与 SSE 补发 Stream（§8.3），**不是主存储**：

- 持久化可以不开 —— 丢了授权回落 `consent_current`、补发失效，不丢业务数据。
- 但必须**绑回环或设 `requirepass`**。裸奔的 Redis 等于把授权缓存和任务事件对同网段公开（硬约束 9 的同一条理由）。
- `maxmemory` 别设到会挤掉 `task:*:events` 的量级。这些键自带 TTL 1 小时，正常不需要淘汰策略。

自检：

```bash
psql "postgresql://cogniwork:***@127.0.0.1:5432/cogniwork" -c "select version()"
redis-cli -h 127.0.0.1 ping        # 设了 requirepass 时加 -a
```

上传文件和产物存在 `uploaded_file.content` / `artifact.content`（`bytea`），备份体积按用户文件增长，不是「只有结构化行」；保留期上限见 §8.2。

### 6.3 数据库迁移

在应用能连上的环境执行，**先于**启动 API：

```bash
sudo -u cogniwork -H bash -lc '
cd /opt/cogniwork/apps/backend
uv venv --python 3.12
uv pip install -e "."          # 生产只装主依赖；[dev] 留给测试机
export COGNIWORK_DATABASE_URL=postgresql://...
.venv/bin/python -m cogniwork.migrate
'
```

用**服务账号**建 venv 和跑迁移。用 root 建出来的 `.venv` 属主是 root，而 pm2 daemon 跑在 `cogniwork` 账号下（§6.4），读不到写不了，症状是启动即失败。

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
| `0008_runtime_state.sql` | `task_runtime_state`（任务运行态，RT-5）|

`execution_audit` 的按月分区不在迁移里建 —— 执行者是 `cogniwork.maintenance`（§8.1），
分区逻辑只有一份实现且有单测。迁移跑完、API 还没起来的那段时间里写入落 `DEFAULT`，
不会丢，启动时会被搬进当月分区。

**LangGraph 的 checkpointer 自带一套表**（`checkpoints*` / `checkpoint_migrations`），
由 `PostgresSaver.setup()` 在 API 启动时建，**不走 `cogniwork.migrate`**：那套表结构属于
langgraph，跟着它的版本走，抄进我们的迁移目录只会在升级时打架。数据库账号因此需要
建表权限，不能只给 DML。

### 6.4 启动 API（pm2）

先把 §4 的变量写进 `/etc/cogniwork/env`。权限必须仅服务账号可读（硬约束 9：凭据不落明文到大家都能看的地方）：

```bash
sudo install -m 640 -o root -g cogniwork /dev/null /etc/cogniwork/env
sudo -e /etc/cogniwork/env
```

这个文件是被 **bash `source`** 的（下面的包装脚本），所以 JSON 之类带特殊字符的值要加单引号：

```bash
COGNIWORK_STORE_BACKEND=postgres
COGNIWORK_DATABASE_URL='postgresql://cogniwork:***@127.0.0.1:5432/cogniwork'
COGNIWORK_CORS_ORIGINS='["https://app.example.com"]'
```

工作目录用 `/opt/cogniwork/apps/backend`，保证能解析包与默认配置查找（§3）。先手工验一次能起来：

```bash
sudo -u cogniwork -H bash -lc '
set -a; . /etc/cogniwork/env; set +a          # §4 的变量
cd /opt/cogniwork/apps/backend
.venv/bin/python -m uvicorn cogniwork.main:app --host 127.0.0.1 --port 8000 --workers 1
'
```

不要 `--reload`。绑定 `127.0.0.1`，把 443 交给反向代理（§6.6）。

起得来之后交给 pm2。**密钥不写进 pm2 配置** —— 用一个包装脚本从 `/etc/cogniwork/env` 注入，
配置文件本身就可以进仓库/配置管理，而 `env` 文件保持 640：

`/opt/cogniwork/bin/api.sh`（root 拥有、`0755`，服务账号只能执行不能改）：

```bash
#!/usr/bin/env bash
set -euo pipefail
set -a; . /etc/cogniwork/env; set +a
cd /opt/cogniwork/apps/backend
# exec：让 uvicorn 变成 pm2 直接管的那个 PID，否则 pm2 重启杀的是 shell，Python 留成孤儿
exec .venv/bin/python -m uvicorn cogniwork.main:app \
  --host 127.0.0.1 --port 8000 --workers 1
```

`/etc/cogniwork/ecosystem.config.cjs`：

```js
module.exports = {
  apps: [{
    name: 'cogniwork-api',
    script: '/opt/cogniwork/bin/api.sh',
    interpreter: 'bash',
    cwd: '/opt/cogniwork/apps/backend',

    // 硬限制（§5）：fork 模式、单实例。cluster / instances>1 会让执行线程与 SSE
    // 连接落到不同进程，直播事件丢失，且启动恢复会把同一个任务恢复多次。
    exec_mode: 'fork',
    instances: 1,

    autorestart: true,
    max_restarts: 10,
    min_uptime: '30s',
    // pm2 先发 SIGINT（uvicorn 按优雅关闭处理），超时才 SIGKILL。任务线程是 daemon：
    // 硬杀即丢掉进行中的图（能从 checkpoint 接回，但正在 stream 的连接会断），所以给足时间。
    kill_timeout: 60000,
    // 不要开 watch：源码文件一动就重启，等于线上热重载。
    watch: false,
    // 不要设 max_memory_restart 到贴着常态用量的值 —— 长任务正在跑时被回收，
    // 用户看到的是任务无声中断。
    error_file: '/var/log/cogniwork/api.err.log',
    out_file: '/var/log/cogniwork/api.out.log',
    time: true,
  }],
}
```

以服务账号启动，并让它在主机重启后自己回来：

```bash
sudo -u cogniwork -H pm2 start /etc/cogniwork/ecosystem.config.cjs
sudo -u cogniwork -H pm2 save                      # 落进程列表，开机时按它恢复
sudo pm2 startup systemd -u cogniwork --hp /opt/cogniwork   # 打印一条命令，按提示执行
sudo -u cogniwork -H pm2 logs cogniwork-api
```

`pm2 save` 是**必须的一步**：没存就重启主机，pm2 daemon 起来但进程列表是空的，服务不会自己回来。改完 ecosystem 后用 `pm2 reload cogniwork-api --update-env`（fork 模式下就是重启，不是零停机 —— 单进程本来就做不到零停机）。

日志由 pm2 写到 `/var/log/cogniwork/`，轮转装 pm2 的模块（要用**同一个账号**，模块是按 pm2 daemon 装的）：
`sudo -u cogniwork -H pm2 install pm2-logrotate`。保留 30 天，
且**不许**为了排障往里补用户内容或凭据（硬约束 8、9；见 §8.2）。

**不用 pm2 的话**，等价的 systemd 单元（`Restart=on-failure`、`TimeoutStopSec=60`、
`User=cogniwork`、`EnvironmentFile=/etc/cogniwork/env`、`ExecStart=` 指向上面那条 uvicorn 命令，
外加 `NoNewPrivileges=yes` / `PrivateTmp=yes` / `ProtectSystem=full` / `ProtectHome=yes`）
效果相同。两者别同时装，否则两个 8000 端口的进程互相抢。

### 6.5 构建前端

在仓库根目录：

```bash
pnpm install
pnpm --filter @cogniwork/web build
```

产物在 `apps/web/dist/`。这一步**可以在 CI 或另一台机器上做**，只把目录同步到生产主机的静态根（主机上装 Node 是为了 pm2，构建不必在这里做）：

```bash
rsync -a --delete apps/web/dist/ deploy@app.example.com:/var/www/cogniwork/
```

前端没有 API 基址配置，所以同一份 `dist` 在任何环境都能用；决定它打到哪个后端的是反向代理（§6.6）。

### 6.6 反向代理

```bash
sudo apt-get install -y nginx
sudo install -d -o www-data -g www-data /var/www/cogniwork
```

TLS 证书用 certbot（`sudo apt-get install certbot python3-certbot-nginx && sudo certbot --nginx -d app.example.com`）或自有证书，都终止在 nginx。

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

### 8.1 `execution_audit` 分区与 12 个月保留期

表按 `created_at` RANGE 分区，保留 12 个月，到期 drop 分区（`P0-07` §7）。执行者是
`cogniwork.maintenance`，不要手搓 SQL：

```bash
cd /opt/cogniwork/apps/backend
.venv/bin/python -m cogniwork.maintenance audit-retention
```

它做两件事：

1. **建**当月与未来 3 个月的分区。若 `DEFAULT` 分区里已经有落在该区间的行，会先把行搬过去
   再 `ATTACH`（不搬走的话 PostgreSQL 会因为 `DEFAULT` 的分区约束冲突而拒绝创建）；
   `DEFAULT` 里没有冲突行时走 `CREATE TABLE … PARTITION OF` 一条语句，索引自动建。
   **搬行是 `INSERT … SELECT` + `DELETE`，在一个事务里** —— 首次在大表上跑先估耗时。
2. **回收**超过 12 个月的月分区（`DROP TABLE`），并 `DELETE` `DEFAULT` 里同样过期的行。

第 2 步会删数据，所以不放在启动流程里。**建**分区那一半 API 启动时会自己跑一次
（`main._ensure_audit_partitions`），失败只记日志、不阻塞启动 —— `DEFAULT` 还在，审计不丢。

放进 cron，每月一次足够（写成每天跑也无害，它是幂等的）：

```cron
17 3 1 * * cogniwork cd /opt/cogniwork/apps/backend && .venv/bin/python -m cogniwork.maintenance audit-retention >> /var/log/cogniwork/maintenance.log 2>&1
```

**`DEFAULT` 分区为什么留着**：它是安全网 —— 分区没建全时插入不至于失败。代价是
`DEFAULT` 永远 `DROP` 不掉，落进去的行只能靠上面第 2 步的 `DELETE` 回收。这条 cron
不跑，保留期承诺就是一句空话（`P0-07` §7 的表里写着「分区自动 drop」）。

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

`memory_item.embedding` 是 `real[]`，余弦在应用层算。PostgreSQL 16 默认不带 `vector` 扩展，CI 也没有。生产若装了 pgvector（PGDG 源里是 `postgresql-16-pgvector`），后续迁移可改 `vector(1024)` + HNSW，接口不用动。Phase 1 不装也能上。

---

## 9. 验收清单（部署当时）

可测量，不要用「感觉正常」代替。

- [ ] `pm2 list` 只有 `cogniwork-api` 一条，`exec_mode=fork`、`instances=1`（§5）
- [ ] `pm2 save` 已执行、`pm2 startup` 生成的开机单元 `enabled`；`systemctl is-enabled postgresql redis-server` 也是 `enabled`
- [ ] 主机重启一次，pm2 把 API 拉回来且 `/health` 通
- [ ] `GET /api/v1/health` 返回 `store=postgres` 且 `scopes_registered` > 0
- [ ] `COGNIWORK_JWT_SECRET` / `IP_HASH_PEPPER` / `VAULT_MASTER_KEY` 均非仓库默认值
- [ ] `COGNIWORK_OAUTH_STUB` 为 false；`COGNIWORK_STORE_BACKEND=postgres`
- [ ] 迁移 `already up to date`（0001–0008）
- [ ] 本月 `execution_audit` 月分区已创建（API 启动时会建；没有就手工跑一次 `audit-retention`），
      且 `audit-retention` 的 cron 已进系统（§8.1）
- [ ] `checkpoint_migrations` 表存在（说明 `PostgresSaver.setup()` 跑过了）
- [ ] `pm2 restart cogniwork-api` 之后：`waiting_approval` 的任务点批准仍能继续（`P0-03` §12 验收 1）
- [ ] `COGNIWORK_MCP_TRANSPORT` 是 `stdio`
- [ ] 工作台能注册、跳过访谈、上传 xlsx、出产物、下载（零授权核心路径，硬约束 5）
- [ ] 有 LLM 密钥时任务走真实模型，而不是 stub 周报模板
- [ ] 反向代理下 SSE 有 `step.*` / `message.delta`，刷新页面能按 `from_seq` 补发
- [ ] 已配置的 OAuth 供应商能走完回调并回到 `/?connected=...`
- [ ] 隐私中心删除账号后，业务表查不到该用户；备份策略书面对齐 72 小时
- [ ] uvicorn 单 worker；pm2 日志抽样无 token / 密码 / 邮件正文
- [ ] `/etc/cogniwork/env` 权限 640、属主 `root:cogniwork`；`.venv` 与 pm2 daemon 都属服务账号
- [ ] Redis 不对公网监听（`ss -lntp | grep 6379` 只见回环，或已设 `requirepass`）

---

## 10. 常见故障

| 现象 | 先查 |
|---|---|
| 进程立刻退出，RegistryError | `scopes.yaml` 路径或六项元数据；设 `COGNIWORK_SCOPES_PATH` |
| 启动后第一次请求 500 / 连库失败 | `DATABASE_URL`、是否已 migrate、`pg_hba.conf` / `listen_addresses`、网络/SSL |
| pm2 里状态反复 `errored` / 重启计数涨 | `pm2 logs cogniwork-api --err`：多半是 `.venv` 属主是 root（§6.3）、`/etc/cogniwork/env` 读不到、或 `cwd` 不是 `/opt/cogniwork/apps/backend` |
| 主机重启后服务没回来 | 漏了 `pm2 save`，或 `pm2 startup` 生成的单元没 enable（§6.4） |
| 任务无声中断、pm2 显示刚重启过 | `max_memory_restart` 设得贴着常态用量，或 `watch: true` 撞上文件改动（§6.4） |
| 启动时 checkpointer 报建表失败 | 数据库角色不是库 owner，建不了 `checkpoints*`（§6.2） |
| 前端空白或全部 API 失败 | 是否同源 `/api` 代理；构建是否指到了旧 dist |
| 任务一直转圈、时间线不动 | 多 worker / pm2 cluster 模式 / 无 sticky；Nginx 缓冲了 SSE；`proxy_read_timeout` 太短 |
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
| 容器镜像 / Kubernetes 清单 | Phase 1 按主机 + pm2 部署（§6）。容器编排解决的是水平扩容，而扩容本身不在范围。自行打包务必保持单进程，且状态只留在外部 Postgres / Redis |
| 把 `memory` store 当生产 | 进程一停数据全没，且零授权 E2E 以外的路径未按此容量设计 |
