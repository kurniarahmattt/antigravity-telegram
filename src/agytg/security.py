"""Whitelist auth + safe project-path resolution."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set


class AccessDenied(Exception):
    pass


class InvalidProject(Exception):
    pass


class Security:
    def __init__(self, allowed_users: List[int], approved_directory: Path):
        self.allowed_users: Set[int] = set(allowed_users)
        self.approved_directory: Path = approved_directory.resolve()

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.allowed_users

    def list_projects(self) -> List[str]:
        if not self.approved_directory.exists():
            return []
        names = []
        for entry in sorted(self.approved_directory.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                names.append(entry.name)
        return names

    def resolve_project(self, name: Optional[str]) -> Path:
        """Resolve a project name to an absolute path inside approved_directory.

        `None` or empty → approved_directory itself.
        """
        if not name or name == ".":
            return self.approved_directory

        if "/" in name or name.startswith(".."):
            raise InvalidProject(f"Invalid project name: {name!r}")

        candidate = (self.approved_directory / name).resolve()
        try:
            candidate.relative_to(self.approved_directory)
        except ValueError:
            raise InvalidProject(f"Path escapes approved dir: {name!r}")

        if not candidate.exists() or not candidate.is_dir():
            raise InvalidProject(f"Project not found: {name!r}")

        return candidate
