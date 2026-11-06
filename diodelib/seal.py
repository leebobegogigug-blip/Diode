# -*- coding: utf-8 -*-
"""seal — 초안 brief 를 가명 토큰으로 바꾸고 검사해 펼친다 (SP-02a · SP-04 · SP-05) · 말 봉인 (SP-09).

가명 표 (PseudonymTable) 는 이 프로세스의 메모리에만 있다 (Q6 · W-05 · AL-05).
- 디스크 · 로그 · 출력 · 감사 기록 어디에도 쓰지 않는다. 직렬화 (pickle · copy · json) 를 막는다.
- repr 은 개수만 보인다. 진짜 단어를 꺼내는 길은 real_of() · binding() 둘뿐이고, 둘 다 안쪽에서만 쓴다.

초안 (draft) 은 안쪽 (사내 LLM) 이 쓰는 꼴이다 — brief 와 같되 entities[] · fields[] 가 token 대신
{"ref": "e1", "name": "<진짜 이름>", "label": "<표시 글>"} 을 가질 수 있고, 자유 글은 [[e1]] 로 그것을 가리킨다.
seal 이 ref 마다 토큰을 뽑아 바꾸고 name · label · ref 를 지운다. 진짜 이름은 바깥 글에 남지 않는다.
"""

import copy
import re
import secrets

from . import scan
from .render import render
from .textnorm import prepare
from .scan import TOKEN_ALPHABET, TOKEN_RE

MAX_TOKENS = 2000               # 한 job 의 토큰 상한 [제안]
_REF_RE = re.compile(r"^[a-z][a-z0-9]{0,7}$")
_REF_USE = re.compile(r"\[\[([a-z][a-z0-9]{0,7})\]\]")
_LEFT_REF = re.compile(r"\[\[[^\]]*\]\]")
KINDS = ("entity", "field", "word")


class PseudonymTable(object):
    """토큰 ↔ 진짜 단어. job 하나에 하나 (자문마다 새로 · AL-05)."""

    __slots__ = ("_by_token", "_by_real")

    def __init__(self):
        self._by_token = {}         # token -> (real, kind, label)
        self._by_real = {}          # (real, kind) -> token

    def __repr__(self):
        return "<PseudonymTable %d개>" % len(self._by_token)

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("가명 표는 직렬화하지 않는다")

    def __reduce_ex__(self, protocol):
        raise TypeError("가명 표는 직렬화하지 않는다")

    def __copy__(self):
        raise TypeError("가명 표는 복사하지 않는다")

    def __deepcopy__(self, memo):
        raise TypeError("가명 표는 복사하지 않는다")

    def __len__(self):
        return len(self._by_token)

    def __contains__(self, token):
        return token in self._by_token

    def _new_token(self):
        for _ in range(1000):
            t = "PH_" + "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4))
            if t not in self._by_token:
                return t
        raise RuntimeError("토큰을 뽑지 못함")

    def token_for(self, real, kind="word", label=None):
        """진짜 단어의 토큰. 같은 단어 · 같은 종류는 같은 토큰 (한 job 안에서)."""
        if not isinstance(real, str) or not real.strip():
            raise ValueError("빈 이름")
        if kind not in KINDS:
            raise ValueError("종류")
        key = (real, kind)
        tok = self._by_real.get(key)
        if tok is None:
            if len(self._by_token) >= MAX_TOKENS:
                raise RuntimeError("토큰 상한")
            tok = self._new_token()
            self._by_real[key] = tok
            self._by_token[tok] = (real, kind, label)
        elif label is not None and self._by_token[tok][2] is None:
            self._by_token[tok] = (real, kind, label)
        return tok

    def tokens(self):
        return frozenset(self._by_token)

    def real_of(self, token):
        """안쪽 전용. 모르는 토큰이면 None."""
        e = self._by_token.get(token)
        return e[0] if e else None

    def kind_of(self, token):
        e = self._by_token.get(token)
        return e[1] if e else None

    def reals(self, kinds=KINDS):
        """안쪽 전용 — D2 · U2 가 진짜 이름을 사전처럼 보는 데만 쓴다."""
        return [e[0] for e in self._by_token.values() if e[1] in kinds]

    def binding(self):
        """묶기 파일의 내용 (SP-07) — 안쪽 전용. 화면 코드는 토큰으로만 짜고 이것으로 이름을 붙인다."""
        fields = {}
        entities = {}
        for tok in sorted(self._by_token):
            real, kind, label = self._by_token[tok]
            if kind == "field":
                fields[tok] = {"name": real, "label": label if label is not None else real}
            elif kind == "entity":
                entities[tok] = {"name": real}
        return {"format": 1, "fields": fields, "entities": entities}


# ---------------------------------------------------------------- seal (초안 → 봉인 글)

def _fail(hits):
    return {"ok": False, "hits": hits}


def _free_text_paths(brief):
    """초안의 자유 글을 고쳐 쓸 수 있게 (부모, 키) 목록으로."""
    out = []
    kind = brief.get("kind")
    keys_one = ("goal", "ask") if kind != "report" else ()
    for k in keys_one:
        if isinstance(brief.get(k), str):
            out.append((brief, k))
    for k in ("context", "constraints", "summary", "questions"):
        v = brief.get(k)
        if isinstance(v, list):
            for i in range(len(v)):
                if isinstance(v[i], str):
                    out.append((v, i))
    for e in brief.get("entities") or []:
        if isinstance(e, dict) and isinstance(e.get("note"), str):
            out.append((e, "note"))
    err = brief.get("error")
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        out.append((err, "message"))
    return out


def seal(draft, table, policy, known_tokens=()):
    """초안 (dict) → {"ok": true, "text": <펼친 글>, "brief": <봉인한 brief>} 또는 {"ok": false, "hits": [...]}.

    - ref 가 있는 entities · fields 에 table 로 토큰을 준다. [[ref]] 를 토큰으로 바꾼다.
    - 그 job 의 진짜 이름 (table 전체) 을 사전에 더해 검사한다 — 진짜 이름을 자유 글에 바로 쓴 것을 잡는다.
    - 검사는 scan.check_brief (D1–D6 · D5a). 하나라도 걸리면 글을 돌려주지 않는다 (자동으로 가려 보내지 않는다).
    - 실패 · 예외는 막는 쪽 (E-20). 결과에 단어는 없다 (AL-11).
    """
    try:
        if not isinstance(table, PseudonymTable) or not isinstance(policy, scan.Policy):
            return scan.e20()
        if not isinstance(draft, dict):
            return _fail([{"check": "D1", "count": 1, "where": ["(root)"]}])
        return _seal(draft, table, policy, frozenset(known_tokens))
    except Exception:
        return scan.e20()


def _seal(draft, table, policy, known_tokens=frozenset()):
    b = copy.deepcopy(draft)
    refs = {}
    bad_refs = []
    for key, kind in (("entities", "entity"), ("fields", "field")):
        items = b.get(key)
        if not isinstance(items, list):
            continue
        for i, e in enumerate(items):
            if not isinstance(e, dict):
                continue
            if "name" in e or "ref" in e or "label" in e:
                ref = e.pop("ref", None)
                name = e.pop("name", None)
                label = e.pop("label", None)
                if (ref is not None and (not isinstance(ref, str) or not _REF_RE.match(ref) or ref in refs)) \
                        or not isinstance(name, str) or not name.strip() \
                        or (label is not None and not isinstance(label, str)) \
                        or (label is not None and kind != "field") or "token" in e:
                    bad_refs.append("%s[%d]" % (key, i))
                    continue
                tok = table.token_for(name, kind, label)
                e["token"] = tok
                if ref is not None:
                    refs[ref] = tok
    if bad_refs:
        return _fail([{"check": "D1", "count": len(bad_refs), "where": bad_refs}])

    left = []
    for parent, k in _free_text_paths(b):
        s = _REF_USE.sub(lambda m: refs.get(m.group(1), m.group(0)), parent[k])
        parent[k] = s
        if _LEFT_REF.search(s):
            left.append(k if isinstance(k, str) else "[%d]" % k)
    if left:
        return _fail([{"check": "D1", "count": len(left), "where": ["(ref)"]}])

    pol = policy.derive(tokens=table.tokens() | known_tokens, extra_words=table.reals())
    res = scan.check_brief(b, pol)
    if not res.get("ok"):
        return res
    return {"ok": True, "text": render(b), "brief": b}


# ---------------------------------------------------------------- 말 봉인 (사람이 사내 말로 쓴 글)

def _word_regex(word):
    """사전 단어 하나를 글자 사이 구분자 (빈칸 · - _ . / · ,) 를 허용하는 정규식으로 (대소문자 무시)."""
    chars = [c for c in word if c.isalnum()]
    if len(chars) < 2:
        return None
    sep = r"[\s\-_./·,]*"
    return re.compile(sep.join(re.escape(c) for c in chars), re.I)


def seal_speech(text, table, policy, words):
    """사람이 사내 말로 쓴 글 → 사전 단어를 토큰으로 바꾼 글과 남은 검사 결과.

    {"text": <토큰 글>, "check": <scan.check_text 결과 (D2 · D3 · D4 · D6)>}
    사전 단어는 긴 것부터 바꾼다. 바꾼 뒤에도 걸리는 것 (숫자 · 경로 · 사전에 없는 변형) 은 사람이 고친다.
    돌려주는 글은 창에만 보이고, 사람이 [복사] 할 때만 밖으로 간다 (D8).
    """
    try:
        out = prepare(text)
        for w in sorted(set(x for x in words if isinstance(x, str)), key=len, reverse=True):
            rx = _word_regex(w)
            if rx is None:
                continue
            if rx.search(out):
                tok = table.token_for(w, "word")
                out = rx.sub(tok, out)
        pol = policy.derive(tokens=table.tokens(), extra_words=table.reals())
        return {"text": out, "check": scan.check_text(out, pol, ("D2", "D3", "D4", "D6"))}
    except Exception:
        return {"text": None, "check": scan.e20()}


def is_token(s):
    return bool(TOKEN_RE.fullmatch(s))
