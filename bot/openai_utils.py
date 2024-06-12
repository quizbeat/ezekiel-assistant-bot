from typing import Optional, List, AsyncGenerator

import openai
from openai import AsyncOpenAI

from bot_config import BotConfig
from chat_modes.chat_modes import ChatModes
from logger_factory import LoggerFactory

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


class AssistantResponse:

    def __init__(
        self,
        message: str,
        n_input_tokens: Optional[int] = None,
        n_output_tokens: Optional[int] = None,
        n_messages_removed: int = 0,
        is_finished: bool = False
    ) -> None:
        self.message = message
        self.n_input_tokens = n_input_tokens
        self.n_output_tokens = n_output_tokens
        self.n_messages_removed = n_messages_removed
        self.is_finished = is_finished


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
        message: str,
        chat_history: List[dict],
        chat_mode: str,
        language: Optional[str]
    ) -> AsyncGenerator[AssistantResponse, None]:

        stream = self._send_message(
            message=message,
            chat_history=chat_history,
            chat_mode=chat_mode,
            language=language
        )

        async for response in stream:
            if self.should_stream or response.is_finished:
                yield response

    # Private

    async def _send_message(
        self,
        message: str,
        chat_history: List[dict],
        chat_mode: str,
        language: Optional[str]
    ) -> AsyncGenerator[AssistantResponse, None]:

        if chat_mode not in self.chat_modes.get_all_chat_modes(language):
            raise ValueError(f"Chat mode {chat_mode} is not supported")

        chat_history_len_before = len(chat_history)

        response_message = None
        n_input_tokens = None
        n_output_tokens = None

        while response_message is None:
            try:
                messages = self._compose_completion_messages(message, chat_history, chat_mode, language)
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    **OPENAI_COMPLETION_OPTIONS
                )

                response_message = ""

                async for chunk in stream:
                    n_messages_removed = chat_history_len_before - len(chat_history)

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

            except openai.error.InvalidRequestError as e:  # too many tokens
                if len(chat_history) == 0:
                    raise e

                # drop the first message in the chat history
                chat_history = chat_history[1:]

        yield AssistantResponse(
            message=response_message,
            n_input_tokens=n_input_tokens,
            n_output_tokens=n_output_tokens,
            n_messages_removed=n_messages_removed,
            is_finished=True
        )

    def _compose_completion_messages(
        self,
        new_message: str,
        history: List[dict],
        chat_mode: str,
        language: Optional[str]
    ) -> List:
        system_message = self.chat_modes.get_system_message(chat_mode, language)

        messages = [{
            "role": "system",
            "content": system_message
        }]

        for message in history:
            messages.append({
                "role": "user",
                "content": message["user"]
            })
            messages.append({
                "role": "assistant",
                "content": message["bot"]
            })

        messages.append({
            "role": "user",
            "content": new_message
        })

        return messages


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
