# -*- coding: utf-8 -*-
"""가명 금고 · 작업 묶음 (diodelib.vault · SP-20 · AL-05 · W-05 · W-06) 과 `diode.py project`. 합성 값 · 합성 자리만."""

import copy
import io
import json
import os
import pickle
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import diode  # noqa: E402
from diodelib import derive, vault  # noqa: E402
from diodelib.scan import TOKEN_ALPHABET, TOKEN_RE  # noqa: E402
from diodelib.vault import Vault, VaultError  # noqa: E402

# 합성 카나리아 - 출력 · repr · 오류 어디에도 있으면 안 된다
REAL_WORD = "노을공정KITVAULT"
REAL_PATH = "kitsrc/kitvault_secret_module.py"
REAL_NUMBER = "731337"
CANARIES = (REAL_WORD, REAL_PATH, "kitvault_secret_module", REAL_NUMBER)

NT = os.name == "nt"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-vault-"))
        self.home = os.path.join(self.tmp, "data")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self):
        return vault.open_project(self.home, False)

    def locked(self, **kw):
        return Vault.locked(self.home, False, **kw)

    def vdir(self):
        return vault.vault_dir(self.home)

    def listing(self):
        return sorted(os.listdir(self.vdir())) if os.path.isdir(self.vdir()) else []

    def write_vault(self, project, obj=None, raw=None):
        """금고 파일을 직접 쓴다 (이 OS 의 감싸기로 - Windows 는 DPAPI). raw 를 주면 그 바이트 그대로."""
        if raw is None:
            payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            raw = vault._encode(project, payload)
        with open(vault.vault_path(self.home, project), "wb") as f:
            f.write(raw)

    def content(self, project="P-0001", **kw):
        obj = {"format": 1, "project": project, "entries": [], "files": [], "sent_bytes": 0, "halted": False}
        obj.update(kw)
        return obj

    def assertCode(self, cm, code, reason=None):
        self.assertEqual(cm.exception.code, code)
        if reason is not None:
            self.assertEqual(cm.exception.reason, reason)
        self.assertEqual(str(cm.exception), code)                  # 오류 글은 번호뿐이다


class Tokens(Base):
    def test_same_value_same_token_and_it_lasts_across_sessions(self):
        self.open()
        with self.locked() as v:
            a = v.token_for(REAL_WORD)
            self.assertEqual(v.token_for(REAL_WORD, "word"), a)
            self.assertEqual(v.real_of(a), (REAL_WORD, "word"))
        with self.locked() as v:
            self.assertEqual(v.token_for(REAL_WORD), a)
            self.assertEqual(len(v), 1)
            self.assertIn(a, v)
            self.assertEqual(v.tokens(), frozenset([a]))

    def test_another_kind_is_another_token(self):
        self.open()
        with self.locked() as v:
            toks = [v.token_for(REAL_NUMBER, k) for k in vault.KINDS]
            self.assertEqual(len(set(toks)), len(vault.KINDS))
            self.assertEqual(v.real_of(toks[1]), (REAL_NUMBER, "number"))
            unknown = next(t for t in ("PH_2222", "PH_3333", "PH_4444", "PH_5555", "PH_6666") if t not in toks)
            self.assertIsNone(v.real_of(unknown))

    def test_another_project_is_another_token(self):
        self.open()
        with self.locked() as v:
            first = v.token_for(REAL_WORD)
        vault.close_project(self.home)
        self.assertEqual(self.open(), "P-0002")
        with self.locked() as v:
            self.assertNotIn(first, v.tokens())
            self.assertIsNone(v.real_of(first))
            self.assertNotEqual(v.token_for(REAL_WORD), first)

    def test_tokens_are_random_not_a_hash(self):
        # 같은 번호 (P-0001) · 같은 값이라도 다른 자리에서 연 금고면 다른 토큰이다 (해시라면 같다 · AL-05)
        other = os.path.join(self.tmp, "data2")
        self.open()
        vault.open_project(other, False)
        with self.locked() as v:
            a = v.token_for(REAL_WORD)
        with Vault.locked(other, False) as v:
            b = v.token_for(REAL_WORD)
        self.assertNotEqual(a, b)

    def test_token_shape(self):
        self.open()
        with self.locked() as v:
            for i in range(200):
                t = v.token_for("kitvalue%03d" % i, vault.KINDS[i % 4])
                self.assertTrue(TOKEN_RE.fullmatch(t), t)
                self.assertTrue(all(c in TOKEN_ALPHABET for c in t[3:]))

    def test_tokens_do_not_collide_inside_a_vault(self):
        self.open()
        draws = iter("2222" + "2222" + "2222" + "3333")
        with self.locked() as v, mock.patch.object(vault.secrets, "choice", lambda seq: next(draws)):
            a = v.token_for("kitone")
            b = v.token_for("kittwo")
        self.assertEqual((a, b), ("PH_2222", "PH_3333"))

    def test_limit_is_e31(self):
        self.open()
        with mock.patch.object(vault, "MAX_PROJECT_TOKENS", 3), self.locked() as v:
            toks = [v.token_for("kitlimit%d" % i) for i in range(3)]
            with self.assertRaises(VaultError) as cm:
                v.token_for("kitlimit3")
            self.assertCode(cm, "E-31")
            self.assertEqual(v.token_for("kitlimit0"), toks[0])        # 이미 있는 값은 그대로
            self.assertEqual(len(v), 3)

    def test_bad_values_are_refused(self):
        self.open()
        with self.locked() as v:
            for real in ("", "   ", None, 7, "a\x00b", "x" * (vault.MAX_REAL_CHARS + 1)):
                with self.assertRaises(ValueError):
                    v.token_for(real)
            with self.assertRaises(ValueError):
                v.token_for(REAL_WORD, "entity")
            self.assertEqual(len(v), 0)
            v.token_for("x" * vault.MAX_REAL_CHARS)

    def test_reals_longest_first_and_short_ones_left_out(self):
        self.open()
        with self.locked() as v:
            for real, kind in (("ab", "word"), ("kitlongervalue", "word"), ("kitlongervalue", "ident"),
                               ("a-", "word"), ("kitmid", "path"), ("Z", "number")):
                v.token_for(real, kind)
            self.assertEqual(v.reals(), ["kitlongervalue", "kitmid", "ab"])
            self.assertEqual(v.reals(min_len=3), ["kitlongervalue", "kitmid"])
            self.assertEqual(v.reals(min_len=1), ["kitlongervalue", "kitmid", "a-", "ab", "Z"])


class SentBytes(Base):
    def test_sum_lasts_and_the_cap_does_not_add(self):
        self.open()
        with self.locked() as v:
            v.add_sent(100)
            v.add_sent(0)
        with mock.patch.object(vault, "MAX_PROJECT_BYTES", 1000), self.locked() as v:
            self.assertEqual(v.sent_bytes, 100)
            v.add_sent(900)
            with self.assertRaises(VaultError) as cm:
                v.add_sent(1)
            self.assertCode(cm, "E-31")
            self.assertEqual(v.sent_bytes, 1000)
        self.assertEqual(vault.project_status(self.home)["sent_bytes"], 1000)

    def test_bad_counts(self):
        self.open()
        with self.locked() as v:
            for n in (-1, True, 1.5, "3", None):
                with self.assertRaises(ValueError):
                    v.add_sent(n)
            self.assertEqual(v.sent_bytes, 0)

    def test_default_cap_is_8_mib(self):
        self.assertEqual(vault.MAX_PROJECT_BYTES, 8 * 1024 * 1024)
        self.assertEqual(vault.MAX_PROJECT_TOKENS, 20000)
        self.assertEqual(vault.MAX_PROJECT_FILES, 2000)
        self.assertEqual(vault.KINDS, ("word", "number", "path", "ident"))


class FileNames(Base):
    def test_names_are_stable_in_the_project(self):
        self.open()
        with self.locked() as v:
            self.assertEqual(v.file_name(REAL_PATH, "py"), "F01.py")
            self.assertEqual(v.file_name("kitdocs/kitnotes.md", "md"), "F02.md")
            self.assertEqual(v.file_name(REAL_PATH, "txt"), "F01.py")         # 같은 경로면 같은 이름 (확장자가 달라도)
        with self.locked() as v:
            self.assertEqual(v.file_name(REAL_PATH, "py"), "F01.py")
            self.assertEqual(v.file_name("kitdocs/kittable.csv", "csv"), "F03.csv")
            self.assertEqual(v.file_real("F01.py"), REAL_PATH)
            self.assertEqual(v.file_real("F03.csv"), "kitdocs/kittable.csv")
            for unknown in ("F09.py", "F01.md", "../F01.py", None, 3):
                self.assertIsNone(v.file_real(unknown))
        self.assertEqual(vault.project_status(self.home)["files"], 3)

    def test_after_f99_comes_f100(self):
        self.open()
        with self.locked() as v:
            names = [v.file_name("kitdir/kitfile%03d.txt" % i, "txt") for i in range(101)]
        self.assertEqual(names[0], "F01.txt")
        self.assertEqual(names[98], "F99.txt")
        self.assertEqual(names[99], "F100.txt")
        self.assertEqual(names[100], "F101.txt")
        self.assertTrue(all(vault.FILE_NAME_RE.match(n) for n in names))

    def test_bad_extension_or_path_is_value_error(self):
        self.open()
        with self.locked() as v:
            for ext in ("", ".py", "p.y", "toolongext", "py!", "한글", None):
                with self.assertRaises(ValueError):
                    v.file_name(REAL_PATH, ext)
            for real in ("", None, "a\x00b", "x" * (vault.MAX_FILE_REAL_CHARS + 1)):
                with self.assertRaises(ValueError):
                    v.file_name(real, "py")
            self.assertEqual(v.file_name(REAL_PATH, "ABCdef12"), "F01.ABCdef12")

    def test_limit_is_e31(self):
        self.open()
        with mock.patch.object(vault, "MAX_PROJECT_FILES", 2), self.locked() as v:
            v.file_name("kita", "md")
            v.file_name("kitb", "md")
            with self.assertRaises(VaultError) as cm:
                v.file_name("kitc", "md")
            self.assertCode(cm, "E-31")
            self.assertEqual(v.file_name("kita", "md"), "F01.md")

    def test_no_add_file(self):
        self.assertFalse(hasattr(Vault, "add_file"))


class Halted(Base):
    def test_halt_is_saved_and_the_vault_still_opens(self):
        self.open()
        with self.locked() as v:
            self.assertFalse(v.halted)
            v.token_for(REAL_WORD)
            v.halt()
        self.assertTrue(vault.project_status(self.home)["halted"])
        with self.locked() as v:                                     # 깃발이 서 있어도 연다 (읽기만)
            self.assertTrue(v.halted)
            self.assertEqual(len(v), 1)
        self.assertEqual(vault.resume_project(self.home, False), "P-0001")
        self.assertFalse(vault.project_status(self.home)["halted"])
        self.assertEqual(vault.resume_project(self.home, False), "P-0001")   # 서 있지 않아도 같은 답

    def test_only_the_person_lowers_it(self):
        self.open()
        with self.locked() as v:
            v.halt()
        self.assertFalse(hasattr(Vault, "resume"))                  # 허브 · 묶음 코드가 부를 공개 메서드가 없다


class Locking(Base):
    def test_second_locked_waits_then_e20(self):
        self.open()
        with mock.patch.object(vault, "LOCK_WAIT_S", 0.3), mock.patch.object(vault, "LOCK_POLL_S", 0.05):
            with self.locked():
                t0 = time.monotonic()
                with self.assertRaises(VaultError) as cm:
                    with self.locked():
                        pass
                self.assertGreaterEqual(time.monotonic() - t0, 0.29)
                self.assertCode(cm, "E-20", "lock")
                with self.assertRaises(VaultError):
                    vault.close_project(self.home)                  # 닫기도 같은 잠금을 기다린다
        self.assertNotIn("P-0001.lock", self.listing())
        with self.locked():
            pass

    def test_lock_file_holds_pid_and_time_and_goes_away(self):
        self.open()
        with self.locked():
            with open(vault.lock_path(self.home, "P-0001"), "rb") as f:
                pid, at = f.read().decode("ascii").split()
            self.assertEqual(int(pid), os.getpid())
            self.assertLess(abs(float(at) - time.time()), 30)
        self.assertNotIn("P-0001.lock", self.listing())
        with self.assertRaises(RuntimeError):
            with self.locked():
                raise RuntimeError("boom")
        self.assertNotIn("P-0001.lock", self.listing())

    def test_a_stale_lock_is_removed_and_told(self):
        self.open()
        with open(vault.lock_path(self.home, "P-0001"), "wb") as f:
            f.write(("99999 %.3f\n" % (time.time() - 120)).encode("ascii"))
        told = []
        with self.locked(notice=told.append) as v:
            self.assertTrue(v.stale_lock_removed)
        self.assertEqual(told, ["stale_lock"])
        with self.locked(notice=told.append) as v:
            self.assertFalse(v.stale_lock_removed)
        self.assertEqual(told, ["stale_lock"])

    def test_a_fresh_lock_with_odd_content_is_not_stale(self):
        self.open()
        with open(vault.lock_path(self.home, "P-0001"), "wb") as f:
            f.write(b"")                                            # 막 만들어 아직 적지 않은 잠금 - 파일 시각을 본다
        with mock.patch.object(vault, "LOCK_WAIT_S", 0.2), mock.patch.object(vault, "LOCK_POLL_S", 0.05):
            with self.assertRaises(VaultError) as cm:
                with self.locked():
                    pass
        self.assertCode(cm, "E-20", "lock")
        self.assertIn("P-0001.lock", self.listing())

    def test_concurrent_writers_do_not_lose_updates(self):
        self.open()
        errors = []

        def work(tag):
            try:
                for i in range(10):
                    with self.locked() as v:
                        v.token_for("kit%s%02d" % (tag, i))
                        v.add_sent(1)
            except Exception as e:                                  # pragma: no cover - 실패를 본다
                errors.append(e)

        threads = [threading.Thread(target=work, args=(t,)) for t in ("a", "b", "c")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        st = vault.project_status(self.home)
        self.assertEqual((st["tokens"], st["sent_bytes"]), (30, 30))

    def test_status_does_not_wait_for_the_lock(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
            self.assertEqual(vault.project_status(self.home)["tokens"], 0)     # 아직 저장 전
        self.assertEqual(vault.project_status(self.home)["tokens"], 1)


class AtomicSave(Base):
    def test_saved_only_when_changed(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
        with mock.patch.object(vault, "_write_atomic", wraps=vault._write_atomic) as w:
            with self.locked() as v:
                v.token_for(REAL_WORD)                               # 이미 있는 값 - 바뀐 것 없음
                v.reals()
                v.file_real("F01.md")
            self.assertEqual(w.call_count, 0)
            with self.locked() as v:
                v.token_for("kitnew")
            self.assertEqual(w.call_count, 1)

    def test_a_failed_save_leaves_the_old_file_and_no_temp(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
        path = vault.vault_path(self.home, "P-0001")
        with open(path, "rb") as f:
            before = f.read()
        with mock.patch.object(vault.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(VaultError) as cm:
                with self.locked() as v:
                    v.token_for("kitnew")
        self.assertCode(cm, "E-20", "io")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual([n for n in self.listing() if n.endswith(".tmp")], [])
        self.assertNotIn("P-0001.lock", self.listing())
        self.assertEqual(vault.project_status(self.home)["tokens"], 1)

    def test_changes_are_saved_even_when_the_block_raises(self):
        self.open()
        with self.assertRaises(KeyError):
            with self.locked() as v:
                tok = v.token_for(REAL_WORD)
                raise KeyError("x")
        with self.locked() as v:
            self.assertEqual(v.token_for(REAL_WORD), tok)

    def test_the_object_is_dead_after_the_block(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
        for call in (lambda: v.token_for("kitx"), v.tokens, v.reals, lambda: v.real_of("PH_2222"),
                     lambda: v.file_name("kitx", "md"), lambda: v.file_real("F01.md"), lambda: v.add_sent(1), v.halt):
            with self.assertRaises(VaultError):
                call()
        self.assertEqual(len(v), 0)

    def test_the_content_shape(self):
        if NT:
            self.skipTest("Windows 는 DPAPI 로 감싸 내용을 바로 볼 수 없다 (Dpapi 시험이 따로 본다)")
        self.open()
        with self.locked() as v:
            tok = v.token_for(REAL_WORD)
            v.file_name(REAL_PATH, "py")
            v.add_sent(12)
        with open(vault.vault_path(self.home, "P-0001"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"DIODE-VAULT-1\nplain\n"))
        obj = json.loads(raw[len(b"DIODE-VAULT-1\nplain\n"):].decode("utf-8"))
        self.assertEqual(obj, {"format": 1, "project": "P-0001",
                               "entries": [{"token": tok, "real": REAL_WORD, "kind": "word"}],
                               "files": [{"name": "F01.py", "real": REAL_PATH}], "sent_bytes": 12, "halted": False})


class Broken(Base):
    def setUp(self):
        Base.setUp(self)
        self.open()
        self.path = vault.vault_path(self.home, "P-0001")

    def assertBroken(self, n=0):
        with self.assertRaises(VaultError) as cm:
            with self.locked():
                pass
        self.assertCode(cm, "E-20", "broken")
        self.assertFalse(os.path.exists(self.path))                  # 새 금고를 조용히 만들지 않는다
        self.assertTrue(os.path.exists(self.path + ".broken" + ("" if n == 0 else str(n))))
        with self.assertRaises(VaultError) as cm:                    # 다시 열어도 없다 - 만들지 않는다
            with self.locked():
                pass
        self.assertCode(cm, "E-20", "missing")
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(vault.active_project(self.home), "P-0001")

    def test_garbage(self):
        self.write_vault("P-0001", raw=b"not a vault")
        self.assertBroken()

    def test_unknown_mark_or_no_header(self):
        self.write_vault("P-0001", raw=b"DIODE-VAULT-1\nzzz\n{}")
        self.assertBroken()
        self.write_vault("P-0001", raw=b"DIODE-VAULT-2\nplain\n{}")
        with self.assertRaises(VaultError):
            with self.locked():
                pass
        self.assertTrue(os.path.exists(self.path + ".broken1"))     # 덮어쓰지 않게 번호

    def test_unknown_format(self):
        self.write_vault("P-0001", self.content(format=2))
        self.assertBroken()

    def test_wrong_project_inside(self):
        self.write_vault("P-0001", self.content(project="P-0002"))
        self.assertBroken()

    def test_bad_shapes(self):
        bad = [
            self.content(entries=[{"token": "PH_K7Q1", "real": "kitx", "kind": "word"}]),           # 토큰 꼴
            self.content(entries=[{"token": "PH_K7Q2", "real": "kitx", "kind": "entity"}]),         # 종류
            self.content(entries=[{"token": "PH_K7Q2", "real": "", "kind": "word"}]),
            self.content(entries=[{"token": "PH_K7Q2", "real": "kitx", "kind": "word"},
                                  {"token": "PH_K7Q2", "real": "kity", "kind": "word"}]),           # 토큰 겹침
            self.content(entries=[{"token": "PH_K7Q2", "real": "kitx", "kind": "word"},
                                  {"token": "PH_K7Q3", "real": "kitx", "kind": "word"}]),           # 값 겹침
            self.content(files=[{"name": "../F01.py", "real": "kitx"}]),
            self.content(files=[{"name": "F01.py", "real": "kitx"}, {"name": "F01.md", "real": "kity"}]),
            self.content(files=[{"name": "F01.py", "real": "kitx", "job": "J-0001"}]),
            self.content(sent_bytes=-1),
            self.content(sent_bytes=True),
            self.content(halted="no"),
            dict((k, v) for k, v in self.content().items() if k != "halted"),
            dict(self.content(), extra=1),
            [],
        ]
        for i, obj in enumerate(bad):
            self.write_vault("P-0001", obj)
            with self.assertRaises(VaultError, msg=i) as cm:
                with self.locked():
                    pass
            self.assertCode(cm, "E-20", "broken")
            self.assertFalse(os.path.exists(self.path), i)

    def test_status_reports_but_does_not_move(self):
        self.write_vault("P-0001", raw=b"not a vault")
        with self.assertRaises(VaultError) as cm:
            vault.project_status(self.home)
        self.assertCode(cm, "E-20", "unreadable")
        self.assertTrue(os.path.exists(self.path))

    def test_close_after_broken_closes_with_zero_and_keeps_the_broken_file(self):
        self.write_vault("P-0001", raw=b"not a vault")
        with self.assertRaises(VaultError):
            vault.close_project(self.home)                           # 깨졌다 - 옮기고 알린다
        self.assertEqual(vault.active_project(self.home), "P-0001")
        self.assertEqual(vault.close_project(self.home), ("P-0001", 0))
        self.assertIsNone(vault.active_project(self.home))
        self.assertTrue(os.path.exists(self.path + ".broken"))
        self.assertEqual(vault.open_project(self.home, False), "P-0002")

    @unittest.skipIf(NT, "Windows 밖에서만 - DPAPI 표지는 풀 수 없다")
    def test_dpapi_mark_off_windows_is_broken(self):
        self.write_vault("P-0001", raw=b"DIODE-VAULT-1\ndpapi\n\x01\x02\x03")
        self.assertBroken()

    @unittest.skipUnless(NT, "Windows 만 - 평문 표지는 Windows 에서 쓰지 않는다")
    def test_plain_mark_on_windows_is_broken(self):
        self.write_vault("P-0001", raw=b"DIODE-VAULT-1\nplain\n" + json.dumps(self.content()).encode("utf-8"))
        self.assertBroken()

    def test_bad_active_file(self):
        with open(os.path.join(self.vdir(), "active"), "wb") as f:
            f.write(b"P-12\n")
        with self.assertRaises(VaultError) as cm:
            vault.active_project(self.home)
        self.assertCode(cm, "E-20", "broken")
        with self.assertRaises(VaultError):
            vault.open_project(self.home, False)
        with self.assertRaises(VaultError):
            vault.close_project(self.home)                           # active 를 .broken 으로 옮긴다
        self.assertTrue(os.path.exists(os.path.join(self.vdir(), "active.broken")))
        self.assertIsNone(vault.active_project(self.home))
        self.assertEqual(vault.open_project(self.home, False), "P-0002")    # 남은 흔적 (P-0001.vault) 을 건너뛴다

    def test_bad_next_file(self):
        vault.close_project(self.home)
        with open(os.path.join(self.vdir(), "next"), "wb") as f:
            f.write(b"lots\n")
        with self.assertRaises(VaultError) as cm:
            vault.open_project(self.home, False)
        self.assertCode(cm, "E-20", "broken")
        self.assertTrue(os.path.exists(os.path.join(self.vdir(), "next.broken")))
        self.assertIsNone(vault.active_project(self.home))
        # next 를 잃으면 남은 흔적 (금고 · .broken · 임시 파일) 으로만 번호를 고른다 - 흔적까지 지운 닫힌 번호는 다시 나올 수 있다 (알려진 한계)
        self.assertTrue(vault.PROJECT_RE.match(vault.open_project(self.home, False)))


class Projects(Base):
    def test_open_close_numbers_are_not_reused(self):
        self.assertIsNone(vault.active_project(self.home))
        self.assertEqual(self.open(), "P-0001")
        self.assertEqual(vault.active_project(self.home), "P-0001")
        with self.assertRaises(VaultError) as cm:
            self.open()
        self.assertCode(cm, "E-04", "open")
        self.assertEqual(vault.close_project(self.home), ("P-0001", 0))
        self.assertEqual(self.open(), "P-0002")
        vault.close_project(self.home)
        self.assertEqual(self.open(), "P-0003")

    def test_no_active_is_e33(self):
        with self.assertRaises(VaultError) as cm:
            with self.locked():
                pass
        self.assertCode(cm, "E-33")
        with self.assertRaises(VaultError) as cm:
            vault.close_project(self.home)
        self.assertCode(cm, "E-33")
        with self.assertRaises(VaultError) as cm:
            vault.resume_project(self.home, False)
        self.assertCode(cm, "E-33")
        self.assertEqual(vault.project_status(self.home), {"project": None, "tokens": 0, "files": 0, "sent_bytes": 0,
                                                           "protected": False, "halted": False})

    def test_close_removes_the_vault_and_returns_the_count(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
            v.token_for(REAL_NUMBER, "number")
            v.file_name(REAL_PATH, "py")
        leftover = os.path.join(self.vdir(), ".P-0001-kitleft.tmp")   # 끊긴 쓰기가 남긴 임시 파일
        with open(leftover, "wb") as f:
            f.write(b"x")
        self.assertEqual(vault.close_project(self.home), ("P-0001", 2))
        self.assertEqual(self.listing(), ["next"])
        self.assertIsNone(vault.active_project(self.home))
        with self.assertRaises(VaultError) as cm:
            with self.locked():
                pass
        self.assertCode(cm, "E-33")

    @unittest.skipIf(NT or not hasattr(os, "link"), "하드 링크로 덮어쓴 바이트를 본다 (POSIX)")
    def test_close_overwrites_with_zeros_before_removing(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
        path = vault.vault_path(self.home, "P-0001")
        size = os.path.getsize(path)
        peek = os.path.join(self.tmp, "peek")
        os.link(path, peek)
        vault.close_project(self.home)
        with open(peek, "rb") as f:
            self.assertEqual(f.read(), b"\0" * size)

    def test_status_shape(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
            v.file_name(REAL_PATH, "py")
            v.add_sent(5)
        st = vault.project_status(self.home)
        self.assertEqual(st, {"project": "P-0001", "tokens": 1, "files": 1, "sent_bytes": 5, "protected": NT,
                              "halted": False})

    def test_missing_vault_is_not_recreated(self):
        self.open()
        os.remove(vault.vault_path(self.home, "P-0001"))
        with self.assertRaises(VaultError) as cm:
            with self.locked():
                pass
        self.assertCode(cm, "E-20", "missing")
        self.assertFalse(os.path.exists(vault.vault_path(self.home, "P-0001")))


@unittest.skipIf(NT, "Windows 밖에서만 - Windows 는 늘 DPAPI 로 쓴다")
class PlainOnlyInTestHome(Base):
    def test_default_home_refuses_and_writes_nothing(self):
        with self.assertRaises(VaultError) as cm:
            vault.open_project(self.home, True)
        self.assertCode(cm, "E-20", "os")
        self.assertFalse(os.path.exists(self.home))                  # 폴더도 만들지 않는다
        self.open()                                                  # 시험 자리에서 연 묶음도
        with self.assertRaises(VaultError) as cm:
            with Vault.locked(self.home, True):
                pass
        self.assertCode(cm, "E-20", "os")
        with self.assertRaises(VaultError):
            vault.resume_project(self.home, True)
        self.assertFalse(vault.can_protect())

    def test_test_home_writes_plain_0600(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
            self.assertFalse(v.protected)
        path = vault.vault_path(self.home, "P-0001")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.vdir()).st_mode) & 0o077, 0)
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"DIODE-VAULT-1\nplain\n"))
        self.assertFalse(vault.project_status(self.home)["protected"])

    def test_cli_on_the_default_home_writes_nothing(self):
        fake_home = os.path.join(self.tmp, "userhome")
        os.makedirs(fake_home)
        env = dict((k, v) for k, v in os.environ.items() if k != "DIODE_HOME")
        env["HOME"] = fake_home
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(derive, "stdin_is_terminal", lambda s: True):
            self.assertTrue(diode.data_dir()[1])
            code = diode.main(["project", "open"], out, err)
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue().splitlines(), ['{"project": false, "error": "E-20"}', "결과: 점검 실패"])
        self.assertIn("암호화할 수 없습니다", err.getvalue())
        self.assertEqual(os.listdir(fake_home), [])


@unittest.skipUnless(NT, "Windows 만 - DPAPI (CI 의 windows-latest 가 돌린다)")
class Dpapi(Base):
    def test_file_has_no_plain_value_and_reads_back(self):
        self.open()
        with self.locked() as v:
            tok = v.token_for(REAL_WORD)
            v.file_name(REAL_PATH, "py")
            self.assertTrue(v.protected)
        with open(vault.vault_path(self.home, "P-0001"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"DIODE-VAULT-1\ndpapi\n"))
        for value in CANARIES + (tok,):
            for enc in ("utf-8", "utf-16-le"):
                self.assertNotIn(value.encode(enc), raw)
        with self.locked() as v:
            self.assertEqual(v.real_of(tok), (REAL_WORD, "word"))
            self.assertEqual(v.file_real("F01.py"), REAL_PATH)
        self.assertTrue(vault.project_status(self.home)["protected"])

    def test_other_entropy_does_not_open(self):
        sealed = vault.protect(b"kitvault payload", b"P-0001")
        self.assertNotIn(b"kitvault payload", sealed)
        self.assertEqual(vault.unprotect(sealed, b"P-0001"), b"kitvault payload")
        with self.assertRaises(Exception):
            vault.unprotect(sealed, b"P-0002")

    def test_a_vault_moved_to_another_number_is_broken(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
        with open(vault.vault_path(self.home, "P-0001"), "rb") as f:
            raw = f.read()
        vault.close_project(self.home)
        self.open()
        with open(vault.vault_path(self.home, "P-0002"), "wb") as f:
            f.write(raw)
        with self.assertRaises(VaultError) as cm:
            with self.locked():
                pass
        self.assertCode(cm, "E-20", "broken")


class NoLeaks(Base):
    def test_repr_pickle_copy_json_are_blocked(self):
        self.open()
        with self.locked() as v:
            tok = v.token_for(REAL_WORD)
            v.file_name(REAL_PATH, "py")
            for text in (repr(v), str(v)):
                for value in CANARIES + (tok,):
                    self.assertNotIn(value, text)
                self.assertIn("1", text)
            for call in (lambda: pickle.dumps(v), lambda: copy.copy(v), lambda: copy.deepcopy(v),
                         lambda: json.dumps(v), lambda: v.__reduce_ex__(2)):
                with self.assertRaises(TypeError):
                    call()
        with self.assertRaises(TypeError):
            Vault(object(), self.home, "P-0001", ({}, {}, [], 0, False), False)

    def test_errors_carry_codes_only(self):
        self.open()
        with self.locked() as v:
            v.token_for(REAL_WORD)
        with mock.patch.object(vault, "MAX_PROJECT_TOKENS", 1), self.locked() as v:
            with self.assertRaises(VaultError) as cm:
                v.token_for(REAL_NUMBER, "number")
        self.assertEqual((str(cm.exception), cm.exception.args), ("E-31", ("E-31",)))


class Command(Base):
    """`diode.py project open|close|status|resume` — 한 줄 JSON + 결과 줄 · 번호 · 개수뿐 (AL-11)."""

    def run_cli(self, *argv, terminal=True):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"DIODE_HOME": self.home}), \
                mock.patch.object(derive, "stdin_is_terminal", lambda s: terminal):
            code = diode.main(["project"] + list(argv), out, err, io.StringIO(""))
        for text in (out.getvalue(), err.getvalue()):
            for value in CANARIES:
                self.assertNotIn(value, text)
            self.assertNotIn(self.tmp, text)
        lines = out.getvalue().splitlines()
        return code, lines, err.getvalue()

    def test_not_a_terminal_is_e30(self):
        for action in ("open", "close", "resume"):
            code, lines, err = self.run_cli(action, terminal=False)
            self.assertEqual((code, lines), (3, ['{"project": false, "error": "E-30"}', "결과: 확인 필요"]), action)
            self.assertIn("터미널", err)
        self.assertEqual(self.listing(), [])

    def test_not_a_terminal_for_real(self):
        # derive.stdin_is_terminal 을 바꿔 끼우지 않고, 표준 입력이 파이프인 진짜 프로세스로
        env = dict(os.environ, DIODE_HOME=self.home, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py"), "project", "open"], input=b"",
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout.decode("utf-8").splitlines(), ['{"project": false, "error": "E-30"}', "결과: 확인 필요"])
        self.assertFalse(os.path.exists(self.home))

    def test_open_status_close(self):
        self.assertEqual(self.run_cli("open")[:2], (0, ['{"project": "P-0001"}', "결과: OK"]))
        with self.locked() as v:
            v.token_for(REAL_WORD)
            v.token_for(REAL_NUMBER, "number")
            v.file_name(REAL_PATH, "py")
            v.add_sent(40)
        code, lines, _ = self.run_cli("status", terminal=False)           # status 는 읽기만 - 터미널이 아니어도 된다
        self.assertEqual((code, lines[1]), (0, "결과: OK"))
        self.assertEqual(json.loads(lines[0]), {"project": "P-0001", "tokens": 2, "files": 1, "sent_bytes": 40,
                                                "protected": NT, "halted": False})
        code, lines, err = self.run_cli("close")
        self.assertEqual((code, lines), (0, ['{"closed": "P-0001", "tokens": 2}', "결과: OK"]))
        self.assertIn("되돌릴 수 없습니다", err)
        code, lines, _ = self.run_cli("status")
        self.assertEqual(json.loads(lines[0])["project"], None)

    def test_already_open_and_nothing_open(self):
        self.run_cli("open")
        self.assertEqual(self.run_cli("open")[:2], (3, ['{"project": false, "error": "E-04"}', "결과: 확인 필요"]))
        self.run_cli("close")
        self.assertEqual(self.run_cli("close")[:2], (3, ['{"project": false, "error": "E-33"}', "결과: 확인 필요"]))
        self.assertEqual(self.run_cli("resume")[:2], (3, ['{"project": false, "error": "E-33"}', "결과: 확인 필요"]))

    def test_resume(self):
        self.run_cli("open")
        with self.locked() as v:
            v.halt()
        code, lines, err = self.run_cli("status")
        self.assertTrue(json.loads(lines[0])["halted"])
        self.assertIn("project resume", err)
        self.assertEqual(self.run_cli("resume")[:2], (0, ['{"resumed": "P-0001"}', "결과: OK"]))
        self.assertFalse(json.loads(self.run_cli("status")[1][0])["halted"])

    def test_broken_vault(self):
        self.run_cli("open")
        self.write_vault("P-0001", raw=b"not a vault")
        code, lines, err = self.run_cli("status")
        self.assertEqual((code, lines), (1, ['{"project": false, "error": "E-20"}', "결과: 점검 실패"]))
        self.assertIn("project close", err)

    def test_usage(self):
        for argv in ([], ["nope"], ["open", "extra"], ["--help"]):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {"DIODE_HOME": self.home}):
                self.assertEqual(diode.main(["project"] + argv, out, err, io.StringIO("")), 2, argv)
            self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.listing(), [])

    def test_help_and_docstring(self):
        out = io.StringIO()
        diode.main(["help"], out, io.StringIO())
        self.assertIn("project open|close|status|resume", out.getvalue())
        self.assertIn("project <open|close|status|resume>", diode.__doc__)


if __name__ == "__main__":
    unittest.main()
