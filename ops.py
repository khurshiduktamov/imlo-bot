"""Keeping the bot healthy: error alerts, daily backups, heartbeat, restarts after a deploy."""
import asyncio
import collections
import gzip
import logging
import os
import time
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, html
from aiogram.types import BufferedInputFile

import db
from common import ADMIN_IDS, BASE_DIR, DATA_DIR

HEARTBEAT_FILE = os.path.join(DATA_DIR, "heartbeat")
# deploy.sh touches this file; the bot exits when it changes and alwaysdata starts it again
RESTART_FILE = os.path.join(BASE_DIR, ".restart_request")
BACKUP_HOUR = 3  # daily backup time, Tashkent

log = logging.getLogger("ops")


# ---------------------------------------------------------------- error alerts

class AlertHandler(logging.Handler):
    """Collects ERROR log records; alert_loop() sends them to the admins in batches."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.queue = collections.deque(maxlen=50)  # thread-safe; file jobs log from worker threads
        self.setFormatter(logging.Formatter("%(asctime)s %(name)s\n%(message)s"))

    def emit(self, record):
        if record.name == "ops":
            return  # never alert about failing to alert
        if record.name == "aiogram.dispatcher" and "Failed to fetch updates" in record.getMessage():
            return  # network blips: aiogram retries by itself
        try:
            text = self.format(record)
        except Exception:
            text = record.getMessage()
        self.queue.append(text[-1500:])  # the end of a traceback is the useful part


alerts = AlertHandler()


async def alert_loop(bot: Bot):
    while True:
        await asyncio.sleep(60)  # at most one alert message per minute
        if not alerts.queue:
            continue
        items = []
        while alerts.queue:
            items.append(alerts.queue.popleft())
        body = "\n\n".join(items)[-3500:]
        text = f"⚠️ <b>Bot errors ({len(items)})</b>\n<pre>{html.quote(body)}</pre>"
        for admin in ADMIN_IDS:
            try:
                await bot.send_message(admin, text)
            except Exception as e:
                log.warning("Could not send alert to %s: %s", admin, e)


# ---------------------------------------------------------------- backups

async def send_backup(bot: Bot, chat_id, note="Daily backup"):
    data = gzip.compress(await asyncio.to_thread(db.backup_bytes))
    s = db.stats()
    name = f"imlobot-{datetime.now(db.TASHKENT):%Y-%m-%d}.db.gz"
    await bot.send_document(chat_id, BufferedInputFile(data, filename=name), caption=(
        f"🗄 {note}\nUsers: {s['users']} · active 24h: {s['active_1d']} · Premium: {s['premium_active']}\n"
        "Restore: gunzip, then replace data/bot.db while the bot is stopped."))


async def backup_loop(bot: Bot):
    while True:
        now = datetime.now(db.TASHKENT)
        nxt = now.replace(hour=BACKUP_HOUR, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        for admin in ADMIN_IDS:
            try:
                await send_backup(bot, admin)
            except Exception:
                log.exception("Daily backup to %s failed", admin)
                logging.error("Daily backup failed (see log)")  # goes to the alert queue


# ---------------------------------------------------------------- heartbeat & restarts

async def heartbeat_loop():
    """healthcheck.py (alwaysdata 'monitoring command') restarts the bot if this file goes stale."""
    os.makedirs(DATA_DIR, exist_ok=True)
    while True:
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(int(time.time())))
        except OSError as e:
            log.warning("Heartbeat write failed: %s", e)
        await asyncio.sleep(30)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


restart_requested = False


async def restart_watch_loop(dp: Dispatcher):
    """Stop polling when deploy.sh touches RESTART_FILE; main() then exits and alwaysdata
    starts the service again with the new code."""
    global restart_requested
    started = _mtime(RESTART_FILE)
    while True:
        await asyncio.sleep(10)
        if _mtime(RESTART_FILE) > started:
            log.warning("Restart requested by deploy: stopping")
            restart_requested = True
            await dp.stop_polling()
            return


def start_background_tasks(bot: Bot, dp: Dispatcher):
    tasks = [alert_loop(bot), backup_loop(bot), heartbeat_loop(), restart_watch_loop(dp)]
    # keep references so the tasks are not garbage-collected
    return [asyncio.create_task(t) for t in tasks]
