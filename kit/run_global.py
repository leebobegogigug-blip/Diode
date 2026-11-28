"""전역 확인 — Diode 가 이 PC 의 모든 Claude Code 세션에서 꺼지지 않고 켜져 있는가 (진짜 CLI · 가짜 서버 · 합성 단어).

마켓플레이스로 설치한 diode 를 (임시 HOME · 이 PC 의 내 설정은 건드리지 않는다) 사람이 흔히 끄는 길로 꺼 보고,
그래도 사전 단어가 막히는지 본다. 관리형 설정 (managed settings — IT 가 PC 전체에 거는 설정) 은 임시 HOME 과 상관없이
이 PC 의 모든 Claude Code 에 걸리므로, IT 가 Diode 를 강제로 켜 두었다면 여기서 G2–G6 이 모두 "막힘" 이어야 한다.

  G1 대조: 보통 폴더 · 사전 단어 → 막힘이어야 한다 (설치 · 설정이 맞다는 뜻)
  G2 그 폴더의 .claude/settings.json 에 "enabledPlugins": {"diode@diode": false}
  G3 같은 줄을 .claude/settings.local.json 에
  G4 그 폴더의 .claude/settings.json 에 "disableAllHooks": true
  G5 명령줄 --settings 로 enabledPlugins false
  G6 사용자 설정 (~/.claude/settings.json) 에 enabledPlugins false

2026-11-28 · Claude Code 2.1.318 · 리눅스 · 관리형 설정 없음: G1 막힘 · G2–G6 꺼짐 (그대로 나감). 즉 사용자 범위 설치만으로는
"늘 켜짐" 이 아니다 — 끄는 길을 막는 것은 관리형 설정뿐이다 (Claude 가 도구로 끄는 길은 훅이 따로 막는다 · R32 · R33).

쓰는 법:  python run_global.py [--claude claude] [--expect report|open|locked]
  report (기본): 모두 막히면 결과: OK (0) · 꺼지는 길이 하나라도 있으면 결과: 확인 필요 (3) — 사내 점검표가 이것을 쓴다
  locked: 모두 막혀야 OK (1 실패) — IT 가 관리형 설정을 건 뒤
  open:   G1 은 막히고 G2–G6 은 꺼져야 OK — 관리형 설정이 없는 CI 에서 "한계가 그대로인가" 를 기록한다 (R15 처럼)
출력은 판정 · 개수뿐이다 (사전 단어 · 경로 · 키 없음). 모델 요청은 127.0.0.1 의 가짜 서버로만 간다.
Python 3.8 이상 · 의존 없음.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import run_install as ri  # noqa: E402
import run_kit as rk  # noqa: E402
from diodelib import config  # noqa: E402

OFF = {"enabledPlugins": {"diode@diode": False}}


def project(e, name, file_name=None, settings=None):
    """보통 폴더 하나 (원자료 · 방이 아닌) - 끄는 설정 파일을 둘 수 있다."""
    d = os.path.join(e.work, "proj-" + name)
    os.makedirs(os.path.join(d, ".claude"), exist_ok=True)
    if file_name:
        with open(os.path.join(d, ".claude", file_name), "w", encoding="utf-8") as f:
            json.dump(settings, f)
    return d


def user_settings_path(e):
    """임시 HOME 의 Claude Code 사용자 설정 (clean_env 가 CLAUDE_CONFIG_DIR 를 주면 그 아래)."""
    env = rk.clean_env(e.home, 9, os.path.join(e.work, "probe"), {})
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(e.home, ".claude")
    return os.path.join(base, "settings.json")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", default="claude")
    ap.add_argument("--expect", choices=("report", "open", "locked"), default="report")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    e = ri.Env(a.claude)
    word = rk.CANARY["dict_word"]
    rows = []
    try:
        c1, _ = e.cli("plugin", "marketplace", "add", REPO)
        c2, o2 = e.cli("plugin", "install", "diode@diode")
        if c1 != 0 or c2 != 0 or "Successfully installed" not in o2:
            print("G0 실패 마켓플레이스 추가 %s · 설치 %s — 설치부터 막혔다 (INSTALL 3단계 · 관리형 설정)" % (c1, c2))
            print("결과: 점검 실패 (G0)")
            return 1
        print("G0 OK   마켓플레이스로 설치 (사용자 범위)")
        config.apply_state(ri.data_dir_of(e.home), {"words": [word], "raw_dirs": [e.raw], "room_path": e.room})

        cases = [
            ("G1", "대조: 보통 폴더 · 끄는 설정 없음", project(e, "plain"), None),
            ("G2", "프로젝트 .claude/settings.json 에 enabledPlugins false", project(e, "g2", "settings.json", OFF), None),
            ("G3", "프로젝트 .claude/settings.local.json 에 enabledPlugins false", project(e, "g3", "settings.local.json", OFF), None),
            ("G4", "프로젝트 .claude/settings.json 에 disableAllHooks true", project(e, "g4", "settings.json", {"disableAllHooks": True}), None),
            ("G5", "명령줄 --settings 로 enabledPlugins false", project(e, "g5"), ["--settings", json.dumps(OFF)]),
        ]
        for cid, what, cwd, args in cases:
            _code, n, _out, body = e.ask("이건 %s 야" % word, cwd, args=args)
            rows.append((cid, what, n == 0 and word not in body))

        # G6 - 사용자 설정에서 끔 (사람이 /plugin 화면에서 끄는 것과 같은 자리) · 끝나면 되돌린다 (임시 HOME)
        path = user_settings_path(e)
        old = None
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                old = f.read()
        try:
            cur = json.loads(old) if old else {}
            cur.setdefault("enabledPlugins", {})["diode@diode"] = False
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            _code, n, _out, body = e.ask("이건 %s 야" % word, project(e, "g6"))
            rows.append(("G6", "사용자 설정 (~/.claude/settings.json) 에 enabledPlugins false", n == 0 and word not in body))
        finally:
            if old is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(old)
    finally:
        if not a.keep:
            shutil.rmtree(e.work, ignore_errors=True)

    for cid, what, blocked in rows:
        print("%s %-4s %s → %s" % (cid, "막힘" if blocked else "꺼짐", what,
                                   "사전 단어가 막혔다" if blocked else "Diode 가 꺼져 사전 단어가 그대로 나갔다"))
    g1 = rows[0][2]
    opened = [cid for cid, _w, blocked in rows[1:] if not blocked]
    if not g1:
        print("결과: 점검 실패 (G1 — 끄는 설정이 없는데도 막히지 않았다 · 설치 · 설정 · python 을 먼저 보세요)")
        return 1
    if a.expect == "locked":
        print("결과: OK" if not opened else "결과: 점검 실패 (%s — 관리형 설정이 끄는 길을 막지 못했다)" % " ".join(opened))
        return 0 if not opened else 1
    if a.expect == "open":
        ok = len(opened) == len(rows) - 1
        print("결과: OK (한계 그대로 — 관리형 설정 없이는 G2–G6 으로 꺼진다)" if ok
              else "결과: 점검 실패 (막힌 길이 생겼다 — Claude Code 가 바뀌었는지 보고 문서를 고친다)")
        return 0 if ok else 1
    if opened:
        print("결과: 확인 필요 (%s 로 꺼진다 — 사람 · 프로젝트 설정이 Diode 를 끌 수 있다 · IT 의 관리형 설정이 필요하다)" % " ".join(opened))
        return 3
    print("결과: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
