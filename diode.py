#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diode - Claude Code 플러그인 Diode 의 진입점 (표준 라이브러리만 · Python 3.8+)

  diode.py version | help | check | scan | hook <session|prompt|tool>

개발 중 (v0.0) — 훅 (hook) · 검사기 (scan) 는 있다. 허브 · 확정 창은 아직 없다 (docs/PLAN.md › 10 로드맵).
아직 없는 명령 (mcp · --statusline · --status · propose · confirm · lib) 은 종료 코드 2 로 끝난다.
hook 은 Claude Code 훅 (SP-11) — 플러그인 hooks/hooks.json 이 부른다.
scan 은 표준 입력의 글을 검사한다 (D2 · D3 · D5) — 종료 코드 0 통과 · 2 막음 (SP-16 · 훅과 같은 뜻).
종료 코드: 0 OK · 1 점검 실패 · 2 사용법 오류 · 3 사람 확인 필요 (RULES.md › S-03)
점검 출력의 마지막 줄은 결과: OK · 결과: 확인 필요 · 결과: 점검 실패 중 하나 (에이전트가 이 줄로 판단한다)
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diodelib import APP, NAME, VERSION  # noqa: E402

OK, FAIL, USAGE, CONFIRM = 0, 1, 2, 3
RESULT = {OK: "결과: OK", CONFIRM: "결과: 확인 필요", FAIL: "결과: 점검 실패"}
MIN_PYTHON = (3, 8)
HOME_ENV = "DIODE_HOME"        # 테스트용 — 데이터 폴더를 옮긴다 (docs/PLAN.md › AL-12). 그 밖의 설정은 환경 변수로 받지 않는다
ALIASES = {"-h": "help", "--help": "help", "--version": "version"}

# 아직 없는 명령 (v0.0) — 계약은 docs/SPEC.md SP-16. (이름, 도움말의 설명)
PENDING = (
    ("lib", "lib names <이름>                허용 라이브러리의 공개 이름"),
)
PENDING_FLAGS = ()

HELP = """%s %s — Claude Code 플러그인 (개발 중 · v0.0 · 훅만 있습니다)

사용법: python diode.py <명령>

  version                         버전
  help                            이 도움말 (-h · --help 도 됩니다)
  check                           자가 점검 (마지막 줄 결과: …)
  scan                            표준 입력의 글 검사 (D2 · D3 · D5 · 0 통과 · 2 막음 · 단어는 찍지 않음)
  hook <session|prompt|tool>      Claude Code 훅 (플러그인이 부른다 · 표준 입력 = 훅 입력 JSON)
  --status --json [--room 폴더]   상태 명령 (읽기 전용 · JSON 한 줄 · 단어는 없음)
  --statusline                    statusLine 기록 (방 설정이 부른다 · 표준 입력 = statusLine JSON)
  mcp                             허브 (MCP 서버 · 플러그인 .mcp.json 이 띄운다 · 표준 입출력 JSON-RPC)
  propose <report.json>           일꾼 보고 내기 (미리 보고 걸리면 2 · 통과면 허브의 대기열에 넣고 0)
  confirm <요청 파일>             확정 창 (허브가 부른다 · 결과는 JSON 한 줄 · 0 보냄 · 3 사람이 안 보냄 · 2 꼴 오류 · 1 창 없음)

아직 없는 명령 (v0.0 — 부르면 종료 코드 2 로 끝납니다)
  %s

종료 코드  0 OK · 1 점검 실패 · 2 사용법 오류 · 3 사람 확인 필요
설계는 docs/PLAN.md · 계약은 docs/SPEC.md (SP-16) 에 있습니다.
""" % (NAME, VERSION, "\n  ".join([d for _, d in PENDING] + [d for _, d in PENDING_FLAGS]))


class UsageError(Exception):
    """사용법이 틀렸다 — 메시지는 사람에게 그대로 보여 줄 한 줄"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        """argparse 의 영어 오류 글 중 흔한 것을 한국어로 바꾼다 (나머지는 그대로)"""
        m = re.search(r"invalid choice: '([^']*)'", message)
        if m:
            message = "모르는 명령입니다: %s" % m.group(1)
        elif message.startswith("unrecognized arguments: "):
            message = "모르는 인자입니다: " + message[len("unrecognized arguments: "):]
        elif message.endswith("expected one argument"):
            message = message[:-len("expected one argument")].replace("argument ", "") + "다음에 값이 필요합니다"
        raise UsageError(message)


def build_parser():
    p = _Parser(prog="diode.py", add_help=False, allow_abbrev=False)
    p.add_argument("--statusline", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--room", metavar="폴더")
    sub = p.add_subparsers(dest="command", metavar="명령")
    for name in ("version", "help", "check", "scan"):
        sub.add_parser(name, add_help=False)
    sub.add_parser("confirm", add_help=False).add_argument("rest", nargs=argparse.REMAINDER)
    sub.add_parser("propose", add_help=False).add_argument("rest", nargs=argparse.REMAINDER)
    sub.add_parser("mcp", add_help=False)
    sub.add_parser("hook", add_help=False).add_argument("event", nargs="?", default="")
    for name, _ in PENDING:
        sub.add_parser(name, add_help=False).add_argument("rest", nargs=argparse.REMAINDER)
    return p


def data_dir():
    """데이터 폴더 자리 → (경로, 기본 위치인가). 읽기만 하고 만들지 않는다 (RULES.md › W-06)"""
    override = os.environ.get(HOME_ENV, "")
    if override:
        return os.path.abspath(override), False
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, APP), True
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP), True


def check(out, version_info=None):
    """자가 점검 — 파이썬 판 · 데이터 폴더 자리. 아무것도 만들거나 바꾸지 않는다"""
    vi = tuple(version_info or sys.version_info[:3])
    fails, confirms = [], []
    out.write("%s %s · 개발 중 (v0.0)\n" % (NAME, VERSION))
    py_ok = vi[:2] >= MIN_PYTHON
    out.write("  파이썬        %s (%d.%d 이상 필요) · %s\n"
              % (".".join(str(n) for n in vi), MIN_PYTHON[0], MIN_PYTHON[1], "OK" if py_ok else "모자람"))
    if not py_ok:
        fails.append("파이썬 %d.%d 이상이 필요합니다" % MIN_PYTHON)
    folder, default = data_dir()
    if os.path.isdir(folder):
        state = "있음"
    elif os.path.exists(folder):
        state = "폴더가 아님"
        fails.append("데이터 폴더 자리에 파일이 있습니다: 옮기거나 지우세요")
    else:
        state = "아직 없음 (v0.0 은 만들지 않습니다)"
    out.write("  데이터 폴더   %s · %s\n" % (folder, state))
    out.write("  자리          %s\n" % ("기본 위치" if default else HOME_ENV + " (테스트용)"))
    if not default:
        confirms.append("%s 이 설정되어 있습니다 — 테스트용 자리입니다 (docs/PLAN.md › AL-12). 평소에는 지우세요" % HOME_ENV)
    for line in fails:
        out.write("  × %s\n" % line)
    for line in confirms:
        out.write("  ‼ %s\n" % line)
    code = FAIL if fails else (CONFIRM if confirms else OK)
    out.write(RESULT[code] + "\n")
    return code


def scan_command(out, err, inp):
    """scan — 표준 입력 (바이트) 을 데이터 폴더의 사전 · 설정으로 검사한다. 출력에 단어는 없다 (AL-11)"""
    from diodelib import scan
    data = inp.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    code, line_json, line_human = scan.main_scan(data_dir()[0], data)
    out.write(line_json + "\n")
    err.write(line_human + "\n")
    return code


def confirm_command(out, rest):
    """confirm — 확정 창 (SP-09). 표준 출력은 결과 한 줄뿐 (ASCII · 글 · 단어 없음). 어떤 실패도 보내지 않는 쪽으로"""
    try:
        from diodelib import confirm            # import 실패도 보내지 않는 쪽으로
        code, line = confirm.main_confirm(rest[0] if len(rest) == 1 else None)
    except Exception:
        code, line = 1, '{"decision": "error", "code": "E-20"}'
    out.write(line + "\n")
    return code


def run(args, out, err, inp=None):
    if (args.json or args.room) and not args.status:
        raise UsageError("--json · --room 은 --status 와 같이 씁니다")
    if args.command is None and not (args.status or args.statusline):
        raise UsageError("명령이 없습니다")
    if args.command is not None and (args.status or args.statusline):
        raise UsageError("--status · --statusline 은 명령과 같이 쓰지 않습니다")
    if args.status and args.statusline:
        raise UsageError("--status 와 --statusline 은 같이 쓰지 않습니다")
    if args.command == "version":
        out.write("%s %s\n" % (NAME, VERSION))
        return OK
    if args.command == "help":
        out.write(HELP)
        return OK
    if args.command == "check":
        return check(out)
    if args.command == "scan":
        return scan_command(out, err, inp if inp is not None else _stdin_bytes())
    if args.command == "confirm":
        return confirm_command(out, args.rest)
    if args.command == "propose":
        try:
            from diodelib import propose
            code, line = propose.main_propose(args.rest[0] if len(args.rest) == 1 else None)
        except Exception:
            code, line = 2, '{"queued": false, "error": "E-20"}'
        out.write(line + "\n")
        return code
    if args.command == "mcp":
        from diodelib import hub
        return hub.main(stdin=inp if inp is not None else None, stdout=out if out is not sys.stdout else None)
    if args.command == "hook":
        from diodelib import hook
        return hook.main([args.event], stdin=inp if inp is not None else _stdin_bytes(), stdout=out, stderr=err)
    if args.status:
        from diodelib import status
        home, default = data_dir()
        argv = ["--json"] if args.json else []
        if args.room:
            argv += ["--room", args.room]
        return status.main_status(argv, out, home=home, home_is_default=default, err=err)
    if args.statusline:
        from diodelib import status
        data = (inp if inp is not None else _stdin_bytes()).read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        return status.main_statusline(data, out, data_dir()[0])
    name = args.command
    err.write("diode.py %s: 아직 없음 (v0.0) — 계약은 docs/SPEC.md (SP-16), 순서는 docs/PLAN.md › 10 로드맵\n" % name)
    return USAGE


def _stdin_bytes():
    return getattr(sys.stdin, "buffer", sys.stdin)


def main(argv=None, out=None, err=None, inp=None):
    out = out or sys.stdout
    err = err or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 1 and argv[0] in ALIASES:
        argv = [ALIASES[argv[0]]]
    try:
        return run(build_parser().parse_args(argv), out, err, inp)
    except UsageError as e:
        err.write("사용법 오류: %s\n  python diode.py help 를 보세요\n" % e)
        return USAGE


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
