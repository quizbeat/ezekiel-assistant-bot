from abc import ABC, abstractmethod
from typing import Optional, Any
from datetime import datetime

class BotDatabase(ABC):

    # User Management

    @abstractmethod
    def is_user_registered(
        self, 
        user_id: int, 
        raise_exception: bool = False
    ) -> bool:
        pass

    @abstractmethod
    def register_new_user(
        self,
        user_id: int,
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ):
        pass

    # Dialog Management

    @abstractmethod
    def start_new_dialog(self, user_id: int) -> str:
        pass
    
    @abstractmethod
    def get_current_dialog_id(self, user_id: int) -> Optional[str]:
        pass

    @abstractmethod
    def get_dialog_messages(self, user_id: int, dialog_id: Optional[str] = None) -> dict:
        pass

    @abstractmethod
    def set_dialog_messages(self, user_id: int, dialog_messages: list, dialog_id: Optional[str] = None):
        pass

    # Last Interaction

    @abstractmethod
    def get_last_interaction(self, user_id: int) -> datetime:
        pass

    @abstractmethod
    def set_last_interaction(self, user_id: int, last_interaction: datetime):
        pass

    # Current Model

    @abstractmethod
    def get_current_model(self, user_id: int) -> Optional[str]:
        pass

    @abstractmethod
    def set_current_model(self, user_id: int, current_model: str):
        pass

    # Current Chat Mode

    @abstractmethod
    def get_current_chat_mode(self, user_id: int) -> str:
        pass

    @abstractmethod
    def set_current_chat_mode(self, user_id: int, current_chat_mode: str):
        pass

    # Tokens

    @abstractmethod
    def get_n_used_tokens(self, user_id: int) -> dict:
        pass

    @abstractmethod
    def set_n_used_tokens(self, user_id: int, model: str, n_input_tokens: int, n_output_tokens: int):
        pass

    # Transcribed Seconds

    @abstractmethod
    def get_n_transcribed_seconds(self, user_id: int) -> Optional[float]:
        pass

    @abstractmethod
    def set_n_transcribed_seconds(self, user_id: int, n_transcribed_seconds: float):
        pass

    # Generated Images

    @abstractmethod
    def get_n_generated_images(self, user_id: int) -> Optional[int]:
        pass

    @abstractmethod
    def set_n_generated_images(self, user_id: int, n_generated_images: int):
        pass
