import asyncio
import traceback
import html
import json
import math
import re
import tempfile
from enum import Enum
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from urllib.request import urlopen
from bs4 import BeautifulSoup

import openai
import pydub

import telegram
from telegram import (
    User,
    Update,
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    AIORateLimiter,
    filters
)
from telegram.constants import ParseMode

from bot_config import BotConfig
from bot_resources import BotResources
from database_factory import DatabaseFactory
from usage_calculator import UsageCalculator
from logger_factory import LoggerFactory
from chat_modes.chat_modes import ChatModes

import openai_utils
import telegram_utils
import bot_utils
import health_check


class ChatContextSwitch(Enum):
    SWITCHED = 1
    NOT_NEEDED = 2
    CANT_SWITCH = 3


class Bot:

    def __init__(self):
        config = BotConfig()

        openai_utils.configure_openai(config.openai_api_key)

        self.config = config
        self.chat_modes = ChatModes()
        self.resources = BotResources()
        self.db = DatabaseFactory(config).create_database()
        self.usage_calculator = UsageCalculator(config, self.db, self.resources)
        self.logger = LoggerFactory(config).create_logger(__name__)

        self.user_semaphores = {}
        self.user_tasks = {}

    def update_last_interaction(self, user_id: int):
        self.db.set_last_interaction(user_id, datetime.now(timezone.utc))

    async def register_user_if_not_registered_for_update(self, update: Update):
        if update.message is None or update.message.from_user is None:
            self.logger.error("Update has no message or sender")
            return

        await self.register_user_if_not_registered(
            user=update.message.from_user,
            chat_id=update.message.chat_id)

    async def register_user_if_not_registered_for_callback(self, callback_query: CallbackQuery):
        if callback_query.message is None or callback_query.from_user is None:
            self.logger.error("Callback Query has no message or sender")
            return

        await self.register_user_if_not_registered(
            user=callback_query.from_user,
            chat_id=callback_query.message.chat_id)

    async def register_user_if_not_registered(self, user: User, chat_id: int):
        if not self.db.is_user_registered(user.id):
            self.db.register_new_user(
                user_id=user.id,
                chat_id=chat_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                current_chat_mode=self.chat_modes.get_default_chat_mode())

            self.db.start_new_dialog(user.id)

        if user.id not in self.user_semaphores:
            self.user_semaphores[user.id] = asyncio.Semaphore(1)

    async def should_ignore(self, update: Update, context: CallbackContext) -> bool:
        try:
            message = update.message
            if message is None:
                self.logger.error("Update has no message")
                return True

            if message.chat.type == "private":
                return False

            if message.text is not None and ("@" + context.bot.username) in message.text:
                # The bot mentioned in a group chat, should ignore messages w/o mentions only.
                return False

            if (message.reply_to_message is not None
                and message.reply_to_message.from_user is not None
                    and message.reply_to_message.from_user.id == context.bot.id):
                return False

        except Exception as e:
            self.logger.error("Exception: %s", e)
            return False  # TODO: Why False?

        return True

    async def start_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user = update.message.from_user
        self.update_last_interaction(user.id)

        # language = telegram_utils.get_language(update)
        # welcome_message = self.resources.welcome_message(language)
        # await update.message.reply_text(welcome_message, parse_mode=ParseMode.HTML)

        await self.help_handle(update, context)
        # await self.show_chat_modes_handle(update, context)

    async def help_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("Message has no sender (from_user)")
            return

        user = update.message.from_user
        user_id = user.id

        # This update probably allows to bypass the dialog timeout
        # self.update_last_interaction(user_id)

        help_text = self.resources.get_help_message(user.language_code)
        help_text_chunks = help_text.split("\n\n")

        message_text = help_text_chunks[0]
        message = await update.message.reply_text(message_text, parse_mode=ParseMode.HTML)

        async def complete_by_chunks(message_text, help_text_chunks):
            for i in range(1, len(help_text_chunks)):
                message_text += f"\n\n{help_text_chunks[i]}"
                await context.bot.edit_message_text(
                    message_text,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    parse_mode=ParseMode.HTML)
                await asyncio.sleep(1.5)

        async with self.user_semaphores[user_id]:
            task = asyncio.create_task(complete_by_chunks(message_text, help_text_chunks))
            self.user_tasks[user_id] = task

            try:
                await task
            except Exception:
                pass
            finally:
                if user_id in self.user_tasks:
                    del self.user_tasks[user_id]

    async def help_group_chat_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user = update.message.from_user
        self.update_last_interaction(user.id)

        bot_username = "@" + context.bot.username
        help_message = self.resources.get_help_group_chat_message(
            language=user.language_code,
            bot_username=bot_username)

        await update.message.reply_text(help_message, parse_mode=ParseMode.HTML)
        await update.message.reply_video(self.config.help_group_chat_video_path)

    async def retry_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message is not answered yet")
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)
        dialog_messages = self.db.get_dialog_messages(user_id)

        if len(dialog_messages) == 0:
            language = telegram_utils.get_language(update)
            reply_text = self.resources.no_message_to_retry(language)
            await update.message.reply_text(reply_text)
            return

        last_dialog_message = dialog_messages.pop()
        # last message was removed from the context
        self.db.set_dialog_messages(user_id, dialog_messages, dialog_id=None)
        await self.message_handle(
            update,
            context,
            message=last_dialog_message["user"],
            use_new_dialog_timeout=False)

    async def channel_message_handle(
            self,
            update: Update,
            context: CallbackContext):

        if update.channel_post is None:
            return

        channel_post = update.channel_post
        chat_id = channel_post.chat.id

        if chat_id != self.config.episodes_chat_id:
            self.logger.debug(f"expected {self.config.episodes_chat_id}, got {chat_id}")
            return

        message_id = channel_post.message_id
        caption = channel_post.caption

        episode_url = caption
        soup = self.get_soup(episode_url)
        episode_date = self.get_episode_date(soup)
        episode_number = self.get_episode_number(soup)
        episode_title = self.get_episode_title(soup)
        episode_description = self.get_episode_description(soup)
        episode_timecodes = self.get_episode_timecodes(soup)

        episode_caption = self.make_episode_caption(
            episode_date=episode_date,
            episode_number=episode_number,
            episode_title=episode_title,
            episode_description=episode_description,
            episode_timecodes=episode_timecodes,
            episode_url=episode_url)

        self.logger.debug(episode_caption)

        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=episode_caption,
            parse_mode=ParseMode.MARKDOWN_V2)

        table_of_contents_message_id = self.config.episodes_toc_message_id

        forwarded_message = await context.bot.forward_message(
            chat_id=chat_id,
            from_chat_id=chat_id,
            message_id=table_of_contents_message_id,
            disable_notification=True)

        table_of_contents = forwarded_message.text_markdown_v2

        episode_message_link = self.escape_markdown(self.make_message_link(chat_id, message_id))
        table_of_contents += f"\n• [{episode_number}: {self.escape_markdown(episode_title)}]({episode_message_link})"

        await context.bot.edit_message_text(
            table_of_contents,
            chat_id=chat_id,
            message_id=table_of_contents_message_id,
            parse_mode=ParseMode.MARKDOWN_V2)

        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=forwarded_message.id)

    def escape_markdown(self, text):
        return telegram.helpers.escape_markdown(text=text, version=2)

    def make_message_link(self, chat_id, message_id) -> str:
        fixed_chat_id = str(abs(chat_id))[3:]
        return f"https://t.me/c/{fixed_chat_id}/{message_id}"

    def get_soup(self, url):
        return BeautifulSoup(urlopen(url), 'html.parser')

    def make_episode_caption(
            self,
            episode_date,
            episode_number,
            episode_title,
            episode_description,
            episode_timecodes,
            episode_url):

        caption = f"{episode_date}\n"
        caption += f"*Episode {episode_number}: {self.escape_markdown(episode_title)}*\n\n"
        caption += f"{episode_description}\n\n"
        caption += f"{episode_timecodes}\n"
        caption += f"{self.escape_markdown(episode_url)}"
        return caption

        # return f"{episode_date}\n*Episode {episode_number}: {self.escape_markdown(episode_title)}*\n{self.escape_markdown(episode_url)}\n\n{episode_timecodes}"

    def get_episode_timecodes(self, soup):
        content = soup.find('div', {"class": "m-mb1"})
        data = content.get_text('<separator>').split('<separator>')

        timecodes = ""
        for i in range(0, len(data), 2):
            title = data[i]
            timecode = data[i + 1]
            timecodes += f"{timecode} {self.escape_markdown(title)}\n"

        return timecodes

    def get_episode_title(self, soup):
        content = soup.find('h1', {"class": "fg-white fg-black bold ts-d-r3 ts-m-r2 lh-2 center"})
        return content.get_text()

    def get_episode_description(self, soup):
        div_tag = soup.find('div', {"class": "md-ctn"})
        p_tag = div_tag.find('p')

        for code_tag in p_tag.find_all('code'):
            code_tag.replace_with('`' + code_tag.get_text() + '`')

        p_contents = ''.join(map(str, p_tag.contents))

        escape_chars = r"\_*[]()~>#+-=|{}.!"
        return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", p_contents)

    def get_episode_number(self, soup):
        return soup.find('div', {"class": "m-pb2 fg-gray650 fg-black normal h6 lh-4 center"}).get_text().split(' • ')[0].split('#')[-1].rjust(3, '0')

    def get_episode_date(self, soup):
        return soup.find('div', {"class": "m-pb2 fg-gray650 fg-black normal h6 lh-4 center"}).get_text().split(' • ')[1]

    async def message_handle(
            self,
            update: Update,
            context: CallbackContext,
            message: Optional[str] = None,
            use_new_dialog_timeout=True):

        if update.edited_message is not None:
            self.logger.warning("Ignoring edited messages")
            await self.edited_message_handle(update, context)
            return

        if await self.should_ignore(update, context):
            self.logger.debug("Ignoring the update")
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender")
            return

        message_text = message or update.message.text or ""

        self.logger.debug("%s sent \"%s\"", telegram_utils.get_username_or_id(update), message_text)

        # remove bot mention (in group chats)
        if update.message.chat.type != "private":
            message_text = message_text.replace("@" + context.bot.username, "").strip()

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message has not been answered yet")
            return

        context_switch = await self.switch_context_if_needed(update.message, context)

        if context_switch is ChatContextSwitch.CANT_SWITCH:
            return

        user_id = update.message.from_user.id
        chat_mode = self.db.get_current_chat_mode(user_id)

        if chat_mode == "artist":
            self.logger.debug("Current chat mode is Artist, will generate image")
            await self.generate_image_handle(update, context, message=message)
            return

        current_n_remaining_tokens = self.db.get_n_remaining_tokens(user_id)
        if current_n_remaining_tokens <= 0:
            language = telegram_utils.get_language(update)
            reply_text = self.resources.tokens_limit_reached(language)
            await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
            return

        async def message_handle_fn():
            if update.message is None:
                self.logger.error("The update has no message")
                return

            if use_new_dialog_timeout:
                last_interaction = self.db.get_last_interaction(user_id)
                has_dialog_messages = len(self.db.get_dialog_messages(user_id)) > 0
                seconds_since_last_interaction = (datetime.now(timezone.utc) - last_interaction).seconds
                if seconds_since_last_interaction > self.config.new_dialog_timeout and has_dialog_messages:
                    self.db.start_new_dialog(user_id)
                    language = telegram_utils.get_language(update)
                    chat_mode_name = self.chat_modes.get_name(chat_mode, language)
                    reply_text = self.resources.starting_new_dialog_due_to_timeout(
                        language=language,
                        chat_mode_name=chat_mode_name)
                    await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

            self.update_last_interaction(user_id)

            # in case of CancelledError
            n_input_tokens, n_output_tokens = 0, 0
            current_model = self.db.get_current_model(user_id)

            try:
                # send a placeholder message to the user
                placeholder_message = await update.message.reply_text("…")

                # send typing action
                await update.message.chat.send_action(action="typing")

                language = telegram_utils.get_language(update)

                if message_text is None or len(message_text) == 0:
                    reply_text = self.resources.empty_message_sent(language)
                    await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
                    return

                dialog_messages = self.db.get_dialog_messages(user_id, dialog_id=None)
                internal_parse_mode = self.chat_modes.get_parse_mode(chat_mode, language)
                parse_mode = telegram_utils.get_parse_mode(internal_parse_mode)
                language = bot_utils.detect_language(message_text)

                answer = ""
                n_first_dialog_messages_removed = 0
                chatgpt_instance = openai_utils.ChatGPT(
                    config=self.config,
                    chat_modes=self.chat_modes,
                    model=current_model)

                if self.config.enable_message_streaming:
                    gen = chatgpt_instance.send_message_stream(
                        message_text,
                        dialog_messages=dialog_messages,
                        chat_mode=chat_mode,
                        language=language)

                else:
                    answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed = await chatgpt_instance.send_message(
                        message_text,
                        dialog_messages=dialog_messages,
                        chat_mode=chat_mode,
                        language=language)

                    async def fake_gen():
                        yield "finished", answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed

                    gen = fake_gen()

                previous_answer = ""

                async for gen_item in gen:
                    status, answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed = gen_item

                    answer = answer[:telegram_utils.MESSAGE_LENGTH_LIMIT]

                    # update only when 100 new symbols are ready
                    if abs(len(answer) - len(previous_answer)) < 100 and status != "finished":
                        continue

                    try:
                        await context.bot.edit_message_text(
                            answer,
                            chat_id=placeholder_message.chat_id,
                            message_id=placeholder_message.message_id,
                            parse_mode=parse_mode)

                    except telegram.error.BadRequest as e:
                        if str(e).startswith("Message is not modified"):
                            continue

                        await context.bot.edit_message_text(
                            answer,
                            chat_id=placeholder_message.chat_id,
                            message_id=placeholder_message.message_id
                        )

                    await asyncio.sleep(0.01)  # wait a bit to avoid flooding

                    previous_answer = answer

                # update user data
                new_dialog_message = {
                    "user": message_text,
                    "bot": answer,
                    "message_id": placeholder_message.message_id,
                    "date": datetime.now(timezone.utc)
                }

                current_dialog_messages = self.db.get_dialog_messages(user_id)
                new_dialog_messages = current_dialog_messages + [new_dialog_message]
                self.db.set_dialog_messages(user_id, new_dialog_messages)

                self.db.set_n_used_tokens(user_id, current_model, n_input_tokens, n_output_tokens)

                new_n_remaining_tokens = current_n_remaining_tokens - (n_input_tokens + n_output_tokens)
                self.db.set_n_remaining_tokens(user_id, new_n_remaining_tokens)

            except asyncio.CancelledError:
                # note: intermediate token updates only work when enable_message_streaming=True (config.yml)
                self.db.set_n_used_tokens(user_id, current_model, n_input_tokens, n_output_tokens)
                raise

            except Exception as e:
                user_info = telegram_utils.get_username_or_id(update)
                error_message = f"User {user_info} got an exception during completion: {e}"
                self.logger.error(error_message)
                language = telegram_utils.get_language(update)
                reply_text = self.resources.completion_error(language)
                await update.message.reply_text(reply_text)
                return

            # send message if some messages were removed from the context

            if n_first_dialog_messages_removed is None:
                self.logger.error("n_first_dialog_messages_removed is None")
                return

            if n_first_dialog_messages_removed > 0:
                reply_text = self.resources.dialog_is_too_long(
                    language=telegram_utils.get_language(update),
                    count=n_first_dialog_messages_removed)

                await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

        async with self.user_semaphores[user_id]:
            task = asyncio.create_task(message_handle_fn())
            self.user_tasks[user_id] = task

            try:
                await task
            except asyncio.CancelledError:
                language = telegram_utils.get_language(update)
                reply_text = self.resources.dialog_cancelled(language)
                await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
            else:
                pass
            finally:
                if user_id in self.user_tasks:
                    del self.user_tasks[user_id]

    async def switch_context_if_needed(self, message: Message, context: CallbackContext) -> ChatContextSwitch:
        if message.from_user is None:
            return ChatContextSwitch.CANT_SWITCH

        user_id = message.from_user.id

        if message.reply_to_message is None:
            self.logger.debug("There is no reply, context switch not needed")
            return ChatContextSwitch.NOT_NEEDED

        if message.reply_to_message.from_user is None:
            self.logger.error("The sender of the message is unknown")
            return ChatContextSwitch.CANT_SWITCH

        if message.reply_to_message.from_user.id != context.bot.id:
            self.logger.debug("This is not a reply to a bot's message")
            return ChatContextSwitch.NOT_NEEDED

        # User has replied to a bot's message.
        # Check if the message is from a different context.

        reply_to_message_id = message.reply_to_message.message_id
        current_dialog_id = self.db.get_current_dialog_id(user_id)
        target_dialog_id, target_message_i = self.db.get_dialog_id(user_id, reply_to_message_id)

        if target_dialog_id is None or target_message_i is None:
            language = telegram_utils.get_language(message)
            reply_text = self.resources.cant_return_to_dialog(language)
            await message.reply_text(reply_text, parse_mode=ParseMode.HTML)
            return ChatContextSwitch.CANT_SWITCH

        # Should update last interaction here, otherwise if this is the same dialog,
        # the bot will start a new dialog due to timeout if exceeded.
        self.update_last_interaction(user_id)

        target_dialog_messages = self.db.get_dialog_messages(user_id, target_dialog_id)

        has_replied_to_current_dialog = (target_dialog_id == current_dialog_id)
        has_replied_to_last_message_from_dialog = (target_message_i == (len(target_dialog_messages) - 1))

        if has_replied_to_current_dialog and has_replied_to_last_message_from_dialog:
            self.logger.debug("This is the last message of the same dialog, do nothing")
            return ChatContextSwitch.NOT_NEEDED

        target_chat_mode = self.db.get_chat_mode(user_id, target_dialog_id)
        self.db.set_current_chat_mode(user_id, target_chat_mode)

        new_dialog_id = self.db.start_new_dialog(user_id)
        new_dialog_messages = target_dialog_messages[:(target_message_i + 1)]
        self.db.set_dialog_messages(user_id, new_dialog_messages, new_dialog_id)

        return ChatContextSwitch.SWITCHED

    async def is_previous_message_not_answered_yet_for_update(self, update: Update) -> bool:
        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return False

        return await self.is_previous_message_not_answered_yet(
            message=update.message,
            user_id=update.message.from_user.id,
            language=update.message.from_user.language_code)

    async def is_previous_message_not_answered_yet_for_callback(self, callback_query: CallbackQuery) -> bool:
        await self.register_user_if_not_registered_for_callback(callback_query)

        if callback_query.message is None or callback_query.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return False

        return await self.is_previous_message_not_answered_yet(
            message=callback_query.message,
            user_id=callback_query.from_user.id,
            language=callback_query.from_user.language_code)

    async def is_previous_message_not_answered_yet(self, message: Message, user_id: int, language: Optional[str]) -> bool:
        if not self.user_semaphores[user_id].locked():
            return False

        await message.reply_text(
            self.resources.wait_for_reply(language),
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML)

        return True

    async def voice_message_handle(self, update: Update, context: CallbackContext):
        if await self.should_ignore(update, context):
            self.logger.debug("Ignoring the update")
            return

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message has not been answered yet")
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        current_n_remaining_transcribed_seconds = self.db.get_n_remaining_transcribed_seconds(user_id)

        if current_n_remaining_transcribed_seconds <= 0:
            language = telegram_utils.get_language(update)
            reply_text = self.resources.voice_recognition_limit_reached(language)
            await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
            return

        voice = update.message.voice

        if voice is None:
            self.logger.error("The Voice Message has no voice attached")
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir = Path(tmp_dir)
            voice_ogg_path = tmp_dir / "voice.ogg"

            # download
            voice_file = await context.bot.get_file(voice.file_id)
            await voice_file.download_to_drive(voice_ogg_path)

            # convert to mp3
            voice_mp3_path = tmp_dir / "voice.mp3"
            pydub.AudioSegment.from_file(voice_ogg_path).export(
                voice_mp3_path, format="mp3")

            # transcribe
            with open(voice_mp3_path, "rb") as f:
                transcribed_text = await openai_utils.transcribe_audio(f) or ""

        reply_text = f"🎤: <i>{transcribed_text}</i>"
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

        self.logger.debug("%s sent voice \"%s\"", telegram_utils.get_username_or_id(update), transcribed_text)

        current_n_transcribed_seconds = self.db.get_n_transcribed_seconds(user_id)
        new_n_transcribed_seconds = current_n_transcribed_seconds + voice.duration
        self.db.set_n_transcribed_seconds(user_id, new_n_transcribed_seconds)

        new_n_remaining_transcribed_seconds = current_n_remaining_transcribed_seconds - voice.duration
        self.db.set_n_remaining_transcribed_seconds(user_id, new_n_remaining_transcribed_seconds)

        await self.message_handle(update, context, message=transcribed_text)

    async def generate_image_handle(self, update: Update, context: CallbackContext, message: Optional[str] = None):
        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        current_n_remaining_generated_images = self.db.get_n_remaining_generated_images(user_id)
        if current_n_remaining_generated_images <= 0:
            language = telegram_utils.get_language(update)
            reply_text = self.resources.image_generation_limit_reached(language)
            await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
            return

        await update.message.chat.send_action(action="upload_photo")

        message_text = message or update.message.text
        if message_text is None or len(message_text) == 0:
            self.logger.error("Expected non-empty message")
            return

        try:
            image_urls = await openai_utils.generate_images(
                prompt=message_text,
                n_images=self.config.return_n_generated_images)

        except openai.error.InvalidRequestError as e:
            if str(e).startswith(openai_utils.OPENAI_INVALID_REQUEST_PREFIX):
                language = telegram_utils.get_language(update)
                reply_text = self.resources.invalid_request(language)
                await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
                return

            raise

        n_generated_images = self.db.get_n_generated_images(user_id)
        new_n_generated_images = n_generated_images + self.config.return_n_generated_images
        self.db.set_n_generated_images(user_id, new_n_generated_images)

        new_n_remaining_generated_images = current_n_remaining_generated_images - 1
        self.db.set_n_remaining_generated_images(user_id, new_n_remaining_generated_images)

        for image_url in image_urls:
            await update.message.chat.send_action(action="upload_photo")
            await update.message.reply_photo(image_url, parse_mode=ParseMode.HTML)

    async def new_dialog_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        self.db.start_new_dialog(user_id)

        language = telegram_utils.get_language(update)
        reply_text = self.resources.starting_new_dialog(language)
        await update.message.reply_text(reply_text)

        chat_mode = self.db.get_current_chat_mode(user_id)
        welcome_message = self.chat_modes.get_welcome_message(chat_mode, language)
        await update.message.reply_text(f"{welcome_message}", parse_mode=ParseMode.HTML)

    async def cancel_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        if user_id in self.user_tasks:
            task = self.user_tasks[user_id]
            task.cancel()
        else:
            language = telegram_utils.get_language(update)
            reply_text = self.resources.nothing_to_cancel(language)
            await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

    def get_chat_mode_menu(self, page_index: int, current_chat_mode: str, language: Optional[str]):
        n_chat_modes = self.chat_modes.get_chat_modes_count(language)
        n_chat_modes_per_page = self.config.n_chat_modes_per_page
        n_pages = math.ceil(n_chat_modes / n_chat_modes_per_page)

        reply_text = self.resources.select_chat_mode(language, count=n_chat_modes)

        # buttons
        chat_modes = self.chat_modes.get_all_chat_modes(language)
        page_chat_modes = chat_modes[page_index * n_chat_modes_per_page:(page_index + 1) * n_chat_modes_per_page]

        keyboard = []
        for chat_mode in page_chat_modes:
            name = self.chat_modes.get_name(chat_mode, language)
            if chat_mode == current_chat_mode:
                name = f"✔ {name}"
            callback_data = f"set_chat_mode|{chat_mode}"
            keyboard.append([InlineKeyboardButton(name, callback_data=callback_data)])

        # pagination
        if len(chat_modes) > n_chat_modes_per_page:
            last_page_index = (n_pages - 1)
            is_first_page = (page_index == 0)
            is_last_page = (page_index == last_page_index)
            is_middle_page = not (is_first_page or is_last_page)

            previous_page_index = page_index - 1
            previous_page_data = f"show_chat_modes|{previous_page_index}"
            previous_page_button = InlineKeyboardButton("←", callback_data=previous_page_data)

            next_page_index = page_index + 1
            next_page_data = f"show_chat_modes|{next_page_index}"
            next_page_button = InlineKeyboardButton("→", callback_data=next_page_data)

            if is_first_page:
                keyboard.append([next_page_button])

            elif is_middle_page:
                keyboard.append([previous_page_button, next_page_button])

            elif is_last_page:
                keyboard.append([previous_page_button])

        reply_markup = InlineKeyboardMarkup(keyboard)

        return reply_text, reply_markup

    def get_page_index(self, chat_mode: str, language: Optional[str]) -> int:
        n_chat_modes_per_page = self.config.n_chat_modes_per_page
        chat_mode_index = self.chat_modes.get_chat_mode_index(chat_mode, language)
        page_index = chat_mode_index // n_chat_modes_per_page
        return page_index

    async def show_chat_modes_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message has not been answered yet")
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        language = telegram_utils.get_language(update)
        current_chat_mode = self.db.get_current_chat_mode(user_id)
        reply_text, reply_markup = self.get_chat_mode_menu(0, current_chat_mode, language)

        await update.message.reply_text(
            reply_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML)

    # The Update object passed to this function has only callback_query field.
    # All the data you need to work with should be extracted from callback_query.
    async def show_chat_modes_callback_handle(self, update: Update, context: CallbackContext):
        callback_query = update.callback_query
        if callback_query is None:
            self.logger.error("Callback Query is None")
            return

        # NOTE: The user info is in the callback_query.from_user,
        # not in the callback_query.message.from_user.
        user = callback_query.from_user
        self.logger.debug("called for %s", user.username)

        await self.register_user_if_not_registered_for_callback(callback_query)

        if await self.is_previous_message_not_answered_yet_for_callback(callback_query):
            self.logger.debug("The previous message has not been answered yet")
            return

        await callback_query.answer()

        if callback_query.data is None:
            self.logger.error("Callback Query Data is None")
            return

        page_index = int(callback_query.data.split("|")[1])
        if page_index < 0:
            self.logger.error("Invalid page index: %d", page_index)
            return

        current_chat_mode = self.db.get_current_chat_mode(user.id)

        text, reply_markup = self.get_chat_mode_menu(
            page_index=page_index,
            current_chat_mode=current_chat_mode,
            language=user.language_code)

        try:
            await callback_query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML)

        except telegram.error.BadRequest as e:
            if str(e).startswith("Message is not modified"):
                pass

    # The Update object passed to this function has only callback_query field.
    # All the data you need to work with should be extracted from callback_query.
    async def set_chat_mode_handle(self, update: Update, context: CallbackContext):
        callback_query = update.callback_query
        if callback_query is None:
            self.logger.error("Callback Query is None")
            return

        # NOTE: The user info is in the callback_query.from_user,
        # not in the callback_query.message.from_user.
        user = callback_query.from_user
        self.logger.debug("called for %s", user.username)

        await self.register_user_if_not_registered_for_callback(callback_query)

        if callback_query.message is None:
            self.logger.error("Callback Query has no message")
            return

        await callback_query.answer()

        if callback_query.data is None:
            self.logger.error("Callback Query Data is None")
            return

        chat_mode = callback_query.data.split("|")[1]
        # page_index = self.get_page_index(chat_mode, user.language_code)

        # text, reply_markup = self.get_chat_mode_menu(
        #     page_index=page_index,
        #     current_chat_mode=chat_mode,
        #     language=user.language_code)

        welcome_message = self.chat_modes.get_welcome_message(chat_mode, user.language_code)

        try:
            await callback_query.delete_message()

        except telegram.error.BadRequest as e:
            if str(e).startswith("Message is not modified"):
                pass

        self.update_last_interaction(user.id)
        self.db.set_current_chat_mode(user.id, chat_mode)
        self.db.start_new_dialog(user.id)

        await context.bot.send_message(
            callback_query.message.chat.id,
            welcome_message,
            parse_mode=ParseMode.HTML)

    def get_settings_menu(self, user_id: int):
        current_model = self.db.get_current_model(user_id)
        text = self.config.models["info"][current_model]["description"]

        text += "\n\n"
        score_dict = self.config.models["info"][current_model]["scores"]
        for score_key, score_value in score_dict.items():
            text += "🟢" * score_value + "⚪️" * (5 - score_value) + f" – {score_key}\n\n"

        text += "\nSelect <b>model</b>:"

        # buttons to choose models
        buttons = []
        for model_key in self.config.models["available_text_models"]:
            title = self.config.models["info"][model_key]["name"]

            if model_key == current_model:
                title = "✅ " + title

            callback_data = f"set_settings|{model_key}"
            buttons.append(InlineKeyboardButton(title, callback_data=callback_data))

        reply_markup = InlineKeyboardMarkup([buttons])

        return text, reply_markup

    async def settings_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message has not been answered yet")
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("Update has no message or sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        text, reply_markup = self.get_settings_menu(user_id)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    # The Update object passed to this function has only callback_query field.
    # All the data you need to work with should be extracted from callback_query.
    async def set_settings_handle(self, update: Update, context: CallbackContext):
        callback_query = update.callback_query
        if callback_query is None:
            self.logger.error("Callback Query is None")
            return

        # NOTE: The user info is in the callback_query.from_user,
        # not in the callback_query.message.from_user.
        user = callback_query.from_user
        self.logger.debug("called for %s", user.username)

        await self.register_user_if_not_registered_for_callback(callback_query)

        await callback_query.answer()

        if callback_query.data is None:
            self.logger.error("Callback Query has no data")
            return

        _, model_key = callback_query.data.split("|")
        self.db.set_current_model(user.id, model_key)
        self.db.start_new_dialog(user.id)

        text, reply_markup = self.get_settings_menu(user.id)

        try:
            await callback_query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML)

        except telegram.error.BadRequest as e:
            if str(e).startswith("Message is not modified"):
                pass

    async def show_balance_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("Update has no message or sender (from_user)")
            return

        user = update.message.from_user
        self.update_last_interaction(user.id)

        reply_text = self.usage_calculator.get_usage_description(user.id, user.language_code)
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

    async def show_stats_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        if update.message is None:
            self.logger.error("Update has no message")
            return

        reply_text = "All Users Stats:\n\n"

        for user_id in self.db.get_all_users_ids():
            username = self.db.get_username(user_id) or f"id:{user_id}"
            reply_text += f"@{username}\n"
            usage_description = self.usage_calculator.get_usage_description(user_id, "en")
            reply_text += f"{usage_description}\n\n"

        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

    async def edited_message_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", telegram_utils.get_username_or_id(update))

        if update.edited_message is None:
            self.logger.error("Update has no edited message")
            return

        language = telegram_utils.get_language(update)
        reply_text = self.resources.editing_not_supported(language)
        await update.edited_message.reply_text(reply_text, parse_mode=ParseMode.HTML)

    async def error_handle(self, update: Update, context: CallbackContext) -> None:
        self.logger.error(msg="Exception while handling an update:", exc_info=context.error)

        # if isinstance(context.error, telegram.error.Conflict):
        #     self.logger.debug("DigitalOcean deploy conflict")
        #     return

        if update is None:
            self.logger.debug("Update is None")
            return

        chat_id = int(self.config.bot_admin_id)

        try:
            # collect error message
            tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
            tb_string = "".join(tb_list)
            update_str = update.to_dict() if isinstance(update, Update) else str(update)
            message = (
                f"An exception was raised while handling an update\n"
                f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
                "</pre>\n\n"
                f"<pre>{html.escape(tb_string)}</pre>")

            for message_chunk in bot_utils.split_into_chunks(message, telegram_utils.MESSAGE_LENGTH_LIMIT):
                try:
                    await context.bot.send_message(
                        chat_id,
                        message_chunk,
                        parse_mode=ParseMode.HTML)

                except telegram.error.BadRequest:
                    # answer has invalid characters, so we send it without parse_mode
                    await context.bot.send_message(
                        chat_id,
                        message_chunk)

        except Exception as e:
            await context.bot.send_message(
                chat_id,
                f"Exception thrown in error handler: {e}")

    async def set_commands(
        self,
        application: Application,
        command_language: str,
        user_language: str = ""
    ):
        await application.bot.set_my_commands([
            BotCommand("/new", self.resources.get_new_command_title(command_language)),
            BotCommand("/mode", self.resources.get_mode_command_title(command_language)),
            BotCommand("/retry", self.resources.get_retry_command_title(command_language)),
            # BotCommand("/balance", self.resources.get_balance_command_title(command_language)),
            # BotCommand("/settings", resources.get_settings_command_title(command_language)),
            BotCommand("/help", self.resources.get_help_command_title(command_language)),
        ], language_code=user_language)

    async def set_description(
        self,
        application: Application,
        description_language: str,
        user_language: str = ""
    ):
        await application.bot.set_my_description(
            self.resources.description(description_language),
            language_code=user_language)

    async def post_init(self, application: Application):
        self.logger.debug(self.resources.get_supported_languages())

        # Setup supported languages
        for language in self.resources.get_supported_languages():
            await self.set_commands(application, language, language)
            await self.set_description(application, language, language)

            await application.bot.set_my_description(
                self.resources.description(language),
                language_code=language)

        # Setup other languages
        default_language = "en"
        await self.set_commands(application, default_language)
        await self.set_description(application, default_language)

        # Notify admin
        chat_id = int(self.config.bot_admin_id)
        await application.bot.sendMessage(chat_id, "🚀 Started")

    def run(self) -> None:
        application = (
            ApplicationBuilder()
            .token(self.config.telegram_token)
            .concurrent_updates(True)
            .rate_limiter(AIORateLimiter(max_retries=5))
            .post_init(self.post_init)
            .build())

        # add handlers
        user_filter = filters.ALL
        if len(self.config.allowed_telegram_usernames) > 0:
            usernames = [x for x in self.config.allowed_telegram_usernames if isinstance(x, str)]
            user_ids = [int(x) for x in self.config.allowed_telegram_usernames if x.isdigit()]
            user_filter = filters.User(username=usernames) | filters.User(user_id=user_ids)

        application.add_handler(CommandHandler("start", self.start_handle, filters=user_filter))
        application.add_handler(CommandHandler("help", self.help_handle, filters=user_filter))
        application.add_handler(CommandHandler("help_group_chat", self.help_group_chat_handle, filters=user_filter))

        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, self.message_handle))
        application.add_handler(CommandHandler("retry", self.retry_handle, filters=user_filter))
        application.add_handler(CommandHandler("new", self.new_dialog_handle, filters=user_filter))
        application.add_handler(CommandHandler("cancel", self.cancel_handle, filters=user_filter))

        application.add_handler(MessageHandler(filters.VOICE & user_filter, self.voice_message_handle))

        application.add_handler(CommandHandler("mode", self.show_chat_modes_handle, filters=user_filter))
        application.add_handler(CallbackQueryHandler(self.show_chat_modes_callback_handle, pattern="^show_chat_modes"))
        application.add_handler(CallbackQueryHandler(self.set_chat_mode_handle, pattern="^set_chat_mode"))

        admin_filter = filters.User(user_id=self.config.bot_admin_id)
        application.add_handler(CommandHandler("stats", self.show_stats_handle, filters=admin_filter))

        application.add_handler(CommandHandler("settings", self.settings_handle, filters=admin_filter))
        application.add_handler(CallbackQueryHandler(self.set_settings_handle, pattern="^set_settings"))

        application.add_handler(CommandHandler("balance", self.show_balance_handle, filters=admin_filter))

        application.add_error_handler(self.error_handle)

        application.add_handler(MessageHandler(filters.ALL, self.channel_message_handle))

        # start the bot
        application.run_polling()


if __name__ == "__main__":
    health_check.start_health_check_thread()
    Bot().run()
