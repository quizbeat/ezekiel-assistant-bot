from telegram import Update
from telegram.constants import ParseMode


PARSE_MODE_MAPPING = {
    "html": ParseMode.HTML,
    "markdown": ParseMode.MARKDOWN
}


def split_into_chunks(text: str, chunk_size: int):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def get_username(update: Update) -> str:
    if update.message is None or update.message.from_user is None:
        return "unknown user"

    return update.message.from_user.username or "unknown user"


def convert_to_telegram_parse_mode(parse_mode: str) -> ParseMode:
    if parse_mode not in PARSE_MODE_MAPPING:
        raise ValueError(f"Unknown parse mode <{parse_mode}>")

    return PARSE_MODE_MAPPING[parse_mode]
