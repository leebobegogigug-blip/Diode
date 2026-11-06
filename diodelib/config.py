# -*- coding: utf-8 -*-
"""데이터 폴더의 사전 · 설정을 읽고 쓴다 (SP-15 · W-06 · 표준 라이브러리 · Python 3.8).

- 사전 `dictionary.json` {"format": 1, "words": [...]} · 설정 `config.json` {"format": 1, "policy": {...}, ...}.
- 쓰기는 사람이 확정한 창 (policy_window) 만 부른다 (AL-12) — Claude 가 설정을 바꾸는 길은 없다.
  훅은 데이터 폴더를 가리키는 파일 도구 · 셸 명령을 막는다 (hook.py).
- 쓰기는 원자적 (임시 파일 → fsync → 바꿔치기). 깨진 파일은 `.broken` 으로 옮기고 새로 쓴다.
  더 새 format 이면 읽기만 하고 쓰지 않는다 (ConfigError).
- 우리가 모르는 칸 (llm · transport · 앞으로 생길 칸) 은 그대로 둔다.
- 결과 · 오류에는 단어 · 경로를 쓰지 않는다 — 코드 (짧은 글) 와 개수만 (AL-11).
"""

import json
import os
import re
import tempfile

from . import scan, worker
from .textnorm import dict_key

FORMAT = 1
MAX_WORDS = 5000
MAX_WORD_LEN = 80
MAX_LIST = 200
MAX_PATH_LEN = 300
_LIB_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}\Z")


class ConfigError(Exception):
    """코드만 (예: "newer" · "broken" · "words"). 사람에게는 코드 → 문구는 부르는 쪽이."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def config_path(home):
    return os.path.join(home, "config.json")


def dictionary_path(home):
    return os.path.join(home, "dictionary.json")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_atomic(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cfg-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _set_aside(path):
    """깨진 파일을 .broken 으로 옮긴다 (이미 있으면 번호). 옮긴 이름을 돌려준다."""
    n = 0
    while True:
        dst = path + ".broken" + ("" if n == 0 else str(n))
        if not os.path.exists(dst):
            os.replace(path, dst)
            return dst
        n += 1


def read_config(home):
    """설정 dict. 파일이 없으면 {"format": 1}. 깨졌거나 모르는 format 이면 ConfigError (broken · newer)."""
    p = config_path(home)
    if not os.path.exists(p):
        return {"format": FORMAT}
    try:
        cfg = _read_json(p)
    except Exception:
        raise ConfigError("broken")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("format"), int) or isinstance(cfg.get("format"), bool):
        raise ConfigError("broken")
    if cfg["format"] > FORMAT:
        raise ConfigError("newer")
    if cfg["format"] != FORMAT:
        raise ConfigError("broken")
    return cfg


def read_words(home):
    p = dictionary_path(home)
    if not os.path.exists(p):
        return []
    try:
        d = _read_json(p)
    except Exception:
        raise ConfigError("broken")
    if not isinstance(d, dict) or not isinstance(d.get("format"), int) or isinstance(d.get("format"), bool):
        raise ConfigError("broken")
    if d["format"] > FORMAT:
        raise ConfigError("newer")
    words = d.get("words")
    if d["format"] != FORMAT or not isinstance(words, list) or not all(isinstance(w, str) for w in words):
        raise ConfigError("broken")
    return list(words)


def _sub(cfg, name):
    v = cfg.get(name)
    return v if isinstance(v, dict) else {}


def load_state(home):
    """창이 보여 줄 현재 값 (안쪽 PC 안에서만 쓴다 — 단어 · 경로가 든다). 처음이면 기본값."""
    cfg = read_config(home)
    pol, wk, cl, rm = _sub(cfg, "policy"), _sub(cfg, "worker"), _sub(cfg, "claude"), _sub(cfg, "room")
    return {
        "words": read_words(home),
        "raw_dirs": list(pol.get("raw_dirs") or []),
        "inner_tools": list(pol.get("inner_tools") or []),
        "lib_allow": list(pol.get("lib_allow") or []),
        "patterns": list(pol.get("patterns") or []),
        "web_search": pol.get("web_search", True) is not False,
        "real_data": pol.get("real_data") is True,
        "worker_command": list(wk["command"]) if isinstance(wk.get("command"), list) else None,
        "worker_cwd": wk.get("cwd") if isinstance(wk.get("cwd"), str) else None,
        "monthly_budget_usd": cl.get("monthly_budget_usd", 0) if isinstance(cl.get("monthly_budget_usd", 0), (int, float))
        and not isinstance(cl.get("monthly_budget_usd", 0), bool) else 0,
        "room_path": rm.get("path") if isinstance(rm.get("path"), str) else None,
        "llm": cfg.get("llm") if isinstance(cfg.get("llm"), dict) else None,
    }


def _is_abs(p):
    return os.path.isabs(p) or bool(re.match(r"^[A-Za-z]:[\\/]", p)) or p.startswith("\\\\")


def _strs(v, name, limit=MAX_LIST, each=MAX_PATH_LEN):
    if not isinstance(v, list) or len(v) > limit:
        raise ConfigError(name)
    out = []
    for x in v:
        if not isinstance(x, str):
            raise ConfigError(name)
        x = x.strip()
        if not x:
            continue
        if len(x) > each or "\x00" in x or "\n" in x or "\r" in x:
            raise ConfigError(name)
        out.append(x)
    return out


def validate_state(state):
    """창에서 온 값 → (정리한 값, 경고 코드 목록). 못 쓰는 값이면 ConfigError(영역 코드).

    경고: "short" (사전 항목 중 N(w) 가 두 글자 미만이라 쓰이지 않음) · "raw_missing" (없는 원자료 폴더) ·
    "words_empty" · "raw_empty" (비면 seal 을 막는다).
    """
    if not isinstance(state, dict):
        raise ConfigError("state")
    warn = []
    words, seen, short = [], set(), 0
    raw_words = state.get("words", [])
    if not isinstance(raw_words, list) or len(raw_words) > MAX_WORDS * 2:
        raise ConfigError("words")
    for w in raw_words:
        if not isinstance(w, str):
            raise ConfigError("words")
        w = " ".join(w.split())
        if not w:
            continue
        if len(w) > MAX_WORD_LEN or "\x00" in w:
            raise ConfigError("words")
        k = dict_key(w)
        if len(k) < 2:
            short += 1
            continue
        if k in seen:
            continue
        seen.add(k)
        words.append(w)
    if len(words) > MAX_WORDS:
        raise ConfigError("words")
    if short:
        warn.append("short")
    if not words:
        warn.append("words_empty")

    raw_dirs = _strs(state.get("raw_dirs", []), "raw_dirs")
    for p in raw_dirs:
        if not _is_abs(p):
            raise ConfigError("raw_dirs")
        if not os.path.isdir(p):
            warn.append("raw_missing")
    if not raw_dirs:
        warn.append("raw_empty")

    inner = sorted(set(x.lower() for x in _strs(state.get("inner_tools", []), "inner_tools", each=60)))
    lib = _strs(state.get("lib_allow", []), "lib_allow", each=64)
    if not all(_LIB_NAME.match(x) for x in lib):
        raise ConfigError("lib_allow")
    patterns = _strs(state.get("patterns", []), "patterns", limit=50, each=300)
    for p in patterns:
        try:
            re.compile(p)
        except re.error:
            raise ConfigError("patterns")

    ws, rd = state.get("web_search", True), state.get("real_data", False)
    if not isinstance(ws, bool) or not isinstance(rd, bool):
        raise ConfigError("flags")
    budget = state.get("monthly_budget_usd", 0)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not (0 <= budget <= 100000):
        raise ConfigError("budget")

    cmd = state.get("worker_command")
    cwd = state.get("worker_cwd")
    if cmd is not None:
        try:
            worker.load_command({"worker": {"command": cmd, "cwd": cwd}})
        except worker.WorkerConfigError:
            raise ConfigError("worker")
    elif cwd is not None:
        raise ConfigError("worker")

    room_path = state.get("room_path")
    if room_path is not None and (not isinstance(room_path, str) or not room_path.strip() or not _is_abs(room_path.strip())
                                  or len(room_path) > MAX_PATH_LEN):
        raise ConfigError("room_path")

    llm = state.get("llm")
    if llm is not None:
        if not isinstance(llm, dict):
            raise ConfigError("llm")
        try:
            from . import judge
            judge._settings(llm)
        except ConfigError:
            raise
        except Exception:
            raise ConfigError("llm")

    clean = {"words": words, "raw_dirs": raw_dirs, "inner_tools": inner, "lib_allow": lib, "patterns": patterns,
             "web_search": ws, "real_data": rd, "monthly_budget_usd": budget, "worker_command": cmd, "worker_cwd": cwd,
             "room_path": room_path.strip() if room_path else None, "llm": llm}
    return clean, sorted(set(warn))


def apply_state(home, state):
    """검증하고 사전 · 설정을 원자적으로 쓴다 → (개수 dict, 경고 코드). 사람이 확정한 창만 부른다 (AL-12)."""
    clean, warn = validate_state(state)
    try:
        cfg = read_config(home)
    except ConfigError as e:
        if e.code == "newer":
            raise
        cfg = {"format": FORMAT}
        if os.path.exists(config_path(home)):
            _set_aside(config_path(home))
    try:
        read_words(home)
    except ConfigError as e:
        if e.code == "newer":
            raise
        if os.path.exists(dictionary_path(home)):
            _set_aside(dictionary_path(home))
    cfg["format"] = FORMAT
    pol = dict(_sub(cfg, "policy"))
    pol.update({"raw_dirs": clean["raw_dirs"], "inner_tools": clean["inner_tools"], "lib_allow": clean["lib_allow"],
                "patterns": clean["patterns"], "web_search": clean["web_search"], "real_data": clean["real_data"]})
    cfg["policy"] = pol
    cl = dict(_sub(cfg, "claude"))
    cl["monthly_budget_usd"] = clean["monthly_budget_usd"]
    cfg["claude"] = cl
    wk = dict(_sub(cfg, "worker"))
    if clean["worker_command"] is None:
        wk.pop("command", None)
        wk.pop("cwd", None)
    else:
        wk["command"] = clean["worker_command"]
        if clean["worker_cwd"] is None:
            wk.pop("cwd", None)
        else:
            wk["cwd"] = clean["worker_cwd"]
    if wk:
        cfg["worker"] = wk
    else:
        cfg.pop("worker", None)
    rm = dict(_sub(cfg, "room"))
    if clean["room_path"]:
        rm["path"] = clean["room_path"]
    else:
        rm.pop("path", None)
    if rm:
        cfg["room"] = rm
    else:
        cfg.pop("room", None)
    if clean["llm"] is not None:
        cfg["llm"] = clean["llm"]
    # 사전을 먼저 (훅이 설정만 있고 사전이 없는 틈에 막는 쪽으로 읽는다)
    _write_atomic(dictionary_path(home), {"format": FORMAT, "words": clean["words"]})
    _write_atomic(config_path(home), cfg)
    return counts(home), warn


def counts(home):
    """사람 · Claude 에게 보여도 되는 개수와 켜짐 여부 (단어 · 경로 · 이름 없음). 읽지 못하면 {"error": 코드}."""
    try:
        st = load_state(home)
    except ConfigError as e:
        return {"error": e.code}
    except Exception:
        return {"error": "read"}
    return {"dictionary": len(st["words"]), "raw_dirs": len(st["raw_dirs"]), "inner_tools": len(st["inner_tools"]),
            "lib_allow": len(st["lib_allow"]), "patterns": len(st["patterns"]), "web_search": st["web_search"],
            "real_data": st["real_data"], "worker": st["worker_command"] is not None, "llm": st["llm"] is not None,
            "room_path": st["room_path"] is not None}


def ready(home):
    """seal 을 쓸 수 있나: 사전이 비지 않고 원자료 폴더 목록이 비지 않았나 (AL-12). (참거짓, 모자란 것 코드 목록)."""
    c = counts(home)
    if "error" in c:
        return False, [c["error"]]
    missing = []
    if not c["dictionary"]:
        missing.append("words_empty")
    if not c["raw_dirs"]:
        missing.append("raw_empty")
    return (not missing), missing


def policy_ok(home):
    """scan.policy_from_home 이 읽을 수 있는 상태인가 (예외 없이)."""
    try:
        scan.policy_from_home(home)
        return True
    except Exception:
        return False
