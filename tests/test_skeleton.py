# -*- coding: utf-8 -*-
"""뼈대 시험 — diode.py 의 version · help · check · 아직 없는 명령 · 종료 코드, 이름 · 버전 상수, 플러그인 파일
(plugin.json · marketplace.json · SKILL.md), .gitignore · .gitattributes · 워크플로, 문서의 약속 (고지 · 필수 절 · 조항 · 링크).
이 PC 의 실제 설정 · 데이터 폴더는 건드리지 않는다 — HOME · LOCALAPPDATA · DIODE_HOME 을 임시 폴더로 옮겨 부른다 (W-06)."""
import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import diodelib  # noqa: E402

spec = importlib.util.spec_from_file_location("diode_cli", os.path.join(ROOT, "diode.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

PINNED = ("13e56a0a5801da56dc18523363cd219ebf6d2e21", "8df8bca44a80a8034e343f646967e2eea744a28b")   # works 고정 커밋 (RULES.md)
DOCS = ("README.md", "INSTALL.md", "RULES.md", "AGENTS.md", "docs/MANUAL.md", "docs/INHOUSE.md")
MINE = DOCS + ("diode.py", "diodelib/__init__.py", "tools/diode_check.py", "skills/diode/SKILL.md",
               "tests/test_skeleton.py", "tests/test_diode_check.py", ".github/workflows/diode.yml")
# Claude Code 문서의 plugin.json 칸 표 (2.1.318 · 2026-11-05 에 읽음) — 이 밖의 최상위 칸은 validate 가 경고한다
MANIFEST_FIELDS = {"$schema", "name", "displayName", "version", "description", "author", "homepage", "repository", "license",
                   "keywords", "metadata", "icon", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl",
                   "defaultEnabled", "dependencies", "settings", "userConfig", "types", "channels", "skills", "commands",
                   "agents", "hooks", "mcpServers", "lspServers", "outputStyles", "workflows", "experimental"}


def read_path(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read(rel):
    return read_path(os.path.join(ROOT, *rel.split("/")))


def exists(rel):
    return os.path.exists(os.path.join(ROOT, *rel.split("/")))


def home_env(home):
    return {"HOME": home, "USERPROFILE": home, "LOCALAPPDATA": os.path.join(home, "AppData", "Local")}


def run(*argv, env=None):
    """diode.main 을 프로세스 안에서 부른다. env 를 주면 그 환경 변수만 있는 것처럼 (나머지는 비운다)"""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env if env is not None else {}, clear=env is not None):
        code = cli.main(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def last_line(text):
    return text.rstrip("\n").splitlines()[-1]


# ─────────────────────────────────────────────────────────────── 이름 · 버전

class TestConstants(unittest.TestCase):
    def test_names_and_version(self):
        self.assertEqual((diodelib.APP, diodelib.NAME), ("diode", "Diode"))
        self.assertRegex(diodelib.VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_matches_the_plugin_manifest(self):
        self.assertEqual(json.loads(read(".claude-plugin/plugin.json"))["version"], diodelib.VERSION)

    def test_init_holds_only_the_constants(self):
        """AGENTS.md: diodelib/__init__.py 에는 이름 · 버전 상수만 둔다"""
        tree = ast.parse(read("diodelib/__init__.py"))
        body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
        names = [t.id for n in body for t in n.targets] if all(isinstance(n, ast.Assign) for n in body) else None
        self.assertEqual(names, ["APP", "NAME", "VERSION"])


# ─────────────────────────────────────────────────────────────── diode.py (프로세스 안)

class TestCommands(unittest.TestCase):
    def test_version(self):
        code, out, err = run("version")
        self.assertEqual((code, out, err), (0, "Diode 0.0.1\n", ""))
        self.assertEqual(out.strip(), "%s %s" % (diodelib.NAME, diodelib.VERSION))

    def test_aliases(self):
        self.assertEqual(run("--version"), run("version"))
        self.assertEqual(run("-h"), run("help"))
        self.assertEqual(run("--help"), run("help"))

    def test_help_lists_every_command(self):
        code, out, err = run("help")
        self.assertEqual((code, err), (0, ""))
        for name in ("version", "help", "check", "mcp", "hook", "--statusline", "--status", "propose", "confirm", "scan", "lib"):
            self.assertIn(name, out)
        self.assertIn("개발 중", out)

    def test_pending_commands_say_so_and_exit_2(self):
        """아직 없는 명령 (PENDING) 은 아직 없음을 알리고 2 로 끝난다 - 지금은 없어서 (lib names 가 마지막이었다) 가짜 하나를 끼워 시험한다"""
        with mock.patch.object(cli, "PENDING", (("future", "future x                       없는 명령"),)):
            for argv in (["future"], ["future", "x"]):
                with self.subTest(argv):
                    code, out, err = run(*argv)
                    self.assertEqual(code, 2)
                    self.assertEqual(out, "")
                    self.assertIn("아직 없음 (v0.0)", err)
                    self.assertIn("future", err)

    def test_lib_names_is_a_real_command_now(self):
        """lib names 는 더 이상 '아직 없음' 이 아니다 (SP-16) - 허용 목록이 빈 곳에서는 고정 문구와 2 (자세한 시험은 test_libnames.py)"""
        self.assertNotIn("lib", [n for n, _ in cli.PENDING + cli.PENDING_FLAGS])
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run("lib", "names", "pkg", env=dict(home_env(tmp), DIODE_HOME=os.path.join(tmp, "data")))
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("사용법 오류: 허용 목록 (policy.lib_allow) 에 없는 이름입니다"), err)
            self.assertNotIn("아직 없음", err)
            self.assertEqual(os.listdir(tmp), [])

    def test_usage_errors_exit_2_with_a_korean_message(self):
        for argv in ([], ["frobnicate"], ["check", "extra"], ["--json"], ["--room", "x", "check"], ["--status", "check"],
                     ["--statusline", "--status"], ["--room"], ["--stat"]):
            with self.subTest(argv):
                code, out, err = run(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("사용법 오류: "), err)
                self.assertIn("help", err)

    def test_every_pending_command_is_in_the_manual(self):
        manual = read("docs/MANUAL.md")
        for name, _ in cli.PENDING + cli.PENDING_FLAGS:
            self.assertIn("`%s" % name, manual)


class TestCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = self._tmp.name
        self.default = (os.path.join(self.home, "AppData", "Local", "diode") if os.name == "nt"
                        else os.path.join(self.home, ".local", "share", "diode"))

    def test_default_location_is_ok(self):
        code, out, err = run("check", env=home_env(self.home))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(last_line(out), "결과: OK")
        self.assertIn(self.default, out)
        self.assertIn("기본 위치", out)
        self.assertIn("3.8", out)

    def test_check_creates_nothing(self):
        run("check", env=home_env(self.home))
        run("check", env=dict(home_env(self.home), DIODE_HOME=os.path.join(self.home, "x", "y")))
        self.assertEqual(os.listdir(self.home), [])

    def test_test_home_needs_a_human(self):
        folder = os.path.join(self.home, "elsewhere")
        code, out, err = run("check", env=dict(home_env(self.home), DIODE_HOME=folder))
        self.assertEqual(code, 3)
        self.assertEqual(last_line(out), "결과: 확인 필요")
        self.assertIn(folder, out)
        self.assertIn("DIODE_HOME", out)
        self.assertNotIn(self.default, out)

    def test_empty_test_home_is_the_same_as_none(self):
        code, out, _ = run("check", env=dict(home_env(self.home), DIODE_HOME=""))
        self.assertEqual((code, last_line(out)), (0, "결과: OK"))

    def test_existing_data_folder(self):
        os.makedirs(self.default)
        code, out, _ = run("check", env=home_env(self.home))
        self.assertEqual((code, last_line(out)), (0, "결과: OK"))
        self.assertIn("있음", out)

    def test_data_folder_that_is_a_file_fails(self):
        os.makedirs(os.path.dirname(self.default))
        with open(self.default, "w") as f:
            f.write("x")
        code, out, _ = run("check", env=home_env(self.home))
        self.assertEqual((code, last_line(out)), (1, "결과: 점검 실패"))

    def test_old_python_fails(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, home_env(self.home), clear=True):
            self.assertEqual(cli.check(out, version_info=(3, 7, 9)), 1)
            self.assertEqual(last_line(out.getvalue()), "결과: 점검 실패")
            self.assertEqual(cli.check(io.StringIO(), version_info=(3, 8, 0)), 0)
            self.assertEqual(cli.check(io.StringIO(), version_info=(3, 13, 1)), 0)

    def test_last_line_is_always_one_of_the_three(self):
        for env in (home_env(self.home), dict(home_env(self.home), DIODE_HOME=self.home)):
            _, out, _ = run("check", env=env)
            self.assertIn(last_line(out), ("결과: OK", "결과: 확인 필요", "결과: 점검 실패"))


# ─────────────────────────────────────────────────────────────── diode.py (스크립트로)

class TestEntryScript(unittest.TestCase):
    """다른 폴더에서 스크립트로 부른다 (훅 · 마켓플레이스가 부르는 모양) — 출력은 UTF-8"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        self.env.pop("DIODE_HOME", None)
        self.env.update(home_env(self._tmp.name))

    def call(self, *argv):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py")] + list(argv), cwd=self._tmp.name, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        # Windows 의 텍스트 모드 표준 출력은 줄 끝이 \r\n 이다 (프로그램 잘못이 아니다) — 비교는 \n 으로 맞춘다
        return p.returncode, p.stdout.decode("utf-8").replace("\r\n", "\n"), p.stderr.decode("utf-8").replace("\r\n", "\n")

    def test_version(self):
        self.assertEqual(self.call("version"), (0, "Diode 0.0.1\n", ""))

    def test_check(self):
        code, out, err = self.call("check")
        self.assertEqual((code, last_line(out)), (0, "결과: OK"))
        self.assertEqual(err, "")

    def test_lib_names_command(self):
        """스크립트로 부른 lib names - 허용 목록에 없는 이름은 아직 없음이 아니라 고정 문구와 2, 이름을 되풀이하지 않고 아무것도 만들지 않는다"""
        code, out, err = self.call("lib", "names", "pkg")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("사용법 오류: 허용 목록 (policy.lib_allow) 에 없는 이름입니다"), err)
        self.assertNotIn("아직 없음", err)
        self.assertNotIn("pkg", err)
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_no_command(self):
        code, out, err = self.call()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("사용법 오류", err)

    def test_nothing_is_created_in_the_home(self):
        self.call("check")
        self.call("version")
        self.assertEqual(os.listdir(self._tmp.name), [])


# ─────────────────────────────────────────────────────────────── 플러그인 파일

class TestPluginFiles(unittest.TestCase):
    def setUp(self):
        self.plugin = json.loads(read(".claude-plugin/plugin.json"))
        self.market = json.loads(read(".claude-plugin/marketplace.json"))

    def test_plugin_manifest(self):
        p = self.plugin
        self.assertEqual((p["name"], p["displayName"]), ("diode", "Diode"))
        self.assertEqual(p["repository"], "https://github.com/leebobegogigug-blip/Diode")
        self.assertEqual(p["author"], {"name": "diode"})
        self.assertTrue(p["keywords"] and all(isinstance(k, str) for k in p["keywords"]))
        self.assertIn("개발 중 (v0.0)", p["description"])
        self.assertEqual(sorted(set(p) - MANIFEST_FIELDS), [])

    def test_marketplace_manifest(self):
        m = self.market
        self.assertEqual(m["name"], "diode")
        self.assertIn("name", m["owner"])
        self.assertEqual(len(m["plugins"]), 1)
        entry = m["plugins"][0]
        self.assertEqual(entry["name"], self.plugin["name"])      # 항목 이름과 plugin.json 의 이름이 같아야 설치된다
        self.assertIn(entry["source"], (".", "./"))               # 이 저장소 루트가 플러그인
        self.assertNotIn("version", entry)                        # plugin.json 의 version 이 앞서고, 둘 다 있으면 validate 가 경고한다

    def test_skill(self):
        text = read("skills/diode/SKILL.md")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        self.assertIsNotNone(m, "frontmatter 가 없다")
        front = dict(ln.split(": ", 1) for ln in m.group(1).splitlines())
        self.assertEqual(front["name"], "diode")
        self.assertIn("PH_", front["description"])
        self.assertLess(len(front["description"]), 400)                  # 모든 세션에 실리는 글이라 짧게
        body = m.group(2)
        self.assertLess(len(body.splitlines()), 80)
        for needle in ("mcp__plugin_diode_hub__dispatch", "inbox", "ToolSearch", "E-01", "E-20", "벽이 아니다"):
            self.assertIn(needle, body)
        # 안내문은 벽이 아니다 (AL-09) — 사내 이름 · 실제 경로 · 주소를 담지 않는다
        for bad in ("http", "D:\\", "/home/", "opencode"):
            self.assertNotIn(bad, body)

    def test_only_one_skill_and_it_is_named_like_the_plugin(self):
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "skills"))), ["diode"])

    def test_no_files_that_the_plugin_must_not_have(self):
        self.assertFalse(exists("CLAUDE.md"), "플러그인 루트의 CLAUDE.md 는 claude plugin validate 가 경고한다 (AGENTS.md)")
        self.assertFalse(exists("bin"), "bin/ 은 Bash PATH 에 올라가고 claude.ai · Cowork 가 설치하지 않는다 (RULES.md › W-01)")


# ─────────────────────────────────────────────────────────────── 저장소 파일

def run_scripts(workflow):
    """워크플로의 run: 스크립트 글 (한 줄 · 블록 모두)"""
    lines, found, i = workflow.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        base, value = len(m.group(1)), m.group(2).strip()
        if value[:1] in ("|", ">"):
            block = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > base):
                block.append(lines[i])
                i += 1
            found.append("\n".join(block))
        else:
            found.append(value)
            i += 1
    return found


class TestRepoFiles(unittest.TestCase):
    def test_gitignore(self):
        lines = {ln.strip() for ln in read(".gitignore").splitlines()}
        for want in ("kit/out/", "__pycache__/", "*.py[cod]", "*.tmp", "binding.local.json", "adapters.local/"):
            self.assertIn(want, lines)
        self.assertTrue({"config.json", "/config.json"} & lines)

    def test_gitattributes(self):
        lines = {ln.strip() for ln in read(".gitattributes").splitlines()}
        for want in ("* text=auto eol=lf", "*.ps1 text eol=crlf", "*.cmd text eol=crlf", "*.bat text eol=crlf"):
            self.assertIn(want, lines)

    def test_workflow(self):
        wf = read(".github/workflows/diode.yml")
        for want in ("windows-latest", "ubuntu-22.04", '"3.8"', '"3.13"', "actions/checkout@", "actions/setup-python@",
                     "pip install jsonschema", "python -m unittest discover -s tests -v", "python tools/diode_check.py --strict"):
            self.assertIn(want, wf)
        self.assertNotIn("paths:", wf)                            # 모든 push · PR 에서 저장소 전체를 본다

    def test_workflow_keeps_expressions_out_of_scripts(self):
        """${{ }} 를 run 스크립트에 직접 넣으면 값이 셸 글로 풀린다 — env 로 넘긴다"""
        scripts = run_scripts(read(".github/workflows/diode.yml"))
        self.assertGreaterEqual(len(scripts), 3)
        for script in scripts:
            self.assertNotIn("${{", script)

    def test_run_scripts_helper(self):
        wf = "steps:\n  - run: echo ${{ x }}\n  - name: a\n    run: |\n      echo one\n\n      echo two ${{ y }}\n    env:\n      Z: ${{ z }}\n  - run: ls\n"
        self.assertEqual(run_scripts(wf), ["echo ${{ x }}", "      echo one\n\n      echo two ${{ y }}", "ls"])


# ─────────────────────────────────────────────────────────────── 문서

def slug(heading):
    """GitHub 제목 앵커의 근사 — 소문자 · 글자 · 숫자 · 밑줄 · 하이픈 · 빈칸만 남기고 빈칸을 하이픈으로"""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def headings(text):
    out, fenced = [], False
    for ln in text.splitlines():
        if ln.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"^#{1,6} ", ln):
            out.append(ln.lstrip("#").strip())
    return out


def links(text):
    return re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'(?:href|src)="([^"]+)"', text)


def broken_links(rel):
    base, bad = os.path.dirname(os.path.join(ROOT, *rel.split("/"))), []
    for target in links(read(rel)):
        if re.match(r"^[a-z][a-z0-9+.\-]*:", target, re.I) or target.startswith("//"):
            continue
        path, _, frag = target.partition("#")
        full = os.path.normpath(os.path.join(base, path)) if path else os.path.join(ROOT, *rel.split("/"))
        if not os.path.exists(full):
            bad.append(target)
        elif frag and full.endswith(".md") and frag not in {slug(h) for h in headings(read_path(full))}:
            bad.append(target)
    return bad


class TestDocs(unittest.TestCase):
    def test_all_docs_exist(self):
        for rel in DOCS:
            self.assertTrue(exists(rel), rel)

    def test_relative_links_and_anchors_resolve(self):
        for rel in DOCS:
            with self.subTest(rel):
                self.assertEqual(broken_links(rel), [])

    def test_link_helpers(self):
        self.assertEqual(slug("09 규칙 — 새 저장소 `diode` 의 RULES.md 원고"), "09-규칙--새-저장소-diode-의-rulesmd-원고")
        self.assertEqual(slug("SP-15 설정 (format 1)"), "sp-15-설정-format-1")
        self.assertEqual(headings("# a\n```\n# not\n```\n## b c\n"), ["a", "b c"])

    def test_works_links_are_pinned_to_a_commit(self):
        for rel in DOCS:
            text = read(rel)
            for ref in re.findall(r"github\.com/leebobegogigug-blip/Works/(?:blob|tree)/([^/]+)/", text):
                self.assertIn(ref, PINNED, "%s: works 링크가 고정 커밋이 아니다" % rel)
            self.assertNotRegex(text, r"Works/(?:blob|tree)/(?:main|master)\b")

    def test_readme_promises(self):
        text = read("README.md")
        first = next(ln for ln in text.splitlines() if ln.strip())
        self.assertIn("개발 중 (v0.0) — 합성 자료로만 시험했다. 사내 자체 검증을 마치기 전에는 real data 에 쓰지 않는다.", first)
        self.assertIn("이름은 비유다 — 하드웨어 데이터 다이오드가 아니다.", text)
        self.assertIn("화면 문법은 소형 하드웨어 계측기(Teenage Engineering 류)에서 영감을 받았으며, 해당 회사와는 관련이 없다.", text)
        self.assertIn("파이썬 3.8+ · 표준 라이브러리만", text)
        self.assertRegex(text, r"테스트 \d+ · WINDOWS \+ UBUNTU CI")
        for target in ("docs/PLAN.md", "docs/SPEC.md", "docs/BLUEPRINT.md", "RULES.md"):
            self.assertIn(target, text)
        self.assertEqual(len(re.findall(r"테스트\s*\d+", text)), 1)       # 검사기가 비교하는 수는 사양 줄의 하나뿐
        # 그림: 가리키는 파일이 있고 · 대체 글이 있고 · 너무 무겁지 않다 (README 가 느려지지 않게 2 MiB 이하)
        imgs = re.findall(r'<img\s[^>]*src="([^"]+)"[^>]*alt="([^"]+)"', text)
        self.assertEqual(len(imgs), 1)
        src, alt = imgs[0]
        self.assertTrue(os.path.isfile(os.path.join(ROOT, src)), src)
        self.assertLess(os.path.getsize(os.path.join(ROOT, src)), 2 * 1024 * 1024)
        self.assertGreater(len(alt), 10)
        self.assertNotIn("http", src)                                       # 바깥 주소로 가져오지 않는다 (W-03)
        self.assertIn("공식 그림이 아니다", text)                           # 제품 그림 고지

    def test_w10_exception_names_the_one_banner(self):
        rules = read("RULES.md")
        self.assertEqual(rules.count("docs/img/diode-banner.png"), 1)        # 예외는 이 한 장뿐
        self.assertIn("한 장에만 걸린다", rules)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "docs", "img", "diode-banner.png")))
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "docs", "img"))), ["diode-banner.png"])   # 예외가 슬그머니 늘지 않게

    def test_readme_uses_the_blueprint_metaphor(self):
        text = read("README.md")
        for word in ("접합", "순방향", "역방향", "봉인 보고"):
            self.assertIn(word, text)
            self.assertIn(word, read("docs/BLUEPRINT.md"))

    def test_manual_opens_with_the_name_notice_and_has_the_development_commands(self):
        text = read("docs/MANUAL.md")
        self.assertIn("이름은 비유입니다 — 하드웨어 데이터 다이오드가 아닙니다.", text.split("## ", 1)[0])
        self.assertIn("python -m unittest discover -s tests", text)
        self.assertIn("python tools/diode_check.py", text)
        self.assertIn("알려진 한계", headings(text))
        self.assertIn("S-09", text.split("## 알려진 한계", 1)[1])

    def test_install_has_the_required_sections(self):
        text = read("INSTALL.md")
        heads = " | ".join(headings(text))
        for need in ("규칙", "보고", "문제 해결", "업데이트", "제거"):
            self.assertIn(need, heads)
        self.assertIn("[질문]", text)
        for place in ("D:\\claude\\diode", "D:\\claude\\room", "%LOCALAPPDATA%\\diode"):
            self.assertIn(place, text)

        # 뼈대가 아니다: 채우지 않은 자리 · 뼈대 문구가 없고, 실제 주소도 없다 (W-12 — 주소는 [질문] 으로 받는다)
        for gone in ("v0.1", "뼈대"):
            self.assertNotIn(gone, text)
        self.assertNotRegex(text, r"https?://")
        self.assertIn("<저장소 주소>", text)

        # 단계 0–9 가 차례로 있다. 1–8 단계마다 명령(코드 블록) → 확인 → 실패하면 의 표지와 [질문] 이 있다
        parts = re.split(r"^## (\d+)\. (.+)$", text, flags=re.M)
        steps = {}
        for i in range(1, len(parts) - 2, 3):
            steps[int(parts[i])] = (parts[i + 1], parts[i + 2].split("\n## ", 1)[0])
        self.assertEqual(sorted(steps), list(range(0, 10)))
        positions = [m.start() for m in re.finditer(r"^## \d+\. ", text, flags=re.M)]
        self.assertEqual(positions, sorted(positions))
        for n, word in {1: "파이썬", 2: "코드", 3: "플러그인", 4: "설정", 5: "방", 6: "점검", 9: "보고"}.items():
            self.assertIn(word, steps[n][0], "%d단계 제목" % n)
        for n in (7, 8):
            self.assertIn("(선택)", steps[n][0], "%d단계는 선택이다" % n)
        for n in range(1, 9):
            body = steps[n][1]
            for mark in ("```", "**확인**", "**실패하면**", "[질문]"):
                self.assertIn(mark, body, "%d단계에 %s 가 없다" % (n, mark))
            self.assertLess(body.index("```"), body.index("**확인**"), "%d단계: 명령이 확인보다 먼저다" % n)
            self.assertLess(body.index("**확인**"), body.index("**실패하면**"), "%d단계: 확인이 실패하면보다 먼저다" % n)
        # 명령은 어느 셸에서나 돈다: 드라이브 경로는 큰따옴표 안에 있다 (S-05)
        for ln in text.splitlines():
            if ln.strip().startswith(("python ", "git ", "claude ", "/plugin ")):
                self.assertNotRegex(ln, r'(?<!")\b[A-Za-z]:\\', ln)
        # 단계가 가리키는 명령 · 절
        self.assertIn('claude plugin marketplace add "D:\\claude\\diode"', steps[3][1])
        self.assertIn("claude plugin install diode@diode", steps[3][1])
        self.assertIn('/plugin marketplace add "D:\\claude\\diode"', steps[3][1])
        self.assertIn("/plugin install diode@diode", steps[3][1])
        self.assertIn("py -3", steps[1][1])                                  # `python` 이름만 인정한다
        self.assertIn('git -C "D:\\claude\\diode" pull --ff-only', steps[2][1])
        self.assertIn("setup --check", steps[6][1])
        self.assertIn("kit/inhouse-questions.md", steps[8][1])
        for word in ("백업", "diode-worker", "docs/MANUAL.md"):
            self.assertIn(word, steps[7][1])
        for rule in ("사전", "원자료 폴더", "직접 입력"):                         # 사내 단어는 사람이 창에서만 (AL-11 · AL-12)
            self.assertIn(rule, steps[4][1])
        for label in ("위치", "파이썬", "코드", "플러그인", "설정", "방", "일꾼", "점검", "멈춘 곳", "쓰는 법"):
            self.assertRegex(steps[9][1], r"(?m)^- %s\s*:" % label)
        sections = {h: text.split("\n## " + h, 1)[1].split("\n## ", 1)[0] for h in ("업데이트", "제거")}
        self.assertIn('git -C "D:\\claude\\diode" pull --ff-only', sections["업데이트"])
        self.assertIn("claude plugin update diode@diode", sections["업데이트"])
        self.assertIn("claude plugin uninstall diode@diode", sections["제거"])
        self.assertIn("claude plugin marketplace remove diode", sections["제거"])
        self.assertGreaterEqual(sections["제거"].count("[질문]"), 4)           # 방 · 데이터 · 소스 · 일꾼은 묻고서야 지운다
        self.assertIn("감사 기록", sections["제거"])

        # 문제 해결 표의 문구는 코드가 찍는 그대로다 — 코드가 바뀌면 이 시험이 문서를 고치게 한다
        from diodelib import hook as hook_mod, setup as setup_mod
        setup_src, cli_src = read("diodelib/setup.py"), read("diode.py")
        for sentence in setup_mod.REFUSE_TEXT.values():                      # 방 거절 여섯
            self.assertIn(sentence, text)
        self.assertEqual(sorted(setup_mod.REFUSE_TEXT), ["git", "guide", "nonempty", "path", "plugin", "raw"])
        for key in ("unset", "e20", "changed", "raw_prompt", "auto"):
            self.assertIn(hook_mod.MSG[key], text, key)
        self.assertIn(hook_mod.MSG["guide"].replace("%d", "<개수>"), text)
        for phrase in ("사전이 비어 있음 — 보내기를 막습니다", "원자료 폴더 목록이 비어 있음 — 보내기를 막습니다",
                       "사내 LLM 판정 (D7) 설정이 없음 — 보내기를 막습니다", "훅 자체 시험", "방이 ok 가 아님",
                       "설정을 읽지 못해 창을 열지 않았습니다", "사전 · 설정을 읽지 못함", "python 명령 (훅 · 허브가 부름)",
                       "방이 이미 있는데 설정이 바뀌었습니다 (changed) — 덮어쓰지 않습니다. 지우고 다시 만들거나 되돌리세요",
                       "방을 만들었습니다 (표지 · 방 설정 · outbox · inbox · work)", "방이 이미 있고 ok 입니다",
                       "정책 (사전 · 원자료 폴더) 이 비어 있는데 정책 창을 띄울 수 없습니다 (E-07) - 화면이 없거나 이 파이썬에 tkinter 가 없습니다",
                       "정책 (사전 · 원자료 폴더) 이 비어 있어 정책 창을 엽니다 — 창에서 직접 입력하고 [저장] 하세요",
                       "단어는 이 대화로 보내지 않습니다 (입력하면 곧바로 Claude 로 나갑니다)",
                       "저장한 뒤 /diode:setup 을 다시 실행하면 방을 만들고 점검합니다",
                       "일꾼 명령 문제:", "일꾼 명령에 문제가 있음", "일 넘기기는 E-01",
                       "실행 파일을 PATH 에서 찾지 못함",
                       "Windows .cmd 껍데기에 {prompt} 를 인자로 줌 (명령 주입 길 - 표준 입력으로 받게 {prompt} 를 빼세요)",
                       "안내 파일에 사전 단어가 있음 (L-29) — 지우거나 옮기세요 · 그 전에는 프롬프트가 막힙니다",
                       "안내 파일 (CLAUDE.md · AGENTS.md) 을 사전으로 검사하지 못함",
                       "없음 (/diode:room)", "changed (방 설정이 바뀜 — 막힘)"):      # 앞의 "방 " 은 코드가 서식으로 붙인다
            self.assertIn(phrase, text, phrase)
            self.assertTrue(phrase in setup_src, phrase)
        self.assertIn("방 없음 (/diode:room)", text)
        self.assertIn("방 changed (방 설정이 바뀜 — 막힘)", text)
        guide_line = "안내 파일 (사용자 범위 · 이 폴더와 위 폴더의 CLAUDE.md · AGENTS.md) 에 사전 단어가 %d개 있음 — Claude 가 모든 요청에 읽어 갑니다"
        self.assertTrue(guide_line in setup_src)
        self.assertIn(guide_line.replace("%d", "<n>"), text)
        for phrase in ("파이썬 3.8 이상이 필요합니다", "DIODE_HOME 이 설정되어 있습니다", "데이터 폴더 자리에 파일이 있습니다"):
            self.assertIn(phrase, text, phrase)
        for piece in ("이상이 필요합니다", "이 설정되어 있습니다", "데이터 폴더 자리에 파일이 있습니다", "diode.py %s: 실패 (E-20)",
                      "정책 창을 열었습니다 - "):
            self.assertTrue(piece in cli_src, piece)
        for phrase in ("diode.py room: 실패 (E-20)", "diode.py setup: 실패 (E-20)", "정책 창을 열었습니다 - "):
            self.assertIn(phrase, text, phrase)
        # 정책 창의 칸 · 버튼 · 제목 이름 (사람이 그 이름으로 찾는다)
        window_src = read("diodelib/policy_window.py")
        for label in ("01 사전", "02 원자료 폴더", "04 일꾼 명령", "06 방 자리", "06 llm", "Diode - 정책", "예시 넣기"):
            self.assertTrue(label in window_src, label)
            self.assertIn(label, text, label)
        # 플러그인이 실제로 싣는 것과 문서가 말하는 것이 같다 (claude plugin details 의 확인 줄)
        hooks = json.loads(read("hooks/hooks.json"))["hooks"]
        for event in hooks:
            self.assertIn(event, steps[3][1])
        for server in json.loads(read(".mcp.json"))["mcpServers"]:
            self.assertIn("`%s`" % server, steps[3][1])
        for cmd in sorted(os.listdir(os.path.join(ROOT, "commands"))):
            name = cmd[:-len(".md")]
            self.assertIn("/diode:" + name, text)
            self.assertIn("`%s`" % name, steps[3][1])
        self.assertIn("2.1.295", read("docs/PLAN.md"))                        # 3단계가 요구하는 Claude Code 판의 출처
        self.assertIn("2.1.295", steps[3][1])

    def test_inhouse_keeps_the_boundary(self):
        text = read("docs/INHOUSE.md")
        for word in ("adapters.local", "D:\\claude\\diode", "diff", "어댑터 계약"):
            self.assertIn(word, text)

    def test_rules_have_twelve_constitution_articles(self):
        found = re.findall(r"^### (W-\d\d) ", read("RULES.md"), re.M)
        self.assertEqual(found, ["W-%02d" % n for n in range(1, 13)])

    def test_agents_summary_matches_the_rules(self):
        """AGENTS.md 의 헌법 요약 제목이 RULES.md 와 같다 (works 검사기의 RULES 검사와 같은 뜻)"""
        rules = {m.group(1): m.group(2).strip() for m in re.finditer(r"^### (W-\d\d) (.+)$", read("RULES.md"), re.M)}
        summary = {m.group(1): m.group(2).strip() for m in re.finditer(r"^- (W-\d\d) \*\*(.+?)\*\*", read("AGENTS.md"), re.M)}
        self.assertEqual(summary, rules)

    def test_agents_carries_the_working_rules(self):
        text = read("AGENTS.md")
        for want in ("docs/BLUEPRINT.md", "python -m unittest discover -s tests", "python tools/diode_check.py --strict",
                     "diode: 무엇 · 무엇", "kit/out/", "#d-05-", "#d-11-", "RULES.md", "docs/SPEC.md", "docs/PLAN.md"):
            self.assertIn(want, text)
        order = [text.index(x) for x in ("AGENTS.md → [RULES.md]", "[docs/SPEC.md]", "[docs/PLAN.md]")]
        self.assertEqual(order, sorted(order))                              # 읽는 순서

    def test_no_emoji_or_wide_symbols(self):
        wide = {"\u2713", "\u26a0", "\u2605"}                               # DESIGN.md › 03: 체크 · 경고 · 별 기호는 폭 2칸
        for rel in MINE:
            for ch in read(rel):
                self.assertFalse(0x1F000 <= ord(ch) <= 0x1FAFF or ch in wide, "%s: U+%04X" % (rel, ord(ch)))


if __name__ == "__main__":
    unittest.main()
