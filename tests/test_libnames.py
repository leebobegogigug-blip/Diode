# -*- coding: utf-8 -*-
"""diode.py lib names <이름> (diodelib.libnames) - 허용 라이브러리의 공개 이름 목록 만들기 (SP-05 D5a · SP-16).

대상은 표준 라이브러리 (json · collections) 와 시험이 임시 폴더에 쓴 가짜 라이브러리다 - 외부 패키지에 기대지 않는다.
이 PC 의 실제 설정 · 데이터 폴더는 건드리지 않는다 (임시 데이터 폴더 · DIODE_HOME · HOME 을 임시 폴더로) (W-06).
진짜 하위 프로세스를 띄운다. 시간 초과 · 출력 상한 · 깨진 출력은 가짜 하위 프로세스 (`python -c ...`) 로 시험한다.
"""
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import libnames, scan  # noqa: E402

spec = importlib.util.spec_from_file_location("diode_cli_libnames", os.path.join(ROOT, "diode.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
ALLOW = ["JSON", "Collections", "diode_no_such_lib_xyz", "diode_t_scope"]


def write_json(path, obj):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def wrapped_argv(name, path):
    """libnames.child_argv 의 코드 앞에 path 를 검색 경로로 더한다 - 가짜 라이브러리를 불러오는 시험용
    (진짜 하위 프로세스는 -E 로 PYTHONPATH 를 무시하고 작업 폴더도 검색 경로에서 뺀다)"""
    argv = libnames.child_argv(name)
    argv[3] = "import sys\nsys.path.insert(0, %r)\n" % path + argv[3]
    return argv


def fake_child(code):
    return [sys.executable, "-c", code]


def good_output_code(names=("alpha", "beta"), truncated=False):
    return "import json; print(json.dumps({'version': '1.2', 'names': %r, 'truncated': %r}))" % (list(names), truncated)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.home = os.path.join(self.root, "data")
        os.makedirs(self.home)
        self.set_allow(ALLOW)

    def set_allow(self, allow):
        write_json(os.path.join(self.home, "config.json"), {"format": 1, "policy": {"lib_allow": allow}})

    def path(self, *parts):
        return os.path.join(self.home, "libnames", *parts)

    def listing(self):
        d = os.path.join(self.home, "libnames")
        return sorted(os.listdir(d)) if os.path.isdir(d) else None

    def fake_lib_dir(self, files):
        d = os.path.join(self.root, "fakelibs")
        for rel, src in files.items():
            p = os.path.join(d, *rel.split("/"))
            if not os.path.isdir(os.path.dirname(p)):
                os.makedirs(os.path.dirname(p))
            with open(p, "w", encoding="utf-8") as f:
                f.write(textwrap.dedent(src))
        return d

    def gather_fake(self, name, files):
        return libnames.gather(name, argv=wrapped_argv(name, self.fake_lib_dir(files)))


# ---------------------------------------------------------------- 명령의 몸통 (프로세스 안)

class MainNames(Base):
    def test_not_in_allow_list_is_a_usage_error(self):
        code, lines, text = libnames.main_names(self.home, "os")
        self.assertEqual((code, lines, text), (2, [], libnames.USAGE_TEXT["not_allowed"]))
        self.assertNotIn("os", text.replace("policy.lib_allow", "").replace("/diode:dict", "").split())   # 이름을 되풀이하지 않는다
        self.assertIsNone(self.listing())                                                                # 아무것도 만들지 않는다

    def test_nothing_is_allowed_without_a_config(self):
        os.unlink(os.path.join(self.home, "config.json"))
        self.assertEqual(libnames.main_names(self.home, "json")[0], 2)
        self.assertEqual(libnames.main_names(os.path.join(self.root, "no-such-folder"), "json")[0], 2)
        self.assertFalse(os.path.exists(os.path.join(self.root, "no-such-folder")))

    def test_broken_or_newer_config_is_a_check_failure(self):
        with open(os.path.join(self.home, "config.json"), "w") as f:
            f.write("{ not json")
        code, lines, text = libnames.main_names(self.home, "json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "config"})
        write_json(os.path.join(self.home, "config.json"), {"format": 2, "policy": {"lib_allow": ["json"]}})
        self.assertEqual(libnames.main_names(self.home, "json")[0], 1)
        self.assertIsNone(self.listing())

    def test_bad_names_are_usage_errors_and_write_nothing(self):
        self.set_allow(["../x", "a/b", "con", "a..b", "x"])         # 허용 목록에 있어도 꼴이 틀리면 거절한다
        bad = ["../x", "a/b", "a\\b", "", " json", "json ", "json\n", "1abc", "a..b", "a.", ".a", "con", "NUL", "com1.x", "x" * 65,
               "a;b", "a b", "a\x00b", "한글", "-json", "_json", "..", "a:b"]
        for name in bad:
            with self.subTest(repr(name)):
                code, lines, text = libnames.main_names(self.home, name)
                self.assertEqual((code, lines, text), (2, [], libnames.USAGE_TEXT["bad_name"]))
        self.assertIsNone(self.listing())
        self.assertEqual(sorted(os.listdir(self.root)), ["data"])

    def test_not_installed_is_a_check_failure(self):
        code, lines, text = libnames.main_names(self.home, "diode_no_such_lib_xyz")
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "not_installed"})
        self.assertEqual(lines[1], "결과: 점검 실패")
        self.assertEqual(text, libnames.FAIL_TEXT["not_installed"])
        self.assertNotIn("diode_no_such_lib_xyz", "\n".join(lines) + text)
        self.assertIsNone(self.listing())

    def test_ok_writes_the_list(self):
        code, lines, text = libnames.main_names(self.home, "json")
        self.assertEqual((code, text), (0, ""))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1], "결과: OK")
        data = read_json(self.path("json.json"))
        self.assertEqual(list(data), ["format", "library", "version", "names", "truncated"])
        self.assertEqual((data["format"], data["library"], data["truncated"]), (1, "json", False))
        self.assertIsInstance(data["version"], str)
        names = data["names"]
        self.assertEqual(names, sorted(set(names)))
        self.assertTrue(all(NAME_RE.match(n) for n in names))
        for want in ("dumps", "loads", "dump", "load", "JSONDecodeError", "JSONEncoder", "indent", "sort_keys"):   # 공개 속성 · 클래스 · 키워드 인자
            self.assertIn(want, names)
        for hidden in ("self", "cls", "kw"):                                  # 묶어 받는 인자 (**kw) · 첫 인자는 키워드로 못 쓴다
            self.assertNotIn(hidden, names)
        self.assertEqual(json.loads(lines[0]), {"ok": True, "library": "json", "names": len(names), "truncated": False})
        self.assertEqual(self.listing(), ["json.json"])                      # 임시 파일이 남지 않는다

    def test_output_has_counts_but_no_names(self):
        code, lines, text = libnames.main_names(self.home, "json")
        words = set(re.findall(r"[A-Za-z_]+", "\n".join(lines) + text))
        listed = set(read_json(self.path("json.json"))["names"])
        self.assertEqual(words - {"ok", "library", "json", "names", "truncated", "false", "true", "OK"}, set())   # 낱말은 칸 이름 · 판정뿐
        self.assertNotIn("dumps", words)
        self.assertGreater(len(listed), 50)
        self.assertNotIn(self.home, "\n".join(lines) + text)

    def test_allow_list_and_file_name_ignore_case(self):
        self.assertEqual(libnames.main_names(self.home, "collections")[0], 0)           # 허용 목록에는 Collections
        self.assertEqual(self.listing(), ["collections.json"])
        self.assertEqual(read_json(self.path("collections.json"))["library"], "collections")
        self.assertIn("OrderedDict", read_json(self.path("collections.json"))["names"])
        self.assertEqual(libnames.main_names(self.home, "json")[0], 0)                  # 허용 목록에는 JSON · 파일 이름은 소문자
        self.assertEqual(self.listing(), ["collections.json", "json.json"])

    def test_rewriting_the_same_file_is_fine_and_leaves_no_temp_file(self):
        write_json(self.path("other.json"), {"format": 1, "library": "other", "names": ["keep_me"]})
        with open(self.path("other.json"), "rb") as f:
            other = f.read()
        self.assertEqual(libnames.main_names(self.home, "json")[0], 0)
        first = read_json(self.path("json.json"))
        self.assertEqual(libnames.main_names(self.home, "json")[0], 0)
        self.assertEqual(read_json(self.path("json.json")), first)
        self.assertEqual(self.listing(), ["json.json", "other.json"])
        with open(self.path("other.json"), "rb") as f:
            self.assertEqual(f.read(), other)                                          # 다른 파일은 그대로

    def test_a_newer_format_file_is_not_overwritten(self):
        write_json(self.path("json.json"), {"format": 2, "library": "json", "names": ["from_the_future"]})
        with open(self.path("json.json"), "rb") as f:
            before = f.read()
        code, lines, text = libnames.main_names(self.home, "json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "newer"})
        with open(self.path("json.json"), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.listing(), ["json.json"])

    def test_a_broken_file_is_set_aside_not_lost(self):
        os.makedirs(self.path())
        for i, body in enumerate(("{ broken", "[]", '{"format": true}')):
            with open(self.path("json.json"), "w") as f:
                f.write(body)
            self.assertEqual(libnames.main_names(self.home, "json")[0], 0, body)
            self.assertEqual(read_json(self.path("json.json"))["format"], 1)
            aside = self.path("json.json.broken" + ("" if i == 0 else str(i)))
            with open(aside) as f:
                self.assertEqual(f.read(), body)
        self.assertEqual(self.listing(), ["json.json", "json.json.broken", "json.json.broken1", "json.json.broken2"])

    def test_a_directory_in_the_way_is_a_write_failure(self):
        os.makedirs(self.path("json.json"))
        code, lines, text = libnames.main_names(self.home, "json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "write"})
        self.assertEqual(self.listing(), ["json.json"])

    def test_a_symlink_in_the_way_is_not_followed(self):
        target = os.path.join(self.root, "target.json")
        write_json(target, {"format": 1, "library": "json", "names": ["untouched"]})
        os.makedirs(self.path())
        try:
            os.symlink(target, self.path("json.json"))
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        self.assertEqual(libnames.main_names(self.home, "json")[0], 1)
        self.assertEqual(read_json(target)["names"], ["untouched"])
        self.assertEqual(self.listing(), ["json.json"])

    def test_names_are_cut_and_marked_truncated(self):
        with mock.patch.object(libnames, "MAX_NAMES", 10):
            code, lines, text = libnames.main_names(self.home, "json")
        self.assertEqual(code, 0)
        data = read_json(self.path("json.json"))
        self.assertEqual((len(data["names"]), data["truncated"]), (10, True))
        self.assertEqual(data["names"], sorted(data["names"]))
        self.assertEqual(json.loads(lines[0]), {"ok": True, "library": "json", "names": 10, "truncated": True})

    def test_exactly_at_the_limit_is_not_truncated(self):
        full = len(libnames.gather("json")[1][1])
        with mock.patch.object(libnames, "MAX_NAMES", full):
            code, got = libnames.gather("json")
        self.assertEqual((code, got[2], len(got[1])), ("ok", False, full))
        with mock.patch.object(libnames, "MAX_NAMES", full - 1):
            code, got = libnames.gather("json")
        self.assertEqual((code, got[2], len(got[1])), ("ok", True, full - 1))


# ---------------------------------------------------------------- 하위 프로세스 (가짜)

class ChildProcess(Base):
    def test_timeout_kills_the_child_and_writes_nothing(self):
        started = time.monotonic()
        code, lines, text = libnames.main_names(self.home, "json", argv=fake_child("import time; time.sleep(60)"), timeout_s=1)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "timeout"})
        self.assertEqual(lines[1], "결과: 점검 실패")
        self.assertIsNone(self.listing())

    def test_timeout_when_output_is_written_but_the_child_never_exits(self):
        code = good_output_code() + "; import sys; sys.stdout.flush(); import time; time.sleep(60)"
        self.assertEqual(libnames.gather("json", argv=fake_child(code), timeout_s=2)[0], "timeout")

    def test_output_over_the_cap_is_refused(self):
        code = "import sys; sys.stdout.write('a' * (%d + 1)); sys.stdout.flush()" % libnames.MAX_OUTPUT_BYTES
        c, lines, text = libnames.main_names(self.home, "json", argv=fake_child(code))
        self.assertEqual(c, 1)
        self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "too_large"})
        self.assertIsNone(self.listing())

    def test_output_at_the_cap_is_read_but_not_valid(self):
        code = "import sys; sys.stdout.write('a' * %d)" % libnames.MAX_OUTPUT_BYTES
        self.assertEqual(libnames.gather("json", argv=fake_child(code))[0], "bad_output")

    def test_a_child_that_streams_forever_is_stopped(self):
        code = "import sys\nwhile True:\n    sys.stdout.write('a' * 65536)\n    sys.stdout.flush()\n"
        started = time.monotonic()
        self.assertEqual(libnames.gather("json", argv=fake_child(code), max_bytes=100000)[0], "too_large")
        self.assertLess(time.monotonic() - started, 30)

    def test_a_good_fake_child(self):
        code, got = libnames.gather("json", argv=fake_child(good_output_code(["beta", "alpha", "alpha"])))
        self.assertEqual((code, got), ("ok", ("1.2", ["alpha", "beta"], False)))      # 부모가 정렬 · 중복 없앰

    def test_the_parent_cuts_a_child_that_sends_too_many_names(self):
        names = ["n%02d" % i for i in range(30)]
        with mock.patch.object(libnames, "MAX_NAMES", 10):
            code, got = libnames.gather("json", argv=fake_child(good_output_code(names)))
        self.assertEqual((code, got[1], got[2]), ("ok", names[:10], True))

    def test_exit_codes_of_the_child(self):
        self.assertEqual(libnames.gather("json", argv=fake_child("import sys; sys.exit(%d)" % libnames.EXIT_NOT_INSTALLED))[0],
                         "not_installed")
        self.assertEqual(libnames.gather("json", argv=fake_child("import sys; sys.exit(1)"))[0], "failed")
        self.assertEqual(libnames.gather("json", argv=fake_child(good_output_code() + "; import sys; sys.exit(1)"))[0], "failed")
        self.assertEqual(libnames.gather("json", argv=fake_child("raise RuntimeError('boom')"))[0], "failed")
        self.assertEqual(libnames.gather("json", argv=["diode-no-such-program-xyz"])[0], "failed")
        self.assertEqual(libnames.gather("json", argv=[])[0], "failed")

    def test_bad_outputs_are_refused(self):
        good = {"version": "1", "names": ["alpha"], "truncated": False}
        cases = [
            "",
            "not json",
            json.dumps(good) + "\n" + json.dumps(good),
            '{"version": "1", "names": [NaN], "truncated": false}',
            '{"version": "1", "names": [Infinity], "truncated": false}',
            json.dumps(dict(good, extra=1)),
            json.dumps({k: v for k, v in good.items() if k != "version"}),
            json.dumps(dict(good, names="alpha")),
            json.dumps(dict(good, names=["has space"])),
            json.dumps(dict(good, names=["1leading"])),
            json.dumps(dict(good, names=["_private"])),
            json.dumps(dict(good, names=["a" * 65])),
            json.dumps(dict(good, names=["../x"])),
            json.dumps(dict(good, names=["alpha\n"])),
            json.dumps(dict(good, names=[1])),
            json.dumps(dict(good, names=["한글"])),
            json.dumps(dict(good, truncated=1)),
            json.dumps(dict(good, version=1)),
            json.dumps([good]),
            json.dumps("alpha"),
        ]
        for text in cases:
            with self.subTest(text[:60]):
                code = "import sys; sys.stdout.write(%r)" % text
                c, lines, _ = libnames.main_names(self.home, "json", argv=fake_child(code))
                self.assertEqual(c, 1)
                self.assertEqual(json.loads(lines[0]), {"ok": False, "error": "bad_output"})
        self.assertIsNone(self.listing())
        self.assertIsNone(libnames.parse_output(b"\xff\xfe"))

    def test_a_strange_version_is_dropped_not_fatal(self):
        for version, want in (("2.1.0rc1", "2.1.0rc1"), ("1!2.0+local", "1!2.0+local"), ("has space", ""), ("v" * 65, ""), ("", "")):
            out = json.dumps({"version": version, "names": ["alpha"], "truncated": False}).encode("ascii")
            self.assertEqual(libnames.parse_output(out), (want, ["alpha"], False), version)

    def test_stderr_of_the_child_is_thrown_away(self):
        code = ("import sys; sys.stderr.write('secret-marker-path-xyz'); sys.stderr.flush(); " + good_output_code())
        c, lines, text = libnames.main_names(self.home, "json", argv=fake_child(code))
        self.assertEqual(c, 0)
        self.assertNotIn("secret-marker-path-xyz", "\n".join(lines) + text)

    def test_the_real_command_line_is_a_list_without_a_shell(self):
        argv = libnames.child_argv("diode_t_marker_name")
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[:3], [sys.executable, "-E", "-c"])
        self.assertEqual(argv[4], "diode_t_marker_name")               # 이름은 코드에 끼우지 않고 인자로 준다
        self.assertNotIn("diode_t_marker_name", argv[3])
        with mock.patch.object(subprocess, "Popen", wraps=subprocess.Popen) as popen:
            libnames.gather("json")
        _, kwargs = popen.call_args
        self.assertFalse(kwargs.get("shell"))
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)


# ---------------------------------------------------------------- 모으는 범위 (가짜 라이브러리)

class Scope(Base):
    def test_scope_of_the_collection(self):
        mark_prop = os.path.join(self.root, "mark-property")
        mark_lazy = os.path.join(self.root, "mark-lazy")
        src = '''
            import json as foreign_mod
            import os
            print("noise on stdout at import")
            os.write(1, b"raw noise on fd 1\\n")

            def public_func(alpha, beta=1, *rest, gamma, **options):
                pass

            def only_positional(p_only, /, p_kw):
                pass

            def _private_func(hidden_param):
                pass

            class Widget(object):
                kind = 1

                def method_a(self, delta, epsilon=2):
                    pass

                @staticmethod
                def static_b(zeta):
                    pass

                @classmethod
                def class_c(cls, eta):
                    pass

                @property
                def prop_d(self):
                    open(%r, "w").close()
                    return 1

                def _hidden(self, iota):
                    pass

                class Inner(object):
                    def inner_m(self, theta):
                        pass

            Widget.self_ref = Widget

            class FromBase(dict):
                pass

            def __getattr__(name):
                if name == "lazy_attr":
                    open(%r, "w").close()
                raise AttributeError(name)

            def __dir__():
                return ["lazy_attr", "public_func", "only_positional", "Widget", "FromBase", "foreign_mod", "_x"]
        ''' % (mark_prop, mark_lazy)
        code, got = self.gather_fake("diode_t_scope", {"diode_t_scope.py": src})
        self.assertEqual(code, "ok")
        names = set(got[1])
        for want in ("public_func", "Widget", "FromBase", "foreign_mod", "lazy_attr",        # 공개 속성 (dir 이 말하는 것)
                     "kind", "method_a", "static_b", "class_c", "prop_d", "Inner", "self_ref",   # 클래스의 공개 멤버 · 안쪽 클래스 · 순환
                     "inner_m", "keys", "items",                                              # 안쪽 클래스의 멤버 · 물려받은 멤버
                     "alpha", "beta", "gamma", "p_kw", "delta", "epsilon", "zeta", "eta", "theta"):   # 키워드로 쓰이는 매개변수 이름
            self.assertIn(want, names)
        for absent in ("_private_func", "hidden_param", "_hidden", "iota", "_x", "_",          # 밑줄로 시작
                       "self", "cls", "rest", "options", "p_only",                              # 키워드 인자로 쓸 수 없는 것
                       "dumps", "loads", "JSONDecoder",                                         # 다른 라이브러리의 내용
                       "noise", "raw"):                                                         # 불러오며 찍은 글
            self.assertNotIn(absent, names)
        self.assertFalse(os.path.exists(mark_prop), "속성 접근이 코드를 돌렸다")
        self.assertFalse(os.path.exists(mark_lazy), "게으른 __getattr__ 이 불렸다")

    def test_depth_is_three(self):
        self.assertEqual(libnames.MAX_DEPTH, 3)
        src = '''
            class A(object):
                def m_a(self, p_a):
                    pass

                class B(object):
                    def m_b(self, p_b):
                        pass

                    class C(object):
                        def m_c(self, p_c):
                            pass

                        class D(object):
                            def m_d(self, p_d):
                                pass

                            class E(object):
                                def m_e(self, p_e):
                                    pass
        '''
        code, got = self.gather_fake("diode_t_depth", {"diode_t_depth.py": src})
        names = set(got[1])
        self.assertEqual(code, "ok")
        self.assertEqual(sorted(names), sorted(["A", "B", "C", "D", "m_a", "m_b", "m_c", "p_a", "p_b", "p_c"]))

    def test_only_already_imported_submodules_are_read(self):
        files = {
            "diode_t_pkg/__init__.py": "from . import loaded\ntop_name = 1\n",
            "diode_t_pkg/loaded.py": "def in_loaded(param_in_loaded):\n    pass\n",
            "diode_t_pkg/unloaded.py": "raise RuntimeError('이 모듈은 불러오면 안 된다')\n",
        }
        code, got = self.gather_fake("diode_t_pkg", files)
        self.assertEqual(code, "ok")
        self.assertEqual(sorted(got[1]), ["in_loaded", "loaded", "param_in_loaded", "top_name"])

    def test_import_failures_are_not_installed(self):
        for body in ("raise RuntimeError('boom')\n", "import sys\nsys.exit(0)\n", "raise ImportError('x')\n", "this is not python\n"):
            with self.subTest(body):
                code, got = self.gather_fake("diode_t_bad", {"diode_t_bad.py": body})
                self.assertEqual((code, got), ("not_installed", None))

    def test_the_working_folder_is_not_searched(self):
        d = os.path.join(self.root, "cwd")
        os.makedirs(d)
        with open(os.path.join(d, "diode_t_cwdlib.py"), "w") as f:
            f.write("marker_name = 1\n")
        before = os.getcwd()
        self.addCleanup(os.chdir, before)
        os.chdir(d)
        self.assertEqual(libnames.gather("diode_t_cwdlib"), ("not_installed", None))
        self.assertEqual(libnames.gather("json")[0], "ok")                 # 표준 라이브러리는 그대로 불러진다

    def test_python_environment_variables_are_ignored(self):
        d = self.fake_lib_dir({"diode_t_envlib.py": "marker_name = 1\n"})
        with mock.patch.dict(os.environ, {"PYTHONPATH": d}):
            self.assertEqual(libnames.gather("diode_t_envlib"), ("not_installed", None))

    def test_dotted_library_names(self):
        code, got = libnames.gather("collections.abc")
        self.assertEqual(code, "ok")
        self.assertIn("Mapping", got[1])


# ---------------------------------------------------------------- 정책이 읽고 D5a 가 쓴다

BRIEF = {"format": 1, "kind": "lib", "data_class": "synthetic", "library": {"name": "json", "version": "3.8"},
         "language": "python", "goal": "문자열로 바꾸고 싶다",
         "repro": 'import json\nitem = {"a": "b"}\nresult = json.dumps(item)\n',
         "error": {"type": "json.JSONDecodeError", "message": "읽지 못했다고 한다"},
         "ask": "왜 이렇게 되나"}


class WithPolicy(Base):
    def setUp(self):
        Base.setUp(self)
        self.set_allow(["json", "collections"])          # D5a 의 이름 검사는 허용 목록에 적은 글자 그대로 본다
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 1, "words": ["KITWORDALPHA"]})

    def test_before_the_list_the_public_names_are_blocked(self):
        res = scan.check_brief(BRIEF, scan.policy_from_home(self.home))
        self.assertFalse(res["ok"])
        self.assertEqual([(h["check"], h["where"]) for h in res["hits"]], [("D5a", ["repro:3", "error.type"])])

    def test_policy_reads_the_list_and_d5a_passes_a_json_dumps_repro(self):
        self.assertEqual(libnames.main_names(self.home, "json")[0], 0)
        policy = scan.policy_from_home(self.home)
        self.assertLessEqual({"dumps", "loads", "JSONDecodeError"}, policy.lib_names)
        self.assertEqual(scan.check_repro(BRIEF["repro"], policy), [])
        self.assertEqual(scan.check_brief(BRIEF, policy), {"ok": True, "hits": []})

    def test_a_name_that_is_not_public_still_blocks(self):
        self.assertEqual(libnames.main_names(self.home, "json")[0], 0)
        policy = scan.policy_from_home(self.home)
        brief = dict(BRIEF, repro=BRIEF["repro"].replace("dumps", "frobnicate_internal"),
                     error={"type": "json.InternalOnlyError", "message": "읽지 못했다고 한다"})
        res = scan.check_brief(brief, policy)
        self.assertEqual([(h["check"], h["where"]) for h in res["hits"]], [("D5a", ["repro:3", "error.type"])])

    def test_a_list_for_a_library_that_is_not_allowed_is_ignored(self):
        self.assertEqual(libnames.main_names(self.home, "json")[0], 0)
        self.set_allow(["collections"])
        self.assertNotIn("dumps", scan.policy_from_home(self.home).lib_names)


# ---------------------------------------------------------------- 명령줄

class CommandLine(Base):
    """diode.py lib names - 종료 코드 · 표준 출력 · 표준 오류 (프로세스 안과 스크립트로)"""

    def run_inproc(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"DIODE_HOME": self.home, "HOME": self.root, "USERPROFILE": self.root, "LOCALAPPDATA": os.path.join(self.root, "AppData")}
        with mock.patch.dict(os.environ, env):
            code = cli.main(list(argv), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def run_script(self, *argv):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", DIODE_HOME=self.home, HOME=self.root,
                   USERPROFILE=self.root, LOCALAPPDATA=os.path.join(self.root, "AppData"))
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py")] + list(argv), cwd=self.root, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        return p.returncode, p.stdout.decode("utf-8").replace("\r\n", "\n"), p.stderr.decode("utf-8").replace("\r\n", "\n")

    def test_ok(self):
        for run in (self.run_inproc, self.run_script):
            with self.subTest(run.__name__):
                code, out, err = run("lib", "names", "json")
                self.assertEqual((code, err), (0, ""))
                lines = out.split("\n")
                self.assertEqual(lines[-1], "")
                self.assertEqual(lines[-2], "결과: OK")
                got = json.loads(lines[0])
                self.assertEqual(sorted(got), ["library", "names", "ok", "truncated"])
                self.assertEqual((got["ok"], got["library"], got["truncated"]), (True, "json", False))
                self.assertEqual(got["names"], len(read_json(self.path("json.json"))["names"]))
                self.assertNotIn("dumps", out)
                self.assertEqual(len(lines), 3)

    def test_the_default_data_folder_is_not_touched(self):
        code, _, _ = self.run_script("lib", "names", "json")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(self.root)), ["data"])           # HOME 에 .local 등이 생기지 않았다
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "data"))), ["config.json", "libnames"])

    def test_not_allowed_is_exit_2_with_a_fixed_sentence(self):
        for run in (self.run_inproc, self.run_script):
            with self.subTest(run.__name__):
                code, out, err = run("lib", "names", "diode_not_allowed_xyz")
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("사용법 오류: " + libnames.USAGE_TEXT["not_allowed"]), err)
                self.assertNotIn("diode_not_allowed_xyz", err)
        self.assertIsNone(self.listing())

    def test_bad_name_is_exit_2_and_not_echoed(self):
        for run in (self.run_inproc, self.run_script):
            with self.subTest(run.__name__):
                code, out, err = run("lib", "names", "../secret_x")
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("사용법 오류: " + libnames.USAGE_TEXT["bad_name"]), err)
                self.assertNotIn("secret_x", err)

    def test_not_installed_is_exit_1(self):
        for run in (self.run_inproc, self.run_script):
            with self.subTest(run.__name__):
                code, out, err = run("lib", "names", "diode_no_such_lib_xyz")
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(out.split("\n")[0]), {"ok": False, "error": "not_installed"})
                self.assertEqual(out.rstrip("\n").split("\n")[-1], "결과: 점검 실패")
                self.assertEqual(err.strip(), libnames.FAIL_TEXT["not_installed"])
                self.assertNotIn("diode_no_such_lib_xyz", out + err)

    def test_wrong_forms_are_usage_errors(self):
        for argv in (["lib"], ["lib", "names"], ["lib", "names", "json", "extra"], ["lib", "frob", "json"], ["lib", "json"],
                     ["lib", "names", "--json"]):
            with self.subTest(argv):
                code, out, err = self.run_inproc(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("사용법 오류: "), err)
                self.assertIn("help", err)
        self.assertIsNone(self.listing())

    def test_lib_is_no_longer_pending(self):
        self.assertNotIn("lib", [n for n, _ in cli.PENDING + cli.PENDING_FLAGS])
        code, out, err = self.run_inproc("help")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("lib names <이름>", out)
        self.assertNotIn("아직 없는 명령", out)
        for argv in (["lib", "names", "json"], ["lib", "names", "os"], ["lib"]):
            self.assertNotIn("아직 없음", "".join(self.run_inproc(*argv)[1:]))


# ---------------------------------------------------------------- 문서가 코드와 같은 말을 한다

class Docs(unittest.TestCase):
    """MANUAL · SPEC (SP-05 · SP-16) 의 숫자 · 상태가 코드의 상수와 같다 - 약속은 CI 가 지킨다 (W-11)"""

    def text(self, rel):
        with open(os.path.join(ROOT, *rel.split("/")), "r", encoding="utf-8") as f:
            return f.read()

    def test_the_command_rows_say_it_exists(self):
        manual_row = next(l for l in self.text("docs/MANUAL.md").splitlines() if l.startswith("| `lib names <이름>`"))
        self.assertTrue(manual_row.rstrip().endswith("| 있음 |"), manual_row)
        self.assertNotIn("아직 없음", manual_row)
        spec_row = next(l for l in self.text("docs/SPEC.md").splitlines() if l.startswith("| `diode.py lib names <이름>`"))
        self.assertNotIn("창에서 확정", spec_row)
        self.assertIn("libnames", spec_row)

    def test_the_numbers_match_the_constants(self):
        wants = ["%d초" % libnames.TIMEOUT_S, "%d MiB" % (libnames.MAX_OUTPUT_BYTES // (1024 * 1024)),
                 "{:,}".format(libnames.MAX_NAMES), "깊이 %d" % libnames.MAX_DEPTH]
        for rel in ("docs/MANUAL.md", "docs/SPEC.md"):
            text = self.text(rel)
            for want in wants:
                self.assertIn(want, text, "%s: %s" % (rel, want))

    def test_every_error_code_is_documented(self):
        manual, spec_ = self.text("docs/MANUAL.md"), self.text("docs/SPEC.md")
        for code in list(libnames.FAIL_TEXT) + ["not_installed", "timeout", "too_large", "failed", "bad_output"]:
            self.assertIn("`%s`" % code, manual, code)
            self.assertIn("`%s`" % code, spec_, code)


if __name__ == "__main__":
    unittest.main()
