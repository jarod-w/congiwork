"""内置工具（L1，无需授权）。核心路径全程走这里。"""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from cogniwork.consent.models import Risk
from cogniwork.core.clock import now
from cogniwork.core.ids import new_id
from cogniwork.runtime.models import Artifact
from cogniwork.runtime.weekly_report import build_weekly_report, table_as_text

from .spec import ToolResult, ToolSpec

READ_UPLOADED_FILE = ToolSpec(
    name="builtin.read_uploaded_file",
    provider="builtin",
    description="Read a file the user uploaded for this task. Pass the file_id.",
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Uploaded file id"},
        },
        "required": ["file_id"],
    },
    scope_key=None,
    risk=Risk.READ,
)

WRITE_ARTIFACT = ToolSpec(
    name="builtin.write_artifact",
    provider="builtin",
    description=(
        "Write a downloadable artifact for this task. "
        "Use markdown or csv text, or pass generate='weekly_report' to build "
        "a weekly report from an uploaded spreadsheet."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "content": {"type": "string", "description": "UTF-8 text body"},
            "content_base64": {"type": "string"},
            "content_type": {"type": "string"},
            "generate": {
                "type": "string",
                "enum": ["weekly_report"],
                "description": "Build a weekly report from an uploaded spreadsheet",
            },
            "source_file_id": {"type": "string"},
        },
        "required": ["filename"],
    },
    scope_key=None,
    # 写产物仍是 L1：只作用于本次任务，用户随后下载。给它加 Scope
    # 会让零授权 E2E（P0-07 §8.3）当场失败。
    risk=Risk.WRITE,
)

SEARCH_MEMORY = ToolSpec(
    name="builtin.search_memory",
    provider="builtin",
    description="Search the user's own memory. Returns nothing until Memory OS ships.",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    scope_key=None,
    risk=Risk.READ,
)

ASK_USER = ToolSpec(
    name="builtin.ask_user",
    provider="builtin",
    description="Ask the user a clarifying question as a structured prompt.",
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question"],
    },
    scope_key=None,
    risk=Risk.READ,
)

BUILTIN_TOOLS = (READ_UPLOADED_FILE, WRITE_ARTIFACT, SEARCH_MEMORY, ASK_USER)


class BuiltinExecutor:
    """只操作本次任务的上传文件与产物，没有上游 SaaS。"""

    def invoke(
        self, spec: ToolSpec, arguments: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        if spec.name == READ_UPLOADED_FILE.name:
            return self._read(arguments, context)
        if spec.name == WRITE_ARTIFACT.name:
            return self._write(arguments, context)
        if spec.name == SEARCH_MEMORY.name:
            return ToolResult(
                spec.name,
                True,
                "No memories stored yet. Continue with the files and instructions "
                "you already have.",
            )
        if spec.name == ASK_USER.name:
            question = str(arguments.get("question") or "").strip()
            return ToolResult(
                spec.name,
                True,
                f"Asked the user: {question}",
                {"question": question, "choices": arguments.get("choices") or []},
            )
        return ToolResult(spec.name, False, f"Unknown builtin tool: {spec.name}")

    def _read(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        file_id = arguments.get("file_id")
        store = context["store"]
        user_id = context["user_id"]
        if not file_id:
            return ToolResult(READ_UPLOADED_FILE.name, False, "file_id is required")
        uploaded = store.get_file(UUID(str(user_id)), UUID(str(file_id)))
        if uploaded is None:
            return ToolResult(READ_UPLOADED_FILE.name, False, "File not found for this account.")
        text = table_as_text(uploaded.content, uploaded.filename)
        preview = text if len(text) < 8000 else text[:8000] + "\n…(truncated)"
        return ToolResult(
            READ_UPLOADED_FILE.name,
            True,
            preview,
            {
                "file_id": str(uploaded.id),
                "filename": uploaded.filename,
                "content_type": uploaded.content_type,
                "size_bytes": uploaded.size_bytes,
            },
        )

    def _write(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        store = context["store"]
        user_id = UUID(str(context["user_id"]))
        task_id = UUID(str(context["task_id"]))
        generate = arguments.get("generate")
        filename = str(arguments.get("filename") or "artifact.md")
        artifacts: list[Artifact] = []

        if generate == "weekly_report":
            source_id = arguments.get("source_file_id") or (context.get("file_ids") or [None])[0]
            if not source_id:
                return ToolResult(WRITE_ARTIFACT.name, False, "source_file_id is required")
            uploaded = store.get_file(user_id, UUID(str(source_id)))
            if uploaded is None:
                return ToolResult(WRITE_ARTIFACT.name, False, "Source file not found.")
            markdown, xlsx = build_weekly_report(uploaded.content, uploaded.filename)
            artifacts.append(
                _artifact(
                    user_id,
                    task_id,
                    _ensure_ext(filename, ".md"),
                    "text/markdown",
                    markdown.encode(),
                )
            )
            artifacts.append(
                _artifact(
                    user_id,
                    task_id,
                    _ensure_ext(filename, ".xlsx").replace(".md", ".xlsx"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    xlsx,
                )
            )
        else:
            raw = arguments.get("content_base64")
            if raw:
                body = base64.b64decode(str(raw))
            else:
                body = str(arguments.get("content") or "").encode()
            content_type = str(arguments.get("content_type") or _guess_type(filename))
            artifacts.append(_artifact(user_id, task_id, filename, content_type, body))

        created = []
        for item in artifacts:
            store.put_artifact(item)
            created.append(
                {
                    "id": str(item.id),
                    "filename": item.filename,
                    "content_type": item.content_type,
                    "size_bytes": item.size_bytes,
                }
            )
        names = ", ".join(item["filename"] for item in created)
        return ToolResult(
            WRITE_ARTIFACT.name,
            True,
            f"Wrote {names}.",
            {"artifacts": created},
        )


def _artifact(
    user_id: UUID, task_id: UUID, filename: str, content_type: str, content: bytes
) -> Artifact:
    return Artifact(
        id=new_id(),
        user_id=user_id,
        task_id=task_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        content=content,
        created_at=now(),
    )


def _ensure_ext(filename: str, ext: str) -> str:
    lower = filename.lower()
    if lower.endswith(ext):
        return filename
    if "." in filename:
        return filename.rsplit(".", 1)[0] + ext
    return filename + ext


def _guess_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".md"):
        return "text/markdown"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lower.endswith(".json"):
        return "application/json"
    return "text/plain"
