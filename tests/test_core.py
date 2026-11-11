#!/usr/bin/env python3
"""dojo 核心回归测试：解析、策略引擎、脱敏、快照、回滚、CLI 端到端"""
import importlib.util
from importlib.machinery import SourceFileLoader
import os
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
            os.write(master, b"echo HOOK_MARK >&2; [ -t 2 ] && echo IS_TTY2 || echo NOT_TTY2\n")
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
                if b"NOT_TTY2" in buf or b"IS_TTY2" in buf:
                    break
            os.write(master, b"exit\n")
        finally:
            try:
                proc.terminate()
            except OSError:
                pass
        out = buf.decode("utf-8", "replace")
        self.assertIn("IS_TTY2", out)
        self.assertNotIn("NOT_TTY2", out)
        log = os.path.join(self.home, ".local", "state", "dojo", "stderr.log")
        end = time.time() + 3
        while time.time() < end and not (os.path.exists(log) and "HOOK_MARK" in readfile(log)):
            time.sleep(0.1)
        self.assertIn("HOOK_MARK", readfile(log))


if __name__ == "__main__":
    unittest.main(verbosity=2)
