"""Tests für Gate (gate.py) und Routing (route.py)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import gate  # noqa: E402
import route  # noqa: E402

PROTECTED = ["factory/checks.sh", "factory/config.json", ".github/*", "policy/*"]


class GateTests(unittest.TestCase):
    def test_modifying_protected_file_is_a_hit(self):
        hits = gate.protected_hits(["M\tfactory/checks.sh"], PROTECTED)
        self.assertEqual(hits, ["M factory/checks.sh"])

    def test_deleting_protected_file_is_a_hit(self):
        self.assertEqual(gate.protected_hits(["D\tpolicy/agent.rego"], PROTECTED), ["D policy/agent.rego"])

    def test_adding_new_file_under_protected_path_is_fine(self):
        self.assertEqual(gate.protected_hits(["A\tpolicy/neu.rego"], PROTECTED), [])

    def test_rename_checks_the_old_path(self):
        hits = gate.protected_hits(["R100\tfactory/config.json\tsrc/x.json"], PROTECTED)
        self.assertEqual(hits, ["R factory/config.json"])

    def test_unrelated_files_pass(self):
        self.assertEqual(gate.protected_hits(["M\tsrc/app.ts"], PROTECTED), [])

    def test_failing_checks_give_fail_and_log_tail(self):
        with tempfile.TemporaryDirectory() as d:
            verdict, log = gate.run_checks(["bash", "-c", "echo böse >&2; exit 3"], Path(d))
        self.assertEqual(verdict, "FAIL")
        self.assertIn("böse", log)

    def test_passing_checks(self):
        with tempfile.TemporaryDirectory() as d:
            verdict, _ = gate.run_checks(["bash", "-c", "exit 0"], Path(d))
        self.assertEqual(verdict, "PASS")

    def test_protected_hit_fails_even_if_checks_pass(self):
        self.assertEqual(gate.decide("PASS", ["M factory/checks.sh"]), "FAIL")
        self.assertEqual(gate.decide("PASS", []), "PASS")
        self.assertEqual(gate.decide("FAIL", []), "FAIL")


CFG = {
    "builder_model": "opus",
    "reviewer_floor": "sonnet",
    "routing": {"low": {"code": "haiku"}, "medium": {"code": "sonnet"}, "high": {"code": "sonnet"}},
    "surface_reviewers": {"ui": {"ux": "sonnet", "ui": "haiku"}, "security": {"security": "opus"}},
}


class RouteTests(unittest.TestCase):
    def test_low_risk_without_surfaces_gets_one_reviewer(self):
        self.assertEqual(list(route.route("low", [], CFG)), ["code"])

    def test_floor_lifts_weak_reviewer_models(self):
        r = route.route("low", [], CFG)
        self.assertEqual(r["code"], "sonnet")  # Konfiguration sagte haiku, Untergrenze hebt an

    def test_ui_surface_adds_two_reviewers(self):
        r = route.route("medium", ["ui"], CFG)
        self.assertEqual(sorted(r), ["code", "ui", "ux"])
        self.assertEqual(r["ui"], "sonnet")

    def test_security_surface_gets_strong_model(self):
        self.assertEqual(route.route("high", ["security"], CFG)["security"], "opus")

    def test_unknown_risk_is_an_error_not_a_default(self):
        with self.assertRaises(ValueError):
            route.route("mittel", [], CFG)

    def test_unknown_surface_is_an_error(self):
        with self.assertRaises(ValueError):
            route.route("low", ["gpu"], CFG)


if __name__ == "__main__":
    unittest.main()


class ReportTests(unittest.TestCase):
    def test_report_is_english_and_lists_protected_hits(self):
        text = gate.render_report("FAIL", ["M factory/checks.sh"], "boom")
        self.assertTrue(text.startswith("GATE: FAIL"))
        self.assertIn("Protected files changed", text)
        self.assertIn("- M factory/checks.sh", text)
        self.assertIn("Output of the checks (tail)", text)


class BaseChecksTests(unittest.TestCase):
    """The checks come from the base branch, not from the branch under test."""

    def test_checks_script_is_taken_from_base_not_from_branch(self):
        import subprocess

        def sh(*a, cwd):
            subprocess.run(a, cwd=cwd, check=True, capture_output=True)

        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            sh("git", "init", "-q", "-b", "main", cwd=repo)
            sh("git", "config", "user.email", "t@example.com", cwd=repo)
            sh("git", "config", "user.name", "t", cwd=repo)
            (repo / "factory").mkdir()
            (repo / "factory/checks.sh").write_text("exit 1\n")
            sh("git", "add", "-A", cwd=repo)
            sh("git", "commit", "-qm", "base", cwd=repo)
            sh("git", "checkout", "-qb", "factory/x", cwd=repo)
            (repo / "factory/checks.sh").write_text("exit 0\n")  # branch tries to make itself green
            sh("git", "commit", "-qam", "cheat", cwd=repo)
            script = gate.base_checks_script(repo, "main", "factory/checks.sh")
            try:
                verdict, _ = gate.run_checks(["bash", str(script)], repo)
            finally:
                script.unlink()
        self.assertEqual(verdict, "FAIL")
