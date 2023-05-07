from typing import Optional, Any
from datetime import datetime, timezone
import uuid

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

from bot_config import BotConfig
from database import BotDatabase


class Firestore(BotDatabase):

    def __init__(self, config: BotConfig):
        creds = credentials.Certificate('firebase_service_account.json')
        self.app = firebase_admin.initialize_app(creds)
        self.db = firestore.client()
        self.users_ref = self.db.collection("users")
        self.config = config

    # User

    def check_if_user_exists(self, user_id: int, raise_exception: bool = False) -> bool:
        if self.get_user_snapshot(user_id).exists:
            return True
        
        if raise_exception:
            raise ValueError(f"User {user_id} does not exist")
        
        return False

    def add_new_user(
        self,
        user_id: int,
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ):
        current_model = self.config.models["available_text_models"][0]

        user_dict = {
            "chat_id": chat_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,

            "last_interaction": datetime.now(),
            "first_seen": datetime.now(),

            "current_dialog_id": None,
            "current_chat_mode": "assistant",
            "current_model": current_model,

            "n_used_tokens": {},

            "n_generated_images": 0,
            "n_transcribed_seconds": 0.0  # voice message transcription
        }

        if not self.check_if_user_exists(user_id):
            new_user_ref = self.users_ref.document(f"{user_id}")
            new_user_ref.set(user_dict)

    # Dialog

    def start_new_dialog(self, user_id: int) -> str:
        self.check_if_user_exists(user_id, raise_exception=True)

        dialog_id = str(uuid.uuid4())
        chat_mode = self.get_user_attribute(user_id, "current_chat_mode")
        start_time = datetime.now(timezone.utc)
        model = self.get_user_attribute(user_id, "current_model")

        dialog_dict = {
            "chat_mode": chat_mode,
            "start_time": start_time,
            "model": model,
            "messages": []
        }

        dialogs_collection = self.get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(f"{dialog_id}")
        dialog_ref.set(dialog_dict)

        # update user's current dialog
        self.set_current_dialog_id(user_id, dialog_id)

        return dialog_id

    def get_current_dialog_id(self, user_id: int):
        return self.get_user_attribute(user_id, "current_dialog_id")

    def get_dialog_messages(self, user_id: int, dialog_id: Optional[str] = None) -> dict:
        self.check_if_user_exists(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_current_dialog_id(user_id)

        dialogs_collection = self.get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_dict = dialog_ref.get().to_dict()
        
        return dialog_dict["messages"]

    def set_dialog_messages(self, user_id: int, dialog_messages: list, dialog_id: Optional[str] = None):
        self.check_if_user_exists(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_current_dialog_id(user_id)

        dialogs_collection = self.get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_ref.update({"messages": dialog_messages})

    # Current Model

    def get_current_model(self, user_id: int) -> Optional[str]:
        return self.get_user_attribute(user_id, "current_model")

    def set_current_model(self, user_id: int, current_model: str):
        self.set_user_attribute(user_id, "current_model", current_model)

    # Current Chat Mode

    def get_current_chat_mode(self, user_id: int) -> str:
        return self.get_user_attribute(user_id, "current_chat_mode")

    def set_current_chat_mode(self, user_id: int, current_chat_mode: str):
        self.set_user_attribute(user_id, "current_chat_mode", current_chat_mode)

    # Used Tokens

    def get_n_used_tokens(self, user_id: int):
        return self.get_user_attribute(user_id, "n_used_tokens")

    def set_n_used_tokens(self, user_id: int, model: str, n_input_tokens: int, n_output_tokens: int):
        n_used_tokens_dict = self.get_n_used_tokens(user_id)

        if model in n_used_tokens_dict:
            n_used_tokens_dict[model]["n_input_tokens"] += n_input_tokens
            n_used_tokens_dict[model]["n_output_tokens"] += n_output_tokens
        else:
            n_used_tokens_dict[model] = {
                "n_input_tokens": n_input_tokens,
                "n_output_tokens": n_output_tokens
            }

        self.set_user_attribute(user_id, "n_used_tokens", n_used_tokens_dict)

    # Transcribed Seconds

    def get_n_transcribed_seconds(self, user_id: int) -> Optional[float]:
        return self.get_user_attribute(user_id, "n_transcribed_seconds")

    def set_n_transcribed_seconds(self, user_id: int, n_transcribed_seconds: float):
        self.set_user_attribute(user_id, "n_transcribed_seconds", n_transcribed_seconds)

    # Generated Images

    def get_n_generated_images(self, user_id: int) -> Optional[int]:
        return self.get_user_attribute(user_id, "n_generated_images")

    def set_n_generated_images(self, user_id: int, n_generated_images: int):
        self.set_user_attribute(user_id, "n_generated_images", n_generated_images)

    # Last Interaction

    def get_last_interaction(self, user_id: int) -> datetime:
        google_last_interaction = self.get_user_attribute(user_id, "last_interaction")
        last_interaction = datetime.fromisoformat(google_last_interaction.isoformat())
        return last_interaction

    def set_last_interaction(self, user_id: int, last_interaction: datetime):
        self.set_user_attribute(user_id, "last_interaction", last_interaction)

    # Private

    def get_user_ref(self, user_id: int):
        return self.users_ref.document(f"{user_id}")

    def get_user_snapshot(self, user_id: int):
        return self.get_user_ref(user_id).get()
    
    # Dialogs

    def set_current_dialog_id(self, user_id: int, dialog_id: str):
        self.set_user_attribute(user_id, "current_dialog_id", dialog_id)

    def get_dialogs_collection(self, user_id: int):
        return self.get_user_ref(user_id).collection("dialogs")

    # Attributes Read/Write

    def get_user_attribute(self, user_id: int, key: str) -> Any:
        self.check_if_user_exists(user_id, raise_exception=True)
        user_dict = self.get_user_snapshot(user_id).to_dict()

        if key not in user_dict:
            return None

        return user_dict[key]

    def set_user_attribute(self, user_id: int, key: str, value: Any):
        self.check_if_user_exists(user_id, raise_exception=True)
        self.get_user_ref(user_id).update({key: value})
