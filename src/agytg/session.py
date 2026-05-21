"""SQLite-backed per-(user, project) conversation tracking + current project."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    user_id     INTEGER NOT NULL,
    project     TEXT    NOT NULL,
    conversation_id TEXT NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (user_id, project)
);

CREATE TABLE IF NOT EXISTS user_state (
    user_id     INTEGER PRIMARY KEY,
    project     TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);
"""


class SessionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def get_conversation(self, user_id: int, project: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT conversation_id FROM conversations WHERE user_id=? AND project=?",
                (user_id, project),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def set_conversation(
        self, user_id: int, project: str, conversation_id: str
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO conversations (user_id, project, conversation_id, updated_at)
                VALUES (?, ?, ?, strftime('%s','now'))
                ON CONFLICT(user_id, project) DO UPDATE SET
                    conversation_id=excluded.conversation_id,
                    updated_at=excluded.updated_at
                """,
                (user_id, project, conversation_id),
            )
            await db.commit()

    async def clear_conversation(self, user_id: int, project: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM conversations WHERE user_id=? AND project=?",
                (user_id, project),
            )
            await db.commit()

    async def get_project(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT project FROM user_state WHERE user_id=?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def set_project(self, user_id: int, project: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_state (user_id, project, updated_at)
                VALUES (?, ?, strftime('%s','now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    project=excluded.project,
                    updated_at=excluded.updated_at
                """,
                (user_id, project),
            )
            await db.commit()

    async def clear_project(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))
            await db.commit()
