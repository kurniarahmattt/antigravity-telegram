"""Entry point: load config, build deps, run polling loop."""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from .agy_runner import AgyRunner
from .bot import Bot, build_application
from .config import Settings
from .security import Security
from .session import SessionStore


def setup_logging(level: str, debug: bool) -> None:
    log_level = logging.DEBUG if debug else getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.KeyValueRenderer(key_order=["event"]),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    # Quiet noisy libs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)


async def _amain() -> None:
    settings = Settings()
    setup_logging(settings.log_level, settings.debug)

    log = structlog.get_logger()
    log.info(
        "boot",
        approved_directory=str(settings.approved_directory),
        allowed_users=settings.allowed_users,
        agy_bin=settings.agy_bin,
    )

    store = SessionStore(settings.database_path)
    await store.init()

    runner = AgyRunner(
        agy_bin=settings.agy_bin,
        conversations_dir=settings.agy_conversations_dir,
        timeout_seconds=settings.agy_timeout_seconds,
        skip_permissions=settings.agy_skip_permissions,
        chat_scratch_dir=settings.agy_chat_scratch_dir,
    )

    security = Security(
        allowed_users=settings.allowed_users,
        approved_directory=settings.approved_directory,
    )

    bot = Bot(
        runner=runner,
        store=store,
        security=security,
        bot_username=settings.telegram_bot_username,
        chat_prompt_prefix=settings.chat_prompt_prefix,
    )

    app = build_application(settings.telegram_bot_token, bot)

    log.info("polling.start")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        try:
            # Block forever; PTB handles its own signal teardown when the
            # process receives SIGINT/SIGTERM and asyncio cancels this task.
            stop_event = asyncio.Event()
            await stop_event.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            log.info("polling.stop")
            await app.updater.stop()
            await app.stop()


def run() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
