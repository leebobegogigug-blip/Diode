# -*- coding: utf-8 -*-
"""방 만들기 (room.create_room) · 점검 (setup.check) · 처음 설정 (setup.run_setup). 합성 자리 · 합성 단어만."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import config, room, setup  # noqa: E402

WORD = "KITWORDALPHA"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-setup-"))
        self.home = os.path.join(self.tmp, "data")
        self.raw = os.path.join(self.tmp, "kitraw")
        self.room = os.path.join(self.tmp, "claude", "room")
        os.makedirs(self.raw)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ready_policy(self, **kw):
        st = {"words": [WORD], "raw_dirs": [self.raw], "room_path": self.room,
              "llm": {"base_url": "http://127.0.0.1:1/v1", "model": "m"}, "worker_command": ["opencode", "run", "{prompt}"]}
        st.update(kw)
        config.apply_state(self.home, st)


class CreateRoom(Base):
    def test_created_room_is_ok_and_has_the_five_settings(self):
        self.assertEqual(room.create_room(self.room, [self.raw]), {"room": "created"})
        self.assertEqual(room.room_state(self.room), "ok")
        self.assertEqual(sorted(os.listdir(self.room)), [".claude", ".diode-room", "inbox", "outbox", "work"])
        with open(os.path.join(self.room, ".claude", "settings.json"), encoding="utf-8") as f:
            s = json.load(f)
        self.assertIs(s["autoMemoryEnabled"], False)
        self.assertEqual(s["permissions"]["defaultMode"], "default")
        self.assertIs(s["permissions"]["blockReadsOutsideWorkingDirectories"], True)
        self.assertEqual(s["permissions"]["deny"], ["Bash", "WebFetch"])
        self.assertIn("**/CLAUDE.md", s["claudeMdExcludes"])
        self.assertTrue(s["statusLine"]["command"].startswith('python "'))          # python 은 이름만 (L-30)
        self.assertTrue(s["statusLine"]["command"].endswith('diode.py" --statusline'))
        dumped = json.dumps(s)
        self.assertNotIn(self.raw, dumped)                                         # 권한 규칙에 원자료 경로를 쓰지 않는다 (L-31)

    def test_idempotent_and_never_overwrites(self):
        room.create_room(self.room, [])
        with open(os.path.join(self.room, ".claude", "settings.json"), "rb") as f:
            before = f.read()
        self.assertEqual(room.create_room(self.room, []), {"room": "ok"})
        with open(os.path.join(self.room, ".claude", "settings.json"), "w") as f:
            f.write("{}")
        self.assertEqual(room.create_room(self.room, []), {"room": "changed"})        # 바뀌었으면 알리기만
        with open(os.path.join(self.room, ".claude", "settings.json")) as f:
            self.assertEqual(f.read(), "{}")                                        # 덮어쓰지 않았다
        self.assertNotEqual(before, b"{}")

    def test_refusals(self):
        # 원자료 폴더와 겹침 (안 · 위)
        self.assertEqual(room.create_room(os.path.join(self.raw, "room"), [self.raw]), {"room": "refused", "code": "raw"})
        self.assertEqual(room.create_room(self.tmp, [self.raw]), {"room": "refused", "code": "raw"})
        # 플러그인 소스와 겹침
        self.assertEqual(room.create_room(os.path.join(room.PLUGIN_ROOT, "room"), []), {"room": "refused", "code": "plugin"})
        # git 저장소 안
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        self.assertEqual(room.create_room(os.path.join(repo, "room"), []), {"room": "refused", "code": "git"})
        # 위 폴더에 안내 파일
        for rel in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "AGENTS.md"):
            top = os.path.join(self.tmp, "guide-" + rel.replace(os.sep, "-"))
            os.makedirs(os.path.join(top, os.path.dirname(rel)) if os.path.dirname(rel) else top, exist_ok=True)
            with open(os.path.join(top, rel), "w") as f:
                f.write("x")
            self.assertEqual(room.create_room(os.path.join(top, "room"), []), {"room": "refused", "code": "guide"}, rel)
        # 비어 있지 않은 폴더 · 상대 경로
        full = os.path.join(self.tmp, "full")
        os.makedirs(full)
        open(os.path.join(full, "a.txt"), "w").close()
        self.assertEqual(room.create_room(full, []), {"room": "refused", "code": "nonempty"})
        self.assertEqual(room.create_room("room", []), {"room": "refused", "code": "path"})
        self.assertEqual(room.create_room("", []), {"room": "refused", "code": "path"})
        self.assertFalse(os.path.exists(os.path.join(self.raw, "room")))              # 거부했으니 아무것도 만들지 않았다

    def test_empty_existing_folder_is_fine(self):
        os.makedirs(self.room)
        self.assertEqual(room.create_room(self.room, []), {"room": "created"})

    def test_default_room_path(self):
        self.assertEqual(room.default_room_path("  /x/room  "), "/x/room")
        self.assertTrue(room.default_room_path(None).endswith("room"))


class Check(Base):
    def lines(self, **kw):
        return setup.check(self.home, python_probe=kw.get("probe") or (lambda: (True, "3.12")))

    def test_first_run_needs_confirmation(self):
        lines, code = self.lines()
        self.assertEqual(code, 3)
        self.assertEqual(lines[-1], "결과: 확인 필요")
        text = "\n".join(lines)
        self.assertIn("사전이 비어 있음", text)
        self.assertIn("훅 자체 시험 OK", text)

    def test_all_ready_is_ok(self):
        self.ready_policy()
        room.create_room(self.room, [self.raw])
        lines, code = self.lines()
        self.assertEqual((code, lines[-1]), (0, "결과: OK"))

    def test_python_missing_fails(self):
        _, code = self.lines(probe=lambda: (False, None))
        self.assertEqual(code, 1)
        _, code = self.lines(probe=lambda: (False, "3.6"))
        self.assertEqual(code, 1)

    def test_broken_config_fails(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        lines, code = self.lines()
        self.assertEqual(code, 1)
        self.assertIn("(broken)", "\n".join(lines))

    def test_output_has_no_words_or_paths(self):
        self.ready_policy()
        room.create_room(self.room, [self.raw])
        text = "\n".join(self.lines()[0])
        for w in (WORD, "kitraw", self.tmp, "opencode run", "127.0.0.1"):
            self.assertNotIn(w, text)

    def test_user_guide_with_dictionary_word(self):
        self.ready_policy()
        md = os.path.join(self.tmp, "CLAUDE.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write("# 메모\n%s 프로젝트\n" % WORD)
        self.assertEqual(setup.user_guide_hits(self.home, md), 1)
        with open(md, "w", encoding="utf-8") as f:
            f.write("평범한 메모\n")
        self.assertEqual(setup.user_guide_hits(self.home, md), 0)
        self.assertEqual(setup.user_guide_hits(self.home, os.path.join(self.tmp, "없음.md")), 0)


class RunSetup(Base):
    def test_first_run_opens_the_window_and_does_not_make_a_room(self):
        launched = []
        lines, code = setup.run_setup(self.home, path=self.room, launch=lambda: launched.append(1))
        self.assertEqual(launched, [1])
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.room))
        self.assertIn("정책 창을 엽니다", "\n".join(lines))
        self.assertNotIn(WORD, "\n".join(lines))

    def test_ready_makes_the_room_without_the_window(self):
        self.ready_policy()
        launched = []
        lines, code = setup.run_setup(self.home, path=self.room, launch=lambda: launched.append(1))
        self.assertEqual(launched, [])
        self.assertEqual(room.room_state(self.room), "ok")
        self.assertIn("방을 만들었습니다", lines[0])
        self.assertEqual(code, 0)

    def test_broken_config_does_not_open_the_window(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        launched = []
        lines, code = setup.run_setup(self.home, path=self.room, launch=lambda: launched.append(1))
        self.assertEqual((launched, code >= 1), ([], True))

    def test_refused_room_is_reported(self):
        self.ready_policy()
        lines, code = setup.run_setup(self.home, path=os.path.join(self.raw, "room"), launch=lambda: None)
        self.assertIn("원자료 폴더와 겹칩니다", "\n".join(lines))
        self.assertNotEqual(code, 0)


class Cli(Base):
    """diode.py setup · room · dict — 진짜 프로세스 · 임시 HOME (기본 데이터 폴더)."""

    def _run(self, *argv):
        import subprocess
        env = dict(os.environ)
        env.update({"HOME": self.tmp, "USERPROFILE": self.tmp, "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local"),
                    "PYTHONIOENCODING": "utf-8"})
        env.pop("DIODE_HOME", None)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py")] + list(argv), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env, timeout=60)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_setup_check(self):
        code, out, err = self._run("setup", "--check")
        self.assertEqual(code, 3)
        self.assertEqual(out.strip().splitlines()[-1], "결과: 확인 필요")
        self.assertFalse(os.path.exists(self.home))                         # 점검은 아무것도 만들지 않는다

    def test_report_mode_always_exits_zero(self):
        # 슬래시 명령의 ! 는 종료 코드가 0 이 아니면 명령을 실패로 본다 — 결과 줄이 상태를 알린다
        code, out, err = self._run("setup", "--check", "--report")
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "결과: 확인 필요"))
        code, out, err = self._run("room", "--path", os.path.join(room.PLUGIN_ROOT, "x"), "--report")
        self.assertEqual(code, 0)
        self.assertIn("플러그인 소스", out)

    def test_room_path(self):
        code, out, err = self._run("room", "--path", self.room)
        self.assertEqual((code, room.room_state(self.room)), (0, "ok"))
        self.assertEqual(self._run("room", "--path", self.room)[0], 0)
        code, out, err = self._run("room", "--path", os.path.join(room.PLUGIN_ROOT, "x"))
        self.assertEqual(code, 2)
        self.assertIn("플러그인 소스", out)

    def test_bad_arguments(self):
        for argv in (("setup", "extra"), ("room", "--bogus"), ("room", "--path"), ("dict", "x"), ("policy", "x")):
            code, out, err = self._run(*argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertIn("사용법 오류", err)


if __name__ == "__main__":
    unittest.main()
