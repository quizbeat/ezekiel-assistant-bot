import os
import glob
from typing import List
from string import Template

import yaml
from babel.plural import PluralRule


class Localization:

    def __init__(self) -> None:
        self.data = {}
        self.plural_rule = PluralRule({'one': 'n is 1'})

        files = glob.glob(os.path.join("bot/localization", "*.yaml"))

        for file in files:
            language = os.path.splitext(os.path.basename(file))[0]
            with open(file, 'r', encoding='utf8') as f:
                self.data[language] = yaml.safe_load(f)

    def get_supported_languages(self) -> List[str]:
        return list(self.data.keys())

    def get_localized(self, key: str, language: str, **kwargs) -> str:
        if language not in self.data:
            return key

        text = self.data[language].get(key, key)

        if isinstance(text, dict):
            count = kwargs.get("count", 1)
            try:
                count = int(count)
            except Exception:
                return key

            text = text.get(self.plural_rule(count), key)

        return Template(text).safe_substitute(**kwargs)
