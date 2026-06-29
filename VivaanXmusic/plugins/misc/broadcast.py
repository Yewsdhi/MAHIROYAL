import asyncio
import os
import time
from pyrogram import filters
from pyrogram.enums import ChatMembersFilter
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from VivaanXmusic import app
from VivaanXmusic.misc import SUDOERS
from VivaanXmusic.utils.database import (
    get_active_chats,
    get_authuser_names,
    get_client,
    get_served_chats,
    get_served_users,
)
from VivaanXmusic.utils.decorators.language import language
from VivaanXmusic.utils.formatters import alpha_to_int
from config import adminlist, CACHE_DURATION, CACHE_SLEEP, file_cache, autoclean

IS_BROADCASTING = False


def parse_flags(text: str):
    return {
        "pin": "-pin" in text,
        "pinloud": "-pinloud" in text,
        "nobot": "-nobot" in text,
        "user": "-user" in text,
        "assistant": "-assistant" in text
    }


async def broadcast_to_targets(client, targets, query, y=None, x=None, pin=False, pinloud=False):
    sent = 0
    pinned = 0
    footer = "\n\n"
    for target_id in targets:
        try:
            if x and y:
                m = await client.forward_messages(target_id, y, x)
            else:
                m = await client.send_message(target_id, text=query + footer)

            if pin:
                try:
                    await m.pin(disable_notification=True)
                    pinned += 1
                except:
                    pass
            elif pinloud:
                try:
                    await m.pin(disable_notification=False)
                    pinned += 1
                except:
                    pass
            sent += 1
            await asyncio.sleep(0.2)

        except FloodWait as fw:
            if fw.value > 200:
                continue
            await asyncio.sleep(fw.value)
        except:
            continue
    return sent, pinned


@app.on_message(filters.command("broadcast") & SUDOERS)
@language
async def broadcast_message(client, message: Message, _):
    global IS_BROADCASTING
    if IS_BROADCASTING:
        return await message.reply_text("A broadcast is already running. Please wait.")

    flags = parse_flags(message.text)
    query = None
    y = x = None

    if message.reply_to_message:
        y = message.chat.id
        x = message.reply_to_message.id
    else:
        if len(message.command) < 2:
            return await message.reply_text(_["broad_2"])
        query = message.text.split(None, 1)[1]
        for flag in flags:
            query = query.replace(f"-{flag}", "").strip()
        if not query:
            return await message.reply_text(_["broad_8"])

    IS_BROADCASTING = True
    await message.reply_text(_["broad_1"])

    # Bot Broadcast
    if not flags["nobot"]:
        schats = await get_served_chats()
        chat_ids = [int(chat["chat_id"]) for chat in schats]
        sent, pinned = await broadcast_to_targets(
            client, chat_ids, query, y, x, flags["pin"], flags["pinloud"]
        )
        try:
            await message.reply_text(_["broad_3"].format(sent, pinned))
        except:
            pass

    # User Broadcast
    if flags["user"]:
        susers = await get_served_users()
        user_ids = [int(user["user_id"]) for user in susers]
        sent, _ = await broadcast_to_targets(client, user_ids, query, y, x)
        try:
            await message.reply_text(_["broad_4"].format(sent))
        except:
            pass

    # Assistant Broadcast
    if flags["assistant"]:
        from VivaanXmusic.core.userbot import assistants
        status_msg = await message.reply_text(_["broad_5"])
        result_text = _["broad_6"]
        footer = "\n\n🔊 Broadcasted by VivaanXmusic"

        for num in assistants:
            sent = 0
            try:
                user_client = await get_client(num)
                async for dialog in user_client.get_dialogs():
                    try:
                        if x and y:
                            await user_client.forward_messages(dialog.chat.id, y, x)
                        else:
                            await user_client.send_message(dialog.chat.id, text=query + footer)
                        sent += 1
                        await asyncio.sleep(3)
                    except FloodWait as fw:
                        if fw.value > 200:
                            continue
                        await asyncio.sleep(fw.value)
                    except:
                        continue
                result_text += _["broad_7"].format(num, sent)
            except:
                continue
        try:
            await status_msg.edit_text(result_text)
        except:
            pass

    IS_BROADCASTING = False


async def auto_clean():
    while not await asyncio.sleep(10):
        try:
            served_chats = await get_active_chats()
            for chat_id in served_chats:
                if chat_id not in adminlist:
                    adminlist[chat_id] = []
                    async for user in app.get_chat_members(
                        chat_id, filter=ChatMembersFilter.ADMINISTRATORS
                    ):
                        if user.privileges.can_manage_video_chats:
                            adminlist[chat_id].append(user.user.id)
                    authusers = await get_authuser_names(chat_id)
                    for user in authusers:
                        user_id = await alpha_to_int(user)
                        adminlist[chat_id].append(user_id)
        except:
            continue


async def auto_clean_cache():
    while not await asyncio.sleep(CACHE_SLEEP):
        try:
            now = time.time()
            expired = [
                f for f, t in file_cache.items()
                if now - t > CACHE_DURATION and f not in autoclean
            ]
            for file in expired:
                try:
                    if os.path.exists(file):
                        os.remove(file)
                        file_cache.pop(file, None)
                except:
                    continue
        except:
            continue


asyncio.create_task(auto_clean())
asyncio.create_task(auto_clean_cache())
