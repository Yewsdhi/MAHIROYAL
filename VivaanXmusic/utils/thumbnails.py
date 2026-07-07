import os
import re

import aiofiles
import aiohttp
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from unidecode import unidecode
from youtubesearchpython.future import Video

from VivaanXmusic import app
from config import YOUTUBE_IMG_URL


CANVAS_SIZE = (1280, 720)
RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def changeImageSize(maxWidth, maxHeight, image):
    return image.resize((maxWidth, maxHeight), RESAMPLE)


def coverImageSize(width, height, image):
    image = image.convert("RGBA")
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio > target_ratio:
        resized_height = height
        resized_width = int(height * source_ratio)
    else:
        resized_width = width
        resized_height = int(width / source_ratio)
    image = image.resize((resized_width, resized_height), RESAMPLE)
    left = (resized_width - width) // 2
    top = (resized_height - height) // 2
    return image.crop((left, top, left + width, top + height))


def circle(img):
    size = min(img.size)
    img = coverImageSize(size, size, img)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    c = np.array(img.convert("RGB"))
    d = np.array(mask)
    e = np.dstack((c, d))
    return Image.fromarray(e)


def clear(text):
    list = text.split(" ")
    title = ""
    for i in list:
        if len(title) + len(i) < 60:
            title += " " + i
    return title.strip()


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _text_width(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _ellipsize(draw, text, font, max_width):
    if _text_width(draw, text, font) <= max_width:
        return text
    text = text.strip()
    while text and _text_width(draw, f"{text}...", font) > max_width:
        text = text[:-1].rstrip()
    return f"{text}..." if text else "..."


def _wrap_text(draw, text, font, max_width, max_lines=2):
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = ""
    for index, word in enumerate(words):
        candidate = f"{current} {word}".strip()
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            remaining = " ".join(words[index:])
            lines.append(_ellipsize(draw, remaining, font, max_width))
            break
    else:
        if current:
            lines.append(current)

    if not lines and current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(draw, lines[-1], font, max_width)
    return [_ellipsize(draw, line, font, max_width) for line in lines]


def _rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _draw_shadow(base, box, radius, blur=28, offset=(0, 18), alpha=120):
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    shadow_box = (
        x1 + offset[0],
        y1 + offset[1],
        x2 + offset[0],
        y2 + offset[1],
    )
    draw.rounded_rectangle(shadow_box, radius=radius, fill=(0, 0, 0, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow)


def _draw_glass_panel(base, box, radius=34):
    _draw_shadow(base, box, radius, blur=36, offset=(0, 18), alpha=105)
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    mask = _rounded_mask((w, h), radius)
    frosted = base.crop(box).filter(ImageFilter.GaussianBlur(18))
    base.paste(frosted, (x1, y1), mask)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=(255, 255, 255, 38),
        outline=(255, 255, 255, 86),
        width=2,
    )
    draw.rounded_rectangle(
        (x1 + 2, y1 + 2, x2 - 2, y1 + 88),
        radius=radius,
        fill=(255, 255, 255, 20),
    )
    base.alpha_composite(overlay)


def _paste_rounded(base, image, box, radius=28, border=(255, 255, 255, 105)):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    _draw_shadow(base, box, radius, blur=24, offset=(0, 14), alpha=135)
    fitted = coverImageSize(w, h, image)
    mask = _rounded_mask((w, h), radius)
    base.paste(fitted, (x1, y1), mask)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(box, radius=radius, outline=border, width=2)
    base.alpha_composite(overlay)


def _paste_circle(base, image, box, border=(255, 255, 255, 155)):
    x1, y1, x2, y2 = box
    size = min(x2 - x1, y2 - y1)
    circle_box = (x1, y1, x1 + size, y1 + size)
    _draw_shadow(base, circle_box, size // 2, blur=24, offset=(0, 12), alpha=120)
    fitted = coverImageSize(size, size, image)
    mask = Image.new("L", (size, size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, size, size), fill=255)
    base.paste(fitted, (x1, y1), mask)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse(circle_box, outline=(12, 14, 24, 210), width=14)
    draw.ellipse(
        (x1 + 10, y1 + 10, x1 + size - 10, y1 + size - 10),
        outline=border,
        width=3,
    )
    base.alpha_composite(overlay)


def _draw_badge(base, box, text, font, fill=(255, 255, 255, 42)):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        box,
        radius=(box[3] - box[1]) // 2,
        fill=fill,
        outline=(255, 255, 255, 82),
        width=1,
    )
    text = _ellipsize(draw, text, font, box[2] - box[0] - 34)
    text_box = draw.textbbox((0, 0), text, font=font)
    y = box[1] + ((box[3] - box[1]) - (text_box[3] - text_box[1])) // 2 - 1
    draw.text((box[0] + 17, y), text, fill=(255, 255, 255, 238), font=font)
    base.alpha_composite(overlay)


def _fallback_avatar(name):
    image = Image.new("RGBA", (512, 512), (18, 20, 31, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((42, 42, 470, 470), fill=(236, 64, 122, 255))
    initial = unidecode(str(name or "B").strip()[:1]).upper() or "B"
    font = _font("BaddieXmusic/assets/font.ttf", 170)
    box = draw.textbbox((0, 0), initial, font=font)
    draw.text(
        ((512 - (box[2] - box[0])) // 2, (512 - (box[3] - box[1])) // 2 - 18),
        initial,
        fill=(255, 255, 255, 255),
        font=font,
    )
    return image


def _build_background(youtube):
    background = coverImageSize(*CANVAS_SIZE, youtube)
    background = background.filter(ImageFilter.GaussianBlur(22))
    background = ImageEnhance.Brightness(background).enhance(0.58)
    background = ImageEnhance.Contrast(background).enhance(1.08)

    gradient = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient)
    for y in range(CANVAS_SIZE[1]):
        alpha = int(50 + (y / CANVAS_SIZE[1]) * 155)
        draw.line((0, y, CANVAS_SIZE[0], y), fill=(0, 0, 0, alpha))
    draw.rectangle((0, 0, 1280, 130), fill=(0, 0, 0, 72))
    background.alpha_composite(gradient)

    light = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(light)
    draw.polygon(
        [(-140, 120), (420, -100), (820, 720), (260, 840)],
        fill=(255, 255, 255, 16),
    )
    draw.polygon(
        [(760, -60), (1460, 80), (1180, 740), (610, 630)],
        fill=(236, 64, 122, 18),
    )
    light = light.filter(ImageFilter.GaussianBlur(28))
    background.alpha_composite(light)
    return background


def _duration_text(result):
    duration = result.get("duration")
    if isinstance(duration, dict):
        return duration.get("text") or "Unknown"
    if duration:
        return str(duration)
    return "Unknown"


async def _download_chat_photo(user_id):
    try:
        async for photo in app.get_chat_photos(user_id, 1):
            return await app.download_media(photo.file_id, file_name=f"cache/{user_id}.jpg")
    except Exception:
        pass
    try:
        async for photo in app.get_chat_photos(app.id, 1):
            return await app.download_media(photo.file_id, file_name=f"cache/{app.id}.jpg")
    except Exception:
        return None
    return None


async def get_thumb(videoid, user_id):
    os.makedirs("cache", exist_ok=True)
    if os.path.isfile(f"cache/{videoid}_{user_id}.png"):
        return f"cache/{videoid}_{user_id}.png"

    try:
        result = await Video.get(videoid)
        if not result or not result.get("title"):
            return YOUTUBE_IMG_URL
        try:
            title = result["title"]
            title = re.sub(r"\W+", " ", title)
            title = title.title()
        except:
            title = "Unsupported Title"
        duration = _duration_text(result)
        thumbnail = YOUTUBE_IMG_URL
        for thumb in result.get("thumbnails") or []:
            if isinstance(thumb, dict) and thumb.get("url"):
                thumbnail = thumb["url"].split("?")[0]
                break
        try:
            views = (result.get("viewCount") or {}).get("short") or "Unknown Views"
        except:
            views = "Unknown Views"
        try:
            channel = (result.get("channel") or {}).get("name") or "Unknown Channel"
        except:
            channel = "Unknown Channel"

        thumb_path = f"cache/thumb{videoid}.png"
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail) as resp:
                if resp.status == 200:
                    f = await aiofiles.open(thumb_path, mode="wb")
                    await f.write(await resp.read())
                    await f.close()
        if not os.path.isfile(thumb_path):
            return YOUTUBE_IMG_URL

        sp = await _download_chat_photo(user_id)
        if sp and os.path.isfile(sp):
            xp = Image.open(sp)
        else:
            xp = _fallback_avatar(getattr(app, "name", "BaddieXmusic"))

        youtube = Image.open(thumb_path)
        background = _build_background(youtube)
        _draw_glass_panel(background, (54, 74, 1226, 642), radius=36)
        _paste_rounded(background, youtube, (88, 142, 502, 546), radius=30)
        _paste_circle(background, xp, (416, 426, 526, 536))

        draw = ImageDraw.Draw(background)
        arial = _font("VivaanXmusic/assets/font2.ttf", 28)
        small = _font("VivaanXmusic/assets/font2.ttf", 24)
        font = _font("VivaanXmusic/assets/font.ttf", 44)
        title_font = _font("VivaanXmusic/assets/font.ttf", 48)
        bot_name = unidecode(getattr(app, "name", "VivaanXmusic") or "VivaanXmusic")

        _draw_badge(background, (84, 94, 306, 140), "NOW PLAYING", small, fill=(236, 64, 122, 126))
        _draw_badge(background, (966, 18, 1220, 66), bot_name, arial)

        meta = f"{channel}  |  {views[:23]}"
        draw.text(
            (548, 224),
            _ellipsize(draw, unidecode(meta), arial, 630),
            (226, 231, 242),
            font=arial,
        )
        title_lines = _wrap_text(draw, unidecode(clear(title)), title_font, 630, 2)
        for index, line in enumerate(title_lines):
            draw.text((548, 274 + index * 56), line, (255, 255, 255), font=title_font)

        draw.text((548, 420), "Premium Music Experience", (232, 235, 244), font=font)

        progress_overlay = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        progress = ImageDraw.Draw(progress_overlay)
        progress.rounded_rectangle((88, 564, 1192, 574), radius=5, fill=(255, 255, 255, 62))
        progress.rounded_rectangle((88, 564, 766, 574), radius=5, fill=(255, 255, 255, 235))
        progress.ellipse((748, 550, 788, 590), fill=(255, 255, 255, 255))
        progress.ellipse((758, 560, 778, 580), fill=(236, 64, 122, 255))
        background.alpha_composite(progress_overlay)

        draw = ImageDraw.Draw(background)
        draw.text((88, 592), "00:00", (255, 255, 255), font=arial)
        draw.text(
            (1110, 592),
            _ellipsize(draw, f"{duration[:23]}", arial, 90),
            (255, 255, 255),
            font=arial,
        )
        try:
            os.remove(thumb_path)
        except:
            pass
        background.save(f"cache/{videoid}_{user_id}.png")
        return f"cache/{videoid}_{user_id}.png"
    except Exception:
        return YOUTUBE_IMG_URL
