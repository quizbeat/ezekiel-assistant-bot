import logging
from sys import stdout

from bot_config import BotConfig


class LoggerFactory:

    def __init__(self, config: BotConfig) -> None:
        self._log_level = config.log_level

    def create_logger(self, logger_name: str) -> logging.Logger:
        logger = logging.getLogger(logger_name)
        logger.setLevel(self._log_level)
        logger.setLevel(logging.DEBUG)

        log_handler = logging.StreamHandler(stdout)
        log_handler.setFormatter(self._create_log_formatter())

        logger.addHandler(log_handler)

        return logger

    def _create_log_formatter(self) -> logging.Formatter:
        return logging.Formatter(
            "%(name)-12s %(asctime)s %(levelname)-8s %(filename)s:%(funcName)s %(message)s")
