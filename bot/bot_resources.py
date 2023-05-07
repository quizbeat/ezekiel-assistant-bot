from typing import List

class BotResources:

    def __init__(self):
        pass

    def get_supported_languages(self) -> List[str]:
        return ["en", "ru"]

    def get_help_message(self, language="en") -> str:
        return HELP_MESSAGES[language]
    
    def get_help_group_chat_message(self, language="en") -> str:
        return HELP_GROUP_CHAT_MESSAGES[language]
    
    def get_new_command_title(self, language="en") -> str:
        if language == "en":
            return "Start new dialog"
        
        if language == "ru":
            return "Начать новый диалог"
        
        return "Start new dialog"
    
    def get_mode_command_title(self, language="en") -> str:
        if language == "en":
            return "Select chat mode"
        
        if language == "ru":
            return "Выбрать режим"
        
        return "Select chat mode"
    
    def get_retry_command_title(self, language="en") -> str:
        if language == "en":
            return "Re-generate response for previous query"
        
        if language == "ru":
            return "Перегенерировать последний ответ"
        
        return "Re-generate response for previous query"

    def get_balance_command_title(self, language="en") -> str:
        if language == "en":
            return "Show balance"
        
        if language == "ru":
            return "Баланс"
        
        return "Show balance"

    def get_settings_command_title(self, language="en") -> str:
        if language == "en":
            return "Show settings"
        
        if language == "ru":
            return "Настройки"
        
        return "Show settings"

    def get_help_command_title(self, language="en") -> str:
        if language == "en":
            return "Show help message"
        
        if language == "ru":
            return "Помощь"
        
        return "Show help message"


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

HELP_MESSAGES = {
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

HELP_GROUP_CHAT_MESSAGES = {
    "en": HELP_GROUP_CHAT_MESSAGE_EN
}
