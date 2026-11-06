# -*- coding: utf-8 -*-
"""감사 기록 (SP-14 · AL-07) — 표준 라이브러리 · Python 3.8.

자리: <데이터 폴더>/audit/<YYYY-MM>/<job>-<순번>-<out|in|dispatch>.json
  - 데이터 폴더는 인자로 받는다 (기본 자리는 room.default_data_dir — 부르는 쪽이 정한다).
  - 쓰기는 임시 파일 → 링크로 이름 붙이기 (있으면 실패 · 덮어쓰지 않음). 순번은 그 job 의 다음 빈 번호.
  - 링크를 못 만드는 파일 체계면 배타적 만들기 (xb).

남기는 것
  out       보낸 펼친 글 그대로 (text) · sha256 · 크기 — decision 이 sent 면 text 가 꼭 있다
  in        Claude 의 답 — text 를 남기지 않는다 (해시 · 크기 · 검사 결과만)
  dispatch  넘기기 (안쪽으로) — text 에 되돌리기 전의 지시 (토큰 꼴)
  derive    파생 표본을 만든 기록 (derive_record) — 변환 종류별 열 수 · 행 수뿐 (값 · 열 이름 · 토큰 없음)

남기지 않는 것: 가명 표 · 원자료 · 사전 단어. 그것을 받을 인자 자체가 없다 (W-05).
checks 는 SP-05 꼴의 칸 (검사 번호 · 개수 · 자리 · 판정 · 닫힌 까닭 번호) 만 받는다 (AL-11).
"""

import datetime
import errno
import hashlib
import json
import os
import re
import tempfile

FORMAT = 1
AUDIT_DIR = "audit"
DIRECTIONS = ("out", "in", "dispatch")
DECISIONS = ("sent", "discarded", "blocked", "timeout")
# [제안] dispatch 의 kind 는 SP-14 에 없다 — "instruction" 으로 둔다
KINDS = ("plan", "ui", "lib", "report", "instruction")
# [제안] dispatch 의 transport 는 SP-14 에 없다 — 일꾼에 넣으므로 "worker"
TRANSPORTS = ("clipboard", "room", "adapter", "worker")
EFFORTS = ("", "auto", "low", "medium", "high", "xhigh", "max")
JOB_RE = re.compile(r"^J-[0-9]{4,6}\Z")
MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}\Z")
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
MAX_TEXT_BYTES = 524288          # 남길 글의 상한 (U4 의 ui 상한과 같게) [제안]
MAX_MODEL_CHARS = 200
MAX_SEQ = 9999
# checks 의 칸 — 단어 · 값을 담을 칸이 없다 (AL-11)
CHECK_KEYS = frozenset(["check", "verdict", "reason", "count", "where", "code", "lines"])
MAX_CHECKS = 50
MAX_CHECK_STR = 64
MAX_CHECK_LIST = 50
_CHECK_STR_RE = re.compile(r"^[A-Za-z0-9_\-\[\]:.*]{1,64}\Z")


class AuditError(ValueError):
    """감사 기록을 쓸 수 없다 — 부르는 쪽은 보내지 않는다 (AL-03)."""


def _now():
    return datetime.datetime.now().astimezone().replace(microsecond=0)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_checks(checks):
    if checks is None:
        return []
    if not isinstance(checks, (list, tuple)) or len(checks) > MAX_CHECKS:
        raise AuditError("checks 꼴")
    out = []
    for c in checks:
        if not isinstance(c, dict) or not isinstance(c.get("check"), str) or set(c) - CHECK_KEYS:
            raise AuditError("checks 꼴")
        item = {}
        for k, v in c.items():
            if isinstance(v, bool) or (isinstance(v, int) and k in ("count",)):
                if isinstance(v, bool) or v < 0 or v > 1000000:
                    raise AuditError("checks 꼴")
                item[k] = v
            elif isinstance(v, str):
                if not _CHECK_STR_RE.match(v):
                    raise AuditError("checks 꼴")
                item[k] = v
            elif isinstance(v, list) and k in ("where", "lines"):
                if len(v) > MAX_CHECK_LIST:
                    v = v[:MAX_CHECK_LIST]
                vals = []
                for x in v:
                    if isinstance(x, bool):
                        raise AuditError("checks 꼴")
                    if isinstance(x, int) and 0 <= x <= 1000000:
                        vals.append(x)
                    elif isinstance(x, str) and _CHECK_STR_RE.match(x):
                        vals.append(x)
                    else:
                        raise AuditError("checks 꼴")
                item[k] = vals
            else:
                raise AuditError("checks 꼴")
        out.append(item)
    return out


def build(job, direction, kind, transport, decision, text=None, sha256=None, size=None,
          checks=None, model="", effort="", now=None):
    """기록 한 건 (사전) 을 만든다. 꼴이 틀리면 AuditError."""
    if not isinstance(job, str) or not JOB_RE.match(job):
        raise AuditError("job 꼴")
    if direction not in DIRECTIONS:
        raise AuditError("direction")
    if kind not in KINDS:
        raise AuditError("kind")
    if transport not in TRANSPORTS:
        raise AuditError("transport")
    if decision not in DECISIONS:
        raise AuditError("decision")
    if not isinstance(model, str) or len(model) > MAX_MODEL_CHARS or any(ch in model for ch in "\r\n\t"):
        raise AuditError("model")
    if effort not in EFFORTS:
        raise AuditError("effort")
    if direction == "in" and text is not None:
        raise AuditError("in 은 글을 남기지 않는다")
    if direction != "in" and decision == "sent" and text is None:
        raise AuditError("보낸 글이 없다")
    if text is not None:
        if not isinstance(text, str):
            raise AuditError("text 꼴")
        data = text.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise AuditError("text 가 너무 크다")
        h = hashlib.sha256(data).hexdigest()
        if sha256 is not None and sha256 != h:
            raise AuditError("sha256 이 글과 다르다")
        if size is not None and size != len(data):
            raise AuditError("크기가 글과 다르다")
        sha256, size = h, len(data)
    if sha256 is not None and (not isinstance(sha256, str) or not HEX64_RE.match(sha256)):
        raise AuditError("sha256 꼴")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
        raise AuditError("크기 꼴")
    if direction == "in" and sha256 is None:
        raise AuditError("in 은 해시가 있어야 한다")
    at = now or _now()
    rec = {"format": FORMAT, "at": at.isoformat(), "job": job, "direction": direction, "kind": kind,
           "transport": transport, "decision": decision}
    if sha256 is not None:
        rec["sha256"] = sha256
    if size is not None:
        rec["bytes"] = size
    if text is not None:
        rec["text"] = text
    rec["checks"] = _clean_checks(checks)
    rec["model"] = model
    rec["effort"] = effort
    return rec


def _link_new(tmp, data, d, job, direction):
    """임시 파일을 다음 빈 순번의 이름에 링크한다 (있으면 다음 번호). 쓴 자리를 돌려준다."""
    pat = re.compile(r"^" + re.escape(job) + r"-([0-9]+)-(?:out|in|dispatch|derive)\.json\Z")
    used = [int(m.group(1)) for m in (pat.match(fn) for fn in os.listdir(d)) if m]
    seq = (max(used) + 1) if used else 1
    while seq <= MAX_SEQ:
        cand = os.path.join(d, "%s-%03d-%s.json" % (job, seq, direction))
        try:
            os.link(tmp, cand)          # 있으면 FileExistsError — 덮어쓰지 않는다
            return cand
        except FileExistsError:
            seq += 1
            continue
        except OSError as e:
            if e.errno == errno.EEXIST:
                seq += 1
                continue
            try:                        # 링크를 못 만드는 파일 체계
                with open(cand, "xb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                return cand
            except FileExistsError:
                seq += 1
                continue
    raise AuditError("빈 순번이 없다")


def write(home, rec):
    """만든 기록을 데이터 폴더에 쓴다. 쓴 자리를 돌려준다. 실패하면 예외 (부르는 쪽이 막는다)."""
    month = rec["at"][:7]
    if not MONTH_RE.match(month):
        raise AuditError("시각 꼴")
    d = os.path.join(home, AUDIT_DIR, month)
    os.makedirs(d, exist_ok=True)
    data = (json.dumps(rec, ensure_ascii=False, sort_keys=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".diode-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return _link_new(tmp, data, d, rec["job"], rec["direction"])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def record(home, job, direction, kind, transport, decision, text=None, sha256=None, size=None,
           checks=None, model="", effort="", now=None):
    """감사 기록 한 건을 남긴다 → 쓴 파일 자리. 꼴이 틀리거나 못 쓰면 예외 (AL-03 — 보내지 않는다).

    가명 표 · 원자료 · 사전 단어를 받을 인자가 없다. direction "in" 은 text 를 받지 않는다 (sha256 · size 만).
    """
    rec = build(job, direction, kind, transport, decision, text=text, sha256=sha256, size=size,
                checks=checks, model=model, effort=effort, now=now)
    return write(home, rec)


# 파생 표본 (L2) 의 만든 기록 - 변환 종류별 열 수 · 열 수 · 행 수뿐이다 (값 · 열 이름 · 토큰이 없다 · 모자이크 누계 L-05)
DERIVE_TRANSFORMS = ("bucket", "rank", "category")


def derive_record(home, job, transforms, rows, now=None):
    """파생 표본을 만들었다는 기록 한 건 -> 쓴 자리. transforms 는 {변환 종류: 열 수}. 꼴이 틀리거나 못 쓰면 예외 (만들지 않는다).

    파일 이름은 `<job>-<순번>-derive.json` - 보낸 것 (out) 이 아니라서 확정 목록 · job 상태에는 끼지 않는다.
    """
    if not isinstance(job, str) or not JOB_RE.match(job):
        raise AuditError("job 꼴")
    if not isinstance(transforms, dict) or set(transforms) - set(DERIVE_TRANSFORMS):
        raise AuditError("transforms 꼴")
    clean = {}
    for k in DERIVE_TRANSFORMS:
        v = transforms.get(k, 0)
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 8:
            raise AuditError("transforms 꼴")
        clean[k] = v
    if isinstance(rows, bool) or not isinstance(rows, int) or not 0 < rows <= 50:
        raise AuditError("rows 꼴")
    at = now or _now()
    rec = {"format": FORMAT, "at": at.isoformat(), "job": job, "direction": "derive", "kind": "derive",
           "transforms": clean, "columns": sum(clean.values()), "rows": rows}
    return write(home, rec)


def derived_rows(home, job):
    """그 job 의 파생 표본 누계 행 수 (모자이크 상한 L-05). 읽지 못한 기록은 건너뛴다 (읽기만 한다)."""
    total = 0
    for _, rec in _records(home, ("-derive.json",)):
        if rec.get("format") == FORMAT and rec.get("direction") == "derive" and rec.get("job") == job:
            r = rec.get("rows")
            if isinstance(r, int) and not isinstance(r, bool) and r > 0:
                total += r
    return total


def sink(home, transport="room", kind="report"):
    """허브의 audit(record: dict) 부품. 사전의 칸을 record 에 넘긴다 — 모르는 칸이 있으면 예외.

    [제안] 허브가 kind · transport 를 넘기지 않으면: dispatch 는 instruction · worker, 그 밖은 인자의 값.
    """
    allowed = ("job", "direction", "kind", "transport", "decision", "text", "sha256", "size", "checks",
               "model", "effort")

    def _sink(rec):
        if not isinstance(rec, dict) or set(rec) - set(allowed):
            raise AuditError("기록 칸")
        r = dict(rec)
        dispatch = r.get("direction") == "dispatch"
        r.setdefault("kind", "instruction" if dispatch else kind)
        r.setdefault("transport", "worker" if dispatch else transport)
        return record(home, **r)
    return _sink


# ---------------------------------------------------------------- 읽기

def _records(home, suffixes):
    """(파일 이름, 기록) 을 달 · 이름 차례로. 못 읽는 것은 건너뛴다 (읽기만 한다)."""
    base = os.path.join(home, AUDIT_DIR)
    if not os.path.isdir(base):
        return
    for month in sorted(os.listdir(base)):
        d = os.path.join(base, month)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(suffixes):
                continue
            try:
                with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                    rec = json.load(f)
            except Exception:
                continue
            if isinstance(rec, dict):
                yield fn, rec


def confirmed_hashes(home):
    """사람이 확정해 보낸 글 (direction out · decision sent) 의 sha256 집합.

    hook._confirmed_hashes 와 같은 뜻 · 같은 결과 (audit 아래 모든 달 폴더의 *-out.json · format 1 ·
    sha256 이 글자열인 것). 방 프로필이 outbox 읽기를 허락할 때 쓴다 (AL-13).
    """
    got = set()
    for _, rec in _records(home, ("-out.json",)):
        if rec.get("format") == 1 and rec.get("direction") == "out" and rec.get("decision") == "sent":
            h = rec.get("sha256")
            if isinstance(h, str):
                got.add(h)
    return got


JOB_STATES = ("sent", "working", "reported", "rejected")


def job_states(home, limit=20):
    """감사 기록에서 job 마다 마지막 상태 → [{"job", "state"}] (최근 limit 개 · 글 · 해시는 내주지 않는다).

    dispatch · sent → working · out · report · sent → reported · out · report · discarded → rejected.
    그 밖의 기록은 상태를 바꾸지 않는다. [제안] expired (24시간) 는 허브가 정한다 — 여기서는 내지 않는다.
    """
    events = []
    for fn, rec in _records(home, ("-out.json", "-dispatch.json")):
        if rec.get("format") != 1:
            continue
        job = rec.get("job")
        if not isinstance(job, str) or not JOB_RE.match(job):
            continue
        try:
            at = datetime.datetime.fromisoformat(str(rec.get("at"))).timestamp()
        except Exception:
            continue
        d, dec = rec.get("direction"), rec.get("decision")
        state = None
        if d == "dispatch" and dec == "sent":
            state = "working"
        elif d == "out" and rec.get("kind") == "report" and dec == "sent":
            state = "reported"
        elif d == "out" and rec.get("kind") == "report" and dec == "discarded":
            state = "rejected"
        if state:
            events.append((at, fn, job, state))
    events.sort()
    last = {}
    order = []
    for at, _, job, state in events:
        if job in last:
            order.remove(job)
        last[job] = state
        order.append(job)
    return [{"job": j, "state": last[j]} for j in order[-limit:]]
