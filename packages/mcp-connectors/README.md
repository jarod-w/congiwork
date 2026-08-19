# MCP connectors (P0-05)

First-party connectors live in `apps/backend/src/cogniwork/tools/`.
This package is the stdio process boundary:

```bash
COGNIWORK_MCP_TOKEN=... python -m cogniwork.tools.mcp_server --provider gcal
```

Each `(user, provider)` pair is its own process. Credentials are injected
through the environment for that process only and are never written to disk.

Phase 1 order (A10): **Calendar → Notion → Gmail**, then GitHub as the
approval-path proving ground (`search_code` / `create_issue` / `merge_pr`).
