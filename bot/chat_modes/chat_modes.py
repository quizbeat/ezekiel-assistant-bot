import os
import glob
from typing import Optional, List

import yaml

CHAT_MODE_NAME_KEY = "name"
CHAT_MODE_WELCOME_MESSAGE_KEY = "welcome_message"
CHAT_MODE_PROMPT_START_KEY = "prompt_start"
CHAT_MODE_PARSE_MODE_KEY = "parse_mode"


class ChatModes:

    def __init__(self, default_language: str = "en") -> None:
        self.chat_modes = {}
        self.default_language = default_language

        chat_modes_yml_files = glob.glob(os.path.join("bot/chat_modes", "*.yml"))
        for chat_mode_yml_file in chat_modes_yml_files:
            language = os.path.splitext(os.path.basename(chat_mode_yml_file))[0]
            with open(chat_mode_yml_file, 'r', encoding='utf8') as f:
                self.chat_modes[language] = yaml.safe_load(f)

    # Public

    def get_supported_languages(self) -> List[str]:
        return list(self.chat_modes.keys())

    def get_default_chat_mode(self) -> str:
        return "assistant"

    def get_all_chat_modes(self, language: Optional[str]) -> List[str]:
        if language is None or language not in self.get_supported_languages():
            language = self.default_language

        return list(self.chat_modes[language].keys())

    def get_chat_modes_count(self, language: Optional[str]) -> int:
        return len(self.get_all_chat_modes(language=language))

    def get_chat_mode_index(self, chat_mode: str, language: Optional[str]) -> int:
        all_chat_modes = self.get_all_chat_modes(language=language)
        for index, item in enumerate(all_chat_modes):
            if item == chat_mode:
                return index

        return 0

    def get_name(self, chat_mode: str, language: Optional[str]) -> str:
        return self._get_value(
            key=CHAT_MODE_NAME_KEY,
            chat_mode=chat_mode,
            language=language)

    def get_welcome_message(self, chat_mode: str, language: Optional[str]) -> str:
        return self._get_value(
            key=CHAT_MODE_WELCOME_MESSAGE_KEY,
            chat_mode=chat_mode,
            language=language)

    def get_prompt_start(self, chat_mode: str, language: Optional[str]) -> str:
        return self._get_value(
            key=CHAT_MODE_PROMPT_START_KEY,
            chat_mode=chat_mode,
            language=language)

    def get_parse_mode(self, chat_mode: str, language: Optional[str]) -> str:
        return self._get_value(
            key=CHAT_MODE_PARSE_MODE_KEY,
            chat_mode=chat_mode,
            language=language)

    # Private

    def _get_value(self, key: str, chat_mode: str, language: Optional[str]) -> str:
        if language is None or language not in self.get_supported_languages():
            language = self.default_language

        chat_modes_for_language = self.chat_modes[language]

        if chat_mode not in chat_modes_for_language:
            raise ValueError(f"Unknown chat mode <{chat_mode}>")

        chat_mode_dict = chat_modes_for_language[chat_mode]

        if key not in chat_mode_dict:
            raise ValueError(f"Chat mode <{chat_mode}> has no <{key}> field")

        return chat_mode_dict[key] or ""
