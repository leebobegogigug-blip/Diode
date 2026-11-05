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
PENDING_CASES = (["mcp"], ["hook", "prompt"], ["--statusline"], ["--status", "--json"], ["--status", "--json", "--room", "x"],
                 ["propose", "r.json"], ["confirm", "req.json"], ["lib", "names", "pkg"])


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
        for argv in PENDING_CASES:
            with self.subTest(argv):
                code, out, err = run(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("아직 없음 (v0.0)", err)

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
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_version(self):
        self.assertEqual(self.call("version"), (0, "Diode 0.0.1\n", ""))

    def test_check(self):
        code, out, err = self.call("check")
        self.assertEqual((code, last_line(out)), (0, "결과: OK"))
        self.assertEqual(err, "")

    def test_pending_command(self):
        code, out, err = self.call("mcp")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("아직 없음 (v0.0)", err)

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

    def test_skill_placeholder(self):
        text = read("skills/diode/SKILL.md")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        self.assertIsNotNone(m, "frontmatter 가 없다")
        front = dict(ln.split(": ", 1) for ln in m.group(1).splitlines())
        self.assertEqual(front["name"], "diode")
        self.assertIn("개발 중 (v0.0)", front["description"])
        self.assertIn("아직 아무것도 막지 않는다", front["description"])
        self.assertTrue(m.group(2).strip())
        self.assertLessEqual(len(m.group(2).strip().splitlines()), 4)     # 자리표시 — 본문은 두세 줄

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
        self.assertIn("개발 중 (v0.0) — 아직 아무것도 막지 않습니다. 설치하지 마세요.", first)
        self.assertIn("이름은 비유입니다 — 하드웨어 데이터 다이오드가 아닙니다.", text)
        self.assertIn("화면 문법은 소형 하드웨어 계측기(Teenage Engineering 류)에서 영감을 받았고, 해당 회사와는 관련이 없습니다.", text)
        self.assertIn("파이썬 3.8+ · 표준 라이브러리만", text)
        self.assertRegex(text, r"테스트 \d+ · WINDOWS \+ UBUNTU CI")
        for target in ("docs/PLAN.md", "docs/SPEC.md", "docs/BLUEPRINT.md", "RULES.md"):
            self.assertIn(target, text)
        self.assertEqual(len(re.findall(r"테스트\s*\d+", text)), 1)       # 검사기가 비교하는 수는 사양 줄의 하나뿐
        self.assertNotIn("<img", text)                                     # 그림은 아직 없다

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
        self.assertIn("v0.1 에서 채운다", text)

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
