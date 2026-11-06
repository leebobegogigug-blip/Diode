"""진짜 opencode 와 이어 보는 시험 (T13 · 선택) — 가짜 로컬 모델 · 격리된 설정 · 합성 글만.

하는 일 (밖으로 나가는 요청은 없다 — 모델은 127.0.0.1 의 가짜 OpenAI 호환 서버, 설정 · 데이터 · 캐시는 임시 폴더):
  R1  일꾼 부품 (diodelib.worker.CommandWorker) 이 진짜 `opencode run` 을 띄우고 지시가 모델에 닿는다
  R2  opencode 의 셸 권한을 "propose 만 허락 · 나머지 거절" 로 두면 propose 는 돌고 (보고가 대기열에 들어간다),
      허락하지 않은 명령은 돌지 않는다
  R5  (Windows 의 .cmd 껍데기일 때만) 일꾼 부품이 `{prompt}` 인자를 거절하고, 표준 입력으로 준 글의 & | ^ % ! " 가
      명령이 되지 않고 모델에 그대로 닿는다

쓰는 법:  python run_opencode.py [--opencode <실행 파일>]      (기본 `opencode` · PATH)
  opencode 는 `npm install --prefix <폴더> opencode-ai` 로 받을 수 있다. 판이 오르면 다시 돌려 본다.
확인한 판: 1.19.5 — `opencode run [message..]` · 권한 규칙은 나중에 적은 것이 이긴다 (`*` 를 앞에) ·
  `--dir` 을 주지 않으면 셸이 일꾼의 작업 폴더 밖에서 돈다 (그래서 worker.command 에 `--dir {cwd}`).
`--auto` (권한 자동 승인) 는 쓰지 않는다.
Windows: npm 으로 깐 opencode 는 `.cmd` 껍데기다 — 이 시험은 껍데기면 `{prompt}` 대신 표준 입력으로 지시를 준다 (일꾼 부품이
껍데기에 `{prompt}` 를 거절하기 때문 · 사내도 같은 길이다). 데이터 폴더는 LOCALAPPDATA 를 임시 폴더로 옮겨 이 PC 의 것을 건드리지 않는다.
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
SHIM_EXT = (".cmd", ".bat")


def is_shim(oc):
    return os.name == "nt" and oc.lower().endswith(SHIM_EXT)


def data_dir(tmp):
    """propose 가 보고를 쓰는 diode 데이터 폴더 (isolate 가 LOCALAPPDATA 를 옮긴 뒤의 자리)"""
    if os.name == "nt":
        return os.path.join(tmp, "AppData", "Local", "diode")
    return os.path.join(tmp, ".local", "share", "diode")


def py_name():
    """opencode 의 셸 규칙 (python3 *diode.py propose *) 과 맞는 파이썬 이름"""
    return "python" if os.name == "nt" else "python3"


def fwd(path):
    """셸 명령 글에 쓸 경로 - 역슬래시는 셸이 먹는다 (Windows 도 슬래시를 받는다)"""
    return path.replace("\\", "/")


def worker_cmd(oc, extra=()):
    """일꾼 명령 목록 - 껍데기(.cmd)면 {prompt} 를 빼고 표준 입력으로 (일꾼 부품이 껍데기의 {prompt} 를 거절한다)"""
    cmd = [oc, "run", "-m", "fake/m", "--dir", "{cwd}"] + list(extra)
    return cmd if is_shim(oc) else cmd + ["{prompt}"]


class FakeModel(object):
    """도구 결과를 받으면 끝, 도구 목록이 있고 아직 결과가 없으면 정해진 셸 명령을 부르는 가짜 모델."""

    def __init__(self, command=None, tool="bash", tool_args=None):
        self.command = command
        self.tool = tool
        self.tool_args = tool_args
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
                if (outer.command or outer.tool_args) and req.get("tools") and not done:
                    args = outer.tool_args if outer.tool_args is not None else {"command": outer.command, "description": "propose"}
                    ch({"role": "assistant", "content": None, "tool_calls": [{
                        "index": 0, "id": "call_1", "type": "function",
                        "function": {"name": outer.tool, "arguments": json.dumps(args)}}]})
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


AGENT = "diode-worker"


def mark_cmd():
    """허락 안 한 명령의 대역 - 셸 종류와 무관하게 작업 폴더에 표지 파일을 만든다 (touch 는 cmd · PowerShell 에 없다)"""
    return '%s -c "open(\'marker-inside.txt\',\'w\').close()"' % py_name()


def agent_config(permission):
    """일꾼 전용 에이전트 하나에만 권한을 준다 — 전역 설정은 평소 쓰던 대로 (허락) 둔다."""
    return {"description": "Diode 일꾼 - propose 만 셸로 · 작업 폴더 밖에는 쓰지 않는다", "mode": "primary", "permission": permission}


def isolate(tmp, port, permission=None, agent=None):
    """opencode 가 이 PC 의 설정 · 로그인 · 기록을 건드리지 않게 환경을 격리한다. 돌려주는 것: 이전 환경 (복구용)."""
    cfg = {"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
           "provider": {"fake": {"npm": "@ai-sdk/openai-compatible", "name": "fake",
                                 "options": {"baseURL": "http://127.0.0.1:%d/v1" % port, "apiKey": "x"},
                                 "models": {"m": {"name": "m", "tool_call": True,
                                                  "limit": {"context": 32000, "output": 4000}}}}},
           "model": "fake/m", "small_model": "fake/m"}
    if permission:
        cfg["permission"] = permission
    if agent:
        cfg["agent"] = {AGENT: agent}
    env = {"HOME": tmp, "USERPROFILE": tmp, "XDG_CONFIG_HOME": tmp + "/cfg", "XDG_DATA_HOME": tmp + "/xdgdata",
           "XDG_CACHE_HOME": tmp + "/cache", "XDG_STATE_HOME": tmp + "/state",
           "OPENCODE_CONFIG_CONTENT": json.dumps(cfg), "OPENCODE_DISABLE_AUTOUPDATE": "true",
           "NO_PROXY": "127.0.0.1,localhost"}
    if os.name == "nt":
        env["LOCALAPPDATA"] = os.path.join(tmp, "AppData", "Local")
        env["APPDATA"] = os.path.join(tmp, "AppData", "Roaming")
        os.makedirs(env["LOCALAPPDATA"], exist_ok=True)
        os.makedirs(env["APPDATA"], exist_ok=True)
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
        w = worker.CommandWorker(worker_cmd(oc), home, room)
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
    data = data_dir(tmp)
    os.makedirs(data)
    with open(os.path.join(data, "dictionary.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)
    # 표지는 일꾼의 작업 폴더 **안** 에 둔다 — 작업 폴더 밖 경로라서 막힌 것 (external_directory) 과 bash 규칙이 막은 것을 구별한다
    marker = os.path.join(tmp, "dhome", "work", "J-0001", "marker-inside.txt")
    cmd = ("%s %s propose report.json" % (py_name(), fwd(DIODE))) if allowed else mark_cmd()
    model = FakeModel(cmd)
    permission = {"bash": {"*": "deny", "python3 *diode.py propose *": "allow", "python *diode.py propose *": "allow"},
                  "edit": "deny", "webfetch": "deny"}
    saved = isolate(tmp, model.port, permission)
    try:
        room, home = os.path.join(tmp, "room"), os.path.join(tmp, "dhome")
        os.makedirs(os.path.join(room, "work"))
        os.makedirs(home)
        with open(os.path.join(room, "work", "report.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0001",
                       "status": "done", "summary": ["화면을 만들었다"]}, f, ensure_ascii=False)
        w = worker.CommandWorker(worker_cmd(oc), home, room)
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


def r3(oc, inside):
    """일꾼이 방으로 새는 길 — `write` 로 작업 폴더 안 (허락) 과 밖 (거절) 에 파일을 쓰게 해 본다.

    권한: edit 허락 · external_directory 거절 (프로젝트 폴더 밖은 못 씀) · bash 는 propose 만. 밖에 쓰는 길이 열려 있으면
    일꾼이 방 (Claude 가 읽는 자리) 에 확정 창을 거치지 않고 글을 둘 수 있다.
    """
    tmp = tempfile.mkdtemp(prefix="oc-r3-")
    home, room_dir = os.path.join(tmp, "dhome"), os.path.join(tmp, "room")
    os.makedirs(os.path.join(room_dir, "work"))
    os.makedirs(home)
    job_dir = os.path.join(home, "work", "J-0001")
    target = os.path.join(job_dir, "inside.txt") if inside else os.path.join(room_dir, "work", "outside.txt")
    model = FakeModel(tool="write", tool_args={"filePath": target, "content": "합성 글"})
    permission = {"bash": {"*": "deny", "python3 *diode.py propose *": "allow", "python *diode.py propose *": "allow"},
                  "edit": "allow", "external_directory": "deny", "webfetch": "deny"}
    saved = isolate(tmp, model.port, permission)
    try:
        w = worker.CommandWorker([oc, "run", "-m", "fake/m", "--dir", "{cwd}"], home, room_dir)
        ok = w.send("J-0001", "[diode J-0001]\n파일을 써라", [])
        code = wait(w.children[-1]) if ok else None
        wrote = os.path.exists(target)
        if inside:
            return code == 0 and wrote, "종료 %s · 작업 폴더 안에 씀: %s (True 여야)" % (code, wrote)
        return code == 0 and not wrote, "종료 %s · 작업 폴더 밖 (방) 에 씀: %s (False 여야)" % (code, wrote)
    finally:
        restore(saved)
        shutil.rmtree(tmp, ignore_errors=True)


def r4(oc, case):
    """전역은 느슨하게 (평소 쓰는 opencode) 두고 일꾼 전용 에이전트 (--agent diode-worker) 에만 권한을 준다.

    case: propose (허락한 명령은 돈다) · outside_cmd (허락 안 한 명령은 안 돈다) · outside_write (작업 폴더 밖 쓰기는 안 된다)
    · other_agent (에이전트를 안 쓰면 전역 그대로 — 평소 사용이 좁아지지 않았다는 확인).
    """
    tmp = tempfile.mkdtemp(prefix="oc-r4-")
    data = data_dir(tmp)
    os.makedirs(data)
    with open(os.path.join(data, "dictionary.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)
    home, room_dir = os.path.join(tmp, "dhome"), os.path.join(tmp, "room")
    os.makedirs(os.path.join(room_dir, "work"))
    os.makedirs(home)
    with open(os.path.join(room_dir, "work", "report.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0001", "status": "done",
                   "summary": ["화면을 만들었다"]}, f, ensure_ascii=False)
    marker = os.path.join(home, "work", "J-0001", "marker-inside.txt")      # 작업 폴더 안 — bash 규칙만이 막고 푼다
    outside = os.path.join(room_dir, "work", "outside.txt")
    if case == "propose":
        model = FakeModel(("%s %s propose report.json" % (py_name(), fwd(DIODE))))
    elif case in ("outside_cmd", "other_agent"):
        model = FakeModel(mark_cmd())
    else:
        model = FakeModel(tool="write", tool_args={"filePath": outside, "content": "x"})
    loose = {"bash": "allow", "edit": "allow", "webfetch": "allow"}                # 평소 쓰는 느슨한 전역 설정
    strict = {"bash": {"*": "deny", "python3 *diode.py propose *": "allow", "python *diode.py propose *": "allow"},
              "edit": "allow", "external_directory": "deny", "webfetch": "deny"}
    saved = isolate(tmp, model.port, loose, agent_config(strict))
    try:
        cmd = [oc, "run", "-m", "fake/m", "--dir", "{cwd}"] + ([] if case == "other_agent" else ["--agent", AGENT])
        w = worker.CommandWorker(cmd, home, room_dir)
        ok = w.send("J-0001", "[diode J-0001]\n해라", ["report.json"])
        code = wait(w.children[-1]) if ok else None
        q = os.path.join(data, "queue")
        queued = len(os.listdir(q)) if os.path.isdir(q) else 0
        if case == "propose":
            return code == 0 and queued == 1, "종료 %s · 대기열 %d (1이어야)" % (code, queued)
        if case == "outside_cmd":
            return code == 0 and not os.path.exists(marker), "종료 %s · 거절돼야 할 명령이 돌았나 %s" % (code, os.path.exists(marker))
        if case == "outside_write":
            return code == 0 and not os.path.exists(outside), "종료 %s · 방에 썼나 %s" % (code, os.path.exists(outside))
        return code == 0 and os.path.exists(marker), "종료 %s · 에이전트를 안 쓰면 전역 (느슨) 그대로 — 평소 사용이 안 좁아짐: %s" % (code, os.path.exists(marker))
    finally:
        restore(saved)
        shutil.rmtree(tmp, ignore_errors=True)


def has_text(obj, needle):
    """요청 본문(JSON 에서 읽은 값) 안의 어느 글에든 needle 이 그대로 들어 있나 (JSON 이스케이프를 거치지 않은 값끼리 비교)"""
    if isinstance(obj, str):
        return needle in obj
    if isinstance(obj, dict):
        return any(has_text(v, needle) for v in obj.values())
    if isinstance(obj, list):
        return any(has_text(v, needle) for v in obj)
    return False


def r5(oc):
    """Windows 의 .cmd 껍데기 - 명령 주입 방어가 진짜로 선다 (cmd.exe 가 인자를 다시 해석한다).

    a. `{prompt}` 를 인자로 주는 설정은 일꾼 부품이 거절한다 (cmd_shim_prompt) - 아무것도 띄우지 않는다
    b. 표준 입력으로 준 글의 & | ^ % ! " 는 명령이 되지 않고 (표지 파일이 안 생김) 모델에 그대로 닿는다
    """
    tmp = tempfile.mkdtemp(prefix="oc-r5-")
    model = FakeModel()
    saved = isolate(tmp, model.port)
    try:
        home, room = os.path.join(tmp, "dhome"), os.path.join(tmp, "room")
        os.makedirs(os.path.join(room, "work"))
        os.makedirs(home)
        bad = worker.command_problem([oc, "run", "{prompt}"])
        w_bad = worker.CommandWorker([oc, "run", "--dir", "{cwd}", "{prompt}"], home, room)
        refused = (bad == "cmd_shim_prompt") and (w_bad.send("J-0002", "x", []) is False) and not w_bad.children
        nasty = 'a & echo INJECTED > injected.txt | echo X ^ %PATH% !VAR! "q" (r) < nul'
        w = worker.CommandWorker(worker_cmd(oc), home, room)
        ok = w.check() and w.send("J-0001", "[diode J-0001]\n[지시]\n%s\n[/지시]\n" % nasty, [])
        code = wait(w.children[-1]) if ok else None
        arrived = any(has_text(r, nasty) for r in model.requests)
        job_dir = os.path.join(home, "work", "J-0001")
        injected = any(os.path.exists(os.path.join(d, "injected.txt")) for d in (job_dir, os.getcwd(), tmp))
        return (refused and code == 0 and arrived and not injected,
                "{prompt} 거절 %s (%s) · 종료 %s · 특수문자가 모델에 그대로 닿음 %s · 주입된 명령이 돌았나 %s (False 여야)"
                % (refused, bad, code, arrived, injected))
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
               ("R2b 허락하지 않은 명령은 돌지 않는다", r2(oc, False)),
               ("R3a 일꾼이 작업 폴더 안에는 파일을 쓸 수 있다", r3(oc, True)),
               ("R3b 일꾼이 작업 폴더 밖 (방) 에는 파일을 쓰지 못한다", r3(oc, False)),
               ("R4a 일꾼 전용 에이전트 — propose 는 돈다", r4(oc, "propose")),
               ("R4b 일꾼 전용 에이전트 — 허락하지 않은 명령은 안 돈다", r4(oc, "outside_cmd")),
               ("R4c 일꾼 전용 에이전트 — 방에는 파일을 못 쓴다", r4(oc, "outside_write")),
               ("R4d 에이전트를 안 쓰면 전역 설정 그대로 (평소 사용이 좁아지지 않음)", r4(oc, "other_agent"))]
    if is_shim(oc):
        results.append(("R5 .cmd 껍데기 - {prompt} 인자는 거절 · 표준 입력의 특수문자는 명령이 되지 않는다", r5(oc)))
    bad = 0
    for name, (ok, why) in results:
        print("%s %-4s %s" % (name.split(" ")[0], "OK" if ok else "실패", name.split(" ", 1)[1] + " — " + why))
        bad += 0 if ok else 1
    print("결과: OK" if not bad else "결과: 점검 실패")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
