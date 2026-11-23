"""Verhaltenstests für den Dashboard-Export (export.py). Zuerst geschrieben, zuerst rot."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import export  # noqa: E402
import job  # noqa: E402

CONFIG = {"max_rounds": 3}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_job(self, stages, title="Dark mode", issue=1, notes=None):
        j = job.create(self.root, issue=issue, title=title)
        for i, s in enumerate(stages):
            note = (notes or {}).get(i, "")
            j = job.advance(self.root, j["id"], s, CONFIG, note=note)
        return j

    def round_file(self, job_id, rnd, name, text):
        d = self.root / "factory" / "jobs" / job_id / f"round-{rnd}"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)

    # --- Bereinigung ---------------------------------------------------
    def test_sanitize_removes_emails_tokens_and_home_paths(self):
        raw = "Mail a.b@example.com, Token ghp_abcdefghijklmnopqrstuvwxyz0123456789, Pfad /home/raffael/x/y"
        out = export.sanitize(raw)
        self.assertNotIn("a.b@example.com", out)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123456789", out)
        self.assertNotIn("/home/raffael", out)

    def test_sanitize_removes_long_hex_strings(self):
        out = export.sanitize("hash " + "a1" * 32)
        self.assertNotIn("a1" * 32, out)

    # --- Spalten und Chips ----------------------------------------------
    def test_job_lands_in_column_of_its_stage(self):
        self.make_job(["spec", "build"])
        data = export.build(self.root)
        self.assertEqual(data["jobs"][0]["stage"], "build")
        self.assertEqual(data["jobs"][0]["column"], "build")

    def test_chips_per_round_read_gate_and_reviews(self):
        j = self.make_job(["spec", "build", "gate", "review"])
        self.round_file(j["id"], 1, "checks.md", "GATE: PASS\n\n## Ausgabe\n")
        self.round_file(j["id"], 1, "review-code.md", "VERDICT: PASS\n")
        self.round_file(j["id"], 1, "review-security.md", "VERDICT: FAIL\n")
        data = export.build(self.root)
        chips = data["jobs"][0]["rounds"][0]["chips"]
        self.assertEqual(chips, [
            {"name": "gate", "verdict": "PASS"},
            {"name": "code", "verdict": "PASS"},
            {"name": "security", "verdict": "FAIL"},
        ])

    def test_unreadable_verdict_is_marked_unknown(self):
        j = self.make_job(["spec", "build", "gate"])
        self.round_file(j["id"], 1, "checks.md", "irgendwas\n")
        data = export.build(self.root)
        self.assertEqual(data["jobs"][0]["rounds"][0]["chips"][0]["verdict"], "UNKNOWN")

    # --- YOUR CALL -------------------------------------------------------
    def test_needs_human_job_is_your_call_with_reason(self):
        self.make_job(["spec", "build", "needs-human"], notes={2: "Approver: ESCALATE (Berechtigung)"})
        data = export.build(self.root)
        call = data["jobs"][0]["your_call"]
        self.assertTrue(call["needed"])
        self.assertIn("Berechtigung", call["reason"])
        self.assertEqual(data["summary"]["your_call"], 1)

    def test_rejected_job_shows_reason_but_is_not_your_call(self):
        self.make_job(["rejected"], notes={0: "Kundendaten an Dritte"})
        j = export.build(self.root)["jobs"][0]
        self.assertFalse(j["your_call"]["needed"])
        self.assertIn("Kundendaten", j["your_call"]["reason"])

    def test_merged_job_is_not_your_call(self):
        self.make_job(["spec", "build", "gate", "review", "approve", "merging", "merged"])
        data = export.build(self.root)
        self.assertFalse(data["jobs"][0]["your_call"]["needed"])

    # --- Wo es hakt ------------------------------------------------------
    def test_bounces_are_counted_per_origin_stage(self):
        # gate -> build (Gate rot), review -> build (Reviewer lehnt ab)
        self.make_job(["spec", "build", "gate", "build", "gate", "review", "build"])
        data = export.build(self.root)
        self.assertEqual(data["summary"]["bounces"], {"gate": 1, "review": 1})

    def test_reason_notes_are_sanitized_in_export(self):
        self.make_job(["spec", "build", "needs-human"], notes={2: "Fehler bei mail x@y.de"})
        data = export.build(self.root)
        self.assertNotIn("x@y.de", json.dumps(data))

    # --- Dateien ---------------------------------------------------------
    def test_write_creates_json_and_html_without_internal_files(self):
        j = self.make_job(["spec", "build"])
        (self.root / "factory" / "jobs" / j["id"] / "spec.md").write_text("GEHEIM-INHALT")
        out = self.root / "docs"
        export.write(self.root, out)
        self.assertTrue((out / "dashboard.json").exists())
        html = (out / "index.html").read_text()
        self.assertIn("Dark mode", html)
        self.assertNotIn("GEHEIM-INHALT", html + (out / "dashboard.json").read_text())

    def test_html_escapes_titles(self):
        self.make_job(["spec"], title="<script>alert(1)</script>")
        out = self.root / "docs"
        export.write(self.root, out)
        self.assertNotIn("<script>alert(1)</script>", (out / "index.html").read_text())

    # --- Kennzahlen, Risiko, Zeit -----------------------------------------
    def raw_job(self, job_id, stage, events, intake=None, title="Job", issue=1, round_=1):
        d = self.root / "factory" / "jobs" / job_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(json.dumps({
            "id": job_id, "issue": issue, "title": title, "stage": stage, "round": round_,
            "events": [{"at": a, "stage": s, "round": 1, "note": n} for a, s, n in events]}))
        if intake:
            (d / "intake.md").write_text(intake)

    NOW = "2026-11-15T12:00:00+00:00"

    def test_risk_and_surfaces_come_from_intake(self):
        self.raw_job("001-x", "build", [("2026-11-15T10:00:00+00:00", "intake", "")],
                     intake="DECISION: ACCEPT\nRISK: high\nSURFACES: security, ui\n")
        j = export.build(self.root, now=self.NOW)["jobs"][0]
        self.assertEqual(j["risk"], "high")
        self.assertEqual(j["surfaces"], ["security", "ui"])

    def test_missing_intake_gives_unknown_risk(self):
        self.raw_job("001-x", "build", [("2026-11-15T10:00:00+00:00", "intake", "")])
        j = export.build(self.root, now=self.NOW)["jobs"][0]
        self.assertEqual(j["risk"], "unknown")
        self.assertEqual(j["surfaces"], [])

    def test_lead_time_and_human_wait(self):
        self.raw_job("001-x", "merged", [
            ("2026-11-15T08:00:00+00:00", "intake", ""),
            ("2026-11-15T08:10:00+00:00", "build", ""),
            ("2026-11-15T08:20:00+00:00", "needs-human", "Berechtigung"),
            ("2026-11-15T09:20:00+00:00", "build", ""),
            ("2026-11-15T09:30:00+00:00", "merged", ""),
        ])
        j = export.build(self.root, now=self.NOW)["jobs"][0]
        self.assertEqual(j["lead_minutes"], 90)
        self.assertEqual(j["human_wait_minutes"], 60)
        self.assertEqual(j["machine_minutes"], 30)

    def test_open_job_waits_until_now(self):
        self.raw_job("001-x", "needs-human", [
            ("2026-11-15T10:00:00+00:00", "build", ""),
            ("2026-11-15T10:30:00+00:00", "needs-human", "Frage")])
        j = export.build(self.root, now=self.NOW)["jobs"][0]
        self.assertEqual(j["human_wait_minutes"], 90)

    def test_summary_autonomy_and_stage_minutes(self):
        self.raw_job("001-a", "merged", [("2026-11-15T08:00:00+00:00", "intake", ""),
                                         ("2026-11-15T08:10:00+00:00", "merged", "")], issue=1)
        self.raw_job("002-b", "merged", [("2026-11-15T08:00:00+00:00", "intake", ""),
                                         ("2026-11-15T08:10:00+00:00", "needs-human", ""),
                                         ("2026-11-15T09:10:00+00:00", "merged", "")], issue=2)
        s = export.build(self.root, now=self.NOW)["summary"]
        self.assertEqual(s["merged_alone"], 1)
        self.assertEqual(s["merged_with_human"], 1)
        self.assertEqual(s["stage_minutes"]["needs-human"], 60)
        self.assertEqual(s["stage_minutes"]["intake"], 20)
        self.assertEqual(s["human_wait_share"], 60 / 80)

    def test_stepper_position_of_needs_human_follows_previous_stage(self):
        self.raw_job("001-x", "needs-human", [
            ("2026-11-15T10:00:00+00:00", "intake", ""), ("2026-11-15T10:01:00+00:00", "approve", ""),
            ("2026-11-15T10:02:00+00:00", "needs-human", "x")])
        j = export.build(self.root, now=self.NOW)["jobs"][0]
        self.assertEqual(j["progress"]["position"], "approve")
        self.assertTrue(j["progress"]["waiting_for_human"])

    def test_confidence_comes_from_decision(self):
        self.raw_job("001-x", "approve", [("2026-11-15T10:00:00+00:00", "intake", "")])
        (self.root / "factory/jobs/001-x/decision.md").write_text("APPROVE\n\nCONFIDENCE: high\nCATEGORIES: none\n")
        self.assertEqual(export.build(self.root, now=self.NOW)["jobs"][0]["confidence"], "high")

    def test_confidence_missing_is_none(self):
        self.raw_job("001-x", "approve", [("2026-11-15T10:00:00+00:00", "intake", "")])
        self.assertIsNone(export.build(self.root, now=self.NOW)["jobs"][0]["confidence"])

    def test_learning_summary_reads_eval_log_and_proposals(self):
        (self.root / "factory/evals").mkdir(parents=True)
        (self.root / "factory/evals/last.json").write_text(json.dumps({"total": 9, "passed": 8, "warned": 1, "failed": 0}))
        (self.root / "factory/learning").mkdir(parents=True)
        (self.root / "factory/learning/log.jsonl").write_text(
            json.dumps({"job": "001", "outcome": "auto", "regret": False}) + "\n" +
            json.dumps({"job": "002", "outcome": "human-changed", "regret": True}) + "\n")
        (self.root / "factory/learning/proposals.md").write_text("- [ ] a/feedback-1: x\n- [x] b/feedback-1: y\n")
        L = export.build(self.root, now=self.NOW)["summary"]["learning"]
        self.assertEqual(L["evals"], {"total": 9, "passed": 8, "warned": 1, "failed": 0})
        self.assertEqual(L["logged"], 2)
        self.assertEqual(L["regrets"], 1)
        self.assertEqual(L["open_proposals"], 1)

    def test_learning_summary_is_empty_without_files(self):
        L = export.build(self.root, now=self.NOW)["summary"]["learning"]
        self.assertIsNone(L["evals"])
        self.assertEqual((L["logged"], L["regrets"], L["open_proposals"]), (0, 0, 0))

    def test_format_minutes(self):
        self.assertEqual(export.fmt_minutes(5), "5 min")
        self.assertEqual(export.fmt_minutes(80), "1 h 20 min")
        self.assertEqual(export.fmt_minutes(1380), "23 h")
        self.assertEqual(export.fmt_minutes(None), "–")

    # --- English dashboard ------------------------------------------------------
    def test_html_is_english(self):
        self.raw_job("001-x", "needs-human", [("2026-11-15T10:00:00+00:00", "intake", ""),
                                               ("2026-11-15T10:30:00+00:00", "needs-human", "Permission")],
                     intake="DECISION: ACCEPT\nRISK: high\nSURFACES: security\n")
        self.round_file("001-x", 1, "checks.md", "GATE: PASS\n")
        page = export.render_html(export.build(self.root, now=self.NOW))
        self.assertIn('<html lang="en">', page)
        for german in ("Risiko", "Runde", "Wartet", "Aufträge", "Rückfrage", "Gemergt", "Prüfer", "Fortschritt",
                       "selbstständig", "Konfidenz", "Spezifikation", "Warten"):
            self.assertNotIn(german, page)
        self.assertIn("Risk high", page)
        self.assertIn("Round 1", page)

    # --- Throughput and the path to the monthly target ---------------------------
    def config(self, targets):
        (self.root / "factory").mkdir(parents=True, exist_ok=True)
        (self.root / "factory/config.json").write_text(json.dumps({"targets": targets}))

    def three_merged(self):
        base = "2026-11-15T08:00:00+00:00"
        self.raw_job("001-a", "merged", [(base, "intake", ""), ("2026-11-15T08:10:00+00:00", "merged", "")], issue=1)
        self.raw_job("002-b", "merged", [(base, "intake", ""), ("2026-11-15T08:10:00+00:00", "merged", "")], issue=2)
        self.raw_job("003-c", "merged", [(base, "intake", ""), ("2026-11-15T08:10:00+00:00", "needs-human", ""),
                                          ("2026-11-15T09:10:00+00:00", "merged", "")], issue=3, round_=2)

    def test_throughput_defaults_to_2500_a_month(self):
        t = export.build(self.root, now=self.NOW)["summary"]["throughput"]
        self.assertEqual(t["target_per_month"], 2500)
        self.assertEqual(t["human_hours_per_week"], 10)
        self.assertEqual(t["minutes_per_human_review"], 10)
        self.assertEqual(t["merged_in_window"], 0)
        self.assertIsNone(t["auto_merge_rate"])

    def test_throughput_projection_and_capacity_model(self):
        self.config({"prs_per_month": 300, "human_hours_per_week": 7, "minutes_per_human_review": 10})
        self.three_merged()
        t = export.build(self.root, now=self.NOW)["summary"]["throughput"]
        self.assertEqual(t["merged_in_window"], 3)
        self.assertEqual(t["window_days"], 1)
        self.assertEqual(t["projected_per_month"], 90)
        self.assertAlmostEqual(t["progress_to_target"], 0.3)
        self.assertAlmostEqual(t["auto_merge_rate"], 2 / 3)
        self.assertEqual(t["human_review_capacity_per_month"], 180)
        self.assertAlmostEqual(t["required_auto_merge_rate"], 0.4)
        self.assertEqual(t["max_target_at_current_autonomy"], 540)
        self.assertAlmostEqual(t["first_pass_rate"], 2 / 3)

    def test_required_autonomy_for_the_default_target(self):
        t = export.build(self.root, now=self.NOW)["summary"]["throughput"]
        self.assertAlmostEqual(t["required_auto_merge_rate"], 1 - 257.142857 / 2500, places=3)

    def test_small_samples_are_marked_as_anecdotes(self):
        self.three_merged()
        self.assertFalse(export.build(self.root, now=self.NOW)["summary"]["throughput"]["sample_ok"])

    def test_merges_older_than_the_window_do_not_count(self):
        self.raw_job("001-a", "merged", [("2026-09-01T08:00:00+00:00", "intake", ""), ("2026-09-01T08:10:00+00:00", "merged", "")])
        self.assertEqual(export.build(self.root, now=self.NOW)["summary"]["throughput"]["merged_in_window"], 0)

    def test_escape_rate_counts_flagged_self_merges(self):
        (self.root / "factory/learning").mkdir(parents=True)
        (self.root / "factory/learning/log.jsonl").write_text(
            json.dumps({"job": "1", "outcome": "auto", "regret": True}) + "\n" +
            json.dumps({"job": "2", "outcome": "auto", "regret": False}) + "\n" +
            json.dumps({"job": "3", "outcome": "human-changed", "regret": False}) + "\n")
        self.assertAlmostEqual(export.build(self.root, now=self.NOW)["summary"]["throughput"]["escape_rate"], 0.5)

    def test_throughput_panel_names_the_target(self):
        self.three_merged()
        page = export.render_html(export.build(self.root, now=self.NOW))
        self.assertIn("Path to 2,500 PRs a month", page)
        self.assertIn("anecdote", page)

    def test_learning_summary_reports_lessons_by_level(self):
        (self.root / "factory/learning").mkdir(parents=True)
        (self.root / "factory/learning/log.jsonl").write_text("")
        (self.root / "factory/learning/levels.json").write_text(json.dumps({"a/feedback-1": "rule", "a/feedback-2": "skill"}))
        L = export.build(self.root, now=self.NOW)["summary"]["learning"]
        self.assertEqual(L["levels"], {"rule": 1, "skill": 1})


if __name__ == "__main__":
    unittest.main()
