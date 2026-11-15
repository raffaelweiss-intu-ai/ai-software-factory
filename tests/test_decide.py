"""Verhaltenstests für die Freigabe-Regel (decide.py). Zuerst geschrieben, zuerst rot."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import decide  # noqa: E402

CONFIG = {
    "escalate_always": ["payments", "auth", "permissions", "deploy", "ci", "schema-migration", "new-dependency", "public-copy"],
    "autonomy": {"auto_merge": True, "min_confidence": "high", "max_risk": "low",
                 "never_surfaces": ["security"], "max_auto_round": 2},
}


class DecideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, verdict="APPROVE", confidence="high", categories="none", risk="low", surfaces="none",
            gate="PASS", reviews=(("code", "PASS"),), rnd=1, intake=True):
        if intake:
            (self.dir / "intake.md").write_text(f"DECISION: ACCEPT\nRISK: {risk}\nSURFACES: {surfaces}\n")
        lines = [verdict, "", "## Summary", "- x"]
        if confidence is not None:
            lines.append(f"CONFIDENCE: {confidence}")
        lines.append(f"CATEGORIES: {categories}")
        (self.dir / "decision.md").write_text("\n".join(lines) + "\n")
        r = self.dir / f"round-{rnd}"
        r.mkdir(exist_ok=True)
        (r / "checks.md").write_text(f"GATE: {gate}\n")
        for name, v in reviews:
            (r / f"review-{name}.md").write_text(f"VERDICT: {v}\n")
        return decide.decide(self.dir, rnd, CONFIG)

    def test_clean_low_risk_job_merges_alone(self):
        out = self.job()
        self.assertEqual(out["outcome"], "AUTO-MERGE")
        self.assertEqual(out["reasons"], [])

    def test_escalate_verdict_goes_to_human(self):
        out = self.job(verdict="ESCALATE")
        self.assertEqual(out["outcome"], "HUMAN")

    def test_medium_confidence_goes_to_human(self):
        self.assertEqual(self.job(confidence="medium")["outcome"], "HUMAN")

    def test_missing_confidence_counts_as_low(self):
        out = self.job(confidence=None)
        self.assertEqual(out["outcome"], "HUMAN")
        self.assertTrue(any("Konfidenz" in r for r in out["reasons"]))

    def test_medium_risk_goes_to_human(self):
        self.assertEqual(self.job(risk="medium")["outcome"], "HUMAN")

    def test_unknown_risk_without_intake_goes_to_human(self):
        self.assertEqual(self.job(intake=False)["outcome"], "HUMAN")

    def test_security_surface_goes_to_human(self):
        self.assertEqual(self.job(surfaces="security")["outcome"], "HUMAN")

    def test_ui_surface_alone_may_merge_alone(self):
        self.assertEqual(self.job(surfaces="ui", reviews=(("code", "PASS"), ("ui", "PASS")))["outcome"], "AUTO-MERGE")

    def test_reported_escalation_category_goes_to_human(self):
        out = self.job(categories="auth")
        self.assertEqual(out["outcome"], "HUMAN")
        self.assertTrue(any("auth" in r for r in out["reasons"]))

    def test_failed_review_goes_to_human(self):
        self.assertEqual(self.job(reviews=(("code", "PASS"), ("security", "FAIL")))["outcome"], "HUMAN")

    def test_gate_not_pass_goes_to_human(self):
        self.assertEqual(self.job(gate="FAIL")["outcome"], "HUMAN")

    def test_no_reviews_goes_to_human(self):
        self.assertEqual(self.job(reviews=())["outcome"], "HUMAN")

    def test_late_round_goes_to_human(self):
        self.assertEqual(self.job(rnd=3)["outcome"], "HUMAN")

    def test_auto_merge_switched_off_always_goes_to_human(self):
        cfg = json.loads(json.dumps(CONFIG))
        cfg["autonomy"]["auto_merge"] = False
        self.job()
        self.assertEqual(decide.decide(self.dir, 1, cfg)["outcome"], "HUMAN")

    def test_missing_autonomy_config_is_strict(self):
        self.job()
        self.assertEqual(decide.decide(self.dir, 1, {"escalate_always": []})["outcome"], "HUMAN")

    def test_reasons_accumulate(self):
        out = self.job(confidence="low", risk="high", surfaces="security")
        self.assertGreaterEqual(len(out["reasons"]), 3)

    def test_cli_exit_codes(self):
        self.job()
        cfgfile = self.dir / "config.json"
        cfgfile.write_text(json.dumps(CONFIG))
        self.assertEqual(decide.main([str(self.dir), "1", str(cfgfile)]), 0)
        self.job(confidence="low")
        self.assertEqual(decide.main([str(self.dir), "1", str(cfgfile)]), 1)


if __name__ == "__main__":
    unittest.main()
