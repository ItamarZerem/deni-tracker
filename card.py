"""תמונת המשחק לערוץ הטלגרם, בעיצוב קבוע.

‏1280x720: הקבוצה של דני מימין (עברית נקראת מימין לשמאל), היריבה משמאל, כל צד בצבע
של הקבוצה, ודני במרכז. ‏למעלה שם הערוץ, ובאמצע מתי המשחק.
‏כל טקסט עברי עובר דרך python-bidi, והגופן נטען תמיד במנוע BASIC (ראו font).
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
    # ‏BASIC תמיד: ב-GitHub ל-Pillow יש raqm, שהופך עברית בעצמו, ואז get_display הפך אותה
    # ‏בחזרה והתמונה יצאה «םירזוח». ‏עם BASIC ההיפוך נעשה רק פעם אחת, ב-get_display.
    f = ImageFont.truetype(FONT, size, layout_engine=ImageFont.Layout.BASIC)
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


def paste_logo(img: Image.Image, url: str, cx: int, cy: int, size: int) -> None:
    """‏לוגו ממורכז ב-(cx, cy), עם צל רך כדי שיבלוט על כל צבע."""
    logo = fetch_image(url)
    logo.thumbnail((size, size), Image.LANCZOS)
    x, y = cx - logo.width // 2, cy - logo.height // 2
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 255), (x + 6, y + 10), logo.split()[3].point(lambda a: int(a * 0.55)))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(logo, (x, y))


def paste_player(img: Image.Image, url: str, max_w: int, max_h: int) -> None:
    """‏דני במרכז, מהחזה ומעלה, נשען על התחתית."""
    p = fetch_image(url)
    p.thumbnail((max_w, max_h), Image.LANCZOS)
    img.alpha_composite(p, ((W - p.width) // 2, H - p.height))


def bottom_fade(img: Image.Image, height: int = 200) -> None:
    """‏פס כהה בתחתית, כדי שהטקסט עליו ייקרא."""
    fade = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for y in range(height):
        fd.line([(0, y), (W, y)], fill=(*BASE, int(235 * (y / height) ** 1.6)))
    img.alpha_composite(fade, (0, H - height))


def pill(draw, text: str, cx: int, cy: int, size: int, fill: tuple, color: tuple = BASE) -> None:
    f = font(size, 800)
    t = get_display(text)
    x0, y0, x1, y1 = draw.textbbox((0, 0), t, font=f)
    w, h = x1 - x0 + 44, y1 - y0 + 22
    draw.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], radius=h // 2, fill=fill)
    draw.text((cx, cy), t, font=f, fill=color, anchor="mm")


def header(draw) -> None:
    text_center(draw, (W // 2, 46), CHANNEL, font(30, 600), fill=(255, 255, 255, 215))
    draw.line([(W // 2 - 150, 74), (W // 2 + 150, 74)], fill=(255, 255, 255, 90), width=2)


def jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def preview_card(us: dict, them: dict, when: str, date: str, label: str = "",
                 chip: str = "", player_png: str = "") -> bytes:
    """‏us / them: {"name": "פורטלנד", "logo": url, "color": hex, "alt": hex}.
    ‏when: «הלילה 5:00». ‏date: «יום שלישי 28.10». ‏label: «עונה סדירה» / «פלייאוף».
    ‏chip: תגית צהובה ליד דני, למשל «בספק למשחק»."""
    img = background(team_color(us["color"], us.get("alt", "")),
                     team_color(them["color"], them.get("alt", ""))).convert("RGBA")
    draw = ImageDraw.Draw(img)
    for team, cx in ((us, W - 245), (them, 245)):
        paste_logo(img, team["logo"], cx, 300, 300)
        text_center(draw, (cx, 500), team["name"], font(52, 800))
    if player_png:
        paste_player(img, player_png, 620, 460)
    bottom_fade(img)
    draw = ImageDraw.Draw(img)
    header(draw)
    text_center(draw, (W // 2, 128), when, font(64, 900))
    text_center(draw, (W // 2, 188), date, font(34, 500), fill=(255, 255, 255, 220))
    if label:
        text_center(draw, (W // 2, H - 40), label, font(30, 600), fill=(255, 255, 255, 200))
    if chip:
        pill(draw, chip, W // 2, H - 96, 32, (250, 196, 40))
    return jpeg(img)


def score_card(us: dict, them: dict, ours: int, theirs: int, title: str, chip: str,
               player_png: str = "") -> bytes:
    """‏תמונת הסיום: התוצאה בגדול, כל מספר ליד הלוגו של הקבוצה שלו (שלנו מימין),
    והמנצחת בלבן מלא. ‏title: «סיום» / «סיום אחרי הארכה». ‏chip: השורה של דני."""
    img = background(team_color(us["color"], us.get("alt", "")),
                     team_color(them["color"], them.get("alt", ""))).convert("RGBA")
    draw = ImageDraw.Draw(img)
    for team, cx in ((us, W - 190), (them, 190)):
        paste_logo(img, team["logo"], cx, 290, 250)
        text_center(draw, (cx, 455), team["name"], font(44, 800))
    if player_png:
        paste_player(img, player_png, 520, 380)
    bottom_fade(img, 170)
    draw = ImageDraw.Draw(img)
    header(draw)
    text_center(draw, (W // 2, 118), title, font(46, 800), fill=(255, 255, 255, 230))
    win, lose = (255, 255, 255, 255), (255, 255, 255, 140)
    big = font(150, 900)
    draw.text((W // 2 + 175, 250), str(ours), font=big, anchor="mm", fill=win if ours > theirs else lose)
    draw.text((W // 2 - 175, 250), str(theirs), font=big, anchor="mm", fill=win if theirs > ours else lose)
    draw.text((W // 2, 250), "-", font=font(110, 700), anchor="mm", fill=(255, 255, 255, 170))
    if chip:
        pill(draw, chip, W // 2, H - 70, 34, (255, 255, 255))
    return jpeg(img)


def announce_card(team: dict, title: str, lines: list, player_png: str) -> bytes:
    """‏תמונה להודעה כללית (למשל «חוזרים לעדכן»): כל הרקע בצבע הקבוצה, דני משמאל,
    והטקסט מימין. ‏team: {"logo": url, "color": hex, "alt": hex}."""
    c = team_color(team["color"], team.get("alt", ""))
    img = background(c, mix(BASE, c, 0.5)).convert("RGBA")

    p = fetch_image(player_png)
    p.thumbnail((700, 560), Image.LANCZOS)
    img.alpha_composite(p, (20, H - p.height))

    logo = fetch_image(team["logo"])
    logo.thumbnail((130, 130), Image.LANCZOS)
    img.alpha_composite(logo, (W - 60 - logo.width, 50))

    draw = ImageDraw.Draw(img)
    right = W - 70
    draw.text((right - 160, 115), get_display(CHANNEL), font=font(30, 600),
              fill=(255, 255, 255, 215), anchor="rm")
    draw.text((right, 300), get_display(title), font=font(96, 900), anchor="rm")
    y = 400
    for line in lines:
        draw.text((right, y), get_display(line), font=font(40, 500), fill=(255, 255, 255, 225), anchor="rm")
        y += 58

    return jpeg(img)
