from bot_config import BotConfig
from firestore import Firestore


class DatabaseFactory:

    def __init__(self, config: BotConfig):
        self.config = config

    def create_database(self) -> Firestore:
        return Firestore(self.config)
