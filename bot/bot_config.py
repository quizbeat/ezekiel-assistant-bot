from pathlib import Path
import yaml

class BotConfig:

    def __init__(self) -> None:
        config_dir = Path(__file__).parent.parent.resolve() / "config"

        # Load yaml config
        with open(config_dir / "config.yml", 'r', encoding="utf-8") as file:
            self.config_yaml = yaml.safe_load(file)

        # Initialize config parameters
        self.db_type = self.config_yaml["db_type"]
        self.telegram_token = self.config_yaml["telegram_token"]
        self.openai_api_key = self.config_yaml["openai_api_key"]
        self.bot_admin_id = self.config_yaml["bot_admin_id"]
        self.allowed_telegram_usernames = self.config_yaml["allowed_telegram_usernames"]
        self.new_dialog_timeout = self.config_yaml["new_dialog_timeout"]
        self.enable_message_streaming = self.config_yaml.get("enable_message_streaming", True)
        self.return_n_generated_images = self.config_yaml.get("return_n_generated_images", 1)
        self.n_chat_modes_per_page = self.config_yaml.get("n_chat_modes_per_page", 5)

        # Load chat_modes
        with open(config_dir / "chat_modes.yml", 'r', encoding="utf-8") as file:
            self.chat_modes = yaml.safe_load(file)

        # Load models
        with open(config_dir / "models.yml", 'r', encoding="utf-8") as file:
            self.models = yaml.safe_load(file)

        # files
        self.help_group_chat_video_path = Path(__file__).parent.parent.resolve() / "static" / "help_group_chat.mp4"

    def get_default_chat_mode(self) -> str:
        return "assistant"

    def get_default_model(self) -> str:
        return self.models["available_text_models"][0]
