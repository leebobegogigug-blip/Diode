# -*- coding: utf-8 -*-
"""훅 (diodelib.hook · SP-11) 과 방 상태 (diodelib.room · SP-10). 합성 자리 · 합성 단어만."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import hook, room  # noqa: E402

WORD = "KITWORDALPHA"
ROOM_SETTINGS = {"autoMemoryEnabled": False, "permissions": {"defaultMode": "default", "deny": ["Bash", "WebFetch"]}}


def write_json(path, obj):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def make_room(folder):
    settings = os.path.join(folder, ".claude", "settings.json")
    write_json(settings, ROOM_SETTINGS)
    with open(settings, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    write_json(os.path.join(folder, ".diode-room"), {"format": 1, "created": "2026-11-05T00:00:00Z",
                                                     "settings_sha256": sha})
    for sub in ("outbox", "inbox", "work"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-hook-"))
        self.home = os.path.join(self.tmp, "data")
        self.raw = os.path.join(self.tmp, "kitraw")
        self.room = os.path.join(self.tmp, "claude", "room")
        self.other = os.path.join(self.tmp, "other")
        for d in (self.raw, self.other):
            os.makedirs(d)
        with open(os.path.join(self.raw, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("KIT_RAW_TEXT_CANARY")
        make_room(self.room)
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 1, "words": [WORD]})
        write_json(os.path.join(self.home, "config.json"), {"format": 1, "policy": {"raw_dirs": [self.raw]}})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, event, data, project, home=None):
        data = dict(data)
        data.setdefault("cwd", project)
        code, out, err = hook.run(event, json.dumps(data).encode("utf-8"), home=home or self.home,
                                  env={"CLAUDE_PROJECT_DIR": project})
        for text in (out, err):
            self.assertNotIn(WORD, text.upper())
            self.assertNotIn("kitraw", text)
            self.assertNotIn(self.tmp, text)
        return code, out, err

    def prompt(self, text, project, **kw):
        extra = {k: v for k, v in kw.items() if k != "home"}
        return self.call("prompt", dict({"prompt": text, "permission_mode": "default"}, **extra), project,
                         home=kw.get("home"))

    def tool(self, name, ti, project, home=None):
        return self.call("tool", {"tool_name": name, "tool_input": ti}, project, home=home)

    def assertDenied(self, res):
        code, out, err = res
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def assertAllowed(self, res):
        self.assertEqual(res, (0, "", ""))


class RoomState(Base):
    def test_ok(self):
        self.assertEqual(room.room_state(self.room), "ok")
        self.assertEqual(room.room_state(self.other), "missing")

    def test_changed_settings(self):
        write_json(os.path.join(self.room, ".claude", "settings.json"), {"permissions": {"defaultMode": "auto"}})
        self.assertEqual(room.room_state(self.room), "changed")

    def test_changed_overrides(self):
        for rel in (os.path.join(".claude", "settings.local.json"), ".mcp.json"):
            p = os.path.join(self.room, rel)
            write_json(p, {})
            self.assertEqual(room.room_state(self.room), "changed", rel)
            os.remove(p)
        self.assertEqual(room.room_state(self.room), "ok")

    def test_broken_marker(self):
        with open(os.path.join(self.room, ".diode-room"), "w") as f:
            f.write("{")
        self.assertEqual(room.room_state(self.room), "changed")

    def test_default_data_dir_ignores_diode_home(self):
        old = os.environ.get("DIODE_HOME")
        os.environ["DIODE_HOME"] = self.tmp
        try:
            self.assertNotEqual(room.default_data_dir(), self.tmp)
        finally:
            if old is None:
                del os.environ["DIODE_HOME"]
            else:
                os.environ["DIODE_HOME"] = old


class Modes(Base):
    def test_modes(self):
        s = hook.load_settings(self.home)
        self.assertEqual(s.state, "ok")
        self.assertEqual(hook.mode_of(self.raw, s)[0], "raw")
        self.assertEqual(hook.mode_of(os.path.join(self.raw, "sub"), s)[0], "raw")
        self.assertEqual(hook.mode_of(self.tmp, s)[0], "raw")            # 원자료 폴더를 품은 폴더
        self.assertEqual(hook.mode_of(self.room, s)[0], "room")
        self.assertEqual(hook.mode_of(self.other, s)[0], "other")

    def test_room_inside_raw_is_raw(self):
        inner = os.path.join(self.raw, "room")
        make_room(inner)
        self.assertEqual(hook.mode_of(inner, hook.load_settings(self.home))[0], "raw")


class Prompt(Base):
    def test_raw_blocks_everything(self):
        code, out, err = self.prompt("안녕", self.raw)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("원자료 폴더", err)

    def test_room_clean_and_dirty(self):
        self.assertEqual(self.prompt("화면 초안을 그려 달라", self.room), (0, "", ""))
        code, out, err = self.prompt("kit-word alpha 를 그려 달라", self.room)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("DIODE V<Vth 막힘 · D2 x1 @L1"), err)
        code, _, err = self.prompt("파일은 D:\\work\\a", self.room)
        self.assertEqual(code, 2)
        self.assertIn("D3", err)

    def test_room_auto_mode_blocks(self):
        for pm in ("auto", "bypassPermissions", "새로운모드"):
            code, _, err = self.prompt("화면", self.room, permission_mode=pm)
            self.assertEqual(code, 2, pm)
            self.assertIn("수동", err)
        for pm in ("default", "plan", "acceptEdits"):
            self.assertEqual(self.prompt("화면", self.room, permission_mode=pm)[0], 0, pm)

    def test_room_changed_blocks(self):
        write_json(os.path.join(self.room, ".claude", "settings.local.json"), {"permissions": {"allow": ["Bash"]}})
        code, _, err = self.prompt("화면", self.room)
        self.assertEqual(code, 2)
        self.assertIn("changed", err)

    def test_other_belt(self):
        self.assertEqual(self.prompt("평범한 질문", self.other)[0], 0)
        self.assertEqual(self.prompt("KitWordAlpha 의 일", self.other)[0], 2)

    def test_unset(self):
        empty = os.path.join(self.tmp, "empty")
        self.assertEqual(self.prompt("KITWORDALPHA", self.other, home=empty)[0], 0)   # 설정 전 — 지켜지지 않는다
        self.assertEqual(self.prompt("화면", self.room, home=empty)[0], 2)           # 방은 설정 없이 쓰지 않는다

    def test_broken_dictionary(self):
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 9, "words": [WORD]})
        self.assertEqual(self.prompt("평범한 질문", self.other)[0], 2)
        self.assertEqual(self.prompt("/diode:setup", self.other)[0], 0)
        self.assertEqual(self.prompt("/diode:setup", self.room)[0], 2)

    def test_bad_input(self):
        code, out, err = hook.run("prompt", b"{", home=self.home, env={"CLAUDE_PROJECT_DIR": self.other})
        self.assertEqual(code, 2)
        self.assertIn("E-20", err)
        self.assertEqual(hook.run("prompt", b'{"prompt": 3}', home=self.home,
                                  env={"CLAUDE_PROJECT_DIR": self.other})[0], 2)
        self.assertEqual(hook.run("nope", b"{}", home=self.home, env={})[0], 2)


class ToolRoom(Base):
    def test_raw_denies_all(self):
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(self.raw, "secret.txt")}, self.raw))
        self.assertDenied(self.tool("TodoWrite", {"todos": []}, self.raw))

    def test_file_tools_inside_only(self):
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(self.room, "work", "a.md")}, self.room))
        self.assertAllowed(self.tool("Write", {"file_path": "work/b.md", "content": "x"}, self.room))
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(self.raw, "secret.txt")}, self.room))
        self.assertDenied(self.tool("Read", {"file_path": "../../kitraw/secret.txt"}, self.room))
        self.assertDenied(self.tool("Glob", {"pattern": "../**/*.txt"}, self.room))
        self.assertDenied(self.tool("Glob", {"pattern": "*.txt", "path": self.raw}, self.room))
        self.assertDenied(self.tool("Grep", {"pattern": "x", "path": self.other}, self.room))
        self.assertDenied(self.tool("Read", {"file_path": 3}, self.room))

    @unittest.skipIf(os.name == "nt", "심볼릭 링크는 Windows 에서 권한이 필요하다")
    def test_symlink_out_of_room(self):
        link = os.path.join(self.room, "work", "link")
        os.symlink(self.raw, link)
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(link, "secret.txt")}, self.room))

    def test_protected_places(self):
        for rel in (".claude/settings.json", ".claude/settings.local.json", ".diode-room", ".mcp.json",
                    "outbox/J-0001.md", "CLAUDE.md"):
            self.assertDenied(self.tool("Write", {"file_path": os.path.join(self.room, rel), "content": "{}"},
                                        self.room))
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(self.room, ".claude", "settings.json")},
                                     self.room))

    def test_tools(self):
        for name in ("Bash", "WebFetch", "PowerShell", "mcp__other__read", "NewToolNobodyKnows"):
            self.assertDenied(self.tool(name, {"command": "ls"}, self.room))
        self.assertAllowed(self.tool("WebSearch", {"query": "q"}, self.room))
        self.assertAllowed(self.tool("ToolSearch", {"query": "select:x"}, self.room))
        self.assertAllowed(self.tool("mcp__plugin_diode_hub__dispatch", {"instruction": "x"}, self.room))
        self.assertAllowed(self.tool("Skill", {"skill": "diode"}, self.room))
        self.assertDenied(self.tool("Skill", {"skill": "someone-else"}, self.room))

    def test_web_search_off(self):
        write_json(os.path.join(self.home, "config.json"),
                   {"format": 1, "policy": {"raw_dirs": [self.raw], "web_search": False}})
        self.assertDenied(self.tool("WebSearch", {"query": "q"}, self.room))

    def test_outbox_needs_confirmed_hash(self):
        p = os.path.join(self.room, "outbox", "J-0007.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("[diode report format=1 job=J-0007 status=done]\n")
        self.assertDenied(self.tool("Read", {"file_path": p}, self.room))
        self.assertDenied(self.tool("Grep", {"pattern": "x"}, self.room))               # 방 전체 Grep 은 outbox 를 읽는다
        with open(p, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        write_json(os.path.join(self.home, "audit", "2026-11", "J-0007-1-out.json"),
                   {"format": 1, "direction": "out", "decision": "sent", "sha256": sha})
        self.assertAllowed(self.tool("Read", {"file_path": p}, self.room))
        with open(p, "a", encoding="utf-8") as f:
            f.write("덧붙인 글\n")
        self.assertDenied(self.tool("Read", {"file_path": p}, self.room))              # 확정 뒤에 바뀜

    def test_room_needs_settings(self):
        empty = os.path.join(self.tmp, "empty")
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(self.room, "work", "a.md")}, self.room,
                                    home=empty))


class ToolOther(Base):
    def test_belt(self):
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(self.raw, "secret.txt")}, self.other))
        self.assertDenied(self.tool("Grep", {"pattern": "x", "path": self.raw}, self.other))
        self.assertDenied(self.tool("Glob", {"pattern": "*", "path": self.tmp}, self.other))   # 원자료를 품은 폴더
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(self.other, "a.txt")}, self.other))
        self.assertDenied(self.tool("Bash", {"command": "cat %s/secret.txt" % self.raw}, self.other))
        self.assertDenied(self.tool("Bash", {"command": "type %s\\secret.txt" % self.raw.replace("/", "\\")},
                                    self.other))
        self.assertAllowed(self.tool("Bash", {"command": "ls"}, self.other))
        self.assertAllowed(self.tool("WebFetch", {"url": "x"}, self.other))

    def test_bash_in_raw_cwd(self):
        code, out, _ = self.call("tool", {"tool_name": "Bash", "tool_input": {"command": "cat secret.txt"},
                                          "cwd": self.raw}, self.other)
        self.assertDenied((code, out, ""))

    def test_no_raw_dirs(self):
        write_json(os.path.join(self.home, "config.json"), {"format": 1, "policy": {"raw_dirs": []}})
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(self.raw, "secret.txt")}, self.other))

    def test_bad_input_denies(self):
        code, out, _ = hook.run("tool", b"[]", home=self.home, env={"CLAUDE_PROJECT_DIR": self.other})
        self.assertDenied((code, out, ""))


class InnerTools(Base):
    """안쪽 도구 (opencode) 는 어느 폴더에서 열었든 허브로만 — Claude 가 직접 부르면 결과가 Claude 로 돌아간다."""

    def test_denied_in_every_mode(self):
        for project in (self.other, self.room):
            for name in ("mcp__opencode__run", "mcp__plugin_x_OpenCode__ask"):
                self.assertDenied(self.tool(name, {"prompt": "x"}, project))
        self.assertDenied(self.tool("Agent", {"subagent_type": "opencode-worker", "prompt": "x"}, self.other))
        self.assertDenied(self.tool("Skill", {"skill": "opencode"}, self.other))
        self.assertDenied(self.tool("Bash", {"command": "opencode run '요약해'"}, self.other))
        self.assertDenied(self.tool("Bash", {"command": 5}, self.other))

    def test_hub_and_ordinary_tools_pass(self):
        self.assertAllowed(self.tool("mcp__plugin_diode_hub__dispatch", {"instruction": "x"}, self.room))
        self.assertAllowed(self.tool("Bash", {"command": "ls"}, self.other))
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(self.other, "opencode-notes.txt")}, self.other))

    def test_works_before_setup(self):
        empty = os.path.join(self.tmp, "empty")
        self.assertDenied(self.tool("mcp__opencode__run", {}, self.other, home=empty))

    def test_extra_names_from_config(self):
        self.assertAllowed(self.tool("mcp__innerx__ask", {}, self.other))
        write_json(os.path.join(self.home, "config.json"),
                   {"format": 1, "policy": {"raw_dirs": [self.raw], "inner_tools": ["InnerX"]}})
        self.assertDenied(self.tool("mcp__innerx__ask", {}, self.other))
        self.assertDenied(self.tool("mcp__opencode__run", {}, self.other))        # 기본 목록은 그대로
        write_json(os.path.join(self.home, "config.json"),
                   {"format": 1, "policy": {"raw_dirs": [self.raw], "inner_tools": "innerx"}})
        code, _, err = self.prompt("평범한 질문", self.other)                       # 꼴이 틀리면 설정이 깨진 것
        self.assertEqual(code, 2)


class DataFolderGuard(Base):
    """사전 · 설정 · 기록이 든 데이터 폴더와 플러그인 소스는 Claude 가 읽거나 고치지 않는다 — 정책은 사람이 창에서만 (AL-12)."""

    def test_file_tools_denied_everywhere(self):
        d = os.path.join(self.home, "dictionary.json")
        for project in (self.other, self.room):
            for name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
                self.assertDenied(self.tool(name, {"file_path": d, "content": "x"}, project))
        for rel in ("config.json", os.path.join("audit", "2026-11", "J-0001-001-out.json"), os.path.join("queue", "x.json")):
            self.assertDenied(self.tool("Read", {"file_path": os.path.join(self.home, rel)}, self.other))
        self.assertDenied(self.tool("Grep", {"pattern": "x", "path": self.home}, self.other))
        self.assertDenied(self.tool("Glob", {"pattern": "*", "path": self.home}, self.other))

    def test_listing_the_parent_is_fine_but_searching_its_content_is_not(self):
        # 데이터 폴더를 품은 위 폴더 (원자료 폴더는 없음): 이름만 보는 Glob 은 통과 · 내용을 읽는 Grep 은 막음
        parent = os.path.join(self.tmp, "up")
        home = os.path.join(parent, "diode-data")
        os.makedirs(home)
        write_json(os.path.join(home, "dictionary.json"), {"format": 1, "words": [WORD]})
        write_json(os.path.join(home, "config.json"), {"format": 1, "policy": {"raw_dirs": []}})
        self.assertAllowed(self.tool("Glob", {"pattern": "*.nothing", "path": parent}, self.other, home=home))
        self.assertDenied(self.tool("Grep", {"pattern": "x", "path": parent}, self.other, home=home))
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(home, "dictionary.json")}, self.other, home=home))

    def test_shell_mentions(self):
        for cmd in ("cat %s/dictionary.json" % self.home, "type %s\\config.json" % self.home.replace("/", "\\"),
                    "cat ~/.local/share/diode/dictionary.json", "type %LOCALAPPDATA%\\diode\\config.json",
                    "ls diode/audit"):
            self.assertDenied(self.tool("Bash", {"command": cmd}, self.other))
        self.assertAllowed(self.tool("Bash", {"command": "ls"}, self.other))
        self.assertAllowed(self.tool("Bash", {"command": 'python "/x/diode/diode.py" setup'}, self.other))
        code, out, _ = self.call("tool", {"tool_name": "Bash", "tool_input": {"command": "cat dictionary.json"},
                                          "cwd": self.home}, self.other)
        self.assertDenied((code, out, ""))                                    # 데이터 폴더 안에서 연 셸

    def test_plugin_source_is_write_protected_but_readable(self):
        from diodelib.room import PLUGIN_ROOT
        f = os.path.join(PLUGIN_ROOT, "diode.py")
        for name in ("Write", "Edit", "MultiEdit"):
            self.assertDenied(self.tool(name, {"file_path": f, "content": "x"}, self.other))
        self.assertAllowed(self.tool("Read", {"file_path": f}, self.other))

    def test_hub_tools_and_ordinary_paths_pass(self):
        self.assertAllowed(self.tool("mcp__plugin_diode_hub__status", {}, self.room))
        self.assertAllowed(self.tool("Write", {"file_path": os.path.join(self.other, "a.txt"), "content": "x"}, self.other))

    def test_before_setup_too(self):
        empty = os.path.join(self.tmp, "empty")
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(empty, "dictionary.json")}, self.other, home=empty))


class ReadScan(Base):
    """원자료 폴더 목록 밖의 파일도 내용에 사내 단어가 있으면 읽지 못한다 — 안전벨트가 이름이 아니라 내용도 본다."""

    def _file(self, name, data):
        p = os.path.join(self.other, name)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(p, mode, **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
            f.write(data)
        return p

    def test_file_with_a_dictionary_word_is_denied_anywhere(self):
        for text in ("메모\n%s 프로젝트\n" % WORD, "kit-word alpha 의 일", "ＫＩＴＷＯＲＤＡＬＰＨＡ"):
            code, out, _ = self.tool("Read", {"file_path": self._file("n.txt", text)}, self.other)
            self.assertDenied((code, out, ""))
            self.assertIn("D2 x1", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_clean_files_and_special_cases_pass(self):
        self.assertAllowed(self.tool("Read", {"file_path": self._file("ok.txt", "평범한 메모\n")}, self.other))
        self.assertAllowed(self.tool("Read", {"file_path": self._file("img.png", b"\x89PNG\x00" + WORD.encode())}, self.other))
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(self.other, "없는파일.txt")}, self.other))
        self.assertAllowed(self.tool("Read", {"file_path": "ok.txt"}, self.other))                       # 상대 경로 (cwd)

    def test_too_big_is_denied(self):
        from diodelib import hook
        p = self._file("big.txt", "가" * 10)
        saved = hook.READ_SCAN_MAX
        hook.READ_SCAN_MAX = 5
        try:
            code, out, _ = self.tool("Read", {"file_path": p}, self.other)
        finally:
            hook.READ_SCAN_MAX = saved
        self.assertDenied((code, out, ""))
        self.assertIn("너무 커서", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_output_has_no_word_or_path(self):
        code, out, err = self.tool("Read", {"file_path": self._file("secret-name.txt", WORD)}, self.other)
        self.assertNotIn("secret-name", out)
        self.assertNotIn(WORD.lower(), out.lower())

    def test_not_before_setup(self):
        empty = os.path.join(self.tmp, "empty")
        self.assertAllowed(self.tool("Read", {"file_path": self._file("n.txt", WORD)}, self.other, home=empty))

    def test_room_files_are_not_scanned_here(self):
        # 방은 방 안의 파일만 읽고 (다른 규칙) 방 안에는 원자료가 없다 — 내용 검사는 방 밖 (그 밖의 폴더) 에서만
        p = os.path.join(self.room, "work", "a.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("평범한 글")
        self.assertAllowed(self.tool("Read", {"file_path": p}, self.room))


class Session(Base):
    def test_messages(self):
        self.assertEqual(self.call("session", {}, self.room), (0, "", ""))
        code, out, _ = self.call("session", {}, self.other, home=os.path.join(self.tmp, "empty"))
        self.assertIn("/diode:setup", json.loads(out)["systemMessage"])
        write_json(os.path.join(self.room, ".mcp.json"), {})
        code, out, _ = self.call("session", {}, self.room)
        self.assertIn("changed", json.loads(out)["systemMessage"])


class Cli(Base):
    """diode.py hook — 하위 프로세스 · 기본 데이터 폴더 (HOME 아래) · DIODE_HOME 은 무시."""

    def _run(self, event, data, project, env_extra=None):
        home_dir = os.path.join(self.tmp, "userhome")
        data_dir = (os.path.join(home_dir, "AppData", "Local", "diode") if os.name == "nt"
                    else os.path.join(home_dir, ".local", "share", "diode"))
        if not os.path.isdir(data_dir):
            shutil.copytree(self.home, data_dir)
        env = dict(os.environ)
        env.update({"HOME": home_dir, "USERPROFILE": home_dir, "LOCALAPPDATA": os.path.join(home_dir, "AppData", "Local"),
                    "CLAUDE_PROJECT_DIR": project, "PYTHONIOENCODING": "utf-8"})
        env.pop("DIODE_HOME", None)
        env.update(env_extra or {})
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py"), "hook", event],
                           input=json.dumps(data).encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, timeout=60)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_prompt_block_and_pass(self):
        code, out, err = self._run("prompt", {"prompt": "KitWordAlpha", "cwd": self.room}, self.room)
        self.assertEqual((code, out), (2, ""))
        self.assertNotIn("KITWORD", err.upper())
        self.assertEqual(self._run("prompt", {"prompt": "화면", "cwd": self.room, "permission_mode": "default"},
                                   self.room), (0, "", ""))

    def test_diode_home_is_ignored(self):
        fake = os.path.join(self.tmp, "fake")
        write_json(os.path.join(fake, "dictionary.json"), {"format": 1, "words": ["ZZQQXX"]})
        code, _, _ = self._run("prompt", {"prompt": "KitWordAlpha", "cwd": self.other}, self.other,
                               {"DIODE_HOME": fake})
        self.assertEqual(code, 2)

    def test_tool_deny(self):
        code, out, err = self._run("tool", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": self.room},
                                   self.room)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")


class PluginHooksFile(unittest.TestCase):
    def test_hooks_json(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
            h = json.load(f)["hooks"]
        self.assertEqual(set(h), {"SessionStart", "UserPromptSubmit", "PreToolUse"})
        events = {"SessionStart": "session", "UserPromptSubmit": "prompt", "PreToolUse": "tool"}
        for name, groups in h.items():
            for g in groups:
                for x in g["hooks"]:
                    self.assertEqual(x["command"], "python")                   # 이름만 (L-30)
                    self.assertEqual(x["args"], ["${CLAUDE_PLUGIN_ROOT}/diode.py", "hook", events[name]])
                    self.assertEqual(x["onFailure"], "block")
                    self.assertLessEqual(x["timeout"], 10)
        self.assertEqual(h["PreToolUse"][0]["matcher"], "*")


if __name__ == "__main__":
    unittest.main()
