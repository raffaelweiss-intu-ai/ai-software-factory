"""Parallel jobs: unique ids under concurrent creation, isolated worktrees, overlap detection,
syncing a branch with a moved base. Written first, seen red."""
import json
import multiprocessing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"))
import job  # noqa: E402
import workspace  # noqa: E402

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout


def _create(args):
    root, n = args
    return job.create(Path(root), issue=n, title=f"Same title")["id"]


class IdRaceTests(unittest.TestCase):
    def test_concurrent_creates_never_share_an_id(self):
        with tempfile.TemporaryDirectory() as d:
            with multiprocessing.Pool(8) as pool:
                ids = pool.map(_create, [(d, n) for n in range(1, 25)])
            self.assertEqual(len(set(ids)), 24, f"duplicate job ids: {sorted(ids)}")
            self.assertEqual(len(list((Path(d) / "factory/jobs").iterdir())), 24)

    def test_id_after_a_gap_does_not_reuse_a_number(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = job.create(root, 1, "A")
            b = job.create(root, 2, "B")
            import shutil
            shutil.rmtree(job.job_dir(root, a["id"]))
            c = job.create(root, 3, "C")
            self.assertNotEqual(c["id"][:3], b["id"][:3])
            self.assertEqual(c["id"][:3], "003")


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        (self.root / "src").mkdir()
        for n in ("a", "b", "c"):
            (self.root / f"src/{n}.js").write_text("// v1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()


class WorkspaceTests(RepoCase):
    def test_each_job_gets_its_own_worktree_and_branch(self):
        w1 = workspace.add(self.root, "001-one", "origin/main")
        w2 = workspace.add(self.root, "002-two", "origin/main")
        self.assertNotEqual(w1, w2)
        self.assertEqual(git(w1, "branch", "--show-current").strip(), "factory/001-one")
        self.assertEqual(git(w2, "branch", "--show-current").strip(), "factory/002-two")

    def test_edits_in_one_worktree_do_not_show_in_the_other(self):
        w1 = workspace.add(self.root, "001-one", "origin/main")
        w2 = workspace.add(self.root, "002-two", "origin/main")
        (w1 / "src/a.js").write_text("// changed\n")
        self.assertEqual(git(w2, "status", "--porcelain").strip(), "")

    def test_adding_the_same_job_twice_is_idempotent(self):
        w1 = workspace.add(self.root, "001-one", "origin/main")
        self.assertEqual(workspace.add(self.root, "001-one", "origin/main"), w1)

    def test_remove_deletes_the_worktree(self):
        w1 = workspace.add(self.root, "001-one", "origin/main")
        workspace.remove(self.root, "001-one")
        self.assertFalse(w1.exists())

    def test_free_slots_ignore_jobs_waiting_for_a_human(self):
        jobs = [{"stage": "build"}, {"stage": "review"}, {"stage": "needs-human"}, {"stage": "needs-info"},
                {"stage": "merged"}, {"stage": "rejected"}]
        self.assertEqual(workspace.free_slots(jobs, concurrency=3), 1)
        self.assertEqual(workspace.free_slots(jobs, concurrency=1), 0)


class OverlapTests(RepoCase):
    def commit_on(self, name, files):
        w = workspace.add(self.root, name, "origin/main")
        for f in files:
            (w / f).write_text(f"// {name}\n")
        git(w, "add", "-A")
        git(w, "commit", "-qm", name)
        return w

    def test_disjoint_branches_do_not_overlap(self):
        self.commit_on("001-one", ["src/a.js"])
        self.commit_on("002-two", ["src/b.js"])
        self.assertEqual(workspace.overlaps(self.root, ["001-one", "002-two"], "origin/main"), [])

    def test_same_file_is_reported_with_the_pair(self):
        self.commit_on("001-one", ["src/a.js", "src/b.js"])
        self.commit_on("002-two", ["src/b.js"])
        self.commit_on("003-three", ["src/c.js"])
        out = workspace.overlaps(self.root, ["001-one", "002-two", "003-three"], "origin/main")
        self.assertEqual(out, [{"jobs": ["001-one", "002-two"], "files": ["src/b.js"]}])


class SyncTests(RepoCase):
    def test_sync_brings_in_main_when_it_moved(self):
        w = workspace.add(self.root, "001-one", "origin/main")
        (self.root / "src/c.js").write_text("// main moved\n")
        git(self.root, "commit", "-qam", "main moves")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        ok, msg = workspace.sync(self.root, "001-one", "origin/main")
        self.assertTrue(ok, msg)
        self.assertEqual((w / "src/c.js").read_text(), "// main moved\n")

    def test_sync_conflict_is_reported_and_leaves_no_half_merge(self):
        w = workspace.add(self.root, "001-one", "origin/main")
        (w / "src/a.js").write_text("// branch\n")
        git(w, "commit", "-qam", "branch edit")
        (self.root / "src/a.js").write_text("// main\n")
        git(self.root, "commit", "-qam", "main edit")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        ok, msg = workspace.sync(self.root, "001-one", "origin/main")
        self.assertFalse(ok)
        self.assertIn("src/a.js", msg)
        self.assertEqual(git(w, "status", "--porcelain").strip(), "")


if __name__ == "__main__":
    unittest.main()
