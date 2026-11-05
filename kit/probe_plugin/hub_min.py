"""M0 키트 · 최소 MCP 허브 (표준 입출력 JSON-RPC · 표준 라이브러리 · 포트 없음).

확인할 것 (KIT-7): 플러그인의 .mcp.json 으로 자동으로 뜨는가 · 어떤 환경 변수가 오는가 ·
도구 결과가 모델 요청에 어떤 모양으로 실리는가. 지시 글은 기록만 하고 어디에도 보내지 않는다.
기록은 DIODE_PROBE_OUT (없으면 CLAUDE_PLUGIN_DATA) 아래 hub.log — 환경 변수는 이름과 '있음/없음' 만 남긴다.
"""
import json
import os
import sys
import time

WATCH_ENV = ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR", "DIODE_WORKER_URL",
             "DIODE_PROBE_OUT", "OPENCODE_SERVER_PASSWORD", "HOME", "CLAUDE_CONFIG_DIR")

TOOLS = [
    {"name": "dispatch", "description": "Hand a task to the inside worker. Returns only sent and job.",
     "inputSchema": {"type": "object", "properties": {"instruction": {"type": "string"}},
                     "required": ["instruction"], "additionalProperties": False}},
    {"name": "inbox", "description": "Return confirmed sealed reports only.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def log_path():
    base = os.environ.get("DIODE_PROBE_OUT") or os.environ.get("CLAUDE_PLUGIN_DATA") or "."
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "hub.log")


def log(kind, data):
    with open(log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "kind": kind, "data": data}, ensure_ascii=False) + "\n")


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def call_tool(name, args):
    if name == "dispatch":
        # 안쪽으로 가는 지시 — 이 키트에서는 기록만 (실제 허브는 확정 창 · 토큰 되돌림 · 일꾼에 넣기)
        log("dispatch", {"instruction_chars": len(str(args.get("instruction", ""))), "instruction": args.get("instruction", "")})
        return {"content": [{"type": "text", "text": json.dumps({"sent": True, "job": "J-0001"})}]}
    if name == "inbox":
        return {"content": [{"type": "text", "text": "[sealed J-0001] status=done · changed_files=3 · tests_passed=12 · PH_K7Q2 screen ready"}]}
    return {"content": [{"type": "text", "text": json.dumps({"error": "E-TOOL"})}], "isError": True}


def main():
    log("start", {"env": {k: ("있음" if os.environ.get(k) else "없음") for k in WATCH_ENV},
                  "project_dir": os.environ.get("CLAUDE_PROJECT_DIR", ""), "cwd": os.getcwd(), "argv": sys.argv[1:],
                  "python": sys.version.split()[0]})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            log("bad_json", {"chars": len(line)})
            continue
        method, mid = msg.get("method"), msg.get("id")
        log("rpc", {"method": method})
        if mid is None:  # 알림 — 답하지 않는다
            continue
        if method == "initialize":
            pv = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
            reply(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                        "serverInfo": {"name": "diode-probe", "version": "0.0.1"}})
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            p = msg.get("params") or {}
            reply(mid, call_tool(p.get("name"), p.get("arguments") or {}))
        elif method == "ping":
            reply(mid, {})
        else:
            reply(mid, error={"code": -32601, "message": "method not found"})
    log("stop", {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
