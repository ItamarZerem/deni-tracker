"""תמונת המשחק לערוץ הטלגרם, בעיצוב קבוע.

‏1280x720: הקבוצה של דני מימין (עברית נקראת מימין לשמאל), היריבה משמאל, כל צד בצבע
של הקבוצה, ודני במרכז. ‏למעלה שם הערוץ, ובאמצע מתי המשחק.
‏Pillow ‏בלי raqm לא יודע לכתוב מימין לשמאל, לכן כל טקסט עברי עובר דרך python-bidi.
"""
import io
import os
import urllib.request

from bidi import get_display
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(ROOT, "fonts", "Heebo.ttf")
W, H = 1280, 720
CHANNEL = "עדכונים דני אבדיה"
BASE = (11, 13, 18)


def font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_axes([weight])
    return f


def fetch_image(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGBA")


def hex_rgb(h: str) -> tuple:
    h = (h or "777777").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def team_color(color: str, alternate: str) -> tuple:
    """‏הצבע הראשי, אלא אם הוא כמעט שחור (ברוקלין, סן אנטוניו) - אז המשני."""
    c = hex_rgb(color)
    if sum(c) < 120:
        c = hex_rgb(alternate)
    if sum(c) > 690:  # ‏לבן: לא יבלוט על הרקע ולא ייראה כמו צבע קבוצה
        c = (120, 120, 130)
    return c


def mix(c: tuple, other: tuple, t: float) -> tuple:
    return tuple(int(a + (b - a) * t) for a, b in zip(c, other))


def text_center(draw, xy, text, fnt, fill=(255, 255, 255), anchor="mm"):
    draw.text(xy, get_display(text), font=fnt, fill=fill, anchor=anchor)


def background(right: tuple, left: tuple) -> Image.Image:
    """‏שני חצאים בצבעי הקבוצות, עם קו אלכסוני ביניהם, שמחשיכים לכיוון המרכז."""
    img = Image.new("RGB", (W, H), BASE)
    px = img.load()
    for x in range(W):
        for y in range(H):
            # ‏הקו האלכסוני: עובר באמצע, נוטה 70 פיקסלים לכל כיוון
            edge = W / 2 + 70 - 140 * y / H
            c = right if x > edge else left
            dist = abs(x - edge) / (W / 2)            # ‏0 בקו, 1 בשוליים
            glow = 0.35 + 0.45 * min(dist * 1.4, 1)   # ‏חזק בשוליים, כהה במרכז
            shade = 0.85 - 0.35 * (y / H)             # ‏כהה יותר למטה
            px[x, y] = mix(BASE, c, glow * shade)
    return img


def preview_card(us: dict, them: dict, when: str, date: str, label: str = "",
                 chip: str = "", player_png: str = "") -> bytes:
    """‏us / them: {"name": "פורטלנד", "logo": url, "color": hex, "alt": hex}.
    ‏when: «הלילה 5:00». ‏date: «יום שלישי 28.10». ‏label: «עונה סדירה» / «פלייאוף».
    ‏chip: תגית צהובה ליד דני, למשל «בספק למשחק»."""
    right = team_color(us["color"], us.get("alt", ""))
    left = team_color(them["color"], them.get("alt", ""))
    img = background(right, left).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # ‏לוגואים, עם צל רך כדי שיבלטו על כל צבע
    for team, cx in ((us, W - 245), (them, 245)):
        logo = fetch_image(team["logo"])
        logo.thumbnail((300, 300), Image.LANCZOS)
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        mask = logo.split()[3].point(lambda a: int(a * 0.55))
        shadow.paste((0, 0, 0, 255), (cx - logo.width // 2 + 6, 300 - logo.height // 2 + 10), mask)
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
        img.alpha_composite(logo, (cx - logo.width // 2, 300 - logo.height // 2))
        text_center(draw, (cx, 500), team["name"], font(52, 800))

    # ‏דני במרכז, מהחזה ומעלה, נשען על התחתית
    if player_png:
        p = fetch_image(player_png)
        p.thumbnail((620, 460), Image.LANCZOS)
        img.alpha_composite(p, ((W - p.width) // 2, H - p.height))

    # ‏פס כהה בתחתית, כדי שהטקסט עליו ייקרא
    fade = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for y in range(200):
        fd.line([(0, y), (W, y)], fill=(*BASE, int(235 * (y / 200) ** 1.6)))
    img.alpha_composite(fade, (0, H - 200))
    draw = ImageDraw.Draw(img)

    # ‏למעלה: שם הערוץ, ומתחתיו מתי
    text_center(draw, (W // 2, 46), CHANNEL, font(30, 600), fill=(255, 255, 255, 215))
    draw.line([(W // 2 - 150, 74), (W // 2 + 150, 74)], fill=(255, 255, 255, 90), width=2)
    text_center(draw, (W // 2, 128), when, font(64, 900))
    text_center(draw, (W // 2, 188), date, font(34, 500), fill=(255, 255, 255, 220))

    if label:
        text_center(draw, (W // 2, H - 40), label, font(30, 600), fill=(255, 255, 255, 200))
    if chip:
        f = font(32, 800)
        t = get_display(chip)
        x0, y0, x1, y1 = draw.textbbox((0, 0), t, font=f)
        w, h = x1 - x0 + 44, y1 - y0 + 22
        cx, cy = W // 2, H - 96
        draw.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                               radius=h // 2, fill=(250, 196, 40))
        draw.text((cx, cy), t, font=f, fill=BASE, anchor="mm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()
