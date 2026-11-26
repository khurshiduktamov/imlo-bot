import asyncio
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, ChatMemberUpdated,
                           InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery, Message)

import admin
import db
import fileproc
import inline
import ops
import premium
from alphabetCheck import is_cyrillic
from checkWords import is_known, suggest
from common import (ADMIN_IDS, ALL_MENU_TEXTS, BASE_DIR, LATIN_LABELS, MESSAGE_LIMIT, TOKEN,
                    latin_target, main_keyboard, menu_texts, private_keyboard, ui)
from translitarate import convert, is_new_latin

SHORT_TEXT_WORDS = 30    # up to this many words: show every word; above: only the mistakes
MAX_TEXT_WORDS = 500     # above this: ask for a file instead
MAX_TEXT_SUGGESTIONS = 60  # distinct misspelled words per message that get suggestions

# Heavy file jobs run in threads; keep at most 2 at a time on the small server
file_jobs = asyncio.Semaphore(2)

dp = Dispatcher()
# The core features. Included last: its catch-all text handler would otherwise swallow
# messages meant for the admin/premium routers.
router = Router(name="core")


# ---------------------------------------------------------------- tracking

class TrackMiddleware(BaseMiddleware):
    """Saves every user/chat that talks to the bot and logs the interaction for /stats."""

    def __init__(self):
        self.last_inline = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user and not user.is_bot:
            if isinstance(event, InlineQuery):
                # Telegram sends a query on almost every keystroke: count a user once a minute
                if time.time() - self.last_inline.get(user.id, 0) < 60:
                    return await handler(event, data)
                self.last_inline[user.id] = time.time()
                kind = "inline"
            elif isinstance(event, CallbackQuery):
                kind = "button"
            elif event.successful_payment:
                kind = "payment"
            elif event.document:
                kind = "file"
            elif event.text and event.text.startswith("/"):
                kind = "command"
            elif event.text and event.text in ALL_MENU_TEXTS:
                kind = "button"
            elif event.text:
                kind = "text"
            else:
                kind = "other"
            try:
                db.track(user, chat, kind)
            except Exception:
                logging.exception("Could not save user activity")
        return await handler(event, data)


tracker = TrackMiddleware()
dp.message.outer_middleware(tracker)
dp.callback_query.outer_middleware(tracker)
dp.inline_query.outer_middleware(tracker)


@router.my_chat_member(F.chat.type == ChatType.PRIVATE)
async def on_block_change(update: ChatMemberUpdated) -> None:
    """User blocked or unblocked the bot."""
    db.set_blocked(update.from_user.id, update.new_chat_member.status == "kicked")


# ---------------------------------------------------------------- menu

@router.message(CommandStart())
@router.message(Command("help"))
@router.message(F.text.in_(menu_texts("help")))
async def command_start_handler(message: Message, bot: Bot) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    me = await bot.me()
    text = ui(
        "Assalomu alaykum, {name}!\n\n"
        "Men oʻzbek tilidagi matnlar bilan ishlayman:\n\n"
        "✍️ <b>Imlo tekshirish</b> — matn yuboring, har bir soʻzni tekshirib, "
        "xato boʻlsa toʻgʻri variantlarini koʻrsataman.\n\n"
        "🔤 <b>Matnni oʻgirish</b> — matnni kirill, yangi lotin yoki eski lotin alifbosiga oʻgiraman.\n\n"
        "📄 <b>Fayl bilan ishlash</b> — .docx yoki .txt faylni oʻgirib beraman "
        "yoki undagi imlo xatolarni belgilab qaytaraman.\n\n"
        "💬 <b>Istalgan chatda</b>: <code>@{bot} matn</code> deb yozing — "
        "oʻgirilgan variantni tanlab yuborasiz.\n\n"
        "Pastdagi tugmalardan foydalaning.\n\n",
        variant,
    ).format(name=html.quote(message.from_user.full_name), bot=me.username)
    text += ("🆕 Yangi lotin alifbosi (2026): Oʻ → Ö, Gʻ → Ğ, Sh → Ş, Ch → Ç\n"
             + ui("Lotin alifbosidagi javoblarim: <b>{label}</b>", variant)
             .format(label=LATIN_LABELS[variant]))
    await message.answer(text, reply_markup=private_keyboard(message, variant))


@router.message(F.text.in_(menu_texts("check")))
async def menu_check(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    db.set_mode(message.from_user.id, "check")
    await message.answer(ui("✍️ Tekshirish uchun matn yuboring.", variant))


@router.message(F.text.in_(menu_texts("convert")))
async def menu_convert(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    db.set_mode(message.from_user.id, "convert")
    await message.answer(ui("🔤 Oʻgirish uchun matn yuboring, keyin alifboni tanlaysiz.\n\n"
                            "Imlo tekshirishga qaytish: «Imlo tekshirish» tugmasi.", variant))


@router.message(F.text.in_(menu_texts("file")))
async def menu_file(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    await message.answer(ui(
        "📎 <b>.docx</b> (Word) yoki <b>.txt</b> fayl yuboring ({mb} MB gacha).\n\n"
        "Keyin tanlaysiz:\n"
        "• lotin (yangi yoki eski) yoki kirill alifbosiga oʻgirish\n"
        "• imlo xatolarni belgilash", variant).format(mb=premium.max_file_mb(message.from_user.id))
        + limit_note(message.from_user.id, variant))


def limit_note(user_id, variant):
    left = premium.files_left_today(user_id)
    if left is None:
        return ""
    return "\n\n" + ui(f"🆓 Bugun yana {left} ta fayl bepul. Cheksiz: ⭐ Premium", variant)


def settings_keyboard(variant):
    mark = {v: "✅ " if v == variant else "" for v in ("new", "old")}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{mark['new']}Yangi: ö ğ ş ç", callback_data="lat:new")],
        [InlineKeyboardButton(text=f"{mark['old']}Eski: oʻ gʻ sh ch", callback_data="lat:old")],
    ])


@router.message(Command("settings"))
@router.message(F.text.in_(menu_texts("settings")))
async def command_settings(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    await message.answer(ui("⚙️ Lotin alifbosidagi javoblar qaysi alifboda boʻlsin?", variant),
                         reply_markup=settings_keyboard(variant))


@router.callback_query(F.data.startswith("lat:"))
async def on_settings_choice(callback: CallbackQuery) -> None:
    variant = callback.data.split(":", 1)[1]
    if variant not in LATIN_LABELS:
        await callback.answer()
        return
    if variant == db.get_latin_variant(callback.from_user.id):
        await callback.answer("✅")  # already selected: nothing to change
        return
    db.set_latin_variant(callback.from_user.id, variant)
    await callback.answer("✅")
    if callback.message and hasattr(callback.message, "edit_text"):
        await callback.message.edit_text(
            ui("⚙️ Lotin alifbosidagi javoblar qaysi alifboda boʻlsin?", variant),
            reply_markup=settings_keyboard(variant))
        if callback.message.chat.type == ChatType.PRIVATE:
            # refresh the bottom menu so its labels use the chosen alphabet
            await callback.message.answer(
                ui("✅ Saqlandi: <b>{label}</b>", variant).format(label=LATIN_LABELS[variant]),
                reply_markup=main_keyboard(variant))


# ---------------------------------------------------------------- convert text

def convert_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Lotin (yangi): ö ğ ş ç", callback_data="t:latin_new")],
        [InlineKeyboardButton(text="Lotin (eski): oʻ gʻ sh ch", callback_data="t:latin_old")],
        [InlineKeyboardButton(text="Кирилл", callback_data="t:cyrillic")],
    ])


async def ask_convert_target(message: Message, variant) -> None:
    # The menu replies to the user's text, so the button handler finds the text through it
    await message.reply(ui("Qaysi alifboga oʻgiray?", variant), reply_markup=convert_keyboard())


@router.callback_query(F.data.startswith("t:"))
async def on_convert_text(callback: CallbackQuery, bot: Bot) -> None:
    variant = db.get_latin_variant(callback.from_user.id)
    target = callback.data[2:]
    source = getattr(callback.message, "reply_to_message", None)
    if not source or not source.text or target not in TARGET_LABELS:
        await callback.answer(ui("Matn topilmadi. Uni qayta yuboring.", variant), show_alert=True)
        return
    await callback.answer()
    result = await asyncio.to_thread(convert, source.text, target)
    if len(html.quote(result)) > MESSAGE_LIMIT:
        await source.reply_document(BufferedInputFile(result.encode("utf-8"), filename=f"matn_{TARGET_LABELS[target][0]}.txt"))
        return
    if html.quote(result) != getattr(callback.message, "html_text", None):
        # show the result in place of the menu; the buttons stay to try another alphabet
        await callback.message.edit_text(html.quote(result), reply_markup=convert_keyboard())


@router.message(Command("id"))
async def command_id(message: Message) -> None:
    await message.answer(f"ID: <code>{message.from_user.id}</code>")


# ---------------------------------------------------------------- files

@router.message(F.document)
async def on_document(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    doc = message.document
    name = doc.file_name or "file"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("docx", "txt"):
        await message.reply(ui(
            "Hozircha faqat <b>.docx</b> (Word) va <b>.txt</b> fayllarni qabul qilaman.\n"
            "Eski .doc faylni Wordda «Saqlash» → .docx qilib saqlab yuboring.", variant))
        return
    uid = message.from_user.id
    if doc.file_size and doc.file_size > premium.max_file_mb(uid) * 1024 * 1024:
        await message.reply(premium.too_big_text(variant, uid),
                            reply_markup=None if premium.has_unlimited(uid) else premium.buy_keyboard(variant))
        return
    if premium.files_left_today(uid) == 0:
        await message.reply(premium.limit_reached_text(variant), reply_markup=premium.buy_keyboard(variant))
        return
    # The keyboard message replies to the file, so the button handler finds the file through it
    await message.reply(
        f"📄 {html.quote(name)}\n\n" + ui("Nima qilay?", variant),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔤 Lotin (yangi): ö ğ ş ç", callback_data="f:latin_new")],
            [InlineKeyboardButton(text="🔤 Lotin (eski): oʻ gʻ sh ch", callback_data="f:latin_old")],
            [InlineKeyboardButton(text="🔤 Кирилл", callback_data="f:cyrillic")],
            [InlineKeyboardButton(text=ui("🔍 Imlo xatolarni belgilash", variant), callback_data="f:spell")],
        ]),
    )


TARGET_LABELS = {"latin_new": ("lotin_yangi", "Lotin (yangi alifbo)"),
                 "latin_old": ("lotin_eski", "Lotin (eski alifbo)"),
                 "cyrillic": ("kirill", "Кирилл")}


@router.callback_query(F.data.startswith("f:"))
async def on_file_action(callback: CallbackQuery, bot: Bot) -> None:
    variant = db.get_latin_variant(callback.from_user.id)
    action = callback.data[2:]
    menu = callback.message
    source = getattr(menu, "reply_to_message", None)
    if not source or not source.document or action not in (*TARGET_LABELS, "spell"):
        await callback.answer(ui("Fayl topilmadi. Uni qayta yuboring.", variant), show_alert=True)
        return
    if premium.files_left_today(callback.from_user.id) == 0:
        await callback.answer()
        await menu.edit_text(premium.limit_reached_text(variant), reply_markup=premium.buy_keyboard(variant))
        return
    await callback.answer()
    await menu.edit_text(ui("⏳ Ishlanmoqda...", variant))

    name = source.document.file_name or "file"
    stem, ext = name.rsplit(".", 1)[0], name.rsplit(".", 1)[-1].lower()
    try:
        async with file_jobs:
            data = (await bot.download(source.document)).read()
            if action == "spell":
                fn = fileproc.spellcheck_docx if ext == "docx" else fileproc.spellcheck_txt
                result, report = await asyncio.to_thread(fn, data, variant, lambda s: ui(s, variant))
            else:
                fn = fileproc.convert_docx if ext == "docx" else fileproc.convert_txt
                result = await asyncio.to_thread(fn, data, action)
    except fileproc.FileError as e:
        await menu.edit_text("⚠️ " + ui(str(e), variant))
        return
    except Exception:
        logging.exception("File processing failed: %s (%s)", name, action)
        await menu.edit_text("⚠️ " + ui("Faylni ishlashda xatolik yuz berdi. Keyinroq qayta urinib koʻring.", variant))
        return

    if action == "spell":
        if not report.errors:
            await menu.edit_text(ui(f"✅ Xato topilmadi! Jami soʻzlar: {report.total_words}", variant))
            return
        caption = ui(f"Jami soʻzlar: {report.total_words}\n"
                     f"Xatolar: {report.errors} (turli soʻzlar: {len(report.unique)})\n\n", variant)
        if ext == "docx":
            caption += ui("Xato soʻzlar sariq rang bilan belgilandi, toʻgʻri variantlar izohlarda (comments).",
                          variant)
            out_name = f"{stem}_imlo.docx"
        else:
            caption += ui("Xato soʻzlar va toʻgʻri variantlar roʻyxati faylda.", variant)
            out_name = f"{stem}_imlo_xatolar.txt"
        if report.truncated:
            caption += ui("\n\nXatolar juda koʻp: ayrim soʻzlar uchun variant berilmadi.", variant)
    else:
        suffix, label = TARGET_LABELS[action]
        caption = "✅ " + (label if action == "cyrillic" else ui(label, variant))
        out_name = f"{stem}_{suffix}.{ext}"

    await source.reply_document(BufferedInputFile(result, filename=out_name), caption=caption)
    db.add_event(callback.from_user.id, menu.chat.id, "file_job")  # counts toward the daily limit
    await menu.delete()


# ---------------------------------------------------------------- text check

@router.message(F.text)
async def imloCheck(message: Message) -> None:
    """
    This function checks each word in the user's message for Uzbek grammar.
    It returns the response in the same alphabet (Cyrillic or Latin) as the user's input.
    """
    if message.text.startswith("/"):
        return  # unknown command (or an admin command from a non-admin): not text to check
    variant = db.get_latin_variant(message.from_user.id)
    if db.get_mode(message.from_user.id) == "convert":
        await ask_convert_target(message, variant)
        return
    words = [word for _, _, word in fileproc.words_outside_links(message.text)]
    if not words:
        return
    if len(words) > MAX_TEXT_WORDS:
        await message.answer(ui(f"Matn juda uzun ({len(words)} ta soʻz). "
                                "Uni .txt yoki .docx fayl qilib yuboring.", variant))
        return
    response = await asyncio.to_thread(build_response, message.text, words, variant)
    for chunk in split_message(response):
        await message.answer(chunk)


def build_response(text, words, variant):
    # Detect if the input text is in Cyrillic or Latin
    is_input_cyrillic = all(is_cyrillic(word) for word in words)
    new_alphabet = is_new_latin(text)
    short = len(words) <= SHORT_TEXT_WORDS

    response, errors, lookups = [], 0, 0
    seen = set()
    for word in words:
        # Transliterate Latin input to Cyrillic for grammar check
        word_in_cyrillic = word if is_cyrillic(word) else convert(word, 'cyrillic', new_alphabet)
        key = word_in_cyrillic.lower()
        known = is_known(key)
        if not known:
            errors += 1
        # every word once; long texts: only the mistakes
        if key in seen or (not short and known):
            continue
        seen.add(key)
        if known:
            result = {'available': True, 'matches': key}
        elif lookups < MAX_TEXT_SUGGESTIONS:  # suggestions are slow: cap them per message
            lookups += 1
            result = {'available': False, 'matches': suggest(key)}
        else:
            result = {'available': False, 'matches': ()}
        response.append(generate_word_response(word_in_cyrillic, result))

    if not short:
        header = ui(f"Jami soʻzlar: {len(words)}, xatolar: {errors}", variant)
        if not errors:
            header = "✅ " + ui(f"Xato topilmadi ({len(words)} ta soʻz)", variant)
        response.insert(0, header + "\n")

    # Combine all responses for the full message
    combined_response = "\n".join(response)

    # If the user's input was in Latin, transliterate the final response back to Latin
    if not is_input_cyrillic:
        combined_response = transliterate_response_to_latin(combined_response, variant)
    return combined_response


def generate_word_response(word, result) -> str:
    """
    Generate the response string for a single word based on the grammar check result.
    """
    if result['available']:
        return f"✅ {word.capitalize()}"

    # If the word is incorrect, show corrections, each suggestion on a new line
    response = f"❌ {word.capitalize()}\n"
    for suggestion in result['matches']:
        response += f"✅ {suggestion.capitalize()}\n"

    return response


def transliterate_response_to_latin(response: str, variant: str) -> str:
    """
    Transliterate each line in the response from Cyrillic to Latin, leaving Latin lines intact.
    """
    lines = response.splitlines()
    return "\n".join(convert(line, latin_target(variant), False) if is_cyrillic(line) else line
                     for line in lines)


def split_message(text):
    """Split a long reply into Telegram-sized messages at line breaks."""
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MESSAGE_LIMIT and current:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks


@router.message(F.chat.type == ChatType.PRIVATE)
async def other_messages(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    await message.answer(ui("Menga matn yoki .docx / .txt fayl yuboring.", variant),
                         reply_markup=main_keyboard(variant))


# order matters: the core router (with the catch-all handlers) goes last
dp.include_routers(admin.router, premium.router, inline.router, router)


async def main() -> None:
    # Initialize Bot instance with default bot properties which will be passed to all API calls
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db.conn()  # create/upgrade the database on startup
    tasks = ops.start_background_tasks(bot, dp)
    await bot.set_my_commands([
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="premium", description="⭐ Premium"),
        BotCommand(command="settings", description="Lotin alifbosi: yangi yoki eski"),
        BotCommand(command="help", description="Yordam"),
    ])
    logging.info("Admins: %s", ADMIN_IDS or "none (set ADMIN_IDS in .env)")

    # And the run events dispatching
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    for t in tasks:
        t.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[
                            # keep the log from growing forever: 5 MB x 3 files
                            RotatingFileHandler(os.path.join(BASE_DIR, "bot.log"),
                                                maxBytes=5 * 1024 * 1024, backupCount=3,
                                                encoding="utf-8"),
                            logging.StreamHandler(sys.stdout),
                            ops.alerts,  # errors are also sent to the admins on Telegram
                        ]
                        )
    asyncio.run(main())
    if ops.restart_requested:
        sys.exit(3)  # non-zero: alwaysdata starts the service again with the new code
