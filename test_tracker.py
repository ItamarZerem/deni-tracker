"""בדיקות יחידה: כל מסלולי ההחלטה, בלי רשת. ‏הרצה: python3 -m unittest -v test_tracker"""
import datetime as dt
import json
import os
import re
import unittest
from unittest import mock

import tracker

UTC = dt.timezone.utc
TIP = dt.datetime(2026, 10, 22, 2, 0, tzinfo=UTC)
GAME = {"id": "G1", "tip": TIP, "name": "x"}
LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]


def summary(status="STATUS_FINAL", completed=True, deni=None, injuries=(), state=None):
    """‏summary מדומה של ESPN. ‏deni = dict של שדות השחקן, או None אם אינו ברשימה."""
    # ‏השחקן הראשון בלי id - כמו שנמצא באמת ב-boxscore של משחקים ישנים (גרם לקריסה).
    athletes = [{"athlete": {"displayName": "x"}, "didNotPlay": False, "stats": ["30"] + ["0"] * 13},
                {"athlete": {"id": "999"}, "didNotPlay": False, "stats": ["30"] + ["0"] * 13}]
    if deni is not None:
        athletes.append({"athlete": {"id": tracker.PLAYER_ID}, **deni})
    return {
        "header": {"competitions": [{"status": {"type": {"name": status, "completed": completed,
                                                          "state": state or ("post" if completed else "pre")}}}]},
        "boxscore": {"players": [{"statistics": [{"labels": LABELS, "athletes": athletes}]}]},
        "injuries": [{"injuries": list(injuries)}],
    }


def played(minutes):
    return {"didNotPlay": False, "stats": [str(minutes)] + ["7"] * 13, "reason": "COACH'S DECISION"}


class PostGame(unittest.TestCase):
    def run_post(self, data, keys=()):
        sent = []
        with mock.patch.object(tracker, "get_json", return_value=data), \
             mock.patch.object(tracker, "send", side_effect=lambda m, k, priority=3: sent.append((m, k))):
            tracker.post_game(GAME, set(keys))
        return sent

    def test_played_full(self):
        self.assertEqual(self.run_post(summary(deni=played(34))), [("🏀 דני שיחק הלילה. צפייה נעימה!", "G1-post")])

    def test_threshold_exact_10_counts_as_played(self):
        self.assertIn("🏀", self.run_post(summary(deni=played(10)))[0][0])

    def test_under_10(self):
        for m in (1, 4, 9):
            msg = self.run_post(summary(deni=played(m)))[0][0]
            self.assertEqual(msg, "⚠️ דני שיחק הלילה פחות מ-10 דקות", m)

    def test_did_not_play_flag(self):
        self.assertEqual(self.run_post(summary(deni={"didNotPlay": True, "stats": [], "reason": "INJURY"}))[0][0],
                         "❌ דני לא שיחק הלילה")

    def test_empty_stats(self):
        self.assertIn("❌", self.run_post(summary(deni={"didNotPlay": False, "stats": []}))[0][0])

    def test_zero_minutes(self):
        self.assertIn("❌", self.run_post(summary(deni=played(0)))[0][0])

    def test_not_in_boxscore(self):
        self.assertIn("❌", self.run_post(summary(deni=None))[0][0])

    def test_not_finished_sends_nothing(self):
        self.assertEqual(self.run_post(summary(status="STATUS_IN_PROGRESS", completed=False, deni=played(30))), [])

    def test_postponed(self):
        self.assertEqual(self.run_post(summary(status="STATUS_POSTPONED", completed=False))[0][0],
                         "📅 המשחק של הלילה נדחה")

    def test_quiet_confirmation_after_on_court(self):
        sent = []
        with mock.patch.object(tracker, "get_json", return_value=summary(deni=played(30))), \
             mock.patch.object(tracker, "send", side_effect=lambda m, k, priority=3: sent.append(priority)):
            tracker.post_game(GAME, {"G1-in"})
        self.assertEqual(sent, [2])

    def test_already_sent(self):
        self.assertEqual(self.run_post(summary(deni=played(30)), keys={"G1-post"}), [])

    def test_no_numbers_leak(self):
        """‏שום ספרה בהודעה חוץ מהסף - כדי שדקות/נקודות לא ידלפו בטעות."""
        for d in (played(3), played(41), {"didNotPlay": True, "stats": []}):
            msg = self.run_post(summary(deni=d))[0][0]
            self.assertEqual(set(re.findall(r"\d+", msg)) - {"10"}, set(), msg)


class InGame(unittest.TestCase):
    def run_in(self, data, keys=()):
        sent = []
        with mock.patch.object(tracker, "get_json", return_value=data), \
             mock.patch.object(tracker, "send", side_effect=lambda m, k, priority=3: sent.append((m, k))):
            tracker.in_game(GAME, set(keys))
        return sent

    def live(self, deni):
        return summary(status="STATUS_IN_PROGRESS", completed=False, state="in", deni=deni)

    def test_starter_on_court(self):
        d = {"didNotPlay": False, "starter": True, "stats": ["0"] + ["0"] * 13}
        self.assertEqual(self.run_in(self.live(d)), [("🏀 דני על המגרש, המשחק התחיל", "G1-in")])

    def test_bench_with_minutes(self):
        self.assertEqual(self.run_in(self.live({**played(3), "starter": False}))[0][1], "G1-in")

    def test_not_yet_in_is_silent(self):
        self.assertEqual(self.run_in(self.live({"didNotPlay": False, "starter": False, "stats": ["0"] * 14})), [])
        self.assertEqual(self.run_in(self.live(None)), [])

    def test_game_not_started_is_silent(self):
        self.assertEqual(self.run_in(summary(status="STATUS_SCHEDULED", completed=False, deni=played(0))), [])

    def test_postponed(self):
        self.assertEqual(self.run_in(summary(status="STATUS_POSTPONED", completed=False))[0][1], "G1-post")

    def test_not_resent(self):
        self.assertEqual(self.run_in(self.live({**played(3), "starter": True}), keys={"G1-in"}), [])


class PreGame(unittest.TestCase):
    def run_pre(self, status, keys=()):
        sent = []
        with mock.patch.object(tracker, "official_status", return_value=status), \
             mock.patch.object(tracker, "send", side_effect=lambda m, k, priority=3: sent.append((m, k))):
            tracker.pre_game(GAME, set(keys))
        return sent

    def test_questionable(self):
        self.assertEqual(self.run_pre(("Questionable", "Injury/Illness - Right Ankle Soreness")),
                         [("⚠️ דני בספק למשחק הלילה (Questionable) · קרסול ימין", "G1-pre-Questionable")])

    def test_out(self):
        self.assertEqual(self.run_pre(("Out", "Injury/Illness - Left Knee; Sprain"))[0],
                         ("❌ דני לא ישחק הלילה · ברך שמאל", "G1-pre-Out"))

    def test_doubtful(self):
        self.assertIn("Doubtful", self.run_pre(("Doubtful", "Rest"))[0][0])

    def test_unknown_reason_no_suffix(self):
        self.assertEqual(self.run_pre(("Out", "League Suspension"))[0][0], "❌ דני לא ישחק הלילה")

    def test_available_silent(self):
        self.assertEqual(self.run_pre(("Available", "")), [])
        self.assertEqual(self.run_pre(("Probable", "Right Ankle")), [])

    def test_same_status_not_resent(self):
        self.assertEqual(self.run_pre(("Questionable", "x"), keys={"G1-pre-Questionable"}), [])

    def test_downgrade_is_sent(self):
        self.assertEqual(self.run_pre(("Out", "x"), keys={"G1-pre-Questionable"})[0][1], "G1-pre-Out")

    def test_cleared_after_warning(self):
        self.assertEqual(self.run_pre(("Available", ""), keys={"G1-pre-Questionable"}),
                         [("✅ דני הוגדר כשיר למשחק הלילה", "G1-pre-ok")])
        self.assertEqual(self.run_pre(("Probable", ""), keys={"G1-pre-Questionable"})[0][1], "G1-pre-ok")
        self.assertEqual(self.run_pre(("Available", ""), keys={"G1-pre-Questionable", "G1-pre-ok"}), [])

    def test_espn_fallback(self):
        data = summary(injuries=[{"athlete": {"id": tracker.PLAYER_ID}, "status": "Out", "details": {"type": "Knee"}}])
        with mock.patch.object(tracker, "get_json", return_value=data):
            self.assertEqual(tracker.espn_status("G1"), ("Out", "Knee"))
        data = summary(injuries=[{"athlete": {"id": tracker.PLAYER_ID}, "status": "Day-To-Day", "details": {}}])
        with mock.patch.object(tracker, "get_json", return_value=data):
            self.assertEqual(tracker.espn_status("G1")[0], "Questionable")
        with mock.patch.object(tracker, "get_json", return_value=summary()):
            self.assertEqual(tracker.espn_status("G1")[0], "Available")


class Routing(unittest.TestCase):
    """‏איזו ריצה הולכת לאיזה מסלול, לפי השעה. ‏הריצות כל 10 דקות, כך שכל דקה אפשרית."""
    def route(self, now):
        calls = []
        if isinstance(now, dt.datetime):
            now = now.strftime("%Y-%m-%dT%H:%MZ")
        with mock.patch.dict("os.environ", {"DENI_NOW": now}), \
             mock.patch.object(tracker, "current_team_id", return_value="22"), \
             mock.patch.object(tracker, "team_games", return_value=[GAME, {"id": "G2", "tip": TIP + dt.timedelta(days=2), "name": "y"}]), \
             mock.patch.object(tracker, "sent_keys", return_value=set()), \
             mock.patch.object(tracker, "pre_game", side_effect=lambda g, k: calls.append(("pre", g["id"]))), \
             mock.patch.object(tracker, "post_game", side_effect=lambda g, k: calls.append(("post", g["id"]))), \
             mock.patch.object(tracker, "in_game", side_effect=lambda g, k: calls.append(("in", g["id"]))):
            tracker.check()
        return calls

    def test_every_minute_around_the_game(self):
        """‏כל דקה מ-3 שעות לפני ועד 8 שעות אחרי: המסלול הנכון, או כלום."""
        for m in range(-180, 480):
            got = self.route(TIP + dt.timedelta(minutes=m))
            if -75 <= m < 0:
                want = [("pre", "G1")]
            elif 10 <= m < 150:
                want = [("in", "G1")]
            elif 195 <= m <= 360:
                want = [("post", "G1")]
            else:
                want = []
            self.assertEqual(got, want, m)

    def test_ten_minute_cadence_hits_every_window(self):
        """‏ריצות בדקות 4, 14, 24... (כמו ה-cron): כל חלון מקבל לפחות 2 ריצות, בכל שעת פתיחה."""
        for tip_minute in range(0, 60, 5):
            tip = TIP.replace(minute=tip_minute)
            game = {"id": "G1", "tip": tip, "name": "x"}
            hits = {"pre": 0, "in": 0, "post": 0}
            t = tip - dt.timedelta(hours=3)
            t = t.replace(minute=4)
            while t < tip + dt.timedelta(hours=8):
                with mock.patch.dict("os.environ", {"DENI_NOW": t.strftime("%Y-%m-%dT%H:%MZ")}), \
                     mock.patch.object(tracker, "current_team_id", return_value="22"), \
                     mock.patch.object(tracker, "team_games", return_value=[game]), \
                     mock.patch.object(tracker, "sent_keys", return_value=set()), \
                     mock.patch.object(tracker, "pre_game", side_effect=lambda g, k: hits.__setitem__("pre", hits["pre"] + 1)), \
                     mock.patch.object(tracker, "in_game", side_effect=lambda g, k: hits.__setitem__("in", hits["in"] + 1)), \
                     mock.patch.object(tracker, "post_game", side_effect=lambda g, k: hits.__setitem__("post", hits["post"] + 1)):
                    tracker.check()
                t += dt.timedelta(minutes=10)
            self.assertTrue(all(v >= 2 for v in hits.values()), (tip_minute, hits))

    def test_post_never_before_3h15(self):
        """‏שעת ההתראה של הבוקר לא תלויה באורך המשחק."""
        for m in range(150, 195):
            self.assertEqual(self.route(TIP + dt.timedelta(minutes=m)), [], m)

    def test_far_from_game_does_nothing(self):
        self.assertEqual(self.route("2026-10-23T02:00Z"), [])


class Watch(unittest.TestCase):
    """‏מצב «שמירה» (Run workflow): שעון מדומה שמתקדם עם כל sleep."""
    def run_watch(self, start, keys_after=None, games=None):
        clock = [start]
        checks, out = [], {}
        def sleep(sec): clock[0] += dt.timedelta(seconds=sec)
        def keys():
            return {"G1-post"} if keys_after and clock[0] >= keys_after else set()
        import tempfile, os
        f = tempfile.NamedTemporaryFile("w+", delete=False)
        with mock.patch.object(tracker, "now_utc", lambda: clock[0]), \
             mock.patch("time.sleep", sleep), \
             mock.patch.object(tracker, "current_team_id", return_value="22"), \
             mock.patch.object(tracker, "team_games", return_value=games or [GAME]), \
             mock.patch.object(tracker, "sent_keys", side_effect=keys), \
             mock.patch.object(tracker, "check", side_effect=lambda: checks.append(clock[0])), \
             mock.patch.dict("os.environ", {"GITHUB_OUTPUT": f.name}):
            tracker.watch()
        cont = open(f.name).read()
        os.unlink(f.name)
        return checks, cont, clock[0]

    def test_no_game_soon(self):
        checks, cont, _ = self.run_watch(TIP - dt.timedelta(hours=31))
        self.assertEqual((checks, cont), ([], ""))

    def test_continues_after_5h30_then_resumes_to_the_end(self):
        """‏לחיצה ב-23:00 (5 שעות לפני הפתיחה): ריצה ראשונה ממשיכה, השנייה מסיימת בסוף החלון."""
        start = TIP - dt.timedelta(hours=5)
        checks, cont, t = self.run_watch(start)
        self.assertEqual(cont, "continue=true\n")
        self.assertLessEqual((t - start).total_seconds() / 60, 340)
        checks2, cont2, t2 = self.run_watch(t)
        self.assertEqual(cont2, "")
        self.assertGreaterEqual(t2, TIP + dt.timedelta(minutes=tracker.POST_WINDOW[1]))
        # ‏בין שתי הריצות יש בדיקה לפחות כל 10 דקות לאורך כל חלונות המשחק
        allc = checks + checks2
        for a, b in zip(allc, allc[1:]):
            self.assertLessEqual((b - a).total_seconds(), 600)
        self.assertLessEqual(allc[0], TIP + dt.timedelta(minutes=tracker.PRE_WINDOW[0]))
        self.assertGreaterEqual(allc[-1], TIP + dt.timedelta(minutes=tracker.POST_WINDOW[1] - 10))

    def test_stops_once_morning_message_sent(self):
        start = TIP - dt.timedelta(hours=1)
        checks, cont, t = self.run_watch(start, keys_after=TIP + dt.timedelta(minutes=200))
        self.assertEqual(cont, "")
        self.assertLess(t, TIP + dt.timedelta(minutes=215))

    def test_network_error_does_not_stop(self):
        clock = [TIP - dt.timedelta(hours=1)]
        n = [0]
        def boom():
            n[0] += 1
            raise OSError("x")
        with mock.patch.object(tracker, "now_utc", lambda: clock[0]), \
             mock.patch("time.sleep", lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=s))), \
             mock.patch.object(tracker, "current_team_id", return_value="22"), \
             mock.patch.object(tracker, "team_games", return_value=[GAME]), \
             mock.patch.object(tracker, "sent_keys", return_value=set()), \
             mock.patch.object(tracker, "check", side_effect=boom), \
             mock.patch.dict("os.environ", {"GITHUB_OUTPUT": "/dev/null"}):
            tracker.watch()
        self.assertGreater(n[0], 20)


class Shabbat(unittest.TestCase):
    """‏איתמר שומר שבת: הודעות בשבת ממתינות ב-ntfy עד אחרי ההבדלה."""
    HEB = {"items": [
        {"category": "candles", "date": "2026-10-23T17:18:00+03:00"},
        {"category": "parashat", "date": "2026-10-24"},
        {"category": "havdalah", "date": "2026-10-24T18:34:00+03:00"},
    ]}
    RELEASE = dt.datetime(2026, 10, 24, 15, 44, tzinfo=UTC)  # ‏18:34 + 10 דק', שעון ישראל

    def hold(self, now, data=None, fail=False):
        def gj(url):
            if fail:
                raise OSError("down")
            return data or self.HEB
        with mock.patch.object(tracker, "get_json", side_effect=gj):
            return tracker.hold_until(tracker.parse_time(now))

    def test_weekday_not_held(self):
        self.assertIsNone(self.hold("2026-10-22T20:00Z"))

    def test_shabbat_game_is_held_until_after_havdalah(self):
        for now in ("2026-10-23T13:30Z", "2026-10-24T01:00Z", "2026-10-24T05:20Z", "2026-10-24T15:40Z"):
            self.assertEqual(self.hold(now), self.RELEASE, now)

    def test_margins(self):
        self.assertIsNone(self.hold("2026-10-23T13:17Z"))        # ‏שעה ודקה לפני הדלקה
        self.assertEqual(self.hold("2026-10-23T13:18Z"), self.RELEASE)
        self.assertIsNone(self.hold("2026-10-24T15:44Z"))        # ‏משוחרר

    def test_fallback_when_hebcal_down(self):
        self.assertIsNotNone(self.hold("2026-10-24T05:00Z", fail=True))   # ‏שבת בבוקר
        self.assertIsNone(self.hold("2026-10-22T20:00Z", fail=True))      # ‏חמישי
        rel = self.hold("2026-10-23T12:00Z", fail=True)                    # ‏שישי 15:00
        self.assertEqual(rel.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime("%a %H:%M"), "Sat 20:30")

    def test_send_attaches_delay(self):
        bodies = []
        class R:
            def read(self): return b""
        with mock.patch.dict("os.environ", {"DENI_NOW": "2026-10-24T05:20Z"}), \
             mock.patch.object(tracker, "get_json", return_value=self.HEB), \
             mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: bodies.append(json.loads(req.data)) or R()):
            os.environ.pop("DENI_DRY", None)
            tracker.send("x", "k")
        self.assertEqual(bodies[0]["delay"], str(int(self.RELEASE.timestamp())))

    def test_send_no_delay_on_weekday(self):
        bodies = []
        class R:
            def read(self): return b""
        with mock.patch.dict("os.environ", {"DENI_NOW": "2026-10-22T05:20Z"}), \
             mock.patch.object(tracker, "get_json", return_value=self.HEB), \
             mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: bodies.append(json.loads(req.data)) or R()):
            tracker.send("x", "k")
        self.assertNotIn("delay", bodies[0])


class Misc(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(tracker.parse_time("2026-10-22T02:00Z"), TIP)
        self.assertEqual(tracker.parse_time("2026-10-22T02:00:00Z"), TIP)

    def test_reason_he(self):
        self.assertEqual(tracker.reason_he("Injury/Illness - Right Ankle; Soreness"), "קרסול ימין")
        self.assertEqual(tracker.reason_he("Injury/Illness - Left Hamstring; Strain"), "שריר אחורי בירך שמאל")
        self.assertEqual(tracker.reason_he("Rest"), "מנוחה")


if __name__ == "__main__":
    unittest.main()
