# -*- coding: utf-8 -*-
"""건네기 (diodelib.transport · PLAN 07) — 계약 · room · clipboard. 임시 방 · 가짜 TUI (하위 프로세스)."""

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import audit, transport  # noqa: E402

SEALED = "[diode report format=1 job=J-0007 status=done]\nSUMMARY:\n- PH_K7Q2 화면을 만들었다\n[/diode report]\n"
ROUTE = {"model": "fake-route-model-q", "effort": "max"}
ROOM_SETTINGS = {"autoMemoryEnabled": False, "permissions": {"defaultMode": "default", "deny": ["Bash", "WebFetch"]}}

# 가짜 TUI — 방의 outbox 를 읽고 inbox 에 답을 쓴다 (사람이 TUI 에 한 줄을 넣은 것을 흉내)
FAKE_TUI = r"""
import os, sys
room, job = sys.argv[1], sys.argv[2]
with open(os.path.join(room, "outbox", job + ".md"), "rb") as f:
    got = f.read()
with open(os.path.join(room, "inbox", job + ".md"), "wb") as f:
    f.write(("받음 " + str(len(got)) + "\n").encode("utf-8"))
"""


def make_room(folder):
    settings = os.path.join(folder, ".claude", "settings.json")
    os.makedirs(os.path.dirname(settings))
    with open(settings, "w", encoding="utf-8") as f:
        json.dump(ROOM_SETTINGS, f)
    with open(settings, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(folder, ".diode-room"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "created": "2026-11-05T00:00:00Z", "settings_sha256": sha}, f)
    for sub in ("outbox", "inbox", "work"):
        os.makedirs(os.path.join(folder, sub))


class ContractTest(unittest.TestCase):
    def test_contract_shape(self):
        for cls in (transport.RoomTransport, transport.ClipboardTransport):
            self.assertIsInstance(cls.name, str)
            self.assertEqual(list(inspect.signature(cls.put).parameters), ["self", "job", "sealed_text", "route"])
            self.assertEqual(list(inspect.signature(cls.get).parameters), ["self", "job"])
            self.assertEqual(list(inspect.signature(cls.check).parameters), ["self"])
        self.assertEqual(transport.RoomTransport.name, "room")
        self.assertEqual(transport.ClipboardTransport.name, "clipboard")

    def test_route_only_two_values(self):
        self.assertEqual(transport.check_route({}), {"model": "", "effort": ""})
        self.assertEqual(transport.check_route(ROUTE), ROUTE)
        for bad in ({"model": "m", "effort": "max", "table": {}}, {"effort": "turbo"}, {"model": 3}, [1],
                    {"model": "a\nb"}):
            with self.assertRaises(transport.TransportError):
                transport.check_route(bad)

    def test_clipboard_is_name_and_check_only(self):
        c = transport.get_transport("clipboard")
        self.assertTrue(c.check()["ok"])
        with self.assertRaises(transport.TransportError):
            c.put("J-0007", SEALED, ROUTE)
        with self.assertRaises(transport.TransportError):
            c.get("J-0007")
        for name in ("adapter", "mail", ""):
            with self.assertRaises(transport.TransportError):
                transport.get_transport(name)
        with self.assertRaises(transport.TransportError):
            transport.get_transport("room")


class RoomTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diode-transport-")
        self.room = os.path.join(self.tmp, "room")
        os.makedirs(self.room)
        make_room(self.room)
        self.t = transport.get_transport("room", self.room)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def outbox(self, job="J-0007"):
        return os.path.join(self.room, "outbox", job + ".md")

    def test_check(self):
        self.assertEqual(self.t.check(), {"ok": True, "room": "ok", "effort": True})

    def test_put_writes_exact_bytes_and_hash_matches_audit(self):
        self.t.put("J-0007", SEALED, ROUTE)
        with open(self.outbox(), "rb") as f:
            raw = f.read()
        self.assertEqual(raw, SEALED.encode("utf-8"))
        home = os.path.join(self.tmp, "home")
        audit.record(home, "J-0007", "out", "report", "room", "sent", text=SEALED)
        self.assertIn(hashlib.sha256(raw).hexdigest(), audit.confirmed_hashes(home))
        self.assertEqual(os.listdir(os.path.join(self.room, "outbox")), ["J-0007.md"])   # 임시 파일 없음

    def test_route_not_in_sealed_text(self):
        self.t.put("J-0007", SEALED, ROUTE)
        with open(self.outbox(), "rb") as f:
            raw = f.read().decode("utf-8")
        self.assertNotIn(ROUTE["model"], raw)
        self.assertNotIn("max", raw)
        self.assertNotIn("effort", raw)
        self.assertNotIn("model", raw)
        # 방 안 어디에도 route 가 남지 않는다
        for r, _, fs in os.walk(self.room):
            for fn in fs:
                with open(os.path.join(r, fn), "rb") as f:
                    self.assertNotIn(ROUTE["model"].encode("utf-8"), f.read())

    def test_never_overwrites(self):
        self.t.put("J-0007", SEALED, ROUTE)
        with self.assertRaises(transport.TransportError):
            self.t.put("J-0007", "다른 글", ROUTE)
        with open(self.outbox(), "rb") as f:
            self.assertEqual(f.read(), SEALED.encode("utf-8"))

    def test_bad_input_refused(self):
        for job in ("../J-0007", "J-7", "J-0007/../x", "", None):
            with self.assertRaises(transport.TransportError):
                self.t.put(job, SEALED, ROUTE)
            with self.assertRaises(transport.TransportError):
                self.t.get(job)
        for text in ("", None, b"bytes", "가" * 5000):
            with self.assertRaises(transport.TransportError):
                self.t.put("J-0007", text, ROUTE)
        with self.assertRaises(transport.TransportError):
            self.t.put("J-0007", SEALED, {"model": "m", "effort": "max", "raw": "원문"})
        self.assertEqual(os.listdir(os.path.join(self.room, "outbox")), [])

    def test_changed_room_refused(self):
        with open(os.path.join(self.room, ".claude", "settings.json"), "a", encoding="utf-8") as f:
            f.write(" ")
        self.assertFalse(self.t.check()["ok"])
        with self.assertRaises(transport.TransportError):
            self.t.put("J-0007", SEALED, ROUTE)
        missing = transport.RoomTransport(os.path.join(self.tmp, "nowhere"))
        self.assertFalse(missing.check()["ok"])
        with self.assertRaises(transport.TransportError):
            missing.put("J-0007", SEALED, ROUTE)

    def test_get_with_fake_tui(self):
        self.assertIsNone(self.t.get("J-0007"))
        self.t.put("J-0007", SEALED, ROUTE)
        subprocess.run([sys.executable, "-I", "-c", FAKE_TUI, self.room, "J-0007"], check=True, timeout=30)
        self.assertEqual(self.t.get("J-0007"), "받음 %d\n" % len(SEALED.encode("utf-8")))

    def test_get_too_big_refused(self):
        with open(os.path.join(self.room, "inbox", "J-0007.md"), "wb") as f:
            f.write(b"x" * (transport.MAX_ANSWER_BYTES + 1))
        with self.assertRaises(transport.TransportError):
            self.t.get("J-0007")


if __name__ == "__main__":
    unittest.main()
