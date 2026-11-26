"""Inline mode: type "@Uzimlo_xato_bot some text" in any chat to convert or check it.

Needs to be switched on once in @BotFather: /setinline -> pick the bot -> placeholder text.
"""
import asyncio

from aiogram import Router, html
from aiogram.types import (InlineQuery, InlineQueryResultArticle, InlineQueryResultsButton,
                           InputTextMessageContent)

import db
from alphabetCheck import is_cyrillic
from checkWords import is_known, suggest
from common import latin_target, ui
from fileproc import words_outside_links
from translitarate import convert, is_new_latin

router = Router(name="inline")

MAX_INLINE_SUGGESTIONS = 8  # Telegram expects an answer within a few seconds


def spell_summary(text, variant):
    """(number of misspelled words, lines 'wrong → right') for an inline result."""
    words = [w for _, _, w in words_outside_links(text)]
    new_alphabet = is_new_latin(text)
    lines, seen, errors = [], set(), 0
    for word in words:
        cyr = word if is_cyrillic(word) else convert(word, "cyrillic", new_alphabet)
        key = cyr.lower()
        if is_known(key):
            continue
        errors += 1
        if key in seen:
            continue
        seen.add(key)
        options = suggest(key)[:3] if len(seen) <= MAX_INLINE_SUGGESTIONS else ()
        if not is_cyrillic(word):  # answer in the alphabet the user writes in
            options = [convert(o, latin_target(variant), False) for o in options]
        lines.append(f"❌ {word} → " + (", ".join(options) if options else "?"))
    return errors, lines


@router.inline_query()
async def on_inline(query: InlineQuery) -> None:
    text = query.query.strip()
    variant = db.get_latin_variant(query.from_user.id)
    if not text:
        await query.answer([], cache_time=300, is_personal=True, button=InlineQueryResultsButton(
            text=ui("✍️ Matn yozing — oʻgirib yoki tekshirib beraman", variant), start_parameter="inline"))
        return

    def article(id_, title, result_text, description=None):
        return InlineQueryResultArticle(
            id=id_, title=title, description=(description or result_text)[:200],
            input_message_content=InputTextMessageContent(message_text=html.quote(result_text)[:4096]))

    results = [
        article("latin_new", "🔤 Lotin (yangi): ö ğ ş ç", convert(text, "latin_new")),
        article("latin_old", "🔤 Lotin (eski): oʻ gʻ sh ch", convert(text, "latin_old")),
        article("cyrillic", "🔤 Кирилл", convert(text, "cyrillic")),
    ]
    errors, lines = await asyncio.to_thread(spell_summary, text, variant)
    if errors:
        title = ui(f"🔍 Imlo: {errors} ta xato", variant)
        results.append(article("spell", title, text + "\n\n" + "\n".join(lines), " · ".join(lines)))
    else:
        results.append(article("spell", ui("🔍 Imlo: xato topilmadi ✅", variant), text))
    await query.answer(results, cache_time=10, is_personal=True)
