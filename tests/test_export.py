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


if __name__ == "__main__":
    unittest.main()
