#!/usr/bin/python3
"""סוכן הכתבות: אוסף חומרים, נותן ל-Claude (במנוי, בלי API) לכתוב, ושולח טיוטה מוסתרת לאיתמר.

  writer.py preview|recap <gameId>                  ריצה אמיתית
  writer.py preview|recap <gameId> --sample <קובץ>  דוגמה על משחק ישן: בלי כלי רשת ובלי שליחה

⛔ הפלט כאן נכנס ליומן שמוצג בעמוד הסוכנים, ולכן הוא ניטרלי: רק צעדים ו«נשלח». הכתבה עצמה
נשמרת רק ב-~/.config/deni-writer/drafts ובטיוטה בטלגרם, עם הטקסט מוסתר.
הפרסום בערוץ קורה רק כשאיתמר לוחץ על הכפתור, ב-channel.py (art_answer).
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("DENI_WRITER_HOME", os.path.expanduser("~/.config/deni-writer"))
sys.path.insert(0, ROOT)
if not os.environ.get("TELEGRAM_TOKEN"):
    try:
        with open(os.path.join(BASE, "telegram_token")) as f:
            os.environ["TELEGRAM_TOKEN"] = f.read().strip()
    except OSError:
        pass

import channel  # noqa: E402
import tracker  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
MAX_ARTICLE = 3900  # מגבלת ההודעה בטלגרם היא 4,096 תווים, כולל שורת הטיוטה
CLAUDE_TIMEOUT = 25 * 60
GEMINI_MODEL = "gemini-4-argon-high"
H = dt.timedelta(hours=1)

# בלוגים של קבוצות. הבדיקה מ-4.11.26: רובם עונים ב-/rss/index.xml, חלקם ב-/feed, וחלקם חסומים.
BLOGS = {
    "ATL": "peachtreehoops.com", "BOS": "celticsblog.com", "BKN": "netsdaily.com", "CHA": "atthehive.com",
    "CHI": "secondcityhoops.com", "CLE": "fearthesword.com", "DAL": "mavsmoneyball.com",
    "DEN": "denverstiffs.com", "DET": "detroitbadboys.com", "GS": "goldenstateofmind.com",
    "HOU": "thedreamshake.com", "IND": "indycornrows.com", "LAC": "clipsnation.com",
    "LAL": "silverscreenandroll.com", "MEM": "grizzlybearblues.com", "MIA": "hothothoops.com",
    "MIL": "brewhoop.com", "MIN": "canishoopus.com", "NO": "thebirdwrites.com",
    "NY": "postingandtoasting.com", "OKC": "welcometoloudcity.com", "ORL": "orlandopinstripedpost.com",
    "PHI": "libertyballers.com", "PHX": "brightsideofthesun.com", "POR": "blazersedge.com",
    "SAC": "sactownroyalty.com", "SA": "poundingtherock.com", "TOR": "raptorshq.com",
    "UTAH": "slcdunk.com", "WSH": "bulletsforever.com",
}
# מקורות ישראליים: לוקחים רק פריטים שמוזכר בהם דני.
HEBREW = [
    ("וואלה", "https://rss.walla.co.il/feed/3"),
    ("ONE", "https://www.one.co.il/rss"),
    ("ynet", "https://www.ynet.co.il/Integration/StoryRss3.xml"),
    ("ספורט 5", "https://www.sport5.co.il/sitemap/nba/news-sitemap.xml"),
]
PORTLAND = [
    ("OregonLive (תקצירים)", "https://www.oregonlive.com/arc/outboundfeeds/rss/category/blazers/?outputType=xml"),
    ("Hoops Rumors", "https://www.hoopsrumors.com/portland-trail-blazers/feed"),
]
NBA_TEAM_NEWS = "https://www.nba.com/blazers/api/content/category/news?page=1"


def step(text: str) -> None:
    print(f"{dt.datetime.now():%H:%M} 🔧 {text}", flush=True)


def fetch(url: str, timeout: int = 20) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def strip_tags(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_date(raw: Optional[str]) -> Optional[dt.datetime]:
    if not raw:
        return None
    raw = raw.strip()
    try:
        t = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            t = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(data: bytes) -> list:
    """RSS, Atom או מפת אתר של חדשות: [{"title", "text", "date", "link"}]."""
    items = []
    for node in ET.fromstring(data).iter():
        if local(node.tag) not in ("item", "entry", "url"):
            continue
        d = {}
        for child in node.iter():
            name = local(child.tag)
            value = (child.text or "").strip()
            if name == "link" and not value:
                value = child.get("href", "")
            if value and name not in d:
                d[name] = value
        items.append({
            "title": strip_tags(d.get("title", "")),
            "text": strip_tags(d.get("encoded") or d.get("content") or d.get("description") or d.get("summary") or ""),
            "date": parse_date(d.get("pubDate") or d.get("published") or d.get("publication_date")
                               or d.get("updated") or d.get("date") or d.get("lastmod")),
            "link": d.get("link") or d.get("loc") or "",
            "author": strip_tags(d.get("creator") or d.get("name") or d.get("author") or ""),
        })
    return items


def in_range(items: list, start: dt.datetime, end: dt.datetime) -> list:
    picked = [i for i in items if i["date"] and start <= i["date"] <= end]
    return sorted(picked, key=lambda i: i["date"], reverse=True)


def about_deni(item: dict) -> bool:
    text = item["title"] + " " + item["text"]
    return "אבדיה" in text or "Avdija" in text


def fmt_items(source: str, items: list, limit: int, chars: int = 5000) -> str:
    out = []
    for i in items[:limit]:
        when = i["date"].astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        by = f" · כותב: {i['author']}" if i.get("author") else ""
        out.append(f"### {source}{by} · {when}\n{i['title']}\n{i['text'][:chars]}")
    return "\n\n".join(out)


def blog_items(abbr: str, start: dt.datetime, end: dt.datetime) -> list:
    """הכתבות של בלוג הקבוצה בחלון הזמן. למשחק ישן: מהארכיון, כי ה-RSS מכיל רק כתבות חדשות."""
    site = BLOGS.get(abbr)
    if not site:
        return []
    if tracker.now_utc() - end > dt.timedelta(days=7):
        return archive_items(site, start, end)
    for path in ("/rss/index.xml", "/feed"):
        try:
            return in_range(parse_feed(fetch(f"https://www.{site}{path}")), start, end)
        except Exception:
            continue
    return []


def archive_items(site: str, start: dt.datetime, end: dt.datetime) -> list:
    out = []
    for month in sorted({(start.year, start.month), (end.year, end.month)}):
        try:
            pages = parse_feed(fetch(f"https://www.{site}/sitemaps/entries/{month[0]}/{month[1]}"))
        except Exception:
            continue
        for p in in_range(pages, start, end)[:12]:
            try:
                page = fetch(p["link"]).decode("utf-8", "replace")
            except Exception:
                continue
            title = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
            body = " ".join(re.findall(r"(?is)<p[^>]*>(.*?)</p>", page))
            author = re.search(r'(?is)<meta[^>]+name="author"[^>]+content="([^"]+)"', page)
            out.append({**p, "title": strip_tags(title.group(1)) if title else "", "text": strip_tags(body),
                        "author": author.group(1) if author else ""})
    return sorted(out, key=lambda i: i["date"], reverse=True)


def team_news(start: dt.datetime, end: dt.datetime) -> list:
    items = []
    for it in json.loads(fetch(NBA_TEAM_NEWS)).get("items", []):
        when = dt.datetime.fromtimestamp(it.get("timestamp", 0) / 1000, dt.timezone.utc)
        items.append({"title": it.get("title", ""), "text": strip_tags(it.get("excerpt", "")), "date": when, "link": ""})
    return in_range(items, start, end)


def recent_form(team_id: str, before: dt.datetime, count: int = 5) -> str:
    """התוצאות האחרונות של קבוצה לפני מועד נתון."""
    season = os.environ.get("DENI_SEASON")
    url = f"{tracker.ESPN}/teams/{team_id}/schedule?seasontype=2" + (f"&season={season}" if season else "")
    rows = []
    for e in tracker.get_json(url).get("events", []):
        t = tracker.parse_time(e["date"])
        c = e["competitions"][0]
        if t >= before or not c.get("status", {}).get("type", {}).get("completed"):
            continue
        us = next(x for x in c["competitors"] if x["team"]["id"] == team_id)
        them = next(x for x in c["competitors"] if x["team"]["id"] != team_id)
        rows.append((t, f"{t:%m-%d} {'בית' if us['homeAway'] == 'home' else 'חוץ'} מול {them['team']['abbreviation']}: "
                        f"{'ניצחון' if us.get('winner') else 'הפסד'} "
                        f"{us['score']['displayValue']}-{them['score']['displayValue']}"))
    return "\n".join(r for _, r in sorted(rows)[-count:]) or "אין נתונים"


def deni_recent(before: dt.datetime, count: int = 5) -> str:
    season = os.environ.get("DENI_SEASON")
    url = f"{tracker.ESPN_WEB}/athletes/{tracker.PLAYER_ID}/gamelog" + (f"?season={season}" if season else "")
    d = tracker.get_json(url)
    labels = d.get("labels", [])
    rows = []
    for st in d.get("seasonTypes", []):
        for c in st.get("categories", []):
            for e in c.get("events", []):
                meta = d.get("events", {}).get(str(e["eventId"])) or {}
                when = parse_date(meta.get("gameDate"))
                if when and when < before:
                    stats = " ".join(f"{k} {v}" for k, v in zip(labels, e.get("stats", [])))
                    rows.append((when, f"{when:%m-%d} מול {meta.get('opponent', {}).get('abbreviation', '')}: {stats}"))
    return "\n".join(r for _, r in sorted(rows)[-count:]) or "אין נתונים"


def injuries_text(summary: dict) -> str:
    out = []
    for team in summary.get("injuries", []):
        rows = []
        for i in team.get("injuries", []):
            name = i.get("athlete", {}).get("displayName", "")
            detail = i.get("details", {})
            rows.append(f"{name}: {i.get('status', '')} {detail.get('type', '')} {detail.get('detail', '')}".strip())
        out.append(f"{team.get('team', {}).get('displayName', '')}: " + ("; ".join(rows) or "אין"))
    return "\n".join(out) or "אין נתונים"


def odds_text(summary: dict) -> str:
    picks = summary.get("pickcenter") or []
    if not picks:
        return "אין נתונים"
    p = picks[0]
    return f"{p.get('provider', {}).get('name', '')}: {p.get('details', '')} · סך נקודות צפוי {p.get('overUnder', '')}"


def box_text(summary: dict) -> str:
    """שורות הסטטיסטיקה של כל מי ששיחק."""
    out = []
    for team in summary.get("boxscore", {}).get("players", []):
        out.append(f"#### {team.get('team', {}).get('displayName', '')}")
        for group in team.get("statistics", []):
            labels = group.get("labels") or []
            for a in group.get("athletes", []):
                if a.get("stats"):
                    row = " ".join(f"{k} {v}" for k, v in zip(labels, a["stats"]))
                    out.append(f"{a.get('athlete', {}).get('displayName', '')}{' (חמישייה)' if a.get('starter') else ''}: {row}")
    return "\n".join(out)


def game_head(game: dict, teams: dict) -> str:
    side = "בבית" if game["home"] else "בחוץ"
    return (f"המשחק: {teams.get(game['us']['id'], game['us']['abbr'])} מול "
            f"{teams.get(game['them']['id'], game['them']['abbr'])}, {side}. "
            f"שם היריבה בעברית: {channel.team_he(game['them']['abbr'])}. "
            f"שעת הפתיחה: {game['tip']:%Y-%m-%d %H:%M} UTC. שלב: {channel.SEASON_LABEL.get(game['type'], '')}.")


def bundle(mode: str, game: dict, sample: bool) -> str:
    """חבילת החומרים ל-Claude. תקלה במקור אחד לא עוצרת את השאר."""
    summary = tracker.get_json(f"{tracker.ESPN}/summary?event={game['id']}")
    comp = summary.get("header", {}).get("competitions", [{}])[0]
    teams = {c["team"]["id"]: c["team"].get("displayName", "") for c in comp.get("competitors", [])}
    tip, now = game["tip"], tracker.now_utc()
    parts = [game_head(game, teams)]

    def add(title: str, fn, *args) -> None:
        try:
            text = fn(*args)
        except Exception as e:
            print(f"{dt.datetime.now():%H:%M} מקור אחד לא זמין ({type(e).__name__})", flush=True)
            return
        if text:
            parts.append(f"## {title}\n{text}")

    us, them = game["us"], game["them"]
    if mode == "preview":
        start, end = tip - 72 * H, min(now, tip)
        add(f"התוצאות האחרונות של {us['abbr']}", recent_form, us["id"], tip)
        add(f"התוצאות האחרונות של {them['abbr']}", recent_form, them["id"], tip)
        add("המשחקים האחרונים של דני", deni_recent, tip)
        # במשחק ישן (דוגמה) הסיכום כבר מכיל את התוצאה, אז לוקחים ממנו רק את מה שידוע מראש
        add("פציעות (ESPN)", injuries_text, summary)
        add("יחסי הימורים", odds_text, summary)
    else:
        start, end = tip, min(now, tip + 40 * H)
        scores = "\n".join(f"{c['team'].get('displayName', '')}: {c.get('score', '')} "
                           f"(רבעים: {' '.join(str(q.get('displayValue', '')) for q in c.get('linescores') or [])})"
                           for c in comp.get("competitors", []))
        parts.append(f"## התוצאה\n{scores}")
        add("הסטטיסטיקה של המשחק", box_text, summary)
        article = summary.get("article") or {}
        if article.get("story"):
            parts.append(f"## סיכום AP דרך ESPN\n{strip_tags(article['story'])}")

    add(f"בלוג הקבוצה של {us['abbr']}", lambda: fmt_items(BLOGS.get(us["abbr"], ""), blog_items(us["abbr"], start, end), 4))
    add(f"בלוג היריבה {them['abbr']}", lambda: fmt_items(BLOGS.get(them["abbr"], ""), blog_items(them["abbr"], start, end), 2))
    if not sample:  # המקורות האלה מכילים רק את הימים האחרונים, ואין להם ארכיון
        if us["abbr"] == "POR":
            add("האתר של פורטלנד", lambda: fmt_items("nba.com/blazers", team_news(start, end), 6, 1000))
            for name, url in PORTLAND:
                add(name, lambda u=url, n=name: fmt_items(n, in_range(parse_feed(fetch(u)), start, end), 4, 1500))
        for name, url in HEBREW:
            add(name, lambda u=url, n=name: fmt_items(
                n, [i for i in in_range(parse_feed(fetch(u)), start, end) if about_deni(i)], 3, 2500))
    return "\n\n".join(parts)[:60000]


def edit_article(article: str, engine: str = "gemini") -> str:
    """עריכת לשון אחרי הכתיבה. העורך רואה רק את הטיוטה, בלי החומר באנגלית שגורר תרגום מילולי.
    בכל תקלה, או אם מספר כלשהו השתנה, נשארת הטיוטה המקורית: ליטוש לא שווה טעות בעובדה."""
    try:
        with open(os.path.join(ROOT, "tool", "editor_guide.md")) as f:
            guide = f.read()
        prompt = f"{guide}\n\n# הטיוטה\n\n{article}"
        edited = extract_article(run_gemini(prompt) if engine == "gemini" else run_claude(prompt, web=False))
    except Exception as e:
        print(f"העריכה לא הצליחה ({type(e).__name__}), נשארת הטיוטה", flush=True)
        return article
    if not same_numbers(article, edited):
        print("העריכה שינתה מספר, נשארת הטיוטה", flush=True)
        return article
    return edited


def same_numbers(a: str, b: str) -> bool:
    numbers = lambda text: Counter(re.findall(r"\d+(?:[.,]\d+)?", text))
    return numbers(a) == numbers(b)


def run_gemini(prompt: str) -> str:
    """ג'מיני דרך Antigravity CLI, בהתחברות של המנוי. בלי מפתחות בסביבה, כדי שלא ייגבה תשלום,
    ובלי אישור לכלים: בהרצה כזו כל פעולה שדורשת אישור נדחית."""
    work = os.path.join(BASE, "work")
    os.makedirs(work, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TELEGRAM_TOKEN")}
    agy = shutil.which("agy") or os.path.expanduser("~/.local/bin/agy")
    cmd = [agy, "-p", prompt, "--model", GEMINI_MODEL, "--output-format", "text",
           "--print-timeout", "10m", "--disable-slash-commands"]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, cwd=work, env=env,
                       timeout=CLAUDE_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"agy יצא עם קוד {r.returncode}")
    return r.stdout


def run_claude(prompt: str, web: bool) -> str:
    """Claude במנוי בלבד: מנקים מהסביבה כל מפתח API, כדי שלעולם לא ייגבה תשלום. רץ מתיקייה ריקה,
    בלי הגדרות, בלי שמירת השיחה (כדי שלא תופיע בשום רשימה) ובלי גישה לקבצים או לפקודות."""
    work = os.path.join(BASE, "work")
    os.makedirs(work, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TELEGRAM_TOKEN")}
    tools = "WebSearch,WebFetch" if web else ""
    claude = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    cmd = [claude, "-p", "--model", "opus", "--output-format", "text", "--no-session-persistence",
           "--setting-sources", "project", "--strict-mcp-config", "--permission-mode", "dontAsk",
           "--tools", tools, "--allowedTools", tools]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=work, env=env, timeout=CLAUDE_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"claude יצא עם קוד {r.returncode}")
    return r.stdout


def extract_article(output: str) -> str:
    m = re.search(r"(?s)<article>\s*(.*?)\s*</article>", output)
    if not m:
        raise RuntimeError("לא התקבלה כתבה בפורמט הנדרש")
    text = m.group(1).strip()
    if len(text) < 200 or len(text) > MAX_ARTICLE:
        raise RuntimeError(f"אורך לא תקין ({len(text)} תווים)")
    return text


def draft_message(mode: str, game: dict, article: str) -> dict:
    """הטקסט מוסתר. שורת הכותרת לא מסגירה כלום. channel.art_text מפריד אותה בפרסום."""
    kind = "כתבה לפני המשחק" if mode == "preview" else "סיכום המשחק"
    head = f"📝 טיוטה · {kind} מול {channel.team_he(game['them']['abbr'])} · לחיצה על הטקסט חושפת אותו"
    return {
        "chat_id": channel.ADMIN, "parse_mode": "HTML",
        "text": f"{html.escape(head)}\n\n<tg-spoiler>{html.escape(article)}</tg-spoiler>",
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ לפרסם בערוץ", "callback_data": "art|go"},
            {"text": "🚫 לא לפרסם", "callback_data": "art|no"},
        ]]},
    }


def find_game(game_id: str) -> dict:
    team = os.environ.get("DENI_TEAM") or tracker.current_team_id()
    return next(g for g in channel.schedule(team) if g["id"] == game_id)


def main(argv: list) -> int:
    if argv[0] == "edit":  # השוואה בין עורכים על אותה טיוטה: edit <עורך> <קלט> <פלט>
        with open(argv[2]) as f:
            text = f.read().strip()
        with open(argv[3], "w") as f:
            f.write(edit_article(text, argv[1]) + "\n")
        print("הגרסה הערוכה נשמרה")
        return 0
    mode, game_id = argv[0], argv[1]
    sample_path = argv[3] if len(argv) > 3 and argv[2] == "--sample" else None
    game = find_game(game_id)
    drafts = os.path.join(BASE, "drafts")
    cached = os.path.join(drafts, f"{game_id}-{mode}.txt")

    if not sample_path and os.path.exists(cached):  # ניסיון קודם כתב, והשליחה נכשלה
        with open(cached) as f:
            article = f.read()
    else:
        step("אוסף נתונים וכתבות")
        material = bundle(mode, game, bool(sample_path))
        with open(os.path.join(ROOT, "tool", "writer_guide.md")) as f:
            guide = f.read()
        kind = "כתבה לפני המשחק" if mode == "preview" else "כתבה אחרי המשחק"
        prompt = f"{guide}\n\n# המשימה: {kind}\n\n# חבילת החומרים\n\n{material}"
        step("כותב את הכתבה")
        article = extract_article(run_claude(prompt, web=not sample_path))
        step("עורך את העברית")
        article = edit_article(article)

    if sample_path:
        with open(sample_path, "w") as f:
            f.write(article + "\n")
        print("הדוגמה נשמרה")
        return 0

    os.makedirs(drafts, exist_ok=True)
    with open(cached, "w") as f:
        f.write(article)
    step("שולח טיוטה לטלגרם")
    channel.tg("sendMessage", draft_message(mode, game, article))
    os.remove(cached)
    return 0


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except Exception as e:
        # בלי תוכן ובלי פרטי השגיאה מעבר לסוג: היומן מוצג בעמוד הסוכנים
        print(f"הריצה נכשלה ({type(e).__name__})")
        code = 1
    sys.exit(code)
