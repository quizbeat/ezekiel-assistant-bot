import config

import database
import firestore

class DatabaseFactory:

    def __init__(self):
        self.db_type = config.db_type

    def create_database(self) -> database.BotDatabase:
        if self.db_type == "firestore":
            return firestore.Firestore()

        raise ValueError(f"Unknown database type <{self.db_type}>")
