# -*- coding: utf-8 -*-
"""한 바퀴 (진짜 프로세스): 넘기기 → 일꾼 명령이 diode.py propose 로 보고를 냄 → 허브가 봉인 · D7 · 확정 → outbox → inbox.

확정 창만 가짜다 (화면이 필요하다 · 창은 tests/test_confirm.py 가 본다). 일꾼은 이 파이썬이 띄우는 작은 스크립트.
합성 자료만 쓴다.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import audit, hub, room, scan, transport, worker  # noqa: E402
from tests.test_propose import make_room  # noqa: E402

REAL = "주간 점검표 (가상)"

# 일꾼: 받은 지시에 진짜 이름이 되돌려져 있는지 보고, 보고 초안을 써서 propose 한다 (자기 이름 REAL 은 ref 로 쓴다)
WORKER = r'''
import json, os, subprocess, sys
text = sys.stdin.read()
job = os.environ["DIODE_JOB"]
saw_real = %(real)r in text
draft = {"format": 1, "kind": "report", "data_class": "synthetic", "job": job,
         "status": "done" if saw_real else "question", "counts": {"changed_files": 2},
         "entities": [{"ref": "s1", "name": %(real)r, "type": "화면"}],
         "summary": ["[[s1]] 화면을 만들었다"]}
json.dump(draft, open("report.json", "w", encoding="utf-8"), ensure_ascii=False)
r = subprocess.run([sys.executable, %(diode)r, "propose", "report.json"], capture_output=True, text=True)
open("propose.out", "w", encoding="utf-8").write(r.stdout)
'''


class FullLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-e2e-"))
        env = {"HOME": self.tmp, "USERPROFILE": self.tmp, "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local")}
        self.patch = mock.patch.dict(os.environ, env)
        self.patch.start()
        self.home = room.default_data_dir()
        os.makedirs(self.home)
        with open(os.path.join(self.home, "dictionary.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)
        self.diode_py = os.path.join(ROOT, "diode.py")

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hub(self):
        def confirm(req):
            self.assertTrue(req["checks"]["ok"])
            return {"decision": "send", "sha256": hashlib.sha256(req["text"].encode("utf-8")).hexdigest()}
        script = WORKER % {"real": REAL, "diode": self.diode_py}
        parts = hub.Parts(confirm=confirm,
                          worker=worker.CommandWorker([sys.executable, "-c", script], self.home, self.room),
                          judge=lambda t: {"verdict": "pass"}, transport=transport.RoomTransport(self.room),
                          audit=audit.sink(self.home), confirmed=lambda: audit.confirmed_hashes(self.home),
                          policy=lambda: scan.policy_from_home(self.home), reserve=hub.file_reserver(self.home))
        return hub.Hub(self.room, parts)

    def test_loop(self):
        h = self.hub()
        first = h._new_job()                         # 앞선 일 하나 — 그 표의 토큰이 지시에 들어온다
        tok = first.table.token_for(REAL, "entity")
        res = h.call("dispatch", {"instruction": "%s 화면을 만들어 달라" % tok})
        self.assertEqual(res, {"sent": True, "job": "J-0002"})
        out = os.path.join(self.home, "work", "J-0002", "propose.out")
        end = time.time() + 30
        while time.time() < end and not os.path.exists(out):
            time.sleep(0.1)
        time.sleep(0.2)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read()), {"queued": True, "job": "J-0002"})
        self.assertEqual(hub.poll_queue(h, self.home), 1)
        reports = h.call("inbox", {})["reports"]
        self.assertEqual([r["job"] for r in reports], ["J-0002"])
        text = reports[0]["text"]
        self.assertIn("status=done", text)               # 일꾼이 지시에서 진짜 이름을 봤다 (되돌림이 안쪽으로 갔다)
        self.assertNotIn("주간", text)                    # 바깥으로 나가는 글에는 없다
        self.assertRegex(text, r"PH_[2-9A-HJKMNP-TV-Z]{4} 화면을 만들었다")
        for root, _, files in os.walk(os.path.join(self.home, "audit")):
            for fn in files:
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    self.assertNotIn("주간", f.read())
        self.assertEqual(h.call("jobs", {})["jobs"][-1]["state"], "reported")


if __name__ == "__main__":
    unittest.main()
