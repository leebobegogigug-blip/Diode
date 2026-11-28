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
        self.userdir = os.path.join(self.tmp, "userclaude")                      # 훅이 읽는 사용자 폴더 (이 PC 의 것을 건드리지 않는다)
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 1, "words": [WORD]})
        write_json(os.path.join(self.home, "config.json"), {"format": 1, "policy": {"raw_dirs": [self.raw]}})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, event, data, project, home=None, env_extra=None):
        data = dict(data)
        data.setdefault("cwd", project)
        env = {"CLAUDE_PROJECT_DIR": project, "CLAUDE_CONFIG_DIR": self.userdir}
        env.update(env_extra or {})
        code, out, err = hook.run(event, json.dumps(data).encode("utf-8"), home=home or self.home, env=env)
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
        self.assertAllowed(self.tool("Skill", {"skill": "diode:status"}, self.room))
        self.assertDenied(self.tool("Skill", {"skill": "diode:../x"}, self.room))
        self.assertDenied(self.tool("Skill", {"skill": "diode:a b"}, self.room))
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

    def test_outbox_bundle_folder_files_need_confirmed_hashes(self):
        """가린 묶음 (SP-20) 의 outbox/<job>/ 파일도 확정 해시가 있어야 Read 된다 (AL-13 · 감사 기록 kind bundle)."""
        from diodelib import audit
        d = os.path.join(self.room, "outbox", "J-0008")
        os.makedirs(d)
        files = {"F01.md": "PH_K7Q2 의 글\n", "MANIFEST.md": "# MANIFEST J-0008\n"}
        for name, text in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        for name in files:
            self.assertDenied(self.tool("Read", {"file_path": os.path.join(d, name)}, self.room))
        audit.record(self.home, "J-0008", "out", "bundle", "room", "sent", text=files["F01.md"])
        self.assertAllowed(self.tool("Read", {"file_path": os.path.join(d, "F01.md")}, self.room))
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(d, "MANIFEST.md")}, self.room))   # 확정 안 됨
        self.assertDenied(self.tool("Read", {"file_path": d}, self.room))                                # 폴더 자체
        self.assertDenied(self.tool("Grep", {"pattern": "x", "path": d}, self.room))
        self.assertDenied(self.tool("Write", {"file_path": os.path.join(d, "F02.md"), "content": "x"}, self.room))
        with open(os.path.join(d, "F01.md"), "a", encoding="utf-8") as f:
            f.write("덧붙인 글\n")
        self.assertDenied(self.tool("Read", {"file_path": os.path.join(d, "F01.md")}, self.room))       # 확정 뒤에 바뀜

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

    def test_git_bash_drive_forms_count_as_the_same_folder(self):
        """Git Bash (/d/..) · Cygwin · WSL 꼴로 쓴 Windows 경로도 같은 폴더다 - 벨트가 지나가면 안 된다"""
        forms = hook._path_forms("D:\\Data\\Raw")
        for want in ("d:/data/raw", "/d/data/raw", "/cygdrive/d/data/raw", "/mnt/d/data/raw"):
            self.assertIn(want, forms)
        raw = ["D:\\Data\\Raw"]
        for cmd in ("cat /d/data/raw/secret.txt", "cd /D/DATA/RAW && ls", "cat /mnt/d/data/raw/a",
                    "type d:\\data\\raw\\a", "cat /cygdrive/d/data/raw/a", "cat D:/Data/Raw/a"):
            self.assertTrue(hook._mentions_raw(cmd, raw, "/nowhere-cwd"), cmd)
        for cmd in ("ls /d/data/other", "cat /d/dat", "ls /e/data/raw", "echo hi"):
            self.assertFalse(hook._mentions_raw(cmd, raw, "/nowhere-cwd"), cmd)

    def test_git_bash_drive_forms_for_the_data_folder(self):
        for cmd in ("cat /c/Users/x/AppData/Local/diode/dictionary.json", "ls /mnt/c/users/x/appdata/local/diode/audit"):
            self.assertTrue(hook._mentions_data(cmd, "C:\\Users\\x\\AppData\\Local\\diode", "/nowhere-cwd"), cmd)
        self.assertFalse(hook._mentions_data("ls /c/Users/x/Documents", "C:\\Users\\x\\AppData\\Local\\diode", "/nowhere-cwd"))

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

    def test_vault_is_not_readable(self):
        # 가명 금고 (SP-20) 는 데이터 폴더 안이다 - 파일 도구 · 셸 어느 쪽으로도 읽지 못한다 (진짜 값 · 원래 파일 이름)
        v = os.path.join(self.home, "vault", "P-0001.vault")
        write_json(v, {"x": 1})
        for project in (self.other, self.room):
            for name in ("Read", "Write", "Edit"):
                self.assertDenied(self.tool(name, {"file_path": v, "content": "x"}, project))
            self.assertDenied(self.tool("Grep", {"pattern": "PH_", "path": os.path.dirname(v)}, project))
            self.assertDenied(self.tool("Glob", {"pattern": "*.vault", "path": os.path.dirname(v)}, project))
        for cmd in ("cat %s" % v, "cat %s" % v.replace("/", "\\"), "type %s\\vault\\active" % self.home.replace("/", "\\"),
                    "cat ~/.local/share/diode/vault/P-0001.vault", "type %LOCALAPPDATA%\\diode\\vault\\P-0001.vault",
                    "cat diode/vault/P-0001.vault", "ls diode\\vault"):
            self.assertDenied(self.tool("Bash", {"command": cmd}, self.other))
        code, out, _ = self.call("tool", {"tool_name": "Bash", "tool_input": {"command": "cat P-0001.vault"},
                                          "cwd": os.path.dirname(v)}, self.other)
        self.assertDenied((code, out, ""))
        self.assertAllowed(self.tool("Bash", {"command": 'python "/x/diode/diode.py" project status'}, self.other))

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


class SwitchGuard(Base):
    """Claude 가 도구로 다음 세션의 Diode 를 끄지 못한다 — Claude Code 설정 파일 쓰기 · claude plugin 끄기 · Diode 없는
    claude 띄우기 (SP-11 · L-28 · AL-12). 사람이 끄는 것은 관리형 설정이 맡는다. 합성 자리만 (이 PC 의 설정은 건드리지 않는다)."""

    # 프로젝트 설정에 이 글을 쓰면 막는다 - 마지막 둘: 낱말 diode (대소문자 무시) · JSON 이스케이프로 감춘 꼴
    OFF_TEXTS = ('{"enabledPlugins": {"diode@diode": false}}', '{"disableAllHooks": true}',
                 '{"permissions": {"deny": ["Read(./Diode-notes/**)"]}}',
                 '{"\\u0065nabledPlugins": {"\\u0064iode@\\u0064iode": false}}')
    # 요청받은 여섯 꼴 (Bash 다섯 · PowerShell 하나)
    SPEC_SHELL = (("Bash", "claude plugin disable diode@diode"), ("Bash", "claude plugin uninstall x"),
                  ("Bash", "echo '{\"disableAllHooks\":true}' > .claude/settings.local.json"),
                  ("Bash", "sed -i 's/true/false/' .claude/settings.json"),
                  ("Bash", "claude --settings '{\"model\": \"x\"}' -p hi"),
                  ("PowerShell", "Set-Content .claude\\settings.local.json '{}'"))
    MORE_SHELL = (
        "claude plugins remove diode", "claude plugin marketplace remove diode", "claude plugin marketplace rm diode",
        "claude plugin disable --scope user diode@diode", "/usr/local/bin/claude plugin disable diode",
        "npx @anthropic-ai/claude-code plugin uninstall diode@diode", 'cl"aude" plugin disable diode',
        "cl\\aude plugin disable x", "cd /tmp && claude plugin uninstall diode@diode",
        # Diode 없는 claude 를 띄우는 꼴 (2.1.318 의 --help 에 있는 것)
        "claude --setting-sources project -p hi", "claude --bare -p hi", "claude --safe-mode", "claude --restricted -p hi",
        "claude -p hi --settings=./s.json", "CLAUDE_CODE_SIMPLE=1 claude -p hi", "CLAUDE_CONFIG_DIR=/tmp/empty claude -p hi",
        # 설정 낱말 - 읽기라도 막는다 (헛걸림은 사람이 보면 된다)
        "python3 -c \"import json; d={}; d['enabledPlugins']={}; print(d)\"", "grep -r disableAllHooks .",
        # 설정 자리 + 쓰기 꼴
        "echo {} > ~/.claude/settings.json", "cp /tmp/s.json ~/.claude/settings.json", "rm -rf ~/.claude/plugins",
        "mv x.json .claude/settings.local.json", "cat a.json | tee .claude/settings.json",
        "jq '.x=1' .claude/settings.json > t && mv t .claude/settings.json", "echo {} >> ~/.claude.json",
        "cp x.json /etc/claude-code/managed-settings.json", "cd .claude && echo {} > settings.local.json",
        "python3 -c \"open('/home/x/.claude/settings.json','w').write('{}')\"",
        "sed --in-place 's/a/b/' .claude/settings.json", "cp x.json $CLAUDE_CONFIG_DIR/settings.json",
        "cp x.json \"${CLAUDE_CONFIG_DIR}/plugins/known_marketplaces.json\"")
    MORE_PS = ("Out-File -FilePath .claude\\settings.json", "Add-Content -Path $env:USERPROFILE\\.claude\\settings.json -Value x",
               "Remove-Item .claude\\settings.local.json", "New-Item -Path .claude\\settings.local.json -Force",
               "del .claude\\settings.json", "& claude.exe plugin disable diode@diode",
               "'{}' | Set-Content \"$env:USERPROFILE\\.claude\\settings.json\"", "$env:CLAUDE_CONFIG_DIR = 'C:\\x'; claude")
    SHELL_OK = ("cat .claude/settings.json", "cat .claude/settings.json 2>/dev/null", "ls -la ~/.claude/plugins",
                "jq . ~/.claude/settings.json", "claude plugin list", "claude plugin install diode@diode",
                "claude plugin enable diode@diode", "claude plugin details diode", "claude plugin validate .",
                "claude -p hi", "claude --version", "claude mcp list", "python manage.py runserver --settings=mysite.settings",
                "vagrant plugin uninstall foo", "asdf plugin remove nodejs", "grep -r x . > out.txt", "echo hello",
                "cat D:/claude/room/notes.md", "ls ~/.claude", "cat ~/.claude/CLAUDE.md", "git status")

    def setUp(self):
        super(SwitchGuard, self).setUp()
        self.userhome = os.path.join(self.tmp, "userhome")                # 훅이 보는 홈 (.claude · .claude.json 이 있는 곳)
        os.makedirs(self.userhome)

    def st(self, name, ti, project=None, home=None, cwd=None):
        data = {"tool_name": name, "tool_input": ti}
        if cwd:
            data["cwd"] = cwd
        return self.call("tool", data, project or self.other, home=home,
                         env_extra={"HOME": self.userhome, "USERPROFILE": self.userhome})

    def assertSwitch(self, res, what=""):
        code, out, _ = res
        self.assertEqual(code, 0, what)
        self.assertTrue(out, "지나감: %s" % (what,))
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny", what)
        self.assertEqual(hso["permissionDecisionReason"], hook.MSG["switch"], what)

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_project_settings_with_switch_words_are_denied(self):
        for project in (self.other, self.room):
            for rel in (os.path.join(".claude", "settings.json"), os.path.join(".claude", "settings.local.json")):
                p = os.path.join(self.other, rel)
                for text in self.OFF_TEXTS:
                    self.assertSwitch(self.st("Write", {"file_path": p, "content": text}, project), (project, rel, text))
        # 어느 폴더든 · 상대 경로 · 이름의 대소문자 · NotebookEdit
        deep = os.path.join(self.other, "a", "b", ".claude", "settings.local.json")
        self.assertSwitch(self.st("Write", {"file_path": deep, "content": self.OFF_TEXTS[0]}))
        self.assertSwitch(self.st("Write", {"file_path": ".claude/settings.local.json", "content": self.OFF_TEXTS[1]}))
        self.assertSwitch(self.st("Write", {"file_path": os.path.join(self.other, ".Claude", "Settings.Local.JSON"),
                                            "content": self.OFF_TEXTS[0]}))
        self.assertSwitch(self.st("NotebookEdit", {"notebook_path": deep, "new_source": self.OFF_TEXTS[1]}))

    def test_ordinary_project_settings_pass(self):
        p = os.path.join(self.other, ".claude", "settings.json")
        perms = '{"permissions": {"allow": ["Bash(ls:*)"], "deny": ["WebFetch"]}}'
        self.assertAllowed(self.st("Write", {"file_path": p, "content": perms}))           # 새 파일 · 권한 규칙만
        self.put(p, perms)
        self.assertAllowed(self.st("Write", {"file_path": p, "content": '{"permissions": {}}'}))   # 덮을 파일에도 낱말 없음
        self.assertAllowed(self.st("Edit", {"file_path": p, "old_string": '"WebFetch"',
                                            "new_string": '"WebFetch", "Bash(rm:*)"'}))
        self.assertAllowed(self.st("Read", {"file_path": p}))
        self.assertAllowed(self.st("Write", {"file_path": os.path.join(self.other, ".claude", "notes.md"), "content": "diode"}))

    def test_edit_that_touches_the_switch_is_denied(self):
        p = self.put(os.path.join(self.other, ".claude", "settings.json"),
                     '{"enabledPlugins": {"diode@diode": true}, "permissions": {"allow": []}}')
        self.assertSwitch(self.st("Edit", {"file_path": p, "old_string": '"diode@diode": true', "new_string": ""}))
        self.assertSwitch(self.st("Edit", {"file_path": p, "old_string": '"allow": []',
                                           "new_string": '"allow": [], "disableAllHooks": true'}))
        self.assertSwitch(self.st("MultiEdit", {"file_path": p, "edits": [
            {"old_string": '"allow": []', "new_string": '"allow": ["Read"]'},
            {"old_string": '{"diode@diode": true}', "new_string": "{}"}]}))
        # 권한 규칙만 고치는 Edit 는 통과 (enabledPlugins 가 든 파일이라도 - 헛걸림을 줄이려고)
        self.assertAllowed(self.st("Edit", {"file_path": p, "old_string": '"allow": []', "new_string": '"allow": ["Read"]'}))

    def test_write_that_drops_the_switch_is_denied(self):
        p = self.put(os.path.join(self.other, ".claude", "settings.local.json"), '{"enabledPlugins": {"diode@diode": true}}')
        self.assertSwitch(self.st("Write", {"file_path": p, "content": '{"permissions": {}}'}))
        # 덮을 파일을 못 읽으면 막는다: 폴더 · 너무 큼
        d = os.path.join(self.other, "x", ".claude", "settings.json")
        os.makedirs(d)
        self.assertSwitch(self.st("Write", {"file_path": d, "content": "{}"}))
        q = self.put(os.path.join(self.other, "y", ".claude", "settings.json"), '{"permissions": {}}')
        saved = hook.SWITCH_READ_MAX
        hook.SWITCH_READ_MAX = 5
        try:
            self.assertSwitch(self.st("Write", {"file_path": q, "content": "{}"}))
        finally:
            hook.SWITCH_READ_MAX = saved
        self.assertAllowed(self.st("Write", {"file_path": q, "content": "{}"}))
        # UTF-16 으로 저장된 옛 파일도 풀어서 본다
        r = os.path.join(self.other, "z", ".claude", "settings.json")
        os.makedirs(os.path.dirname(r))
        with open(r, "wb") as f:
            f.write(b"\xff\xfe" + '{"disableAllHooks": false}'.encode("utf-16-le"))
        self.assertSwitch(self.st("Write", {"file_path": r, "content": "{}"}))

    def test_user_scope_settings_and_plugins_regardless_of_content(self):
        for d in (self.userdir, os.path.join(self.userhome, ".claude")):           # CLAUDE_CONFIG_DIR · 홈의 .claude
            for rel in ("settings.json", "settings.local.json", os.path.join("plugins", "known_marketplaces.json"),
                        os.path.join("plugins", "installed_plugins.json"),
                        os.path.join("plugins", "cache", "diode", "diode", "0.0.0", "hooks", "hooks.json")):
                p = os.path.join(d, rel)
                for name, ti in (("Write", {"file_path": p, "content": "{}"}),
                                 ("Edit", {"file_path": p, "old_string": "a", "new_string": "b"}),
                                 ("MultiEdit", {"file_path": p, "edits": [{"old_string": "a", "new_string": "b"}]})):
                    for project in (self.other, self.room):
                        self.assertSwitch(self.st(name, ti, project), (name, rel))
        self.assertAllowed(self.st("Read", {"file_path": os.path.join(self.userdir, "settings.json")}))
        self.assertAllowed(self.st("Write", {"file_path": os.path.join(self.userdir, "notes", "a.md"), "content": "x"}))

    def test_state_file_and_managed_settings_anywhere(self):
        for p in (os.path.join(self.userhome, ".claude.json"), os.path.join(self.userdir, ".claude.json"),
                  os.path.join(self.tmp, "etc", "claude-code", "managed-settings.json"),
                  os.path.join(self.tmp, "etc", "claude-code", "managed-mcp.json"),
                  os.path.join(self.tmp, "etc", "claude-code", "managed-settings.d", "10-x.json"),
                  os.path.join(self.other, "Managed-Settings.json")):
            for project in (self.other, self.room):
                self.assertSwitch(self.st("Write", {"file_path": p, "content": "{}"}, project), p)
                self.assertSwitch(self.st("Edit", {"file_path": p, "old_string": "a", "new_string": "b"}, project), p)

    def test_before_setup_and_with_broken_settings(self):
        empty = os.path.join(self.tmp, "empty")
        broken = os.path.join(self.tmp, "broken")
        os.makedirs(broken)
        with open(os.path.join(broken, "dictionary.json"), "w") as f:
            f.write("{")
        for home in (empty, broken):
            for project in (self.other, self.room):
                self.assertSwitch(self.st("Write", {"file_path": os.path.join(self.userdir, "settings.json"), "content": "{}"},
                                          project, home=home))
                self.assertSwitch(self.st("Write", {"file_path": os.path.join(self.other, ".claude", "settings.local.json"),
                                                    "content": self.OFF_TEXTS[0]}, project, home=home))
                self.assertSwitch(self.st("Bash", {"command": "claude plugin disable diode@diode"}, project, home=home))

    def test_shell_forms_are_denied(self):
        for project in (self.other, self.room):
            for name, cmd in self.SPEC_SHELL:
                self.assertSwitch(self.st(name, {"command": cmd}, project), cmd)
        for cmd in self.MORE_SHELL:
            self.assertSwitch(self.st("Bash", {"command": cmd}), cmd)
        for cmd in self.MORE_PS:
            self.assertSwitch(self.st("PowerShell", {"command": cmd}), cmd)

    def test_shell_reads_and_ordinary_commands_pass(self):
        for cmd in self.SHELL_OK:
            self.assertAllowed(self.st("Bash", {"command": cmd}))
        self.assertAllowed(self.st("PowerShell", {"command": "Get-Content .claude\\settings.json"}))

    def test_shell_path_resolved_from_the_user_folder(self):
        # 사용자 폴더 안에서 연 셸의 상대 경로 (낱말 · 자리 이름 없이) - 경로를 풀어 본다
        self.put(os.path.join(self.userdir, "settings.json"), "{}")
        self.assertSwitch(self.st("Bash", {"command": "rm settings.json"}, cwd=self.userdir))
        self.assertSwitch(self.st("Bash", {"command": "cp x.json ./plugins/installed_plugins.json"}, cwd=self.userdir))
        self.assertAllowed(self.st("Bash", {"command": "cat settings.json"}, cwd=self.userdir))

    def test_hub_tools_untouched(self):
        self.assertAllowed(self.st("mcp__plugin_diode_hub__status", {"command": "claude plugin disable diode@diode"}))

    @unittest.skipIf(os.name == "nt", "심볼릭 링크는 Windows 에서 권한이 필요하다")
    def test_symlinked_project_settings_that_point_at_user_settings(self):
        target = self.put(os.path.join(self.userdir, "settings.json"), '{"permissions": {}}')
        link = os.path.join(self.other, ".claude", "settings.local.json")
        os.makedirs(os.path.dirname(link))
        os.symlink(target, link)
        self.assertSwitch(self.st("Write", {"file_path": link, "content": '{"permissions": {}}'}))
        self.assertSwitch(self.st("Edit", {"file_path": link, "old_string": "{}", "new_string": "[]"}))

    @unittest.skipUnless(os.name == "nt", "Git Bash 꼴 (/c/Users/..) 은 Windows 에서만 드라이브 경로로 푼다")
    def test_git_bash_form_of_the_user_folder(self):
        p = os.path.join(self.userdir, "settings.json")
        drive, rest = os.path.splitdrive(p)
        posix = "/%s%s" % (drive[0].lower(), rest.replace("\\", "/"))
        self.assertSwitch(self.st("Write", {"file_path": posix, "content": "{}"}))
        self.assertSwitch(self.st("Bash", {"command": "cp x.json %s" % posix}))


class FileMentions(Base):
    """프롬프트의 `@경로` 는 Claude Code 가 도구 호출 없이 파일 내용을 요청에 싣는다 - 훅이 그 경로를 본다 (레드팀 F-01)."""

    def blocked(self, text, project=None):
        code, out, err = self.prompt(text, project or self.other)
        self.assertEqual((code, out), (2, ""), text)
        return err

    def test_raw_folder_files_by_every_spelling(self):
        self.blocked("@../kitraw/secret.txt 요약해")
        self.blocked("이걸 봐 @%s" % os.path.join(self.raw, "secret.txt"))
        self.blocked('"quoted" @"%s" 요약' % os.path.join(self.raw, "secret.txt"))
        self.blocked("(@../kitraw/secret.txt)")
        self.blocked("@../kitraw/secret.txt.")                     # 문장 끝의 마침표
        self.blocked("@../kitraw")                                   # 폴더째

    def test_room_too(self):
        self.blocked("@../../kitraw/secret.txt", self.room)

    def test_a_file_outside_raw_is_read_for_dictionary_words(self):
        bad = os.path.join(self.other, "notes.txt")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("메모 %s 끝" % WORD)
        good = os.path.join(self.other, "ok.txt")
        with open(good, "w", encoding="utf-8") as f:
            f.write("평범한 메모")
        err = self.blocked("@notes.txt 읽어")
        self.assertIn("D2", err)
        self.assertEqual(self.prompt("@ok.txt 읽어", self.other), (0, "", ""))

    def test_nothing_to_pull_passes(self):
        for text in ("@nothing-here.txt 읽어", "담당은 @handle 님", "@ 혼자", "그냥 말"):
            self.assertEqual(self.prompt(text, self.other), (0, "", ""), text)

    def test_data_folder_files(self):
        rel = os.path.relpath(os.path.join(self.home, "dictionary.json"), self.other).replace(os.sep, "/")
        err = self.blocked("@%s" % rel)
        self.assertIn("@파일", err)


class ContentDecoding(Base):
    """Read 의 내용 검사는 인코딩 · 이스케이프를 풀어서 본다 (레드팀 F-02)."""

    def read(self, name, data):
        p = os.path.join(self.other, name)
        with open(p, "wb") as f:
            f.write(data)
        return self.tool("Read", {"file_path": p}, self.other)

    def test_utf16_with_bom_and_without(self):
        text = "메모 %s 끝" % WORD
        self.assertDenied(self.read("a.txt", b"\xff\xfe" + text.encode("utf-16-le")))        # PowerShell 5.1 의 > 출력
        self.assertDenied(self.read("b.txt", b"\xfe\xff" + text.encode("utf-16-be")))
        self.assertDenied(self.read("c.txt", text.encode("utf-16-le")))                       # BOM 없는 UTF-16
        self.assertDenied(self.read("d.txt", b"\xff\xfe\x00\x00" + text.encode("utf-32-le")))

    def test_leading_nul_and_unknown_binary_are_refused(self):
        self.assertDenied(self.read("e.txt", b"\x00" + ("메모 %s" % WORD).encode("utf-8")))
        self.assertDenied(self.read("f.bin", b"\x00\x01\x02\x03\x04" * 50))
        # 알려진 이미지 · PDF 는 내용을 보지 않는다 (알려진 한계)
        self.assertEqual(self.read("g.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 40), (0, "", ""))

    def test_json_and_html_escapes(self):
        esc = "".join("\\u%04x" % ord(c) for c in WORD)
        self.assertDenied(self.read("h.ipynb", ('{"cells": [{"source": ["%s"]}]}' % esc).encode("utf-8")))
        ent = "".join("&#%d;" % ord(c) for c in WORD)
        self.assertDenied(self.read("i.html", ("<p>%s</p>" % ent).encode("utf-8")))

    def test_cp949(self):
        word = "사내용어가나"
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 1, "words": [WORD, word]})
        self.assertDenied(self.read("j.txt", ("보고 %s 끝" % word).encode("cp949")))

    def test_clean_text_still_passes(self):
        self.assertEqual(self.read("k.txt", "평범한 글".encode("utf-8")), (0, "", ""))
        self.assertEqual(self.read("l.txt", b"\xff\xfe" + "평범한 글".encode("utf-16-le")), (0, "", ""))


class SlashCommandsWhenBroken(Base):
    def test_only_the_bare_command_passes_a_broken_dictionary(self):
        broken = os.path.join(self.tmp, "broken")
        os.makedirs(broken)
        with open(os.path.join(broken, "dictionary.json"), "w") as f:
            f.write("{")
        self.assertEqual(self.prompt("/diode:status", self.other, home=broken), (0, "", ""))
        self.assertEqual(self.prompt("  /diode:setup  ", self.other, home=broken), (0, "", ""))
        for text in ("/diode:status %s 수율" % WORD, "/diode:dict 뒤에 글", "/diode:status\n%s" % WORD):
            code, out, _ = self.prompt(text, self.other, home=broken)
            self.assertEqual(code, 2, text)


class ShellRelativePaths(Base):
    """셸은 벽이 아니지만 Claude 가 평소 쓰는 상대 경로 꼴은 본다 (레드팀 F-04)."""

    def test_relative_and_cd_forms(self):
        for cmd in ("cat ../kitraw/secret.txt", "cd ../kitraw && cat secret.txt", "grep -r x ../kitraw",
                    "cat --file=../kitraw/secret.txt", 'cat "../kitraw/secret.txt"'):
            self.assertDenied(self.tool("Bash", {"command": cmd}, self.other))
        self.assertAllowed(self.tool("Bash", {"command": "ls -la ."}, self.other))
        self.assertAllowed(self.tool("Bash", {"command": "cat ../other/a.txt"}, self.other))
        self.assertAllowed(self.tool("Bash", {"command": "echo hello | wc -c"}, self.other))

    def test_data_folder_relative(self):
        rel = os.path.relpath(self.home, self.other).replace(os.sep, "/")
        self.assertDenied(self.tool("Bash", {"command": "cat %s/dictionary.json" % rel}, self.other))


class InnerToolNames(Base):
    """안쪽 도구 이름을 구분자 · 따옴표로 쪼개도 같은 도구로 본다 (레드팀 F-05)."""

    def test_split_names(self):
        for name in ("mcp__open_code__run", "mcp__open-code__run", "mcp__OpenCode__x"):
            self.assertDenied(self.tool(name, {}, self.other))
        for cmd in ('o"pen"code run x', "open\\code run x", "OPENCODE run", "'opencode' run"):
            self.assertDenied(self.tool("Bash", {"command": cmd}, self.other))
        self.assertDenied(self.tool("Agent", {"subagent_type": "open-code", "prompt": "x"}, self.other))
        self.assertAllowed(self.tool("Bash", {"command": "echo open code editor"}, self.other))


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


class GuideFiles(Base):
    """CLAUDE.md · AGENTS.md 는 모든 요청에 실려 간다 — 사내 단어가 있으면 프롬프트를 보내지 않는다 (사용자 입력이 없어도 나가는 길)."""

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_user_scope_guide_with_a_word_blocks_the_prompt(self):
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "# 메모\n%s 프로젝트\n" % WORD)
        code, out, err = self.prompt("평범한 질문", self.other)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("D2 x1 @안내파일", err)
        self.assertNotIn(WORD, err)

    def test_project_and_parent_guides_and_rules(self):
        sub = os.path.join(self.other, "a", "b")
        os.makedirs(sub)
        for rel in (os.path.join(self.other, "CLAUDE.md"), os.path.join(self.other, "a", "AGENTS.md"),
                    os.path.join(sub, ".claude", "CLAUDE.md"), os.path.join(sub, "CLAUDE.local.md"),
                    os.path.join(sub, ".claude", "rules", "r.md"), os.path.join(self.userdir, "rules", "u.md")):
            self._write(rel, "kit-word alpha 가 있다")
            self.assertEqual(self.prompt("질문", sub)[0], 2, rel)
            os.remove(rel)
        self.assertEqual(self.prompt("질문", sub), (0, "", ""))

    def test_clean_guides_pass(self):
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "평범한 선호 설정\n")
        self._write(os.path.join(self.other, "AGENTS.md"), "코딩 규칙\n")
        self.assertEqual(self.prompt("질문", self.other), (0, "", ""))

    def test_counts_distinct_words_per_file(self):
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 1, "words": [WORD, "가람소재"]})
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "%s 와 가람소재 와 %s\n" % (WORD, WORD))
        self.assertIn("D2 x2", self.prompt("질문", self.other)[2])

    def test_too_big_or_unreadable_blocks(self):
        from diodelib import hook
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "가" * 20)
        saved = hook.GUIDE_MAX_BYTES
        hook.GUIDE_MAX_BYTES = 5
        try:
            code, _, err = self.prompt("질문", self.other)
        finally:
            hook.GUIDE_MAX_BYTES = saved
        self.assertEqual(code, 2)                                                  # 검사하지 못하면 막는 쪽

    def test_a_failing_scan_blocks_instead_of_letting_it_through(self):
        from unittest import mock
        from diodelib import hook, scan
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "평범한 글\n")
        with mock.patch.object(scan, "policy_dict_hits", side_effect=RuntimeError("x")):
            code, out, err = self.prompt("질문", self.other)
        self.assertEqual(code, 2)                                                  # 검사가 실패하면 통과가 아니라 막음
        self.assertIn("D2 x1", err)

    def test_room_and_session_message(self):
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "%s\n" % WORD)
        self.assertEqual(self.prompt("질문", self.room)[0], 0)                      # 방은 claudeMdExcludes 로 안내 파일을 싣지 않는다
        code, out, _ = self.call("session", {}, self.other)
        self.assertIn("D2 x1", json.loads(out)["systemMessage"])                   # 세션 시작 때도 알린다

    def test_unset_state_does_not_scan(self):
        empty = os.path.join(self.tmp, "empty")
        self._write(os.path.join(self.userdir, "CLAUDE.md"), "%s\n" % WORD)
        self.assertEqual(self.prompt("질문", self.other, home=empty)[0], 0)


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
