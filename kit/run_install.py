"""처음부터 끝까지 (T19) — 마켓플레이스로 설치 → 정책 입력 → /diode:setup 이 방을 만듦 → 방 안 세션이 훅 · 허브 아래에서 돈다.

합성 자리 · 가짜 Anthropic 서버 (127.0.0.1) · 빈 환경의 Claude CLI · 임시 HOME 과 CLAUDE_CONFIG_DIR — 이 PC 의 설정은 건드리지 않는다.
정책은 창 대신 창이 쓰는 같은 저장 함수 (config.apply_state) 로 넣는다 (사람 역할 · 시험이라서). 진짜 창은 사람이 연다.

쓰는 법:  python run_install.py [--claude claude]
  사내 Windows 에서는 `python` 이 PATH 에 있어야 한다 (훅 · 허브가 이름으로 부른다).
확인하는 것 (줄마다 OK · 실패):
  I1 마켓플레이스 추가 · 설치가 된다
  I2 /diode:setup 이 방을 만들고 (표지 · 방 설정 · 해시 ok) 점검 결과가 Claude 에게 간다 · 사전 단어는 없다
  I3 방에서 깨끗한 말은 간다
  I4 방에서 사전 단어 (변형) 는 모델 요청 0 으로 막힌다
  I5 방에서 허브가 뜨고 dispatch 결과는 고정 꼴 한 줄 (일꾼을 안 달았으니 E-01)
  I6 방 밖 (원자료 폴더) 읽기는 막힌다
Python 3.8 이상 · 의존 없음.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import run_kit as rk  # noqa: E402
from diodelib import config, room  # noqa: E402


def data_dir_of(home):
    if os.name == "nt":
        return os.path.join(home, "AppData", "Local", "diode")
    return os.path.join(home, ".local", "share", "diode")


class Env(object):
    def __init__(self, claude):
        self.claude = claude
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="diode-install-"))
        self.home = os.path.join(self.work, "home")
        self.raw = os.path.join(self.work, "raw")
        self.other = os.path.join(self.work, "other")
        self.room = os.path.join(self.work, "claude2", "room")
        for d in (self.home, self.raw, self.other):
            os.makedirs(d)
        with open(os.path.join(self.raw, "secret.txt"), "w", encoding="utf-8") as f:
            f.write(rk.CANARY["raw_text"] + "\n")
        self.n = 0

    def ask(self, prompt, cwd, steps=None, vars_=None, args=None, plugin_args=(), timeout=180):
        """프롬프트 하나를 새 가짜 서버로 돌린다 → (종료 코드, 모델 요청 수, 표준 출력, 요청 본문 글)."""
        self.n += 1
        out = os.path.join(self.work, "out%d" % self.n)
        srv = rk.start_server(out, "steps" if steps else "text", "", {}, steps, vars_)
        env = rk.clean_env(self.home, srv.server_address[1], out, {})
        cmd = [self.claude, "-p", prompt, "--output-format", "json", "--model", rk.MODEL] + list(args or [])
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
            code, stdout = p.returncode, p.stdout
        except subprocess.TimeoutExpired:
            code, stdout = "timeout", ""
        finally:
            srv.shutdown()
        dumps = rk.load_dumps(out)
        msgs = [d for d in dumps if d.get("method") == "POST" and d.get("path", "").split("?")[0].endswith("/v1/messages")]
        body = json.dumps([d.get("body") for d in msgs], ensure_ascii=False)
        return code, len(msgs), stdout, body

    def cli(self, *args):
        env = rk.clean_env(self.home, 9, os.path.join(self.work, "cli"), {})
        p = subprocess.run([self.claude] + list(args), cwd=self.other, env=env, capture_output=True, text=True, timeout=240)
        return p.returncode, (p.stdout + p.stderr)


def last_user_text(body):
    """가짜 서버가 받은 요청 본문 글(JSON 목록)에서 마지막 요청의 마지막 messages 글 - 진단용"""
    try:
        reqs = json.loads(body)
        msgs = (reqs[-1] or {}).get("messages") or []
        return json.dumps(msgs[-1].get("content") if msgs else "", ensure_ascii=False)
    except (ValueError, AttributeError, IndexError, TypeError):
        return ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", default="claude")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    e = Env(a.claude)
    word = rk.CANARY["dict_word"]
    results = []

    def check(name, ok, why):
        results.append(ok)
        print("%s %-4s %s" % (name, "OK" if ok else "실패", why))

    try:
        c1, o1 = e.cli("plugin", "marketplace", "add", REPO)
        c2, o2 = e.cli("plugin", "install", "diode@diode")
        check("I1", c1 == 0 and c2 == 0 and "Successfully installed" in o2, "마켓플레이스 추가 %s · 설치 %s" % (c1, c2))

        # 사람 역할: 정책 입력 (창이 쓰는 같은 저장 함수 · 일꾼은 달지 않는다 → dispatch 는 E-01)
        config.apply_state(data_dir_of(e.home), {"words": [word], "raw_dirs": [e.raw], "room_path": e.room})

        code, n, stdout, body = e.ask("/diode:setup", e.other)
        made = room.room_state(e.room)
        ok2 = n >= 1 and made == "ok" and "방을 만들었습니다" in body and word not in body and rk.CANARY["raw_text"] not in body
        check("I2", ok2, "모델 요청 %d · 방 %s · 점검 결과가 Claude 에게 감 %s · 사전 단어 없음 %s" % (n, made, "방을 만들었습니다" in body, word not in body))
        if not ok2:
            print("  진단 (합성 자료만 — 종료 코드 %s):" % code)
            print("  claude 표준 출력 끝:", (stdout or "")[-500:].replace("\n", " "))
            print("  모델이 받은 마지막 사용자 글 끝:", last_user_text(body)[-1200:].replace("\n", " "))
            if not os.path.isdir(e.room):
                print("  방 폴더가 없어 이어서 시험할 수 없다 — 여기서 멈춘다")
                print("결과: 점검 실패 (I2)")
                return 1

        code, n, stdout, body = e.ask("안녕", e.room)
        check("I3", n >= 1, "방에서 깨끗한 말 → 모델 요청 %d" % n)

        code, n, stdout, body = e.ask("이건 kit-word alpha 야", e.room)
        check("I4", n == 0, "방에서 사전 단어 (변형) → 모델 요청 %d (0 이어야)" % n)

        steps = [{"tool": "ToolSearch", "input": {"query": "select:{dispatch}", "max_results": 1}},
                 {"tool": "{dispatch}", "input": {"instruction": "PH_K7Q2 화면을 만들어 달라"}}]
        code, n, stdout, body = e.ask("일을 넘겨", e.room, steps=steps, vars_={"dispatch": r"mcp__plugin_diode_hub__dispatch"},
                                      args=["--allowedTools", "mcp__plugin_diode_hub__dispatch"])
        flat = body.replace("\\", "").replace(" ", "")
        check("I5", '{"sent":false,"error":"E-01"}' in flat, "허브가 뜨고 dispatch 결과가 고정 꼴 한 줄 (E-01) · 모델 요청 %d" % n)

        steps = [{"tool": "Read", "input": {"file_path": os.path.join(e.raw, "secret.txt")}}]
        code, n, stdout, body = e.ask("읽어", e.room, steps=steps, args=["--allowedTools", "Read"])
        check("I6", rk.CANARY["raw_text"] not in body and "DIODE" in body, "방에서 원자료 읽기 → 막힘 · 원자료 카나리아가 Claude 에게 안 감")
    finally:
        if not a.keep:
            shutil.rmtree(e.work, ignore_errors=True)
    bad = results.count(False)
    print("결과: OK" if not bad else "결과: 점검 실패 (%d)" % bad)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
