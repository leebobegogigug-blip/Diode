# -*- coding: utf-8 -*-
"""말 봉인 창 (diodelib.speak) - 봉인 · 복사 조건 · 되돌리기 · 닫기 · 시간 · 창을 못 띄움 (E-07) · 건너뛰는 길이 없음 ·
실제 tk 창 (DISPLAY 가 있을 때만). 화면은 가짜 백엔드로 바꿔 끼운다 (시험 안에만 있다). 모든 자료는 지어낸 것이다."""
import ast
import builtins
import colorsys
import contextlib
import copy
import inspect
import io
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import confirm, scan, speak  # noqa: E402
from diodelib.textnorm import dict_key  # noqa: E402

SPEAK_PY = os.path.join(ROOT, "diodelib", "speak.py")
WORDS = ["KITWORDALPHA", "가람소재", "BX-7 라인"]
TOKEN = re.compile(scan.TOKEN_RE.pattern)


def has_word(text):
    return any(dict_key(w) in dict_key(text) for w in WORDS)


class Clock(object):
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeClip(object):
    def __init__(self):
        self.text = None
        self.calls = []
        self.fail_put = self.fail_get = False
        self.garble = False
        self.crlf = False

    def put(self, text):
        self.calls.append(text)
        if self.fail_put:
            raise OSError("x")
        self.text = text

    def get(self):
        if self.fail_get:
            raise OSError("x")
        t = self.text
        if self.garble:
            return t + "x"
        return t.replace("\n", "\r\n") if self.crlf else t


class FakeView(object):
    """화면 백엔드 흉내 (시험 안에만 둔다). 대본: ("input", 글) · ("seal",) · ("copy",) · ("answer", 글) · ("unseal",) ·
    ("close",) · ("raise", 예외)"""

    def __init__(self, script=(), finish_open=False):
        self.script = list(script)
        self.ran = False
        self.clip = FakeClip()
        self.finish_open = finish_open

    def clip_put(self, text):
        self.clip.put(text)

    def clip_get(self):
        return self.clip.get()

    def run(self, session):
        self.ran = True
        for step in self.script:
            op = step[0]
            if op == "input":
                session.set_input(step[1])
            elif op == "seal":
                session.seal()
            elif op == "copy":
                session.copy()
            elif op == "answer":
                session.set_answer(step[1])
            elif op == "unseal":
                session.unseal()
            elif op == "close":
                while not session.request_close():
                    pass
            elif op == "raise":
                raise step[1]


def write_dictionary(home, words=WORDS):
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "dictionary.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "words": words}, f, ensure_ascii=False)


def listing(folder):
    out = []
    for base, dirs, files in os.walk(folder):
        for n in dirs + files:
            p = os.path.join(base, n)
            out.append((p, os.path.getsize(p) if os.path.isfile(p) else -1))
    return sorted(out)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-speak-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "data")
        write_dictionary(self.home)
        self.clock = Clock()
        self.clip = FakeClip()

    def session(self, **kw):
        kw.setdefault("clipboard_put", self.clip.put)
        kw.setdefault("clipboard_get", self.clip.get)
        kw.setdefault("clock", self.clock)
        return speak.SpeakSession(self.home, **kw)

    def sealed(self, text, **kw):
        s = self.session(**kw)
        s.set_input(text)
        return s, s.seal()


# ─────────────────────────────────────────────────────────────── 열기

class TestOpen(Base):
    def test_ready_and_empty(self):
        s = self.session()
        self.assertEqual((s.state, s.tokens, s.closed, s.code), ("ready", 0, False, ""))
        self.assertEqual(repr(s), "<SpeakSession ready 토큰 0개>")

    def test_unavailable_cases_refuse_everything(self):
        def cfg(text):
            with open(os.path.join(self.home, "config.json"), "w") as f:
                f.write(text)
        cases = [("words_empty", lambda: os.remove(os.path.join(self.home, "dictionary.json"))),
                 ("words_empty", lambda: write_dictionary(self.home, [])),
                 ("broken", lambda: open(os.path.join(self.home, "dictionary.json"), "w").write("{")),
                 ("newer", lambda: open(os.path.join(self.home, "dictionary.json"), "w").write('{"format": 2, "words": ["a"]}')),
                 ("broken", lambda: write_dictionary(self.home, ["a"])),
                 ("broken", lambda: cfg("{")),
                 ("broken", lambda: cfg('{"format": 2}'))]
        for code, setup in cases:
            write_dictionary(self.home)
            if os.path.exists(os.path.join(self.home, "config.json")):
                os.remove(os.path.join(self.home, "config.json"))
            setup()
            with self.subTest(code=code):
                s = self.session()
                self.assertEqual((s.state, s.code), ("unavailable", code))
                r = s.seal()
                self.assertEqual((r.text, r.copyable, r.reason), (None, False, "unavailable"))
                u = s.unseal()
                self.assertEqual((u.ok, u.reason, u.text), (False, "unavailable", None))
                self.assertFalse(s.copy())
                self.assertEqual(self.clip.calls, [])
                self.assertIn("E-20", s.snapshot().message)

    def test_missing_data_folder_is_unavailable(self):
        shutil.rmtree(self.home)
        self.assertEqual(self.session().code, "words_empty")

    def test_opening_writes_nothing(self):
        before = listing(self.tmp)
        self.session()
        self.assertEqual(listing(self.tmp), before)


# ─────────────────────────────────────────────────────────────── 봉인

class TestSeal(Base):
    def test_variants_become_the_same_token(self):
        s = self.session()
        tokens = set()
        for variant in ("KITWORDALPHA", "kitwordalpha", "KitWordAlpha", "KIT-WORD ALPHA", "K I T W O R D A L P H A",
                        "\uff2b\uff29\uff34\uff37\uff2f\uff32\uff24\uff21\uff2c\uff30\uff28\uff21", "KIT_WORD.ALPHA"):
            s.set_input("앞 %s 뒤" % variant)
            r = s.seal()
            m = re.fullmatch(r"앞 (PH_\w{4}) 뒤", r.text)
            self.assertIsNotNone(m, variant)
            tokens.add(m.group(1))
            self.assertTrue(r.ok and r.copyable, (variant, r.line))
        self.assertEqual((len(tokens), s.tokens), (1, 1))

    def test_korean_word_with_a_particle_and_a_word_with_digits(self):
        s, r = self.sealed("가람소재의 bx7라인 BX 7 라인")
        self.assertTrue(r.copyable, r.line)
        self.assertEqual(len(TOKEN.findall(r.text)), 3)
        self.assertEqual(s.tokens, 2)                      # 가람소재 하나 · BX-7 라인 하나 (변형 둘은 같은 토큰)
        self.assertFalse(has_word(r.text))

    def test_same_word_same_token_across_seals_and_words_differ(self):
        s, a = self.sealed("KITWORDALPHA 가람소재")
        s.set_input("가람소재 KITWORDALPHA")
        b = s.seal()
        ta, tb = TOKEN.findall(a.text), TOKEN.findall(b.text)
        self.assertEqual(ta, tb[::-1])
        self.assertNotEqual(ta[0], ta[1])

    def test_a_text_without_words_passes_unchanged(self):
        s, r = self.sealed("일반적인 질문 하나")
        self.assertEqual((r.text, r.copyable, s.tokens), ("일반적인 질문 하나", True, 0))
        self.assertEqual(r.line, "DIODE V>Vth 통과")

    def test_leftovers_turn_copy_off_with_numbers_only_in_the_line(self):
        s, r = self.sealed("첫 줄\n온도 350\n셋째")
        self.assertEqual((r.copyable, r.reason, r.line), (False, "check", "DIODE V<Vth 막힘 · D4 x1 @L2"))
        for text in ("D:\\x\\y", "/home/kit/a", "http://a.example.com/x", "a@example.com", "127.0.0.1", "PH_ABCD"):
            s.set_input("가람소재 " + text)
            r = s.seal()
            self.assertFalse(r.copyable, text)
            self.assertFalse(s.copy_enabled)
            self.assertFalse(has_word(r.line + s.snapshot().message))

    def test_a_lookalike_variant_that_is_not_replaced_is_caught_by_d2(self):
        s, r = self.sealed("\u043aITWORDALPHA 질문")
        self.assertEqual((r.copyable, r.line), (False, "DIODE V<Vth 막힘 · D2 x1 @L1"))

    def test_hidden_characters_turn_copy_off(self):
        for ch in ("\u200b", "\u202e", "\ufeff"):
            s, r = self.sealed("안녕%s하세요" % ch)
            self.assertEqual((r.copyable, r.reason, r.hidden), (False, "hidden", 1), ch)
            self.assertEqual(s.hidden_lines(), [1])
            self.assertIn("보이지 않는 글자 1개", s.snapshot().message)
        s, r = self.sealed("안녕\u00a0하세요")             # NFKC 가 보통 빈칸으로 바꾼다
        self.assertTrue(r.copyable)

    def test_empty_and_limits(self):
        s, r = self.sealed("   \n")
        self.assertEqual((r.reason, r.text), ("empty", None))
        self.assertEqual(speak.MAX_INPUT_BYTES, 64 * 1024)
        self.assertEqual(speak.MAX_SEALED_BYTES, confirm.MAX_TEXT_BYTES)
        self.assertEqual(speak.MAX_ANSWER_BYTES, 256 * 1024)
        with mock.patch.object(speak, "MAX_INPUT_BYTES", 100):
            s.set_input("a" * 100)
            self.assertEqual(s.seal().reason, None)
            s.set_input("a" * 101)
            self.assertEqual(s.seal().reason, "size_in")
        s.set_input("가\ud800")
        self.assertEqual(s.seal().reason, "text")

    def test_a_sealed_text_longer_than_the_limit_is_not_copyable(self):
        write_dictionary(self.home, ["KITE", "KITWORDALPHA"])
        line = " ".join(["KITE"] * 10)
        s, r = self.sealed("\n".join([line] * 1200))
        self.assertLess(len(s._input.encode("utf-8")), speak.MAX_INPUT_BYTES)
        self.assertEqual((r.reason, r.copyable), ("size_out", False))

    def test_the_token_cap_fails_closed(self):
        with mock.patch("diodelib.seal.MAX_TOKENS", 1):
            s, r = self.sealed("KITWORDALPHA 가람소재")
        self.assertEqual((r.reason, r.text, r.copyable), ("e20", None, False))
        self.assertIn("E-20", s.snapshot().message)

    def test_not_the_default_data_folder_blocks_the_copy(self):
        s, r = self.sealed("KITWORDALPHA 질문", home_is_default=False)
        self.assertEqual((r.ok, r.copyable, r.reason), (True, False, "home"))
        self.assertIn("E-20", s.snapshot().message)
        self.assertFalse(s.copy())
        self.assertEqual(self.clip.calls, [])


# ─────────────────────────────────────────────────────────────── 복사

class TestCopy(Base):
    def test_copy_puts_exactly_the_sealed_text_and_reads_it_back(self):
        s, r = self.sealed("가람소재 의 질문\n둘째 줄")
        self.assertTrue(s.copy_enabled)
        self.assertTrue(s.copy())
        self.assertEqual(self.clip.calls, [r.text])
        self.assertEqual((s.copies, s.snapshot().level), (1, "ok"))

    def test_an_edit_turns_copy_off_at_once_and_a_reseal_turns_it_on(self):
        s, r = self.sealed("가람소재 질문")
        s.set_input("가람소재 질문 둘")
        snap = s.snapshot()
        self.assertEqual((s.copy_enabled, snap.copy_enabled, snap.check_kind, snap.message), (False, False, "stale", speak.TEXT_STALE))
        self.assertFalse(s.copy())
        self.assertEqual(self.clip.calls, [])
        s.seal()
        self.assertTrue(s.copy_enabled)
        s.set_input("다른 글")
        s.set_input("가람소재 질문 둘")                          # 봉인한 글과 같은 글로 돌아오면 그 봉인은 맞다
        self.assertTrue(s.copy_enabled)

    def test_copy_without_a_seal_or_with_a_blocked_seal_does_nothing(self):
        s = self.session()
        self.assertFalse(s.copy())
        s.set_input("온도 350")
        s.seal()
        self.assertFalse(s.copy())
        self.assertEqual(self.clip.calls, [])

    def test_readback_failures_are_failures(self):
        for attr in ("garble", "fail_put", "fail_get"):
            clip = FakeClip()
            setattr(clip, attr, True)
            s = speak.SpeakSession(self.home, clipboard_put=clip.put, clipboard_get=clip.get, clock=self.clock)
            s.set_input("가람소재 질문")
            s.seal()
            self.assertFalse(s.copy(), attr)
            self.assertEqual((s.copies, s.snapshot().message, s.snapshot().level), (0, speak.TEXT_COPY_FAILED, "alert"))
        s = speak.SpeakSession(self.home, clock=self.clock)
        s.set_input("질문")
        s.seal()
        self.assertFalse(s.copy())                            # 클립보드 접근이 없다

    def test_a_windows_style_readback_is_accepted(self):
        self.clip.crlf = True
        s, r = self.sealed("가람소재\n질문")
        self.assertTrue(s.copy())


# ─────────────────────────────────────────────────────────────── 되돌리기

class TestUnseal(Base):
    def setUp(self):
        super().setUp()
        self.s, self.r = self.sealed("KITWORDALPHA 가람소재 질문")
        self.t1, self.t2 = TOKEN.findall(self.r.text)

    def answer(self, text):
        self.s.set_answer(text)
        return self.s.unseal()

    def test_known_tokens_are_restored(self):
        u = self.answer("# 답\n- %s를 먼저\n- %s 도\n" % (self.t1, self.t2))
        self.assertTrue(u.ok)
        self.assertEqual(u.text, "# 답\n- KITWORDALPHA를 먼저\n- 가람소재 도\n")
        self.assertEqual(u.issues, {"U1": [], "U2": 0, "U3": [], "U4": False})
        self.assertNotIn("KITWORD", repr(u) + str(u))

    def test_unknown_and_broken_tokens_are_only_line_numbers(self):
        u = self.answer("첫 줄 %s\nPH_ZZZZ 는 모른다\nph_%s 는 깨졌다\n" % (self.t1, self.t1[3:].lower()))
        self.assertTrue(u.ok)
        self.assertEqual(u.issues["U1"], [2, 3])
        self.assertIn("L2, L3", u.summary)
        self.assertIn("PH_ZZZZ", u.text)                      # 모르는 토큰은 되돌리지 않는다
        self.assertFalse(has_word(u.summary))

    def test_a_dictionary_word_in_the_answer_alarms_and_makes_no_text(self):
        for ans in ("이건 가람소재 의 것", "KIT-WORD alpha", "bx7 라인", "%s 그리고 \uff2b\uff29\uff34WORDALPHA" % self.t1):
            u = self.answer(ans)
            self.assertEqual((u.ok, u.stop, u.text, u.reason, u.level), (False, True, None, "u2", "alert"), ans)
            self.assertGreater(u.issues["U2"], 0)
            self.assertFalse(has_word(u.summary + self.s.snapshot().message))

    def test_urls_are_removed_and_the_lines_shown(self):
        u = self.answer("참고 https://docs.example.com/a\n끝")
        self.assertTrue(u.ok)
        self.assertEqual((u.issues["U3"], u.text), ([1], "참고 <주소 지움>\n끝"))
        self.assertIn("L1", u.summary)

    def test_empty_and_limits(self):
        self.assertEqual(self.answer("  ").reason, "empty")
        with mock.patch.object(speak, "MAX_ANSWER_BYTES", 50):
            self.assertTrue(self.answer("a" * 50).ok)
            u = self.answer("a" * 51)
            self.assertEqual((u.ok, u.reason), (False, "size"))
        self.assertEqual(self.answer("가\ud800").reason, "text")

    def test_an_answer_over_64_kib_but_under_the_limit_is_restored(self):
        body = "".join("%s 줄 %d번째\n" % (self.t1, 0) for _ in range(5000))
        self.assertGreater(len(body.encode("utf-8")), 64 * 1024)
        u = self.answer(body)
        self.assertTrue(u.ok)
        self.assertEqual(u.text.count("KITWORDALPHA"), 5000)

    def test_restored_text_never_reaches_the_clipboard_files_or_output(self):
        self.assertTrue(self.s.copy())
        before = listing(self.tmp)
        real_open = builtins.open

        def guarded(file, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                raise AssertionError("파일에 씀")
            return real_open(file, mode, *a, **k)
        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with mock.patch.object(builtins, "open", guarded), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                u = self.answer("%s 와 %s" % (self.t1, self.t2))
                self.s.snapshot()
        finally:
            os.chdir(cwd)
        self.assertTrue(u.ok)
        self.assertIn("KITWORDALPHA", u.text)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertEqual(listing(self.tmp), before)
        self.assertEqual(self.clip.calls, [self.r.text])      # 클립보드에 간 것은 봉인한 글 하나뿐
        self.assertFalse(any(has_word(c) for c in self.clip.calls))


# ─────────────────────────────────────────────────────────────── 메모리에만 · 닫기 · 시간

class TestMemoryAndClose(Base):
    def test_the_table_is_not_serializable_and_nothing_hits_the_disk(self):
        before = listing(self.tmp)
        s, r = self.sealed("KITWORDALPHA 질문")
        s.copy()
        s.set_answer(TOKEN.findall(r.text)[0])
        s.unseal()
        for f in (pickle.dumps, copy.copy, copy.deepcopy, json.dumps):
            with self.assertRaises(TypeError):
                f(s)
        self.assertEqual(listing(self.tmp), before)

    def test_every_visible_string_is_free_of_words_and_paths(self):
        seen = []
        s = self.session()
        for text in ("KITWORDALPHA 가람소재 질문", "KITWORDALPHA 온도 350 D:\\x", "안녕\u200b", "\u043aITWORDALPHA"):
            s.set_input(text)
            r = s.seal()
            seen += [r.line, s.snapshot().message, s.snapshot().check_line]
            s.copy()
            seen.append(s.snapshot().message)
        for ans in ("가람소재", "PH_ZZZZ https://a.example.com", ""):
            s.set_answer(ans)
            u = s.unseal()
            seen += [u.summary, s.snapshot().message]
        s.request_close()
        seen.append(s.snapshot().message)
        s.set_input("")
        for text in seen:
            self.assertFalse(has_word(text), text)
            self.assertNotIn(self.tmp, text)
        tree = ast.parse(open(SPEAK_PY, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertFalse(has_word(node.value), node.value)

    def test_clear_keeps_the_table(self):
        s, r = self.sealed("KITWORDALPHA 질문")
        tok = TOKEN.findall(r.text)[0]
        s.set_answer("답")
        s.clear()
        snap = s.snapshot()
        self.assertEqual((s.sealed, snap.clear_enabled, snap.seal_enabled, snap.unseal_enabled), (None, False, False, False))
        s.set_input("KITWORDALPHA")
        self.assertEqual(s.seal().text, tok)

    def test_close_asks_once_when_there_are_tokens_then_wipes(self):
        s, r = self.sealed("KITWORDALPHA 질문")
        self.assertFalse(s.request_close())
        self.assertEqual((s.snapshot().message, s.snapshot().level, s.closed), (speak.TEXT_CLOSE_ASK, "ask", False))
        s.set_input("KITWORDALPHA 질문 둘")                       # 손대면 다시 묻는다
        self.assertFalse(s.request_close())
        self.assertTrue(s.request_close())
        self.assertEqual((s.state, s.tokens, s.sealed), ("closed", 0, None))
        s.set_input("x")
        self.assertEqual(s.seal().reason, "unavailable")
        self.assertTrue(s.request_close())

    def test_close_without_tokens_is_at_once_and_keys(self):
        s = self.session()
        self.assertTrue(s.key("Escape"))
        s = self.session()
        s.set_input("KITWORDALPHA")
        s.seal()
        self.assertTrue(s.copy_enabled)
        for name in ("Return", "KP_Enter", "space"):
            self.assertFalse(s.key(name))
        self.assertEqual((s.copies, self.clip.calls, s.closed), (0, [], False))
        self.assertFalse(s.key("Escape"))                        # 토큰이 있어 한 번 묻는다
        self.assertTrue(s.key("Escape"))

    def test_idle_expiry_wipes_the_table(self):
        s, r = self.sealed("KITWORDALPHA 질문")
        self.clock.advance(speak.IDLE_LIMIT_S - 1)
        s.tick()
        self.assertEqual((s.state, s.snapshot().remaining_s), ("ready", 1))
        self.clock.advance(1)
        s.tick()
        self.assertEqual((s.state, s.expired, s.closed, s.tokens), ("expired", True, True, 0))
        self.assertEqual(s.seal().reason, "unavailable")

    def test_touching_restarts_the_time(self):
        s = self.session()
        s.start()
        self.clock.advance(1700)
        s.touch()
        self.clock.advance(1700)
        s.tick()
        self.assertEqual(s.state, "ready")
        s.set_input("글")
        self.clock.advance(1799)
        s.tick()
        self.assertEqual(s.state, "ready")
        self.clock.advance(1)
        s.tick()
        self.assertEqual(s.state, "expired")


# ─────────────────────────────────────────────────────────────── diode.py speak 의 몸통

E07 = '{"closed": false, "error": "E-07"}'
E20 = '{"closed": false, "error": "E-20"}'


def env_with(**display):
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env.update(display)
    return mock.patch.dict(os.environ, env, clear=True)


class TestMain(Base):
    def run_main(self, view, **kw):
        with mock.patch.object(speak, "create_view", return_value=view):
            return speak.main_speak(self.home, **kw)

    def test_a_closed_window_reports_counts_only(self):
        view = FakeView([("input", "KITWORDALPHA 질문"), ("seal",), ("copy",), ("answer", "답"), ("unseal",), ("close",)])
        code, line = self.run_main(view)
        self.assertEqual((code, line), (0, '{"closed": true, "expired": false, "seals": 1, "copies": 1, "unseals": 1}'))
        self.assertFalse(has_word(line))

    def test_unavailable_does_not_open_the_window(self):
        write_dictionary(self.home, [])
        view = FakeView()
        self.assertEqual(self.run_main(view), (3, '{"closed": false, "error": "E-20", "code": "words_empty"}'))
        self.assertFalse(view.ran)

    def test_not_the_default_folder_blocks_copying_in_the_window(self):
        view = FakeView([("input", "KITWORDALPHA 질문"), ("seal",), ("copy",), ("close",)])
        code, line = self.run_main(view, home_is_default=False)
        self.assertEqual((code, json.loads(line)["copies"], view.clip.calls), (0, 0, []))

    def test_errors_never_end_as_closed(self):
        self.assertEqual(self.run_main(FakeView([("raise", RuntimeError("x"))])), (1, E20))
        self.assertEqual(self.run_main(FakeView([("input", "a")])), (1, E20))     # 닫기 전에 끝난 화면

    def test_no_display_is_e07_and_tkinter_is_not_loaded(self):
        before = listing(self.tmp)
        with env_with(), mock.patch.object(speak, "_is_windows", return_value=False), mock.patch.dict(sys.modules):
            for name in [n for n in sys.modules if n.split(".")[0] in ("tkinter", "_tkinter")]:
                del sys.modules[name]
            self.assertEqual(speak.main_speak(self.home), (1, E07))
            self.assertFalse([n for n in sys.modules if n.split(".")[0] in ("tkinter", "_tkinter")])
        with env_with(DISPLAY=":0"), mock.patch.object(speak, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertEqual(speak.main_speak(self.home), (1, E07))
            self.assertFalse(speak.can_open())
        self.assertEqual(listing(self.tmp), before)

    def test_a_tcl_error_is_e07_and_another_error_is_e20(self):
        for error, want in ((None, E07), (RuntimeError, E20)):
            tk = types.ModuleType("tkinter")

            class TclError(Exception):
                pass

            def Tk(*a, _e=error or TclError, **k):
                raise _e("x")
            tk.TclError, tk.Tk, tk.font = TclError, Tk, types.ModuleType("tkinter.font")
            with env_with(DISPLAY=":0"), mock.patch.object(speak, "_is_windows", return_value=False), \
                    mock.patch.dict(sys.modules, {"tkinter": tk, "tkinter.font": tk.font}):
                self.assertEqual(speak.main_speak(self.home), (1, want))


class TestDetached(Base):
    def test_every_refusal_is_honest_and_launches_nothing(self):
        with mock.patch.object(speak, "launch_detached") as launch:
            with mock.patch.object(speak, "can_open", return_value=False):
                self.assertEqual(speak.open_detached(self.home, "p", "d.py"), (1, "", speak.TEXT_NO_WINDOW))
            write_dictionary(self.home, [])
            with mock.patch.object(speak, "can_open", return_value=True):
                self.assertEqual(speak.open_detached(self.home, "p", "d.py"), (3, "", speak.TEXT_NOT_READY["words_empty"]))
            launch.assert_not_called()

    def test_a_failed_launch_is_reported_and_a_good_one_says_nothing_of_words(self):
        with mock.patch.object(speak, "can_open", return_value=True):
            with mock.patch.object(speak, "launch_detached", side_effect=OSError("x")):
                self.assertEqual(speak.open_detached(self.home, "p", "d.py"), (1, "", speak.TEXT_LAUNCH_FAILED))
            with mock.patch.object(speak, "launch_detached", return_value=7) as launch:
                code, out, err = speak.open_detached(self.home, "p", "d.py")
            launch.assert_called_once_with("p", "d.py")
        self.assertEqual((code, out, err), (0, speak.TEXT_OPENED, ""))
        for text in [speak.TEXT_NO_WINDOW, speak.TEXT_OPENED, speak.TEXT_LAUNCH_FAILED] + list(speak.TEXT_NOT_READY.values()):
            self.assertFalse(has_word(text) or self.tmp in text)

    def popen(self, windows):
        with mock.patch.object(speak, "_is_windows", return_value=windows), mock.patch.object(subprocess, "Popen") as popen:
            popen.return_value.pid = 4242
            return speak.launch_detached("pythonX", "/x/diode.py"), popen

    def test_the_launch_command_is_python_diode_speak_and_nothing_else(self):
        for windows in (False, True):
            pid, popen = self.popen(windows)
            kw = popen.call_args[1]
            self.assertEqual((pid, popen.call_args[0]), (4242, (["pythonX", "/x/diode.py", "speak"],)))
            self.assertEqual((kw["stdin"], kw["stdout"], kw["stderr"]), (subprocess.DEVNULL,) * 3)
            for bad in ("shell", "env", "cwd"):
                self.assertNotIn(bad, kw)
            if windows:
                self.assertEqual(kw["creationflags"], 0x8 | 0x200)
            else:
                self.assertIs(kw["start_new_session"], True)

    def test_the_caller_is_not_made_to_wait(self):
        child = os.path.join(self.tmp, "child.py")
        with open(child, "w") as f:
            f.write("import os, sys, time\nhere = os.path.dirname(os.path.abspath(__file__))\nend = time.time() + 40\n"
                    "while not os.path.exists(os.path.join(here, 'go')) and time.time() < end:\n    time.sleep(0.05)\n"
                    "open(os.path.join(here, 'args.txt'), 'w').write(' '.join(sys.argv[1:]))\n")
        go, args = os.path.join(self.tmp, "go"), os.path.join(self.tmp, "args.txt")
        self.addCleanup(lambda: open(go, "w").close())
        speak.launch_detached(sys.executable, child)
        self.assertFalse(os.path.exists(args))
        open(go, "w").close()
        end = time.time() + 30
        while not os.path.exists(args) and time.time() < end:
            time.sleep(0.05)
        time.sleep(0.2)
        with open(args) as f:
            self.assertEqual(f.read(), "speak")


# ─────────────────────────────────────────────────────────────── diode.py · 명령 파일 · 문서

class TestCli(Base):
    def cli(self, *argv, env=None):
        sys.path.insert(0, ROOT)
        import diode
        out, err = io.StringIO(), io.StringIO()
        env = dict({"HOME": self.tmp, "USERPROFILE": self.tmp, "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local")}, **(env or {}))
        with mock.patch.dict(os.environ, env):
            if "DIODE_HOME" not in (env or {}):
                os.environ.pop("DIODE_HOME", None)
            code = diode.main(list(argv), out=out, err=err)
        return code, out.getvalue(), err.getvalue(), diode

    def default_home(self):
        code, _, _, diode = self.cli("version")
        with mock.patch.dict(os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp,
                                          "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local")}):
            os.environ.pop("DIODE_HOME", None)
            return diode.data_dir()[0]

    def test_detached_opens_the_window_and_tells_no_words(self):
        write_dictionary(self.default_home())
        with mock.patch.object(speak, "can_open", return_value=True), mock.patch.object(speak, "launch_detached", return_value=1) as launch:
            code, out, err, _ = self.cli("speak", "--detached")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(os.path.basename(launch.call_args[0][1]), "diode.py")
        self.assertIn("말 봉인 창을 열었습니다", out)

    def test_detached_refusals_are_exit_codes_with_stderr(self):
        write_dictionary(self.default_home())
        with mock.patch.object(speak, "can_open", return_value=False), mock.patch.object(speak, "launch_detached") as launch:
            code, out, err, _ = self.cli("speak", "--detached")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("E-07", err)
        launch.assert_not_called()
        write_dictionary(self.default_home(), [])
        with mock.patch.object(speak, "can_open", return_value=True), mock.patch.object(speak, "launch_detached") as launch:
            code, out, err, _ = self.cli("speak", "--detached")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("E-20", err)

    def test_foreground_passes_the_home_and_whether_it_is_the_default(self):
        with mock.patch.object(speak, "main_speak", return_value=(0, '{"closed": true}')) as m:
            code, out, err, _ = self.cli("speak")
            self.assertEqual((code, out.strip()), (0, '{"closed": true}'))
            self.assertEqual((os.path.basename(m.call_args[0][0]), m.call_args[0][1]), ("diode", True))
            self.cli("speak", env={"DIODE_HOME": self.tmp})
            self.assertEqual(m.call_args[0][1], False)

    def test_bad_arguments_and_failures(self):
        for argv in (("speak", "x"), ("speak", "--bogus"), ("speak", "--detached", "x")):
            code, out, err, _ = self.cli(*argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertIn("사용법 오류", err)
        with mock.patch.object(speak, "main_speak", side_effect=RuntimeError("x")):
            code, out, err, _ = self.cli("speak")
        self.assertEqual((code, out, err), (1, "", "diode.py speak: 실패 (E-20)\n"))

    def test_help_lists_speak(self):
        self.assertIn("speak", self.cli("help")[1])

    @unittest.skipIf(os.name == "nt", "Windows 는 화면이 있다고 본다")
    def test_a_real_process_without_a_display_is_e07_and_creates_nothing(self):
        env = dict(os.environ, HOME=self.tmp, USERPROFILE=self.tmp, PYTHONIOENCODING="utf-8")
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "DIODE_HOME"):
            env.pop(k, None)
        before = listing(self.tmp)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py"), "speak"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env, timeout=60)
        self.assertEqual((p.returncode, json.loads(p.stdout.decode("utf-8"))), (1, {"closed": False, "error": "E-07"}))
        self.assertEqual(listing(self.tmp), before)


class TestFiles(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as f:
            return f.read()

    def test_the_slash_command_only_opens_the_window(self):
        text = self.read("commands/speak.md")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        front = dict(ln.split(": ", 1) for ln in m.group(1).splitlines())
        self.assertEqual(front["allowed-tools"], "Bash(python:*)")
        self.assertIn("말 봉인", front["description"])
        bangs = [ln for ln in m.group(2).splitlines() if ln.startswith("!")]
        self.assertEqual(bangs, ['!`python "${CLAUDE_PLUGIN_ROOT}/diode.py" speak --detached`'])
        self.assertIn("묻거나 받아 적지 않는다", m.group(2))
        self.assertNotIn("$ARGUMENTS", text)

    def test_docs_and_skill_carry_the_command(self):
        self.assertIn("`speak", self.read("docs/MANUAL.md"))
        self.assertIn("/diode:speak", self.read("docs/MANUAL.md"))
        self.assertIn("`diode.py speak", self.read("docs/SPEC.md"))
        self.assertIn("/diode:speak", self.read("skills/diode/SKILL.md"))
        self.assertIn("/diode:speak", self.read("INSTALL.md"))


# ─────────────────────────────────────────────────────────────── 건너뛰는 길이 없다 · 규칙 (AST)

def _source():
    with open(SPEAK_PY, "r", encoding="utf-8") as f:
        return f.read()


def _is_environ(node):
    return (isinstance(node, ast.Name) and node.id == "environ") or (isinstance(node, ast.Attribute) and node.attr == "environ")


def color_ok(r, g, b):
    if (max(r, g, b) - min(r, g, b)) / 255 < 0.10:
        return True
    hue = int(round(colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360))
    return 190 <= hue <= 230 or 75 <= hue <= 110


class TestNoWayAround(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(_source())

    def test_the_entry_points_take_no_switches(self):
        self.assertEqual(list(inspect.signature(speak.main_speak).parameters), ["home", "home_is_default"])
        self.assertEqual(list(inspect.signature(speak.create_view).parameters), [])
        self.assertEqual(list(inspect.signature(speak.launch_detached).parameters), ["python", "diode_py"])
        self.assertEqual(list(inspect.signature(speak.open_detached).parameters), ["home", "python", "diode_py"])
        self.assertEqual(list(inspect.signature(speak.SpeakSession).parameters),
                         ["home", "home_is_default", "clipboard_put", "clipboard_get", "clock"])
        self.assertEqual(list(inspect.signature(speak.TkView).parameters), ["tk_module", "clock"])

    def test_the_only_environment_read_is_the_display_check(self):
        parents = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        found = [n for n in ast.walk(self.tree) if _is_environ(n) and not isinstance(parents.get(n), ast.Attribute)]
        self.assertEqual(len(found), 2)
        for env in found:
            call = parents[env]
            self.assertIsInstance(call, ast.Call)
            self.assertEqual(getattr(call.func, "attr", None), "display_missing")
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, ("getenv", "putenv", "unsetenv"))
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                self.fail("환경 변수를 읽음")
            if isinstance(node, ast.Attribute) and node.attr in ("argv", "orig_argv"):
                self.fail("명령줄 인자를 읽음")

    def test_the_module_reads_no_file_and_prints_nothing(self):
        allowed = {"collections", "json", "os", "subprocess", "threading", "time", "tkinter"}
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module.split(".")[0])
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    self.assertNotIn(fn.id, ("open", "print", "input", "exec", "eval", "compile", "__import__"))
                if isinstance(fn, ast.Attribute):
                    self.assertNotIn(fn.attr, ("write", "writelines", "write_text", "write_bytes", "read_text", "read_bytes",
                                               "dump", "load", "import_module", "rename", "mkstemp", "makedirs"))
            if isinstance(node, ast.Attribute) and node.attr in ("stdout", "stderr", "stdin") \
                    and not (isinstance(node.value, ast.Name) and node.value.id == "subprocess"):
                self.fail("표준 입출력을 건드림")
        self.assertLessEqual(names, allowed, names)

    def test_os_is_used_for_two_things_only_and_subprocess_in_one_function(self):
        used = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os"}
        self.assertEqual(used, {"name", "environ"})
        for func in [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]:
            uses = [n for n in ast.walk(func) if isinstance(n, ast.Name) and n.id == "subprocess"]
            self.assertEqual(bool(uses), func.name == "launch_detached", func.name)

    def test_only_copy_reaches_the_clipboard_and_it_never_sees_restored_text(self):
        users = set()
        for cls in [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)]:
            for f in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                for n in ast.walk(f):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("_put", "_get"):
                        users.add((cls.name, f.name))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("clipboard_append", "clipboard_clear"):
                        users.add((cls.name, f.name))
        self.assertEqual(users, {("SpeakSession", "copy"), ("TkView", "clip_put")})
        copy_fn = [f for c in ast.walk(self.tree) if isinstance(c, ast.ClassDef) and c.name == "SpeakSession"
                   for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "copy"][0]
        names = {n.id for n in ast.walk(copy_fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(copy_fn) if isinstance(n, ast.Attribute)}
        self.assertFalse(names & {"unseal_checks", "_answer", "real_of", "reals", "binding", "_table", "unseals"}, names)

    def test_no_name_offers_a_way_around(self):
        words = re.compile(r"fake|bypass|skip|silent|quiet|headless|unattended|assume|force|auto|noconfirm|yes", re.I)
        names = set(n for n in dir(speak) if not n.startswith("__"))
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            if isinstance(node, ast.arg):
                names.add(node.arg)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
        self.assertEqual([n for n in names if words.search(n)], [])

    def test_importing_the_module_does_not_load_tkinter(self):
        code = ("import sys; sys.path.insert(0, %r); import diodelib.speak; "
                "print('|'.join(n for n in sys.modules if n.split('.')[0] in ('tkinter', '_tkinter')))" % ROOT)
        p = subprocess.run([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual((p.returncode, p.stdout.decode().strip()), (0, ""), p.stderr.decode())

    def test_python38_syntax_colors_and_symbols(self):
        ast.parse(_source(), filename=SPEAK_PY, feature_version=(3, 8))
        ast.parse(open(os.path.abspath(__file__), encoding="utf-8").read(), feature_version=(3, 8))
        src = _source()
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", src), [])
        for name, value in speak.PALETTE.items():
            self.assertTrue(color_ok(*(int(value[i:i + 2], 16) for i in (1, 3, 5))), name)
        banned = {"red", "orange", "yellow", "pink", "purple", "magenta", "brown", "crimson", "tomato", "gold", "violet"}
        keys = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn(node.value.strip().lower(), banned)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in ("c", "PALETTE"):
                sl = node.slice.value if type(node.slice).__name__ == "Index" else node.slice
                if isinstance(sl, ast.Constant):
                    keys.add(sl.value)
        self.assertTrue(keys)
        self.assertLessEqual(keys, set(speak.PALETTE))
        for chip, bg, fg in speak._CHIPS.values():
            self.assertIn(bg, speak.PALETTE)
            self.assertIn(fg, speak.PALETTE)
        for path in (SPEAK_PY, os.path.abspath(__file__)):
            for ch in open(path, encoding="utf-8").read():
                self.assertFalse(0x1F000 <= ord(ch) <= 0x1FAFF or ch in "\u2713\u26a0\u2605", "U+%04X" % ord(ch))
        extra = set(ch for ch in src if ord(ch) > 127 and not (0xAC00 <= ord(ch) <= 0xD7A3))
        self.assertLessEqual(extra, {"\u00b7", "\u203a", "\u203c"})


# ─────────────────────────────────────────────────────────────── 실제 tk 창 (DISPLAY 가 있을 때만)

def _tk_usable():
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
        self.view = speak.TkView(tkinter, clock=self.clock)
        self.addCleanup(self.view.close)
        self.s = speak.SpeakSession(self.home, clipboard_put=self.view.clip_put, clipboard_get=self.view.clip_get, clock=self.clock)
        self.view.open(self.s)
        self.w = self.view.widgets
        self.root = self.view.root

    def type_in(self, key, text):
        self.w[key].delete("1.0", "end")
        self.w[key].insert("1.0", text)
        self.root.update()

    def shown(self, key):
        return self.w[key].get("1.0", "end-1c")

    def no_clipboard(self):
        self.root.clipboard_clear()
        self.root.update()

    def clipboard(self):
        try:
            return self.root.clipboard_get()
        except self.tk.TclError:
            return None

    def test_zones_buttons_and_default_focus(self):
        self.assertEqual(self.w["title"]["text"], "말 봉인")
        chips = [wd["text"].strip() for wd in all_widgets(self.root) if wd.winfo_class() == "Label"]
        for chip in ("01 WRITE", "02 SEALED", "03 CHECK", "04 ANSWER", "05 RESTORED"):
            self.assertIn(chip, chips)
        buttons = sorted(wd["text"] for wd in all_widgets(self.root) if wd.winfo_class() == "Button")
        self.assertEqual(buttons, sorted(["봉인", "복사", "비우기", "되돌려 보기", "닫기"]))       # 되돌린 글에는 복사 단추가 없다
        self.assertEqual(str(self.root.tk.call("focus", "-lastfor", ".")), str(self.w["input"]))
        self.assertEqual(str(self.w["sealed"].cget("state")), "disabled")
        self.assertEqual(str(self.w["restored"].cget("state")), "disabled")
        self.assertEqual(str(self.w["seal"]["state"]), "disabled")

    def test_seal_copy_and_edit(self):
        self.type_in("input", "가람소재 의 KitWordAlpha 질문")
        self.assertEqual(str(self.w["seal"]["state"]), "normal")                  # 친 즉시 켜진다
        self.w["seal"].invoke()
        text = self.s.sealed.text
        self.assertEqual(self.shown("sealed"), text)
        ranges = self.w["sealed"].tag_ranges("token")
        self.assertEqual(len(ranges) // 2, 2)
        self.assertEqual(self.w["sealed"].tag_cget("token", "background").lower(), confirm.PALETTE["lime"].lower())
        self.assertEqual(self.w["check"]["text"], "DIODE V>Vth 통과")
        self.assertEqual(str(self.w["copy"]["state"]), "normal")
        self.w["copy"].invoke()
        self.assertEqual(self.clipboard(), text)
        self.assertEqual(self.s.copies, 1)
        self.w["input"].insert("end", " 더")
        self.root.update()
        self.assertEqual(str(self.w["copy"]["state"]), "disabled")                # 글이 바뀐 즉시 꺼진다
        self.assertEqual(self.w["check"]["text"], speak.TEXT_STALE_LINE)

    def test_blocked_and_hidden(self):
        self.type_in("input", "가람소재 온도 350")
        self.w["seal"].invoke()
        self.assertEqual(self.w["check"]["text"], "DIODE V<Vth 막힘 · D4 x1 @L1")
        self.root.update()
        self.assertTrue(self.w["check_chip"].winfo_ismapped())
        self.assertEqual(str(self.w["copy"]["state"]), "disabled")
        self.no_clipboard()
        self.w["sealed"].tag_add("sel", "1.0", "end")
        self.w["sealed"].event_generate("<<Copy>>")                              # 걸린 글은 선택 복사로도 나가지 않는다
        self.assertIsNone(self.clipboard())
        self.type_in("input", "안녕\u200b하세요")
        self.w["seal"].invoke()
        self.assertEqual(self.shown("sealed"), "안녕[U+200B]하세요")
        self.assertEqual(str(self.w["copy"]["state"]), "disabled")
        self.assertEqual(len(self.w["input"].tag_ranges("hidden")), 2)
        self.assertIn("보이지 않는 글자", self.w["status"]["text"])

    def test_unseal_shows_text_only_in_the_window(self):
        self.type_in("input", "KITWORDALPHA 질문")
        self.w["seal"].invoke()
        tok = TOKEN.findall(self.s.sealed.text)[0]
        self.no_clipboard()
        self.type_in("answer", "답: %s 를 보세요\nPH_ZZZZ 는 모른다" % tok)
        self.w["unseal"].invoke()
        self.assertEqual(self.shown("restored"), "답: KITWORDALPHA 를 보세요\nPH_ZZZZ 는 모른다")
        self.assertIn("L2", self.w["unseal_note"]["text"])
        r = self.w["restored"]
        r.tag_add("sel", "1.0", "end")
        for ev in ("<<Copy>>", "<<Cut>>"):
            r.event_generate(ev)
        self.assertIsNone(self.clipboard())
        self.assertIn(str(r.cget("exportselection")), ("0", "False"))
        self.type_in("answer", "가람소재 라고 맞혔다")
        self.w["unseal"].invoke()
        self.assertEqual(self.shown("restored"), "")
        self.assertIn("U2", self.w["status"]["text"])

    def test_enter_never_presses_anything(self):
        self.type_in("input", "KITWORDALPHA 질문")
        self.w["seal"].invoke()
        self.no_clipboard()
        self.root.update()
        copies = self.s.copies
        for target in (self.w["seal"], self.w["copy"], self.w["clear"], self.w["unseal"], self.w["close"], self.root):
            target.focus_force()
            self.root.update()
            for seq in ("<Return>", "<KP_Enter>"):
                target.event_generate(seq)
                self.root.update()
        self.assertEqual((self.s.copies, self.s.closed, self.clipboard()), (copies, False, None))

    def test_clear_keeps_the_table_and_close_asks_then_closes(self):
        self.type_in("input", "KITWORDALPHA 질문")
        self.type_in("answer", "답")
        self.w["seal"].invoke()
        self.w["clear"].invoke()
        for key in ("input", "sealed", "answer", "restored"):
            self.assertEqual(self.shown(key), "", key)
        self.view.pump()
        self.assertEqual(self.w["tokens"]["text"], "가명 표 1개 (메모리에만)")
        self.root.focus_force()
        self.root.event_generate("<Escape>")
        self.root.update()
        self.assertFalse(self.s.closed)
        self.assertEqual(self.w["status_chip"]["text"].strip(), "ASK")
        self.root.event_generate("<Escape>")
        self.root.update()
        self.assertTrue(self.s.closed)
        self.assertEqual(self.s.tokens, 0)

    def test_window_close_and_idle_expiry(self):
        self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))
        self.assertTrue(self.s.closed)                                           # 토큰이 없으면 바로 닫힌다

    def test_touching_keeps_the_window_and_idle_closes_it(self):
        self.clock.advance(1700)
        self.root.event_generate("<Motion>", x=3, y=3)
        self.root.update()
        self.clock.advance(1700)
        self.view.pump()
        self.assertEqual(self.s.state, "ready")
        self.clock.advance(200)
        self.view.pump()
        self.assertTrue(self.s.expired)

    def test_run_ends_and_the_window_is_gone_when_time_is_up(self):
        self.view.close()
        view = speak.TkView(self.tk, clock=self.clock)
        s = speak.SpeakSession(self.home, clock=self.clock)
        opened = view.open

        def open_then_wait(session):
            opened(session)
            self.clock.advance(speak.IDLE_LIMIT_S)                  # 창이 뜬 뒤 손대지 않은 채 시간이 흐른다
        view.open = open_then_wait
        view.run(s)
        self.assertEqual((s.expired, view.root), (True, None))

    def test_it_fits_the_screen_and_small_screens_shrink_the_boxes(self):
        self.root.update_idletasks()
        self.assertLessEqual(self.root.winfo_reqheight(), self.root.winfo_screenheight() - speak.SCREEN_MARGIN_PX)
        self.assertLessEqual(self.root.winfo_reqwidth(), self.root.winfo_screenwidth())
        self.view._fit_height(480)
        self.assertLessEqual(self.root.winfo_reqheight(), 480)
        self.assertTrue(self.w["close"].winfo_ismapped())
        for key in speak.BOXES:
            self.assertGreaterEqual(int(self.w[key].cget("height")), speak.MIN_BOX_LINES)
        self.view._fit_width(1000)
        self.assertLessEqual(self.root.winfo_reqwidth(), 1000)

    def test_every_color_is_navy_lime_or_gray(self):
        self.type_in("input", "가람소재 온도 350")
        self.w["seal"].invoke()
        self.view.pump()
        seen = 0
        for widget in all_widgets(self.root):
            for option in COLOR_OPTIONS:
                try:
                    value = widget.cget(option)
                except self.tk.TclError:
                    continue
                if str(value):
                    r, g, b = (v >> 8 for v in widget.winfo_rgb(str(value)))
                    self.assertTrue(color_ok(r, g, b), "%s %s=%s" % (widget, option, value))
                    seen += 1
        self.assertGreater(seen, 50)

    def test_create_view_and_a_callback_error(self):
        self.assertIsInstance(speak.create_view(), speak.TkView)
        self.view._after(10, lambda: 1 / 0)
        with self.assertRaises(ZeroDivisionError):
            for _ in range(40):
                self.view.pump()
                time.sleep(0.01)

    def test_main_speak_end_to_end_with_real_widgets(self):
        self.view.close()
        steps = [lambda v: self.fill(v, "input", "KITWORDALPHA 질문"), lambda v: v.widgets["seal"].invoke(),
                 lambda v: v.widgets["copy"].invoke(),
                 lambda v: self.fill(v, "answer", "답"), lambda v: v.widgets["unseal"].invoke(),
                 lambda v: v.widgets["close"].invoke(), lambda v: v.widgets["close"].invoke()]
        with mock.patch.object(speak, "create_view", return_value=Scripted(self.tk, steps)):
            code, line = speak.main_speak(self.home)
        self.assertEqual((code, line), (0, '{"closed": true, "expired": false, "seals": 1, "copies": 1, "unseals": 1}'))

    def fill(self, view, key, text):
        view.widgets[key].insert("1.0", text)
        view.root.update()
        view.pump()

    def test_an_unreachable_display_is_e07(self):
        with mock.patch.dict(os.environ, {"DISPLAY": ":987"}):
            self.assertEqual(speak.main_speak(self.home), (1, E07))


class Scripted(speak.TkView):
    """진짜 tk 창 위에서 대본 (위젯을 누르는 함수들) 을 차례로 돌리는 시험용 화면."""

    def __init__(self, tk_module, steps):
        speak.TkView.__init__(self, tk_module)
        self.steps = list(steps)

    def open(self, session):
        speak.TkView.open(self, session)
        self._after(30, self._step)
        self._after(30000, lambda: session.request_close() or session.request_close())

    def _step(self):
        if self.steps and self.root is not None:
            self.steps.pop(0)(self)
            if self.root is not None:
                self._after(30, self._step)


if __name__ == "__main__":
    unittest.main()
