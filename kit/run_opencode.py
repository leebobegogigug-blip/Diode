"""진짜 opencode 와 이어 보는 시험 (T13 · 선택) — 가짜 로컬 모델 · 격리된 설정 · 합성 글만.

하는 일 (밖으로 나가는 요청은 없다 — 모델은 127.0.0.1 의 가짜 OpenAI 호환 서버, 설정 · 데이터 · 캐시는 임시 폴더):
  R1  일꾼 부품 (diodelib.worker.CommandWorker) 이 진짜 `opencode run` 을 띄우고 지시가 모델에 닿는다
  R2  opencode 의 셸 권한을 "propose 만 허락 · 나머지 거절" 로 두면 propose 는 돌고 (보고가 대기열에 들어간다),
      허락하지 않은 명령은 돌지 않는다

쓰는 법:  python run_opencode.py [--opencode <실행 파일>]      (기본 `opencode` · PATH)
  opencode 는 `npm install --prefix <폴더> opencode-ai` 로 받을 수 있다. 판이 오르면 다시 돌려 본다.
확인한 판: 1.19.5 — `opencode run [message..]` · 권한 규칙은 나중에 적은 것이 이긴다 (`*` 를 앞에) ·
  `--dir` 을 주지 않으면 셸이 일꾼의 작업 폴더 밖에서 돈다 (그래서 worker.command 에 `--dir {cwd}`).
`--auto` (권한 자동 승인) 는 쓰지 않는다.
Python 3.8 이상 · 의존 없음 (opencode 가 처음 돌 때 공급자 꾸러미를 npm 에서 받는다).
"""
import argparse
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from diodelib import worker  # noqa: E402

DIODE = os.path.join(ROOT, "diode.py")


class FakeModel(object):
    """도구 결과를 받으면 끝, 도구 목록이 있고 아직 결과가 없으면 정해진 셸 명령을 부르는 가짜 모델."""

    def __init__(self, command=None):
        self.command = command
        self.requests = []
        self.tool_results = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append(req)
                msgs = req.get("messages", [])
                done = any(m.get("role") == "tool" for m in msgs)
                for m in msgs:
                    if m.get("role") == "tool":
                        outer.tool_results.append(str(m.get("content")))
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()

                def ch(delta, fin=None, usage=None):
                    o = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "m",
                         "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
                    if usage:
                        o["usage"] = usage
                    self.wfile.write(("data: " + json.dumps(o) + "\n\n").encode())
                    self.wfile.flush()
                usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
                if outer.command and req.get("tools") and not done:
                    ch({"role": "assistant", "content": None, "tool_calls": [{
                        "index": 0, "id": "call_1", "type": "function",
                        "function": {"name": "bash", "arguments": json.dumps(
                            {"command": outer.command, "description": "propose"})}}]})
                    ch({}, "tool_calls", usage)
                else:
                    ch({"role": "assistant", "content": ""})
                    ch({"content": "끝"})
                    ch({}, "stop", usage)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]


def isolate(tmp, port, permission=None):
    """opencode 가 이 PC 의 설정 · 로그인 · 기록을 건드리지 않게 환경을 격리한다. 돌려주는 것: 이전 환경 (복구용)."""
    cfg = {"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
           "provider": {"fake": {"npm": "@ai-sdk/openai-compatible", "name": "fake",
                                 "options": {"baseURL": "http://127.0.0.1:%d/v1" % port, "apiKey": "x"},
                                 "models": {"m": {"name": "m", "tool_call": True,
                                                  "limit": {"context": 32000, "output": 4000}}}}},
           "model": "fake/m", "small_model": "fake/m"}
    if permission:
        cfg["permission"] = permission
    env = {"HOME": tmp, "USERPROFILE": tmp, "XDG_CONFIG_HOME": tmp + "/cfg", "XDG_DATA_HOME": tmp + "/xdgdata",
           "XDG_CACHE_HOME": tmp + "/cache", "XDG_STATE_HOME": tmp + "/state",
           "OPENCODE_CONFIG_CONTENT": json.dumps(cfg), "OPENCODE_DISABLE_AUTOUPDATE": "true",
           "NO_PROXY": "127.0.0.1,localhost"}
    saved = {k: os.environ.get(k) for k in list(env) + ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]}
    os.environ.update(env)
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        os.environ.pop(k, None)
    return saved


def restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def wait(proc, secs=120):
    t0 = time.time()
    while proc.poll() is None and time.time() - t0 < secs:
        time.sleep(0.3)
    return proc.poll()


def r1(oc):
    tmp = tempfile.mkdtemp(prefix="oc-r1-")
    model = FakeModel()
    saved = isolate(tmp, model.port)
    try:
        home, room = os.path.join(tmp, "dhome"), os.path.join(tmp, "room")
        os.makedirs(os.path.join(room, "work"))
        os.makedirs(home)
        w = worker.CommandWorker([oc, "run", "-m", "fake/m", "--dir", "{cwd}", "{prompt}"], home, room)
        ok = w.check() and w.send("J-0001", "[diode J-0001]\n[지시]\n목록 화면의 정렬을 바꿔 줘\n[/지시]\n", [])
        code = wait(w.children[-1]) if ok else None
        arrived = any("정렬을 바꿔 줘" in json.dumps(r, ensure_ascii=False) for r in model.requests)
        silent = w.children[-1].stdout is None and w.children[-1].stderr is None if ok else False
        return code == 0 and arrived and silent, "종료 %s · 지시가 모델에 닿음 %s · 출력 파이프 없음 %s" % (code, arrived, silent)
    finally:
        restore(saved)
        shutil.rmtree(tmp, ignore_errors=True)


def r2(oc, allowed):
    tmp = tempfile.mkdtemp(prefix="oc-r2-")
    data = os.path.join(tmp, ".local", "share", "diode")
    os.makedirs(data)
    with open(os.path.join(data, "dictionary.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)
    marker = os.path.join(tmp, "MARKER")
    py = os.path.basename(sys.executable) if os.path.basename(sys.executable) in ("python", "python3") else "python3"
    cmd = ("%s %s propose report.json" % (py, DIODE)) if allowed else ("touch %s" % marker)
    model = FakeModel(cmd)
    permission = {"bash": {"*": "deny", "python3 */diode.py propose *": "allow", "python */diode.py propose *": "allow"},
                  "edit": "deny", "webfetch": "deny"}
    saved = isolate(tmp, model.port, permission)
    try:
        room, home = os.path.join(tmp, "room"), os.path.join(tmp, "dhome")
        os.makedirs(os.path.join(room, "work"))
        os.makedirs(home)
        with open(os.path.join(room, "work", "report.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0001",
                       "status": "done", "summary": ["화면을 만들었다"]}, f, ensure_ascii=False)
        w = worker.CommandWorker([oc, "run", "-m", "fake/m", "--dir", "{cwd}", "{prompt}"], home, room)
        ok = w.send("J-0001", "[diode J-0001]\n보고를 내라", ["report.json"])
        code = wait(w.children[-1]) if ok else None
        q = os.path.join(data, "queue")
        queued = sorted(os.listdir(q)) if os.path.isdir(q) else []
        ran = os.path.exists(marker)
        if allowed:
            return code == 0 and len(queued) == 1, "종료 %s · 대기열 %d개 (1개여야)" % (code, len(queued))
        return code == 0 and not ran and not queued, "종료 %s · 거절돼야 할 명령이 돌았나 %s · 대기열 %d개 (0이어야)" % (code, ran, len(queued))
    finally:
        restore(saved)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--opencode", default="opencode")
    a = ap.parse_args(argv)
    oc = shutil.which(a.opencode) or (a.opencode if os.path.isfile(a.opencode) else None)
    if not oc:
        print("opencode 를 찾지 못했다 (--opencode <경로>) — 시험을 건너뛴다")
        print("결과: 확인 필요")
        return 3
    results = [("R1 일꾼 부품이 진짜 opencode 를 띄운다", r1(oc)),
               ("R2a 허락한 명령 (propose) 은 돈다", r2(oc, True)),
               ("R2b 허락하지 않은 명령은 돌지 않는다", r2(oc, False))]
    bad = 0
    for name, (ok, why) in results:
        print("%s %-4s %s" % (name.split(" ")[0], "OK" if ok else "실패", name.split(" ", 1)[1] + " — " + why))
        bad += 0 if ok else 1
    print("결과: OK" if not bad else "결과: 점검 실패")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
