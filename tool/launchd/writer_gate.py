#!/usr/bin/python3
"""השער של סוכן הכתבות: מחליט מתי לרוץ, לפי לוח המשחקים.

מותקן ב-~/.config/deni-writer/gate.py (המקור כאן בריפו), כי macOS חוסם משימת launchd מלקרוא את
~/Desktop. לכן הקובץ עומד בפני עצמו, בלי ייבוא מהריפו ובלי תלויות.

  gate.py tick          launchd מריץ כל 10 דקות: מעדכן את next_run ואת missed.log, ומפעיל את הסוכן אם הגיע הזמן
  gate.py pick          מה הסוכן צריך לכתוב עכשיו: «<mode> <gameId>», או כלום
  gate.py begin <key>   ניסיון התחיל
  gate.py done <key>    הטיוטה נשלחה

⛔ איתמר רואה את הטרמינל ואת עמוד הסוכנים: השער קורא מהלוח רק זמנים ו«הסתיים», ולא תוצאות.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

HOME = os.path.expanduser("~")
BASE = os.environ.get("DENI_WRITER_HOME", os.path.join(HOME, ".config/deni-writer"))
LOGS = os.environ.get("DENI_WRITER_LOGS", os.path.join(HOME, "Library/Logs/deni-writer"))
STATE = os.path.join(BASE, "state.json")
LABEL = "com.itamar.deni-writer"

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
PLAYER_ID = "4683021"
HEBCAL = "https://www.hebcal.com/shabbat?cfg=json&geonameid=281184&M=on"

H = dt.timedelta(hours=1)
PREVIEW_AT = -7 * H        # הכתבה שלפני המשחק: 7 שעות לפני הפתיחה, כדי שאיתמר יאשר לפני השינה
RECAP_AT = 6 * H           # הסיכום: 6 שעות אחרי הפתיחה, כשרוב הכתבות כבר בחוץ
RECAP_UNTIL = 72 * H       # מחשב שהיה כבוי עדיין משלים סיכום עד 3 ימים אחרי המשחק
EARLY_PREVIEW = 24 * H     # הפעלה ידנית יכולה לכתוב כתבה מוקדם, עד יממה לפני המשחק
MISSED_KEEP = 24 * H       # כמה זמן מציגים כתבה שהוחמצה
RETRY_AFTER = dt.timedelta(minutes=30)
MAX_ATTEMPTS = 3
RECAP_LATE = 2 * H         # סיכום שלא נכתב שעתיים אחרי המועד נחשב לא רץ

TEAMS_HE = {
    "ATL": "אטלנטה", "BOS": "בוסטון", "BKN": "ברוקלין", "CHA": "שארלוט", "CHI": "שיקגו",
    "CLE": "קליבלנד", "DAL": "דאלאס", "DEN": "דנבר", "DET": "דטרויט", "GS": "גולדן סטייט",
    "HOU": "יוסטון", "IND": "אינדיאנה", "LAC": "הקליפרס", "LAL": "הלייקרס", "MEM": "ממפיס",
    "MIA": "מיאמי", "MIL": "מילווקי", "MIN": "מינסוטה", "NO": "ניו אורלינס", "NY": "ניו יורק",
    "OKC": "אוקלהומה סיטי", "ORL": "אורלנדו", "PHI": "פילדלפיה", "PHX": "פיניקס",
    "POR": "פורטלנד", "SAC": "סקרמנטו", "SA": "סן אנטוניו", "TOR": "טורונטו", "UTAH": "יוטה",
    "WSH": "וושינגטון",
}


def now_utc() -> dt.datetime:
    fake = os.environ.get("DENI_NOW")
    return parse_time(fake) if fake else dt.datetime.now(dt.timezone.utc)


def parse_time(s: str) -> dt.datetime:
    s = s.replace("Z", "+00:00")
    if len(s) == 22 and s[10] == "T":  # «2026-10-22T01:03+00:00»
        s = s[:16] + ":00" + s[16:]
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def load_state(now: dt.datetime) -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        # הריצה הראשונה: לא משלימים כתבות למשחקים שהיו לפני ההתקנה
        return {"since": now.isoformat(), "done": {}, "tries": {}}


def save_state(state: dict) -> None:
    os.makedirs(BASE, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)


def fetch_games() -> list:
    team = get_json(f"{ESPN_WEB}/athletes/{PLAYER_ID}")["athlete"]["team"]["id"]
    games = {}
    for st in (2, 3, 5):
        try:
            data = get_json(f"{ESPN}/teams/{team}/schedule?seasontype={st}")
        except Exception:
            continue
        for e in data.get("events", []):
            c = e["competitions"][0]
            them = next(x for x in c["competitors"] if x["team"]["id"] != team)
            games[e["id"]] = {
                "id": e["id"], "tip": parse_time(e["date"]), "them": them["team"]["abbreviation"],
                "over": bool(c.get("status", {}).get("type", {}).get("completed")),
            }
    return sorted(games.values(), key=lambda g: g["tip"])


def jobs(games: list) -> list:
    out = []
    for g in games:
        out.append({"key": f"{g['id']}-preview", "mode": "preview", "game": g,
                    "at": g["tip"] + PREVIEW_AT, "until": g["tip"]})
        out.append({"key": f"{g['id']}-recap", "mode": "recap", "game": g,
                    "at": g["tip"] + RECAP_AT, "until": g["tip"] + RECAP_UNTIL})
    return out


def in_window(j: dict, now: dt.datetime) -> bool:
    if not j["at"] <= now <= j["until"]:
        return False
    return j["mode"] != "recap" or j["game"]["over"]  # משחק שנדחה עוד לא נגמר


def due_auto(j: dict, state: dict, now: dt.datetime) -> bool:
    """הגיע הזמן להפעיל את הסוכן לבד."""
    if j["key"] in state["done"] or not in_window(j, now) or j["at"] < parse_time(state["since"]):
        return False
    t = state["tries"].get(j["key"], {})
    if t.get("n", 0) >= MAX_ATTEMPTS:
        return False
    return not t.get("last") or now - parse_time(t["last"]) >= RETRY_AFTER


def pick_job(all_jobs: list, state: dict, now: dt.datetime):
    """מה לכתוב כשהסוכן מופעל: קודם מה שהגיע זמנו (גם אם נכשל שלוש פעמים, כי הפעלה ידנית
    היא ניסיון נוסף), ואם אין, הפעלה ידנית כותבת סיכום של משחק שנגמר או כתבה מוקדמת."""
    open_jobs = [j for j in all_jobs if j["key"] not in state["done"]]
    for j in open_jobs:
        if in_window(j, now) and j["at"] >= parse_time(state["since"]):
            return j
    for j in reversed(open_jobs):
        if j["mode"] == "recap" and j["game"]["over"] and j["game"]["tip"] <= now <= j["until"]:
            return j
    for j in open_jobs:
        if j["mode"] == "preview" and now < j["until"] <= now + EARLY_PREVIEW:
            return j
    return None


def shabbat_ranges() -> list:
    """[(התחלה, סוף)] מ-Hebcal: שעה לפני הדלקת נרות עד 10 דקות אחרי ההבדלה, כמו ב-tracker.py."""
    items = get_json(HEBCAL)["items"]
    candles = [parse_time(i["date"]) for i in items if i["category"] == "candles"]
    havdalah = [parse_time(i["date"]) for i in items if i["category"] == "havdalah"]
    out = []
    for c in candles:
        after = [h for h in havdalah if h > c]
        if after:
            out.append((c - H, after[0] + dt.timedelta(minutes=10)))
    return out


def rough_shabbat(t: dt.datetime) -> bool:
    """כשאין Hebcal: שישי מ-14:00 עד מוצ״ש 20:30, בקירוב בשעון ישראל (UTC+2)."""
    il = t.astimezone(dt.timezone(2 * H))
    return (il.weekday() == 4 and il.hour >= 14) or (il.weekday() == 5 and (il.hour, il.minute) < (20, 30))


def is_shabbat(t: dt.datetime, ranges) -> bool:
    if ranges is None:
        return rough_shabbat(t)
    return any(a <= t < b for a, b in ranges)


def missed_lines(all_jobs: list, state: dict, now: dt.datetime, ranges) -> list:
    """מה היה צריך להיכתב ולא נכתב. כתבה שנפלה על שבת היא החלטה, לא תקלה, ולכן לא מסומנת."""
    since = parse_time(state["since"])
    out = []
    for j in all_jobs:
        if j["key"] in state["done"] or j["at"] < since or is_shabbat(j["at"], ranges):
            continue
        name = TEAMS_HE.get(j["game"]["them"], j["game"]["them"])
        tries = state["tries"].get(j["key"], {}).get("n", 0)
        why = "הריצות נכשלו" if tries >= MAX_ATTEMPTS else "המחשב היה כבוי או רדום"
        if j["mode"] == "preview" and j["until"] < now <= j["until"] + MISSED_KEEP:
            out.append(f"הכתבה לפני המשחק מול {name} לא נכתבה: {why}")
        elif j["mode"] == "preview" and tries >= MAX_ATTEMPTS and j["at"] <= now <= j["until"]:
            out.append(f"הכתבה לפני המשחק מול {name} נכשלה. אפשר להפעיל ידנית.")
        elif (j["mode"] == "recap" and j["game"]["over"] and j["at"] + RECAP_LATE <= now <= j["until"]
              and not is_shabbat(now, ranges)):
            out.append(f"הסיכום של המשחק מול {name} עוד לא נכתב: {why}. אפשר להפעיל ידנית.")
    return out


def next_run(all_jobs: list, state: dict, now: dt.datetime):
    future = [j["at"] for j in all_jobs if j["at"] > now and j["key"] not in state["done"]]
    return min(future) if future else None


def write_text(name: str, text: str) -> None:
    os.makedirs(LOGS, exist_ok=True)
    path = os.path.join(LOGS, name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def writer_running() -> bool:
    return subprocess.run(["/usr/bin/pgrep", "-f", "tool/writer.sh"], capture_output=True).returncode == 0


def tick() -> None:
    now = now_utc()
    state = load_state(now)
    if not os.path.exists(STATE):
        save_state(state)
    all_jobs = jobs(fetch_games())
    try:
        ranges = shabbat_ranges()
    except Exception:
        ranges = None
    write_text("missed.log", "\n".join(missed_lines(all_jobs, state, now, ranges)))
    nxt = next_run(all_jobs, state, now)
    write_text("next_run", str(int(nxt.timestamp() * 1000)) if nxt else "")
    if is_shabbat(now, ranges) or writer_running():
        return
    if any(due_auto(j, state, now) for j in all_jobs):
        subprocess.run(["/bin/launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    now = now_utc()
    if cmd == "tick":
        tick()
    elif cmd == "pick":
        j = pick_job(jobs(fetch_games()), load_state(now), now)
        if j:
            print(j["mode"], j["game"]["id"])
    elif cmd in ("begin", "done"):
        state = load_state(now)
        if cmd == "done":
            state["done"][sys.argv[2]] = now.isoformat()
        else:
            t = state["tries"].setdefault(sys.argv[2], {"n": 0})
            t.update(n=t["n"] + 1, last=now.isoformat())
        save_state(state)
    else:
        sys.exit("gate.py tick|pick|begin|done")


if __name__ == "__main__":
    main()
