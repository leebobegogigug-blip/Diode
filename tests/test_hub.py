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
        sha = hub.request_sha256(req)          # 가린 묶음이면 묶음 다이제스트 · 아니면 text 의 sha256
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
                     {"instruction": "x", "attachments": ["a.html"] * (hub.MAX_ATTACH + 1)}, {"instruction": 3}):
            self.assertEqual(self.h.call("dispatch", args), {"sent": False, "error": "E-04"}, args)
        self.assertEqual(self.h.call("nope", {}), {"error": "E-04"})

    def test_twenty_attachments(self):
        self.assertEqual(hub.MAX_ATTACH, 20)
        self.assertEqual(hub.TOOLS[0]["inputSchema"]["properties"]["attachments"]["maxItems"], 20)
        res = self.h.call("dispatch", {"instruction": "x", "attachments": ["a.html"] * 20})
        self.assertEqual(res, {"sent": True, "job": "J-0001"})
        self.assertEqual(self.worker.sent[0][2], ["a.html"] * 20)

    def test_preamble_is_spec_appendix_b(self):
        """일꾼 안내문 (hub.PREAMBLE) 은 SPEC 부록 B 의 글과 글자까지 같다 (가린 묶음 · restored/ 안내 포함)."""
        import re
        with open(os.path.join(ROOT, "docs", "SPEC.md"), encoding="utf-8") as f:
            spec = f.read()
        part = spec[spec.index("## 부록 B"):spec.index("## 부록 C")]
        block = re.search(r"```text\n(.*?)```", part, re.S).group(1)
        self.assertEqual(hub.PREAMBLE.replace("{{", "{").replace("}}", "}"), block)
        body = hub.PREAMBLE.format(job="J-0007", propose_cmd="P", instruction="I")
        self.assertIn('"job": "J-0007"', body)
        self.assertIn("restored/", body)

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

    # Windows 는 DISPLAY 가 없어도 진짜 확정 창이 뜬다 (CI 에서 600초 기다린 뒤에야 건너뛰었다) — 창을 띄우기 전에 건너뛴다
    @unittest.skipIf(os.name == "nt", "Windows 는 화면이 있다고 본다 - 진짜 확정 창이 뜨므로 시험하지 않는다")
    def test_headless_is_e07_and_temp_removed(self):
        home = os.path.join(self.tmp, "data")
        self.parts.confirm = hub.ProcessConfirm(home)
        saved = {k: os.environ.pop(k) for k in ("DISPLAY", "WAYLAND_DISPLAY") if k in os.environ}
        try:
            res = self.h.call("dispatch", {"instruction": "목록 화면을 만들어 달라"})
        finally:
            os.environ.update(saved)
        self.assertEqual(res, {"sent": False, "error": "E-07"})
        self.assertEqual(self.worker.sent, [])
        self.assertEqual(os.listdir(os.path.join(home, "tmp")), [])     # 요청 파일은 지운다

    def test_bundle_result_is_read_with_the_bundle_digest(self):
        """가린 묶음의 창 결과는 confirm.bundle_sha256 으로 맞춰 본다 (text 의 sha256 이 아니다) - 가짜 창 프로그램으로."""
        from diodelib import confirm
        fake = os.path.join(self.tmp, "fake_confirm.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write("import json, sys\nsys.path.insert(0, %r)\nfrom diodelib import confirm\n"
                    "req = json.load(open(sys.argv[2], encoding='utf-8'))\n"
                    "print(json.dumps({'decision': 'send', 'sha256': confirm.bundle_sha256(req['text'], req['files'])}))\n"
                    % ROOT)
        pc = hub.ProcessConfirm(os.path.join(self.tmp, "data"), diode_py=fake)
        files = [{"name": "F01.md", "type": "doc", "text": "PH_K7Q2 의 글\n"}]
        req = {"format": 1, "direction": "out", "job": "J-0001", "kind": "bundle", "transport": "room",
               "text": "# MANIFEST J-0001\n", "attachments": [], "files": files}
        self.assertEqual(pc(req), {"decision": "send", "sha256": confirm.bundle_sha256(req["text"], files)})
        self.assertEqual(hub.request_sha256(dict(req, kind="report")), confirm.text_sha256(req["text"]))
        text_only = json.dumps({"decision": "send", "sha256": confirm.text_sha256(req["text"])})
        self.assertEqual(confirm.parse_result(0, text_only, hub.request_sha256(req)), ("error", "E-20"))  # MANIFEST 만의 해시는 send 가 아니다

    def test_bad_output_is_not_send(self):
        from diodelib import confirm
        want = confirm.text_sha256("x")
        for code, out in ((0, ""), (0, '{"decision": "send", "sha256": "%s"}\n{}' % want),
                          (0, '{"decision": "send", "sha256": "%s"}' % ("0" * 64)), (3, '{"decision": "send", "sha256": "%s"}' % want)):
            self.assertNotEqual(confirm.parse_result(code, out, want)[0], "send", (code, out))
        self.assertEqual(confirm.parse_result(0, '{"decision": "send", "sha256": "%s"}' % want, want), ("send", None))


# ---------------------------------------------------------------- 가린 왕복 (SP-20) — 진짜 금고 (DIODE_HOME 자리 · 평문) · 합성 값만

# 합성 카나리아 - 결과 · 오류 · 감사 기록 · 대기열 · 방 어디에도 있으면 안 된다 (가린 바이트에는 토큰만)
K_WORD = "KITBUNDLEWORDQ"
K_IDENT = "kitBundleCalcQ"
K_NUMBER = "731337"
K_PATH = "kitsrc/kitbundle_secret_mod.py"
K_CANARIES = (K_WORD, K_IDENT, K_NUMBER, K_PATH, "kitbundle_secret_mod", "kitsrc")
O, C = "\u27e6", "\u27e7"


class Recording(object):
    """가짜 판정 - 받은 글을 남기고, block_at 번째 (0부터) 부름만 block."""

    def __init__(self, block_at=None):
        self.block_at, self.seen = block_at, []

    def __call__(self, text):
        self.seen.append(text)
        return {"verdict": "block" if len(self.seen) - 1 == self.block_at else "pass"}


class VaultBase(Base):
    def setUp(self):
        Base.setUp(self)
        from diodelib import audit, transport, vault
        self.vault_mod = vault
        self.home = os.path.join(self.tmp, "data")
        os.makedirs(self.home)
        with open(os.path.join(self.home, "dictionary.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "words": ["KITWORDALPHA"]}, f)
        self.project = vault.open_project(self.home, False)
        self.work = os.path.join(self.tmp, "opencode-work")        # 일꾼 (opencode) 의 작업 폴더
        os.makedirs(os.path.join(self.work, "kitsrc"))
        self.judge = Recording()
        self.parts.judge = self.judge
        self.parts.audit = audit.sink(self.home)
        self.parts.confirmed = lambda: audit.confirmed_hashes(self.home)
        self.parts.transport = transport.RoomTransport(self.room)
        self.parts.policy = lambda: scan.policy_from_home(self.home)
        self.parts.reserve = hub.file_reserver(self.home)
        self.parts.vault = lambda: vault.Vault.locked(self.home, False)

    def locked(self):
        return self.vault_mod.Vault.locked(self.home, False)

    def status(self):
        return self.vault_mod.project_status(self.home)

    def audit_texts(self):
        out = []
        for root, _, files in os.walk(os.path.join(self.home, "audit")):
            for fn in sorted(files):
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out

    def assertClean(self, *blobs):
        for b in blobs:
            dumped = b if isinstance(b, str) else json.dumps(b, ensure_ascii=False)
            for c in K_CANARIES + ("KITWORDALPHA",):
                self.assertNotIn(c, dumped)
                self.assertNotIn(c.lower(), dumped.lower())
            self.assertNotIn(self.tmp, dumped)

    def assertCleanEverywhere(self):
        """감사 기록 · 방 (outbox 포함) 의 모든 파일에 진짜 값 · 원래 이름이 없다 (합성 단어로 grep)."""
        for top in (os.path.join(self.home, "audit"), self.room):
            for root, _, files in os.walk(top):
                for fn in files:
                    self.assertClean(fn)
                    with open(os.path.join(root, fn), "rb") as f:
                        self.assertClean(f.read().decode("utf-8", "replace"))


class BundleOut(VaultBase):
    """propose bundle → 대기열 → take_bundle (다시 검사 · 확정 · outbox/<job>/ · 감사 기록) → inbox."""

    def source(self):
        with open(os.path.join(self.work, K_PATH), "w", encoding="utf-8", newline="\n") as f:
            f.write("def %si:%s%s():\n    return %sn:%s%s\n" % (O, K_IDENT, C, O, K_NUMBER, C))
        with open(os.path.join(self.work, "kitnotes.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("%s%s%s 의 계산을 고친다.\n" % (O, K_WORD, C))

    def propose(self, job=None, files=None):
        from diodelib import propose
        self.source()
        man = {"format": 1, "kind": "bundle", "note": "계산 함수를 고쳐 달라",
               "files": files or [{"path": K_PATH, "type": "code"}, {"path": "kitnotes.md", "type": "doc"}]}
        if job:
            man["job"] = job
        mp = os.path.join(self.work, "bundle.json")
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False)
        code, line = propose.main_propose(mp, home=self.home)
        self.assertEqual(code, 0, line)
        return json.loads(line)

    def queued(self):
        d = os.path.join(self.home, "queue")
        names = sorted(x for x in os.listdir(d) if x.endswith(".json"))
        self.assertEqual(len(names), 1)
        with open(os.path.join(d, names[0]), encoding="utf-8") as f:
            return names[0], json.load(f)

    def write_queue(self, draft, name="bundle-1.json"):
        d = os.path.join(self.home, "queue")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False)

    def test_jobless_bundle_gets_a_new_job_and_outbox_is_what_the_window_showed(self):
        self.assertEqual(self.propose(), {"queued": True, "bundle": True})
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        req = self.confirm.seen[-1]
        self.assertEqual((req["kind"], req["direction"], req["job"]), ("bundle", "out", "J-0001"))
        self.assertEqual(self.h.jobs[-1].state, "reported")
        folder = os.path.join(self.room, "outbox", "J-0001")
        self.assertEqual(sorted(os.listdir(folder)), ["F01.py", "F02.md", "MANIFEST.md"])
        for f in req["files"]:                                  # outbox 의 바이트 = 확정 창이 보인 바이트
            with open(os.path.join(folder, f["name"]), "rb") as fh:
                self.assertEqual(fh.read(), f["text"].encode("utf-8"))
        with open(os.path.join(folder, "MANIFEST.md"), "rb") as fh:
            self.assertEqual(fh.read(), req["text"].encode("utf-8"))
        self.assertEqual(req["stats"]["files"], 2)
        sent = [r for r in self.audit_texts() if r["direction"] == "out" and r["decision"] == "sent"]
        self.assertEqual(len(sent), len(req["files"]) + 1)      # 파일마다 + MANIFEST
        self.assertTrue(all(r["kind"] == "bundle" for r in sent))
        res = self.h.call("inbox", {})
        self.assertEqual(res["reports"], [{"job": "J-0001", "kind": "bundle", "files": [
            {"name": "MANIFEST.md", "type": "manifest", "bytes": len(req["text"].encode("utf-8"))},
            {"name": "F01.py", "type": "code", "bytes": len(req["files"][0]["text"].encode("utf-8"))},
            {"name": "F02.md", "type": "doc", "bytes": len(req["files"][1]["text"].encode("utf-8"))}]}])
        self.assertEqual(self.h.call("inbox", {"job": "J-0001"}), res)
        self.assertEqual(self.status()["sent_bytes"], sum(x["bytes"] for x in res["reports"][0]["files"]))
        self.assertClean(res, req["text"])
        self.assertCleanEverywhere()
        # 훅이 보는 확정 해시와 같다 - 방은 이 파일들만 Read 한다 (AL-13)
        from diodelib import audit, hook
        self.assertEqual(hook._confirmed_hashes(self.home), audit.confirmed_hashes(self.home))

    def test_bundle_with_job_answers_a_working_job_once(self):
        self.assertEqual(self.h.call("dispatch", {"instruction": "계산을 보내 달라"}), {"sent": True, "job": "J-0001"})
        self.assertEqual(self.propose(job="J-0001"), {"queued": True, "job": "J-0001"})
        self.assertTrue(self.queued()[0].startswith("J-0001-"))
        self.assertEqual(hub.poll_queue(self.h, self.home), 1)
        self.assertEqual(self.h.jobs[0].state, "reported")
        self.assertTrue(os.path.isdir(os.path.join(self.room, "outbox", "J-0001")))
        self.propose(job="J-0001")
        name, draft = self.queued()
        self.assertEqual(hub.poll_queue(self.h, self.home), 0)              # working 이 아닌 일의 묶음은 이 허브가 읽지 않는다
        self.assertEqual(self.h.take_bundle(draft), "unknown_job")

    def test_unconfirmed_bundle_folder_is_not_served(self):
        folder = os.path.join(self.room, "outbox", "J-0050")
        os.makedirs(folder)
        for name, text in (("F01.md", "몰래 쓴 글\n"), ("MANIFEST.md", "# MANIFEST J-0050\n")):
            with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        self.assertEqual(self.h.call("inbox", {})["reports"], [])
        from diodelib import audit
        audit.record(self.home, "J-0050", "out", "bundle", "room", "sent", text="몰래 쓴 글\n")   # 하나만 확정
        self.assertEqual(self.h.call("inbox", {})["reports"], [])
        self.assertEqual(self.h.call("inbox", {"job": "J-0050"}), {"error": "E-06"})

    def _forge(self, text, project=None, name="F01.md"):
        with self.locked() as v:
            tok = v.token_for(K_WORD, "word")
            v.file_name("kitnotes.md", "md")
        body = text.replace("{tok}", tok)
        return {"format": 1, "kind": "bundle", "project": project or self.project, "job": None, "note": "",
                "files": [{"name": name, "type": "doc", "text": body}],
                "stats": {"files": 1, "bytes": len(body.encode("utf-8")), "tokens": 1, "marked": 1, "auto": 0}}

    def test_forged_queue_files_are_checked_again(self):
        """대기열을 직접 쓴 꼼수 - 가리지 않은 바이트 · 다른 묶음 · 모르는 토큰 · 금고가 매기지 않은 이름 · 꼴."""
        cases = [
            (self._forge("{tok} 와 %s 를 그대로 쓴다\n" % K_WORD), "R2"),          # 금고 값이 그대로
            (self._forge("{tok} 와 KITWORDALPHA\n"), "R1"),                       # 사전 단어
            (self._forge("{tok} 의 값은 %s 이다\n" % K_NUMBER), "R4"),            # 가리지 않은 수
            (self._forge("{tok} 와 PH_ZZZZ\n"), "R6"),                            # 모르는 토큰
            (self._forge("{tok} 의 글\n", project="P-0002"), "E"),               # 다른 묶음
            (self._forge("{tok} 의 글\n", name="F09.md"), "E"),                  # 금고가 매기지 않은 이름
        ]
        for draft, check in cases:
            self.write_queue(draft)
            self.assertEqual(hub.poll_queue(self.h, self.home), 1)
            rec = self.audit_texts()[-1]
            self.assertEqual((rec["kind"], rec["decision"]), ("bundle", "blocked"))
            self.assertIn(check, [c["check"] for c in rec["checks"]], check)
        bad = self._forge("{tok} 의 글\n")
        for broken in (dict(bad, extra=1), dict(bad, format=2), dict(bad, files=[]),
                       dict(bad, stats=dict(bad["stats"], bytes=1)), dict(bad, project="P-1")):
            self.assertEqual(self.h.take_bundle(broken), "blocked")
        self.assertEqual(self.confirm.seen, [])                 # 창을 띄우지 않았다
        self.assertEqual(os.listdir(os.path.join(self.room, "outbox")), [])
        self.assertEqual(self.status()["sent_bytes"], 0)
        self.assertCleanEverywhere()

    def test_code_rules_follow_the_outgoing_name_not_the_claimed_type(self):
        """대기열이 type code 라고 적어도 설정 파일 이름 (F01.ini) 이면 doc 규칙 (bundle.check_type) - 호스트 꼴이 R3 에 걸린다."""
        with self.locked() as v:
            tok = v.token_for(K_WORD, "word")
            name = v.file_name("kitconf.ini", "ini")
        body = "[%s]\nhost = kitdb.example.corp\n" % tok
        draft = {"format": 1, "kind": "bundle", "project": self.project, "job": None, "note": "",
                 "files": [{"name": name, "type": "code", "text": body}],
                 "stats": {"files": 1, "bytes": len(body.encode("utf-8")), "tokens": 1, "marked": 1, "auto": 0}}
        self.assertEqual(self.h.take_bundle(draft), "blocked")
        self.assertIn("R3", [c["check"] for c in self.audit_texts()[-1]["checks"]])
        self.assertEqual(self.confirm.seen, [])

    def test_d7_blocks_if_one_chunk_blocks(self):
        line = "가나다 라마바 사아자 차카타 파하\n"
        big = line * (70 * 1024 // len(line.encode("utf-8")) * 2)       # 64 KiB 조각 셋
        draft = self._forge("{tok} " + big)
        self.assertGreater(len(draft["files"][0]["text"].encode("utf-8")), 2 * hub.D7_CHUNK_BYTES)
        chunks = hub.d7_chunks(draft["files"][0]["text"])
        self.assertEqual("".join(chunks), draft["files"][0]["text"])
        self.assertTrue(all(len(c.encode("utf-8")) <= hub.D7_CHUNK_BYTES for c in chunks))
        self.judge.block_at = 1
        self.assertEqual(self.h.take_bundle(draft), "blocked")
        self.assertEqual(len(self.judge.seen), 2)               # 두 번째 조각에서 멈춘다
        self.assertEqual(self.confirm.seen, [])
        self.judge.block_at, self.judge.seen = None, []
        self.assertEqual(self.h.take_bundle(draft), "sent")
        self.assertEqual(len(self.judge.seen), len(chunks))

    def test_file_chunks_use_the_bundle_prompt_and_note_the_report_prompt(self):
        """파일 조각은 judge_bundle (부록 A2) · note 한 줄은 judge (부록 A) 로 묻는다. judge_bundle 이 없으면 judge (더 엄격)."""
        asked = []
        self.parts.judge = lambda t: asked.append(("report", t)) or {"verdict": "pass"}
        self.parts.judge_bundle = lambda t: asked.append(("bundle", t)) or {"verdict": "pass"}
        draft = self._forge("{tok} 의 글\n")
        draft["note"] = "계산 함수를 고쳐 달라"
        self.assertEqual(self.h.take_bundle(draft), "sent")
        kinds = [k for k, _ in asked]
        self.assertEqual(kinds, ["bundle"] * len(draft["files"]) + ["report"])
        self.assertEqual(asked[-1][1], "계산 함수를 고쳐 달라")

    def test_human_discards_or_bytes_differ(self):
        draft = self._forge("{tok} 의 글\n")
        self.confirm.decision = "discard"
        self.assertEqual(self.h.take_bundle(draft), "rejected")
        self.confirm.decision, self.confirm.wrong_sha = "send", True
        self.assertEqual(self.h.take_bundle(draft), "rejected")
        self.assertEqual(os.listdir(os.path.join(self.room, "outbox")), [])
        self.assertEqual(self.status()["sent_bytes"], 0)
        self.assertEqual([r["decision"] for r in self.audit_texts()], ["discarded", "discarded"])

    def test_sent_bytes_limit_blocks_without_a_window(self):
        with self.locked() as v:
            v.add_sent(self.vault_mod.MAX_PROJECT_BYTES - 10)
        self.assertEqual(self.h.take_bundle(self._forge("{tok} 의 글\n")), "blocked")
        self.assertEqual(self.confirm.seen, [])
        self.assertEqual(self.audit_texts()[-1]["checks"], [{"check": "E", "code": "E-31"}])

    def test_halted_or_closed_project_blocks(self):
        draft = self._forge("{tok} 의 글\n")
        with self.locked() as v:
            v.halt()
        self.assertEqual(self.h.take_bundle(draft), "blocked")
        self.vault_mod.close_project(self.home)
        self.assertEqual(self.h.take_bundle(draft), "blocked")
        self.assertEqual(self.audit_texts()[-1]["checks"], [{"check": "E", "code": "E-33"}])
        self.assertEqual(self.confirm.seen, [])

    def test_no_vault_part_blocks(self):
        self.parts.vault = None
        self.assertEqual(self.h.take_bundle(self._forge("{tok} 의 글\n")), "blocked")


class DispatchReturn(VaultBase):
    """열린 묶음이 있을 때의 dispatch - U1 · U2 · U3 · 금고로 되돌리기 · restored/ · 고정된 결과."""

    def setUp(self):
        VaultBase.setUp(self)
        with self.locked() as v:
            self.t_ident = v.token_for(K_IDENT, "ident")
            self.t_num = v.token_for(K_NUMBER, "number")
            self.t_word = v.token_for(K_WORD, "word")
            self.t_path = v.token_for("kitdir/kitsub", "path")
            self.fname = v.file_name(K_PATH, "py")

    def put(self, name, text):
        with open(os.path.join(self.room, "work", name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def test_restored_attachment_goes_to_the_original_path(self):
        self.put(self.fname, "def %s():\n    return %s + 1\n" % (self.t_ident, self.t_num))
        res = self.h.call("dispatch", {"instruction": "%s 를 고쳤다 - 적용해 달라" % self.t_ident,
                                       "attachments": [self.fname]})
        self.assertEqual(res, {"sent": True, "job": "J-0001"})
        job, body, files = self.worker.sent[0]
        self.assertEqual(files, [(K_PATH, "def %s():\n    return %s + 1\n" % (K_IDENT, K_NUMBER))])
        self.assertIn(K_IDENT + " 를 고쳤다", body)
        req = self.confirm.seen[0]
        self.assertEqual(req["attachments"], [K_PATH])           # 창에는 되돌린 이름 (안쪽 PC)
        self.assertEqual(req["restored"], [{"name": K_PATH, "tokens": 2}])
        self.assertEqual(req["text"], K_IDENT + " 를 고쳤다 - 적용해 달라")
        rec = self.audit_texts()[-1]
        self.assertEqual((rec["direction"], rec["decision"]), ("dispatch", "sent"))
        self.assertIn(self.t_ident, rec["text"])                 # 감사 기록은 토큰 꼴 · 첨부는 해시도 없다
        self.assertClean(res, self.audit_texts())

    def test_real_worker_writes_restored_files_without_overwriting(self):
        from diodelib import worker
        self.parts.worker = worker.CommandWorker([sys.executable, "-c", "pass", "{prompt}"], self.home, self.room,
                                                 cwd=os.path.join(self.tmp, "inner"))
        self.put(self.fname, "x = %s\n" % self.t_num)
        for _ in range(2):
            self.assertTrue(self.h.call("dispatch", {"instruction": "적용", "attachments": [self.fname]})["sent"])
        base = os.path.join(self.tmp, "inner", "restored", "kitsrc")
        self.assertEqual(sorted(os.listdir(base)), ["kitbundle_secret_mod-2.py", "kitbundle_secret_mod.py"])
        with open(os.path.join(base, "kitbundle_secret_mod.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "x = %s\n" % K_NUMBER)

    def test_u1_and_u3_are_e04_before_the_window(self):
        self.put("a.md", "%s 와 PH_ZZZZ\n" % self.t_ident)
        self.put("b.md", "%s 와 ph_k7q\n" % self.t_ident)
        for args in ({"instruction": "적용", "attachments": ["a.md"]}, {"instruction": "적용", "attachments": ["b.md"]},
                     {"instruction": "PH_ZZZZ 를 적용"}, {"instruction": "https://kit.example.com 을 보라"}):
            self.assertEqual(self.h.call("dispatch", args), {"sent": False, "error": "E-04"}, args)
        self.assertEqual(self.confirm.seen, [])
        self.assertFalse(self.status()["halted"])

    def test_u2_halts_and_shows_a_window_that_cannot_send(self):
        for args in ({"instruction": "%s 를 적용" % K_WORD},
                     {"instruction": "적용", "attachments": ["c.md"]}):
            self.put("c.md", "값은 %s 이고 이름은 %s 다\n" % (K_NUMBER, self.t_ident))
            self.confirm.seen = []
            self.confirm.decision = "send"                       # 사람이 무엇을 눌러도 넘기지 않는다
            res = self.h.call("dispatch", args)
            self.assertEqual(res, {"sent": False, "error": "E-02"})        # 사람이 거절한 것과 같은 답
            req = self.confirm.seen[0]
            self.assertFalse(req["checks"]["ok"])
            self.assertEqual(req["checks"]["hits"][0]["check"], "U2")
            self.assertNotIn("restored", req)
            self.assertTrue(self.status()["halted"])
            self.assertEqual(self.worker.sent, [])
            with self.locked() as v:
                v._resume()
        self.confirm.decision = "timeout"
        self.put("c.md", "%s\n" % K_IDENT)
        self.assertEqual(self.h.call("dispatch", {"instruction": "적용", "attachments": ["c.md"]}),
                         {"sent": False, "error": "E-03"})       # 시간 초과도 보통 넘기기와 같은 답
        self.assertFalse(os.path.exists(os.path.join(self.home, "work")))     # 되돌린 파일이 없다
        self.assertEqual([r["decision"] for r in self.audit_texts()], ["blocked"] * 3)
        self.assertClean(self.audit_texts())

    def test_halted_vault_blocks_dispatches_that_use_it(self):
        with self.locked() as v:
            v.halt()
        self.put(self.fname, "x = 1\n")
        for args in ({"instruction": "%s 를 적용" % self.t_ident}, {"instruction": "적용", "attachments": [self.fname]}):
            self.confirm.seen = []
            self.assertEqual(self.h.call("dispatch", args), {"sent": False, "error": "E-02"})
            self.assertFalse(self.confirm.seen[0]["checks"]["ok"])
        self.assertEqual(self.worker.sent, [])
        self.assertEqual(self.h.call("dispatch", {"instruction": "목록을 정리해 달라"})["sent"], True)  # 금고를 안 쓰면 그대로

    def test_unusable_restored_names_fall_back_to_token_names(self):
        """되돌린 이름에 경로 글자가 생기면 오류 대신 토큰 꼴 이름 그대로 - 결과로 가린 값을 짐작하지 못하게 (oracle 없음)."""
        self.put("%s.md" % self.t_path, "글\n")                  # 되돌리면 kitdir/kitsub.md - 경로 글자가 생긴다
        with self.locked() as v:
            dots = v.token_for("..", "word")
        self.put("%s.md" % dots, "글\n")                         # 되돌리면 ...md
        for name in ("%s.md" % self.t_path, "%s.md" % dots):
            self.worker.sent = []
            self.assertEqual(self.h.call("dispatch", {"instruction": "적용", "attachments": [name]})["sent"], True)
            self.assertEqual([n for n, _ in self.worker.sent[0][2]], [name])

    def test_colliding_restored_names_fall_back_together(self):
        """PH_A.txt 와 k.txt (PH_A = k · 한 글자라 U2 밖) 를 함께 보내도 E-04 가 아니다 - 겹치면 모두 토큰 꼴 이름 (어느 것이 겹쳤는지 숨김)."""
        with self.locked() as v:
            tok = v.token_for("k", "word")
        self.put("%s.txt" % tok, "글\n")
        self.put("k.txt", "글\n")
        att = ["%s.txt" % tok, "k.txt"]
        self.assertEqual(self.h.call("dispatch", {"instruction": "적용", "attachments": att})["sent"], True)
        self.assertEqual([n for n, _ in self.worker.sent[0][2]], att)

    def test_real_value_in_attachment_name_is_u2(self):
        """Claude 가 첨부 이름에 금고의 진짜 값을 쓰면 U2 - 멈추고 막힌 창 · Claude 에게는 E-02."""
        with self.locked() as v:
            v.token_for("kitname", "word")
        self.put("kitname.txt", "글\n")
        self.assertEqual(self.h.call("dispatch", {"instruction": "적용", "attachments": ["kitname.txt"]}),
                         {"sent": False, "error": "E-02"})
        self.assertFalse(self.confirm.seen[-1]["checks"]["ok"])
        self.assertEqual(self.worker.sent, [])
        with self.locked() as v:
            self.assertTrue(v.halted)

    def test_no_open_project_keeps_the_session_table_path(self):
        self.vault_mod.close_project(self.home)
        self.put("a.md", "PH_ZZZZ 그대로\n")
        self.assertEqual(self.h.call("dispatch", {"instruction": "적용", "attachments": ["a.md"]}),
                         {"sent": True, "job": "J-0001"})
        self.assertEqual(self.worker.sent[0][2], ["a.md"])         # 이름 그대로 (복사) · 되돌리기 없음
        self.assertNotIn("restored", self.confirm.seen[0])

    def test_broken_vault_is_e20(self):
        with open(self.vault_mod.vault_path(self.home, self.project), "wb") as f:
            f.write(b"broken")
        self.assertEqual(self.h.call("dispatch", {"instruction": "적용"}), {"sent": False, "error": "E-20"})
        self.assertEqual(self.confirm.seen, [])


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
