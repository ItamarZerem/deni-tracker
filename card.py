"""התמונות לערוץ הטלגרם, בעיצוב קבוע: משחק, סיום, הודעה כללית, השבוע ומפת זריקות.

‏1280x720: הקבוצה של דני מימין (עברית נקראת מימין לשמאל), היריבה משמאל, כל צד בצבע
של הקבוצה, ודני במרכז. ‏למעלה שם הערוץ, ובאמצע מתי המשחק.
‏כל טקסט עברי עובר דרך python-bidi, והגופן נטען תמיד במנוע BASIC (ראו font).
"""
import io
import math
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


def overlay_box(img: Image.Image, box: tuple, radius: int, fill: tuple) -> None:
    """‏מלבן שקוף-למחצה. ‏ציור ישיר על RGBA מחליף פיקסלים ולא מערבב, לכן שכבה נפרדת."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=fill)
    img.alpha_composite(layer)


def week_card(team: dict, title: str, dates: str, rows: list) -> bytes:
    """‏«השבוע של דני»: שורה לכל משחק. ‏team: {"logo", "color", "alt"}.
    ‏rows: [{"date": "יום שני 2.11", "time": "5:00", "name": "דנבר", "logo": url,
    "side": "בחוץ", "tv": "ספורט 5"}]. ‏עד 5 שורות."""
    c = team_color(team["color"], team.get("alt", ""))
    img = background(c, mix(BASE, c, 0.5)).convert("RGBA")
    logo = fetch_image(team["logo"])
    logo.thumbnail((120, 120), Image.LANCZOS)
    img.alpha_composite(logo, (70, 45))
    right = W - 70
    draw = ImageDraw.Draw(img)
    draw.text((right, 52), get_display(CHANNEL), font=font(28, 600), fill=(255, 255, 255, 210), anchor="rm")
    draw.text((right, 122), get_display(title), font=font(70, 900), anchor="rm")
    draw.text((right, 188), get_display(dates), font=font(34, 500), fill=(255, 255, 255, 220), anchor="rm")

    top, step = 240, 92
    for i, r in enumerate(rows[:5]):
        cy = top + i * step + 38
        overlay_box(img, (60, cy - 38, W - 60, cy + 38), 22, (0, 0, 0, 80))
        draw = ImageDraw.Draw(img)
        draw.text((right - 20, cy), get_display(r["date"]), font=font(34, 600), anchor="rm")
        draw.text((870, cy), r["time"], font=font(42, 800), anchor="mm")
        opp = fetch_image(r["logo"])
        opp.thumbnail((62, 62), Image.LANCZOS)
        img.alpha_composite(opp, (780 - opp.width // 2, cy - opp.height // 2))
        draw = ImageDraw.Draw(img)
        draw.text((735, cy), get_display(r["name"]), font=font(40, 800), anchor="rm")
        pill(draw, r["side"], 405, cy, 26, (255, 255, 255))
        if r.get("tv"):
            draw.text((95, cy), get_display(r["tv"]), font=font(30, 600), fill=(250, 196, 40), anchor="lm")
    return jpeg(img)


# ‏מגרש בפיט, כמו ב-ESPN: x מ-0 עד 50 לרוחב, y המרחק מהסל לכיוון מרכז המגרש (הסל ב-(25, 0)).
BASELINE = -5.25
HALF = 47 + BASELINE


def court_lines(draw, to_px, scale: float) -> None:
    line = (255, 255, 255)

    def arc(cx, cy, r, a0, a1, n=60):
        pts = [to_px(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
                     cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]
        draw.line(pts, fill=line, width=3)

    x0, y0 = to_px(0, BASELINE)
    x1, y1 = to_px(50, HALF)
    draw.rectangle([x0, y1, x1, y0], outline=line, width=4)
    px0, py0 = to_px(17, BASELINE)
    px1, py1 = to_px(33, 19 + BASELINE)
    draw.rectangle([px0, py1, px1, py0], outline=line, width=3)       # ‏הצבע
    arc(25, 19 + BASELINE, 6, 0, 180)                                  # ‏חצי עיגול העונשין
    arc(25, 0, 4, 0, 180)                                              # ‏אזור החסימה
    draw.line([to_px(22, -1.25), to_px(28, -1.25)], fill=line, width=4)   # ‏הלוח
    hx, hy = to_px(25, 0)
    r = 0.75 * scale
    draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline=(255, 140, 60), width=3)
    corner = (23.75 ** 2 - 22 ** 2) ** 0.5
    for x in (3, 47):
        draw.line([to_px(x, BASELINE), to_px(x, corner)], fill=line, width=3)
    a = math.degrees(math.atan2(corner, -22))
    arc(25, 0, 23.75, 180 - a, a)                                      # ‏קשת השלוש
    arc(25, HALF, 6, 180, 360)                                         # ‏מעגל המרכז


def shot_card(team: dict, title: str, subtitle: str, shots: list, lines: list, player_png: str = "") -> bytes:
    """‏מפת זריקות: המגרש משמאל, המספרים מימין. ‏shots: [(x, y, נכנסה)] בפיט, לפי ESPN.
    ‏קליעה: עיגול ירוק. ‏החטאה: איקס אדום."""
    c = team_color(team["color"], team.get("alt", ""))
    img = background(c, mix(BASE, c, 0.35)).convert("RGBA")
    if player_png:
        p = fetch_image(player_png)
        p.thumbnail((430, 360), Image.LANCZOS)
        img.alpha_composite(p, (W - 40 - p.width, H - p.height))
        bottom_fade(img, 120)
    scale = 12.6
    left, bottom = 45, H - 30

    def to_px(x, y):
        return left + x * scale, bottom - (y - BASELINE) * scale

    overlay_box(img, (left, bottom - (HALF - BASELINE) * scale, left + 50 * scale, bottom), 0, (0, 0, 0, 70))
    draw = ImageDraw.Draw(img)
    court_lines(draw, to_px, scale)
    green, red = (61, 220, 132), (255, 90, 95)
    for x, y, made in sorted(shots, key=lambda s: s[2]):   # ‏הקליעות מעל ההחטאות
        px, py = to_px(min(max(x, 0.5), 49.5), min(max(y, BASELINE + 0.5), HALF - 0.5))
        if made:
            draw.ellipse([px - 11, py - 11, px + 11, py + 11], fill=green, outline=BASE, width=3)
        else:
            for d in (1, -1):
                draw.line([(px - 9, py - 9 * d), (px + 9, py + 9 * d)], fill=red, width=5)

    right = W - 60
    draw.text((right, 52), get_display(CHANNEL), font=font(28, 600), fill=(255, 255, 255, 210), anchor="rm")
    draw.text((right, 125), get_display(title), font=font(62, 900), anchor="rm")
    draw.text((right, 185), get_display(subtitle), font=font(32, 500), fill=(255, 255, 255, 220), anchor="rm")
    y = 255
    for line in lines:
        draw.text((right, y), get_display(line), font=font(40, 700), anchor="rm")
        y += 56
    ly = y + 18
    draw.ellipse([right - 22, ly - 11, right, ly + 11], fill=green, outline=BASE, width=3)
    draw.text((right - 34, ly), get_display("קליעה"), font=font(28, 600), anchor="rm")
    lx = right - 190
    for d in (1, -1):
        draw.line([(lx - 9, ly - 9 * d), (lx + 9, ly + 9 * d)], fill=red, width=5)
    draw.text((lx - 22, ly), get_display("החטאה"), font=font(28, 600), anchor="rm")
    return jpeg(img)
