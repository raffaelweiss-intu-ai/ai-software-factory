"""Behaviour tests for verify.py: the feature map and the verification step. Written first, seen red."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import verify  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"})


MAP = {
    "ignore": ["test/*", "docs/*", "*.md"],
    "features": [
        {"id": "booking", "description": "A customer books a slot", "paths": ["src/store.js"],
         "verify": {"cmd": "bash factory/verify/booking.sh", "timeout": 20}},
        {"id": "page", "description": "The booking page renders", "paths": ["src/page.js", "src/server.js"],
         "verify": {"cmd": "bash factory/verify/page.sh", "timeout": 20}},
    ],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "main")
        (self.root / "src").mkdir()
        (self.root / "factory/verify").mkdir(parents=True)
        for f in ("store", "page", "server"):
            (self.root / f"src/{f}.js").write_text("// v1\n")
        (self.root / "factory/verify/features.json").write_text(json.dumps(MAP))
        (self.root / "factory/verify/booking.sh").write_text("echo booked; exit 0\n")
        (self.root / "factory/verify/page.sh").write_text("echo page; exit 0\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.root, "checkout", "-qb", "factory/x")

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, rel, text="// v2\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", f"change {rel}")


class MapTests(Base):
    def test_valid_map_has_no_problems(self):
        self.assertEqual(verify.check_map(self.root), [])

    def test_duplicate_id_and_missing_recipe_are_reported(self):
        bad = json.loads(json.dumps(MAP))
        bad["features"].append(dict(bad["features"][0]))
        bad["features"][1]["verify"]["cmd"] = "bash factory/verify/nope.sh"
        (self.root / "factory/verify/features.json").write_text(json.dumps(bad))
        problems = " ".join(verify.check_map(self.root))
        self.assertIn("duplicate", problems)
        self.assertIn("nope.sh", problems)

    def test_path_pattern_that_matches_no_file_is_reported(self):
        bad = json.loads(json.dumps(MAP))
        bad["features"][0]["paths"] = ["src/gone.js"]
        (self.root / "factory/verify/features.json").write_text(json.dumps(bad))
        self.assertIn("matches no file", " ".join(verify.check_map(self.root)))


class PlanTests(Base):
    def test_changed_file_maps_to_its_feature(self):
        self.change("src/store.js")
        plan = verify.plan(self.root, "origin/main")
        self.assertEqual([f["id"] for f in plan["features"]], ["booking"])
        self.assertEqual(plan["gaps"], [])

    def test_two_files_one_feature_run_once(self):
        self.change("src/page.js")
        self.change("src/server.js")
        plan = verify.plan(self.root, "origin/main")
        self.assertEqual([f["id"] for f in plan["features"]], ["page"])

    def test_unmapped_source_file_is_a_gap(self):
        self.change("src/mailer.js")
        plan = verify.plan(self.root, "origin/main")
        self.assertEqual(plan["gaps"], ["src/mailer.js"])

    def test_ignored_files_are_neither_features_nor_gaps(self):
        self.change("docs/guide.md")
        self.change("test/x.test.js")
        plan = verify.plan(self.root, "origin/main")
        self.assertEqual((plan["features"], plan["gaps"]), ([], []))


class RunTests(Base):
    def test_passing_recipes_pass_and_keep_their_output_as_evidence(self):
        self.change("src/store.js")
        verdict, report = verify.run(self.root, "origin/main")
        self.assertEqual(verdict, "PASS")
        self.assertIn("VERIFY: PASS", report)
        self.assertIn("booked", report)
        self.assertIn("VERIFY-GAPS: 0", report)

    def test_failing_recipe_fails(self):
        (self.root / "factory/verify/booking.sh").write_text("echo broken >&2; exit 3\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "break recipe")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.change("src/store.js")
        verdict, report = verify.run(self.root, "origin/main")
        self.assertEqual(verdict, "FAIL")
        self.assertIn("broken", report)

    def test_slow_recipe_times_out_and_fails(self):
        slow = json.loads(json.dumps(MAP))
        slow["features"][0]["verify"] = {"cmd": "sleep 5", "timeout": 1}
        (self.root / "factory/verify/features.json").write_text(json.dumps(slow))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "slow")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.change("src/store.js")
        verdict, report = verify.run(self.root, "origin/main")
        self.assertEqual(verdict, "FAIL")
        self.assertIn("timed out", report)

    def test_gap_passes_the_run_but_is_counted_for_the_approval_rule(self):
        self.change("src/mailer.js")
        verdict, report = verify.run(self.root, "origin/main")
        self.assertEqual(verdict, "PASS")
        self.assertIn("VERIFY-GAPS: 1", report)
        self.assertIn("src/mailer.js", report)

    def test_no_map_means_no_verification_and_says_so(self):
        (self.root / "factory/verify/features.json").unlink()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "no map")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.change("src/store.js")
        verdict, report = verify.run(self.root, "origin/main")
        self.assertEqual(verdict, "SKIP")
        self.assertIn("VERIFY: SKIP", report)


if __name__ == "__main__":
    unittest.main()
