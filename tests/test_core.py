#!/usr/bin/env python3
"""dojo 核心回归测试：解析、策略引擎、脱敏、快照、回滚、CLI 端到端"""
import importlib.util
from importlib.machinery import SourceFileLoader
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DOJO = os.path.join(ROOT, "bin", "dojo")


def load_module():
    loader = SourceFileLoader("dojo", DOJO)
    spec = importlib.util.spec_from_loader("dojo", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def readfile(path):
    with open(path, encoding="utf-8") as f:
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

    def test_targets_rm_cp_mv_with_force_flag(self):
        self.assertEqual(self.m.targets("rm -f a.txt"),
                         [os.path.join(self.tmp, "a.txt")])
        self.assertEqual(self.m.targets("cp -f src.txt dst.txt"),
                         [os.path.join(self.tmp, "dst.txt")])
        self.assertEqual(self.m.targets("mv -f src.txt dst.txt"),
                         [os.path.join(self.tmp, "dst.txt"), os.path.join(self.tmp, "src.txt")])

    def test_targets_cp_into_existing_dir(self):
        sub = os.path.join(self.tmp, "exist_dir")
        os.makedirs(sub, exist_ok=True)
        got = self.m.targets("cp foo.txt exist_dir")
        self.assertEqual(got, [os.path.join(sub, "foo.txt")])

    def test_targets_mv_keeps_source(self):
        got = self.m.targets("mv a.txt b.txt")
        self.assertEqual(got, [os.path.join(self.tmp, "b.txt"), os.path.join(self.tmp, "a.txt")])

    def test_targets_sed_inplace(self):
        self.assertEqual(self.m.targets("sed -i 's/a/b/' f.txt"),
                         [os.path.join(self.tmp, "f.txt")])
        self.assertEqual(self.m.targets("sed -i -e 's/a/b/' f2.txt"),
                         [os.path.join(self.tmp, "f2.txt")])
        self.assertEqual(self.m.targets("sed -i.bak 's/a/b/' f3.txt"),
                         [os.path.join(self.tmp, "f3.txt"), os.path.join(self.tmp, "f3.txt.bak")])

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
            with open(f, "w", encoding="utf-8") as fp:
                fp.write("x")
        paths, coarse, why = self.m.analyze("find logs -name '*.log' -delete")
        self.assertEqual(sorted(paths), sorted([f1, f2]))
        self.assertEqual(why, "")

    def test_classify_and_compound(self):
        self.assertEqual(self.m.classify("apt install nginx"), "irreversible")
        self.assertEqual(self.m.classify("sudo systemctl restart nginx"), "irreversible")
        self.assertEqual(self.m.classify("echo ok && sudo systemctl restart nginx"), "irreversible")
        self.assertEqual(self.m.classify("echo hi > f"), "reversible")

    def test_suggest_inverse(self):
        self.assertIn("sudo apt remove nginx", self.m.suggest_inverse("sudo apt install -y nginx"))
        self.assertIn("sudo systemctl stop redis", self.m.suggest_inverse("systemctl start redis"))
        self.assertIn("pip3 uninstall requests", self.m.suggest_inverse("pip3 install requests"))

    def test_policy_engine_blocks_deny_paths_and_destructive(self):
        cfg = self.m.load_config()
        ok1, risk1, _ = self.m.check_policy("echo hack > /etc/passwd", cfg)
        self.assertFalse(ok1)
        self.assertEqual(risk1, "blocked")
        ok2, risk2, _ = self.m.check_policy("rm -rf /", cfg)
        self.assertFalse(ok2)
        self.assertEqual(risk2, "blocked")
        ok3, risk3, _ = self.m.check_policy("mkfs.ext4 /dev/sdb1", cfg)
        self.assertFalse(ok3)
        self.assertEqual(risk3, "blocked")

    def test_redact_sensitive(self):
        raw = "export DEEPSEEK_API_KEY=sk-1234567890abcdef1234 password=mysecret99 Authorization: Bearer abcdef12345678"
        cleaned = self.m.redact_sensitive(raw)
        self.assertNotIn("sk-1234567890abcdef1234", cleaned)
        self.assertNotIn("mysecret99", cleaned)
        self.assertIn("REDACTED", cleaned)

    def test_build_messages_with_history(self):
        cfg = self.m.load_config()
        msgs = self.m.build_messages(cfg, [], "第二问", 3, history=[
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
        ])
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["content"], "第一问")
        self.assertEqual(msgs[2]["content"], "第一答")
        self.assertEqual(msgs[-1]["content"], "第二问")

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
        with open(path, "w", encoding="utf-8") as f:
            f.write("old")
        snap = self.m.Snapshot(self.run_dir, 1, "rm -f a.txt", self.cfg)
        snap.capture()
        os.unlink(path)
        snap.restore()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(readfile(path), "old")

    def test_remove_created_file(self):
        path = os.path.join(self.tmp, "new.txt")
        snap = self.m.Snapshot(self.run_dir, 1, "echo x > new.txt", self.cfg)
        snap.capture()
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        snap.restore()
        self.assertFalse(os.path.exists(path))

    def test_remove_created_nested_mkdir_p(self):
        leaf = os.path.join(self.tmp, "p1", "p2", "p3")
        snap = self.m.Snapshot(self.run_dir, 1, "mkdir -p p1/p2/p3", self.cfg)
        snap.capture()
        os.makedirs(leaf, exist_ok=True)
        snap.restore()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "p1")))

    def test_restore_dir(self):
        d = os.path.join(self.tmp, "d")
        os.makedirs(d)
        with open(os.path.join(d, "x"), "w", encoding="utf-8") as f:
            f.write("1")
        snap = self.m.Snapshot(self.run_dir, 1, "rm -rf d", self.cfg)
        snap.capture()
        shutil.rmtree(d)
        snap.restore()
        self.assertEqual(readfile(os.path.join(d, "x")), "1")

    def test_restore_symlink(self):
        target = os.path.join(self.tmp, "real.txt")
        link = os.path.join(self.tmp, "sym.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("hello")
        os.symlink(target, link)
        snap = self.m.Snapshot(self.run_dir, 1, "rm sym.txt", self.cfg)
        snap.capture()
        os.unlink(link)
        snap.restore()
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), target)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-home-")
        self.conf_dir = os.path.join(self.home, ".config", "dojo")
        os.makedirs(self.conf_dir)
        with open(os.path.join(self.conf_dir, "config.toml"), "w", encoding="utf-8") as f:
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

    def test_chat_exit(self):
        import pty
        import select
        import time

        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [sys.executable, DOJO, "chat"],
            stdin=slave, stdout=slave, stderr=slave, env=self.env, cwd=self.work,
            preexec_fn=os.setsid,
        )
        os.close(slave)
        buf = b""
        end = time.time() + 10
        try:
            while time.time() < end:
                r, _, _ = select.select([master], [], [], 0.2)
                if r:
                    buf += os.read(master, 4096)
                if "你>".encode() in buf:
                    break
            os.write(master, b"/exit\n")
            proc.wait(timeout=10)
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(proc.returncode, 0)

    def test_quickstart_without_config(self):
        os.unlink(os.path.join(self.conf_dir, "config.toml"))
        r = self.run_dojo()
        self.assertEqual(r.returncode, 0)
        self.assertIn("三步就能用", r.stdout)

    def test_init_and_uninstall_hook(self):
        rc = os.path.join(self.home, ".bashrc")
        r = self.run_dojo("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(rc, encoding="utf-8") as f:
            self.assertIn(">>> dojo >>>", f.read())
        u = self.run_dojo("uninstall", "--yes")
        self.assertEqual(u.returncode, 0, u.stderr)
        with open(rc, encoding="utf-8") as f:
            self.assertNotIn(">>> dojo >>>", f.read())

    def test_config_set_and_get(self):
        r1 = self.run_dojo("config", "set", "assist.level=4")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self.run_dojo("config", "get", "assist.level")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(r2.stdout.strip(), "4")

    def test_run_and_undo_created_file(self):
        path = os.path.join(self.work, "x.txt")
        r = self.run_dojo("exec", "--yes", "echo hi > x.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(path))
        r = self.run_dojo("undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(path))

    def test_run_and_undo_deleted_file(self):
        path = os.path.join(self.work, "y.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("keep")
        r = self.run_dojo("exec", "--yes", "rm -f y.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(path))
        self.run_dojo("undo")
        self.assertEqual(readfile(path), "keep")

    def test_undo_pipe_written_file(self):
        path = os.path.join(self.work, "pipe.txt")
        r = self.run_dojo("exec", "--yes", "echo hi | tee pipe.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(path))
        self.run_dojo("undo")
        self.assertFalse(os.path.exists(path))

    def test_policy_blocks_protected_path_in_cli(self):
        r = self.run_dojo("exec", "--yes", "echo bad > /etc/dojo_test_forbidden")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("安全拦截", r.stderr)

    def test_brake_default_rollback(self):
        import pty
        import select
        import signal
        import time

        master, slave = pty.openpty()
        env = dict(self.env)
        proc = subprocess.Popen(
            [sys.executable, DOJO, "exec", "sleep 30; echo x > brake.txt"],
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
            out = read_until("已中断".encode(), timeout=15)
            self.assertIn("已中断", out.decode("utf-8", "replace"))
            proc.wait(timeout=10)
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
        self.assertFalse(os.path.exists(os.path.join(self.work, "brake.txt")))

    def test_upgrade_from_url(self):
        bindir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bindir)
        cur = os.path.join(bindir, "dojo")
        shutil.copy2(DOJO, cur)
        os.chmod(cur, 0o755)
        fake = os.path.join(self.work, "fake_update.sh")
        with open(fake, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env bash\nset -e\nmkdir -p \"$HOME/.local/bin\"\n"
                    "sed 's/^VERSION = \".*\"/VERSION = \"9.9.9\"/' "
                    + DOJO + " > \"$HOME/.local/bin/dojo\"\n"
                    "chmod +x \"$HOME/.local/bin/dojo\"\n")
        env = dict(self.env, DOJO_INSTALL_URL="file://" + fake)
        r = subprocess.run([sys.executable, cur, "upgrade", "--yes"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        v = subprocess.run([sys.executable, cur, "version"], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertIn("9.9.9", v.stdout)

    def test_level_gate(self):
        with open(os.path.join(self.conf_dir, "config.toml"), "w", encoding="utf-8") as f:
            f.write("[assist]\nlevel = 3\n")
        r = self.run_dojo("exec", "--yes", "echo hi > z.txt")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.work, "z.txt")))

    def test_stop_without_active_run(self):
        r = self.run_dojo("stop")
        self.assertEqual(r.returncode, 0)
        self.assertIn("现在没有在跑的任务", r.stdout)
        halt = os.path.join(self.env["DOJO_STATE_DIR"], "halt")
        self.assertFalse(os.path.exists(halt))

    def test_history_lists_runs(self):
        self.run_dojo("exec", "--yes", "echo hi > h.txt")
        r = self.run_dojo("history")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 步", r.stdout)

    def test_undo_specific_run(self):
        a = os.path.join(self.work, "a1.txt")
        b = os.path.join(self.work, "b1.txt")
        self.run_dojo("exec", "--yes", "echo 1 > a1.txt")
        self.run_dojo("exec", "--yes", "echo 2 > b1.txt")
        runs = sorted(os.listdir(os.path.join(self.env["DOJO_STATE_DIR"], "runs")))
        r = self.run_dojo("undo", runs[0])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(a))
        self.assertTrue(os.path.exists(b))

    def test_undo_all(self):
        a = os.path.join(self.work, "a.txt")
        b = os.path.join(self.work, "b.txt")
        self.run_dojo("exec", "--yes", "echo 1 > a.txt")
        self.run_dojo("exec", "--yes", "echo 2 > b.txt")
        self.run_dojo("undo", "all")
        self.assertFalse(os.path.exists(b))
        # a.txt 属于更早的一次运行，undo all 只撤最近一次
        self.assertTrue(os.path.exists(a))



class TestExtra(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-extra-")
        self.conf_dir = os.path.join(self.home, ".config", "dojo")
        os.makedirs(self.conf_dir)
        with open(os.path.join(self.conf_dir, "config.toml"), "w") as f:
            f.write("[assist]\nlevel = 5\n[model]\nstream = false\n[stop]\ntimeout_seconds = 2\n")
        self.env = dict(os.environ, HOME=self.home,
                        DOJO_CONFIG=os.path.join(self.conf_dir, "config.toml"),
                        DOJO_STATE_DIR=os.path.join(self.home, ".local", "state", "dojo"))
        self.work = tempfile.mkdtemp(prefix="dojo-extra-work-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def run_dojo(self, *args):
        return subprocess.run([sys.executable, DOJO, *args], env=self.env, cwd=self.work,
                              capture_output=True, text=True, timeout=60)

    def test_commands_log(self):
        self.run_dojo("exec", "--yes", "echo hi > c.txt")
        r = self.run_dojo("commands")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("echo hi > c.txt", r.stdout)
        log = os.path.join(self.env["DOJO_STATE_DIR"], "commands.log")
        self.assertTrue(os.path.exists(log))

    def test_nl_run_needs_model(self):
        path = os.path.join(self.work, "nl.txt")
        r = self.run_dojo("run", "--yes", "echo hi > nl.txt")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(path))

    def test_chat_exit(self):
        import pty
        import select
        import time
        master, slave = pty.openpty()
        proc = subprocess.Popen([sys.executable, DOJO, "chat"], stdin=slave, stdout=slave,
                                stderr=slave, env=self.env, cwd=self.work, preexec_fn=os.setsid)
        os.close(slave)
        buf = b""
        end = time.time() + 10
        try:
            while time.time() < end:
                r, _, _ = select.select([master], [], [], 0.2)
                if r:
                    buf += os.read(master, 4096)
                if "你>".encode() in buf:
                    break
            os.write(master, b"/exit\n")
            proc.wait(timeout=10)
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(proc.returncode, 0)

    def test_upgrade_from_url(self):
        bindir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bindir)
        cur = os.path.join(bindir, "dojo")
        shutil.copy2(DOJO, cur)
        os.chmod(cur, 0o755)
        fake = os.path.join(self.work, "fake_update.sh")
        with open(fake, "w") as f:
            f.write("#!/usr/bin/env bash\nset -e\nmkdir -p \"$HOME/.local/bin\"\n"
                    "sed 's/^VERSION = .*/VERSION = \"9.9.9\"/' " + DOJO +
                    " > \"$HOME/.local/bin/dojo\"\nchmod +x \"$HOME/.local/bin/dojo\"\n")
        env = dict(self.env, DOJO_INSTALL_URL="file://" + fake)
        r = subprocess.run([sys.executable, cur, "upgrade", "--yes"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        v = subprocess.run([sys.executable, cur, "version"], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertIn("9.9.9", v.stdout)

    def test_download_with_progress(self):
        import http.server
        import threading
        srv_dir = os.path.join(self.work, "srv")
        os.makedirs(srv_dir)
        with open(os.path.join(srv_dir, "pkg.sh"), "wb") as f:
            f.write(b"x" * 40000)
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=srv_dir, **kw)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/pkg.sh" % srv.server_address[1]
            out = subprocess.run([sys.executable, "-c",
                "from importlib.machinery import SourceFileLoader\n"
                "import importlib.util\n"
                "l=SourceFileLoader('d','%s'); s=importlib.util.spec_from_loader('d',l)\n"
                "m=importlib.util.module_from_spec(s); l.exec_module(m)\n"
                "print(len(m.download_with_progress('%s')))" % (DOJO, url)],
                env=self.env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.stdout.strip(), "40000", out.stderr)
        finally:
            srv.shutdown()
            srv.server_close()



class TestPreviewAndCapture(unittest.TestCase):
    """沙盒预演（overlayfs）与 PTY 输出捕获"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-home-")
        conf_dir = os.path.join(self.home, ".config", "dojo")
        os.makedirs(conf_dir)
        with open(os.path.join(conf_dir, "config.toml"), "w", encoding="utf-8") as f:
            f.write("[assist]\nlevel = 5\n[model]\nstream = false\n[stop]\ntimeout_seconds = 2\n")
        self.env = dict(os.environ, HOME=self.home,
                        DOJO_CONFIG=os.path.join(conf_dir, "config.toml"),
                        DOJO_STATE_DIR=os.path.join(self.home, ".local", "state", "dojo"))
        self.work = tempfile.mkdtemp(prefix="dojo-work-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def run_dojo(self, *args, timeout=60):
        return subprocess.run([sys.executable, DOJO, *args], env=self.env, cwd=self.work,
                              capture_output=True, text=True, timeout=timeout)

    def userns_ok(self):
        m = load_module()
        return m.sandbox_available()[0]

    def test_capture_preserves_tty_and_logs(self):
        r = self.run_dojo("exec", "--yes",
                          "if [ -t 1 ]; then echo OUT_TTY; else echo OUT_PIPE; fi; echo CAP_MARK")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OUT_TTY", r.stdout)
        self.assertIn("CAP_MARK", r.stdout)
        runs = os.path.join(self.env["DOJO_STATE_DIR"], "runs")
        logs = []
        for d in os.listdir(runs):
            p = os.path.join(runs, d, "output.log")
            if os.path.exists(p):
                logs.append(readfile(p))
        self.assertTrue(any("CAP_MARK" in x for x in logs), logs)

    def test_preview_discard_keeps_files(self):
        if not self.userns_ok():
            self.skipTest("内核不允许无特权用户命名空间")
        r = self.run_dojo("preview", "--yes", "echo hi > a.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.work, "a.txt")))
        self.assertIn("丢弃", r.stdout)

    def test_preview_apply_writes_and_deletes(self):
        if not self.userns_ok():
            self.skipTest("内核不允许无特权用户命名空间")
        keep = os.path.join(self.work, "keep.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("old\n")
        gone = os.path.join(self.work, "gone.txt")
        with open(gone, "w", encoding="utf-8") as f:
            f.write("x\n")
        r = self.run_dojo("preview", "--yes", "--apply",
                          "echo new > a.txt; rm -f gone.txt; mkdir -p d1/d2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(readfile(os.path.join(self.work, "a.txt")), "new\n")
        self.assertFalse(os.path.exists(gone))
        self.assertTrue(os.path.isdir(os.path.join(self.work, "d1", "d2")))
        # 没动过的文件不能被碰
        with open(os.path.join(self.work, "untouched.txt"), "w", encoding="utf-8") as f:
            f.write("stay\n")
        r2 = self.run_dojo("preview", "--yes", "--apply", "echo z > b.txt")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(readfile(os.path.join(self.work, "untouched.txt")), "stay\n")


class TestHookStderrPTY(unittest.TestCase):
    """shell hook 的 stderr 捕获不能把 isatty(2) 弄丢"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-hook-")
        os.makedirs(os.path.join(self.home, ".config", "dojo"))
        with open(os.path.join(self.home, ".config", "dojo", "config.toml"), "w", encoding="utf-8") as f:
            f.write("[context]\ncapture_stderr = true\n")
        share = os.path.join(self.home, ".local", "share", "dojo")
        os.makedirs(share)
        shutil.copy(os.path.join(ROOT, "lib", "hook.bash"), os.path.join(share, "hook.bash"))
        with open(os.path.join(self.home, ".bashrc"), "w", encoding="utf-8") as f:
            f.write("source ~/.local/share/dojo/hook.bash\n")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_isatty2_and_capture(self):
        import pty
        import select
        import time

        master, slave = pty.openpty()
        env = dict(os.environ, HOME=self.home, PS1="P> ", TERM="xterm-256color")
        proc = subprocess.Popen(["/bin/bash", "--noprofile", "-i"], stdin=slave, stdout=slave,
                                stderr=slave, env=env, preexec_fn=os.setsid)
        os.close(slave)
        buf = b""
        try:
            time.sleep(1.0)
            # 拆成两段拼接，回显里不会出现完整字样，免得把回显当成输出
            os.write(master, b'echo HOOK_MARK >&2; [ -t 2 ] && echo "TTY_""IS_OK" || echo "TTY_""NOT_OK"\n')
            end = time.time() + 8
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                if b"TTY_NOT_OK" in buf or b"TTY_IS_OK" in buf:
                    break
            os.write(master, b"exit\n")
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        out = buf.decode("utf-8", "replace")
        # 回显把整条命令也打到屏幕上了，还夹着 readline 的转义序列，先洗一遍再按行比对
        clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out)
        lines = [ln.strip() for ln in clean.splitlines()]
        self.assertTrue(any(ln.endswith("TTY_IS_OK") for ln in lines), lines)
        self.assertFalse(any(ln.endswith("TTY_NOT_OK") for ln in lines), lines)
        # 只进日志不算数：stderr 必须同时回到终端屏幕上
        self.assertIn("HOOK_MARK", out)
        log = os.path.join(self.home, ".local", "state", "dojo", "stderr.log")
        end = time.time() + 3
        while time.time() < end and not (os.path.exists(log) and "HOOK_MARK" in readfile(log)):
            time.sleep(0.1)
        self.assertIn("HOOK_MARK", readfile(log))



class TestDoLoop(unittest.TestCase):
    """dojo run 不能跑一步就收摊，也不能只给侦察命令当方案"""

    def _run(self, replies):
        import copy
        import types
        from unittest import mock

        m = load_module()
        cfg = copy.deepcopy(m.DEFAULTS)
        seen = []

        def fake_model(cfg_, msgs, **kw):
            seen.append(msgs)
            return replies[min(len(seen) - 1, len(replies) - 1)]

        class FakeRunner:
            def __init__(self, *a, **kw):
                self.last_run = types.SimpleNamespace(
                    data={"steps": [{"cmd": "cat /etc/os-release", "rc": 0}]}
                )

            def execute(self, cmds):
                return 0

        fake_stdin = types.SimpleNamespace(isatty=lambda: True)
        with mock.patch.object(m, "call_model", fake_model), \
             mock.patch.object(m, "Runner", FakeRunner), \
             mock.patch.object(m.sys, "stdin", fake_stdin), \
             mock.patch("builtins.input", return_value=""):
            m.cmd_do(cfg, ["装个中文输入法"], 5)
        return m, seen

    def test_continues_until_done(self):
        plan = "```bash\nsudo apt install -y fcitx5\nfcitx5 --version\n```"
        m, seen = self._run(["```bash\ncat /etc/os-release\n```", plan, "DONE"])
        # 侦察被打回 → 完整方案 → DONE
        self.assertGreaterEqual(len(seen), 3)
        self.assertIn("这只能算摸底", str(seen[1]))
        # 进入第二轮时带上了已执行记录
        self.assertIn("已经执行过这些", str(seen[2]))

    def test_recon_only_detection(self):
        m = load_module()
        self.assertTrue(m.plan_is_recon_only(["cat /etc/os-release", "uname -a"]))
        self.assertFalse(m.plan_is_recon_only(["cat /etc/os-release", "sudo apt install -y fcitx5"]))
        self.assertFalse(m.plan_is_recon_only([]))



class TestSudoEscalation(unittest.TestCase):
    """缺 root 权限时应该问一句，而不是直接失败"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-sudo-")
        self.state = os.path.join(self.home, "state")
        os.makedirs(self.state)
        self.env_backup = {k: os.environ.get(k) for k in ("DOJO_STATE_DIR", "DOJO_CONFIG")}
        os.environ["DOJO_STATE_DIR"] = self.state
        os.environ["DOJO_CONFIG"] = os.path.join(self.home, "config.toml")
        self.m = load_module()
        self.m._refresh_paths()

    def tearDown(self):
        for k, v in self.env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)

    def test_needs_root(self):
        m = self.m
        self.assertTrue(m._needs_root("apt install -y fcitx5"))
        self.assertTrue(m._needs_root("sudo systemctl restart nginx"))
        self.assertFalse(m._needs_root("ls -l"))
        self.assertTrue(m._sudo_wrap("a && b").startswith("sudo -- bash"))

    def test_offers_sudo_after_permission_error(self):
        import copy
        import types
        from unittest import mock

        m = self.m
        cfg = copy.deepcopy(m.DEFAULTS)
        calls = []

        def fake_run_one(self, cmd, run_id=None):
            calls.append(cmd)
            if len(calls) == 1:
                # 把「缺权限」写进这次运行的输出，让检测逻辑能读到
                path = os.path.join(m.RUNS_DIR, run_id, "output.log")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write("mkdir: cannot create directory '/root/x': Permission denied\n")
                return 1, False
            return 0, False

        fake_stdin = types.SimpleNamespace(isatty=lambda: True)
        answers = iter(["y", "y"])  # 先确认要跑，再同意提权
        with mock.patch.object(m.Runner, "_run_one", fake_run_one), \
             mock.patch.object(m.sys, "stdin", fake_stdin), \
             mock.patch("builtins.input", side_effect=lambda *a, **k: next(answers)), \
             mock.patch.object(m.os, "geteuid", return_value=1000):
            runner = m.Runner(cfg, yes=False)
            runner._execute(["mkdir /root/x"], None)
            run = runner.last_run
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0] == "mkdir /root/x")
        self.assertTrue(calls[1].startswith("sudo -- bash"))
        step = run.data["steps"][-1]
        self.assertTrue(step.get("escalated"))
        self.assertEqual(step["kind"], "irreversible")



class TestAutoExplain(unittest.TestCase):
    """空敲 dojo，上一条挂了就直接给原因"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-auto-")
        conf = os.path.join(self.home, ".config", "dojo")
        os.makedirs(conf)
        self.conf = os.path.join(conf, "config.toml")
        with open(self.conf, "w", encoding="utf-8") as f:
            f.write('[model]\napi_key = "test"\nstream = false\n[assist]\nlevel = 3\n')
        self.state = os.path.join(self.home, ".local", "state", "dojo")
        os.makedirs(self.state)
        self.env_backup = {k: os.environ.get(k) for k in ("DOJO_CONFIG", "DOJO_STATE_DIR")}
        os.environ["DOJO_CONFIG"] = self.conf
        os.environ["DOJO_STATE_DIR"] = self.state
        self.m = load_module()
        self.m._refresh_paths()

    def tearDown(self):
        for k, v in self.env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)

    def write_ctx(self, rows):
        path = os.path.join(self.state, "ctx.tsv")
        with open(path, "w", encoding="utf-8") as f:
            for ts, code, cwd, cmd in rows:
                f.write(f"{ts}\x1f{code}\x1f{cwd}\x1f{cmd}\x1f\n")

    def test_last_failure_detection(self):
        import time
        now = int(time.time())
        self.write_ctx([(now, "1", "/tmp", "ls /nope")])
        self.assertIsNotNone(self.m.last_failure())
        self.write_ctx([(now, "0", "/tmp", "ls /tmp")])
        self.assertIsNone(self.m.last_failure())
        # 太旧的失败不再主动提
        self.write_ctx([(now - 7200, "1", "/tmp", "ls /nope")])
        self.assertIsNone(self.m.last_failure())

    def test_bare_dojo_answers_error(self):
        import io
        import time
        from contextlib import redirect_stdout
        from unittest import mock

        now = int(time.time())
        self.write_ctx([(now, "127", "/tmp", "notacommand --foo")])
        m = self.m
        buf = io.StringIO()
        with mock.patch.object(m, "call_model", return_value="这命令压根不存在") as cm, \
             mock.patch.object(m.sys, "argv", ["dojo"]), \
             redirect_stdout(buf):
            m.main()
        out = buf.getvalue()
        self.assertIn("上一条命令挂了", out)
        self.assertIn("127", out)
        self.assertIn("这命令压根不存在", out)
        self.assertEqual(cm.call_count, 1)


    def test_error_card_format(self):
        import io
        import time
        from contextlib import redirect_stdout
        from unittest import mock

        now = int(time.time())
        self.write_ctx([(now, "127", "/tmp", "notacommand --foo")])
        m = self.m
        payload = ('{"cause": "命令名拼错了，系统里没有 notacommand", '
                   '"guess": "你想看一条命令在不在", '
                   '"solutions": ["`command -v notacommand`", "2. history | grep nota"]}')
        buf = io.StringIO()
        with mock.patch.object(m, "call_model", return_value=payload), \
             mock.patch.object(m.sys, "argv", ["dojo"]), \
             redirect_stdout(buf):
            m.main()
        out = buf.getvalue()
        self.assertIn("原因  命令名拼错了", out)
        self.assertIn("猜测  你想看一条命令在不在", out)
        self.assertIn("1. command -v notacommand", out)
        self.assertIn("2. history | grep nota", out)
        self.assertNotIn("`", out)
        self.assertNotIn("老王：", out)
        self.assertIn('dojo why', out)

    def test_error_card_falls_back_to_text(self):
        import io
        import time
        from contextlib import redirect_stdout
        from unittest import mock

        now = int(time.time())
        self.write_ctx([(now, "1", "/tmp", "cat nope")])
        m = self.m
        buf = io.StringIO()
        with mock.patch.object(m, "call_model", return_value="就是文件不存在"), \
             mock.patch.object(m.sys, "argv", ["dojo"]), \
             redirect_stdout(buf):
            m.main()
        self.assertIn("就是文件不存在", buf.getvalue())

    def test_why_carries_intent(self):
        import io
        import time
        from contextlib import redirect_stdout
        from unittest import mock

        now = int(time.time())
        self.write_ctx([(now, "127", "/tmp", "notacommand")])
        m = self.m
        seen = []

        def fake(cfg_, msgs, **kw):
            seen.append(msgs)
            return '{"cause": "x", "guess": "y", "solutions": ["z"]}'

        buf = io.StringIO()
        with mock.patch.object(m, "call_model", fake), redirect_stdout(buf):
            m.cmd_why(m.load_config(), ["我其实想改", "输入法配置"], 3)
        self.assertIn("我其实想改 输入法配置", str(seen[0]))
        self.assertIn("原因", buf.getvalue())

    def test_errors_list(self):
        import io
        import time
        from contextlib import redirect_stdout

        now = int(time.time())
        self.write_ctx([(now, "0", "/tmp", "ls"), (now, "2", "/tmp", "grep x y"), (now, "1", "/tmp", "cat nope")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.m.cmd_errors(self.m.load_config(), ["5"])
        out = buf.getvalue()
        self.assertIn("grep x y", out)
        self.assertIn("cat nope", out)
        self.assertNotIn("ls\n", out)



class TestAcpAndFim(unittest.TestCase):
    """ACP agent 模式与 FIM 补全"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dojo-acp-")
        conf = os.path.join(self.home, ".config", "dojo")
        os.makedirs(conf)
        with open(os.path.join(conf, "config.toml"), "w", encoding="utf-8") as f:
            f.write('[model]\napi_key = "test"\nstream = false\n[assist]\nlevel = 3\n')
        self.env = dict(os.environ, HOME=self.home,
                        DOJO_CONFIG=os.path.join(conf, "config.toml"),
                        DOJO_STATE_DIR=os.path.join(self.home, "state"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_acp_initialize_and_session(self):
        import json
        p = subprocess.Popen([sys.executable, DOJO, "acp"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=self.env, text=True, bufsize=1)
        try:
            def send(obj):
                p.stdin.write(json.dumps(obj) + "\n")
                p.stdin.flush()

            send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": 1, "clientCapabilities": {}}})
            init = json.loads(p.stdout.readline())
            self.assertEqual(init["result"]["protocolVersion"], 1)
            self.assertEqual(init["result"]["agentInfo"]["name"], "dojo")

            send({"jsonrpc": "2.0", "id": 2, "method": "session/new",
                  "params": {"cwd": "/tmp", "mcpServers": []}})
            new = json.loads(p.stdout.readline())
            self.assertTrue(new["result"]["sessionId"].startswith("sess_"))

            send({"jsonrpc": "2.0", "id": 3, "method": "no/such", "params": {}})
            err = json.loads(p.stdout.readline())
            self.assertEqual(err["error"]["code"], -32601)
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait(timeout=10)
            for stream in (p.stdout, p.stderr):
                try:
                    stream.close()
                except (OSError, AttributeError):
                    pass

    def test_acp_prompt_streams(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        m = load_module()
        cfg = m.load_config()
        sent = []
        sess = {"cwd": "/tmp", "history": [], "cancel": __import__("threading").Event()}

        def fake_stream(cfg_, messages, max_tokens=0):
            yield "你"
            yield "好"

        buf = io.StringIO()
        with mock.patch.object(m, "iter_model_stream", fake_stream), \
             mock.patch.object(m, "_acp_update", lambda sid, t: sent.append(t)), \
             redirect_stdout(buf):
            reason = m._acp_run_prompt(cfg, 3, "sess_x", sess, "打个招呼")
        self.assertEqual(reason, "end_turn")
        self.assertEqual("".join(sent), "你好")
        self.assertEqual(sess["history"][-1]["content"], "你好")
        self.assertEqual(sess["history"][0]["content"], "打个招呼")

    def test_fim_url(self):
        m = load_module()
        cfg = m.load_config()
        self.assertEqual(m._fim_url(cfg), "https://api.deepseek.com/beta/completions")

    def test_complete_without_prefix_fails_cleanly(self):
        r = subprocess.run([sys.executable, DOJO, "complete"], env=self.env,
                           input="", capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("用法", r.stderr)


class TestV061Regressions(unittest.TestCase):
    """v0.6.1 修的六个真问题，每条都留一份回归"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dojo-v061-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sudo_wrap_stays_irreversible(self):
        m = load_module()
        wrapped = m._sudo_wrap("apt install -y nginx")
        self.assertEqual(m.classify(wrapped), "irreversible")
        self.assertTrue(any("apt remove nginx" in h for h in m.suggest_inverse(wrapped)))

    def test_shell_c_payload_unwrapped(self):
        m = load_module()
        self.assertEqual(m._shell_c_payload(["bash", "-c", "ls -l"]), "ls -l")
        self.assertIsNone(m._shell_c_payload(["bash"]))
        name, args = m._cmd_args(["sudo", "--", "bash", "--noprofile", "-c", "apt install -y nginx"])
        self.assertEqual(name, "apt")
        self.assertEqual(args, ["install", "-y", "nginx"])

    def test_hook_no_double_cr(self):
        """程序自己写 \r\n 时，屏幕上不能再被转成 \r\r\n"""
        import pty, select, time
        home = os.path.join(self.tmp, "crlf")
        conf = os.path.join(home, ".config", "dojo")
        os.makedirs(conf)
        with open(os.path.join(conf, "config.toml"), "w", encoding="utf-8") as f:
            f.write("[context]\ncapture_stderr = true\n")
        pid, master = pty.fork()
        if pid == 0:
            os.environ["HOME"] = home
            os.environ["PS1"] = "P> "
            os.execvp("bash", ["bash", "--noprofile", "--norc", "-i"])
        buf = b""

        def drain(seconds):
            nonlocal buf
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf += chunk
        try:
            drain(0.6)
            os.write(master, b"source " + os.path.join(ROOT, "lib", "hook.bash").encode() + b"\n")
            drain(1.2)
            os.write(master, b"printf 'AAAA\\r\\n' >&2\n")
            drain(1.5)
            os.write(master, b"exit\n")
        finally:
            try:
                os.close(master)
            except OSError:
                pass
        self.assertIn(b"AAAA\r\n", buf)
        self.assertNotIn(b"AAAA\r\r\n", buf)

    def test_commands_log_follows_state_dir_and_redacts(self):
        state = os.path.join(self.tmp, "state")
        os.environ["DOJO_STATE_DIR"] = state
        try:
            m = load_module()
            m._refresh_paths()
            self.assertEqual(m.COMMANDS_LOG, os.path.join(state, "commands.log"))
            m.log_command("r1", 1, 1, 'curl -H "Authorization: Bearer sk-abcdef123" https://x', 0)
            text = readfile(m.COMMANDS_LOG)
            self.assertIn("run=r1", text)
            self.assertNotIn("sk-abcdef123", text)
        finally:
            os.environ.pop("DOJO_STATE_DIR", None)

    def test_apply_upper_file_to_dir(self):
        root = os.path.join(self.tmp, "root")
        upper = os.path.join(self.tmp, "upper")
        os.makedirs(root)
        os.makedirs(os.path.join(upper, "sub"))
        with open(os.path.join(root, "sub"), "w", encoding="utf-8") as f:
            f.write("old file")
        with open(os.path.join(upper, "sub", "a.txt"), "w", encoding="utf-8") as f:
            f.write("inner")
        m = load_module()
        m._apply_upper(upper, root)
        self.assertTrue(os.path.isdir(os.path.join(root, "sub")))
        self.assertEqual(readfile(os.path.join(root, "sub", "a.txt")), "inner")

    def test_preview_exit_code_propagates(self):
        home = os.path.join(self.tmp, "home")
        conf = os.path.join(home, ".config", "dojo")
        os.makedirs(conf)
        with open(os.path.join(conf, "config.toml"), "w", encoding="utf-8") as f:
            f.write('[model]\napi_key = "test"\nstream = false\n[assist]\nlevel = 3\n')
        env = dict(os.environ, HOME=home, DOJO_CONFIG=os.path.join(conf, "config.toml"),
                   DOJO_STATE_DIR=os.path.join(home, "state"))
        r = subprocess.run([sys.executable, DOJO, "preview", "ls"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)

    def test_acp_parse_error_and_cancel_reply(self):
        import json
        home = os.path.join(self.tmp, "acphome")
        conf = os.path.join(home, ".config", "dojo")
        os.makedirs(conf)
        with open(os.path.join(conf, "config.toml"), "w", encoding="utf-8") as f:
            f.write('[model]\napi_key = "test"\nstream = false\n[assist]\nlevel = 3\n')
        env = dict(os.environ, HOME=home, DOJO_CONFIG=os.path.join(conf, "config.toml"),
                   DOJO_STATE_DIR=os.path.join(home, "state"))
        p = subprocess.Popen([sys.executable, DOJO, "acp"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, text=True, bufsize=1)
        try:
            p.stdin.write("这不是 JSON\n")
            p.stdin.flush()
            bad = json.loads(p.stdout.readline())
            self.assertEqual(bad["error"]["code"], -32700)
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 7,
                                      "method": "session/cancel",
                                      "params": {"sessionId": "nope"}}) + "\n")
            p.stdin.flush()
            cancel = json.loads(p.stdout.readline())
            self.assertEqual(cancel["id"], 7)
            self.assertEqual(cancel["result"], {})
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait(timeout=10)
            for stream in (p.stdout, p.stderr):
                try:
                    stream.close()
                except (OSError, AttributeError):
                    pass

    def test_fim_url_non_deepseek(self):
        m = load_module()
        cfg = {"model": {"base_url": "https://openrouter.ai/api/v1"}}
        self.assertEqual(m._fim_url(cfg), "https://openrouter.ai/api/v1/completions")


class TestV070Interactive(unittest.TestCase):
    """v0.7：报错卡片选号执行、dojo diff、Ctrl-G 补全绑定"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dojo-v070-")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state)
        self.conf = os.path.join(self.tmp, "config.toml")
        with open(self.conf, "w", encoding="utf-8") as f:
            f.write('[model]\napi_key = "test"\nstream = false\n[assist]\nlevel = 3\n')
        self.env = dict(os.environ, HOME=self.tmp, DOJO_CONFIG=self.conf,
                        DOJO_STATE_DIR=self.state)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _card(self, sols):
        import json
        with open(os.path.join(self.state, "last_card.json"), "w", encoding="utf-8") as f:
            json.dump({"cmd": "systemctl restart nginx", "cwd": self.tmp,
                       "solutions": sols, "ts": 1}, f, ensure_ascii=False)

    def test_pick_without_card(self):
        r = subprocess.run([sys.executable, DOJO, "1"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("还没有报错卡片", r.stderr)

    def test_pick_out_of_range(self):
        self._card(["a", "b"])
        r = subprocess.run([sys.executable, DOJO, "3"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("只有 2 条方案", r.stderr)

    def test_pick_selects_solution(self):
        self._card(["systemctl status nginx", "journalctl -u nginx -n 50"])
        r = subprocess.run([sys.executable, DOJO, "2"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertIn("方案 2：journalctl -u nginx -n 50", r.stdout)
        # L3 不代跑，只验证选中的是哪条
        self.assertEqual(r.returncode, 1)

    def test_diff_shows_changes(self):
        run_id = "20261112-200000-000000-0000001-001"
        run_dir = os.path.join(self.state, "runs", run_id)
        os.makedirs(os.path.join(run_dir, "steps", "001"))
        target = os.path.join(self.tmp, "file.txt")
        with open(os.path.join(run_dir, "steps", "001", "0"), "w", encoding="utf-8") as f:
            f.write("line1\nline2\n")
        with open(target, "w", encoding="utf-8") as f:
            f.write("line1 CHANGED\nline2\nline3\n")
        manifest = {"id": run_id, "created": 1, "cwd": self.tmp, "question": "t",
                    "steps": [{"n": 1, "cmd": "sed -i s/line2/CHANGED/ file.txt",
                               "cwd": self.tmp, "kind": "reversible", "rc": 0,
                               "records": [{"path": target, "existed": True,
                                            "kind": "file", "backup": "0"}],
                               "undone": False}]}
        import json
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        r = subprocess.run([sys.executable, DOJO, "diff", run_id], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("+line1 CHANGED", r.stdout)
        self.assertIn("+line3", r.stdout)

    def test_diff_no_changes(self):
        run_id = "20261112-200000-000000-0000001-002"
        run_dir = os.path.join(self.state, "runs", run_id)
        os.makedirs(os.path.join(run_dir, "steps", "001"))
        target = os.path.join(self.tmp, "same.txt")
        with open(os.path.join(run_dir, "steps", "001", "0"), "w", encoding="utf-8") as f:
            f.write("same\n")
        with open(target, "w", encoding="utf-8") as f:
            f.write("same\n")
        import json
        manifest = {"id": run_id, "created": 1, "cwd": self.tmp, "question": "t",
                    "steps": [{"n": 1, "cmd": "true", "cwd": self.tmp, "kind": "reversible",
                               "rc": 0, "records": [{"path": target, "existed": True,
                                                     "kind": "file", "backup": "0"}],
                               "undone": False}]}
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        r = subprocess.run([sys.executable, DOJO, "diff", run_id], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertIn("没有差异", r.stdout)

    def _pty_lines(self, argv, setup_lines):
        import pty, select, time
        pid, master = pty.fork()
        if pid == 0:
            os.environ["HOME"] = self.tmp
            os.environ["PS1"] = "P> "
            os.execvp(argv[0], argv)
        buf = b""

        def drain(seconds):
            nonlocal buf
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf += chunk
        try:
            drain(0.8)
            for line in setup_lines:
                os.write(master, line.encode() + b"\n")
                drain(1.2)
            os.write(master, b"exit\n")
            drain(0.5)
        finally:
            try:
                os.close(master)
            except OSError:
                pass
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", buf.decode("utf-8", "replace"))

    def test_ctrl_g_bound_in_bash(self):
        hook = os.path.join(ROOT, "lib", "hook.bash")
        out = self._pty_lines(["bash", "--noprofile", "--norc", "-i"],
                              ["source " + hook, "bind -X | grep -c dojo_complete"])
        lines = [ln.strip() for ln in out.splitlines()]
        self.assertIn("1", lines)

    def test_ctrl_g_bound_in_zsh(self):
        if not shutil.which("zsh"):
            self.skipTest("没有 zsh")
        hook = os.path.join(ROOT, "lib", "hook.zsh")
        out = self._pty_lines(["zsh", "-f", "-i"],
                              ["source " + hook, "bindkey '^G'"])
        self.assertIn("__dojo_complete_widget", out)


class TestV080Freeform(unittest.TestCase):
    """v0.8：说话免指令，控制留短词"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dojo-v080-")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state)
        self.conf = os.path.join(self.tmp, "config.toml")
        with open(self.conf, "w", encoding="utf-8") as f:
            f.write('[model]\napi_key = "test"\nstream = false\n[assist]\nlevel = 3\n')
        self.env = dict(os.environ, HOME=self.tmp, DOJO_CONFIG=self.conf,
                        DOJO_STATE_DIR=self.state)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_route_freeform(self):
        from unittest import mock
        m = load_module()
        cfg = m.load_config()
        with mock.patch.object(m, "last_failure", return_value={"cmd": "x", "code": 1, "cwd": "/tmp"}):
            self.assertEqual(m.route_freeform(cfg, 3), "why")
            # L5 直接进规划，上下文里本来就带着报错
            self.assertEqual(m.route_freeform(cfg, 5), "do")
        with mock.patch.object(m, "last_failure", return_value=None):
            self.assertEqual(m.route_freeform(cfg, 3), "ask")
            self.assertEqual(m.route_freeform(cfg, 5), "do")

    def test_looks_like_typo(self):
        m = load_module()
        self.assertEqual(m.looks_like_typo("stauts"), "status")
        self.assertEqual(m.looks_like_typo("histry"), "history")
        self.assertIsNone(m.looks_like_typo("status"))
        self.assertIsNone(m.looks_like_typo("你好"))
        self.assertIsNone(m.looks_like_typo("80端口被谁占了"))

    def test_typo_gives_hint_not_model_call(self):
        r = subprocess.run([sys.executable, DOJO, "stauts"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("dojo status", r.stderr)

    def test_log_subcommands(self):
        r = subprocess.run([sys.executable, DOJO, "log", "err"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("最近没有失败的命令", r.stdout)
        r = subprocess.run([sys.executable, DOJO, "log", "run"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("还没有运行记录", r.stdout)


class TestInstallerMirrors(unittest.TestCase):
    """拉安装器的多源退让"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dojo-mirror-")
        self.dir = os.path.join(self.tmp, "srv")
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "install.sh"), "wb") as f:
            f.write(b"#!/usr/bin/env bash\n# dojo installer\necho dojo\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_falls_back_to_second_mirror(self):
        import http.server
        import threading
        from unittest import mock

        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
            *a, directory=self.dir, **kw)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        good = "http://127.0.0.1:%d/install.sh" % srv.server_address[1]
        try:
            m = load_module()
            with mock.patch.object(m, "INSTALL_MIRRORS",
                                   (("坏源", "http://127.0.0.1:1/install.sh"), ("好源", good))):
                data, src = m.fetch_installer(timeout=5)
            self.assertIsNotNone(data)
            self.assertEqual(src, "好源")
            self.assertIn(b"dojo", data)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_all_broken_reports_reason(self):
        from unittest import mock
        m = load_module()
        with mock.patch.object(m, "INSTALL_MIRRORS",
                               (("坏源A", "http://127.0.0.1:1/a"), ("坏源B", "http://127.0.0.1:2/b"))):
            data, err = m.fetch_installer(timeout=3)
        self.assertIsNone(data)
        self.assertIn("坏源A", err)
        self.assertIn("坏源B", err)

    def test_explicit_url_wins(self):
        import http.server
        import threading
        from unittest import mock

        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
            *a, directory=self.dir, **kw)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        good = "http://127.0.0.1:%d/install.sh" % srv.server_address[1]
        try:
            m = load_module()
            with mock.patch.object(m, "INSTALL_MIRRORS",
                                   (("镜像", "http://127.0.0.1:1/install.sh"),)):
                data, src = m.fetch_installer(explicit=good, timeout=5)
            self.assertEqual(src, "DOJO_INSTALL_URL")
            self.assertIn(b"dojo", data)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
