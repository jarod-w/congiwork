# CogniWork (AI Coworker OS)

> The AI coworker that learns how you work, remembers your business, and takes the busywork off your plate.

CogniWork is a personal AI work platform that goes beyond a chatbot with tools. It builds a persistent understanding of who you are, how your business runs, and how you get work done — then gradually takes on more of that work for you, under your explicit control.

---

## What CogniWork Does

Most AI assistants answer questions. CogniWork is designed to progress through four stages with every user:

```
AI understands your work
        ↓
AI learns your work (within scopes you explicitly authorize)
        ↓
AI executes your work (with review checkpoints, expanding over time)
        ↓
AI improves your work
```

Core capabilities:

- **Personal Profile** — CogniWork interviews you to understand your role, company context, business goals, tools, and preferences.
- **Memory System** — Semantic memory (facts about your company/product/customers), episodic memory (past tasks and decisions), and preference memory (your writing style, formats, habits).
- **Task Execution Workspace** — A chat-based workspace where you delegate real tasks, review AI output, and connect your tools via MCP.
- **Skill Library** — Reusable, structured capabilities distilled from how you actually work — created manually at first, later semi-automatically with your confirmation.
- **Computer Use (Desktop)** — CogniWork's desktop client can operate a defined whitelist of local applications (e.g. Excel, browser, email client) on your behalf, with per-application opt-in.
- **Browser Automation** — Playwright-based automation for SaaS tools and web workflows.

---

## Product Form

CogniWork ships as two connected surfaces sharing one account, memory, and skill library:

| Surface | Role |
|---|---|
| **Web SaaS** | Primary entry point. Zero install, used for onboarding and lower-trust tasks (one-off task delegation, read-only tool connections). |
| **Desktop App** | Full client with local Computer Use capability, for users who want deeper automation of local applications. Not a thin wrapper — it runs a local agent process for whitelisted app automation. |

You can start on the web and move to desktop without losing any context — memories and skills carry over.

---

## Trust-First Design

CogniWork does not assume broad access. Every capability is unlocked progressively, and the user is always in control:

```
Level 1: One-off task delegation      → no authorization required
Level 2: Read-only tool connections   → e.g. Gmail read-only, calendar read-only
Level 3: Action-taking tools /        → e.g. send email, create task,
         local app operation             operate a specific whitelisted app
                                          (each with a review/confirm step)
Level 4: Structured activity logging  → opt-in per scenario, fully visible,
                                          revocable, deletable at any time
```

**Privacy model:** All data collection is off by default. A user opts in individually, sees exactly what will be collected before agreeing, and can review, pause, or delete collected data at any time. CogniWork does not collect raw screen recordings, keystrokes, or mouse coordinates — only structured, purpose-scoped activity records.

---

## Architecture Overview

```
                       CogniWork (AI Coworker OS)

           Web UI                    Desktop UI (Electron + local agent)
              |                                |
                     Agent Orchestration Layer
                                |
        --------------------------------------------------
        |                    |                           |
    Memory OS           Skill Engine                Task Runtime
                                |
                     Tool Execution Layer
                                |
      Browser Automation / SaaS Connectors (MCP) / File System
                                |
        Local Computer Use (Desktop client only, whitelisted apps)
```

### Tech Stack

| Layer | Technology |
|---|---|
| Web Client | React, TypeScript, TailwindCSS |
| Desktop Client | Electron + React/TypeScript, local agent (Python) |
| Backend | Python, FastAPI, PostgreSQL, Redis |
| Agent Runtime | LangGraph |
| Memory | PostgreSQL + pgvector |
| Tool Integration | MCP (Model Context Protocol) |
| Browser Automation | Playwright |
| Desktop Automation | PyAutoGUI / Accessibility API (whitelisted apps only) |

---

## Repository Structure

CogniWork is developed as a monorepo, with the local desktop automation agent maintained as a separate repository due to its distinct release cadence and security boundary (it runs on end-user machines and requires independent code signing and distribution).

```
cogniwork/                  (this repo — monorepo)
├── apps/
│   ├── web/                 # Web SaaS frontend
│   ├── desktop-shell/       # Electron shell + desktop UI (not created yet — P0-08)
│   └── backend/             # FastAPI backend, Agent Orchestration, Memory OS,
│                            #   and the four SaaS connectors (src/cogniwork/tools/)
├── packages/
│   ├── shared-ui/           # Components shared between web and desktop
│   ├── shared-types/        # API types, Skill schema definitions
│   └── mcp-connectors/      # stdio entry point notes; the adapters live in the
│                            #   backend — see deviation 12 in docs/design/README.md
└── docs/

cogniwork-desktop-agent/     (separate repo)
└── Local Computer Use agent — whitelisted-application automation,
    independently versioned, signed, and distributed.
```

---

## Development Roadmap

| Phase | Timeline | Focus |
|---|---|---|
| **Phase 1** | 0–3 months | Web SaaS + Desktop app with whitelisted Computer Use, Memory System, MCP tool connections, manual Skill creation, trust-tier privacy model |
| **Phase 2** | 3–6 months | Structured activity logging, semi-automatic Skill generation, browser automation, expanded Computer Use app whitelist |
| **Phase 3** | 6–12 months | Multi-agent team, agent marketplace, enterprise knowledge base, enterprise workflow automation |

---

## Deploy

Production runbook (Chinese): [`docs/deploy.md`](docs/deploy.md). Local development: [`apps/backend/README.md`](apps/backend/README.md) and [`apps/web/README.md`](apps/web/README.md).

## Status

Early-stage product in active planning and development. Interfaces, schemas, and repository boundaries described above are subject to change as Phase 1 validation progresses.


