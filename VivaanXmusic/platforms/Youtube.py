import asyncio
import os
import re
from typing import Union
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.future import VideosSearch
import aiohttp

# API_URL and API_KEY
API_URL = "https://teaminflex.xyz"  # Change to your API server URL
API_KEY = "INFLEX57434628D"

DOWNLOAD_DIR = "downloads"

def time_to_seconds(time):
    stringt = str(time)
    return sum(int(x) * 60 ** i for i, x in enumerate(reversed(stringt.split(":"))))


# ==============================================
# 🎵 AUDIO DOWNLOAD (Safe JSON + 200 Retry)
# ==============================================
async def download_song(link: str) -> str:
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    logger = LOGGER("InflexMusic/platforms/Youtube.py")
    logger.info(f"🎵 [AUDIO] Starting download process for ID: {video_id}")

    if not video_id or len(video_id) < 3:
        return

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.webm")

    if os.path.exists(file_path):
        logger.info(f"🎵 [LOCAL] Found existing audio for ID {video_id}")
        return file_path

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"url": video_id, "type": "audio"}
            headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}

            async def safe_json(resp):
                try:
                    return await resp.json(content_type=None)
                except:
                    txt = await resp.text()
                    logger.error(f"[AUDIO] Invalid JSON → {txt}")
                    return None

            # Step 1 → First request
            async with session.post(f"{API_URL}/download", json=payload, headers=headers) as response:
                data = await safe_json(response)

            # 🚫 STOP if API explicitly returns error
            if data and data.get("status") == "error":
                logger.error(f"[AUDIO] API ERROR → {data}")
                return

            retries = 200

            if not data or not data.get("download_url"):
                logger.warning("[AUDIO] File not ready / JSON missing → retrying...")

                for i in range(retries):
                    await asyncio.sleep(8)
                    async with session.post(f"{API_URL}/download", json=payload, headers=headers) as response:
                        data = await safe_json(response)

                    # 🚫 STOP retrying if error appears anytime
                    if data and data.get("status") == "error":
                        logger.error(f"[AUDIO] API ERROR during retry → {data}")
                        return

                    if data and data.get("status") == "success" and data.get("download_url"):
                        logger.info(f"[AUDIO] Got URL after retry #{i+1}")
                        break

                    logger.warning(f"[AUDIO] Retry {i+1}/{retries} → still not ready")

            if not data or not data.get("download_url"):
                logger.error(f"[AUDIO] FAILED after all retries → {data}")
                return

            download_link = API_URL + data["download_url"]

            async with session.get(download_link) as file_response:
                if file_response.status != 200:
                    logger.error(f"[AUDIO] Download failed → {file_response.status}")
                    return

                with open(file_path, "wb") as f:
                    async for chunk in file_response.content.iter_chunked(8192):
                        f.write(chunk)

        logger.info(f"🎵 [API] Audio download completed for {video_id}")
        return file_path

    except Exception as e:
        logger.error(f"[AUDIO] Exception: {e}")
        return


# ==============================================
# 🎥 VIDEO DOWNLOAD (Safe JSON + 100 Retry)
# ==============================================
async def download_video(link: str) -> str:
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    logger = LOGGER("InflexMusic/platforms/Youtube.py")
    logger.info(f"🎥 [VIDEO] Starting download process for ID: {video_id}")

    if not video_id or len(video_id) < 3:
        return

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mkv")

    if os.path.exists(file_path):
        logger.info(f"🎥 [LOCAL] Found existing video for ID {video_id}")
        return file_path

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"url": video_id, "type": "video"}
            headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}

            async def safe_json(resp):
                try:
                    return await resp.json(content_type=None)
                except:
                    txt = await resp.text()
                    logger.error(f"[VIDEO] Invalid JSON → {txt}")
                    return None

            # Step 1 → First request
            async with session.post(f"{API_URL}/download", json=payload, headers=headers) as response:
                data = await safe_json(response)

            # 🚫 STOP if API explicitly returns error
            if data and data.get("status") == "error":
                logger.error(f"[VIDEO] API ERROR → {data}")
                return

            retries = 100

            if not data or not data.get("download_url"):
                logger.warning("[VIDEO] File not ready / JSON missing → retrying...")

                for i in range(retries):
                    await asyncio.sleep(20)
                    async with session.post(f"{API_URL}/download", json=payload, headers=headers) as response:
                        data = await safe_json(response)

                    # 🚫 STOP retrying if error appears anytime
                    if data and data.get("status") == "error":
                        logger.error(f"[VIDEO] API ERROR during retry → {data}")
                        return

                    if data and data.get("status") == "success" and data.get("download_url"):
                        logger.info(f"[VIDEO] Got URL after retry #{i+1}")
                        break

                    logger.warning(f"[VIDEO] Retry {i+1}/{retries} → still not ready")

            if not data or not data.get("download_url"):
                logger.error(f"[VIDEO] FAILED after all retries → {data}")
                return

            download_link = API_URL + data["download_url"]

            async with session.get(download_link) as file_response:
                if file_response.status != 200:
                    logger.error(f"[VIDEO] Download failed → {file_response.status}")
                    return

                with open(file_path, "wb") as f:
                    async for chunk in file_response.content.iter_chunked(8192):
                        f.write(chunk)

        logger.info(f"🎥 [API] Video download completed for {video_id}")
        return file_path

    except Exception as e:
        logger.error(f"[VIDEO] Exception: {e}")
        return


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        return text[entity.offset: entity.offset + entity.length]
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            duration_sec = int(time_to_seconds(duration_min)) if duration_min else 0
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["title"]

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["duration"]

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["thumbnails"][0]["url"].split("?")[0]

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return 1, downloaded_file
            return 0, "Video download failed"
        except Exception as e:
            return 0, f"Video download error: {e}"

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            plist = await Playlist.get(link)
        except Exception:
            return []
        videos = plist.get("videos") or []
        ids = []
        for data in videos[:limit]:
            if not data:
                continue
            vid = data.get("id")
            if not vid:
                continue
            ids.append(vid)
        return ids

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    if "dash" not in str(format["format"]).lower():
                        formats_available.append(
                            {
                                "format": format["format"],
                                "filesize": format.get("filesize"),
                                "format_id": format["format_id"],
                                "ext": format["ext"],
                                "format_note": format["format_note"],
                                "yturl": link,
                            }
                        )
                except Exception:
                    continue
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        a = VideosSearch(link, limit=10)
        result = (await a.next()).get("result")
        title = result[query_type]["title"]
        duration_min = result[query_type]["duration"]
        vidid = result[query_type]["id"]
        thumbnail = result[query_type]["thumbnails"][0]["url"].split("?")[0]
        return title, duration_min, thumbnail, vidid

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link
        try:
            if video:
                downloaded_file = await download_video(link)
            else:
                downloaded_file = await download_song(link)
            if downloaded_file:
                return downloaded_file, True
            return None, False
        except Exception:
            return None, False


YouTube = YouTubeAPI()
    
