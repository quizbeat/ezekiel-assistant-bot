from typing import Optional, List, Any
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

USER_N_GENERATED_IMAGES_KEY = "n_generated_images"
USER_N_TRANSCRIBED_SECONDS_KEY = "n_transcribed_seconds"

DIALOGS_COLLECTION_NAME = "dialogs"
DIALOG_CHAT_MODE_KEY = "chat_mode"
DIALOG_START_TIME_KEY = "start_time"
DIALOG_MODEL_KEY = "model"
DIALOG_MESSAGES_KEY = "messages"


class Firestore:

    def __init__(self, config: BotConfig):
        creds = credentials.Certificate('firebase_service_account.json')
        self.app = firebase_admin.initialize_app(creds)
        self.db = firestore.client()
        self.users_ref = self.db.collection(USERS_COLLECTION_NAME)
        self.config = config

        self.user_snapshot_cache = {}
        self.user_snapshot_watch = {}

        self.logger = LoggerFactory(config).create_logger(__name__)

    def __del__(self):
        for watch in self.user_snapshot_watch.values():
            watch.unsubscribe()

    # User

    def is_user_registered(self, user_id: int, raise_exception: bool = False) -> bool:
        if self.get_user_snapshot(user_id).exists:
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
            USER_N_GENERATED_IMAGES_KEY: 0,
            USER_N_TRANSCRIBED_SECONDS_KEY: 0
        }

        new_user_ref = self.users_ref.document(f"{user_id}")
        new_user_ref.set(user_dict)

    # Dialog

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

        dialogs_collection = self.get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(f"{dialog_id}")
        dialog_ref.set(dialog_dict)

        self.set_current_dialog_id(user_id, dialog_id)

        return dialog_id

    def get_dialog_messages(self, user_id: int, dialog_id: Optional[str] = None) -> List[dict]:
        self.is_user_registered(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_current_dialog_id(user_id)

        dialogs_collection = self.get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_dict = dialog_ref.get().to_dict()

        return dialog_dict[DIALOG_MESSAGES_KEY]

    def set_dialog_messages(self, user_id: int, dialog_messages: list, dialog_id: Optional[str] = None):
        self.is_user_registered(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_current_dialog_id(user_id)

        dialogs_collection = self.get_dialogs_collection(user_id)
        dialog_ref = dialogs_collection.document(dialog_id)
        dialog_ref.update({DIALOG_MESSAGES_KEY: dialog_messages})

    # Current Model

    def get_current_model(self, user_id: int) -> str:
        return self.get_user_attribute(user_id, USER_CURRENT_MODEL_KEY) or self.config.get_default_model()

    def set_current_model(self, user_id: int, current_model: str):
        self.set_user_attribute(user_id, USER_CURRENT_MODEL_KEY, current_model)

    # Current Chat Mode

    def get_current_chat_mode(self, user_id: int) -> str:
        return self.get_user_attribute(user_id, USER_CURRENT_CHAT_MODE_KEY)

    def set_current_chat_mode(self, user_id: int, current_chat_mode: str):
        self.set_user_attribute(
            user_id, USER_CURRENT_CHAT_MODE_KEY, current_chat_mode)

    # Used Tokens

    def get_n_used_tokens(self, user_id: int):
        return self.get_user_attribute(user_id, USER_N_USED_TOKENS_KEY)

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

        self.set_user_attribute(
            user_id, USER_N_USED_TOKENS_KEY, n_used_tokens_dict)

    # Transcribed Seconds

    def get_n_transcribed_seconds(self, user_id: int) -> int:
        return int(self.get_user_attribute(user_id, USER_N_TRANSCRIBED_SECONDS_KEY) or 0)

    def set_n_transcribed_seconds(self, user_id: int, n_transcribed_seconds: int):
        self.set_user_attribute(
            user_id, USER_N_TRANSCRIBED_SECONDS_KEY, n_transcribed_seconds)

    # Generated Images

    def get_n_generated_images(self, user_id: int) -> int:
        return self.get_user_attribute(user_id, USER_N_GENERATED_IMAGES_KEY) or 0

    def set_n_generated_images(self, user_id: int, n_generated_images: int):
        self.set_user_attribute(
            user_id, USER_N_GENERATED_IMAGES_KEY, n_generated_images)

    # Last Interaction

    def get_last_interaction(self, user_id: int) -> datetime:
        google_last_interaction = self.get_user_attribute(
            user_id, USER_LAST_INTERACTION_KEY)
        last_interaction = datetime.fromisoformat(
            google_last_interaction.isoformat())
        return last_interaction

    def set_last_interaction(self, user_id: int, last_interaction: datetime):
        self.set_user_attribute(
            user_id, USER_LAST_INTERACTION_KEY, last_interaction)

    # Admin Stats

    def get_all_users_ids(self) -> List[int]:
        users_stream = self.users_ref.stream()

        ids = []
        for user in users_stream:
            ids.append(user.id)

        return ids

    def get_user_username(self, user_id: int) -> str:
        return self.get_user_attribute(user_id, "username") or f"id:{user_id}"

    # Private

    def get_user_ref(self, user_id: int):
        return self.users_ref.document(f"{user_id}")

    # Returns a snapshot of the current document.
    # If the document does not exist at the time of the snapshot is taken,
    # the snapshot’s reference, data, update_time, and create_time attributes
    # will all be None and its exists attribute will be False.
    def get_user_snapshot(self, user_id: int):
        if user_id in self.user_snapshot_cache:
            # self.logger.debug("Reading from Cache")
            return self.user_snapshot_cache[user_id]

        # self.logger.debug("Reading from Firestore")

        user_ref = self.get_user_ref(user_id)
        user_snapshot_watch = user_ref.on_snapshot(
            self.on_user_snapshot_changes)
        self.user_snapshot_watch[user_id] = user_snapshot_watch

        user_snapshot = user_ref.get()
        self.update_user_snapshot_cache(user_id, user_snapshot)

        return user_snapshot

    def on_user_snapshot_changes(self, snapshots, changes, read_time):
        if len(snapshots) == 0:
            self.logger.error("received an empty snapshot list")
            return

        user_snapshot = snapshots[0]
        user_id = int(user_snapshot.id)
        self.update_user_snapshot_cache(user_id, user_snapshot)

    def update_user_snapshot_cache(self, user_id: int, user_snapshot):
        self.user_snapshot_cache[user_id] = user_snapshot
        # self.logger.debug("User shapshot cache updated")

    # Dialogs

    def get_current_dialog_id(self, user_id: int) -> Optional[str]:
        return self.get_user_attribute(user_id, USER_CURRENT_DIALOG_ID_KEY)

    def set_current_dialog_id(self, user_id: int, dialog_id: str):
        self.set_user_attribute(user_id, USER_CURRENT_DIALOG_ID_KEY, dialog_id)

    # TODO: Declare the return value type
    def get_dialogs_collection(self, user_id: int):
        return self.get_user_ref(user_id).collection(DIALOGS_COLLECTION_NAME)

    # Attributes Read/Write

    def get_user_attribute(self, user_id: int, key: str) -> Any:
        # self.logger.debug("key = %s", key)

        user_dict = self.get_user_snapshot(user_id).to_dict()

        if key not in user_dict:
            self.logger.error("Unknown key: %s", key)
            return None

        return user_dict[key]

    def set_user_attribute(self, user_id: int, key: str, value: Any):
        # self.logger.debug("key = %s", key)
        self.get_user_ref(user_id).update({key: value})
