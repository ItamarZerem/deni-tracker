"""בדיקות לבוט הערוץ, בלי רשת. ‏כל המספרים כאן מומצאים."""
import datetime as dt
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
            mock.patch.object(channel, "sport5_channel", lambda g: "ספורט 5"),
            mock.patch.object(tracker, "hold_until", lambda now: None),
        ]
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

    def tearDown(self):
        self.tmp.cleanup()

    def fake_tg(self, method, params, photo=None):
        self.sent.append((method, params.get("chat_id"), params.get("caption") or params.get("text") or ""))
        return {"message_id": 7} if method != "getUpdates" else []

    def at(self, minutes_from_tip):
        channel.process(self.g, None, self.state, self.g["tip"] + dt.timedelta(minutes=minutes_from_tip))

    def channel_msgs(self):
        return [t for m, c, t in self.sent if c == "@chan"]

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

    def test_postponed(self):
        self.state["games"]["1"] = {"preview": "x"}
        self.data = summary(state="post", name="STATUS_POSTPONED")
        self.at(30)
        self.at(35)
        self.assertEqual(self.channel_msgs(), ["📅 המשחק של פורטלנד נגד הלייקרס נדחה"])


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


if __name__ == "__main__":
    unittest.main()
