"""M0 키트 · 가짜 Anthropic Messages API 서버 (표준 라이브러리 · 127.0.0.1 에만).

받은 요청을 <out>/NNN.json 에 그대로 남기고, 시나리오대로 답한다.
- 키 · 인증 헤더 값은 남기지 않는다 (길이만 · W-04).
- 시나리오 text: 늘 "OK" 한 마디.
- 시나리오 steps: 미리 적은 도구 호출을 차례로 시킨다 (지연 로딩 도구는 ToolSearch 를 먼저).
- 시나리오 tool: 요청의 도구 목록에서 --tool 이름 (끝이 같으면 됨) 을 찾아 한 번 부르게 하고,
  그 결과가 돌아오면 "done" 으로 끝낸다. 도구가 없으면 text 처럼.
Python 3.8 이상 · 의존 없음.
"""
import argparse
import http.server
import json
import os
import re
import sys
import threading

SECRET_HEADERS = ("x-api-key", "authorization", "proxy-authorization", "cookie")


class Box:
    lock = threading.Lock()
    n = 0
    out = "."
    scenario = "text"
    tool = ""
    tool_input = {}
    called = False
    steps = []      # 시나리오 steps: [{"tool": 이름 또는 "{변수}", "input": {...}}] · 변수는 vars 의 정규식으로 요청 글에서 찾는다
    step_i = 0
    vars = {}


def save(record):
    with Box.lock:
        Box.n += 1
        n = Box.n
    path = os.path.join(Box.out, "%03d.json" % n)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return n


def clean_headers(headers):
    out = {}
    for k, v in headers.items():
        if k.lower() in SECRET_HEADERS:
            out[k] = "설정됨 (%d자 · 값은 남기지 않음)" % len(v)
        else:
            out[k] = v
    return out


def last_has_tool_result(body):
    msgs = body.get("messages") or []
    if not msgs:
        return False
    c = msgs[-1].get("content")
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def pick_tool(body):
    if Box.scenario != "tool" or Box.called:
        return None
    for t in body.get("tools") or []:
        name = t.get("name", "") if isinstance(t, dict) else ""
        if name == Box.tool or name.endswith(Box.tool):
            return name
    return None


def resolve(value, text):
    """'{이름}' 을 vars 의 정규식으로 요청 글에서 찾은 값으로 바꾼다 (문자열 · 사전 · 목록 안까지)"""
    if isinstance(value, str):
        def sub(m):
            pat = Box.vars.get(m.group(1))
            found = re.search(pat, text) if pat else None
            return found.group(0) if found else m.group(0)
        return re.sub(r"\{(\w+)\}", sub, value)
    if isinstance(value, dict):
        return {k: resolve(v, text) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, text) for v in value]
    return value


def blocks_for(body):
    """돌려줄 content 블록과 stop_reason"""
    if Box.scenario == "steps":
        if body.get("tools") and Box.step_i < len(Box.steps):
            st = Box.steps[Box.step_i]
            Box.step_i += 1
            text = json.dumps(body, ensure_ascii=False)
            return [{"type": "tool_use", "id": "toolu_kit_%03d" % Box.n, "name": resolve(st["tool"], text),
                     "input": resolve(st.get("input", {}), text)}], "tool_use"
        return [{"type": "text", "text": "done"}], "end_turn"
    if last_has_tool_result(body):
        return [{"type": "text", "text": "done"}], "end_turn"
    name = pick_tool(body)
    if name:
        Box.called = True
        return [{"type": "tool_use", "id": "toolu_kit_%03d" % Box.n, "name": name, "input": Box.tool_input}], "tool_use"
    return [{"type": "text", "text": "OK"}], "end_turn"


def sse(event, data):
    return ("event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))).encode("utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 화면을 조용히 — 기록은 파일에
        pass

    def _send_json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        save({"method": "GET", "path": self.path, "headers": clean_headers(self.headers)})
        self._send_json(404, {"type": "error", "error": {"type": "not_found_error", "message": "kit"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            body = {"_unparsed_bytes": len(raw)}
        n = save({"method": "POST", "path": self.path, "headers": clean_headers(self.headers), "body": body})
        path = self.path.split("?")[0]
        if path.endswith("/count_tokens"):
            return self._send_json(200, {"input_tokens": 100})
        if not path.endswith("/v1/messages"):
            return self._send_json(404, {"type": "error", "error": {"type": "not_found_error", "message": "kit"}})
        model = body.get("model", "kit-model")
        content, stop = blocks_for(body)
        msg_id = "msg_kit_%03d" % n
        usage = {"input_tokens": 100, "output_tokens": 5}
        if not body.get("stream"):
            return self._send_json(200, {"id": msg_id, "type": "message", "role": "assistant", "model": model,
                                         "content": content, "stop_reason": stop, "stop_sequence": None, "usage": usage})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        w = self.wfile.write
        w(sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant",
                                                                      "model": model, "content": [], "stop_reason": None,
                                                                      "stop_sequence": None, "usage": usage}}))
        for i, b in enumerate(content):
            if b["type"] == "text":
                w(sse("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}))
                w(sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}}))
            else:
                w(sse("content_block_start", {"type": "content_block_start", "index": i,
                                              "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}}))
                w(sse("content_block_delta", {"type": "content_block_delta", "index": i,
                                              "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"], ensure_ascii=False)}}))
            w(sse("content_block_stop", {"type": "content_block_stop", "index": i}))
        w(sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 5}}))
        w(sse("message_stop", {"type": "message_stop"}))
        self.close_connection = True


def main(argv=None):
    ap = argparse.ArgumentParser(description="M0 키트 · 가짜 Anthropic 서버 (127.0.0.1)")
    ap.add_argument("--port", type=int, default=0, help="0 이면 빈 포트")
    ap.add_argument("--out", required=True, help="요청을 남길 폴더")
    ap.add_argument("--scenario", choices=["text", "tool", "steps"], default="text")
    ap.add_argument("--steps", default="[]", help="steps 시나리오의 단계 (JSON)")
    ap.add_argument("--vars", default="{}", help="steps 의 변수 정규식 (JSON)")
    ap.add_argument("--tool", default="", help="tool 시나리오에서 부르게 할 도구 이름 (끝이 같으면 됨)")
    ap.add_argument("--tool-input", default="{}", help="그 도구에 줄 입력 (JSON)")
    ap.add_argument("--port-file", default="", help="실제 포트를 적을 파일")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    Box.out, Box.scenario, Box.tool, Box.tool_input = a.out, a.scenario, a.tool, json.loads(a.tool_input)
    Box.steps, Box.vars, Box.step_i = json.loads(a.steps), json.loads(a.vars), 0
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    if a.port_file:
        with open(a.port_file, "w", encoding="utf-8") as f:
            f.write(str(srv.server_address[1]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
