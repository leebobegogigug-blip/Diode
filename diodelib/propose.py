# -*- coding: utf-8 -*-
"""propose — 일꾼 (사내 LLM) 이 보고 초안을 허브에 낸다 (SP-09 · 표준 라이브러리 · Python 3.8).

    python diode.py propose <report.json>

1. 초안을 읽는다 (UTF-8 JSON · 64 KiB 이하 · kind report · job 꼴).
2. 미리 본다: 데이터 폴더의 사전 · 설정으로 seal 을 한 번 돌린다 (토큰은 새 표 · 초안에 이미 있는 정확한 꼴 토큰은
   지시에서 받은 것으로 본다 — 표 확인은 허브가 한다). 걸리면 {"queued": false, "hits": [...]} (단어 없음) · 종료 코드 2.
3. 통과하면 데이터 폴더 queue\\<job>-<시각>.json 에 (0600 · 원자적으로) 두고 {"queued": true, "job": "J-0007"} · 0.
   허브가 그 job 의 표로 다시 봉인 → D7 → 확정 창 → outbox.

표준 출력은 JSON 한 줄뿐이다. 데이터 폴더는 늘 기본 자리 (허브 · 훅과 같은 자리 · DIODE_HOME 을 받지 않는다).
"""

import json
import os
import re
import tempfile
import time

from . import scan
from .room import default_data_dir
from .seal import PseudonymTable, seal

MAX_BYTES = 64 * 1024
JOB_RE = re.compile(r"^J-[0-9]{4}\Z")


def _line(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _err(code):
    return _line({"queued": False, "error": code})


def main_propose(path, home=None):
    """(종료 코드, 표준 출력 한 줄). 0 넣음 · 2 걸림 · 꼴 오류 (E-04) · 사전 · 설정 오류 (E-20)."""
    try:
        home = home or default_data_dir()
        if not isinstance(path, str) or not os.path.isfile(path):
            return 2, _err("E-04")
        if os.path.getsize(path) > MAX_BYTES:
            return 2, _err("E-04")
        with open(path, "rb") as f:
            draft = scan.parse_brief(f.read())
        if not isinstance(draft, dict) or draft.get("kind") != "report" \
                or not isinstance(draft.get("job"), str) or not JOB_RE.match(draft["job"]):
            return 2, _err("E-04")
        try:
            policy = scan.policy_from_home(home)
        except Exception:
            return 2, _err("E-20")
        known = set()
        for v in _strings(draft):
            known.update(scan.find_tokens(v))
        res = seal(draft, PseudonymTable(), policy, known_tokens=known)
        if not res.get("ok"):
            return 2, _line({"queued": False, "hits": res.get("hits", [])})
        _enqueue(home, draft)
        return 0, _line({"queued": True, "job": draft["job"]})
    except Exception:
        return 2, _err("E-20")


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            for s in _strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in _strings(v):
                yield s


def _enqueue(home, draft):
    d = os.path.join(home, "queue")
    os.makedirs(d, mode=0o700, exist_ok=True)
    stamp = "%d%06d" % (int(time.time()), os.getpid() % 1000000)
    fd, tmp = tempfile.mkstemp(prefix=".q-", suffix=".tmp", dir=d)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        for n in range(100):
            name = os.path.join(d, "%s-%s%s.json" % (draft["job"], stamp, "" if n == 0 else "x%d" % n))
            try:
                os.link(tmp, name)
                return name
            except FileExistsError:
                continue
        raise RuntimeError("대기열 이름")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
