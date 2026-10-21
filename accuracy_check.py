"""בדיקת דיוק מול מקור עצמאי: ההחלטה של tracker.post_game (מבוססת ESPN) מול
Basketball-Reference, על כל משחקי עונה שלמה של הקבוצה. ‏מדפיס רק ספירת התאמות.
‏הרצה: python3 accuracy_check.py <bbref.html> <עונת ESPN, למשל 2026>"""
import datetime as dt, re, sys
from unittest import mock
from zoneinfo import ZoneInfo
import tracker

html = open(sys.argv[1]).read()
truth = {}
for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
    d = re.search(r'data-stat="date"[^>]*><a[^>]*>(\d{4}-\d\d-\d\d)', row)
    if not d:
        continue
    mp = re.search(r'data-stat="mp"[^>]*>(\d+)(?::(\d+))?<', row)
    minutes = int(mp.group(1)) + int(mp.group(2) or 0) / 60 if mp else 0
    truth[d.group(1)] = minutes

def category(m):
    return "dnp" if not m else "under" if m < tracker.MIN_MINUTES else "played"

events = tracker.get_json(f"{tracker.ESPN}/teams/22/schedule?season={sys.argv[2]}&seasontype=2")["events"]
agree, total, missing, diffs = 0, 0, 0, []
for e in events:
    date = tracker.parse_time(e["date"]).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    sent = []
    with mock.patch.object(tracker, "send", side_effect=lambda m, k, priority=3: sent.append(m)):
        tracker.post_game({"id": e["id"]}, set())
    got = "played" if "🏀" in sent[0] else "under" if "⚠️" in sent[0] else "dnp"
    total += 1
    # ‏ב-bbref משחק שהשחקן לא היה בסגל (פציעה ארוכה) לפעמים חסר לגמרי = לא שיחק.
    want = category(truth.get(date, 0))
    if date not in truth:
        missing += 1
    if got == want:
        agree += 1
    else:
        diffs.append((date, got, want, round(truth.get(date, 0), 2)))
print(f"תואם: {agree}/{total}  (שורות שחסרות ב-bbref: {missing})")
if "--show-diffs" in sys.argv:
    for d in diffs: print(d)
else:
    print(f"אי-התאמות: {len(diffs)}")
