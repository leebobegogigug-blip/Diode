# -*- coding: utf-8 -*-
"""가린 묶음 (SP-20) — 표시 읽기 · 토큰 매기기 · 자동 가림 · 잔여 검사 R1–R6 · 되돌리기 (표준 라이브러리 · Python 3.8).

결정적 순수 함수만 둔다. 허브 · 금고 파일 · 확정 창과 잇는 일은 부르는 쪽이 한다.
- parse_marks(text)                          ⟦값⟧ · ⟦n:값⟧ · ⟦p:값⟧ · ⟦i:값⟧ 을 읽는다. 틀린 꼴은 BundleError("E-04")
- mask_text(text, vault, words)              표시 → 금고 토큰, 그다음 표시 밖의 사전 단어 · 금고 값을 자동으로 한 번 더 가림
- residual_hits(masked, policy, vault, n)    잔여 검사 R1–R6 (SP-05 의 hits 꼴 · 자리는 "F02:L14")
- build_bundle(manifest, workdir, vault, policy, words, job)    묶음 하나: 꼴 검사 → 가림 → R1–R6 · note 의 D1–D6
- restore_text(text, vault) · restore_name(name, vault)           금고로 되돌리기 (안쪽 전용)
- return_checks(text, vault, policy)         Claude 가 돌려준 글의 U1 · U2 · U3

금고는 덕 타이핑으로만 쓴다 (이 모듈은 금고를 import 하지 않는다):
  token_for(real, kind) -> "PH_XXXX" · real_of(token) -> (real, kind) | None · tokens() -> frozenset ·
  reals(min_len=2) -> list (긴 것부터) · file_name(real_path, ext) -> "F03.py" · file_real(name) -> 상대 경로 | None

지키는 것
- 결과 · 예외에는 검사 번호 · 개수 · 자리 (칸 이름 · 파일 번호 · 줄 번호) 와 고정된 까닭 낱말만 쓴다. 값 · 단어 ·
  경로 · 원래 파일 이름은 쓰지 않는다 (AL-11). 가린 글 (files[].text) 은 확정 창에만 보인다 (D8).
- 같은 입력 · 같은 금고 상태 → 같은 출력. 금고에 묻는 차례도 정해져 있다 (파일 차례 → 표시 차례 → 후보 차례 → 글 차례).
- restore_text · restore_name 이 돌려주는 글에는 진짜 값이 있다. 안쪽 작업 폴더에만 쓴다 (AL-14).
"""

import hashlib
import os
import re
import stat
import unicodedata
from bisect import bisect_right
from collections import namedtuple

from . import scan, unseal
from .scan import TOKEN_RE, find_broken_tokens, remove_tokens
from .seal import _word_regex
from .textnorm import allowed_text_char, dict_key, nfkc, prepare, skeleton

MARK_OPEN = "\u27e6"            # ⟦
MARK_CLOSE = "\u27e7"           # ⟧
MARK_PREFIXES = {"n": "number", "p": "path", "i": "ident"}     # 머리 글자가 없으면 word
KINDS = ("word", "number", "path", "ident")
MAX_MARK_VALUE = 512            # 표시 값의 글자 수 상한 (SP-20)
MAX_BUNDLE_FILES = 20
MAX_FILE_BYTES = 256 * 1024     # 파일마다 (원본 · 가린 글 모두)
MAX_BUNDLE_BYTES = 1024 * 1024  # 묶음 합계 (원본 · 가린 글 모두)
FILE_TYPES = ("doc", "table", "code")
BUNDLE_FORMAT = 1
BUNDLE_KIND = "bundle"
MANIFEST_REQUIRED = frozenset(["format", "kind", "files"])
MANIFEST_OPTIONAL = frozenset(["job", "note"])      # job 이 없으면 허브가 번호를 붙인다
FILE_ENTRY_KEYS = frozenset(["path", "type"])
MAX_NOTE_CHARS = 200            # note 한 줄의 글자 수 상한 - SP-02 의 text200 과 같게 [제안]
NOTE_CHECKS = ("D2", "D3", "D4", "D5", "D6")       # + D1 (한 줄 · 글자 규칙 · 틀 표지 · 길이) 은 여기서
PAYLOAD_FREE_NUMBER_MAX = 99    # R4 - 이 값 이하의 정수 (두 자리 이하) 는 그대로 둔다
MIN_VAULT_REAL = 2              # R2 · U2 · 자동 가림 - 금고 값은 2글자 이상만 본다
OUT_EXT_DEFAULT = "txt"         # 원본 확장자가 영숫자 1-8자가 아니면
R5_MIN_CHUNK = 20               # R5 - 엔트로피를 재는 덩어리의 최소 길이 (D5 의 ASCII 덩어리와 같다)

JOB_RE = re.compile(r"\AJ-[0-9]{4}\Z")
EXT_RE = re.compile(r"\A[A-Za-z0-9]{1,8}\Z")
OUT_NAME_RE = re.compile(r"\AF[0-9]{2,4}\.[A-Za-z0-9]{1,8}\Z")    # 금고가 매기는 나가는 이름
_ERROR_CODE_RE = re.compile(r"\AE-[0-9]{2}\Z")

_ASCII_ALNUM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
_ASCII_WORD = _ASCII_ALNUM | frozenset("_")
# 토큰 정규식 (SP-04) 의 경계: 앞에 [A-Za-z0-9_] · 뒤에 [A-Za-z0-9] 가 붙으면 토큰으로 읽히지 않는다.
_TOKEN_LEFT_BAD = _ASCII_WORD
_TOKEN_RIGHT_BAD = _ASCII_ALNUM
_LINE_BREAKS = frozenset("\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")
_KIND_RANK = {"word": 0, "number": 1, "path": 2, "ident": 3}
_WINDOWS_DEVICES = frozenset(["con", "prn", "aux", "nul"] + ["com%d" % i for i in range(1, 10)]
                             + ["lpt%d" % i for i in range(1, 10)])


class BundleError(Exception):
    """묶음을 받지 않는 까닭. code (E-04 · E-20 …) · where (칸 · "F02:L14") · reason (고정된 영어 낱말) 만 싣는다.

    메시지는 번호뿐이다 - 값 · 단어 · 경로 · 파일 이름을 넣지 않는다 (AL-11).
    """

    def __init__(self, code, where=(), reason=None):
        Exception.__init__(self, code)
        self.code = code
        self.where = list(where)
        self.reason = reason

    def __str__(self):
        return self.code


def _e04(where, reason):
    return BundleError("E-04", where, reason)


# ---------------------------------------------------------------- 표시 (⟦ … ⟧)

Mark = namedtuple("Mark", "start end kind value line")      # start · end: 글 안의 자리 (⟦ 부터 ⟧ 다음까지) · line: 1부터


def parse_marks(text):
    """가리기 표시를 읽는다 -> [Mark] (나온 차례).

    머리 글자 n: p: i: 가 종류 (없으면 word). 머리 글자 꼴은 "영문 한 글자 + :" 이고, 그 꼴이 아니면 값의 일부다
    (⟦p:D:\\x⟧ 는 path 값 D:\\x · ⟦a:b⟧ 는 머리 글자를 모르는 꼴 · ⟦ab:c⟧ 는 word 값 ab:c).
    틀린 꼴은 모두 모아 BundleError("E-04", where=["L<줄>", …]) 하나로 낸다. 까닭 (reason · 처음 것):
      unclosed 닫히지 않음 · newline 값에 줄바꿈 · empty 빈 값 · prefix 모르는 머리 글자 · nested 겹침 ·
      long 값이 MAX_MARK_VALUE 를 넘음 · stray 여는 표시 없이 닫음 ·
      boundary 표시 바로 앞에 ASCII 글자 · 숫자 · _ 가, 바로 뒤에 ASCII 글자 · 숫자가 붙음 (또는 표시끼리 붙음) -
               그 자리에 토큰을 넣으면 토큰으로 읽히지 않아 되돌릴 수 없다 (SP-04 의 경계). 낱말 전체를 감싸야 한다.
    """
    if not isinstance(text, str):
        raise _e04(["(root)"], "text")
    marks = []
    bad = []
    offset = 0
    skip_close = -1             # 줄바꿈이 든 표시의 닫는 자리 - 다음 줄에서 따로 "stray" 로 세지 않는다
    for no, ln in enumerate(text.split("\n"), 1):
        i = 0
        while True:
            o = ln.find(MARK_OPEN, i)
            c = ln.find(MARK_CLOSE, i)
            if o < 0 and c < 0:
                break
            if c >= 0 and (o < 0 or c < o):
                if offset + c != skip_close:
                    bad.append((no, "stray"))
                i = c + 1
                continue
            c2 = ln.find(MARK_CLOSE, o + 1)
            o2 = ln.find(MARK_OPEN, o + 1)
            if c2 < 0:
                later = _closes_later(text, offset + len(ln))
                if later >= 0:
                    skip_close = later
                bad.append((no, "newline" if later >= 0 else "unclosed"))
                break
            if 0 <= o2 < c2:
                bad.append((no, "nested"))
                i = c2 + 1
                continue
            reason, kind, value = _mark_value(ln[o + 1:c2])
            if reason is None:
                before = ln[o - 1] if o > 0 else ""
                after = ln[c2 + 1] if c2 + 1 < len(ln) else ""
                if before in _TOKEN_LEFT_BAD or before == MARK_CLOSE \
                        or after in _TOKEN_RIGHT_BAD or after == MARK_OPEN:
                    reason = "boundary"
            if reason is not None:
                bad.append((no, reason))
            else:
                marks.append(Mark(offset + o, offset + c2 + 1, kind, value, no))
            i = c2 + 1
        offset += len(ln) + 1
    if bad:
        raise _e04(["L%d" % n for n in sorted(set(n for n, _r in bad))], bad[0][1])
    return marks


def _closes_later(text, pos):
    """줄 끝 (pos) 뒤에서 여는 표시보다 닫는 표시가 먼저 나오면 그 자리 (값에 줄바꿈이 든 표시) · 아니면 -1."""
    c = text.find(MARK_CLOSE, pos)
    o = text.find(MARK_OPEN, pos)
    return c if c >= 0 and (o < 0 or c < o) else -1


def _mark_value(content):
    """표시 안의 글 -> (까닭 | None, 종류, 값)."""
    kind = "word"
    value = content
    if len(content) >= 2 and content[1] == ":" and content[0] in _ASCII_ALNUM and not content[0].isdigit():
        kind = MARK_PREFIXES.get(content[0])
        if kind is None:
            return "prefix", None, None
        value = content[2:]
    if not value.strip():
        return "empty", None, None
    if any(ch in _LINE_BREAKS for ch in value):
        return "newline", None, None
    if len(value) > MAX_MARK_VALUE:
        return "long", None, None
    return None, kind, value


# ---------------------------------------------------------------- 가림 (표시 → 토큰 · 자동 가림)

_FREE, _TOKEN, _LOCK = 0, 1, 2      # 조각 종류: 아직 볼 글 · 토큰 · 건드리지 않고 남긴 글 (R1 · R2 가 잡는다)


def _checked_token(tok):
    if not isinstance(tok, str) or not TOKEN_RE.fullmatch(tok):
        raise BundleError("E-20", [], "vault")          # 금고가 정확한 꼴이 아닌 토큰을 줌 - 막는 쪽
    return tok


def _mark_pieces(text, marks, vault):
    """표시를 금고 토큰으로 바꾸고, 원래 있던 정확한 꼴의 토큰도 조각으로 떼어 둔다 (건드리지 않는다)."""
    pieces = []
    pos = 0
    for m in marks:
        if m.start > pos:
            pieces.append([_FREE, text[pos:m.start]])
        pieces.append([_TOKEN, _checked_token(vault.token_for(m.value, m.kind))])
        pos = m.end
    if pos < len(text):
        pieces.append([_FREE, text[pos:]])
    out = []
    for kind, s in pieces:
        if kind != _FREE:
            out.append([kind, s])
            continue
        last = 0
        for t in TOKEN_RE.finditer(s):
            if t.start() > last:
                out.append([_FREE, s[last:t.start()]])
            out.append([_TOKEN, t.group(0)])
            last = t.end()
        if last < len(s):
            out.append([_FREE, s[last:]])
    return out


def _vault_kinds(vault):
    """금고의 진짜 값 -> 종류. 한 값이 여러 종류면 KINDS 의 차례로 앞의 것 (word 먼저)."""
    out = {}
    for tok in sorted(vault.tokens()):
        e = vault.real_of(tok)
        if not e:
            continue
        real, kind = e
        prev = out.get(real)
        if prev is None or _KIND_RANK.get(kind, 9) < _KIND_RANK.get(prev, 9):
            out[real] = kind
    return out


def _candidates(vault, words, kinds):
    """자동 가림 후보 [_Cand] - 알맹이 글자가 긴 것부터 · 같으면 글자 차례 (결정적).

    정규식은 SP-09 말 봉인과 같은 규칙 (seal._word_regex - 글자 사이 구분자 허용 · 대소문자 무시) 에
    값 그대로의 꼴을 앞에 더한 것이다 (D:\\a 처럼 구분자 밖의 글자가 든 금고 값도 그대로 나오면 가린다).
    """
    pool = {}
    for w in words:
        if isinstance(w, str):
            pool.setdefault(w, "word")
    for r in vault.reals(min_len=MIN_VAULT_REAL):
        if isinstance(r, str):
            pool[r] = kinds.get(r, "word")       # 금고 값이 원래 다른 종류였으면 그 종류의 토큰
    out = []
    for w, kind in pool.items():
        key = dict_key(w)
        alnum = sum(1 for c in w if c.isalnum())
        if alnum < 2 or len(key) < scan.MIN_WORD_KEY:
            continue                               # seal._word_regex 가 None 을 내는 꼴 · D2 가 쓰지 않는 짧은 열쇠
        out.append((-alnum, w, key, kind))
    out.sort(key=lambda x: (x[0], x[1]))
    return [_Cand(w, key, kind) for _n, w, key, kind in out]


class _Cand(object):
    """자동 가림 후보 하나. 정규식은 글에 열쇠가 있을 때 처음 한 번만 만든다 (금고 값이 많아도 빠르게)."""

    __slots__ = ("word", "key", "kind", "_rx")

    def __init__(self, word, key, kind):
        self.word, self.key, self.kind, self._rx = word, key, kind, None

    @property
    def rx(self):
        if self._rx is None:
            self._rx = re.compile("(?:%s)|(?:%s)" % (re.escape(self.word), _word_regex(self.word).pattern), re.I)
        return self._rx


def _line_matches(rx, s):
    """s 의 줄마다 rx 가 찾은 자리 [(시작, 끝)] (s 기준). 줄을 넘는 자리는 찾지 않는다 - 줄바꿈을 토큰에 삼키지 않고,
    줄을 넘겨 쪼갠 단어는 그대로 남겨 R1 · R2 가 줄 번호와 함께 잡게 한다."""
    out = []
    base = 0
    for seg in s.split("\n"):
        for m in rx.finditer(seg):
            if m.end() > m.start():
                out.append((base + m.start(), base + m.end()))
        base += len(seg) + 1
    return out


def _auto_mask(pieces, cands, vault, kinds, dkey):
    """후보마다 아직 볼 글 (_FREE) 에서만 찾아 토큰으로 바꾼다 -> (조각, 바꾼 수).

    - 찾은 자리가 ASCII 낱말 안이면 (loadKITWORDALPHAData) 그 낱말 끝까지 넓혀 한 값으로 가린다 - 토큰 앞뒤가
      [A-Za-z0-9_] · [A-Za-z0-9] 에 붙으면 토큰으로 읽히지 않기 때문이다. 넓힌 자리끼리 겹치거나 붙으면 하나로 합친다.
    - 토큰은 찾은 글 그대로를 값으로 받는다 (kit-word alpha 는 그 글의 토큰) - 되돌린 글이 원문과 같게.
    - 넓혀도 이웃 토큰에 붙는 자리는 바꾸지 않고 남긴다 (_LOCK). 더 짧은 후보가 그 안을 쪼개지 않고, R1 · R2 가 잡는다.
    - 한 줄 안에서만 찾는다 (_line_matches).
    """
    n_auto = 0
    present = set(_present_keys(dkey, [c.key for c in cands]))
    for cand in cands:
        if cand.key not in present:
            continue                              # 정규화한 글에 열쇠가 없으면 이 후보는 어디에도 없다
        rx, ckind = cand.rx, cand.kind
        new = []
        for idx, piece in enumerate(pieces):
            if piece[0] != _FREE:
                new.append(piece)
                continue
            s = piece[1]
            spans = []
            for a, b in _line_matches(rx, s):
                while a > 0 and s[a - 1] in _ASCII_WORD:
                    a -= 1
                while b < len(s) and s[b] in _ASCII_ALNUM:
                    b += 1
                if spans and a <= spans[-1][1]:
                    spans[-1][1] = max(spans[-1][1], b)
                else:
                    spans.append([a, b])
            if not spans:
                new.append(piece)
                continue
            left_char = new[-1][1][-1] if new else ""
            right_char = pieces[idx + 1][1][0] if idx + 1 < len(pieces) else ""
            pos = 0
            for a, b in spans:
                if a > pos:
                    new.append([_FREE, s[pos:a]])
                surface = s[a:b]
                lc = left_char if a == 0 else s[a - 1]
                rc = right_char if b == len(s) else s[b]
                if lc in _TOKEN_LEFT_BAD or rc in _TOKEN_RIGHT_BAD:
                    new.append([_LOCK, surface])
                else:
                    kind = kinds.get(surface) or ckind
                    new.append([_TOKEN, _checked_token(vault.token_for(surface, kind))])
                    kinds.setdefault(surface, kind)
                    n_auto += 1
                left_char = surface[-1]
                pos = b
            if pos < len(s):
                new.append([_FREE, s[pos:]])
        pieces = new
    return pieces, n_auto


def _join_pieces(pieces):
    masked = "".join(p[1] for p in pieces)
    n_tok = sum(1 for p in pieces if p[0] == _TOKEN)
    if len(TOKEN_RE.findall(masked)) != n_tok:
        raise BundleError("E-20", [], "token")       # 넣은 토큰이 토큰으로 읽히지 않음 - 되돌릴 수 없으니 막는다
    return masked


def _stats(masked, marked, auto):
    return {"marked": marked, "auto": auto, "tokens": len(set(TOKEN_RE.findall(masked)))}


def mask_text(text, vault, words):
    """글 하나를 가린다 -> (가린 글, {"marked": n, "auto": n, "tokens": n}).

    (가) 표시를 금고 토큰으로 (종류는 머리 글자) · (나) 자동 가림: 표시 밖에 남은 사전 단어 (words) 와 금고 값
    (vault.reals) 을 긴 것부터 찾아 토큰으로 (사전 단어는 word · 금고 값은 그 값의 종류). 이미 토큰인 자리는 건드리지 않는다.
    tokens 는 가린 글에 든 서로 다른 토큰 수. 틀린 표시는 BundleError("E-04", ["L<줄>"]).
    """
    marks = parse_marks(text)
    pieces = _mark_pieces(text, marks, vault)
    kinds = _vault_kinds(vault)
    cands = _candidates(vault, words, kinds)
    pieces, auto = _auto_mask(pieces, cands, vault, kinds, dict_key(text))
    masked = _join_pieces(pieces)
    return masked, _stats(masked, len(marks), auto)


# ---------------------------------------------------------------- 잔여 검사 R1–R6

def _join(parts):
    starts = []
    pos = 0
    for p in parts:
        starts.append(pos)
        pos += len(p)
    return "".join(parts), starts


_SET_SEARCH_MIN = 256           # 같은 길이의 열쇠가 이보다 많으면 부분 문자열 집합으로 한꺼번에 본다 (금고 값이 많을 때)


def _present_keys(big, keys):
    """keys 가운데 big 에 부분 문자열로 든 것 (keys 차례 그대로)."""
    by_len = {}
    for k in keys:
        by_len.setdefault(len(k), []).append(k)
    hit = set()
    n = len(big)
    for size, ks in by_len.items():
        if size > n:
            continue
        if len(ks) < _SET_SEARCH_MIN:
            hit.update(k for k in ks if k in big)
            continue
        subs = set(map(big.__getitem__, map(slice, range(n - size + 1), range(size, n + 1))))
        hit.update(k for k in ks if k in subs)
    return [k for k in keys if k in hit]


def _find_lines(big, starts, needle, out):
    """big 안의 needle 이 시작하는 줄 번호 (1부터) 를 out 에 더한다. 줄을 넘는 것은 시작한 줄."""
    i = big.find(needle)
    while i >= 0:
        out.add(bisect_right(starts, i))
        i = big.find(needle, i + 1)


def _key_lines(norm_variants, keys, use_skeleton=True):
    """정규화한 줄 목록들 (변형마다) 에서 열쇠가 걸린 자리 -> {줄: {열쇠}}.

    줄마다 따로 정규화해 이어 붙인 글에서 찾는다 - 줄 안 · 줄을 넘는 것 (scan.check_text 의 "*") 을 한 번에,
    걸린 줄 번호와 함께. 길이 SKELETON_MIN_KEY 이상의 열쇠는 ASCII 닮은 꼴을 접은 글에서도 찾는다 (D2 와 같다).
    """
    found = {}
    long_keys = [k for k in keys if len(k) >= scan.SKELETON_MIN_KEY] if use_skeleton else []
    for norm in norm_variants:
        big, starts = _join(norm)
        for k in _present_keys(big, keys):
            hit = set()
            _find_lines(big, starts, k, hit)
            for ln in hit:
                found.setdefault(ln, set()).add(k)
        if not long_keys:
            continue
        sbig, sstarts = _join([skeleton(p) for p in norm])
        sk_of = dict((k, scan._skeleton_of(k)) for k in long_keys)
        present = set(_present_keys(sbig, sorted(set(sk_of.values()))))
        for k in long_keys:
            if sk_of[k] in present:
                hit = set()
                _find_lines(sbig, sstarts, sk_of[k], hit)
                for ln in hit:
                    found.setdefault(ln, set()).add(k)
    return found


def _norms(lines):
    """줄마다 D2 정규화 - (토큰 그대로, 토큰 지움). R1 · R2 · U2 가 함께 쓴다."""
    return [dict_key(ln) for ln in lines], [dict_key(remove_tokens(ln, "")) for ln in lines]


def _dict_line_hits(norms, policy):
    """R1 · U2 의 사전 쪽: D2 와 같은 두 글 (토큰 그대로 · 토큰 지움) 에서 사전 열쇠 (scan._matched_keys 와 같은 규칙)."""
    return _key_lines(list(norms), policy.word_keys)


def _ascii_digits(s):
    """NFKC 뒤에도 남은 유니코드 숫자 (아랍 · 데바나가리 숫자 …) 를 ASCII 숫자로. 숫자 값이 없는 숫자 글자는 0 으로."""
    out = []
    for ch in s:
        if "0" <= ch <= "9" or ch.isascii():
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat == "Nd":
            out.append(str(unicodedata.decimal(ch, 0)))
        elif cat in ("No", "Nl"):
            d = unicodedata.digit(ch, None)
            out.append("0" if d is None else str(d))
        else:
            out.append(ch)
    return "".join(out)


def _number_text(line):
    """R4 · R2 가 보는 숫자 글: 토큰을 지우고 NFKC (전각 숫자) 뒤 유니코드 숫자를 ASCII 로."""
    return _ascii_digits(nfkc(remove_tokens(line, " ")))


_NUM_RUN_RE = re.compile(r"[0-9]+(?:[.,:/\-][0-9]+)*")      # R2 의 숫자 덩어리 (구분자 한 글자씩 · 빈칸은 끊는다)


def _digit_key(s):
    return "".join(ch for ch in _ascii_digits(nfkc(s)) if "0" <= ch <= "9")


class _VaultIndex(object):
    """R2 · U2 의 금고 쪽 비교 열쇠. 값은 밖으로 내지 않는다.

    - number 값: 숫자만 이어 붙인 열쇠 (3.5 -> 35 · 2026-11-26 -> 20261126) 를 글의 숫자 덩어리 열쇠와 **같음** 으로 본다.
      글자를 다 지우는 D2 정규화로 짧은 수를 보면 3 + 5 같은 흔한 글이 모두 걸린다. 세 자리 이상 · 소수 · 날짜 · 시각은
      R4 가 따로 막는다.
    - 그 밖의 값: dict_key 열쇠 (D2 정규화) 를 토큰을 지운 글에서 부분 문자열로 (ASCII 닮은 꼴 접기 포함).
      토큰을 남긴 글은 보지 않는다 - 토큰 글자 (PH_K35Q) 가 짧은 값 (35) 과 우연히 겹친다.
    """

    def __init__(self, vault):
        self.tokens = frozenset(vault.tokens())
        kinds = _vault_kinds(vault)
        num = set()
        text = set()
        for real in vault.reals(min_len=MIN_VAULT_REAL):
            if not isinstance(real, str):
                continue
            if kinds.get(real) == "number":
                dk = _digit_key(real)
                if len(dk) >= MIN_VAULT_REAL:
                    num.add(dk)
                    continue
            k = dict_key(real)
            if len(k) >= scan.MIN_WORD_KEY:
                text.add(k)
        self.num_keys = frozenset(num)
        self.text_keys = sorted(text)

    def line_hits(self, lines, norms):
        """{줄: 걸린 열쇠 수}. norms = _norms(lines)."""
        out = {}
        if self.text_keys:
            for ln, ks in _key_lines([norms[1]], self.text_keys).items():
                out[ln] = out.get(ln, 0) + len(ks)
        if self.num_keys:
            for no, line in enumerate(lines, 1):
                runs = set(_digit_key(m.group(0)) for m in _NUM_RUN_RE.finditer(_number_text(line)))
                n = len(runs & self.num_keys)
                if n:
                    out[no] = out.get(no, 0) + n
        return out


# R4 - 날짜 · 시각 · 소수 (지수 꼴 포함) · 정수 덩어리. 날짜와 시각이 숫자를 먼저 먹는다.
_R4_RE = re.compile(
    r"(?P<date>[0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})"
    r"|(?P<time>[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)"
    r"|(?P<dec>[0-9]*\.[0-9]+(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)"
    r"|(?P<int>[0-9]+)")
_FREE_INT_DIGITS = len(str(PAYLOAD_FREE_NUMBER_MAX))


def number_hits(line):
    """R4: 토큰을 지운 줄에서 세 자리 이상 정수 · 소수 · 날짜 · 시각 꼴의 개수. 두 자리 이하 정수 (<= 99) 는 세지 않는다."""
    n = 0
    for m in _R4_RE.finditer(_number_text(line)):
        run = m.group("int")
        if run is not None and len(run) <= _FREE_INT_DIGITS and int(run) <= PAYLOAD_FREE_NUMBER_MAX:
            continue
        n += 1
    return n


# R5 - 코드 · 표 · JSON 의 구분 글자로 자른 덩어리만 잰다 (이어 쓴 코드 한 줄 전체를 한 덩어리로 재지 않게).
_R5_CUT = re.compile(r"[\s()\[\]{}<>,;:=\"'`|]+")
_R5_CHUNK_RE = re.compile(r"[\x21-\x7e]{%d,}" % R5_MIN_CHUNK)


def secret_blob_hits(line, policy):
    """R5: 비밀처럼 보이는 덩어리의 개수 (D5 의 hex · base64 · 엔트로피 규칙 - 코드 꼴 · 식별자 꼴 규칙은 걸지 않는다).

    - hex 16자 이상 (scan._HEX_RE 그대로)
    - 구분 글자로 자른 ASCII 덩어리 (20자 이상) 중 공개 이름이 아니고, 글자와 숫자가 함께 있고, 셰넌 엔트로피가
      ENTROPY_BITS 이상인 것 - base64 꼴 (scan._B64_RE) 도 이 덩어리 안에 든다. 글자만 있는 긴 식별자
      (test_restore_name_returns_path) 는 글자와 숫자가 함께 있지 않아 세지 않는다.
    """
    s = remove_tokens(nfkc(line), " ")
    n = sum(1 for _ in scan._HEX_RE.finditer(s))
    for piece in _R5_CUT.split(s):
        if len(piece) < R5_MIN_CHUNK:
            continue
        for m in _R5_CHUNK_RE.finditer(piece):
            chunk = m.group(0)
            if scan._public_name(chunk, policy):
                continue
            if not any(c.isdigit() for c in chunk) or not any(c.isalpha() for c in chunk):
                continue
            if scan._entropy(chunk) >= scan.ENTROPY_BITS:
                n += 1
    return n


def token_problems(line, tokens):
    """R6: 금고에 없는 정확한 꼴 토큰 + 깨진 꼴 + 남은 표시 기호 (⟦ ⟧) 의 개수."""
    unknown = sum(1 for t in TOKEN_RE.findall(line) if t not in tokens)
    return unknown + find_broken_tokens(line) + line.count(MARK_OPEN) + line.count(MARK_CLOSE)


def _residual(masked, policy, index, file_no, hits):
    tag = "F%02d" % file_no
    lines = masked.split("\n")

    def add(check, per_line):
        for ln in sorted(per_line):
            hits.add(check, "%s:L%d" % (tag, ln), per_line[ln])

    norms = _norms(lines)
    add("R1", dict((ln, len(ks)) for ln, ks in _dict_line_hits(norms, policy).items()))
    add("R2", index.line_hits(lines, norms))
    for check, fn in (("R3", lambda ln: scan.pattern_hits(remove_tokens(ln, " "), policy)),
                      ("R4", number_hits),
                      ("R5", lambda ln: secret_blob_hits(ln, policy)),
                      ("R6", lambda ln: token_problems(ln, index.tokens))):
        for no, line in enumerate(lines, 1):
            hits.add(check, "%s:L%d" % (tag, no), fn(line))


def _ordered(hits):
    """_Hits 의 결과를 R1-R6 · D1-D6 차례로 (검사 차례가 파일 차례에 섞이지 않게)."""
    order = ["R1", "R2", "R3", "R4", "R5", "R6", "D1", "D2", "D3", "D4", "D5", "D6"]
    res = hits.result()["hits"]
    return sorted(res, key=lambda h: order.index(h["check"]) if h["check"] in order else len(order))


def residual_hits(masked, policy, vault, file_no):
    """가린 글 하나의 잔여 검사 R1-R6 -> SP-05 꼴의 hits 목록 [{"check": "R4", "count": 2, "where": ["F02:L14"]}].

    file_no 는 나가는 이름의 번호 (F02.py -> 2).

    R1 사전 (D2 정규화 · 변형) · R2 금고 값 (2글자 이상) · R3 D3 꼴 (줄마다 · 상대 경로는 세지 않는다 · 토큰은 지우고) ·
    R4 숫자 · R5 비밀 덩어리 · R6 토큰 (금고에 없음 · 깨진 꼴 · 남은 표시 기호). 줄 번호는 1부터. 값 · 단어는 넣지 않는다.
    """
    if not isinstance(policy, scan.Policy) or not isinstance(masked, str):
        raise BundleError("E-20", [], "input")
    hits = scan._Hits()
    _residual(masked, policy, _VaultIndex(vault), int(file_no), hits)
    return _ordered(hits)


# ---------------------------------------------------------------- note (한 줄 · SP-05 의 D1-D6)

def _note_hits(note, policy, vault, hits):
    text = prepare(note)
    d1 = 1 if len(note) > MAX_NOTE_CHARS else 0
    d1 += sum(1 for ch in text if not allowed_text_char(ch))          # 줄바꿈 · 탭 · 표시 기호 · ASCII 밖 글자
    if scan._DIODE_MARK.search(text) or re.search(r"\[/?diode", re.sub(r"\s+", "", text.lower())):
        d1 += 1
    hits.add("D1", "note", d1)
    rel = scan.pattern_hits(text, policy, relative=True) - scan.pattern_hits(text, policy)
    hits.add("D3", "note", rel)                                       # note 는 brief 의 자유 글 - 상대 경로도 센다 (SP-05 D3)
    pol = policy.derive(tokens=vault.tokens(), extra_words=vault.reals(min_len=MIN_VAULT_REAL))
    res = scan.check_text(text, pol, NOTE_CHECKS)
    for h in res.get("hits", []):
        if h.get("check") == "E":
            raise BundleError("E-20", ["note"], "check")
        hits.add(h["check"], "note", h.get("count", 1))
    return text


# ---------------------------------------------------------------- 묶음 (manifest → 가린 파일들)

def _rel_parts(path):
    """작업 폴더 안 상대 경로 -> 조각 목록 (/ · \\ 를 모두 나눔). 틀리면 None.

    거절: 빈 글 · NUL · 절대 경로 · 드라이브 · 콜론 (NTFS 의 다른 흐름 포함) · 빈 조각 · . · .. ·
    끝이 점 · 빈칸인 조각 (Windows 가 지워 다른 이름이 된다) · Windows 장치 이름 (CON · NUL …).
    """
    if not isinstance(path, str) or not path or "\x00" in path or ":" in path:
        return None
    if any(ch in _LINE_BREAKS for ch in path):
        return None
    parts = re.split(r"[/\\]", path)
    for p in parts:
        if p in ("", ".", "..") or p.endswith(".") or p.endswith(" "):
            return None
        if p.split(".")[0].lower() in _WINDOWS_DEVICES:
            return None
    return parts


def _read_inside(root, parts):
    """root (실제 경로) 안의 보통 파일을 읽는다 -> bytes (MAX_FILE_BYTES + 1 까지). 틀리면 까닭 낱말 (str)."""
    cur = root
    for p in parts:
        cur = os.path.join(cur, p)
        if os.path.islink(cur):
            return "link"
    try:
        st = os.lstat(cur)
    except OSError:
        return "missing"
    if not stat.S_ISREG(st.st_mode):
        return "missing"
    real = os.path.realpath(cur)
    try:
        if os.path.commonpath([root, real]) != root:
            return "link"                         # 정션 · 이름 바꾸기로 작업 폴더 밖을 가리킴
    except ValueError:
        return "link"
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(cur, flags)
    except OSError:
        return "missing"
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(fst.st_mode):
            return "link"                         # 검사와 열기 사이에 바뀜
        chunks = []
        left = MAX_FILE_BYTES + 1
        while left > 0:
            b = os.read(fd, min(left, 65536))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _out_ext(base, policy):
    """나가는 이름의 확장자: 원본 확장자 (영숫자 1-8자) · 아니면 txt. 사전 단어가 든 확장자도 txt (이름으로 새지 않게)."""
    ext = os.path.splitext(base)[1][1:]
    if not EXT_RE.match(ext):
        return OUT_EXT_DEFAULT
    if scan._matched_keys(ext, policy.word_keys):
        return OUT_EXT_DEFAULT
    return ext


def _count_lines(text):
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _check_manifest(manifest, job):
    """manifest 의 꼴 -> ([(상대 경로 조각, 종류)], note, job). 틀리면 BundleError("E-04")."""
    if not isinstance(manifest, dict):
        raise _e04(["(root)"], "manifest")
    keys = set(manifest)
    if not MANIFEST_REQUIRED <= keys or keys - MANIFEST_REQUIRED - MANIFEST_OPTIONAL:
        raise _e04(["(root)"], "keys")
    fmt = manifest["format"]
    if type(fmt) is not int or fmt != BUNDLE_FORMAT:
        raise _e04(["format"], "format")
    if manifest["kind"] != BUNDLE_KIND:
        raise _e04(["kind"], "kind")
    if job is not None and (not isinstance(job, str) or not JOB_RE.match(job)):
        raise _e04(["job"], "job")
    mjob = manifest.get("job")
    if mjob is not None or "job" in manifest:
        if not isinstance(mjob, str) or not JOB_RE.match(mjob) or (job is not None and mjob != job):
            raise _e04(["job"], "job")
    note = manifest.get("note", "")
    if not isinstance(note, str):
        raise _e04(["note"], "note")
    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_BUNDLE_FILES:
        raise _e04(["files"], "files")
    entries = []
    bad = []
    seen = set()
    for i, f in enumerate(files):
        if not isinstance(f, dict) or set(f) != FILE_ENTRY_KEYS:
            bad.append(("files[%d]" % i, "keys"))
            continue
        if f["type"] not in FILE_TYPES:
            bad.append(("files[%d].type" % i, "type"))
            continue
        parts = _rel_parts(f["path"])
        if parts is None:
            bad.append(("files[%d].path" % i, "path"))
            continue
        norm = os.path.normcase("/".join(parts))
        if norm in seen:
            bad.append(("files[%d].path" % i, "dup"))
            continue
        seen.add(norm)
        entries.append((parts, f["type"]))
    if bad:
        raise _e04([w for w, _r in bad], bad[0][1])
    return entries, note, mjob if mjob is not None else job


def build_bundle(manifest, workdir, vault, policy, words, job=None):
    """묶음 하나를 만든다 -> {"ok", "files", "hits", "stats", "note"}.

    files  manifest 차례 그대로 [{"name": "F01.md", "type", "bytes", "lines", "text", "sha256"}] - ok 가 아니면
           text · sha256 은 None (걸린 값이 남은 글을 돌려주지 않는다). bytes · lines · sha256 은 가린 글 (UTF-8) 의 것.
    hits   SP-05 꼴 · R1-R6 (자리 "F03:L14" - 나가는 이름의 번호와 줄) + note 의 D1-D6 (자리 "note"). 비면 ok.
    stats  {"files", "bytes", "marked", "auto", "tokens"} - 개수만 (tokens 는 묶음 전체의 서로 다른 토큰 수).
    note   손질한 note 한 줄 (MANIFEST.md 에 쓸 글 · 검사한 글과 같다) - ok 가 아니면 None.

    꼴이 틀리면 (manifest · 경로 · 크기 · 글이 아님 · 틀린 표시) BundleError("E-04", where) - 자리는 칸 이름
    ("files[2].path") 또는 manifest 차례와 줄 ("files[2]:L7" - 이름을 매기기 전이다). 그 밖의 실패는
    BundleError("E-20") (금고가 번호를 실은 예외면 그 번호).
    job 은 선택 - 있으면 manifest 의 job 과 같아야 한다.

    금고에 남는 것: 꼴 검사를 모두 통과한 뒤에만 금고를 부른다. 그 뒤 잔여 검사에서 걸려도 이미 만든 토큰 ·
    나가는 이름 (vault.file_name) 은 금고에 남는다 - 같은 값 · 같은 파일은 다시 보낼 때 같은 토큰 · 같은 이름이어야
    하고, 토큰 · 이름은 값을 담지 않는다 (무작위 · 번호). 금고는 이 함수가 쓰지 않는다 (부르는 쪽이 저장).
    """
    try:
        if not isinstance(policy, scan.Policy):
            raise BundleError("E-20", [], "policy")
        return _build(manifest, workdir, vault, policy, words, job)
    except BundleError:
        raise
    except Exception as e:                        # 막는 쪽 (AL-03) - 원래 예외의 글은 싣지 않는다
        code = getattr(e, "code", None)
        raise BundleError(code if isinstance(code, str) and _ERROR_CODE_RE.match(code) else "E-20",
                          [], "error") from None


def _build(manifest, workdir, vault, policy, words, job):
    entries, note, _job = _check_manifest(manifest, job)
    if not isinstance(workdir, str) or not os.path.isdir(workdir):
        raise _e04(["(root)"], "workdir")
    root = os.path.realpath(workdir)

    # 1) 읽기 · 크기 · UTF-8 · NUL · 표시 꼴 - 모두 금고를 부르기 전에 (틀리면 금고에 아무것도 남기지 않는다)
    texts = []
    bad = []
    total = 0
    for i, (parts, _t) in enumerate(entries):
        data = _read_inside(root, parts)
        if isinstance(data, str):
            bad.append(("files[%d].path" % i, data))
            continue
        if len(data) > MAX_FILE_BYTES:
            bad.append(("files[%d]" % i, "size"))
            continue
        total += len(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            bad.append(("files[%d]" % i, "utf8"))
            continue
        if "\x00" in text:
            bad.append(("files[%d]" % i, "nul"))
            continue
        texts.append(text)
    if bad:
        raise _e04([w for w, _r in bad], bad[0][1])
    if total > MAX_BUNDLE_BYTES:
        raise _e04(["files"], "total")
    all_marks = []
    for i, text in enumerate(texts):
        try:
            all_marks.append(parse_marks(text))
        except BundleError as e:
            bad.extend(("files[%d]:%s" % (i, w), e.reason) for w in e.where)
    if bad:
        raise _e04([w for w, _r in bad], bad[0][1])

    # 2) 표시 -> 토큰 (모든 파일 먼저 - 다른 파일에서 표시한 값도 자동 가림의 후보가 된다)
    file_pieces = [_mark_pieces(t, m, vault) for t, m in zip(texts, all_marks)]
    kinds = _vault_kinds(vault)
    cands = _candidates(vault, words, kinds)

    # 3) 자동 가림 · 나가는 이름 · 크기
    out_files = []
    stats = {"files": len(texts), "bytes": 0, "marked": 0, "auto": 0, "tokens": 0}
    all_tokens = set()
    masked_texts = []
    for i, (parts, ftype) in enumerate(entries):
        pieces, auto = _auto_mask(file_pieces[i], cands, vault, kinds, dict_key(texts[i]))
        masked = _join_pieces(pieces)
        raw = masked.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise _e04(["files[%d]" % i], "size")
        name = vault.file_name("/".join(parts), _out_ext(parts[-1], policy))
        if not isinstance(name, str) or not OUT_NAME_RE.match(name):
            raise BundleError("E-20", [], "vault")
        stats["bytes"] += len(raw)
        stats["marked"] += len(all_marks[i])
        stats["auto"] += auto
        all_tokens.update(TOKEN_RE.findall(masked))
        masked_texts.append(masked)
        out_files.append({"name": name, "type": ftype, "bytes": len(raw), "lines": _count_lines(masked),
                          "text": masked, "sha256": hashlib.sha256(raw).hexdigest()})
    if stats["bytes"] > MAX_BUNDLE_BYTES:
        raise _e04(["files"], "total")
    if len(set(f["name"] for f in out_files)) != len(out_files):
        raise BundleError("E-20", [], "vault")    # 다른 원본에 같은 이름 - 되돌리기가 모호해진다
    stats["tokens"] = len(all_tokens)

    # 4) 잔여 검사 R1-R6 · note 의 D1-D6
    hits = scan._Hits()
    index = _VaultIndex(vault)
    for f, masked in zip(out_files, masked_texts):
        _residual(masked, policy, index, int(f["name"][1:f["name"].index(".")]), hits)
    note_text = _note_hits(note, policy, vault, hits)
    res = _ordered(hits)
    ok = not res
    if not ok:
        for f in out_files:
            f["text"] = None
            f["sha256"] = None
    return {"ok": ok, "files": out_files, "hits": res, "stats": stats, "note": note_text if ok else None}


# ---------------------------------------------------------------- 되돌리기 · 들어오는 검사

def restore_text(text, vault):
    """정확한 꼴의 토큰 가운데 금고에 있는 것만 진짜 값으로 (모든 종류) -> (되돌린 글, 바꾼 수). 모르는 토큰은 그대로."""
    if not isinstance(text, str):
        raise _e04(["(root)"], "text")
    count = [0]

    def back(m):
        e = vault.real_of(m.group(0))
        if not e:
            return m.group(0)
        count[0] += 1
        return e[0]
    return TOKEN_RE.sub(back, text), count[0]


def restore_name(name, vault):
    """첨부 이름 -> 안쪽에 쓸 이름 (없으면 None).

    묶음 이름 (F01.md 꼴) 이고 금고가 아는 이름이면 원래 상대 경로 (/ 구분). 아니면 이름 안의 토큰만 되돌린 이름 -
    되돌린 이름에 경로 글자 (/ \\ .. : NUL · 줄바꿈) 가 있거나 비면 거절 (None).
    """
    if not isinstance(name, str) or not name:
        return None
    if OUT_NAME_RE.match(name):
        real = vault.file_real(name)
        if real is not None:
            parts = _rel_parts(real) if isinstance(real, str) else None
            return "/".join(parts) if parts else None
    restored, _n = restore_text(name, vault)
    if not restored or restored in (".",) or "/" in restored or "\\" in restored or ".." in restored \
            or ":" in restored or "\x00" in restored or any(ch in _LINE_BREAKS for ch in restored):
        return None
    return restored


def return_checks(text, vault, policy):
    """Claude 가 돌려준 글 (첨부 · 지시) 의 들어오는 검사 -> {"U1": [줄], "U2": n, "U3": [줄]}.

    U1 금고에 없는 정확한 꼴 · 깨진 꼴의 줄 (unseal.u1) · U2 사전 단어 + 금고 값이 글에 나온 수 (R1 · R2 와 같은
    비교 · 개수만 - 하나라도 있으면 그 묶음을 멈춘다) · U3 바깥 주소의 줄 (unseal.u3). 값은 넣지 않는다.
    """
    if not isinstance(text, str) or not isinstance(policy, scan.Policy):
        raise BundleError("E-20", [], "input")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    index = _VaultIndex(vault)
    lines = text.split("\n")
    norms = _norms(lines)
    u2 = sum(len(ks) for ks in _dict_line_hits(norms, policy).values())
    u2 += sum(index.line_hits(lines, norms).values())
    return {"U1": unseal.u1(text, index.tokens), "U2": u2, "U3": unseal.u3(text)}
