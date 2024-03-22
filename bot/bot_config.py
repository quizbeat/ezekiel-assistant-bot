import os
from pathlib import Path
import yaml


class BotConfig:

    def __init__(self) -> None:
        self.log_level = int(os.getenv("LOG_LEVEL") or 10)

        self.telegram_token = os.getenv("TELEGRAM_TOKEN")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")

        self.bot_admin_id = int(os.getenv("BOT_ADMIN_ID") or -1)
        self.allowed_telegram_usernames = (os.getenv("ALLOWED_TELEGRAM_USERNAMES") or "").split(",")

        self.episodes_chat_id = int(os.getenv("EPISODES_CHAT_ID") or -1)
        self.episodes_aux_chat_id = int(os.getenv("EPISODES_AUX_CHAT_ID") or -1)
        self.episodes_toc_message_id = int(os.getenv("EPISODES_TOC_MESSAGE_ID") or -1)
        self.episodes_url_name = (os.getenv("EPISODES_URL_NAME") or "")

        self.new_dialog_timeout = int(os.getenv("NEW_DIALOG_TIMEOUT") or 600)
        self.enable_message_streaming = True

        self.return_n_generated_images = 1
        self.n_chat_modes_per_page = 5

        # Load models
        config_dir = Path(__file__).parent.parent.resolve() / "config"
        with open(config_dir / "models.yml", 'r', encoding="utf-8") as file:
            self.models = yaml.safe_load(file)

        # files
        self.help_group_chat_video_path = Path(
            __file__).parent.parent.resolve() / "static" / "help_group_chat.mp4"

    def get_default_model(self) -> str:
        return self.models["available_text_models"][0]
