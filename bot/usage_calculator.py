from typing import Optional, List
from dataclasses import dataclass

from bot_config import BotConfig
from bot_resources import BotResources
from firestore import Firestore


@dataclass
class DALLE2Usage:
    n_generated_images: int


@dataclass
class WhisperUsage:
    n_transcribed_seconds: int


@dataclass
class GPTUsage:
    model_name: str
    n_used_input_tokens: int
    n_user_output_tokens: int


class UsageCalculator:

    # Init

    def __init__(self, config: BotConfig, db: Firestore, resources: BotResources) -> None:
        self.resources = resources
        self.config = config
        self.db = db

    # Public

    def get_usage_description(self, user_id: int, language: Optional[str]) -> str:
        gpt_usage = self._get_gpt_usage(user_id)
        dalle2_usage = self._get_dalle_usage(user_id)
        whisper_usage = self._get_whisper_usage(user_id)

        usage_header = self.resources.usage_header(language)
        description = f"<b>{usage_header}</b>:\n"

        for usage in gpt_usage:
            n_total_used_tokens = usage.n_used_input_tokens + usage.n_user_output_tokens
            usage_tokens = self.resources.usage_tokens(language, count=n_total_used_tokens)
            description += f"💬 <b>{usage.model_name}</b>: {usage_tokens}\n"

        if dalle2_usage.n_generated_images > 0:
            usage_images = self.resources.usage_images(language, count=dalle2_usage.n_generated_images)
            description += f"🏞️ <b>DALL·E 2</b>: {usage_images}\n"

        if whisper_usage.n_transcribed_seconds > 0:
            usage_seconds = self.resources.usage_seconds(language, count=whisper_usage.n_transcribed_seconds)
            description += f"🎤 <b>Whisper</b>: {usage_seconds}\n"

        return description

    # Private

    def _get_gpt_usage(self, user_id: int) -> List[GPTUsage]:
        models_usage = []

        n_used_tokens_dict = self.db.get_n_used_tokens(user_id)
        for model_name in sorted(n_used_tokens_dict.keys()):
            n_input_tokens = n_used_tokens_dict[model_name]["n_input_tokens"]
            n_output_tokens = n_used_tokens_dict[model_name]["n_output_tokens"]
            usage = GPTUsage(model_name, n_input_tokens, n_output_tokens)
            models_usage.append(usage)

        return models_usage

    def _get_price_per_1000_input_tokens(self, model_name: str) -> float:
        return self.config.models["info"][model_name]["price_per_1000_input_tokens"]

    def _get_price_per_1000_output_tokens(self, model_name: str) -> float:
        return self.config.models["info"][model_name]["price_per_1000_output_tokens"]

    def _get_dollars_spent(self, n_used_tokens: int, price_per_1000_tokens: float) -> float:
        return price_per_1000_tokens * (n_used_tokens / 1000)

    def _get_dalle_usage(self, user_id: int) -> DALLE2Usage:
        n_generated_images = self.db.get_n_generated_images(user_id)
        return DALLE2Usage(n_generated_images)

    def _get_whisper_usage(self, user_id: int) -> WhisperUsage:
        n_transcribed_seconds = self.db.get_n_transcribed_seconds(user_id)
        return WhisperUsage(n_transcribed_seconds)
