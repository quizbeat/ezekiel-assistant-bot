from typing import List, Optional
from localization.localization import Localization


class BotResources:

    def __init__(self, default_language: str = "en"):
        self.localization = Localization()
        self.default_language = default_language

    def get_supported_languages(self) -> List[str]:
        return self.localization.get_supported_languages()

    # Help Messages

    def get_help_message(self, language: Optional[str]) -> str:
        return self._get_localized("help_message", language)

    def get_help_group_chat_message(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("help_message_group_chat", language, **kwargs)

    # Commands

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

    # Common

    def select_chat_mode(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("select_chat_mode", language, **kwargs)

    def starting_new_dialog(self, language: Optional[str]) -> str:
        return self._get_localized("starting_new_dialog", language)

    def starting_new_dialog_due_to_timeout(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("starting_new_dialog_due_to_timeout", language, **kwargs)

    def dialog_is_too_long(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("dialog_is_too_long", language, **kwargs)

    def dialog_cancelled(self, language: Optional[str]) -> str:
        return self._get_localized("dialog_cancelled", language)

    def wait_for_reply(self, language: Optional[str]) -> str:
        return self._get_localized("wait_for_reply", language)

    def invalid_request(self, language: Optional[str]) -> str:
        return self._get_localized("invalid_request", language)

    def nothing_to_cancel(self, language: Optional[str]) -> str:
        return self._get_localized("nothing_to_cancel", language)

    def editing_not_supported(self, language: Optional[str]) -> str:
        return self._get_localized("editing_not_supported", language)

    def cant_return_to_dialog(self, language: Optional[str]) -> str:
        return self._get_localized("cant_return_to_dialog", language)

    def completion_error(self, language: Optional[str]) -> str:
        return self._get_localized("completion_error", language)

    def no_message_to_retry(self, language: Optional[str]) -> str:
        return self._get_localized("no_message_to_retry", language)

    def empty_message_sent(self, language: Optional[str]) -> str:
        return self._get_localized("empty_message_sent", language)

    def image_generation_limit_exceeded(self, language: Optional[str]) -> str:
        return self._get_localized("image_generation_limit_exceeded", language)

    def description(self, language: Optional[str]) -> str:
        return self._get_localized("description", language)

    def welcome_message(self, language: Optional[str]) -> str:
        return self._get_localized("welcome_message", language)

    def balance_you_spent(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("balance_you_spent", language, **kwargs)

    def balance_tokens_used(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("balance_tokens_used", language, **kwargs)

    def balance_images_generated(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("balance_images_generated", language, **kwargs)

    def balance_seconds_transcribed(self, language: Optional[str], **kwargs) -> str:
        return self._get_localized("balance_seconds_transcribed", language, **kwargs)

    # Private

    def _get_localized(self, key: str, language: Optional[str], **kwargs) -> str:
        if not language in self.get_supported_languages():
            language = self.default_language

        language = language or self.default_language
        return self.localization.get_localized(key, language, **kwargs)
