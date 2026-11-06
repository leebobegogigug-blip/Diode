# -*- coding: utf-8 -*-
"""처음 설정 · 점검 (/diode:setup · /diode:status · /diode:room) — 표준 라이브러리 · Python 3.8.

출력은 개수 · 참거짓 · 코드뿐이다 — 단어 · 경로 · 일꾼 명령을 찍지 않는다 (AL-11). 명령 (슬래시) 의 표준 출력은 Claude 의
맥락에 붙기 때문이다. 사내 단어는 정책 창에서만 입력한다 (config.py · policy_window.py).

점검 결과 (마지막 줄): 결과: OK · 결과: 확인 필요 · 결과: 점검 실패  (종료 코드 0 · 3 · 1)
"""

import os
import re
import subprocess
import sys

from . import config, hook, room, scan

MIN_PY = (3, 8)


def python_name_ok(name="python", runner=None):
    """훅 · 허브가 부르는 `python` (이름만 · L-30) 이 3.8 이상으로 찾아지나 → (참거짓, 판 글자열 또는 None)."""
    try:
        run = runner or (lambda: subprocess.run([name, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20))
        p = run()
        v = p.stdout.decode("ascii", "replace").strip()
        m = re.match(r"^(\d+)\.(\d+)$", v)
        if p.returncode != 0 or not m:
            return False, None
        return (int(m.group(1)), int(m.group(2))) >= MIN_PY, v
    except Exception:
        return False, None


def user_guide_hits(home, user_md=None):
    """사용자 범위 ~/.claude/CLAUDE.md 에 사전 단어가 있나 (L-29) → 걸린 단어 수 (단어는 내지 않는다). 못 보면 None."""
    path = user_md or os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
    if not os.path.isfile(path):
        return 0
    try:
        policy = scan.policy_from_home(home)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            res = scan.check_text(f.read(), policy, ("D2",))
        return sum(h.get("count", 0) for h in res.get("hits", []) if h.get("check") == "D2")
    except Exception:
        return None


def guide_hits_here(home, cwd=None, env=None):
    """훅과 같은 안내 파일 검사 (사용자 범위 + 지금 폴더에서 위로) → 걸린 단어 수 · 못 보면 None."""
    try:
        policy = scan.policy_from_home(home)
        return hook.guide_hits(cwd or os.getcwd(), hook.user_claude_dir(os.environ if env is None else env), policy)
    except Exception:
        return None


def hook_selftest(plugin_root=None):
    """`diode.py hook prompt` 를 임시 폴더에서 하위 프로세스로 한 번 돌려 본다 — 평범한 말은 통과 (종료 0 · 출력 없음)."""
    import json
    import tempfile
    root = plugin_root or room.PLUGIN_ROOT
    try:
        with tempfile.TemporaryDirectory(prefix="diode-selftest-") as d:
            env = dict(os.environ)
            env["CLAUDE_PROJECT_DIR"] = d
            data = json.dumps({"prompt": "평범한 질문", "cwd": d, "permission_mode": "default"}).encode("utf-8")
            p = subprocess.run([sys.executable, os.path.join(root, "diode.py"), "hook", "prompt"], input=data,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=30)
        return p.returncode == 0 and not p.stdout.strip()
    except Exception:
        return False


def room_folder(home):
    """방 자리: 설정 room.path → 기본."""
    try:
        cfg = config.read_config(home)
        return room.default_room_path((cfg.get("room") or {}).get("path") if isinstance(cfg.get("room"), dict) else None)
    except config.ConfigError:
        return room.default_room_path(None)


def check(home, plugin_root=None, python_probe=None):
    """점검 → (줄 목록, 종료 코드). 단어 · 경로 없음."""
    lines, fails, confirms = [], [], []
    vi = sys.version_info[:2]
    lines.append("파이썬 (이 점검) %d.%d · %s" % (vi[0], vi[1], "OK" if vi >= MIN_PY else "모자람"))
    ok, ver = (python_probe or python_name_ok)()
    lines.append("python 명령 (훅 · 허브가 부름) %s" % (("%s · OK" % ver) if ok else ("%s · 모자람" % ver if ver else "못 찾음")))
    if not ok:
        fails.append("python 명령")
    lines.append("데이터 폴더 %s" % ("있음" if os.path.isdir(home) else "아직 없음 (설정할 때 만들어집니다)"))
    c = config.counts(home)
    if "error" in c:
        lines.append("사전 · 설정을 읽지 못함 (%s)" % c["error"])
        fails.append("설정")
    else:
        lines.append("사전 %d개 · 원자료 폴더 %d개 · 안쪽 도구 이름 %d개 (+ 기본 opencode)" % (c["dictionary"], c["raw_dirs"], c["inner_tools"]))
        lines.append("일꾼 명령 %s · 사내 LLM 판정 (D7) %s" % ("설정함" if c["worker"] else "없음 (일 넘기기는 E-01)",
                                                              "설정함" if c["llm"] else "없음 (보내기는 막힘)"))
        lines.append("실데이터 %s" % ("허용됨 (보안 승인 뒤에만)" if c["real_data"] else "꺼짐 (기본)"))
        if c["worker"]:
            from . import worker as wk
            try:
                cmd, _cwd = wk.load_command(config.read_config(home))
                prob = wk.command_problem(cmd)
            except Exception:
                prob = "config"
            if prob:
                lines.append("일꾼 명령 문제: %s" % {"not_found": "실행 파일을 PATH 에서 찾지 못함",
                                                      "cmd_shim_prompt": "Windows .cmd 껍데기에 {prompt} 를 인자로 줌 (명령 주입 길 - 표준 입력으로 받게 {prompt} 를 빼세요)",
                                                      "config": "설정을 읽지 못함"}.get(prob, prob))
                confirms.append("일꾼 명령에 문제가 있음 (%s) — 일 넘기기는 E-01" % prob)
        if not c["dictionary"]:
            confirms.append("사전이 비어 있음 — 보내기를 막습니다")
        if not c["raw_dirs"]:
            confirms.append("원자료 폴더 목록이 비어 있음 — 보내기를 막습니다")
        if not c["llm"]:
            confirms.append("사내 LLM 판정 (D7) 설정이 없음 — 보내기를 막습니다")
        if c["dictionary"]:
            hits = guide_hits_here(home)
            if hits is None:
                confirms.append("안내 파일 (CLAUDE.md · AGENTS.md) 을 사전으로 검사하지 못함")
            elif hits:
                lines.append("안내 파일 (사용자 범위 · 이 폴더와 위 폴더의 CLAUDE.md · AGENTS.md) 에 사전 단어가 %d개 있음 — Claude 가 모든 요청에 읽어 갑니다" % hits)
                confirms.append("안내 파일에 사전 단어가 있음 (L-29) — 지우거나 옮기세요 · 그 전에는 프롬프트가 막힙니다")
    st = room.room_state(room_folder(home))
    lines.append("방 %s" % {"ok": "ok", "missing": "없음 (/diode:room)", "changed": "changed (방 설정이 바뀜 — 막힘)"}[st])
    if st != "ok":
        confirms.append("방이 ok 가 아님 (%s)" % st)
    st_hook = hook_selftest(plugin_root)
    lines.append("훅 자체 시험 %s" % ("OK" if st_hook else "실패"))
    if not st_hook:
        fails.append("훅")
    for f in fails:
        lines.append("  × %s" % f)
    for c_ in confirms:
        lines.append("  ‼ %s" % c_)
    code = 1 if fails else (3 if confirms else 0)
    lines.append({0: "결과: OK", 3: "결과: 확인 필요", 1: "결과: 점검 실패"}[code])
    return lines, code


REFUSE_TEXT = {
    "path": "방 자리가 절대 경로가 아닙니다",
    "plugin": "방 자리가 플러그인 소스 폴더 안이거나 위입니다 — 다른 자리를 쓰세요",
    "raw": "방 자리가 원자료 폴더와 겹칩니다 — 다른 자리를 쓰세요",
    "git": "방 자리가 git 저장소 안입니다 — 저장소 밖에 만드세요",
    "guide": "방 자리나 그 위 폴더에 CLAUDE.md · AGENTS.md 가 있습니다 — 지우거나 다른 자리를 쓰세요",
    "nonempty": "방 자리가 비어 있지 않은 폴더입니다 — 빈 폴더나 새 자리를 쓰세요",
}


def make_room(home, path=None, plugin_root=None):
    """방을 만든다 → (줄 목록, 종료 코드). 원자료 폴더 목록은 설정에서."""
    try:
        raw_dirs = config.load_state(home)["raw_dirs"]
    except config.ConfigError:
        raw_dirs = []
    folder = path or room_folder(home)
    res = room.create_room(folder, raw_dirs, plugin_root)
    state = res["room"]
    if state == "created":
        return ["방을 만들었습니다 (표지 · 방 설정 · outbox · inbox · work)"], 0
    if state == "ok":
        return ["방이 이미 있고 ok 입니다"], 0
    if state == "changed":
        return ["방이 이미 있는데 설정이 바뀌었습니다 (changed) — 덮어쓰지 않습니다. 지우고 다시 만들거나 되돌리세요"], 3
    return ["방을 만들지 않았습니다: %s" % REFUSE_TEXT.get(res.get("code"), res.get("code"))], 2


def run_setup(home, plugin_root=None, path=None, launch=None):
    """/diode:setup — 점검하고, 모자란 정책은 창을 열어 사람이 입력하게 하고, 방이 없으면 만든다 → (줄, 종료 코드).

    창은 따로 떼어 연다 (기다리지 않는다) — 저장한 뒤 /diode:setup 을 다시 실행하거나 /diode:status 로 본다.
    """
    os.makedirs(home, exist_ok=True)
    out = []
    ready, missing = config.ready(home)
    if not ready and missing and missing[0] not in ("words_empty", "raw_empty"):
        lines, code = check(home, plugin_root)
        note = "설정을 읽지 못해 창을 열지 않았습니다 (%s)" % missing[0]
        if lines and lines[-1].startswith("결과:"):          # 마지막 줄은 늘 결과 (S-03)
            return lines[:-1] + [note] + lines[-1:], max(code, 1)
        return lines + [note], max(code, 1)
    if not ready:
        out.append("정책 (사전 · 원자료 폴더) 이 비어 있어 정책 창을 엽니다 — 창에서 직접 입력하고 [저장] 하세요")
        out.append("단어는 이 대화로 보내지 않습니다 (입력하면 곧바로 Claude 로 나갑니다)")
        opened = True
        if launch is not None:
            launch()
        else:
            from . import policy_window
            if policy_window.can_open():
                policy_window.launch_detached(sys.executable, os.path.join(plugin_root or room.PLUGIN_ROOT, "diode.py"))
            else:
                opened = False
        if opened:
            out.append("저장한 뒤 /diode:setup 을 다시 실행하면 방을 만들고 점검합니다")
        else:
            out[:] = ["정책 (사전 · 원자료 폴더) 이 비어 있는데 정책 창을 띄울 수 없습니다 (E-07) - 화면이 없거나 이 파이썬에 tkinter 가 없습니다",
                      "정책은 정책 창에서만 바뀌므로 화면이 있는 PC 에서 /diode:dict 를 여세요"]
        lines, code = check(home, plugin_root)
        return out + lines, (code if code else 3)
    mlines, mcode = make_room(home, path, plugin_root)
    lines, code = check(home, plugin_root)
    return mlines + lines, (code if code else (mcode if mcode else 0))
