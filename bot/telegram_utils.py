from typing import Optional
from telegram import Update, Message
from telegram.constants import ParseMode

PARSE_MODE_MAPPING = {
    "html": ParseMode.HTML,
    "markdown": ParseMode.MARKDOWN
}

MESSAGE_LENGTH_LIMIT = 4096


def get_username_or_id(update: Update) -> str:
    username = get_username(update)
    if username is not None:
        return username

    return str(get_user_id(update))


def get_username(update: Update) -> Optional[str]:
    if update.edited_message is not None and update.edited_message.from_user is not None:
        return update.edited_message.from_user.username

    if update.message is None or update.message.from_user is None:
        return None

    return update.message.from_user.username


def get_user_id(update: Update) -> int:
    if update.edited_message is not None and update.edited_message.from_user is not None:
        return update.edited_message.from_user.id

    if update.message is None or update.message.from_user is None:
        return 0

    return update.message.from_user.id


def get_language(source) -> Optional[str]:
    if isinstance(source, Update):
        return source.message.from_user.language_code

    if isinstance(source, Message):
        return source.from_user.language_code

    return None


def get_parse_mode(parse_mode: str) -> ParseMode:
    if parse_mode not in PARSE_MODE_MAPPING:
        raise ValueError(f"Unknown parse mode <{parse_mode}>")

    return PARSE_MODE_MAPPING[parse_mode]
