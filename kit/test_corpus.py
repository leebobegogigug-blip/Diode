#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KIT-3 합성 말뭉치 시험 (작업 T3).

돌리기:  python3 -m unittest kit/test_corpus.py        (저장소 맨 위에서)
         python3 -m unittest test_corpus               (kit/ 안에서)
Python 3.8 이상 · 표준 라이브러리만 (jsonschema 가 있으면 형식 판정을 한 번 더 맞대어 본다).

지키는 것
  - 과제 40개 (plan 15 · ui 15 · lib 10) 가 모두 읽히고 꼴이 맞다.
  - good_brief 는 스키마를 통과하고, 카나리아 · 변형 · 사전 단어가 하나도 없고, SPEC 의 D1–D6 · D5a 에 걸리지 않는다.
  - leaky_briefs 는 모두 카나리아를 담고, 스키마를 통과하고, 검사 D1–D5a 중 하나 이상에 걸린다.
  - 모든 자료는 지어낸 것이고 공개 저장소에 둘 수 있다 (사설 주소 · example.com 뿐 · 비밀 흔적 없음).
  - canary_variants.py · leak_rate.py 가 정해진 대로 돈다.

옵션 환경 변수
  KIT3_RUN_REPRO=1     lib 과제의 합성 재현 코드를 이 PC 의 라이브러리로 돌려 error.type 과 같은 예외가 나는지 본다
  KIT3_WITH_CHECKER=1  diodelib.scan 이 있으면 good_brief 통과 · leaky_briefs 막음을 시험한다 (다른 작업자의 검사기 연결)
"""
import ast
import builtins
import glob
import importlib
import io
import json
import keyword
import math
import os
import re
import subprocess
import sys
import tempfile
import tokenize
import unicodedata
import unittest
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import canary_variants as cv  # noqa: E402
import leak_rate as lr  # noqa: E402

TASKS_DIR = os.path.join(HERE, "corpus", "tasks")
SCHEMA_PATH = os.path.join(ROOT, "schema", "brief.schema.json")

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None

TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])PH_[2-9A-HJKMNP-TV-Z]{4}(?![A-Za-z0-9])")
BROKEN_RE = re.compile(r"(?<![A-Za-z0-9_])ph[ _\-]?[0-9a-z]{3,5}(?![A-Za-z0-9])", re.I)
PLACEHOLDER_NAMES = set(["df", "a", "b", "c", "x", "y", "z", "i", "j", "k", "n", "s", "t", "item", "value", "key",
                         "data", "result", "row", "arr", "obj", "fn", "cls"] + ["col_%d" % d for d in range(1, 10)])
PLACEHOLDER_STRINGS = PLACEHOLDER_NAMES | set([""])
IMPORT_ALIASES = set(["pd", "np", "plt", "sns", "tf", "nn", "F", "sp", "mpl", "pl", "xr", "dd"])
KNOWN_TLDS = ("com", "net", "org", "io", "kr", "jp", "cn", "co", "us", "uk", "de", "dev", "app", "cloud", "ai", "edu",
              "gov", "biz", "info", "local", "lan", "corp", "internal", "intra", "intranet", "home", "localdomain")

# lib 과제의 합성 재현 코드 · error.type 이 쓰는 공개 이름 (이 PC 에 라이브러리가 있으면 실제 dir() 로 다시 확인한다)
PUBLIC_NAMES = {
    "pandas": ["DataFrame", "IntCastingNaNError", "Series", "astype", "columns", "errors", "groupby", "index", "mean",
               "merge", "pivot", "rolling", "values"],
    "numpy": ["arange", "reshape", "zeros"],
    "pydantic": ["BaseModel", "ValidationError"],
    "openpyxl": ["Workbook", "active", "cell"],
    "requests": ["SSLError", "exceptions"],
}

# 풀어 쓴 수 (한글 수사) 는 D4 가 못 잡는 알려진 한계라 (SPEC SP-05) good_brief 가 스스로 피한다.
NUMWORD_RE = re.compile(
    "(?<![가-힣])(둘|셋|넷|다섯|여섯|일곱|여덟|아홉)(의|가|를|로|도|만|씩)?(?![가-힣])"
    "|(?<![가-힣])(두|세|네|다섯|여섯|일곱|여덟|아홉|열)\\s?(가지|개|곳|번|대|기|단계|명|쪽|장|줄|종류|부서|사람|배|군데|차례|차|항목|건)(?![가-힣])"
    "|(?<![가-힣])(첫째|둘째|셋째|넷째|절반)(?![가-힣])"
    "|(?<![가-힣])(일|이|삼|사|오|육|칠|팔|구|십)\\s?(차|단계)(?![가-힣])")


# ───────────────────────────────────────────────────────── 말뭉치 읽기

def load_corpus() -> List[Dict[str, Any]]:
    return lr.load_tasks(TASKS_DIR)


_CORPUS_CACHE = {}  # type: Dict[str, Any]


def corpus() -> List[Dict[str, Any]]:
    if "tasks" not in _CORPUS_CACHE:
        _CORPUS_CACHE["tasks"] = load_corpus()
    return _CORPUS_CACHE["tasks"]


def lib_allow_names() -> List[str]:
    return lr.Context(corpus()).lib_allow


def task_tokens(task: Dict[str, Any]) -> Set[str]:
    return set(TOKEN_RE.findall(task["instruction"]))


# ───────────────────────────────────────────────────────── SPEC D1–D6 · D5a 를 작게 옮긴 점검기
# 검사기 (diodelib.scan) 와 따로 짠 것이다. 말뭉치가 SPEC 대로인지 스스로 확인하고, 검사기 시험의 기준표로 쓴다.

def _prepare(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    table = {"…": "...", "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "“": '"', "”": '"', "„": '"',
             "″": '"', "‘": "'", "’": "'", "‚": "'", "′": "'", "→": "->", "×": "x"}
    out = []
    for ch in s:
        out.append(", " if ch in "•·∙‧" else table.get(ch, ch))
    return "".join(out)


def _is_hangul(ch: str) -> bool:
    o = ord(ch)
    return 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F


def _allowed_text_char(ch: str) -> bool:
    return 0x20 <= ord(ch) <= 0x7E or _is_hangul(ch)


def free_text_fields(brief: Dict[str, Any]) -> List[Tuple[str, str]]:
    """SPEC SP-02 의 자유 글 칸 (plan · ui · lib)."""
    out = []  # type: List[Tuple[str, str]]
    if brief.get("kind") == "lib":
        if isinstance(brief.get("goal"), str):
            out.append(("goal", brief["goal"]))
        err = brief.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            out.append(("error.message", err["message"]))
        if isinstance(brief.get("ask"), str):
            out.append(("ask", brief["ask"]))
        return out
    if isinstance(brief.get("goal"), str):
        out.append(("goal", brief["goal"]))
    for i, x in enumerate(brief.get("context") or []):
        out.append(("context[%d]" % i, x))
    for i, e in enumerate(brief.get("entities") or []):
        if isinstance(e, dict) and isinstance(e.get("note"), str):
            out.append(("entities[%d].note" % i, e["note"]))
    for i, x in enumerate(brief.get("constraints") or []):
        out.append(("constraints[%d]" % i, x))
    if isinstance(brief.get("ask"), str):
        out.append(("ask", brief["ask"]))
    return out


_HOST_RE = re.compile(r"(?<![A-Za-z0-9\-.])(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+(?:%s)(?![A-Za-z0-9\-]|\.[A-Za-z0-9])"
                      % "|".join(KNOWN_TLDS), re.I)
_D3_PATTERNS = [
    re.compile(r"[A-Za-z]:[\\/]"), re.compile(r"\\\\"), re.compile(r"(?i)/(?:home|users)/"), re.compile(r"~[/\\]"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://"), re.compile(r"(?<![0-9.])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9])"),
    re.compile(r"[\w.+%\-]+@[\w\-]+(?:\.[\w\-]+)+"),
]


def _d3_count(text: str, lib_allow: Sequence[str]) -> int:
    n = sum(len(p.findall(text)) for p in _D3_PATTERNS)
    for m in _HOST_RE.finditer(text):
        if m.group(0).split(".")[0].lower() in [x.lower() for x in lib_allow]:
            continue
        n += 1
    return n


def _d4_count(text: str) -> int:
    s = unicodedata.normalize("NFKC", TOKEN_RE.sub(" ", text))
    return sum(1 for ch in s if unicodedata.category(ch) == "Nd")


def _entropy(s: str) -> float:
    cnt = {}  # type: Dict[str, int]
    for ch in s:
        cnt[ch] = cnt.get(ch, 0) + 1
    n = float(len(s))
    return -sum((c / n) * math.log(c / n, 2) for c in cnt.values())


def _d5_count(text: str) -> int:
    s = TOKEN_RE.sub(" ", text)
    n = s.count("```")
    n += len(re.findall(r"[A-Za-z0-9+/]{24,}={0,2}", s))
    n += len(re.findall(r"[0-9A-Fa-f]{16,}", s))
    for m in re.finditer(r"\S{20,}", s):
        chunk = m.group(0)
        if re.fullmatch(r"[\x21-\x7e]+", chunk) and _entropy(chunk) >= 4.0:
            n += 1
    return n


def check_repro(code: str, lib_allow: Sequence[str], public: Set[str]) -> List[int]:
    """D5a: 걸린 줄 번호 (비면 통과). 이름은 예약어 · 내장 이름 · 자리 이름 · 공개 이름만, 글은 자리 글만, 주석 없음, 수는 세 자리 이하."""
    bad = []  # type: List[int]
    code = code.replace("\r\n", "\n")
    lines = code.split("\n")
    if len(code.rstrip("\n").split("\n")) > 40:
        bad.append(41)
    for no, line in enumerate(lines, 1):
        if any(not (0x20 <= ord(ch) <= 0x7E or ch == "\t") for ch in line):
            bad.append(no)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return sorted(set(bad + [e.lineno or 1]))
    allow = [x.lower() for x in lib_allow]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name.split(".")[0].lower() not in allow:
                    bad.append(node.lineno)
                if al.asname and al.asname not in IMPORT_ALIASES and al.asname not in PLACEHOLDER_NAMES:
                    bad.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            bad.append(node.lineno)
    names = set(keyword.kwlist) | set(dir(builtins)) | PLACEHOLDER_NAMES | IMPORT_ALIASES | set(public) | set(lib_allow)
    for t in (str, bytes, list, dict, set, frozenset, tuple, int, float, bool, object, BaseException):
        names.update(dir(t))
    nums = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER, tokenize.OP):
                continue
            line = tok.start[0]
            if tok.type == tokenize.NAME:
                if tok.string not in names and not TOKEN_RE.fullmatch(tok.string):
                    bad.append(line)
            elif tok.type == tokenize.STRING:
                try:
                    v = ast.literal_eval(tok.string)
                except Exception:
                    bad.append(line)
                    continue
                if not isinstance(v, str) or tok.string[0] not in "\"'" or not (v in PLACEHOLDER_STRINGS or TOKEN_RE.fullmatch(v)):
                    bad.append(line)
            elif tok.type == tokenize.NUMBER:
                nums += 1
                if not re.fullmatch(r"[0-9]{1,3}", tok.string) or nums > 20:
                    bad.append(line)
            else:
                bad.append(line)
    except (tokenize.TokenError, SyntaxError, IndentationError):
        bad.append(len(lines))
    return sorted(set(bad))


def mini_check(brief: Dict[str, Any], dictionary: Sequence[str], tokens: Set[str], lib_allow: Sequence[str],
               public: Optional[Set[str]] = None) -> Dict[str, List[str]]:
    """SPEC 의 D1–D6 · D5a 중 걸린 검사 → 걸린 자리 (칸 이름). 비면 통과. (형식의 스키마 판정은 따로 본다.)"""
    hits = {}  # type: Dict[str, List[str]]

    def add(check: str, where: str) -> None:
        hits.setdefault(check, [])
        if where not in hits[check]:
            hits[check].append(where)

    kind = brief.get("kind")
    fields = [(w, _prepare(t)) for w, t in free_text_fields(brief)]
    if kind == "lib" and str((brief.get("library") or {}).get("name", "")).lower() not in [x.lower() for x in lib_allow]:
        add("D1", "library.name")
    for w, t in fields:
        if any(not _allowed_text_char(ch) for ch in t) or "\n" in t:
            add("D1", w)
    if len(json.dumps(brief, ensure_ascii=False).encode("utf-8")) > 7000:
        add("D1", "(size)")
    for slot in ("entities", "fields"):
        for i, e in enumerate(brief.get(slot) or []):
            if e.get("token") not in tokens:
                add("D6", "%s[%d].token" % (slot, i))
    for w, t in fields:
        if any(tk not in tokens for tk in TOKEN_RE.findall(t)):
            add("D6", w)
        if any(not TOKEN_RE.fullmatch(m.group(0)) for m in BROKEN_RE.finditer(TOKEN_RE.sub(" ", t))):
            add("D6", w)
    keys = [cv.normalize(x) for x in dictionary if len(cv.normalize(x)) >= 2]
    for w, t in fields:
        k = cv.normalize(t)
        k2 = cv.normalize(TOKEN_RE.sub("", t))
        if any(x in k or x in k2 for x in keys):
            add("D2", w)
    joined = cv.normalize("".join(t for _w, t in fields))
    if "D2" not in hits and any(x in joined for x in keys):
        add("D2", "*")
    for w, t in fields:
        if _d3_count(t, lib_allow):
            add("D3", w)
        if _d4_count(t):
            add("D4", w)
        if _d5_count(t):
            add("D5", w)
    if kind == "lib" and isinstance(brief.get("repro"), str) and brief["repro"]:
        for no in check_repro(brief["repro"], lib_allow, public or set()):
            add("D5a", "repro:%d" % no)
    return hits


def numword_fields(brief: Dict[str, Any]) -> List[str]:
    return [w for w, t in free_text_fields(brief) if NUMWORD_RE.search(t)]


def validate_schema(brief: Any) -> List[str]:
    """스키마 위반 목록 (jsonschema 가 있으면 그것으로 · 없으면 leak_rate 의 MiniSchema 로)."""
    with io.open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    if jsonschema is not None:
        v = jsonschema.Draft202012Validator(schema)
        return ["%s %s" % (list(e.absolute_path), e.validator) for e in v.iter_errors(brief)]
    return ["%s %s" % e for e in lr.MiniSchema(schema).errors(brief)]


def run_py(args: Sequence[str], cwd: Optional[str] = None, env_extra: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
    p = subprocess.run([sys.executable] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace")


# ───────────────────────────────────────────────────────── 말뭉치 꼴

class CorpusShapeTest(unittest.TestCase):
    def test_forty_tasks(self) -> None:
        tasks = corpus()
        self.assertEqual(len(tasks), 40)
        self.assertEqual([t["id"] for t in tasks], ["T3-%02d" % i for i in range(1, 41)])
        files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(TASKS_DIR, "*.json")))
        self.assertEqual(files, [t["id"] + ".json" for t in tasks])
        kinds = [t["kind"] for t in tasks]
        self.assertEqual(kinds.count("plan"), 15)
        self.assertEqual(kinds.count("ui"), 15)
        self.assertEqual(kinds.count("lib"), 10)
        self.assertEqual(set(kinds[:15]), {"plan"})
        self.assertEqual(set(kinds[15:30]), {"ui"})
        self.assertEqual(set(kinds[30:]), {"lib"})

    def test_fields(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                for k in ("id", "kind", "domain", "instruction", "raw"):
                    self.assertIsInstance(t[k], str)
                    self.assertTrue(t[k].strip())
                self.assertIsInstance(t["canaries"], list)
                self.assertIsInstance(t["dictionary"], list)
                self.assertIsInstance(t["good_brief"], dict)
                self.assertIsInstance(t["leaky_briefs"], list)
                self.assertEqual(t["good_brief"]["kind"], t["kind"])
                self.assertEqual(t["good_brief"]["data_class"], "synthetic")

    def test_domain_spread(self) -> None:
        heads = [t["domain"].split(" · ")[0] for t in corpus()]
        self.assertGreaterEqual(len(set(heads)), 10)
        for h in set(heads):
            self.assertLessEqual(heads.count(h), 8, "한 분야에 몰림: %s" % h)
        for need in ("제조", "화학", "식품", "물류", "금융", "의료기기", "에너지"):
            self.assertIn(need, heads)

    def test_canaries(self) -> None:
        seen_classes = set()  # type: Set[str]
        for t in corpus():
            with self.subTest(task=t["id"]):
                cs = t["canaries"]
                self.assertTrue(5 <= len(cs) <= 10, "카나리아 %d개" % len(cs))
                self.assertEqual([c["id"] for c in cs], ["C%d" % (i + 1) for i in range(len(cs))])
                for c in cs:
                    self.assertIn(c["class"], cv.CLASSES)
                    seen_classes.add(c["class"])
                    self.assertIsInstance(c["value"], str)
                    self.assertIn(c["value"], t["raw"], "%s 가 원자료에 없다" % c["id"])
                    for a in c.get("aliases", []):
                        self.assertIn(a, t["raw"], "별칭 %r 가 원자료에 없다" % a)
                    if c["class"] == "number":
                        self.assertGreaterEqual(len(re.sub(r"\D", "", c["value"])), 4, "수치는 숫자 넉 자리 이상")
                    if c["class"] == "host":
                        self.assertTrue(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", c["value"])
                                        or c["value"].split(".")[-1] in KNOWN_TLDS, "검사기가 볼 수 있는 호스트 꼴이어야 한다")
                    if c["class"] == "path":
                        self.assertTrue(re.match(r"^([A-Za-z]:\\|\\\\|/home/)", c["value"]), "검사기가 볼 수 있는 경로 꼴이어야 한다")
                self.assertTrue(any("KITC" in c["value"].upper() for c in cs), "KITC 머리가 든 카나리아가 하나는 있어야 한다")
        self.assertEqual(seen_classes, set(cv.CLASSES))

    def test_class_distribution(self) -> None:
        count = {}  # type: Dict[str, int]
        for t in corpus():
            for c in t["canaries"]:
                count[c["class"]] = count.get(c["class"], 0) + 1
        for cls in cv.CLASSES:
            self.assertGreaterEqual(count.get(cls, 0), 30, "%s 가 너무 적다" % cls)

    def test_dictionary(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                d = t["dictionary"]
                self.assertEqual(len(d), len(set(d)))
                for c in t["canaries"]:
                    if c["class"] in ("name", "code"):
                        self.assertIn(c["value"], d)
                        for a in c.get("aliases", []):
                            self.assertIn(a, d)
                    else:
                        self.assertNotIn(c["value"], d)
                for w in d:
                    self.assertGreaterEqual(len(cv.normalize(w)), 2)
                # 한 과제의 사전 단어가 다른 사전 단어의 일부이면 개수가 겹쳐 센다
                keys = [cv.normalize(w) for w in d]
                for i, a in enumerate(keys):
                    for j, b in enumerate(keys):
                        if i != j:
                            self.assertNotIn(a, b, "사전 단어끼리 겹침")

    def test_raw_looks_real(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                lines = t["raw"].strip().splitlines()
                self.assertGreaterEqual(len(lines), 15, "원자료가 짧다")
                self.assertIn("(가상", t["raw"], "지어낸 자료라는 표시가 없다")
                self.assertIn("[표기 메모]", t["raw"])
                if t["kind"] == "lib":
                    self.assertIn("import ", t["raw"])
                    self.assertTrue(re.search(r"(Error|Traceback)", t["raw"]), "오류 글이 없다")

    def test_instruction(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                ins = t["instruction"]
                self.assertIn("brief.json", ins)
                self.assertIn("[원자료]", ins)
                toks = TOKEN_RE.findall(ins)
                self.assertEqual(len(toks), len(set(toks)))
                self.assertEqual(len(toks), 3 if t["kind"] == "lib" else 12)
                self.assertIn('kind 는 "%s"' % t["kind"], ins)
                if t["kind"] == "lib":
                    self.assertIn("합성 재현 코드", ins)
                    self.assertIn("repro", ins)
                if t["kind"] == "ui":
                    self.assertIn("HTML 한 파일", ins)

    def test_public_repo_safety(self) -> None:
        """실재하는 주소 · 비밀이 없다: 호스트는 example.com / .local 등, IP 는 사설 대역, 키 · 비밀번호 꼴 없음."""
        host_ok = re.compile(r"(\.example\.(com|org|net)|\.local|\.corp\.local|\.internal|\.test)$", re.I)
        for t in corpus():
            with self.subTest(task=t["id"]):
                blob = json.dumps(t, ensure_ascii=False)
                for m in re.finditer(r"://([A-Za-z0-9.\-]+)", blob):
                    self.assertRegex(m.group(1), host_ok, "공개 주소가 있다")
                for m in re.finditer(r"(?<![0-9.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9.])", blob):
                    a, b = int(m.group(1)), int(m.group(2))
                    private = a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
                    self.assertTrue(private, "사설 대역이 아닌 IP")
                for m in re.finditer(r"\b([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.(?:com|net|org|io|kr|jp|cn|dev|app|ai))\b", blob):
                    host = m.group(1).lower()
                    self.assertTrue(host.endswith(("example.com", "example.org", "example.net")) or host.startswith(
                        ("pandas.", "numpy.", "requests.", "pydantic.", "openpyxl.")), "공개 주소 꼴: %s" % host)
                self.assertNotRegex(blob, r"AKIA[0-9A-Z]{16}")
                self.assertNotRegex(blob, r"-----BEGIN")
                self.assertNotRegex(blob, r"(?i)(password|passwd|secret|api[_-]?key|bearer)\s*[=:]")
                self.assertNotRegex(blob, r"[\w.+\-]+@[\w\-]+\.[\w.\-]+", "메일 꼴이 있다")

    def test_readme_numbers_match_corpus(self) -> None:
        """corpus/README.md 에 적힌 말뭉치 숫자 (돌려서 얻은 값) 가 지금 말뭉치와 같다."""
        with io.open(os.path.join(HERE, "corpus", "README.md"), "r", encoding="utf-8") as fh:
            text = fh.read()
        tasks = corpus()
        cls = {}  # type: Dict[str, int]
        for t in tasks:
            for c in t["canaries"]:
                cls[c["class"]] = cls.get(c["class"], 0) + 1
        m = re.search(r"카나리아 (\d+)개: name (\d+) · number (\d+) · path (\d+) · host (\d+) · id (\d+) · code (\d+)", text)
        self.assertIsNotNone(m, "README 에 카나리아 수 줄이 없다")
        self.assertEqual([int(x) for x in m.groups()], [sum(cls.values())] + [cls[k] for k in ("name", "number", "path", "host", "id", "code")])
        m = re.search(r"별칭이 붙은 카나리아 (\d+)개 \(별칭 (\d+)개\) · 사전 단어 (\d+)개 · 새는 brief (\d+)개", text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), sum(1 for t in tasks for c in t["canaries"] if c.get("aliases")))
        self.assertEqual(int(m.group(2)), sum(len(c.get("aliases", [])) for t in tasks for c in t["canaries"]))
        self.assertEqual(int(m.group(3)), sum(len(t["dictionary"]) for t in tasks))
        self.assertEqual(int(m.group(4)), sum(len(t["leaky_briefs"]) for t in tasks))
        rows = re.findall(r"^\| (T3-\d\d) \| (\w+) \| (.+?) \| (\d+) \|", text, re.M)
        self.assertEqual([(r[0], r[1], r[2], int(r[3])) for r in rows], [(t["id"], t["kind"], t["domain"], len(t["canaries"])) for t in tasks])
        total = sum(cls.values())
        self.assertIn("n/%d" % total, text)

    def test_no_canary_cross_counting(self) -> None:
        """한 카나리아의 변형 열쇠가 같은 과제의 다른 카나리아 값 안에 들어 있으면 하나를 새게 할 때 둘이 센다."""
        for t in corpus():
            with self.subTest(task=t["id"]):
                ms = lr.build_matchers(t)
                for a in ms:
                    for b in t["canaries"]:
                        if a.id == b["id"]:
                            continue
                        texts = [b["value"]] + list(b.get("aliases", []))
                        lk = [cv.normalize_loose(x) for x in texts]
                        dk = [cv.normalize(x) for x in texts]
                        for key in a.loose:
                            self.assertFalse(any(key in x for x in lk), "%s 의 열쇠가 %s 안에 있다" % (a.id, b["id"]))
                        for key in a.d2:
                            self.assertFalse(any(key in x for x in dk), "%s 의 D2 열쇠가 %s 안에 있다" % (a.id, b["id"]))


# ───────────────────────────────────────────────────────── 좋은 추상화

class GoodBriefTest(unittest.TestCase):
    def test_schema(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                self.assertEqual(validate_schema(t["good_brief"]), [])

    def test_no_canary_in_any_cell(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                leaks = lr.scan_obj(lr.build_matchers(t), obj=t["good_brief"])
                self.assertEqual(leaks, [])
                text = json.dumps(t["good_brief"], ensure_ascii=False)
                for c in t["canaries"]:
                    self.assertNotIn(c["value"], text)
                    for a in c.get("aliases", []):
                        self.assertNotIn(a, text)
                keys = [cv.normalize(w) for w in t["dictionary"]]
                for _p, s, _k in lr.iter_strings(t["good_brief"]):
                    n = cv.normalize(s)
                    for k in keys:
                        self.assertNotIn(k, n, "사전 단어가 brief 에 있다")

    def test_spec_rules(self) -> None:
        allow = lib_allow_names()
        for t in corpus():
            with self.subTest(task=t["id"]):
                g = t["good_brief"]
                lib = (g.get("library") or {}).get("name")
                public = set(PUBLIC_NAMES.get(lib, [])) if lib else set()
                self.assertEqual(mini_check(g, t["dictionary"], task_tokens(t), allow, public), {})
                self.assertEqual(numword_fields(g), [], "풀어 쓴 수가 있다")

    def test_tokens(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                g = t["good_brief"]
                used = TOKEN_RE.findall(json.dumps(g, ensure_ascii=False))
                self.assertTrue(set(used) <= task_tokens(t), "지시문에 없는 토큰")
                slots = [e["token"] for e in g.get("entities", [])] + [f["token"] for f in g.get("fields", [])]
                self.assertEqual(len(slots), len(set(slots)), "같은 토큰을 두 대상에 썼다")
                if t["kind"] != "lib":
                    self.assertGreaterEqual(len(g.get("entities", [])), 4)
                    self.assertGreaterEqual(len(g.get("fields", [])), 4)
                    self.assertTrue(g.get("context"))
                    self.assertTrue(g.get("constraints"))

    def test_ui_asks_for_single_html(self) -> None:
        for t in corpus():
            if t["kind"] == "ui":
                with self.subTest(task=t["id"]):
                    self.assertIn("HTML 한 파일", t["good_brief"]["ask"])
                    self.assertTrue(any("HTML 한 파일" in c for c in t["good_brief"]["constraints"]))

    def test_lib_repro_names_exist(self) -> None:
        """재현 코드 · error.type 의 공개 이름이 정말 그 라이브러리에 있다 (라이브러리가 이 PC 에 있을 때)."""
        checked = 0
        for lib, names in PUBLIC_NAMES.items():
            got = lr.public_names(lib)
            if got is None:
                continue
            checked += 1
            for n in names:
                self.assertIn(n, got, "%s 에 %s 가 없다" % (lib, n))
        if checked == 0:
            self.skipTest("이 PC 에는 시험에 쓰는 라이브러리가 없다")

    @unittest.skipUnless(os.environ.get("KIT3_RUN_REPRO") == "1", "KIT3_RUN_REPRO=1 일 때만 (라이브러리 판에 따라 오류 글이 다르다)")
    def test_lib_repro_raises_declared_error(self) -> None:
        prog = ("import sys, warnings\nwarnings.simplefilter('ignore')\nsrc = sys.stdin.read()\n"
                "try:\n    exec(compile(src, '<repro>', 'exec'), {})\n    print('NOERROR')\n"
                "except BaseException as e:\n    print(type(e).__name__)\n")
        for t in corpus():
            g = t["good_brief"]
            if t["kind"] == "lib" and g.get("repro"):
                with self.subTest(task=t["id"]):
                    p = subprocess.run([sys.executable, "-c", prog], input=g["repro"].encode("utf-8"),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
                    self.assertEqual(p.stdout.decode("utf-8").strip().splitlines()[-1], g["error"]["type"].split(".")[-1])

    def test_lib_tasks_shape(self) -> None:
        libs = set()
        for t in corpus():
            if t["kind"] != "lib":
                continue
            with self.subTest(task=t["id"]):
                g = t["good_brief"]
                self.assertEqual(g["language"], "python")
                libs.add(g["library"]["name"])
                self.assertTrue(re.fullmatch(r"[0-9]+\.[0-9]+", g["library"]["version"]))
                self.assertIn("error", g)
                if "repro" in g:
                    self.assertLessEqual(len(g["repro"].splitlines()), 40)
                    self.assertNotIn("#", g["repro"])
        self.assertGreaterEqual(len(libs), 4)


# ───────────────────────────────────────────────────────── 새는 추상화

class LeakyBriefTest(unittest.TestCase):
    def test_two_or_three_each(self) -> None:
        for t in corpus():
            with self.subTest(task=t["id"]):
                self.assertTrue(2 <= len(t["leaky_briefs"]) <= 3)
                self.assertEqual(len(t["leaky_notes"]), len(t["leaky_briefs"]))

    def test_schema(self) -> None:
        for t in corpus():
            for i, lb in enumerate(t["leaky_briefs"]):
                with self.subTest(task=t["id"], leaky=i):
                    self.assertEqual(validate_schema(lb), [], "새는 brief 도 형식은 맞아야 D2–D5 를 시험할 수 있다")

    def test_each_contains_a_canary(self) -> None:
        for t in corpus():
            ms = lr.build_matchers(t)
            for i, lb in enumerate(t["leaky_briefs"]):
                with self.subTest(task=t["id"], leaky=i):
                    found = {l["canary"] for l in lr.scan_obj(ms, obj=lb)}
                    self.assertTrue(found, "카나리아가 없다")

    def test_notes_match_detection_and_spec_checks(self) -> None:
        allow = lib_allow_names()
        for t in corpus():
            ms = lr.build_matchers(t)
            g = t["good_brief"]
            lib = (g.get("library") or {}).get("name")
            public = set(PUBLIC_NAMES.get(lib, [])) if lib else set()
            for i, (lb, note) in enumerate(zip(t["leaky_briefs"], t["leaky_notes"])):
                with self.subTest(task=t["id"], leaky=i):
                    found = sorted({l["canary"] for l in lr.scan_obj(ms, obj=lb)}, key=lambda s: (len(s), s))
                    self.assertEqual(found, note["leaks"])
                    hits = mini_check(lb, t["dictionary"], task_tokens(t), allow, public)
                    self.assertEqual(sorted(hits), note["expect"])
                    self.assertTrue(hits, "SPEC 의 검사가 잡지 못한다")
                    self.assertTrue(set(hits) <= {"D1", "D2", "D3", "D4", "D5", "D5a"})
                    self.assertTrue(note["how"])
                    self.assertNotEqual(lb, g)

    def test_every_check_and_class_is_covered(self) -> None:
        checks = set()  # type: Set[str]
        classes = set()  # type: Set[str]
        families = set()  # type: Set[str]
        for t in corpus():
            ms = lr.build_matchers(t)
            cls = {c["id"]: c["class"] for c in t["canaries"]}
            for lb, note in zip(t["leaky_briefs"], t["leaky_notes"]):
                checks.update(note["expect"])
                classes.update(cls[c] for c in note["leaks"])
                families.update(l["family"] for l in lr.scan_obj(ms, obj=lb))
        self.assertTrue({"D1", "D2", "D3", "D4", "D5a"} <= checks, checks)
        self.assertEqual(classes, set(cv.CLASSES))
        for fam in ("exact", "alias", "case", "ident", "fullwidth"):
            self.assertIn(fam, families, "새는 꼴 %s 가 하나도 없다" % fam)


# ───────────────────────────────────────────────────────── 변형 만들기

class VariantsTest(unittest.TestCase):
    def test_spec_examples_for_numbers(self) -> None:
        v = cv.variants("350도", "number")
        self.assertEqual(v[0], "350도")
        for want in ("350 °C", "350℃", "３５０", "삼백오십도", "623.15K", "662°F"):
            self.assertTrue(want in v or want.replace(" ", "") in [x.replace(" ", "") for x in v], want)

    def test_name_families(self) -> None:
        items = cv.variant_items("KitWord Alpha", "name", ["키트워드"])
        fams = {f for f, _t in items}
        for f in ("exact", "case", "space", "hyphen", "underscore", "dot", "fullwidth", "alias", "affix", "ident", "comment", "string"):
            self.assertIn(f, fams)
        texts = [t for _f, t in items]
        for want in ("KITWORD ALPHA", "kitword alpha", "Kit Word Alpha", "kit_word_alpha", "kitWordAlpha",
                     "KitWordAlpha", "KitWord-Alpha", "KitWord.Alpha", "ＫｉｔＷｏｒｄ\u3000Ａｌｐｈａ", "# KitWord Alpha",
                     '"KitWord Alpha"', "키트워드"):
            self.assertIn(want, texts)

    def test_normalization_folds_variants(self) -> None:
        base = cv.normalize("KITWORDALPHA")
        for s in ("kit-word alpha", "ＫＩＴＷＯＲＤＡＬＰＨＡ", "KitWordAlpha.", "KIT_WORD/ALPHA", "Kit·Word Alpha"):
            self.assertEqual(cv.normalize(s), base, s)
        self.assertNotEqual(cv.normalize("D:\\a"), cv.normalize("D:/a"))                  # D2 는 역슬래시를 지우지 않는다
        self.assertEqual(cv.normalize_loose("D:\\a"), cv.normalize_loose("D:/a"))         # 느슨한 정규화는 지운다

    def test_hangul_alias_mix(self) -> None:
        texts = cv.variants("가람 소재", "name", ["Garam Materials"])
        for want in ("Garam Materials", "가람 Materials", "Garam 소재", "가람 소재(Garam Materials)"):
            self.assertIn(want, texts)

    def test_code_identifier_forms(self) -> None:
        texts = cv.variants("calc_soak_ramp", "code")
        for want in ("calcSoakRamp", "CalcSoakRamp", "CALC_SOAK_RAMP", "calc-soak-ramp", "get_calc_soak_ramp", "self.calc_soak_ramp"):
            self.assertIn(want, texts)

    def test_path_host_id_forms(self) -> None:
        p = cv.variants("D:\\KITC_열처리\\로그\\furnace_rev12.csv", "path")
        for want in ("D:/KITC_열처리/로그/furnace_rev12.csv", "d:\\KITC_열처리\\로그\\furnace_rev12.csv", "furnace_rev12.csv"):
            self.assertIn(want, p)
        ip = ".".join(("10", "20", "30", "41"))        # 소스 글에 사설 주소 꼴을 그대로 적지 않는다 (자기 검사기 W-12)
        h = cv.variants(ip, "host")
        for want in (ip + ":8080", "%03d.%03d.%03d.%03d" % (10, 20, 30, 41), "0x0A141E29", "http://" + ip):
            self.assertIn(want, h)
        h2 = cv.variants("kitc-mes01.example.com", "host")
        self.assertIn("KITC-MES01.EXAMPLE.COM", h2)
        self.assertIn("kitc-mes01", h2)
        i = cv.variants("KITC-S20417", "id")
        for want in ("KITCS20417", "kitc-s20417", "S20417", "20417"):
            self.assertIn(want, i)

    def test_number_unit_conversion_and_hangul(self) -> None:
        v = cv.variants("3.8 MPa", "number")
        for want in ("3800 kPa", "38 bar", "3800000 Pa"):
            self.assertIn(want, v)
        self.assertEqual(cv.ko_int(1285), "천이백팔십오")
        self.assertEqual(cv.ko_int(12400), "일만이천사백")
        self.assertEqual(cv.ko_int(350), "삼백오십")
        pct = cv.variants("94.6%", "number")
        self.assertIn("구십사점육퍼센트", pct)
        self.assertIn("0.946", pct)

    def test_errors(self) -> None:
        with self.assertRaises(ValueError):
            cv.variants("값", "nothing")
        with self.assertRaises(ValueError):
            cv.variants("  ", "name")

    def test_every_canary_has_variants_found_by_the_scanner(self) -> None:
        """말뭉치의 모든 카나리아에 대해, 변형 몇 개를 brief 한 칸에 넣으면 leak_rate 가 그 카나리아로 센다."""
        for t in corpus():
            ms = lr.build_matchers(t)
            for c in t["canaries"]:
                items = cv.variant_items(c["value"], c["class"], c.get("aliases"))
                self.assertGreater(len(items), 40, "%s %s 변형이 너무 적다" % (t["id"], c["id"]))
                for fam in ("exact", "fullwidth", "affix", "comment", "string"):
                    text = next((x for f, x in items if f == fam), None)
                    if text is None:
                        self.assertEqual(fam, "fullwidth", "%s %s 에 %s 꼴이 없다" % (t["id"], c["id"], fam))
                        self.assertFalse(any(ord(ch) < 128 and ch.strip() for ch in c["value"]))   # 한글뿐인 값은 전각 변형이 같다
                        continue
                    obj = {"goal": text}
                    ids = {l["canary"] for l in lr.scan_obj(ms, obj=obj)}
                    self.assertIn(c["id"], ids, "%s %s 의 %s 꼴을 못 찾음" % (t["id"], c["id"], fam))

    def test_cli(self) -> None:
        code, out = run_py([os.path.join(HERE, "canary_variants.py"), "가람소재", "--class", "name", "--alias", "Garam Materials"])
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "가람소재")
        self.assertIn("Garam Materials", lines)
        self.assertGreater(len(lines), 100)
        code, out = run_py([os.path.join(HERE, "canary_variants.py"), "350도", "--class", "number", "--families"])
        self.assertEqual(code, 0)
        self.assertIn("단위 바꿈\t623.15K", out)
        code, out = run_py([os.path.join(HERE, "canary_variants.py"), "x", "--class", "nothing"])
        self.assertEqual(code, 2)
        code, out = run_py([os.path.join(HERE, "canary_variants.py"), "350도", "--class", "number", "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0], {"family": "exact", "text": "350도"})


# ───────────────────────────────────────────────────────── 새는 비율 계산기

def write_briefs(folder: str, tasks: Sequence[Dict[str, Any]], pick: Any) -> None:
    for t in tasks:
        b = pick(t)
        if b is None:
            continue
        with io.open(os.path.join(folder, t["id"] + ".json"), "w", encoding="utf-8", newline="\n") as fh:
            if isinstance(b, str):
                fh.write(b)
            else:
                json.dump(b, fh, ensure_ascii=False)


class LeakRateTest(unittest.TestCase):
    def test_self_test_command(self) -> None:
        code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--self-test"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip().splitlines()[-1], "결과: OK")
        self.assertIn("good_brief 40개", out)
        self.assertIn("leaky_briefs 120개", out)

    def test_self_test_fails_when_a_good_brief_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for t in corpus():
                t2 = json.loads(json.dumps(t))
                if t2["id"] == "T3-01":
                    t2["good_brief"]["goal"] = t2["good_brief"]["goal"] + " " + t2["canaries"][0]["value"]
                if t2["id"] == "T3-02":
                    t2["leaky_briefs"] = [t2["good_brief"], t2["good_brief"]]
                    t2["leaky_notes"] = []
                with io.open(os.path.join(d, t2["id"] + ".json"), "w", encoding="utf-8") as fh:
                    json.dump(t2, fh, ensure_ascii=False)
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--self-test", "--tasks", d])
        self.assertEqual(code, 1, out)
        self.assertIn("T3-01 good_brief 에 새는 것", out)
        self.assertIn("T3-02 leaky_briefs[0] 에서 카나리아를 못 찾음", out)
        self.assertEqual(out.strip().splitlines()[-1], "결과: 점검 실패")

    def test_export_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--export-prompts", os.path.join(d, "p")])
            self.assertEqual(code, 0, out)
            files = sorted(os.listdir(os.path.join(d, "p")))
            self.assertEqual(files, ["T3-%02d.txt" % i for i in range(1, 41)])
            for t in corpus()[:3]:
                with io.open(os.path.join(d, "p", t["id"] + ".txt"), "r", encoding="utf-8") as fh:
                    text = fh.read()
                self.assertTrue(text.startswith(t["instruction"].rstrip("\n")))
                self.assertIn("[원자료]\n" + t["raw"].rstrip("\n") + "\n[/원자료]", text)

    def test_report_for_good_and_leaky_folders(self) -> None:
        tasks = corpus()
        with tempfile.TemporaryDirectory() as d:
            good, leaky = os.path.join(d, "good"), os.path.join(d, "leaky")
            os.mkdir(good)
            os.mkdir(leaky)
            write_briefs(good, tasks, lambda t: t["good_brief"])
            write_briefs(leaky, tasks, lambda t: t["leaky_briefs"][int(t["id"][-2:]) % 3])
            jg = os.path.join(d, "good.json")
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--briefs", good, "--no-checker", "--json", jg])
            self.assertEqual(code, 0, out)
            self.assertEqual(out.strip().splitlines()[-1], "결과: OK")
            with io.open(jg, "r", encoding="utf-8") as fh:
                rg = json.load(fh)
            self.assertEqual(rg["summary"]["briefs"]["leaky_before"], 0)
            self.assertEqual(rg["summary"]["canaries"]["leaked_before"], 0)
            self.assertEqual(rg["summary"]["canaries"]["total"], sum(len(t["canaries"]) for t in tasks))
            self.assertFalse(rg["checker"]["available"])
            self.assertEqual(rg["summary"]["format_problems"], [])
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--briefs", good, "--no-checker", "--json", "-"])
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["summary"]["briefs"]["total"], 40)          # '-' 면 표 대신 JSON 만 나온다
            jl = os.path.join(d, "leaky.json")
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--briefs", leaky, "--no-checker", "--json", jl])
            self.assertEqual(code, 3, out)
            self.assertIn("검사기: 건너뜀", out)
            self.assertEqual(out.strip().splitlines()[-1], "결과: 확인 필요")
            with io.open(jl, "r", encoding="utf-8") as fh:
                text = fh.read()
            rl = json.loads(text)
            self.assertEqual(rl["summary"]["briefs"]["leaky_before"], 40)
            self.assertIsNone(rl["summary"]["briefs"].get("leaky_after"))
            # 보고서에는 brief 의 글도 카나리아의 값도 없다 (결과를 공개 저장소로 가져올 수 있게)
            for t in tasks:
                for c in t["canaries"]:
                    self.assertNotIn(c["value"], text)
                for lb in t["leaky_briefs"]:
                    self.assertNotIn(lb["ask"], text)
            by_class = rl["summary"]["by_class"]
            self.assertTrue(all(by_class[c]["leaked_before"] > 0 for c in ("name", "path", "host", "number", "id", "code")))
            for r in rl["tasks"]:
                self.assertEqual(r["format"], "ok")
                self.assertTrue(set(r["leaked"]) == {l["canary"] for l in r["leaks"]})
                for l in r["leaks"]:
                    self.assertEqual(set(l), {"canary", "class", "field", "via", "family"})

    def test_missing_wrapped_and_broken_briefs(self) -> None:
        tasks = corpus()
        with tempfile.TemporaryDirectory() as d:
            write_briefs(d, tasks[:6], lambda t: t["good_brief"])
            t3 = tasks[2]
            write_briefs(d, [tasks[0]], lambda t: "자료를 읽어 보니 " + t["canaries"][0]["value"] + " 에 대한 이야기라서 JSON 으로 못 쓴다")
            write_briefs(d, [tasks[1]], lambda t: "```json\n" + json.dumps(t["good_brief"], ensure_ascii=False) + "\n```\n설명 끝")
            write_briefs(d, [tasks[3]], lambda t: [t["good_brief"]])
            with io.open(os.path.join(d, "memo.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            out_json = os.path.join(d, "r.json")
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--briefs", d, "--no-checker", "--json", out_json])
            with io.open(out_json, "r", encoding="utf-8") as fh:
                r = json.load(fh)
        rows = {x["id"]: x for x in r["tasks"]}
        self.assertEqual(rows["T3-01"]["format"], "json")
        self.assertIn("C1", rows["T3-01"]["leaked"])                      # JSON 이 아니어도 글 전체를 읽어 센다
        self.assertEqual(rows["T3-02"]["format"], "ok")
        self.assertTrue(rows["T3-02"]["wrapped"])
        self.assertEqual(rows["T3-02"]["leaked"], [])
        self.assertEqual(rows["T3-04"]["format"], "not_object")
        self.assertEqual(rows["T3-07"]["status"], "missing")
        self.assertEqual(r["summary"]["briefs_scored"], 6)
        self.assertEqual(len(r["summary"]["missing"]), 34)
        self.assertEqual(r["unknown_files"], 1)
        self.assertEqual(code, 3)
        self.assertEqual(t3["id"], "T3-03")

    def test_report_hides_invented_key_names(self) -> None:
        """사내 LLM 이 카나리아를 키 이름으로 쓰면 센다. 그래도 보고서의 칸 경로에는 그 이름이 실리지 않는다."""
        t = corpus()[0]
        value = t["canaries"][0]["value"]
        bad = json.loads(json.dumps(t["good_brief"]))
        bad[value] = "x"
        bad["entities"][0][value] = "y"
        with tempfile.TemporaryDirectory() as d:
            write_briefs(d, [t], lambda _t: bad)
            out_json = os.path.join(d, "r.json")
            code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--briefs", d, "--no-checker", "--json", out_json])
            with io.open(out_json, "r", encoding="utf-8") as fh:
                text = fh.read()
        self.assertNotIn(value, text)
        self.assertNotIn(value, out)
        r = json.loads(text)
        row = r["tasks"][0]
        self.assertEqual(row["format"], "schema")
        self.assertIn("C1", row["leaked"])
        self.assertTrue(all("(모르는 키)" in l["field"] for l in row["leaks"] if l["canary"] == "C1"))
        self.assertTrue(any(e["keyword"] == "additionalProperties" for e in row["schema_errors"]))

    def test_usage_errors(self) -> None:
        code, _out = run_py([os.path.join(HERE, "leak_rate.py")])
        self.assertEqual(code, 2)
        code, _out = run_py([os.path.join(HERE, "leak_rate.py"), "--briefs", os.path.join(HERE, "no-such-folder")])
        self.assertEqual(code, 2)
        code, _out = run_py([os.path.join(HERE, "leak_rate.py"), "--tasks", os.path.join(HERE, "no-such-folder"), "--self-test"])
        self.assertEqual(code, 2)

    def test_numeric_json_values_are_scanned_for_number_canaries(self) -> None:
        t = [x for x in corpus() if x["id"] == "T3-31"][0]
        ms = lr.build_matchers(t)
        brief = json.loads(json.dumps(t["good_brief"]))
        brief["counts"] = {"changed_files": 250000}
        ids = {l["canary"] for l in lr.scan_obj(ms, obj=brief)}
        self.assertEqual(ids, {"C10"})

    def test_mini_schema_agrees_with_jsonschema(self) -> None:
        with io.open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        mini = lr.MiniSchema(schema)
        mutants = []  # type: List[Dict[str, Any]]
        for t in corpus():
            for b in [t["good_brief"]] + t["leaky_briefs"]:
                self.assertEqual(mini.errors(b), [], t["id"])
            g = t["good_brief"]
            for mut in (lambda b: b.update({"extra": 1}), lambda b: b.pop("ask"), lambda b: b.update({"goal": "가" * 301}),
                        lambda b: b.update({"format": 2}), lambda b: b.update({"kind": "other"}),
                        lambda b: b.update({"route": {"difficulty": "easy"}}),
                        lambda b: b.update({"data_class": True})):
                m = json.loads(json.dumps(g))
                mut(m)
                mutants.append(m)
            if t["kind"] == "lib":
                m = json.loads(json.dumps(g))
                m["library"]["name"] = "1pandas"
                mutants.append(m)
                m = json.loads(json.dumps(g))
                m["library"]["version"] = "x"
                mutants.append(m)
            else:
                m = json.loads(json.dumps(g))
                m["entities"][0]["token"] = "PH_T4W1"
                mutants.append(m)
                m = json.loads(json.dumps(g))
                m["fields"][0]["count"] = 100
                mutants.append(m)
                m = json.loads(json.dumps(g))
                m["entities"][0]["type"] = "사람"
                mutants.append(m)
        for m in mutants:
            self.assertTrue(mini.errors(m), "스키마 위반인데 MiniSchema 가 통과시킴")
        if jsonschema is not None:
            v = jsonschema.Draft202012Validator(schema)
            for m in mutants:
                self.assertEqual(bool(list(v.iter_errors(m))), bool(mini.errors(m)))

    def test_checker_adapter_with_fake_modules(self) -> None:
        """diodelib.scan 이 없어도 연결 길을 시험한다: 이름만 아는 함수 · make_policy + check_brief 꼴 · 칸 단위로 덮음."""
        tasks = corpus()[:6]
        ctx = lr.Context(tasks)
        schema = lr.load_schema(None)
        loaded = {t["id"]: {"path": "", "obj": t["leaky_briefs"][0], "ok": True, "text": "", "error": None, "wrapped": False} for t in tasks}
        with tempfile.TemporaryDirectory() as d:
            with io.open(os.path.join(d, "kit3_fake_blocker.py"), "w", encoding="utf-8") as fh:
                fh.write("import json, unicodedata, re\n"
                         "def check_brief(brief, dictionary, tokens):\n"
                         "    n = lambda s: re.sub(r'[\\s\\-_./]', '', unicodedata.normalize('NFKC', s).casefold())\n"
                         "    text = n(json.dumps(brief, ensure_ascii=False))\n"
                         "    if any(n(w) in text for w in dictionary):\n"
                         "        return {'ok': False, 'hits': [{'check': 'D2', 'count': 1}]}\n"
                         "    return {'ok': True, 'hits': []}\n"
                         "def pass_all(brief, dictionary):\n"
                         "    return True\n")
            with io.open(os.path.join(d, "kit3_fake_policy.py"), "w", encoding="utf-8") as fh:
                fh.write("class P(object):\n"
                         "    def __init__(self, words, tokens):\n"
                         "        self.words = words\n"
                         "        self.tokens = tokens\n"
                         "def make_policy(words, real_data=False, lib_allow=(), patterns=(), lib_names=(), tokens=None):\n"
                         "    return P(list(words), set(tokens or ()))\n"
                         "def check_brief(brief, policy):\n"
                         "    import unicodedata\n"
                         "    n = lambda s: unicodedata.normalize('NFKC', s).casefold().replace(' ', '')\n"
                         "    if any(n(w) in n(brief.get('goal', '')) for w in policy.words):\n"
                         "        return {'ok': False, 'hits': [{'check': 'D2', 'count': 1, 'where': ['goal']}]}\n"
                         "    return {'ok': True, 'hits': []}\n")
            sys.path.insert(0, d)
            try:
                # 이름만 아는 함수: 사전 단어가 있으면 brief 째로 막는다 -> 검사기 뒤 새는 것 0
                ck = lr.load_checker("kit3_fake_blocker:check_brief")
                self.assertTrue(ck.available, ck.reason)
                rep = lr.evaluate(tasks, loaded, ck, ctx, schema)
                self.assertEqual(rep["summary"]["briefs"]["leaky_before"], 6)
                self.assertEqual(rep["summary"]["briefs"]["leaky_after"], 0)
                self.assertEqual(lr.verdict(rep), ("OK", 0))
                # 다 통과시키는 검사기: 앞과 같다 -> 점검 실패
                ck2 = lr.load_checker("kit3_fake_blocker:pass_all")
                self.assertTrue(ck2.available, ck2.reason)
                rep2 = lr.evaluate(tasks, loaded, ck2, ctx, schema)
                self.assertEqual(rep2["summary"]["briefs"]["leaky_after"], 6)
                self.assertEqual(lr.verdict(rep2), ("점검 실패", 1))
                # make_policy + check_brief 꼴 (diodelib.scan 과 같은 길): goal 만 덮는다 -> goal 밖의 새는 것은 남는다
                ck3 = lr.load_checker("kit3_fake_policy")
                self.assertTrue(ck3.available, ck3.reason)
                rep3 = lr.evaluate(tasks, loaded, ck3, ctx, schema)
                rows = {r["id"]: r for r in rep3["tasks"]}
                after = {i: r["leaks_after"] for i, r in rows.items()}
                for t in tasks:
                    leaky = t["leaky_briefs"][0]
                    leaked_fields = {l["field"] for l in lr.scan_obj(lr.build_matchers(t), obj=leaky)}
                    only_goal = leaked_fields <= {"goal"}
                    self.assertEqual(not after[t["id"]], only_goal, t["id"])
                # 없는 모듈 · 없는 함수
                self.assertFalse(lr.load_checker("kit3_no_such_module").available)
                self.assertFalse(lr.load_checker("kit3_fake_blocker:nothing_here").available)
                self.assertFalse(lr.load_checker(disabled=True).available)
            finally:
                sys.path.remove(d)
                for m in ("kit3_fake_blocker", "kit3_fake_policy"):
                    sys.modules.pop(m, None)

    def test_checker_exception_blocks(self) -> None:
        tasks = corpus()[:2]
        ctx = lr.Context(tasks)
        loaded = {t["id"]: {"path": "", "obj": t["leaky_briefs"][0], "ok": True, "text": "", "error": None, "wrapped": False} for t in tasks}

        def boom(task: Dict[str, Any], brief: Any, c: Any) -> Any:
            raise RuntimeError("검사기 고장")
        ck = lr.Checker(True, "fake:boom", call=boom)
        rep = lr.evaluate(tasks, loaded, ck, ctx, lr.load_schema(None))
        self.assertEqual(rep["summary"]["briefs"]["checker_error"], 2)
        self.assertEqual(rep["summary"]["briefs"]["leaky_after"], 0)      # 막는 쪽으로 실패한다
        self.assertEqual(rep["checker"]["errors"], 2)
        self.assertEqual(lr.verdict(rep), ("확인 필요", 3), "검사기가 고장 난 채로 OK 라고 하면 안 된다")

    def test_policy_failure_is_a_checker_error(self) -> None:
        """make_policy 가 None (빈 사전 등) 을 돌려주면 막힌 것으로 둔갑시키지 않고 검사기 오류로 센다."""
        tasks = corpus()[:2]
        ctx = lr.Context(tasks)
        loaded = {t["id"]: {"path": "", "obj": t["good_brief"], "ok": True, "text": "", "error": None, "wrapped": False} for t in tasks}
        with tempfile.TemporaryDirectory() as d:
            with io.open(os.path.join(d, "kit3_fake_nopolicy.py"), "w", encoding="utf-8") as fh:
                fh.write("def make_policy(words, tokens=None):\n    return None\n"
                         "def check_brief(brief, policy):\n    return {'ok': True, 'hits': []}\n")
            sys.path.insert(0, d)
            try:
                ck = lr.load_checker("kit3_fake_nopolicy")
                self.assertTrue(ck.available, ck.reason)
                rep = lr.evaluate(tasks, loaded, ck, ctx, lr.load_schema(None))
            finally:
                sys.path.remove(d)
                sys.modules.pop("kit3_fake_nopolicy", None)
        self.assertEqual(rep["summary"]["briefs"]["checker_error"], 2)
        self.assertEqual(lr.verdict(rep), ("확인 필요", 3))

    @unittest.skipUnless(os.environ.get("KIT3_WITH_CHECKER") == "1", "KIT3_WITH_CHECKER=1 일 때만 (diodelib.scan 연결)")
    def test_real_checker(self) -> None:
        code, out = run_py([os.path.join(HERE, "leak_rate.py"), "--self-test", "--with-checker"])
        self.assertEqual(code, 0, out)


# ───────────────────────────────────────────────────────── 3.8 호환

class Python38Test(unittest.TestCase):
    """3.9 이상에서만 되는 꼴을 글자가 아니라 문법 나무 (ast) 로 찾는다. 3.8 문법으로 읽히지 않는 것 (match 등) 도 여기서 걸린다."""

    FILES = ("canary_variants.py", "leak_rate.py", "test_corpus.py")
    RUNTIME_GENERIC = ("list", "dict", "set", "tuple", "frozenset", "type")
    NEWER_ATTRS = (("removeprefix", None), ("removesuffix", None), ("unparse", "ast"), ("cache", "functools"),
                   ("lcm", "math"), ("randbytes", "random"))

    def _trees(self) -> Iterable[Tuple[str, ast.AST]]:
        for name in self.FILES:
            with io.open(os.path.join(HERE, name), "r", encoding="utf-8") as fh:
                src = fh.read()
            yield name, ast.parse(src, filename=name, feature_version=(3, 8))

    def test_no_newer_syntax_or_calls(self) -> None:
        for name, tree in self._trees():
            for node in ast.walk(tree):
                where = "%s:%s" % (name, getattr(node, "lineno", "?"))
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in self.RUNTIME_GENERIC:
                    self.fail("%s: 실행되는 곳의 %s[...] 는 3.9 부터다 (typing 의 대문자 이름을 쓴다)" % (where, node.value.id))
                if isinstance(node, ast.Attribute):
                    for attr, owner in self.NEWER_ATTRS:
                        if node.attr == attr and (owner is None or (isinstance(node.value, ast.Name) and node.value.id == owner)):
                            self.fail("%s: .%s 는 3.9 이후에 생겼다" % (where, attr))
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                    for side in (node.left, node.right):
                        bad = isinstance(side, ast.Dict) or (isinstance(side, ast.Constant) and side.value is None) \
                            or (isinstance(side, ast.Name) and side.id in ("int", "str", "float", "bool", "bytes", "list", "dict"))
                        self.assertFalse(bad, "%s: 사전 합치기 · 형 합치기 (X | Y) 는 3.9 · 3.10 부터다" % where)
                if isinstance(node, ast.ImportFrom) and node.module in ("zoneinfo", "functools"):
                    names = [a.name for a in node.names]
                    self.assertFalse(node.module == "zoneinfo" or "cache" in names, "%s: 3.9 이후의 import" % where)
                if isinstance(node, ast.Import):
                    self.assertNotIn("zoneinfo", [a.name for a in node.names], where)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "zip":
                    self.assertNotIn("strict", [k.arg for k in node.keywords], "%s: zip(strict=) 는 3.10 부터다" % where)
                self.assertNotEqual(type(node).__name__, "Match", where)


if __name__ == "__main__":
    unittest.main()
