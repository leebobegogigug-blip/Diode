# -*- coding: utf-8 -*-
"""unseal — 들어오는 답을 U1–U4 로 보고 토큰을 되돌린다 (SP-06 · SP-07). U5: 받은 코드는 돌리지 않는다.

- 글 (plan · lib · report 의 답, 마크다운): 아는 정확한 꼴의 토큰을 진짜 단어로 바꾼다.
- 화면 코드 (ui, HTML 한 파일): 글자를 바꾸지 않는다. 묶기 파일 (binding.local.json) 을 따로 만든다.

돌려주는 text · binding 에는 진짜 단어가 있다 — 안쪽 작업 폴더에만 쓰고, 허브 도구의 결과 · 로그 ·
감사 기록 · 표준 출력으로 내보내지 않는다 (AL-14). issues 칸은 줄 번호 · 개수만이라 내보내도 된다.
"""

import errno
import json
import os
import re
import tempfile

from . import scan
from .seal import PseudonymTable
from .scan import TOKEN_RE

MAX_MD_BYTES = 64 * 1024        # U4 [제안]
MAX_UI_BYTES = 512 * 1024       # U4 [제안]

_URL_RE = re.compile(r"(?i)\b(?:https?|wss?|ftp|file)://[^\s\"'<>)\]]*|(?<![:\w/])//[A-Za-z0-9.\-]+\.[A-Za-z]{2,}[^\s\"'<>)\]]*")
_U3_CODE = (
    re.compile(r"\bfetch\s*\("),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\bWebSocket\s*\("),
    re.compile(r"\bEventSource\s*\("),
    re.compile(r"\bnavigator\s*\.\s*sendBeacon\b"),
    re.compile(r"\bimportScripts\s*\("),
    re.compile(r"(?i)<\s*script\b[^>]*\bsrc\s*="),
    re.compile(r"(?i)<\s*link\b[^>]*\bhref\s*="),
    re.compile(r"(?i)<\s*iframe\b"),
    re.compile(r"(?i)<\s*form\b[^>]*\baction\s*="),
    re.compile(r"(?i)@import\b"),
    re.compile(r"(?i)\bimport\s*\(\s*['\"](?:https?:)?//"),
    re.compile(r"(?i)\burl\s*\(\s*['\"]?(?:https?:)?//"),
    re.compile(r"\bwindow\s*\.\s*open\s*\("),
    re.compile(r"\blocation\s*\.\s*(?:href|assign|replace)\b"),
)
_HTML_HEAD = re.compile(r"(?is)^\s*(?:<!--.*?-->\s*)*(?:<!doctype\s+html\b|<html\b)")
_HTML_END = re.compile(r"(?i)</html\s*>\s*$")
URL_REMOVED = "<주소 지움>"


def _lines_of(rx, lines):
    return [no for no, line in enumerate(lines, 1) if rx.search(line)]


def u1(text, table):
    """U1: 표에 없는 정확한 꼴 · 깨진 꼴이 있는 줄 번호."""
    bad = []
    for no, line in enumerate(text.split("\n"), 1):
        unknown = any(t not in table for t in scan.find_tokens(line))
        if unknown or scan.find_broken_tokens(line):
            bad.append(no)
    return bad


def u2(text, table, policy):
    """U2: 답에 든 사전 단어의 개수 (D2 의 정규화 · 줄마다 + 전체).

    말 봉인으로 토큰이 된 단어 (종류 word) 도 본다. 화면 · 항목 이름 (entity · field) 은 흔한 말일 수 있어
    U2 에 넣지 않는다 — 나가는 쪽 (seal) 에서는 넣는다.
    """
    pol = policy.derive(extra_words=table.reals(("word",)))
    res = scan.check_text(text, pol, ("D2",))
    if not isinstance(res, dict) or any(h.get("check") == "E" for h in res.get("hits", [])):
        raise RuntimeError("U2 검사 실패")
    return sum(h.get("count", 0) for h in res.get("hits", []))


def u3(text):
    """U3: 바깥 주소 · 바깥으로 부르는 코드가 있는 줄 번호."""
    lines = text.split("\n")
    out = set(_lines_of(_URL_RE, lines))
    for rx in _U3_CODE:
        out.update(_lines_of(rx, lines))
    return sorted(out)


def unseal(answer, table, policy, kind, md_limit=None):
    """답 (str) → {"ok", "stop", "text", "binding", "issues"}.

    ok    False 면 안쪽에 쓰지 않는다 (U2 · U4 · ui 의 U3 · 오류).
    stop  True 면 그 job 을 멈추고 사람에게 알린다 (U2 — Claude 가 진짜 단어를 맞혔다 · 재식별).
    issues {"U1": [줄], "U2": 개수, "U3": [줄], "U4": bool} — 단어 없음.
    md_limit  글 답 (ui 밖) 의 U4 상한을 바이트로 바꾼다 (없으면 MAX_MD_BYTES). 말 봉인 창이 자기 상한을 줄 때 쓴다.
    """
    try:
        if not isinstance(table, PseudonymTable) or not isinstance(policy, scan.Policy) \
                or not isinstance(answer, str) or kind not in ("plan", "ui", "lib", "report"):
            return _err()
        if md_limit is not None and (type(md_limit) is not int or md_limit < 1):
            return _err()
        return _unseal(answer, table, policy, kind, MAX_MD_BYTES if md_limit is None else md_limit)
    except Exception:
        return _err()


def _err():
    return {"ok": False, "stop": True, "text": None, "binding": None, "issues": {"E": "E-20"}}


def _unseal(answer, table, policy, kind, md_limit=MAX_MD_BYTES):
    text = answer.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    size = len(text.encode("utf-8"))
    if kind == "ui":
        u4_bad = size > MAX_UI_BYTES or not _HTML_HEAD.search(text) or not _HTML_END.search(text)
    else:
        u4_bad = size > md_limit
    issues = {"U1": u1(text, table), "U2": u2(text, table, policy), "U3": u3(text), "U4": bool(u4_bad)}

    if issues["U2"]:
        return {"ok": False, "stop": True, "text": None, "binding": None, "issues": issues}
    if issues["U4"]:
        return {"ok": False, "stop": False, "text": None, "binding": None, "issues": issues}

    if kind == "ui":
        if issues["U3"]:
            # 화면 코드는 글자를 바꾸지 않는다 — 바깥으로 부르는 코드가 있으면 쓰지 않는다 (W-03)
            return {"ok": False, "stop": False, "text": None, "binding": None, "issues": issues}
        return {"ok": True, "stop": False, "text": text, "binding": table.binding(), "issues": issues}

    # 글: 바깥 주소는 지우고 (줄은 issues 에), 아는 토큰만 되돌린다
    text = _URL_RE.sub(URL_REMOVED, text)

    def back(m):
        real = table.real_of(m.group(0))
        return real if real is not None else m.group(0)
    return {"ok": True, "stop": False, "text": TOKEN_RE.sub(back, text), "binding": None, "issues": issues}


# ---------------------------------------------------------------- 결과 파일 (덮어쓰지 않는다 · SP-07)

def _free_name(path):
    if not os.path.exists(path):
        yield path
    base, ext = os.path.splitext(path)
    for n in range(2, 1000):
        yield "%s-%d%s" % (base, n, ext)


def write_new(path, text):
    """path 에 새 파일로 쓴다. 이미 있으면 -2 · -3 … 을 붙인다. 원자적 (임시 파일 → 링크). 쓴 자리를 돌려준다."""
    d = os.path.dirname(os.path.abspath(path))
    data = text.encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".diode-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for cand in _free_name(path):
            try:
                os.link(tmp, cand)          # 있으면 FileExistsError — 덮어쓰지 않는다
                return cand
            except FileExistsError:
                continue
            except OSError as e:
                if e.errno in (errno.EEXIST,):
                    continue
                # 링크를 못 만드는 파일 체계: 배타적 만들기로
                try:
                    with open(cand, "xb") as f:
                        f.write(data)
                    return cand
                except FileExistsError:
                    continue
        raise RuntimeError("빈 이름을 찾지 못함")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def write_binding(work_dir, table):
    """안쪽 작업 폴더에 binding.local.json 을 새로 쓴다 (덮어쓰지 않음). 커밋하지 않는다 (.gitignore)."""
    text = json.dumps(table.binding(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    return write_new(os.path.join(work_dir, "binding.local.json"), text)
