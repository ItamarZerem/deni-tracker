#!/usr/bin/env python3
"""מעקב בלי ספוילרים אחרי דני אבדיה.

‏`python3 tracker.py check` רץ ב-GitHub Actions כל 10 דקות. ‏כל ריצה קוראת את לוח
המשחקים בעצמה ומחליטה לפי חלון הזמן סביב המשחק הקרוב: לפני (דוח פציעות), במהלך
(«על המגרש») ואחרי (שיחק / לא / פחות מ-10). ‏מחוץ לחלונות - יוצאת בלי לעשות כלום.
‏אין לוח זמנים שצריך לרענן, ואין תלות במק.

⛔ כלל הברזל: שום תוצאה, ניקוד, סטטיסטיקה או מנצח לא נכתבים להודעה ולא ללוג
(הלוגים של Actions נראים בדף הריפו). מה שמותר לצאת: שיחק / לא שיחק / פחות מ-10 דק',
וסטטוס פציעה מלפני המשחק.

תואם Python 3.9 (הפייתון של המערכת במק), בלי ספריות חיצוניות חוץ מ-pypdf, שנחוצה
רק לקריאת דוח הפציעות הרשמי ונטענת רק כשצריך.
"""
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(ROOT, "config.json")))
PLAYER_ID = CONFIG["espn_player_id"]          # 4683021
LAST_NAME = CONFIG["last_name"]               # "Avdija"
TOPIC = CONFIG["ntfy_topic"]
MIN_MINUTES = CONFIG.get("min_minutes", 10)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
ICON = f"https://a.espncdn.com/i/headshots/nba/players/full/{PLAYER_ID}.png"

# ‏חלונות הבדיקה ביחס לתחילת המשחק, בדקות. ‏הריצות כל 10 דקות, ובתוך חלון כל ריצה
# ‏בודקת שוב (ntfy זוכר מה כבר נשלח, אז אין כפילויות). ‏כך גם ריצה שמתעכבת או נופלת
# ‏ב-GitHub לא מפספסת כלום - הבאה תתפוס.
# ‏אחרי המשחק: שולחים רק מ-+3:15, ולא «ברגע שנגמר», כדי ששעת ההתראה עצמה לא תסגיר
# ‏משחק צמוד או הארכה.
PRE_WINDOW = (-75, 0)     # ‏דוח פציעות
IN_WINDOW = (10, 150)     # ‏«דני על המגרש»
POST_WINDOW = (195, 360)  # ‏סיכום הבוקר

STATUS_HE = {
    "Out": "❌ דני לא ישחק הלילה",
    "Doubtful": "⚠️ דני בספק גדול למשחק הלילה (Doubtful)",
    "Questionable": "⚠️ דני בספק למשחק הלילה (Questionable)",
}


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def now_utc() -> dt.datetime:
    fake = os.environ.get("DENI_NOW")  # ‏לבדיקות: DENI_NOW=2026-10-22T01:00Z
    if fake:
        return parse_time(fake)
    return dt.datetime.now(dt.timezone.utc)


def parse_time(s: str) -> dt.datetime:
    s = s.replace("Z", "+00:00")
    if re.match(r".*T\d\d:\d\d\+", s):
        s = s.replace("+", ":00+", 1)
    return dt.datetime.fromisoformat(s)


def current_team_id() -> str:
    """‏הקבוצה הנוכחית של דני - כדי שטרייד לא ישבור את המעקב."""
    return get_json(f"{ESPN_WEB}/athletes/{PLAYER_ID}")["athlete"]["team"]["id"]


def team_games(team_id: str) -> list:
    """‏כל המשחקים (עונה סדירה + פלייאוף), רק תאריך ומזהה. ‏בלי תוצאות."""
    games = {}
    for seasontype in (2, 3, 5):
        try:
            data = get_json(f"{ESPN}/teams/{team_id}/schedule?seasontype={seasontype}")
        except Exception:
            continue
        for e in data.get("events", []):
            games[e["id"]] = {"id": e["id"], "tip": parse_time(e["date"]), "name": e["name"]}
    return sorted(games.values(), key=lambda g: g["tip"])


# ---------------------------------------------------------------- ntfy

def sent_keys() -> set:
    """‏ntfy.sh שומר הודעות 12 שעות. ‏משתמשים בזה כזיכרון של «מה כבר נשלח», כך
    שאין צורך בקובץ מצב ובקומיטים מתוך Actions. ‏המפתח רוכב על שדה ה-icon."""
    # ‏scheduled=1: לכלול גם הודעות שמחכות לצאת השבת (delay), אחרת הן יישלחו שוב.
    url = f"https://ntfy.sh/{TOPIC}/json?poll=1&since=all&scheduled=1"
    req = urllib.request.Request(url, headers={"User-Agent": "deni-tracker"})
    keys = set()
    with urllib.request.urlopen(req, timeout=20) as r:
        for line in r.read().decode().splitlines():
            if not line.strip():
                continue
            m = re.search(r"[?&]k=([^&]+)", json.loads(line).get("icon", "") or "")
            if m:
                keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------- שבת

# ‏איתמר שומר שבת: הודעה שנוצרת בשבת או ביום טוב לא נשלחת מיד, אלא ממתינה ב-ntfy (delay)
# ‏עד אחרי צאת השבת. ‏הזמנים מ-Hebcal (ירושלים, בלי מפתח). ‏מרווחי ביטחון: שעה לפני הדלקת
# ‏נרות, ו-10 דקות אחרי ההבדלה.
HEBCAL = "https://www.hebcal.com/shabbat?cfg=json&geonameid=281184&M=on"
HOLD_BEFORE = dt.timedelta(minutes=60)
HOLD_AFTER = dt.timedelta(minutes=10)


def hold_until(now: dt.datetime) -> Optional[dt.datetime]:
    """‏אם עכשיו שבת/יום טוב (כולל המרווחים) - מתי לשחרר. ‏אחרת None."""
    try:
        items = get_json(HEBCAL)["items"]
        candles = [parse_time(i["date"]) for i in items if i["category"] == "candles"]
        havdalah = [parse_time(i["date"]) for i in items if i["category"] == "havdalah"]
    except Exception:
        # ‏אם Hebcal לא זמין: כלל גס ושמרני לפי שעון ישראל - שישי מ-14:00 עד מוצ״ש 20:30.
        from zoneinfo import ZoneInfo
        il = now.astimezone(ZoneInfo("Asia/Jerusalem"))
        if (il.weekday() == 4 and il.hour >= 14) or (il.weekday() == 5 and (il.hour, il.minute) < (20, 30)):
            sat = il + dt.timedelta(days=1 if il.weekday() == 4 else 0)
            return sat.replace(hour=20, minute=30, second=0, microsecond=0)
        return None
    for c in candles:
        after = [h for h in havdalah if h > c]
        if after and c - HOLD_BEFORE <= now < after[0] + HOLD_AFTER:
            return after[0] + HOLD_AFTER
    return None


def send(message: str, key: str, priority: int = 3) -> None:
    body = {
        "topic": TOPIC,
        "title": "דני אבדיה",
        "message": message,
        "icon": f"{ICON}?k={key}",
        "priority": priority,
    }
    held = hold_until(now_utc())
    if held:
        body["delay"] = str(int(held.timestamp()))
        print("ממתין לצאת השבת")
    if os.environ.get("DENI_DRY"):
        print("DRY:", key, message)
        return
    req = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "deni-tracker"},
    )
    urllib.request.urlopen(req, timeout=20).read()
    print("נשלח")  # ⛔ ‏בלי המפתח: «-in» / «-post» בלוג מסגירים מה קרה


# ---------------------------------------------------------------- לפני המשחק

def official_status(tip: dt.datetime) -> Optional[tuple]:
    """‏הדוח הרשמי של ה-NBA (PDF, מתעדכן כל רבע שעה, בשעון ניו יורק). ‏מחזיר
    (סטטוס, סיבה) לשורה של דני, ("Available", "") אם הדוח קיים ודני לא בו, או
    None אם לא נמצא דוח בכלל."""
    from zoneinfo import ZoneInfo
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    et = now_utc().astimezone(ZoneInfo("America/New_York"))
    t = et.replace(minute=et.minute - et.minute % 15, second=0, microsecond=0)
    for _ in range(24):  # ‏עד 6 שעות אחורה
        name = t.strftime("%Y-%m-%d_%I_%M%p")
        url = f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{name}.pdf"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            pdf = urllib.request.urlopen(req, timeout=20).read()
        except Exception:
            t -= dt.timedelta(minutes=15)
            continue
        text = "\n".join(p.extract_text(extraction_mode="layout") for p in PdfReader(io.BytesIO(pdf)).pages)
        for line in text.splitlines():
            if f"{LAST_NAME}," in line:
                m = re.search(r"(Available|Probable|Questionable|Doubtful|Out)\s+(.*)$", line)
                if m:
                    return m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        return "Available", ""
    return None


def espn_status(game_id: str) -> tuple:
    """‏גיבוי, אם הדוח הרשמי לא נמצא. ‏ל-ESPN יש רק Out / Day-To-Day."""
    data = get_json(f"{ESPN}/summary?event={game_id}")
    for team in data.get("injuries", []):
        for i in team.get("injuries", []):
            if i.get("athlete", {}).get("id") == PLAYER_ID:
                s = i.get("status", "")
                reason = (i.get("details") or {}).get("type", "")
                if s == "Out":
                    return "Out", reason
                if s:
                    return "Questionable", reason
    return "Available", ""


REASON_HE = {
    "Ankle": "קרסול", "Knee": "ברך", "Hamstring": "שריר אחורי בירך", "Back": "גב",
    "Calf": "שוק", "Groin": "מפשעה", "Foot": "כף רגל", "Hip": "ירך", "Wrist": "שורש כף היד",
    "Shoulder": "כתף", "Illness": "מחלה", "Rest": "מנוחה", "Concussion": "זעזוע מוח",
    "Thumb": "אגודל", "Finger": "אצבע", "Hand": "יד", "Toe": "בוהן", "Elbow": "מרפק",
    "Personal": "סיבה אישית", "Achilles": "אכילס", "Quad": "שריר ארבע-ראשי",
}


def reason_he(reason: str) -> str:
    side = "ימין " if "Right" in reason else "שמאל " if "Left" in reason else ""
    for en, he in REASON_HE.items():
        if en.lower() in reason.lower():
            return f"{he} {side.strip()}".strip()
    return ""


def pre_game(game: dict, keys: set) -> None:
    status = official_status(game["tip"])
    source = "official"
    if status is None:
        status, source = espn_status(game["id"]), "espn"
    s, reason = status
    print(f"מקור: {source}")
    gid = game["id"]
    if s in STATUS_HE:
        key = f"{gid}-pre-{s}"
        if key not in keys:
            r = reason_he(reason)
            send(STATUS_HE[s] + (f" · {r}" if r else ""), key, priority=4)
    elif any(k.startswith(f"{gid}-pre-") for k in keys) and f"{gid}-pre-ok" not in keys:
        send("✅ דני הוגדר כשיר למשחק הלילה", f"{gid}-pre-ok")


# ---------------------------------------------------------------- במהלך המשחק ואחריו

def deni_in_boxscore(data: dict) -> tuple:
    """‏(דקות, פתח בחמישייה). ‏דקות=0 אם לא שיחק או לא מופיע בכלל.
    🔴 ‏לא לכל שחקן ב-boxscore יש id (נמצא בבדיקת הדיוק על העונה שעברה) - לכן .get."""
    for team in data.get("boxscore", {}).get("players", []):
        for group in team.get("statistics", []):
            labels = group.get("labels") or group.get("names") or []
            for a in group.get("athletes", []):
                if a.get("athlete", {}).get("id") != PLAYER_ID:
                    continue
                if a.get("didNotPlay") or not a.get("stats") or "MIN" not in labels:
                    return 0, bool(a.get("starter"))
                raw = str(a["stats"][labels.index("MIN")])
                return (int(raw) if raw.isdigit() else 0), bool(a.get("starter"))
    return 0, False


def game_status(data: dict) -> dict:
    return data["header"]["competitions"][0]["status"]["type"]


POSTPONED = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED")


def in_game(game: dict, keys: set) -> None:
    """‏בחלון IN_WINDOW: ברגע שברור שדני על המגרש - הודעה, כדי שגם מי
    שמתעורר באמצע המשחק יידע שהוא לא נפצע לפני ושבאמת התחיל לשחק. ‏אם עדיין לא
    נכנס - שותקים, ההודעה של אחרי המשחק תכריע."""
    gid = game["id"]
    if f"{gid}-in" in keys or f"{gid}-post" in keys:
        print("בדיקה הסתיימה")
        return
    data = get_json(f"{ESPN}/summary?event={gid}")
    st = game_status(data)
    if st.get("name") in POSTPONED:
        send("📅 המשחק של הלילה נדחה", f"{gid}-post")
        return
    if st.get("state") != "in" and not st.get("completed"):
        print("המשחק עוד לא התחיל")
        return
    minutes, starter = deni_in_boxscore(data)
    if starter or minutes > 0:
        send("🏀 דני על המגרש, המשחק התחיל", f"{gid}-in", priority=4)
    else:
        print("בדיקה הסתיימה")  # ⛔ ‏לא «עוד לא נכנס» - הלוג גלוי, וזה ספוילר


def post_game(game: dict, keys: set) -> None:
    gid = game["id"]
    key = f"{gid}-post"
    if key in keys:
        print("כבר נשלח")
        return
    data = get_json(f"{ESPN}/summary?event={gid}")
    st = game_status(data)
    if st.get("name") in POSTPONED:
        send("📅 המשחק של הלילה נדחה", key)
        return
    if not st.get("completed"):
        print("בדיקה הסתיימה")  # ⛔ «עוד לא נגמר» ב-+3:15 מסגיר הארכה
        return

    minutes, _ = deni_in_boxscore(data)
    # ⛔ ‏לא מדפיסים את מספר הדקות ללוג - רק את ההחלטה.
    if not minutes:
        send("❌ דני לא שיחק הלילה", key, priority=4)
    elif minutes < MIN_MINUTES:
        send(f"⚠️ דני שיחק הלילה פחות מ-{MIN_MINUTES} דקות", key, priority=4)
    else:
        # ‏אם כבר נשלח «על המגרש» - אישור שקט (בלי צליל). ‏שולחים בכל זאת, כדי
        # ‏שהיעדר הודעת בוקר תמיד יאותת על תקלה ולא יתפרש כ«הכול בסדר».
        quiet = f"{gid}-in" in keys
        send("🏀 דני שיחק הלילה. צפייה נעימה!", key, priority=2 if quiet else 3)


def check() -> None:
    now = now_utc()
    games = team_games(current_team_id())
    near = [g for g in games
            if now - dt.timedelta(minutes=POST_WINDOW[1]) <= g["tip"] <= now - dt.timedelta(minutes=PRE_WINDOW[0])]
    if not near:
        print("אין משחק קרוב")
        return
    game = min(near, key=lambda g: abs((g["tip"] - now).total_seconds()))
    delta = (now - game["tip"]).total_seconds() / 60
    if PRE_WINDOW[0] <= delta < PRE_WINDOW[1]:
        pre_game(game, sent_keys())
    elif IN_WINDOW[0] <= delta < IN_WINDOW[1]:
        in_game(game, sent_keys())
    elif POST_WINDOW[0] <= delta <= POST_WINDOW[1]:
        post_game(game, sent_keys())
    else:
        print("בדיקה הסתיימה")


# ‏מצב «שמירה» (watch): פתרון זמני כל עוד התזמון של GitHub לא רץ בריפו (ראו CLAUDE.md).
# ‏איתמר לוחץ Run workflow פעם אחת לפני השינה; הריצה נשארת חיה לאורך כל חלון המשחק הקרוב
# ‏ובודקת כל 10 דקות. ‏ריצה ב-GitHub מוגבלת ל-6 שעות, ולכן אחרי WATCH_MAX_MIN דקות היא
# ‏כותבת continue=true ל-GITHUB_OUTPUT, וה-workflow מפעיל את עצמו מחדש.
# ‏ה-env מאפשר לבדוק את השרשור ב-GitHub בלי לחכות 5.5 שעות.
WATCH_LOOKAHEAD_H = int(os.environ.get("DENI_WATCH_LOOKAHEAD_H", 30))  # ‏משחק בתוך 30 שעות
WATCH_MAX_MIN = int(os.environ.get("DENI_WATCH_MAX_MIN", 330))         # ‏5.5 שעות, מתחת ל-6
WATCH_STEP_MIN = 10


def watch() -> None:
    import time
    started = now_utc()
    games = team_games(current_team_id())
    upcoming = [g for g in games
                if g["tip"] + dt.timedelta(minutes=POST_WINDOW[1]) > started
                and g["tip"] < started + dt.timedelta(hours=WATCH_LOOKAHEAD_H)]
    if not upcoming:
        print("אין משחק ב-30 השעות הקרובות")
        return
    game = upcoming[0]
    end = game["tip"] + dt.timedelta(minutes=POST_WINDOW[1])
    print(f"שומר עד {end:%Y-%m-%d %H:%M} UTC")
    while True:
        now = now_utc()
        if now > end or f"{game['id']}-post" in sent_keys():
            print("החלון הסתיים")
            return
        if (now - started).total_seconds() / 60 >= WATCH_MAX_MIN:
            if end - now <= dt.timedelta(minutes=WATCH_STEP_MIN):
                print("החלון הסתיים")
                return
            print("ממשיך בריצה חדשה")
            out = os.environ.get("GITHUB_OUTPUT")
            if out:
                open(out, "a").write("continue=true\n")
            return
        try:
            check()
        except Exception as e:  # ‏תקלת רשת רגעית לא עוצרת את השמירה
            print("שגיאה, ממשיך:", type(e).__name__)
        time.sleep(WATCH_STEP_MIN * 60)


if __name__ == "__main__":
    {"check": check, "watch": watch}[sys.argv[1]]()
