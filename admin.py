"""Admin-only commands: /admin, /stats, /users, /broadcast, /givepremium, /refund, /backup.

All of them work only in a private chat with the bot, so nothing leaks into a group.
"""
import asyncio
import logging
import time
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)

import db
import ops
from common import ADMIN_IDS, PREMIUM_DAYS

router = Router(name="admin")
# every handler in this router: admins only, private chat only
router.message.filter(F.from_user.id.in_(ADMIN_IDS), F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


@router.message(Command("admin"))
async def admin_help(message: Message) -> None:
    await message.answer(
        "👑 <b>Admin commands</b>\n\n"
        "/stats — users, activity, Premium, revenue\n"
        "/users — full user list (CSV)\n"
        "/broadcast — reply to any message with this to send it to all users\n"
        f"/givepremium <code>user_id</code> [days] — free Premium (default {PREMIUM_DAYS} days)\n"
        "/refund <code>charge_id</code> — refund a Stars payment (id is in the payment notice)\n"
        "/backup — database backup now (also sent daily at 03:00)")


@router.message(Command("stats"))
async def command_stats(message: Message) -> None:
    s = db.stats()
    top = max([n for _, n in s["daily"]] + [1])
    daily = "\n".join(f"{day[5:]}  {'▇' * max(1, round(n / top * 12)) if n else '·'} {n}"
                      for day, n in s["daily"])
    since = ("—" if not s["tracking_since"] else
             datetime.fromtimestamp(s["tracking_since"], db.TASHKENT).strftime("%Y-%m-%d"))
    await message.answer(
        "📊 <b>Bot statistics</b>\n\n"
        f"Users: <b>{s['users']}</b> (blocked the bot: {s['blocked']})\n"
        f"Groups: {s['groups']} · prefer old Latin: {s['latin_old']}\n\n"
        "<b>Active users</b> (sent anything)\n"
        f"24h: <b>{s['active_1d']}</b> · 7d: <b>{s['active_7d']}</b> · 30d: <b>{s['active_30d']}</b>\n"
        f"Used inline mode (7d): {s['inline_7d']}\n\n"
        "<b>New users</b>\n"
        f"24h: {s['new_1d']} · 7d: {s['new_7d']} · 30d: {s['new_30d']}\n\n"
        "<b>Texts sent</b> (spell check or convert)\n"
        f"24h: {s['texts_1d']} · 7d: {s['texts_7d']} · 30d: {s['texts_30d']}\n\n"
        "<b>Files</b> (uploaded / processed today)\n"
        f"24h: {s['files_1d']} · 7d: {s['files_7d']} · 30d: {s['files_30d']} · processed today: {s['files_done_today']}\n\n"
        "⭐ <b>Premium</b>\n"
        f"Active: <b>{s['premium_active']}</b> · payments 30d: {s['payments_30d']} ({s['stars_30d']} ⭐) · "
        f"all time: {s['payments_all']} ({s['stars_all']} ⭐)\n\n"
        f"<b>Daily active users</b> (Tashkent time)\n<pre>{daily}</pre>\n"
        f"Tracking since {since}. /admin lists all commands.")


@router.message(Command("users"))
async def command_users(message: Message) -> None:
    await message.answer_document(BufferedInputFile(db.export_users_csv(), filename="users.csv"))


@router.message(Command("backup"))
async def command_backup(message: Message, bot: Bot) -> None:
    await ops.send_backup(bot, message.chat.id, note="Backup")


@router.message(Command("givepremium"))
async def command_give(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args or not args[0].lstrip("-").isdigit() or (len(args) > 1 and not args[1].isdigit()):
        await message.answer("Usage: /givepremium <code>user_id</code> [days]")
        return
    uid, days = int(args[0]), int(args[1]) if len(args) > 1 else PREMIUM_DAYS
    until = db.extend_premium(uid, days)
    await message.answer(f"✅ Premium for <code>{uid}</code> until "
                         f"{datetime.fromtimestamp(until, db.TASHKENT):%d.%m.%Y}")


@router.message(Command("refund"))
async def command_refund(message: Message, command: CommandObject, bot: Bot) -> None:
    charge_id = (command.args or "").strip()
    payment = db.get_payment(charge_id) if charge_id else None
    if not payment:
        await message.answer("Usage: /refund <code>charge_id</code> (from the payment notice). Payment not found.")
        return
    if payment["refunded"]:
        await message.answer("Already refunded.")
        return
    try:
        await bot.refund_star_payment(user_id=payment["user_id"], telegram_payment_charge_id=charge_id)
    except TelegramBadRequest as e:
        await message.answer(f"❌ Telegram refused the refund: {e.message}")
        return
    db.mark_refunded(charge_id, PREMIUM_DAYS)
    await message.answer(f"✅ Refunded {payment['amount']} ⭐ to <code>{payment['user_id']}</code>; "
                         "their Premium days were removed.")


# ---------------------------------------------------------------- broadcast

broadcast = {"running": False}
_tasks = set()


@router.message(Command("broadcast"))
async def command_broadcast(message: Message) -> None:
    source = message.reply_to_message
    if not source:
        await message.answer(
            "📣 How to broadcast:\n1. Send (or forward) the post to this chat — text, photo, video, "
            "anything, with formatting.\n2. Reply to it with /broadcast.\n3. Confirm.\n\n"
            "It is copied to every user who has not blocked the bot (~20 per second).")
        return
    if broadcast["running"]:
        await message.answer("A broadcast is already running.")
        return
    n = len(db.broadcast_targets())
    await source.reply(
        f"📣 Send this message to <b>{n}</b> users?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✅ Send to {n}", callback_data=f"bc:go:{source.chat.id}:{source.message_id}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="bc:cancel"),
        ]]))


@router.callback_query(F.data == "bc:cancel")
async def on_broadcast_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("Broadcast cancelled.")


@router.callback_query(F.data.startswith("bc:go:"))
async def on_broadcast_go(callback: CallbackQuery, bot: Bot) -> None:
    if broadcast["running"]:
        await callback.answer("Already running", show_alert=True)
        return
    _, _, chat_id, message_id = callback.data.split(":")
    await callback.answer()
    await callback.message.edit_text("📣 Starting…")
    broadcast["running"] = True
    task = asyncio.create_task(run_broadcast(bot, int(chat_id), int(message_id), callback.message))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_broadcast(bot: Bot, from_chat, message_id, status_msg):
    targets = db.broadcast_targets()
    sent = blocked = failed = 0
    started = time.time()

    async def report(final=False):
        head = "✅ Broadcast finished" if final else "📣 Sending…"
        text = (f"{head}\n\nSent: <b>{sent}</b> / {len(targets)}\nBlocked the bot: {blocked}\n"
                f"Failed: {failed}\nTime: {int(time.time() - started)} s")
        try:
            await status_msg.edit_text(text)
        except TelegramBadRequest:
            pass  # text unchanged

    try:
        for i, uid in enumerate(targets, 1):
            for attempt in range(2):
                try:
                    await bot.copy_message(chat_id=uid, from_chat_id=from_chat, message_id=message_id)
                    sent += 1
                    break
                except TelegramRetryAfter as e:  # Telegram asks us to slow down
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:  # user blocked the bot / deleted account
                    blocked += 1
                    db.set_blocked(uid, True)
                    break
                except Exception as e:
                    failed += 1
                    logging.warning("Broadcast to %s failed: %s", uid, e)
                    break
            else:  # still rate-limited after retrying
                failed += 1
            await asyncio.sleep(0.05)  # ~20 messages/second, under Telegram's limit
            if i % 100 == 0:
                await report()
    finally:
        broadcast["running"] = False
        await report(final=True)
