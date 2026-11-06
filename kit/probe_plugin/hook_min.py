"""M0 키트 · 최소 훅 (KIT-2 리눅스판 · 표준 라이브러리).

모드는 세션의 프로젝트 폴더로 가른다: 방 · 원자료 폴더 · 그 밖.
- prompt: 사전 단어가 있으면 종료 코드 2 (사람에게만 보이는 까닭 · 단어는 쓰지 않는다 · AL-11).
- tool:   방에서는 방 밖 파일 도구 · Bash · WebFetch · 다른 MCP 를 deny. 원자료 폴더에서는 전부 deny.
          그 밖에서는 원자료 폴더를 건드리는 파일 도구를 deny.
- DIODE_PROBE_CRASH=1 이면 일부러 죽는다 (onFailure block 시험).
설정은 이 파일 옆의 probe_config.json (키트가 만든다 · 합성 값만).
기록은 DIODE_PROBE_OUT 아래 hooks.log — 사전 단어 · 파일 내용은 남기지 않는다.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILE_TOOLS = ("Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "NotebookEdit")


def load_config():
    with open(os.path.join(HERE, "probe_config.json"), encoding="utf-8") as f:
        return json.load(f)


def log(data):
    base = os.environ.get("DIODE_PROBE_OUT") or "."
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "hooks.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(data, t=round(time.time(), 3)), ensure_ascii=False) + "\n")


def norm(p):
    return os.path.normcase(os.path.realpath(p))


def inside(path, root):
    path, root = norm(path), norm(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def mode_of(project_dir, cfg):
    if any(inside(project_dir, r) for r in cfg["raw_dirs"]):
        return "raw"
    if inside(project_dir, cfg["room"]):
        return "room"
    return "other"


def paths_in(tool_input):
    out = []
    for k in ("file_path", "path", "notebook_path"):
        v = tool_input.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    return out


def deny(reason):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                        "permissionDecision": "deny",
                                                        "permissionDecisionReason": reason}}, ensure_ascii=False))
    return 0


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    crash = os.environ.get("DIODE_PROBE_CRASH", "")
    if crash and crash in ("1", event):
        raise SystemExit(1)  # 일부러 실패 — onFailure: block 이면 막혀야 한다
    data = json.loads(sys.stdin.read() or "{}")
    cfg = load_config()
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    mode = mode_of(project_dir, cfg)
    rec = {"event": event, "mode": mode, "project_dir_env": bool(os.environ.get("CLAUDE_PROJECT_DIR")),
           "cwd_field": bool(data.get("cwd")), "tool": data.get("tool_name", "")}

    if event == "session":
        log(dict(rec, decision="none"))
        return 0

    if event == "prompt":
        prompt = data.get("prompt") or ""
        hits = sum(1 for w in cfg["dictionary"] if w.lower() in prompt.lower())
        if mode == "raw":
            log(dict(rec, decision="block", why="raw"))
            sys.stderr.write("DIODE: 원자료 폴더에서 Claude 를 열었습니다 — 방에서 여세요\n")
            return 2
        if hits:
            log(dict(rec, decision="block", why="D2", hits=hits))
            sys.stderr.write("DIODE: 사전 단어 %d개 (D2) — 말 봉인 칸을 쓰세요\n" % hits)
            return 2
        log(dict(rec, decision="allow"))
        return 0

    if event == "tool":
        tool = data.get("tool_name") or ""
        ti = data.get("tool_input") or {}
        if mode == "raw":
            log(dict(rec, decision="deny", why="raw"))
            return deny("DIODE: 원자료 폴더 — 모든 도구를 막습니다")
        if mode == "room":
            if tool in FILE_TOOLS:
                ps = paths_in(ti) or [project_dir]
                if not all(inside(p if os.path.isabs(p) else os.path.join(project_dir, p), cfg["room"]) for p in ps):
                    log(dict(rec, decision="deny", why="room-outside"))
                    return deny("DIODE: 방 밖 (AL-06)")
            elif tool in ("Bash", "WebFetch") or (tool.startswith("mcp__") and "diode" not in tool):
                log(dict(rec, decision="deny", why="room-tool"))
                return deny("DIODE: 방에서 쓰지 않는 도구 (AL-06)")
        else:
            for p in paths_in(ti):
                full = p if os.path.isabs(p) else os.path.join(project_dir, p)
                if any(inside(full, r) for r in cfg["raw_dirs"]):
                    log(dict(rec, decision="deny", why="raw-path"))
                    return deny("DIODE: 원자료 폴더 (안전벨트)")
        log(dict(rec, decision="allow"))
        return 0

    log(dict(rec, decision="unknown-event"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
