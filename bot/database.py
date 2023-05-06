from abc import ABC, abstractmethod
from typing import Optional, Any
from datetime import datetime

class BotDatabase(ABC):

    @abstractmethod
    def check_if_user_exists(
        self, 
        user_id: int, 
        raise_exception: bool = False
    ) -> bool:
        pass

    @abstractmethod
    def add_new_user(
        self,
        user_id: int,
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ):
        pass

    # Returns a dialog ID
    @abstractmethod
    def start_new_dialog(self, user_id: int) -> str:
        pass

    @abstractmethod
    def get_user_attribute(self, user_id: int, key: str) -> Any:
        pass

    @abstractmethod
    def set_user_attribute(self, user_id: int, key: str, value: Any):
        pass

    @abstractmethod
    def update_n_used_tokens(self, user_id: int, model: str, n_input_tokens: int, n_output_tokens: int):
        pass

    @abstractmethod
    def get_dialog_messages(self, user_id: int, dialog_id: Optional[str] = None) -> dict:
        pass

    @abstractmethod
    def set_dialog_messages(self, user_id: int, dialog_messages: list, dialog_id: Optional[str] = None):
        pass

    @abstractmethod
    def get_last_interaction(self, user_id: int) -> datetime:
        pass

    @abstractmethod
    def set_last_interaction(self, user_id: int, new_last_interaction: datetime):
        pass
