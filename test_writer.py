"""בדיקות לסוכן הכתבות, בלי רשת ובלי Claude."""
import datetime as dt
import importlib.util
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = load("writer_gate", "tool/launchd/writer_gate.py")
writer = load("writer", "tool/writer.py")

UTC = dt.timezone.utc
TIP = dt.datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # יום שלישי לפנות בוקר
H = dt.timedelta(hours=1)


def game(tip=TIP, over=False, gid="1"):
    return {"id": gid, "tip": tip, "them": "DEN", "over": over}


def state(**kw):
    return {"since": (TIP - 72 * H).isoformat(), "done": {}, "tries": {}, **kw}


class Due(unittest.TestCase):
    def job(self, mode, g=None):
        return next(j for j in gate.jobs([g or game()]) if j["mode"] == mode)

    def test_preview_window(self):
        j = self.job("preview")
        self.assertFalse(gate.due_auto(j, state(), TIP - 8 * H))
        self.assertTrue(gate.due_auto(j, state(), TIP - 7 * H))
        self.assertTrue(gate.due_auto(j, state(), TIP - H))   # מחשב שהתעורר משלים
        self.assertFalse(gate.due_auto(j, state(), TIP + H))  # אחרי הפתיחה אין טעם

    def test_recap_waits_for_end_of_game(self):
        self.assertFalse(gate.due_auto(self.job("recap", game(over=True)), state(), TIP + 5 * H))
        self.assertFalse(gate.due_auto(self.job("recap"), state(), TIP + 7 * H))  # נדחה
        self.assertTrue(gate.due_auto(self.job("recap", game(over=True)), state(), TIP + 7 * H))

    def test_recap_catch_up_days_later(self):
        j = self.job("recap", game(over=True))
        self.assertTrue(gate.due_auto(j, state(), TIP + 60 * H))
        self.assertFalse(gate.due_auto(j, state(), TIP + 73 * H))

    def test_done_never_repeats(self):
        j = self.job("preview")
        self.assertFalse(gate.due_auto(j, state(done={j["key"]: "x"}), TIP - 2 * H))

    def test_games_before_install_are_ignored(self):
        j = self.job("recap", game(over=True))
        self.assertFalse(gate.due_auto(j, state(since=(TIP + 7 * H).isoformat()), TIP + 8 * H))

    def test_retries_are_spaced_and_limited(self):
        j = self.job("preview")
        now = TIP - 5 * H
        last = now - dt.timedelta(minutes=10)
        self.assertFalse(gate.due_auto(j, state(tries={j["key"]: {"n": 1, "last": last.isoformat()}}), now))
        last = now - dt.timedelta(minutes=40)
        self.assertTrue(gate.due_auto(j, state(tries={j["key"]: {"n": 1, "last": last.isoformat()}}), now))
        self.assertFalse(gate.due_auto(j, state(tries={j["key"]: {"n": 3, "last": last.isoformat()}}), now))


class Pick(unittest.TestCase):
    def test_nothing_to_do(self):
        self.assertIsNone(gate.pick_job(gate.jobs([game()]), state(), TIP - 48 * H))

    def test_manual_early_preview(self):
        j = gate.pick_job(gate.jobs([game()]), state(), TIP - 20 * H)
        self.assertEqual(j["mode"], "preview")

    def test_manual_recap_right_after_the_game(self):
        j = gate.pick_job(gate.jobs([game(over=True)]), state(), TIP + 3 * H)
        self.assertEqual(j["mode"], "recap")

    def test_due_comes_before_early(self):
        old = game(tip=TIP - 24 * H, over=True, gid="1")
        new = game(gid="2")
        j = gate.pick_job(gate.jobs([old, new]), state(since=(TIP - 96 * H).isoformat()), TIP - 12 * H)
        self.assertEqual(j["key"], "1-recap")

    def test_manual_retry_after_three_failures(self):
        jobs = gate.jobs([game()])
        s = state(tries={"1-preview": {"n": 3, "last": (TIP - 5 * H).isoformat()}})
        self.assertEqual(gate.pick_job(jobs, s, TIP - 4 * H)["key"], "1-preview")


class Missed(unittest.TestCase):
    def lines(self, now, g=None, s=None, ranges=()):
        return gate.missed_lines(gate.jobs([g or game()]), s or state(), now, list(ranges))

    def test_preview_after_tip(self):
        self.assertEqual(self.lines(TIP - H), [])
        self.assertIn("לא נכתבה", self.lines(TIP + H)[0])
        self.assertEqual(self.lines(TIP + 25 * H), [])

    def test_written_preview_not_missed(self):
        self.assertEqual(self.lines(TIP + H, s=state(done={"1-preview": "x"})), [])

    def test_recap_late(self):
        g = game(over=True)
        s = state(done={"1-preview": "x"})
        self.assertEqual(self.lines(TIP + 7 * H, g, s), [])
        self.assertIn("אפשר להפעיל ידנית", self.lines(TIP + 9 * H, g, s)[0])

    def test_shabbat_preview_is_not_a_fault(self):
        ranges = [(TIP - 10 * H, TIP + 12 * H)]
        self.assertEqual(self.lines(TIP + H, ranges=ranges), [])

    def test_no_spoilers_in_lines(self):
        for line in self.lines(TIP + 9 * H, game(over=True), state()):
            self.assertFalse(any(c.isdigit() for c in line))


class Article(unittest.TestCase):
    TEXT = "כותרת\n" + "גוף הכתבה " * 40

    def test_extract(self):
        self.assertEqual(writer.extract_article(f"הקדמה\n<article>\n{self.TEXT}\n</article>\nסוף"), self.TEXT.strip())

    def test_rejects_missing_tags_short_and_long(self):
        for bad in (self.TEXT, "<article>קצר</article>", f"<article>{'א' * 4000}</article>"):
            with self.assertRaises(RuntimeError):
                writer.extract_article(bad)

    def test_draft_hides_article_and_header_is_neutral(self):
        g = {"them": {"abbr": "DEN"}}
        msg = writer.draft_message("recap", g, "כותרת\nניצחון 110-100 <גדול>")
        head, _, body = msg["text"].partition("\n\n")
        self.assertTrue(body.startswith("<tg-spoiler>") and body.endswith("</tg-spoiler>"))
        self.assertIn("&lt;גדול&gt;", body)
        self.assertNotIn("110", head)

    def test_draft_round_trip_to_channel(self):
        g = {"them": {"abbr": "DEN"}}
        msg = writer.draft_message("preview", g, "כותרת\nפסקה")
        # טלגרם מחזיר בלחיצה את הטקסט בלי התגיות
        plain = msg["text"].replace("<tg-spoiler>", "").replace("</tg-spoiler>", "")
        self.assertEqual(writer.channel.art_text(plain), "<b>כותרת</b>\nפסקה")


class Editor(unittest.TestCase):
    DRAFT = "כותרת\n" + "פורטלנד ניצחה 117-101 עם 55 נקודות מהספסל. " * 8

    def edit(self, output=None, error=None):
        def fake(prompt):
            self.assertIn(self.DRAFT, prompt)
            if error:
                raise error
            return output
        with mock.patch.object(writer, "run_gemini", fake):
            return writer.edit_article(self.DRAFT)

    def test_claude_editor_has_no_web_tools(self):
        def fake(prompt, web):
            self.assertFalse(web)
            return "בלי תגיות"
        with mock.patch.object(writer, "run_claude", fake):
            self.assertEqual(writer.edit_article(self.DRAFT, "claude"), self.DRAFT)

    def test_uses_edited_text(self):
        edited = self.DRAFT.replace("ניצחה", "גברה")
        self.assertEqual(self.edit(f"<article>{edited}</article>"), edited.strip())

    def test_changed_number_keeps_draft(self):
        edited = self.DRAFT.replace("55", "56")
        self.assertEqual(self.edit(f"<article>{edited}</article>"), self.DRAFT)

    def test_number_turned_into_word_keeps_draft(self):
        edited = self.DRAFT.replace("55", "חמישים וחמש")
        self.assertEqual(self.edit(f"<article>{edited}</article>"), self.DRAFT)

    def test_failure_keeps_draft(self):
        self.assertEqual(self.edit(error=RuntimeError("x")), self.DRAFT)
        self.assertEqual(self.edit("בלי תגיות"), self.DRAFT)


class Feeds(unittest.TestCase):
    def test_rss_with_full_text(self):
        xml = (b'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><title>T</title>'
               b'<link>http://x</link><pubDate>Tue, 10 Nov 2026 03:00:00 GMT</pubDate><description>d</description>'
               b'<content:encoded><![CDATA[<p>full &amp; text</p>]]></content:encoded></item></channel></rss>')
        item = writer.parse_feed(xml)[0]
        self.assertEqual(item["text"], "full & text")
        self.assertEqual(item["date"], TIP)

    def test_atom_and_news_sitemap(self):
        atom = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title><link href="http://a"/>'
                b'<published>2026-11-10T03:00:00Z</published><summary>s</summary></entry></feed>')
        self.assertEqual(writer.parse_feed(atom)[0]["link"], "http://a")
        site = (b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                b'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url><loc>http://s</loc><news:news>'
                b'<news:publication_date>2026-11-10T03:00:00Z</news:publication_date><news:title>N</news:title>'
                b'</news:news></url></urlset>')
        item = writer.parse_feed(site)[0]
        self.assertEqual((item["title"], item["link"], item["date"]), ("N", "http://s", TIP))

    def test_window_and_deni_filter(self):
        items = [{"title": "אבדיה", "text": "", "date": TIP, "link": ""},
                 {"title": "אחר", "text": "", "date": TIP, "link": ""},
                 {"title": "ישן", "text": "", "date": TIP - 99 * H, "link": ""}]
        self.assertEqual(len(writer.in_range(items, TIP - H, TIP + H)), 2)
        self.assertEqual([i["title"] for i in items if writer.about_deni(i)], ["אבדיה"])


if __name__ == "__main__":
    unittest.main()
