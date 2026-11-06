# -*- coding: utf-8 -*-
"""확정 창 (diodelib.confirm) - 요청 파일 꼴 · 창의 논리 (2초 · Enter · 닫기 · 시간 초과 · clipboard) · 결정과 종료 코드 ·
창에 적는 글 · 창을 못 띄움 (E-07) · 건너뛰는 길이 없음 (AL-02) · 실제 tk 창 (DISPLAY 가 있을 때만).

화면은 가짜 백엔드로 바꿔 끼운다 (FakeView - 이 파일 안에만 있다. 실행 코드에는 우회가 없다). 모든 자료는 지어낸 것이다.
"""
import ast
import colorsys
import copy
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import confirm, scan  # noqa: E402

CONFIRM_PY = os.path.join(ROOT, "diodelib", "confirm.py")

TEXT = ("[diode report format=1 job=J-0007 status=done]\n"
        "COUNTS: changed_files=3 tests_passed=12 tests_failed=0\n"
        "SUMMARY:\n"
        "- PH_K7Q2 화면을 만들었다\n"
        "- 항목 PH_M3X9 의 표시를 붙였다\n"
        "QUESTIONS:\n"
        "- 목록의 정렬 기준을 정해 달라\n"
        "[/diode report]\n")

BASE = {
    "format": 1, "direction": "out", "job": "J-0007", "kind": "report", "transport": "room", "text": TEXT,
    "attachments": [], "checks": {"ok": True, "hits": []}, "model": "model-a", "effort": "high",
    "month": {"pct": 12, "estimated": False}, "effort_env_override": False, "timeout_s": 600,
}
HIT = {"ok": False, "hits": [{"check": "D2", "count": 2, "where": ["context[1]", "ask"]}]}


def make(**over):
    d = copy.deepcopy(BASE)
    d.update(over)
    return d


def raw(**over):
    return json.dumps(make(**over)).encode("utf-8")          # 허브처럼 ASCII 로 풀어 쓴 JSON


def parse(**over):
    return confirm.parse_request(raw(**over))


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Clock(object):
    """시각을 손으로 흘린다."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeView(object):
    """화면 백엔드 흉내 - 대본대로 시간을 흘리고 단추를 누른다. 시험 안에만 둔다 (실행 코드에 우회가 생기지 않게).

    대본의 걸음: ("wait", 초) · ("send",) · ("copy",) · ("edit",) · ("discard",) · ("close",) · ("key", 이름) · ("raise", 예외)
    """

    def __init__(self, script=(), clipboard_error=None, fail_after=None):
        self.script = list(script)
        self.now = 1000.0
        self.copies = []
        self.clipboard_error = clipboard_error
        self.fail_after = fail_after
        self.ran = False

    def set_clipboard(self, text):
        if self.clipboard_error is not None:
            raise self.clipboard_error
        self.copies.append(text)

    def run(self, session):
        self.ran = True
        session.start(self.now)
        for step in self.script:
            if session.decision is not None:
                break
            op = step[0]
            if op == "wait":
                self.now += step[1]
                session.tick(self.now)
            elif op == "send":
                session.press_send(self.now)
            elif op == "copy":
                session.press_copy(self.now)
            elif op == "edit":
                session.press_edit(self.now)
            elif op == "discard":
                session.press_discard(self.now)
            elif op == "close":
                session.close(self.now)
            elif op == "key":
                session.key(step[1], self.now)
            elif op == "raise":
                raise step[1]
        if self.fail_after is not None:
            raise self.fail_after


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="diode-confirm-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, data):
        path = os.path.join(self.dir, "request.json")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def run_main(self, view, **over):
        """가짜 화면을 끼워 main_confirm 을 부른다 -> (종료 코드, 한 줄)."""
        path = self.write(raw(**over))
        with mock.patch.object(confirm, "create_view", return_value=view):
            return confirm.main_confirm(path)


# ─────────────────────────────────────────────────────────────── 요청 파일 꼴

BAD_VALUES = [
    ("format", 2), ("format", "1"), ("format", True), ("format", 1.0), ("format", None),
    ("direction", "in"), ("direction", ""), ("direction", None), ("direction", 1),
    ("job", "J-7"), ("job", "j-0007"), ("job", "J-0007\n"), ("job", " J-0007"), ("job", 7), ("job", None),
    ("kind", "dispatch"), ("kind", "Report"), ("kind", None),
    ("transport", "adapter"), ("transport", ""), ("transport", None),
    ("text", ""), ("text", None), ("text", 5), ("text", ["a"]), ("text", "가\ud800나"), ("text", "가" * 22000),
    ("attachments", None), ("attachments", "a.html"), ("attachments", [1]), ("attachments", [""]),
    ("attachments", ["a\nb"]), ("attachments", ["a\u202eb"]), ("attachments", ["x" * 121]), ("attachments", ["a"] * 6),
    ("checks", None), ("checks", {}), ("checks", {"ok": True}), ("checks", {"ok": True, "hits": [], "x": 1}),
    ("checks", {"ok": 1, "hits": []}),
    ("checks", {"ok": True, "hits": [{"check": "D2", "count": 1, "where": ["ask"]}]}),     # ok 인데 hits 가 있음
    ("checks", {"ok": False, "hits": []}),                                                   # 걸렸는데 hits 가 없음
    ("checks", {"ok": False, "hits": ["D2"]}),
    ("checks", {"ok": False, "hits": [{"check": "D2", "count": -1, "where": []}]}),
    ("checks", {"ok": False, "hits": [{"check": "D2", "count": True, "where": []}]}),
    ("checks", {"ok": False, "hits": [{"check": "D2", "count": 1, "where": [1]}]}),
    ("checks", {"ok": False, "hits": [{"check": "D2", "count": 1, "where": ["가나"]}]}),
    ("checks", {"ok": False, "hits": [{"check": "D 2", "count": 1, "where": []}]}),
    ("checks", {"ok": False, "hits": [{"check": "E", "code": "E-2"}]}),
    ("checks", {"ok": False, "hits": [{"check": "D2"}]}),
    ("checks", {"ok": False, "hits": [{"check": "D2", "count": 1, "where": ["a"], "word": "x"}]}),
    ("model", None), ("model", 3), ("model", "a\nb"), ("model", "x" * 81),
    ("effort", "ultra"), ("effort", None), ("effort", "HIGH"), ("effort", 1),
    ("month", None), ("month", {}), ("month", {"pct": 1}), ("month", {"pct": "12", "estimated": False}),
    ("month", {"pct": True, "estimated": False}), ("month", {"pct": -1, "estimated": False}),
    ("month", {"pct": 1001, "estimated": False}), ("month", {"pct": 12, "estimated": 0}),
    ("month", {"pct": 12, "estimated": False, "x": 1}),
    ("effort_env_override", 0), ("effort_env_override", "false"), ("effort_env_override", None),
    ("timeout_s", "600"), ("timeout_s", True), ("timeout_s", None), ("timeout_s", [600]),
]

NOT_REQUESTS = [
    b"", b"{", b"[]", b"null", b"1", b'"x"', b"\xff\xfe\x00", b'{"format": 1',
    b'{"format": 1, "format": 1}',                                            # 같은 키 두 번
    json.dumps(BASE).encode("utf-8").replace(b'"timeout_s": 600', b'"timeout_s": NaN'),
    json.dumps(BASE).encode("utf-8").replace(b'"timeout_s": 600', b'"timeout_s": Infinity'),
    json.dumps(BASE).encode("utf-8") + b" x",                                 # 뒤에 쓰레기
    b"[" * 100000 + b"]" * 100000,                                            # 너무 깊음
]


class TestRequestShape(Base):
    def test_a_good_request_is_read(self):
        r = parse(attachments=["a.html", "b.png"], direction="dispatch", kind="plan", transport="clipboard",
                  checks=HIT, model="", effort="", month={"pct": None, "estimated": True}, effort_env_override=True)
        self.assertEqual((r.direction, r.job, r.kind, r.transport), ("dispatch", "J-0007", "plan", "clipboard"))
        self.assertEqual(r.text, TEXT)
        self.assertEqual(r.attachments, ("a.html", "b.png"))
        self.assertFalse(r.checks_ok)
        self.assertIsNone(r.month_pct)
        self.assertTrue(r.month_estimated and r.effort_env_override)
        self.assertEqual((r.model, r.effort), ("", ""))
        self.assertEqual(r.sha256, sha(TEXT))
        self.assertEqual(r.text_bytes, len(TEXT.encode("utf-8")))

    def test_utf8_without_escapes_and_a_bom_are_read(self):
        data = json.dumps(BASE, ensure_ascii=False).encode("utf-8")
        self.assertEqual(confirm.parse_request(data).text, TEXT)
        self.assertEqual(confirm.parse_request(b"\xef\xbb\xbf" + data).text, TEXT)

    def test_timeout_default_and_clamp(self):
        d = make()
        del d["timeout_s"]
        self.assertEqual(confirm.parse_request(json.dumps(d).encode()).timeout_s, 600)
        for given, want in ((9999, 600), (601, 600), (600, 600), (30, 30), (30.5, 30.5), (1, 1), (0, 1), (0.2, 1), (-5, 1)):
            self.assertEqual(parse(timeout_s=given).timeout_s, want, given)

    def test_every_missing_field_is_an_error(self):
        self.assertEqual(len(confirm._REQUIRED), 11)
        for key in confirm._REQUIRED:
            d = make()
            del d[key]
            with self.assertRaises(confirm.RequestError, msg=key):
                confirm.parse_request(json.dumps(d).encode())

    def test_only_two_fields_may_be_left_out(self):
        d = make()
        del d["timeout_s"], d["effort_env_override"]
        r = confirm.parse_request(json.dumps(d).encode())
        self.assertEqual((r.timeout_s, r.effort_env_override), (600.0, False))

    def test_the_requests_the_hub_builds_today_are_accepted(self):
        """diodelib/hub.py 가 지금 만드는 요청 두 가지 (넘기기 · 보고) 그대로."""
        for direction in ("dispatch", "out"):
            hub_request = {"format": 1, "direction": direction, "job": "J-0007", "kind": "report", "transport": "room",
                           "text": TEXT, "attachments": ["draft-screen.html"] if direction == "dispatch" else [],
                           "checks": {"ok": True, "hits": []}, "model": "", "effort": "",
                           "month": {"pct": 0, "estimated": True}}
            r = confirm.parse_request(json.dumps(hub_request).encode())
            self.assertEqual((r.direction, r.timeout_s, r.effort_env_override), (direction, 600.0, False))

    def test_an_unknown_field_is_an_error(self):
        for extra in ({"auto_send": True}, {"skip": 1}, {"word": "x"}):
            d = make()
            d.update(extra)
            with self.assertRaises(confirm.RequestError):
                confirm.parse_request(json.dumps(d).encode())

    def test_wrong_values_are_errors(self):
        for key, value in BAD_VALUES:
            with self.assertRaises(confirm.RequestError, msg="%s=%r" % (key, value if len(repr(value)) < 60 else "...")):
                parse(**{key: value})

    def test_things_that_are_not_requests(self):
        for data in NOT_REQUESTS:
            with self.assertRaises(confirm.RequestError, msg=data[:40]):
                confirm.parse_request(data)

    def test_size_limits(self):
        edge = "가" * (confirm.MAX_TEXT_BYTES // 3)                 # 정확히 상한
        self.assertEqual(parse(text=edge).text_bytes, confirm.MAX_TEXT_BYTES - confirm.MAX_TEXT_BYTES % 3)
        with self.assertRaises(confirm.RequestError):
            parse(text=edge + "가가")
        path = self.write(b" " * (confirm.MAX_REQUEST_BYTES + 1))
        with self.assertRaises(confirm.RequestError):
            confirm.read_request(path)

    def test_error_messages_never_carry_the_text(self):
        with self.assertRaises(confirm.RequestError) as ctx:
            parse(text=TEXT, kind="가상소재")
        self.assertNotIn("가상소재", str(ctx.exception))
        self.assertNotIn("화면", str(ctx.exception))


# ─────────────────────────────────────────────────────────────── 창의 논리

class TestSession(unittest.TestCase):
    def make(self, start=0.0, **over):
        self.copies = []
        s = confirm.ConfirmSession(parse(**over), clipboard=self.copies.append)
        if start is not None:
            s.start(start)
        return s

    def test_send_is_off_for_the_first_two_seconds(self):
        s = self.make()
        for t in (0.0, 0.5, 1.99):
            self.assertFalse(s.snapshot(t).send_enabled, t)
            self.assertFalse(s.press_send(t), t)
            self.assertIsNone(s.decision)
        self.assertTrue(s.snapshot(2.0).send_enabled)
        self.assertTrue(s.press_send(2.0))
        self.assertEqual(s.decision, "send")

    def test_the_two_seconds_count_from_the_window_start(self):
        s = self.make(start=None)
        self.assertFalse(s.press_send(50.0))                     # 아직 창이 안 떴다
        s.start(100.0)
        s.start(500.0)                                           # 두 번째 start 는 무시
        self.assertFalse(s.press_send(101.9))
        self.assertTrue(s.press_send(102.0))

    def test_discard_and_edit_work_at_once(self):
        for method, want in (("press_discard", "discard"), ("press_edit", "edit")):
            s = self.make()
            self.assertTrue(getattr(s, method)(0.0))
            self.assertEqual(s.decision, want)

    def test_closing_and_escape_discard(self):
        s = self.make()
        self.assertTrue(s.close(0.1))
        self.assertEqual(s.decision, "discard")
        s = self.make()
        self.assertTrue(s.key("Escape", 0.1))
        self.assertEqual(s.decision, "discard")
        s = self.make(start=None)                                # 창이 뜨기 전에 닫아도 버림
        self.assertTrue(s.close(0.0))
        self.assertEqual(s.decision, "discard")

    def test_enter_never_sends(self):
        s = self.make()
        self.assertTrue(s.snapshot(5.0).send_enabled)            # 보낼 수 있는 때에도
        for name in ("Return", "KP_Enter", "space", "y", "s", "Tab", ""):
            self.assertFalse(s.key(name, 5.0), name)
        self.assertIsNone(s.decision)
        self.assertTrue(s.snapshot(5.0).send_enabled)

    def test_timeout(self):
        s = self.make()
        s.tick(599.9)
        self.assertIsNone(s.decision)
        s.tick(600.0)
        self.assertEqual(s.decision, "timeout")

    def test_a_press_after_the_deadline_is_a_timeout_never_a_send(self):
        s = self.make()
        self.assertFalse(s.press_send(600.5))
        self.assertEqual(s.decision, "timeout")
        s = self.make()
        self.assertFalse(s.press_discard(700.0))                 # 시간이 지난 뒤의 손은 시간 초과
        self.assertEqual(s.decision, "timeout")
        s = self.make(timeout_s=1)
        self.assertFalse(s.press_send(2.0))                      # 2초 (켜짐) 가 되기 전에 1초 (끝) 이 왔다
        self.assertEqual(s.decision, "timeout")

    def test_failed_checks_never_turn_send_on(self):
        s = self.make(checks=HIT)
        for t in (2.0, 60.0, 599.0):
            self.assertFalse(s.snapshot(t).send_enabled)
            self.assertFalse(s.press_send(t))
        snap = s.snapshot(10.0)
        self.assertIn("검사에 걸린", snap.message)
        self.assertFalse(snap.check_ok)
        self.assertTrue(s.press_discard(10.0))
        self.assertEqual(s.decision, "discard")

    def test_the_first_decision_wins(self):
        s = self.make()
        self.assertTrue(s.press_send(3.0))
        self.assertFalse(s.press_discard(3.1))
        self.assertFalse(s.press_edit(3.2))
        self.assertFalse(s.close(3.3))
        self.assertFalse(s.key("Escape", 3.4))
        self.assertEqual(s.decision, "send")
        s = self.make()
        s.press_discard(0.5)
        self.assertFalse(s.press_send(5.0))
        self.assertEqual(s.decision, "discard")

    def test_clipboard_send_needs_the_copy(self):
        s = self.make(transport="clipboard")
        self.assertTrue(s.needs_copy)
        self.assertFalse(s.snapshot(3.0).copy_enabled)
        self.assertFalse(s.press_copy(3.0))                      # 보내기를 누르기 전에는 복사가 안 된다
        self.assertEqual(self.copies, [])
        self.assertTrue(s.press_send(3.0))
        self.assertIsNone(s.decision)                            # 아직 보낸 것이 아니다
        self.assertTrue(s.approved)
        snap = s.snapshot(3.1)
        self.assertTrue(snap.copy_enabled)
        self.assertFalse(snap.send_enabled)
        self.assertFalse(s.press_send(3.2))                      # 두 번 눌러도 소용없다
        self.assertTrue(s.press_copy(4.0))
        self.assertEqual(self.copies, [TEXT])                    # 보낼 글 그대로
        self.assertEqual(s.decision, "send")

    def test_a_failed_copy_is_not_a_send(self):
        for clipboard in (mock.Mock(side_effect=OSError("x")), None):
            s = confirm.ConfirmSession(parse(transport="clipboard"), clipboard=clipboard)
            s.start(0.0)
            s.press_send(3.0)
            self.assertFalse(s.press_copy(3.5))
            self.assertIsNone(s.decision)
            self.assertIn("클립보드", s.snapshot(3.6).message)
            self.assertTrue(s.snapshot(3.6).copy_enabled)       # 다시 눌러 볼 수 있다
            self.assertTrue(s.press_discard(4.0))
            self.assertEqual(s.decision, "discard")

    def test_clipboard_without_the_copy_is_never_a_send(self):
        s = self.make(transport="clipboard")
        s.press_send(3.0)
        s.close(4.0)
        self.assertEqual(s.decision, "discard")
        self.assertEqual(self.copies, [])
        s = self.make(transport="clipboard")
        s.press_send(3.0)
        s.tick(700.0)
        self.assertEqual(s.decision, "timeout")

    def test_dispatch_is_never_copied(self):
        s = self.make(direction="dispatch", transport="clipboard", kind="plan")
        self.assertFalse(s.needs_copy)
        self.assertFalse(s.press_copy(3.0))
        self.assertTrue(s.press_send(3.0))
        self.assertEqual(s.decision, "send")
        self.assertEqual(self.copies, [])

    def test_numbers_for_the_screen(self):
        s = self.make()
        a = s.snapshot(0.5)
        self.assertEqual((a.delay_s, a.remaining_s, a.send_enabled, a.decided), (2, 600, False, False))
        b = s.snapshot(1.2)
        self.assertEqual((b.delay_s, b.remaining_s), (1, 599))
        c = s.snapshot(2.0)
        self.assertEqual((c.delay_s, c.send_enabled), (0, True))
        self.assertEqual(s.snapshot(599.2).remaining_s, 1)
        d = s.snapshot(600.0)
        self.assertEqual((d.remaining_s, d.decided, d.send_enabled), (0, True, False))


# ─────────────────────────────────────────────────────────────── 결정 · 결과 한 줄 · 종료 코드

class TestMain(Base):
    def test_each_decision_has_its_result_and_exit_code(self):
        cases = (
            ([("wait", 3), ("send",)], "send", 0),
            ([("discard",)], "discard", 3),
            ([("edit",)], "edit", 3),
            ([("close",)], "discard", 3),
            ([("key", "Escape")], "discard", 3),
            ([("wait", 601)], "timeout", 3),
        )
        for script, decision, code in cases:
            view = FakeView(script)
            got = self.run_main(view)
            self.assertEqual(got, (code, json.dumps({"decision": decision, "sha256": sha(TEXT)})), script)
            self.assertTrue(view.ran)

    def test_the_hash_is_the_text_bytes(self):
        for text in ("가나다 PH_K7Q2\r\n끝", "ASCII only", "한글 " * 300, "\u00a0탭\t과 \u200b"):
            line = self.run_main(FakeView([("wait", 3), ("send",)]), text=text)[1]
            self.assertEqual(json.loads(line)["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
            self.assertEqual(json.loads(line)["sha256"], confirm.text_sha256(text))

    def test_the_result_never_carries_the_text(self):
        for script in ([("wait", 3), ("send",)], [("edit",)], [("discard",)], [("wait", 700)]):
            code, line = self.run_main(FakeView(script), model="model-a")
            self.assertEqual(sorted(json.loads(line)), ["decision", "sha256"])
            self.assertEqual(line, line.encode("ascii").decode("ascii"))
            self.assertNotIn("\n", line)
            for piece in ("화면", "정렬", "PH_", "diode", "J-0007", "model-a", "high"):
                self.assertNotIn(piece, line, piece)

    def test_enter_does_not_send_even_after_the_wait(self):
        view = FakeView([("wait", 3), ("key", "Return"), ("key", "KP_Enter"), ("wait", 700)])
        self.assertEqual(self.run_main(view)[0], 3)
        self.assertEqual(json.loads(self.run_main(FakeView([("wait", 3), ("key", "Return"), ("wait", 700)]))[1])["decision"], "timeout")

    def test_a_press_in_the_first_two_seconds_is_ignored(self):
        view = FakeView([("send",), ("wait", 1.5), ("send",), ("discard",)])
        self.assertEqual(json.loads(self.run_main(view)[1])["decision"], "discard")

    def test_failed_checks_cannot_be_sent(self):
        view = FakeView([("wait", 5), ("send",), ("wait", 100), ("send",), ("discard",)])
        self.assertEqual(json.loads(self.run_main(view, checks=HIT)[1])["decision"], "discard")

    def test_clipboard_flow(self):
        view = FakeView([("wait", 3), ("send",), ("copy",)])
        code, line = self.run_main(view, transport="clipboard")
        self.assertEqual((code, json.loads(line)["decision"]), (0, "send"))
        self.assertEqual(view.copies, [TEXT])
        view = FakeView([("wait", 3), ("send",), ("close",)])                 # 복사하지 않고 닫음
        code, line = self.run_main(view, transport="clipboard")
        self.assertEqual((code, json.loads(line)["decision"]), (3, "discard"))
        self.assertEqual(view.copies, [])
        view = FakeView([("wait", 3), ("send",)])                              # 보내기만 눌렀고 화면이 끝남
        self.assertEqual(self.run_main(view, transport="clipboard")[0], 1)
        view = FakeView([("wait", 3), ("send",), ("copy",)], clipboard_error=OSError("x"))
        self.assertEqual(self.run_main(view, transport="clipboard")[0], 1)     # 복사 실패 = 결정이 없다 = 보내지 않음
        self.assertEqual(view.copies, [])

    def test_dispatch_says_send_without_a_copy(self):
        view = FakeView([("wait", 3), ("send",)])
        code, line = self.run_main(view, direction="dispatch", kind="plan", transport="clipboard")
        self.assertEqual((code, json.loads(line)["decision"]), (0, "send"))
        self.assertEqual(view.copies, [])

    def test_a_bad_request_never_opens_a_window(self):
        for data in NOT_REQUESTS[:6] + [raw(format=2), raw(text=""), raw(direction="x")]:
            path = self.write(data)
            with mock.patch.object(confirm, "create_view") as create:
                self.assertEqual(confirm.main_confirm(path), (2, '{"decision": "error", "code": "E-04"}'))
                create.assert_not_called()

    def test_a_missing_path_or_file(self):
        with mock.patch.object(confirm, "create_view") as create:
            for path in (None, "", 5, ["a"]):
                self.assertEqual(confirm.main_confirm(path), (2, '{"decision": "error", "code": "E-04"}'), path)
            for path in (os.path.join(self.dir, "none.json"), self.dir):         # 없는 파일 · 폴더
                self.assertEqual(confirm.main_confirm(path), (1, '{"decision": "error", "code": "E-20"}'), path)
            create.assert_not_called()

    def test_no_exception_ends_as_a_send(self):
        err = '{"decision": "error", "code": "E-20"}'
        cases = (
            FakeView([("raise", RuntimeError("x"))]),
            FakeView([("wait", 3), ("raise", ValueError("x"))]),
            FakeView([("wait", 3), ("send",)], fail_after=RuntimeError("x")),     # 결정이 난 뒤의 예외도 send 가 아니다
            FakeView([("wait", 3), ("send",)], fail_after=KeyboardInterrupt()),
            FakeView([]),                                                         # 결정 없이 끝난 화면
        )
        for view in cases:
            self.assertEqual(self.run_main(view), (1, err))

    def test_window_unavailable_is_e07_and_other_errors_are_e20(self):
        path = self.write(raw())
        for effect, want in ((confirm.WindowUnavailable("x"), (1, '{"decision": "error", "code": "E-07"}')),
                             (RuntimeError("x"), (1, '{"decision": "error", "code": "E-20"}')),
                             (KeyboardInterrupt(), (1, '{"decision": "error", "code": "E-20"}'))):
            with mock.patch.object(confirm, "create_view", side_effect=effect):
                self.assertEqual(confirm.main_confirm(path), want)

    def test_the_request_file_is_left_alone(self):
        path = self.write(raw())
        with open(path, "rb") as f:
            before = f.read()
        for script in ([("wait", 3), ("send",)], [("discard",)]):
            with mock.patch.object(confirm, "create_view", return_value=FakeView(script)):
                confirm.main_confirm(path)
        self.assertEqual(os.listdir(self.dir), ["request.json"])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)


class TestParseResult(Base):
    """허브 쪽의 읽기 - 보낼 글의 sha256 과 맞고 꼴이 정확할 때만 send 로 읽는다."""

    def test_round_trip(self):
        for script, decision in (([("wait", 3), ("send",)], "send"), ([("discard",)], "discard"),
                                 ([("edit",)], "edit"), ([("wait", 700)], "timeout")):
            code, line = self.run_main(FakeView(script))
            self.assertEqual(confirm.parse_result(code, line + "\n", sha(TEXT)), (decision, None))

    def test_errors_round_trip(self):
        for code, line in ((2, '{"decision": "error", "code": "E-04"}'), (1, '{"decision": "error", "code": "E-07"}'),
                           (1, '{"decision": "error", "code": "E-20"}')):
            self.assertEqual(confirm.parse_result(code, line, sha(TEXT)), ("error", json.loads(line)["code"]))

    def test_anything_else_is_an_error_never_a_send(self):
        good = json.dumps({"decision": "send", "sha256": sha(TEXT)})
        other = sha("다른 글")
        bad = "error", "E-20"
        self.assertEqual(confirm.parse_result(0, good, sha(TEXT)), ("send", None))
        for code, out, expect in (
                (0, good, other),                                                              # 사람이 본 글 != 보낼 글
                (3, good, sha(TEXT)),                                                          # 종료 코드가 send 가 아님
                (1, good, sha(TEXT)), (None, good, sha(TEXT)), (True, good, sha(TEXT)),
                (0, "", sha(TEXT)), (0, "\n", sha(TEXT)), (0, good + "\n" + good, sha(TEXT)),
                (0, "열려요 " + good, sha(TEXT)), (0, "[]", sha(TEXT)), (0, "null", sha(TEXT)),
                (0, json.dumps({"decision": "send"}), sha(TEXT)),
                (0, json.dumps({"decision": "send", "sha256": sha(TEXT), "text": "x"}), sha(TEXT)),
                (0, json.dumps({"decision": "send", "sha256": sha(TEXT).upper()}), sha(TEXT)),
                (0, json.dumps({"decision": "sent", "sha256": sha(TEXT)}), sha(TEXT)),
                (0, '{"decision": "send", "decision": "send", "sha256": "%s"}' % sha(TEXT), sha(TEXT)),
                (0, good, None), (0, good, sha(TEXT).upper()), (0, good, "abc"),              # 기대한 값이 없거나 꼴이 틀림
                (3, json.dumps({"decision": "discard", "sha256": other}), sha(TEXT)),
                (0, json.dumps({"decision": "discard", "sha256": sha(TEXT)}), sha(TEXT)),     # 종료 코드가 discard 와 안 맞음
                (2, '{"decision": "error", "code": "E-07"}', sha(TEXT)),
                (1, '{"decision": "error", "code": "E-99"}', sha(TEXT)),
                (1, '{"decision": "error", "code": "E-07", "text": "x"}', sha(TEXT)),
                (0, '{"decision": "error", "code": "E-20"}', sha(TEXT))):
            self.assertEqual(confirm.parse_result(code, out, expect), bad, (code, out[:50], expect))
        self.assertEqual(confirm.parse_result(0, None, sha(TEXT)), bad)                       # 글이 아님


# ─────────────────────────────────────────────────────────────── 창에 적는 글 (화면 없이)

class TestPanels(unittest.TestCase):
    def test_direction_is_on_top_and_the_button_names_follow_it(self):
        out = confirm.build_panels(parse())
        self.assertEqual((out.chip, out.title, out.send_label), ("OUT", "바깥으로 보내기", "보내기"))
        inner = confirm.build_panels(parse(direction="dispatch", kind="plan"))
        self.assertEqual((inner.chip, inner.title, inner.send_label), ("IN", "안쪽으로 넘기기", "넘기기"))

    def test_the_notices(self):
        notices = dict(confirm.build_panels(parse()).notices)
        self.assertEqual(notices["보내면 되돌릴 수 없습니다"], "strong")
        self.assertEqual(notices["이 내용이 감사 기록에 남습니다"], "strong")
        self.assertEqual(len(notices), 2)                                            # 평소에는 이 둘뿐
        inner = dict(confirm.build_panels(parse(direction="dispatch", kind="plan")).notices)
        self.assertIn("넘기면 되돌릴 수 없습니다", inner)
        self.assertIn("이 내용이 감사 기록에 남습니다", inner)
        self.assertNotIn("보내면 되돌릴 수 없습니다", inner)
        self.assertTrue(any("사내 말이 보일 수 있습니다" in n for n in inner))        # 되돌린 지시 (이 창 안에서만)
        self.assertFalse(any("사내 말" in n for n in notices))

    def test_the_effort_override_notice(self):
        on = [n for n, _ in confirm.build_panels(parse(effort_env_override=True)).notices]
        self.assertTrue(any("환경 변수 CLAUDE_CODE_EFFORT_LEVEL 이 effort 를 덮어씁니다" in n for n in on))
        off = [n for n, _ in confirm.build_panels(parse(effort_env_override=False)).notices]
        self.assertFalse(any("CLAUDE_CODE_EFFORT_LEVEL" in n for n in off))

    def test_the_month_is_marked_when_estimated(self):
        self.assertIn("이번 달 ~12%", confirm.build_panels(parse(month={"pct": 12, "estimated": True})).route)
        self.assertIn("이번 달 12%", confirm.build_panels(parse(month={"pct": 12, "estimated": False})).route)
        self.assertNotIn("~", confirm.build_panels(parse(month={"pct": 12, "estimated": False})).route)
        self.assertIn("이번 달 12%", confirm.build_panels(parse(month={"pct": 12.4, "estimated": False})).route)
        self.assertIn("이번 달 -", confirm.build_panels(parse(month={"pct": None, "estimated": True})).route)

    def test_model_effort_and_blanks(self):
        route = confirm.build_panels(parse(model="model-a", effort="xhigh")).route
        self.assertIn("모델 model-a", route)
        self.assertIn("effort xhigh", route)
        blank = confirm.build_panels(parse(model="", effort="")).route
        self.assertIn("모델 -", blank)
        self.assertIn("effort -", blank)

    def test_the_check_line_is_the_scan_line(self):
        self.assertEqual(confirm.build_panels(parse()).check_line, "DIODE V>Vth 통과")
        p = confirm.build_panels(parse(checks=HIT))
        self.assertEqual(p.check_line, scan.format_line(HIT))
        self.assertEqual(p.check_line, "DIODE V<Vth 막힘 · D2 x2 @context[1], ask")
        self.assertFalse(p.check_ok)

    def test_attachments_and_the_text_line(self):
        self.assertEqual(confirm.build_panels(parse()).files, "없음")
        self.assertEqual(confirm.build_panels(parse(attachments=["a.html", "b.png"])).files, "a.html · b.png")
        info = confirm.build_panels(parse()).text_info
        for want in ("J-0007", "report", "room", "%d B" % len(TEXT.encode("utf-8")), "8 줄", "sha256 " + sha(TEXT)[:16]):
            self.assertIn(want, info)
        inner = confirm.build_panels(parse(direction="dispatch", kind="plan", transport="clipboard")).text_info
        self.assertNotIn("clipboard", inner)                                         # 넘기기에는 전달 길이 없다

    def test_tokens_are_marked(self):
        segs = confirm.display_segments("가 PH_K7Q2를 PH_M3X9 PH_K7Q1 ph_k7q2 PH_K7Q2X")
        self.assertEqual([s for s, f in segs if f == "token"], ["PH_K7Q2", "PH_M3X9"])
        plain = "".join(s for s, f in segs if f is None)
        self.assertIn("PH_K7Q1", plain)                                              # 글자 1 은 토큰 꼴이 아니다
        self.assertEqual("".join(s for s, _ in segs), "가 PH_K7Q2를 PH_M3X9 PH_K7Q1 ph_k7q2 PH_K7Q2X")

    def test_hidden_characters_are_shown_and_the_text_is_recoverable(self):
        tricky = "a\u200bb\u202ec\u00a0d\r\ne\x00f\u3164g\ufe0fh\u2028i\ue000j\tk l\n가나다ㄱ\x1b[0m PH_K7Q2\ufeff"
        segs = confirm.display_segments(tricky)
        marks = [s for s, f in segs if f == "hidden"]
        self.assertEqual(marks, ["[U+200B]", "[U+202E]", "[U+00A0]", "[U+000D]", "[U+0000]", "[U+3164]", "[U+FE0F]",
                                 "[U+2028]", "[U+E000]", "[U+001B]", "[U+FEFF]"])
        back = "".join(chr(int(s[3:-1], 16)) if f == "hidden" else s for s, f in segs)
        self.assertEqual(back, tricky)                                               # 보인 것을 되돌리면 보낼 글 그대로
        shown = "".join(s for s, _ in segs)
        for ch in "\u200b\u202e\u00a0\r\x00\u3164\ufe0f\u2028\ue000\x1b\ufeff":
            self.assertNotIn(ch, shown)
        for ch in "\n\t 가나다ㄱ":                                                     # 보이는 글자는 그대로
            self.assertIn(ch, shown)
        notice = [n for n, level in confirm.build_panels(parse(text=tricky)).notices if level == "alert"]
        self.assertEqual(len(notice), 1)
        self.assertIn("보이지 않는 글자 %d개" % len(marks), notice[0])

    def test_plain_text_has_no_alert(self):
        self.assertEqual([lv for _, lv in confirm.build_panels(parse()).notices if lv == "alert"], [])
        self.assertFalse(any(f == "hidden" for _, f in confirm.display_segments(TEXT)))

    def test_visible_text_comes_through_verbatim(self):
        self.assertEqual("".join(s for s, _ in confirm.build_panels(parse()).segments), TEXT)

    def test_the_act_note_names_the_path(self):
        self.assertIn("outbox", confirm.build_panels(parse()).act_note)
        self.assertIn("복사", confirm.build_panels(parse(transport="clipboard")).act_note)
        self.assertIn("일꾼", confirm.build_panels(parse(direction="dispatch", kind="plan")).act_note)


# ─────────────────────────────────────────────────────────────── 창을 못 띄움 (E-07)

def env_with(**display):
    """DISPLAY · WAYLAND_DISPLAY 만 바꾼 환경 (나머지 환경 변수는 그대로 - Windows 에서도 안전하게)."""
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env.update(display)
    return mock.patch.dict(os.environ, env, clear=True)


def fake_tkinter(error):
    """창을 못 여는 가짜 tkinter - Tk() 가 error 로 실패한다."""
    tk = types.ModuleType("tkinter")

    class TclError(Exception):
        pass

    def Tk(*args, **kw):
        raise (TclError if error is None else error)("no display")

    tk.TclError, tk.Tk, tk.font = TclError, Tk, types.ModuleType("tkinter.font")
    return tk


class TestNoWindow(Base):
    E07 = (1, '{"decision": "error", "code": "E-07"}')

    def test_no_display_is_e07_and_tkinter_is_not_even_loaded(self):
        path = self.write(raw())
        with env_with(), mock.patch.object(confirm, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules):
            for name in [n for n in sys.modules if n.split(".")[0] in ("tkinter", "_tkinter")]:
                del sys.modules[name]
            self.assertEqual(confirm.main_confirm(path), self.E07)
            self.assertFalse([n for n in sys.modules if n.split(".")[0] in ("tkinter", "_tkinter")])
        with env_with(DISPLAY=""), mock.patch.object(confirm, "_is_windows", return_value=False):
            self.assertEqual(confirm.main_confirm(path), self.E07)                          # 빈 DISPLAY 도 없는 것

    def test_which_environments_count_as_a_display(self):
        self.assertTrue(confirm.display_missing({}, False))
        self.assertTrue(confirm.display_missing({"DISPLAY": "", "WAYLAND_DISPLAY": ""}, False))
        self.assertFalse(confirm.display_missing({"DISPLAY": ":0"}, False))
        self.assertFalse(confirm.display_missing({"WAYLAND_DISPLAY": "wayland-0"}, False))
        self.assertFalse(confirm.display_missing({}, True))                                 # Windows 는 보지 않는다

    def test_a_display_does_not_skip_anything_it_only_lets_the_window_try(self):
        with env_with(DISPLAY=":0"), mock.patch.object(confirm, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertEqual(confirm.main_confirm(self.write(raw())), self.E07)             # tkinter 를 못 부름

    def test_tkinter_import_failure_is_e07(self):
        with env_with(DISPLAY=":0"), mock.patch.object(confirm, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": None}):
            with self.assertRaises(confirm.WindowUnavailable):
                confirm.create_view()
            self.assertEqual(confirm.main_confirm(self.write(raw())), self.E07)

    def test_a_tcl_error_is_e07(self):
        fake = fake_tkinter(None)
        with env_with(DISPLAY=":0"), mock.patch.object(confirm, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": fake, "tkinter.font": fake.font}):
            self.assertEqual(confirm.main_confirm(self.write(raw())), self.E07)

    def test_another_error_when_opening_is_e20_not_a_send(self):
        fake = fake_tkinter(RuntimeError)
        with env_with(DISPLAY=":0"), mock.patch.object(confirm, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": fake, "tkinter.font": fake.font}):
            self.assertEqual(confirm.main_confirm(self.write(raw())), (1, '{"decision": "error", "code": "E-20"}'))


# ─────────────────────────────────────────────────────────────── 건너뛰는 길이 없다 (AL-02) · 규칙

def _source():
    with open(CONFIRM_PY, "r", encoding="utf-8") as f:
        return f.read()


def _const(node):
    """첨자의 상수 값 (3.8 의 ast 는 상수를 Index 로 감싼다)."""
    if type(node).__name__ == "Index":
        node = node.value
    return node.value if isinstance(node, ast.Constant) else None


def _is_environ(node):
    return (isinstance(node, ast.Name) and node.id == "environ") or (isinstance(node, ast.Attribute) and node.attr == "environ")


# works tools/works_check.py 의 색 규칙 (DESIGN.md › 02): 채도가 있으면 네이비 (190-230도) 나 라임 (75-110도) 이어야 한다
def color_ok(r, g, b):
    if (max(r, g, b) - min(r, g, b)) / 255 < 0.10:
        return True
    hue = int(round(colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360))
    return 190 <= hue <= 230 or 75 <= hue <= 110


class TestNoWayAround(unittest.TestCase):
    def test_the_entry_points_take_no_switches(self):
        self.assertEqual(list(inspect.signature(confirm.main_confirm).parameters), ["path"])
        self.assertEqual(list(inspect.signature(confirm.create_view).parameters), [])

    def test_the_only_environment_reads_are_the_display_variables(self):
        tree = ast.parse(_source())
        keys, other = set(), []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("getenv", "putenv", "unsetenv", "setdefault", "pop", "update") and (
                        node.func.attr.endswith("env") or _is_environ(node.func.value)):
                    other.append(node.lineno)
                if node.func.attr == "get" and _is_environ(node.func.value):
                    keys.add(_const(node.args[0]))
            elif isinstance(node, ast.Subscript) and _is_environ(node.value):
                keys.add(_const(node.slice))
            elif isinstance(node, ast.Attribute) and node.attr in ("argv", "orig_argv"):
                other.append(node.lineno)
        self.assertEqual(other, [])
        self.assertEqual(keys, {"DISPLAY", "WAYLAND_DISPLAY"})

    def test_the_module_writes_nothing_and_prints_nothing(self):
        tree = ast.parse(_source())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    names.add((getattr(node, "module", None) or a.name).split(".")[0])
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in ("print", "exec", "eval", "compile"):
                    self.fail("%s() 를 부름 (줄 %d)" % (fn.id, node.lineno))
                if isinstance(fn, ast.Name) and fn.id == "open":
                    mode = node.args[1].value if len(node.args) > 1 else "r"
                    self.assertEqual(mode, "rb", "open 은 읽기 (rb) 만 (줄 %d)" % node.lineno)
                if isinstance(fn, ast.Attribute) and fn.attr in ("write", "writelines", "write_text", "write_bytes"):
                    self.fail("%s 를 부름 (줄 %d)" % (fn.attr, node.lineno))
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "os":
                    self.fail("os.%s 를 부름 (줄 %d) - 파일 · 프로세스를 건드리지 않는다" % (fn.attr, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr in ("stdout", "stderr", "stdin"):
                self.fail("표준 입출력을 건드림 (줄 %d)" % node.lineno)
        self.assertFalse(names & {"logging", "subprocess", "shutil", "tempfile", "socket", "urllib", "http", "pickle", "sys"}, names)

    def test_the_fake_screen_lives_only_in_the_tests(self):
        lib = os.path.join(ROOT, "diodelib")
        for name in sorted(os.listdir(lib)):
            if name.endswith(".py"):
                with open(os.path.join(lib, name), "r", encoding="utf-8") as f:
                    self.assertNotIn("FakeView", f.read(), name)
        self.assertFalse([n for n in dir(confirm) if re.search(r"fake|auto|bypass|skip|yes", n, re.I)])

    def test_python38_syntax(self):
        ast.parse(_source(), filename=CONFIRM_PY, feature_version=(3, 8))

    def test_colors_are_navy_lime_or_gray_never_red(self):
        src = _source()
        found = re.findall(r"#([0-9A-Fa-f]{6})\b", src)
        self.assertTrue(found)
        for h in found:
            self.assertTrue(color_ok(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), "#" + h)
        for name, value in confirm.PALETTE.items():
            r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
            self.assertTrue(color_ok(r, g, b), name)
        banned = {"red", "orange", "yellow", "pink", "purple", "magenta", "brown", "crimson", "tomato", "gold", "violet",
                  "firebrick", "darkred", "salmon", "coral", "maroon"}
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn(node.value.strip().lower(), banned)

    def test_no_emoji_or_wide_symbols(self):
        wide = {"\u2713", "\u26a0", "\u2605"}                               # DESIGN.md › 03: 체크 · 경고 · 별 기호는 폭 2칸
        for path in (CONFIRM_PY, os.path.abspath(__file__)):
            with open(path, "r", encoding="utf-8") as f:
                for ch in f.read():
                    self.assertFalse(0x1F000 <= ord(ch) <= 0x1FAFF or ch in wide, "%s: U+%04X" % (os.path.basename(path), ord(ch)))

    def test_the_fixed_phrases_are_in_the_window_code(self):
        src = _source()
        for want in ("보내면 되돌릴 수 없습니다", "이 내용이 감사 기록에 남습니다", "환경 변수 CLAUDE_CODE_EFFORT_LEVEL 이 effort 를 덮어씁니다"):
            self.assertIn(want, src)


# ─────────────────────────────────────────────────────────────── 실제 tk 창 (DISPLAY 가 있을 때만)

def _tk_usable():
    """DISPLAY 가 있고 tkinter 로 창을 열 수 있는가. 환경이 창을 못 열면 시험이 같이 죽지 않게 따로 한 번 열어 본다."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        p = subprocess.run([sys.executable, "-c", "import tkinter; r = tkinter.Tk(); r.destroy()"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


TK_OK = _tk_usable()
COLOR_OPTIONS = ("bg", "fg", "activebackground", "activeforeground", "disabledforeground", "highlightbackground",
                 "highlightcolor", "selectbackground", "selectforeground", "troughcolor", "insertbackground")


def all_widgets(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(all_widgets(child))
    return out


@unittest.skipUnless(TK_OK, "DISPLAY 가 없거나 tkinter 로 창을 열 수 없어 실제 창 시험은 건너뜀")
class TestRealWindow(Base):
    def setUp(self):
        super().setUp()
        import tkinter
        self.tk = tkinter
        self.clock = Clock()
        self.view = confirm.TkView(tkinter, clock=self.clock)
        self.addCleanup(self.view.close)

    def open(self, **over):
        self.session = confirm.ConfirmSession(parse(**over), clipboard=self.view.set_clipboard)
        self.view.open(self.session)
        self.w = self.view.widgets
        return self.session

    def wake(self, seconds=3.0):
        self.clock.advance(seconds)
        self.view.pump()

    def test_the_text_is_shown_exactly_and_cannot_be_edited(self):
        self.open()
        text = self.w["text"]
        self.assertEqual(text.get("1.0", "end-1c"), TEXT)
        self.assertEqual(str(text.cget("state")), "disabled")
        text.insert("end", "끼워 넣기")
        text.delete("1.0", "2.0")
        self.assertEqual(text.get("1.0", "end-1c"), TEXT)

    def test_tokens_are_highlighted_in_lime(self):
        self.open()
        text = self.w["text"]
        ranges = text.tag_ranges("token")
        shown = [text.get(str(a), str(b)) for a, b in zip(ranges[0::2], ranges[1::2])]
        self.assertEqual(shown, ["PH_K7Q2", "PH_M3X9"])
        self.assertEqual(text.tag_cget("token", "background").lower(), confirm.PALETTE["lime"].lower())

    def test_hidden_characters_are_visible_in_the_widget(self):
        self.open(text="가\u200b나\u202e다 PH_K7Q2\r\n")
        text = self.w["text"]
        shown = text.get("1.0", "end-1c")
        self.assertEqual(shown, "가[U+200B]나[U+202E]다 PH_K7Q2[U+000D]\n")
        ranges = text.tag_ranges("hidden")
        self.assertEqual([text.get(str(a), str(b)) for a, b in zip(ranges[0::2], ranges[1::2])],
                         ["[U+200B]", "[U+202E]", "[U+000D]"])

    def test_the_direction_is_the_big_title_on_top(self):
        self.open()
        self.assertEqual(self.w["title"]["text"], "바깥으로 보내기")
        self.assertGreater(self.w["title"].winfo_reqheight(), self.w["info"].winfo_reqheight())
        self.assertEqual(self.w["title"].master.grid_info()["row"], 0)             # 맨 위 구역
        self.view.close()
        self.view = confirm.TkView(self.tk, clock=self.clock)
        self.open(direction="dispatch", kind="plan")
        self.assertEqual(self.w["title"]["text"], "안쪽으로 넘기기")
        self.assertEqual(self.w["send"]["text"], "넘기기 (2)")

    def test_the_lines_of_the_window(self):
        self.open(attachments=["a.html"], effort_env_override=True, month={"pct": 12, "estimated": True})
        self.assertEqual(self.w["check"]["text"], "DIODE V>Vth 통과")
        self.assertEqual(self.w["files"]["text"], "a.html")
        self.assertIn("이번 달 ~12%", self.w["route"]["text"])
        labels = [wd["text"] for wd in all_widgets(self.view.root) if wd.winfo_class() == "Label"]
        for want in ("보내면 되돌릴 수 없습니다", "이 내용이 감사 기록에 남습니다"):
            self.assertIn(want, labels)
        self.assertTrue(any("CLAUDE_CODE_EFFORT_LEVEL" in t for t in labels))

    def test_send_wakes_after_two_seconds_and_the_label_counts_down(self):
        s = self.open()
        self.assertEqual(str(self.w["send"]["state"]), "disabled")
        self.assertEqual(self.w["send"]["text"], "보내기 (2)")
        self.w["send"].invoke()                                                   # 꺼진 단추를 눌러도 아무 일이 없다
        self.assertIsNone(s.decision)
        self.wake(1.0)
        self.assertEqual(self.w["send"]["text"], "보내기 (1)")
        self.assertEqual(str(self.w["send"]["state"]), "disabled")
        self.wake(1.0)
        self.assertEqual(str(self.w["send"]["state"]), "normal")
        self.assertEqual(self.w["send"]["text"], "보내기")
        self.assertEqual(self.w["time"]["text"], "남은 시간 09:58")

    def test_the_buttons_decide(self):
        for key, want in (("send", "send"), ("edit", "edit"), ("discard", "discard")):
            self.view = confirm.TkView(self.tk, clock=self.clock)
            self.addCleanup(self.view.close)
            s = self.open()
            self.wake()
            self.w[key].invoke()
            self.view.pump()
            self.assertEqual(s.decision, want)
            self.view.close()

    def test_edit_and_discard_are_on_from_the_start(self):
        self.open()
        self.assertEqual(str(self.w["edit"]["state"]), "normal")
        self.assertEqual(str(self.w["discard"]["state"]), "normal")

    def test_the_default_focus_is_discard(self):
        self.open()
        self.view.root.update()
        self.assertEqual(str(self.view.root.tk.call("focus", "-lastfor", ".")), str(self.w["discard"]))

    def test_enter_never_sends(self):
        s = self.open()
        self.wake()
        self.assertEqual(str(self.w["send"]["state"]), "normal")
        root = self.view.root
        for target in (self.w["send"], self.w["edit"], self.w["discard"], root, self.w["text"]):
            target.focus_force()
            root.update()
            for sequence in ("<Return>", "<KP_Enter>"):
                target.event_generate(sequence)
                root.update()
        self.assertIsNone(s.decision)

    def test_escape_and_closing_discard(self):
        s = self.open()
        root = self.view.root
        root.focus_force()
        root.update()
        root.event_generate("<Escape>")
        root.update()
        self.assertEqual(s.decision, "discard")
        self.view.close()
        self.view = confirm.TkView(self.tk, clock=self.clock)
        s = self.open()
        self.view.root.tk.call(self.view.root.protocol("WM_DELETE_WINDOW"))      # 창 닫기 (X)
        self.assertEqual(s.decision, "discard")

    def test_time_runs_out(self):
        s = self.open(timeout_s=30)
        self.wake(31.0)
        self.assertEqual(s.decision, "timeout")

    def test_failed_checks_leave_send_off(self):
        s = self.open(checks=HIT)
        self.wake(100.0)
        self.assertEqual(str(self.w["send"]["state"]), "disabled")
        self.w["send"].invoke()
        self.assertIsNone(s.decision)
        self.assertEqual(self.w["check"]["text"], "DIODE V<Vth 막힘 · D2 x2 @context[1], ask")
        self.assertIn(" V<Vth ", [wd["text"] for wd in all_widgets(self.view.root) if wd.winfo_class() == "Label"])
        self.assertIn("검사에 걸린", self.w["message"]["text"])

    def test_clipboard_copy_comes_after_send_and_puts_the_exact_text_on_the_clipboard(self):
        s = self.open(transport="clipboard", text="가상 글 PH_K7Q2\r\n둘째 줄\n")
        self.wake()
        self.assertEqual(str(self.w["copy"]["state"]), "disabled")
        self.w["send"].invoke()
        self.view.pump()
        self.assertIsNone(s.decision)
        self.assertEqual(str(self.w["copy"]["state"]), "normal")
        self.assertEqual(str(self.w["send"]["state"]), "disabled")
        self.w["copy"].invoke()
        self.assertEqual(s.decision, "send")
        self.assertEqual(self.view.root.clipboard_get().replace("\r\n", "\n"), "가상 글 PH_K7Q2\n둘째 줄\n")

    def test_no_copy_button_on_the_room_path_or_for_dispatch(self):
        self.open()
        self.assertIsNone(self.w["copy"])
        self.view.close()
        self.view = confirm.TkView(self.tk, clock=self.clock)
        self.open(direction="dispatch", kind="plan", transport="clipboard")
        self.assertIsNone(self.w["copy"])

    def test_create_view_makes_the_tk_screen(self):
        self.assertIsInstance(confirm.create_view(), confirm.TkView)

    def test_a_small_screen_still_shows_the_buttons(self):
        self.open()
        before = int(self.w["text"].cget("height"))
        self.view._fit_height(500)
        self.assertLessEqual(self.view.root.winfo_reqheight(), 500)
        self.assertLess(int(self.w["text"].cget("height")), before)
        self.assertGreaterEqual(int(self.w["text"].cget("height")), 4)
        self.assertTrue(self.w["send"].winfo_ismapped())
        shrunk = int(self.w["text"].cget("height"))
        self.view._fit_height(5000)                                              # 넉넉하면 더 줄이지 않는다
        self.assertEqual(int(self.w["text"].cget("height")), shrunk)

    def test_long_lines_wrap_instead_of_pushing_the_window_sideways(self):
        self.open(attachments=["f" * 120] * 5, model="m" * 80, checks={"ok": False, "hits": [
            {"check": "D2", "count": 9, "where": ["w" * 64] * 6}]})
        self.assertLess(self.view.root.winfo_reqwidth(), self.w["text"].winfo_reqwidth() + 120)

    def test_a_realistic_busy_window_fits_the_screen(self):
        self.open(attachments=["draft-screen-%d.html" % n for n in range(5)], model="model-name-with-a-long-label-x",
                  effort_env_override=True, direction="dispatch", kind="plan", text="가" * 600)
        root = self.view.root
        self.assertLessEqual(root.winfo_reqheight(), root.winfo_screenheight() - 120)
        for key in ("send", "edit", "discard", "time"):
            self.assertTrue(self.w[key].winfo_ismapped(), key)

    def test_every_color_is_navy_lime_or_gray(self):
        self.open(checks=HIT, effort_env_override=True, text="가\u200b PH_K7Q2")
        self.wake()
        seen = 0
        for widget in all_widgets(self.view.root):
            for option in COLOR_OPTIONS:
                try:
                    value = widget.cget(option)
                except self.tk.TclError:
                    continue
                if not str(value):
                    continue
                r, g, b = (v >> 8 for v in widget.winfo_rgb(str(value)))
                self.assertTrue(color_ok(r, g, b), "%s %s=%s" % (widget, option, value))
                seen += 1
        text = self.w["text"]
        for tag in ("token", "hidden"):
            for option in ("background", "foreground"):
                value = text.tag_cget(tag, option)
                r, g, b = (v >> 8 for v in text.winfo_rgb(value))
                self.assertTrue(color_ok(r, g, b), "%s %s=%s" % (tag, option, value))
        self.assertGreater(seen, 50)

    def test_run_ends_when_the_time_is_up_and_the_window_is_gone(self):
        view = confirm.TkView(self.tk)                              # 진짜 시계
        s = confirm.ConfirmSession(parse(timeout_s=1), clipboard=view.set_clipboard)
        view.run(s)
        self.assertEqual(s.decision, "timeout")
        self.assertIsNone(view.root)

    def test_main_confirm_with_a_real_window(self):
        path = self.write(raw(timeout_s=1))
        self.assertEqual(confirm.main_confirm(path), (3, json.dumps({"decision": "timeout", "sha256": sha(TEXT)})))

    def test_an_unreachable_display_is_e07(self):
        path = self.write(raw())
        with mock.patch.dict(os.environ, {"DISPLAY": ":987"}):
            self.assertEqual(confirm.main_confirm(path), (1, '{"decision": "error", "code": "E-07"}'))


if __name__ == "__main__":
    unittest.main()
