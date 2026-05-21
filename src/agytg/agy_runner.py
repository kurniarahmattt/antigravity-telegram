"""Wrap the `agy` CLI as an async subprocess.

`agy --help` exposes:
    --print              one-shot non-interactive
    --continue           resume the most recent conversation
    --conversation <id>  resume a specific conversation
    --add-dir <path>     add workspace directory
    --dangerously-skip-permissions
    --print-timeout

Modes
-----
- **Chat mode** (workspace=None): no --add-dir, no
  --dangerously-skip-permissions. agy behaves conversationally because no
  workspace = no project to explore.
- **Code mode** (workspace=Path): pass --add-dir <workspace> +
  --dangerously-skip-permissions so agy can read/edit files non-interactively.

Conversation ID detection
-------------------------
The CLI does not print conversation IDs to stdout. We parse `cli.log` for the
line emitted by `printmode.go`:
    Print mode: starting (... conversationID="<UUID>")
between the byte-offsets snapshotted before and after each invocation.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


# Patterns agy writes to cli.log that contain the conversation UUID. The
# `printmode.go` line on first start has conversationID="" (empty); the real
# UUID shows up later in `Created conversation <uuid>` or
# `Print mode: conversation=<uuid>`.
_UUID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
_CONV_ID_PATTERNS = [
    re.compile(rf'conversationID="{_UUID}"'),
    re.compile(rf"Created conversation {_UUID}"),
    re.compile(rf"Print mode: conversation={_UUID}"),
]

_CLI_LOG_DEFAULT = Path.home() / ".gemini" / "antigravity-cli" / "cli.log"


@dataclass
class AgyResult:
    stdout: str
    stderr: str
    returncode: int
    conversation_id: Optional[str]
    duration_ms: int
    timed_out: bool = False


class AgyRunner:
    def __init__(
        self,
        agy_bin: str,
        conversations_dir: Path,
        timeout_seconds: int,
        skip_permissions: bool,
        cli_log_path: Optional[Path] = None,
    ):
        self.agy_bin = agy_bin
        self.conversations_dir = conversations_dir
        self.timeout_seconds = timeout_seconds
        self.skip_permissions = skip_permissions
        self.cli_log_path = cli_log_path or _CLI_LOG_DEFAULT

    def _resolve_cli_log_target(self) -> Optional[Path]:
        """`cli.log` is typically a symlink that agy retargets each invocation
        to `log/cli-<timestamp>.log`. Return the current target path, or None
        if the symlink is missing."""
        try:
            return self.cli_log_path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return None

    def _extract_conversation_id(self, log_path: Optional[Path]) -> Optional[str]:
        """Scan a (per-invocation) agy log file for the conversation UUID."""
        if log_path is None or not log_path.exists():
            return None
        try:
            blob = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        for pat in _CONV_ID_PATTERNS:
            m = pat.search(blob)
            if m:
                return m.group(1)
        return None

    async def run(
        self,
        prompt: str,
        conversation_id: Optional[str],
        workspace: Optional[Path] = None,
    ) -> AgyResult:
        """Run agy --print and capture its stdout.

        - If `workspace` is None → chat mode (no --add-dir).
        - If `conversation_id` is None → start a new conversation and try to
          extract its ID from cli.log.
        """
        argv = [self.agy_bin, "--print"]
        if workspace is not None:
            argv.extend(["--add-dir", str(workspace)])
            if self.skip_permissions:
                argv.append("--dangerously-skip-permissions")
        if conversation_id:
            argv.extend(["--conversation", conversation_id])
        argv.append(prompt)

        logger.info(
            "agy.run",
            workspace=str(workspace) if workspace else None,
            chat_mode=workspace is None,
            conversation_id=conversation_id,
            prompt_len=len(prompt),
        )

        loop = asyncio.get_running_loop()
        start = loop.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout_seconds
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()
                timed_out = True
        except FileNotFoundError as e:
            raise RuntimeError(f"agy binary not found at {self.agy_bin!r}: {e}")

        duration_ms = int((loop.time() - start) * 1000)
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")

        resolved_id = conversation_id
        if not conversation_id:
            log_target = self._resolve_cli_log_target()
            resolved_id = self._extract_conversation_id(log_target)
            if not resolved_id:
                logger.warning(
                    "agy.run.no_conversation_id",
                    cli_log=str(log_target) if log_target else None,
                    msg="could not extract conversation ID from agy log",
                )

        logger.info(
            "agy.run.done",
            returncode=proc.returncode,
            duration_ms=duration_ms,
            conversation_id=resolved_id,
            timed_out=timed_out,
            stdout_len=len(out),
        )

        return AgyResult(
            stdout=out,
            stderr=err,
            returncode=proc.returncode if proc.returncode is not None else -1,
            conversation_id=resolved_id,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
