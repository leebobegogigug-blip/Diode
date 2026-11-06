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
