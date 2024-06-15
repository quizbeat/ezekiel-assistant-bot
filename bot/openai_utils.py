import base64
from io import BytesIO
from typing import Optional, List, AsyncGenerator
from dataclasses import dataclass

import openai
from openai import AsyncOpenAI

from bot_config import BotConfig
from chat_modes.chat_modes import ChatModes
from logger_factory import LoggerFactory
from dialog import DialogMessage, DialogMessageImage

OPENAI_COMPLETION_OPTIONS = {
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "temperature": 0.7,
    "max_tokens": 1000,
    "top_p": 1,
}

OPENAI_INVALID_REQUEST_PREFIX = "Your request was rejected as a result of our safety system"
OPENAI_SUPPORTED_MODELS = {"gpt-3.5-turbo", "gpt-4o"}
OPENAI_DEFAULT_MODEL = "gpt-3.5-turbo"


@dataclass
class AssistantResponse:
    message: str
    n_input_tokens: Optional[int] = None
    n_output_tokens: Optional[int] = None
    n_messages_removed: int = 0
    is_finished: bool = False


class Assistant:

    # Init

    def __init__(
        self,
        config: BotConfig,
        chat_modes: ChatModes,
        model=OPENAI_DEFAULT_MODEL
    ) -> None:
        assert model in OPENAI_SUPPORTED_MODELS, f"Unknown model: {model}"

        self.logger = LoggerFactory(config).create_logger(__name__)
        self.client = AsyncOpenAI(api_key=config.openai_api_key)
        self.should_stream = config.enable_message_streaming
        self.chat_modes = chat_modes
        self.model = model

    # Public

    async def send_message(
        self,
        message_text: str,
        message_images: list[DialogMessageImage],
        dialog_messages: list[DialogMessage],
        chat_mode: str,
        language: Optional[str]
    ) -> AsyncGenerator[AssistantResponse, None]:

        stream = self._send_message(
            message_text=message_text,
            message_images=message_images,
            dialog_messages=dialog_messages,
            chat_mode=chat_mode,
            language=language
        )

        async for response in stream:
            if self.should_stream or response.is_finished:
                yield response

    # Private

    async def _send_message(
        self,
        message_text: str,
        message_images: list[DialogMessageImage],
        dialog_messages: list[DialogMessage],
        chat_mode: str,
        language: Optional[str]
    ) -> AsyncGenerator[AssistantResponse, None]:

        if chat_mode not in self.chat_modes.get_all_chat_modes(language):
            raise ValueError(f"Chat mode {chat_mode} is not supported")

        if len(message_images) > 0 and self.model != "gpt-4o":
            raise ValueError('Vision feature requires GTP-4o')

        dialog_messages_len_before = len(dialog_messages)

        response_message = None
        n_input_tokens = None
        n_output_tokens = None

        while response_message is None:
            try:
                messages = self._compose_completion_messages(
                    new_message_text=message_text,
                    new_message_images=message_images,
                    dialog_messages=dialog_messages,
                    chat_mode=chat_mode,
                    language=language
                )

                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    **OPENAI_COMPLETION_OPTIONS
                )

                response_message = ""

                async for chunk in stream:
                    n_messages_removed = dialog_messages_len_before - len(dialog_messages)

                    if chunk.choices:
                        response_message += chunk.choices[0].delta.content or ""

                    if chunk.usage:
                        n_input_tokens = chunk.usage.prompt_tokens
                        n_output_tokens = chunk.usage.completion_tokens

                    yield AssistantResponse(
                        message=response_message,
                        n_messages_removed=n_messages_removed
                    )

                # postprocess
                response_message = response_message.strip()

            # TODO: Handle too many tokens error
            except openai.BadRequestError as e:
                self.logger.error(f"Exception: {e}")

                if len(dialog_messages) == 0:
                    raise e

                # drop the first message in the chat history
                dialog_messages = dialog_messages[1:]

        self.logger.debug(f"tokens used: input={n_input_tokens}; output={n_output_tokens}")

        # TODO: Handle [DONE] message from the response

        yield AssistantResponse(
            message=response_message,
            n_input_tokens=n_input_tokens,
            n_output_tokens=n_output_tokens,
            n_messages_removed=n_messages_removed,
            is_finished=True
        )

    # TODO: Extract the logic to CompletionMessagesComposer
    def _compose_completion_messages(
        self,
        new_message_text: str,
        new_message_images: list[DialogMessageImage],
        dialog_messages: list[DialogMessage],
        chat_mode: str,
        language: Optional[str]
    ) -> list[dict]:
        system_message = self.chat_modes.get_system_message(chat_mode, language)

        messages = []

        # Feed the prompt
        messages.append(
            self._compose_completion_message(
                role="system",
                content=system_message
            )
        )

        # Feed the context
        for message in dialog_messages:
            user_content = []

            user_content.append({
                "type": "text",
                "text": message.user.text
            })

            for image in message.user.images:
                user_content.append(
                    self._compose_completion_user_message_image(image)
                )

            messages.append(
                self._compose_completion_message(
                    role="user",
                    content=user_content
                )
            )

            messages.append(
                self._compose_completion_message(
                    role="assistant",
                    content=message.bot.text
                )
            )

        # Feed the new content
        new_user_content: list[dict] = [{
            "type": "text",
            "text": new_message_text
        }]

        for image in new_message_images:
            new_user_content.append(
                self._compose_completion_user_message_image(image)
            )

        messages.append(
            self._compose_completion_message(
                role="user",
                content=new_user_content
            )
        )

        # self.logger.debug(f"composed messages: {messages}")

        return messages

    def _compose_completion_user_message_image(self, image: DialogMessageImage) -> dict:
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image.base64}",
                "detail": "high"
            }
        }

    def _compose_completion_message(self, role: str, content) -> dict:
        return {"role": role, "content": content}

    def _encode_image(self, image: BytesIO) -> str:
        return base64.b64encode(image.read()).decode("utf-8")


# TODO: Migrate to openai 1.x
async def transcribe_audio(audio_file) -> str:
    transcription = openai.audio.transcriptions.create(file=audio_file, model='whisper-1')
    return transcription.text


# TODO: Migrate to openai 1.x
async def generate_images(prompt, n_images=4) -> List:
    r = await openai.Image.acreate(prompt=prompt, n=n_images, size="512x512")
    image_urls = [item.url for item in r.data]
    return image_urls


async def is_content_acceptable(prompt):
    r = await openai.Moderation.acreate(input=prompt)
    return not all(r.results[0].categories.values())
