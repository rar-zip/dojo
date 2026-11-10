#!/usr/bin/env python3
"""dojo 核心回归测试：解析、快照、回滚、CLI 端到端"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DOJO = os.path.join(ROOT, "bin", "dojo")


def load_module():
    loader = SourceFileLoader("dojo", DOJO)
    spec = importlib.util.spec_from_loader("dojo", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def readfile(path):
    with open(path) as f:
        return f.read()


class TestParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.tmp = tempfile.mkdtemp(prefix="dojo-parse-")
        os.chdir(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        os.chdir("/")
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_targets_redirect(self):
        got = self.m.targets("echo hi > out.txt")
        self.assertEqual(got, [os.path.join(self.tmp, "out.txt")])

    def test_targets_append_and_devnull(self):
        self.assertEqual(self.m.targets("echo hi >> log.txt"),
                         [os.path.join(self.tmp, "log.txt")])
        self.assertEqual(self.m.targets("echo hi > /dev/null"), [])

    def test_targets_rm(self):
        self.assertEqual(self.m.targets("rm -rf ./tmpdir"),
                         [os.path.join(self.tmp, "tmpdir")])

    def test_targets_mv_keeps_source(self):
        got = self.m.targets("mv a.txt b.txt")
        self.assertEqual(got, [os.path.join(self.tmp, "b.txt"), os.path.join(self.tmp, "a.txt")])

    def test_targets_sed_inplace(self):
        self.assertEqual(self.m.targets("sed -i 's/a/b/' f.txt"),
                         [os.path.join(self.tmp, "f.txt")])

    def test_classify(self):
        self.assertEqual(self.m.classify("apt install nginx"), "irreversible")
        self.assertEqual(self.m.classify("sudo systemctl restart nginx"), "irreversible")
        self.assertEqual(self.m.classify("echo hi > f"), "reversible")

    def test_extract_commands(self):
        text = "先这样\n```bash\necho 1\necho 2\n```\n"
        self.assertEqual(self.m.extract_commands(text), ["echo 1", "echo 2"])


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self.m = load_module()
        self.tmp = tempfile.mkdtemp(prefix="dojo-snap-")
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        self.cfg = self.m.load_config()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir("/")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_restore_existing_file(self):
        path = os.path.join(self.tmp, "a.txt")
        with open(path, "w") as f:
            f.write("old")
        snap = self.m.Snapshot(self.run_dir, 1, "rm a.txt", self.cfg)
        snap.capture()
        os.unlink(path)
        snap.restore()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(readfile(path), "old")

    def test_remove_created_file(self):
        path = os.path.join(self.tmp, "new.txt")
        snap = self.m.Snapshot(self.run_dir, 1, "echo x > new.txt", self.cfg)
        snap.capture()
        with open(path, "w") as f:
            f.write("x")
        snap.restore()
        self.assertFalse(os.path.exists(path))

    def test_restore_dir(self):
        d = os.path.join(self.tmp, "d")
        os.makedirs(d)
        with open(os.path.join(d, "x"), "w") as f:
            f.write("1")
        snap = self.m.Snapshot(self.run_dir, 1, "rm -rf d", self.cfg)
        snap.capture()
        shutil.rmtree(d)
        snap.restore()
        self.assertEqual(readfile(os.path.join(d, "x")), "1")


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-home-")
        self.conf_dir = os.path.join(self.home, ".config", "dojo")
        os.makedirs(self.conf_dir)
        with open(os.path.join(self.conf_dir, "config.toml"), "w") as f:
            f.write("[assist]\nlevel = 5\n[model]\nstream = false\n")
        self.env = dict(os.environ, HOME=self.home, DOJO_CONFIG=os.path.join(self.conf_dir, "config.toml"),
                        DOJO_STATE_DIR=os.path.join(self.home, ".local", "state", "dojo"))
        self.work = tempfile.mkdtemp(prefix="dojo-work-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def run_dojo(self, *args):
        return subprocess.run([sys.executable, DOJO, *args], env=self.env, cwd=self.work,
                              capture_output=True, text=True, timeout=60)

    def test_run_and_undo_created_file(self):
        path = os.path.join(self.work, "x.txt")
        r = self.run_dojo("run", "--yes", "echo hi > x.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(path))
        r = self.run_dojo("undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(path))

    def test_run_and_undo_deleted_file(self):
        path = os.path.join(self.work, "y.txt")
        with open(path, "w") as f:
            f.write("keep")
        r = self.run_dojo("run", "--yes", "rm y.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(path))
        self.run_dojo("undo")
        self.assertEqual(readfile(path), "keep")

    def test_level_gate(self):
        with open(os.path.join(self.conf_dir, "config.toml"), "w") as f:
            f.write("[assist]\nlevel = 3\n")
        r = self.run_dojo("run", "--yes", "echo hi > z.txt")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.work, "z.txt")))

    def test_undo_all(self):
        a = os.path.join(self.work, "a.txt")
        b = os.path.join(self.work, "b.txt")
        self.run_dojo("run", "--yes", "echo 1 > a.txt")
        self.run_dojo("run", "--yes", "echo 2 > b.txt")
        self.run_dojo("undo", "all")
        self.assertFalse(os.path.exists(b))
        # a.txt 属于更早的一次运行，undo all 只撤最近一次
        self.assertTrue(os.path.exists(a))


if __name__ == "__main__":
    unittest.main(verbosity=2)
