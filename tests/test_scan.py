# -*- coding: utf-8 -*-
"""검사기 D1-D6 · D5a (diodelib.scan) · 손질 (textnorm) · 형식 판정 (briefschema) · 펼치기 (render).

반례 묶음은 tests/vectors/ (SP-17). 모든 자료는 지어낸 것이다.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import briefschema, scan, textnorm  # noqa: E402
from diodelib.render import render  # noqa: E402

VEC = os.path.join(HERE, "vectors")


def _load(name):
    with open(os.path.join(VEC, name), "r", encoding="utf-8") as f:
        return json.load(f)


POL = _load("policy.json")


def policy(**over):
    kw = dict(words=POL["words"], real_data=POL["real_data"], lib_allow=POL["lib_allow"],
              patterns=POL["patterns"], lib_names=POL["lib_names"], tokens=POL["tokens"])
    kw.update(over)
    return scan.Policy(**kw)


# 결과의 자리 (where) 로 나와도 되는 꼴 — 칸 이름 · 목록 번호 · 줄 번호뿐 (AL-11).
SAFE_WHERE = re.compile(r"^(\(root\)|\(size\)|\*|L\d+|repro(:\d+)?|[a-z_]+(\[\d+\])?(\.[a-z_]+(\[\d+\])?)*)$")


def checks_of(res):
    return [h["check"] for h in res["hits"]]


class TextVectors(unittest.TestCase):
    def test_block(self):
        p = policy()
        for case in _load("text.json")["block"]:
            res = scan.check_text(case["text"], p, scan.TEXT_CHECKS)
            self.assertIn(case["check"], checks_of(res), case["text"])

    def test_pass(self):
        p = policy()
        for case in _load("text.json")["pass"]:
            res = scan.check_text(case["text"], p, scan.TEXT_CHECKS)
            self.assertEqual(res, {"ok": True, "hits": []}, case["text"])


class BriefVectors(unittest.TestCase):
    def test_block(self):
        p = policy()
        for case in _load("brief.json")["block"]:
            res = scan.check_brief(case["brief"], p)
            self.assertFalse(res["ok"], case["id"])
            self.assertIn(case["check"], checks_of(res), case["id"])

    def test_pass(self):
        p = policy()
        for case in _load("brief.json")["pass"]:
            res = scan.check_brief(case["brief"], p)
            self.assertEqual(res, {"ok": True, "hits": []}, case["id"])

    def test_bytes_input(self):
        p = policy()
        case = _load("brief.json")["pass"][0]["brief"]
        raw = json.dumps(case, ensure_ascii=False).encode("utf-8")
        self.assertTrue(scan.check_brief(raw, p)["ok"])
        self.assertTrue(scan.check_brief(b"\xef\xbb\xbf" + raw, p)["ok"])   # BOM

    def test_bad_json(self):
        p = policy()
        for raw in (b"{", b"\xff\xfe", b'{"format": 1, "format": 1}', b'{"format": NaN}',
                    b"[]", b" " * (scan.MAX_INPUT_BYTES + 1)):
            res = scan.check_brief(raw, p)
            self.assertEqual(checks_of(res), ["D1"], raw[:20])

    def test_d1_stops_before_text_checks(self):
        p = policy()
        b = dict(_load("brief.json")["pass"][0]["brief"])
        b["extra"] = "KITWORDALPHA 127.0.0.1"
        self.assertEqual(checks_of(scan.check_brief(b, p)), ["D1"])

    def test_real_data_policy(self):
        b = dict(_load("brief.json")["pass"][0]["brief"])
        b["data_class"] = "real"
        self.assertIn("D1", checks_of(scan.check_brief(b, policy())))
        self.assertTrue(scan.check_brief(b, policy(real_data=True))["ok"])
        # 참 (bool) 만 받는다 — 글 "true" · 숫자 1 은 거짓으로 본다
        self.assertIn("D1", checks_of(scan.check_brief(b, policy(real_data="true"))))
        self.assertIn("D1", checks_of(scan.check_brief(b, policy(real_data=1))))

    def test_tokens_none_means_empty_table(self):
        b = _load("brief.json")["pass"][0]["brief"]
        self.assertIn("D6", checks_of(scan.check_brief(b, policy(tokens=None))))


class NoWordsInOutput(unittest.TestCase):
    """AL-11: 결과 · 사람이 보는 한 줄에 단어 · 값 · 모르는 키 이름이 없다."""

    def _assert_clean(self, res, src):
        dumped = json.dumps(res, ensure_ascii=False) + "\n" + scan.format_line(res)
        for w in POL["words"]:
            self.assertNotIn(w, dumped)
            self.assertNotIn(textnorm.dict_key(w), textnorm.dict_key(dumped))
        for h in res["hits"]:
            for where in h.get("where", []):
                self.assertRegex(where, SAFE_WHERE, src)

    def test_text(self):
        p = policy()
        for case in _load("text.json")["block"]:
            self._assert_clean(scan.check_text(case["text"], p, scan.TEXT_CHECKS), case["text"])

    def test_brief(self):
        p = policy()
        for case in _load("brief.json")["block"]:
            self._assert_clean(scan.check_brief(case["brief"], p), case["id"])

    def test_unknown_key_name_not_printed(self):
        b = {"format": 1, "kind": "plan", "data_class": "synthetic", "goal": "x", "ask": "y",
             "KITWORDALPHA": 1, "entities": [{"token": "PH_K7Q2", "type": "화면", "가람소재": 1}]}
        res = scan.check_brief(b, policy())
        self.assertEqual(res["hits"][0]["where"], ["(root)", "entities[0]"])
        self._assert_clean(res, "unknown-key")

    def test_format_line(self):
        res = {"ok": False, "hits": [{"check": "D2", "count": 2, "where": ["context[1]", "ask"]}]}
        self.assertEqual(scan.format_line(res), "DIODE D2 x2 @context[1], ask")
        self.assertEqual(scan.format_line({"ok": True, "hits": []}), "DIODE OK")
        self.assertEqual(scan.format_line(scan.e20()), "DIODE E-20")


class FailClosed(unittest.TestCase):
    """AL-03: 사전이 빔 · 정규식이 깨짐 · 예외 -> E-20."""

    def test_empty_dictionary(self):
        self.assertIsNone(scan.make_policy(words=[]))
        self.assertIsNone(scan.make_policy(words=["a", "-", " "]))        # 두 글자 미만만
        self.assertEqual(scan.check_brief({"format": 1}, None), scan.e20())
        self.assertEqual(scan.check_text("글", None), scan.e20())

    def test_bad_user_pattern(self):
        self.assertIsNone(scan.make_policy(words=["KITWORDALPHA"], patterns=["("]))

    def test_non_string_word(self):
        self.assertIsNone(scan.make_policy(words=["KITWORDALPHA", 3]))

    def test_unknown_check_name(self):
        self.assertEqual(scan.check_text("글", policy(), ("D9",)), scan.e20())

    def test_exception_inside(self):
        p = policy()
        orig = scan.pattern_hits

        def boom(*a, **k):
            raise RuntimeError("x")
        scan.pattern_hits = boom
        try:
            self.assertEqual(scan.check_text("글", p), scan.e20())
            self.assertEqual(scan.check_brief(_load("brief.json")["pass"][0]["brief"], p), scan.e20())
        finally:
            scan.pattern_hits = orig

    def test_schema_missing(self):
        p = policy()
        saved = dict(scan._SCHEMA)
        orig = briefschema.default_schema_path
        scan._SCHEMA.clear()
        briefschema.default_schema_path = lambda: os.path.join(VEC, "no-such-schema.json")
        try:
            self.assertEqual(scan.check_brief(_load("brief.json")["pass"][0]["brief"], p), scan.e20())
        finally:
            briefschema.default_schema_path = orig
            scan._SCHEMA.clear()
            scan._SCHEMA.update(saved)

    def test_unsupported_schema_keyword(self):
        with self.assertRaises(briefschema.SchemaUnsupported):
            briefschema.validate("a", {"format": "email"})


class Tokens(unittest.TestCase):
    def test_exact_with_korean_particle(self):
        self.assertEqual(scan.find_tokens("PH_K7Q2를 PH_M3X9의"), ["PH_K7Q2", "PH_M3X9"])

    def test_broken(self):
        for t in ("ph_k7q2", "PH_K7Q", "PH K7Q2", "PH_K7Q2X", "PH-K7Q2", "PH_K7Q1", "PHK7Q2", "PH_ABCDEF"):
            self.assertEqual(scan.find_broken_tokens(t), 1, t)

    def test_not_broken(self):
        for t in ("PH_K7Q2", "phone", "photo", "phase", "Photo", "pH 7", "FIELDS.PH_M3X9", "PH_M3X9_label"):
            self.assertEqual(scan.find_broken_tokens(t), 0, t)

    def test_alphabet(self):
        self.assertEqual(len(scan.TOKEN_ALPHABET), 30)
        for ch in "01ILOU":
            self.assertNotIn(ch, scan.TOKEN_ALPHABET)
        self.assertEqual(briefschema.validate("PH_K7Q2", {"$ref": "#/$defs/token", "$defs": {"token": {
            "type": "string", "pattern": "^PH_[2-9A-HJKMNP-TV-Z]{4}$"}}}), [])


class TextNorm(unittest.TestCase):
    def test_prepare_table(self):
        self.assertEqual(textnorm.prepare("a\u2026b"), "a...b")
        self.assertEqual(textnorm.prepare("a—b\u2013c"), "a-b-c")
        self.assertEqual(textnorm.prepare("\u201ca\u201d \u2018b\u2019"), "\"a\" 'b'")
        self.assertEqual(textnorm.prepare("a · b·c"), "a, b, c")
        self.assertEqual(textnorm.prepare("\u2022 첫째"), "- 첫째")
        self.assertEqual(textnorm.prepare("A \u2192 B"), "A -> B")
        self.assertEqual(textnorm.prepare("\uff21\uff22\uff23"), "ABC")                 # 전각 (NFKC)

    def test_allowed_chars(self):
        ok = textnorm.prepare("화면 구성 - 흐름, 빈 상태 (가) \"a\"")
        self.assertTrue(all(textnorm.allowed_text_char(c) for c in ok))
        for bad in ("\u2606", "\u00b0", "\u4e00", "\t", "\n", "\u200b", "\u0430", "\u3131", "\u1100"):
            self.assertFalse(textnorm.allowed_text_char(textnorm.prepare(bad)[0]), repr(bad))

    def test_dict_key(self):
        k = textnorm.dict_key("KITWORDALPHA")
        for v in ("kit-word alpha", "\uff2b\uff29\uff34WORDALPHA", "Kit.Word_Alpha/", "KIT\u200bWORDALPHA",
                  "K\u0308ITWORDALPHA", "\u043aitwordalpha"):
            self.assertEqual(textnorm.dict_key(v), k, repr(v))
        self.assertEqual(textnorm.dict_key("가 람·소-재"), "가람소재")


class SchemaAgreement(unittest.TestCase):
    """표준 라이브러리 판정기와 jsonschema (개발 시험용 · 있으면) 가 같은 답을 내는가."""

    def test_against_jsonschema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema 없음 (개발 시험용)")
        schema = briefschema.load_schema(briefschema.default_schema_path())
        v = jsonschema.Draft202012Validator(schema)
        data = _load("brief.json")
        n = 0
        for case in data["block"] + data["pass"]:
            mine = briefschema.validate(case["brief"], schema) == []
            theirs = v.is_valid(case["brief"])
            self.assertEqual(mine, theirs, case["id"])
            n += 1
        self.assertGreater(n, 40)


class Render(unittest.TestCase):
    def test_appendix_c(self):
        with open(os.path.join(ROOT, "docs", "SPEC.md"), "r", encoding="utf-8") as f:
            spec = f.read()
        block = spec.split("## 부록 C")[1].split("```text\n")[1].split("```")[0]
        rep = [c for c in _load("brief.json")["pass"] if c["id"] == "report-appendix-c"][0]["brief"]
        self.assertEqual(render(rep), block)

    def test_route_not_rendered(self):
        b = _load("brief.json")["pass"][0]["brief"]
        out = render(b)
        self.assertNotIn("normal", out)
        self.assertNotIn("route", out.lower())
        self.assertTrue(out.startswith("[diode brief format=1 kind=plan data=synthetic]\n"))
        self.assertTrue(out.endswith("[/diode brief]\n"))

    def test_rendered_is_prepared(self):
        b = _load("brief.json")["pass"][0]["brief"]
        out = render(b)
        self.assertNotIn("·", out)
        self.assertTrue(all(textnorm.allowed_text_char(c) or c == "\n" for c in out))


class Repro(unittest.TestCase):
    def test_lines_reported(self):
        p = policy()
        code = "import pandas as pd\n# 우리\ndf = pd.DataFrame()\nx = df[\"line_temp\"]\nimport kitpkg\n"
        self.assertEqual(scan.check_repro(code, p), [2, 4, 5])

    def test_placeholders(self):
        p = policy()
        code = ("import pandas as pd\n"
                "df = pd.DataFrame({\"col_1\": [1, 2, 3], \"col_2\": [\"a\", \"b\", \"x\"]})\n"
                "result = df.groupby(\"col_2\").agg(\"sum\")\n")
        # "sum" 은 자리 글이 아니다 — 문자열 값은 자리 글만
        self.assertEqual(scan.check_repro(code, p), [3])
        code2 = code.replace('.agg("sum")', ".sum()")
        self.assertEqual(scan.check_repro(code2, p), [])

    def test_exactly_40_lines(self):
        p = policy()
        self.assertEqual(scan.check_repro("x = y\n" * 40, p), [])
        self.assertEqual(scan.check_repro("x = y\n" * 41, p), [41])
        # 작은 정수도 스무 개까지만 [제안]
        self.assertEqual(scan.check_repro("x = 1\n" * 20, p), [])
        self.assertEqual(scan.check_repro("x = 1\n" * 21, p), [21])


class ScanCommand(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="diode-test-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _write(self, name, obj):
        path = os.path.join(self.home, name)
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def test_no_dictionary_blocks(self):
        code, out, line = scan.main_scan(self.home, "글".encode("utf-8"))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out), scan.e20())

    def test_empty_dictionary_blocks(self):
        self._write("dictionary.json", {"format": 1, "words": []})
        self.assertEqual(scan.main_scan(self.home, b"x")[0], 2)

    def test_newer_format_blocks(self):
        self._write("dictionary.json", {"format": 2, "words": ["KITWORDALPHA"]})
        self.assertEqual(scan.main_scan(self.home, b"x")[0], 2)

    def test_pass_and_block(self):
        self._write("dictionary.json", {"format": 1, "words": ["KITWORDALPHA"]})
        code, out, line = scan.main_scan(self.home, "화면 초안을 그려 달라".encode("utf-8"))
        self.assertEqual((code, line), (0, "DIODE OK"))
        code, out, line = scan.main_scan(self.home, "kit word alpha\n둘째 줄 127.0.0.1".encode("utf-8"))
        self.assertEqual(code, 2)
        self.assertEqual(line, "DIODE D2 x1 @L1 · D3 x1 @L2")
        self.assertNotIn("KITWORD", out.upper())
        self.assertEqual(scan.main_scan(self.home, b"\xff")[0], 2)

    def test_config_and_libnames(self):
        self._write("dictionary.json", {"format": 1, "words": ["KITWORDALPHA"]})
        self._write("config.json", {"format": 1, "policy": {"lib_allow": ["pandas"], "patterns": ["(?i)kitlot"]}})
        self._write(os.path.join("libnames", "pandas.json"),
                    {"format": 1, "library": "pandas", "names": ["read_csv"]})
        p = scan.policy_from_home(self.home)
        self.assertIn("read_csv", p.lib_names)
        self.assertEqual(scan.main_scan(self.home, b"pandas.io and read_csv")[0], 0)
        self.assertEqual(scan.main_scan(self.home, b"KITLOT here")[0], 2)
        self._write("config.json", {"format": 1, "policy": {"patterns": ["("]}})
        self.assertEqual(scan.main_scan(self.home, b"x")[0], 2)


if __name__ == "__main__":
    unittest.main()
