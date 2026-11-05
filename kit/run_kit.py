"""M0 키트 · 돌리기 (KIT-1 바이트 · KIT-2 훅 · KIT-7 허브) — Linux 와 사내 Windows 에서 같은 스크립트.

하는 일
1. 임시 폴더에 합성 자리를 만든다 — D:\\claude 를 흉내 낸 claude/ (diode/ · room/) · 원자료 폴더 raw/ · 보통 폴더 other/.
   곳곳에 카나리아 (지어낸 문자열) 를 심는다.
2. 시나리오마다 가짜 Anthropic 서버 (127.0.0.1) 를 띄우고, 빈 환경 (허용 목록) 의 claude CLI 를 그쪽으로 붙여 돌린다.
   진짜 Anthropic 으로는 아무것도 가지 않는다. 이 PC 의 Claude 설정 · 기록도 건드리지 않는다 (임시 HOME · CLAUDE_CONFIG_DIR).
3. 받은 요청에서 카나리아 · 경로 · 사용자 이름 · 도구 목록 · 도구 결과를 찾아 out/report.json · report.md 에 쓴다.

쓰는 법:  python run_kit.py [--claude claude] [--python python3] [--only S01,S05] [--keep]
결과 폴더 out/ 는 커밋하지 않는다 (Claude Code 의 시스템 프롬프트 원문이 들어 있다 · .gitignore).
Python 3.8 이상 · 의존 없음.
"""
import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_anthropic as fa  # noqa: E402

CANARY = {
    "parent_md": "KIT_PARENT_MD_CANARY_7Q2",      # claude/CLAUDE.md — 방 위 폴더의 안내 파일
    "source_md": "KIT_SOURCE_MD_CANARY_3X8",      # claude/diode/AGENTS.md — 플러그인 소스
    "sibling_name": "KIT_SIBLING_NAME_CANARY_5W",  # claude/ 의 파일 이름
    "raw_text": "KIT_RAW_TEXT_CANARY_9Z1",        # raw/secret.txt 의 내용
    "raw_name": "KIT_RAW_NAME_CANARY_4M",          # raw/ 의 파일 이름
    "git_branch": "kit-branch-canary-6p",          # claude/ 를 git 저장소로 만든 판의 가지 이름
    "dict_word": "KITWORDALPHA",                   # 사전 단어 (사람이 친 말에 넣는다)
    "outbox": "PH_K7Q2",                           # 방 outbox 의 봉인 글 토큰
    "user_md": "KIT_USER_MD_CANARY_2H",            # 사용자 범위 ~/.claude/CLAUDE.md
}
MODEL = "claude-opus-5"


# ─────────────────────────────────────────────── 자리
def build_layout(base):
    claude = os.path.join(base, "claude")
    room = os.path.join(claude, "room")
    src = os.path.join(claude, "diode")
    raw = os.path.join(base, "raw")
    other = os.path.join(base, "other")
    for d in (room, os.path.join(room, "outbox"), os.path.join(room, "inbox"), src, raw, other):
        os.makedirs(d, exist_ok=True)
    w = lambda p, s: open(p, "w", encoding="utf-8").write(s)
    w(os.path.join(claude, "CLAUDE.md"), "# parent\n%s\n" % CANARY["parent_md"])
    w(os.path.join(claude, CANARY["sibling_name"] + ".txt"), "x\n")
    w(os.path.join(src, "AGENTS.md"), "# source\n%s\n" % CANARY["source_md"])
    w(os.path.join(room, ".diode-room"), "format=1\n")
    w(os.path.join(room, "outbox", "J-0001.md"), "[sealed J-0001] %s: 화면 하나 · 항목 둘\n" % CANARY["outbox"])
    w(os.path.join(raw, "secret.txt"), "%s\n" % CANARY["raw_text"])
    w(os.path.join(raw, CANARY["raw_name"] + ".txt"), "y\n")
    w(os.path.join(other, "note.txt"), "z\n")
    return {"base": base, "claude": claude, "room": room, "src": src, "raw": raw, "other": other}


def git_init(path, branch):
    run = lambda *a: subprocess.run(["git", "-C", path] + list(a), capture_output=True, text=True)
    run("init", "-q", "-b", branch)
    run("-c", "user.email=kit@example.com", "-c", "user.name=kit", "add", "-A")
    run("-c", "user.email=kit@example.com", "-c", "user.name=kit", "commit", "-q", "-m", "kit")


def git_remove(path):
    shutil.rmtree(os.path.join(path, ".git"), ignore_errors=True)


def make_plugin(work, lay, python_cmd):
    """probe_plugin 을 복사하고 probe_config.json 을 쓴다. Windows 에서는 python 명령 이름을 바꾼다"""
    dst = os.path.join(work, "probe_plugin")
    shutil.copytree(os.path.join(HERE, "probe_plugin"), dst)
    cfg = {"room": lay["room"], "raw_dirs": [lay["raw"]], "dictionary": [CANARY["dict_word"]]}
    with open(os.path.join(dst, "probe_config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    for rel in ("hooks/hooks.json", ".mcp.json"):
        p = os.path.join(dst, rel)
        s = open(p, encoding="utf-8").read().replace('"command": "python3"', '"command": %s' % json.dumps(python_cmd))
        open(p, "w", encoding="utf-8").write(s)
    return dst


# ─────────────────────────────────────────────── 실행
KEEP_ENV = ("PATH", "LANG", "LC_ALL", "TERM", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "DISPLAY")


def clean_env(home, port, out, extra):
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update({
        "HOME": home, "USERPROFILE": home, "CLAUDE_CONFIG_DIR": os.path.join(home, ".claude"),
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % port, "ANTHROPIC_API_KEY": "sk-kit-fake-000",
        "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "DIODE_PROBE_OUT": out,
    })
    env.update(extra or {})
    return env


def start_server(out, scenario, tool, tool_input, steps=None, vars_=None):
    fa.Box.n, fa.Box.called, fa.Box.step_i = 0, False, 0
    fa.Box.out, fa.Box.scenario, fa.Box.tool, fa.Box.tool_input = out, scenario, tool, tool_input
    fa.Box.steps, fa.Box.vars = steps or [], vars_ or {}
    os.makedirs(out, exist_ok=True)
    srv = fa.http.server.ThreadingHTTPServer(("127.0.0.1", 0), fa.Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


def run_scenario(sc, a, work, lay, plugin):
    out = os.path.join(a.out, sc["id"])
    shutil.rmtree(out, ignore_errors=True)
    home = os.path.join(work, "home-" + sc["id"])
    os.makedirs(home, exist_ok=True)
    srv = start_server(out, sc.get("server", "text"), sc.get("tool", ""), sc.get("tool_input", {}),
                       sc.get("steps"), sc.get("vars"))
    room_settings = os.path.join(lay["room"], ".claude", "settings.json")
    if sc.get("room_settings") is not None:
        os.makedirs(os.path.dirname(room_settings), exist_ok=True)
        with open(room_settings, "w", encoding="utf-8") as f:
            json.dump(sc["room_settings"], f, ensure_ascii=False, indent=1)
    if sc.get("user_md"):
        os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
        with open(os.path.join(home, ".claude", "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# user\n%s\n" % CANARY["user_md"])
    port = srv.server_address[1]
    cmd = [a.claude, "-p", sc["prompt"], "--output-format", "json", "--model", sc.get("model", MODEL)]
    if sc.get("plugin"):
        cmd += ["--plugin-dir", plugin]
    cmd += sc.get("args", [])
    env = clean_env(home, port, out, sc.get("env"))
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=lay[sc["cwd"]], env=env, capture_output=True, text=True, timeout=a.timeout)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        code, stdout, stderr = "timeout", e.stdout or "", e.stderr or ""
    finally:
        srv.shutdown()
        if os.path.exists(room_settings):
            os.remove(room_settings)
    res = {"id": sc["id"], "what": sc["what"], "exit": code, "seconds": round(time.time() - t0, 1),
           "stdout_tail": (stdout or "")[-600:], "stderr_tail": (stderr or "")[-600:]}
    res.update(analyze(out, lay, sc))
    return res


# ─────────────────────────────────────────────── 보기
def load_dumps(out):
    ds = []
    for name in sorted(os.listdir(out)) if os.path.isdir(out) else []:
        if name.endswith(".json") and name[:3].isdigit():
            with open(os.path.join(out, name), encoding="utf-8") as f:
                ds.append(json.load(f))
    return ds


def text_of(obj):
    return json.dumps(obj, ensure_ascii=False)


def where(body, needle):
    hits = []
    for part in ("system", "tools", "messages", "metadata"):
        if needle and needle in text_of(body.get(part, "")):
            hits.append(part)
    rest = {k: v for k, v in body.items() if k not in ("system", "tools", "messages", "metadata")}
    if needle and needle in text_of(rest):
        hits.append("other")
    return hits


def tool_results(body):
    out = []
    for m in body.get("messages") or []:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append(b.get("content"))
    return out


def analyze(out, lay, sc):
    dumps = load_dumps(out)
    msgs = [d for d in dumps if d.get("method") == "POST" and d.get("path", "").split("?")[0].endswith("/v1/messages")]
    other_paths = sorted({d.get("path", "") for d in dumps if d not in msgs})
    needles = dict(CANARY)
    needles.update({"room_path": lay["room"], "base_path": lay["base"], "home_dir": "home-" + sc["id"],
                    "username": getpass.getuser(), "hostname": socket.gethostname()})
    found = {}
    for k, v in needles.items():
        places = sorted({p for d in msgs for p in where(d.get("body", {}), v)})
        if places:
            found[k] = places
    main = [d for d in msgs if (d.get("body") or {}).get("tools")]
    first = (main or msgs or [{}])[0].get("body", {}) if (main or msgs) else {}
    tools = [t.get("name") for t in first.get("tools") or [] if isinstance(t, dict)]
    sysblocks = first.get("system")
    sys_chars = len(text_of(sysblocks)) if sysblocks else 0
    hdrs = sorted((main or msgs or [{}])[0].get("headers", {}).keys()) if (main or msgs) else []
    beta = (main or msgs or [{}])[0].get("headers", {}).get("anthropic-beta", "") if (main or msgs) else ""
    knobs = {k: first.get(k) for k in ("model", "max_tokens", "thinking", "output_config", "stream") if k in first}
    knobs["metadata_keys"] = sorted((first.get("metadata") or {}).keys())
    trs = [tr for d in msgs for tr in tool_results(d.get("body", {}))]
    logs = {}
    for name in ("hooks.log", "hub.log"):
        p = os.path.join(out, name)
        if os.path.exists(p):
            logs[name] = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    return {"requests_total": len(dumps), "messages_requests": len(msgs), "other_paths": other_paths,
            "found": found, "tools": tools, "mcp_tools": [t for t in tools if t and t.startswith("mcp__")],
            "system_chars": sys_chars, "header_names": hdrs, "anthropic_beta": beta, "knobs": knobs,
            "tool_results": trs[:4], "logs": logs}


# ─────────────────────────────────────────────── 시나리오
def scenarios(lay):
    secret = os.path.join(lay["raw"], "secret.txt")
    room_file = os.path.join(lay["room"], "outbox", "J-0001.md")
    return [
        {"id": "S01", "what": "KIT-1 방 · 플러그인 없음 · 위 폴더에 CLAUDE.md", "cwd": "room", "prompt": "안녕"},
        {"id": "S02", "what": "KIT-1 방 · 위 폴더가 git 저장소", "cwd": "room", "prompt": "안녕", "git": True},
        {"id": "S03", "what": "KIT-1 effort low (--effort) · 모델 이름 [1m]", "cwd": "room", "prompt": "안녕",
         "model": MODEL + "[1m]", "args": ["--effort", "low"]},
        {"id": "S04", "what": "KIT-7 플러그인 · 허브가 뜨는가 · 도구 목록 · 환경 변수", "cwd": "room", "prompt": "안녕",
         "plugin": True, "env": {"DIODE_WORKER_URL": "http://127.0.0.1:4096"}},
        {"id": "S05", "what": "KIT-7 ToolSearch → dispatch → inbox · 결과가 모델에 어떻게 실리나", "cwd": "room", "prompt": "일을 넘겨",
         "plugin": True, "server": "steps", "vars": {"dispatch": r"mcp__plugin_[\w\-]+__dispatch", "inbox": r"mcp__plugin_[\w\-]+__inbox"},
         "steps": [{"tool": "ToolSearch", "input": {"query": "select:{dispatch},{inbox}", "max_results": 2}},
                   {"tool": "{dispatch}", "input": {"instruction": "PH_K7Q2 화면을 만들어"}},
                   {"tool": "{inbox}", "input": {}}],
         "args": ["--allowedTools", "mcp__plugin_diode-probe_hub__dispatch mcp__plugin_diode-probe_hub__inbox"]},
        {"id": "S06", "what": "KIT-2 사람이 친 말에 사전 단어 → 막힘", "cwd": "room",
         "prompt": "이건 %s 이야" % CANARY["dict_word"], "plugin": True},
        {"id": "S07", "what": "KIT-2 방에서 방 밖 (원자료) Read → deny", "cwd": "room", "prompt": "읽어",
         "plugin": True, "server": "tool", "tool": "Read", "tool_input": {"file_path": secret}, "args": ["--allowedTools", "Read"]},
        {"id": "S08", "what": "KIT-2 방에서 Bash → deny", "cwd": "room", "prompt": "실행해",
         "plugin": True, "server": "tool", "tool": "Bash", "tool_input": {"command": "cat '%s'" % secret, "description": "kit"},
         "args": ["--allowedTools", "Bash"]},
        {"id": "S09", "what": "KIT-2 PreToolUse 훅이 죽으면 (onFailure block) → 막힘", "cwd": "room", "prompt": "읽어",
         "plugin": True, "server": "tool", "tool": "Read", "tool_input": {"file_path": room_file},
         "args": ["--allowedTools", "Read"], "env": {"DIODE_PROBE_CRASH": "tool"}},
        {"id": "S10", "what": "KIT-2 원자료 폴더에서 연 세션 → 프롬프트 막힘", "cwd": "raw", "prompt": "안녕", "plugin": True},
        {"id": "S11", "what": "KIT-2 보통 폴더에서 원자료 Read → deny (안전벨트)", "cwd": "other", "prompt": "읽어",
         "plugin": True, "server": "tool", "tool": "Read", "tool_input": {"file_path": secret}, "args": ["--allowedTools", "Read"]},
        {"id": "S12", "what": "대조: 플러그인 없이 보통 폴더에서 원자료 Read → 그대로 읽힘 (안전벨트가 없을 때)", "cwd": "other",
         "prompt": "읽어", "server": "tool", "tool": "Read", "tool_input": {"file_path": secret}, "args": ["--allowedTools", "Read"]},
        {"id": "S13", "what": "KIT-1 방 설정 autoMemoryEnabled false → 메모리 경로 (HOME) 가 빠지나", "cwd": "room", "prompt": "안녕",
         "room_settings": {"autoMemoryEnabled": False}},
        {"id": "S14", "what": "KIT-1 방 설정 claudeMdExcludes → 위 폴더 · 사용자 CLAUDE.md 가 빠지나", "cwd": "room", "prompt": "안녕",
         "user_md": True, "room_settings": {"autoMemoryEnabled": False,
                                             "claudeMdExcludes": ["**/CLAUDE.md", "**/.claude/CLAUDE.md", "**/AGENTS.md", "**/.claude/rules/**"]}},
        {"id": "S15", "what": "대조: 사용자 CLAUDE.md 가 방 세션에 실리나 (빼는 설정 없음)", "cwd": "room", "prompt": "안녕", "user_md": True},
        {"id": "S17", "what": "KIT-1 방 설정 effortLevel medium → 요청의 effort", "cwd": "room", "prompt": "안녕",
         "room_settings": {"effortLevel": "medium"}},
        {"id": "S18", "what": "KIT-7 허브 (MCP 자식) 가 tkinter 창을 띄우는가 · Python 3.8 로 훅 · 허브 (DISPLAY 필요)", "cwd": "room",
         "prompt": "일을 넘겨", "plugin": True, "server": "steps",
         "vars": {"dispatch": r"mcp__plugin_[\w\-]+__dispatch"},
         "steps": [{"tool": "ToolSearch", "input": {"query": "select:{dispatch}", "max_results": 1}},
                   {"tool": "{dispatch}", "input": {"instruction": "PH_K7Q2 화면을 만들어"}}],
         "args": ["--allowedTools", "mcp__plugin_diode-probe_hub__dispatch"], "env": {"DIODE_PROBE_TK": "1"}, "needs_display": True},
        {"id": "S16", "what": "KIT-2 권한 층: 방 설정 blockReadsOutsideWorkingDirectories · 플러그인 없이 방 밖 Read", "cwd": "room",
         "prompt": "읽어", "server": "tool", "tool": "Read", "tool_input": {"file_path": secret}, "args": ["--allowedTools", "Read"],
         "room_settings": {"permissions": {"blockReadsOutsideWorkingDirectories": True}}},
    ]


def report_md(results):
    lines = ["# M0 키트 결과 (자동 · %s)" % time.strftime("%Y-%m-%d %H:%M"), "",
             "| # | 무엇 | 종료 | 모델 요청 | 찾은 카나리아 · 정보 (어디서) | MCP 도구 | 도구 결과 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        found = " · ".join("%s(%s)" % (k, ",".join(v)) for k, v in r["found"].items()) or "없음"
        trs = " / ".join(text_of(x)[:80] for x in r["tool_results"]) or "—"
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (r["id"], r["what"], r["exit"], r["messages_requests"],
                                                             found, ", ".join(r["mcp_tools"]) or "—", trs.replace("|", "/")))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="M0 키트 (KIT-1 · KIT-2 · KIT-7) — 합성 자료 · 가짜 서버")
    ap.add_argument("--claude", default="claude", help="Claude CLI 명령")
    ap.add_argument("--python", default="python3" if os.name != "nt" else "python", help="훅 · 허브를 돌릴 Python 명령")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--only", default="", help="S01,S05 처럼 일부만")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--keep", action="store_true", help="임시 자리를 지우지 않는다")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="diode-kit-")
    lay = build_layout(os.path.join(work, "base"))
    plugin = make_plugin(work, lay, a.python)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    results = []
    try:
        for sc in scenarios(lay):
            if only and sc["id"] not in only:
                continue
            if sc.get("needs_display") and not os.environ.get("DISPLAY") and os.name != "nt":
                print("%s 건너뜀 — DISPLAY 없음 (Xvfb 를 띄우고 DISPLAY 를 주면 돈다)" % sc["id"])
                continue
            if sc.get("git"):
                git_init(lay["claude"], CANARY["git_branch"])
            r = run_scenario(sc, a, work, lay, plugin)
            if sc.get("git"):
                git_remove(lay["claude"])
            results.append(r)
            print("%s exit=%s msgs=%s found=%s mcp=%s" % (r["id"], r["exit"], r["messages_requests"],
                                                         ",".join(r["found"]) or "-", ",".join(r["mcp_tools"]) or "-"))
    finally:
        prev = {}
        rp = os.path.join(a.out, "report.json")
        if os.path.exists(rp):  # --only 로 일부만 돌려도 앞의 결과를 지우지 않는다
            try:
                prev = {r["id"]: r for r in json.load(open(rp, encoding="utf-8")).get("results", [])}
            except (OSError, ValueError, KeyError):
                prev = {}
        prev.update({r["id"]: r for r in results})
        results = [prev[k] for k in sorted(prev)]
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"layout": lay, "results": results}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
            f.write(report_md(results))
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
