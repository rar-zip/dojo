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

    def test_analyze_pipe_and_tee(self):
        got = self.m.analyze("echo hi | tee out.txt")
        self.assertEqual(got[0], [os.path.join(self.tmp, "out.txt")])

    def test_analyze_xargs_unsupported(self):
        paths, coarse, why = self.m.analyze("cat list.txt | xargs rm")
        self.assertEqual(paths, [])
        self.assertIn("xargs", why)

    def test_analyze_command_substitution(self):
        paths, coarse, why = self.m.analyze("echo $(cat a) > b.txt")
        self.assertEqual(paths, [])
        self.assertIn("命令替换", why)

    def test_analyze_coarse_for_unzip(self):
        paths, coarse, why = self.m.analyze("unzip pkg.zip")
        self.assertEqual(paths, [])
        self.assertTrue(coarse)

    def test_analyze_find_delete(self):
        os.makedirs(os.path.join(self.tmp, "logs"), exist_ok=True)
        f1 = os.path.join(self.tmp, "logs", "a.log")
        f2 = os.path.join(self.tmp, "logs", "b.log")
        for f in (f1, f2):
            open(f, "w").write("x")
        paths, coarse, why = self.m.analyze("find logs -name '*.log' -delete")
        self.assertEqual(sorted(paths), sorted([f1, f2]))
        self.assertEqual(why, "")

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
            f.write("[assist]\nlevel = 5\n[model]\nstream = false\n[stop]\ntimeout_seconds = 2\n")
        self.env = dict(os.environ, HOME=self.home, DOJO_CONFIG=os.path.join(self.conf_dir, "config.toml"),
                        DOJO_STATE_DIR=os.path.join(self.home, ".local", "state", "dojo"))
        self.work = tempfile.mkdtemp(prefix="dojo-work-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def run_dojo(self, *args):
        return subprocess.run([sys.executable, DOJO, *args], env=self.env, cwd=self.work,
                              capture_output=True, text=True, timeout=60)

    def test_quickstart_without_config(self):
        os.unlink(os.path.join(self.conf_dir, "config.toml"))
        r = self.run_dojo()
        self.assertEqual(r.returncode, 0)
        self.assertIn("三步就能用", r.stdout)

    def test_init_writes_hook(self):
        rc = os.path.join(self.home, ".bashrc")
        r = self.run_dojo("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(">>> dojo >>>", open(rc).read())

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

    def test_undo_pipe_written_file(self):
        path = os.path.join(self.work, "pipe.txt")
        r = self.run_dojo("run", "--yes", "echo hi | tee pipe.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(path))
        self.run_dojo("undo")
        self.assertFalse(os.path.exists(path))

    def test_brake_default_rollback(self):
        import pty
        import select
        import signal
        import time

        master, slave = pty.openpty()
        env = dict(self.env)
        proc = subprocess.Popen(
            [sys.executable, DOJO, "run", "sleep 30; echo x > brake.txt"],
            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=self.work,
            preexec_fn=os.setsid,
        )
        os.close(slave)

        def read_until(marker, timeout=15):
            buf = b""
            end = time.time() + timeout
            while time.time() < end:
                r, _, _ = select.select([master], [], [], 0.2)
                if r:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    if marker in buf:
                        return buf
            return buf

        try:
            out = read_until("要跑吗".encode())
            self.assertIn("要跑吗", out.decode("utf-8", "replace"))
            os.write(master, b"\n")
            time.sleep(0.6)
            os.killpg(proc.pid, signal.SIGINT)
            out = read_until("选 1-4".encode())
            self.assertIn("选 1-4", out.decode("utf-8", "replace"))
            # 什么都不按，等默认超时回滚
            out = read_until("已中断".encode(), timeout=15)
            self.assertIn("已中断", out.decode("utf-8", "replace"))
            proc.wait(timeout=10)
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
        self.assertFalse(os.path.exists(os.path.join(self.work, "brake.txt")))

    def test_level_gate(self):
        with open(os.path.join(self.conf_dir, "config.toml"), "w") as f:
            f.write("[assist]\nlevel = 3\n")
        r = self.run_dojo("run", "--yes", "echo hi > z.txt")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.work, "z.txt")))

    def test_stop_without_active_run(self):
        r = self.run_dojo("stop")
        self.assertEqual(r.returncode, 0)
        self.assertIn("现在没有在跑的任务", r.stdout)
        halt = os.path.join(self.env["DOJO_STATE_DIR"], "halt")
        self.assertFalse(os.path.exists(halt))

    def test_history_lists_runs(self):
        self.run_dojo("run", "--yes", "echo hi > h.txt")
        r = self.run_dojo("history")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 步", r.stdout)

    def test_undo_specific_run(self):
        a = os.path.join(self.work, "a1.txt")
        b = os.path.join(self.work, "b1.txt")
        self.run_dojo("run", "--yes", "echo 1 > a1.txt")
        self.run_dojo("run", "--yes", "echo 2 > b1.txt")
        runs = sorted(os.listdir(os.path.join(self.env["DOJO_STATE_DIR"], "runs")))
        r = self.run_dojo("undo", runs[0])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(a))
        self.assertTrue(os.path.exists(b))

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
