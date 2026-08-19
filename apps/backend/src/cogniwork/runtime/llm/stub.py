"""无密钥时的本地模型。把「整理成周报」做成确定性工具调用序列。"""

from __future__ import annotations

import json
from typing import Any

from cogniwork.core.ids import new_id

from .types import ChatMessage, LLMResult, ToolCallDelta


class StubLLM:
    vendor = "stub"
    model = "stub-local"

    def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        on_delta: Any | None = None,
    ) -> LLMResult:
        tool_names = {t["function"]["name"] for t in tools}
        called = _called_tools(messages)
        file_ids = _file_ids_from_messages(messages)

        needs_read = (
            "builtin.read_uploaded_file" in tool_names
            and file_ids
            and "builtin.read_uploaded_file" not in called
        )
        if needs_read:
            return LLMResult(
                text="",
                tool_calls=[
                    ToolCallDelta(
                        id=str(new_id()),
                        name="builtin.read_uploaded_file",
                        arguments={"file_id": file_ids[0]},
                    )
                ],
                vendor=self.vendor,
                model=self.model,
            )

        if "builtin.write_artifact" in tool_names and "builtin.write_artifact" not in called:
            source = file_ids[0] if file_ids else None
            arguments: dict[str, Any] = {
                "filename": "weekly-report.md",
                "generate": "weekly_report",
            }
            if source:
                arguments["source_file_id"] = source
            else:
                arguments["content"] = (
                    "# Weekly report\n\nNo spreadsheet was uploaded. "
                    "Paste a table and I will format it.\n"
                )
            return LLMResult(
                text="",
                tool_calls=[
                    ToolCallDelta(
                        id=str(new_id()),
                        name="builtin.write_artifact",
                        arguments=arguments,
                    )
                ],
                vendor=self.vendor,
                model=self.model,
            )

        text = (
            "Done. I turned the spreadsheet into a weekly report. "
            "You can download the markdown and spreadsheet from the artifacts panel."
        )
        if on_delta:
            on_delta(text)
        return LLMResult(text=text, vendor=self.vendor, model=self.model)


def _called_tools(messages: list[ChatMessage]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if message.role == "tool" and message.name:
            names.add(message.name)
    return names


def _file_ids_from_messages(messages: list[ChatMessage]) -> list[str]:
    for message in messages:
        if message.role != "system":
            continue
        marker = "file_ids="
        if marker not in message.content:
            continue
        raw = message.content.split(marker, 1)[1].split("\n", 1)[0].strip()
        if not raw or raw == "[]":
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed]
    return []
