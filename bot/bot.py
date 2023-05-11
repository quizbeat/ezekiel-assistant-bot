from typing import Optional
from textwrap import dedent
import asyncio
import traceback
import html
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import openai
from openai import error
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
from logger_factory import LoggerFactory

import openai_utils
import bot_utils

TELEGRAM_MESSAGE_LENGTH_LIMIT = 4096


class Bot:

    def __init__(self, config: BotConfig):
        openai_utils.configure_openai(config)

        self.config = config
        self.resources = BotResources()
        self.db = DatabaseFactory(config).create_database()
        self.logger = LoggerFactory(config).create_logger(__name__)

        self.user_semaphores = {}
        self.user_tasks = {}

    def update_last_interaction(self, user_id: int):
        self.db.set_last_interaction(user_id, datetime.now(timezone.utc))

    def get_username(self, update: Update) -> str:
        if update.message is None or update.message.from_user is None:
            return "unknown user"

        return update.message.from_user.username or "unknown user"

    async def register_user_if_not_registered_for_update(self, update: Update):
        if update.message is None or update.message.from_user is None:
            self.logger.error("Update has no message or sender")
            return

        await self.register_user_if_not_registered(
            user=update.message.from_user,
            chat_id=update.message.chat_id
        )

    async def register_user_if_not_registered_for_callback(self, callback_query: CallbackQuery):
        if callback_query.message is None:
            self.logger.error("Callback Query has no message")
            return

        user = callback_query.from_user
        if user is None:
            self.logger.error("Callback Query has no sender (user)")
            return

        chat_id = callback_query.message.chat_id

        await self.register_user_if_not_registered(user, chat_id)

    async def register_user_if_not_registered(self, user: User, chat_id: int):
        if not self.db.is_user_registered(user.id):
            self.db.register_new_user(
                user_id=user.id,
                chat_id=chat_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )

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
                # The bot mentioned in a group chat, should ignore messages w/o mentions.
                return False

            if message.reply_to_message is not None and message.reply_to_message.from_user is not None:
                if message.reply_to_message.from_user.id == context.bot.id:
                    return False

        except Exception as e:
            self.logger.error("Exception: %s", e)
            return False  # TODO: Why False?

        return True

    async def start_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", self.get_username(update))

        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user = update.message.from_user
        self.update_last_interaction(user.id)

        reply_text = "Hi! I'm <b>ChatGPT</b> bot implemented with OpenAI API 🤖\n\n"
        reply_text += self.resources.get_help_message(user.language_code)

        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)
        await self.show_chat_modes_handle(update, context)

    async def help_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", self.get_username(update))

        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("Message has no sender (from_user)")
            return

        user = update.message.from_user
        self.update_last_interaction(user.id)
        help_message = self.resources.get_help_message(user.language_code)

        await update.message.reply_text(help_message, parse_mode=ParseMode.HTML)

    async def help_group_chat_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user = update.message.from_user

        self.update_last_interaction(user.id)

        help_message = self.resources.get_help_group_chat_message(
            user.language_code)
        text = help_message.format(bot_username="@" + context.bot.username)

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        await update.message.reply_video(self.config.help_group_chat_video_path)

    async def retry_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user = update.message.from_user
        self.update_last_interaction(user.id)
        dialog_messages = self.db.get_dialog_messages(user.id)

        if len(dialog_messages) == 0:
            await update.message.reply_text("No message to retry 🤷‍♂️")
            return

        last_dialog_message = dialog_messages.pop()
        # last message was removed from the context
        self.db.set_dialog_messages(user.id, dialog_messages, dialog_id=None)
        await self.message_handle(update, context, message=last_dialog_message["user"], use_new_dialog_timeout=False)

    async def message_handle(
            self,
            update: Update,
            context: CallbackContext,
            message: Optional[str] = None,
            use_new_dialog_timeout=True):
        if await self.should_ignore(update, context):
            self.logger.debug("Ignoring the update")
            return

        if update.edited_message is not None:
            self.logger.warning("Ignoring edited messages")
            await self.edited_message_handle(update, context)
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user field)")
            return

        message_text = message or update.message.text or ""

        self.logger.debug("%s sent \"%s\"",
                          update.message.from_user.username, message_text)

        # remove bot mention (in group chats)
        if update.message.chat.type != "private":
            message_text = message_text.replace(
                "@" + context.bot.username, "").strip()

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message not answered yet")
            return

        user_id = update.message.from_user.id
        chat_mode = self.db.get_current_chat_mode(user_id)

        if chat_mode == "artist":
            self.logger.debug(
                "Current chat mode is Artist, will generate image")
            await self.generate_image_handle(update, context, message=message)
            return

        async def message_handle_fn():
            if update.message is None:
                self.logger.error("The update has no message")
                return

            # new dialog timeout
            if use_new_dialog_timeout:
                last_interaction = self.db.get_last_interaction(user_id)
                has_dialog_messages = len(
                    self.db.get_dialog_messages(user_id)) > 0
                seconds_since_last_interaction = (datetime.now(
                    timezone.utc) - last_interaction).seconds
                if seconds_since_last_interaction > self.config.new_dialog_timeout and has_dialog_messages:
                    self.db.start_new_dialog(user_id)
                    chat_mode_name = self.config.chat_modes[chat_mode]["name"]
                    reply_text = f"Starting new dialog due to timeout (<b>{chat_mode_name}</b> mode) ✅"
                    await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML)

            self.update_last_interaction(user_id)

            # in case of CancelledError
            n_input_tokens, n_output_tokens = 0, 0
            current_model = self.db.get_current_model(user_id)

            try:
                # send placeholder message to user
                placeholder_message = await update.message.reply_text("...")

                # send typing action
                await update.message.chat.send_action(action="typing")

                if message_text is None or len(message_text) == 0:
                    await update.message.reply_text("🥲 You sent <b>empty message</b>. Please, try again!", parse_mode=ParseMode.HTML)
                    return

                dialog_messages = self.db.get_dialog_messages(
                    user_id, dialog_id=None)
                parse_mode = {
                    "html": ParseMode.HTML,
                    "markdown": ParseMode.MARKDOWN
                }[self.config.chat_modes[chat_mode]["parse_mode"]]

                answer = ""
                n_first_dialog_messages_removed = 0
                chatgpt_instance = openai_utils.ChatGPT(
                    self.config, model=current_model)

                if self.config.enable_message_streaming:
                    gen = chatgpt_instance.send_message_stream(
                        message_text,
                        dialog_messages=dialog_messages,
                        chat_mode=chat_mode
                    )

                else:
                    answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed = await chatgpt_instance.send_message(
                        message_text,
                        dialog_messages=dialog_messages,
                        chat_mode=chat_mode
                    )

                    async def fake_gen():
                        yield "finished", answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed

                    gen = fake_gen()

                previous_answer = ""

                async for gen_item in gen:
                    status, answer, (n_input_tokens,
                                     n_output_tokens), n_first_dialog_messages_removed = gen_item

                    answer = answer[:TELEGRAM_MESSAGE_LENGTH_LIMIT]

                    # update only when 100 new symbols are ready
                    if abs(len(answer) - len(previous_answer)) < 100 and status != "finished":
                        continue

                    try:
                        await context.bot.edit_message_text(
                            answer,
                            chat_id=placeholder_message.chat_id,
                            message_id=placeholder_message.message_id,
                            parse_mode=parse_mode
                        )

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
                    "date": datetime.now(timezone.utc)
                }

                current_dialog_messages = self.db.get_dialog_messages(user_id)
                new_dialog_messages = current_dialog_messages + \
                    [new_dialog_message]
                self.db.set_dialog_messages(user_id, new_dialog_messages)

                self.db.set_n_used_tokens(user_id, current_model,
                                          n_input_tokens, n_output_tokens)

            except asyncio.CancelledError:
                # note: intermediate token updates only work when enable_message_streaming=True (config.yml)
                self.db.set_n_used_tokens(user_id, current_model,
                                          n_input_tokens, n_output_tokens)
                raise

            except Exception as e:
                error_text = f"Something went wrong during completion. Reason: {e}"
                self.logger.error(error_text)
                await update.message.reply_text(error_text)
                return

            # send message if some messages were removed from the context

            if n_first_dialog_messages_removed is None:
                self.logger.error("n_first_dialog_messages_removed is None")
                return

            if n_first_dialog_messages_removed > 0:
                if n_first_dialog_messages_removed == 1:
                    text = dedent("""\
                        ✍️ <i>Note:</i> Your current dialog is too long, 
                        so your <b>first message</b> was removed from the context.\n
                        Send /new command to start a new dialog.""")

                else:
                    text = dedent("""\
                        ✍️ <i>Note:</i> Your current dialog is too long, 
                        so <b>{n_first_dialog_messages_removed} first messages</b>
                        were removed from the context.\n Send /new command to start a new dialog""")

                await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        async with self.user_semaphores[user_id]:
            task = asyncio.create_task(message_handle_fn())
            self.user_tasks[user_id] = task

            try:
                await task
            except asyncio.CancelledError:
                await update.message.reply_text("✅ Canceled", parse_mode=ParseMode.HTML)
            else:
                pass
            finally:
                if user_id in self.user_tasks:
                    del self.user_tasks[user_id]

    async def is_previous_message_not_answered_yet_for_update(self, update: Update):
        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        return await self.is_previous_message_not_answered_yet(
            message=update.message,
            user_id=update.message.from_user.id
        )

    async def is_previous_message_not_answered_yet_for_callback(self, callback_query: CallbackQuery):
        await self.register_user_if_not_registered_for_callback(callback_query)

        if callback_query.message is None or callback_query.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        return await self.is_previous_message_not_answered_yet(
            message=callback_query.message,
            user_id=callback_query.from_user.id
        )

    async def is_previous_message_not_answered_yet(self, message: Message, user_id: int):
        if self.user_semaphores[user_id].locked():
            text = "⏳ Please <b>wait</b> for a reply to the previous message\n"
            text += "Or you can /cancel it"

            await message.reply_text(
                text,
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

            return True

        return False

    async def voice_message_handle(self, update: Update, context: CallbackContext):
        if await self.should_ignore(update, context):
            self.logger.debug("Ignoring the update")
            return

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            self.logger.debug("The previous message not answered yet")
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

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
                transcribed_text = await openai_utils.transcribe_audio(f)

                if transcribed_text is None:
                    transcribed_text = ""

        text = f"🎤: <i>{transcribed_text}</i>"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        self.logger.debug("%s sent voice \"%s\"",
                          update.message.from_user.username, text)

        current_n_transcribed_seconds = self.db.get_n_transcribed_seconds(
            user_id)
        new_n_transcribed_seconds = current_n_transcribed_seconds + voice.duration
        self.db.set_n_transcribed_seconds(user_id, new_n_transcribed_seconds)

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

        await update.message.chat.send_action(action="upload_photo")

        message_text = message or update.message.text
        if message_text is None or len(message_text) == 0:
            self.logger.error("Expected non-empty message")
            return

        try:
            image_urls = await openai_utils.generate_images(message_text, n_images=self.config.return_n_generated_images)

        except openai.error.InvalidRequestError as e:
            if str(e).startswith("Your request was rejected as a result of our safety system"):
                text = "🥲 Your request <b>doesn't comply</b> with OpenAI's usage policies.\nWhat did you write there, huh?"
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                return

            raise

        n_generated_images = self.db.get_n_generated_images(user_id)
        new_n_generated_images = n_generated_images + \
            self.config.return_n_generated_images
        self.db.set_n_generated_images(user_id, new_n_generated_images)

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
        await update.message.reply_text("Starting new dialog ✅")

        chat_mode = self.db.get_current_chat_mode(user_id)
        welcome_message = self.config.chat_modes[chat_mode]["welcome_message"]
        await update.message.reply_text(f"{welcome_message}", parse_mode=ParseMode.HTML)

    async def cancel_handle(self, update: Update, context: CallbackContext):
        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        if user_id in self.user_tasks:
            task = self.user_tasks[user_id]
            task.cancel()
        else:
            await update.message.reply_text("<i>Nothing to cancel...</i>", parse_mode=ParseMode.HTML)

    def get_chat_mode_menu(self, page_index: int):
        n_chat_modes_per_page = self.config.n_chat_modes_per_page
        text = f"Select <b>chat mode</b> ({len(self.config.chat_modes)} modes available):"

        # buttons
        chat_mode_keys = list(self.config.chat_modes.keys())
        page_chat_mode_keys = chat_mode_keys[page_index *
                                             n_chat_modes_per_page:(page_index + 1) * n_chat_modes_per_page]

        keyboard = []
        for chat_mode_key in page_chat_mode_keys:
            name = self.config.chat_modes[chat_mode_key]["name"]
            keyboard.append([InlineKeyboardButton(
                name, callback_data=f"set_chat_mode|{chat_mode_key}")])

        # pagination
        if len(chat_mode_keys) > n_chat_modes_per_page:
            is_first_page = (page_index == 0)
            is_last_page = ((page_index + 1) *
                            n_chat_modes_per_page >= len(chat_mode_keys))

            if is_first_page:
                keyboard.append([
                    InlineKeyboardButton(
                        "»", callback_data=f"show_chat_modes|{page_index + 1}")
                ])
            elif is_last_page:
                keyboard.append([
                    InlineKeyboardButton(
                        "«", callback_data=f"show_chat_modes|{page_index - 1}"),
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        "«", callback_data=f"show_chat_modes|{page_index - 1}"),
                    InlineKeyboardButton(
                        "»", callback_data=f"show_chat_modes|{page_index + 1}")
                ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        return text, reply_markup

    async def show_chat_modes_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", self.get_username(update))

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
            return

        if update.message is None or update.message.from_user is None:
            self.logger.error("The message has no sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        text, reply_markup = self.get_chat_mode_menu(0)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

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
            self.logger.debug("The previous message not answered yet")
            return

        # update_last_interaction(user_id)

        await callback_query.answer()

        if callback_query.data is None:
            self.logger.error("Callback Query Data is None")
            return

        page_index = int(callback_query.data.split("|")[1])
        if page_index < 0:
            self.logger.error("Invalid page index: %d", page_index)
            return

        text, reply_markup = self.get_chat_mode_menu(page_index)

        try:
            await callback_query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )

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

        self.update_last_interaction(user.id)
        self.db.set_current_chat_mode(user.id, chat_mode)
        self.db.start_new_dialog(user.id)

        await context.bot.send_message(
            callback_query.message.chat.id,
            f"{config.chat_modes[chat_mode]['welcome_message']}",
            parse_mode=ParseMode.HTML
        )

    def get_settings_menu(self, user_id: int):
        current_model = self.db.get_current_model(user_id)
        text = self.config.models["info"][current_model]["description"]

        text += "\n\n"
        score_dict = self.config.models["info"][current_model]["scores"]
        for score_key, score_value in score_dict.items():
            text += "🟢" * score_value + "⚪️" * \
                (5 - score_value) + f" – {score_key}\n\n"

        text += "\nSelect <b>model</b>:"

        # buttons to choose models
        buttons = []
        for model_key in self.config.models["available_text_models"]:
            title = self.config.models["info"][model_key]["name"]
            if model_key == current_model:
                title = "✅ " + title

            buttons.append(
                InlineKeyboardButton(
                    title, callback_data=f"set_settings|{model_key}")
            )
        reply_markup = InlineKeyboardMarkup([buttons])

        return text, reply_markup

    async def settings_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", self.get_username(update))

        await self.register_user_if_not_registered_for_update(update)

        if await self.is_previous_message_not_answered_yet_for_update(update):
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
                parse_mode=ParseMode.HTML
            )

        except telegram.error.BadRequest as e:
            if str(e).startswith("Message is not modified"):
                pass

    async def show_balance_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", self.get_username(update))

        await self.register_user_if_not_registered_for_update(update)

        if update.message is None or update.message.from_user is None:
            self.logger.error("Update has no message or sender (from_user)")
            return

        user_id = update.message.from_user.id
        self.update_last_interaction(user_id)

        # count total usage statistics
        total_n_spent_dollars = 0
        total_n_used_tokens = 0

        n_used_tokens_dict = self.db.get_n_used_tokens(user_id)
        n_generated_images = self.db.get_n_generated_images(user_id)
        n_transcribed_seconds = self.db.get_n_transcribed_seconds(user_id)

        details_text = "🏷️ Details:\n"
        for model_key in sorted(n_used_tokens_dict.keys()):
            n_input_tokens, n_output_tokens = n_used_tokens_dict[model_key][
                "n_input_tokens"], n_used_tokens_dict[model_key]["n_output_tokens"]
            total_n_used_tokens += n_input_tokens + n_output_tokens

            n_input_spent_dollars = self.config.models["info"][model_key]["price_per_1000_input_tokens"] * (
                n_input_tokens / 1000)
            n_output_spent_dollars = self.config.models["info"][model_key]["price_per_1000_output_tokens"] * (
                n_output_tokens / 1000)
            total_n_spent_dollars += n_input_spent_dollars + n_output_spent_dollars

            details_text += f"- {model_key}: <b>{total_n_spent_dollars:.03f}$</b> / <b>{total_n_used_tokens} tokens</b>\n"

        # image generation
        image_generation_n_spent_dollars = self.config.models["info"][
            "dalle-2"]["price_per_1_image"] * n_generated_images
        if n_generated_images != 0:
            details_text += f"- DALL·E 2 (image generation): <b>{image_generation_n_spent_dollars:.03f}$</b> / <b>{n_generated_images} generated images</b>\n"

        total_n_spent_dollars += image_generation_n_spent_dollars

        # voice recognition
        voice_recognition_n_spent_dollars = self.config.models["info"]["whisper"]["price_per_1_min"] * (
            n_transcribed_seconds / 60)
        if n_transcribed_seconds != 0:
            details_text += f"- Whisper (voice recognition): <b>{voice_recognition_n_spent_dollars:.03f}$</b> / <b>{n_transcribed_seconds:.01f} seconds</b>\n"

        total_n_spent_dollars += voice_recognition_n_spent_dollars

        text = f"You spent <b>{total_n_spent_dollars:.03f}$</b>\n"
        text += f"You used <b>{total_n_used_tokens}</b> tokens\n\n"
        text += details_text

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    async def edited_message_handle(self, update: Update, context: CallbackContext):
        self.logger.debug("called for %s", self.get_username(update))

        if update.edited_message is None:
            self.logger.error("Update has no edited message")
            return

        text = "🥲 Unfortunately, message <b>editing</b> is not supported"
        await update.edited_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def error_handle(self, update: Update, context: CallbackContext) -> None:
        self.logger.error(msg="Exception while handling an update:",
                          exc_info=context.error)

        if update is None or update.effective_chat is None:
            self.logger.error("Update is None or has no effective chat")
            return

        try:
            # collect error message
            tb_list = traceback.format_exception(
                None, context.error, context.error.__traceback__)
            tb_string = "".join(tb_list)
            update_str = update.to_dict() if isinstance(update, Update) else str(update)
            message = (
                f"An exception was raised while handling an update\n"
                f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
                "</pre>\n\n"
                f"<pre>{html.escape(tb_string)}</pre>"
            )

            for message_chunk in bot_utils.split_into_chunks(message, TELEGRAM_MESSAGE_LENGTH_LIMIT):
                try:
                    await context.bot.send_message(
                        update.effective_chat.id,
                        message_chunk,
                        parse_mode=ParseMode.HTML
                    )

                except telegram.error.BadRequest:
                    # answer has invalid characters, so we send it without parse_mode
                    await context.bot.send_message(
                        update.effective_chat.id,
                        message_chunk
                    )

        except Exception as e:
            await context.bot.send_message(
                update.effective_chat.id,
                f"Exception thrown in error handler: {e}"
            )

    async def post_init(self, application: Application):
        for language in self.resources.get_supported_languages():
            await application.bot.set_my_commands([
                BotCommand(
                    "/new", self.resources.get_new_command_title(language)),
                BotCommand(
                    "/mode", self.resources.get_mode_command_title(language)),
                BotCommand(
                    "/retry", self.resources.get_retry_command_title(language)),
                BotCommand(
                    "/balance", self.resources.get_balance_command_title(language)),
                # BotCommand("/settings", resources.get_settings_command_title(language)),
                BotCommand(
                    "/help", self.resources.get_help_command_title(language)),
            ], language_code=language)

    def run(self) -> None:
        application = (
            ApplicationBuilder()
            .token(self.config.telegram_token)
            .concurrent_updates(True)
            .rate_limiter(AIORateLimiter(max_retries=5))
            .post_init(self.post_init)
            .build()
        )

        # add handlers
        user_filter = filters.ALL
        if len(self.config.allowed_telegram_usernames) > 0:
            usernames = [
                x for x in self.config.allowed_telegram_usernames if isinstance(x, str)]
            user_ids = [
                x for x in self.config.allowed_telegram_usernames if isinstance(x, int)]
            user_filter = filters.User(
                username=usernames) | filters.User(user_id=user_ids)

        application.add_handler(CommandHandler(
            "start", self.start_handle, filters=user_filter))
        application.add_handler(CommandHandler(
            "help", self.help_handle, filters=user_filter))
        application.add_handler(CommandHandler(
            "help_group_chat", self.help_group_chat_handle, filters=user_filter))

        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & user_filter, self.message_handle))
        application.add_handler(CommandHandler(
            "retry", self.retry_handle, filters=user_filter))
        application.add_handler(CommandHandler(
            "new", self.new_dialog_handle, filters=user_filter))
        application.add_handler(CommandHandler(
            "cancel", self.cancel_handle, filters=user_filter))

        application.add_handler(MessageHandler(
            filters.VOICE & user_filter, self.voice_message_handle))

        application.add_handler(CommandHandler(
            "mode", self.show_chat_modes_handle, filters=user_filter))
        application.add_handler(CallbackQueryHandler(
            self.show_chat_modes_callback_handle, pattern="^show_chat_modes"))
        application.add_handler(CallbackQueryHandler(
            self.set_chat_mode_handle, pattern="^set_chat_mode"))

        # NOTE: Model selection is temporarily disabled until access to GTP-4 is granted.
        # application.add_handler(CommandHandler("settings", settings_handle, filters=user_filter))
        # application.add_handler(CallbackQueryHandler(set_settings_handle, pattern="^set_settings"))

        application.add_handler(CommandHandler(
            "balance", self.show_balance_handle, filters=user_filter))

        application.add_error_handler(self.error_handle)

        # start the bot
        application.run_polling()


if __name__ == "__main__":
    config = BotConfig()
    bot = Bot(config)
    bot.run()
