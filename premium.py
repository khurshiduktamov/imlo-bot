"""Premium: free daily limits for files, monthly Premium paid with Telegram Stars."""
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
                           Message, PreCheckoutQuery)

import db
from common import (ADMIN_IDS, FREE_FILE_MB, FREE_FILES_PER_DAY, PREMIUM_DAYS, PREMIUM_FILE_MB,
                    PREMIUM_PRICE_STARS, SUPPORT_CONTACT, is_admin, menu_texts, ui)

router = Router(name="premium")

PAYLOAD = f"premium_{PREMIUM_DAYS}d"


# ---------------------------------------------------------------- limits

def has_unlimited(user_id):
    return is_admin(user_id) or db.is_premium(user_id)


def max_file_mb(user_id):
    return PREMIUM_FILE_MB if has_unlimited(user_id) else FREE_FILE_MB


def files_left_today(user_id):
    """None = unlimited, otherwise how many free files are left today."""
    if has_unlimited(user_id):
        return None
    return max(0, FREE_FILES_PER_DAY - db.files_today(user_id))


def until_text(user_id):
    return datetime.fromtimestamp(db.premium_until(user_id), db.TASHKENT).strftime("%d.%m.%Y")


def buy_keyboard(variant):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=ui(f"⭐ Premium olish — {PREMIUM_PRICE_STARS} Stars", variant), callback_data="prem:buy")]])


def limit_reached_text(variant):
    return ui(f"⏳ Bugungi bepul limit tugadi: kuniga {FREE_FILES_PER_DAY} ta fayl.\n\n"
              "Ertaga yana foydalanishingiz yoki ⭐ <b>Premium</b> olib, cheksiz ishlashingiz mumkin.", variant)


def too_big_text(variant, user_id):
    if has_unlimited(user_id):
        return ui(f"Fayl juda katta. {PREMIUM_FILE_MB} MB gacha boʻlgan fayl yuboring.", variant)
    return ui(f"Fayl juda katta. Bepul: {FREE_FILE_MB} MB gacha, ⭐ Premium: {PREMIUM_FILE_MB} MB gacha.", variant)


# ---------------------------------------------------------------- /premium

@router.message(Command("premium"))
@router.message(F.text.in_(menu_texts("premium")))
async def premium_info(message: Message) -> None:
    uid = message.from_user.id
    variant = db.get_latin_variant(uid)
    text = ui("⭐ <b>Premium</b>\n\n"
              f"🆓 Bepul: kuniga {FREE_FILES_PER_DAY} ta fayl, {FREE_FILE_MB} MB gacha.\n"
              f"⭐ Premium: cheksiz fayllar, {PREMIUM_FILE_MB} MB gacha.\n\n"
              f"Narxi: <b>{PREMIUM_PRICE_STARS} Stars</b> — {PREMIUM_DAYS} kun.\n"
              "Matnni tekshirish va oʻgirish har doim bepul.\n\n", variant)
    if db.is_premium(uid):
        text += ui(f"✅ Sizda Premium bor: <b>{until_text(uid)}</b> gacha.\n"
                   "Uzaytirish uchun yana sotib olishingiz mumkin.", variant)
    elif is_admin(uid):
        text += "👑 Admin: no limits."
    else:
        used = db.files_today(uid)
        text += ui(f"Bugun: {min(used, FREE_FILES_PER_DAY)}/{FREE_FILES_PER_DAY} ta fayl ishlatildi.", variant)
    await message.answer(text, reply_markup=buy_keyboard(variant))


@router.callback_query(F.data == "prem:buy")
async def on_buy(callback: CallbackQuery, bot: Bot) -> None:
    variant = db.get_latin_variant(callback.from_user.id)
    await callback.answer()
    # Telegram Stars: currency XTR, no payment provider needed
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=ui(f"Premium — {PREMIUM_DAYS} kun", variant),
        description=ui(f"Cheksiz fayllar va {PREMIUM_FILE_MB} MB gacha fayllar, {PREMIUM_DAYS} kun davomida. "
                       "Avtomatik uzaytirilmaydi.", variant),
        payload=PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(label=f"Premium {PREMIUM_DAYS}", amount=PREMIUM_PRICE_STARS)],
    )


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Telegram asks us to confirm right before charging. Must answer within 10 seconds."""
    if query.invoice_payload == PAYLOAD and query.currency == "XTR" and query.total_amount == PREMIUM_PRICE_STARS:
        await query.answer(ok=True)
    else:  # an old invoice with another price/period
        variant = db.get_latin_variant(query.from_user.id)
        await query.answer(ok=False, error_message=ui("Bu hisob eskirgan. /premium orqali qayta urinib koʻring.", variant))


@router.message(F.successful_payment)
async def on_paid(message: Message, bot: Bot) -> None:
    pay = message.successful_payment
    uid = message.from_user.id
    variant = db.get_latin_variant(uid)
    if not db.record_payment(pay.telegram_payment_charge_id, uid, pay.total_amount, pay.invoice_payload):
        return  # the same payment delivered twice: already handled
    db.extend_premium(uid, PREMIUM_DAYS)
    logging.info("Premium bought: user %s, %s Stars, charge %s", uid, pay.total_amount, pay.telegram_payment_charge_id)
    await message.answer(ui(f"🎉 Rahmat! ⭐ Premium <b>{until_text(uid)}</b> gacha faol.", variant))
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, f"💰 New Premium: {message.from_user.full_name} "
                                          f"(<code>{uid}</code>), {pay.total_amount} ⭐\n"
                                          f"Charge: <code>{pay.telegram_payment_charge_id}</code>")
        except Exception:
            logging.warning("Could not notify admin %s about a payment", admin)


# ---------------------------------------------------------------- required by Telegram for payments

@router.message(Command("paysupport"))
async def pay_support(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    admin = next(iter(ADMIN_IDS), None)
    contact = SUPPORT_CONTACT or (f'<a href="tg://user?id={admin}">admin</a>' if admin else "—")
    await message.answer(ui("💬 Toʻlovlar boʻyicha savol yoki muammo boʻlsa, yozing: ", variant) + contact
                         + ui("\n\nMuammoni va toʻlov sanasini yozib qoldiring. "
                              "Pulni qaytarish kerak boʻlsa, 1–2 kun ichida koʻrib chiqamiz.", variant))


@router.message(Command("terms"))
async def terms(message: Message) -> None:
    variant = db.get_latin_variant(message.from_user.id)
    await message.answer(ui(
        "📄 <b>Foydalanish shartlari</b>\n\n"
        "• Matnni tekshirish va oʻgirish bepul.\n"
        f"• Bepul: kuniga {FREE_FILES_PER_DAY} ta fayl, {FREE_FILE_MB} MB gacha.\n"
        f"• ⭐ Premium {PREMIUM_DAYS} kunga beriladi, Telegram Stars bilan toʻlanadi "
        "va avtomatik uzaytirilmaydi.\n"
        "• Imlo tekshiruvi lugʻatga asoslangan va 100% aniq emas: muhim hujjatlarni qayta koʻrib chiqing.\n"
        "• Yuborilgan fayllar faqat ishlash uchun ishlatiladi va saqlanmaydi.\n"
        "• Texnik muammo tufayli Premiumdan foydalana olmasangiz, pulingiz qaytariladi: /paysupport", variant))
