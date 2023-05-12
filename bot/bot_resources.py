from typing import List, Optional
from localization.localization import Localization


class BotResources:

    def __init__(self, default_language: str = "en"):
        self.localization = Localization()
        self.default_language = default_language

    def get_supported_languages(self) -> List[str]:
        return self.localization.get_supported_languages()

    def get_help_message(self, language: Optional[str]) -> str:
        return self._get_localized("help_message", language)

    def get_help_group_chat_message(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("help_message_group_chat", language, **kwargs)

    def get_new_command_title(self, language: Optional[str]) -> str:
        return self._get_localized("command_new", language)

    def get_mode_command_title(self, language: Optional[str]) -> str:
        return self._get_localized("command_mode", language)

    def get_retry_command_title(self, language: Optional[str]) -> str:
        return self._get_localized("command_retry", language)

    def get_balance_command_title(self, language: Optional[str]) -> str:
        return self._get_localized("command_balance", language)

    def get_settings_command_title(self, language: Optional[str]) -> str:
        return self._get_localized("command_settings", language)

    def get_help_command_title(self, language: Optional[str]) -> str:
        return self._get_localized("command_help", language)

    def _get_localized(self, key: str, language: Optional[str], **kwargs) -> str:
        if not language in self.get_supported_languages():
            language = self.default_language

        language = language or self.default_language
        return self.localization.get_localized(key, language, **kwargs)
