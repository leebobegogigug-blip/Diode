# -*- coding: utf-8 -*-
"""감사 기록 (diodelib.audit · SP-14 · AL-07 · AL-13). 임시 폴더 · 합성 글만."""

import datetime
import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import audit, hook  # noqa: E402

TEXT = "[diode report format=1 job=J-0007 status=done]\nSUMMARY:\n- PH_K7Q2 화면을 만들었다\n[/diode report]\n"
NOW = datetime.datetime(2026, 11, 5, 10, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))


def sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="diode-audit-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def files(self):
        out = []
        for root, _, fns in os.walk(os.path.join(self.home, "audit")):
            out.extend(os.path.join(root, f) for f in fns)
        return sorted(out)

    def test_out_record_shape(self):
        p = audit.record(self.home, "J-0007", "out", "report", "room", "sent", text=TEXT,
                         checks=[{"check": "D7", "verdict": "pass"}], model="fake-model", effort="high", now=NOW)
        self.assertEqual(os.path.basename(p), "J-0007-001-out.json")
        self.assertEqual(os.path.basename(os.path.dirname(p)), "2026-11")
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual(rec["format"], 1)
        self.assertEqual(rec["at"], "2026-11-05T10:00:00+09:00")
        self.assertEqual(rec["text"], TEXT)
        self.assertEqual(rec["sha256"], sha(TEXT))
        self.assertEqual(rec["bytes"], len(TEXT.encode("utf-8")))
        self.assertEqual(rec["checks"], [{"check": "D7", "verdict": "pass"}])
        for k in ("job", "direction", "kind", "transport", "decision", "model", "effort"):
            self.assertIn(k, rec)

    def test_sequence_never_overwrites(self):
        a = audit.record(self.home, "J-0007", "dispatch", "instruction", "worker", "sent", text="지시 PH_K7Q2", now=NOW)
        b = audit.record(self.home, "J-0007", "out", "report", "room", "sent", text=TEXT, now=NOW)
        c = audit.record(self.home, "J-0007", "in", "report", "room", "sent", sha256=sha("답"), size=3, now=NOW)
        names = [os.path.basename(x) for x in (a, b, c)]
        self.assertEqual(names, ["J-0007-001-dispatch.json", "J-0007-002-out.json", "J-0007-003-in.json"])
        self.assertEqual(len(self.files()), 3)
        # 다른 job 은 따로 센다
        d = audit.record(self.home, "J-0008", "out", "report", "room", "blocked", now=NOW)
        self.assertEqual(os.path.basename(d), "J-0008-001-out.json")

    def test_concurrent_writers_get_distinct_files(self):
        errs = []

        def w():
            try:
                for _ in range(10):
                    audit.record(self.home, "J-0001", "out", "report", "room", "blocked", now=NOW)
            except Exception as e:  # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=w) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(len(self.files()), 40)

    def test_no_temp_left(self):
        audit.record(self.home, "J-0007", "out", "report", "room", "sent", text=TEXT, now=NOW)
        self.assertFalse([f for f in self.files() if f.endswith(".tmp")])

    def test_in_keeps_no_text(self):
        with self.assertRaises(audit.AuditError):
            audit.record(self.home, "J-0007", "in", "report", "room", "sent", text="답 글", now=NOW)
        with self.assertRaises(audit.AuditError):
            audit.record(self.home, "J-0007", "in", "report", "room", "sent", now=NOW)   # 해시가 없다
        p = audit.record(self.home, "J-0007", "in", "report", "room", "sent", sha256=sha("답 글"), size=7,
                         checks=[{"check": "U1", "count": 0, "lines": [3]}], now=NOW)
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        self.assertNotIn("text", rec)
        self.assertEqual(self.files(), [p])

    def test_no_argument_for_table_or_raw(self):
        params = set(inspect.signature(audit.record).parameters)
        for bad in ("table", "pseudonyms", "raw", "words", "dictionary", "original", "real"):
            self.assertNotIn(bad, params)
        sink = audit.sink(self.home)
        with self.assertRaises(audit.AuditError):
            sink({"job": "J-0007", "direction": "out", "decision": "blocked", "table": {"PH_K7Q2": "x"}})

    def test_checks_accept_only_codes(self):
        with self.assertRaises(audit.AuditError):
            audit.record(self.home, "J-0007", "out", "report", "room", "blocked",
                         checks=[{"check": "D2", "word": "KITWORDALPHA"}], now=NOW)
        with self.assertRaises(audit.AuditError):
            audit.record(self.home, "J-0007", "out", "report", "room", "blocked",
                         checks=[{"check": "D2", "where": ["사내 단어 그대로"]}], now=NOW)
        audit.record(self.home, "J-0007", "out", "report", "room", "blocked",
                     checks=[{"check": "D2", "count": 2, "where": ["context[1]", "ask"]},
                             {"check": "E", "code": "E-20"}], now=NOW)

    def test_bad_values_refused(self):
        bad = [
            dict(job="../J-0001"), dict(job="J-1"), dict(direction="up"), dict(kind="raw"),
            dict(transport="mail"), dict(decision="ok"), dict(effort="huge"), dict(model="a\nb"),
        ]
        base = dict(job="J-0001", direction="out", kind="report", transport="room", decision="blocked")
        for b in bad:
            kw = dict(base)
            kw.update(b)
            with self.assertRaises(audit.AuditError, msg=str(b)):
                audit.record(self.home, now=NOW, **kw)
        with self.assertRaises(audit.AuditError):     # 보냈다면 글이 있어야 한다
            audit.record(self.home, "J-0001", "out", "report", "room", "sent", now=NOW)
        with self.assertRaises(audit.AuditError):     # 해시가 글과 다르다
            audit.record(self.home, "J-0001", "out", "report", "room", "sent", text=TEXT, sha256="0" * 64, now=NOW)
        self.assertEqual(self.files(), [])

    def test_confirmed_hashes_match_hook(self):
        audit.record(self.home, "J-0001", "out", "report", "room", "sent", text=TEXT, now=NOW)
        audit.record(self.home, "J-0002", "out", "report", "room", "discarded", sha256=sha("버림"), now=NOW)
        audit.record(self.home, "J-0003", "out", "report", "room", "blocked", now=NOW)
        audit.record(self.home, "J-0004", "in", "report", "room", "sent", sha256=sha("답"), now=NOW)
        audit.record(self.home, "J-0005", "dispatch", "instruction", "worker", "sent", text="지시", now=NOW)
        later = NOW.replace(month=12)
        audit.record(self.home, "J-0006", "out", "plan", "clipboard", "sent", text="다른 달", now=later)
        # 깨진 파일 · 다른 format · 목록 꼴
        d = os.path.join(self.home, "audit", "2026-11")
        with open(os.path.join(d, "J-0009-001-out.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        with open(os.path.join(d, "J-0009-002-out.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 2, "direction": "out", "decision": "sent", "sha256": sha("새 판")}, f)
        with open(os.path.join(d, "J-0009-003-out.json"), "w", encoding="utf-8") as f:
            json.dump([1, 2], f)
        got = audit.confirmed_hashes(self.home)
        self.assertEqual(got, {sha(TEXT), sha("다른 달")})
        self.assertEqual(got, hook._confirmed_hashes(self.home))
        self.assertEqual(audit.confirmed_hashes(os.path.join(self.home, "없음")), set())

    def test_job_states(self):
        audit.record(self.home, "J-0001", "dispatch", "instruction", "worker", "sent", text="지시", now=NOW)
        audit.record(self.home, "J-0002", "dispatch", "instruction", "worker", "sent", text="지시", now=NOW)
        later = NOW + datetime.timedelta(minutes=5)
        audit.record(self.home, "J-0001", "out", "report", "room", "sent", text=TEXT, now=later)
        audit.record(self.home, "J-0002", "out", "report", "room", "discarded", sha256=sha("x"), now=later)
        audit.record(self.home, "J-0003", "dispatch", "instruction", "worker", "discarded", text="지시", now=later)
        st = audit.job_states(self.home)
        self.assertEqual(st, [{"job": "J-0001", "state": "reported"}, {"job": "J-0002", "state": "rejected"}])
        for j in st:
            self.assertEqual(set(j), {"job", "state"})

    def test_sink_for_hub(self):
        sink = audit.sink(self.home)
        p = sink({"job": "J-0007", "direction": "dispatch", "decision": "sent", "text": "지시 PH_K7Q2",
                  "sha256": sha("지시 PH_K7Q2")})
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual((rec["kind"], rec["transport"]), ("instruction", "worker"))
        p = sink({"job": "J-0007", "direction": "out", "decision": "sent", "text": TEXT,
                  "checks": [{"check": "D7", "verdict": "pass"}]})
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual((rec["kind"], rec["transport"]), ("report", "room"))
        self.assertIn(sha(TEXT), audit.confirmed_hashes(self.home))


if __name__ == "__main__":
    unittest.main()
