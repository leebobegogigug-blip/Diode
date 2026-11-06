"""M0 키트 · 대화형 (TUI) 세션 한 번 — 리눅스 · macOS 의 의사 터미널 (표준 라이브러리 pty).

print 모드 (run_kit.py) 와 무엇이 다른지 본다: 시스템 프롬프트 · 환경 칸 · statusLine 이 받는 JSON 칸 이름.
방 설정에 statusLine 을 걸어, Claude Code 가 statusLine 명령에 주는 JSON 의 칸 이름 (값은 남기지 않음) 을 기록한다.
Windows 에는 pty 가 없다 — 사내에서는 손으로 같은 절차를 밟는다 (README).
쓰는 법:  python run_tui.py [--claude claude]
"""
import argparse
import json
import os
import pty
import re
import select
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_kit as rk  # noqa: E402

STATUSLINE = r'''import json, os, sys
d = json.load(sys.stdin)
def keys(o, p=""):
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            out.append(p + k)
            out += keys(v, p + k + ".")
    return out
with open(os.path.join(os.environ["DIODE_PROBE_OUT"], "statusline.json"), "w", encoding="utf-8") as f:
    json.dump({"keys": keys(d), "effort": (d.get("effort") or {}).get("level"), "has_cost": "cost" in d}, f)
print("DIODE room")
'''


def drive(cmd, cwd, env, steps, timeout=90):
    """steps: [(기다릴 정규식, 보낼 글)] — 화면 글은 ANSI 를 지우고 본다"""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe(cmd[0], cmd, env)
    buf, log = "", []
    t_end = time.time() + timeout
    i = 0
    while time.time() < t_end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                data = os.read(fd, 65536).decode("utf-8", "replace")
            except OSError:
                break
            buf += re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]", "", data)
        if i < len(steps) and re.search(steps[i][0], buf):
            log.append("matched %r" % steps[i][0])
            time.sleep(0.8)
            os.write(fd, steps[i][1].encode("utf-8"))
            buf = ""
            i += 1
        if i >= len(steps):
            time.sleep(3)
            break
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    return i, log, buf[-800:]


def main(argv=None):
    ap = argparse.ArgumentParser(description="M0 키트 · 대화형 세션 한 번 (pty)")
    ap.add_argument("--claude", default="claude")
    ap.add_argument("--python", default="python3")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--id", default="T01")
    ap.add_argument("--settings-extra", default="{}", help="방 설정에 더할 JSON (시험용)")
    a = ap.parse_args(argv)
    work = tempfile.mkdtemp(prefix="diode-tui-")
    lay = rk.build_layout(os.path.join(work, "base"))
    out = os.path.join(a.out, a.id)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    home = os.path.join(work, "home")
    cfg_dir = os.path.join(home, ".claude")
    os.makedirs(cfg_dir)
    sl = os.path.join(work, "statusline.py")
    open(sl, "w", encoding="utf-8").write(STATUSLINE)
    os.makedirs(os.path.join(lay["room"], ".claude"), exist_ok=True)
    settings = {"statusLine": {"type": "command", "command": "%s %s" % (a.python, sl)},
                "autoMemoryEnabled": False,
                "claudeMdExcludes": ["**/CLAUDE.md", "**/.claude/CLAUDE.md", "**/AGENTS.md", "**/.claude/rules/**"],
                "effortLevel": "medium"}
    settings.update(json.loads(a.settings_extra))
    with open(os.path.join(lay["room"], ".claude", "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=1)
    key = "sk-kit-fake-000"
    # 처음 실행의 안내 · 폴더 신뢰 · 키 승인을 미리 채운다 (합성 설정 · 임시 폴더에만)
    with open(os.path.join(cfg_dir, ".claude.json"), "w", encoding="utf-8") as f:
        json.dump({"hasCompletedOnboarding": True, "theme": "dark",
                   "customApiKeyResponses": {"approved": [key[-20:]], "rejected": []},
                   "projects": {lay["room"]: {"hasTrustDialogAccepted": True}}}, f)
    srv = rk.start_server(out, "text", "", {})
    env = rk.clean_env(home, srv.server_address[1], out, {"TERM": "xterm-256color"})
    try:
        n, log, tail = drive([a.claude], lay["room"], env,
                             [(r"(>|│|\? for shortcuts|Try)", "안녕\r"), (r"OK", "/exit\r")])
    finally:
        srv.shutdown()
    res = {"steps_done": n, "log": log, "screen_tail": tail}
    res.update(rk.analyze(out, lay, {"id": "home"}))
    slp = os.path.join(out, "statusline.json")
    res["statusline"] = json.load(open(slp, encoding="utf-8")) if os.path.exists(slp) else None
    bodies = [d.get("body", {}) for d in rk.load_dumps(out) if isinstance(d.get("body"), dict)]
    sg = [b.get("safeguards") for b in bodies if b.get("safeguards")]
    ctx = (sg[0][0].get("classifier_context") if sg and isinstance(sg[0], list) and sg[0] else {}) or {}
    res["safeguards"] = {"present": bool(sg), "permission_mode": ctx.get("permission_mode"),
                         "keys": sorted(ctx.keys()), "home_dir_sent": bool(ctx.get("home_dir")),
                         "rule_canary_sent": any("KIT_RULE_CANARY_8R" in json.dumps(b, ensure_ascii=False) for b in bodies)}
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("steps_done", "messages_requests", "found", "safeguards")}, ensure_ascii=False))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
