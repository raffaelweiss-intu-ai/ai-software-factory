"""Verhaltenstests für die Evals der Fabrik (eval.py). Zuerst geschrieben, zuerst rot."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import eval as fe  # noqa: E402

CONFIG = {"escalate_always": ["auth"],
          "autonomy": {"auto_merge": True, "min_confidence": "high", "max_risk": "low",
                       "never_surfaces": ["security"], "max_auto_round": 1}}


class EvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "factory").mkdir()
        (self.root / "factory" / "config.json").write_text(json.dumps(CONFIG))

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, jid, decision="ACCEPT", risk="low", surfaces="none", verdict="APPROVE", confidence="high",
            round_=1, gate="PASS", reviews=(("code", "PASS"),)):
        d = self.root / "factory" / "jobs" / jid
        (d / f"round-{round_}").mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(json.dumps({"id": jid, "issue": 1, "title": "t", "stage": "merged", "round": round_, "events": []}))
        (d / "intake.md").write_text(f"DECISION: {decision}\nRISK: {risk}\nSURFACES: {surfaces}\n")
        (d / "decision.md").write_text(f"{verdict}\n\nCONFIDENCE: {confidence}\nCATEGORIES: none\n")
        (d / f"round-{round_}" / "checks.md").write_text(f"GATE: {gate}\n")
        for n, v in reviews:
            (d / f"round-{round_}" / f"review-{n}.md").write_text(f"VERDICT: {v}\n")

    def cases(self, *cases):
        (self.root / "factory" / "evals").mkdir(parents=True, exist_ok=True)
        (self.root / "factory" / "evals" / "cases.jsonl").write_text("\n".join(json.dumps(c) for c in cases) + "\n")

    def run_one(self, case):
        self.cases(case)
        return fe.run(self.root)["results"][0]

    def test_intake_exact_match_passes(self):
        self.job("001-a", risk="high", surfaces="security")
        r = self.run_one({"id": "i1", "kind": "intake", "job": "001-a",
                          "expect": {"decision": "ACCEPT", "risk": "high", "surfaces": ["security"]}})
        self.assertEqual(r["status"], "PASS")

    def test_wrong_decision_fails(self):
        self.job("001-a", decision="REJECT")
        r = self.run_one({"id": "i1", "kind": "intake", "job": "001-a", "expect": {"decision": "ACCEPT"}})
        self.assertEqual(r["status"], "FAIL")

    def test_underestimated_risk_fails(self):
        self.job("001-a", risk="low")
        r = self.run_one({"id": "i1", "kind": "intake", "job": "001-a", "expect": {"decision": "ACCEPT", "risk": "high"}})
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("unterschätzt", r["reason"])

    def test_overestimated_risk_only_warns(self):
        self.job("001-a", risk="high")
        r = self.run_one({"id": "i1", "kind": "intake", "job": "001-a", "expect": {"decision": "ACCEPT", "risk": "low"}})
        self.assertEqual(r["status"], "WARN")

    def test_missing_expected_surface_fails(self):
        self.job("001-a", surfaces="ui")
        r = self.run_one({"id": "i1", "kind": "intake", "job": "001-a",
                          "expect": {"decision": "ACCEPT", "surfaces": ["ui", "security"]}})
        self.assertEqual(r["status"], "FAIL")

    def test_policy_case_expects_human_for_security_surface(self):
        self.job("003-a", risk="low", surfaces="security", reviews=(("code", "PASS"), ("security", "PASS")))
        r = self.run_one({"id": "p1", "kind": "policy", "job": "003-a", "expect": {"outcome": "HUMAN"}})
        self.assertEqual(r["status"], "PASS")

    def test_policy_case_fails_when_outcome_differs(self):
        self.job("002-a")
        r = self.run_one({"id": "p1", "kind": "policy", "job": "002-a", "expect": {"outcome": "HUMAN"}})
        self.assertEqual(r["status"], "FAIL")

    def test_missing_job_fails_not_crashes(self):
        r = self.run_one({"id": "i1", "kind": "intake", "job": "999-x", "expect": {"decision": "ACCEPT"}})
        self.assertEqual(r["status"], "FAIL")

    def test_unknown_kind_fails(self):
        self.job("001-a")
        r = self.run_one({"id": "x", "kind": "magic", "job": "001-a", "expect": {}})
        self.assertEqual(r["status"], "FAIL")

    def test_summary_and_exit_code(self):
        self.job("001-a")
        self.cases({"id": "a", "kind": "intake", "job": "001-a", "expect": {"decision": "ACCEPT"}},
                   {"id": "b", "kind": "intake", "job": "001-a", "expect": {"decision": "REJECT"}})
        out = fe.run(self.root)
        self.assertEqual((out["passed"], out["failed"], out["total"]), (1, 1, 2))
        self.assertEqual(fe.main([str(self.root)]), 1)

    def test_run_writes_last_json(self):
        self.job("001-a")
        self.cases({"id": "a", "kind": "intake", "job": "001-a", "expect": {"decision": "ACCEPT"}})
        fe.run(self.root, write=True)
        self.assertTrue((self.root / "factory" / "evals" / "last.json").exists())

    def test_add_appends_case(self):
        fe.add(self.root, "intake", "001-a", {"decision": "ACCEPT", "risk": "high"})
        fe.add(self.root, "policy", "001-a", {"outcome": "HUMAN"})
        lines = (self.root / "factory" / "evals" / "cases.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["kind"], "intake")

    def test_empty_suite_is_not_a_pass(self):
        self.cases()
        self.assertEqual(fe.main([str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()
