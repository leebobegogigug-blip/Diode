# -*- coding: utf-8 -*-
"""가린 묶음 (diodelib.bundle · SP-20) — 표시 · 자동 가림 · 잔여 검사 R1-R6 · 묶음 꼴 · 되돌리기 · 들어오는 검사.

금고는 같은 인터페이스의 메모리 가짜 (FakeVault · 토큰은 차례대로 매긴다) 를 쓴다. 모든 자료는 지어낸 것이다.
사전 단어는 tests/vectors/policy.json 의 것이다.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import bundle, scan  # noqa: E402
from diodelib.bundle import (BundleError, build_bundle, mask_text, parse_marks, residual_hits,  # noqa: E402
                             restore_name, restore_text, return_checks)

with open(os.path.join(HERE, "vectors", "policy.json"), "r", encoding="utf-8") as _f:
    POL = json.load(_f)
WORDS = POL["words"]            # KITWORDALPHA · 가람소재 · BX-7 라인 · KITC_ORBIT · 모래시계공정
O, C = bundle.MARK_OPEN, bundle.MARK_CLOSE


def policy(extra=()):
    return scan.Policy(words=list(WORDS) + list(extra), lib_allow=POL["lib_allow"], lib_names=POL["lib_names"])


def mk(value, prefix=""):
    """표시 하나: mk("350", "n") -> ⟦n:350⟧."""
    return O + (prefix + ":" if prefix else "") + value + C


def unmark(text):
    """표시 기호만 뺀 원문 (되돌린 글이 같아야 하는 글)."""
    out = []
    pos = 0
    for m in parse_marks(text):
        out.append(text[pos:m.start])
        out.append(m.value)
        pos = m.end
    out.append(text[pos:])
    return "".join(out)


class FakeVault(object):
    """diodelib.vault.Vault 와 같은 인터페이스의 메모리 가짜. 토큰은 무작위 대신 차례대로 (시험이 결정적이게)."""

    def __init__(self, start=0):
        self._by_token = {}
        self._by_key = {}
        self._names = {}            # real_path -> name
        self._n = start

    def _make(self):
        n = self._n
        self._n += 1
        chars = []
        for _ in range(4):
            chars.append(scan.TOKEN_ALPHABET[n % 30])
            n //= 30
        return "PH_" + "".join(reversed(chars))

    def token_for(self, real, kind):
        if kind not in bundle.KINDS or not isinstance(real, str) or not real.strip():
            raise ValueError("bad")
        tok = self._by_key.get((real, kind))
        if tok is None:
            tok = self._make()
            self._by_key[(real, kind)] = tok
            self._by_token[tok] = (real, kind)
        return tok

    def real_of(self, token):
        return self._by_token.get(token)

    def tokens(self):
        return frozenset(self._by_token)

    def reals(self, min_len=2):
        return sorted(set(r for r, _k in self._by_token.values() if len(r) >= min_len), key=lambda r: (-len(r), r))

    def file_name(self, real_path, ext):
        name = self._names.get(real_path)
        if name is None:
            name = "F%02d.%s" % (len(self._names) + 1, ext)
            self._names[real_path] = name
        return name

    def file_real(self, name):
        for real, n in self._names.items():
            if n == name:
                return real
        return None

    def token_of(self, real, kind):
        return self._by_key.get((real, kind))


def checks_of(hits):
    return [h["check"] for h in hits]


SAFE_WHERE = re.compile(r"^(\(root\)|format|kind|job|note|files|files\[\d+\](\.(path|type)|:L\d+)?|F\d{2,4}:L\d+|L\d+)$")


# ---------------------------------------------------------------- 표시

class Marks(unittest.TestCase):
    def test_four_kinds(self):
        text = "첫 줄\n%s 의 수율은 %s · 자리 %s\ndef %s():" % (
            mk("모래시계공정"), mk("350", "n"), mk("D:\\data\\a.csv", "p"), mk("calcYield", "i"))
        ms = parse_marks(text)
        self.assertEqual([(m.kind, m.value, m.line) for m in ms],
                         [("word", "모래시계공정", 2), ("number", "350", 2), ("path", "D:\\data\\a.csv", 2),
                          ("ident", "calcYield", 3)])
        for m in ms:
            self.assertEqual(text[m.start], O)
            self.assertEqual(text[m.end - 1], C)

    def test_colon_inside_value(self):
        self.assertEqual([(m.kind, m.value) for m in parse_marks(mk("D:\\x", "p"))], [("path", "D:\\x")])
        self.assertEqual([(m.kind, m.value) for m in parse_marks(mk("ab:c"))], [("word", "ab:c")])
        self.assertEqual([(m.kind, m.value) for m in parse_marks(mk("1:2"))], [("word", "1:2")])
        self.assertEqual([(m.kind, m.value) for m in parse_marks(mk(":x"))], [("word", ":x")])

    def _bad(self, text, line, reason):
        with self.assertRaises(BundleError) as cm:
            parse_marks(text)
        self.assertEqual(cm.exception.code, "E-04")
        self.assertEqual(cm.exception.where, ["L%d" % line])
        self.assertEqual(cm.exception.reason, reason)
        self.assertEqual(str(cm.exception), "E-04")

    def test_six_malformed(self):
        head = "머리 줄\n둘째 줄\n"
        self._bad(head + "가 " + O + "닫히지 않음", 3, "unclosed")
        self._bad(head + "빈 " + O + C + " 값", 3, "empty")
        self._bad(head + "빈 " + mk("", "n") + " 값", 3, "empty")
        self._bad(head + "빈칸 " + mk("  ") + " 값", 3, "empty")
        self._bad(head + "모름 " + mk("350", "x"), 3, "prefix")
        self._bad(head + "대문자 " + mk("350", "N"), 3, "prefix")
        self._bad(head + "겹침 " + O + "a" + O + "b" + C + C, 3, "nested")
        self._bad(head + "긴 값 " + mk("가" * (bundle.MAX_MARK_VALUE + 1)), 3, "long")
        self._bad(head + "줄바꿈 " + O + "ab\ncd" + C, 3, "newline")
        self._bad(head + "줄바꿈 " + O + "ab\rcd" + C, 3, "newline")
        self._bad(head + "줄바꿈 " + O + "ab\ncd" + C + " 뒤 " + mk("a"), 3, "newline")     # 닫는 자리를 따로 세지 않는다

    def test_more_malformed(self):
        self._bad("닫기만 " + C, 1, "stray")
        self._bad("x" + mk("a"), 1, "boundary")                 # 앞에 ASCII 글자
        self._bad("get_" + mk("yield", "i"), 1, "boundary")     # 앞에 _
        self._bad(mk("350", "n") + "ms", 1, "boundary")         # 뒤에 ASCII 글자
        self._bad("PH_K7Q2" + mk("a"), 1, "boundary")           # 토큰에 붙음
        self._bad(mk("a") + mk("b"), 1, "boundary")             # 표시끼리 붙음

    def test_boundary_ok(self):
        for text in (mk("kitc", "i") + "_temp", "(" + mk("350", "n") + ")", mk("가람소재") + "의",
                     "x = " + mk("350", "n") + ";", '"' + mk("D:\\a", "p") + '"', mk("350", "n") + "도"):
            self.assertEqual(len(parse_marks(text)), 1, text)

    def test_limit_exact(self):
        self.assertEqual(parse_marks(mk("가" * bundle.MAX_MARK_VALUE))[0].value, "가" * bundle.MAX_MARK_VALUE)

    def test_all_bad_lines_collected(self):
        with self.assertRaises(BundleError) as cm:
            parse_marks(O + C + "\n좋은 줄 " + mk("a") + "\n" + O + "열림\n" + C + "\n닫기만 " + C)
        self.assertEqual(cm.exception.where, ["L1", "L3", "L5"])
        self.assertEqual(cm.exception.reason, "empty")

    def test_no_marks(self):
        self.assertEqual(parse_marks("표시 없는 글\n둘째 줄"), [])


# ---------------------------------------------------------------- 가림

class Mask(unittest.TestCase):
    def test_marks_to_tokens(self):
        v = FakeVault()
        text = "%s 의 온도 %s · 다시 %s" % (mk("모래시계공정"), mk("350", "n"), mk("모래시계공정"))
        masked, stats = mask_text(text, v, WORDS)
        tw, tn = v.token_of("모래시계공정", "word"), v.token_of("350", "number")
        self.assertEqual(masked, "%s 의 온도 %s · 다시 %s" % (tw, tn, tw))          # 같은 값 같은 토큰
        self.assertEqual(stats, {"marked": 3, "auto": 0, "tokens": 2})

    def test_same_value_different_kind_is_different_token(self):
        v = FakeVault()
        masked, _s = mask_text("%s %s" % (mk("350"), mk("350", "n")), v, WORDS)
        self.assertEqual(len(set(scan.TOKEN_RE.findall(masked))), 2)

    def test_auto_mask_missed_dictionary_word(self):
        v = FakeVault()
        masked, stats = mask_text("KITWORDALPHA 을 쓰는 가람소재 표", v, WORDS)
        self.assertNotIn("KITWORD", masked)
        self.assertNotIn("가람", masked)
        self.assertEqual(stats["auto"], 2)
        self.assertEqual(v.real_of(scan.TOKEN_RE.findall(masked)[0]), ("KITWORDALPHA", "word"))

    def test_auto_mask_variant_keeps_surface(self):
        v = FakeVault()
        text = "kit-word alpha 와 KitWordAlpha 와 bx-7 라인"
        masked, stats = mask_text(text, v, WORDS)
        self.assertEqual(stats["auto"], 3)
        for w in ("kit", "Kit", "bx", "라인"):
            self.assertNotIn(w, masked)
        self.assertEqual(restore_text(masked, v)[0], text)        # 찾은 글 그대로가 값 - 되돌리면 원문

    def test_auto_mask_vault_value_keeps_kind(self):
        v = FakeVault()
        text = "def %s():\n    return calcYield(%s) + 350\n" % (mk("calcYield", "i"), mk("350", "n"))
        masked, stats = mask_text(text, v, WORDS)
        ti, tn = v.token_of("calcYield", "ident"), v.token_of("350", "number")
        self.assertEqual(masked, "def %s():\n    return %s(%s) + %s\n" % (ti, ti, tn, tn))
        self.assertEqual(stats, {"marked": 2, "auto": 2, "tokens": 2})

    def test_value_from_earlier_text_is_auto_masked(self):
        v = FakeVault()
        mask_text("처음 " + mk("calcYield", "i"), v, WORDS)
        masked, stats = mask_text("나중에 calcYield 만", v, WORDS)
        self.assertEqual(masked, "나중에 %s 만" % v.token_of("calcYield", "ident"))
        self.assertEqual(stats["auto"], 1)

    def test_embedded_in_ascii_word_masks_whole_word(self):
        v = FakeVault()
        text = "x = loadKITWORDALPHAData(1) + KITC_ORBIT_temp"
        masked, _s = mask_text(text, v, WORDS)
        toks = scan.TOKEN_RE.findall(masked)
        self.assertEqual(len(toks), 2)
        self.assertEqual(v.real_of(toks[0]), ("loadKITWORDALPHAData", "word"))
        self.assertTrue(masked.endswith(toks[1] + "_temp"))        # 뒤의 _ 는 토큰 경계라 넓히지 않는다
        self.assertEqual(restore_text(masked, v)[0], text)

    def test_auto_mask_stays_in_one_line(self):
        v = FakeVault()
        masked, stats = mask_text("앞 KITWORD\nALPHA 뒤\n", v, WORDS)
        self.assertEqual((masked, stats["auto"]), ("앞 KITWORD\nALPHA 뒤\n", 0))     # 줄바꿈을 토큰에 삼키지 않는다
        self.assertEqual(residual_hits(masked, policy(), v, 1),
                         [{"check": "R1", "count": 1, "where": ["F01:L1"]}])

    def test_existing_tokens_untouched(self):
        v = FakeVault()
        t = v.token_for("모래시계공정", "word")
        masked, stats = mask_text("이미 %s 와 PH_ZZZZ 는 그대로" % t, v, WORDS)
        self.assertEqual(masked, "이미 %s 와 PH_ZZZZ 는 그대로" % t)
        self.assertEqual(stats, {"marked": 0, "auto": 0, "tokens": 2})

    def test_adjacent_to_token_is_left_for_r1(self):
        v = FakeVault()
        masked, stats = mask_text(mk("350", "n") + "가람소재 의 값", v, WORDS)
        self.assertIn("가람소재", masked)                            # 토큰에 붙어 가리지 못함 - 남겨 둔다
        self.assertEqual(stats["auto"], 0)
        hits = residual_hits(masked, policy(), v, 1)
        self.assertIn("R1", checks_of(hits))

    def test_bad_mark_raises(self):
        with self.assertRaises(BundleError) as cm:
            mask_text("첫 줄\n" + O + "열림", FakeVault(), WORDS)
        self.assertEqual((cm.exception.code, cm.exception.where), ("E-04", ["L2"]))


# ---------------------------------------------------------------- 잔여 검사

def _secret_b64():
    return base64.b64encode(hashlib.sha256(b"diode-bundle-test").digest()).decode("ascii")


def _secret_hex():
    return hashlib.sha256(b"diode-bundle-test-hex").hexdigest()


PY_CODE = (
    "def total(rows):\n"
    "    out = 0\n"
    "    for row in rows:\n"
    "        if row.get(\"ok\") and row[\"n\"] != 0:\n"
    "            out += row[\"n\"] * 2\n"
    "    return {\"total\": out, \"count\": len(rows)}\n")
SQL_CODE = "SELECT name, SUM(qty) AS qty FROM orders WHERE status = 'open' GROUP BY name ORDER BY qty DESC LIMIT 10;\n"
JSON_CODE = '{"items": [{"id": 1, "tags": ["a", "b"], "active": true}], "page": 2, "next_page_token": null}\n'


class Residual(unittest.TestCase):
    def setUp(self):
        self.v = FakeVault()
        self.p = policy()

    def hits(self, text, file_no=1):
        return residual_hits(text, self.p, self.v, file_no)

    def test_clean_text(self):
        t = self.v.token_for("모래시계공정", "word")
        self.assertEqual(self.hits("%s 의 수율 표\n두 번째 줄 x = 7\n" % t), [])

    def test_r1_dictionary(self):
        for text in ("남은 KITWORDALPHA", "KlTWORDALPHA 닮은 꼴", "KITWORD\nALPHA 줄을 넘음", "ＫＩＴＷＯＲＤＡＬＰＨＡ"):
            self.assertIn("R1", checks_of(self.hits(text)), text)
        hits = self.hits("가\n나\n남은 가람소재\n")
        self.assertEqual(hits, [{"check": "R1", "count": 1, "where": ["F01:L3"]}])
        self.assertEqual(self.hits("KITWORD\nALPHA", 2)[0]["where"], ["F02:L1"])    # 줄을 넘으면 시작한 줄

    def test_r2_vault_value(self):
        self.v.token_for("calcYield", "ident")
        self.v.token_for("35", "number")
        self.assertEqual(self.hits("x = calc+Yield"), [{"check": "R2", "count": 1, "where": ["F01:L1"]}])
        self.assertEqual(checks_of(self.hits("ratio 3:5")), ["R2"])
        for text in ("x = 3 + 5", "calc 와 Yield 를 따로", "range(3, 5)"):
            self.assertEqual(self.hits(text), [], text)

    def test_r2_short_values_only_two_chars_or_more(self):
        self.v.token_for("q", "word")
        self.assertEqual(self.hits("q q q"), [])

    def test_r3_patterns(self):
        for text in ("open(\"D:\\work\\a\")", "http://x.example.com/a", "a@example.com", "203.0.113.5",
                     "db01.example.local"):
            self.assertIn("R3", checks_of(self.hits(text)), text)
        for text in ("x = a / b", "../up 은 brief 에서만 센다", PY_CODE):
            self.assertNotIn("R3", checks_of(self.hits(text)), text)

    def test_r4_numbers(self):
        for text in ("x = 7", "for i in range(10):", "99 개", "SP-05 절", "PH_K7Q2"):
            self.assertNotIn("R4", checks_of(self.hits(text)), text)
        for text in ("temp = 350", "rate = 3.5", "2026-11-26 에", "\uff11\uff12\uff13", "09:30 시작", "x = .5",
                     "\u0663\u0665\u0660", "1e5", "007", "v1.2.3"):
            self.assertIn("R4", checks_of(self.hits(text)), text)
        self.assertEqual(self.hits("a 350 b 3.5\nc 7"), [{"check": "R4", "count": 2, "where": ["F01:L1"]}])

    def test_r4_masked_numbers_pass(self):
        masked, _s = mask_text("temp = %s · rate = %s · day %s" % (mk("350", "n"), mk("3.5", "n"),
                                                                   mk("2026-11-26", "n")), self.v, WORDS)
        self.assertEqual(self.hits(masked), [])

    def test_r5_blobs(self):
        for text in ("key = \"%s\"" % _secret_b64(), "sum %s" % _secret_hex()):
            self.assertIn("R5", checks_of(self.hits(text)), text)
        long_ident = "test_restore_name_returns_original_relative_path"
        for text in (long_ident, "self.assertEqual(res[\"hits\"][0][\"where\"], expected)", "pandas.DataFrame.groupby"):
            self.assertNotIn("R5", checks_of(self.hits(text)), text)

    def test_code_bodies_are_not_blocked_for_looking_like_code(self):
        for code in (PY_CODE, SQL_CODE, JSON_CODE):
            self.assertGreater(scan.blob_hits(code, self.p), 0)        # 자유 글이면 D5 가 막을 꼴이다
            self.assertEqual(self.hits(code), [], code)

    def test_r6_tokens(self):
        t = self.v.token_for("모래시계공정", "word")
        self.assertEqual(self.hits("아는 %s" % t), [])
        self.assertEqual(self.hits("모르는 PH_ZZZZ"), [{"check": "R6", "count": 1, "where": ["F01:L1"]}])
        self.assertIn("R6", checks_of(self.hits("깨진 ph_%s" % t[3:].lower())))
        self.assertIn("R6", checks_of(self.hits("남은 " + O)))
        self.assertIn("R6", checks_of(self.hits("남은 " + C)))

    def test_where_has_file_and_line_only(self):
        text = "a KITWORDALPHA\nb 350\nc D:\\x\nd PH_ZZZZ\ne %s\n" % _secret_b64()
        hits = self.hits(text, 7)
        self.assertEqual(checks_of(hits), ["R1", "R3", "R4", "R5", "R6"])
        for h in hits:
            for w in h["where"]:
                self.assertRegex(w, r"^F07:L\d+$")

    def test_bad_policy(self):
        with self.assertRaises(BundleError):
            residual_hits("a", None, self.v, 1)


# ---------------------------------------------------------------- 묶음

class Build(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="diode-bundle-")
        self.v = FakeVault()
        self.p = policy()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, rel, data):
        path = os.path.join(self.d, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        return rel

    def manifest(self, files, **over):
        m = {"format": 1, "kind": "bundle", "job": "J-0007", "files": files, "note": "가린 표와 코드 둘"}
        m.update(over)
        return m

    def build(self, m, job=None):
        return build_bundle(m, self.d, self.v, self.p, WORDS, job)

    def e04(self, m, job=None):
        with self.assertRaises(BundleError) as cm:
            self.build(m, job)
        self.assertEqual(cm.exception.code, "E-04")
        return cm.exception

    def test_ok_bundle(self):
        a = self.write("docs/a.md", "# %s 의 수율\n온도는 %s 이다\n" % (mk("모래시계공정"), mk("350", "n")))
        b = self.write("src/b.py", "def %s(rows):\n    return 모래시계공정 + %s\n" % (mk("calcYield", "i"), mk("350", "n")))
        res = self.build(self.manifest([{"path": a, "type": "doc"}, {"path": b, "type": "code"}]), "J-0007")
        self.assertTrue(res["ok"], res["hits"])
        self.assertEqual([f["name"] for f in res["files"]], ["F01.md", "F02.py"])
        self.assertEqual([f["type"] for f in res["files"]], ["doc", "code"])
        tw, tn = self.v.token_of("모래시계공정", "word"), self.v.token_of("350", "number")
        f1, f2 = res["files"]
        self.assertIn(tw, f1["text"])
        self.assertIn(tw, f2["text"])                     # 파일 사이에도 같은 값 같은 토큰 (자동 가림 포함)
        self.assertIn(tn, f2["text"])
        for f in res["files"]:
            raw = f["text"].encode("utf-8")
            self.assertEqual(f["bytes"], len(raw))
            self.assertEqual(f["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(f["lines"], 2)
        self.assertEqual(res["stats"], {"files": 2, "bytes": f1["bytes"] + f2["bytes"], "marked": 4, "auto": 1,
                                        "tokens": 3})
        self.assertEqual(res["note"], "가린 표와 코드 둘")
        self.assertEqual(self.v.file_real("F02.py"), "src/b.py")

    def test_names_are_stable_in_project(self):
        a = self.write("a.md", "가")
        b = self.write("b.md", "나 350")
        self.build(self.manifest([{"path": a, "type": "doc"}]))
        res = self.build(self.manifest([{"path": b, "type": "doc"}, {"path": a, "type": "doc"}]))
        self.assertEqual([f["name"] for f in res["files"]], ["F02.md", "F01.md"])     # manifest 차례 · 같은 원본 같은 이름
        self.assertEqual(res["hits"], [{"check": "R4", "count": 1, "where": ["F02:L1"]}])    # 자리는 나가는 이름의 번호

    def test_extensions(self):
        rels = [self.write(n, "가") for n in ("x/noext", "y.tar.gz", "z.verylongext", "w.a-b", "v.KitZip")]
        p = policy(extra=["kitzip"])
        res = build_bundle(self.manifest([{"path": r, "type": "doc"} for r in rels]), self.d, self.v, p, WORDS)
        self.assertTrue(res["ok"], res["hits"])
        self.assertEqual([f["name"] for f in res["files"]], ["F01.txt", "F02.gz", "F03.txt", "F04.txt", "F05.txt"])

    def test_job_optional_and_checked(self):
        a = self.write("a.md", "가")
        files = [{"path": a, "type": "doc"}]
        m = self.manifest(files)
        del m["job"]
        self.assertTrue(self.build(m)["ok"])
        self.assertTrue(self.build(m, "J-0009")["ok"])
        self.assertEqual(self.e04(self.manifest(files), "J-0009").where, ["job"])      # 다르면 거절
        for bad in ("J-7", "j-0007", "J-00071", 7, None):
            self.assertEqual(self.e04(self.manifest(files, job=bad)).where, ["job"], bad)

    def test_manifest_shape(self):
        a = self.write("a.md", "가")
        files = [{"path": a, "type": "doc"}]
        self.assertEqual(self.e04("x").where, ["(root)"])
        self.assertEqual(self.e04(self.manifest(files, extra=1)).where, ["(root)"])
        m = self.manifest(files)
        del m["files"]
        self.assertEqual(self.e04(m).where, ["(root)"])
        self.assertEqual(self.e04(self.manifest(files, format=2)).where, ["format"])
        self.assertEqual(self.e04(self.manifest(files, format=True)).where, ["format"])
        self.assertEqual(self.e04(self.manifest(files, kind="report")).where, ["kind"])
        self.assertEqual(self.e04(self.manifest(files, note=3)).where, ["note"])
        self.assertEqual(self.e04(self.manifest([{"path": a, "type": "image"}])).where, ["files[0].type"])
        self.assertEqual(self.e04(self.manifest([{"path": a}])).where, ["files[0]"])
        self.assertEqual(self.e04(self.manifest([{"path": a, "type": "doc", "x": 1}])).where, ["files[0]"])
        self.assertEqual(self.e04(self.manifest(files + files)).where, ["files[1].path"])     # 같은 파일 두 번

    def test_file_count_limits(self):
        self.assertEqual(self.e04(self.manifest([])).where, ["files"])
        rels = [self.write("f%02d.md" % i, "가") for i in range(bundle.MAX_BUNDLE_FILES + 1)]
        self.assertEqual(self.e04(self.manifest([{"path": r, "type": "doc"} for r in rels])).where, ["files"])
        res = self.build(self.manifest([{"path": r, "type": "doc"} for r in rels[:bundle.MAX_BUNDLE_FILES]]))
        self.assertTrue(res["ok"])
        self.assertEqual(res["files"][-1]["name"], "F20.md")

    def test_size_limits(self):
        big = self.write("big.md", "x" * (bundle.MAX_FILE_BYTES + 1))
        e = self.e04(self.manifest([{"path": big, "type": "doc"}]))
        self.assertEqual((e.where, e.reason), (["files[0]"], "size"))
        just = self.write("just.md", "x" * bundle.MAX_FILE_BYTES)
        self.assertTrue(self.build(self.manifest([{"path": just, "type": "doc"}]))["ok"])
        rels = [self.write("p%d.md" % i, "x" * (250 * 1024)) for i in range(5)]           # 합계 1.22 MiB
        e = self.e04(self.manifest([{"path": r, "type": "doc"} for r in rels]))
        self.assertEqual((e.where, e.reason), (["files"], "total"))

    def test_paths_stay_inside(self):
        self.write("in/a.md", "가")
        outside = tempfile.mkdtemp(prefix="diode-out-")
        self.addCleanup(shutil.rmtree, outside, True)
        with open(os.path.join(outside, "x.md"), "w", encoding="utf-8") as f:
            f.write("가")
        for path in ("../x.md", "in/../in/a.md", "/etc/hosts", "C:x.md", "C:\\x.md", "in\\..\\a.md", "",
                     "in//a.md", "./in/a.md", "in/a.md.", "in/a.md:s", "CON", "nul.md", "in/a\x00.md"):
            e = self.e04(self.manifest([{"path": path, "type": "doc"}]))
            self.assertEqual(e.where, ["files[0].path"], path)
        for path in ("in/none.md", "in"):                                     # 없는 파일 · 폴더
            e = self.e04(self.manifest([{"path": path, "type": "doc"}]))
            self.assertEqual((e.where, e.reason), (["files[0].path"], "missing"), path)
        self.assertTrue(self.build(self.manifest([{"path": "in\\a.md", "type": "doc"}]))["ok"])   # 역슬래시도 나눔

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink 없음")
    def test_links_refused(self):
        outside = tempfile.mkdtemp(prefix="diode-out-")
        self.addCleanup(shutil.rmtree, outside, True)
        target = os.path.join(outside, "x.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write("가")
        try:
            os.symlink(target, os.path.join(self.d, "link.md"))
            os.symlink(outside, os.path.join(self.d, "dirlink"))
        except (OSError, NotImplementedError):
            self.skipTest("링크를 만들 권한이 없음")
        for path in ("link.md", "dirlink/x.md"):
            e = self.e04(self.manifest([{"path": path, "type": "doc"}]))
            self.assertEqual((e.where, e.reason), (["files[0].path"], "link"), path)

    def test_binary_and_nul_refused(self):
        b = self.write("b.bin", b"\xff\xfe\x00\x01")
        e = self.e04(self.manifest([{"path": b, "type": "doc"}]))
        self.assertEqual((e.where, e.reason), (["files[0]"], "utf8"))
        n = self.write("n.md", "가\x00나")
        e = self.e04(self.manifest([{"path": n, "type": "doc"}]))
        self.assertEqual((e.where, e.reason), (["files[0]"], "nul"))

    def test_bad_mark_names_file_and_line_and_leaves_vault_alone(self):
        a = self.write("a.md", "좋은 " + mk("350", "n") + "\n")
        b = self.write("b.md", "하나\n둘\n셋 " + O + "열림\n")
        e = self.e04(self.manifest([{"path": a, "type": "doc"}, {"path": b, "type": "doc"}]))
        self.assertEqual((e.where, e.reason), (["files[1]:L3"], "unclosed"))         # 이름을 매기기 전 - manifest 차례
        self.assertEqual(self.v.tokens(), frozenset())             # 꼴이 틀리면 토큰 · 이름을 만들지 않는다
        self.assertIsNone(self.v.file_real("F01.md"))

    def test_residual_failure_returns_no_text(self):
        a = self.write("a.md", "남은 KITWORDALPHA 는 가렸다\n온도 350\n")
        res = self.build(self.manifest([{"path": a, "type": "doc"}]))
        self.assertFalse(res["ok"])
        self.assertEqual(res["hits"], [{"check": "R4", "count": 1, "where": ["F01:L2"]}])
        self.assertIsNone(res["files"][0]["text"])
        self.assertIsNone(res["files"][0]["sha256"])
        self.assertIsNone(res["note"])
        self.assertEqual(res["stats"]["auto"], 1)

    def test_note_checks(self):
        a = self.write("a.md", "가")
        files = [{"path": a, "type": "doc"}]
        for note, check in (("가람소재 를 보냄", "D2"), ("두 줄\n노트", "D1"), ("D:\\x 에서", "D3"),
                            ("온도 350", "D4"), ("../up 을 고침", "D3"), ("f(x) {", "D5"), ("PH_ZZZZ 를 보냄", "D6"),
                            ("[diode brief]", "D1"), ("가" * (bundle.MAX_NOTE_CHARS + 1), "D1"), (mk("a"), "D1")):
            res = self.build(self.manifest(files, note=note))
            self.assertFalse(res["ok"], note)
            self.assertIn({"check": check, "count": res["hits"][0]["count"], "where": ["note"]}, res["hits"], note)
        self.assertEqual(self.build(self.manifest(files, note="표 \u2014 둘"))["note"], "표 - 둘")     # 손질한 글
        m = self.manifest(files)
        del m["note"]
        self.assertEqual(self.build(m)["note"], "")

    def test_note_sees_vault_values(self):
        a = self.write("a.md", "처음 " + mk("노을빛"))
        res = self.build(self.manifest([{"path": a, "type": "doc"}], note="노을빛 을 고침"))
        self.assertEqual(checks_of(res["hits"]), ["D2"])

    def test_bad_inputs(self):
        a = self.write("a.md", "가")
        m = self.manifest([{"path": a, "type": "doc"}])
        with self.assertRaises(BundleError) as cm:
            build_bundle(m, self.d, self.v, None, WORDS)
        self.assertEqual(cm.exception.code, "E-20")
        with self.assertRaises(BundleError) as cm:
            build_bundle(m, os.path.join(self.d, "none"), self.v, self.p, WORDS)
        self.assertEqual(cm.exception.code, "E-04")

    def test_vault_errors_fail_closed_keep_code(self):
        class Full(FakeVault):
            def token_for(self, real, kind):
                e = RuntimeError("값이 든 글 KITWORDALPHA")
                e.code = "E-31"
                raise e

        class Broken(FakeVault):
            def token_for(self, real, kind):
                return "PH_1111"

        a = self.write("a.md", "가 " + mk("350", "n"))
        m = self.manifest([{"path": a, "type": "doc"}])
        for vault, code in ((Full(), "E-31"), (Broken(), "E-20")):
            with self.assertRaises(BundleError) as cm:
                build_bundle(m, self.d, vault, self.p, WORDS)
            self.assertEqual(cm.exception.code, code)
            self.assertNotIn("KITWORD", str(cm.exception) + repr(cm.exception.where))
            self.assertIsNone(cm.exception.__cause__)          # 원래 예외 (글에 값이 있을 수 있다) 를 잇지 않는다
            self.assertTrue(cm.exception.__context__ is None or cm.exception.__suppress_context__)


# ---------------------------------------------------------------- 되돌리기 · 들어오는 검사

class Restore(unittest.TestCase):
    def test_round_trip(self):
        v = FakeVault()
        text = ("# %s 표\r\n온도 %s · 날짜 %s\r\nopen(\"%s\")\r\ndef %s(): return calcYield\n"
                "kit-word alpha · loadKITWORDALPHAData · bx-7 라인 · 이미 PH_ZZZZ\n") % (
            mk("모래시계공정"), mk("350", "n"), mk("2026-11-26", "n"), mk("D:\\data\\a.csv", "p"), mk("calcYield", "i"))
        masked, stats = mask_text(text, v, WORDS)
        self.assertGreater(stats["auto"], 3)
        restored, n = restore_text(masked, v)
        self.assertEqual(restored, unmark(text))
        self.assertEqual(n, len(scan.TOKEN_RE.findall(masked)) - 1)          # PH_ZZZZ 는 금고에 없어 그대로

    def test_unknown_token_kept(self):
        v = FakeVault()
        t = v.token_for("가람소재", "word")
        self.assertEqual(restore_text("%s 와 PH_ZZZZ" % t, v), ("가람소재 와 PH_ZZZZ", 1))
        with self.assertRaises(BundleError):
            restore_text(None, v)

    def test_restore_name(self):
        v = FakeVault()
        self.assertEqual(v.file_name("docs/a.md", "md"), "F01.md")
        tw = v.token_for("가람소재", "word")
        tp = v.token_for("D:\\x", "path")
        td = v.token_for("..", "word")
        self.assertEqual(restore_name("F01.md", v), "docs/a.md")
        self.assertEqual(restore_name("F09.md", v), "F09.md")                # 금고가 모르는 묶음 이름 - 새 파일
        self.assertEqual(restore_name("%s_note.md" % tw, v), "가람소재_note.md")
        self.assertIsNone(restore_name("%s.md" % tp, v))                     # 되돌리니 경로 글자
        self.assertIsNone(restore_name("%s.md" % td, v))
        for bad in ("../x.md", "a/b.md", "a\\b.md", "", None, "a:b"):
            self.assertIsNone(restore_name(bad, v), bad)
        v._names["sub/z.py"] = "F100.py"
        self.assertEqual(restore_name("F100.py", v), "sub/z.py")             # 이름 꼴은 F + 2-4 자리
        v._names["../evil.md"] = "F101.md"
        self.assertIsNone(restore_name("F101.md", v))                         # 금고가 준 경로도 다시 본다


class ReturnChecks(unittest.TestCase):
    def setUp(self):
        self.v = FakeVault()
        self.p = policy()
        self.tw = self.v.token_for("모래시계공정", "word")
        self.v.token_for("calcYield", "ident")
        self.v.token_for("35", "number")

    def test_clean(self):
        res = return_checks("%s 를 고쳤다\n두 번째 줄 x = 3 + 5\n" % self.tw, self.v, self.p)
        self.assertEqual(res, {"U1": [], "U2": 0, "U3": []})

    def test_u1_u3(self):
        res = return_checks("가\nPH_ZZZZ 모름\nph_%s 깨짐\nhttps://x.example.com 봄\n" % self.tw[3:].lower(),
                            self.v, self.p)
        self.assertEqual(res["U1"], [2, 3])
        self.assertEqual(res["U3"], [4])

    def test_u2_real_words_written_by_claude(self):
        for text in ("모래시계공정 을 고쳤다", "calc_yield 함수", "KIT-WORD alpha", "값은 35 다"):
            self.assertGreater(return_checks(text, self.v, self.p)["U2"], 0, text)

    def test_crlf_lines(self):
        self.assertEqual(return_checks("a\r\nPH_ZZZZ\r\n", self.v, self.p)["U1"], [2])


# ---------------------------------------------------------------- 단어 없음 · 결정성

class NoWordsOut(unittest.TestCase):
    """AL-11: 결과 (가린 글 밖) · 예외에 단어 · 값 · 경로가 없다."""

    def _clean(self, s):
        for w in WORDS + ["calcYield", "350", "data", "secret-dir"]:
            self.assertNotIn(w, s)
            self.assertNotIn(w.lower(), s.lower())

    def test_errors(self):
        texts = ["KITWORDALPHA " + O + "가람소재", "350" + mk("calcYield"), mk("가람소재", "x"), mk("secret-dir") + "x"]
        for t in texts:
            with self.assertRaises(BundleError) as cm:
                parse_marks(t)
            e = cm.exception
            self._clean(str(e) + json.dumps(e.where) + str(e.reason) + repr(e.args))
            for w in e.where:
                self.assertRegex(w, SAFE_WHERE)

    def test_bundle_result(self):
        d = tempfile.mkdtemp(prefix="diode-bundle-")
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "secret-dir"))
        with open(os.path.join(d, "secret-dir", "data.md"), "w", encoding="utf-8") as f:
            f.write("KITWORDALPHA %s 남은 가람소재%s 350 calcYield\n" % (mk("calcYield", "i"), mk("x")))
        m = {"format": 1, "kind": "bundle", "files": [{"path": "secret-dir/data.md", "type": "doc"}],
             "note": "모래시계공정 350"}
        res = build_bundle(m, d, FakeVault(), policy(), WORDS)
        self.assertFalse(res["ok"])
        dumped = json.dumps(res, ensure_ascii=False)
        self._clean(dumped)
        for h in res["hits"]:
            for w in h["where"]:
                self.assertRegex(w, SAFE_WHERE)

    def test_checks_results(self):
        v = FakeVault()
        v.token_for("calcYield", "ident")
        s = json.dumps(residual_hits("KITWORDALPHA calcYield 350 D:\\data", policy(), v, 1))
        s += json.dumps(return_checks("가람소재 calcYield 350 http://data.example.com", v, policy()))
        self._clean(s)


class Determinism(unittest.TestCase):
    TEXT = ("# %s\nkit-word alpha 와 KITC_ORBIT_temp · %s · 가람소재 · BX-7 라인 · 모래시계공정\n"
            % (mk("calcYield", "i"), mk("350", "n")))

    def test_same_input_same_output(self):
        a = mask_text(self.TEXT, FakeVault(), WORDS)
        b = mask_text(self.TEXT, FakeVault(), WORDS)
        self.assertEqual(a, b)
        v = FakeVault()
        first = mask_text(self.TEXT, v, WORDS)
        second = mask_text(self.TEXT, v, WORDS)              # 같은 금고에 다시 - 이미 있는 값은 같은 토큰
        self.assertEqual(first[0], second[0])
        self.assertEqual(len(v.tokens()), first[1]["tokens"])

    def test_hash_seed_does_not_matter(self):
        code = ("import json, sys; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
                "from test_bundle import FakeVault, WORDS, Determinism, policy\n"
                "from diodelib.bundle import mask_text, residual_hits\n"
                "v = FakeVault(); m, s = mask_text(Determinism.TEXT, v, WORDS)\n"
                "print(json.dumps([m, s, residual_hits(m + ' KlTWORDALPHA 350', policy(), v, 1)], ensure_ascii=False))\n"
                % (ROOT, HERE))
        outs = set()
        for seed in ("1", "2", "3"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            p = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
            outs.add(p.stdout)
        self.assertEqual(len(outs), 1)


if __name__ == "__main__":
    unittest.main()
