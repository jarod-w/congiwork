# CogniWork Web

任务工作台（`docs/design/P0-04-task-workspace.md` M1 / M2 / M3 / M5）。

三栏布局：任务列表 · 对话/时间线 · 「凭什么」面板（默认展开）。文案走 i18n，语言从 `GET /api/v1/config` 读取。

```bash
# 仓库根目录
pnpm install
pnpm --filter @cogniwork/web dev
```

开发时 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`。生产构建没有独立 API 基址，必须由反向代理把 `/api` 转到后端，见 [`docs/deploy.md`](../../docs/deploy.md)。先起后端：

```bash
cd apps/backend
COGNIWORK_STORE_BACKEND=memory .venv/bin/python -m uvicorn cogniwork.main:app --reload
```
