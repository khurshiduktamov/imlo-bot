"""Settings, texts and keyboards shared by all parts of the bot."""
import os
from os import getenv

from aiogram.enums import ChatType
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv

from translitarate import latin_old_to_new

# Load environment variables from .env file
load_dotenv()

# Bot token can be obtained via https://t.me/BotFather
TOKEN = getenv("BOT_TOKEN")
# Telegram user ids allowed to use admin commands, e.g. ADMIN_IDS=123456789,987654321
ADMIN_IDS = {int(x) for x in getenv("ADMIN_IDS", "").replace(",", " ").split()}
# Who users contact about payments (/paysupport), e.g. SUPPORT_CONTACT=@my_username
SUPPORT_CONTACT = getenv("SUPPORT_CONTACT", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Limits and Premium
FREE_FILES_PER_DAY = 5
FREE_FILE_MB = 10
PREMIUM_FILE_MB = 20          # Telegram does not let bots download bigger files
PREMIUM_PRICE_STARS = 150
PREMIUM_DAYS = 30

MESSAGE_LIMIT = 4000          # Telegram allows 4096 characters per message

LATIN_LABELS = {"new": "yangi (ö ğ ş ç)", "old": "eski (oʻ gʻ sh ch)"}


def ui(text, variant):
    """Our messages are written in the old Latin alphabet; show them in the user's choice."""
    return latin_old_to_new(text) if variant == "new" else text


def latin_target(variant):
    return "latin_new" if variant == "new" else "latin_old"


def is_admin(user_id):
    return user_id in ADMIN_IDS


# ---------------------------------------------------------------- bottom menu

# Bottom menu buttons, written in the old alphabet; shown in the user's alphabet.
MENU = {
    "check": "✍️ Imlo tekshirish",
    "convert": "🔤 Matnni oʻgirish",
    "file": "📄 Fayl bilan ishlash",
    "premium": "⭐ Premium",
    "settings": "⚙️ Sozlamalar",
    "help": "ℹ️ Yordam",
}


def menu_texts(key):
    """A button press arrives as its label; accept it in both alphabets."""
    return {MENU[key], latin_old_to_new(MENU[key])}


ALL_MENU_TEXTS = set().union(*(menu_texts(k) for k in MENU))


def main_keyboard(variant):
    b = {k: KeyboardButton(text=ui(v, variant)) for k, v in MENU.items()}
    return ReplyKeyboardMarkup(
        keyboard=[[b["check"], b["convert"]], [b["file"], b["premium"]], [b["settings"], b["help"]]],
        resize_keyboard=True, is_persistent=True,
        input_field_placeholder=ui("Matn yoki fayl yuboring...", variant),
    )


def private_keyboard(message, variant):
    """The menu keyboard only in private chats: in groups it would cover everyone's screen."""
    return main_keyboard(variant) if message.chat.type == ChatType.PRIVATE else None
