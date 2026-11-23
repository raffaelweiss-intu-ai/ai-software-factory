"""Verhaltenstests für den Lernzyklus (learn.py). Zuerst geschrieben, zuerst rot."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import learn  # noqa: E402


class LearnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, jid, stage, risk="low", surfaces="none", confidence="high", events=None, feedback=0, issue=1):
        d = self.root / "factory" / "jobs" / jid
        d.mkdir(parents=True, exist_ok=True)
        ev = events or [("intake", ""), (stage, "")]
        (d / "job.json").write_text(json.dumps({
            "id": jid, "issue": issue, "title": "T " + jid, "stage": stage, "round": 1,
            "events": [{"at": f"2026-11-15T10:0{i}:00+00:00", "stage": s, "round": 1, "note": n} for i, (s, n) in enumerate(ev)]}))
        (d / "intake.md").write_text(f"DECISION: ACCEPT\nRISK: {risk}\nSURFACES: {surfaces}\n")
        (d / "decision.md").write_text(f"APPROVE\n\nCONFIDENCE: {confidence}\nCATEGORIES: none\n")
        for k in range(1, feedback + 1):
            (d / f"feedback-{k}.md").write_text(f"Entscheidung {k} von {jid}: Token hashen.")

    def lines(self):
        f = self.root / "factory" / "learning" / "log.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()]

    def test_auto_merge_is_recorded_as_auto(self):
        self.job("001-a", "merged")
        self.assertEqual(learn.record(self.root, "001-a")["outcome"], "auto")

    def test_human_without_feedback_is_unchanged(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "Frage"), ("merged", "")])
        self.assertEqual(learn.record(self.root, "001-a")["outcome"], "human-unchanged")

    def test_human_with_feedback_is_changed(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "Frage"), ("build", ""), ("merged", "")], feedback=1)
        self.assertEqual(learn.record(self.root, "001-a")["outcome"], "human-changed")

    def test_rejected_job_is_recorded(self):
        self.job("001-a", "rejected")
        self.assertEqual(learn.record(self.root, "001-a")["outcome"], "rejected")

    def test_open_job_cannot_be_recorded(self):
        self.job("001-a", "build")
        with self.assertRaises(ValueError):
            learn.record(self.root, "001-a")

    def test_record_is_idempotent(self):
        self.job("001-a", "merged")
        learn.record(self.root, "001-a")
        learn.record(self.root, "001-a")
        self.assertEqual(len(self.lines()), 1)

    def test_flag_marks_regret_and_survives_rerecord(self):
        self.job("001-a", "merged")
        learn.record(self.root, "001-a")
        learn.flag(self.root, "001-a", "Doppelbuchung in Produktion")
        learn.record(self.root, "001-a")
        e = self.lines()[0]
        self.assertTrue(e["regret"])
        self.assertIn("Doppelbuchung", e["regret_reason"])

    def test_regret_on_auto_cell_proposes_tightening(self):
        self.job("001-a", "merged")
        learn.record(self.root, "001-a")
        learn.flag(self.root, "001-a", "kaputt")
        rep = learn.report(self.root)
        self.assertTrue(any("Tighten" in p for p in rep["proposals"]))

    def test_small_sample_gives_no_loosening_proposal(self):
        for i in range(3):
            self.job(f"00{i}-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("merged", "")], issue=i)
            learn.record(self.root, f"00{i}-a")
        rep = learn.report(self.root, min_sample=5)
        self.assertFalse(any("Loosen" in p for p in rep["proposals"]))

    def test_enough_unchanged_escalations_propose_loosening(self):
        for i in range(5):
            self.job(f"00{i}-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("merged", "")], issue=i)
            learn.record(self.root, f"00{i}-a")
        rep = learn.report(self.root, min_sample=5)
        self.assertTrue(any("Loosen" in p and "low/high" in p for p in rep["proposals"]))

    def test_changed_escalation_blocks_loosening(self):
        for i in range(5):
            fb = 1 if i == 0 else 0
            self.job(f"00{i}-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")] if fb
                     else [("intake", ""), ("needs-human", "x"), ("merged", "")], feedback=fb, issue=i)
            learn.record(self.root, f"00{i}-a")
        self.assertFalse(any("Loosen" in p for p in learn.report(self.root, min_sample=5)["proposals"]))

    def test_report_never_changes_config(self):
        cfg = self.root / "factory" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"autonomy": {"max_risk": "low"}}')
        self.job("001-a", "merged")
        learn.record(self.root, "001-a")
        learn.flag(self.root, "001-a", "kaputt")
        learn.report(self.root)
        self.assertEqual(cfg.read_text(), '{"autonomy": {"max_risk": "low"}}')

    def test_lessons_lists_human_feedback_as_open_proposals(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")], feedback=2)
        learn.record(self.root, "001-a")
        n = learn.lessons(self.root)
        text = (self.root / "factory" / "learning" / "proposals.md").read_text()
        self.assertEqual(n, 2)
        self.assertIn("- [ ] 001-a/feedback-1", text)
        self.assertIn("Token hashen", text)

    def test_lessons_keeps_ticked_items(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")], feedback=1)
        learn.record(self.root, "001-a")
        learn.lessons(self.root)
        f = self.root / "factory" / "learning" / "proposals.md"
        f.write_text(f.read_text().replace("- [ ] 001-a/feedback-1", "- [x] 001-a/feedback-1"))
        learn.lessons(self.root)
        self.assertIn("- [x] 001-a/feedback-1", f.read_text())

    # --- Fix ladder and repeat detection ------------------------------------
    def categories(self, jid, cats):
        (self.root / "factory/jobs" / jid / "decision.md").write_text(f"ESCALATE\n\nCONFIDENCE: high\nCATEGORIES: {cats}\n")

    def test_record_keeps_escalation_categories(self):
        self.job("001-a", "merged")
        self.categories("001-a", "auth, permissions")
        self.assertEqual(learn.record(self.root, "001-a")["categories"], ["auth", "permissions"])

    def test_category_none_is_not_a_category(self):
        self.job("001-a", "merged")
        self.assertEqual(learn.record(self.root, "001-a")["categories"], [])

    def test_repeated_category_proposes_structural_fix(self):
        for i in range(3):
            self.job(f"00{i}-a", "merged", issue=i)
            self.categories(f"00{i}-a", "auth")
            learn.record(self.root, f"00{i}-a")
        props = learn.report(self.root)["proposals"]
        self.assertTrue(any("Make structural" in p and "auth" in p and "3" in p for p in props))

    def test_twice_is_not_yet_a_repeat(self):
        for i in range(2):
            self.job(f"00{i}-a", "merged", issue=i)
            self.categories(f"00{i}-a", "auth")
            learn.record(self.root, f"00{i}-a")
        self.assertFalse(any("Make structural" in p for p in learn.report(self.root)["proposals"]))

    def test_lessons_show_level_and_keep_ticks(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")], feedback=1)
        learn.record(self.root, "001-a")
        learn.lessons(self.root)
        learn.set_level(self.root, "001-a/feedback-1", "static-check")
        learn.lessons(self.root)
        text = (self.root / "factory/learning/proposals.md").read_text()
        self.assertIn("001-a/feedback-1 (level: static-check)", text)
        text = text.replace("- [ ]", "- [x]")
        (self.root / "factory/learning/proposals.md").write_text(text)
        learn.lessons(self.root)
        self.assertIn("- [x] 001-a/feedback-1 (level: static-check)", (self.root / "factory/learning/proposals.md").read_text())

    def test_unknown_level_is_refused(self):
        with self.assertRaises(ValueError):
            learn.set_level(self.root, "001-a/feedback-1", "vibes")

    def test_report_counts_lessons_by_level(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")], feedback=2)
        learn.record(self.root, "001-a")
        learn.set_level(self.root, "001-a/feedback-1", "rule")
        by = learn.report(self.root)["lessons_by_level"]
        self.assertEqual(by["rule"], 1)
        self.assertEqual(by["unclassified"], 1)

    def test_mostly_weak_levels_propose_pushing_up(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")], feedback=5)
        learn.record(self.root, "001-a")
        for k in range(1, 5):
            learn.set_level(self.root, f"001-a/feedback-{k}", "skill" if k < 4 else "guide")
        self.assertTrue(any("Move up the ladder" in p for p in learn.report(self.root)["proposals"]))

    def test_mostly_strong_levels_propose_nothing(self):
        self.job("001-a", "merged", events=[("intake", ""), ("needs-human", "x"), ("build", ""), ("merged", "")], feedback=5)
        learn.record(self.root, "001-a")
        for k in range(1, 5):
            learn.set_level(self.root, f"001-a/feedback-{k}", "static-check")
        self.assertFalse(any("Move up the ladder" in p for p in learn.report(self.root)["proposals"]))


if __name__ == "__main__":
    unittest.main()