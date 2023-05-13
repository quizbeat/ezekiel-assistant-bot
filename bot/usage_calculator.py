from typing import Optional, List

from bot_config import BotConfig
from bot_resources import BotResources
from firestore import Firestore


class DALLE2Usage:

    def __init__(self, n_generated_images: int, n_dollars_spent: float) -> None:
        self.n_generated_images = n_generated_images
        self.n_dollars_spent = n_dollars_spent


class WhisperUsage:

    def __init__(self, n_transcribed_seconds: int, n_dollars_spent: float) -> None:
        self.n_transcribed_seconds = n_transcribed_seconds
        self.n_dollars_spent = n_dollars_spent


class GPTUsage:

    def __init__(self,
                 model_name: str,
                 n_used_input_tokens: int,
                 n_user_output_tokens: int,
                 n_dollars_spent) -> None:

        self.model_name = model_name
        self.n_used_input_tokens = n_used_input_tokens
        self.n_user_output_tokens = n_user_output_tokens
        self.n_dollars_spent = n_dollars_spent


class UsageCalculator:

    def __init__(self, config: BotConfig, db: Firestore, resources: BotResources) -> None:
        self.resources = resources
        self.config = config
        self.db = db

    def get_usage_description(self, user_id: int, language: Optional[str]) -> str:
        n_total_spent_dollars = 0.0

        gpt_models_usage = self._get_gpt_usage(user_id)
        for usage in gpt_models_usage:
            n_total_spent_dollars += usage.n_dollars_spent

        dalle2_usage = self._get_dalle_usage(user_id)
        if dalle2_usage.n_generated_images > 0:
            n_total_spent_dollars += dalle2_usage.n_dollars_spent

        whisper_usage = self._get_whisper_usage(user_id)
        if whisper_usage.n_transcribed_seconds > 0:
            n_total_spent_dollars += whisper_usage.n_dollars_spent

        you_spent_text = self.resources.balance_you_spent(language)
        description = f"{you_spent_text}: <b>${n_total_spent_dollars:.03f}</b>\n\n"

        for usage in gpt_models_usage:
            n_total_used_tokens = usage.n_used_input_tokens + usage.n_user_output_tokens
            description += f"💬 {usage.model_name}: "
            description += f"<b>$ {usage.n_dollars_spent:.03f}</b> "
            description += f"({self.resources.balance_tokens_used(language, count=n_total_used_tokens)})\n"

        if dalle2_usage.n_generated_images > 0:
            description += "🏞️ DALL·E 2: "
            description += f"<b>$ {dalle2_usage.n_dollars_spent:.03f}</b> "
            description += f"({self.resources.balance_images_generated(language, count=dalle2_usage.n_generated_images)})\n"

        if whisper_usage.n_transcribed_seconds > 0:
            description += "🎤 Whisper: "
            description += f"<b>$ {whisper_usage.n_dollars_spent:.03f}</b> "
            description += f"({self.resources.balance_seconds_transcribed(language, count=whisper_usage.n_transcribed_seconds)})\n"

        return description

    def _get_gpt_usage(self, user_id: int) -> List[GPTUsage]:
        models_usage = []

        n_used_tokens_dict = self.db.get_n_used_tokens(user_id)
        for model_name in sorted(n_used_tokens_dict.keys()):
            n_input_tokens = n_used_tokens_dict[model_name]["n_input_tokens"]
            price_per_1000_input_tokens = self._get_price_per_1000_input_tokens(model_name)
            n_input_spent_dollars = self._get_dollars_spent(n_input_tokens, price_per_1000_input_tokens)

            n_output_tokens = n_used_tokens_dict[model_name]["n_output_tokens"]
            price_per_1000_output_tokens = self._get_price_per_1000_output_tokens(model_name)
            n_output_spent_dollars = self._get_dollars_spent(n_output_tokens, price_per_1000_output_tokens)

            n_total_spent_dollars = n_input_spent_dollars + n_output_spent_dollars

            usage = GPTUsage(model_name, n_input_tokens, n_output_tokens, n_total_spent_dollars)
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
        price_per_image = self.config.models["info"]["dalle-2"]["price_per_1_image"]
        n_dollars_spent = price_per_image * n_generated_images
        return DALLE2Usage(n_generated_images, n_dollars_spent)

    def _get_whisper_usage(self, user_id: int) -> WhisperUsage:
        n_transcribed_seconds = self.db.get_n_transcribed_seconds(user_id)
        price_per_minute = self.config.models["info"]["whisper"]["price_per_1_min"]
        n_dollars_spent = price_per_minute * (n_transcribed_seconds / 60)
        return WhisperUsage(n_transcribed_seconds, n_dollars_spent)
