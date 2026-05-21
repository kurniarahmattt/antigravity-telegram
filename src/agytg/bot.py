"""Telegram bot handlers — hybrid chat / code mode.

Modes
-----
- **Chat mode** (default, no active project): the bot sends prompts to
  `agy --print` *without* `--add-dir`, so agy answers conversationally.
- **Code mode** (active project set via /repo <name>): the bot sends prompts
  with `--add-dir <project>` and `--dangerously-skip-permissions`, so agy can
  read and edit files in that project non-interactively.

`/chat` returns to chat mode. Each (user, scope) pair has its own conversation
ID. The "chat" scope is stored as the literal string ":chat:".
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

import structlog
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .agy_runner import AgyRunner
from .formatter import markdown_to_telegram_html
from .security import InvalidProject, Security
from .session import SessionStore

logger = structlog.get_logger()

CHAT_SCOPE = ":chat:"
MAX_TG_LEN = 3800


def _chunk(text: str, max_len: int = MAX_TG_LEN):
    if not text:
        yield text
        return
    while text:
        if len(text) <= max_len:
            yield text
            return
        cut = text.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        yield text[:cut]
        text = text[cut:].lstrip("\n")


class Bot:
    def __init__(
        self,
        runner: AgyRunner,
        store: SessionStore,
        security: Security,
        bot_username: str,
    ):
        self.runner = runner
        self.store = store
        self.security = security
        self.bot_username = bot_username

    async def _check_auth(self, update: Update) -> bool:
        user = update.effective_user
        if not user or not self.security.is_authorized(user.id):
            uid = user.id if user else "?"
            logger.warning("auth.denied", user_id=uid)
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"Akses ditolak. User ID kamu: {uid}\n"
                    "Hubungi admin untuk menambahkan ID ke ALLOWED_USERS."
                )
            return False
        return True

    async def _resolve_mode(self, user_id: int):
        """Return (workspace_or_None, scope_label).

        workspace=None means chat mode; scope_label is what we key
        conversations by in storage (":chat:" or the project relpath).
        """
        name = await self.store.get_project(user_id)
        if not name:
            return None, CHAT_SCOPE
        try:
            project = self.security.resolve_project(name)
        except InvalidProject:
            # Stale or invalid pointer — fall back to chat.
            await self.store.clear_project(user_id)
            return None, CHAT_SCOPE
        rel = str(project.relative_to(self.security.approved_directory)) or "."
        return project, rel

    # ----- commands -----

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        user = update.effective_user
        workspace, scope = await self._resolve_mode(user.id)
        if workspace is None:
            mode_line = "💬 Mode: <b>chat</b> (obrolan polos, agy tidak akses file)"
        else:
            mode_line = (
                f"🛠️ Mode: <b>code</b> — project <code>{html.escape(scope)}</code>"
            )
        await update.effective_message.reply_text(
            "Halo! Saya wrapper Telegram untuk <b>agy</b> (Antigravity CLI).\n\n"
            f"{mode_line}\n"
            f"📂 Base dir: <code>{html.escape(str(self.security.approved_directory))}</code>\n\n"
            "Perintah:\n"
            "• /repo — daftar project / pindah ke code mode\n"
            "• /chat — kembali ke chat mode\n"
            "• /new — reset conversation untuk scope sekarang\n"
            "• /status — info session\n"
            "• /whoami — user ID kamu\n\n"
            "Kirim pesan apa saja untuk diteruskan ke agy.",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_whoami(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.effective_message.reply_text(
            f"User ID: <code>{user.id}</code>\nUsername: @{user.username or '-'}",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        user = update.effective_user
        _, scope = await self._resolve_mode(user.id)
        await self.store.clear_conversation(user.id, scope)
        label = "chat" if scope == CHAT_SCOPE else f"project <code>{html.escape(scope)}</code>"
        await update.effective_message.reply_text(
            f"Conversation untuk {label} di-reset. "
            "Pesan berikutnya akan memulai conversation baru.",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_chat(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        user = update.effective_user
        await self.store.clear_project(user.id)
        existing = await self.store.get_conversation(user.id, CHAT_SCOPE)
        msg = "💬 Kembali ke chat mode (tidak akses workspace)."
        if existing:
            msg += f"\nResume conversation: <code>{html.escape(existing[:8])}…</code>"
        else:
            msg += "\nConversation baru akan dimulai saat kamu kirim pesan."
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def cmd_repo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        user = update.effective_user
        args = ctx.args or []

        if not args:
            projects = self.security.list_projects()
            current = await self.store.get_project(user.id)
            if not projects:
                await update.effective_message.reply_text(
                    f"Tidak ada subfolder di base dir: <code>{html.escape(str(self.security.approved_directory))}</code>",
                    parse_mode=ParseMode.HTML,
                )
                return
            lines = ["<b>Project tersedia:</b>"]
            for p in projects:
                marker = " ◀" if p == current else ""
                lines.append(f"• <code>{html.escape(p)}</code>{marker}")
            lines.append("")
            lines.append(
                "Pakai <code>/repo &lt;nama&gt;</code> untuk masuk code mode, "
                "atau <code>/chat</code> untuk kembali ke chat mode."
            )
            await update.effective_message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.HTML
            )
            return

        name = args[0]
        try:
            project = self.security.resolve_project(name)
        except InvalidProject as e:
            await update.effective_message.reply_text(f"⛔ {e}")
            return

        rel = str(project.relative_to(self.security.approved_directory)) or "."
        await self.store.set_project(user.id, rel)
        existing = await self.store.get_conversation(user.id, rel)
        msg = (
            f"🛠️ Code mode aktif: <code>{html.escape(rel)}</code>\n"
            f"Workspace: <code>{html.escape(str(project))}</code>"
        )
        if existing:
            msg += f"\nResume conversation: <code>{html.escape(existing[:8])}…</code>"
        else:
            msg += "\nConversation baru akan dimulai saat kamu kirim pesan."
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        user = update.effective_user
        workspace, scope = await self._resolve_mode(user.id)
        conv = await self.store.get_conversation(user.id, scope)
        mode = "chat" if workspace is None else "code"
        ws_line = (
            "—" if workspace is None else html.escape(str(workspace))
        )
        await update.effective_message.reply_text(
            "<b>Status</b>\n"
            f"User ID: <code>{user.id}</code>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Scope: <code>{html.escape(scope)}</code>\n"
            f"Workspace: <code>{ws_line}</code>\n"
            f"Conversation: <code>{html.escape(conv or '(belum ada)')}</code>",
            parse_mode=ParseMode.HTML,
        )

    # ----- chat -----

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        msg = update.effective_message
        if not msg or not msg.text or msg.text.startswith("/"):
            return

        user = update.effective_user
        workspace, scope = await self._resolve_mode(user.id)
        conv_id: Optional[str] = await self.store.get_conversation(user.id, scope)

        await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)

        try:
            result = await self.runner.run(
                prompt=msg.text,
                workspace=workspace,
                conversation_id=conv_id,
            )
        except Exception as e:
            logger.exception("agy.run.error")
            await msg.reply_text(f"⚠️ Error menjalankan agy: {e}")
            return

        if result.timed_out:
            await msg.reply_text(
                f"⏱️ Timeout setelah {self.runner.timeout_seconds}s. Coba pesan lebih kecil."
            )
            return

        if result.returncode != 0:
            err_excerpt = (result.stderr or "")[-500:].strip()
            await msg.reply_text(
                f"⚠️ agy exited {result.returncode}.\n<pre>{html.escape(err_excerpt) or '(no stderr)'}</pre>",
                parse_mode=ParseMode.HTML,
            )
            return

        if result.conversation_id and result.conversation_id != conv_id:
            await self.store.set_conversation(user.id, scope, result.conversation_id)

        reply = (result.stdout or "").strip()
        if not reply:
            reply = "(agy returned empty output)"

        await self._send_formatted(msg, reply)

    async def _send_formatted(self, msg, text: str) -> None:
        """Send `text` to Telegram with markdown→HTML conversion. On HTML
        parse rejection by Telegram, fall back to plain text."""
        html_text = markdown_to_telegram_html(text)
        for chunk in _chunk(html_text):
            try:
                await msg.reply_text(
                    chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.warning("reply.html_failed", error=str(e))
                # Fallback: send the chunk's plain-text equivalent so the
                # user at least sees the content.
                await msg.reply_text(_strip_html(chunk))


def _strip_html(s: str) -> str:
    import re as _re
    return _re.sub(r"<[^>]+>", "", s)


def build_application(token: str, bot: Bot) -> Application:
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("help", bot.cmd_start))
    app.add_handler(CommandHandler("new", bot.cmd_new))
    app.add_handler(CommandHandler("repo", bot.cmd_repo))
    app.add_handler(CommandHandler("chat", bot.cmd_chat))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("whoami", bot.cmd_whoami))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.on_text))

    return app
