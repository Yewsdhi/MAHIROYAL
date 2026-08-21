import asyncio
import os
import re
from typing import Union

import aiohttp
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.future import VideosSearch, Playlist


# ==========================================================
# CONFIG
# ==========================================================

API_URL = os.environ.get(
    "SHRUTI_API_URL",
    "https://api.shrutibots.site"
)

API_KEY = os.environ.get(
    "SHRUTI_API_KEY",
    "ShrutiBotsAlSpfeG7JItQmuoxCqKd"
)

DOWNLOAD_DIR = "downloads"

# FIX: cookie_txt_file was missing
cookie_txt_file = os.environ.get(
    "COOKIE_TXT_FILE",
    "cookies.txt"
)


# ==========================================================
# HELPERS
# ==========================================================

def time_to_seconds(time):
    if not time:
        return 0

    try:
        stringt = str(time)
        return sum(
            int(x) * 60 ** i
            for i, x in enumerate(reversed(stringt.split(":")))
        )
    except Exception:
        return 0


def get_cookie_file():
    """
    Return cookies file only if it exists.
    """
    try:
        if cookie_txt_file and os.path.isfile(cookie_txt_file):
            return cookie_txt_file
    except Exception:
        pass

    return None


def extract_video_id(link: str):
    if not link:
        return None

    link = str(link).strip()

    if "youtu.be/" in link:
        video_id = link.split("youtu.be/", 1)[1]
        video_id = video_id.split("?", 1)[0]
        video_id = video_id.split("&", 1)[0]
        return video_id

    if "v=" in link:
        video_id = link.split("v=", 1)[1]
        video_id = video_id.split("&", 1)[0]
        return video_id

    return link


# ==========================================================
# DOWNLOAD SONG
# ==========================================================

async def download_song(link: str) -> Union[str, None]:
    video_id = extract_video_id(link)

    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    file_path = os.path.join(
        DOWNLOAD_DIR,
        f"{video_id}.mp3"
    )

    if (
        os.path.exists(file_path)
        and os.path.getsize(file_path) > 0
    ):
        return file_path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/download",
                params={
                    "url": video_id,
                    "type": "audio",
                    "api_key": API_KEY,
                },
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:

                if resp.status != 200:
                    return None

                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        if chunk:
                            f.write(chunk)

        if (
            os.path.exists(file_path)
            and os.path.getsize(file_path) > 0
        ):
            return file_path

        return None

    except Exception:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

        return None


# ==========================================================
# DOWNLOAD VIDEO
# ==========================================================

async def download_video(link: str) -> Union[str, None]:
    video_id = extract_video_id(link)

    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    file_path = os.path.join(
        DOWNLOAD_DIR,
        f"{video_id}.mp4"
    )

    if (
        os.path.exists(file_path)
        and os.path.getsize(file_path) > 0
    ):
        return file_path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/download",
                params={
                    "url": video_id,
                    "type": "video",
                    "api_key": API_KEY,
                },
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:

                if resp.status != 200:
                    return None

                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        if chunk:
                            f.write(chunk)

        if (
            os.path.exists(file_path)
            and os.path.getsize(file_path) > 0
        ):
            return file_path

        return None

    except Exception:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

        return None


# ==========================================================
# YOUTUBE API
# ==========================================================

class YouTubeAPI:

    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="

        self.reg = re.compile(
            r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        )

    # ======================================================
    # EXISTS
    # ======================================================

    async def exists(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):
        if not link:
            return False

        if videoid:
            link = self.base + str(link)

        return bool(
            re.search(
                self.regex,
                str(link)
            )
        )

    # ======================================================
    # URL
    # ======================================================

    async def url(
        self,
        message_1: Message
    ) -> Union[str, None]:

        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(
                message_1.reply_to_message
            )

        for message in messages:

            if message.entities:

                for entity in message.entities:

                    if entity.type == MessageEntityType.URL:

                        text = (
                            message.text
                            or message.caption
                            or ""
                        )

                        return text[
                            entity.offset:
                            entity.offset + entity.length
                        ]

                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url

            if message.caption_entities:

                for entity in message.caption_entities:

                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url

        return None

    # ======================================================
    # DETAILS
    # ======================================================

    async def details(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        results = VideosSearch(
            link,
            limit=1
        )

        data = await results.next()
        result_list = data.get("result", [])

        if not result_list:
            return (
                None,
                None,
                0,
                None,
                None
            )

        result = result_list[0]

        title = result.get("title")
        duration_min = result.get("duration")

        thumbnail_list = result.get("thumbnails") or []

        thumbnail = (
            thumbnail_list[0]["url"].split("?")[0]
            if thumbnail_list
            else None
        )

        vidid = result.get("id")

        duration_sec = time_to_seconds(
            duration_min
        )

        return (
            title,
            duration_min,
            duration_sec,
            thumbnail,
            vidid
        )

    # ======================================================
    # TITLE
    # ======================================================

    async def title(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        results = VideosSearch(
            link,
            limit=1
        )

        data = await results.next()
        result_list = data.get("result", [])

        if not result_list:
            return None

        return result_list[0].get("title")

    # ======================================================
    # DURATION
    # ======================================================

    async def duration(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        results = VideosSearch(
            link,
            limit=1
        )

        data = await results.next()
        result_list = data.get("result", [])

        if not result_list:
            return None

        return result_list[0].get("duration")

    # ======================================================
    # THUMBNAIL
    # ======================================================

    async def thumbnail(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        results = VideosSearch(
            link,
            limit=1
        )

        data = await results.next()
        result_list = data.get("result", [])

        if not result_list:
            return None

        thumbnails = result_list[0].get(
            "thumbnails"
        ) or []

        if not thumbnails:
            return None

        return thumbnails[0]["url"].split("?")[0]

    # ======================================================
    # VIDEO
    # ======================================================

    async def video(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        try:
            downloaded_file = await download_video(
                link
            )

            if downloaded_file:
                return 1, downloaded_file

            return 0, "Video download failed"

        except Exception as e:
            return 0, f"Video download error: {e}"

    # ======================================================
    # PLAYLIST
    # ======================================================

    async def playlist(
        self,
        link,
        limit,
        user_id,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.listbase + str(link)

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

    # ======================================================
    # TRACK
    # ======================================================

    async def track(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        results = VideosSearch(
            link,
            limit=1
        )

        data = await results.next()
        result_list = data.get("result", [])

        if not result_list:
            return None, None

        result = result_list[0]

        title = result.get("title")
        duration_min = result.get("duration")
        vidid = result.get("id")
        yturl = result.get("link")

        thumbnails = result.get(
            "thumbnails"
        ) or []

        thumbnail = (
            thumbnails[0]["url"].split("?")[0]
            if thumbnails
            else None
        )

        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }

        return track_details, vidid

    # ======================================================
    # FORMATS
    # ======================================================

    async def formats(
        self,
        link: str,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        ytdl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

        # FIX: use cookies only when file exists
        cookies = get_cookie_file()

        if cookies:
            ytdl_opts["cookiefile"] = cookies

        try:
            ydl = yt_dlp.YoutubeDL(
                ytdl_opts
            )

            with ydl:

                formats_available = []

                r = ydl.extract_info(
                    link,
                    download=False
                )

                for fmt in r.get("formats", []):

                    try:

                        if "dash" in str(
                            fmt.get("format", "")
                        ).lower():
                            continue

                        formats_available.append(
                            {
                                "format": fmt.get("format"),
                                "filesize": fmt.get("filesize"),
                                "format_id": fmt.get("format_id"),
                                "ext": fmt.get("ext"),
                                "format_note": fmt.get("format_note"),
                                "yturl": link,
                            }
                        )

                    except Exception:
                        continue

                return formats_available, link

        except Exception:
            return [], link

    # ======================================================
    # SLIDER
    # ======================================================

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None
    ):

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&")[0]

        search = VideosSearch(
            link,
            limit=10
        )

        data = await search.next()

        result = data.get("result") or []

        if not result:
            return (
                None,
                None,
                None,
                None
            )

        if query_type >= len(result):
            query_type = 0

        selected = result[query_type]

        title = selected.get("title")
        duration_min = selected.get("duration")
        vidid = selected.get("id")

        thumbnails = selected.get(
            "thumbnails"
        ) or []

        thumbnail = (
            thumbnails[0]["url"].split("?")[0]
            if thumbnails
            else None
        )

        return (
            title,
            duration_min,
            thumbnail,
            vidid
        )

    # ======================================================
    # DOWNLOAD
    # ======================================================

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
    ):

        if videoid:
            link = self.base + str(link)

        try:

            if video:
                downloaded_file = await download_video(
                    link
                )

            else:
                downloaded_file = await download_song(
                    link
                )

            if downloaded_file:
                return downloaded_file, True

            return None, False

        except Exception:
            return None, False


# ==========================================================
# GLOBAL YOUTUBE OBJECT
# ==========================================================

YouTube = YouTubeAPI()
