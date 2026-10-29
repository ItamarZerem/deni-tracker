#!/usr/bin/env python3
"""הבוט של ערוץ הטלגרם «עדכונים דני אבדיה».

‏בניגוד ל-tracker.py (התראות פרטיות לאיתמר, בלי ספוילרים), הערוץ ציבורי ומפרסם הכול:
  · טיוטה לאיתמר בפרטי, 3 שעות לפני הפרסום: ערוץ השידור (מזוהה לבד מלוח השידורים של
    ספורט 5), כפתורים לשינוי ערוץ ולפרסום מיידי, ואפשרות לכתוב שורת פתיחה מיוחדת.
    ‏בשבת לא נשלחת טיוטה, וההודעה מתפרסמת לבד.
  · הודעת המשחק בערוץ, ביום המשחק ב-12:00, עם תמונה (card.py) ומצב הכשירות של דני.
  · עדכון כשירות, אם דני היה בספק והמצב השתנה (או שהוא כבר על המגרש).
  · מחצית: תוצאה וסטטיסטיקה של דני, רק אם שיחק.
  · סיום: תוצאה, סטטיסטיקה מלאה והמשחק הבא. ‏אחריו: אבני דרך (שיא קריירה, דאבל-דאבל,
    רף בקריירה), מפת הזריקות של דני, תשובה לסקר, ובהמשך היילייטס.
  · סקר «כמה נקודות דני יקלע» 3 שעות אחרי הודעת המשחק.
  · «השבוע של דני» ביום ראשון ב-11:00, עם טיוטה לאיתמר ב-8:00.
  · מסיבות עיתונאים של דני מהיוטיוב של הקבוצה, גם בימים בלי משחק.

‏רץ ב-GitHub Actions כל 5 דקות (טריגר חיצוני מ-cron-job.org, ראו CLAUDE.md). ‏מחוץ לחלון של
משחק יוצא מיד. ‏המצב (מה כבר פורסם, מה איתמר בחר) נשמר ב-tgstate/state.json, שנשמר בין
ריצות ב-cache של Actions ולא בריפו.

⛔ ‏הלוג של Actions ציבורי, ואיתמר רואה את הטרמינל: לא מדפיסים תוכן הודעות, רק «נשלח».
‏ב-DENI_DRY מודפס תוכן, אבל הספרות מוסתרות (#), אלא אם DENI_SHOW=1.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from typing import Optional
from zoneinfo import ZoneInfo

import tracker
from tracker import ESPN, ESPN_WEB, PLAYER_ID, get_json, now_utc, parse_time

IL = ZoneInfo("Asia/Jerusalem")
CFG = tracker.CONFIG
CHANNEL = os.environ.get("DENI_TG_CHANNEL") or CFG.get("telegram_channel", "")   # ‏«@handle» או מזהה מספרי
ADMIN = os.environ.get("DENI_TG_ADMIN") or str(CFG.get("telegram_admin", ""))  # ‏המזהה המספרי של איתמר
PREVIEW_HOUR = CFG.get("preview_hour", 12)
LINKS_LINE = CFG.get("links_line", "קישורים לשידור בתגובות🔗")
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
DRY = bool(os.environ.get("DENI_DRY"))
STATE_PATH = os.environ.get("DENI_TG_STATE", os.path.join(tracker.ROOT, "tgstate", "state.json"))

DRAFT_LEAD = dt.timedelta(hours=3)       # ‏הטיוטה לאיתמר: 3 שעות לפני הפרסום
STATUS_UNTIL = dt.timedelta(minutes=30)  # ‏עדכוני כשירות: עד חצי שעה אחרי הפתיחה
HALF_WINDOW = (dt.timedelta(minutes=40), dt.timedelta(hours=4))
GAME_UNTIL = dt.timedelta(hours=8)       # ‏הודעת הסיום: עד 8 שעות אחרי הפתיחה

# ‏שם בעברית, ומה מחפשים בלוח השידורים של ספורט 5 (שם כותבים «ל.א. לייקרס» וגם
# ‏«לוס אנג׳לס לייקרס», לכן בקבוצות של לוס אנג'לס מחפשים רק את הכינוי).
TEAMS_HE = {
    "ATL": "אטלנטה", "BOS": "בוסטון", "BKN": "ברוקלין", "CHA": "שארלוט", "CHI": "שיקגו",
    "CLE": "קליבלנד", "DAL": "דאלאס", "DEN": "דנבר", "DET": "דטרויט", "GS": "גולדן סטייט",
    "HOU": "יוסטון", "IND": "אינדיאנה", "LAC": "הקליפרס", "LAL": "הלייקרס", "MEM": "ממפיס",
    "MIA": "מיאמי", "MIL": "מילווקי", "MIN": "מינסוטה", "NO": "ניו אורלינס", "NY": "ניו יורק",
    "OKC": "אוקלהומה סיטי", "ORL": "אורלנדו", "PHI": "פילדלפיה", "PHX": "פיניקס",
    "POR": "פורטלנד", "SAC": "סקרמנטו", "SA": "סן אנטוניו", "TOR": "טורונטו", "UTAH": "יוטה",
    "WSH": "וושינגטון",
}
SPORT5_KEY = {"LAC": "קליפרס", "LAL": "לייקרס", "OKC": "אוקלהומה"}

SEASON_LABEL = {2: "עונה סדירה", 3: "פלייאוף", 5: "פליי-אין"}
DAYS_HE = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"]

# ‏כפתורי ערוץ השידור בטיוטה. ‏callback_data מוגבל ל-64 בתים, לכן קודים קצרים.
TV_CODES = {
    "s5": "ספורט 5", "s5p": "ספורט 5+", "live": "ספורט 5 Live",
    "stars": "5Stars", "gold": "5Gold", "max": "5MAX", "none": "",
}
SPORT5_NAMES = {"ערוץ הספורט": "ספורט 5"}
SPORT5_URL = "https://www.sport5.co.il/Ajax/GetBroadcastSheetData.aspx?Type=&Date={}"

DOUBT = ("Questionable", "Doubtful", "Out")
STATUS_LINE = {
    "Questionable": "⚠️ דני מוגדר בספק למשחק",
    "Doubtful": "⚠️ דני בספק גדול למשחק",
    "Out": "❌ דני לא ישחק במשחק",
}
STATUS_UPDATE = {
    "Questionable": "⚠️ עדכון: דני הוגדר בספק למשחק {when}",
    "Doubtful": "⚠️ עדכון: דני בספק גדול למשחק {when}",
    "Out": "❌ עדכון: דני לא ישחק {when}",
    "Available": "✅ עדכון: דני כשיר וישחק {when}!",
}


def team_he(abbr: str) -> str:
    return TEAMS_HE.get(abbr, abbr)


def card_name(abbr: str) -> str:
    """‏בתמונה בלי ה' הידיעה: «לייקרס» ולא «הלייקרס»."""
    name = team_he(abbr)
    return name[1:] if name.startswith("ה") else name


# ---------------------------------------------------------------- זמנים

def preview_at(tip: dt.datetime) -> dt.datetime:
    """‏מתי לפרסם את הודעת המשחק: ב-12:00 ביום של המשחק. ‏«יום המשחק» של משחק ב-5:00
    בלילה הוא היום שלפניו, לכן מחסירים 8 שעות לפני שלוקחים את התאריך. ‏לכל המאוחר
    3 שעות לפני הפתיחה."""
    at = dt.datetime.combine(game_day(tip), dt.time(PREVIEW_HOUR), tzinfo=IL)
    return min(at, tip - dt.timedelta(hours=3)).astimezone(dt.timezone.utc)


def game_day(tip: dt.datetime) -> dt.date:
    """‏משחק לילה (עד 8:00) שייך ליום שלפניו."""
    return (tip.astimezone(IL) - dt.timedelta(hours=8)).date()


def when_word(tip: dt.datetime) -> str:
    h = tip.astimezone(IL).hour
    if h < 8 or h >= 21:
        return "הלילה"
    return "היום" if h < 17 else "הערב"


def clock(t: dt.datetime) -> str:
    il = t.astimezone(IL)
    return f"{il.hour}:{il.minute:02d}"


def date_he(t: dt.datetime) -> str:
    il = t.astimezone(IL)
    return f"{DAYS_HE[il.weekday()]} {il.day}.{il.month}"


# ---------------------------------------------------------------- נתונים

def schedule(team_id: str) -> list:
    """‏כל המשחקים של הקבוצה: מי בבית, נגד מי, איזה שלב. ‏DENI_SEASON - לבדיקות על עונה קודמת."""
    season = os.environ.get("DENI_SEASON")
    games = {}
    for st in (2, 3, 5):
        url = f"{ESPN}/teams/{team_id}/schedule?seasontype={st}" + (f"&season={season}" if season else "")
        try:
            data = get_json(url)
        except Exception:
            continue
        for e in data.get("events", []):
            c = e["competitions"][0]
            sides = {x["homeAway"]: {"id": x["team"]["id"], "abbr": x["team"]["abbreviation"]}
                     for x in c["competitors"]}
            home = sides["home"]["id"] == team_id
            games[e["id"]] = {
                "id": e["id"], "tip": parse_time(e["date"]), "home": home,
                "neutral": bool(c.get("neutralSite")), "type": st,
                "us": sides["home" if home else "away"], "them": sides["away" if home else "home"],
            }
    return sorted(games.values(), key=lambda g: g["tip"])


def team_look(team_id: str) -> dict:
    """‏צבעים ולוגו לתמונה. ‏הלוגו בגרסה לרקע כהה."""
    t = get_json(f"{ESPN}/teams/{team_id}")["team"]
    logos = [l["href"] for l in t.get("logos", [])]
    dark = [h for h in logos if "/500-dark/" in h]
    return {"logo": (dark or logos)[0], "color": t.get("color", ""), "alt": t.get("alternateColor", "")}


def parse_sport5(page: str) -> list:
    """‏[(ערוץ, «HH:MM», תיאור)] מלוח השידורים של ספורט 5."""
    rows, channel = [], ""
    pattern = r'<tr class="tr-header">.*?alt="([^"]*)"|<td class="date">\s*<div>\s*([\d:]+).*?<td class="text">(.*?)</td>'
    for m in re.finditer(pattern, page, re.S):
        if m.group(1) is not None:
            channel = m.group(1)
        else:
            rows.append((channel, m.group(2), html.unescape(re.sub(r"\s+", " ", m.group(3))).strip()))
    return rows


def sport5_channel(game: dict, page: Optional[str] = None) -> Optional[str]:
    """‏איפה המשחק משודר, לפי לוח השידורים של ספורט 5 (מתעדכן כמה ימים מראש). ‏None אם
    לא נמצא. ‏ספורט מובייל (האפליקציה) רק אם אין שידור בערוץ טלוויזיה."""
    il = game["tip"].astimezone(IL)
    if page is None:
        req = urllib.request.Request(SPORT5_URL.format(il.date()), headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    key = SPORT5_KEY.get(game["us"]["abbr"], team_he(game["us"]["abbr"]))
    found = []
    for channel, hhmm, text in parse_sport5(page):
        if "NBA" not in text or key not in text or "מוקלט" in text:
            continue
        h, m = map(int, hhmm.split(":"))
        if abs((il.replace(hour=h, minute=m) - il).total_seconds()) <= 90 * 60:
            found.append(channel)
    tv = [c for c in found if "מובייל" not in c]
    if tv:
        return SPORT5_NAMES.get(tv[0], tv[0])
    return "אפליקציית ספורט 5" if found else None


def injury(game: dict, official_only: bool = False) -> Optional[tuple]:
    """‏(סטטוס, סיבה). ‏Probable נחשב כשיר. ‏official_only: בלי הגיבוי של ESPN, כדי
    שתקלה רגעית בדוח הרשמי לא תיצור עדכון מזויף בערוץ."""
    st = tracker.official_status(game["tip"])
    if st is None:
        if official_only:
            return None
        st = tracker.espn_status(game["id"])
    s, reason = st
    return ("Available" if s == "Probable" else s), reason


def deni_box(data: dict) -> Optional[dict]:
    """‏השורה של דני ב-boxscore: {"MIN": "36", "PTS": "24", ..., "starter": bool,
    "dnp": bool, "reason": str}. ‏None אם הוא לא מופיע."""
    for team in data.get("boxscore", {}).get("players", []):
        for group in team.get("statistics", []):
            labels = group.get("labels") or []
            for a in group.get("athletes", []):
                if a.get("athlete", {}).get("id") != PLAYER_ID:
                    continue
                row = dict(zip(labels, a.get("stats") or []))
                row.update(starter=bool(a.get("starter")), reason=a.get("reason", "") or "",
                           dnp=bool(a.get("didNotPlay")) or not a.get("stats"))
                return row
    return None


def minutes(row: Optional[dict]) -> int:
    if not row or row["dnp"]:
        return 0
    raw = str(row.get("MIN", "0"))
    return int(raw) if raw.isdigit() else 0


def scores(data: dict, game: dict) -> tuple:
    """‏(שלנו, שלהם, מספר הארכות)."""
    comp = data["header"]["competitions"][0]
    pts = {c["team"]["id"]: int(c.get("score") or 0) for c in comp["competitors"]}
    periods = max(len(c.get("linescores") or []) for c in comp["competitors"])
    return pts[game["us"]["id"]], pts[game["them"]["id"]], max(periods - 4, 0)


# ---------------------------------------------------------------- טקסטים

def count(n, one: str, many: str) -> str:
    return f"{n} {one if str(n) == '1' else many}"


def opening(game: dict) -> str:
    us, them = team_he(game["us"]["abbr"]), team_he(game["them"]["abbr"])
    when = f"{when_word(game['tip'])} ({clock(game['tip'])})"
    if game["neutral"]:
        return f"{us} ודני פוגשים {when} את {them}🏀"
    if game["home"]:
        return f"{us} ודני מארחים {when} את {them}🏀"
    return f"{us} ודני מתארחים {when} אצל {them}🏀"


def on_tv(tv: str) -> str:
    return ("ב" if "֐" <= tv[0] <= "׿" else "ב-") + tv


def status_line(status: tuple) -> str:
    s, reason = status
    if s not in DOUBT:
        return ""
    r = tracker.reason_he(reason)
    return STATUS_LINE[s] + (f" ({r})" if r else "")


def preview_text(game: dict, tv: Optional[str], status: tuple, headline: str = "") -> str:
    """‏הודעת המשחק. ‏שורת פתיחה מיוחדת מאיתמר מחליפה את השורה האוטומטית."""
    parts = [headline.strip() or opening(game), status_line(status)]
    if tv:
        parts.append(f"המשחק משודר {on_tv(tv)}🔥")
    parts.append(LINKS_LINE)
    return "\n\n".join(p for p in parts if p)


def status_update_text(game: dict, status: tuple) -> str:
    s, reason = status
    text = STATUS_UPDATE[s].format(when=when_word(game["tip"]))
    r = tracker.reason_he(reason) if s in DOUBT else ""
    return text + (f" ({r})" if r else "")


def le(name: str) -> str:
    """‏«ל» לפני שם: «לדנבר», ו«ללייקרס» ולא «להלייקרס»."""
    return "ל" + (name[1:] if name.startswith("ה") else name)


def score(a: int, b: int) -> str:
    # ‏הגבוה קודם, כמו שאיתמר כתב בערוץ. ‏«61-58» נקרא משמאל לימין גם בתוך טקסט עברי.
    return f"{max(a, b)}-{min(a, b)}"


def made(shots: str) -> tuple:
    m, _, a = str(shots).partition("-")
    return (int(m), int(a)) if m.isdigit() and a.isdigit() else (0, 0)


def stats_lines(row: dict, full: bool) -> list:
    """‏רשימה אנכית, בסגנון של הערוץ. ‏full: הסטטיסטיקה המלאה של סוף המשחק."""
    lines = [count(row.get("PTS", 0), "נקודה", "נקודות")]
    if full:
        fg, three, ft = made(row.get("FG")), made(row.get("3PT")), made(row.get("FT"))
        two = (fg[0] - three[0], fg[1] - three[1])
        for (m, a), where in ((two, "לשתיים"), (three, "לשלוש"), (ft, "מהקו")):
            if a:
                lines.append(f"{m} מ-{a} {where}")
    lines += [count(row.get("REB", 0), "ריבאונד", "ריבאונדים"),
              count(row.get("AST", 0), "אסיסט", "אסיסטים")]
    if full:
        for key, one, many in (("STL", "חטיפה", "חטיפות"), ("BLK", "חסימה", "חסימות"),
                               ("TO", "איבוד", "איבודים")):
            if str(row.get(key, "0")) != "0":
                lines.append(count(row[key], one, many))
    lines.append(f"ב-{row.get('MIN', 0)} דקות")
    return lines


def half_text(game: dict, ours: int, theirs: int, row: dict) -> str:
    us, them = team_he(game["us"]["abbr"]), team_he(game["them"]["abbr"])
    if ours == theirs:
        line = f"{ours}-{theirs}, שוויון בין {us} {le(them)}"
    else:
        lead, trail = (us, them) if ours > theirs else (them, us)
        line = f"{score(ours, theirs)} {le(lead)} על {trail}"
    return "\n".join(["מחצית⏸️", line, "דני עם"] + stats_lines(row, full=False))


def day_phrase(tip: dt.datetime) -> str:
    """‏«בין שני לשלישי» למשחק לילה, אחרת «ביום שני» / «בשבת»."""
    names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    il = tip.astimezone(IL)
    day = names[il.weekday()]
    if il.hour < 8:
        return f"בין {names[(il.weekday() - 1) % 7]} ל{day}"
    return "בשבת" if day == "שבת" else f"ביום {day}"


def next_game_line(nxt: dict) -> str:
    """‏«משחק הבא בין שני לשלישי (5:00) נגד דנבר (בחוץ)». ‏משחק לילה נקרא לפי שני הימים."""
    side = "בבית" if nxt["home"] else "בחוץ"
    return f"משחק הבא {day_phrase(nxt['tip'])} ({clock(nxt['tip'])}) נגד {team_he(nxt['them']['abbr'])} ({side})"


def final_text(game: dict, ours: int, theirs: int, ot: int, row: Optional[dict],
               nxt: Optional[dict]) -> str:
    us, them = team_he(game["us"]["abbr"]), team_he(game["them"]["abbr"])
    extra = "" if not ot else " אחרי הארכה" if ot == 1 else f" אחרי {ot} הארכות"
    if ours > theirs:
        lines = [f"דני בניצחון {score(ours, theirs)} של {us} על {them}{extra}🔥"]
    else:
        lines = [f"{us} מפסידה {le(them)} {score(ours, theirs)}{extra}"]
    if minutes(row):
        lines += ["דני מסיים את המשחק עם"] + stats_lines(row, full=True)
    else:
        r = tracker.reason_he(row["reason"].title()) if row else ""
        if row and "COACH" in row["reason"].upper():
            r = "החלטת המאמן"
        lines.append("דני לא שיחק" + (f" ({r})" if r else ""))
    if nxt:
        lines += ["", next_game_line(nxt)]
    return "\n".join(lines)


# ---------------------------------------------------------------- טלגרם

def masked(text: str) -> str:
    return text if os.environ.get("DENI_SHOW") else re.sub(r"\d", "#", text)


def tg(method: str, params: dict, photo: Optional[bytes] = None):
    if DRY:
        shown = params.get("caption") or params.get("text") or params.get("question") or ""
        print(f"DRY {method} → {params.get('chat_id', '')}\n{masked(shown)}\n")
        if photo and os.environ.get("DENI_OUT"):
            open(os.path.join(os.environ["DENI_OUT"], f"{params.get('chat_id')}-{uuid.uuid4().hex[:6]}.jpg"), "wb").write(photo)
        return {"message_id": 1} if method != "getUpdates" else []
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if photo is None:
        body, ctype = json.dumps(params).encode(), "application/json"
    else:
        boundary = uuid.uuid4().hex
        chunks = []
        for k, v in params.items():
            v = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="game.jpg"\r\n'
                      f'Content-Type: image/jpeg\r\n\r\n'.encode() + photo + b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body, ctype = b"".join(chunks), f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        # ‏בלי ה-URL: יש בו את הטוקן
        raise RuntimeError(f"Telegram {method}: {json.load(e).get('description', e.code)}") from None


def is_admin(user: dict) -> bool:
    return bool(ADMIN) and str(user.get("id")) == ADMIN


def keyboard(gid: str) -> dict:
    b = lambda code: {"text": TV_CODES[code] or "בלי ערוץ", "callback_data": f"{gid}|tv|{code}"}
    return {"inline_keyboard": [
        [{"text": "✅ לפרסם עכשיו", "callback_data": f"{gid}|go"},
         {"text": "🚫 לא לפרסם", "callback_data": f"{gid}|skip"}],
        [b("s5"), b("s5p"), b("live")],
        [b("stars"), b("gold"), b("max")],
        [b("none")],
    ]}


# ---------------------------------------------------------------- מצב

def load_state() -> dict:
    try:
        return json.load(open(STATE_PATH))
    except (OSError, ValueError):
        return {"offset": 0, "games": {}}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    json.dump(state, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        open(out, "a").write("changed=true\n")


# ---------------------------------------------------------------- שלבים

def tv_for(game: dict, gs: dict) -> Optional[str]:
    """‏בחירה של איתמר גוברת על הזיהוי האוטומטי. ‏"" = בחר «בלי ערוץ»."""
    if "tv" in gs:
        return gs["tv"]
    try:
        return sport5_channel(game)
    except Exception:
        return None


def card_for(game: dict, status: tuple) -> bytes:
    import card
    us, them = game["us"], game["them"]
    return card.preview_card(
        {"name": card_name(us["abbr"]), **team_look(us["id"])},
        {"name": card_name(them["abbr"]), **team_look(them["id"])},
        f"{when_word(game['tip'])} {clock(game['tip'])}", date_he(game["tip"]),
        SEASON_LABEL.get(game["type"], ""),
        {"Questionable": "בספק למשחק", "Doubtful": "בספק גדול", "Out": "לא ישחק"}.get(status[0], ""),
        tracker.ICON,
    )


def draft_caption(game: dict, gs: dict) -> str:
    text = preview_text(game, gs.get("tv", gs.get("tv_auto")), tuple(gs["draft_status"]), gs.get("headline", ""))
    at = clock(preview_at(game["tip"]))
    head = "🚫 לא תתפרסם · ✅ מפרסם בכל זאת" if gs.get("skip") else f"📝 טיוטה · תתפרסם בערוץ ב-{at}"
    return (f"{head}\n\n{text}\n\n"
            "· כפתור: שינוי ערוץ השידור\n· הודעה כתובה: שורת פתיחה מיוחדת (‎/reset לביטול)")


def send_draft(game: dict, gs: dict) -> None:
    status = injury(game)
    gs["tv_auto"] = tv_for(game, {})
    gs["draft_status"] = list(status)
    msg = tg("sendPhoto", {"chat_id": ADMIN, "caption": draft_caption(game, gs),
                           "reply_markup": keyboard(game["id"])}, card_for(game, status))
    gs["draft"] = msg["message_id"]
    gs["draft_at"] = now_utc().isoformat()


def refresh_draft(game: dict, gs: dict) -> None:
    try:
        tg("editMessageCaption", {"chat_id": ADMIN, "message_id": gs["draft"],
                                  "caption": draft_caption(game, gs), "reply_markup": keyboard(game["id"])})
    except Exception as e:
        print("עדכון טיוטה נכשל:", e)


def publish_preview(game: dict, gs: dict) -> None:
    status = injury(game)
    tv = tv_for(game, gs)
    tg("sendPhoto", {"chat_id": CHANNEL, "caption": preview_text(game, tv, status, gs.get("headline", ""))},
       card_for(game, status))
    gs["preview"] = now_utc().isoformat()
    gs["status"] = status[0] if status[0] in DOUBT else "Available"
    print("נשלח")
    if gs.get("draft"):
        try:
            tg("editMessageReplyMarkup", {"chat_id": ADMIN, "message_id": gs["draft"],
                                          "reply_markup": {"inline_keyboard": []}})
            tg("sendMessage", {"chat_id": ADMIN, "text": "✅ פורסם בערוץ",
                               "reply_parameters": {"message_id": gs["draft"]}})
        except Exception as e:
            print("עדכון טיוטה נכשל:", e)


def post(text: str) -> None:
    tg("sendMessage", {"chat_id": CHANNEL, "text": text})
    print("נשלח")


def status_phase(game: dict, gs: dict, now: dt.datetime, data: Optional[dict]) -> None:
    """‏עדכון כשירות, רק כשמשהו השתנה ביחס למה שכבר נאמר בערוץ."""
    said = gs.get("status", "Available")
    if now < game["tip"]:
        status = injury(game, official_only=True)
        if status is None:
            return
        if (status[0] in DOUBT and status[0] != said) or (status[0] == "Available" and said in DOUBT):
            post(status_update_text(game, status))
            gs["status"] = status[0]
    elif data is not None and said in DOUBT:
        # ‏אחרי הפתיחה הדוח כבר לא מתעדכן. ‏מה שמכריע הוא ה-boxscore.
        row = deni_box(data)
        if row and (row["starter"] or minutes(row)):
            post("✅ דני על המגרש!")
            gs["status"] = "Available"


def process(game: dict, nxt: Optional[dict], state: dict, now: dt.datetime,
            prev: Optional[dict] = None) -> None:
    gs = state["games"].setdefault(game["id"], {})
    tip, pv = game["tip"], preview_at(game["tip"])

    if not gs.get("preview") and not gs.get("draft") and ADMIN and now < pv \
            and tracker.hold_until(now) is None:  # ‏איתמר שומר שבת: בלי טיוטה בשבת
        send_draft(game, gs)
        save_state(state)

    if not gs.get("preview") and not gs.get("skip") and (now >= pv or gs.get("go")) \
            and now < tip - dt.timedelta(minutes=10):
        publish_preview(game, gs)
        save_state(state)

    if gs.get("preview") and not gs.get("poll") and gs.get("status") == "Available" \
            and poll_at(tip) <= now < tip:
        safely(send_poll, game, gs)
        save_state(state)

    data = None
    if now >= tip:
        data = get_json(f"{ESPN}/summary?event={game['id']}")
        if tracker.game_status(data).get("name") in tracker.POSTPONED:
            if not gs.get("final"):
                post(f"📅 המשחק של {team_he(game['us']['abbr'])} נגד {team_he(game['them']['abbr'])} נדחה")
                gs["final"] = True
                save_state(state)
            return

    if gs.get("preview") and not gs.get("final") and now < tip + STATUS_UNTIL:
        status_phase(game, gs, now, data)
        save_state(state)

    if data is None:
        return
    st = tracker.game_status(data)
    if not gs.get("final"):
        if not gs.get("half") and HALF_WINDOW[0] <= now - tip <= HALF_WINDOW[1] \
                and st.get("name") == "STATUS_HALFTIME":
            row = deni_box(data)
            if minutes(row):  # ‏רק אם דני שיחק
                post(half_text(game, *scores(data, game)[:2], row))
            gs["half"] = True
            save_state(state)
        if st.get("completed"):
            publish_final(game, data, nxt)
            gs["final"], gs["final_at"] = True, now.isoformat()
            save_state(state)
    if gs.get("final_at"):
        after_final(game, gs, now, data, prev)
        highlights_phase(game, gs, now, data)
        save_state(state)


def final_card(game: dict, ours: int, theirs: int, ot: int, row: Optional[dict]) -> bytes:
    import card
    us, them = game["us"], game["them"]
    title = "סיום" if not ot else "סיום אחרי הארכה" if ot == 1 else f"סיום אחרי {ot} הארכות"
    if minutes(row):
        chip = (f"דני: {count(row.get('PTS', 0), 'נקודה', 'נקודות')} · "
                f"{count(row.get('REB', 0), 'ריבאונד', 'ריבאונדים')} · "
                f"{count(row.get('AST', 0), 'אסיסט', 'אסיסטים')}")
    else:
        chip = "דני לא שיחק"
    return card.score_card({"name": card_name(us["abbr"]), **team_look(us["id"])},
                           {"name": card_name(them["abbr"]), **team_look(them["id"])},
                           ours, theirs, title, chip, tracker.ICON)


def publish_final(game: dict, data: dict, nxt: Optional[dict]) -> None:
    """‏הודעת הסיום, עם תמונת התוצאה. ‏אם התמונה נכשלת - הטקסט יוצא בלעדיה."""
    ours, theirs, ot = scores(data, game)
    row = deni_box(data)
    text = final_text(game, ours, theirs, ot, row, nxt)
    try:
        photo = final_card(game, ours, theirs, ot, row)
    except Exception as e:
        print("תמונה נכשלה:", type(e).__name__)
        post(text)
        return
    tg("sendPhoto", {"chat_id": CHANNEL, "caption": text}, photo)
    print("נשלח")


def safely(fn, *args) -> None:
    """‏לתוספות (סקר, אבני דרך, מפת זריקות, השבוע, ראיונות): תקלה באחת מהן לא תעצור את
    ההודעות העיקריות. ‏בלוג רק סוג השגיאה, בלי תוכן."""
    try:
        fn(*args)
    except Exception as e:
        print(f"{fn.__name__} נכשל:", type(e).__name__)


# ---------------------------------------------------------------- סקר

POLL_OPTIONS = [("פחות מ-15", 0, 14), ("15 עד 19", 15, 19), ("20 עד 24", 20, 24),
                ("25 עד 29", 25, 29), ("30 ומעלה", 30, 999)]
POLL_AFTER = dt.timedelta(hours=3)


def poll_at(tip: dt.datetime) -> dt.datetime:
    """‏3 שעות אחרי הודעת המשחק, ולכל המאוחר שעה לפני הפתיחה."""
    return min(preview_at(tip) + POLL_AFTER, tip - dt.timedelta(hours=1))


def send_poll(game: dict, gs: dict) -> None:
    msg = tg("sendPoll", {"chat_id": CHANNEL, "question": f"כמה נקודות דני יקלע {when_word(game['tip'])}? 🏀",
                          "options": [{"text": o[0]} for o in POLL_OPTIONS]})
    gs["poll"] = msg["message_id"]
    print("נשלח")


def poll_answer(row: Optional[dict]) -> str:
    if not minutes(row):
        return "דני לא שיחק בסוף, אז אין תשובה הפעם"
    pts = int(row.get("PTS") or 0)
    option = next(o[0] for o in POLL_OPTIONS if o[1] <= pts <= o[2])
    return f"✅ התשובה: {option} (דני קלע {count(pts, 'נקודה', 'נקודות')})"


def close_poll(gs: dict, data: dict) -> None:
    gs["poll_closed"] = True
    try:
        tg("stopPoll", {"chat_id": CHANNEL, "message_id": gs["poll"]})
    except Exception as e:
        print("סגירת הסקר נכשלה:", type(e).__name__)
    tg("sendMessage", {"chat_id": CHANNEL, "text": poll_answer(deni_box(data)),
                       "reply_parameters": {"message_id": gs["poll"]}})
    print("נשלח")


# ---------------------------------------------------------------- אבני דרך

STATS = ("PTS", "REB", "AST", "STL", "BLK")
HIGH_MIN = {"PTS": 20, "REB": 10, "AST": 8}   # ‏מתחת לזה «שיא» הוא כנראה תקלה בנתונים
TOTAL_STEP = {"PTS": 1000, "REB": 500, "AST": 500}
STAT_HE = {"PTS": "נקודות", "REB": "ריבאונדים", "AST": "אסיסטים"}
# ‏הפליי-אין נקרא ב-ESPN «Play In Regular Season», לכן נבדק לפני העונה הסדירה.
SEASON_KIND = (("Play In", 5), ("Play-In", 5), ("Postseason", 3), ("Regular Season", 2))


def num(v) -> int:
    v = str(v or "0").replace(",", "")
    return int(v) if v.isdigit() else 0


def career_log() -> list:
    """‏כל המשחקים של דני ב-NBA (בלי משחקי הכנה ובלי אולסטאר), מה-gamelog של ESPN, עונה אחרי
    עונה: [{"id", "type", "season", "MIN", "PTS", ...}]. ‏נבדק מול הסיכומים העונתיים של ESPN.
    ‏משחקי האולסטאר מופיעים שם בתוך העונה הסדירה, בקבוצות כמו WORLD (מזהה גבוה מ-30)."""
    url = f"{ESPN_WEB}/athletes/{PLAYER_ID}/gamelog"
    first = get_json(url)
    seasons = [o["value"] for f in first.get("filters", []) if f.get("name") == "season" for o in f["options"]]
    if not seasons:
        raise RuntimeError("אין רשימת עונות")
    out = []
    for y in seasons:
        d = get_json(f"{url}?season={y}")
        labels = d.get("labels", [])
        for st in d.get("seasonTypes", []):
            kind = next((k for name, k in SEASON_KIND if name in st.get("displayName", "")), None)
            if kind is None:
                continue
            for c in st.get("categories", []):
                if c.get("type") != "event":
                    continue
                for e in c.get("events", []):
                    team = (d.get("events", {}).get(str(e["eventId"])) or {}).get("team", {}).get("id", "0")
                    if not 1 <= num(team) <= 30:
                        continue
                    row = dict(zip(labels, e.get("stats", [])))
                    out.append({"id": str(e["eventId"]), "type": kind, "season": int(y),
                                **{k: num(row.get(k)) for k in ("MIN",) + STATS}})
    return out


def ordinal(n: int, first: str) -> str:
    return first if n == 1 else f"ה-{n}"


def milestones(game: dict, row: dict, log: list) -> list:
    """‏מה מיוחד במשחק הזה, ביחס לכל המשחקים הקודמים של דני. ‏log בלי המשחק הנוכחי.
    ‏רף בקריירה ומספר משחקים נספרים רק בעונה הסדירה, כמו ב-NBA."""
    cur = {k: num(row.get(k)) for k in STATS}
    lines = []
    for k in ("PTS", "REB", "AST"):
        best = max((g[k] for g in log), default=0)
        if cur[k] >= HIGH_MIN[k] and cur[k] > best:
            lines.append(f"🏆 שיא קריירה לדני: {cur[k]} {STAT_HE[k]}!")
        elif cur[k] >= HIGH_MIN[k] and cur[k] == best:
            lines.append(f"🏆 דני השווה את שיא הקריירה שלו: {cur[k]} {STAT_HE[k]}")
    tens = lambda r: sum(r[k] >= 10 for k in STATS)
    if tens(cur) >= 3:
        n = 1 + sum(tens(g) >= 3 for g in log)
        lines.append(f"🔥 טריפל-דאבל לדני! {ordinal(n, 'הראשון')} בקריירה")
    elif tens(cur) == 2 and game["type"] == 2:
        season = max((g["season"] for g in log), default=0)
        n = 1 + sum(tens(g) == 2 for g in log if g["season"] == season and g["type"] == 2)
        lines.append(f"💪 דאבל-דאבל לדני, {ordinal(n, 'הראשון')} שלו העונה")
    if game["type"] == 2:
        regular = [g for g in log if g["type"] == 2]
        for k, step in TOTAL_STEP.items():
            before = sum(g[k] for g in regular)
            after = before + cur[k]
            if after // step > before // step:
                lines.append(f"🎉 דני עבר את רף {after // step * step:,} ה{STAT_HE[k]} בקריירה ב-NBA!")
        n = 1 + sum(g["MIN"] > 0 for g in regular)
        if n % 100 == 0:
            lines.append(f"🎂 המשחק ה-{n} של דני בעונה הסדירה של ה-NBA")
    return lines


def log_has_previous(log: list, prev: Optional[dict]) -> bool:
    """‏ה-gamelog מתעדכן באיחור. ‏אם חסר בו המשחק הקודם, השיאים והסכומים לא נכונים."""
    if prev is None or prev["id"] in {g["id"] for g in log}:
        return True
    return not minutes(deni_box(get_json(f"{ESPN}/summary?event={prev['id']}")))


def milestones_phase(game: dict, gs: dict, row: dict, prev: Optional[dict]) -> None:
    log = [g for g in career_log() if g["id"] != game["id"]]
    if not log_has_previous(log, prev):
        return   # ‏ננסה שוב בריצה הבאה
    gs["milestones"] = True
    lines = milestones(game, row, log)
    if lines:
        post("\n".join(lines))


# ---------------------------------------------------------------- מפת זריקות

def deni_shots(data: dict) -> list:
    """‏[(x, y, נכנסה)] של הזריקות מהשדה של דני (בלי עונשין). ‏זריקה בלי מיקום תקין היא None,
    ואז אין תמונה."""
    out = []
    for p in data.get("plays", []):
        parts = p.get("participants") or []
        if not p.get("shootingPlay") or not parts or parts[0].get("athlete", {}).get("id") != PLAYER_ID:
            continue
        if "free throw" in (p.get("type") or {}).get("text", "").lower():
            continue
        c = p.get("coordinate") or {}
        x, y = c.get("x"), c.get("y")
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and -5 <= x <= 55 and -10 <= y <= 90):
            out.append(None)
            continue
        if is_heave(p, x, y):
            continue
        out.append((x, y, bool(p.get("scoringPlay"))))
    return out


def is_heave(p: dict, x: float, y: float) -> bool:
    """‏מהעונה 2025-26: החטאה מעבר ל-36 רגל בשלוש השניות האחרונות של רבע 1-3 לא נספרת כזריקה
    של השחקן, ולכן גם לא ב-boxscore."""
    clock = (p.get("clock") or {}).get("displayValue", "")
    secs = float(clock) if re.fullmatch(r"\d+(\.\d+)?", clock) else 99
    return (not p.get("scoringPlay") and (p.get("period") or {}).get("number", 4) <= 3 and secs <= 3
            and ((x - 25) ** 2 + y ** 2) ** 0.5 > 36)


SHOTS_WAIT = dt.timedelta(hours=1)   # ‏ה-play-by-play משלים לפעמים באיחור


def shots_phase(game: dict, gs: dict, now: dt.datetime, data: dict, row: dict) -> None:
    import card
    fg, three = made(row.get("FG")), made(row.get("3PT"))
    shots = deni_shots(data)
    if fg[1] == 0 or len(shots) != fg[1] or None in shots:
        if fg[1] == 0 or now - parse_time(gs["final_at"]) > SHOTS_WAIT:
            gs["shots"] = True
        return
    two = (fg[0] - three[0], fg[1] - three[1])
    lines = [f"{fg[0]} מ-{fg[1]} מהשדה"] + [f"{m} מ-{a} {where}" for (m, a), where in
                                             ((two, "לשתיים"), (three, "לשלוש")) if a]
    photo = card.shot_card(team_look(game["us"]["id"]), "מפת הזריקות",
                           f"נגד {card_name(game['them']['abbr'])} · {date_he(game['tip'])}",
                           shots, lines, tracker.ICON)
    tg("sendPhoto", {"chat_id": CHANNEL, "caption": f"🎯 הזריקות של דני נגד {team_he(game['them']['abbr'])}"}, photo)
    gs["shots"] = True
    print("נשלח")


def after_final(game: dict, gs: dict, now: dt.datetime, data: dict, prev: Optional[dict]) -> None:
    """‏מה שיוצא אחרי הודעת הסיום: תשובה לסקר, אבני דרך ומפת זריקות. ‏כל אחד פעם אחת."""
    if gs.get("poll") and not gs.get("poll_closed"):
        safely(close_poll, gs, data)
    row = deni_box(data)
    if not minutes(row):
        return
    if not gs.get("milestones") and now - parse_time(gs["final_at"]) < GAME_UNTIL:
        safely(milestones_phase, game, gs, row, prev)
    if not gs.get("shots"):
        safely(shots_phase, game, gs, now, data, row)


# ---------------------------------------------------------------- ראיונות

INTERVIEW_WORDS = ("Postgame", "Media Availability", "Interview", "Press Conference")


def interviews_phase(state: dict, now: dt.datetime, abbr: str) -> None:
    """‏ראיון או מסיבת עיתונאים של דני ביוטיוב של הקבוצה, גם בימים בלי משחק. ‏בודקים פעם בחצי
    שעה (הריצות כל 5 דקות), ורק סרטונים מה-24 השעות האחרונות."""
    cid = TEAM_YOUTUBE.get(abbr)
    if not cid or now.minute % 30 >= 5:
        return
    posted = state.setdefault("yt_posted", [])
    new = False
    for title, link, pub in sorted(youtube(cid), key=lambda v: v[2]):
        if link in posted or now - pub >= dt.timedelta(hours=24) or "Highlights" in title:
            continue
        if tracker.LAST_NAME not in title or not any(w in title for w in INTERVIEW_WORDS):
            continue
        post(("🎙️ דני אחרי המשחק" if "Postgame" in title else "🎙️ דני מדבר עם התקשורת") + f"\n{link}")
        posted.append(link)
        new = True
    if new:
        state["yt_posted"] = posted[-30:]
        save_state(state)


# ---------------------------------------------------------------- השבוע של דני
# ‏ביום ראשון: כל המשחקים של השבוע (ראשון עד שבת, לפי «יום המשחק»), עם ערוץ השידור אם הוא
# ‏כבר ידוע (ספורט 5 מפרסם כ-5 ימים מראש). ‏טיוטה לאיתמר 3 שעות לפני, כמו בהודעת המשחק.

WEEKLY_HOUR = CFG.get("weekly_hour", 11)
WEEKLY_UNTIL = dt.timedelta(hours=8)   # ‏אם הבוט לא רץ עד אז, מוותרים על השבוע הזה


def week_sunday(now: dt.datetime) -> dt.date:
    d = now.astimezone(IL).date()
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def week_games(games: list, sunday: dt.date) -> list:
    return [g for g in games if sunday <= game_day(g["tip"]) <= sunday + dt.timedelta(days=6)]


def week_text(rows: list) -> str:
    """‏rows: [(game, ערוץ או None)]."""
    lines = []
    for g, tv in rows:
        side = "בבית" if g["home"] else "בחוץ"
        line = f"🔸 {day_phrase(g['tip'])} ({clock(g['tip'])}) נגד {team_he(g['them']['abbr'])} ({side})"
        lines.append(line + (f" · {tv}" if tv else ""))
    return "השבוע של דני🗓️\n\n" + "\n".join(lines)


def week_post(gl: list) -> tuple:
    """‏(טקסט, תמונה)."""
    import card
    rows = [(g, tv_for(g, {})) for g in gl]
    # ‏התאריכים בתמונה הם התאריכים בפועל (משחק לילה ב-5:00 בבוקר של יום ראשון הבא שייך לשבוע הזה)
    first, last = gl[0]["tip"].astimezone(IL), gl[-1]["tip"].astimezone(IL)
    span = f"{first.day}.{first.month}" + (f" – {last.day}.{last.month}" if last.date() != first.date() else "")
    photo = card.week_card(team_look(gl[0]["us"]["id"]), "השבוע של דני", span,
                           [{"date": date_he(g["tip"]), "time": clock(g["tip"]), "name": card_name(g["them"]["abbr"]),
                             "logo": team_look(g["them"]["id"])["logo"], "side": "בית" if g["home"] else "חוץ",
                             "tv": tv or ""} for g, tv in rows])
    return week_text(rows), photo


def weekly_phase(state: dict, games: list, now: dt.datetime) -> None:
    sunday = week_sunday(now)
    wk = state.get("weekly") or {}
    if wk.get("key") != sunday.isoformat():
        wk = {"key": sunday.isoformat()}
    at = dt.datetime.combine(sunday, dt.time(WEEKLY_HOUR), tzinfo=IL)
    if wk.get("posted") or wk.get("skip") or not at - DRAFT_LEAD <= now < at + WEEKLY_UNTIL:
        return
    gl = week_games(games, sunday)
    if not gl:
        return
    if not wk.get("draft") and ADMIN and now < at and tracker.hold_until(now) is None:
        text, photo = week_post(gl)
        msg = tg("sendPhoto", {"chat_id": ADMIN, "caption": f"📝 טיוטה · תתפרסם בערוץ ב-{WEEKLY_HOUR}:00\n\n{text}",
                               "reply_markup": {"inline_keyboard": [[
                                   {"text": "✅ לפרסם עכשיו", "callback_data": "wk|go"},
                                   {"text": "🚫 לא לפרסם", "callback_data": "wk|skip"}]]}}, photo)
        wk["draft"] = msg["message_id"]
        state["weekly"] = wk
        save_state(state)
    if now >= at or wk.get("go"):
        text, photo = week_post(gl)
        tg("sendPhoto", {"chat_id": CHANNEL, "caption": text}, photo)
        print("נשלח")
        wk["posted"] = True
        state["weekly"] = wk
        save_state(state)
        if wk.get("draft"):
            close_weekly_draft(wk, "✅ פורסם בערוץ")


def close_weekly_draft(wk: dict, note: str) -> None:
    try:
        tg("editMessageReplyMarkup", {"chat_id": ADMIN, "message_id": wk["draft"],
                                      "reply_markup": {"inline_keyboard": []}})
        tg("sendMessage", {"chat_id": ADMIN, "text": note, "reply_parameters": {"message_id": wk["draft"]}})
    except Exception as e:
        print("עדכון טיוטה נכשל:", type(e).__name__)


def weekly_answer(state: dict, action: str) -> None:
    wk = state.get("weekly")
    if not wk or wk.get("posted") or wk.get("skip"):
        return
    if action == "go":
        wk["go"] = True
    elif action == "skip":
        wk["skip"] = True
        close_weekly_draft(wk, "🚫 לא יתפרסם")


# ---------------------------------------------------------------- היילייטס
# ‏רק קישורים למקורות רשמיים (יוטיוב של הקבוצה ושל ה-NBA). ‏לא ESPN: שם כל מהלך בודד הוא
# ‏סרטון עם השם של דני, והקישורים פגים אחרי זמן קצר. ‏לא מעלים סרטונים מחדש:
# ‏הזכויות של ה-NBA. ‏בטלגרם קישור ליוטיוב מוצג עם תמונה וכפתור הפעלה.

TEAM_YOUTUBE = {"POR": "UCXk66yyzXo7-2M1BMqLhltQ"}   # ‏קבוצה חדשה אחרי טרייד: להוסיף כאן
NBA_YOUTUBE = "UCWJ2lWNubArHWmf3FIHbfcQ"
HL_WAIT = dt.timedelta(minutes=60)    # ‏כמה מחכים לסרטון של דני לפני שמסתפקים בתקציר המשחק
HL_UNTIL = dt.timedelta(hours=4)      # ‏אחרי זה מפסיקים לחפש


def youtube(channel_id: str) -> list:
    """‏[(כותרת, קישור, זמן פרסום)]: מה-RSS של הערוץ (15 האחרונים, בלי מפתח). ‏ה-RSS של יוטיוב
    מחזיר לפעמים 404 לכל הערוצים (כך ב-29.10.26), ואז קוראים את דף הסרטונים של הערוץ."""
    try:
        return youtube_rss(channel_id)
    except Exception:
        return youtube_page(get_text(f"https://www.youtube.com/channel/{channel_id}/videos"), now_utc())


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"})
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")


def youtube_rss(channel_id: str) -> list:
    page = get_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", page, re.S):
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        link = re.search(r'<link rel="alternate" href="([^"]+)"', e)
        pub = re.search(r"<published>(.*?)</published>", e)
        if title and link and pub:
            out.append((html.unescape(title.group(1)), link.group(1), parse_time(pub.group(1))))
    return out


# ‏«5 hours ago» או בקיצור «5h ago» (כך יוטיוב מציג כרגע). ‏mo לפני m, כדי ש-«2mo» לא ייקרא כדקות.
AGO = [("mo", 2592000), ("s", 1), ("m", 60), ("h", 3600), ("d", 86400), ("w", 604800), ("y", 31536000)]


def youtube_page(page: str, now: dt.datetime) -> list:
    """‏דף הסרטונים של ערוץ. ‏אין שם זמן מדויק, רק «לפני 5 שעות». ‏יוטיוב מעגל כלפי מטה, ולכן
    הזמן שמחושב מאוחר מהאמיתי: תקציר של משחק קודם («לפני יום») לא ייראה כחדש."""
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", page, re.S)
    if not m:
        raise RuntimeError("דף יוטיוב בלי ytInitialData")
    out = []

    def walk(o):
        if isinstance(o, dict):
            lock = o.get("lockupViewModel")
            if isinstance(lock, dict) and lock.get("contentId"):
                md = lock.get("metadata", {}).get("lockupMetadataViewModel", {})
                title = md.get("title", {}).get("content", "")
                rows = md.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
                parts = " ".join(p.get("text", {}).get("content", "") for r in rows for p in r.get("metadataParts", []))
                ago = re.search(r"(\d+)\s*([a-z]+) ago", parts)
                unit = ago and next((sec for pre, sec in AGO if ago.group(2).startswith(pre)), None)
                if title and unit:
                    pub = now - dt.timedelta(seconds=int(ago.group(1)) * unit)
                    out.append((title, f"https://www.youtube.com/watch?v={lock['contentId']}", pub))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(json.loads(m.group(1)))
    return out


def find_videos(game: dict, data: dict) -> dict:
    """‏{"deni": קישור או None, "game": קישור או None}, מהיוטיוב של הקבוצה ושל ה-NBA."""
    them = next((c["team"] for c in data["header"]["competitions"][0]["competitors"]
                 if c["team"]["id"] == game["them"]["id"]), {})
    them_names = [n for n in (them.get("name"), them.get("location")) if n]
    found = {"deni": None, "game": None}
    feeds = [TEAM_YOUTUBE.get(game["us"]["abbr"]), NBA_YOUTUBE]
    for cid in filter(None, feeds):
        try:
            videos = youtube(cid)
        except Exception:
            continue
        for title, link, pub in videos:
            if pub < game["tip"]:
                continue
            if not found["deni"] and tracker.LAST_NAME in title and "Highlights" in title:
                found["deni"] = link
            if not found["game"] and cid != NBA_YOUTUBE and title.startswith("Game Highlights") \
                    and any(n in title for n in them_names):
                found["game"] = link
    return found


def highlights_phase(game: dict, gs: dict, now: dt.datetime, data: dict) -> None:
    """‏אחרי הסיום: סרטון של דני אם יש. ‏אם אין תוך שעה - תקציר המשחק. ‏סרטון של דני
    שמגיע אחרי התקציר עדיין מתפרסם."""
    since = now - parse_time(gs["final_at"])
    if gs.get("hl_deni") or since > HL_UNTIL:
        return
    played = bool(minutes(deni_box(data)))
    found = find_videos(game, data)
    if played and found["deni"]:
        post(f"🎥 ההיילייטס של דני מהמשחק\n{found['deni']}")
        gs["hl_deni"] = True
    elif found["game"] and not gs.get("hl_game") and (since >= HL_WAIT or not played):
        post(f"🎥 תקציר המשחק\n{found['game']}")
        gs["hl_game"] = True


def highlights_now() -> None:
    """‏ידני (Run workflow, mode=highlights): ההיילייטס של המשחק האחרון שהסתיים, אם החיפוש
    האוטומטי פספס או שהקישור נמחק. ‏אותה עדיפות כמו ב-highlights_phase, בלי לחכות שעה."""
    now = now_utc()
    for g in reversed(schedule(os.environ.get("DENI_TEAM") or tracker.current_team_id())):
        if g["tip"] >= now:
            continue
        data = get_json(f"{ESPN}/summary?event={g['id']}")
        if not tracker.game_status(data).get("completed"):
            continue
        found = find_videos(g, data)
        if minutes(deni_box(data)) and found["deni"]:
            post(f"🎥 ההיילייטס של דני מהמשחק\n{found['deni']}")
        elif found["game"]:
            post(f"🎥 תקציר המשחק\n{found['game']}")
        else:
            print("לא נמצא סרטון")
        return


def handle_updates(state: dict, games: list) -> None:
    """‏מה איתמר לחץ או כתב לבוט בפרטי מאז הריצה הקודמת."""
    params = {"offset": state.get("offset", 0), "timeout": 0, "allowed_updates": ["message", "callback_query"]}
    try:
        updates = tg("getUpdates", params)
    except RuntimeError as e:
        # ‏הבוט שימש בעבר את Make, שהגדיר לו webhook. ‏כל עוד הוא קיים, getUpdates נחסם.
        if "webhook" not in str(e).lower():
            raise
        tg("deleteWebhook", {})
        updates = tg("getUpdates", params)
    by_id = {g["id"]: g for g in games}
    touched = set()
    for u in updates:
        state["offset"] = u["update_id"] + 1
        if "callback_query" in u:
            q = u["callback_query"]
            if not is_admin(q["from"]):
                continue
            try:
                tg("answerCallbackQuery", {"callback_query_id": q["id"]})
            except Exception:
                pass  # ‏עבר יותר מדי זמן מהלחיצה (הריצות כל 5 דקות). ‏לא חשוב.
            gid, action, *rest = q.get("data", "").split("|") + [""]
            if gid == "ann":
                announce_answer(state, action)
                continue
            if gid == "wk":
                weekly_answer(state, action)
                continue
            gs = state["games"].get(gid)
            if not gs or gs.get("preview"):
                continue
            if action == "go":
                gs["go"], gs["skip"] = True, False
            elif action == "skip":
                gs["skip"], gs["go"] = True, False
                touched.add(gid)
            elif action == "tv" and rest[0] in TV_CODES:
                gs["tv"] = TV_CODES[rest[0]]
                touched.add(gid)
        elif "message" in u:
            m = u["message"]
            if m.get("chat", {}).get("type") != "private":
                continue
            text = (m.get("text") or "").strip()
            if text.startswith("/start"):
                tg("sendMessage", {"chat_id": m["chat"]["id"],
                                   "text": f"✅ מחובר. המזהה שלך: {m['from']['id']}"})
                continue
            if not is_admin(m["from"]) or not text:
                continue
            open_drafts = [gid for gid, gs in state["games"].items() if gs.get("draft") and not gs.get("preview")]
            if not open_drafts:
                tg("sendMessage", {"chat_id": ADMIN, "text": "אין כרגע טיוטה פתוחה"})
                continue
            gid = open_drafts[-1]
            state["games"][gid]["headline"] = "" if text == "/reset" else text
            touched.add(gid)
    if updates:
        save_state(state)
    for gid in touched:
        if gid in by_id:
            refresh_draft(by_id[gid], state["games"][gid])


# ---------------------------------------------------------------- פוסט החזרה (חד-פעמי)
# ‏איתמר ביקש פוסט «חוזרים לעדכן» עם סיכום קצר של המשחקים שכבר היו. ‏⛔ התוצאות לא עוברות
# ‏דרך הצ'אט או הטרמינל: הפוסט נבנה ב-Actions (`mode=announce`) ונשלח לאיתמר בפרטי עם
# ‏כפתורים, והריצה הרגילה מפרסמת אותו בערוץ רק אחרי שהוא לחץ «לפרסם».

ANNOUNCE_INTRO = """חוזרים לעדכן! 🏀🔥

הערוץ חוזר לפעול, והפעם עם עדכונים קבועים לכל משחק של דני ופורטלנד:
📣 ביום המשחק: מתי, נגד מי ואיפה משודר
⚠️ אם דני בספק למשחק, ועדכון כשיש החלטה
⏸️ במחצית: התוצאה והמספרים של דני
🏁 בסיום: התוצאה, הסטטיסטיקה המלאה והמשחק הבא"""


def season_label(t: dt.datetime) -> str:
    y = t.year if t.month >= 8 else t.year - 1
    return f"עונת {y}/{(y + 1) % 100:02d}"


def recap_line(game: dict, data: dict, first: bool) -> str:
    """‏שורה קצרה על משחק שכבר היה: תוצאה, ושלושת המספרים העיקריים של דני."""
    ours, theirs, ot = scores(data, game)
    il = game["tip"].astimezone(IL)
    when = "פתיחת העונה" if first else f"{il.day}.{il.month}"
    side = "בבית" if game["home"] else "בחוץ"
    result = "ניצחון" if ours > theirs else "הפסד"
    extra = " אחרי הארכה" if ot == 1 else f" אחרי {ot} הארכות" if ot else ""
    head = f"🔸 {when}, {side} מול {team_he(game['them']['abbr'])}: {result} {score(ours, theirs)}{extra}"
    row = deni_box(data)
    if minutes(row):
        deni = (f"דני: {count(row.get('PTS', 0), 'נקודה', 'נקודות')}, "
                f"{count(row.get('REB', 0), 'ריבאונד', 'ריבאונדים')}, "
                f"{count(row.get('AST', 0), 'אסיסט', 'אסיסטים')} ב-{row.get('MIN', 0)} דקות")
    else:
        deni = "דני לא שיחק"
    return f"{head}\n{deni}"


def announce_text(past: list, nxt: Optional[dict]) -> str:
    """‏past: [(game, summary)] של המשחקים שכבר נגמרו העונה, לפי הסדר."""
    parts = [ANNOUNCE_INTRO]
    if past:
        parts.append("מה היה עד עכשיו:\n" + "\n\n".join(
            recap_line(g, d, i == 0 and g["type"] == 2) for i, (g, d) in enumerate(past)))
    if nxt:
        parts.append(next_game_line(nxt))
    return "\n\n".join(parts)


def announce(state: dict) -> None:
    import card
    now = now_utc()
    team = os.environ.get("DENI_TEAM") or tracker.current_team_id()
    games = schedule(team)
    nxt = next((g for g in games if g["tip"] > now), None)
    start = dt.datetime(now.year if now.month >= 8 else now.year - 1, 8, 1, tzinfo=dt.timezone.utc)
    past = []
    for g in games:
        if start <= g["tip"] < now:
            data = get_json(f"{ESPN}/summary?event={g['id']}")
            if tracker.game_status(data).get("completed"):
                past.append((g, data))
    text = announce_text(past, nxt)
    if len(text) > 1024:  # ‏מגבלת כיתוב של תמונה בטלגרם
        raise RuntimeError("הפוסט ארוך מדי")
    old = state.get("announce")
    if old and not old.get("done"):  # ‏טיוטה קודמת: בלי כפתורים, כדי שלא תפורסם בטעות
        try:
            tg("editMessageReplyMarkup", {"chat_id": ADMIN, "message_id": old["draft"],
                                          "reply_markup": {"inline_keyboard": []}})
        except Exception as e:
            print("עדכון טיוטה נכשל:", e)
    look = team_look(team)
    photo = card.announce_card(look, "חוזרים לעדכן!",
                               [season_label(now), "כל משחק של דני ופורטלנד", "לפני, במהלך ואחרי"], tracker.ICON)
    msg = tg("sendPhoto", {"chat_id": ADMIN, "caption": text, "reply_markup": {"inline_keyboard": [[
        {"text": "✅ לפרסם בערוץ", "callback_data": "ann|go"},
        {"text": "🚫 לבטל", "callback_data": "ann|no"}]]}}, photo)
    tg("sendMessage", {"chat_id": ADMIN, "text": "☝️ טיוטה לפוסט החזרה. כך בדיוק הוא ייראה בערוץ. "
                                                "הפרסום יוצא תוך 5 דקות מהלחיצה."})
    state["announce"] = {"draft": msg.get("message_id"), "caption": text,
                         "photo": (msg.get("photo") or [{}])[-1].get("file_id", "")}
    save_state(state)
    print("נשלח")


def announce_answer(state: dict, action: str) -> None:
    ann = state.get("announce")
    if not ann or ann.get("done"):
        return
    if action == "go":
        tg("sendPhoto", {"chat_id": CHANNEL, "photo": ann["photo"], "caption": ann["caption"]})
        print("נשלח")
    ann["done"] = True
    save_state(state)
    try:
        tg("editMessageReplyMarkup", {"chat_id": ADMIN, "message_id": ann["draft"],
                                      "reply_markup": {"inline_keyboard": []}})
        tg("sendMessage", {"chat_id": ADMIN, "text": "✅ פורסם בערוץ" if action == "go" else "🚫 בוטל",
                           "reply_parameters": {"message_id": ann["draft"]}})
    except Exception as e:
        print("עדכון טיוטה נכשל:", e)


def run() -> None:
    if not DRY and not (TOKEN and CHANNEL):
        print("הבוט לא מוגדר")
        return
    state = load_state()
    now = now_utc()
    games = schedule(os.environ.get("DENI_TEAM") or tracker.current_team_id())
    handle_updates(state, games)
    safely(weekly_phase, state, games, now)
    if games:
        safely(interviews_phase, state, now, games[0]["us"]["abbr"])
    active = False
    for i, g in enumerate(games):
        if preview_at(g["tip"]) - DRAFT_LEAD <= now <= g["tip"] + GAME_UNTIL:
            active = True
            process(g, games[i + 1] if i + 1 < len(games) else None, state, now, games[i - 1] if i else None)
    # ‏ניקוי משחקים ישנים
    old = [gid for gid in state["games"] if gid not in {g["id"] for g in games}
           or next(g for g in games if g["id"] == gid)["tip"] < now - dt.timedelta(days=3)]
    for gid in old:
        del state["games"][gid]
    if old:
        save_state(state)
    print("בדיקה הסתיימה" if active else "אין משחק קרוב")


if __name__ == "__main__":
    if sys.argv[1:] == ["announce"]:
        if DRY or (TOKEN and CHANNEL and ADMIN):
            announce(load_state())
    elif sys.argv[1:] == ["highlights"]:
        if DRY or (TOKEN and CHANNEL):
            highlights_now()
    else:
        run()
