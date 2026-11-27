# -*- coding: utf-8 -*-
"""propose (일꾼 보고 내기) · 허브 대기열 · job 예약 · diode.py mcp 프로세스 · 플러그인 .mcp.json. 합성 자료만."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import hub, propose, scan  # noqa: E402

REAL = "주간 점검표 (가상)"


def make_room(folder):
    settings = os.path.join(folder, ".claude", "settings.json")
    os.makedirs(os.path.dirname(settings))
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"defaultMode": "default"}}, f)
    with open(settings, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(folder, ".diode-room"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "created": "2026-11-05T00:00:00Z", "settings_sha256": sha}, f)
    for sub in ("outbox", "inbox", "work"):
        os.makedirs(os.path.join(folder, sub))


def draft(job="J-0001", **kw):
    d = {"format": 1, "kind": "report", "data_class": "synthetic", "job": job, "status": "done",
         "counts": {"changed_files": 2}, "entities": [{"ref": "s1", "name": REAL, "type": "화면"}],
         "summary": ["[[s1]] 화면을 만들었다"]}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-propose-"))
        self.home = os.path.join(self.tmp, "data")
        os.makedirs(self.home)
        with open(os.path.join(self.home, "dictionary.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, obj, name="report.json"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return p

    def queue(self):
        d = os.path.join(self.home, "queue")
        return sorted(x for x in os.listdir(d) if x.endswith(".json")) if os.path.isdir(d) else []


class Propose(Base):
    def test_queued(self):
        code, line = propose.main_propose(self.write(draft()), home=self.home)
        self.assertEqual((code, json.loads(line)), (0, {"queued": True, "job": "J-0001"}))
        q = self.queue()
        self.assertEqual(len(q), 1)
        self.assertTrue(q[0].startswith("J-0001-"))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.home, "queue", q[0])).st_mode), 0o600)

    def test_blocked_without_words(self):
        for bad in (draft(summary=["KITWORDALPHA 화면을 만들었다"]), draft(summary=["%s 을 직접 썼다" % REAL]),
                    draft(summary=["온도 350 을 맞췄다"]), draft(summary=["ph_k7q2 화면"])):
            code, line = propose.main_propose(self.write(bad), home=self.home)
            res = json.loads(line)
            self.assertEqual(code, 2)
            self.assertFalse(res["queued"])
            self.assertTrue(res["hits"])
            for w in ("KITWORD", "주간", "350"):
                self.assertNotIn(w, line)
        self.assertEqual(self.queue(), [])

    def test_tokens_from_instruction_are_allowed(self):
        code, _ = propose.main_propose(self.write(draft(summary=["PH_K7Q2 화면의 정렬을 바꿨다"])), home=self.home)
        self.assertEqual(code, 0)        # 표 확인은 허브가 한다

    def test_bad_input(self):
        for obj in (draft(kind="plan"), draft(job="7"), [1]):
            self.assertEqual(json.loads(propose.main_propose(self.write(obj), home=self.home)[1]),
                             {"queued": False, "error": "E-04"})
        self.assertEqual(propose.main_propose(os.path.join(self.tmp, "none.json"), home=self.home)[0], 2)
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.assertEqual(json.loads(propose.main_propose(self.write(draft()), home=empty)[1]),
                         {"queued": False, "error": "E-20"})


# 합성 카나리아 (가린 묶음) - 대기열 · 출력 어디에도 있으면 안 된다
K_WORD = "KITPROPOSEWORDQ"
K_IDENT = "kitProposeCalcQ"
K_NUMBER = "731337"
K_DIR = "kitsrcq"
K_FILE = "kitpropose_secret_mod.py"
O, C = "\u27e6", "\u27e7"


class ProposeBundle(Base):
    """propose bundle.json (SP-20) - 가리기는 안쪽 프로세스에서 · 대기열에는 가린 바이트만."""

    def setUp(self):
        Base.setUp(self)
        from diodelib import vault
        self.vault = vault
        self.work = os.path.join(self.tmp, "opencode-work")
        os.makedirs(os.path.join(self.work, K_DIR))
        with open(os.path.join(self.work, K_DIR, K_FILE), "w", encoding="utf-8", newline="\n") as f:
            f.write("def %si:%s%s():\n    return %sn:%s%s  # %s%s%s\n" % (O, K_IDENT, C, O, K_NUMBER, C, O, K_WORD, C))
        with open(os.path.join(self.work, "kitnotes.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("%s%s%s 와 KITWORDALPHA 의 계산\n" % (O, K_WORD, C))      # 사전 단어는 자동 가림

    def manifest(self, **kw):
        m = {"format": 1, "kind": "bundle", "note": "계산 함수를 고쳐 달라",
             "files": [{"path": K_DIR + "/" + K_FILE, "type": "code"}, {"path": "kitnotes.md", "type": "doc"}]}
        m.update(kw)
        return m

    def run_propose(self, man):
        p = os.path.join(self.work, "bundle.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False)
        code, line = propose.main_propose(p, home=self.home)
        for c in (K_WORD, K_IDENT, K_NUMBER, K_DIR, K_FILE, "kitnotes", "KITWORDALPHA", self.tmp):
            self.assertNotIn(c, line)
        return code, json.loads(line)

    def test_no_open_project_is_e33(self):
        self.assertEqual(self.run_propose(self.manifest()), (2, {"queued": False, "error": "E-33"}))
        self.assertEqual(self.queue(), [])

    def test_queued_file_has_only_masked_bytes(self):
        self.vault.open_project(self.home, False)
        self.assertEqual(self.run_propose(self.manifest()), (0, {"queued": True, "bundle": True}))
        q = self.queue()
        self.assertEqual(len(q), 1)
        self.assertTrue(q[0].startswith("bundle-"))
        path = os.path.join(self.home, "queue", q[0])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, "rb") as f:
            raw = f.read()
        for c in (K_WORD, K_IDENT, K_NUMBER, K_DIR, K_FILE, "kitnotes", "KITWORDALPHA", self.work, "\u27e6"):
            self.assertNotIn(c.encode("utf-8"), raw)        # 원본 바이트 · 원래 이름 · 경로 · 표시가 없다
        d = json.loads(raw.decode("utf-8"))
        self.assertEqual(set(d), {"format", "kind", "project", "job", "note", "files", "stats"})
        self.assertEqual((d["kind"], d["project"], d["job"]), ("bundle", "P-0001", None))
        self.assertEqual([(f["name"], f["type"]) for f in d["files"]], [("F01.py", "code"), ("F02.md", "doc")])
        self.assertEqual(d["stats"]["files"], 2)
        self.assertGreaterEqual(d["stats"]["auto"], 1)
        self.assertEqual(self.vault.project_status(self.home)["files"], 2)       # 원래 이름은 금고에만

    def test_job_is_optional(self):
        self.vault.open_project(self.home, False)
        self.assertEqual(self.run_propose(self.manifest(job="J-0007")), (0, {"queued": True, "job": "J-0007"}))
        self.assertTrue(self.queue()[0].startswith("J-0007-"))
        self.assertEqual(self.run_propose(self.manifest(job="7"))[1], {"queued": False, "error": "E-04", "where": ["job"]})

    def test_hits_have_no_words(self):
        self.vault.open_project(self.home, False)
        with open(os.path.join(self.work, "kitnotes.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("값 8642 는 표시하지 않았다\n")           # 금고에 없는 수 (금고 값이면 자동 가림이 가린다)
        code, res = self.run_propose(self.manifest())
        self.assertEqual(code, 2)
        self.assertFalse(res["queued"])
        self.assertIn({"check": "R4", "count": 1, "where": ["F02:L1"]}, res["hits"])
        self.assertEqual(self.queue(), [])

    def test_bad_marks_and_shapes_are_e04_with_places_only(self):
        self.vault.open_project(self.home, False)
        with open(os.path.join(self.work, "kitnotes.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("첫 줄\n%s%s 닫지 않음\n" % (O, K_WORD))
        self.assertEqual(self.run_propose(self.manifest()), (2, {"queued": False, "error": "E-04", "where": ["files[1]:L2"]}))
        for man in (self.manifest(files=[{"path": "../x.md", "type": "doc"}]), self.manifest(extra=1),
                    self.manifest(files=[{"path": "kitnotes.md", "type": "raw"}])):
            code, res = self.run_propose(man)
            self.assertEqual((code, res["error"]), (2, "E-04"))
        with open(os.path.join(self.work, "kitnotes.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("")
        self.assertEqual(self.run_propose(self.manifest())[1], {"queued": False, "error": "E-04", "where": ["files[1]"]})
        self.assertEqual(self.queue(), [])

    def test_queue_limit_is_4_mib_for_bundles(self):
        self.vault.open_project(self.home, False)
        self.assertEqual(propose.MAX_BUNDLE_QUEUE_BYTES, 4 * 1024 * 1024)
        self.assertEqual(hub.QUEUE_MAX_BUNDLE_BYTES, propose.MAX_BUNDLE_QUEUE_BYTES)
        saved = propose.MAX_BUNDLE_QUEUE_BYTES
        propose.MAX_BUNDLE_QUEUE_BYTES = 200                     # 상한을 줄여 넘김을 본다 (실행 코드에는 바꾸는 길이 없다)
        try:
            self.assertEqual(self.run_propose(self.manifest()), (2, {"queued": False, "error": "E-04"}))
        finally:
            propose.MAX_BUNDLE_QUEUE_BYTES = saved
        self.assertEqual(self.queue(), [])

    def test_halted_project_is_refused(self):
        self.vault.open_project(self.home, False)
        with self.vault.Vault.locked(self.home, False) as v:
            v.halt()
        self.assertEqual(self.run_propose(self.manifest()), (2, {"queued": False, "error": "E-20"}))

    def test_big_queue_files_of_other_sessions_are_left(self):
        d = os.path.join(self.home, "queue")
        os.makedirs(d)
        with open(os.path.join(d, "J-0042-1.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "bundle", "pad": "x" * (hub.QUEUE_MAX_BYTES + 10)}))
        room = os.path.join(self.tmp, "room")
        make_room(room)
        h = hub.Hub(room, hub.Parts())
        self.assertEqual(hub.poll_queue(h, self.home), 0)
        self.assertEqual(self.queue(), ["J-0042-1.json"])


class FakeWorker(object):
    def check(self):
        return True

    def send(self, job, text, attachments):
        return True


class Queue(Base):
    def setUp(self):
        Base.setUp(self)
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)
        self.seen = []

        def confirm(req):
            self.seen.append(req["direction"])
            return {"decision": "send", "sha256": hashlib.sha256(req["text"].encode("utf-8")).hexdigest()}
        from diodelib import audit, transport
        self.parts = hub.Parts(confirm=confirm, worker=FakeWorker(), judge=lambda t: {"verdict": "pass"},
                               transport=transport.RoomTransport(self.room), audit=audit.sink(self.home),
                               confirmed=lambda: audit.confirmed_hashes(self.home),
                               policy=lambda: scan.policy_from_home(self.home), reserve=hub.file_reserver(self.home))
        self.h = hub.Hub(self.room, self.parts)

    def test_round_trip(self):
        self.assertEqual(self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"}), {"sent": True, "job": "J-0001"})
        self.assertEqual(propose.main_propose(self.write(draft()), home=self.home)[0], 0)
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual(self.queue(), [])                            # 읽은 초안은 지운다
        self.assertEqual(self.seen, ["dispatch", "out"])
        reports = self.h.call("inbox", {})["reports"]
        self.assertEqual([r["job"] for r in reports], ["J-0001"])
        self.assertNotIn("주간", json.dumps(reports, ensure_ascii=False))

    def test_other_sessions_files_are_left(self):
        propose.main_propose(self.write(draft(job="J-0042")), home=self.home)
        self.assertEqual(hub.poll_queue(self.h, self.home), 0)
        self.assertEqual(len(self.queue()), 1)
        old = time.time() - hub.QUEUE_MAX_AGE_S - 10
        p = os.path.join(self.home, "queue", self.queue()[0])
        os.utime(p, (old, old))
        hub.poll_queue(self.h, self.home)
        self.assertEqual(self.queue(), [])                            # 24시간 넘은 초안은 지운다

    def test_job_numbers_unique_across_sessions(self):
        other = hub.Hub(self.room, self.parts)
        a = self.h.call("dispatch", {"instruction": "하나"})["job"]
        b = other.call("dispatch", {"instruction": "둘"})["job"]
        self.assertNotEqual(a, b)


class McpProcess(Base):
    """진짜 diode.py mcp 프로세스 — 방이면 도구가 돌고 (일꾼이 없어 E-01), 방이 아니면 E-05."""

    def _run(self, project):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "dispatch", "arguments": {"instruction": "목록 화면을 만들어 달라"}}}]
        env = dict(os.environ)
        env.update({"HOME": self.tmp, "USERPROFILE": self.tmp, "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local"),
                    "CLAUDE_PROJECT_DIR": project, "PYTHONIOENCODING": "utf-8"})
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py"), "mcp"],
                           input="".join(json.dumps(m) + "\n" for m in msgs).encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        self.assertEqual(p.returncode, 0)
        return [json.loads(x) for x in p.stdout.decode("utf-8").splitlines()]

    def test_room(self):
        room = os.path.join(self.tmp, "room")
        make_room(room)
        r = self._run(room)
        self.assertEqual(r[0]["result"]["serverInfo"]["name"], "diode")
        self.assertEqual(len(r[1]["result"]["tools"]), 4)
        self.assertEqual(json.loads(r[2]["result"]["content"][0]["text"]), {"sent": False, "error": "E-01"})

    def test_not_room(self):
        r = self._run(self.tmp)
        self.assertEqual(json.loads(r[2]["result"]["content"][0]["text"]), {"sent": False, "error": "E-05"})


class PluginMcpFile(unittest.TestCase):
    def test_mcp_json(self):
        with open(os.path.join(ROOT, ".mcp.json"), encoding="utf-8") as f:
            m = json.load(f)["mcpServers"]
        self.assertEqual(list(m), ["hub"])                              # 도구 이름 mcp__plugin_diode_hub__*
        self.assertEqual(m["hub"]["command"], "python")                 # 이름만 (L-30)
        self.assertEqual(m["hub"]["args"], ["${CLAUDE_PLUGIN_ROOT}/diode.py", "mcp"])


if __name__ == "__main__":
    unittest.main()
