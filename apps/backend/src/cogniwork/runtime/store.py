"""会话 / 任务 / 文件 / 产物存储。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from cogniwork.core.clock import now
from cogniwork.core.ids import new_id

from .models import (
    Artifact,
    Conversation,
    StepStatus,
    StepType,
    Surface,
    Task,
    TaskStatus,
    TaskStep,
    UploadedFile,
)


def _task_from_row(row: dict[str, Any], steps: list[TaskStep] | None = None) -> Task:
    return Task(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        title=row["title"],
        intent=row["intent"],
        status=TaskStatus(row["status"]),
        surface=Surface(row["surface"]),
        skill_id=row["skill_id"],
        input=row["input"] or {},
        result=row["result"],
        error=row["error"],
        thread_id=row["thread_id"],
        cost_usd=float(row["cost_usd"]),
        token_in=int(row["token_in"]),
        token_out=int(row["token_out"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        steps=steps or [],
    )


def _step_from_row(row: dict[str, Any]) -> TaskStep:
    return TaskStep(
        id=row["id"],
        task_id=row["task_id"],
        seq=int(row["seq"]),
        type=StepType(row["type"]),
        title=row["title"],
        status=StepStatus(row["status"]),
        scope_key=row["scope_key"],
        input_digest=row["input_digest"],
        output_digest=row["output_digest"],
        error=row["error"],
        duration_ms=row["duration_ms"],
        created_at=row["created_at"],
    )


def _conversation_from_row(row: dict[str, Any]) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class InMemoryTaskStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.tasks: dict[UUID, Task] = {}
        self.files: dict[UUID, UploadedFile] = {}
        self.artifacts: dict[UUID, Artifact] = {}

    def create_conversation(self, user_id: UUID, title: str | None = None) -> Conversation:
        created = now()
        conv = Conversation(new_id(), user_id, title, created, created)
        self.conversations[conv.id] = conv
        return conv

    def get_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        conv = self.conversations.get(conversation_id)
        if conv is None or conv.user_id != user_id:
            return None
        return conv

    def list_conversations(self, user_id: UUID) -> list[Conversation]:
        found = [c for c in self.conversations.values() if c.user_id == user_id]
        found.sort(key=lambda c: c.updated_at, reverse=True)
        return found

    def touch_conversation(self, conversation_id: UUID, title: str | None = None) -> None:
        conv = self.conversations.get(conversation_id)
        if conv is None:
            return
        conv.updated_at = now()
        if title and not conv.title:
            conv.title = title

    def create_task(self, task: Task) -> Task:
        self.tasks[task.id] = task
        return task

    def get_task(self, user_id: UUID, task_id: UUID) -> Task | None:
        task = self.tasks.get(task_id)
        if task is None or task.user_id != user_id:
            return None
        return task

    def list_tasks(self, user_id: UUID, conversation_id: UUID | None = None) -> list[Task]:
        found = [t for t in self.tasks.values() if t.user_id == user_id]
        if conversation_id is not None:
            found = [t for t in found if t.conversation_id == conversation_id]
        found.sort(key=lambda t: t.created_at, reverse=True)
        return found

    def save_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def add_step(self, step: TaskStep) -> TaskStep:
        task = self.tasks[step.task_id]
        if all(existing.id != step.id for existing in task.steps):
            task.steps.append(step)
        return step

    def save_step(self, step: TaskStep) -> None:
        task = self.tasks[step.task_id]
        for i, existing in enumerate(task.steps):
            if existing.id == step.id:
                task.steps[i] = step
                return
        task.steps.append(step)

    def put_file(self, uploaded: UploadedFile) -> UploadedFile:
        self.files[uploaded.id] = uploaded
        return uploaded

    def get_file(self, user_id: UUID, file_id: UUID) -> UploadedFile | None:
        item = self.files.get(file_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def put_artifact(self, artifact: Artifact) -> Artifact:
        self.artifacts[artifact.id] = artifact
        return artifact

    def get_artifact(self, user_id: UUID, artifact_id: UUID) -> Artifact | None:
        item = self.artifacts.get(artifact_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def list_artifacts(self, user_id: UUID, task_id: UUID) -> list[Artifact]:
        found = [
            a for a in self.artifacts.values() if a.user_id == user_id and a.task_id == task_id
        ]
        found.sort(key=lambda a: a.created_at)
        return found

    def list_files(self, user_id: UUID) -> list[UploadedFile]:
        found = [item for item in self.files.values() if item.user_id == user_id]
        found.sort(key=lambda item: item.created_at, reverse=True)
        return found

    def delete_for_user(self, user_id: UUID) -> int:
        tasks = [task.id for task in self.list_tasks(user_id)]
        for task_id in tasks:
            self.tasks.pop(task_id, None)
        for conv in list(self.conversations.values()):
            if conv.user_id == user_id:
                self.conversations.pop(conv.id, None)
        for item in list(self.files.values()):
            if item.user_id == user_id:
                self.files.pop(item.id, None)
        for item in list(self.artifacts.values()):
            if item.user_id == user_id:
                self.artifacts.pop(item.id, None)
        return len(tasks)

    def clear(self) -> None:
        self.conversations.clear()
        self.tasks.clear()
        self.files.clear()
        self.artifacts.clear()


class PostgresTaskStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def create_conversation(self, user_id: UUID, title: str | None = None) -> Conversation:
        created = now()
        conv_id = new_id()
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation (id, user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (conv_id, user_id, title, created, created),
            )
        return Conversation(conv_id, user_id, title, created, created)

    def get_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversation WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
        return _conversation_from_row(row) if row else None

    def list_conversations(self, user_id: UUID) -> list[Conversation]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversation
                WHERE user_id = %s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_conversation_from_row(r) for r in rows]

    def touch_conversation(self, conversation_id: UUID, title: str | None = None) -> None:
        with self._pool.connection() as conn:
            if title:
                conn.execute(
                    """
                    UPDATE conversation
                    SET updated_at = %s, title = COALESCE(title, %s)
                    WHERE id = %s
                    """,
                    (now(), title, conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE conversation SET updated_at = %s WHERE id = %s",
                    (now(), conversation_id),
                )

    def create_task(self, task: Task) -> Task:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO task (
                    id, user_id, conversation_id, title, intent, status, surface,
                    skill_id, input, result, error, thread_id, cost_usd, token_in,
                    token_out, started_at, ended_at, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    task.id,
                    task.user_id,
                    task.conversation_id,
                    task.title,
                    task.intent,
                    task.status.value,
                    task.surface.value,
                    task.skill_id,
                    Json(task.input),
                    Json(task.result) if task.result is not None else None,
                    Json(task.error) if task.error is not None else None,
                    task.thread_id,
                    task.cost_usd,
                    task.token_in,
                    task.token_out,
                    task.started_at,
                    task.ended_at,
                    task.created_at,
                    task.updated_at,
                ),
            )
        return task

    def get_task(self, user_id: UUID, task_id: UUID) -> Task | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM task WHERE id = %s AND user_id = %s",
                (task_id, user_id),
            ).fetchone()
            if row is None:
                return None
            steps = conn.execute(
                "SELECT * FROM task_step WHERE task_id = %s ORDER BY seq",
                (task_id,),
            ).fetchall()
        return _task_from_row(row, [_step_from_row(s) for s in steps])

    def list_tasks(self, user_id: UUID, conversation_id: UUID | None = None) -> list[Task]:
        sql = "SELECT * FROM task WHERE user_id = %s"
        params: list[Any] = [user_id]
        if conversation_id is not None:
            sql += " AND conversation_id = %s"
            params.append(conversation_id)
        sql += " ORDER BY created_at DESC"
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_task_from_row(r) for r in rows]

    def save_task(self, task: Task) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE task SET
                    title = %s, intent = %s, status = %s, result = %s, error = %s,
                    cost_usd = %s, token_in = %s, token_out = %s,
                    started_at = %s, ended_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    task.title,
                    task.intent,
                    task.status.value,
                    Json(task.result) if task.result is not None else None,
                    Json(task.error) if task.error is not None else None,
                    task.cost_usd,
                    task.token_in,
                    task.token_out,
                    task.started_at,
                    task.ended_at,
                    now(),
                    task.id,
                ),
            )

    def add_step(self, step: TaskStep) -> TaskStep:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO task_step (
                    id, task_id, seq, type, title, status, scope_key,
                    input_digest, output_digest, error, duration_ms, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    step.id,
                    step.task_id,
                    step.seq,
                    step.type.value,
                    step.title,
                    step.status.value,
                    step.scope_key,
                    Json(step.input_digest) if step.input_digest is not None else None,
                    Json(step.output_digest) if step.output_digest is not None else None,
                    Json(step.error) if step.error is not None else None,
                    step.duration_ms,
                    step.created_at,
                ),
            )
        return step

    def save_step(self, step: TaskStep) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE task_step SET
                    title = %s, status = %s, input_digest = %s, output_digest = %s,
                    error = %s, duration_ms = %s
                WHERE id = %s
                """,
                (
                    step.title,
                    step.status.value,
                    Json(step.input_digest) if step.input_digest is not None else None,
                    Json(step.output_digest) if step.output_digest is not None else None,
                    Json(step.error) if step.error is not None else None,
                    step.duration_ms,
                    step.id,
                ),
            )

    def put_file(self, uploaded: UploadedFile) -> UploadedFile:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO uploaded_file (
                    id, user_id, filename, content_type, size_bytes, persist, content, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uploaded.id,
                    uploaded.user_id,
                    uploaded.filename,
                    uploaded.content_type,
                    uploaded.size_bytes,
                    uploaded.persist,
                    uploaded.content,
                    uploaded.created_at,
                ),
            )
        return uploaded

    def get_file(self, user_id: UUID, file_id: UUID) -> UploadedFile | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM uploaded_file WHERE id = %s AND user_id = %s",
                (file_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return UploadedFile(
            id=row["id"],
            user_id=row["user_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            size_bytes=int(row["size_bytes"]),
            persist=bool(row["persist"]),
            content=bytes(row["content"]),
            created_at=row["created_at"],
        )

    def put_artifact(self, artifact: Artifact) -> Artifact:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO artifact (
                    id, user_id, task_id, filename, content_type, size_bytes, content, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    artifact.id,
                    artifact.user_id,
                    artifact.task_id,
                    artifact.filename,
                    artifact.content_type,
                    artifact.size_bytes,
                    artifact.content,
                    artifact.created_at,
                ),
            )
        return artifact

    def get_artifact(self, user_id: UUID, artifact_id: UUID) -> Artifact | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifact WHERE id = %s AND user_id = %s",
                (artifact_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return Artifact(
            id=row["id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            size_bytes=int(row["size_bytes"]),
            content=bytes(row["content"]),
            created_at=row["created_at"],
        )

    def list_artifacts(self, user_id: UUID, task_id: UUID) -> list[Artifact]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM artifact
                WHERE user_id = %s AND task_id = %s
                ORDER BY created_at
                """,
                (user_id, task_id),
            ).fetchall()
        return [
            Artifact(
                id=r["id"],
                user_id=r["user_id"],
                task_id=r["task_id"],
                filename=r["filename"],
                content_type=r["content_type"],
                size_bytes=int(r["size_bytes"]),
                content=bytes(r["content"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def list_files(self, user_id: UUID) -> list[UploadedFile]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM uploaded_file
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            UploadedFile(
                id=r["id"],
                user_id=r["user_id"],
                filename=r["filename"],
                content_type=r["content_type"],
                size_bytes=int(r["size_bytes"]),
                persist=bool(r["persist"]),
                content=bytes(r["content"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def delete_for_user(self, user_id: UUID) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM task WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            count = int(row["n"]) if row else 0
            conn.execute("DELETE FROM conversation WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM uploaded_file WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM artifact WHERE user_id = %s", (user_id,))
        return count

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE conversation CASCADE")
            conn.execute("TRUNCATE uploaded_file")
