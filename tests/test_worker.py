# -*- coding: utf-8 -*-
"""일꾼 부품 (diodelib.worker) · 허브의 첨부 검사 · 설정에서 일꾼 만들기. 가짜 일꾼은 이 파이썬 자신 (합성 자료만)."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import hub, worker  # noqa: E402
from tests.test_propose import make_room  # noqa: E402

# 가짜 일꾼: 받은 글을 DIODE_JOB 이름의 파일로 남기고 (시험이 읽는다) 끝난다
ECHO = ("import os, sys; t = (sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read());"
        " open(os.environ['DIODE_JOB'] + '.got', 'w', encoding='utf-8').write(t)")


def wait_for(path, secs=20):
    end = time.time() + secs
    while time.time() < end:
        if os.path.exists(path):
            time.sleep(0.05)
            return True
        time.sleep(0.05)
    return False


class Config(unittest.TestCase):
    def test_load(self):
        cmd, cwd = worker.load_command({"worker": {"command": ["opencode", "run", "{prompt}"]}})
        self.assertEqual((cmd, cwd), (["opencode", "run", "{prompt}"], None))
        for bad in ({}, {"worker": 3}, {"worker": {}}, {"worker": {"command": []}}, {"worker": {"command": "opencode"}},
                    {"worker": {"command": ["a", 3]}}, {"worker": {"command": [""]}},
                    {"worker": {"command": ["a", "{prompt}", "{prompt}"]}},
                    {"worker": {"command": ["a"], "cwd": ""}}, {"worker": {"command": ["a\x00"]}}):
            with self.assertRaises(worker.WorkerConfigError):
                worker.load_command(bad)


class Send(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-worker-"))
        self.home = os.path.join(self.tmp, "data")
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)
        with open(os.path.join(self.room, "work", "a.html"), "w", encoding="utf-8") as f:
            f.write("<html></html>")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def got(self, job):
        p = os.path.join(self.home, "work", job, job + ".got")
        self.assertTrue(wait_for(p), "일꾼이 글을 받지 못했다")
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_prompt_in_argv(self):
        w = worker.CommandWorker([sys.executable, "-c", ECHO, "{prompt}"], self.home, self.room)
        self.assertTrue(w.check())
        self.assertTrue(w.send("J-0001", "[diode J-0001]\n한글 지시 \"따옴표\" & $HOME `x`", ["a.html"]))
        self.assertEqual(self.got("J-0001"), "[diode J-0001]\n한글 지시 \"따옴표\" & $HOME `x`")   # 셸이 없으니 그대로
        self.assertTrue(os.path.isfile(os.path.join(self.home, "work", "J-0001", "a.html")))     # 첨부 복사

    def test_prompt_on_stdin(self):
        w = worker.CommandWorker([sys.executable, "-c", ECHO], self.home, self.room)
        self.assertTrue(w.send("J-0002", "표준 입력으로 간다", []))
        self.assertEqual(self.got("J-0002"), "표준 입력으로 간다")

    def test_output_is_not_read(self):
        w = worker.CommandWorker([sys.executable, "-c", "print('안쪽 원문 출력'); import sys; sys.stderr.write('오류 원문')",
                                  "{prompt}"], self.home, self.room)
        self.assertTrue(w.send("J-0003", "x", []))
        self.assertEqual(w.children[-1].stdout, None)               # 파이프가 없다 — 읽을 수 없다
        self.assertEqual(w.children[-1].stderr, None)

    def test_attachment_names_and_no_overwrite(self):
        w = worker.CommandWorker([sys.executable, "-c", "pass", "{prompt}"], self.home, self.room)
        self.assertFalse(w.send("J-0004", "x", ["../a.html"]))
        self.assertFalse(w.send("J-0004", "x", ["없음.html"]))
        self.assertTrue(w.send("J-0004", "x", ["a.html"]))
        self.assertTrue(w.send("J-0004", "x", ["a.html"]))
        self.assertEqual(sorted(x for x in os.listdir(os.path.join(self.home, "work", "J-0004"))),
                         ["a-2.html", "a.html"])

    def test_missing_executable(self):
        w = worker.CommandWorker(["diode-no-such-command-xyz", "{prompt}"], self.home, self.room)
        self.assertFalse(w.check())
        self.assertFalse(w.send("J-0005", "x", []))

    def test_cwd_override(self):
        fixed = os.path.join(self.tmp, "inner")
        w = worker.CommandWorker([sys.executable, "-c", ECHO, "{prompt}"], self.home, self.room, cwd=fixed)
        self.assertTrue(w.send("J-0006", "x", []))
        self.assertTrue(wait_for(os.path.join(fixed, "J-0006.got")))


class HubParts(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-worker-"))
        self.home = os.path.join(self.tmp, "data")
        os.makedirs(self.home)
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self, obj):
        with open(os.path.join(self.home, "config.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def test_worker_from_config(self):
        self.assertIsNone(hub._worker_from_config(self.home, self.room, worker))           # 설정 없음
        self.cfg({"format": 1, "worker": {"command": [sys.executable, "-c", "pass", "{prompt}"]}})
        self.assertIsInstance(hub._worker_from_config(self.home, self.room, worker), worker.CommandWorker)
        self.cfg({"format": 2, "worker": {"command": ["x"]}})
        self.assertIsNone(hub._worker_from_config(self.home, self.room, worker))
        self.cfg({"format": 1, "worker": {"command": "x"}})
        self.assertIsNone(hub._worker_from_config(self.home, self.room, worker))

    def test_attachment_content_checked_before_confirm(self):
        seen = []
        parts = hub.Parts(confirm=lambda r: seen.append(r), worker=worker.CommandWorker(
            [sys.executable, "-c", "pass", "{prompt}"], self.home, self.room), audit=lambda r: None)
        h = hub.Hub(self.room, parts)
        bad = {"a.html": '<script src="https://cdn.example.com/x.js"></script>', "b.html": "<p>fetch('/x')</p>".replace("<p>", "<script>").replace("</p>", "</script>"),
               "c.bin": None}
        for name, body in bad.items():
            with open(os.path.join(self.room, "work", name), "wb") as f:
                f.write(body.encode("utf-8") if body else b"\xff\xfe\x00")
            res = h.call("dispatch", {"instruction": "x", "attachments": [name]})
            self.assertEqual(res, {"sent": False, "error": "E-04"}, name)
        self.assertEqual(seen, [])                                  # 사람을 부르기 전에 막는다


if __name__ == "__main__":
    unittest.main()
