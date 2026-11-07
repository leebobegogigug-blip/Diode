# -*- coding: utf-8 -*-
"""derive 초안 (plan · ui + sample) 이 propose -> 허브 (D1-D7) -> 확정 창 (D8) -> outbox 로 가는 길 (SP-18 · SP-09).

가짜는 확정 창 (프로세스 안에서 함수를 바꿔 끼움 - AL-02 방식 · 실행 코드에는 우회가 없다) 과 일꾼 · 터미널 확인뿐이다.
D7 은 진짜 judge (설정이 없으면 막음) 와 가짜 판정을 둘 다 쓴다. 모든 자료는 지어낸 것이다.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import audit, confirm, config, derive, hook, hub, propose, room, scan, unseal  # noqa: E402
from diodelib.render import SAMPLE_HEAD, render, sample_text  # noqa: E402
from diodelib.seal import PseudonymTable  # noqa: E402
from tests.test_derive import HEAD_CAT, HEAD_NUM, HEAD_SCORE, canaries, csv_text, dialog  # noqa: E402
from tests.test_propose import make_room  # noqa: E402

REAL_TTY_CHECK = propose._stdin_is_tty        # 시험이 바꿔 끼우기 전의 진짜 확인

JOB = "J-0007"
TRANSFORMS = {"bucket": 1, "rank": 1, "category": 1}


def sha_of(text):
    return confirm.text_sha256(text)


class FakeWorker(object):
    def check(self):
        return True

    def send(self, job, text, attachments):
        return True


class FakeConfirm(object):
    """확정 창 대신. 창이 받는 요청 파일 그대로 (JSON 으로 풀었다 읽음) 읽어 창의 논리 (ConfirmSession) 로 결정한다."""

    def __init__(self, decision="send", wrong_sha=False):
        self.decision, self.wrong_sha = decision, wrong_sha
        self.requests, self.panels = [], []

    def __call__(self, req):
        self.requests.append(req)
        parsed = confirm.parse_request(json.dumps(req).encode("utf-8"))        # 창이 읽을 수 있는 꼴이어야 한다 (E-04 가 아님)
        self.panels.append(confirm.build_panels(parsed))
        session = confirm.ConfirmSession(parsed)
        session.start(0.0)
        if self.decision == "send":
            session.press_send(confirm.SEND_DELAY_S + 0.1)
        elif self.decision == "edit":
            session.press_edit(1.0)
        elif self.decision == "discard":
            session.press_discard(1.0)
        else:
            session.tick(parsed.timeout_s + 1)
        out = {"decision": session.decision}
        if session.decision == "send":
            out["sha256"] = "0" * 64 if self.wrong_sha else parsed.sha256
        return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-flow-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "data")
        os.makedirs(self.home)
        with open(os.path.join(self.home, "dictionary.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)
        self.raw = os.path.join(self.tmp, "kitraw")
        os.makedirs(self.raw)
        self.csv = os.path.join(self.tmp, "kit.csv")
        with open(self.csv, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text())
        self.configure()
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)
        self.fake = FakeConfirm()
        self.parts = hub.default_parts(self.home, self.room)             # 진짜 부품 (판정 · 감사 · 건네기 · 예약 · derive 기록)
        self.parts.confirm = self.fake
        self.parts.worker = FakeWorker()
        self.judged = []

        def judge(text):
            self.judged.append(text)
            return {"verdict": "pass"}
        self.parts.judge = judge
        self.h = hub.Hub(self.room, self.parts)
        tty = mock.patch.object(propose, "_stdin_is_tty", return_value=True)
        tty.start()
        self.addCleanup(tty.stop)

    def configure(self, **kw):
        st = {"words": ["KITWORDALPHA"], "raw_dirs": [self.raw], "inner_tools": [], "lib_allow": [], "patterns": [],
              "web_search": True, "real_data": True, "derived_level": 1, "monthly_budget_usd": 0,
              "worker_command": None, "worker_cwd": None, "room_path": None, "llm": None}
        st.update(kw)
        config.apply_state(self.home, st)

    def derive(self, job=JOB, name="draft.json", text=None):
        out = os.path.join(self.tmp, name)
        err = io.StringIO()
        code, line = derive.main_derive(self.home, True, self.csv, out, io.StringIO(text or dialog(job=job)), err)
        self.assertEqual(code, 0, line)
        return out

    def draft(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def write(self, obj, name="edited.json"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return p

    def queue(self):
        d = os.path.join(self.home, "queue")
        return sorted(x for x in os.listdir(d) if x.endswith(".json")) if os.path.isdir(d) else []

    def outbox(self):
        return sorted(os.listdir(os.path.join(self.room, "outbox")))

    def out_records(self):
        recs = []
        for fn, rec in audit._records(self.home, ("-out.json",)):
            recs.append(rec)
        return recs

    def send(self, path=None, job=JOB):
        """derive 초안을 propose 로 내고 허브가 한 번 돈다. (propose 결과, 처리한 수)."""
        code, line = propose.main_propose(path or self.derive(job=job), home=self.home)
        self.assertEqual((code, json.loads(line)), (0, {"queued": True, "job": job}), line)
        return line, hub.poll_queue(self.h, self.home)

    def all_home_text(self):
        chunks = []
        for base, _dirs, files in os.walk(self.home):
            for fn in files:
                with open(os.path.join(base, fn), "r", encoding="utf-8") as f:
                    chunks.append(f.read())
        return "\n".join(chunks)


class FullRoad(Base):
    def test_a_derived_plan_goes_all_the_way_to_the_outbox(self):
        path = self.derive()
        sample = self.draft(path)["sample"]
        line, n = self.send(path)
        self.assertEqual((n, self.queue()), (1, []))                        # 읽은 초안은 지운다
        self.assertEqual(self.outbox(), [JOB + ".md"])
        with open(os.path.join(self.room, "outbox", JOB + ".md"), "rb") as f:
            sent = f.read().decode("utf-8")
        self.assertIn(sample_text(sample), sent)                           # 표가 보낼 바이트 안에 그대로 있다
        self.assertTrue(sent.startswith("[diode brief format=1 kind=plan data=real]"))
        # D7 에는 펼친 글이 그대로 (표 포함) · 창에도 같은 글이 간다
        self.assertEqual(self.judged, [sent])
        self.assertEqual([r["text"] for r in self.fake.requests], [sent])
        req = self.fake.requests[0]
        self.assertEqual((req["direction"], req["kind"], req["job"], req["transport"]), ("out", "plan", JOB, "room"))
        self.assertEqual(req["checks"], {"ok": True, "hits": []})
        # 감사 기록: 보낸 바이트 그대로 · sha256 · kind · sample 요약
        (rec,) = self.out_records()
        self.assertEqual((rec["decision"], rec["kind"], rec["direction"], rec["job"]), ("sent", "plan", "out", JOB))
        self.assertEqual((rec["text"], rec["sha256"], rec["bytes"]), (sent, sha_of(sent), len(sent.encode("utf-8"))))
        self.assertEqual(rec["sample"], {"transforms": TRANSFORMS, "columns": 3, "rows": 50})
        self.assertIn(rec["sha256"], audit.confirmed_hashes(self.home))
        # inbox 도 확정된 글로 내준다 (확정 기록이 있으니까)
        self.assertEqual(self.h.call("inbox", {"job": JOB}), {"reports": [{"job": JOB, "text": sent}]})

    def test_ui_kind_goes_too(self):
        path = self.derive()
        d = self.draft(path)
        d["kind"] = "ui"
        self.send(self.write(d))
        self.assertEqual(self.outbox(), [JOB + ".md"])
        self.assertEqual(self.out_records()[0]["kind"], "ui")

    def test_the_queue_file_is_private_and_has_no_job_or_value(self):
        code, line = propose.main_propose(self.derive(), home=self.home)
        self.assertEqual(code, 0)
        (name,) = self.queue()
        self.assertTrue(name.startswith(JOB + "-"))
        p = os.path.join(self.home, "queue", name)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn('"job"', text)
        for c in canaries():
            self.assertNotIn(c, text)

    def test_not_confirmed_means_not_sent(self):
        for decision in ("discard", "timeout", "edit"):
            self.fake.decision = decision
            self.send(self.derive(name="d-%s.json" % decision))
            self.assertEqual(self.outbox(), [], decision)
        recs = self.out_records()
        self.assertEqual([r["decision"] for r in recs], ["discarded", "timeout", "discarded"])
        self.assertTrue(all("text" not in r for r in recs))              # 보내지 않았으니 글은 남기지 않는다 (해시만)
        self.assertEqual(self.h.call("inbox", {}), {"reports": []})

    def test_a_wrong_hash_from_the_window_means_not_sent(self):
        self.fake.wrong_sha = True
        self.send()
        self.assertEqual(self.outbox(), [])
        self.assertEqual([r["decision"] for r in self.out_records()], ["discarded"])

    def test_a_discarded_draft_can_be_sent_again_after_a_new_derive(self):
        self.fake.decision = "discard"
        self.send()
        self.fake.decision = "send"
        self.send(self.derive(name="again.json"))
        self.assertEqual(self.outbox(), [JOB + ".md"])

    def test_the_job_is_sent_once(self):
        self.send()
        before = self.outbox()
        self.send(self.derive(name="second.json"))
        self.assertEqual(self.outbox(), before)
        self.assertEqual(len(self.fake.requests), 1)                     # 쓸 수 없는 것을 사람에게 묻지 않는다
        self.assertEqual([r["decision"] for r in self.out_records()], ["sent", "blocked"])


class D7(Base):
    def test_a_block_verdict_means_not_sent(self):
        self.parts.judge = lambda t: {"verdict": "block"}
        self.send()
        self.assertEqual((self.outbox(), self.fake.requests), ([], []))
        (rec,) = self.out_records()
        self.assertEqual((rec["decision"], rec["kind"], rec["checks"]), ("blocked", "plan", [{"check": "D7", "verdict": "block"}]))
        self.assertNotIn("text", rec)

    def test_no_answer_from_the_judge_means_not_sent(self):
        self.parts.judge = lambda t: None
        self.send()
        self.assertEqual((self.outbox(), self.fake.requests), ([], []))

    def test_a_judge_that_raises_means_not_sent(self):
        def boom(t):
            raise RuntimeError("연결 끊김")
        self.parts.judge = boom
        self.send()
        self.assertEqual((self.outbox(), self.fake.requests), ([], []))

    def test_the_real_judge_without_a_setting_blocks_fail_closed(self):
        hub_parts = hub.default_parts(self.home, self.room)
        self.parts.judge = hub_parts.judge                                  # 진짜 판정 - llm 설정이 없다
        self.send()
        self.assertEqual((self.outbox(), self.fake.requests), ([], []))
        self.assertEqual([r["decision"] for r in self.out_records()], ["blocked"])


class GatesOfPropose(Base):
    def test_off_means_refused_and_nothing_is_queued(self):
        path = self.derive()
        self.configure(derived_level=0)
        code, line = propose.main_propose(path, home=self.home)
        self.assertEqual((code, json.loads(line)), (3, {"queued": False, "error": "E-30"}))
        self.assertEqual(self.queue(), [])

    def test_real_data_off_means_off_even_if_the_level_says_one(self):
        path = self.derive()
        cfg = os.path.join(self.home, "config.json")
        with open(cfg, encoding="utf-8") as f:
            c = json.load(f)
        c["policy"]["real_data"] = False
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(c, f)
        self.assertEqual(propose.main_propose(path, home=self.home)[0], 3)
        self.assertEqual(self.queue(), [])

    def test_not_a_terminal_means_refused(self):
        path = self.derive()
        with mock.patch.object(propose, "_stdin_is_tty", return_value=False):
            code, line = propose.main_propose(path, home=self.home)
        self.assertEqual((code, json.loads(line)), (3, {"queued": False, "error": "E-30"}))
        self.assertEqual(self.queue(), [])

    def test_the_terminal_check_reads_stdin_and_nothing_else(self):
        class Tty(object):
            def __init__(self, v):
                self.v = v

            def isatty(self):
                return self.v
        with mock.patch.object(sys, "stdin", Tty(True)), mock.patch.object(derive, "_is_real_console", return_value=True):
            self.assertTrue(REAL_TTY_CHECK())
        with mock.patch.object(sys, "stdin", Tty(False)):
            self.assertFalse(REAL_TTY_CHECK())
        with mock.patch.object(sys, "stdin", object()):
            self.assertFalse(REAL_TTY_CHECK())

    @unittest.skipUnless(os.name == "nt", "Windows 에서만 NUL 이 isatty() 참이다")
    def test_windows_nul_is_not_a_terminal(self):
        """Windows 의 NUL 장치는 isatty() 가 참이다 - 진짜 콘솔 모드로 한 번 더 본다 (CI 의 Windows 가 잡은 허점)."""
        with open(os.devnull, "r") as nul:
            self.assertFalse(derive.stdin_is_terminal(nul))

    def test_no_derive_record_means_refused(self):
        path = self.derive()
        shutil_dir = os.path.join(self.home, "audit")
        shutil.rmtree(shutil_dir)
        code, line = propose.main_propose(path, home=self.home)
        self.assertEqual((code, json.loads(line)), (2, {"queued": False, "error": "E-04"}))
        self.assertEqual(self.queue(), [])

    def test_a_record_from_before_the_hash_existed_does_not_match(self):
        path = self.derive()
        for base, _d, files in os.walk(os.path.join(self.home, "audit")):
            for fn in files:
                p = os.path.join(base, fn)
                with open(p, encoding="utf-8") as f:
                    rec = json.load(f)
                rec.pop("table_sha256")
                rec.pop("tokens")
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(rec, f)
        self.assertEqual(json.loads(propose.main_propose(path, home=self.home)[1]), {"queued": False, "error": "E-04"})

    def test_a_table_that_derive_did_not_make_is_refused(self):
        d = self.draft(self.derive())
        d["sample"]["rows"][0][0] = (d["sample"]["rows"][0][0] + 1) % 10            # 한 칸만 바꿔도
        code, line = propose.main_propose(self.write(d), home=self.home)
        self.assertEqual((code, json.loads(line)), (2, {"queued": False, "error": "E-04"}))
        d = self.draft(self.derive(name="two.json"))
        d["sample"]["rows"].pop()                                                    # 행을 빼도
        self.assertEqual(propose.main_propose(self.write(d), home=self.home)[0], 2)
        self.assertEqual(self.queue(), [])

    def test_a_sample_a_worker_made_up_is_refused(self):
        d = self.draft(self.derive())
        cols = [{"token": "PH_AAAA", "kind": "수치"}, {"token": "PH_BBBB", "kind": "수치"}]
        d["sample"] = {"columns": cols, "rows": [[i % 5, i % 7] for i in range(20)]}
        code, line = propose.main_propose(self.write(d), home=self.home)
        self.assertEqual((code, json.loads(line)), (2, {"queued": False, "error": "E-04"}))

    def test_only_what_derive_wrote_is_accepted(self):
        base = self.draft(self.derive())
        extras = [{"context": ["화면을 만든다"]}, {"entities": [{"ref": "e1", "name": "화면 가", "type": "화면"}]},
                  {"fields": []}, {"route": {"difficulty": "easy"}}, {"job": JOB}, {"constraints": ["작게"]}]
        for extra in extras:
            d = dict(base)
            d.update(extra)
            code, line = propose.main_propose(self.write(d), home=self.home)
            self.assertEqual((code, json.loads(line)), (2, {"queued": False, "error": "E-04"}), extra)
        d = dict(base)
        d["data_class"] = "synthetic"
        self.assertEqual(propose.main_propose(self.write(d), home=self.home)[0], 2)
        d = dict(base)
        del d["sample"]
        self.assertEqual(json.loads(propose.main_propose(self.write(d), home=self.home)[1]),
                         {"queued": False, "error": "E-04"})
        for kind in ("lib", "report"):
            d = dict(base)
            d["kind"] = kind
            self.assertEqual(propose.main_propose(self.write(d), home=self.home)[0], 2)
        self.assertEqual(self.queue(), [])

    def test_edited_free_text_still_goes_through_the_checks(self):
        base = self.draft(self.derive())
        for goal in ("KITWORDALPHA 표를 이해한다", "온도 350 을 맞춘다", "표를 PH_ZZZZ 처럼 본다"):
            d = dict(base)
            d["goal"] = goal
            code, line = propose.main_propose(self.write(d), home=self.home)
            res = json.loads(line)
            self.assertEqual((code, res["queued"]), (2, False), goal)
            self.assertTrue(res["hits"])
            for w in ("KITWORD", "350"):
                self.assertNotIn(w, line)
        d = dict(base)
        d["goal"] = "열 구성을 이해한다"
        self.assertEqual(propose.main_propose(self.write(d), home=self.home)[0], 0)

    def test_output_and_errors_have_no_column_name_value_or_path(self):
        path = self.derive()
        lines = []
        for p in (path, os.path.join(self.tmp, "none.json")):
            lines.append(propose.main_propose(p, home=self.home)[1])
        self.configure(derived_level=0)
        lines.append(propose.main_propose(path, home=self.home)[1])
        d = self.draft(path)
        d["sample"]["rows"][0][0] = (d["sample"]["rows"][0][0] + 1) % 10
        lines.append(propose.main_propose(self.write(d), home=self.home)[1])
        for line in lines:
            json.loads(line)
            for c in canaries() + [self.tmp, "kit.csv", "draft.json", HEAD_NUM, HEAD_CAT, HEAD_SCORE]:
                self.assertNotIn(c, line)

    def test_the_report_path_is_unchanged(self):
        """report 는 한 글자도 다르지 않다 - 같은 출력 꼴 · 같은 거절 (옛 시험 test_propose 가 따로 지킨다)."""
        rep = {"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0001", "status": "done",
               "counts": {"changed_files": 2}, "entities": [{"ref": "s1", "name": "주간 점검표 (가상)", "type": "화면"}],
               "summary": ["[[s1]] 화면을 만들었다"]}
        code, line = propose.main_propose(self.write(rep, "rep.json"), home=self.home)
        self.assertEqual((code, line), (0, '{"queued":true,"job":"J-0001"}'))
        bad = dict(rep, summary=["KITWORDALPHA 화면"])
        code, line = propose.main_propose(self.write(bad, "bad.json"), home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(line)["queued"], False)
        self.assertIn("hits", json.loads(line))
        # 터미널이 아니어도 report 는 낸다 (일꾼이 부르는 길)
        with mock.patch.object(propose, "_stdin_is_tty", return_value=False):
            self.assertEqual(propose.main_propose(self.write(rep, "rep2.json"), home=self.home)[0], 0)
        self.configure(derived_level=0)
        self.assertEqual(propose.main_propose(self.write(rep, "rep3.json"), home=self.home)[0], 0)


class GatesOfHub(Base):
    def put_in_queue(self, draft, job=JOB):
        d = os.path.join(self.home, "queue")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s-1x.json" % job), "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False)

    def test_turned_off_after_queueing_means_not_sent(self):
        code, _ = propose.main_propose(self.derive(), home=self.home)
        self.assertEqual(code, 0)
        self.configure(derived_level=0)
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual((self.outbox(), self.fake.requests, self.judged), ([], [], []))

    def test_a_queue_file_without_a_derive_record_means_not_sent(self):
        d = self.draft(self.derive())
        shutil.rmtree(os.path.join(self.home, "audit"))
        self.put_in_queue(d)
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual((self.outbox(), self.fake.requests, self.judged), ([], [], []))
        self.assertEqual(self.queue(), [])

    def test_a_workers_plan_in_the_queue_is_not_a_door(self):
        """일꾼이 queue 에 직접 쓴 plan (derive 기록과 맞지 않음) 은 가지 않는다 - 일꾼의 일이어도."""
        job = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})["job"]
        d = {"format": 1, "kind": "plan", "data_class": "real", "goal": "표를 이해한다", "ask": "제안해 주세요",
             "sample": {"columns": [{"token": "PH_AAAA", "kind": "수치"}], "rows": [[i % 5] for i in range(20)]}}
        self.put_in_queue(d, job)
        plain = {"format": 1, "kind": "plan", "data_class": "synthetic", "goal": "화면을 만든다", "ask": "제안해 주세요"}
        self.put_in_queue(plain, "J-0044")
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual((self.outbox(), self.judged), ([], []))
        self.assertEqual([r["direction"] for r in self.fake.requests], ["dispatch"])      # 바깥으로 보내는 창은 뜨지 않았다
        self.assertEqual(self.h.jobs[0].state, "working")                  # 일꾼의 일은 그대로 일하는 중
        self.assertEqual(self.queue(), ["J-0044-1x.json"])                 # sample 없는 plan 은 건드리지 않는다
        for kind in ("plan", "ui"):
            self.assertEqual(self.h.take_report({"format": 1, "kind": kind, "data_class": "synthetic", "job": job,
                                                  "goal": "화면을 만든다", "ask": "제안해 주세요"}), "blocked")
        self.assertEqual((self.outbox(), len(self.fake.requests)), ([], 1))

    def test_the_report_road_is_unchanged_next_to_a_derived_one(self):
        job = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})["job"]
        rep = {"format": 1, "kind": "report", "data_class": "synthetic", "job": job, "status": "done",
               "counts": {"changed_files": 2}, "summary": ["화면을 만들었다"]}
        self.assertEqual(propose.main_propose(self.write(rep, "r.json"), home=self.home)[0], 0)
        self.send(job="J-0042")                                            # 같은 대기열에 둘이 있다
        self.assertEqual(sorted(self.outbox()), [job + ".md", "J-0042.md"])
        kinds = sorted((r["job"], r["kind"]) for r in self.out_records())
        self.assertEqual(kinds, [(job, "report"), ("J-0042", "plan")])
        self.assertTrue(all("sample" not in r for r in self.out_records() if r["kind"] == "report"))
        self.assertEqual([r["kind"] for r in self.fake.requests if r["direction"] == "out"], ["report", "plan"])
        self.assertEqual(self.h.jobs[0].state, "reported")

    def test_a_job_the_hub_gave_to_a_worker_cannot_carry_a_derived_plan(self):
        job = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})["job"]
        d = self.derive(job=job, name="w.json")
        self.assertEqual(propose.main_propose(d, home=self.home)[0], 0)
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual(self.outbox(), [])
        self.assertEqual(self.h.jobs[0].state, "working")

    def test_other_sessions_report_files_are_left_alone(self):
        rep = {"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0042", "status": "done",
               "summary": ["화면을 만들었다"]}
        propose.main_propose(self.write(rep, "o.json"), home=self.home)
        self.send()
        self.assertEqual(len(self.queue()), 1)
        self.assertTrue(self.queue()[0].startswith("J-0042-"))

    def test_no_window_or_no_part_means_not_sent(self):
        propose.main_propose(self.derive(), home=self.home)
        self.parts.derive_lookup = None
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual((self.outbox(), self.fake.requests), ([], []))
        for i, name in enumerate(("confirm", "audit", "transport", "judge", "policy")):
            propose.main_propose(self.derive(job="J-005%d" % i, name="x-%s.json" % name), home=self.home)
            self.parts.derive_lookup = hub._derive_lookup(self.home)
            saved = getattr(self.parts, name)
            setattr(self.parts, name, None)
            self.assertEqual(hub.poll_queue(self.h, self.home), 1)
            setattr(self.parts, name, saved)
            self.assertEqual(self.outbox(), [], name)

    def test_a_full_outbox_name_means_blocked_before_the_window(self):
        with open(os.path.join(self.room, "outbox", JOB + ".md"), "w") as f:
            f.write("x")
        self.send()
        self.assertEqual(self.fake.requests, [])

    def test_a_room_that_is_not_ok_means_not_sent_and_no_sent_record(self):
        os.unlink(os.path.join(self.room, ".diode-room"))
        propose.main_propose(self.derive(), home=self.home)
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual(os.listdir(os.path.join(self.room, "outbox")), [])
        self.assertEqual([r for r in self.out_records() if r["decision"] == "sent"], [])


class OneWayTokens(Base):
    """derive 의 가명 표는 사라졌다 - 이 토큰은 되돌릴 단어가 없는 일방향 토큰이다."""

    def test_the_sample_tokens_pass_d6_only_through_the_derive_record(self):
        path = self.derive()
        d = self.draft(path)
        toks = derive.sample_tokens(d["sample"])
        self.assertEqual(len(toks), 5)                                     # 열 셋 + 범주 값 둘 (둘은 PH_other 로 묶였다)
        policy = scan.policy_from_home(self.home)
        from diodelib.seal import seal
        self.assertFalse(seal(d, PseudonymTable(), policy)["ok"])          # 표를 모르면 D6 에 걸린다
        self.assertTrue(seal(d, PseudonymTable(), policy, known_tokens=toks)["ok"])

    def test_the_token_count_limit_in_the_record_is_kept(self):
        d = self.draft(self.derive())
        rec = audit.derive_find(self.home, derive.draft_table_sha256(d))
        self.assertEqual((rec["tokens"], rec["job"], rec["columns"], rec["rows"]), (5, JOB, 3, 50))
        self.assertEqual(len(derive.check_draft(d, rec)), 5)
        for bad in (dict(rec, tokens=4), dict(rec, columns=2), dict(rec, rows=49),
                    dict(rec, transforms={"bucket": 1, "rank": 1, "category": 0})):
            with self.assertRaises(derive.DeriveError):
                derive.check_draft(d, bad)

    def test_unseal_does_not_know_them_so_nothing_comes_back(self):
        self.send()
        with open(os.path.join(self.room, "outbox", JOB + ".md"), encoding="utf-8") as f:
            sent = f.read()
        toks = sorted(scan.find_tokens(sent))
        self.assertTrue(toks)
        self.assertEqual(self.h.restore(sent), sent)                       # 안쪽으로 가는 지시에서 되돌려지지 않는다
        for j in self.h.jobs:
            self.assertEqual(len(j.table), 0)
        table = PseudonymTable()                                           # 말 봉인 창의 표든 허브의 표든 이 토큰은 없다
        with_tokens = [no for no, ln in enumerate(sent.split("\n"), 1) if scan.find_tokens(ln)]
        self.assertTrue(set(with_tokens) <= set(unseal.u1(sent, table)))
        policy = scan.policy_from_home(self.home)
        answer = "답 %s 입니다" % toks[0]
        res = unseal.unseal(answer, table, policy, "plan")
        self.assertEqual(res["issues"]["U1"], [1])                         # 모르는 토큰 (U1) - 기존 동작 그대로
        self.assertEqual(res["text"], answer)                              # 되돌려지지 않고 토큰 그대로

    def test_the_sample_tokens_are_not_in_any_job_table_of_the_hub(self):
        job = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})["job"]
        self.assertTrue(job)
        self.send(job="J-0042")
        toks = derive.sample_tokens(self.draft(os.path.join(self.tmp, "draft.json"))["sample"])
        for j in self.h.jobs:
            for t in toks:
                self.assertIsNone(j.table.real_of(t))


class WhatTheWindowShows(Base):
    def test_the_table_is_in_the_bytes_the_human_sees_and_a_warning_names_its_shape(self):
        path = self.derive()
        sample = self.draft(path)["sample"]
        self.send(path)
        panels = self.fake.panels[0]
        shown = "".join(t for t, form in panels.segments if form != "hidden")
        self.assertEqual(shown, self.fake.requests[0]["text"])             # 보낼 바이트 그대로
        self.assertIn(sample_text(sample), shown)
        self.assertIn(SAMPLE_HEAD, shown)
        warn = [t for t, _ in panels.notices if t.startswith("‼ 표가")]
        self.assertEqual(len(warn), 1)
        for want in ("3열", "50행", "실값에서 줄인 값", "재식별이 안 된다고 증명할 수 없습니다"):
            self.assertIn(want, warn[0])
        self.assertEqual(panels.check_line, "DIODE V>Vth 통과")
        self.assertEqual(panels.send_label, "보내기")

    def test_the_shape_is_counted_from_the_text_not_from_a_field(self):
        d = self.draft(self.derive())
        text = render(dict(d, sample=d["sample"]))
        self.assertEqual(confirm.sample_shape(text), (3, 50))
        self.assertIsNone(confirm.sample_shape("[diode report format=1 job=J-0001 status=done]\n[/diode report]\n"))
        self.assertIsNone(confirm.sample_shape(SAMPLE_HEAD + "\nnot a table\n"))

    def test_a_report_window_has_no_table_warning(self):
        req = {"format": 1, "direction": "out", "job": "J-0001", "kind": "report", "transport": "room",
               "text": "[diode report format=1 job=J-0001 status=done]\n[/diode report]\n", "attachments": [],
               "checks": {"ok": True, "hits": []}, "model": "", "effort": "", "month": {"pct": None, "estimated": True}}
        panels = confirm.build_panels(confirm.parse_request(json.dumps(req).encode("utf-8")))
        self.assertEqual([t for t, _ in panels.notices],
                         [confirm.TEXT_IRREVERSIBLE["out"], confirm.TEXT_AUDIT])
        # 안쪽으로 넘기는 지시에 표 꼴이 있어도 (사람이 쓴 지시) 바깥 경고는 아니다
        req2 = dict(req, direction="dispatch", kind="report", text=SAMPLE_HEAD + "\n| PH_AAAA (수치) |\n|---|\n| 1 |\n")
        panels2 = confirm.build_panels(confirm.parse_request(json.dumps(req2).encode("utf-8")))
        self.assertFalse([t for t, _ in panels2.notices if t.startswith("‼ 표가")])

    def test_the_window_cannot_send_before_two_seconds_and_a_blocked_check_keeps_it_off(self):
        d = self.draft(self.derive())
        text = render(d)
        req = {"format": 1, "direction": "out", "job": JOB, "kind": "plan", "transport": "room", "text": text,
               "attachments": [], "checks": {"ok": True, "hits": []}, "model": "", "effort": "",
               "month": {"pct": None, "estimated": True}}
        s = confirm.ConfirmSession(confirm.parse_request(json.dumps(req).encode("utf-8")))
        s.start(0.0)
        self.assertFalse(s.press_send(0.5))
        self.assertTrue(s.press_send(2.5))
        self.assertEqual(s.decision, "send")


class WhatIsRecorded(Base):
    def test_audit_has_the_bytes_the_hash_the_kind_and_only_counts_for_the_sample(self):
        self.send()
        derive_files = [fn for _d, _s, fns in os.walk(os.path.join(self.home, "audit")) for fn in fns]
        self.assertEqual(sorted(derive_files), [JOB + "-001-derive.json", JOB + "-002-out.json"])
        (rec,) = self.out_records()
        self.assertEqual(set(rec), {"format", "at", "job", "direction", "kind", "transport", "decision", "sha256",
                                    "bytes", "text", "checks", "model", "effort", "sample"})
        self.assertEqual(set(rec["sample"]), {"transforms", "columns", "rows"})
        self.assertTrue(all(isinstance(v, int) for v in rec["sample"]["transforms"].values()))
        self.assertEqual(rec["transport"], "room")
        # 감사 기록 · 대기열 · 창 요청 어디에도 열 이름 · 수치 · 고르지 않은 열의 값이 없다
        everything = self.all_home_text() + json.dumps(self.fake.requests, ensure_ascii=False)
        with open(os.path.join(self.room, "outbox", JOB + ".md"), encoding="utf-8") as f:
            everything += f.read()
        for c in canaries():
            self.assertNotIn(c, everything, "새는 값이 있다")

    def test_the_derive_record_has_no_token_or_name(self):
        self.derive()
        text = ""
        for base, _dirs, files in os.walk(os.path.join(self.home, "audit")):
            for fn in files:
                with open(os.path.join(base, fn), "r", encoding="utf-8") as f:
                    text += f.read()
        d = self.draft(os.path.join(self.tmp, "draft.json"))
        for t in derive.sample_tokens(d["sample"]):
            self.assertNotIn(t, text)
        self.assertNotIn(self.tmp, text)

    def test_the_audit_refuses_a_sample_that_is_not_counts_or_not_a_sent_plan(self):
        ok = {"transforms": TRANSFORMS, "columns": 3, "rows": 50}
        for bad in ({"transforms": TRANSFORMS, "columns": 3}, dict(ok, extra=1), dict(ok, columns=4),
                    dict(ok, rows=0), dict(ok, rows=51), dict(ok, transforms={"bucket": 1, "rank": 1}),
                    dict(ok, transforms=dict(TRANSFORMS, bucket="1")), {"cells": [[1]]}, "표"):
            with self.assertRaises(audit.AuditError):
                audit.build(JOB, "out", "plan", "room", "sent", text="글\n", sample=bad)
        for direction, kind in (("in", "plan"), ("out", "report"), ("dispatch", "instruction")):
            with self.assertRaises(audit.AuditError):
                audit.build(JOB, direction, kind, "room" if direction == "out" else "worker", "blocked", sample=ok)
        rec = audit.build(JOB, "out", "ui", "room", "sent", text="글\n", sample=ok)
        self.assertEqual(rec["sample"], ok)

    def test_the_cumulative_limit_still_counts_derive_runs(self):
        for i in range(4):
            self.derive(name="c%d.json" % i)
        self.assertEqual(audit.derived_rows(self.home, JOB), 200)
        out = os.path.join(self.tmp, "fifth.json")
        code, line = derive.main_derive(self.home, True, self.csv, out, io.StringIO(dialog()), io.StringIO())
        self.assertEqual((code, json.loads(line)), (2, {"derived": False, "error": "E-31"}))
        self.assertFalse(os.path.exists(out))


class OtherPieces(Base):
    def test_the_hook_hint_points_at_speak(self):
        self.assertIn("/diode:speak", hook.MSG["hint"])
        self.assertNotIn("말 봉인 칸", hook.MSG["hint"])

    def test_the_cli_refuses_a_derived_draft_when_stdin_is_not_a_terminal(self):
        """진짜 diode.py propose 프로세스 - 표준 입력이 터미널이 아니면 (일꾼이 부르는 모양) 받지 않는다."""
        env = dict(os.environ)
        env.update({"HOME": self.tmp, "USERPROFILE": self.tmp, "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local"),
                    "PYTHONIOENCODING": "utf-8"})
        env.pop("DIODE_HOME", None)
        with mock.patch.dict(os.environ, env):
            default_home = room.default_data_dir()
        shutil.copytree(self.home, default_home)
        path = self.derive()
        p = subprocess.run([sys.executable, os.path.join(ROOT, "diode.py"), "propose", path], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        with open(path, "rb") as fh:
            raw = fh.read()
        parsed = scan.parse_brief(raw)
        try:
            sha_ok = bool(derive.draft_table_sha256(parsed))
        except Exception as e:
            sha_ok = type(e).__name__
        probe = "isfile=%s size=%d parsed=%s shape=%s sha=%s inproc=%s" % (
            os.path.isfile(path), len(raw), isinstance(parsed, dict), derive.draft_shape_ok(parsed), sha_ok,
            propose.main_propose(path, home=default_home))
        why = probe + " | " + (p.stdout + b" | " + p.stderr).decode("utf-8", "replace")[-400:]      # 합성 자료뿐 - 실패 때 까닭을 본다
        self.assertEqual(p.returncode, 3, why)
        self.assertEqual(json.loads(p.stdout.decode("utf-8")), {"queued": False, "error": "E-30"})
        self.assertFalse(os.path.isdir(os.path.join(default_home, "queue")))
        for c in canaries() + [self.tmp]:
            self.assertNotIn(c, p.stdout.decode("utf-8") + p.stderr.decode("utf-8"))


def _tk_ok():
    try:
        from tests.test_confirm import TK_OK
        return TK_OK
    except Exception:
        return False


@unittest.skipUnless(_tk_ok(), "DISPLAY 가 없거나 tkinter 로 창을 열 수 없어 실제 창 시험은 건너뜀")
class RealWindowWithATable(Base):
    def test_the_widget_shows_the_table_exactly_and_the_warning(self):
        import tkinter
        from tests.test_confirm import Clock, all_widgets
        path = self.derive()
        text = render(self.draft(path))
        req = {"format": 1, "direction": "out", "job": JOB, "kind": "plan", "transport": "room", "text": text,
               "attachments": [], "checks": {"ok": True, "hits": []}, "model": "", "effort": "",
               "month": {"pct": None, "estimated": True}}
        view = confirm.TkView(tkinter, clock=Clock())
        self.addCleanup(view.close)
        view.open(confirm.ConfirmSession(confirm.parse_request(json.dumps(req).encode("utf-8")), clipboard=view.set_clipboard))
        self.assertEqual(view.widgets["text"].get("1.0", "end-1c"), text)
        labels = [wd["text"] for wd in all_widgets(view.root) if wd.winfo_class() == "Label"]
        self.assertTrue(any(t.startswith("‼ 표가") and "3열" in t and "50행" in t for t in labels))


if __name__ == "__main__":
    unittest.main()
