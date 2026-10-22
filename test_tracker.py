"""בדיקות יחידה: כל מסלולי ההחלטה, בלי רשת. ‏הרצה: python3 -m unittest -v test_tracker"""
import datetime as dt
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
    """‏איזו ריצה הולכת לאיזה מסלול, לפי השעה."""
    def route(self, now):
        calls = []
        with mock.patch.dict("os.environ", {"DENI_NOW": now}), \
             mock.patch.object(tracker, "current_team_id", return_value="22"), \
             mock.patch.object(tracker, "team_games", return_value=[GAME, {"id": "G2", "tip": TIP + dt.timedelta(days=2), "name": "y"}]), \
             mock.patch.object(tracker, "sent_keys", return_value=set()), \
             mock.patch.object(tracker, "pre_game", side_effect=lambda g, k: calls.append(("pre", g["id"]))), \
             mock.patch.object(tracker, "post_game", side_effect=lambda g, k: calls.append(("post", g["id"]))), \
             mock.patch.object(tracker, "in_game", side_effect=lambda g, k: calls.append(("in", g["id"]))):
            tracker.check()
        return calls

    def test_every_scheduled_offset_routes_correctly(self):
        for off in tracker.PRE_OFFSETS:
            t = TIP + dt.timedelta(minutes=off + 3)
            self.assertEqual(self.route(t.strftime("%Y-%m-%dT%H:%MZ")), [("pre", "G1")], off)
        for off in tracker.IN_OFFSETS:
            t = TIP + dt.timedelta(minutes=off + 3)
            self.assertEqual(self.route(t.strftime("%Y-%m-%dT%H:%MZ")), [("in", "G1")], off)
        for off in tracker.POST_OFFSETS:
            t = TIP + dt.timedelta(minutes=off + 3)
            self.assertEqual(self.route(t.strftime("%Y-%m-%dT%H:%MZ")), [("post", "G1")], off)

    def test_github_delay_of_40_minutes_still_works(self):
        for off in tracker.POST_OFFSETS:
            t = TIP + dt.timedelta(minutes=off + 43)
            self.assertEqual(self.route(t.strftime("%Y-%m-%dT%H:%MZ")), [("post", "G1")], off)

    def test_mid_game_goes_to_in_game(self):
        self.assertEqual(self.route("2026-10-22T03:30Z"), [("in", "G1")])

    def test_far_from_game_does_nothing(self):
        self.assertEqual(self.route("2026-10-23T02:00Z"), [])


class Schedule(unittest.TestCase):
    def test_cron_covers_exactly_the_game_offsets(self):
        """‏כל שורות ה-cron, אחרי האיחוד, מכסות בדיוק את (משחק × היסט) - לא פחות ולא יותר."""
        games = [{"id": str(i), "tip": TIP + dt.timedelta(days=d, minutes=m), "name": ""}
                 for i, (d, m) in enumerate([(0, 0), (2, 0), (3, 30), (9, 0), (10, 90), (40, 0), (41, -420)])]
        written = {}
        fake = "x\n    # >>> נוצר אוטומטית\n    # <<< נוצר אוטומטית\ny\n"

        class F:
            def __init__(self, mode="r"): self.mode = mode
            def read(self): return fake
            def write(self, s): written["t"] = s
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with mock.patch.dict("os.environ", {"DENI_NOW": "2026-10-21T00:00Z"}), \
             mock.patch.object(tracker, "current_team_id", return_value="22"), \
             mock.patch.object(tracker, "team_games", return_value=games), \
             mock.patch.object(tracker, "write_launchd"), \
             mock.patch("builtins.open", lambda p, mode="r": F(mode)):
            tracker.gen()
        fired = set()
        for mi, h, days, mo in re.findall(r"cron: '(\d+) (\d+) ([\d,]+) (\d+) \*'", written["t"]):
            for d in days.split(","):
                fired.add(dt.datetime(2026 if int(mo) >= 10 else 2027, int(mo), int(d), int(h), int(mi), tzinfo=UTC))
        expected = {g["tip"] + dt.timedelta(minutes=o + tracker.GITHUB_LAG) for g in games
                    for o in tracker.PRE_OFFSETS + tracker.IN_OFFSETS + tracker.POST_OFFSETS}
        self.assertEqual(fired, expected)


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
