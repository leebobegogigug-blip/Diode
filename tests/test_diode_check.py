# -*- coding: utf-8 -*-
"""tools/diode_check.py 테스트 — 임시 폴더에 합성 저장소를 만들어 위반을 하나씩 일부러 넣고 잡는지 본다.
이 PC 의 실제 설정 · 데이터 폴더는 건드리지 않는다 (검사기는 읽기만 하고, 합성 저장소는 임시 폴더에만 만든다).
키 · 토큰 · 사설 주소처럼 보이는 값은 이어 붙여 만든다 — 파일에 그대로 쓰면 검사기가 이 시험 파일을 잡는다 (W-04 · W-12)."""
import importlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

spec = importlib.util.spec_from_file_location("diode_check", os.path.join(ROOT, "tools", "diode_check.py"))
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)


def secret(kind):
    """검사기가 잡아야 하는 값 — 이어 붙여 만든다"""
    return {
        "openai": "sk" + "-" + "a1B2c3D4e5F6g7H8i9J0k",
        "github": "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7",
        "aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "slack": "xo" + "xb-" + "1234567890-abcdefghij",
        "pem": "-----BEGIN " + "RSA PRIVATE KEY-----",
    }[kind]


def ip(*octets):
    return ".".join(str(o) for o in octets)


def importlib_invalidate():
    importlib.invalidate_caches()


GOOD = {
    "README.md": "# t\n\n테스트 1 · WINDOWS + UBUNTU CI\n",
    "INSTALL.md": "x\n",
    "docs/MANUAL.md": "x\n",
    "docs/INHOUSE.md": "x\n",
    "RULES.md": "x\n",
    "AGENTS.md": "x\n",
    ".gitignore": "x\n",
    ".gitattributes": "x\n",
    ".github/workflows/diode.yml": "name: diode\n",
    ".claude-plugin/plugin.json": json.dumps({"name": "diode", "version": "0.0.1"}),
    ".claude-plugin/marketplace.json": json.dumps({"name": "diode", "owner": {"name": "diode"},
                                                    "plugins": [{"name": "diode", "source": "./"}]}),
    "diode.py": "import os\nimport sys\nfrom diodelib import VERSION\n",
    "diodelib/__init__.py": "VERSION = '0.0.1'\n",
    "tests/test_one.py": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n",
}


class Synth(unittest.TestCase):
    """GOOD 로 만든 합성 저장소 (git 저장소가 아니다 — 폴더를 훑는 길)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.put(GOOD)

    def put(self, files):
        for rel, text in files.items():
            path = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

    def drop(self, rel):
        os.remove(os.path.join(self.root, *rel.split("/")))

    def run_dc(self, run_tests=False, words_file=None):
        return dc.run_checks(dc.Repo(self.root), run_tests=run_tests, words_file=words_file)

    def hits(self, rule=None, path=None, **kw):
        return [f for f in self.run_dc(**kw) if (rule is None or f.rule == rule) and (path is None or f.path == path)]

    def main(self, *argv):
        out = io.StringIO()
        code = dc.main(["--root", self.root] + list(argv), out=out)
        return code, out.getvalue()


class TestBaseline(Synth):
    def test_clean_repo_has_no_findings(self):
        """시험하는 테스트 수까지 포함해 (run_tests=True) 아무것도 안 걸린다"""
        self.assertEqual(self.run_dc(run_tests=True), [])

    def test_main_clean(self):
        code, out = self.main("--strict", "--no-tests")
        self.assertEqual(code, 0)
        self.assertEqual(out.rstrip().splitlines()[-1], "결과: OK")

    def test_main_reports_one_line_per_violation(self):
        self.put({"a.md": secret("openai"), "b.md": secret("aws")})
        code, out = self.main("--no-tests")
        lines = [ln for ln in out.splitlines() if ln.startswith("  × ")]
        self.assertEqual(len(lines), 2)
        self.assertEqual(out.rstrip().splitlines()[-1], "결과: 점검 실패")

    def test_exit_code_depends_on_strict(self):
        self.put({"a.md": secret("openai")})
        self.assertEqual(self.main("--no-tests")[0], 0)            # 경고 모드는 위반이 있어도 0
        self.assertEqual(self.main("--no-tests", "--strict")[0], 1)

    def test_usage_error_exits_2(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                dc.main(["--no-such-option"], out=io.StringIO())
        self.assertEqual(cm.exception.code, 2)


class TestRequired(Synth):
    def test_each_required_file(self):
        for rel in dc.REQUIRED:
            with self.subTest(rel):
                self.drop(rel)
                self.assertEqual([f.path for f in self.hits("W-01") if f.path == rel], [rel])
                self.put({rel: GOOD[rel]})

    def test_tests_folder_needs_a_test_file(self):
        self.drop("tests/test_one.py")
        self.assertEqual([f.path for f in self.hits("W-01")], ["tests/"])

    def test_non_test_file_in_tests_does_not_count(self):
        self.drop("tests/test_one.py")
        self.put({"tests/helper.py": "x = 1\n"})
        self.assertEqual([f.path for f in self.hits("W-01")], ["tests/"])


class TestPluginFiles(Synth):
    def test_invalid_json(self):
        self.put({".claude-plugin/plugin.json": "{"})
        found = self.hits("W-01", ".claude-plugin/plugin.json")
        self.assertEqual(len(found), 1)
        self.assertIn("JSON", found[0].msg)

    def test_wrong_plugin_name(self):
        self.put({".claude-plugin/plugin.json": json.dumps({"name": "other"})})
        self.assertEqual(len(self.hits("W-01", ".claude-plugin/plugin.json")), 1)

    def test_marketplace_name_and_entry(self):
        self.put({".claude-plugin/marketplace.json": json.dumps({"name": "other", "plugins": [{"name": "x"}]})})
        self.assertEqual(len(self.hits("W-01", ".claude-plugin/marketplace.json")), 2)

    def test_marketplace_without_plugins_list(self):
        self.put({".claude-plugin/marketplace.json": json.dumps({"name": "diode"})})
        self.assertEqual(len(self.hits("W-01", ".claude-plugin/marketplace.json")), 1)

    def test_optional_files_are_checked_only_when_present(self):
        self.assertEqual(self.hits("W-01"), [])
        self.put({".mcp.json": "{not json", "hooks/hooks.json": "[]"})
        self.assertEqual(sorted(f.path for f in self.hits("W-01")), [".mcp.json", "hooks/hooks.json"])

    def test_valid_optional_files_pass(self):
        self.put({".mcp.json": json.dumps({"mcpServers": {}}), "hooks/hooks.json": json.dumps({"hooks": {}})})
        self.assertEqual(self.hits("W-01"), [])


class TestDependencies(Synth):
    def runtime(self, source, rel="diodelib/x.py"):
        self.put({rel: source})
        return [f for f in self.hits("W-02") if f.path == rel]

    def test_stdlib_and_diodelib_pass(self):
        src = ("from __future__ import annotations\nimport os, sys, json, re, argparse, hashlib, secrets, subprocess\n"
               "import tkinter\nimport ctypes\nimport urllib.request\nimport msvcrt\n"
               "from diodelib import VERSION\nimport diodelib.scan\nfrom . import sibling\nfrom .other import thing\n")
        self.assertEqual(self.runtime(src), [])

    def test_missing_third_party(self):
        found = self.runtime("import definitely_not_installed_xyz\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 1)
        self.assertIn("definitely_not_installed_xyz", found[0].msg)

    def test_import_inside_function_and_try(self):
        src = ("def f():\n    import missing_in_function\n\n\ntry:\n    import missing_in_try\nexcept ImportError:\n    pass\n"
               "if True:\n    from missing_in_if import y\n")
        found = self.runtime(src)
        self.assertEqual([f.line for f in found], [2, 6, 10])

    def test_each_module_once_per_file(self):
        found = self.runtime("import missing_twice\nimport missing_twice\nfrom missing_twice import x\n")
        self.assertEqual(len(found), 1)

    def test_dynamic_imports_with_a_constant_name(self):
        src = "import importlib\nm = importlib.import_module('missing_dyn_a')\nn = __import__('missing_dyn_b')\n"
        found = self.runtime(src)
        self.assertEqual(len(found), 2)

    def test_site_packages_and_dist_packages(self):
        for folder in ("site-packages", "dist-packages"):
            with self.subTest(folder):
                name = "fakethird_" + folder.replace("-", "_")
                base = os.path.join(self.root, "libs", folder)
                os.makedirs(os.path.join(base, name))
                with open(os.path.join(base, name, "__init__.py"), "w") as f:
                    f.write("")
                sys.path.insert(0, base)
                importlib_invalidate()
                try:
                    found = self.runtime("import %s\n" % name, rel="diodelib/uses_third.py")
                finally:
                    sys.path.remove(base)
                    importlib_invalidate()
                self.assertEqual(len(found), 1)
                self.assertIn(folder, found[0].msg)

    def test_other_module_of_the_repo(self):
        self.put({"tools/helper.py": "x = 1\n"})
        self.assertEqual(len(self.runtime("import tools\n")), 1)
        self.assertEqual(len(self.runtime("import diode\n")), 1)      # 진입 스크립트도 diodelib 가 부르지 않는다

    def test_entry_script_is_checked(self):
        found = self.runtime("import missing_in_entry\n", rel="diode.py")
        self.assertEqual(len(found), 1)

    def test_nested_package_files_are_checked(self):
        found = self.runtime("import missing_nested\n", rel="diodelib/sub/deep.py")
        self.assertEqual(len(found), 1)

    def test_development_folders_may_use_anything(self):
        self.put({"tests/test_x.py": "import missing_in_tests\n", "tools/y.py": "import missing_in_tools\n",
                  "kit/z.py": "import missing_in_kit\n"})
        self.assertEqual(self.hits("W-02"), [])

    def test_syntax_that_python_38_cannot_read(self):
        found = self.runtime("match x:\n    case 1:\n        pass\n")
        self.assertEqual(len(found), 1)
        self.assertIn("3.8", found[0].msg)

    def test_broken_file_is_reported_not_raised(self):
        found = self.runtime("def (:\n")
        self.assertEqual(len(found), 1)


class TestNetwork(Synth):
    def test_bind_all_interfaces(self):
        for src in ('HOST = "0.0.0.0"\n', "HOST = '0.0.0.0'\n", 'ADDR = "0.0.0.0:8080"\n'):
            with self.subTest(src):
                self.put({"diodelib/net.py": src})
                found = self.hits("W-03", "diodelib/net.py")
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].line, 1)

    def test_every_line_of_a_file_is_listed_in_one_finding(self):
        self.put({"diodelib/net.py": 'A = "0.0.0.0"\nB = 1\nC = \'0.0.0.0:80\'\n'})
        found = self.hits("W-03", "diodelib/net.py")
        self.assertEqual(len(found), 1)
        self.assertIn("줄 1 · 3", found[0].msg)

    def test_bind_all_is_not_flagged_in_docs_tests_tools_or_loopback(self):
        self.put({"docs/x.md": 'host "0.0.0.0"\n', "tests/test_b.py": 'H = "0.0.0.0"\n', "tools/t.py": 'H = "0.0.0.0"\n',
                  "diodelib/ok.py": 'H = "127.0.0.1"\n'})
        self.assertEqual(self.hits("W-03"), [])

    def test_cdn_and_web_font_hosts(self):
        cases = {
            "diodelib/a.html": '<script src="https://cdn.jsdelivr.net/npm/x@1/x.js"></script>\n',
            "diodelib/b.css": "@import url(https://fonts.googleapis.com/css2?family=X);\n",
            "diodelib/c.py": 'URL = "https://unpkg.com/x"\n',
            "diodelib/d.js": "import x from 'https://cdnjs.cloudflare.com/ajax/libs/x.js';\n",
            "diodelib/e.html": '<link rel="stylesheet" href="//cdn2.example.net/x.css">\n',
            "skills/f.html": '<img src="https://images.example.org/x.png">\n',
        }
        for rel, text in cases.items():
            with self.subTest(rel):
                self.put({rel: text})
                self.assertEqual(len(self.hits("W-03", rel)), 1)

    def test_plain_links_and_words_are_fine(self):
        self.put({"diodelib/a.html": '<a href="https://example.com/doc">doc</a>\n',
                  "diodelib/b.py": "# CDN 은 쓰지 않는다 · cdn.js 도 아니다\nX = 'https://example.com'\n",
                  "docs/c.md": "https://cdn.jsdelivr.net/npm/x\n",
                  "tests/test_c.py": "U = 'https://unpkg.com/x'\n"})
        self.assertEqual(self.hits("W-03"), [])


class TestSecrets(Synth):
    def test_each_kind_in_text_and_json(self):
        for kind in ("openai", "github", "aws", "slack", "pem"):
            for rel in ("docs/n.md", "diodelib/c.json"):
                with self.subTest(kind=kind, rel=rel):
                    self.put({rel: "값: %s\n" % secret(kind)})
                    found = self.hits("W-04", rel)
                    self.assertEqual(len(found), 1)
                    self.assertEqual(found[0].line, 1)
                    self.drop(rel)

    def test_every_line_of_a_file_is_listed_in_one_finding(self):
        self.put({"n.md": "%s\n사이\n%s\n" % (secret("openai"), secret("openai"))})
        found = self.hits("W-04", "n.md")
        self.assertEqual(len(found), 1)
        self.assertIn("줄 1 · 3", found[0].msg)

    def test_value_is_never_printed(self):
        for kind in ("openai", "github", "aws", "slack", "pem"):
            with self.subTest(kind):
                self.put({"n.md": secret(kind) + "\n"})
                code, out = self.main("--no-tests", "--strict")
                self.assertEqual(code, 1)
                self.assertNotIn(secret(kind), out)
                self.assertNotIn(secret(kind)[:12], out)
                self.drop("n.md")

    def test_kit_out_and_binary_files_are_skipped(self):
        self.put({"kit/out/dump.json": secret("openai") + "\n", "kit/out/S01/001.json": secret("aws") + "\n"})
        with open(os.path.join(self.root, "blob.bin"), "wb") as f:
            f.write(b"\0\1\2" + secret("github").encode("ascii"))
        self.assertEqual(self.hits("W-04"), [])

    def test_lookalikes_do_not_match(self):
        self.put({"n.md": "task-bar-with-a-very-long-name-here and risk-assessment-for-the-whole-system\n"
                          "AKIA-too-short, xoxb-short, ghp_short\n"})
        self.assertEqual(self.hits("W-04"), [])


class TestPrivateIp(Synth):
    def test_private_ranges_are_flagged(self):
        for addr in (ip(10, 1, 2, 3), ip(192, 168, 0, 7), ip(172, 16, 5, 4), ip(172, 31, 0, 1)):
            with self.subTest(addr):
                self.put({"docs/n.md": "서버는 %s 이다\n" % addr})
                found = self.hits("W-12", "docs/n.md")
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].line, 1)
                self.drop("docs/n.md")

    def test_other_addresses_and_versions_are_fine(self):
        self.put({"docs/n.md": " ".join([ip(172, 32, 0, 1), ip(11, 0, 0, 1), ip(127, 0, 0, 1), ip(8, 8, 8, 8),
                                         "Windows 10.0.19045.1234", "v1.10.2.3", ip(192, 169, 1, 1)]) + "\n"})
        self.assertEqual(self.hits("W-12"), [])

    def test_exempt_places(self):
        text = "예: %s\n" % ip(10, 0, 0, 1)
        self.put({"docs/SPEC.md": text, "tests/vectors/text.json": text})
        self.assertEqual(self.hits("W-12"), [])
        self.put({"tests/test_other.py": text, "docs/PLAN.md": text})
        self.assertEqual(sorted(f.path for f in self.hits("W-12")), ["docs/PLAN.md", "tests/test_other.py"])

    def test_every_line_of_a_file_is_listed_in_one_finding(self):
        self.put({"docs/n.md": "첫 줄\n%s\n가운데\n%s\n끝\n%s\n" % (ip(10, 0, 0, 1), ip(10, 0, 0, 2), ip(192, 168, 1, 1))})
        found = self.hits("W-12", "docs/n.md")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 2)
        self.assertIn("줄 2 · 4 · 6", found[0].msg)

    def test_value_is_never_printed(self):
        self.put({"n.md": ip(10, 9, 8, 7) + "\n"})
        code, out = self.main("--no-tests", "--strict")
        self.assertEqual(code, 1)
        self.assertNotIn(ip(10, 9, 8, 7), out)


class TestReadmeTests(Synth):
    def two_tests(self):
        self.put({"tests/test_two.py": "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                       "    def test_a(self):\n        pass\n\n    def test_b(self):\n        pass\n"})

    def test_count_matches(self):
        self.two_tests()
        self.put({"README.md": "테스트 3 · CI\n"})          # test_one 1 + test_two 2
        self.assertEqual(self.hits("W-11", run_tests=True), [])

    def test_count_differs(self):
        self.two_tests()
        self.put({"README.md": "# t\n테스트 5 · CI\n"})
        found = self.hits("W-11", run_tests=True)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].path, "README.md")
        self.assertEqual(found[0].line, 2)
        self.assertIn("5", found[0].msg)
        self.assertIn("3", found[0].msg)

    def test_claim_is_required(self):
        self.put({"README.md": "# t\n테스트가 있다\n"})
        self.assertEqual(len(self.hits("W-11", run_tests=True)), 1)

    def test_test_that_cannot_be_loaded(self):
        self.put({"tests/test_broken.py": "import missing_module_for_test\n"})
        found = self.hits("W-11", run_tests=True)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].path, "tests")

    def test_skipping_leaves_a_note_and_no_finding(self):
        self.put({"README.md": "테스트 99\n"})
        repo = dc.Repo(self.root)
        self.assertEqual(dc.check_readme_tests(repo, run_tests=False), [])
        self.assertTrue(any("--no-tests" in n for n in repo.notes))


class TestInternalWords(Synth):
    def words_file(self, *words):
        """저장소 밖의 임시 폴더에 낱말 목록 파일을 만든다"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "words.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(words) + "\n")
        return path

    def test_skipped_without_a_file(self):
        repo = dc.Repo(self.root)
        self.assertEqual(dc.check_internal_words(repo, None), [])
        self.assertTrue(any("건너뛰었습니다" in n for n in repo.notes))

    def test_counts_only_and_never_prints_words(self):
        words = self.words_file("zetacorp", "Proj-Alpha", "unused-word")
        self.put({"docs/a.md": "ZetaCorp 의 일\n", "docs/b.md": "아무것도 없다\n", "docs/c.txt": "zetacorp 와 PROJ-ALPHA\n"})
        code, out = self.main("--no-tests", "--strict", "--internal-words", words)
        self.assertEqual(code, 1)
        for w in ("zetacorp", "proj-alpha", "unused-word"):
            self.assertNotIn(w, out.lower())
        self.assertIn("낱말 2개가 파일 2개", out)
        self.assertIn("목록 3개 · 발견 2개 · 파일 2개", out)

    def test_word_in_a_file_name_is_counted(self):
        words = self.words_file("secretname")
        self.put({"docs/secretname-notes.md": "아무 글\n"})
        found = dc.check_internal_words(dc.Repo(self.root), words)
        self.assertEqual(len(found), 1)
        self.assertIn("파일 1개", found[0].msg)

    def test_nothing_found(self):
        words = self.words_file("zetacorp")
        repo = dc.Repo(self.root)
        self.assertEqual(dc.check_internal_words(repo, words), [])
        self.assertTrue(any("발견 0개" in n for n in repo.notes))

    def test_unreadable_or_empty_list_counts_as_a_violation(self):
        repo = dc.Repo(self.root)
        self.assertEqual(len(dc.check_internal_words(repo, os.path.join(self.root, "no-such-file.txt"))), 1)
        self.assertEqual(len(dc.check_internal_words(repo, self.words_file())), 1)


@unittest.skipUnless(shutil.which("git"), "git 이 없다")
class TestGitListing(Synth):
    def test_tracked_and_new_files_but_not_ignored_ones(self):
        env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": self.root, "USERPROFILE": self.root,
               "XDG_CONFIG_HOME": os.path.join(self.root, ".xdg")}
        with mock.patch.dict(os.environ, env):
            subprocess.run(["git", "init", "-q", self.root], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.put({".gitignore": "ignored.md\nkit/out/\n", "ignored.md": secret("openai") + "\n",
                      "new.md": secret("aws") + "\n", "kit/out/x.json": secret("slack") + "\n"})
            repo = dc.Repo(self.root)
            self.assertIn("new.md", repo.files)
            self.assertIn("diode.py", repo.files)
            self.assertNotIn("ignored.md", repo.files)
            self.assertFalse(any(f.startswith((".git/", "kit/out/")) for f in repo.files))
            self.assertEqual([f.path for f in dc.run_checks(repo, run_tests=False) if f.rule == "W-04"], ["new.md"])


if __name__ == "__main__":
    unittest.main()
