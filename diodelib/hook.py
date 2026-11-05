# -*- coding: utf-8 -*-
"""Claude Code 훅 (SP-11) — 방 · 원자료 폴더 · 그 밖 세 모드 (표준 라이브러리 · Python 3.8).

플러그인 hooks/hooks.json 이 부른다: python diode.py hook <session|prompt|tool> (표준 입력 = 훅 입력 JSON).

모드 (프로젝트 폴더 = CLAUDE_PROJECT_DIR · 없으면 입력의 cwd)
  raw    원자료 폴더 (policy.raw_dirs) 와 겹친다 — 그 아래이거나, 그것을 품는다. 프롬프트 · 도구를 모두 막는다
  room   표지가 있는 방. 상태가 changed 면 raw 처럼 막는다
  other  그 밖 (안전벨트) — 사전 · 꼴에 걸리는 프롬프트, 원자료 폴더를 가리키는 도구를 막는다

출력 규칙 (AL-11)
  - 막은 까닭은 고정 문구 · 검사 번호 · 개수 · 줄 번호만. 사전 단어 · 경로 · 원자료 폴더 이름을 쓰지 않는다.
  - prompt: 막으면 종료 코드 2 + 표준 오류 (사람에게만 보인다). 통과면 아무것도 쓰지 않는다
    (표준 출력은 Claude 의 맥락에 붙으므로 쓰지 않는다).
  - tool: 막으면 표준 출력에 permissionDecision deny JSON (까닭은 Claude 가 본다). 통과면 아무것도 쓰지 않는다.
  - session: 알릴 것이 있으면 systemMessage JSON (사람에게 보인다) 만.
  - 이 모듈 안의 예외는 막는 쪽으로 끝난다. 모듈 밖의 고장은 hooks.json 의 onFailure: block 이 막는다.
"""

import json
import os
import re
import sys

from . import scan
from .room import default_data_dir, inside, is_protected, norm, overlaps, room_state, sha256_file

PROMPT_CHECKS = ("D2", "D3")
FILE_TOOLS = ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
# 방에서 쓸 수 있는 도구 (이 밖은 막는다 — 새 도구가 생겨도 막는 쪽)
ROOM_TOOLS = frozenset(FILE_TOOLS + (
    "WebSearch", "ToolSearch", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
    "Task", "Agent", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Skill"))
DIODE_MCP_PREFIX = "mcp__plugin_diode_"
# 방에서 받는 권한 모드. auto 는 요청에 HOME 경로 · 권한 규칙 · git 상태를 싣는다 [실험 T01 · T02]
ROOM_PERMISSION_MODES = frozenset(["default", "plan", "acceptEdits", "dontAsk"])

MSG = {
    "raw_prompt": "DIODE: 원자료 폴더에서 Claude 를 열었습니다 · 방에서 여세요",
    "raw_tool": "DIODE: 원자료 폴더 - 모든 도구를 막습니다",
    "changed": "DIODE: 방 설정이 바뀌었습니다 (changed) · 방 밖에서 /diode:room 을 다시 하세요",
    "auto": "DIODE: 방은 수동 권한 모드로 쓰세요 (auto 막음)",
    "room_outside": "DIODE: 방 밖 (AL-06)",
    "room_tool": "DIODE: 방에서 쓰지 않는 도구 (AL-06)",
    "room_protected": "DIODE: 방 설정 · 표지 · outbox 는 고치지 않습니다 (SP-10)",
    "outbox": "DIODE: 확정되지 않은 outbox (AL-13)",
    "belt_tool": "DIODE: 원자료 폴더 (안전벨트)",
    "e20": "DIODE E-20 - 사전 · 설정을 읽지 못해 막았습니다 · /diode:setup",
    "unset": "DIODE: 아직 설정하지 않았습니다 - 이 세션은 지켜지지 않습니다 · /diode:setup",
    "hint": " - 사내 말은 말 봉인 칸을 쓰세요",
}


# ---------------------------------------------------------------- 설정 읽기

class Settings(object):
    """훅이 쓰는 설정. state: "unset" (데이터 폴더에 사전 · 설정이 없음) · "ok" · "broken"."""

    def __init__(self, state, policy=None, raw_dirs=(), web_search=True, home=None):
        self.state = state
        self.policy = policy
        self.raw_dirs = tuple(raw_dirs)
        self.web_search = web_search
        self.home = home


def load_settings(home):
    dict_path = os.path.join(home, "dictionary.json")
    cfg_path = os.path.join(home, "config.json")
    if not os.path.exists(dict_path) and not os.path.exists(cfg_path):
        return Settings("unset", home=home)
    try:
        raw_dirs = []
        web_search = True
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict) or cfg.get("format") != 1:
                raise ValueError("설정 꼴")
            pol = cfg.get("policy") or {}
            raw_dirs = pol.get("raw_dirs", [])
            if not isinstance(raw_dirs, list) or not all(isinstance(x, str) and x for x in raw_dirs):
                raise ValueError("raw_dirs")
            web_search = pol.get("web_search", True) is not False
        policy = scan.policy_from_home(home)
        return Settings("ok", policy=policy, raw_dirs=raw_dirs, web_search=web_search, home=home)
    except Exception:
        return Settings("broken", home=home)


def mode_of(project_dir, settings):
    """("raw" | "room" | "other", 방 상태)."""
    for r in settings.raw_dirs:
        if overlaps(project_dir, r):
            return "raw", None
    st = room_state(project_dir)
    if st == "ok":
        return "room", st
    if st == "changed":
        return "raw", st
    return "other", None


# ---------------------------------------------------------------- 출력

def _deny(reason):
    return 0, json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}, ensure_ascii=False), ""


def _block(msg):
    return 2, "", msg + "\n"


ALLOW = (0, "", "")


# ---------------------------------------------------------------- 사건마다

def on_prompt(data, settings, project_dir):
    mode, st = mode_of(project_dir, settings)
    if mode == "raw":
        return _block(MSG["changed"] if st == "changed" else MSG["raw_prompt"])
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return _block(MSG["e20"])
    if mode == "room":
        pm = data.get("permission_mode")
        if pm is not None and pm not in ROOM_PERMISSION_MODES:
            return _block(MSG["auto"])
    if settings.state == "unset":
        if mode == "room":
            return _block(MSG["e20"])
        return ALLOW
    if settings.state != "ok":
        if prompt.lstrip().startswith("/diode:") and mode == "other":
            return ALLOW
        return _block(MSG["e20"])
    res = scan.check_text(prompt, settings.policy, PROMPT_CHECKS)
    if res.get("ok"):
        return ALLOW
    return _block(scan.format_line(res) + MSG["hint"])


def _tool_paths(tool, ti, cwd):
    """도구 입력에서 경로 (절대 경로로). 꼴이 수상하면 None (막음)."""
    out = []
    for k in ("file_path", "path", "notebook_path"):
        v = ti.get(k)
        if v is None:
            continue
        if not isinstance(v, str):
            return None
        if v:
            out.append(v if os.path.isabs(v) else os.path.join(cwd, v))
    # Glob · Grep 의 무늬로 방을 벗어나는 것 (../ · 절대 경로 · ~)
    for k in ("pattern", "glob"):
        if tool in ("Glob", "Grep") and k in ti:
            v = ti.get(k)
            if tool == "Grep" and k == "pattern":
                continue            # Grep 의 pattern 은 찾을 글 (경로가 아니다)
            if not isinstance(v, str):
                return None
            if ".." in v.replace("\\", "/").split("/") or os.path.isabs(v) or v.startswith("~") \
                    or re.match(r"^[A-Za-z]:", v) or v.startswith("\\\\"):
                return None
    if not out:
        out.append(cwd)
    return out


def _confirmed_hashes(home):
    """감사 기록 (SP-14) 에서 사람이 확정해 보낸 글 (direction out · decision sent) 의 sha256."""
    got = set()
    base = os.path.join(home, "audit")
    if not os.path.isdir(base):
        return got
    for month in sorted(os.listdir(base)):
        d = os.path.join(base, month)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith("-out.json"):
                continue
            try:
                with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                    rec = json.load(f)
                if rec.get("format") == 1 and rec.get("direction") == "out" and rec.get("decision") == "sent":
                    h = rec.get("sha256")
                    if isinstance(h, str):
                        got.add(h)
            except Exception:
                continue
    return got


def on_tool(data, settings, project_dir):
    mode, st = mode_of(project_dir, settings)
    if mode == "raw":
        return _deny(MSG["changed"] if st == "changed" else MSG["raw_tool"])
    tool = data.get("tool_name")
    ti = data.get("tool_input")
    if not isinstance(tool, str) or not isinstance(ti, dict):
        return _deny(MSG["e20"])
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) and data.get("cwd") else project_dir

    if mode == "room":
        if settings.state != "ok":
            return _deny(MSG["e20"])
        if tool.startswith(DIODE_MCP_PREFIX):
            return ALLOW
        if tool not in ROOM_TOOLS:
            return _deny(MSG["room_tool"])
        if tool == "WebSearch" and not settings.web_search:
            return _deny(MSG["room_tool"])
        if tool == "Skill":
            name = ti.get("skill") if isinstance(ti.get("skill"), str) else ti.get("name")
            if not isinstance(name, str) or not (name == "diode" or name.startswith("diode:")):
                return _deny(MSG["room_tool"])
            return ALLOW
        if tool in FILE_TOOLS:
            paths = _tool_paths(tool, ti, cwd)
            if paths is None:
                return _deny(MSG["room_outside"])
            for p in paths:
                if not inside(p, project_dir):
                    return _deny(MSG["room_outside"])
                if tool in WRITE_TOOLS and is_protected(p, project_dir):
                    return _deny(MSG["room_protected"])
                if tool != "Glob" and tool != "Grep" and inside(p, os.path.join(project_dir, "outbox")) \
                        and norm(p) != norm(os.path.join(project_dir, "outbox")):
                    if not os.path.isfile(p) or sha256_file(p) not in _confirmed_hashes(settings.home):
                        return _deny(MSG["outbox"])
                if tool == "Grep" and overlaps(p, os.path.join(project_dir, "outbox")):
                    return _deny(MSG["outbox"])     # Grep 은 내용을 읽는다 (Glob 은 이름만)
        return ALLOW

    # other — 안전벨트
    if not settings.raw_dirs:
        return ALLOW
    if tool in FILE_TOOLS:
        paths = _tool_paths(tool, ti, cwd)
        if paths is None:
            return _deny(MSG["belt_tool"])
        for p in paths:
            if any(overlaps(p, r) for r in settings.raw_dirs):
                return _deny(MSG["belt_tool"])
        return ALLOW
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            return _deny(MSG["belt_tool"])
        if _mentions_raw(cmd, settings.raw_dirs, cwd):
            return _deny(MSG["belt_tool"])
    return ALLOW


def _mentions_raw(cmd, raw_dirs, cwd):
    """셸 명령에 원자료 폴더 경로 (\\ · / 어느 쪽이든 · 대소문자 무시) 가 있는가. cwd 가 원자료 폴더면 참."""
    if any(overlaps(cwd, r) for r in raw_dirs):
        return True
    c = cmd.replace("\\", "/").lower()
    for r in raw_dirs:
        for form in set([os.path.abspath(r), norm(r)]):
            f = form.replace("\\", "/").lower().rstrip("/")
            if f and f in c:
                return True
    return False


def on_session(data, settings, project_dir):
    mode, st = mode_of(project_dir, settings)
    if st == "changed":
        return 0, json.dumps({"systemMessage": MSG["changed"]}, ensure_ascii=False), ""
    if mode == "raw":
        return 0, json.dumps({"systemMessage": MSG["raw_prompt"]}, ensure_ascii=False), ""
    if settings.state == "unset":
        return 0, json.dumps({"systemMessage": MSG["unset"]}, ensure_ascii=False), ""
    if settings.state != "ok":
        return 0, json.dumps({"systemMessage": MSG["e20"]}, ensure_ascii=False), ""
    return ALLOW


EVENTS = {"prompt": on_prompt, "tool": on_tool, "session": on_session}


def run(event, stdin_bytes, home=None, env=None):
    """(종료 코드, 표준 출력, 표준 오류). 예외는 막는 쪽으로 (prompt 2 · tool deny · session 알림)."""
    env = os.environ if env is None else env
    try:
        if event not in EVENTS:
            return 2, "", "DIODE: 모르는 훅 사건\n"
        data = json.loads(stdin_bytes.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("입력 꼴")
        project_dir = env.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        settings = load_settings(home or default_data_dir())
        return EVENTS[event](data, settings, project_dir)
    except Exception:
        if event == "tool":
            return _deny(MSG["e20"])
        if event == "session":
            return 0, json.dumps({"systemMessage": MSG["e20"]}, ensure_ascii=False), ""
        return _block(MSG["e20"])


def main(argv, stdin=None, stdout=None, stderr=None):
    stdin = stdin or getattr(sys.stdin, "buffer", sys.stdin)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    event = argv[0] if argv else ""
    data = stdin.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    code, out, err = run(event, data)
    if out:
        stdout.write(out)
    if err:
        stderr.write(err)
    return code
