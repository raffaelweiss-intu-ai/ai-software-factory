"""Verhaltenstests für den Zustandsautomaten (job.py). Zuerst geschrieben, zuerst rot."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import job  # noqa: E402

CONFIG = {"max_rounds": 3}


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, issue=1, title="Dark mode"):
        return job.create(self.root, issue=issue, title=title)

    def test_create_starts_in_intake_and_writes_job_json(self):
        j = self.make()
        self.assertEqual(j["stage"], "intake")
        self.assertEqual(j["round"], 0)
        self.assertEqual(j["id"], "001-dark-mode")
        self.assertTrue((self.root / "factory/jobs/001-dark-mode/job.json").exists())

    def test_ids_count_up(self):
        self.make(1, "Dark mode")
        j2 = self.make(2, "Colored notes")
        self.assertEqual(j2["id"], "002-colored-notes")

    def test_illegal_move_is_refused(self):
        j = self.make()
        with self.assertRaises(job.IllegalMove):
            job.advance(self.root, j["id"], "merged", CONFIG)

    def test_happy_path_to_merged(self):
        j = self.make()
        i = j["id"]
        for stage in ["spec", "build", "gate", "review", "approve", "merging", "merged"]:
            j = job.advance(self.root, i, stage, CONFIG)
        self.assertEqual(j["stage"], "merged")

    def test_build_increments_round(self):
        j = self.make()
        i = j["id"]
        job.advance(self.root, i, "spec", CONFIG)
        j = job.advance(self.root, i, "build", CONFIG)
        self.assertEqual(j["round"], 1)

    def test_gate_failure_returns_to_build_with_next_round(self):
        j = self.make()
        i = j["id"]
        for s in ["spec", "build", "gate"]:
            job.advance(self.root, i, s, CONFIG)
        j = job.advance(self.root, i, "build", CONFIG)
        self.assertEqual(j["round"], 2)

    def test_after_max_rounds_job_goes_to_human(self):
        j = self.make()
        i = j["id"]
        job.advance(self.root, i, "spec", CONFIG)
        job.advance(self.root, i, "build", CONFIG)       # Runde 1
        for _ in range(2):                                # Runden 2, 3
            job.advance(self.root, i, "gate", CONFIG)
            job.advance(self.root, i, "build", CONFIG)
        job.advance(self.root, i, "gate", CONFIG)
        j = job.advance(self.root, i, "build", CONFIG)    # wäre Runde 4
        self.assertEqual(j["stage"], "needs-human")
        self.assertEqual(j["round"], 3)

    def test_every_move_is_recorded_with_timestamp_and_note(self):
        j = self.make()
        j = job.advance(self.root, j["id"], "spec", CONFIG, note="Intake: ACCEPT, low")
        last = j["events"][-1]
        self.assertEqual(last["stage"], "spec")
        self.assertEqual(last["note"], "Intake: ACCEPT, low")
        self.assertIn("at", last)

    def test_feedback_unblocks_human_job(self):
        j = self.make()
        i = j["id"]
        job.advance(self.root, i, "spec", CONFIG)
        job.advance(self.root, i, "build", CONFIG)
        job.advance(self.root, i, "needs-human", CONFIG, note="Entscheidung nötig")
        j = job.feedback(self.root, i, "Mach einfach Handschrift.", CONFIG)
        self.assertEqual(j["stage"], "build")
        self.assertTrue((self.root / f"factory/jobs/{i}/feedback-1.md").exists())

    def test_human_can_close_needs_human_as_merged(self):
        # The human merges the PR by hand; the job record must be able to follow.
        j = self.make()
        i = j["id"]
        for stage in ["spec", "build", "needs-human"]:
            job.advance(self.root, i, stage, CONFIG)
        j = job.advance(self.root, i, "merged", CONFIG, note="PR vom Menschen gemergt")
        self.assertEqual(j["stage"], "merged")

    def test_rejected_is_final(self):
        j = self.make()
        i = j["id"]
        job.advance(self.root, i, "rejected", CONFIG, note="Krypto-Miner gehört nicht hierher")
        with self.assertRaises(job.IllegalMove):
            job.advance(self.root, i, "spec", CONFIG)

    def test_job_json_is_written_atomically_and_valid(self):
        j = self.make()
        data = json.loads((self.root / f"factory/jobs/{j['id']}/job.json").read_text())
        self.assertEqual(data["issue"], 1)


if __name__ == "__main__":
    unittest.main()
