# -*- coding: utf-8 -*-
"""상태 명령 (SP-12) 과 statusline 기록 (SP-13) — 표준 라이브러리 · Python 3.8.

--status --json [--room 폴더]
  읽기 전용. 표준 출력에 UTF-8 JSON 하나 (format 1). 칸 · 값 범위는 Terminal-1 사내 작업 지침 › 04-5 의 계약.
  내주지 않는 것: 사전 단어 · 봉인 글 · 답 · 가명 표 · 감사 기록 내용 · 정규식 · 모델 이름.
  허브가 없는 지금은 jobs · queue 를 데이터 폴더 (감사 기록의 상태만) · 방 폴더 (파일 개수만) 에서 읽는다.

--statusline
  표준 입력 JSON 에서 정해진 칸만 읽는다 (session_id · model.id · effort.level · cost.total_cost_usd ·
  context_window.total_input_tokens · context_window.total_output_tokens). transcript_path 는 열지 않는다.
  usage/<YYYY-MM>/<session_id 의 sha256 앞 16자>.json 을 원자적으로 덮어쓴다 (마지막 누계).
  표준 출력은 한 줄: DIODE  room ok  effort high  month 12%. 실패해도 종료 코드 0 과 짧은 한 줄 (보안 경계가 아니다).
"""

import datetime
import hashlib
import json
import math
import os
import re
import socket
import tempfile

from .room import MARKER, default_data_dir, room_state

FORMAT = 1
OK, FAIL, USAGE = 0, 1, 2
EFFORTS = ("low", "medium", "high", "xhigh", "max", "auto")
JOB_FILE_RE = re.compile(r"^(J-[0-9]{4,6})\.md\Z")
USAGE_DIR = "usage"
MAX_PCT = 999
MAX_STDIN = 1048576              # statusline 입력 상한 [제안]
DEFAULT_ROOM = "D:\\claude\\room"          # SP-15 room.path 의 기본
DEFAULT_WORKER = "http://127.0.0.1:4096"    # SP-15 worker.url 의 기본
WORKER_ENV = "DIODE_WORKER_URL"            # SP-15 — 있으면 설정보다 앞선다 (Terminal-1)
WORKER_RE = re.compile(r"^http://127\.0\.0\.1:([0-9]{1,5})/?\Z")
PROBE_SEC = 0.3                  # 일꾼 연결 확인의 제한 시간 [제안]
FAIL_LINE = "DIODE  -"


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _config(home):
    """config.json → 사전. 없으면 {}. 꼴이 틀리면 예외."""
    path = os.path.join(home, "config.json")
    if not os.path.exists(path):
        return {}
    cfg = _read_json(path)
    if not isinstance(cfg, dict) or cfg.get("format") != 1:
        raise ValueError("설정 꼴")
    return cfg


def _section(cfg, name):
    v = cfg.get(name)
    return v if isinstance(v, dict) else {}


def _month_key(now=None):
    return (now or datetime.datetime.now()).strftime("%Y-%m")


def _budget(cfg):
    b = _section(cfg, "claude").get("monthly_budget_usd", 0)
    if isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or b <= 0:
        return 0
    return float(b)


def month_usage(home, month=None):
    """그 달 usage 파일들 → (비용 합, 읽은 개수, 못 읽은 개수, 마지막 effort)."""
    d = os.path.join(home, USAGE_DIR, month or _month_key())
    total, good, bad, last, last_m = 0.0, 0, 0, None, -1.0
    if not os.path.isdir(d):
        return total, good, bad, last
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(d, fn)
        try:
            rec = _read_json(p)
            cost = rec.get("cost_usd") if isinstance(rec, dict) else None
            if rec.get("format") != 1 or isinstance(cost, bool) or not isinstance(cost, (int, float)) \
                    or not math.isfinite(cost) or cost < 0:
                bad += 1
                continue
            total += float(cost)
            good += 1
            m = os.path.getmtime(p)
            if m > last_m and rec.get("effort") in EFFORTS:
                last, last_m = rec.get("effort"), m
        except Exception:
            bad += 1
    return total, good, bad, last


def _month(home, cfg):
    """{"pct", "estimated"} 또는 None (한도 없음). estimated: statusline 기록이 없거나 못 읽은 것이 있다."""
    b = _budget(cfg)
    if not b:
        return None
    total, good, bad, _ = month_usage(home)
    pct = int(round(total / b * 100))
    return {"pct": max(0, min(MAX_PCT, pct)), "estimated": bool(bad or not good)}


# ---------------------------------------------------------------- --status --json

def _worker(cfg, probe):
    url = os.environ.get(WORKER_ENV, "") or _section(cfg, "worker").get("url", DEFAULT_WORKER)
    m = WORKER_RE.match(url) if isinstance(url, str) else None
    if not m or not (0 < int(m.group(1)) < 65536):
        return {"set": False, "reachable": False}
    try:
        reach = bool(probe(int(m.group(1))))
    except Exception:
        reach = False
    return {"set": True, "reachable": reach}


def _probe(port):
    """127.0.0.1 의 그 포트가 연결을 받는가 (아무것도 보내지 않는다)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=PROBE_SEC)
    s.close()
    return True


def _room_files(folder, sub):
    d = os.path.join(folder, sub)
    if not os.path.isdir(d):
        return set()
    return set(m.group(1) for m in (JOB_FILE_RE.match(fn) for fn in os.listdir(d)) if m)


def _queue(folder, home, is_room):
    """outbox: 답 (inbox) 이 아직 없는 봉인 글 · inbox: 받아 들이지 않은 (감사 기록 in 이 없는) 답. 개수만."""
    if not is_room:
        return {"confirm": 0, "outbox": 0, "inbox": 0}
    out_jobs = _room_files(folder, "outbox")
    in_jobs = _room_files(folder, "inbox")
    taken = set()
    base = os.path.join(home, "audit")
    if os.path.isdir(base):
        for month in os.listdir(base):
            d = os.path.join(base, month)
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    m = re.match(r"^(J-[0-9]{4,6})-[0-9]+-in\.json\Z", fn)
                    if m:
                        taken.add(m.group(1))
    # [제안] confirm (확정 대기) 는 허브 프로세스만 안다 — 허브가 없는 지금은 0
    return {"confirm": 0, "outbox": len(out_jobs - in_jobs), "inbox": len(in_jobs - taken)}


def build_status(home, room_dir=None, home_is_default=True, probe=None):
    """상태 사전 (계약 04-5). 칸을 못 읽으면 그 칸을 막는 쪽 값으로 둔다."""
    from . import audit, hook
    from .room import overlaps
    try:
        cfg = _config(home)
    except Exception:
        cfg = None
    if room_dir is None:
        rp = _section(cfg or {}, "room").get("path", DEFAULT_ROOM)
        room_dir = rp if isinstance(rp, str) and rp else DEFAULT_ROOM
    settings = hook.load_settings(home)
    profile = room_state(room_dir)
    is_room = os.path.isfile(os.path.join(room_dir, MARKER))
    if profile == "ok":
        try:
            if any(overlaps(room_dir, r) for r in settings.raw_dirs):
                profile = "changed"     # 원자료 폴더와 겹치는 방은 훅도 막는다 (SP-11)
        except Exception:
            profile = "changed"
    if not is_room:
        profile = "missing"
    if not home_is_default or cfg is None or settings.state == "broken":
        belt = "unknown"                # 훅은 기본 자리만 본다 — 다른 자리의 설정으로 켜짐을 말하지 않는다
    elif settings.state == "ok" and settings.raw_dirs:
        belt = "on"
    else:
        belt = "off"
    out = {"format": FORMAT, "tool": "diode", "room": {"is_room": is_room, "profile": profile},
           "seatbelt": belt}
    out["worker"] = _worker(cfg or {}, probe or _probe)
    try:
        out["queue"] = _queue(room_dir, home, is_room)
    except Exception:
        pass
    try:
        out["jobs"] = [j for j in audit.job_states(home) if j["state"] in audit.JOB_STATES]
    except Exception:
        out["jobs"] = []
    if cfg is not None:
        try:
            m = _month(home, cfg)
            if m is not None:
                out["month"] = m
        except Exception:
            pass
    try:
        last = month_usage(home)[3]
        if last in EFFORTS:
            out["last"] = {"effort": last}
    except Exception:
        pass
    return out


def _parse_status_args(argv):
    """[--status] --json [--room 폴더] → 방 폴더 (없으면 None). 틀리면 ValueError."""
    args = list(argv)
    if args and args[0] == "--status":
        args = args[1:]
    room_dir, seen_json = None, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json" and not seen_json:
            seen_json = True
        elif a == "--room" and room_dir is None and i + 1 < len(args) and args[i + 1]:
            room_dir = args[i + 1]
            i += 1
        else:
            raise ValueError("인자")
        i += 1
    if not seen_json:
        raise ValueError("--json")
    return room_dir


def main_status(argv_list, out, home=None, home_is_default=None, probe=None, err=None):
    """diode.py --status --json [--room 폴더] → 종료 코드 (0 · 1 실패 · 2 사용법).

    home 이 없으면 기본 자리 (room.default_data_dir). 실패하면 JSON 을 쓰지 않는다 (부르는 쪽은 열지 않는다).
    """
    try:
        room_dir = _parse_status_args(argv_list)
    except ValueError:
        if err is not None:
            err.write("사용법 오류: diode.py --status --json [--room 폴더]\n")
        return USAGE
    if home is None:
        home = default_data_dir()
        if home_is_default is None:
            home_is_default = True
    if home_is_default is None:
        home_is_default = os.path.normcase(os.path.abspath(home)) == os.path.normcase(default_data_dir())
    try:
        st = build_status(home, room_dir, home_is_default=home_is_default, probe=probe)
        text = json.dumps(st, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        if err is not None:
            err.write("DIODE E-20 - 상태를 읽지 못했습니다\n")
        return FAIL
    out.write(text + "\n")
    return OK


# ---------------------------------------------------------------- --statusline

def _get(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        return None
    return v


def _count(v):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def read_statusline(data):
    """표준 입력 바이트 → 정해진 칸만 담은 사전 (transcript_path 등 다른 칸은 보지 않는다)."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_STDIN:
        return None
    obj = json.loads(bytes(data).decode("utf-8"))
    if not isinstance(obj, dict):
        return None
    sid = obj.get("session_id")
    model = _get(obj, "model", "id")
    effort = _get(obj, "effort", "level")
    return {
        "session_id": sid if isinstance(sid, str) and 0 < len(sid) <= 200 else None,
        "model": model if isinstance(model, str) and len(model) <= 200
        and not any(ch in model for ch in "\r\n\x00") else "",
        "effort": effort if effort in EFFORTS else "",
        "cost_usd": _num(_get(obj, "cost", "total_cost_usd")),
        "input_tokens": _count(_get(obj, "context_window", "total_input_tokens")),
        "output_tokens": _count(_get(obj, "context_window", "total_output_tokens")),
    }


def _write_replace(path, data):
    """원자적 덮어쓰기 (임시 파일 → 바꿔치기). 더 새 format 의 파일이면 덮어쓰지 않는다 (W-06)."""
    if os.path.exists(path):
        try:
            old = _read_json(path)
            if isinstance(old, dict) and isinstance(old.get("format"), int) and old["format"] > FORMAT:
                return False
        except Exception:
            pass
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".diode-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
        return True
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def record_usage(home, fields, now=None):
    """세션 하나의 마지막 누계를 usage 파일에 쓴다 → 쓴 자리 (session_id 가 없으면 None)."""
    if not fields or not fields.get("session_id"):
        return None
    now = now or datetime.datetime.now().astimezone().replace(microsecond=0)
    month = _month_key(now)
    name = hashlib.sha256(fields["session_id"].encode("utf-8")).hexdigest()[:16] + ".json"
    d = os.path.join(home, USAGE_DIR, month)
    os.makedirs(d, exist_ok=True)
    rec = {"format": FORMAT, "at": now.isoformat(), "month": month,
           "model": fields.get("model") or "", "effort": fields.get("effort") or "",
           "cost_usd": fields.get("cost_usd") or 0,
           "input_tokens": fields.get("input_tokens") or 0,
           "output_tokens": fields.get("output_tokens") or 0}
    path = os.path.join(d, name)
    data = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    return path if _write_replace(path, data) else None


def statusline_text(home, fields, room_dir):
    parts = ["DIODE", "room " + room_state(room_dir)]
    parts.append("effort " + ((fields or {}).get("effort") or "-"))
    try:
        cfg = _config(home)
    except Exception:
        cfg = {}
    m = _month(home, cfg) if cfg else None
    if m is not None:
        parts.append("month %s%d%%" % ("~" if m["estimated"] else "", m["pct"]))
    return "  ".join(parts)


def main_statusline(stdin_bytes, out, home, room_dir=None):
    """diode.py --statusline → 늘 0. 표준 출력에 한 줄 (실패하면 짧은 한 줄)."""
    try:
        fields = read_statusline(stdin_bytes)
        if fields is None:
            raise ValueError("입력 꼴")
        try:
            record_usage(home, fields)
        except Exception:
            pass                        # 기록을 못 해도 한 줄은 보인다
        line = statusline_text(home, fields, room_dir if room_dir is not None else os.getcwd())
    except Exception:
        line = FAIL_LINE
    try:
        out.write(line + "\n")
    except Exception:
        pass
    return OK
