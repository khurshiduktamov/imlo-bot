import asyncio
import logging
import sys
from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from checkWords import checkWord
from translitarate import transliterate
from alphabetCheck import is_latin, is_cyrillic

# Load environment variables from .env file
load_dotenv()

# Bot token can be obtained via https://t.me/BotFather
TOKEN = getenv("BOT_TOKEN")

# All handlers should be attached to the Router (or Dispatcher)
dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """
    This handler receives messages with `/start` command
    """
    # Most event objects have aliases for API methods that can be called in events' context
    # For example if you want to answer to incoming message you can use `message.answer(...)` alias
    # and the target chat will be passed to :ref:`aiogram.methods.send_message.SendMessage`
    # method automatically or call API method directly via
    # Bot instance: `bot.send_message(chat_id=message.chat.id, ...)`
    await message.answer(f"Hello, {html.bold(message.from_user.full_name)}!")


@dp.message()
async def imloCheck(message: Message) -> None:
    """
    This function checks each word in the user's message for Uzbek grammar.
    It returns the response in the same alphabet (Cyrillic or Latin) as the user's input.
    """
    original_text = message.text
    words = original_text.split()

    # Detect if the input text is in Cyrillic or Latin
    is_input_cyrillic = all(is_cyrillic(word) for word in words)

    # Initialize response list to collect results for each word
    response = []

    # Process each word in the user's message
    for word in words:
        if not is_input_cyrillic:
            # Transliterate Latin input to Cyrillic for grammar check
            word_in_cyrillic = transliterate(word, 'cyrillic')
        else:
            word_in_cyrillic = word

        # Check the word's grammar in Cyrillic
        result = checkWord(word_in_cyrillic)

        # Generate response for each word
        response.append(generate_word_response(word_in_cyrillic, result))

    # Combine all responses for the full message
    combined_response = "\n".join(response)

    # If the user's input was in Latin, transliterate the final response back to Latin
    if not is_input_cyrillic:
        combined_response = transliterate_response_to_latin(combined_response)

    # Send the response back to the user
    await message.answer(combined_response)


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


def transliterate_response_to_latin(response: str) -> str:
    """
    Transliterate each word in the response from Cyrillic to Latin, leaving Latin words intact.
    """
    words = response.splitlines()  # Split the response by lines (each word on a new line)
    transliterated_response = []

    for word in words:
        # Check if the word is in Cyrillic and needs transliteration to Latin
        if is_cyrillic(word):
            transliterated_word = transliterate(word, 'latin')
            transliterated_response.append(transliterated_word)
        else:
            transliterated_response.append(word)  # Keep Latin words as is

    # Join the transliterated words back into a single response with each word on a new line
    return "\n".join(transliterated_response)


async def main() -> None:
    # Initialize Bot instance with default bot properties which will be passed to all API calls
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # And the run events dispatching
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[
                            logging.FileHandler("bot.log"),
                            logging.StreamHandler(sys.stdout)
                        ]
                        )
    asyncio.run(main())