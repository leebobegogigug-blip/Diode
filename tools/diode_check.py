#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diode_check.py - Diode 저장소의 자기 검사기 (표준 라이브러리만 · Python 3.8+)

works 의 검사기 (works 저장소의 tools/works_check.py) 는 이 저장소를 보지 않는다 — Diode 는 works 밖 저장소다
(RULES.md › W-11). 그래서 필요한 검사를 옮겨 다듬어 여기 둔다. works 코드를 import 하지 않는다.
옮긴 검사의 출처: works 저장소 tools/works_check.py (커밋 13e56a0a5801da56dc18523363cd219ebf6d2e21) —
  파일 목록 읽기 (git ls-files) · 표준 라이브러리 밖 import (W-02) · 0.0.0.0 바인딩 · 외부 리소스 (W-03) ·
  비밀 패턴 (W-04) · README 의 테스트 수 (W-11) · 사설 IP (W-12)

  python tools/diode_check.py             검사. 위반이 있어도 종료 코드 0 (고치는 중에 볼 때)
  python tools/diode_check.py --strict    위반이 있으면 종료 코드 1 (CI 가 쓰는 차단 모드)
  python tools/diode_check.py --no-tests  README 의 테스트 수 확인 (테스트 불러오기) 을 건너뜀
  python tools/diode_check.py --internal-words <파일>   사내 낱말 검사 (낱말 목록 · 한 줄에 하나 · 대소문자 무시)

[검사하는 것]
  W-01  필수 파일 · 플러그인 파일 (plugin.json · marketplace.json · .mcp.json · hooks/hooks.json 이 JSON 으로 읽히고 이름이 diode)
  W-02  diode.py · diodelib/ 의 import 가 표준 라이브러리 · diodelib 뿐인가 (함수 안 · try 안 import 도 본다) · 3.8 문법
  W-03  "0.0.0.0" 바인딩 문자열 · 외부 CDN · 웹 폰트 (실행 코드 · HTML — tests/ · tools/ · kit/ 는 개발 자리라 뺀다)
  W-04  키 · 토큰처럼 보이는 문자열 (git 이 추적하는 파일 + 새 파일 · kit/out/ 제외)
  W-11  README 의 `테스트 N` 이 tests/ 를 unittest 로 불러온 수와 같은가
  W-12  사설 IP 주소 (docs/SPEC.md · tests/vectors/ 밖) · (선택) 사내 낱말

[출력] 위반마다 한 줄 · 마지막 줄은 결과: OK 또는 결과: 점검 실패.
  비밀 · 사설 주소 · 사내 낱말은 값을 찍지 않는다 (종류 · 개수 · 자리만 — RULES.md › W-04).
"""
import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_NAME = "diode"
REQUIRED = ("README.md", "INSTALL.md", "docs/MANUAL.md", "docs/INHOUSE.md", "RULES.md", "AGENTS.md", "LICENSE",
            ".gitignore", ".gitattributes", ".github/workflows/diode.yml", ".claude-plugin/plugin.json")
PLUGIN_FILES = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".mcp.json", "hooks/hooks.json")
SKIP_PREFIX = ("kit/out/",)                       # M0 정찰 산출물 — 커밋하지 않는다 (AGENTS.md)
DEV_TOP = ("tests", "tools", "kit")               # 개발 자리 — 실행 코드가 아니다
EXEC_EXT = (".py", ".ps1", ".cmd", ".bat", ".js", ".html", ".htm", ".css")
PRIVATE_IP_OK = ("docs/SPEC.md", "tests/vectors/", "kit/corpus/")   # D3 의 반례 · 합성 말뭉치 (T3) 의 원자료 — 지어낸 값이다
MAX_READ = 4 * 1024 * 1024
# 3.10 미만에는 sys.stdlib_module_names 가 없다 — 이 PC 에서 못 찾을 수 있는 플랫폼 전용 표준 모듈만 따로 허락한다
PLATFORM_STDLIB = frozenset(("msvcrt", "winreg", "winsound", "_winapi", "nt", "_msi", "posix", "pwd", "grp", "fcntl",
                             "termios", "resource", "syslog", "readline", "curses", "_curses", "tkinter", "_tkinter"))


class Finding(NamedTuple):
    rule: str        # W-01 · W-02 · …
    path: str        # 저장소 기준 경로 (/ 구분)
    msg: str
    line: int = 0


# ─────────────────────────────────────────────────────────────── 저장소 읽기

class Repo:
    def __init__(self, root: str = ROOT):
        self.root = root
        self.files = self._list_files()
        self.fileset = set(self.files)
        self.notes: List[str] = []           # 결과에는 안 세는 안내 (건너뛴 검사 등)
        self._text: Dict[str, str] = {}

    def _list_files(self) -> List[str]:
        """git 이 추적하는 파일 + 새로 만든 (무시되지 않은) 파일. git 이 없거나 저장소가 아니면 폴더를 훑는다"""
        files: Optional[Set[str]] = None
        try:
            p = subprocess.run(["git", "-C", self.root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=120)
            files = {f for f in p.stdout.decode("utf-8", "replace").split("\0") if f}
        except (OSError, subprocess.SubprocessError):
            files = None
        if files is None:
            files = set()
            for d, subdirs, names in os.walk(self.root):
                subdirs[:] = [s for s in subdirs if s not in (".git", "__pycache__")]
                for n in names:
                    files.add(os.path.relpath(os.path.join(d, n), self.root).replace(os.sep, "/"))
        return sorted(f for f in files if not f.startswith(SKIP_PREFIX) and os.path.isfile(self.abs(f)))

    def abs(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/"))

    def has(self, rel: str) -> bool:
        return rel in self.fileset

    def text(self, rel: str) -> str:
        """파일 글. 바이너리 (NUL 이 든 것) · 4 MiB 넘는 것은 빈 글"""
        if rel not in self._text:
            try:
                with open(self.abs(rel), "rb") as f:
                    raw = f.read(MAX_READ + 1)
            except OSError:
                raw = b""
            if len(raw) > MAX_READ or b"\0" in raw[:8192]:
                raw = b""
            self._text[rel] = raw.decode("utf-8-sig", "replace")
        return self._text[rel]


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def lines_of(rx, text: str, limit: int = 8) -> List[int]:
    """rx 가 걸린 줄 번호들 (겹치지 않게 · 처음 limit 개). 값은 돌려주지 않는다"""
    out: List[int] = []
    for m in rx.finditer(text):
        ln = line_of(text, m.start())
        if ln not in out:
            out.append(ln)
        if len(out) >= limit:
            break
    return out


def also(lines: List[int]) -> str:
    """첫 줄 말고 더 있으면 메시지 끝에 붙일 말"""
    return " (줄 %s)" % " · ".join(str(n) for n in lines) if len(lines) > 1 else ""


def is_exec_code(rel: str) -> bool:
    return rel.lower().endswith(EXEC_EXT) and rel.split("/")[0] not in DEV_TOP


# ─────────────────────────────────────────────────────────────── W-01 필수 파일 · 플러그인 파일

def check_required(repo: Repo) -> List[Finding]:
    out = [Finding("W-01", rel, "필수 파일이 없습니다") for rel in REQUIRED if not repo.has(rel)]
    if not any(f.startswith("tests/") and f.endswith(".py") and os.path.basename(f).startswith("test") for f in repo.files):
        out.append(Finding("W-01", "tests/", "tests/ 에 test*.py 가 없습니다"))
    return out


def check_plugin_files(repo: Repo) -> List[Finding]:
    """JSON 으로 읽히는가 · 이름이 diode 인가. .mcp.json · hooks.json 은 이름 칸이 없어 JSON 객체인지만 본다"""
    out = []
    for rel in PLUGIN_FILES:
        if not repo.has(rel):
            continue                        # plugin.json 이 없는 것은 필수 파일 검사가 알린다
        try:
            data = json.loads(repo.text(rel))
        except ValueError as e:
            out.append(Finding("W-01", rel, "JSON 으로 읽히지 않습니다 (%s)" % getattr(e, "msg", e.__class__.__name__),
                               getattr(e, "lineno", 0)))
            continue
        if not isinstance(data, dict):
            out.append(Finding("W-01", rel, "JSON 객체가 아닙니다"))
        elif rel.endswith("plugin.json") and data.get("name") != PLUGIN_NAME:
            out.append(Finding("W-01", rel, "name 이 %s 이 아닙니다" % PLUGIN_NAME))
        elif rel.endswith("marketplace.json"):
            if data.get("name") != PLUGIN_NAME:
                out.append(Finding("W-01", rel, "마켓플레이스 name 이 %s 이 아닙니다" % PLUGIN_NAME))
            plugins = data.get("plugins")
            if not isinstance(plugins, list) or not any(isinstance(p, dict) and p.get("name") == PLUGIN_NAME for p in plugins):
                out.append(Finding("W-01", rel, "plugins 에 name 이 %s 인 플러그인이 없습니다" % PLUGIN_NAME))
    return out


# ─────────────────────────────────────────────────────────────── W-02 의존성 0

def runtime_files(repo: Repo) -> List[str]:
    return [f for f in repo.files if f == "diode.py" or (f.startswith("diodelib/") and f.endswith(".py"))]


def dynamic_import_name(node: ast.Call) -> Optional[str]:
    """__import__("x") · importlib.import_module("x") — 문자열 상수로 부르는 것"""
    fn = node.func
    called = (isinstance(fn, ast.Name) and fn.id == "__import__") or (isinstance(fn, ast.Attribute) and fn.attr == "import_module")
    if called and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        name = node.args[0].value
        return name if name and not name.startswith(".") else None
    return None


def imports_of(tree: ast.AST) -> List[Tuple[str, int]]:
    """(모듈 첫 이름, 줄). 함수 안 · try 안 · 조건 안의 import 도 센다. 같은 패키지의 상대 import (level>0) 는 뺀다"""
    found: List[Tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((a.name.split(".")[0], node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append((node.module.split(".")[0], node.lineno))
        elif isinstance(node, ast.Call):
            name = dynamic_import_name(node)
            if name:
                found.append((name.split(".")[0], node.lineno))
    return found


def module_problem(name: str, root: str) -> Optional[str]:
    """표준 라이브러리 · diodelib 가 아니면 까닭 (한 줄), 괜찮으면 None"""
    if name in ("diodelib", "__future__"):
        return None
    stdlib = getattr(sys, "stdlib_module_names", None)         # 3.10+
    if stdlib is not None and name in stdlib:
        return None
    if os.path.isfile(os.path.join(root, name + ".py")) or os.path.isdir(os.path.join(root, name)):
        return "저장소 안의 다른 모듈입니다 (diodelib 만 씁니다)"
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, AttributeError):
        spec = None
    if spec is None:
        if stdlib is None and name in PLATFORM_STDLIB:
            return None
        return "표준 라이브러리 밖 모듈입니다 (찾을 수 없음)"
    if spec.origin in ("built-in", "frozen"):
        return None
    places = [str(p) for p in ([spec.origin] if spec.origin else []) + list(spec.submodule_search_locations or [])]
    if any(re.search(r"[\\/](?:site|dist)-packages(?:[\\/]|$)", p) for p in places):
        return "site-packages · dist-packages 에 설치된 외부 패키지입니다"
    root_real = os.path.realpath(root)
    if any(os.path.realpath(p).startswith(root_real + os.sep) for p in places):
        return "저장소 안의 다른 모듈입니다 (diodelib 만 씁니다)"
    return None if stdlib is None else "표준 라이브러리 밖 모듈입니다"


def check_dependencies(repo: Repo) -> List[Finding]:
    out = []
    for rel in runtime_files(repo):
        try:
            tree = ast.parse(repo.text(rel), filename=rel, feature_version=(3, 8))
        except (SyntaxError, ValueError) as e:
            out.append(Finding("W-02", rel, "파이썬 3.8 로 읽히지 않습니다: %s" % getattr(e, "msg", e), getattr(e, "lineno", 0) or 0))
            continue
        seen: Set[str] = set()
        for name, ln in imports_of(tree):
            if name in seen:
                continue
            seen.add(name)
            why = module_problem(name, repo.root)
            if why:
                out.append(Finding("W-02", rel, "%s 을 import 합니다 — %s" % (name, why), ln))
    return out


# ─────────────────────────────────────────────────────────────── W-03 내 PC 에서만

BIND_ALL_RE = re.compile(r"[\"']0\.0\.0\.0(?::\d+)?[\"']")
CDN_HOST_RE = re.compile(
    r"(?<![\w.-])(?:[\w-]+\.)*(?:unpkg\.com|jsdelivr\.net|cdnjs\.cloudflare\.com|fonts\.googleapis\.com|fonts\.gstatic\.com"
    r"|ajax\.googleapis\.com|code\.jquery\.com|fontawesome\.com|bootstrapcdn\.com|esm\.sh|skypack\.dev|fonts\.bunny\.net"
    r"|use\.typekit\.net|rsms\.me)(?![\w-])"
    r"|(?<![\w.-])(?:[\w-]+\.)*cdn\d*\.[a-z0-9-]+\.[a-z]{2,}(?![\w-])", re.I)
EXT_RESOURCE_RE = re.compile(
    r"<(?:script|link|img|iframe)\b[^>]*?\b(?:src|href)\s*=\s*[\"']?(?:https?:)?//"
    r"|(?:@import\s+(?:url\()?|url\()\s*[\"']?(?:https?:)?//", re.I)


def check_network(repo: Repo) -> List[Finding]:
    out = []
    for rel in repo.files:
        if not is_exec_code(rel):
            continue
        text = repo.text(rel)
        found = lines_of(BIND_ALL_RE, text)
        if found:
            out.append(Finding("W-03", rel, "0.0.0.0%s — 서버는 127.0.0.1 에만 바인딩합니다" % also(found), found[0]))
        found = sorted(set(lines_of(CDN_HOST_RE, text) + lines_of(EXT_RESOURCE_RE, text)))
        if found:
            out.append(Finding("W-03", rel, "외부 CDN · 웹 폰트 · 원격 리소스 주소가 있습니다%s" % also(found), found[0]))
    return out


# ─────────────────────────────────────────────────────────────── W-04 비밀 · W-12 사설 주소

SECRET_RES = (
    ("OpenAI 식 키", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("GitHub 토큰", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("AWS 키", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack 토큰", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("개인 키 머리", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
)
PRIVATE_IP_RE = re.compile(r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?!\d|\.\d)")


def check_secrets(repo: Repo) -> List[Finding]:
    out = []
    for rel in repo.files:
        text = repo.text(rel)
        for what, rx in SECRET_RES:
            found = lines_of(rx, text)
            if found:   # 값은 찍지 않는다
                out.append(Finding("W-04", rel, "%s 처럼 보이는 문자열이 있습니다%s — 값은 커밋하지 않습니다" % (what, also(found)), found[0]))
    return out


def check_private_ip(repo: Repo) -> List[Finding]:
    out = []
    for rel in repo.files:
        if rel.startswith(PRIVATE_IP_OK):
            continue
        found = lines_of(PRIVATE_IP_RE, repo.text(rel))
        if found:   # 값은 찍지 않는다
            out.append(Finding("W-12", rel, "사설 IP 주소 꼴이 있습니다%s — 사내 주소는 커밋하지 않습니다. 지어낸 예는 docs/SPEC.md · tests/vectors/ 에 둡니다"
                               % also(found), found[0]))
    return out


# ─────────────────────────────────────────────────────────────── W-11 README 의 테스트 수

TEST_CLAIM_RE = re.compile(r"테스트\s*(\d+)(?!\d|\.\d)")


def count_tests(root: str) -> Tuple[Optional[int], str]:
    """(테스트 수, 오류). unittest 가 찾는 그대로 센다 — 테스트 모듈을 불러오므로 별도 프로세스에서"""
    code = ("import json, unittest\n"
            "l = unittest.TestLoader(); s = l.discover('tests')\n"
            "print(json.dumps({'count': s.countTestCases(), 'errors': len(getattr(l, 'errors', []))}))")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, "-c", code], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=300, env=env)
        res = json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        return None, "테스트를 불러오지 못했습니다 (%s)" % e.__class__.__name__
    if res["errors"]:
        return None, "테스트 %d개를 불러오지 못했습니다" % res["errors"]
    return int(res["count"]), ""


def check_readme_tests(repo: Repo, run_tests: bool = True) -> List[Finding]:
    if not run_tests:
        repo.notes.append("README 의 테스트 수 확인을 건너뛰었습니다 (--no-tests)")
        return []
    if not repo.has("README.md") or not os.path.isdir(repo.abs("tests")):
        return []                           # 없는 것은 필수 파일 검사가 알린다
    text = repo.text("README.md")
    claims = [(int(m.group(1)), line_of(text, m.start())) for m in TEST_CLAIM_RE.finditer(text)]
    if not claims:
        return [Finding("W-11", "README.md", "README 에 `테스트 N` 이 없습니다 (사양 줄에 돌려서 얻은 수를 적습니다)")]
    count, err = count_tests(repo.root)
    if err:
        return [Finding("W-11", "tests", err)]
    return [Finding("W-11", "README.md", "테스트 수를 %d 이라고 적었지만 실제는 %d 입니다" % (n, count), ln)
            for n, ln in claims if n != count]


# ─────────────────────────────────────────────────────────────── W-12 사내 낱말 (선택)

def read_words(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return [w for w in (ln.strip() for ln in f) if w]


def check_internal_words(repo: Repo, words_file: Optional[str]) -> List[Finding]:
    """낱말 목록 파일의 낱말 (대소문자 무시) 이 추적 파일의 이름 · 글에 있는지. 낱말 · 파일 이름은 찍지 않는다 — 개수만"""
    if not words_file:
        repo.notes.append("사내 낱말 검사를 건너뛰었습니다 (--internal-words <파일> 로 켭니다)")
        return []
    try:
        words = read_words(words_file)
    except (OSError, UnicodeError):
        return [Finding("W-12", "-", "사내 낱말 목록 파일을 읽지 못했습니다 — 검사하지 못했으므로 위반으로 셉니다")]
    if not words:
        return [Finding("W-12", "-", "사내 낱말 목록이 비어 있습니다 — 검사하지 못했으므로 위반으로 셉니다")]
    lowered = [w.casefold() for w in words]
    found: Set[int] = set()
    files = 0
    for rel in repo.files:
        hay = (rel + "\n" + repo.text(rel)).casefold()
        hit = {i for i, w in enumerate(lowered) if w in hay}
        if hit:
            files += 1
            found |= hit
    repo.notes.append("사내 낱말 검사: 목록 %d개 · 발견 %d개 · 파일 %d개 (낱말 · 파일 이름은 찍지 않습니다)" % (len(words), len(found), files))
    if not found:
        return []
    return [Finding("W-12", "-", "사내 낱말 %d개가 파일 %d개에 있습니다 (낱말 · 파일 이름은 찍지 않습니다)" % (len(found), files))]


# ─────────────────────────────────────────────────────────────── 실행

def run_checks(repo: Repo, run_tests: bool = True, words_file: Optional[str] = None) -> List[Finding]:
    findings: List[Finding] = []
    for check in (check_required, check_plugin_files, check_dependencies, check_network, check_secrets, check_private_ip):
        findings += check(repo)
    findings += check_readme_tests(repo, run_tests)
    findings += check_internal_words(repo, words_file)
    findings.sort(key=lambda f: (f.rule, f.path, f.line))
    return findings


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "사용법 오류: %s\n" % message)


def main(argv: Optional[List[str]] = None, out=None) -> int:
    out = out or sys.stdout
    ap = _Parser(description="diode 규칙 검사기 (RULES.md)", allow_abbrev=False)
    ap.add_argument("--strict", action="store_true", help="위반이 있으면 종료 코드 1 (차단 모드)")
    ap.add_argument("--no-tests", action="store_true", help="README 의 테스트 수 확인을 건너뜀")
    ap.add_argument("--internal-words", metavar="파일", default=None, help="사내 낱말 목록 (한 줄에 하나) — 낱말은 찍지 않는다")
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    repo = Repo(args.root)
    findings = run_checks(repo, run_tests=not args.no_tests, words_file=args.internal_words)
    out.write("diode 규칙 검사 · 파일 %d개\n" % len(repo.files))
    for f in findings:
        out.write("  × %s  %s  %s\n" % (f.rule, f.path + (":%d" % f.line if f.line else ""), f.msg))
    if not findings:
        out.write("  √ 걸린 것이 없습니다\n")
    for n in repo.notes:
        out.write("  · %s\n" % n)
    out.write("\n위반 %d%s\n" % (len(findings), "" if args.strict or not findings else " · 경고 모드 (--strict 면 종료 코드 1)"))
    out.write("결과: OK\n" if not findings else "결과: 점검 실패\n")
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
