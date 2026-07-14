import asyncio
import glob
import json
import os
import random
import re
import time
from typing import Union
from urllib.parse import parse_qs, urlparse

import requests
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from youtubesearchpython.future import Video, VideosSearch

from VivaanXmusic import LOGGER
from VivaanXmusic.utils.formatters import time_to_seconds
from config import (
    WORKER_FALLBACK_API_KEY,
    WORKER_FALLBACK_API_URL,
    YT_API_KEY,
    YTPROXY_URL as YTPROXY,
)

logger = LOGGER(__name__)

def cookie_txt_file():
    try:
        folder_path = os.path.join(os.getcwd(), "cookies")
        filename = os.path.join(folder_path, "logs.csv")
        txt_files = glob.glob(os.path.join(folder_path, "*.txt"))
        if not txt_files:
            return None
        selected_file = random.choice(txt_files)
        with open(filename, "a", encoding="utf-8") as file:
            file.write(f"Chosen File : {selected_file}\n")
        return os.path.relpath(selected_file, os.getcwd()).replace("\\", "/")
    except OSError as exc:
        logger.warning(f"Unable to use cookies file: {exc}")
        return None


def _apply_cookiefile_option(options: dict) -> dict:
    cookie_file = cookie_txt_file()
    if cookie_file:
        options["cookiefile"] = cookie_file
    return options


def _build_ytdlp_command(*extra_args: str) -> list[str]:
    command = ["yt-dlp"]
    cookie_file = cookie_txt_file()
    if cookie_file:
        command.extend(["--cookies", cookie_file])
    command.extend(extra_args)
    return command


async def check_file_size(link):
    async def get_format_info(link):
        proc = await asyncio.create_subprocess_exec(
            *_build_ytdlp_command("-J", link),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"Error:\n{stderr.decode()}")
            return None
        return json.loads(stdout.decode())

    def parse_size(formats):
        total_size = 0
        for format in formats:
            if "filesize" in format:
                total_size += format["filesize"]
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None
    
    formats = info.get("formats", [])
    if not formats:
        print("No formats found.")
        return None
    
    total_size = parse_size(formats)
    return total_size

_UNSAFE_URL_CHARS = set(";&|$\n\r`")


def _has_unsafe_url_chars(value: str) -> bool:
    if not value:
        return False
    return any(ch in value for ch in _UNSAFE_URL_CHARS)


def _safe_filename(value: str) -> str:
    if not value:
        return value
    cleaned = value.replace("/", "_").replace("\\", "_")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    return cleaned


async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self.dl_stats = {
            "total_requests": 0,
            "okflix_downloads": 0,
            "cookie_downloads": 0,
            "existing_files": 0
        }
        self._cache_ttls = {"video": 300, "search": 180}
        self._video_details_cache = {}
        self._search_cache = {}

    def _cache_get(self, cache_store, key, ttl):
        item = cache_store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            cache_store.pop(key, None)
            return None
        return value

    def _cache_set(self, cache_store, key, value, ttl):
        if value is None:
            return
        if len(cache_store) >= 256:
            oldest_key = min(cache_store, key=lambda current_key: cache_store[current_key][0])
            cache_store.pop(oldest_key, None)
        cache_store[key] = (time.monotonic() + ttl, value)

    def _prepare_lookup(self, value: str):
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", cleaned) or re.search(self.regex, cleaned):
            return self._normalize_link(cleaned)
        return cleaned

    def _normalize_duration(self, value):
        if isinstance(value, dict):
            text = value.get("text")
            if text:
                return text
            seconds = value.get("seconds")
            if seconds is None:
                return None
            seconds = int(seconds)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                return f"{hours}:{minutes:02d}:{seconds:02d}"
            return f"{minutes}:{seconds:02d}"
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return None

    def _thumbnail_from_result(self, result):
        thumbnails = result.get("thumbnails") or []
        for thumb in thumbnails:
            if isinstance(thumb, dict) and thumb.get("url"):
                return thumb["url"].split("?")[0]
        return None

    def _normalize_video_result(self, result):
        if not isinstance(result, dict):
            return None

        video_id = result.get("id") or self._extract_video_id(result.get("link"))
        title = result.get("title")
        if not video_id or not title:
            return None

        duration = self._normalize_duration(result.get("duration"))
        channel = result.get("channel")
        if not isinstance(channel, dict):
            channel = {}

        view_count = result.get("viewCount")
        if isinstance(view_count, str):
            view_count = {"text": view_count, "short": view_count}
        elif not isinstance(view_count, dict):
            view_count = {"text": None, "short": None}

        return {
            **result,
            "id": video_id,
            "title": title,
            "link": result.get("link") or f"{self.base}{video_id}",
            "duration": duration,
            "thumbnails": result.get("thumbnails") or [],
            "channel": {
                "name": channel.get("name"),
                "id": channel.get("id"),
                "link": channel.get("link"),
            },
            "viewCount": view_count,
        }

    def _build_browser_headers(self):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.youtube.com/",
        }

    def _build_primary_api_headers(self):
        headers = self._build_browser_headers()
        headers["Content-Type"] = "application/json"
        if YT_API_KEY:
            headers["x-api-key"] = YT_API_KEY
        return headers

    def _create_session(self):
        session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _extract_error_message(self, payload, fallback="Unknown error"):
        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            errors = payload.get("errors")
            if isinstance(errors, list):
                for item in errors:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                    if isinstance(item, dict):
                        message = item.get("message")
                        if isinstance(message, str) and message.strip():
                            return message.strip()
        return fallback

    def _extract_download_url(self, payload):
        def walk(value):
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            if isinstance(value, dict):
                for key in ("directLink", "streamLink", "url", "download", "link"):
                    match = walk(value.get(key))
                    if match:
                        return match
            if isinstance(value, list):
                for item in value:
                    match = walk(item)
                    if match:
                        return match
            return None

        if not isinstance(payload, dict):
            return None
        for key in ("audio_url", "video_url", "directLink", "streamLink", "downloads"):
            match = walk(payload.get(key))
            if match:
                return match
        return None

    def _normalize_link(self, link: str):
        if not link:
            return link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        return link

    def _extract_video_id(self, link: str):
        if not link:
            return None
        link = self._normalize_link(str(link).strip())
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", link):
            return link
        parsed = urlparse(link)
        query_video_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_video_id:
            return query_video_id
        if parsed.netloc.endswith("youtu.be"):
            return parsed.path.strip("/").split("/")[0] or None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
        return None

    async def _search_results(self, query: str, limit: int):
        prepared_query = self._prepare_lookup(query)
        if not prepared_query:
            return []
        cache_key = (prepared_query.casefold(), int(limit))
        cached = self._cache_get(
            self._search_cache, cache_key, self._cache_ttls["search"]
        )
        if cached is not None:
            return cached
        search = VideosSearch(prepared_query, limit=limit)
        search_results = (await search.next()).get("result", [])
        normalized_results = []
        for result in search_results:
            normalized = self._normalize_video_result(result)
            if normalized:
                normalized_results.append(normalized)
        self._cache_set(
            self._search_cache, cache_key, normalized_results, self._cache_ttls["search"]
        )
        return normalized_results

    def _fetch_primary_media_link_sync(self, vid_id, media_format):
        if not YT_API_KEY or not YTPROXY:
            return None
        session = None
        try:
            session = self._create_session()
            response = session.get(
                f"{YTPROXY.rstrip('/')}/info/{vid_id}",
                headers=self._build_primary_api_headers(),
                timeout=60,
            )
            try:
                payload = response.json()
            except ValueError:
                payload = None

            if response.ok and isinstance(payload, dict) and payload.get("status") == "success":
                media_key = "video_url" if media_format == "mp4" else "audio_url"
                media_url = payload.get(media_key)
                if media_url:
                    return media_url
                logger.error(
                    f"Primary API success response missing {media_key} for video {vid_id}."
                )
                return None

            message = self._extract_error_message(
                payload,
                response.text[:250] if response.text else f"HTTP {response.status_code}",
            )
            logger.error(
                f"Primary API {media_format} lookup failed for {vid_id}: {message}"
            )
            return None
        except requests.RequestException as exc:
            logger.error(f"Primary API request failed for {vid_id}: {exc}")
            return None
        finally:
            if session:
                session.close()

    def _fetch_worker_media_link_sync(self, vid_id, media_format):
        if not WORKER_FALLBACK_API_URL or not WORKER_FALLBACK_API_KEY:
            logger.warning("Worker fallback API URL/key not configured. Skipping worker fallback.")
            return None

        api_url = f"{WORKER_FALLBACK_API_URL.rstrip('/')}/api"
        payload = {
            "key": WORKER_FALLBACK_API_KEY,
            "url": f"{self.base}{vid_id}",
            "format": media_format,
        }

        session = None
        try:
            session = self._create_session()
            attempts = (
                ("GET", lambda: session.get(api_url, params=payload, timeout=75)),
                (
                    "POST",
                    lambda: session.post(
                        api_url,
                        json=payload,
                        headers={"Content-Type": "application/json", **self._build_browser_headers()},
                        timeout=75,
                    ),
                ),
            )

            for method_name, method in attempts:
                response = method()
                try:
                    data = response.json()
                except ValueError:
                    data = None

                media_url = self._extract_download_url(data)
                if response.ok and media_url:
                    return media_url

                message = self._extract_error_message(
                    data,
                    response.text[:250] if response.text else f"HTTP {response.status_code}",
                )
                logger.error(
                    f"Worker fallback {method_name} {media_format} lookup failed for {vid_id}: {message}"
                )
                if response.status_code in {400, 401, 403}:
                    break
            return None
        except requests.RequestException as exc:
            logger.error(f"Worker fallback request failed for {vid_id}: {exc}")
            return None
        finally:
            if session:
                session.close()

    async def _get_video_details(self, link: str, limit: int = 20) -> Union[dict, None]:
        """Fetches direct video details for URLs/IDs and search results for text queries."""
        try:
            link = self._prepare_lookup(link)
            if not link:
                return None
            try:
                limit = int(limit) if limit is not None else 20
                if limit <= 0:
                    limit = 20
            except (TypeError, ValueError):
                limit = 20

            video_reference = self._extract_video_id(link)
            if video_reference:
                cached = self._cache_get(
                    self._video_details_cache,
                    ("video", video_reference),
                    self._cache_ttls["video"],
                )
                if cached is not None:
                    return cached
                result = self._normalize_video_result(await Video.get(video_reference))
                if result:
                    self._cache_set(
                        self._video_details_cache,
                        ("video", video_reference),
                        result,
                        self._cache_ttls["video"],
                    )
                    self._cache_set(
                        self._video_details_cache,
                        ("lookup", link.casefold(), limit),
                        result,
                        self._cache_ttls["video"],
                    )
                    return result

            cached = self._cache_get(
                self._video_details_cache,
                ("lookup", link.casefold(), limit),
                self._cache_ttls["video"],
            )
            if cached is not None:
                return cached

            search_results = await self._search_results(link, limit)
            for result in search_results:
                self._cache_set(
                    self._video_details_cache,
                    ("lookup", link.casefold(), limit),
                    result,
                    self._cache_ttls["video"],
                )
                self._cache_set(
                    self._video_details_cache,
                    ("video", result["id"]),
                    result,
                    self._cache_ttls["video"],
                )
                return result
            return None

        except Exception as e:
            LOGGER(__name__).error(f"Error in _get_video_details: {str(e)}")
            return None

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._prepare_lookup(link)

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("No suitable video found or video is unavailable.")

        title = result["title"]
        duration_min = result.get("duration") or "Unknown"
        thumbnail = self._thumbnail_from_result(result)
        vidid = result["id"]

        if duration_min == "Unknown":
            duration_sec = 0
        else:
            duration_sec = int(time_to_seconds(duration_min))

        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._prepare_lookup(link)

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("No suitable video found or video is unavailable.")
        return result["title"]

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._prepare_lookup(link)

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("No suitable video found or video is unavailable.")
        return result.get("duration") or "Unknown"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._prepare_lookup(link)

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("No suitable video found or video is unavailable.")
        thumbnail = self._thumbnail_from_result(result)
        if not thumbnail:
            raise ValueError("Thumbnail not available for the requested video.")
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._normalize_link(link)

        proc = await asyncio.create_subprocess_exec(
            *_build_ytdlp_command(
                "-g",
                "-f",
                "best[height<=?720][width<=?1280]",
                link,
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        link = self._normalize_link(link)
        if _has_unsafe_url_chars(link):
            return []
        command = [
            "-i",
            "--get-id",
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            "--skip-download",
            link,
        ]
        playlist = await shell_cmd(
            _build_ytdlp_command(*command)
        )
        try:
            result = playlist.split("\n")
            for key in result:
                if key == "":
                    result.remove(key)
        except:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._prepare_lookup(link)

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("No suitable video found or video is unavailable.")

        track_details = {
            "title": result["title"],
            "link": result["link"],
            "vidid": result["id"],
            "duration_min": result.get("duration") or "Unknown",
            "thumb": self._thumbnail_from_result(result),
        }
        return track_details, result["id"]

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._normalize_link(link)
        ytdl_opts = _apply_cookiefile_option({"quiet": True})
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except:
                    continue
                if not "dash" in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        link = self._prepare_lookup(link)

        try:
            results = []
            search_results = await self._search_results(link, 10)

            for normalized in search_results:
                duration_str = normalized.get("duration") or "0:00"
                try:
                    parts = duration_str.split(":")
                    duration_secs = 0
                    if len(parts) == 3:
                        duration_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration_secs = int(parts[0]) * 60 + int(parts[1])

                    if duration_secs <= 3600:
                        results.append(normalized)
                except (ValueError, IndexError):
                    continue

            if not results or query_type >= len(results):
                raise ValueError("No suitable videos found within duration limit")

            selected = results[query_type]
            thumbnail = self._thumbnail_from_result(selected)
            if not thumbnail:
                raise ValueError("Thumbnail not available for the requested video.")
            return (
                selected["title"],
                selected["duration"],
                thumbnail,
                selected["id"]
            )

        except Exception as e:
            LOGGER(__name__).error(f"Error in slider: {str(e)}")
            raise ValueError("Failed to fetch video details")

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
        vid_id = link if videoid else self._extract_video_id(link)
        if videoid:
            vid_id = link
            link = self.base + link
        link = self._normalize_link(link)
        safe_title = _safe_filename(title) if title else title
        loop = asyncio.get_running_loop()

        os.makedirs("downloads", exist_ok=True)

        async def download_with_ytdlp(url, filepath, headers=None, max_retries=3):
            merged_headers = self._build_browser_headers()
            if headers:
                merged_headers.update(headers)

            def run_download():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "outtmpl": filepath,
                    "force_overwrites": True,
                    "nopart": True,
                    "retries": max_retries,
                    "http_headers": merged_headers,
                    "concurrent_fragment_downloads": 8,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                await loop.run_in_executor(None, run_download)
                if os.path.exists(filepath):
                    return filepath
            except Exception as e:
                logger.error(f"yt-dlp download failed: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None

        async def download_with_requests_fallback(url, filepath, headers=None):
            session = None
            try:
                session = self._create_session()
                request_headers = self._build_browser_headers()
                if headers:
                    request_headers.update(headers)
                response = session.get(
                    url,
                    headers=request_headers,
                    stream=True,
                    timeout=60,
                )
                response.raise_for_status()
                chunk_size = 1024 * 1024

                with open(filepath, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file.write(chunk)

                return filepath

            except Exception as e:
                logger.error(f"Requests download failed: {str(e)}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return None
            finally:
                if session:
                    session.close()

        async def download_from_source(url, filepath, headers=None):
            result = await download_with_ytdlp(url, filepath, headers)
            if result:
                return result
            return await download_with_requests_fallback(url, filepath, headers)

        async def get_worker_media_link(vid_id, media_format):
            return await loop.run_in_executor(
                None, self._fetch_worker_media_link_sync, vid_id, media_format
            )

        def download_from_youtube_sync(source_link, media_format, filepath):
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "force_overwrites": True,
                "noplaylist": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "outtmpl": os.path.join("downloads", f"{vid_id}.%(ext)s"),
                "prefer_ffmpeg": True,
            }
            if media_format == "mp4":
                ydl_opts.update(
                    {
                        "format": (
                            "(bestvideo[height<=?720][width<=?1280][ext=mp4]/best[height<=?720][width<=?1280])"
                            "+(bestaudio[ext=m4a]/bestaudio)/best[height<=?720][width<=?1280]"
                        ),
                        "merge_output_format": "mp4",
                    }
                )
            else:
                ydl_opts.update(
                    {
                        "format": "bestaudio/best",
                        "postprocessors": [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192",
                            }
                        ],
                    }
                )
            _apply_cookiefile_option(ydl_opts)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([source_link])
            return filepath if os.path.exists(filepath) else None

        async def download_from_youtube_fallback(source_link, media_format, filepath):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                return await loop.run_in_executor(
                    None,
                    download_from_youtube_sync,
                    source_link,
                    media_format,
                    filepath,
                )
            except Exception as exc:
                logger.error(f"yt-dlp fallback download failed for {vid_id}: {exc}")
                return None

        async def audio_dl(current_vid_id):
            filepath = os.path.join("downloads", f"{current_vid_id}.mp3")
            if os.path.exists(filepath):
                return filepath

            primary_audio_url = await loop.run_in_executor(
                None, self._fetch_primary_media_link_sync, current_vid_id, "mp3"
            )
            if primary_audio_url:
                result = await download_from_source(primary_audio_url, filepath)
                if result:
                    return result
                logger.warning("Paid audio URL download failed, trying worker fallback.")

            fallback_audio_url = await get_worker_media_link(current_vid_id, "mp3")
            if fallback_audio_url:
                result = await download_from_source(fallback_audio_url, filepath)
                if result:
                    return result

            logger.warning(
                f"Audio download APIs failed for {current_vid_id}, trying yt-dlp fallback."
            )
            return await download_from_youtube_fallback(link, "mp3", filepath)
        
        
        async def video_dl(current_vid_id):
            filepath = os.path.join("downloads", f"{current_vid_id}.mp4")
            if os.path.exists(filepath):
                return filepath

            primary_video_url = await loop.run_in_executor(
                None, self._fetch_primary_media_link_sync, current_vid_id, "mp4"
            )
            if primary_video_url:
                result = await download_from_source(primary_video_url, filepath)
                if result:
                    return result
                logger.warning("Paid video URL download failed, trying worker fallback.")

            fallback_video_url = await get_worker_media_link(current_vid_id, "mp4")
            if fallback_video_url:
                result = await download_from_source(fallback_video_url, filepath)
                if result:
                    return result

            logger.warning(
                f"Video download APIs failed for {current_vid_id}, trying yt-dlp fallback."
            )
            return await download_from_youtube_fallback(link, "mp4", filepath)
        
        def song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{safe_title}"
            ydl_optssx = _apply_cookiefile_option({
                "format": formats,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
            })
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        def song_audio_dl():
            fpath = f"downloads/{safe_title}.%(ext)s"
            ydl_optssx = _apply_cookiefile_option({
                "format": format_id,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            })
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = f"downloads/{safe_title}.mp4"
            if not os.path.exists(fpath):
                raise RuntimeError(f"Failed to download song video for {safe_title}.")
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = f"downloads/{safe_title}.mp3"
            if not os.path.exists(fpath):
                raise RuntimeError(f"Failed to download song audio for {safe_title}.")
            return fpath
        elif video:
            direct = True
            if not vid_id:
                raise RuntimeError("Video ID could not be resolved for video download.")
            downloaded_file = await video_dl(vid_id)
        else:
            direct = True
            if not vid_id:
                raise RuntimeError("Video ID could not be resolved for audio download.")
            downloaded_file = await audio_dl(vid_id)

        if not downloaded_file:
            media_type = "video" if video else "audio"
            raise RuntimeError(f"Failed to download {media_type} for {vid_id or link}.")
        return downloaded_file, direct
