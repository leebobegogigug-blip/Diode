"""KIT-2 재시험 — 진짜 Diode 훅 (저장소의 hooks/hooks.json · diode.py hook) 으로 (T12).

run_kit.py 와 같은 틀이다: 합성 자리 · 가짜 Anthropic 서버 (127.0.0.1) · 빈 환경의 Claude CLI.
다른 점: probe_plugin 대신 이 저장소 자체를 --plugin-dir 로 싣고, 방은 진짜 표지 · 방 설정 (SP-10) 으로,
데이터 폴더는 임시 HOME 아래의 기본 자리 (훅은 DIODE_HOME 을 받지 않는다) 에 합성 사전 · 설정을 둔다.

쓰는 법:  python run_hooks.py [--claude claude] [--only R06,R07] [--keep]
결과: out/hooks/report.json · 시나리오별 덤프. out/ 은 커밋하지 않는다.
Python 3.8 이상 · 의존 없음. 훅의 Python 명령은 hooks.json 대로 `python` — PATH 에 있어야 한다.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_kit as rk  # noqa: E402

ROOM_SETTINGS = {
    "autoMemoryEnabled": False,
    "claudeMdExcludes": ["**/CLAUDE.md", "**/.claude/CLAUDE.md", "**/AGENTS.md", "**/.claude/rules/**"],
    "permissions": {"defaultMode": "default", "blockReadsOutsideWorkingDirectories": True,
                    "deny": ["Bash", "WebFetch"]},
}


def make_room(room):
    p = os.path.join(room, ".claude", "settings.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(ROOM_SETTINGS, f, ensure_ascii=False, indent=1)
    with open(p, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(room, ".diode-room"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "created": "2026-11-05T00:00:00Z", "settings_sha256": sha}, f)
    os.makedirs(os.path.join(room, "work"), exist_ok=True)


def data_dir_of(home):
    if os.name == "nt":
        return os.path.join(home, "AppData", "Local", "diode")
    return os.path.join(home, ".local", "share", "diode")


def seed_data(home, lay):
    d = data_dir_of(home)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "dictionary.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "words": [rk.CANARY["dict_word"]]}, f)
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "policy": {"raw_dirs": [lay["raw"]]}}, f)


def broken_python_dir(work):
    """`python` 이 늘 실패하는 PATH 앞자리 (훅 고장 시험 · onFailure block)."""
    d = os.path.join(work, "badbin")
    os.makedirs(d, exist_ok=True)
    if os.name == "nt":
        with open(os.path.join(d, "python.cmd"), "w") as f:
            f.write("@exit /b 1\r\n")
    else:
        p = os.path.join(d, "python")
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return d


def scenarios(lay):
    secret = os.path.join(lay["raw"], "secret.txt")
    word = rk.CANARY["dict_word"]
    return [
        {"id": "R01", "what": "대조: 방 · 깨끗한 말 → 모델 요청이 간다", "cwd": "room", "prompt": "안녕", "expect": "requests"},
        {"id": "R06", "what": "방 · 사전 단어 (변형) → 막힘", "cwd": "room", "prompt": "이건 kit-word alpha 야",
         "expect": "none"},
        {"id": "R07", "what": "방 · 방 밖 (원자료) Read → deny", "cwd": "room", "prompt": "읽어", "server": "tool",
         "tool": "Read", "tool_input": {"file_path": secret}, "args": ["--allowedTools", "Read"], "expect": "deny"},
        {"id": "R08", "what": "방 · Bash → 막힘 (방 설정의 deny 가 도구 목록에서 먼저 뺀다 · 아니면 훅이 deny)", "cwd": "room",
         "prompt": "실행해", "server": "tool", "tool": "Bash",
         "tool_input": {"command": "cat '%s'" % secret, "description": "kit"}, "args": ["--allowedTools", "Bash"],
         "expect": "absent_or_deny"},
        {"id": "R09", "what": "훅이 죽음 (python 이 실패) → 막힘 (onFailure block)", "cwd": "room", "prompt": "안녕",
         "bad_python": True, "expect": "none"},
        {"id": "R10", "what": "원자료 폴더에서 연 세션 → 막힘", "cwd": "raw", "prompt": "안녕", "expect": "none"},
        {"id": "R11", "what": "보통 폴더 · 원자료 Read → deny (안전벨트)", "cwd": "other", "prompt": "읽어", "server": "tool",
         "tool": "Read", "tool_input": {"file_path": secret}, "args": ["--allowedTools", "Read"], "expect": "deny"},
        {"id": "R12", "what": "방 설정이 바뀜 (settings.local.json) → 막힘", "cwd": "room", "prompt": "안녕",
         "local_settings": True, "expect": "none"},
        {"id": "R13", "what": "방 · bypassPermissions 권한 모드 → 막힘", "cwd": "room", "prompt": "안녕",
         "args": ["--permission-mode", "bypassPermissions"], "expect": "none"},
        {"id": "R14", "what": "보통 폴더 · 원자료 폴더를 품은 위 폴더에서 연 세션 → 막힘", "cwd": "base", "prompt": "안녕",
         "expect": "none"},
        {"id": "R15", "what": "한계 기록: 설정 전 (데이터 폴더 없음) 보통 폴더 · 사전 단어 → 지나간다", "cwd": "other",
         "prompt": "이건 %s 야" % word, "no_data": True, "expect": "requests"},
    ]


def run_one(sc, a, work, lay):
    out = os.path.join(a.out, sc["id"])
    shutil.rmtree(out, ignore_errors=True)
    home = os.path.join(work, "home-" + sc["id"])
    os.makedirs(home, exist_ok=True)
    if not sc.get("no_data"):
        seed_data(home, lay)
    local = os.path.join(lay["room"], ".claude", "settings.local.json")
    if sc.get("local_settings"):
        with open(local, "w", encoding="utf-8") as f:
            json.dump({"permissions": {"allow": ["Bash"]}}, f)
    srv = rk.start_server(out, sc.get("server", "text"), sc.get("tool", ""), sc.get("tool_input", {}))
    extra = {}
    if sc.get("bad_python"):
        extra["PATH"] = broken_python_dir(work) + os.pathsep + os.environ.get("PATH", "")
    if os.name == "nt":
        extra["LOCALAPPDATA"] = os.path.join(home, "AppData", "Local")
    cmd = [a.claude, "-p", sc["prompt"], "--output-format", "json", "--model", rk.MODEL, "--plugin-dir", REPO]
    cmd += sc.get("args", [])
    env = rk.clean_env(home, srv.server_address[1], out, extra)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=lay[sc["cwd"]], env=env, capture_output=True, text=True, timeout=a.timeout)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        code, stdout, stderr = "timeout", e.stdout or "", e.stderr or ""
    finally:
        srv.shutdown()
        if os.path.exists(local):
            os.remove(local)
    res = rk.analyze(out, lay, sc)
    trs = json.dumps(res.get("tool_results"), ensure_ascii=False)
    n = res["messages_requests"]
    leaked = [k for k in ("raw_text", "raw_name") if k in res["found"]]
    if sc["expect"] == "none":
        ok = n == 0
    elif sc["expect"] == "deny":
        ok = "DIODE" in trs and not leaked
    elif sc["expect"] == "absent_or_deny":
        ok = not leaked and (sc["tool"] not in res["tools"] or "DIODE" in trs)
    else:
        ok = n > 0
    return {"id": sc["id"], "what": sc["what"], "expect": sc["expect"], "pass": bool(ok), "exit": code,
            "messages_requests": n, "leaked": leaked, "tool_offered": sc.get("tool", "") in res["tools"], "deny_reason_seen": "DIODE" in trs,
            "seconds": round(time.time() - t0, 1), "stderr_tail": (stderr or "")[-300:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", default="claude")
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args(argv)
    a.out = os.path.join(HERE, "out", "hooks")
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="diode-hooks-")
    try:
        lay = rk.build_layout(os.path.realpath(work))
        lay["base"] = lay["base"]
        make_room(lay["room"])
        only = set(x for x in a.only.split(",") if x)
        results = []
        for sc in scenarios(lay):
            if only and sc["id"] not in only:
                continue
            r = run_one(sc, a, work, lay)
            results.append(r)
            print("%s %-4s 요청 %d · %s" % (r["id"], "OK" if r["pass"] else "실패", r["messages_requests"], r["what"]))
        with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
        bad = [r["id"] for r in results if not r["pass"]]
        print("결과: OK" if not bad else "결과: 점검 실패 (%s)" % ", ".join(bad))
        return 0 if not bad else 1
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
