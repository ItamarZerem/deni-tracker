#!/usr/bin/env python3
"""מעקב בלי ספוילרים אחרי דני אבדיה.

שתי פקודות:
  check  - רץ ב-GitHub Actions בזמנים שנקבעו לפי לוח המשחקים. לפני משחק: בודק את
           דוח הפציעות. אחרי משחק: בודק אם דני שיחק, ושולח הודעה אחת ל-ntfy.
  gen    - בונה מחדש את שורות ה-cron ב-.github/workflows/deni.yml לפי לוח המשחקים
           (רץ על המק, ראו refresh.sh).

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

# זמני הבדיקה ביחס לתחילת המשחק, בדקות. ‏השליחה אחרי המשחק נעשית בשעה קבועה
# (‎+3:15) ולא «ברגע שנגמר», כדי ששעת ההתראה עצמה לא תסגיר משחק צמוד או הארכה.
# ‏+4:15 ו-+5:30 הן רשת ביטחון למשחק שעוד לא נגמר, ל-cron של GitHub שמתעכב,
# או לריצה שנפלה.
PRE_OFFSETS = [-60, -25]
IN_OFFSETS = [12, 35]
POST_OFFSETS = [195, 255, 330]
POST_EARLIEST = 180   # ‏לפני זה, ריצה «אחרי המשחק» לא עושה כלום

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
    url = f"https://ntfy.sh/{TOPIC}/json?poll=1&since=all"
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


def send(message: str, key: str, priority: int = 3) -> None:
    body = {
        "topic": TOPIC,
        "title": "דני אבדיה",
        "message": message,
        "icon": f"{ICON}?k={key}",
        "priority": priority,
    }
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
    """‏12 ו-35 דקות אחרי הפתיחה: ברגע שברור שדני על המגרש - הודעה, כדי שגם מי
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
            if now - dt.timedelta(minutes=POST_OFFSETS[-1] + 60) <= g["tip"] <= now + dt.timedelta(minutes=90)]
    if not near:
        print("אין משחק קרוב")
        return
    game = min(near, key=lambda g: abs((g["tip"] - now).total_seconds()))
    delta = (now - game["tip"]).total_seconds() / 60
    keys = sent_keys()
    if delta < 0:
        pre_game(game, keys)
    elif delta >= POST_EARLIEST:
        post_game(game, keys)
    else:
        in_game(game, keys)


# ---------------------------------------------------------------- לוח זמנים

HORIZON_DAYS = 45
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "deni.yml")


def gen() -> None:
    # ‏אופק של 45 יום: לוח מלא לכל העונה יוצא ~236 שורות cron, ולא ברור ש-GitHub
    # ‏מקבל כאלה. ‏המק מרענן כל יום (refresh.sh), כך שהאופק מתגלגל קדימה. ‏אם המק
    # ‏כבוי יותר מ-45 יום ברצף - המעקב נעצר.
    now = now_utc()
    games = [g for g in team_games(current_team_id())
             if now - dt.timedelta(hours=6) < g["tip"] < now + dt.timedelta(days=HORIZON_DAYS)]
    # ‏איחוד: כל המשחקים באותה שעה ובאותו חודש נכנסים לשורה אחת עם רשימת ימים
    # ‏('3 1 22,24,30 10 *'). ‏בלי זה יש ~400 שורות, ולא ברור ש-GitHub מקבל כאלה.
    slots = {}
    for g in games:
        for off in PRE_OFFSETS + IN_OFFSETS + POST_OFFSETS:
            # ‏דקה «עקומה» (לא 00/30): ב-GitHub ריצות בראש השעה מתעכבות ונופלות יותר.
            t = g["tip"] + dt.timedelta(minutes=off + 3)
            slots.setdefault((t.month, t.hour, t.minute), set()).add(t.day)
    lines = [f"    - cron: '{mi} {h} {','.join(map(str, sorted(days)))} {mo} *'"
             for (mo, h, mi), days in sorted(slots.items())]
    text = open(WORKFLOW).read()
    begin, end = "    # >>> נוצר אוטומטית\n", "    # <<< נוצר אוטומטית\n"
    head, rest = text.split(begin)
    _, tail = rest.split(end)
    new = head + begin + "\n".join(lines) + "\n" + end + tail
    if new != text:
        open(WORKFLOW, "w").write(new)
        print(f"עודכן: {len(games)} משחקים, {len(lines)} זמני בדיקה")
    else:
        print("ללא שינוי")


if __name__ == "__main__":
    {"check": check, "gen": gen}[sys.argv[1]]()
