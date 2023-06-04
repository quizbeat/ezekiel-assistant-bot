import os
import json
from base64 import b64decode

from typing import Optional, Tuple, List, Any
from datetime import datetime, timezone
import uuid

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

from bot_config import BotConfig
from logger_factory import LoggerFactory


USERS_COLLECTION_NAME = "users"

USER_CHAT_ID_KEY = "chat_id"
USER_USERNAME_KEY = "username"
USER_FIRST_NAME_KEY = "first_name"
USER_LAST_NAME_KEY = "last_name"

USER_LAST_INTERACTION_KEY = "last_interaction"
USER_FIRST_SEEN_KEY = "first_seen"

USER_CURRENT_DIALOG_ID_KEY = "current_dialog_id"
USER_CURRENT_CHAT_MODE_KEY = "current_chat_mode"
USER_CURRENT_MODEL_KEY = "current_model"

USER_N_USED_TOKENS_KEY = "n_used_tokens"
USER_N_USED_TOKENS_INPUT_KEY = "n_input_tokens"
USER_N_USED_TOKENS_OUTPUT_KEY = "n_output_tokens"
USER_N_REMAINING_TOKENS_KEY = "n_remaining_tokens"
USER_N_REMAINING_TOKENS_INITIAL_VALUE = 50000

USER_N_GENERATED_IMAGES_KEY = "n_generated_images"
USER_N_REMAINING_GENERATED_IMAGES_KEY = "n_remaining_generated_images"
USER_N_REMAINING_GENERATED_IMAGES_INITIAL_VALUE = 5

USER_N_TRANSCRIBED_SECONDS_KEY = "n_transcribed_seconds"
USER_N_REMAINING_TRANSCRIBED_SECONDS_KEY = "n_remaining_transcribed_seconds"
USER_N_REMAINING_TRANSCRIBED_SECONDS_INITIAL_VALUE = 30

DIALOGS_COLLECTION_NAME = "dialogs"
DIALOG_CHAT_MODE_KEY = "chat_mode"
DIALOG_START_TIME_KEY = "start_time"
DIALOG_MODEL_KEY = "model"
DIALOG_MESSAGES_KEY = "messages"

DIALOG_MESSAGE_ID_KEY = "message_id"


class Firestore:

    def __init__(self, config: BotConfig):
        firebase_creds_base64 = os.getenv("FIREBASE_CREDENTIALS")
        if firebase_creds_base64 is None:
            raise ValueError("Firebase credentials missing")

        firebase_creds_json = json.loads(b64decode(firebase_creds_base64))
        creds = credentials.Certificate(firebase_creds_json)

        self.app = firebase_admin.initialize_app(creds)
        self.db = firestore.client()
        self.users_ref = self.db.collection(USERS_COLLECTION_NAME)
        self.config = config

        # Stores a user dict by a user id
        self.user_cache = {}

        reset_user_cache_ref = self.db.collection("reset_user_cache")
        self.reset_user_cache_watch = reset_user_cache_ref.on_snapshot(self._on_reset_user_cache)

        self.logger = LoggerFactory(config).create_logger(__name__)

    def __del__(self):
        self.reset_user_cache_watch.unsubscribe()

    # User

    def is_user_registered(self, user_id: int, raise_exception: bool = False) -> bool:
        if self._get_user_dict(user_id) is not None:
            return True

        if raise_exception:
            raise ValueError(f"User {user_id} does not exist")

        return False

    def register_new_user(
        self,
        user_id: int,
        chat_id: int,
        username: Optional[str],
        first_name: str,
        last_name: Optional[str],
        current_chat_mode: str,
    ):
        current_model = self.config.get_default_model()
        datetime_now = datetime.now(timezone.utc)

        user_dict = {
            USER_CHAT_ID_KEY: chat_id,
            USER_USERNAME_KEY: username,
            USER_FIRST_NAME_KEY: first_name,
            USER_LAST_NAME_KEY: last_name,

            USER_LAST_INTERACTION_KEY: datetime_now,
            USER_FIRST_SEEN_KEY: datetime_now,

            USER_CURRENT_DIALOG_ID_KEY: None,
            USER_CURRENT_CHAT_MODE_KEY: current_chat_mode,
            USER_CURRENT_MODEL_KEY: current_model,

            USER_N_USED_TOKENS_KEY: {},
            USER_N_REMAINING_TOKENS_KEY: USER_N_REMAINING_TOKENS_INITIAL_VALUE,

            USER_N_GENERATED_IMAGES_KEY: 0,
            USER_N_REMAINING_GENERATED_IMAGES_KEY: USER_N_REMAINING_GENERATED_IMAGES_INITIAL_VALUE,

            USER_N_TRANSCRIBED_SECONDS_KEY: 0,
            USER_N_REMAINING_TRANSCRIBED_SECONDS_KEY: USER_N_REMAINING_TRANSCRIBED_SECONDS_INITIAL_VALUE
        }

        new_user_ref = self.users_ref.document(f"{user_id}")
        new_user_ref.set(user_dict)

    # Dialog

    def get_current_dialog_id(self, user_id: int) -> Optional[str]:
        return self._get_user_attribute(user_id, USER_CURRENT_DIALOG_ID_KEY)

    def set_current_dialog_id(self, user_id: int, dialog_id: str):
        self._set_user_attribute(user_id, USER_CURRENT_DIALOG_ID_KEY, dialog_id)

    def start_new_dialog(self, user_id: int) -> str:
        self.is_user_registered(user_id, raise_exception=True)

        dialog_id = str(uuid.uuid4())
        chat_mode = self.get_current_chat_mode(user_id)
        model = self.get_current_model(user_id)
        start_time = datetime.now(timezone.utc)

        dialog_dict = {
            DIALOG_CHAT_MODE_KEY: chat_mode,
            DIALOG_START_TIME_KEY: start_time,
            DIALOG_MODEL_KEY: model,
            DIALOG_MESSAGES_KEY: []
        }

        dialogs_collection = self._get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(f"{dialog_id}")
        dialog_ref.set(dialog_dict)

        self.set_current_dialog_id(user_id, dialog_id)

        return dialog_id

    def get_dialog_messages(self, user_id: int, dialog_id: Optional[str] = None) -> List[dict]:
        self.is_user_registered(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_current_dialog_id(user_id)

        dialogs_collection = self._get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_dict = dialog_ref.get().to_dict()

        messages = dialog_dict.get(DIALOG_MESSAGES_KEY, [])

        return messages

    def set_dialog_messages(self, user_id: int, messages: list, dialog_id: Optional[str] = None):
        self.is_user_registered(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_current_dialog_id(user_id)

        dialogs_collection = self._get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_ref.update({DIALOG_MESSAGES_KEY: messages})

    # Returns a dialog id and the message index
    def get_dialog_id(self, user_id: int, message_id: int) -> Tuple[Optional[str], Optional[int]]:
        # TODO: Improve performance
        dialogs_collection = self._get_dialogs_collection(user_id)
        for dialog in dialogs_collection.get():
            messages = list(dialog.to_dict()[DIALOG_MESSAGES_KEY])
            for message_index, message in enumerate(messages):
                if message.get(DIALOG_MESSAGE_ID_KEY) == message_id:
                    return dialog.id, message_index

        self.logger.warning("Dialog id for a message %d not found", message_id)

        return None, None

    # Current Model

    def get_current_model(self, user_id: int) -> str:
        current_model = self._get_user_attribute(user_id, USER_CURRENT_MODEL_KEY)

        if current_model is None:
            self.logger.debug("Stored current model is None, assuming a default value")
            current_model = self.config.get_default_model()

        return current_model

    def set_current_model(self, user_id: int, current_model: str):
        self._set_user_attribute(user_id, USER_CURRENT_MODEL_KEY, current_model)

    # Current Chat Mode

    def get_chat_mode(self, user_id: int, dialog_id: str) -> str:
        dialogs_collection = self._get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_dict = dialog_ref.get().to_dict()
        chat_mode = dialog_dict.get(DIALOG_CHAT_MODE_KEY)
        return chat_mode

    def get_current_chat_mode(self, user_id: int) -> str:
        chat_mode = self._get_user_attribute(user_id, USER_CURRENT_CHAT_MODE_KEY)
        return chat_mode

    def set_current_chat_mode(self, user_id: int, current_chat_mode: str):
        self._set_user_attribute(user_id, USER_CURRENT_CHAT_MODE_KEY, current_chat_mode)

    # Used Tokens

    def get_n_used_tokens(self, user_id: int, from_cache: bool = False):
        return self._get_user_attribute(user_id, USER_N_USED_TOKENS_KEY, from_cache)

    def set_n_used_tokens(self, user_id: int, model: str, n_input_tokens: int, n_output_tokens: int):
        n_used_tokens_dict = self.get_n_used_tokens(user_id)

        if model in n_used_tokens_dict:
            n_used_tokens_dict[model][USER_N_USED_TOKENS_INPUT_KEY] += n_input_tokens
            n_used_tokens_dict[model][USER_N_USED_TOKENS_OUTPUT_KEY] += n_output_tokens
        else:
            n_used_tokens_dict[model] = {
                USER_N_USED_TOKENS_INPUT_KEY: n_input_tokens,
                USER_N_USED_TOKENS_OUTPUT_KEY: n_output_tokens
            }

        self._set_user_attribute(user_id, USER_N_USED_TOKENS_KEY, n_used_tokens_dict)

    def get_n_remaining_tokens(self, user_id: int) -> int:
        n_remaining_tokens = self._get_user_attribute(user_id, USER_N_REMAINING_TOKENS_KEY)

        if n_remaining_tokens is None:
            self.set_n_remaining_tokens(user_id, USER_N_REMAINING_TOKENS_INITIAL_VALUE)

        return self._get_user_attribute(user_id, USER_N_REMAINING_TOKENS_KEY) or 0

    def set_n_remaining_tokens(self, user_id: int, n_remaining_tokens: int):
        return self._set_user_attribute(user_id, USER_N_REMAINING_TOKENS_KEY, n_remaining_tokens)

    # Transcribed Seconds

    def get_n_transcribed_seconds(self, user_id: int, from_cache: bool = False) -> int:
        return int(self._get_user_attribute(user_id, USER_N_TRANSCRIBED_SECONDS_KEY, from_cache) or 0)

    def set_n_transcribed_seconds(self, user_id: int, n_transcribed_seconds: int):
        self._set_user_attribute(user_id, USER_N_TRANSCRIBED_SECONDS_KEY, n_transcribed_seconds)

    def get_n_remaining_transcribed_seconds(self, user_id: int) -> int:
        n_remaining_transcribed_seconds = self._get_user_attribute(user_id, USER_N_REMAINING_TRANSCRIBED_SECONDS_KEY)

        if n_remaining_transcribed_seconds is None:
            self.set_n_remaining_transcribed_seconds(user_id, USER_N_REMAINING_TRANSCRIBED_SECONDS_INITIAL_VALUE)

        return self._get_user_attribute(user_id, USER_N_REMAINING_TRANSCRIBED_SECONDS_KEY) or 0

    def set_n_remaining_transcribed_seconds(self, user_id: int, n_remaining_transcribed_seconds: int):
        return self._set_user_attribute(
            user_id,
            USER_N_REMAINING_TRANSCRIBED_SECONDS_KEY,
            n_remaining_transcribed_seconds)

    # Generated Images

    def get_n_generated_images(self, user_id: int, from_cache: bool = False) -> int:
        return self._get_user_attribute(user_id, USER_N_GENERATED_IMAGES_KEY, from_cache) or 0

    def set_n_generated_images(self, user_id: int, n_generated_images: int):
        self._set_user_attribute(user_id, USER_N_GENERATED_IMAGES_KEY, n_generated_images)

    def get_n_remaining_generated_images(self, user_id: int) -> int:
        n_remaining_generated_images = self._get_user_attribute(user_id, USER_N_REMAINING_GENERATED_IMAGES_KEY)

        if n_remaining_generated_images is None:
            self.set_n_remaining_generated_images(user_id, USER_N_REMAINING_GENERATED_IMAGES_INITIAL_VALUE)

        return self._get_user_attribute(user_id, USER_N_REMAINING_GENERATED_IMAGES_KEY) or 0

    def set_n_remaining_generated_images(self, user_id: int, n_remaining_generated_images: int):
        return self._set_user_attribute(
            user_id,
            USER_N_REMAINING_GENERATED_IMAGES_KEY,
            n_remaining_generated_images)

    # Last Interaction

    def get_last_interaction(self, user_id: int) -> datetime:
        google_last_interaction = self._get_user_attribute(user_id, USER_LAST_INTERACTION_KEY)
        last_interaction = datetime.fromisoformat(google_last_interaction.isoformat())
        return last_interaction

    def set_last_interaction(self, user_id: int, last_interaction: datetime):
        self._set_user_attribute(user_id, USER_LAST_INTERACTION_KEY, last_interaction)

    # Admin Stats

    def get_all_users_ids(self) -> List[int]:
        users_stream = self.users_ref.stream()

        user_ids = []
        for user in users_stream:
            user_ids.append(int(user.id))

        return user_ids

    def get_username(self, user_id: int) -> Optional[str]:
        return self._get_user_attribute(user_id, USER_USERNAME_KEY)

    # Private

    def _get_user_ref(self, user_id: int):
        return self.users_ref.document(f"{user_id}")

    def _get_user_dict(self, user_id: int, from_cache: bool = True) -> Optional[dict]:
        if from_cache and user_id in self.user_cache:
            return self.user_cache.get(user_id)

        self.logger.debug("Reading from Firestore for the user %d", user_id)

        user_ref = self._get_user_ref(user_id)

        # Read a snapshot from Firestore
        user_snapshot = user_ref.get()

        # If the document does not exist at the time of the snapshot is taken,
        # the snapshot’s reference, data, update_time, and create_time attributes
        # will all be None and its exists attribute will be False.

        if not user_snapshot.exists:
            self.logger.debug("User with id %d does not exist, do not cache the snapshot", user_id)
            return None

        self._update_user_cache(user_id, user_snapshot)

        return self.user_cache.get(user_id)

    def _on_reset_user_cache(self, snapshots, change, read_time):
        self.logger.debug("Resetting user cache")
        self.user_cache = {}

    def _update_user_cache(self, user_id: int, user_snapshot):
        self.user_cache[user_id] = user_snapshot.to_dict()

    # Dialogs

    def _get_dialogs_collection(self, user_id: int):
        return self._get_user_ref(user_id).collection(DIALOGS_COLLECTION_NAME)

    # Attributes Read/Write

    def _get_user_attribute(self, user_id: int, key: str, from_cache: bool = True) -> Any:
        user_dict = self._get_user_dict(user_id, from_cache) or {}
        return user_dict.get(key)

    def _set_user_attribute(self, user_id: int, key: str, value: Any):
        update_dict = {key: value}

        if user_id in self.user_cache:
            self.user_cache[user_id].update(update_dict)

        self._get_user_ref(user_id).update(update_dict)
        self.logger.debug("Did set %s", update_dict)
