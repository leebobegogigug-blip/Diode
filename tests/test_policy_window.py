# -*- coding: utf-8 -*-
"""정책 편집 창 (diodelib.policy_window) - 칸의 글 <-> 값 · 검증 · 경고 · 실데이터 확인 글 (AL-10) · 바뀐 것 없음 · 저장 ·
깨진 설정 · 더 새 설정 · 닫기 확인 · 결과 한 줄과 종료 코드 · 창을 못 띄움 (E-07) · 건너뛰는 길이 없음 (AL-12) · 색 ·
창을 따로 떼어 띄우기 · 실제 tk 창 (DISPLAY 가 있을 때만).

화면은 가짜 백엔드로 바꿔 끼운다 (FakeView - 이 파일 안에만 있다. 실행 코드에는 우회가 없다). 모든 시험은 임시 폴더만 쓰고
(실제 데이터 폴더를 건드리지 않는다), 자료는 모두 지어낸 것이다.
"""
import ast
import colorsys
import contextlib
import inspect
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import config, confirm, policy_window as pw  # noqa: E402

PW_PY = os.path.join(ROOT, "diodelib", "policy_window.py")

MARK = "KITSECRETMARK"                  # 틀린 값에 심는 표 - 어떤 글에도 나오면 안 된다
WORD_A, WORD_B = "KITWORDALPHA", "가람소재(가상)"
E07 = '{"saved": false, "error": "E-07"}'
E20 = '{"saved": false, "error": "E-20"}'
NOT_SAVED = '{"saved": false}'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-policy-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "data")
        self.raw = os.path.join(self.tmp, "kitraw")
        self.key = os.path.join(self.tmp, "kitkey.txt")
        os.makedirs(self.raw)
        with open(self.key, "w") as f:
            f.write("dummy-key-file")

    def state(self, **kw):
        """config.apply_state 에 줄 상태 (지어낸 값)."""
        st = {"words": [WORD_A, WORD_B], "raw_dirs": [self.raw], "inner_tools": ["InnerX"], "lib_allow": ["pandas"],
              "patterns": ["(?i)kitlot-[a-z]+"], "web_search": True, "real_data": False, "monthly_budget_usd": 100,
              "worker_command": ["opencode", "run", "--dir", "{cwd}", "{prompt}"], "worker_cwd": None,
              "room_path": os.path.join(self.tmp, "room"), "llm": None}
        st.update(kw)
        return st

    def texts(self, **over):
        """창의 모든 글 칸에 넣을 멀쩡한 글."""
        t = {"words": "%s\n%s" % (WORD_A, WORD_B), "raw_dirs": self.raw, "inner_tools": "InnerX",
             "worker_command": pw.WORKER_EXAMPLE, "worker_cwd": "", "lib_allow": "pandas", "patterns": "(?i)kitlot-[a-z]+",
             "monthly_budget_usd": "100", "room_path": os.path.join(self.tmp, "room"), "llm": ""}
        t.update(over)
        return t

    def fill(self, s, **over):
        for key, text in self.texts(**over).items():
            s.set_text(key, text)
        return s

    def fresh(self, **over):
        return self.fill(pw.PolicySession(self.home), **over)

    def saved_session(self, **over):
        s = self.fresh(**over)
        self.assertTrue(s.save().ok)
        return s

    def read_files(self):
        out = {}
        if os.path.isdir(self.home):
            for name in sorted(os.listdir(self.home)):
                with open(os.path.join(self.home, name), "rb") as f:
                    out[name] = f.read()
        return out


class FakeView(object):
    """화면 백엔드 흉내 - 대본대로 칸에 글을 넣고 단추를 누른다. 시험 안에만 둔다 (실행 코드에 우회가 생기지 않게).

    대본의 걸음: ("text", 칸, 글) · ("append", 칸, 줄) · ("web", 참거짓) · ("real", 참거짓) · ("confirm", 글) ·
                 ("example",) · ("save",) · ("close",) · ("raise", 예외)
    """

    def __init__(self, script=(), fail_after=None):
        self.script = list(script)
        self.fail_after = fail_after
        self.ran = False
        self.session = None
        self.saves, self.closes = [], []

    def run(self, session):
        self.ran = True
        self.session = session
        for step in self.script:
            if session.finished:
                break
            op = step[0]
            if op == "text":
                session.set_text(step[1], step[2])
            elif op == "append":
                session.append_line(step[1], step[2])
            elif op == "web":
                session.set_web_search(step[1])
            elif op == "real":
                session.toggle_real_data(step[1])
            elif op == "confirm":
                session.set_real_confirm(step[1])
            elif op == "example":
                session.fill_example()
            elif op == "save":
                self.saves.append(session.save())
            elif op == "close":
                self.closes.append(session.request_close())
            elif op == "raise":
                raise step[1]
        if self.fail_after is not None:
            raise self.fail_after


def _blank_state_keys():
    """창이 config 에 넘기는 상태의 칸 (config.validate_state 가 읽는 칸 전부)."""
    return ["words", "raw_dirs", "inner_tools", "lib_allow", "patterns", "web_search", "real_data", "derived_level",
            "monthly_budget_usd", "worker_command", "worker_cwd", "room_path", "llm"]


# ─────────────────────────────────────────────────────────────── 글 <-> 값

class TestCodecs(unittest.TestCase):
    def test_lines_one_per_line_ignoring_blank_lines_and_edges(self):
        self.assertEqual(pw.lines_of("  a  \n\n   b b \t\n\n\nc"), ["a", "b b", "c"])
        self.assertEqual(pw.lines_of(""), [])
        self.assertEqual(pw.lines_of("\n \n\t\n"), [])

    def test_a_hash_line_is_a_line_not_a_comment(self):
        self.assertEqual(pw.lines_of("#KITWORDALPHA\n  # 가람소재(가상) \n#"), ["#KITWORDALPHA", "# 가람소재(가상)", "#"])
        self.assertEqual(pw.to_value("words", "#a1\n#b2"), ["#a1", "#b2"])

    def test_pasted_line_ends_are_all_line_breaks(self):
        self.assertEqual(pw.lines_of("a\r\nb\rc\nd"), ["a", "b", "c", "d"])

    def test_only_a_newline_splits_a_line(self):
        """str.splitlines 는 보이지 않는 글자에서도 줄을 나눈다 - 그 글자는 나누지 않고 남겨 검사가 잡게 한다."""
        for ch in ("\u2028", "\u2029", "\x0b", "\x0c", "\x1c", "\x85"):
            self.assertEqual(pw.lines_of("a%sb" % ch), ["a%sb" % ch], repr(ch))

    def test_every_list_field_round_trips(self):
        for key in pw.LIST_KEYS:
            values = ["하나 1", "#둘", "three-3"]
            self.assertEqual(pw.to_value(key, pw.to_text(key, values)), values, key)
            self.assertEqual(pw.to_text(key, []), "")
            self.assertEqual(pw.to_value(key, ""), [])

    def test_the_worker_command_is_one_line_of_json(self):
        cmd = ["opencode", "run", "--dir", "{cwd}", "{prompt}"]
        self.assertEqual(pw.to_text("worker_command", cmd), '["opencode","run","--dir","{cwd}","{prompt}"]')
        self.assertEqual(pw.to_text("worker_command", cmd), pw.WORKER_EXAMPLE)
        self.assertEqual(pw.to_value("worker_command", pw.WORKER_EXAMPLE), cmd)
        self.assertEqual(pw.to_value("worker_command", '  [ "a" , "b c" ]  '), ["a", "b c"])
        self.assertEqual(pw.to_value("worker_command", r'["C:\\tools\\oc.exe", "{prompt}"]'), ["C:\\tools\\oc.exe", "{prompt}"])
        self.assertIsNone(pw.to_value("worker_command", ""))
        self.assertIsNone(pw.to_value("worker_command", "   "))
        self.assertEqual(pw.to_text("worker_command", None), "")

    def test_a_bad_worker_command_names_the_field(self):
        for text in ("opencode run", "{}", '"a"', "[1, ", '["a",]', "[\n\"a\"\n]", "null"):
            with self.assertRaises(pw.FieldProblem, msg=text) as cm:
                pw.to_value("worker_command", text)
            self.assertEqual((cm.exception.area, cm.exception.field), ("worker", "worker_command"))

    def test_empty_means_none_for_the_one_line_fields(self):
        for key in ("worker_cwd", "room_path"):
            self.assertIsNone(pw.to_value(key, ""))
            self.assertIsNone(pw.to_value(key, "   "))
            self.assertEqual(pw.to_value(key, "  /a/b c  "), "/a/b c")
            self.assertEqual(pw.to_text(key, None), "")
            self.assertEqual(pw.to_text(key, "/a/b"), "/a/b")

    def test_a_one_line_field_with_a_line_break_is_a_problem(self):
        for key, area in (("worker_cwd", "worker"), ("room_path", "room_path"), ("monthly_budget_usd", "budget"),
                          ("worker_command", "worker")):
            with self.assertRaises(pw.FieldProblem, msg=key) as cm:
                pw.to_value(key, "a\nb")
            self.assertEqual((cm.exception.area, cm.exception.field), (area, key))

    def test_the_budget_is_a_number_and_empty_is_zero(self):
        self.assertEqual(pw.to_value("monthly_budget_usd", ""), 0)
        self.assertEqual(pw.to_value("monthly_budget_usd", "  120 "), 120)
        self.assertIsInstance(pw.to_value("monthly_budget_usd", "120"), int)
        self.assertEqual(pw.to_value("monthly_budget_usd", "12.50"), 12.5)
        self.assertEqual(pw.to_value("monthly_budget_usd", "0"), 0)
        for text in ("-1", "+1", "1e3", "1,000", "abc", "١٢٣", "1.", ".5", "1.2.3", "9" * 13, "0x10", "NaN", "inf", "1 2"):
            with self.assertRaises(pw.FieldProblem, msg=text) as cm:
                pw.to_value("monthly_budget_usd", text)
            self.assertEqual((cm.exception.area, cm.exception.field), ("budget", "monthly_budget_usd"))

    def test_the_budget_text_round_trips(self):
        for value, text in ((0, "0"), (120, "120"), (12.5, "12.5"), (100.0, "100"), (0.25, "0.25")):
            self.assertEqual(pw.to_text("monthly_budget_usd", value), text)
            self.assertEqual(pw.to_value("monthly_budget_usd", text), value)

    def test_llm_is_a_json_object_and_empty_is_none(self):
        self.assertIsNone(pw.to_value("llm", ""))
        self.assertIsNone(pw.to_value("llm", " \n "))
        self.assertEqual(pw.to_text("llm", None), "")
        obj = {"base_url": "http://example.com/v1", "model": "m", "temperature": 0.5, "extra_headers": {"X-A": "{file:/a/b.txt}"}}
        text = pw.to_text("llm", obj)
        self.assertIn("\n", text)                                   # 여러 줄 칸에 읽기 좋게
        self.assertEqual(pw.to_value("llm", text), obj)
        for bad in ("[1]", '"x"', "{", "{'a': 1}", '{"a": 1, "a": 2}', '{"a": NaN}', "null", "12"):
            with self.assertRaises(pw.FieldProblem, msg=bad) as cm:
                pw.to_value("llm", bad)
            self.assertEqual((cm.exception.area, cm.exception.field), ("llm", "llm"))

    def test_the_llm_codec_only_reads_json_the_keys_are_the_sessions_business(self):
        for text in ('{"api_key": "{file:/a/key.txt}"}', '{"api_key": "abc-literal"}', '{"api_key": ""}', '{"model": "m"}'):
            self.assertIsInstance(pw.to_value("llm", text), dict, text)

    def test_a_stored_secret_is_masked_when_the_llm_is_shown(self):
        llm = {"base_url": "http://example.com/v1", "api_key": "kit-literal-key-1234", "model": "m",
               "extra_headers": {"X-A": "kit-header-value", "X-B": "{file:/a/b.txt}", "X-C": "{env:NAME}", "X-D": ""}}
        text = pw.to_text("llm", llm)
        shown = json.loads(text)
        self.assertEqual(shown["api_key"], "설정됨 (20자 · 값은 표시 안 함)")
        self.assertEqual(shown["extra_headers"], {"X-A": "설정됨 (16자 · 값은 표시 안 함)", "X-B": "{file:/a/b.txt}",
                                                 "X-C": "{env:NAME}", "X-D": ""})
        self.assertEqual((shown["base_url"], shown["model"]), ("http://example.com/v1", "m"))
        self.assertNotIn("kit-literal-key", text)
        self.assertNotIn("kit-header-value", text)
        self.assertEqual(llm["api_key"], "kit-literal-key-1234")                       # 받은 값은 건드리지 않는다
        self.assertEqual(pw.MASK_TEXT % 3, "설정됨 (3자 · 값은 표시 안 함)")
        self.assertTrue(pw.MASK_RE.match(pw.MASK_TEXT % 3))
        self.assertFalse(pw.MASK_RE.match("설정됨 (x자 · 값은 표시 안 함)"))

    def test_which_values_count_as_secrets(self):
        self.assertEqual(pw._secrets_of(None), {})
        self.assertEqual(pw._secrets_of({"api_key": "", "extra_headers": {"X": "{file:/a}", "Y": "{env:N}", "Z": ""}}), {})
        self.assertEqual(pw._secrets_of({"api_key": "k1", "extra_headers": {"X": "h1", "Y": "{file:/a}"}}),
                         {("api_key",): "k1", ("extra_headers", "X"): "h1"})
        self.assertEqual(pw._secrets_of({"api_key": 5, "extra_headers": ["x"]}), {})

    def test_the_codecs_cover_every_text_field_and_each_has_a_label(self):
        self.assertEqual(set(pw.CODECS), set(pw.TEXT_KEYS))
        self.assertEqual(set(pw.TEXT_KEYS), set(pw.LIST_KEYS) | set(pw.LINE_KEYS) | {"llm"})
        self.assertEqual(len(pw.TEXT_KEYS), len(set(pw.TEXT_KEYS)))
        for key in list(pw.TEXT_KEYS) + ["web_search", "real_data", "real_confirm"]:
            self.assertIn(key, pw.FIELD_LABEL)
            self.assertRegex(pw.FIELD_LABEL[key], r"^0[1-6] ")        # 구역 번호가 앞에 붙는다

    def test_a_field_problem_has_codes_only(self):
        e = pw.FieldProblem("worker", "worker_command")
        self.assertEqual(str(e), "worker")


# ─────────────────────────────────────────────────────────────── 보이는 것 · 표

class TestTables(unittest.TestCase):
    CONFIG_PY = os.path.join(ROOT, "diodelib", "config.py")

    def config_codes(self):
        """config.py 가 내는 경고 코드 (warn.append) · 오류 영역 코드 (ConfigError("...")) 를 AST 로 모은다."""
        with open(self.CONFIG_PY, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        warns, errors = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr == "append" and isinstance(fn.value, ast.Name) and fn.value.id == "warn":
                    warns.add(node.args[0].value)
                if isinstance(fn, ast.Name) and fn.id == "ConfigError":
                    errors.add(node.args[0].value)
        return warns, errors

    def test_every_warning_config_can_give_has_a_korean_line(self):
        warns, _ = self.config_codes()
        self.assertEqual(warns, {"short", "raw_missing", "words_empty", "raw_empty"})
        self.assertEqual(set(pw.WARN_TEXT), warns)

    def test_every_error_area_config_can_give_has_a_korean_line(self):
        _, errors = self.config_codes()
        self.assertTrue({"words", "raw_dirs", "patterns", "lib_allow", "worker", "llm", "budget", "room_path", "flags"} <= errors)
        for code in errors - {"broken", "newer"}:            # broken · newer 는 창이 따로 다룬다
            self.assertIn(code, pw.ERROR_TEXT, code)
            self.assertIn(code, pw.AREA_FIELD, code)

    def test_the_texts_are_one_korean_line_without_emoji(self):
        for table in (pw.WARN_TEXT, pw.ERROR_TEXT):
            for code, text in table.items():
                self.assertRegex(text, r"[가-힣]", code)
                self.assertNotIn("\n", text, code)
                self.assertFalse(any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in text), code)
        for name in dir(pw):
            value = getattr(pw, name)
            if name.startswith("TEXT_") and isinstance(value, str):
                self.assertNotIn("\n", value, name)

    def test_error_areas_point_at_a_field_with_a_label(self):
        for area, field in pw.AREA_FIELD.items():
            self.assertIn(field, pw.FIELD_LABEL, area)
            self.assertIn(area, pw.ERROR_TEXT, area)

    def test_the_limits_in_the_texts_come_from_config(self):
        self.assertIn(str(config.MAX_WORDS), pw.ERROR_TEXT["words"])
        self.assertIn(str(config.MAX_WORD_LEN), pw.ERROR_TEXT["words"])
        self.assertIn(str(config.MAX_PATH_LEN), pw.ERROR_TEXT["raw_dirs"])

    def test_hidden_characters_are_found_the_way_the_confirm_window_finds_them(self):
        tricky = "a\u200bb\u202ec\u00a0d\x00e\u3164f\ufe0fg\u2028h\ue000i\ufeffj\u3000k\x1bl"
        want = ["U+200B", "U+202E", "U+00A0", "U+0000", "U+3164", "U+FE0F", "U+2028", "U+E000", "U+FEFF", "U+3000", "U+001B"]
        self.assertEqual([h.code for h in pw.hidden_hits_in("words", tricky)], want)
        for ch in tricky:
            self.assertEqual(bool(pw.hidden_hits_in("words", ch)), confirm.is_hidden_char(ch), repr(ch))

    def test_plain_text_has_no_hidden_character(self):
        self.assertEqual(pw.hidden_hits_in("words", "가나다 abc\t1\n  라마\r\n\rx ㄱㅏ !@#"), [])

    def test_hits_carry_the_field_and_the_line(self):
        hits = pw.hidden_hits_in("raw_dirs", "ok\nb\u200b\nc\n\u00a0d")
        self.assertEqual([(h.field, h.line, h.code) for h in hits], [("raw_dirs", 2, "U+200B"), ("raw_dirs", 4, "U+00A0")])

    def test_the_hits_are_described_as_brackets_with_the_label_and_the_line(self):
        text = pw.describe_hits(pw.hidden_hits_in("words", "a\nb\u200b\u200b\u200b\nc\u00a0"))
        self.assertIn("보이지 않는 글자 4개", text)
        self.assertIn("01 사전 2째 줄 [U+200B] x3", text)
        self.assertIn("01 사전 3째 줄 [U+00A0]", text)
        many = pw.hidden_hits_in("words", "\n".join("a\u200b" for _ in range(9)))
        text = pw.describe_hits(many)
        self.assertIn("9개", text)
        self.assertIn(" 외 %d곳" % (9 - pw.MAX_HIDDEN_SHOWN), text)

    def test_the_summary_has_counts_and_flags_only(self):
        counts = {"dictionary": 3, "raw_dirs": 2, "inner_tools": 1, "lib_allow": 0, "patterns": 4, "web_search": True,
                  "real_data": False, "worker": True, "llm": False, "room_path": True}
        line = pw.summarize(counts)
        for want in ("사전 3", "원자료 폴더 2", "안쪽 도구 1", "라이브러리 0", "정규식 4", "웹 검색 켜짐", "실데이터 꺼짐", "일꾼 있음",
                     "llm 없음", "방 자리 있음"):
            self.assertIn(want, line)
        self.assertNotIn("\n", line)


# ─────────────────────────────────────────────────────────────── 창을 열 때

class TestOpen(Base):
    def test_the_first_run_is_blank_and_not_dirty(self):
        s = pw.PolicySession(self.home)
        for key in pw.LIST_KEYS + ("worker_command", "worker_cwd", "room_path", "llm"):
            self.assertEqual(s.text(key), "", key)
        self.assertEqual(s.text("monthly_budget_usd"), "0")
        self.assertTrue(s.web_search)
        self.assertFalse(s.real_data)
        self.assertFalse(s.dirty)
        self.assertFalse(s.opened_blank)
        self.assertFalse(s.saved)
        self.assertFalse(s.finished)
        self.assertEqual(s.snapshot().message, pw.TEXT_IDLE)
        self.assertEqual(s.snapshot().level, "")
        self.assertFalse(os.path.exists(self.home))                      # 열기만 해서는 아무것도 만들지 않는다

    def test_the_saved_values_are_shown(self):
        config.apply_state(self.home, self.state(llm={"base_url": "http://example.com/v1", "model": "kit-model",
                                                       "api_key": "{file:%s}" % self.key.replace("\\", "\\\\")},
                                                 worker_cwd=os.path.join(self.tmp, "work"), real_data=True))
        s = pw.PolicySession(self.home)
        self.assertEqual(s.text("words").split("\n"), [WORD_A, WORD_B])
        self.assertEqual(s.text("raw_dirs"), self.raw)
        self.assertEqual(s.text("inner_tools"), "innerx")                  # config 가 소문자로 쓴다
        self.assertEqual(s.text("lib_allow"), "pandas")
        self.assertEqual(s.text("patterns"), "(?i)kitlot-[a-z]+")
        self.assertEqual(s.text("worker_command"), pw.WORKER_EXAMPLE)
        self.assertEqual(s.text("worker_cwd"), os.path.join(self.tmp, "work"))
        self.assertEqual(s.text("monthly_budget_usd"), "100")
        self.assertEqual(s.text("room_path"), os.path.join(self.tmp, "room"))
        self.assertEqual(json.loads(s.text("llm"))["model"], "kit-model")
        self.assertTrue(s.real_data)
        self.assertEqual((s.line_count("words"), s.line_count("raw_dirs"), s.line_count("patterns")), (2, 1, 1))
        self.assertFalse(s.dirty)

    def test_nothing_changed_means_not_dirty_even_after_blank_lines_and_spaces(self):
        config.apply_state(self.home, self.state())
        s = pw.PolicySession(self.home)
        s.set_text("words", s.text("words") + "\n\n   \n")
        s.set_text("raw_dirs", "  " + s.text("raw_dirs") + "  \n")
        s.set_text("monthly_budget_usd", "  100 ")
        s.set_text("worker_cwd", "   ")
        self.assertFalse(s.dirty)
        s.set_text("monthly_budget_usd", "")                       # 비우면 0 - 100 이던 값이 바뀐 것이다
        self.assertTrue(s.dirty)

    def test_a_real_change_is_dirty_and_changing_it_back_is_not(self):
        config.apply_state(self.home, self.state())
        s = pw.PolicySession(self.home)
        old = s.text("words")
        s.set_text("words", old + "\n새단어(가상)")
        self.assertTrue(s.dirty)
        s.set_text("words", old)
        self.assertFalse(s.dirty)
        s.set_web_search(False)
        self.assertTrue(s.dirty)
        s.set_web_search(True)
        self.assertFalse(s.dirty)
        s.set_text("monthly_budget_usd", "abc")                        # 읽히지 않는 글도 고친 것이다
        self.assertTrue(s.dirty)

    def test_typing_the_real_data_phrase_is_not_a_change(self):
        s = pw.PolicySession(self.home)
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertFalse(s.dirty)

    def test_a_broken_config_opens_blank_with_a_notice(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        s = pw.PolicySession(self.home)
        self.assertTrue(s.opened_blank)
        self.assertEqual(s.text("words"), "")
        self.assertEqual(s.snapshot().message, pw.TEXT_BLANK_OPEN)
        self.assertFalse(s.dirty)

    def test_a_broken_config_keeps_the_words_of_an_intact_dictionary(self):
        config.apply_state(self.home, self.state())
        with open(config.config_path(self.home), "w") as f:
            f.write("[]")
        s = pw.PolicySession(self.home)
        self.assertTrue(s.opened_blank)
        self.assertEqual(s.text("words").split("\n"), [WORD_A, WORD_B])           # 멀쩡한 사전을 빈 값으로 덮지 않게
        self.assertEqual(s.text("raw_dirs"), "")
        s.set_text("raw_dirs", self.raw)
        self.assertTrue(s.save().ok)
        self.assertTrue(os.path.exists(config.config_path(self.home) + ".broken"))   # 깨진 파일은 옮겨 둔다
        self.assertEqual(config.counts(self.home)["dictionary"], 2)

    def test_a_broken_dictionary_also_opens(self):
        config.apply_state(self.home, self.state())
        with open(config.dictionary_path(self.home), "w") as f:
            f.write("{")
        s = pw.PolicySession(self.home)
        self.assertTrue(s.opened_blank)
        self.assertEqual(s.text("words"), "")

    def test_saving_a_blank_opened_window_is_not_reported_as_unchanged(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        s = pw.PolicySession(self.home)
        r = s.save()
        self.assertTrue(r.ok)
        self.assertTrue(r.changed)
        self.assertTrue(os.path.exists(config.config_path(self.home) + ".broken"))

    def test_a_newer_config_is_not_opened(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            json.dump({"format": 2}, f)
        with self.assertRaises(config.ConfigError) as cm:
            pw.PolicySession(self.home)
        self.assertEqual(cm.exception.code, "newer")
        with open(config.config_path(self.home)) as f:
            self.assertEqual(json.load(f), {"format": 2})

    def test_a_newer_dictionary_is_not_opened_even_when_the_config_is_broken(self):
        os.makedirs(self.home)
        with open(config.dictionary_path(self.home), "w") as f:
            json.dump({"format": 2, "words": ["x"]}, f)
        with self.assertRaises(config.ConfigError) as cm:
            pw.PolicySession(self.home)
        self.assertEqual(cm.exception.code, "newer")
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        with self.assertRaises(config.ConfigError) as cm:
            pw.PolicySession(self.home)
        self.assertEqual(cm.exception.code, "newer")

    def test_the_state_keys_are_what_config_expects(self):
        s = pw.PolicySession(self.home)
        self.assertEqual(set(s._build_state()), set(config.load_state(self.home)))
        self.assertEqual(set(s._build_state()), set(_blank_state_keys()))

    def test_a_home_that_cannot_be_read_is_an_error_not_a_blank_window(self):
        with mock.patch.object(config, "load_state_tolerant", side_effect=OSError("x")):
            with self.assertRaises(OSError):
                pw.PolicySession(self.home)


# ─────────────────────────────────────────────────────────────── 검증

class TestValidate(Base):
    def test_good_texts_pass_and_give_the_clean_state(self):
        s = self.fresh()
        c = s.validate()
        self.assertTrue(c.ok, c.message)
        self.assertEqual((c.area, c.field, c.message, c.lines), ("", "", "", ()))
        self.assertEqual(c.warnings, [])
        self.assertEqual(c.state["words"], [WORD_A, WORD_B])
        self.assertEqual(c.state["inner_tools"], ["innerx"])
        self.assertEqual(c.state["worker_command"][:2], ["opencode", "run"])
        self.assertEqual(c.state["monthly_budget_usd"], 100)

    def test_validate_writes_nothing(self):
        self.fresh().validate()
        self.assertFalse(os.path.exists(self.home))

    def test_what_was_loaded_comes_back_the_same(self):
        config.apply_state(self.home, self.state(llm={"base_url": "http://example.com/v1", "model": "kit-model",
                                                       "api_key": "{file:%s}" % self.key.replace("\\", "\\\\")}))
        s = pw.PolicySession(self.home)
        want = config.validate_state(config.load_state(self.home))
        got = s.validate()
        self.assertTrue(got.ok, got.message)
        self.assertEqual((got.state, got.warnings), want)

    def test_each_wrong_field_is_named_and_its_value_is_never_written(self):
        cases = (
            ("words", MARK + "가" * 80, "words", "words"),
            ("raw_dirs", MARK + "/relative", "raw_dirs", "raw_dirs"),
            ("inner_tools", MARK + "x" * 60, "inner_tools", "inner_tools"),
            ("lib_allow", "bad name " + MARK, "lib_allow", "lib_allow"),
            ("patterns", "(" + MARK, "patterns", "patterns"),
            ("monthly_budget_usd", MARK, "budget", "monthly_budget_usd"),
            ("monthly_budget_usd", "100001", "budget", "monthly_budget_usd"),
            ("worker_command", '["%s","{prompt}","{prompt}"]' % MARK, "worker", "worker_command"),
            ("worker_command", "{ %s" % MARK, "worker", "worker_command"),
            ("worker_command", '{"%s": 1}' % MARK, "worker", "worker_command"),
            ("room_path", MARK, "room_path", "room_path"),
            ("llm", '{"base_url": "ftp://%s/v1", "model": "m"}' % MARK, "llm", "llm"),
            ("llm", '["%s"]' % MARK, "llm", "llm"),
            ("llm", '{"base_url": "http://example.com/v1", "model": "m", "api_key": "%s"}' % MARK, "llm_key", "llm"),
            ("llm", '{"base_url": "http://example.com/v1", "model": "m", "api_key": "{env:%s}"}' % MARK, "llm", "llm"),
            ("llm", '{"base_url": "http://example.com/v1", "model": "m", "extra_headers": {"X-A": "%s"}}' % MARK, "llm_key", "llm"),
            ("llm", '{"base_url": "http://example.com/v1", "model": "m", "api_key": "{file:%s}"}'
             % os.path.join(self.tmp, MARK + "-missing.txt").replace("\\", "\\\\"), "llm", "llm"),
        )
        for key, bad, area, field in cases:
            s = self.fresh(**{key: bad})
            c = s.validate()
            self.assertFalse(c.ok, key)
            self.assertEqual((c.area, c.field), (area, field), (key, bad[:30]))
            self.assertIn(pw.FIELD_LABEL[field], c.message, key)
            self.assertIn(pw.ERROR_TEXT[area], c.message, key)
            self.assertNotIn(MARK, c.message, key)
            self.assertNotIn("\n", c.message, key)
            self.assertIsNone(c.state)
            self.assertEqual(c.warnings, [])

    def test_a_work_folder_without_a_command_points_at_the_work_folder(self):
        s = self.fresh(worker_command="", worker_cwd=os.path.join(self.tmp, "work"))
        c = s.validate()
        self.assertEqual((c.ok, c.area, c.field), (False, "worker", "worker_cwd"))
        self.assertIn(pw.FIELD_LABEL["worker_cwd"], c.message)
        self.assertTrue(self.fresh(worker_command="", worker_cwd="").validate().ok)

    def test_no_command_and_no_folder_means_no_worker(self):
        c = self.fresh(worker_command="").validate()
        self.assertTrue(c.ok)
        self.assertIsNone(c.state["worker_command"])

    def test_the_wrong_lines_of_a_list_field_are_numbered_without_their_text(self):
        s = self.fresh(words="%s\n%s\n%s\n\n%s" % (WORD_A, MARK + "가" * 80, WORD_B, "나" * 90))
        c = s.validate()
        self.assertEqual((c.area, c.field, c.lines), ("words", "words", (2, 5)))                # 빈 줄 (4) 도 화면의 줄이다
        self.assertIn("(2째 줄 · 5째 줄)", c.message)
        self.assertNotIn(MARK, c.message)
        s = self.fresh(raw_dirs="%s\n%s/rel\n%s" % (self.raw, MARK, MARK))
        self.assertEqual(s.validate().lines, (2, 3))

    def test_only_five_wrong_lines_are_listed(self):
        s = self.fresh(patterns="\n".join("(%d" % n for n in range(8)))
        c = s.validate()
        self.assertEqual(c.area, "patterns")
        self.assertEqual(len(c.lines), 8)
        self.assertIn("외 3곳", c.message)
        self.assertIn("1째 줄", c.message)
        self.assertNotIn("6째 줄", c.message)

    def test_a_limit_that_no_single_line_breaks_has_no_line_numbers(self):
        s = self.fresh(words="\n".join("단어%d다" % n for n in range(config.MAX_WORDS + 1)))
        c = s.validate()
        self.assertEqual((c.area, c.lines), ("words", ()))
        self.assertNotIn("째 줄", c.message)

    def test_hidden_characters_block_every_text_field(self):
        for key in pw.TEXT_KEYS:
            for ch in ("\u200b", "\u00a0", "\u3000", "\x07", "\ufeff", "\u202e", "\u2028", "\x85"):
                bad = {"worker_command": '["a\0","{prompt}"]'.replace("\0", ch), "monthly_budget_usd": "1" + ch}.get(key, "a" + ch + "b")
                s = self.fresh(**{key: bad})
                c = s.validate()
                self.assertEqual((c.ok, c.area, c.field), (False, "hidden", key), (key, repr(ch)))
                self.assertIn("[U+%04X]" % ord(ch), c.message)
                self.assertIn(pw.FIELD_LABEL[key], c.message)
                self.assertIn("1째 줄", c.message)

    def test_hidden_characters_are_found_before_anything_else(self):
        s = self.fresh(words=WORD_A + "\u200b", monthly_budget_usd="abc")
        self.assertEqual(s.validate().area, "hidden")

    def test_a_pasted_windows_text_is_not_hidden_characters(self):
        s = self.fresh(words="%s\r\n%s\r\n" % (WORD_A, WORD_B), raw_dirs=self.raw + "\r\n")
        c = s.validate()
        self.assertTrue(c.ok, c.message)
        self.assertEqual(c.state["words"], [WORD_A, WORD_B])

    def test_a_tab_is_visible_so_it_is_not_hidden(self):
        self.assertTrue(self.fresh(words="a\tb c").validate().ok)

    def test_hidden_lines_are_reported_for_the_screen(self):
        s = self.fresh(words="ok\nb\u200b\n\nc\u00a0")
        self.assertEqual(s.hidden_lines("words"), [2, 4])
        self.assertEqual(s.hidden_lines("raw_dirs"), [])
        self.assertEqual(len(s.hidden_hits()), 2)

    def test_the_four_warnings(self):
        c = self.fresh(words="a\n" + WORD_A).validate()
        self.assertTrue(c.ok)
        self.assertEqual(c.warnings, ["short"])
        c = self.fresh(raw_dirs=os.path.join(self.tmp, "없는폴더")).validate()
        self.assertEqual(c.warnings, ["raw_missing"])
        c = self.fresh(words="", raw_dirs="").validate()
        self.assertTrue(c.ok)
        self.assertEqual(c.warnings, ["raw_empty", "words_empty"])
        for code in ("short", "raw_missing", "words_empty", "raw_empty"):
            self.assertIn(code, pw.WARN_TEXT)

    def test_the_windows_own_checks_come_before_config(self):
        """실데이터 확인 글은 config 가 모르는 창의 규칙이다."""
        s = self.fresh()
        s._real = True                      # 확인 글 없이 켜진 상태를 일부러 만든다 (칸을 건드리지 않고)
        c = s.validate()
        self.assertEqual((c.ok, c.area, c.field), (False, "real_data", "real_confirm"))
        self.assertIn(pw.FIELD_LABEL["real_confirm"], c.message)


# ─────────────────────────────────────────────────────────────── 저장된 키 (W-04 · SPEC-llm › 04)

class TestSecrets(Base):
    """저장된 키 · 헤더 값은 화면에 가려서만 보이고 (설정됨 (n자 · 값은 표시 안 함)), 저장해도 그대로 남는다. 새로 글자 그대로 적는 것은 막는다."""

    SECRET = "kit-literal-key-1234"                 # 지어낸 값 (토큰 꼴이 아니다)
    HEADER = "kit-header-value-5678"

    def seed(self):
        self.llm = {"base_url": "http://example.com/v1", "model": "kit-model", "api_key": self.SECRET,
                    "extra_headers": {"X-Kit-Auth": self.HEADER, "X-Kit-Ref": "{file:%s}" % self.key}}
        config.apply_state(self.home, self.state(llm=self.llm))
        self.assertEqual(config.read_config(self.home)["llm"], self.llm)

    def everything_the_session_says(self, s, *results):
        parts = [s.text(k) for k in pw.TEXT_KEYS] + [s.snapshot().message, repr(s.snapshot())]
        for r in results:
            parts.append(repr(r))
        return "\n".join(parts)

    def test_the_window_shows_the_secret_masked_and_nothing_else_of_it(self):
        self.seed()
        s = pw.PolicySession(self.home)
        shown = json.loads(s.text("llm"))
        self.assertEqual(shown["api_key"], pw.MASK_TEXT % len(self.SECRET))
        self.assertEqual(shown["extra_headers"]["X-Kit-Auth"], pw.MASK_TEXT % len(self.HEADER))
        self.assertEqual(shown["extra_headers"]["X-Kit-Ref"], "{file:%s}" % self.key)        # 참조는 비밀이 아니라 그대로
        self.assertEqual(shown["model"], "kit-model")
        text = self.everything_the_session_says(s)
        self.assertNotIn(self.SECRET, text)
        self.assertNotIn(self.HEADER, text)
        self.assertNotIn("1234", text.replace("(20자", ""))

    def test_leaving_the_masks_alone_is_no_change_and_the_secrets_stay_exactly(self):
        self.seed()
        before = self.read_files()
        s = pw.PolicySession(self.home)
        self.assertFalse(s.dirty)
        c = s.validate()
        self.assertTrue(c.ok, c.message)
        self.assertEqual(c.state["llm"], self.llm)                                    # 가린 표시가 원래 값으로 되돌아 있다
        r = s.save()
        self.assertTrue(r.ok, r.message)
        self.assertFalse(r.changed)
        self.assertEqual(self.read_files(), before)                                     # 파일이 그대로다
        self.assertNotIn(self.SECRET, self.everything_the_session_says(s, r))

    def test_other_edits_keep_the_secrets(self):
        self.seed()
        s = pw.PolicySession(self.home)
        s.set_text("words", s.text("words") + "\n새단어(가상)")
        self.assertTrue(s.save().ok)
        self.assertEqual(config.read_config(self.home)["llm"], self.llm)
        self.assertEqual(config.counts(self.home)["dictionary"], 3)

    def test_editing_the_llm_around_the_masks_keeps_the_secrets(self):
        self.seed()
        s = pw.PolicySession(self.home)
        shown = json.loads(s.text("llm"))
        shown["model"] = "kit-model-2"
        shown["timeout_sec"] = 30
        s.set_text("llm", json.dumps(shown, ensure_ascii=False, indent=1))
        self.assertTrue(s.dirty)
        r = s.save()
        self.assertTrue(r.ok, r.message)
        stored = config.read_config(self.home)["llm"]
        self.assertEqual(stored["api_key"], self.SECRET)
        self.assertEqual(stored["extra_headers"]["X-Kit-Auth"], self.HEADER)
        self.assertEqual((stored["model"], stored["timeout_sec"]), ("kit-model-2", 30))
        self.assertNotIn(self.SECRET, self.everything_the_session_says(s, r))

    def test_removing_the_key_line_on_purpose_removes_the_key(self):
        self.seed()
        s = pw.PolicySession(self.home)
        shown = json.loads(s.text("llm"))
        del shown["api_key"]
        s.set_text("llm", json.dumps(shown))
        self.assertTrue(s.save().ok)
        self.assertNotIn("api_key", config.read_config(self.home)["llm"])

    def test_replacing_the_key_with_a_file_reference_is_allowed(self):
        self.seed()
        s = pw.PolicySession(self.home)
        shown = json.loads(s.text("llm"))
        shown["api_key"] = "{file:%s}" % self.key
        s.set_text("llm", json.dumps(shown))
        r = s.save()
        self.assertTrue(r.ok, r.message)
        self.assertEqual(config.read_config(self.home)["llm"]["api_key"], "{file:%s}" % self.key)

    def test_a_new_literal_key_or_header_value_is_refused_without_echoing_it(self):
        self.seed()
        for where in ("api_key", "header"):
            s = pw.PolicySession(self.home)
            shown = json.loads(s.text("llm"))
            if where == "api_key":
                shown["api_key"] = "brand-new-literal-key"
            else:
                shown["extra_headers"]["X-New"] = "brand-new-header-value"
            s.set_text("llm", json.dumps(shown))
            r = s.save()
            self.assertEqual((r.ok, r.area, r.field), (False, "llm_key", "llm"), where)
            self.assertIn(pw.ERROR_TEXT["llm_key"], r.message)
            self.assertNotIn("brand-new", r.message + repr(s.snapshot()))                     # 상태 줄에는 적은 값을 다시 쓰지 않는다
            self.assertEqual(config.read_config(self.home)["llm"], self.llm)                 # 아무것도 쓰지 않았다

    def test_a_mask_in_a_place_that_never_had_a_secret_is_refused(self):
        s = pw.PolicySession(self.home)
        for text in ('{"api_key": "%s"}' % (pw.MASK_TEXT % 5),
                     '{"extra_headers": {"X": "%s"}}' % (pw.MASK_TEXT % 5)):
            s.set_text("llm", text)
            c = s.validate()
            self.assertEqual((c.ok, c.area, c.field), (False, "llm_key", "llm"), text)
        self.seed()
        s = pw.PolicySession(self.home)
        shown = json.loads(s.text("llm"))
        shown["extra_headers"]["X-Moved"] = shown["extra_headers"].pop("X-Kit-Auth")        # 가린 표시를 다른 이름으로 옮김
        s.set_text("llm", json.dumps(shown))
        self.assertEqual(s.validate().area, "llm_key")

    def test_a_typed_env_reference_goes_to_configs_own_refusal(self):
        s = self.fresh(llm='{"base_url": "http://example.com/v1", "model": "m", "api_key": "{env:SOME_NAME}"}')
        c = s.validate()
        self.assertEqual((c.ok, c.area), (False, "llm"))
        self.assertIn("{file:", c.message)

    def test_a_secret_never_reaches_the_result_line(self):
        self.seed()
        steps = [("text", "words", "새단어(가상)"), ("save",), ("close",)]
        with mock.patch.object(pw, "create_view", return_value=FakeView(steps)):
            code, line = pw.main_policy(self.home)
        self.assertEqual(code, 0)
        self.assertNotIn(self.SECRET, line)
        self.assertNotIn(self.HEADER, line)
        self.assertEqual(json.loads(line)["counts"]["llm"], True)

    def test_a_stored_secret_with_a_broken_config_around_it_still_never_shows(self):
        """읽을 수 없는 llm (모양이 틀림) 은 가릴 수 없으니 비운 칸으로 둔다 - 글자 그대로 보이지 않는다."""
        self.seed()
        s = pw.PolicySession(self.home)
        self.assertNotIn(self.SECRET, s.text("llm"))


# ─────────────────────────────────────────────────────────────── 실데이터 (AL-10)

class TestRealData(Base):
    def test_the_phrase_is_fixed(self):
        self.assertEqual(pw.REAL_DATA_PHRASE, "보안 승인 받음")

    def test_without_the_phrase_it_does_not_turn_on_and_says_why(self):
        s = pw.PolicySession(self.home)
        self.assertFalse(s.toggle_real_data(True))
        self.assertFalse(s.real_data)
        snap = s.snapshot()
        self.assertEqual(snap.level, "alert")
        self.assertIn(pw.REAL_DATA_PHRASE, snap.message)
        self.assertIn(pw.FIELD_LABEL["real_data"], snap.message)
        self.assertFalse(snap.real_data)
        self.assertEqual(s.take_focus(), "real_confirm")                   # 확인 글 칸으로 안내
        self.assertIsNone(s.take_focus())                                    # 한 번만
        self.assertFalse(s.dirty)

    def test_only_the_exact_phrase_turns_it_on(self):
        s = pw.PolicySession(self.home)
        for near in ("", "보안승인받음", "보안 승인 받음 ", " 보안 승인 받음", "보안 승인 받음.", "승인 받음", "보안  승인 받음",
                     "보안 승인 받음\n", "보안\u00a0승인 받음", "보안\u3000승인 받음", "보안 승인 받음\u200b", "BOAN 승인 받음",
                     "보안 승인 받았음"):
            s.set_real_confirm(near)
            self.assertFalse(s.toggle_real_data(True), repr(near))
            self.assertFalse(s.real_data, repr(near))
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertTrue(s.toggle_real_data(True))
        self.assertTrue(s.real_data)
        self.assertTrue(s.dirty)

    def test_the_phrase_alone_does_not_turn_it_on(self):
        s = self.fresh()
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertFalse(s.real_data)
        self.assertTrue(s.save().ok)
        self.assertFalse(config.counts(self.home)["real_data"])

    def test_turned_on_with_the_phrase_it_is_saved(self):
        s = self.fresh()
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertTrue(s.toggle_real_data(True))
        r = s.save()
        self.assertTrue(r.ok, r.message)
        self.assertTrue(r.counts["real_data"])
        self.assertTrue(config.load_state(self.home)["real_data"])
        self.assertIn("실데이터 켜짐", r.message)

    def test_typing_the_phrase_clears_the_refusal_and_the_turn_on_works(self):
        s = pw.PolicySession(self.home)
        s.toggle_real_data(True)
        self.assertEqual(s.snapshot().level, "alert")
        s.set_real_confirm("보안 승인")                                              # 아직 틀렸다 - 안내는 그대로
        self.assertEqual(s.snapshot().level, "alert")
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertEqual((s.snapshot().level, s.snapshot().message), ("", pw.TEXT_IDLE))
        self.assertTrue(s.toggle_real_data(True))
        self.assertEqual((s.snapshot().level, s.snapshot().message), ("", pw.TEXT_IDLE))

    def test_a_successful_turn_on_clears_the_refusal_even_if_the_phrase_was_typed_before(self):
        s = pw.PolicySession(self.home)
        s.toggle_real_data(True)
        s._message_field = "real_data"
        s._real_confirm = pw.REAL_DATA_PHRASE                                       # 칸으로 거치지 않고 글만 둔 상태
        self.assertTrue(s.toggle_real_data(True))
        self.assertEqual((s.snapshot().level, s.snapshot().message), ("", pw.TEXT_IDLE))

    def test_a_success_does_not_clear_an_unrelated_error(self):
        s = self.fresh(monthly_budget_usd="abc")
        self.assertFalse(s.save().ok)
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        s.toggle_real_data(True)
        self.assertEqual(s.snapshot().level, "alert")

    def test_clearing_the_phrase_after_turning_it_on_blocks_the_save(self):
        s = self.fresh()
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        s.toggle_real_data(True)
        s.set_real_confirm("")
        r = s.save()
        self.assertFalse(r.ok)
        self.assertEqual((r.area, r.field), ("real_data", "real_confirm"))
        self.assertFalse(os.path.exists(self.home))                          # 아무것도 쓰지 않았다
        self.assertEqual(s.take_focus(), "real_confirm")

    def test_turning_off_one_that_was_on_needs_no_confirmation(self):
        config.apply_state(self.home, self.state(real_data=True))
        s = pw.PolicySession(self.home)
        self.assertTrue(s.real_data)
        self.assertTrue(s.toggle_real_data(False))
        self.assertFalse(s.real_data)
        self.assertTrue(s.dirty)
        r = s.save()
        self.assertTrue(r.ok)
        self.assertFalse(config.counts(self.home)["real_data"])

    def test_turning_it_back_on_after_turning_it_off_needs_no_confirmation_when_it_was_on_at_the_start(self):
        config.apply_state(self.home, self.state(real_data=True))
        s = pw.PolicySession(self.home)
        s.toggle_real_data(False)
        self.assertTrue(s.toggle_real_data(True))
        self.assertTrue(s.real_data)
        self.assertFalse(s.dirty)
        self.assertTrue(s.save().ok)
        self.assertTrue(config.counts(self.home)["real_data"])

    def test_an_already_on_value_stays_on_without_the_phrase(self):
        config.apply_state(self.home, self.state(real_data=True))
        s = pw.PolicySession(self.home)
        self.assertTrue(s.validate().ok)
        self.assertTrue(s.save().ok)
        self.assertTrue(config.counts(self.home)["real_data"])

    def test_after_the_save_the_box_cannot_change(self):
        s = self.saved_session()
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertFalse(s.toggle_real_data(True))
        self.assertFalse(s.real_data)


# ─────────────────────────────────────────────────────────────── 고치기 도구

class TestEditing(Base):
    def test_set_text_reports_whether_it_changed_and_counts_lines(self):
        s = pw.PolicySession(self.home)
        self.assertTrue(s.set_text("words", "a1\n\nb2\n  \nc3"))
        self.assertEqual(s.line_count("words"), 3)
        self.assertFalse(s.set_text("words", "a1\n\nb2\n  \nc3"))
        self.assertEqual(s.snapshot().lines[0], ("words", 3))

    def test_an_unknown_field_or_a_non_text_is_a_programming_error(self):
        s = pw.PolicySession(self.home)
        with self.assertRaises(KeyError):
            s.set_text("nope", "x")
        with self.assertRaises(TypeError):
            s.set_text("words", ["x"])
        with self.assertRaises(TypeError):
            s.set_real_confirm(None)
        with self.assertRaises(KeyError):
            s.append_line("llm", "x")

    def test_append_line_adds_one_line_once(self):
        s = pw.PolicySession(self.home)
        self.assertTrue(s.append_line("raw_dirs", self.raw))
        self.assertTrue(s.append_line("raw_dirs", os.path.join(self.tmp, "second")))
        self.assertFalse(s.append_line("raw_dirs", self.raw))                 # 이미 있다
        self.assertEqual(s.snapshot().level, "info")
        self.assertEqual(s.snapshot().message, pw.TEXT_LINE_DUP)
        self.assertEqual(s.text("raw_dirs").split("\n"), [self.raw, os.path.join(self.tmp, "second")])
        self.assertEqual(s.line_count("raw_dirs"), 2)
        self.assertTrue(s.dirty)

    def test_append_line_after_existing_text_with_blank_edges(self):
        s = pw.PolicySession(self.home)
        s.set_text("raw_dirs", "/a\n\n  \n")
        s.append_line("raw_dirs", " /b ")
        self.assertEqual(s.text("raw_dirs"), "/a\n/b")

    def test_append_line_ignores_an_empty_or_multi_line_value(self):
        s = pw.PolicySession(self.home)
        for line in ("", "   ", "a\nb"):
            self.assertFalse(s.append_line("raw_dirs", line), repr(line))
        self.assertEqual(s.text("raw_dirs"), "")

    def test_the_message_after_adding_names_the_field_and_not_the_line(self):
        s = pw.PolicySession(self.home)
        s.append_line("raw_dirs", self.raw)
        self.assertEqual(s.snapshot().message, pw.TEXT_LINE_ADDED % pw.FIELD_LABEL["raw_dirs"])
        self.assertNotIn("kitraw", s.snapshot().message)

    def test_the_example_goes_in_only_when_the_command_is_empty(self):
        s = pw.PolicySession(self.home)
        self.assertTrue(s.fill_example())
        self.assertEqual(s.text("worker_command"), pw.WORKER_EXAMPLE)
        self.assertEqual(s.snapshot().message, pw.TEXT_EXAMPLE_DONE)
        s.set_text("worker_command", '["mine","{prompt}"]')
        self.assertFalse(s.fill_example())                                       # 적어 둔 것을 지우지 않는다
        self.assertEqual(s.text("worker_command"), '["mine","{prompt}"]')
        self.assertEqual(s.snapshot().message, pw.TEXT_EXAMPLE_KEPT)

    def test_the_example_is_a_valid_command(self):
        s = self.fresh()
        s.set_text("worker_command", "")
        s.fill_example()
        c = s.validate()
        self.assertTrue(c.ok, c.message)
        self.assertEqual(c.state["worker_command"], ["opencode", "run", "--dir", "{cwd}", "{prompt}"])

    def test_the_web_search_flag(self):
        s = pw.PolicySession(self.home)
        self.assertTrue(s.web_search)
        self.assertFalse(s.set_web_search(False))
        self.assertEqual(s.snapshot().web_search, False)
        self.assertTrue(s.dirty)
        self.assertTrue(s.set_web_search(1))

    def test_editing_the_flagged_field_clears_its_old_error_but_other_edits_do_not(self):
        s = self.fresh(raw_dirs="상대/경로")
        self.assertFalse(s.save().ok)
        self.assertEqual(s.snapshot().level, "alert")
        s.set_text("words", s.text("words") + "\n더단어(가상)")                         # 다른 칸을 고친다 - 오류는 그대로
        s.set_web_search(False)
        self.assertEqual(s.snapshot().level, "alert")
        s.set_text("raw_dirs", self.raw)                                               # 틀렸다고 한 칸을 고친다
        self.assertEqual((s.snapshot().level, s.snapshot().message), ("", pw.TEXT_IDLE))
        self.assertTrue(s.save().ok)

    def test_a_save_attempt_clears_the_wrong_lines_when_the_field_is_edited(self):
        s = self.fresh(patterns="(\nok")
        self.assertFalse(s.save().ok)
        self.assertEqual(s.bad_lines("patterns"), [1])
        s.set_text("patterns", "ok")
        self.assertEqual(s.bad_lines("patterns"), [])


# ─────────────────────────────────────────────────────────────── 저장

class TestSave(Base):
    def test_save_writes_what_the_person_typed_and_reads_it_back(self):
        s = self.fresh()
        r = s.save()
        self.assertTrue(r.ok, r.message)
        self.assertTrue(r.changed)
        self.assertEqual(r.warnings, [])
        self.assertEqual(r.counts, config.counts(self.home))
        self.assertEqual((r.counts["dictionary"], r.counts["raw_dirs"], r.counts["inner_tools"], r.counts["lib_allow"],
                          r.counts["patterns"]), (2, 1, 1, 1, 1))
        self.assertEqual((r.counts["web_search"], r.counts["real_data"], r.counts["worker"], r.counts["llm"],
                          r.counts["room_path"]), (True, False, True, False, True))
        self.assertEqual(sorted(os.listdir(self.home)), ["config.json", "dictionary.json"])
        st = config.load_state(self.home)
        self.assertEqual(st["words"], [WORD_A, WORD_B])
        self.assertEqual(st["worker_command"], ["opencode", "run", "--dir", "{cwd}", "{prompt}"])
        self.assertEqual((s.saved, s.finished), (True, False))
        self.assertEqual(s.counts, r.counts)

    def test_the_status_after_a_save_has_counts_and_no_words_or_paths(self):
        s = self.fresh(llm=json.dumps({"base_url": "http://example.com/v1", "model": "kit-model",
                                        "api_key": "{file:%s}" % self.key.replace("\\", "\\\\")}))
        r = s.save()
        self.assertTrue(r.ok, r.message)
        snap = s.snapshot()
        self.assertEqual(snap.level, "ok")
        self.assertTrue(snap.locked)
        self.assertFalse(snap.save_enabled)
        self.assertEqual(snap.message, r.message)
        lines = r.message.split("\n")
        self.assertEqual(lines[0], pw.TEXT_SAVED)
        self.assertIn("사전 2", lines[1])
        self.assertIn("llm 있음", lines[1])
        for leak in ("KITWORD", "가람", "kitraw", "kitkey", "innerx", "InnerX", "opencode", "kitlot", "pandas", "kit-model",
                     "example.com", self.tmp):
            self.assertNotIn(leak, r.message)

    def test_a_save_without_changes_is_not_blocked_and_says_so(self):
        config.apply_state(self.home, self.state())
        before = self.read_files()
        s = pw.PolicySession(self.home)
        self.assertFalse(s.dirty)
        r = s.save()
        self.assertTrue(r.ok)
        self.assertFalse(r.changed)
        self.assertEqual(r.message.split("\n")[0], pw.TEXT_UNCHANGED)
        self.assertEqual(self.read_files(), before)                                # 같은 내용 그대로
        self.assertTrue(s.saved)

    def test_a_first_save_of_a_blank_window_creates_the_files_and_says_unchanged(self):
        s = pw.PolicySession(self.home)
        r = s.save()
        self.assertTrue(r.ok)
        self.assertFalse(r.changed)
        self.assertEqual(sorted(os.listdir(self.home)), ["config.json", "dictionary.json"])
        self.assertEqual(sorted(r.warnings), ["raw_empty", "words_empty"])
        self.assertIn(pw.TEXT_WARN_MARK + pw.WARN_TEXT["words_empty"], r.message)

    def test_the_same_input_that_was_validated_is_written_so_no_warning_is_lost(self):
        """정리한 값을 넘기면 두 글자 미만 항목이 이미 빠져 있어서 short 경고가 사라진다."""
        s = self.fresh(words="a\nb\n%s\n%s" % (WORD_A, WORD_B))
        checked = s.validate()
        r = s.save()
        self.assertTrue(r.ok)
        self.assertEqual(checked.warnings, ["short"])
        self.assertEqual(r.warnings, ["short"])
        self.assertEqual(s.warnings, ["short"])
        self.assertIn(pw.WARN_TEXT["short"], r.message)
        self.assertEqual(config.counts(self.home)["dictionary"], 2)

    def test_save_passes_config_the_validated_input(self):
        s = self.fresh()
        want = s._build_state()
        with mock.patch.object(config, "apply_state", wraps=config.apply_state) as apply:
            self.assertTrue(s.save().ok)
        apply.assert_called_once_with(self.home, want)

    def test_a_wrong_field_writes_nothing_and_tells_the_person(self):
        s = self.fresh(raw_dirs="상대/" + MARK)
        r = s.save()
        self.assertFalse(r.ok)
        self.assertEqual((r.area, r.field), ("raw_dirs", "raw_dirs"))
        self.assertFalse(os.path.exists(self.home))
        self.assertFalse(s.saved)
        snap = s.snapshot()
        self.assertEqual((snap.level, snap.message, snap.locked), ("alert", r.message, False))
        self.assertTrue(snap.save_enabled)
        self.assertIn(pw.FIELD_LABEL["raw_dirs"], r.message)
        self.assertNotIn(MARK, r.message)
        self.assertEqual(s.take_focus(), "raw_dirs")
        self.assertEqual(s.bad_lines("raw_dirs"), [1])

    def test_fix_and_save_again(self):
        s = self.fresh(raw_dirs="상대/경로")
        self.assertFalse(s.save().ok)
        s.set_text("raw_dirs", self.raw)
        r = s.save()
        self.assertTrue(r.ok, r.message)
        self.assertEqual((s.snapshot().level, s.snapshot().locked), ("ok", True))

    def test_a_second_save_is_the_same_result_and_writes_nothing_more(self):
        s = self.saved_session()
        before = self.read_files()
        first = s.save()
        with mock.patch.object(config, "apply_state") as apply:
            second = s.save()
        apply.assert_not_called()
        self.assertEqual(first, second)
        self.assertEqual(self.read_files(), before)

    def test_after_the_save_nothing_can_be_edited(self):
        s = self.saved_session()
        before = s.text("words")
        self.assertFalse(s.set_text("words", "다른단어"))
        self.assertFalse(s.append_line("raw_dirs", "/x"))
        self.assertFalse(s.fill_example())
        self.assertEqual(s.text("words"), before)
        self.assertTrue(s.set_web_search(False))                                      # 저장한 값 (켜짐) 을 그대로 돌려준다
        self.assertTrue(s.web_search)

    def test_a_write_failure_is_told_and_can_be_retried(self):
        s = self.fresh()
        with mock.patch.object(config, "apply_state", side_effect=OSError("disk")):
            r = s.save()
        self.assertFalse(r.ok)
        self.assertEqual(r.area, "write")
        self.assertEqual(r.message, pw.TEXT_WRITE_FAILED)
        self.assertEqual((s.saved, s.snapshot().level), (False, "alert"))
        self.assertTrue(s.save().ok)

    def test_a_config_that_became_newer_is_not_overwritten(self):
        s = self.fresh()
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            json.dump({"format": 2}, f)
        r = s.save()
        self.assertFalse(r.ok)
        self.assertEqual((r.area, r.message), ("newer", pw.TEXT_NEWER))
        with open(config.config_path(self.home)) as f:
            self.assertEqual(json.load(f), {"format": 2})
        self.assertFalse(s.saved)

    def test_an_error_config_raises_when_the_window_state_was_not_valid_is_told_too(self):
        s = self.fresh()
        with mock.patch.object(config, "apply_state", side_effect=config.ConfigError("raw_dirs")):
            r = s.save()
        self.assertEqual((r.ok, r.area), (False, "raw_dirs"))
        self.assertIn(pw.FIELD_LABEL["raw_dirs"], r.message)

    def test_an_error_code_the_window_does_not_know_still_gets_a_neutral_line(self):
        s = self.fresh()
        with mock.patch.object(config, "validate_state", side_effect=config.ConfigError("brand_new_area")):
            c = s.validate()
            r = s.save()
        self.assertEqual((c.ok, c.area, c.field), (False, "brand_new_area", ""))
        self.assertTrue(c.message.startswith("정책 - "))
        self.assertNotIn("brand_new_area", c.message)
        self.assertFalse(r.ok)
        self.assertEqual(r.message, c.message)
        self.assertIsNone(s.take_focus() or None)
        self.assertFalse(os.path.exists(self.home))

    def test_an_unreadable_result_is_not_a_save(self):
        s = self.fresh()
        with mock.patch.object(config, "apply_state", return_value=({"error": "read"}, [])):
            r = s.save()
        self.assertFalse(r.ok)
        self.assertEqual(r.message, pw.TEXT_READBACK)
        self.assertFalse(s.saved)

    def test_unknown_keys_of_the_config_are_kept(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "transport": {"default": "room"}, "policy": {"daily_cap": 7}}, f)
        self.assertTrue(self.fresh().save().ok)
        cfg = config.read_config(self.home)
        self.assertEqual(cfg["transport"], {"default": "room"})
        self.assertEqual(cfg["policy"]["daily_cap"], 7)

    def test_a_blank_llm_leaves_the_current_llm_alone(self):
        llm = {"base_url": "http://example.com/v1", "model": "kit-model"}
        config.apply_state(self.home, self.state(llm=llm))
        s = pw.PolicySession(self.home)
        s.set_text("llm", "")
        s.set_text("words", s.text("words") + "\n새단어(가상)")
        self.assertTrue(s.save().ok)
        self.assertEqual(config.read_config(self.home)["llm"], llm)

    def test_the_session_never_writes_before_save(self):
        s = self.fresh()
        s.validate()
        s.request_close()
        s.request_close()
        self.assertFalse(os.path.exists(self.home))


# ─────────────────────────────────────────────────────────────── 닫기

class TestClose(Base):
    def test_nothing_changed_closes_at_once(self):
        s = pw.PolicySession(self.home)
        self.assertTrue(s.request_close())
        self.assertTrue(s.finished)
        self.assertFalse(s.saved)

    def test_unsaved_changes_are_asked_once_then_it_closes(self):
        s = self.fresh()
        self.assertFalse(s.request_close())
        self.assertFalse(s.finished)
        snap = s.snapshot()
        self.assertEqual(snap.level, "ask")
        self.assertIn("저장하지 않고 닫을까요", snap.message)
        self.assertEqual(snap.close_label, "저장 안 하고 닫기")
        self.assertTrue(s.request_close())
        self.assertTrue(s.finished)
        self.assertFalse(s.saved)
        self.assertFalse(os.path.exists(self.home))

    def test_an_edit_after_the_question_asks_again(self):
        s = self.fresh()
        s.request_close()
        s.set_text("words", s.text("words") + "\n더단어(가상)")
        self.assertEqual((s.snapshot().level, s.snapshot().close_label), ("", "닫기"))
        self.assertFalse(s.request_close())
        self.assertTrue(s.request_close())

    def test_a_toggle_after_the_question_asks_again(self):
        s = self.fresh()
        s.request_close()
        s.set_web_search(False)
        self.assertFalse(s.request_close())

    def test_a_save_attempt_resets_the_question(self):
        s = self.fresh(raw_dirs="상대/경로")
        s.request_close()
        s.save()
        self.assertFalse(s.request_close())

    def test_after_a_save_it_closes_at_once(self):
        s = self.saved_session()
        self.assertTrue(s.request_close())
        self.assertTrue(s.finished)
        self.assertEqual(s.snapshot().close_label, "닫기")

    def test_finished_stays_finished(self):
        s = pw.PolicySession(self.home)
        s.request_close()
        self.assertTrue(s.request_close())


# ─────────────────────────────────────────────────────────────── diode.py policy 의 몸통

class TestMain(Base):
    def run_main(self, view, home=None):
        with mock.patch.object(pw, "create_view", return_value=view):
            return pw.main_policy(home or self.home)

    def script(self, *extra):
        steps = [("text", key, text) for key, text in self.texts().items()]
        return steps + list(extra)

    def test_a_save_gives_the_counts_and_the_warnings(self):
        view = FakeView(self.script(("save",), ("close",)))
        code, line = self.run_main(view)
        self.assertEqual(code, 0)
        data = json.loads(line)
        self.assertEqual(list(data), ["saved", "counts", "warnings"])
        self.assertIs(data["saved"], True)
        self.assertEqual(data["counts"], config.counts(self.home))
        self.assertEqual(data["warnings"], [])
        self.assertEqual((data["counts"]["dictionary"], data["counts"]["raw_dirs"]), (2, 1))
        self.assertTrue(view.ran)
        self.assertTrue(view.saves[0].ok)

    def test_the_result_has_no_word_path_or_command(self):
        llm = json.dumps({"base_url": "http://example.com/v1", "model": "kit-model",
                          "api_key": "{file:%s}" % self.key.replace("\\", "\\\\")})
        steps = [("text", k, v) for k, v in self.texts(llm=llm, worker_cwd=os.path.join(self.tmp, "kitwork")).items()]
        code, line = self.run_main(FakeView(steps + [("save",), ("close",)]))
        self.assertEqual(code, 0)
        self.assertEqual(line, line.encode("ascii").decode("ascii"))
        self.assertNotIn("\n", line)
        for leak in ("KITWORD", "가람", "kitraw", "kitkey", "kitwork", "innerx", "InnerX", "opencode", "kitlot", "pandas",
                     "kit-model", "example.com", "{cwd}", "{prompt}", self.tmp):
            self.assertNotIn(leak, line)
        counts = json.loads(line)["counts"]
        for key, value in counts.items():
            self.assertTrue(isinstance(value, bool) or (isinstance(value, int) and value >= 0), key)
        self.assertEqual(set(counts), {"dictionary", "raw_dirs", "inner_tools", "lib_allow", "patterns", "web_search",
                                       "real_data", "derived_level", "worker", "llm", "room_path"})

    def test_a_warning_goes_out_as_its_code(self):
        steps = [("text", k, v) for k, v in self.texts(raw_dirs=os.path.join(self.tmp, "없는폴더")).items()]
        code, line = self.run_main(FakeView(steps + [("save",), ("close",)]))
        self.assertEqual((code, json.loads(line)["warnings"]), (0, ["raw_missing"]))
        self.assertNotIn("없는폴더", line)

    def test_closing_without_saving_is_not_saved_and_exit_3(self):
        view = FakeView(self.script(("close",), ("close",)))
        self.assertEqual(self.run_main(view), (3, NOT_SAVED))
        self.assertEqual(view.closes, [False, True])                                  # 한 번 묻고 닫는다
        self.assertFalse(os.path.exists(self.home))

    def test_closing_a_window_nobody_touched_is_not_saved_either(self):
        self.assertEqual(self.run_main(FakeView([("close",)])), (3, NOT_SAVED))

    def test_a_save_that_failed_validation_is_not_a_save(self):
        steps = [("text", k, v) for k, v in self.texts(raw_dirs="상대/경로").items()]
        view = FakeView(steps + [("save",), ("close",), ("close",)])
        self.assertEqual(self.run_main(view), (3, NOT_SAVED))
        self.assertFalse(view.saves[0].ok)
        self.assertFalse(os.path.exists(self.home))

    def test_a_save_after_a_fix_counts(self):
        steps = [("text", k, v) for k, v in self.texts(raw_dirs="상대/경로").items()]
        view = FakeView(steps + [("save",), ("text", "raw_dirs", self.raw), ("save",), ("close",)])
        code, line = self.run_main(view)
        self.assertEqual((code, json.loads(line)["saved"]), (0, True))

    def test_a_view_that_ends_before_the_person_closes_is_an_error(self):
        view = FakeView(self.script(("save",)))                              # 닫지 않고 끝난 화면
        self.assertEqual(self.run_main(view), (1, E20))
        self.assertEqual(self.run_main(FakeView([])), (1, E20))

    def test_the_window_that_cannot_open_is_e07(self):
        with mock.patch.object(pw, "create_view", side_effect=pw.WindowUnavailable("x")):
            self.assertEqual(pw.main_policy(self.home), (1, E07))
        self.assertFalse(os.path.exists(self.home))

    def test_a_view_that_raises_while_running_is_e07_or_e20(self):
        self.assertEqual(self.run_main(FakeView([("raise", pw.WindowUnavailable("tk"))])), (1, E07))
        for exc in (RuntimeError("x"), ValueError("x"), KeyboardInterrupt(), OSError("x")):
            self.assertEqual(self.run_main(FakeView([("raise", exc)])), (1, E20), repr(exc))
        self.assertEqual(self.run_main(FakeView(self.script(("save",), ("close",)), fail_after=RuntimeError("x"))), (1, E20))

    def test_a_newer_config_is_not_opened_and_says_so(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            json.dump({"format": 2}, f)
        with mock.patch.object(pw, "create_view") as create:
            self.assertEqual(pw.main_policy(self.home), (1, '{"saved": false, "error": "E-20", "code": "newer"}'))
            create.assert_not_called()
        with open(config.config_path(self.home)) as f:
            self.assertEqual(json.load(f), {"format": 2})

    def test_a_home_that_cannot_be_read_is_e20(self):
        with mock.patch.object(pw, "create_view") as create:
            for home in (None, 5, b"x" * 3 + b"\xff"):
                self.assertEqual(pw.main_policy(home), (1, E20), repr(home))
            create.assert_not_called()
        with mock.patch.object(config, "load_state_tolerant", side_effect=OSError("x")):
            self.assertEqual(pw.main_policy(self.home), (1, E20))

    def test_a_broken_config_opens_and_a_save_sets_it_aside(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        view = FakeView(self.script(("save",), ("close",)))
        code, line = self.run_main(view)
        self.assertEqual((code, json.loads(line)["saved"]), (0, True))
        self.assertTrue(os.path.exists(config.config_path(self.home) + ".broken"))
        self.assertEqual(config.counts(self.home)["dictionary"], 2)

    def test_the_counts_that_cannot_be_read_back_are_e20_not_saved(self):
        view = FakeView(self.script(("save",), ("close",)))
        with mock.patch.object(config, "counts", return_value={"error": "read"}):
            self.assertEqual(self.run_main(view), (1, E20))

    def test_the_entry_point_takes_the_data_folder_only_and_ignores_the_environment(self):
        self.assertEqual(list(inspect.signature(pw.main_policy).parameters), ["home"])
        other = os.path.join(self.tmp, "other")
        with mock.patch.dict(os.environ, {"DIODE_HOME": other, "DIODE_POLICY": "skip", "HOME": other}):
            code, _ = self.run_main(FakeView(self.script(("save",), ("close",))))
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(self.home))
        self.assertFalse(os.path.exists(other))

    def test_nothing_is_printed(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.run_main(FakeView(self.script(("save",), ("close",))))
            self.run_main(FakeView([("raise", RuntimeError("x"))]))
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_every_result_line_is_a_known_shape(self):
        shapes = []
        shapes.append(self.run_main(FakeView(self.script(("save",), ("close",)))))
        shapes.append(self.run_main(FakeView([("close",)]), home=os.path.join(self.tmp, "x1")))
        shapes.append(self.run_main(FakeView([("raise", RuntimeError("x"))]), home=os.path.join(self.tmp, "x2")))
        with mock.patch.object(pw, "create_view", side_effect=pw.WindowUnavailable("x")):
            shapes.append(pw.main_policy(os.path.join(self.tmp, "x3")))
        got = {(code, tuple(json.loads(line))) for code, line in shapes}
        self.assertEqual(got, {(0, ("saved", "counts", "warnings")), (3, ("saved",)), (1, ("saved", "error"))})
        for code, line in shapes:
            self.assertEqual(json.loads(line)["saved"], code == 0)


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
    tk.filedialog = types.ModuleType("tkinter.filedialog")
    return tk


def fake_modules(tk):
    return {"tkinter": tk, "tkinter.font": tk.font, "tkinter.filedialog": tk.filedialog}


class TestNoWindow(Base):
    def test_no_display_is_e07_and_tkinter_is_not_even_loaded(self):
        with env_with(), mock.patch.object(pw, "_is_windows", return_value=False), mock.patch.dict(sys.modules):
            for name in [n for n in sys.modules if n.split(".")[0] in ("tkinter", "_tkinter")]:
                del sys.modules[name]
            self.assertEqual(pw.main_policy(self.home), (1, E07))
            self.assertFalse([n for n in sys.modules if n.split(".")[0] in ("tkinter", "_tkinter")])
        with env_with(DISPLAY=""), mock.patch.object(pw, "_is_windows", return_value=False):
            self.assertEqual(pw.main_policy(self.home), (1, E07))                      # 빈 DISPLAY 도 없는 것
        self.assertFalse(os.path.exists(self.home))

    def test_a_display_only_lets_the_window_try(self):
        with env_with(DISPLAY=":0"), mock.patch.object(pw, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertEqual(pw.main_policy(self.home), (1, E07))                      # tkinter 를 못 부름
            with self.assertRaises(pw.WindowUnavailable):
                pw.create_view()

    def test_the_wayland_display_counts_too(self):
        with env_with(WAYLAND_DISPLAY="wayland-0"), mock.patch.object(pw, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, {"tkinter": None}):
            with self.assertRaises(pw.WindowUnavailable) as cm:
                pw.create_view()
            self.assertEqual(str(cm.exception), "tkinter")                               # 화면은 있다고 보고 tkinter 에서 막힘

    def test_a_missing_tkinter_font_or_filedialog_is_e07(self):
        for missing in ("tkinter.font", "tkinter.filedialog"):
            with env_with(DISPLAY=":0"), mock.patch.object(pw, "_is_windows", return_value=False), \
                    mock.patch.dict(sys.modules, {missing: None}):
                self.assertEqual(pw.main_policy(self.home), (1, E07), missing)

    def test_a_tcl_error_is_e07(self):
        fake = fake_tkinter(None)
        with env_with(DISPLAY=":0"), mock.patch.object(pw, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, fake_modules(fake)):
            self.assertEqual(pw.main_policy(self.home), (1, E07))

    def test_another_error_when_opening_is_e20(self):
        fake = fake_tkinter(RuntimeError)
        with env_with(DISPLAY=":0"), mock.patch.object(pw, "_is_windows", return_value=False), \
                mock.patch.dict(sys.modules, fake_modules(fake)):
            self.assertEqual(pw.main_policy(self.home), (1, E20))

    def test_windows_does_not_look_for_a_display(self):
        with env_with(), mock.patch.object(pw, "_is_windows", return_value=True), \
                mock.patch.dict(sys.modules, {"tkinter": None}):
            with self.assertRaises(pw.WindowUnavailable) as cm:
                pw.create_view()
            self.assertEqual(str(cm.exception), "tkinter")

    def test_the_unavailable_error_is_the_same_class_as_the_confirm_windows(self):
        self.assertIs(pw.WindowUnavailable, confirm.WindowUnavailable)
        self.assertIs(pw.PALETTE, confirm.PALETTE)


# ─────────────────────────────────────────────────────────────── 창을 따로 떼어 띄우기

class TestLaunch(Base):
    def popen(self, windows):
        with mock.patch.object(pw, "_is_windows", return_value=windows), \
                mock.patch.object(subprocess, "Popen") as popen:
            popen.return_value.pid = 4242
            got = pw.launch_detached("pythonX", "/x/diode.py")
        return got, popen

    def test_the_command_is_python_diode_policy_and_nothing_else(self):
        for windows in (False, True):
            pid, popen = self.popen(windows)
            self.assertEqual(pid, 4242)
            self.assertEqual(popen.call_args[0], (["pythonX", "/x/diode.py", "policy"],))
            kw = popen.call_args[1]
            self.assertEqual((kw["stdin"], kw["stdout"], kw["stderr"]), (subprocess.DEVNULL,) * 3)
            self.assertNotIn("shell", kw)
            self.assertNotIn("env", kw)
            self.assertNotIn("cwd", kw)

    def test_on_a_unix_it_starts_a_new_session(self):
        _, popen = self.popen(False)
        kw = popen.call_args[1]
        self.assertIs(kw["start_new_session"], True)
        self.assertNotIn("creationflags", kw)

    def test_on_windows_it_is_detached_in_its_own_process_group(self):
        _, popen = self.popen(True)
        kw = popen.call_args[1]
        self.assertEqual(kw["creationflags"], 0x00000008 | 0x00000200)             # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        self.assertNotIn("start_new_session", kw)

    def test_the_finished_window_is_reaped_without_waiting_for_it(self):
        with mock.patch.object(pw, "_is_windows", return_value=False), mock.patch.object(subprocess, "Popen") as popen, \
                mock.patch.object(threading, "Thread") as thread:
            popen.return_value.pid = 1
            pw.launch_detached("p", "d.py")
        thread.assert_called_once_with(target=popen.return_value.wait)         # 기다리는 것은 따로 거두는 쪽이다 (부른 쪽이 아니다)
        self.assertIs(thread.return_value.daemon, True)
        thread.return_value.start.assert_called_once_with()
        popen.return_value.wait.assert_not_called()

    def test_a_thread_that_cannot_start_does_not_fail_the_launch(self):
        with mock.patch.object(pw, "_is_windows", return_value=False), mock.patch.object(subprocess, "Popen") as popen, \
                mock.patch.object(threading, "Thread") as thread:
            popen.return_value.pid = 7
            thread.return_value.start.side_effect = RuntimeError("can't start new thread")
            self.assertEqual(pw.launch_detached("p", "d.py"), 7)

    def test_a_launch_that_fails_is_raised(self):
        with mock.patch.object(subprocess, "Popen", side_effect=FileNotFoundError("x")):
            with self.assertRaises(OSError):
                pw.launch_detached("no-such-python", "diode.py")

    def test_the_caller_is_not_made_to_wait_and_the_child_gets_the_policy_command(self):
        """띄운 쪽은 기다리지 않는다 - 자식은 신호 파일이 생길 때까지 기다리고, 부른 쪽은 그 신호 파일을 만든다 (기다렸다면 영원히 못 만든다)."""
        child = os.path.join(self.tmp, "child.py")
        with open(child, "w") as f:
            f.write("import os, sys, time\n"
                    "here = os.path.dirname(os.path.abspath(__file__))\n"
                    "end = time.time() + 40\n"
                    "while not os.path.exists(os.path.join(here, 'go')) and time.time() < end:\n"
                    "    time.sleep(0.05)\n"
                    "with open(os.path.join(here, 'args.txt'), 'w') as out:\n"
                    "    out.write(' '.join(sys.argv[1:]) + '|' + str(os.getpid()))\n")
        go, args = os.path.join(self.tmp, "go"), os.path.join(self.tmp, "args.txt")

        def let_it_finish():
            with open(go, "w"):
                pass
        self.addCleanup(let_it_finish)
        pid = pw.launch_detached(sys.executable, child)
        self.assertIsInstance(pid, int)
        self.assertFalse(os.path.exists(args))                                        # 자식은 아직 기다리는 중인데 여기로 돌아왔다
        if os.name != "nt":
            self.assertEqual(os.getsid(pid), pid)                                   # 새 세션의 우두머리 = 부모 세션에서 떨어졌다
            self.assertNotEqual(os.getsid(pid), os.getsid(0))
        let_it_finish()
        end = time.time() + 30
        while not os.path.exists(args) and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(os.path.exists(args), "자식이 돌지 않았다")
        time.sleep(0.2)
        with open(args) as f:
            self.assertEqual(f.read(), "policy|%d" % pid)


# ─────────────────────────────────────────────────────────────── 건너뛰는 길이 없다 (AL-12) · 규칙

def _source():
    with open(PW_PY, "r", encoding="utf-8") as f:
        return f.read()


def _is_environ(node):
    return (isinstance(node, ast.Name) and node.id == "environ") or (isinstance(node, ast.Attribute) and node.attr == "environ")


def _const(node):
    if type(node).__name__ == "Index":                  # 3.8 의 ast 는 첨자 상수를 Index 로 감싼다
        node = node.value
    return node.value if isinstance(node, ast.Constant) else None


# works tools/works_check.py 의 색 규칙 (DESIGN.md › 02): 채도가 있으면 네이비 (190-230도) 나 라임 (75-110도) 이어야 한다
def color_ok(r, g, b):
    if (max(r, g, b) - min(r, g, b)) / 255 < 0.10:
        return True
    hue = int(round(colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360))
    return 190 <= hue <= 230 or 75 <= hue <= 110


class TestNoWayAround(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(_source())

    def test_the_entry_points_take_no_switches(self):
        self.assertEqual(list(inspect.signature(pw.main_policy).parameters), ["home"])
        self.assertEqual(list(inspect.signature(pw.create_view).parameters), [])
        self.assertEqual(list(inspect.signature(pw.PolicySession).parameters), ["home"])
        self.assertEqual(list(inspect.signature(pw.launch_detached).parameters), ["python", "diode_py"])
        self.assertEqual(list(inspect.signature(pw.TkView).parameters), ["tk_module"])

    def test_the_only_environment_read_is_the_display_check(self):
        """os.environ 은 화면이 있는지 보는 confirm.display_missing 에 넘길 때뿐이고, 그 함수가 읽는 것은 DISPLAY · WAYLAND_DISPLAY 뿐이다."""
        parents = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        found = [node for node in ast.walk(self.tree) if _is_environ(node) and not isinstance(parents.get(node), ast.Attribute)]
        self.assertEqual(len(found), 2)                          # main_policy 의 화면 확인 + can_open (띄우기 전 확인) 의 같은 확인
        for env in found:
            call = parents[env]
            self.assertIsInstance(call, ast.Call)
            self.assertEqual(getattr(call.func, "attr", None), "display_missing")
            self.assertIs(call.args[0], env)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("getenv", "putenv", "unsetenv") or (
                        node.func.attr in ("get", "setdefault", "pop", "update", "clear") and _is_environ(node.func.value)):
                    self.fail("환경 변수를 만짐 (줄 %d)" % node.lineno)
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                self.fail("환경 변수를 읽음 (줄 %d)" % node.lineno)
            if isinstance(node, ast.Attribute) and node.attr in ("argv", "orig_argv"):
                self.fail("명령줄 인자를 읽음 (줄 %d)" % node.lineno)
        keys = set()
        for node in ast.walk(ast.parse(inspect.getsource(confirm.display_missing))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get":
                keys.add(_const(node.args[0]))
        self.assertEqual(keys, {"DISPLAY", "WAYLAND_DISPLAY"})

    def test_the_module_reads_no_file_and_prints_nothing(self):
        allowed = {"collections", "json", "os", "re", "subprocess", "threading", "time", "tkinter"}
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module.split(".")[0])
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    self.assertNotIn(fn.id, ("open", "print", "input", "exec", "eval", "compile", "__import__"),
                                     "%s() 를 부름 (줄 %d)" % (fn.id, node.lineno))
                if isinstance(fn, ast.Attribute):
                    self.assertNotIn(fn.attr, ("write", "writelines", "write_text", "write_bytes", "read_text", "read_bytes",
                                               "dump", "load", "import_module"), "%s 를 부름 (줄 %d)" % (fn.attr, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr in ("stdout", "stderr", "stdin") \
                    and not (isinstance(node.value, ast.Name) and node.value.id == "subprocess"):
                self.fail("표준 입출력을 건드림 (줄 %d)" % node.lineno)
        self.assertLessEqual(names, allowed, names)

    def test_os_is_used_for_three_things_only(self):
        used = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                used.add(node.attr)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) \
                    and isinstance(node.value.value, ast.Name) and node.value.value.id == "os":
                used.add("%s.%s" % (node.value.attr, node.attr))
        self.assertEqual(used, {"name", "environ", "path", "path.normpath"})

    def test_subprocess_is_only_in_launch_detached(self):
        for func in [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]:
            uses = [n for n in ast.walk(func) if isinstance(n, ast.Name) and n.id == "subprocess"]
            self.assertEqual(bool(uses), func.name == "launch_detached", func.name)

    def test_the_only_writer_is_config_apply_state_inside_save(self):
        calls = []
        for cls in [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)]:
            for func in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                for node in ast.walk(func):
                    if isinstance(node, ast.Attribute) and node.attr == "apply_state":
                        calls.append((cls.name, func.name))
        total = [n for n in ast.walk(self.tree) if isinstance(n, ast.Attribute) and n.attr == "apply_state"]
        self.assertEqual(len(total), 1)                                       # 이 이름을 쓰는 곳은 모듈 전체에서 한 곳
        self.assertEqual(calls, [("PolicySession", "save")])

    def test_the_screen_never_talks_to_config(self):
        """저장 · 검증은 논리 (session) 가 하고 화면은 그리기만 한다 - 화면이 config 를 직접 부르는 길이 없다."""
        for cls in [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef) and n.name == "TkView"]:
            for node in ast.walk(cls):
                if isinstance(node, ast.Name) and node.id == "config":
                    self.fail("화면이 config 를 부름 (줄 %d)" % node.lineno)

    def test_no_name_offers_a_way_around(self):
        words = re.compile(r"fake|bypass|skip|silent|quiet|headless|unattended|assume|force|auto|noconfirm|yes", re.I)
        names = set(n for n in dir(pw) if not n.startswith("__"))
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            if isinstance(node, ast.arg):
                names.add(node.arg)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
        self.assertEqual([n for n in names if words.search(n)], [])

    def test_the_fake_screen_lives_only_in_the_tests(self):
        lib = os.path.join(ROOT, "diodelib")
        for name in sorted(os.listdir(lib)):
            if name.endswith(".py"):
                with open(os.path.join(lib, name), "r", encoding="utf-8") as f:
                    self.assertNotIn("FakeView", f.read(), name)

    def test_importing_the_module_does_not_load_tkinter(self):
        code = ("import sys; sys.path.insert(0, %r); import diodelib.policy_window; "
                "print('|'.join(n for n in sys.modules if n.split('.')[0] in ('tkinter', '_tkinter')))" % ROOT)
        p = subprocess.run([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual((p.returncode, p.stdout.decode().strip()), (0, ""), p.stderr.decode())

    def test_python38_syntax(self):
        ast.parse(_source(), filename=PW_PY, feature_version=(3, 8))
        with open(os.path.abspath(__file__), "r", encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 8))

    def test_colors_are_navy_lime_or_gray_never_red(self):
        src = _source()
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", src), [])             # 색 값은 confirm 의 팔레트에서만
        for name, value in pw.PALETTE.items():
            r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
            self.assertTrue(color_ok(r, g, b), name)
        banned = {"red", "orange", "yellow", "pink", "purple", "magenta", "brown", "crimson", "tomato", "gold", "violet",
                  "firebrick", "darkred", "salmon", "coral", "maroon"}
        palette_keys = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn(node.value.strip().lower(), banned)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in ("c", "PALETTE"):
                palette_keys.add(_const(node.slice))
        palette_keys.discard(None)
        self.assertTrue(palette_keys)
        self.assertLessEqual(palette_keys, set(pw.PALETTE))
        for name, entry in list(pw._CHIPS.items()) + [("fg", tuple(pw._STATUS_FG.values()))]:
            for key in entry if isinstance(entry, tuple) else ():
                if key not in ("EDIT", "OK", "ERR", "ASK"):
                    self.assertIn(key, pw.PALETTE, name)

    def test_no_emoji_or_wide_symbols_and_only_the_design_symbols(self):
        wide = {"\u2713", "\u26a0", "\u2605"}                               # DESIGN.md › 03: 체크 · 경고 · 별 기호는 폭 2칸
        for path in (PW_PY, os.path.abspath(__file__)):
            with open(path, "r", encoding="utf-8") as f:
                for ch in f.read():
                    self.assertFalse(0x1F000 <= ord(ch) <= 0x1FAFF or ch in wide, "%s: U+%04X" % (os.path.basename(path), ord(ch)))
        extra = set(ch for ch in _source() if ord(ch) > 127 and not (0xAC00 <= ord(ch) <= 0xD7A3))
        self.assertLessEqual(extra, {"\u00b7", "\u203a", "\u203c", "\u25cf", "\u25cb"})   # · › ‼ ● ○ (DESIGN.md › 03 의 기호)

    def test_the_fixed_phrases_are_in_the_window_code(self):
        src = _source()
        for want in ("정책 편집", "이 창에서만 바뀝니다 · 단어는 화면 밖으로 나가지 않습니다", "저장하지 않고 닫을까요", "보안 승인 받음",
                     "바뀐 것 없음", "01 DICT", "02 RAW", "03 TOOLS", "04 WORKER", "05 LIB", "06 OPTION", "폴더 고르기", "예시 넣기"):
            self.assertIn(want, src)

    def test_the_example_is_the_spec_example(self):
        self.assertEqual(json.loads(pw.WORKER_EXAMPLE), ["opencode", "run", "--dir", "{cwd}", "{prompt}"])


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
                 "highlightcolor", "selectbackground", "selectforeground", "troughcolor", "insertbackground",
                 "disabledbackground", "readonlybackground", "selectcolor")


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
        self.view = pw.TkView(tkinter)
        self.addCleanup(self.view.close)

    def open(self, saved=None, **typed):
        """저장해 둔 상태 (saved) 로 session 을 만들고 창을 연다. typed 는 연 뒤 칸에 직접 친다."""
        if saved is not None:
            config.apply_state(self.home, saved)
        self.session = pw.PolicySession(self.home)
        self.view.open(self.session)
        self.w = self.view.widgets
        for key, text in typed.items():
            self.type(key, text)
        return self.session

    def type(self, key, text):
        """칸에 글을 친다 (지우고 쓴다) - 위젯만 만진다."""
        widget = self.w[key]
        if widget.winfo_class() == "Text":
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        else:
            widget.delete(0, "end")
            widget.insert(0, text)
        self.view.root.update()

    def status(self):
        return self.w["status"]["text"]

    def marked(self, key, tag):
        """tag 로 표시된 줄 번호들 (한 줄 통째로 표시한다)."""
        ranges = [str(r) for r in self.w[key].tag_ranges(tag)]
        for start, end in zip(ranges[0::2], ranges[1::2]):
            self.assertTrue(start.endswith(".0"), start)
            self.assertEqual(end, self.w[key].index("%s.end" % start.split(".")[0]))
        return [int(r.split(".")[0]) for r in ranges[0::2]]

    def test_the_title_the_subtitle_and_the_zones(self):
        self.open()
        self.assertEqual(self.w["title"]["text"], "정책 편집")
        self.assertEqual(self.w["subtitle"]["text"], "이 창에서만 바뀝니다 · 단어는 화면 밖으로 나가지 않습니다")
        self.assertGreater(self.w["title"].winfo_reqheight(), self.w["subtitle"].winfo_reqheight())
        self.assertEqual(self.w["title"].master.grid_info()["row"], 0)             # 맨 위 구역
        chips = [wd["text"].strip() for wd in all_widgets(self.view.root) if wd.winfo_class() == "Label"]
        for chip in ("01 DICT", "02 RAW", "03 TOOLS", "04 WORKER", "05 LIB", "06 OPTION"):
            self.assertIn(chip, chips)
        titles = [wd["text"] for wd in all_widgets(self.view.root) if wd.winfo_class() == "Label"]
        for title in ("사전", "원자료 폴더", "안쪽 도구", "일꾼", "라이브러리", "선택"):
            self.assertIn(title, titles)
        for key in pw.TEXT_KEYS + ("real_confirm", "web_search", "real_data", "save", "close", "pick_dir", "example"):
            self.assertIn(key, self.w, key)

    def test_the_widget_kinds(self):
        self.open()
        for key in pw.LIST_KEYS + ("llm",):
            self.assertEqual(self.w[key].winfo_class(), "Text", key)
        for key in ("worker_command", "worker_cwd", "monthly_budget_usd", "room_path", "real_confirm"):
            self.assertEqual(self.w[key].winfo_class(), "Entry", key)
        for key in ("web_search", "real_data"):
            self.assertEqual(self.w[key].winfo_class(), "Checkbutton", key)

    def test_the_saved_values_are_in_the_widgets(self):
        self.open(saved=self.state(real_data=True))
        self.assertEqual(self.w["words"].get("1.0", "end-1c").split("\n"), [WORD_A, WORD_B])
        self.assertEqual(self.w["raw_dirs"].get("1.0", "end-1c"), self.raw)
        self.assertEqual(self.w["worker_command"].get(), pw.WORKER_EXAMPLE)
        self.assertEqual(self.w["monthly_budget_usd"].get(), "100")
        self.assertEqual(self.w["count_words"]["text"], "2줄")
        self.assertEqual(self.w["count_raw_dirs"]["text"], "1줄")
        self.assertTrue(self.w["real_data"]["text"].startswith("●"))
        self.assertTrue(self.w["web_search"]["text"].startswith("●"))
        self.assertEqual(self.w["real_confirm"].get(), "")
        self.assertFalse(self.session.dirty)

    def test_typing_tells_the_session_and_the_line_count_follows(self):
        s = self.open()
        self.type("words", "하나1\n\n둘2\n셋3")
        self.assertEqual(s.text("words"), "하나1\n\n둘2\n셋3")
        self.assertEqual(self.w["count_words"]["text"], "3줄")
        self.type("raw_dirs", self.raw)
        self.assertEqual(self.w["count_raw_dirs"]["text"], "1줄")
        self.type("worker_command", pw.WORKER_EXAMPLE)
        self.assertEqual(s.text("worker_command"), pw.WORKER_EXAMPLE)
        self.type("monthly_budget_usd", "12.5")
        self.assertEqual(s.text("monthly_budget_usd"), "12.5")
        self.assertTrue(s.dirty)

    def test_a_hash_line_stays_a_line(self):
        s = self.open()
        self.type("words", "#KITWORDALPHA")
        self.assertEqual(s.line_count("words"), 1)
        self.assertEqual(s.validate().state["words"], ["#KITWORDALPHA"])

    def test_save_writes_and_the_counts_read_back(self):
        s = self.open()
        for key, text in self.texts().items():
            self.type(key, text)
        self.w["save"].invoke()
        self.assertTrue(s.saved)
        counts = config.counts(self.home)
        self.assertEqual((counts["dictionary"], counts["raw_dirs"], counts["inner_tools"], counts["lib_allow"],
                          counts["patterns"], counts["worker"], counts["room_path"]), (2, 1, 1, 1, 1, True, True))
        self.assertEqual(config.load_state(self.home)["words"], [WORD_A, WORD_B])
        self.assertEqual(self.status().split("\n")[0], pw.TEXT_SAVED)
        self.assertIn("사전 2", self.status())
        self.assertEqual(self.w["status_chip"]["text"].strip(), "OK")

    def test_after_the_save_only_the_close_button_is_left_and_the_window_stays_open(self):
        s = self.open()
        for key, text in self.texts().items():
            self.type(key, text)
        self.w["save"].invoke()
        self.view.pump()
        self.assertFalse(self.w["save"].winfo_ismapped())
        self.assertTrue(self.w["close"].winfo_ismapped())
        self.assertEqual(str(self.w["close"]["state"]), "normal")
        self.assertIsNotNone(self.view.root)
        self.assertFalse(s.finished)                                                  # 자동으로 닫지 않는다
        for key in pw.TEXT_KEYS + ("real_confirm", "web_search", "real_data"):
            self.assertEqual(str(self.w[key]["state"]), "disabled", key)
        before = self.w["words"].get("1.0", "end-1c")
        self.w["words"].insert("end", "끼워 넣기")
        self.assertEqual(self.w["words"].get("1.0", "end-1c"), before)
        self.w["close"].invoke()
        self.assertTrue(s.finished)

    def test_an_unchanged_save_says_so(self):
        s = self.open(saved=self.state())
        self.w["save"].invoke()
        self.assertTrue(s.saved)
        self.assertEqual(self.status().split("\n")[0], pw.TEXT_UNCHANGED)

    def test_the_status_line_carries_warnings(self):
        self.open()
        for key, text in self.texts(words="a\n" + WORD_A, raw_dirs=os.path.join(self.tmp, "없는폴더")).items():
            self.type(key, text)
        self.w["save"].invoke()
        text = self.status()
        self.assertIn(pw.WARN_TEXT["short"], text)
        self.assertIn(pw.WARN_TEXT["raw_missing"], text)
        self.assertNotIn("없는폴더", text)

    def test_a_wrong_field_shows_err_names_the_field_moves_focus_and_marks_the_line(self):
        s = self.open()
        for key, text in self.texts(raw_dirs="%s\n상대/경로\n%s" % (self.raw, MARK)).items():
            self.type(key, text)
        self.w["save"].invoke()
        self.view.pump()
        self.assertFalse(s.saved)
        self.assertFalse(os.path.exists(self.home))
        self.assertEqual(self.w["status_chip"]["text"].strip(), "ERR")
        self.assertIn(pw.FIELD_LABEL["raw_dirs"], self.status())
        self.assertIn("(2째 줄 · 3째 줄)", self.status())
        self.assertNotIn(MARK, self.status())
        self.assertEqual(str(self.view.root.tk.call("focus", "-lastfor", ".")), str(self.w["raw_dirs"]))
        self.assertEqual(self.marked("raw_dirs", "bad"), [2, 3])
        self.assertEqual(str(self.w["save"]["state"]), "normal")                       # 고쳐서 다시 누를 수 있다
        self.type("raw_dirs", self.raw)
        self.assertEqual(self.w["raw_dirs"].tag_ranges("bad"), ())                      # 그 칸을 고치면 표시가 사라진다
        self.w["save"].invoke()
        self.assertTrue(s.saved)

    def test_hidden_characters_are_marked_blocked_and_named_with_brackets(self):
        s = self.open()
        for key, text in self.texts(words="%s\nKIT\u200bX\n%s\u00a0" % (WORD_A, WORD_B)).items():
            self.type(key, text)
        self.assertEqual(self.marked("words", "hidden"), [2, 3])
        self.w["save"].invoke()
        self.assertFalse(s.saved)
        self.assertFalse(os.path.exists(self.home))
        self.assertIn("[U+200B]", self.status())
        self.assertIn("[U+00A0]", self.status())
        self.assertIn("01 사전 2째 줄", self.status())
        self.assertEqual(self.w["status_chip"]["text"].strip(), "ERR")

    def test_the_hidden_mark_goes_away_when_the_character_is_removed(self):
        self.open()
        self.type("words", "KIT\u200bX")
        self.assertNotEqual(self.w["words"].tag_ranges("hidden"), ())
        self.type("words", "KITX")
        self.assertEqual(self.w["words"].tag_ranges("hidden"), ())

    def test_the_folder_button_adds_one_line_for_the_folder_the_person_picked(self):
        s = self.open()
        picked = os.path.join(self.tmp, "picked-folder")
        with mock.patch("tkinter.filedialog.askdirectory", return_value=picked) as ask:
            self.w["pick_dir"].invoke()
            self.w["pick_dir"].invoke()                                                # 같은 폴더를 또 골라도 한 줄
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(ask.call_args[1]["parent"], self.view.root)
        self.assertTrue(ask.call_args[1]["mustexist"])
        self.assertEqual(self.w["raw_dirs"].get("1.0", "end-1c"), os.path.normpath(picked))
        self.assertEqual(s.text("raw_dirs"), os.path.normpath(picked))
        self.assertEqual(self.w["count_raw_dirs"]["text"], "1줄")
        with mock.patch("tkinter.filedialog.askdirectory", return_value=os.path.join(self.tmp, "second")):
            self.w["pick_dir"].invoke()
        self.assertEqual(self.w["count_raw_dirs"]["text"], "2줄")
        self.assertEqual(len(self.w["raw_dirs"].get("1.0", "end-1c").split("\n")), 2)

    def test_a_folder_dialog_that_cannot_open_counts_as_cancelled(self):
        s = self.open()
        with mock.patch("tkinter.filedialog.askdirectory", side_effect=self.tk.TclError("no dialog")):
            self.w["pick_dir"].invoke()
        self.view.pump()
        self.assertEqual(s.text("raw_dirs"), "")
        self.assertFalse(s.finished)

    def test_cancelling_the_folder_dialog_changes_nothing(self):
        s = self.open()
        for cancelled in ("", (), None):
            with mock.patch("tkinter.filedialog.askdirectory", return_value=cancelled):
                self.w["pick_dir"].invoke()
        self.assertEqual(s.text("raw_dirs"), "")
        self.assertFalse(s.dirty)

    def test_the_example_button_fills_an_empty_command_and_keeps_a_typed_one(self):
        s = self.open()
        self.w["example"].invoke()
        self.assertEqual(self.w["worker_command"].get(), pw.WORKER_EXAMPLE)
        self.assertEqual(s.text("worker_command"), pw.WORKER_EXAMPLE)
        self.assertEqual(self.status(), pw.TEXT_EXAMPLE_DONE)
        self.type("worker_command", '["mine","{prompt}"]')
        self.w["example"].invoke()
        self.assertEqual(self.w["worker_command"].get(), '["mine","{prompt}"]')
        self.assertEqual(self.status(), pw.TEXT_EXAMPLE_KEPT)

    def test_the_web_search_key_toggles_and_shows_it(self):
        s = self.open()
        self.assertTrue(self.w["web_search"]["text"].startswith("●"))
        self.w["web_search"].invoke()
        self.assertFalse(s.web_search)
        self.assertTrue(self.w["web_search"]["text"].startswith("○"))
        self.w["web_search"].invoke()
        self.assertTrue(s.web_search)
        self.assertFalse(s.dirty)

    def test_the_real_data_key_refuses_without_the_phrase_and_goes_to_the_phrase_box(self):
        s = self.open()
        self.assertTrue(self.w["real_data"]["text"].startswith("○"))
        self.w["real_data"].invoke()
        self.assertFalse(s.real_data)
        self.assertTrue(self.w["real_data"]["text"].startswith("○"))                    # 켜지지 않았다
        self.assertEqual(self.view._vars["real_data"].get(), False)
        self.assertIn(pw.REAL_DATA_PHRASE, self.status())
        self.assertEqual(self.w["status_chip"]["text"].strip(), "ERR")
        self.assertEqual(str(self.view.root.tk.call("focus", "-lastfor", ".")), str(self.w["real_confirm"]))

    def test_the_real_data_key_turns_on_with_the_phrase_and_it_is_saved(self):
        s = self.open()
        for key, text in self.texts().items():
            self.type(key, text)
        self.type("real_confirm", pw.REAL_DATA_PHRASE)
        self.w["real_data"].invoke()
        self.assertTrue(s.real_data)
        self.assertTrue(self.w["real_data"]["text"].startswith("●"))
        self.w["save"].invoke()
        self.assertTrue(config.counts(self.home)["real_data"])

    def test_clearing_the_phrase_after_turning_on_blocks_the_save_in_the_window(self):
        s = self.open()
        for key, text in self.texts().items():
            self.type(key, text)
        self.type("real_confirm", pw.REAL_DATA_PHRASE)
        self.w["real_data"].invoke()
        self.type("real_confirm", "")
        self.w["save"].invoke()
        self.assertFalse(s.saved)
        self.assertIn(pw.REAL_DATA_PHRASE, self.status())
        self.assertFalse(os.path.exists(self.home))

    def test_turning_off_a_real_data_that_was_on_needs_no_phrase(self):
        s = self.open(saved=self.state(real_data=True))
        self.assertTrue(self.w["real_data"]["text"].startswith("●"))
        self.w["real_data"].invoke()
        self.assertFalse(s.real_data)
        self.w["save"].invoke()
        self.assertTrue(s.saved)
        self.assertFalse(config.counts(self.home)["real_data"])

    def test_close_asks_once_when_something_is_unsaved(self):
        s = self.open()
        self.type("words", "새단어(가상)")
        self.w["close"].invoke()
        self.assertFalse(s.finished)
        self.assertIn("저장하지 않고 닫을까요", self.status())
        self.assertEqual(self.w["close"]["text"], "저장 안 하고 닫기")
        self.assertEqual(self.w["status_chip"]["text"].strip(), "ASK")
        self.assertFalse(os.path.exists(self.home))
        self.w["close"].invoke()
        self.assertTrue(s.finished)
        self.assertFalse(s.saved)

    def test_closing_the_window_with_the_x_is_the_same_as_the_close_button(self):
        s = self.open()
        self.view.root.tk.call(self.view.root.protocol("WM_DELETE_WINDOW"))
        self.assertTrue(s.finished)                                                    # 고친 것이 없으니 바로
        self.view.close()
        self.view = pw.TkView(self.tk)
        s = self.open()
        self.type("words", "새단어(가상)")
        self.view.root.tk.call(self.view.root.protocol("WM_DELETE_WINDOW"))
        self.assertFalse(s.finished)
        self.view.root.tk.call(self.view.root.protocol("WM_DELETE_WINDOW"))
        self.assertTrue(s.finished)

    def test_enter_and_escape_do_nothing_on_their_own(self):
        s = self.open()
        self.type("words", "새단어(가상)")
        root = self.view.root
        for target in (self.w["save"], self.w["close"], root, self.w["real_confirm"], self.w["worker_command"]):
            target.focus_force()
            root.update()
            for sequence in ("<Return>", "<KP_Enter>", "<Escape>"):
                target.event_generate(sequence)
                root.update()
        self.assertFalse(s.saved)
        self.assertFalse(s.finished)
        self.assertFalse(os.path.exists(self.home))

    def test_tab_moves_the_focus_instead_of_typing_a_tab(self):
        self.open()
        text = self.w["words"]
        text.focus_force()
        self.view.root.update()
        text.event_generate("<Tab>")
        self.view.root.update()
        self.assertEqual(text.get("1.0", "end-1c"), "")
        self.assertNotEqual(str(self.view.root.tk.call("focus", "-lastfor", ".")), str(text))

    def test_the_first_focus_is_the_dictionary_box(self):
        self.open()
        self.view.root.update()
        self.assertEqual(str(self.view.root.tk.call("focus", "-lastfor", ".")), str(self.w["words"]))

    def test_the_body_scrolls_and_the_window_fits_the_screen(self):
        self.open()
        root = self.view.root
        root.update()
        canvas, body = self.w["canvas"], self.w["body"]
        self.assertLessEqual(root.winfo_reqheight(), root.winfo_screenheight() - pw.SCREEN_MARGIN_PX + 5)
        self.assertGreater(body.winfo_reqheight(), canvas.winfo_height())                  # 본문이 더 길어서 굴린다
        self.assertEqual(canvas.yview()[0], 0.0)
        for key in ("save", "close", "title", "status"):
            self.assertTrue(self.w[key].winfo_ismapped(), key)
        canvas.yview_scroll(5, "units")
        root.update()
        self.assertGreater(canvas.yview()[0], 0.0)
        self.view._reveal(self.w["llm"])
        root.update()
        self.assertGreater(canvas.yview()[0], 0.3)
        low = canvas.yview()[0]
        self.view._reveal(self.w["words"])
        root.update()
        self.assertLess(canvas.yview()[0], low)                                           # 사전 칸이 보이게 위로 굴렸다
        top = self.w["words"].winfo_rooty() - canvas.winfo_rooty()
        self.assertTrue(0 <= top < canvas.winfo_height())

    def test_a_stored_key_is_masked_everywhere_on_the_screen_and_kept_by_a_save(self):
        secret, header = "kit-literal-key-1234", "kit-header-value-5678"
        llm = {"base_url": "http://example.com/v1", "model": "kit-model", "api_key": secret,
               "extra_headers": {"X-Kit-Auth": header}}
        s = self.open(saved=self.state(llm=llm))
        shown = self.w["llm"].get("1.0", "end-1c")
        self.assertIn(pw.MASK_TEXT % len(secret), shown)
        self.assertIn(pw.MASK_TEXT % len(header), shown)
        self.w["words"].insert("end", "\n새단어(가상)")
        self.view.root.update()
        self.w["save"].invoke()
        self.assertTrue(s.saved)
        self.assertEqual(config.read_config(self.home)["llm"], llm)                       # 저장해도 키 값이 그대로다
        seen = []
        for widget in all_widgets(self.view.root):
            kind = widget.winfo_class()
            if kind == "Text":
                seen.append(widget.get("1.0", "end-1c"))
            elif kind == "Entry":
                seen.append(widget.get())
            else:
                try:
                    seen.append(str(widget.cget("text")))
                except self.tk.TclError:
                    pass
        everything = "\n".join(seen)
        self.assertGreater(len(everything), 500)
        self.assertNotIn(secret, everything)
        self.assertNotIn(header, everything)

    def test_the_long_captions_wrap_inside_the_window(self):
        self.open()
        self.view.root.update()
        width = self.w["canvas"].winfo_width()
        self.assertGreater(len(self.view._wrapped), 8)
        for label, side in self.view._wrapped:
            self.assertLessEqual(label.winfo_reqwidth(), width, label["text"][:30])
            self.assertTrue(label.winfo_x() + label.winfo_reqwidth() <= width + 1 or not label.winfo_ismapped(), label["text"][:30])

    def test_the_status_line_growing_does_not_grow_the_window(self):
        self.open()
        root = self.view.root
        root.update()
        before = (root.winfo_width(), root.winfo_height())
        self.type("words", "a\n" + WORD_A)
        for key, text in self.texts(raw_dirs=os.path.join(self.tmp, "없는폴더"), words="a\n" + WORD_A).items():
            self.type(key, text)
        self.w["save"].invoke()
        root.update()
        self.assertEqual((root.winfo_width(), root.winfo_height()), before)

    def test_the_wheel_over_the_body_scrolls_the_body(self):
        self.open()
        root = self.view.root
        root.update()
        canvas = self.w["canvas"]
        self.w["title"].event_generate("<Button-5>")
        root.update()
        self.assertGreater(canvas.yview()[0], 0.0)
        self.w["title"].event_generate("<Button-4>")
        root.update()
        self.assertEqual(canvas.yview()[0], 0.0)

    def test_every_color_is_navy_lime_or_gray(self):
        self.open()
        self.type("words", "가\u200b나\n다")
        self.w["save"].invoke()                                                          # ERR 칩 · 틀린 줄 표시
        self.type("raw_dirs", "상대/경로")
        self.w["save"].invoke()
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
        for key in pw.LIST_KEYS + ("llm",):
            for tag in ("hidden", "bad"):
                for option in ("background", "foreground"):
                    value = self.w[key].tag_cget(tag, option)
                    r, g, b = (v >> 8 for v in self.w[key].winfo_rgb(value))
                    self.assertTrue(color_ok(r, g, b), "%s %s %s=%s" % (key, tag, option, value))
        self.assertGreater(seen, 100)

    def test_every_status_style_is_in_the_palette(self):
        self.open()
        for level in ("", "info", "ok", "alert", "ask"):
            chip, bg, fg = pw._CHIPS[level]
            self.assertIn(bg, pw.PALETTE)
            self.assertIn(fg, pw.PALETTE)
            self.assertIn(pw._STATUS_FG[level], pw.PALETTE)

    def test_create_view_makes_the_tk_screen(self):
        self.assertIsInstance(pw.create_view(), pw.TkView)

    def test_an_unreachable_display_is_e07(self):
        with mock.patch.dict(os.environ, {"DISPLAY": ":987"}):
            self.assertEqual(pw.main_policy(self.home), (1, E07))
        self.assertFalse(os.path.exists(self.home))

    def test_run_ends_when_the_session_finishes_and_the_window_is_gone(self):
        s = pw.PolicySession(self.home)
        view = pw.TkView(self.tk)
        s.finished = True
        view.run(s)
        self.assertIsNone(view.root)

    def test_a_callback_error_ends_the_window_as_an_error(self):
        s = pw.PolicySession(self.home)
        view = pw.TkView(self.tk)
        self.addCleanup(view.close)
        view.open(s)
        view._after(10, lambda: 1 / 0)
        with self.assertRaises(ZeroDivisionError):
            for _ in range(40):
                view.pump()
                time.sleep(0.01)

    def test_main_policy_end_to_end_with_real_widgets(self):
        """사람 대신 위젯을 누르는 대본을 창 안에서 돌린다 - create_view 만 바꿔 끼운다."""
        steps = [lambda v, k=k, t=t: self.type_in(v, k, t) for k, t in self.texts().items()]
        steps += [lambda v: v.widgets["save"].invoke(), lambda v: v.widgets["close"].invoke()]
        with mock.patch.object(pw, "create_view", return_value=ScriptedView(self.tk, steps)):
            code, line = pw.main_policy(self.home)
        self.assertEqual(code, 0, line)
        data = json.loads(line)
        self.assertEqual(data["counts"], config.counts(self.home))
        self.assertEqual((data["counts"]["dictionary"], data["counts"]["raw_dirs"]), (2, 1))
        for leak in ("KITWORD", "가람", "kitraw", "InnerX", "opencode", self.tmp):
            self.assertNotIn(leak, line)

    def test_main_policy_closing_a_dirty_window_twice_is_not_saved(self):
        steps = [lambda v: self.type_in(v, "words", "새단어(가상)"), lambda v: v.widgets["close"].invoke(),
                 lambda v: v.widgets["close"].invoke()]
        with mock.patch.object(pw, "create_view", return_value=ScriptedView(self.tk, steps)):
            self.assertEqual(pw.main_policy(self.home), (3, NOT_SAVED))
        self.assertFalse(os.path.exists(self.home))

    def type_in(self, view, key, text):
        widget = view.widgets[key]
        if widget.winfo_class() == "Text":
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        else:
            widget.delete(0, "end")
            widget.insert(0, text)


class ScriptedView(pw.TkView):
    """진짜 tk 창 위에서 대본 (위젯을 누르는 함수들) 을 차례로 돌리는 시험용 화면 - create_view 자리에 끼워 넣는다."""

    def __init__(self, tk_module, steps):
        pw.TkView.__init__(self, tk_module)
        self.steps = list(steps)

    def open(self, session):
        pw.TkView.open(self, session)
        self._after(30, self._step)
        self._after(30000, lambda: setattr(session, "finished", True))            # 대본이 막혀도 시험이 매달리지 않게

    def _step(self):
        if self.steps and self.root is not None:
            self.steps.pop(0)(self)
            if self.root is not None:
                self._after(30, self._step)


if __name__ == "__main__":
    unittest.main()
