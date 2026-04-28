"""Точка входа: запускает БД, FastAPI и Telegram бот в одном процессе."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import uvicorn

import db
import core
import bot
from web import app as web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def run_web():
    port = int(os.environ.get("PORT", "5000"))
    config = uvicorn.Config(
        web_app, host="0.0.0.0", port=port, log_level="info", access_log=False
    )
    server = uvicorn.Server(config)
    log.info("Web starting on http://0.0.0.0:%s", port)
    await server.serve()


async def main():
    db.init_db()
    log.info("DB ready: %s", db.DB_PATH)
    core.bootstrap_admins_from_env()

    tasks = [asyncio.create_task(run_web())]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        tasks.append(asyncio.create_task(bot.run_bot()))
    else:
        log.warning("TELEGRAM_BOT_TOKEN не задан — запускаю только веб")

    stop = asyncio.Event()

    def _shutdown(*_):
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass
    except RuntimeError:
        pass

    done, pending = await asyncio.wait(
        tasks + [asyncio.create_task(stop.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
