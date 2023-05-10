from bot_config import BotConfig
from firestore import Firestore

class DatabaseFactory:

    def __init__(self, config: BotConfig):
        self.config = config

    def create_database(self) -> Firestore:
        if self.config.db_type == "firestore":
            return Firestore(self.config)

        raise ValueError(f"Unknown database type <{self.config.db_type}>")
