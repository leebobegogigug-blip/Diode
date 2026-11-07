# -*- coding: utf-8 -*-
"""seal · 말 봉인 · unseal (U1-U4) · 묶기 파일 · 덮어쓰지 않는 쓰기. 모든 자료는 지어낸 것이다."""

import copy
import json
import os
import pickle
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import scan  # noqa: E402
from diodelib.seal import PseudonymTable, seal, seal_speech  # noqa: E402
from diodelib.unseal import URL_REMOVED, unseal, write_binding, write_new  # noqa: E402

WORDS = ["KITWORDALPHA", "가람소재", "BX-7 라인"]


def policy():
    return scan.Policy(words=WORDS, lib_allow=["pandas"], lib_names=["DataFrame", "groupby", "sum"])


DRAFT = {
    "format": 1, "kind": "plan", "data_class": "synthetic",
    "goal": "[[s1]] 화면의 기획 초안",
    "context": ["사람이 하루에 몇 번 본다", "목록은 [[f2]] 로 나뉜다"],
    "entities": [{"ref": "s1", "name": "주간 점검표 (가상)", "type": "화면", "note": "목록과 상세를 한 화면에"}],
    "fields": [{"ref": "f1", "name": "kitc_orbit_temp", "label": "궤도 온도 (가상)", "kind": "숫자", "unit": "있음"},
               {"ref": "f2", "name": "kitc_orbit_zone", "kind": "범주", "count": 7}],
    "ask": "화면 구성과 빈 상태를 제안해 달라",
}


class Table(unittest.TestCase):
    def test_same_word_same_token(self):
        t = PseudonymTable()
        a = t.token_for("가상 이름", "entity")
        self.assertEqual(t.token_for("가상 이름", "entity"), a)
        self.assertNotEqual(t.token_for("다른 이름", "entity"), a)
        self.assertTrue(scan.TOKEN_RE.fullmatch(a))
        self.assertEqual(len(t), 2)

    def test_fresh_per_table(self):
        # 자문마다 새로 (AL-05) — 같은 단어도 표가 다르면 (거의 늘) 다른 토큰
        toks = set(PseudonymTable().token_for("가상 이름", "entity") for _ in range(30))
        self.assertGreater(len(toks), 25)

    def test_never_serialized(self):
        t = PseudonymTable()
        t.token_for("비밀 이름 (가상)", "entity")
        self.assertNotIn("비밀", repr(t))
        self.assertNotIn("비밀", str(t))
        with self.assertRaises(TypeError):
            pickle.dumps(t)
        with self.assertRaises(TypeError):
            copy.deepcopy(t)
        with self.assertRaises(TypeError):
            copy.copy(t)
        with self.assertRaises(TypeError):
            json.dumps(t)
        with self.assertRaises(AttributeError):
            t.__dict__        # __slots__ — 속성 사전이 없다

    def test_binding(self):
        t = PseudonymTable()
        f = t.token_for("kitc_orbit_temp", "field", "궤도 온도 (가상)")
        e = t.token_for("주간 점검표 (가상)", "entity")
        t.token_for("KITWORDALPHA", "word")
        b = t.binding()
        self.assertEqual(b, {"format": 1, "fields": {f: {"name": "kitc_orbit_temp", "label": "궤도 온도 (가상)"}},
                             "entities": {e: {"name": "주간 점검표 (가상)"}}})


class Seal(unittest.TestCase):
    def test_draft_to_sealed(self):
        t = PseudonymTable()
        res = seal(DRAFT, t, policy())
        self.assertTrue(res["ok"], res)
        text = res["text"]
        for real in ("주간 점검표", "kitc_orbit", "궤도 온도", "[[", "ref", "name", "label"):
            self.assertNotIn(real, text)
        self.assertEqual(len(t), 3)
        s1 = res["brief"]["entities"][0]["token"]
        self.assertIn("GOAL: %s 화면의 기획 초안" % s1, text)
        self.assertEqual(DRAFT["goal"], "[[s1]] 화면의 기획 초안")      # 초안은 바뀌지 않는다

    def test_real_name_written_directly_is_caught(self):
        d = copy.deepcopy(DRAFT)
        d["ask"] = "주간 점검표 (가상) 의 빈 상태를 제안해 달라"    # 사전에는 없지만 그 job 의 진짜 이름
        res = seal(d, PseudonymTable(), policy())
        self.assertFalse(res["ok"])
        self.assertIn("D2", [h["check"] for h in res["hits"]])
        self.assertNotIn("text", res)

    def test_unknown_ref_left(self):
        d = copy.deepcopy(DRAFT)
        d["ask"] = "[[zz]] 를 보여 달라"
        res = seal(d, PseudonymTable(), policy())
        self.assertEqual(res, {"ok": False, "hits": [{"check": "D1", "count": 1, "where": ["(ref)"]}]})

    def test_bad_ref_shapes(self):
        for bad in ({"ref": "S1", "name": "x", "type": "화면"},                        # 대문자
                    {"ref": "s1", "type": "화면"},                                     # 이름 없음
                    {"ref": "s1", "name": "x", "token": "PH_K7Q2", "type": "화면"},     # 둘 다
                    {"ref": "s1", "name": "x", "label": "y", "type": "화면"}):          # label 은 field 만
            d = copy.deepcopy(DRAFT)
            d["entities"] = [bad]
            d["goal"] = "작은 기획"
            res = seal(d, PseudonymTable(), policy())
            self.assertFalse(res["ok"], bad)
            self.assertEqual(res["hits"][0]["check"], "D1")

    def test_duplicate_ref(self):
        d = copy.deepcopy(DRAFT)
        d["fields"][1]["ref"] = "f1"
        self.assertFalse(seal(d, PseudonymTable(), policy())["ok"])

    def test_report_with_known_tokens(self):
        t = PseudonymTable()
        tok = t.token_for("주간 점검표 (가상)", "entity")
        rep = {"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0007", "status": "done",
               "counts": {"changed_files": 2}, "summary": ["%s 화면을 만들었다" % tok]}
        self.assertTrue(seal(rep, t, policy())["ok"])
        rep["summary"] = ["PH_ZZZZ 화면을 만들었다"]
        res = seal(rep, t, policy())
        self.assertIn("D6", [h["check"] for h in res["hits"]])

    def test_bad_inputs_fail_closed(self):
        self.assertEqual(seal(DRAFT, None, policy()), scan.e20())
        self.assertEqual(seal(DRAFT, PseudonymTable(), None), scan.e20())
        self.assertEqual(seal("x", PseudonymTable(), policy())["hits"][0]["check"], "D1")


class Speech(unittest.TestCase):
    def test_words_to_tokens(self):
        t = PseudonymTable()
        res = seal_speech("가람소재 의 bx-7 라인 화면을 KitWordAlpha 처럼", t, policy(), WORDS)
        self.assertTrue(res["check"]["ok"], res["check"])
        for w in ("가람", "bx", "kit", "Kit"):
            self.assertNotIn(w, res["text"])
        self.assertEqual(len(t), 3)

    def test_left_overs_are_reported(self):
        t = PseudonymTable()
        res = seal_speech("가람소재 의 온도 350 을 D:\\x 에서", t, policy(), WORDS)
        checks = [h["check"] for h in res["check"]["hits"]]
        self.assertIn("D4", checks)
        self.assertIn("D3", checks)
        self.assertNotIn("가람", res["text"])

    def test_fullwidth_word(self):
        t = PseudonymTable()
        res = seal_speech("\uff2b\uff29\uff34WORDALPHA 화면", t, policy(), WORDS)
        self.assertTrue(res["check"]["ok"])
        self.assertNotIn("WORDALPHA", res["text"])


class Unseal(unittest.TestCase):
    def setUp(self):
        self.t = PseudonymTable()
        self.e = self.t.token_for("주간 점검표 (가상)", "entity")
        self.f = self.t.token_for("kitc_orbit_temp", "field", "궤도 온도 (가상)")

    def test_md_restored(self):
        ans = "# 기획\n- %s 화면은 목록과 상세로 나눈다\n- %s 는 오른쪽 정렬\n" % (self.e, self.f)
        res = unseal(ans, self.t, policy(), "plan")
        self.assertTrue(res["ok"])
        self.assertIn("주간 점검표 (가상) 화면은", res["text"])
        self.assertIn("kitc_orbit_temp 는", res["text"])
        self.assertEqual(res["issues"], {"U1": [], "U2": 0, "U3": [], "U4": False})

    def test_u1_unknown_and_broken(self):
        ans = "첫 줄 %s\nPH_ZZZZ 는 모른다\nph_%s 는 깨졌다\n" % (self.e, self.e[3:].lower())
        res = unseal(ans, self.t, policy(), "plan")
        self.assertTrue(res["ok"])
        self.assertEqual(res["issues"]["U1"], [2, 3])
        self.assertIn("PH_ZZZZ", res["text"])          # 모르는 토큰은 되돌리지 않는다

    def test_u2_reverse_inflow_stops(self):
        for ans in ("이 화면은 가람소재 의 것 같다", "KIT-WORD alpha 라인", "bx7 라인"):
            res = unseal(ans, self.t, policy(), "plan")
            self.assertFalse(res["ok"], ans)
            self.assertTrue(res["stop"])
            self.assertIsNone(res["text"])
            self.assertGreater(res["issues"]["U2"], 0)

    def test_u2_speech_word(self):
        t = PseudonymTable()
        seal_speech("사내 말 KITWORDALPHA", t, policy(), WORDS)
        self.assertTrue(unseal("평범한 답", t, policy(), "plan")["ok"])

    def test_u3_md_urls_removed(self):
        ans = "참고: https://docs.example.com/a 와 //cdn.example.net/x.js\n본문\n"
        res = unseal(ans, self.t, policy(), "lib")
        self.assertTrue(res["ok"])
        self.assertEqual(res["issues"]["U3"], [1])
        self.assertNotIn("example", res["text"])
        self.assertIn(URL_REMOVED, res["text"])

    def _html(self, body):
        return "<!doctype html>\n<html><head><title>a</title></head><body>%s</body></html>\n" % body

    def test_ui_unchanged_with_binding(self):
        html = self._html("<div id=\"a\"></div><script>const F = FIELDS.%s;</script>" % self.f)
        res = unseal(html, self.t, policy(), "ui")
        self.assertTrue(res["ok"])
        self.assertEqual(res["text"], html)                 # 글자를 바꾸지 않는다
        self.assertIn(self.f, res["binding"]["fields"])
        self.assertIn(self.e, res["binding"]["entities"])

    def test_ui_external_blocked(self):
        for body in ('<script src="https://cdn.example.com/x.js"></script>',
                     '<link href="//fonts.example.com/a.css" rel="stylesheet">',
                     "<script>fetch('/api')</script>",
                     "<script>new WebSocket('ws://a')</script>",
                     "<script>navigator.sendBeacon('/x')</script>",
                     "<style>@import 'a.css';</style>",
                     "<script>import('https://a.example/x.js')</script>",
                     "<script>var x = new XMLHttpRequest()</script>",
                     "<iframe></iframe>"):
            res = unseal(self._html(body), self.t, policy(), "ui")
            self.assertFalse(res["ok"], body)
            self.assertEqual(res["issues"]["U3"], [2], body)

    def test_u4_shape(self):
        self.assertFalse(unseal("그냥 글", self.t, policy(), "ui")["ok"])
        self.assertTrue(unseal(self._html("a"), self.t, policy(), "ui")["ok"])
        big = "가" * (64 * 1024)
        self.assertTrue(unseal(big, self.t, policy(), "plan")["issues"]["U4"])

    def test_md_limit_moves_the_u4_limit_of_text_answers(self):
        big = "가" * (30 * 1024)                               # 90 KiB
        self.assertTrue(unseal(big, self.t, policy(), "plan")["issues"]["U4"])
        self.assertFalse(unseal(big, self.t, policy(), "plan", md_limit=256 * 1024)["issues"]["U4"])
        self.assertTrue(unseal(big, self.t, policy(), "plan", md_limit=1024)["issues"]["U4"])
        for bad in (0, -1, "9", True, 1.5):
            self.assertFalse(unseal("a", self.t, policy(), "plan", md_limit=bad)["ok"], bad)

    def test_issues_have_no_words(self):
        ans = "가람소재 https://x.example.com PH_ZZZZ"
        res = unseal(ans, self.t, policy(), "plan")
        dumped = json.dumps(res["issues"], ensure_ascii=False)
        for w in ("가람", "example", "ZZZZ"):
            self.assertNotIn(w, dumped)

    def test_bad_inputs(self):
        self.assertFalse(unseal("a", None, policy(), "plan")["ok"])
        self.assertFalse(unseal("a", self.t, policy(), "exe")["ok"])
        self.assertFalse(unseal(b"a", self.t, policy(), "plan")["ok"])


class Files(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="diode-test-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_no_overwrite(self):
        p = os.path.join(self.d, "answer.md")
        self.assertEqual(write_new(p, "하나"), p)
        self.assertEqual(write_new(p, "둘"), os.path.join(self.d, "answer-2.md"))
        self.assertEqual(write_new(p, "셋"), os.path.join(self.d, "answer-3.md"))
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "하나")
        self.assertEqual(sorted(os.listdir(self.d)), ["answer-2.md", "answer-3.md", "answer.md"])  # 임시 파일 없음

    def test_binding_file(self):
        t = PseudonymTable()
        f = t.token_for("kitc_orbit_temp", "field", "궤도 온도 (가상)")
        p = write_binding(self.d, t)
        self.assertTrue(p.endswith("binding.local.json"))
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["fields"][f]["label"], "궤도 온도 (가상)")
        self.assertTrue(write_binding(self.d, t).endswith("binding.local-2.json"))


if __name__ == "__main__":
    unittest.main()
