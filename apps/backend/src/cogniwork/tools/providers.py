"""Provider adapters. They receive an already-approved call and a token.

They do not decide whether the user is allowed to call them.
"""

from __future__ import annotations

from typing import Any

from cogniwork.runtime.tools.spec import ToolResult
from cogniwork.tools.http import HttpTransport


def invoke_provider(
    provider: str,
    mcp_name: str,
    arguments: dict[str, Any],
    token: str,
    transport: HttpTransport,
) -> ToolResult:
    if provider == "gcal":
        return _gcal(mcp_name, arguments, token, transport)
    if provider == "notion":
        return _notion(mcp_name, arguments, token, transport)
    if provider == "gmail":
        return _gmail(mcp_name, arguments, token, transport)
    if provider == "github":
        return _github(mcp_name, arguments, token, transport)
    return ToolResult(mcp_name, False, f"Unknown provider: {provider}")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _gcal(name: str, arguments: dict[str, Any], token: str, http: HttpTransport) -> ToolResult:
    if name == "list_events":
        resp = http.request(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=_auth(token),
            params={
                "timeMin": arguments.get("time_min"),
                "timeMax": arguments.get("time_max"),
                "q": arguments.get("query"),
                "maxResults": arguments.get("max_results") or 10,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        items = (resp.data or {}).get("items") or []
        lines = [f"- {row.get('summary') or row.get('id')}" for row in items[:20]]
        return ToolResult(
            "gcal.list_events",
            True,
            "Events:\n" + ("\n".join(lines) or "(none)"),
            {"count": len(items)},
        )
    if name == "get_event":
        event_id = arguments.get("event_id")
        resp = http.request(
            "GET",
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
            headers=_auth(token),
        )
        summary = (resp.data or {}).get("summary") or event_id
        return ToolResult("gcal.get_event", True, f"Event: {summary}", {"id": event_id})
    if name == "find_free_slots":
        resp = http.request(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=_auth(token),
            params={
                "timeMin": arguments.get("time_min"),
                "timeMax": arguments.get("time_max"),
                "singleEvents": "true",
            },
        )
        busy = len((resp.data or {}).get("items") or [])
        return ToolResult(
            "gcal.find_free_slots",
            True,
            f"Found {busy} busy events in that window. Open slots are the gaps between them.",
            {"busy_count": busy, "duration_minutes": arguments.get("duration_minutes") or 30},
        )
    if name == "create_event":
        resp = http.request(
            "POST",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=_auth(token),
            json_body={
                "summary": arguments.get("summary"),
                "start": {"dateTime": arguments.get("start")},
                "end": {"dateTime": arguments.get("end")},
                "attendees": [{"email": item} for item in (arguments.get("attendees") or [])],
            },
        )
        event_id = (resp.data or {}).get("id") or "e1"
        return ToolResult("gcal.create_event", True, f"Created event {event_id}.", {"id": event_id})
    if name == "update_event":
        event_id = arguments.get("event_id")
        resp = http.request(
            "PATCH",
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
            headers=_auth(token),
            json_body={
                "summary": arguments.get("summary"),
                "start": {"dateTime": arguments.get("start")} if arguments.get("start") else None,
                "end": {"dateTime": arguments.get("end")} if arguments.get("end") else None,
            },
        )
        return ToolResult(
            "gcal.update_event",
            True,
            f"Updated event {event_id}.",
            {"id": (resp.data or {}).get("id") or event_id},
        )
    if name == "delete_event":
        event_id = arguments.get("event_id")
        http.request(
            "DELETE",
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
            headers=_auth(token),
        )
        return ToolResult("gcal.delete_event", True, "Event deleted.", {"id": event_id})
    if name == "send_invites":
        event_id = arguments.get("event_id")
        http.request(
            "POST",
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}/sendUpdates",
            headers=_auth(token),
            params={"sendUpdates": "all"},
        )
        return ToolResult("gcal.send_invites", True, "Invites sent.", {"id": event_id})
    return ToolResult(name, False, f"Unknown calendar tool: {name}")


def _notion(name: str, arguments: dict[str, Any], token: str, http: HttpTransport) -> ToolResult:
    headers = {
        **_auth(token),
        "Notion-Version": "2022-06-28",
    }
    if name == "search":
        resp = http.request(
            "POST",
            "https://api.notion.com/v1/search",
            headers=headers,
            json_body={"query": arguments.get("query") or ""},
        )
        results = (resp.data or {}).get("results") or []
        return ToolResult(
            "notion.search",
            True,
            f"Found {len(results)} Notion pages.",
            {"count": len(results), "ids": [r.get("id") for r in results[:10]]},
        )
    if name == "get_page":
        page_id = arguments.get("page_id")
        resp = http.request("GET", f"https://api.notion.com/v1/pages/{page_id}", headers=headers)
        url = (resp.data or {}).get("url") or page_id
        return ToolResult("notion.get_page", True, f"Page {url}", {"id": page_id})
    if name == "query_database":
        database_id = arguments.get("database_id")
        resp = http.request(
            "POST",
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=headers,
            json_body={},
        )
        results = (resp.data or {}).get("results") or []
        return ToolResult(
            "notion.query_database",
            True,
            f"Database returned {len(results)} rows.",
            {"count": len(results)},
        )
    if name == "create_page":
        resp = http.request(
            "POST",
            "https://api.notion.com/v1/pages",
            headers=headers,
            json_body={
                "parent": {"page_id": arguments.get("parent_id")},
                "properties": {
                    "title": {"title": [{"text": {"content": arguments.get("title") or ""}}]}
                },
            },
        )
        page_id = (resp.data or {}).get("id") or "p1"
        return ToolResult("notion.create_page", True, f"Created page {page_id}.", {"id": page_id})
    if name == "update_page":
        page_id = arguments.get("page_id")
        http.request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=headers,
            json_body={},
        )
        return ToolResult("notion.update_page", True, f"Updated page {page_id}.", {"id": page_id})
    if name == "append_block":
        page_id = arguments.get("page_id")
        http.request(
            "PATCH",
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            json_body={
                "children": [
                    {
                        "paragraph": {
                            "rich_text": [{"text": {"content": arguments.get("text") or ""}}]
                        }
                    }
                ]
            },
        )
        return ToolResult("notion.append_block", True, "Appended a block.", {"id": page_id})
    if name == "delete_block":
        block_id = arguments.get("block_id")
        http.request(
            "DELETE",
            f"https://api.notion.com/v1/blocks/{block_id}",
            headers=headers,
        )
        return ToolResult("notion.delete_block", True, "Block deleted.", {"id": block_id})
    return ToolResult(name, False, f"Unknown Notion tool: {name}")


def _gmail(name: str, arguments: dict[str, Any], token: str, http: HttpTransport) -> ToolResult:
    if name == "search_messages":
        resp = http.request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=_auth(token),
            params={"q": arguments.get("query"), "maxResults": arguments.get("max_results") or 10},
        )
        messages = (resp.data or {}).get("messages") or []
        return ToolResult(
            "gmail.search_messages",
            True,
            f"Found {len(messages)} messages.",
            {"count": len(messages), "ids": [m.get("id") for m in messages[:10]]},
        )
    if name == "get_message":
        message_id = arguments.get("message_id")
        resp = http.request(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers=_auth(token),
            params={"format": "metadata"},
        )
        snippet = (resp.data or {}).get("snippet") or ""
        return ToolResult(
            "gmail.get_message",
            True,
            f"Message {message_id}: {snippet}".strip(),
            {"id": message_id, "length": len(snippet)},
        )
    if name == "list_threads":
        resp = http.request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/threads",
            headers=_auth(token),
            params={"q": arguments.get("query"), "maxResults": arguments.get("max_results") or 10},
        )
        threads = (resp.data or {}).get("threads") or []
        return ToolResult(
            "gmail.list_threads",
            True,
            f"Found {len(threads)} threads.",
            {"count": len(threads)},
        )
    if name == "create_draft":
        resp = http.request(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            headers=_auth(token),
            json_body={
                "message": {
                    "raw": _gmail_raw(
                        arguments.get("to") or [],
                        arguments.get("subject") or "",
                        arguments.get("body") or "",
                    )
                }
            },
        )
        draft_id = (resp.data or {}).get("id") or "draft"
        return ToolResult(
            "gmail.create_draft",
            True,
            f"Saved draft {draft_id}. It was not sent.",
            {"id": draft_id, "to_count": len(arguments.get("to") or [])},
        )
    if name == "send_message":
        resp = http.request(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers=_auth(token),
            json_body={
                "raw": _gmail_raw(
                    arguments.get("to") or [],
                    arguments.get("subject") or "",
                    arguments.get("body") or "",
                )
            },
        )
        message_id = (resp.data or {}).get("id") or "sent"
        return ToolResult(
            "gmail.send_message",
            True,
            "Email sent.",
            {"id": message_id, "to_count": len(arguments.get("to") or [])},
        )
    if name == "trash_message":
        message_id = arguments.get("message_id")
        http.request(
            "POST",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash",
            headers=_auth(token),
        )
        return ToolResult(
            "gmail.trash_message",
            True,
            "Message moved to trash.",
            {"id": message_id},
        )
    return ToolResult(name, False, f"Unknown Gmail tool: {name}")


def _github(name: str, arguments: dict[str, Any], token: str, http: HttpTransport) -> ToolResult:
    headers = {**_auth(token), "Accept": "application/vnd.github+json"}
    if name == "search_code":
        resp = http.request(
            "GET",
            "https://api.github.com/search/code",
            headers=headers,
            params={"q": arguments.get("query")},
        )
        items = (resp.data or {}).get("items") or []
        return ToolResult(
            "github.search_code",
            True,
            f"Found {len(items)} code hits.",
            {"count": (resp.data or {}).get("total_count") or len(items)},
        )
    if name == "create_issue":
        owner = arguments.get("owner")
        repo = arguments.get("repo")
        resp = http.request(
            "POST",
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            headers=headers,
            json_body={"title": arguments.get("title"), "body": arguments.get("body") or ""},
        )
        number = (resp.data or {}).get("number")
        url = (resp.data or {}).get("html_url")
        return ToolResult(
            "github.create_issue",
            True,
            f"Opened issue #{number}.",
            {"number": number, "url": url},
        )
    if name == "merge_pr":
        owner = arguments.get("owner")
        repo = arguments.get("repo")
        number = arguments.get("number")
        resp = http.request(
            "PUT",
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge",
            headers=headers,
            json_body={"commit_title": arguments.get("commit_title") or f"Merge #{number}"},
        )
        merged = bool((resp.data or {}).get("merged"))
        return ToolResult(
            "github.merge_pr",
            merged,
            "Pull request merged." if merged else "Merge did not complete.",
            {"sha": (resp.data or {}).get("sha")},
        )
    return ToolResult(name, False, f"Unknown GitHub tool: {name}")


def _gmail_raw(to: list[Any], subject: str, body: str) -> str:
    import base64

    recipients = ", ".join(str(item) for item in to)
    message = f"To: {recipients}\r\nSubject: {subject}\r\n\r\n{body}"
    return base64.urlsafe_b64encode(message.encode()).decode().rstrip("=")
