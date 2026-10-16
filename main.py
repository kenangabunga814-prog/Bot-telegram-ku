from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

OWNER_USER_ID = 7808809047
OUTPUT_CHANNEL_ID = -1003538846439
MEDIA_GROUP_COLLECTION_DELAY_SECONDS = 1.5
MEDIA_GROUP_BUFFERS_KEY = "telegram_media_group_buffers"
MediaGroupKey = tuple[int, str]


@dataclass
class MediaGroupBuffer:
    message_ids: set[int] = field(default_factory=set)
    flush_task: asyncio.Task[None] | None = None


COPYABLE_MESSAGE_FILTER = (
    (filters.TEXT & ~filters.COMMAND)
    | filters.PHOTO
    | filters.VIDEO
    | filters.Document.ALL
    | filters.VOICE
    | filters.Sticker.ALL
)


def _is_authorized_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    return bool(
        chat
        and chat.type == "private"
        and user
        and user.id == OWNER_USER_ID
    )


async def start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if not _is_authorized_private_chat(update):
        return

    if update.effective_message:
        await update.effective_message.reply_text(
            "Halo! Kirim teks, foto, video, dokumen, voice, atau stiker "
            "untuk dikirim ke channel tujuan. Album foto/video tetap menyatu. "
            "Ketik /help untuk bantuan."
        )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if not _is_authorized_private_chat(update):
        return

    if update.effective_message:
        await update.effective_message.reply_text(
            "Perintah yang tersedia:\n"
            "/start — mulai menggunakan bot\n"
            "/help — tampilkan bantuan\n\n"
            "Pesan teks, foto, video, dokumen, voice, dan stiker dikirim ke "
            "channel tujuan tanpa label forward. Album dikirim sebagai satu "
            "album."
        )


def _media_group_buffers(
    application: Application,
) -> dict[MediaGroupKey, MediaGroupBuffer]:
    return application.bot_data.setdefault(MEDIA_GROUP_BUFFERS_KEY, {})


async def _copy_media_group_after_delay(
    application: Application, key: MediaGroupKey
) -> None:
    await asyncio.sleep(MEDIA_GROUP_COLLECTION_DELAY_SECONDS)

    buffer = _media_group_buffers(application).pop(key, None)
    if not buffer or not buffer.message_ids:
        return

    source_chat_id, _ = key
    await application.bot.copy_messages(
        chat_id=OUTPUT_CHANNEL_ID,
        from_chat_id=source_chat_id,
        message_ids=sorted(buffer.message_ids),
    )


async def copy_without_forward_label(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not _is_authorized_private_chat(update):
        return

    if message.media_group_id:
        key = (chat.id, message.media_group_id)
        buffers = _media_group_buffers(context.application)
        buffer = buffers.get(key)
        if buffer is None:
            buffer = MediaGroupBuffer()
            buffers[key] = buffer

        buffer.message_ids.add(message.message_id)

        if buffer.flush_task and not buffer.flush_task.done():
            buffer.flush_task.cancel()
        buffer.flush_task = context.application.create_task(
            _copy_media_group_after_delay(context.application, key),
            update=update,
            name=f"copy-media-group-{chat.id}-{message.media_group_id}",
        )
        return

    await context.bot.copy_message(
        chat_id=OUTPUT_CHANNEL_ID,
        from_chat_id=chat.id,
        message_id=message.message_id,
    )


def create_application(token: str) -> Application:
    """Build the Telegram application without starting network polling."""
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(COPYABLE_MESSAGE_FILTER, copy_without_forward_label),
        group=1,
    )
    return application


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN belum diatur. Tambahkan sebagai Replit Secret."
        )

    logger.info("Bot Telegram berjalan dengan long polling.")
    create_application(token).run_polling()


if __name__ == "__main__":
    main()
