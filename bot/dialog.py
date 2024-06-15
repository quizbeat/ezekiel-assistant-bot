from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class DialogMessageImage:
    base64: str


@dataclass
class DialogMessageContent:
    text: str
    images: list[DialogMessageImage]


@dataclass
class DialogMessage:
    user: DialogMessageContent
    bot: DialogMessageContent
    message_id: Optional[int]
    date: Optional[datetime]
