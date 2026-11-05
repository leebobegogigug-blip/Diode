# -*- coding: utf-8 -*-
"""허브 (diodelib.hub · SP-08) — 가짜 부품 (확정 창 · 일꾼 · 판정 · 건네기 · 감사 기록) 으로. 합성 자료만."""

import hashlib
import io
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

from diodelib import hub, scan  # noqa: E402


def make_room(folder):
    """tests/test_hook.py 의 make_room 과 같은 방 (표지 · 방 설정 · 폴더 셋)."""
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

REAL = "주간 점검표 (가상)"


class FakeWorker(object):
    def __init__(self, ok=True, alive=True):
        self.ok, self.alive, self.sent = ok, alive, []

    def check(self):
        return self.alive

    def send(self, job, text, attachments):
        self.sent.append((job, text, attachments))
        return self.ok


class FakeConfirm(object):
    def __init__(self, decision="send", wrong_sha=False, code=None):
        self.decision, self.wrong_sha, self.code, self.seen = decision, wrong_sha, code, []

    def __call__(self, req):
        self.seen.append(req)
        if self.decision == "error":
            return {"decision": "error", "code": self.code or "E-07"}
        sha = hashlib.sha256(req["text"].encode("utf-8")).hexdigest()
        return {"decision": self.decision, "sha256": ("0" * 64) if self.wrong_sha else sha}


class FakeTransport(object):
    def __init__(self, room):
        self.room = room

    def put(self, job, text, route):
        with open(os.path.join(self.room, "outbox", job + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-hub-"))
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)
        with open(os.path.join(self.room, "work", "a.html"), "w") as f:
            f.write("<html></html>")
        self.records = []
        self.worker = FakeWorker()
        self.confirm = FakeConfirm()
        self.parts = hub.Parts(confirm=self.confirm, worker=self.worker, judge=lambda t: {"verdict": "pass"},
                               transport=FakeTransport(self.room), audit=self.records.append,
                               confirmed=lambda: set(r["sha256"] for r in self.records
                                                     if r.get("direction") == "out" and r.get("decision") == "sent"),
                               policy=lambda: scan.Policy(words=["KITWORDALPHA"]))
        self.h = hub.Hub(self.room, self.parts)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assertNoInner(self, res):
        dumped = json.dumps(res, ensure_ascii=False)
        self.assertNotIn("주간", dumped)
        self.assertNotIn(self.tmp, dumped)


class Dispatch(Base):
    def test_not_room(self):
        h = hub.Hub(self.tmp, self.parts)
        self.assertEqual(h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": "E-05"})
        for t in ("inbox", "jobs", "status"):
            self.assertEqual(h.call(t, {}), {"error": "E-05"})

    def test_input(self):
        for args in ({"instruction": ""}, {"instruction": "x" * 4001}, {"instruction": "x", "extra": 1},
                     {"instruction": "x", "attachments": ["../a.html"]}, {"instruction": "x", "attachments": ["없음.html"]},
                     {"instruction": "x", "attachments": ["a.html"] * 6}, {"instruction": 3}):
            self.assertEqual(self.h.call("dispatch", args), {"sent": False, "error": "E-04"}, args)
        self.assertEqual(self.h.call("nope", {}), {"error": "E-04"})

    def test_no_worker(self):
        self.parts.worker = None
        self.assertEqual(self.h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": "E-01"})
        self.parts.worker = FakeWorker(alive=False)
        self.assertEqual(self.h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": "E-01"})
        self.assertEqual(self.confirm.seen, [])                     # 일꾼이 없으면 사람을 부르지 않는다

    def test_human_decisions(self):
        for decision, code in (("discard", "E-02"), ("edit", "E-02"), ("timeout", "E-03")):
            self.confirm.decision = decision
            self.assertEqual(self.h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": code})
        self.confirm.decision, self.confirm.code = "error", "E-07"
        self.assertEqual(self.h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": "E-07"})
        self.assertEqual(self.worker.sent, [])

    def test_confirm_must_match_bytes(self):
        self.confirm.wrong_sha = True
        self.assertEqual(self.h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": "E-02"})
        self.assertEqual(self.worker.sent, [])

    def test_sent_with_restored_tokens(self):
        first = self.h._new_job()
        tok = first.table.token_for(REAL, "entity")
        res = self.h.call("dispatch", {"instruction": "%s 화면을 만들어 달라" % tok, "attachments": ["a.html"]})
        self.assertEqual(res, {"sent": True, "job": "J-0002"})
        self.assertNoInner(res)
        job, body, att = self.worker.sent[0]
        self.assertEqual(job, "J-0002")
        self.assertTrue(body.startswith("[diode J-0002]\n"))
        self.assertIn(REAL + " 화면을 만들어 달라", body)             # 안쪽으로는 진짜 단어
        self.assertEqual(att, ["a.html"])
        self.assertEqual(self.confirm.seen[0]["text"], REAL + " 화면을 만들어 달라")
        rec = [r for r in self.records if r["direction"] == "dispatch"][-1]
        self.assertEqual(rec["decision"], "sent")
        self.assertIn(tok, rec["text"])                              # 감사 기록에는 토큰 꼴
        self.assertNotIn("주간", rec["text"])

    def test_worker_fails(self):
        self.worker.ok = False
        self.assertEqual(self.h.call("dispatch", {"instruction": "x"}), {"sent": False, "error": "E-01"})

    def test_exception_is_e20(self):
        class Boom(FakeWorker):
            def send(self, *a):
                raise RuntimeError("안쪽 오류 글 %s" % REAL)
        self.parts.worker = Boom()
        res = self.h.call("dispatch", {"instruction": "x"})
        self.assertEqual(res, {"sent": False, "error": "E-20"})
        self.assertNoInner(res)


class Reports(Base):
    def _dispatch(self):
        res = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})
        self.assertTrue(res["sent"])
        return res["job"]

    def _draft(self, job, **kw):
        d = {"format": 1, "kind": "report", "data_class": "synthetic", "job": job, "status": "done",
             "counts": {"changed_files": 2, "tests_passed": 5},
             "entities": [{"ref": "s1", "name": REAL, "type": "화면"}],
             "summary": ["[[s1]] 화면을 만들었다"]}
        d.update(kw)
        return d

    def test_round_trip(self):
        job = self._dispatch()
        self.assertEqual(self.h.take_report(self._draft(job)), "reported")
        res = self.h.call("inbox", {})
        self.assertEqual(len(res["reports"]), 1)
        text = res["reports"][0]["text"]
        self.assertTrue(text.startswith("[diode report format=1 job=%s status=done]" % job))
        self.assertNoInner(res)
        self.assertEqual(self.h.call("jobs", {})["jobs"][-1]["state"], "reported")
        self.assertEqual(self.h.call("inbox", {"job": job})["reports"][0]["job"], job)

    def test_unknown_or_idle_job(self):
        self.assertEqual(self.h.take_report(self._draft("J-0099")), "unknown_job")
        self.assertEqual(self.h.take_report("x"), "unknown_job")
        job = self._dispatch()
        self.assertEqual(self.h.take_report(self._draft(job)), "reported")
        self.assertEqual(self.h.take_report(self._draft(job)), "unknown_job")      # 한 일에 보고는 한 번
        self.confirm.decision = "discard"
        self.assertFalse(self.h.call("dispatch", {"instruction": "x"})["sent"])      # 넘기기를 거절한 일
        self.assertEqual(self.h.take_report(self._draft(self.h.jobs[-1].job)), "unknown_job")

    def test_checks_block(self):
        job = self._dispatch()
        self.assertEqual(self.h.take_report(self._draft(job, summary=["KITWORDALPHA 화면을 만들었다"])), "blocked")
        self.assertEqual(self.h.take_report(self._draft(job, summary=["%s 을 직접 썼다" % REAL])), "blocked")
        self.assertEqual(self.h.call("inbox", {})["reports"], [])
        self.parts.judge = lambda t: {"verdict": "block"}
        self.assertEqual(self.h.take_report(self._draft(job)), "blocked")
        self.parts.judge = lambda t: None
        self.assertEqual(self.h.take_report(self._draft(job)), "blocked")

    def test_human_rejects(self):
        job = self._dispatch()
        self.confirm.decision = "discard"
        self.assertEqual(self.h.take_report(self._draft(job)), "rejected")
        self.assertFalse(os.listdir(os.path.join(self.room, "outbox")))

    def test_unconfirmed_outbox_not_served(self):
        with open(os.path.join(self.room, "outbox", "J-0050.md"), "w", encoding="utf-8") as f:
            f.write("[diode report format=1 job=J-0050 status=done]\n- 몰래 쓴 글\n[/diode report]\n")
        self.assertEqual(self.h.call("inbox", {})["reports"], [])
        self.assertEqual(self.h.call("inbox", {"job": "J-0051"}), {"error": "E-06"})
        self.assertEqual(self.h.call("inbox", {"job": "x"}), {"error": "E-04"})


class RealParts(Base):
    """진짜 감사 기록 (diodelib.audit) · room 건네기 (diodelib.transport) 와 이어 한 바퀴."""

    def test_round_trip_with_audit_and_room(self):
        from diodelib import audit, transport
        home = os.path.join(self.tmp, "data")
        self.parts.audit = audit.sink(home)
        self.parts.confirmed = lambda: audit.confirmed_hashes(home)
        self.parts.transport = transport.RoomTransport(self.room)
        res = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})
        self.assertEqual(res, {"sent": True, "job": "J-0001"})
        draft = {"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0001", "status": "done",
                 "entities": [{"ref": "s1", "name": REAL, "type": "화면"}], "summary": ["[[s1]] 화면을 만들었다"]}
        self.assertEqual(self.h.take_report(draft), "reported")
        reports = self.h.call("inbox", {})["reports"]
        self.assertEqual([r["job"] for r in reports], ["J-0001"])
        self.assertNoInner(reports)
        # 감사 기록 어디에도 진짜 이름이 없다
        for root, _, files in os.walk(os.path.join(home, "audit")):
            for fn in files:
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    self.assertNotIn("주간", f.read())
        # 훅이 읽는 확정 해시와 같다
        from diodelib import hook
        self.assertEqual(hook._confirmed_hashes(home), audit.confirmed_hashes(home))


class ProcessConfirmPart(Base):
    """진짜 확정 창 프로세스 (diode.py confirm) — 화면이 없는 환경에서는 E-07 로 보내지 않는다."""

    def test_headless_is_e07_and_temp_removed(self):
        home = os.path.join(self.tmp, "data")
        self.parts.confirm = hub.ProcessConfirm(home)
        saved = {k: os.environ.pop(k) for k in ("DISPLAY", "WAYLAND_DISPLAY") if k in os.environ}
        try:
            res = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})
        finally:
            os.environ.update(saved)
        if os.name == "nt":
            self.skipTest("Windows 는 화면이 있다고 본다")
        self.assertEqual(res, {"sent": False, "error": "E-07"})
        self.assertEqual(self.worker.sent, [])
        self.assertEqual(os.listdir(os.path.join(home, "tmp")), [])     # 요청 파일은 지운다

    def test_bad_output_is_not_send(self):
        from diodelib import confirm
        want = confirm.text_sha256("x")
        for code, out in ((0, ""), (0, '{"decision": "send", "sha256": "%s"}\n{}' % want),
                          (0, '{"decision": "send", "sha256": "%s"}' % ("0" * 64)), (3, '{"decision": "send", "sha256": "%s"}' % want)):
            self.assertNotEqual(confirm.parse_result(code, out, want)[0], "send", (code, out))
        self.assertEqual(confirm.parse_result(0, '{"decision": "send", "sha256": "%s"}' % want, want), ("send", None))


class JsonRpc(Base):
    def rpc(self, *msgs):
        inp = io.StringIO("".join(json.dumps(m) + "\n" for m in msgs) + "not json\n")
        out = io.StringIO()
        hub.serve(self.h, inp, out)
        return [json.loads(x) for x in out.getvalue().splitlines()]

    def test_session(self):
        replies = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                           {"jsonrpc": "2.0", "method": "notifications/initialized"},
                           {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                           {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "jobs", "arguments": {}}},
                           {"jsonrpc": "2.0", "id": 4, "method": "bogus"})
        self.assertEqual([r.get("id") for r in replies], [1, 2, 3, 4, None])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "diode")
        self.assertEqual([t["name"] for t in replies[1]["result"]["tools"]], ["dispatch", "inbox", "jobs", "status"])
        content = replies[2]["result"]["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(json.loads(content[0]["text"]), {"jobs": []})
        self.assertNotIn("\n", content[0]["text"])
        self.assertEqual(replies[3]["error"]["code"], -32601)
        self.assertEqual(replies[4]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
