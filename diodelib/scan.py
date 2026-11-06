# -*- coding: utf-8 -*-
"""나가는 검사 D1–D6 · D5a (SP-05) — 결정적 검사기 (표준 라이브러리 · Python 3.8).

쓰는 곳
- check_brief(brief, policy)  보고 (propose) · seal 의 D1 → D6 → D2 → D3 → D4 → D5 (+D5a)
- check_text(text, policy)    훅의 프롬프트 검사 (D2 · D3) · scan 명령 (D2 · D3 · D5)
- check_repro(code, policy)   lib 의 합성 재현 코드 (D5a)
- 토큰 · 사전 함수 (find_tokens · find_broken_tokens · dict_hits) 는 들어오는 검사 (U1 · U2) 도 쓴다.

지키는 것
- 결과에는 검사 번호 · 개수 · 자리 (칸 이름 · 목록 번호 · 줄 번호) 만 쓴다. 단어 · 값 · 모르는 키 이름을
  쓰지 않는다 (AL-11).
- 검사 도중의 예외 · 사전이 빔 · 정규식이 깨짐 → {"ok": false, "hits": [{"check": "E", "code": "E-20"}]}
  (막는 쪽 실패 · AL-03). 시간 제한은 부르는 쪽이 건다 (훅 timeout · 허브의 하위 프로세스).
- 검사는 손질한 글 (textnorm.prepare) 을 본다 — 펼친 글 (render) 에 실제로 들어가는 글이다.
"""

import ast
import builtins
import io
import ipaddress
import json
import keyword
import math
import re
import tokenize
import unicodedata
from collections import OrderedDict

from . import briefschema
from .render import SAMPLE_HEAD, SAMPLE_OTHER, render, sample_lines
from .textnorm import (allowed_code_char, allowed_text_char, dict_key, prepare, skeleton)

MAX_RENDERED_BYTES = 8192       # 펼친 글 상한 [제안] (SP-02)
MAX_INPUT_BYTES = 65536         # 들어온 brief JSON 바이트 상한 [제안]
MAX_REPRO_LINES = 40            # D5a
MAX_REPRO_NUMBERS = 20          # D5a — 작은 정수를 늘어놓아 수치를 옮기는 길을 좁힌다 [제안]
MIN_WORD_KEY = 2                # D2 — N(w) 가 이보다 짧은 사전 단어는 쓰지 않는다

def e20():
    """막는 쪽 실패의 결과 (SP-05 · AL-03)."""
    return {"ok": False, "hits": [{"check": "E", "code": "E-20"}]}

# ---------------------------------------------------------------- 토큰 (SP-04 · D6)

TOKEN_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
# 정확한 꼴. 앞뒤 경계는 ASCII 로만 본다 — 한국어 조사 ("PH_K7Q2를") 가 붙어도 토큰으로 읽는다.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])PH_[2-9A-HJKMNP-TV-Z]{4}(?![A-Za-z0-9])")
# 깨진 꼴의 후보. 정확한 꼴을 지운 뒤에 찾는다.
_BROKEN_RE = re.compile(r"(?<![A-Za-z0-9_])(ph)([ _\-]?)([0-9a-z]{2,8})(?![A-Za-z0-9])", re.I)


def find_tokens(text):
    """정확한 꼴의 토큰 목록 (나온 차례 · 겹침 포함)."""
    return TOKEN_RE.findall(text)


def remove_tokens(text, repl=" "):
    return TOKEN_RE.sub(repl, text)


def find_broken_tokens(text):
    """깨진 꼴의 개수. 정확한 꼴이 아닌데 토큰처럼 보이는 것.

    후보 `ph[ _-]?[0-9a-z]{2,8}` (대소문자 무시) 가운데 구분자가 있거나 · 숫자가 있거나 ·
    머리가 대문자 "PH" 인 것만 센다 ("phone" · "photo" 같은 낱말은 세지 않는다).
    """
    n = 0
    for m in _BROKEN_RE.finditer(remove_tokens(text)):
        head, sep, body = m.group(1), m.group(2), m.group(3)
        if sep or any(c.isdigit() for c in body) or head == "PH":
            n += 1
    return n


# ---------------------------------------------------------------- 사전 (D2 · U2)

class _Words(object):
    """사전 단어의 정규화 열쇠. 단어 자체는 밖으로 내지 않는다."""

    def __init__(self, words):
        keys = []
        seen = set()
        short = 0
        for w in words:
            if not isinstance(w, str):
                raise ValueError("사전 항목이 글이 아님")
            k = dict_key(w)
            if len(k) < MIN_WORD_KEY:
                short += 1
                continue
            if k not in seen:
                seen.add(k)
                keys.append(k)
        self.keys = keys
        self.short = short


def dict_hits(text, words_or_keys):
    """글 안에 든 사전 단어의 (서로 다른) 개수. 정확한 꼴의 토큰을 지운 글도 함께 본다."""
    keys = words_or_keys.keys if isinstance(words_or_keys, _Words) else _Words(words_or_keys).keys
    return len(_matched_keys(text, keys))


def policy_dict_hits(text, policy):
    """정책의 사전 (별칭 포함) 단어가 글 안에 몇 개 있나 — 서로 다른 단어 수 (단어는 내지 않는다)."""
    return len(_matched_keys(text, policy.word_keys))


SKELETON_MIN_KEY = 5            # D2 - 닮은 ASCII 글자를 접은 비교는 이 길이 이상의 단어에만 (짧은 단어는 오탐이 는다)
_SKELETON_CACHE = {}


def _skeleton_of(key):
    sk = _SKELETON_CACHE.get(key)
    if sk is None:
        if len(_SKELETON_CACHE) > 20000:
            _SKELETON_CACHE.clear()
        sk = _SKELETON_CACHE[key] = skeleton(key)
    return sk


def _matched_keys(text, keys):
    a = dict_key(text)
    b = dict_key(remove_tokens(text, ""))
    found = set(k for k in keys if k in a or k in b)
    sa, sb = skeleton(a), skeleton(b)                 # KlTWORD (l 이 I 자리) · KITVVORD (VV 가 W 자리) 같은 ASCII 닮은 꼴
    for k in keys:
        if k not in found and len(k) >= SKELETON_MIN_KEY:
            sk = _skeleton_of(k)
            if sk in sa or sk in sb:
                found.add(k)
    return found


SHORT_FIELD = 3                 # D2 — 이보다 짧지 않은 칸은 "짧은 칸 모음" 에 넣지 않는다


def _split_keys(texts, keys, already):
    """칸을 나눠 숨긴 사전 단어 (SP-05 D2 의 '*').

    1) 어느 칸의 끝 + 다른 칸의 머리로 단어가 되는가 (두 조각 모두 두 글자 이상 · 칸의 차례는 따지지 않는다)
    2) 짧은 칸 (N 이 세 글자 이하) 만 차례대로 이어 붙이면 단어가 되는가 — 한 글자씩 흩뿌린 단어
    """
    fks = [dict_key(remove_tokens(t, "")) for t in texts]
    rest = [k for k in keys if k not in already]
    if not rest:
        return set()
    maxlen = max(len(k) for k in rest)
    suffixes = set()
    prefixes = set()
    for fk in fks:
        for i in range(2, min(len(fk), maxlen) + 1):
            suffixes.add(fk[-i:])
            prefixes.add(fk[:i])
    out = set()
    for k in rest:
        for i in range(2, len(k) - 1):
            if k[:i] in suffixes and k[i:] in prefixes:
                out.add(k)
                break
    skeleton = "".join(fk for fk in fks if 0 < len(fk) <= SHORT_FIELD)
    for k in rest:
        if k in skeleton:
            out.add(k)
    return out


# ---------------------------------------------------------------- 꼴 (D3)

# 마지막 칸이 이 이름이면 점 있는 이름을 호스트로 본다 (SP-05 D3 · 코드의 상수).
KNOWN_TLDS = (
    "com", "net", "org", "io", "kr", "jp", "cn", "co", "us", "uk", "de",
    "dev", "app", "cloud", "ai", "edu", "gov", "biz", "info",
    "local", "lan", "corp", "internal", "intra", "intranet", "home", "localdomain",
    # 안쪽 이름으로 흔한 것 (레드팀 C-01)
    "lab", "test", "svc", "prod", "stage", "staging", "qa", "uat", "cluster", "mgmt", "fab", "domain", "ldap", "dmz",
)
# 허용 라이브러리 이름으로 시작해도 호스트로 보는 이름 (안쪽 이름).
INTERNAL_TLDS = frozenset(["local", "lan", "corp", "internal", "intra", "intranet", "home", "localdomain",
                           "lab", "test", "svc", "prod", "stage", "staging", "qa", "uat", "cluster", "mgmt", "fab",
                           "domain", "ldap", "dmz"])

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
_HOST_RE = re.compile(
    r"(?<![A-Za-z0-9\-.])((?:%s\.)+)(%s)(?![A-Za-z0-9\-]|\.[A-Za-z0-9])" % (_LABEL, "|".join(KNOWN_TLDS)),
    re.I)

_D3_PATTERNS = (
    re.compile(r"\\"),                                         # 역슬래시 — Windows 경로 · UNC
    re.compile(r"(?<![A-Za-z])[A-Za-z]:/"),                     # C:/
    re.compile(r"(?i)(?<![\w.])/(?:home|users|root|tmp|var|etc|opt|mnt|srv|data)/"),
    re.compile(r"(?<![\w/.~])/(?:[\w.\-]+/)+"),                 # /a/b/ 꼴의 절대 경로
    re.compile(r"~[/\\]"),
    re.compile(r"(?<![:\w/])//[^\s/]+/"),                     # //서버/공유 (빗금으로 쓴 UNC · //host/ 꼴)
    re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%"),                   # %USERPROFILE%
    re.compile(r"\$(?:\{|[A-Za-z_])"),                         # $HOME · ${X}
    re.compile(r"://"),                                         # URL
    re.compile(r"(?i)(?<![a-z])(?:www\.|mailto:|file:)"),
    re.compile(r"(?<![0-9.])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9])"),          # IPv4 (127.0.0.1 포함)
    re.compile(r"(?i)(?<![0-9a-f:\-])[0-9a-f]{2}(?:[:\-][0-9a-f]{2}){5}(?![0-9a-f:\-])"),  # MAC
    re.compile(r"(?<![\w.+%\-])[\w.+%\-]+@[\w\-]+(?:\.[\w\-]+)*"),   # 메일 · user@host (머리에서만 시작 - 긴 글에서 제곱으로 느려지지 않게)
    re.compile(r"(?i)(?<![A-Za-z0-9])localhost(?![A-Za-z0-9])"),
)
_V6_CAND = re.compile(r"(?i)(?<![0-9a-z:.])[0-9a-f:.]*:[0-9a-f:.]*:[0-9a-f:.]*(?![0-9a-z:])")


def _count_ipv6(text):
    n = 0
    for m in _V6_CAND.finditer(text):
        cand = m.group(0).strip(".")
        if cand.count(":") < 2:
            continue
        try:
            ipaddress.IPv6Address(cand)
        except ValueError:
            continue
        n += 1
    return n


def _count_hosts(text, lib_allow):
    n = 0
    for m in _HOST_RE.finditer(text):
        first = m.group(1).split(".")[0].lower()
        tld = m.group(2).lower()
        if first in lib_allow and tld not in INTERNAL_TLDS:
            continue            # pandas.io 같은 공개 API 이름
        n += 1
    return n


# NFKC 가 못 접는 경로 글자의 닮은 꼴 (나눗셈 빗금 · 표의 마침표 · 집합 빼기 …)
_PATH_FOLD = {0x2215: "/", 0x2044: "/", 0x29F8: "/", 0x3002: ".", 0x2024: ".", 0xFF61: ".", 0x2216: "\\", 0x29F5: "\\"}


# 상대 경로 (../x · ./x) - brief 에서만 센다. 사람이 Claude 에게 치는 말(훅)에서는 개발에 흔한 말이라 막지 않는다
# (그 길은 @파일 · 도구 검사가 본다).
_RELATIVE_PATH = re.compile(r"(?<![\w.])\.\.?/[\w.\-]")


def pattern_hits(text, policy, relative=False):
    """D3: 경로 · 주소 · 메일 · 호스트 · 사용자 정규식에 걸린 개수. relative=True 면 ../x · ./x 도 센다 (brief)."""
    text = unicodedata.normalize("NFKC", text).translate(_PATH_FOLD)
    n = sum(1 for _ in _RELATIVE_PATH.finditer(text)) if relative else 0
    for rx in _D3_PATTERNS:
        n += sum(1 for _ in rx.finditer(text))
    n += _count_ipv6(text)
    n += _count_hosts(text, policy.lib_allow_lower)
    for rx in policy.compiled_patterns:
        n += sum(1 for _ in rx.finditer(text))
    return n


# ---------------------------------------------------------------- 숫자 (D4)

def digit_runs(text):
    """D4: 토큰을 지운 뒤 유니코드 숫자 (Nd · No · Nl) 덩어리의 개수."""
    s = unicodedata.normalize("NFKC", remove_tokens(text))
    n = 0
    in_run = False
    for ch in s:
        if unicodedata.category(ch) in ("Nd", "No", "Nl"):
            if not in_run:
                n += 1
                in_run = True
        else:
            in_run = False
    return n


# ---------------------------------------------------------------- 덩어리 · 코드 꼴 (D5)

_CODE_PATTERNS = (
    re.compile(r"```|~~~|`"),                                   # 코드 울타리 · 백틱
    re.compile(r"\bdef\s+[A-Za-z_]\w*\s*\("),
    re.compile(r"\bclass\s+[A-Za-z_]\w*\s*[(:]"),
    re.compile(r"\bfrom\s+[A-Za-z_][\w.]*\s+import\b"),
    re.compile(r"^\s*import\s+[A-Za-z_][\w.]*(?:\s+as\s+\w+)?\s*$"),
    re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b.*\b(?:FROM|INTO|SET|WHERE)\b"),
    re.compile(r"#include\b|#!/"),
    re.compile(r"[A-Za-z_]\w*\s*\([^()]*\)\s*[{;]"),           # f(x) { · f(x);
    re.compile(r"[{}]"),
    re.compile(r"==|!=|\+=|-=|&&|\|\||::|=>"),
    re.compile(r"<\s*/?\s*[A-Za-z][A-Za-z0-9\-]*(?:\s[^<>]*)?/?>"),   # HTML 꼴
    re.compile(r"\$\(|\$\{"),
)
_SNAKE_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]*[A-Za-z0-9](?![A-Za-z0-9_])")
_CAMEL_RE = re.compile(r"(?<![A-Za-z0-9_])[a-z]{2,}[A-Z][a-z][A-Za-z0-9]*(?![A-Za-z0-9_])")
_B64_RE = re.compile(r"[A-Za-z0-9+/_\-]{24,}={0,2}")
_HEX_RE = re.compile(r"[0-9A-Fa-f]{16,}")
_CHUNK_RE = re.compile(r"[\x21-\x7e]{20,}")     # ASCII 덩어리만 (한글 문장은 엔트로피가 높다)
ENTROPY_BITS = 4.0              # bit/글자 [제안]


def _entropy(s):
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = float(len(s))
    return -sum((c / n) * math.log(c / n, 2) for c in counts.values())


def _public_name(s, policy):
    """공개 이름 (허용 라이브러리 · 그 공개 이름 · 내장 이름) 으로만 된 점 이름인가."""
    parts = s.strip(".,()[]\"'").split(".")
    if not parts or not all(parts):
        return False
    return all(p in policy.public_names or p.lower() in policy.lib_allow_lower for p in parts)


def blob_hits(text, policy):
    """D5: 코드 꼴 · 식별자 꼴 · base64 · hex · 엔트로피 덩어리의 개수 (토큰은 지우고 본다)."""
    s = remove_tokens(text)
    n = 0
    for rx in _CODE_PATTERNS:
        n += sum(1 for _ in rx.finditer(s))
    for rx in (_SNAKE_RE, _CAMEL_RE, _B64_RE):
        for m in rx.finditer(s):
            if not _public_name(m.group(0), policy):
                n += 1
    n += sum(1 for _ in _HEX_RE.finditer(s))
    for m in _CHUNK_RE.finditer(s):
        chunk = m.group(0)
        if _public_name(chunk, policy):
            continue
        if _entropy(chunk) >= ENTROPY_BITS:
            n += 1
    return n


# ---------------------------------------------------------------- 합성 재현 코드 (D5a)

# 자리 이름 (SP-05 D5a). 따옴표로 감싸면 자리 글이 된다.
PLACEHOLDER_NAMES = frozenset(
    ["df", "a", "b", "c", "x", "y", "z", "i", "j", "k", "n", "s", "t", "_",
     "item", "value", "key", "data", "result", "row", "arr", "obj", "fn", "cls"]
    + ["col_%d" % d for d in range(1, 10)])
PLACEHOLDER_STRINGS = frozenset(list(PLACEHOLDER_NAMES - {"_"}) + [""])
# 흔한 import 별칭 (import X as <이것>).
IMPORT_ALIASES = frozenset(["pd", "np", "plt", "sns", "tf", "nn", "F", "sp", "mpl", "pl", "xr", "dd"])
_SOFT_KEYWORDS = frozenset(["match", "case", "type", "_"])

_NUMBER_OK = re.compile(r"[0-9]{1,3}\Z")


def _builtin_names():
    names = set(dir(builtins))
    for t in (str, bytes, list, dict, set, frozenset, tuple, int, float, bool, object, BaseException):
        names.update(dir(t))
    return frozenset(names)


BUILTIN_NAMES = _builtin_names()
BUILTIN_EXCEPTIONS = frozenset(
    n for n in dir(builtins)
    if isinstance(getattr(builtins, n), type) and issubclass(getattr(builtins, n), BaseException))


# 글자 ↔ 숫자 · 바이트를 바꾸거나 코드를 만들어 돌리는 이름 - 재현 코드에서 값을 실어 나르는 길 (레드팀 D5a-01)
FORBIDDEN_CODE_NAMES = frozenset([
    "chr", "ord", "bytes", "bytearray", "memoryview", "decode", "encode", "fromhex", "hex", "bin", "oct", "from_bytes",
    "to_bytes", "eval", "exec", "compile", "getattr", "setattr", "delattr", "globals", "locals", "vars", "__import__",
    "open", "input", "breakpoint", "translate", "maketrans"])


_HUGE = 10 ** 9


def _const_value(node):
    """숫자 상수만으로 된 식의 값 (아니면 None). 지수는 큰 값으로 친다 - 셈하다 멈추지 않게."""
    if isinstance(node, ast.Constant):
        v = node.value
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _const_value(node.operand)
        return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
    if isinstance(node, ast.BinOp):
        left, right = _const_value(node.left), _const_value(node.right)
        if left is None or right is None:
            return None
        op = node.op
        try:
            if isinstance(op, ast.Add):
                return left + right
            if isinstance(op, ast.Sub):
                return left - right
            if isinstance(op, ast.Mult):
                return left * right
            if isinstance(op, ast.Div):
                return left / right
            if isinstance(op, ast.FloorDiv):
                return left // right
            if isinstance(op, ast.Mod):
                return left % right
            if isinstance(op, ast.Pow):
                return _HUGE if abs(right) > 16 or abs(left) > 1000 else left ** right
        except (ArithmeticError, ValueError, OverflowError):
            return None
        return _HUGE                                # 비트 셈 등 - 값을 따지지 않고 큰 수로 본다
    return None


def check_repro(code, policy):
    """D5a: 걸린 줄 번호 목록 (줄 번호만 · 글은 없음). 비면 통과."""
    bad = []
    code = code.replace("\r\n", "\n")
    lines = code.split("\n")
    if len(code.rstrip("\n").split("\n")) > MAX_REPRO_LINES:
        bad.append(MAX_REPRO_LINES + 1)
    for no, line in enumerate(lines, 1):
        if any(not allowed_code_char(ch) for ch in line):
            bad.append(no)

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError) as e:
        bad.append(getattr(e, "lineno", None) or 1)
        return sorted(set(bad))

    allow_top = policy.lib_allow_lower
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name.split(".")[0].lower() not in allow_top:
                    bad.append(node.lineno)
                if al.asname and al.asname not in IMPORT_ALIASES and al.asname not in PLACEHOLDER_NAMES:
                    bad.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or node.module.split(".")[0].lower() not in allow_top:
                bad.append(node.lineno)
            for al in node.names:
                if al.asname and al.asname not in IMPORT_ALIASES and al.asname not in PLACEHOLDER_NAMES:
                    bad.append(node.lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            v = _const_value(node)
            if v is not None and abs(v) >= 1000:
                bad.append(node.lineno)      # 350*10+7 처럼 숫자끼리 셈해 세 자리 제한을 넘는 수를 만드는 길 (1 / 2 같은 작은 셈은 쓴다)
    allowed = policy.code_names - FORBIDDEN_CODE_NAMES
    numbers = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            tt = tok.type
            line = tok.start[0]
            name = tokenize.tok_name.get(tt, "")
            if tt in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                      tokenize.ENDMARKER, tokenize.OP):
                continue
            if tt == tokenize.NAME:
                if tok.string not in allowed and not TOKEN_RE.fullmatch(tok.string):
                    bad.append(line)
            elif tt == tokenize.STRING:
                if not _string_ok(tok.string):
                    bad.append(line)
            elif tt == tokenize.NUMBER:
                numbers += 1
                if not _NUMBER_OK.match(tok.string) or numbers > MAX_REPRO_NUMBERS:
                    bad.append(line)
            elif tt == tokenize.COMMENT:
                bad.append(line)
            elif name.startswith("FSTRING") or name.startswith("TSTRING"):
                bad.append(line)          # f-글 (3.12+ 의 꼴) 은 받지 않는다
            else:
                bad.append(line)          # ERRORTOKEN · 그 밖의 모르는 꼴
    except (tokenize.TokenError, SyntaxError, IndentationError):
        bad.append(len(lines))
    return sorted(set(bad))


def _string_ok(src):
    m = re.match(r"([A-Za-z]*)", src)
    prefix = m.group(1).lower() if m else ""
    if prefix not in ("", "u"):
        return False                      # b"" · r"" · f"" 는 받지 않는다
    try:
        v = ast.literal_eval(src)
    except Exception:
        return False
    if not isinstance(v, str):
        return False
    return v in PLACEHOLDER_STRINGS or bool(TOKEN_RE.fullmatch(v))


def _error_type_ok(name, policy):
    """lib 의 error.type: 내장 예외 · 허용 라이브러리의 공개 이름만 (사내 예외 이름을 막는다)."""
    parts = name.split(".")
    if len(parts) == 1:
        return name in BUILTIN_EXCEPTIONS or name in policy.lib_names
    if parts[0].lower() not in policy.lib_allow_lower:
        return False
    return all(p in policy.lib_names for p in parts[1:])


# ---------------------------------------------------------------- 정책 · 결과

class Policy(object):
    """검사에 쓰는 입력 묶음. 설정 · 사전을 읽는 일은 부르는 쪽이 한다.

    words      사전 단어 (+ 별칭) — 비면 막음 (E-20)
    real_data  설정 policy.real_data (참일 때만 data_class=real 을 받는다)
    lib_allow  설정 policy.lib_allow (라이브러리 이름 · import 이름)
    patterns   설정 policy.patterns (D3 에 더할 정규식 글)
    lib_names  허용 라이브러리의 공개 이름 목록 (diode.py lib names 가 만든 것)
    tokens     이 job 의 가명 표에 있는 토큰 (None 이면 빈 표 — 모든 토큰이 모르는 토큰)
    """

    def __init__(self, words, real_data=False, lib_allow=(), patterns=(), lib_names=(), tokens=None):
        self._words = _Words(list(words))
        if not self._words.keys:
            raise ValueError("사전이 빔")
        self.real_data = real_data is True
        self.lib_allow_lower = frozenset(str(x).lower() for x in lib_allow)
        self.compiled_patterns = tuple(re.compile(p) for p in patterns)
        self.lib_names = frozenset(lib_names)
        self.tokens = frozenset(tokens or ())
        self.public_names = self.lib_names | BUILTIN_NAMES
        self.code_names = (frozenset(keyword.kwlist) | _SOFT_KEYWORDS | BUILTIN_NAMES | PLACEHOLDER_NAMES
                           | IMPORT_ALIASES | self.lib_names | frozenset(str(x) for x in lib_allow)
                           | frozenset(str(x).lower() for x in lib_allow))      # import 검사는 대소문자를 무시한다

    def derive(self, tokens=None, extra_words=()):
        """같은 정책에 가명 표 (tokens) 를 바꾸고 · 사전 단어를 더한 새 Policy (원래 것은 그대로).

        seal · unseal 이 쓴다 — 그 job 의 진짜 이름도 사전처럼 본다 (D2 · U2).
        """
        new = object.__new__(Policy)
        new.__dict__.update(self.__dict__)
        if extra_words:
            extra = _Words([w for w in extra_words if isinstance(w, str)])
            keys = list(self._words.keys)
            seen = set(keys)
            for k in extra.keys:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
            w = object.__new__(_Words)
            w.keys = keys
            w.short = self._words.short + extra.short
            new._words = w
        if tokens is not None:
            new.tokens = frozenset(tokens)
        return new

    @property
    def word_keys(self):
        return self._words.keys

    @property
    def short_words(self):
        """N(w) 가 두 글자보다 짧아 쓰지 않은 사전 항목의 수 (/diode:dict 가 알린다)."""
        return self._words.short


class _Hits(object):
    def __init__(self):
        self._d = OrderedDict()

    def add(self, check, where, n=1):
        if n <= 0:
            return
        slot = self._d.setdefault(check, [0, []])
        slot[0] += n
        if where not in slot[1]:
            slot[1].append(where)

    def __bool__(self):
        return bool(self._d)

    def result(self):
        hits = [{"check": c, "count": v[0], "where": v[1]} for c, v in self._d.items()]
        return {"ok": not hits, "hits": hits}


def make_policy(**kw):
    """Policy 를 만들되 실패하면 None (부르는 쪽은 E-20 으로 막는다)."""
    try:
        return Policy(**kw)
    except Exception:
        return None


# ---------------------------------------------------------------- brief

_FREE_LIST = ("context", "constraints", "summary", "questions")
_DIODE_MARK = re.compile(r"\[\s*/?\s*diode", re.I)


def free_text_fields(brief):
    """자유 글 칸 [(자리, 원래 글)] — SP-02 의 목록. 차례는 펼친 글의 차례."""
    out = []
    kind = brief.get("kind")

    def one(key):
        v = brief.get(key)
        if isinstance(v, str):
            out.append((key, v))

    def many(key):
        v = brief.get(key)
        if isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, str):
                    out.append(("%s[%d]" % (key, i), x))

    def notes():
        v = brief.get("entities")
        if isinstance(v, list):
            for i, e in enumerate(v):
                if isinstance(e, dict) and isinstance(e.get("note"), str):
                    out.append(("entities[%d].note" % i, e["note"]))

    if kind == "report":
        many("summary")
        notes()
        many("questions")
    elif kind == "lib":
        one("goal")
        err = brief.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            out.append(("error.message", err["message"]))
        one("ask")
    else:
        one("goal")
        many("context")
        notes()
        many("constraints")
        one("ask")
    return out


def _token_slots(brief):
    """토큰 칸 [(자리, 토큰)] — entities[].token · fields[].token."""
    out = []
    for key in ("entities", "fields"):
        v = brief.get(key)
        if isinstance(v, list):
            for i, e in enumerate(v):
                if isinstance(e, dict) and isinstance(e.get("token"), str):
                    out.append(("%s[%d].token" % (key, i), e["token"]))
    return out + _sample_slots(brief)


def _sample_slots(brief):
    """파생 표본 (sample) 의 토큰 칸 [(자리, 토큰)] - 열 이름 토큰 · 범주 칸의 토큰 (PH_other 는 토큰이 아니라 묶음 표지)."""
    out = []
    sample = brief.get("sample")
    if isinstance(sample, dict):
        for i, c in enumerate(sample.get("columns") or []):
            if isinstance(c, dict) and isinstance(c.get("token"), str):
                out.append(("sample.columns[%d].token" % i, c["token"]))
        for r, row in enumerate(sample.get("rows") or []):
            if isinstance(row, list):
                for j, cell in enumerate(row):
                    if isinstance(cell, str) and cell != SAMPLE_OTHER:
                        out.append(("sample.rows[%d][%d]" % (r, j), cell))
    return out


def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("같은 키가 두 번")
        d[k] = v
    return d


def _no_constant(_):
    raise ValueError("NaN · Infinity")


def parse_brief(data):
    """bytes · str → dict. 실패하면 None (D1). 같은 키 두 번 · NaN · 크기 넘침 · UTF-8 아님은 실패."""
    if isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = bytes(data)
    if len(raw) > MAX_INPUT_BYTES:
        return None
    try:
        text = raw.decode("utf-8")
        if text.startswith("\ufeff"):
            text = text[1:]
        return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_constant)
    except Exception:
        return None


_SCHEMA = {}


def _schema():
    if "s" not in _SCHEMA:
        _SCHEMA["s"] = briefschema.load_schema(briefschema.default_schema_path())
    return _SCHEMA["s"]


# 파생 표본 (sample · SP-02 · SP-05) - 펼친 글의 표를 닫힌 틀로 다시 읽는다. 칸은 한 자리 정수 · 토큰 · PH_other 뿐이다.
_S_TOKEN = r"PH_[2-9A-HJKMNP-TV-Z]{4}"
_S_CELL = r"(?:[0-9]|%s|%s)" % (_S_TOKEN, SAMPLE_OTHER)
_S_HEAD_RE = re.compile(r"\A\| %s \((?:수치|범주)\)(?: \| %s \((?:수치|범주)\))* \|\Z" % (_S_TOKEN, _S_TOKEN))
_S_SEP_RE = re.compile(r"\A\|(?:---\|)+\Z")
_S_ROW_RE = re.compile(r"\A\| %s(?: \| %s)* \|\Z" % (_S_CELL, _S_CELL))
_S_KIND_RE = re.compile(r"\((?:수치|범주)\)")
_S_FRAME_RE = re.compile(r"[|\-]")


def _check_sample(brief, policy, hits):
    """sample 이 있으면: D1 (칸 수 · 칸 종류 · 열 중복 · 펼친 표가 닫힌 틀) → 틀을 벗긴 표에 D2 · D3 · D5 를 다시.

    D4 의 숫자 칸 예외다 - 셀의 값 범위 (정수 0-9) 는 스키마가, 틀은 여기 D1 이 강제한다.
    """
    sample = brief.get("sample")
    if sample is None:
        return
    cols, rows = sample["columns"], sample["rows"]
    seen = set()
    for i, c in enumerate(cols):
        if c["token"] in seen:
            hits.add("D1", "sample.columns[%d]" % i)
        seen.add(c["token"])
    for r, row in enumerate(rows):
        if len(row) != len(cols):
            hits.add("D1", "sample.rows[%d]" % r)
            continue
        for j, cell in enumerate(row):
            if _is_int_cell(cell) != (cols[j]["kind"] == "수치"):
                hits.add("D1", "sample.rows[%d][%d]" % (r, j))
    lines = sample_lines(sample)
    if ("\n".join(lines) + "\n") not in render(brief):
        hits.add("D1", "sample")
        return
    bad = lines[0] != SAMPLE_HEAD or not _S_HEAD_RE.match(lines[1]) or not _S_SEP_RE.match(lines[2]) \
        or lines[2].count("---") != len(cols)
    hits.add("D1", "sample", 1 if bad else 0)
    for r, line in enumerate(lines[3:]):
        if not _S_ROW_RE.match(line):
            hits.add("D1", "sample.rows[%d]" % r)
    stripped = []
    for line in lines[1:]:
        t = _S_KIND_RE.sub(" ", line)
        t = remove_tokens(t, " ").replace(SAMPLE_OTHER, " ")
        stripped.append(_S_FRAME_RE.sub(" ", t))
    res = _check_text("\n".join(stripped), policy, ("D2", "D3", "D5"))
    for h in res.get("hits", []):
        hits.add(h["check"], "sample", h.get("count", 1))


def _is_int_cell(cell):
    return isinstance(cell, int) and not isinstance(cell, bool)


def check_brief(brief, policy):
    """brief (dict · JSON bytes · str) 를 D1 → D6 → D2 → D3 → D4 → D5 (+D5a) 로 본다.

    돌려주는 것: {"ok": bool, "hits": [{"check", "count", "where"}]} 또는 E-20.
    D1 의 스키마에서 걸리면 거기서 멈춘다 (꼴을 모르면 다음 검사가 칸을 믿을 수 없다).
    """
    try:
        if not isinstance(policy, Policy):
            return e20()
        return _check_brief(brief, policy)
    except Exception:
        return e20()


def _check_brief(brief, policy):
    hits = _Hits()
    if not isinstance(brief, dict):
        brief = parse_brief(brief)
        if brief is None:
            hits.add("D1", "(root)")
            return hits.result()

    # D1 — 스키마
    errs = briefschema.validate(brief, _schema())
    if errs:
        for parts, _kw in errs:
            hits.add("D1", briefschema.format_path(parts))
        return hits.result()

    kind = brief["kind"]
    # D1 — 정책
    if brief["data_class"] == "real" and not policy.real_data:
        hits.add("D1", "data_class")
    if kind == "lib" and brief["library"]["name"].lower() not in policy.lib_allow_lower:
        hits.add("D1", "library.name")

    # D1 — 글자 규칙 · 한 줄 · 틀 표지
    fields = []
    for where, raw in free_text_fields(brief):
        text = prepare(raw)
        bad = sum(1 for ch in text if not allowed_text_char(ch))
        hits.add("D1", where, bad)
        if _DIODE_MARK.search(text) or re.search(r"\[/?diode", re.sub(r"\s+", "", text.lower())):
            hits.add("D1", where)          # [ / d i o d e ] 처럼 글자 사이를 띄운 틀 표지도
        fields.append((where, text))
    repro = brief.get("repro") if kind == "lib" else None
    if isinstance(repro, str):
        hits.add("D1", "repro", sum(1 for ch in repro.replace("\r\n", "\n") if not allowed_code_char(ch)))

    # D1 — 펼친 글 크기
    if len(render(brief).encode("utf-8")) > MAX_RENDERED_BYTES:
        hits.add("D1", "(size)")

    # D1 — 파생 표본 (sample)
    _check_sample(brief, policy, hits)

    # D6 — 토큰
    for where, tok in _token_slots(brief):
        if tok not in policy.tokens:
            hits.add("D6", where)
    for where, text in fields:
        unknown = sum(1 for t in find_tokens(text) if t not in policy.tokens)
        hits.add("D6", where, unknown + find_broken_tokens(text))
    if isinstance(repro, str):
        for no, line in enumerate(repro.replace("\r\n", "\n").split("\n"), 1):
            unknown = sum(1 for t in find_tokens(line) if t not in policy.tokens)
            hits.add("D6", "repro:%d" % no, unknown + find_broken_tokens(line))

    # D2 — 사전 (칸마다 · 그리고 칸을 이어 붙인 글 전체 — 칸을 나눠 숨긴 단어)
    keys = policy.word_keys
    found = set()
    for where, text in fields:
        m = _matched_keys(text, keys)
        hits.add("D2", where, len(m))
        found |= m
    joined = "".join(t for _w, t in fields)
    rest = _matched_keys(joined, keys) - found
    rest |= _split_keys([t for _w, t in fields], keys, found | rest)
    hits.add("D2", "*", len(rest))
    if isinstance(repro, str):
        hits.add("D2", "repro", len(_matched_keys(repro, keys)))
    if kind == "lib":
        if "error" in brief:
            hits.add("D2", "error.type", len(_matched_keys(brief["error"]["type"], keys)))
        if "version" in brief["library"]:
            hits.add("D2", "library.version", len(_matched_keys(brief["library"]["version"], keys)))

    # D3 · D4 · D5 — 자유 글 칸
    for where, text in fields:
        hits.add("D3", where, pattern_hits(text, policy, relative=True))
    for where, text in fields:
        hits.add("D4", where, digit_runs(text))
    for where, text in fields:
        hits.add("D5", where, blob_hits(text, policy))

    # D5a — lib 의 재현 코드 · 예외 이름
    if kind == "lib":
        if isinstance(repro, str) and repro:
            for no in check_repro(repro, policy):
                hits.add("D5a", "repro:%d" % no)
        if "error" in brief and not _error_type_ok(brief["error"]["type"], policy):
            hits.add("D5a", "error.type")

    return hits.result()


# ---------------------------------------------------------------- 글 (프롬프트 · scan)

TEXT_CHECKS = ("D2", "D3", "D4", "D5", "D6")


def check_text(text, policy, checks=("D2", "D3")):
    """사람이 친 글 · 표준 입력의 글을 줄마다 본다. 자리는 "L<줄 번호>" · 줄을 넘는 단어는 "*".

    checks 는 TEXT_CHECKS 의 부분집합. D6 은 policy.tokens 를 가명 표로 본다.
    """
    try:
        if not isinstance(policy, Policy) or not isinstance(text, str):
            return e20()
        for c in checks:
            if c not in TEXT_CHECKS:
                return e20()
        return _check_text(text, policy, checks)
    except Exception:
        return e20()


def _check_text(text, policy, checks):
    hits = _Hits()
    prepared = prepare(text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = prepared.split("\n")
    if "D6" in checks:
        for no, line in enumerate(lines, 1):
            unknown = sum(1 for t in find_tokens(line) if t not in policy.tokens)
            hits.add("D6", "L%d" % no, unknown + find_broken_tokens(line))
    if "D2" in checks:
        keys = policy.word_keys
        found = set()
        for no, line in enumerate(lines, 1):
            m = _matched_keys(line, keys)
            hits.add("D2", "L%d" % no, len(m))
            found |= m
        hits.add("D2", "*", len(_matched_keys(prepared, keys) - found))
    if "D3" in checks:
        for no, line in enumerate(lines, 1):
            hits.add("D3", "L%d" % no, pattern_hits(line, policy))
    if "D4" in checks:
        for no, line in enumerate(lines, 1):
            hits.add("D4", "L%d" % no, digit_runs(line))
    if "D5" in checks:
        for no, line in enumerate(lines, 1):
            hits.add("D5", "L%d" % no, blob_hits(line, policy))
    return hits.result()


# ---------------------------------------------------------------- 사람에게 보이는 한 줄

# 다이오드의 문턱 전압 (BLUEPRINT › 1) 으로 읽는다 — 검사를 모두 통과하면 문턱을 넘어 흐르고 (통과),
# 하나라도 걸리면 문턱을 못 넘어 막힌다.
PASS_LINE = "DIODE V>Vth 통과"
BLOCK_HEAD = "DIODE V<Vth 막힘"


def format_line(result):
    """{"ok": false, "hits": [...]} → "DIODE V<Vth 막힘 · D2 x2 @context[1], ask · D4 x1 @goal" (단어 없음).

    통과면 "DIODE V>Vth 통과" · 막는 쪽 실패면 "DIODE V<Vth 막힘 · E-20".
    """
    if not isinstance(result, dict):
        return BLOCK_HEAD + " · E-20"
    if result.get("ok"):
        return PASS_LINE
    parts = []
    for h in result.get("hits", []):
        if h.get("check") == "E":
            parts.append(str(h.get("code", "E-20")))
            continue
        where = ", ".join(h.get("where", [])[:6])
        if len(h.get("where", [])) > 6:
            where += ", ..."
        parts.append("%s x%d @%s" % (h.get("check"), h.get("count", 0), where))
    return BLOCK_HEAD + " · " + " · ".join(parts if parts else ["E-20"])


# ---------------------------------------------------------------- 데이터 폴더의 정책 (scan 명령 · 훅)

def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def policy_from_home(home, tokens=None):
    """데이터 폴더 (%LOCALAPPDATA%\\diode · 시험은 DIODE_HOME) 의 사전 · 설정 · 공개 이름 목록으로 Policy.

    읽기만 한다. 사전이 없음 · 비었음 · 모르는 format · 깨진 JSON → 예외 (부르는 쪽이 E-20 으로 막는다).
    설정 (config.json) 이 없으면 기본값 (SP-15) 을 쓴다.
    """
    import os
    d = _read_json(os.path.join(home, "dictionary.json"))
    if not isinstance(d, dict) or d.get("format") != 1 or not isinstance(d.get("words"), list):
        raise ValueError("사전 꼴")
    pol = {}
    cfg_path = os.path.join(home, "config.json")
    if os.path.exists(cfg_path):
        cfg = _read_json(cfg_path)
        if not isinstance(cfg, dict) or cfg.get("format") != 1:
            raise ValueError("설정 꼴")
        pol = cfg.get("policy") or {}
        if not isinstance(pol, dict):
            raise ValueError("설정 꼴")
    lib_allow = pol.get("lib_allow", [])
    patterns = pol.get("patterns", [])
    if not isinstance(lib_allow, list) or not isinstance(patterns, list):
        raise ValueError("설정 꼴")
    names = set()
    ln_dir = os.path.join(home, "libnames")
    if os.path.isdir(ln_dir):
        for fn in sorted(os.listdir(ln_dir)):
            if not fn.endswith(".json"):
                continue
            ln = _read_json(os.path.join(ln_dir, fn))
            if not isinstance(ln, dict) or ln.get("format") != 1 or not isinstance(ln.get("names"), list):
                raise ValueError("공개 이름 목록 꼴")
            if str(ln.get("library", "")).lower() in set(str(x).lower() for x in lib_allow):
                names.update(str(x) for x in ln["names"])
    return Policy(words=d["words"], real_data=pol.get("real_data") is True, lib_allow=lib_allow,
                  patterns=patterns, lib_names=names, tokens=tokens)


SCAN_CHECKS = ("D2", "D3", "D5")


def main_scan(home, stdin_bytes):
    """diode.py scan 의 몸통: (종료 코드, 표준 출력 한 줄, 표준 오류 한 줄).

    종료 코드: 0 통과 · 2 막음 (E-20 · 사용법 오류도 2 — 막는 쪽). 출력에 단어는 없다.
    """
    try:
        policy = policy_from_home(home)
    except Exception:
        res = e20()
        return 2, json.dumps(res, ensure_ascii=False), format_line(res)
    try:
        text = stdin_bytes.decode("utf-8")
        if text.startswith("\ufeff"):
            text = text[1:]
    except Exception:
        res = e20()
        return 2, json.dumps(res, ensure_ascii=False), format_line(res)
    res = check_text(text, policy, SCAN_CHECKS)
    code = 0 if res.get("ok") else 2
    return code, json.dumps(res, ensure_ascii=False), format_line(res)
