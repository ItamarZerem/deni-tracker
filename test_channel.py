"""בדיקות לבוט הערוץ, בלי רשת. ‏כל המספרים כאן מומצאים."""
import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.pop("DENI_DRY", None)
import channel  # noqa: E402
import tracker  # noqa: E402

UTC = dt.timezone.utc


def game(tip="2026-10-28T03:00:00+00:00", home=False, abbr="LAL", gid="1", neutral=False, type_=2):
    return {"id": gid, "tip": dt.datetime.fromisoformat(tip), "home": home, "neutral": neutral,
            "type": type_, "us": {"id": "22", "abbr": "POR"}, "them": {"id": "13", "abbr": abbr}}


def summary(state="in", name="STATUS_IN_PROGRESS", completed=False, ours=58, theirs=61,
            periods=2, deni=None):
    comps = [
        {"team": {"id": "22"}, "score": str(ours), "linescores": [{}] * periods},
        {"team": {"id": "13"}, "score": str(theirs), "linescores": [{}] * periods},
    ]
    labels = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]
    athletes = []
    if deni is not None:
        athletes.append({"athlete": {"id": tracker.PLAYER_ID}, **deni})
    return {
        "header": {"competitions": [{"competitors": comps,
                                     "status": {"type": {"state": state, "name": name, "completed": completed}}}]},
        "boxscore": {"players": [{"statistics": [{"labels": labels, "athletes": athletes}]}]},
    }


PLAYED = {"starter": True, "didNotPlay": False,
          "stats": ["17", "12", "5-9", "1-3", "1-2", "4", "3", "1", "1", "0", "1", "3", "2", "+5"]}
DNP = {"starter": False, "didNotPlay": True, "reason": "INJURY/ILLNESS - RIGHT ANKLE; SPRAIN", "stats": []}


class Times(unittest.TestCase):
    def test_preview_day_before_night_game(self):
        # ‏משחק ב-5:00 בלילה שבין שלישי לרביעי → פרסום ביום שלישי ב-12:00
        at = channel.preview_at(dt.datetime(2026, 10, 28, 3, 0, tzinfo=UTC))
        self.assertEqual(at.astimezone(channel.IL).strftime("%d %H:%M"), "27 12:00")

    def test_preview_evening_game_same_day(self):
        at = channel.preview_at(dt.datetime(2026, 11, 1, 19, 0, tzinfo=UTC))  # ‏21:00 בישראל
        self.assertEqual(at.astimezone(channel.IL).strftime("%d %H:%M"), "01 12:00")

    def test_preview_at_least_3h_before(self):
        tip = dt.datetime(2026, 11, 1, 11, 0, tzinfo=UTC)  # ‏13:00 בישראל
        self.assertEqual(channel.preview_at(tip), tip - dt.timedelta(hours=3))

    def test_when_word_and_clock(self):
        self.assertEqual(channel.when_word(dt.datetime(2026, 10, 28, 3, 0, tzinfo=UTC)), "הלילה")
        self.assertEqual(channel.when_word(dt.datetime(2026, 10, 31, 17, 0, tzinfo=UTC)), "הערב")
        self.assertEqual(channel.clock(dt.datetime(2026, 10, 28, 3, 0, tzinfo=UTC)), "5:00")
        self.assertEqual(channel.date_he(dt.datetime(2026, 10, 28, 3, 0, tzinfo=UTC)), "יום רביעי 28.10")

    def test_card_name(self):
        # ‏בטקסט «אצל הלייקרס», בתמונה רק «לייקרס».
        self.assertEqual(channel.card_name("LAL"), "לייקרס")
        self.assertEqual(channel.card_name("LAC"), "קליפרס")
        self.assertEqual(channel.card_name("POR"), "פורטלנד")


class Texts(unittest.TestCase):
    def test_opening_variants(self):
        self.assertEqual(channel.opening(game(home=False)), "פורטלנד ודני מתארחים הלילה (5:00) אצל הלייקרס🏀")
        self.assertEqual(channel.opening(game(home=True, abbr="NO")), "פורטלנד ודני מארחים הלילה (5:00) את ניו אורלינס🏀")
        self.assertIn("פוגשים", channel.opening(game(neutral=True)))

    def test_preview_regular(self):
        text = channel.preview_text(game(), "ספורט 5", ("Available", ""))
        self.assertEqual(text, "פורטלנד ודני מתארחים הלילה (5:00) אצל הלייקרס🏀\n\n"
                               "המשחק משודר בספורט 5🔥\n\nקישורים לשידור בתגובות🔗")

    def test_preview_doubt_and_headline(self):
        text = channel.preview_text(game(), "5MAX", ("Questionable", "Right Ankle; Sprain"), "משחק גורלי!")
        self.assertTrue(text.startswith("משחק גורלי!\n\n⚠️ דני מוגדר בספק למשחק (קרסול ימין)"))
        self.assertIn("משודר ב-5MAX", text)

    def test_preview_without_tv(self):
        self.assertNotIn("משודר", channel.preview_text(game(), "", ("Available", "")))

    def test_half(self):
        text = channel.half_text(game(), 58, 61, channel.deni_box(summary(deni=PLAYED)))
        self.assertEqual(text, "מחצית⏸️\n61-58 ללייקרס על פורטלנד\nדני עם\n12 נקודות\n4 ריבאונדים\n3 אסיסטים\nב-17 דקות")
        self.assertIn("62-58 לפורטלנד על הלייקרס", channel.half_text(game(), 62, 58, channel.deni_box(summary(deni=PLAYED))))
        self.assertIn("58-58, שוויון בין פורטלנד ללייקרס", channel.half_text(game(), 58, 58, channel.deni_box(summary(deni=PLAYED))))

    def test_final_win_ot_next(self):
        nxt = game(tip="2026-10-30T02:00:00+00:00", home=True, abbr="MEM", gid="2")
        text = channel.final_text(game(), 112, 108, 1, channel.deni_box(summary(deni=PLAYED)), nxt)
        self.assertEqual(text, "דני בניצחון 112-108 של פורטלנד על הלייקרס אחרי הארכה🔥\n"
                               "דני מסיים את המשחק עם\n12 נקודות\n4 מ-6 לשתיים\n1 מ-3 לשלוש\n1 מ-2 מהקו\n"
                               "4 ריבאונדים\n3 אסיסטים\n1 חטיפה\n1 איבוד\nב-17 דקות\n\n"
                               "משחק הבא בין חמישי לשישי (4:00) נגד ממפיס (בבית)")

    def test_next_game_evening(self):
        nxt = game(tip="2026-10-31T19:00:00+00:00", abbr="UTAH")  # ‏שבת 21:00
        self.assertEqual(channel.next_game_line(nxt), "משחק הבא בשבת (21:00) נגד יוטה (בחוץ)")

    def test_final_dnp(self):
        text = channel.final_text(game(), 100, 108, 0, channel.deni_box(summary(deni=DNP)), None)
        self.assertEqual(text, "פורטלנד מפסידה ללייקרס 108-100\nדני לא שיחק (קרסול ימין)")

    def test_status_updates(self):
        self.assertEqual(channel.status_update_text(game(), ("Available", "")), "✅ עדכון: דני כשיר וישחק הלילה!")
        self.assertEqual(channel.status_update_text(game(), ("Out", "Left Knee")), "❌ עדכון: דני לא ישחק הלילה (ברך שמאל)")


SPORT5 = """
<tr class="tr-header"><th colspan="4"><img src="x.svg" alt="ערוץ הספורט" /></th></tr>
<tr><td class="date"><div>01:30</div></td><td></td><td class="text">NBA: בוסטון - ברוקלין</td></tr>
<tr><td class="date"><div>05:00</div></td><td></td><td class="text">NBA: לוס אנג׳לס לייקרס - פורטלנד, עונה סדירה</td></tr>
<tr><td class="date"><div>12:40</div></td><td></td><td class="text">מעקבדיה: ל.א. לייקרס - פורטלנד (מוקלט)</td></tr>
<tr class="tr-header"><th><img src="y.svg" alt="ספורט מובייל" /></th></tr>
<tr><td class="date"><div>05:00</div></td><td></td><td class="text">NBA: לוס אנג׳לס לייקרס - פורטלנד</td></tr>
"""


class Sport5(unittest.TestCase):
    def test_found(self):
        self.assertEqual(channel.sport5_channel(game(), SPORT5), "ספורט 5")

    def test_only_app(self):
        page = SPORT5[SPORT5.index('<tr class="tr-header"><th><img src="y.svg"'):]
        self.assertEqual(channel.sport5_channel(game(), page), "אפליקציית ספורט 5")

    def test_time_mismatch(self):
        self.assertIsNone(channel.sport5_channel(game(tip="2026-10-28T09:00:00+00:00"), SPORT5))


class Flow(unittest.TestCase):
    """‏process() מול זמנים ומצבים שונים. ‏tg נאסף לרשימה במקום לשלוח."""

    def setUp(self):
        self.sent = []
        self.tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(channel, "STATE_PATH", os.path.join(self.tmp.name, "s.json")),
            mock.patch.object(channel, "ADMIN", "111"),
            mock.patch.object(channel, "CHANNEL", "@chan"),
            mock.patch.object(channel, "tg", self.fake_tg),
            mock.patch.object(channel, "card_for", lambda g, s: b"jpg"),
            mock.patch.object(channel, "final_card", lambda *a: b"jpg"),
            mock.patch.object(channel, "find_videos", lambda g, d: self.videos),
            mock.patch.object(channel, "sport5_channel", lambda g: "ספורט 5"),
            mock.patch.object(tracker, "hold_until", lambda now: None),
            mock.patch.object(channel, "career_log", lambda: self.log),
        ]
        self.log = []
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.injury = ("Available", "")
        mock.patch.object(channel, "injury", lambda g, official_only=False: self.injury).start()
        self.addCleanup(mock.patch.stopall)
        self.data = None
        mock.patch.object(channel, "get_json", lambda url: self.data).start()
        self.state = {"offset": 0, "games": {}}
        self.g = game()
        self.videos = {"deni": None, "game": None}

    def tearDown(self):
        self.tmp.cleanup()

    def fake_tg(self, method, params, photo=None):
        self.sent.append((method, params.get("chat_id"),
                          params.get("caption") or params.get("text") or params.get("question") or ""))
        return {"message_id": 7} if method != "getUpdates" else []

    def at(self, minutes_from_tip):
        channel.process(self.g, None, self.state, self.g["tip"] + dt.timedelta(minutes=minutes_from_tip))

    def channel_msgs(self):
        """‏בלי הסקר ובלי התשובה אליו - יש להם בדיקות משלהם."""
        return [t for m, c, t in self.sent if c == "@chan" and m in ("sendMessage", "sendPhoto")
                and not t.startswith(("✅ התשובה", "דני לא שיחק בסוף"))]

    def polls(self):
        return [(m, t) for m, c, t in self.sent if c == "@chan" and (m in ("sendPoll", "stopPoll")
                or t.startswith(("✅ התשובה", "דני לא שיחק בסוף")))]

    def test_poll_after_preview_and_answer(self):
        self.at(-17 * 60)   # ‏הודעת המשחק ב-12:00
        self.at(-14 * 60)   # ‏15:00 - הסקר
        self.at(-13 * 60)
        self.assertEqual(self.polls(), [("sendPoll", "כמה נקודות דני יקלע הלילה? 🏀")])
        self.data = summary(state="post", name="STATUS_FINAL", completed=True, periods=4, deni=PLAYED)
        self.at(150)
        self.at(160)
        self.assertEqual(self.polls()[1:], [("stopPoll", ""), ("sendMessage", "✅ התשובה: פחות מ-15 (דני קלע 12 נקודות)")])

    def test_no_poll_when_doubtful(self):
        self.injury = ("Questionable", "Ankle")
        self.at(-17 * 60)
        self.at(-14 * 60)
        self.assertEqual(self.polls(), [])

    def test_poll_answer_dnp(self):
        self.assertEqual(channel.poll_answer(channel.deni_box(summary(deni=DNP))), "דני לא שיחק בסוף, אז אין תשובה הפעם")
        row = {"MIN": "30", "PTS": "30", "dnp": False}
        self.assertEqual(channel.poll_answer(row), "✅ התשובה: 30 ומעלה (דני קלע 30 נקודות)")

    def test_milestone_posted_once(self):
        self.log = [{"id": "9", "type": 2, "season": 2027, "MIN": 30, "PTS": 9, "REB": 14, "AST": 3, "STL": 0, "BLK": 0}]
        hot = dict(PLAYED, stats=["37", "41", "15-22", "4-8", "7-8", "11", "3", "1", "1", "0", "1", "10", "2", "+5"])
        self.data = summary(state="post", name="STATUS_FINAL", completed=True, periods=4, deni=hot)
        self.at(150)
        self.at(155)
        self.assertEqual([t for t in self.channel_msgs() if "🏆" in t or "💪" in t],
                         ["🏆 שיא קריירה לדני: 41 נקודות!\n💪 דאבל-דאבל לדני, הראשון שלו העונה"])

    def test_draft_then_publish_once(self):
        self.at(-20 * 60 + 5)        # ‏9:05 → טיוטה לאיתמר
        self.assertEqual([(m, c) for m, c, _ in self.sent], [("sendPhoto", "111")])
        self.at(-20 * 60 + 10)       # ‏אין טיוטה שנייה
        self.assertEqual(len(self.sent), 1)
        self.at(-17 * 60 + 5)        # ‏12:05 → פרסום
        self.assertEqual(len(self.channel_msgs()), 1)
        self.at(-17 * 60 + 10)
        self.assertEqual(len(self.channel_msgs()), 1)

    def test_no_draft_on_shabbat(self):
        with mock.patch.object(tracker, "hold_until", lambda now: now):
            self.at(-20 * 60 + 5)
        self.assertEqual(self.sent, [])
        self.at(-17 * 60 + 5)        # ‏הפרסום יוצא בכל זאת
        self.assertEqual(len(self.channel_msgs()), 1)

    def test_publish_now_button(self):
        self.at(-20 * 60 + 5)
        self.state["games"]["1"]["go"] = True
        self.at(-20 * 60 + 10)
        self.assertEqual(len(self.channel_msgs()), 1)

    def test_skip_button(self):
        self.at(-20 * 60 + 5)
        self.state["games"]["1"]["skip"] = True
        self.at(-17 * 60 + 5)
        self.assertEqual(self.channel_msgs(), [])

    def test_manual_tv_wins(self):
        self.state["games"]["1"] = {"tv": "5MAX"}
        self.at(-17 * 60 + 5)
        self.assertIn("ב-5MAX", self.channel_msgs()[0])

    def test_doubt_resolved_once(self):
        self.injury = ("Questionable", "Right Ankle")
        self.at(-17 * 60 + 5)
        self.assertIn("בספק", self.channel_msgs()[0])
        self.at(-120)
        self.assertEqual(len(self.channel_msgs()), 1)   # ‏אין שינוי - אין הודעה
        self.injury = ("Available", "")
        self.at(-60)
        self.at(-55)
        self.assertEqual(self.channel_msgs()[1:], ["✅ עדכון: דני כשיר וישחק הלילה!"])

    def test_newly_doubtful_after_preview(self):
        self.at(-17 * 60 + 5)
        self.injury = ("Out", "Illness")
        self.at(-60)
        self.assertEqual(self.channel_msgs()[1], "❌ עדכון: דני לא ישחק הלילה (מחלה)")

    def test_questionable_then_on_court(self):
        self.injury = ("Questionable", "")
        self.at(-17 * 60 + 5)
        self.data = summary(deni=PLAYED)
        self.at(12)
        self.at(17)
        self.assertEqual(self.channel_msgs()[1:], ["✅ דני על המגרש!"])

    def test_half_only_if_played(self):
        self.state["games"]["1"] = {"preview": "x", "status": "Available"}
        self.data = summary(name="STATUS_HALFTIME", deni=PLAYED)
        self.at(70)
        self.at(75)
        self.assertEqual(len(self.channel_msgs()), 1)
        self.assertTrue(self.channel_msgs()[0].startswith("מחצית"))

    def test_no_half_if_not_played(self):
        self.state["games"]["1"] = {"preview": "x"}
        self.data = summary(name="STATUS_HALFTIME", deni=DNP)
        self.at(70)
        self.assertEqual(self.channel_msgs(), [])

    def test_final_once(self):
        self.state["games"]["1"] = {"preview": "x", "half": True}
        self.data = summary(state="post", name="STATUS_FINAL", completed=True, periods=4, deni=PLAYED)
        self.at(150)
        self.at(155)
        self.assertEqual(len(self.channel_msgs()), 1)
        self.assertTrue(self.channel_msgs()[0].startswith("פורטלנד מפסידה ללייקרס"))

    def final_then(self, played=True):
        self.state["games"]["1"] = {"preview": "x", "half": True}
        self.data = summary(state="post", name="STATUS_FINAL", completed=True, periods=4,
                            deni=PLAYED if played else DNP)
        self.at(150)   # ‏הסיום

    def test_highlights_deni_first(self):
        self.final_then()
        self.videos = {"deni": "https://youtu.be/d", "game": "https://youtu.be/g"}
        self.at(160)
        self.at(240)
        self.assertEqual(self.channel_msgs()[1:], ["🎥 ההיילייטס של דני מהמשחק\nhttps://youtu.be/d"])

    def test_highlights_waits_then_game(self):
        self.final_then()
        self.videos = {"deni": None, "game": "https://youtu.be/g"}
        self.at(160)                              # ‏10 דקות אחרי הסיום: מחכים לסרטון של דני
        self.assertEqual(len(self.channel_msgs()), 1)
        self.at(215)                              # ‏שעה וחמש: התקציר
        self.at(220)
        self.assertEqual(self.channel_msgs()[1:], ["🎥 תקציר המשחק\nhttps://youtu.be/g"])
        self.videos = {"deni": "https://youtu.be/d", "game": "https://youtu.be/g"}
        self.at(230)                              # ‏סרטון של דני שהגיע מאוחר - עדיין יוצא
        self.assertEqual(self.channel_msgs()[-1], "🎥 ההיילייטס של דני מהמשחק\nhttps://youtu.be/d")

    def test_highlights_no_wait_if_not_played(self):
        self.final_then(played=False)
        self.videos = {"deni": "https://youtu.be/d", "game": "https://youtu.be/g"}
        self.at(155)
        self.assertEqual(self.channel_msgs()[1:], ["🎥 תקציר המשחק\nhttps://youtu.be/g"])

    def test_highlights_stop_after_4h(self):
        self.final_then()
        self.videos = {"deni": "https://youtu.be/d", "game": None}
        self.at(150 + 4 * 60 + 5)
        self.assertEqual(len(self.channel_msgs()), 1)

    def test_postponed(self):
        self.state["games"]["1"] = {"preview": "x"}
        self.data = summary(state="post", name="STATUS_POSTPONED")
        self.at(30)
        self.at(35)
        self.assertEqual(self.channel_msgs(), ["📅 המשחק של פורטלנד נגד הלייקרס נדחה"])


def log_game(gid, pts=10, reb=5, ast=3, stl=0, blk=0, type_=2, season=2027, mins=30):
    return {"id": gid, "type": type_, "season": season, "MIN": mins, "PTS": pts, "REB": reb,
            "AST": ast, "STL": stl, "BLK": blk}


class Milestones(unittest.TestCase):
    def row(self, pts, reb, ast, stl=0, blk=0):
        return {"PTS": str(pts), "REB": str(reb), "AST": str(ast), "STL": str(stl), "BLK": str(blk)}

    def test_nothing_special(self):
        log = [log_game(str(i), pts=25) for i in range(10)]
        self.assertEqual(channel.milestones(game(), self.row(18, 6, 4), log), [])

    def test_career_high_and_tie(self):
        log = [log_game("1", pts=30, reb=12, ast=9)]
        self.assertEqual(channel.milestones(game(), self.row(31, 12, 2), log),
                         ["🏆 שיא קריירה לדני: 31 נקודות!", "🏆 דני השווה את שיא הקריירה שלו: 12 ריבאונדים",
                          "💪 דאבל-דאבל לדני, ה-2 שלו העונה"])   # ‏גם המשחק ב-log היה דאבל-דאבל

    def test_no_career_high_on_small_numbers(self):
        self.assertEqual(channel.milestones(game(), self.row(12, 4, 3), []), [])

    def test_double_double_count_this_season_only(self):
        log = [log_game("1", pts=20, reb=10, season=2026), log_game("2", pts=20, reb=10), log_game("3", pts=12, ast=10),
               log_game("4", pts=20, reb=10, type_=3)]
        self.assertEqual(channel.milestones(game(), self.row(15, 11, 2), log + [log_game("5", pts=40, reb=20, ast=12)]),
                         ["💪 דאבל-דאבל לדני, ה-3 שלו העונה"])

    def test_triple_double(self):
        log = [log_game("1", pts=30, reb=15, ast=12), log_game("2", pts=12, reb=10, ast=10)]
        self.assertEqual(channel.milestones(game(), self.row(14, 10, 10), log), ["🔥 טריפל-דאבל לדני! ה-3 בקריירה"])

    def test_career_totals_regular_season_only(self):
        log = [log_game(str(i), pts=25, reb=0, ast=0) for i in range(197)] + [   # ‏199 משחקים, 4,975 נקודות
            log_game("x", pts=40, reb=0, ast=0), log_game("y", pts=10, reb=0, ast=0),
            log_game("p", pts=25, reb=0, ast=0, type_=3)]
        self.assertEqual(channel.milestones(game(), self.row(30, 0, 0), log),   # ‏4,975 → 5,005
                         ["🎉 דני עבר את רף 5,000 הנקודות בקריירה ב-NBA!", "🎂 המשחק ה-200 של דני בעונה הסדירה של ה-NBA"])
        self.assertEqual(channel.milestones(game(type_=3), self.row(30, 0, 0), log), [])

    def test_career_log_season_types(self):
        def season(y):
            ev = lambda gid, pts: {"eventId": gid, "stats": ["30", str(pts)]}
            return {"labels": ["MIN", "PTS"], "seasonTypes": [
                {"displayName": f"{y} Play In Regular Season", "categories": [{"type": "event", "events": [ev(f"{y}i", 9)]}]},
                {"displayName": f"{y} Regular Season", "categories": [{"type": "event", "events": [ev(f"{y}r", 20), ev(f"{y}a", 8)]},
                                                                     {"type": "total", "events": []}]},
                {"displayName": f"{y} Postseason", "categories": [{"type": "event", "events": [ev(f"{y}p", 30)]}]},
                {"displayName": f"{y} Preseason", "categories": [{"type": "event", "events": [ev(f"{y}x", 5)]}]}],
                "events": {f"{y}{k}": {"team": {"id": "111386" if k == "a" else "22"}} for k in "irpxa"},
                "filters": [{"name": "season", "options": [{"value": "2027"}, {"value": "2026"}]}]}
        with mock.patch.object(channel, "get_json", lambda url: season(url[-4:] if "season=" in url else "2027")):
            log = channel.career_log()
        self.assertEqual([(g["id"], g["type"], g["season"], g["PTS"]) for g in log],
                         [("2027i", 5, 2027, 9), ("2027r", 2, 2027, 20), ("2027p", 3, 2027, 30),
                          ("2026i", 5, 2026, 9), ("2026r", 2, 2026, 20), ("2026p", 3, 2026, 30)])

    def test_waits_for_gamelog(self):
        prev = game(gid="8")
        with mock.patch.object(channel, "get_json", lambda url: summary(deni=PLAYED)):
            self.assertFalse(channel.log_has_previous([log_game("1")], prev))
        with mock.patch.object(channel, "get_json", lambda url: summary(deni=DNP)):
            self.assertTrue(channel.log_has_previous([log_game("1")], prev))
        self.assertTrue(channel.log_has_previous([log_game("8")], prev))


class Shots(unittest.TestCase):
    def play(self, x, y, made, who=tracker.PLAYER_ID, kind="Jump Shot", period=1, clock="5:00"):
        return {"shootingPlay": True, "scoringPlay": made, "participants": [{"athlete": {"id": who}}],
                "type": {"text": kind}, "coordinate": {"x": x, "y": y},
                "period": {"number": period}, "clock": {"displayValue": clock}}

    def test_parse(self):
        data = {"plays": [self.play(25, 1, True), self.play(3, 2, False), self.play(10, 10, True, who="1"),
                          self.play(-214748340, -214748365, True, kind="Free Throw - 1 of 2"),
                          {"shootingPlay": False, "participants": [{"athlete": {"id": tracker.PLAYER_ID}}]}]}
        self.assertEqual(channel.deni_shots(data), [(25, 1, True), (3, 2, False)])

    def test_heaves(self):
        # ‏החטאה מחצי מגרש בסוף רבע 1-3 לא נספרת. ‏קליעה כזו, או החטאה ברבע הרביעי, כן.
        data = {"plays": [self.play(25, 60, False, period=2, clock="0.0"), self.play(25, 60, True, period=2, clock="0.4"),
                          self.play(25, 60, False, period=4, clock="0.0"), self.play(25, 60, False, period=1, clock="8.0")]}
        self.assertEqual(channel.deni_shots(data), [(25, 60, True), (25, 60, False), (25, 60, False)])
        self.assertEqual(channel.deni_shots({"plays": [self.play(25, 200, False)]}), [None])

    def test_waits_until_counts_match(self):
        sent = []
        gs = {"final_at": "2026-10-28T05:30:00+00:00"}
        data = {"plays": [self.play(25, 1, True)]}
        row = {"FG": "1-2", "3PT": "0-0"}
        with mock.patch.object(channel, "tg", lambda *a: sent.append(a)):
            channel.shots_phase(game(), gs, dt.datetime(2026, 10, 28, 6, 0, tzinfo=UTC), data, row)
            self.assertEqual((sent, gs.get("shots")), ([], None))
            channel.shots_phase(game(), gs, dt.datetime(2026, 10, 28, 7, 0, tzinfo=UTC), data, row)
            self.assertEqual((sent, gs.get("shots")), ([], True))   # ‏אחרי שעה מוותרים


class Weekly(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in [mock.patch.object(channel, "STATE_PATH", os.path.join(self.tmp.name, "s.json")),
                  mock.patch.object(channel, "ADMIN", "111"), mock.patch.object(channel, "CHANNEL", "@chan"),
                  mock.patch.object(channel, "tg", self.fake_tg),
                  mock.patch.object(channel, "week_post", lambda gl: (channel.week_text([(g, None) for g in gl]), b"jpg")),
                  mock.patch.object(tracker, "hold_until", lambda now: None)]:
            p.start()
            self.addCleanup(p.stop)
        # ‏שבוע של 1.11 (ראשון): משחק בלילה שבין ראשון לשני, משחק ערב בשבת, ומשחק בלילה שבין שבת
        # ‏לראשון (שייך לשבת, ולכן לשבוע הזה). ‏ראשון בערב 8.11 - לשבוע הבא.
        self.games = [game("2026-11-02T03:00:00+00:00", gid="a", abbr="DEN"),
                      game("2026-11-07T18:00:00+00:00", gid="b", abbr="UTAH", home=True),
                      game("2026-11-08T03:00:00+00:00", gid="c"),
                      game("2026-11-08T18:00:00+00:00", gid="d")]
        self.state = {"offset": 0, "games": {}}

    def fake_tg(self, method, params, photo=None):
        self.sent.append((method, params.get("chat_id"), params.get("caption") or params.get("text") or ""))
        return {"message_id": 5}

    def at(self, hhmm, day=1):
        h, m = map(int, hhmm.split(":"))
        channel.weekly_phase(self.state, self.games, dt.datetime(2026, 11, day, h, m, tzinfo=channel.IL))

    def test_week_text(self):
        self.assertEqual(channel.week_text([(self.games[0], "ספורט 5"), (self.games[1], None)]),
                         "השבוע של דני🗓️\n\n🔸 בין ראשון לשני (5:00) נגד דנבר (בחוץ) · ספורט 5\n"
                         "🔸 בשבת (20:00) נגד יוטה (בבית)")
        self.assertEqual([g["id"] for g in channel.week_games(self.games, dt.date(2026, 11, 1))], ["a", "b", "c"])

    def test_draft_then_publish_once(self):
        self.at("7:50")
        self.at("8:00")
        self.at("10:55")
        self.assertEqual([(m, c) for m, c, t in self.sent], [("sendPhoto", "111")])
        self.at("11:00")
        self.at("11:05")
        self.at("12:00", day=2)
        self.assertEqual([c for m, c, t in self.sent if m == "sendPhoto"], ["111", "@chan"])

    def test_publish_now_and_skip(self):
        self.at("8:00")
        channel.weekly_answer(self.state, "go")
        self.at("8:05")
        self.assertEqual([c for m, c, t in self.sent if m == "sendPhoto"], ["111", "@chan"])
        self.state, self.sent = {"offset": 0, "games": {}}, []
        self.at("8:00")
        channel.weekly_answer(self.state, "skip")
        self.at("11:00")
        self.assertEqual([c for m, c, t in self.sent if m == "sendPhoto"], ["111"])

    def test_no_draft_on_holiday_still_publishes(self):
        with mock.patch.object(tracker, "hold_until", lambda now: now):
            self.at("8:00")
            self.at("11:00")
        self.assertEqual([c for m, c, t in self.sent if m == "sendPhoto"], ["@chan"])

    def test_no_games_no_post(self):
        self.games = []
        self.at("11:00")
        self.assertEqual(self.sent, [])


class Interviews(unittest.TestCase):
    def test_posts_once_only_deni(self):
        now = dt.datetime(2026, 10, 28, 7, 0, tzinfo=UTC)
        feed = [("Deni Avdija Postgame Interview | Trail Blazers 110, Kings 100", "https://yt/1", now - dt.timedelta(hours=1)),
                ("Deni Avdija Media Availability", "https://yt/2", now - dt.timedelta(hours=5)),
                ("Deni Avdija Highlights (30 PTS)", "https://yt/3", now - dt.timedelta(hours=1)),
                ("Micah Nori Postgame Interview", "https://yt/4", now - dt.timedelta(hours=1)),
                ("Deni Avdija Media Availability", "https://yt/5", now - dt.timedelta(days=2))]
        posted, state = [], {}
        with mock.patch.object(channel, "youtube", lambda cid: feed), \
                mock.patch.object(channel, "post", posted.append), mock.patch.object(channel, "save_state", lambda s: None):
            channel.interviews_phase(state, now, "POR")
            channel.interviews_phase(state, now + dt.timedelta(minutes=30), "POR")
            channel.interviews_phase(state, now + dt.timedelta(minutes=10), "POR")   # ‏לא בדקה של בדיקה
        self.assertEqual(posted, ["🎙️ דני מדבר עם התקשורת\nhttps://yt/2", "🎙️ דני אחרי המשחק\nhttps://yt/1"])


class Videos(unittest.TestCase):
    def test_find(self):
        tip = dt.datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
        g = game(tip=tip.isoformat(), abbr="SAC")
        data = summary()
        data["header"]["competitions"][0]["competitors"][1]["team"].update(name="Kings", location="Sacramento")
        data["videos"] = [{"headline": "Deni Avdija drains the three", "links": {"web": {"href": "https://espn/d"}}},
                          {"headline": "Portland vs. Sacramento: Game Highlights", "links": {"web": {"href": "https://espn/g"}}}]
        late = tip + dt.timedelta(hours=3)
        feeds = {
            channel.TEAM_YOUTUBE["POR"]: [
                ("Micah Nori Postgame Interview | Trail Blazers 110, Kings 100", "https://yt/i", late),
                ("Game Highlights: Portland Trail Blazers 110, Sacramento Kings 100", "https://yt/g", late),
                ("Game Highlights: Portland Trail Blazers 99, Phoenix Suns 98", "https://yt/old", tip - dt.timedelta(days=2)),
            ],
            channel.NBA_YOUTUBE: [("Deni Avdija Highlights | Blazers vs Kings", "https://yt/d", late),
                                  ("Deni Avdija Postgame Interview", "https://yt/x", late)],
        }
        with mock.patch.object(channel, "youtube", lambda cid: feeds[cid]):
            self.assertEqual(channel.find_videos(g, data), {"deni": "https://yt/d", "game": "https://yt/g"})
        with mock.patch.object(channel, "youtube", lambda cid: []):   # ‏אין יוטיוב: לא נופלים ל-ESPN
            self.assertEqual(channel.find_videos(g, data), {"deni": None, "game": None})


    def test_youtube_page(self):
        # ‏הגיבוי כשה-RSS של יוטיוב נופל: דף הסרטונים של הערוץ, עם «לפני X» במקום זמן.
        def item(vid, title, ago):
            return {"richItemRenderer": {"content": {"lockupViewModel": {"contentId": vid, "metadata": {
                "lockupMetadataViewModel": {"title": {"content": title}, "metadata": {"contentMetadataViewModel": {
                    "metadataRows": [{"metadataParts": [{"text": {"content": "12K views"}},
                                                        {"text": {"content": ago}}]}]}}}}}}}}
        data = {"contents": [item("aaaaaaaaaaa", "Game Highlights: Portland Trail Blazers 110, Kings 100", "2 hours ago"),
                             item("bbbbbbbbbbb", "Old", "1d ago"), item("ccccccccccc", "Live", "Streaming now"),
                             item("ddddddddddd", "Older", "2mo ago")]}
        page = f"<script>var ytInitialData = {json.dumps(data)};</script>"
        now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
        self.assertEqual(channel.youtube_page(page, now), [
            ("Game Highlights: Portland Trail Blazers 110, Kings 100", "https://www.youtube.com/watch?v=aaaaaaaaaaa",
             dt.datetime(2026, 10, 29, 10, 0, tzinfo=UTC)),
            ("Old", "https://www.youtube.com/watch?v=bbbbbbbbbbb", dt.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)),
            ("Older", "https://www.youtube.com/watch?v=ddddddddddd", dt.datetime(2026, 8, 30, 12, 0, tzinfo=UTC)),
        ])


class Updates(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.updates = []
        self.tmp = tempfile.TemporaryDirectory()
        for p in [mock.patch.object(channel, "STATE_PATH", os.path.join(self.tmp.name, "s.json")),
                  mock.patch.object(channel, "ADMIN", "111"),
                  mock.patch.object(channel, "tg", self.fake_tg)]:
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.tmp.cleanup)
        self.g = game()
        self.state = {"offset": 0, "games": {"1": {"draft": 7, "draft_status": ["Available", ""], "tv_auto": "ספורט 5"}}}

    def fake_tg(self, method, params, photo=None):
        if method == "getUpdates":
            return self.updates
        self.sent.append((method, params))
        return {}

    def test_button_changes_tv_and_refreshes(self):
        self.updates = [{"update_id": 5, "callback_query": {"id": "q", "from": {"id": 111}, "data": "1|tv|s5p"}}]
        channel.handle_updates(self.state, [self.g])
        self.assertEqual(self.state["games"]["1"]["tv"], "ספורט 5+")
        self.assertEqual(self.state["offset"], 6)
        self.assertIn("editMessageCaption", [m for m, _ in self.sent])

    def test_old_webhook_removed(self):
        calls = []

        def tg(method, params, photo=None):
            calls.append(method)
            if method == "getUpdates" and "deleteWebhook" not in calls:
                raise RuntimeError("Telegram getUpdates: Conflict: can't use getUpdates method while webhook is active")
            return []
        with mock.patch.object(channel, "tg", tg):
            channel.handle_updates(self.state, [self.g])
        self.assertEqual(calls, ["getUpdates", "deleteWebhook", "getUpdates"])

    def test_stranger_ignored(self):
        self.updates = [{"update_id": 5, "callback_query": {"id": "q", "from": {"id": 999}, "data": "1|go"}},
                        {"update_id": 6, "message": {"chat": {"type": "private", "id": 999}, "from": {"id": 999}, "text": "שלום"}}]
        channel.handle_updates(self.state, [self.g])
        self.assertNotIn("go", self.state["games"]["1"])
        self.assertNotIn("headline", self.state["games"]["1"])

    def test_headline_and_reset(self):
        msg = lambda t, i: {"update_id": i, "message": {"chat": {"type": "private", "id": 111}, "from": {"id": 111}, "text": t}}
        self.updates = [msg("הלילה המשחק החשוב בקריירה!", 1)]
        channel.handle_updates(self.state, [self.g])
        self.assertEqual(self.state["games"]["1"]["headline"], "הלילה המשחק החשוב בקריירה!")
        self.updates = [msg("/reset", 2)]
        channel.handle_updates(self.state, [self.g])
        self.assertEqual(self.state["games"]["1"]["headline"], "")


class Announce(unittest.TestCase):
    def test_text(self):
        g1 = game(tip="2026-10-22T02:00:00+00:00", home=True, abbr="PHX", gid="1")
        g2 = game(tip="2026-10-24T02:00:00+00:00", abbr="SAC", gid="2")
        past = [(g1, summary(completed=True, ours=110, theirs=100, periods=4, deni=PLAYED)),
                (g2, summary(completed=True, ours=99, theirs=101, periods=5, deni=DNP))]
        text = channel.announce_text(past, game())
        self.assertTrue(text.startswith("חוזרים לעדכן!"))
        self.assertIn("🔸 פתיחת העונה, בבית מול פיניקס: ניצחון 110-100\n"
                      "דני: 12 נקודות, 4 ריבאונדים, 3 אסיסטים ב-17 דקות", text)
        self.assertIn("🔸 24.10, בחוץ מול סקרמנטו: הפסד 101-99 אחרי הארכה\nדני לא שיחק", text)
        self.assertTrue(text.endswith("משחק הבא בין שלישי לרביעי (5:00) נגד הלייקרס (בחוץ)"))
        self.assertLess(len(text), 1024)

    def test_season_label(self):
        self.assertEqual(channel.season_label(dt.datetime(2026, 10, 26)), "עונת 2026/27")
        self.assertEqual(channel.season_label(dt.datetime(2027, 3, 1)), "עונת 2026/27")

    def test_publish_only_after_go(self):
        sent = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(channel, "tg", lambda m, p, photo=None: sent.append((m, p.get("chat_id"))) or {}), \
                mock.patch.object(channel, "STATE_PATH", os.path.join(tmp.name, "s.json")), \
                mock.patch.object(channel, "CHANNEL", "@chan"), mock.patch.object(channel, "ADMIN", "111"):
            state = {"announce": {"draft": 3, "photo": "F", "caption": "c"}}
            channel.announce_answer(state, "no")
            self.assertNotIn(("sendPhoto", "@chan"), sent)
            state = {"announce": {"draft": 3, "photo": "F", "caption": "c"}}
            channel.announce_answer(state, "go")
            channel.announce_answer(state, "go")   # ‏לחיצה כפולה - פרסום אחד
            self.assertEqual(sent.count(("sendPhoto", "@chan")), 1)


if __name__ == "__main__":
    unittest.main()
