from typing import List

DEFAULT_LANGUAGE = "en"

class BotResources:

    def __init__(self):
        pass

    def get_supported_languages(self) -> List[str]:
        return ["en", "ru"]

    def get_help_message(self, language=DEFAULT_LANGUAGE) -> str:
        return HELP_MESSAGE[language]
    
    def get_help_group_chat_message(self, language=DEFAULT_LANGUAGE) -> str:
        return HELP_GROUP_CHAT_MESSAGE[language]
    
    def get_new_command_title(self, language=DEFAULT_LANGUAGE) -> str:
        return NEW_COMMAND_TITLE[language]
    
    def get_mode_command_title(self, language=DEFAULT_LANGUAGE) -> str:
        return MODE_COMMAND_TITLE[language]
    
    def get_retry_command_title(self, language=DEFAULT_LANGUAGE) -> str:
        return RETRY_COMMAND_TITLE[language]

    def get_balance_command_title(self, language=DEFAULT_LANGUAGE) -> str:
        return BALANCE_COMMAND_TITLE[language]

    def get_settings_command_title(self, language=DEFAULT_LANGUAGE) -> str:
        return SETTINGS_COMMAND_TITLE[language]

    def get_help_command_title(self, language=DEFAULT_LANGUAGE) -> str:
        return HELP_COMMAND_TITLE[language]


HELP_MESSAGE_EN = """<b>Commands</b>:
• /retry – Regenerate last bot answer
• /new – Start new dialog
• /mode – Select chat mode
• /settings – Show settings
• /balance – Show balance
• /help – Show help

🎨 Generate images from text prompts in <b>👩‍🎨 Artist</b> /mode
👥 Add bot to <b>group chat</b>: /help_group_chat
🎤 You can send <b>Voice Messages</b> instead of text
"""

HELP_MESSAGE_RU = """<b>Команды</b>:
• /retry – Перегенерировать последний ответ
• /new – Начать новый диалог
• /mode – Выбрать режим
• /settings – Настройки
• /balance – Баланс
• /help – Помощь

🎨 Генерируй картинки из текста в режиме (/mode) <b>👩‍🎨 Художника</b>
👥 Добавь бота в <b>групповой чат</b>: /help_group_chat
🎤 Ты можешь отправлять <b>голосовые сообщения</b> вместо текста
"""

HELP_MESSAGE = {
    "en": HELP_MESSAGE_EN,
    "ru": HELP_MESSAGE_RU
}

HELP_GROUP_CHAT_MESSAGE_EN = """You can add bot to any <b>group chat</b> to help and entertain its participants!

Instructions (see <b>video</b> below):
1. Add the bot to the group chat
2. Make it an <b>admin</b>, so that it can see messages (all other rights can be restricted)
3. You're awesome!

To get a reply from the bot in the chat – @ <b>tag</b> it or <b>reply</b> to its message.
For example: "{bot_username} write a poem about Telegram"
"""

HELP_GROUP_CHAT_MESSAGE = {
    "en": HELP_GROUP_CHAT_MESSAGE_EN
}

NEW_COMMAND_TITLE = {
    "en": "Start new dialog",
    "ru": "Начать новый диалог"
}

MODE_COMMAND_TITLE = {
    "en": "Select chat mode",
    "ru": "Выбрать режим"
}

RETRY_COMMAND_TITLE = {
    "en": "Re-generate response for previous query",
    "ru": "Перегенерировать последний ответ"
}

BALANCE_COMMAND_TITLE = {
    "en": "Show balance",
    "ru": "Баланс"
}

SETTINGS_COMMAND_TITLE = {
    "en": "Show settings",
    "ru": "Настройки"
}

HELP_COMMAND_TITLE = {
    "en": "Show help message",
    "ru": "Помощь"
}
