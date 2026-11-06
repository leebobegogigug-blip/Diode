# -*- coding: utf-8 -*-
"""상태 명령 (SP-12 · 지침 04-5 계약) · statusline (SP-13). 임시 폴더 · 합성 단어만."""

import builtins
import datetime
import hashlib
import io
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

from diodelib import audit, status  # noqa: E402

WORD = "KITWORDALPHA"
SEALED = "[diode report format=1 job=J-0007 status=done]\nSUMMARY:\n- CANARYSEALEDTEXT\n[/diode report]\n"
ANSWER = "CANARYANSWERTEXT"
PATTERN = "CANARYPATTERN[0-9]+"
JUDGE_MODEL = "fake-judge-model-x"
PLAN_MODEL = "fake-plan-model-y"
SESSION_MODEL = "fake-session-model-z"
ROOM_SETTINGS = {"autoMemoryEnabled": False, "permissions": {"defaultMode": "default", "deny": ["Bash", "WebFetch"]}}

# 지침 04-5 의 예시 (계약) — 꼴 시험의 기준
CONTRACT_EXAMPLE = {
    "format": 1,
    "tool": "diode",
    "room": {"is_room": True, "profile": "ok"},
    "seatbelt": "on",
    "worker": {"set": True, "reachable": True},
    "queue": {"confirm": 0, "outbox": 0, "inbox": 0},
    "jobs": [{"job": "J-0007", "state": "working"}],
    "month": {"pct": 12, "estimated": False},
    "last": {"effort": "high"},
}


def contract_errors(obj):
    """지침 04-5 의 판정 (Terminal-1 이 읽는 쪽) — 필수 칸 · 값 범위. 틀린 곳의 목록."""
    errs = []
    if not isinstance(obj, dict) or obj.get("format") != 1:
        return ["format"]
    room = obj.get("room")
    if not isinstance(room, dict) or not isinstance(room.get("is_room"), bool):
        errs.append("room.is_room")
    if not isinstance(room, dict) or room.get("profile") not in ("ok", "missing", "changed"):
        errs.append("room.profile")
    if obj.get("seatbelt") not in ("on", "off", "unknown"):
        errs.append("seatbelt")
    for j in obj.get("jobs", []):
        if j.get("state") not in ("sent", "working", "reported", "rejected"):
            errs.append("jobs.state")
    if "month" in obj:
        m = obj["month"]
        if not (isinstance(m.get("pct"), int) and 0 <= m["pct"] <= 999) or not isinstance(m.get("estimated"), bool):
            errs.append("month")
    if "last" in obj and obj["last"].get("effort") not in ("low", "medium", "high", "xhigh", "max", "auto"):
        errs.append("last.effort")
    if "worker" in obj:
        w = obj["worker"]
        if not isinstance(w.get("set"), bool) or not isinstance(w.get("reachable"), bool):
            errs.append("worker")
    if "queue" in obj:
        for k in ("confirm", "outbox", "inbox"):
            v = obj["queue"].get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errs.append("queue." + k)
    return errs


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


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diode-status-")
        self.home = os.path.join(self.tmp, "home")
        self.room = os.path.join(self.tmp, "room")
        self.raw = os.path.join(self.tmp, "raw")
        os.makedirs(self.raw)
        make_room(self.room)
        write_json(os.path.join(self.home, "dictionary.json"), {"format": 1, "words": [WORD]})
        self.cfg = {"format": 1, "llm": {"base_url": "http://judge.example.local/v1", "model": JUDGE_MODEL},
                    "claude": {"model_plan": PLAN_MODEL, "monthly_budget_usd": 50},
                    "worker": {"url": "http://127.0.0.1:4096"},
                    "policy": {"raw_dirs": [self.raw], "patterns": [PATTERN]}}
        write_json(os.path.join(self.home, "config.json"), self.cfg)
        self.env = mock.patch.dict(os.environ, {"DIODE_WORKER_URL": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def status(self, argv=None, probe=lambda port: True, home_is_default=True):
        out, err = io.StringIO(), io.StringIO()
        code = status.main_status(argv if argv is not None else ["--status", "--json", "--room", self.room], out,
                                  home=self.home, home_is_default=home_is_default, probe=probe, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_contract_example_passes_checker(self):
        self.assertEqual(contract_errors(CONTRACT_EXAMPLE), [])

    def test_shape_matches_contract(self):
        code, out, _ = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("\n"))
        self.assertEqual(out.count("\n"), 1)
        obj = json.loads(out)
        self.assertEqual(contract_errors(obj), [])
        # 계약 예시의 칸이 모두 있고 같은 꼴이다
        for k, v in CONTRACT_EXAMPLE.items():
            if k in ("month", "last"):
                continue
            self.assertIn(k, obj)
            self.assertEqual(type(obj[k]), type(v), k)
            if isinstance(v, dict):
                self.assertEqual(set(obj[k]), set(v), k)
        self.assertEqual(obj["room"], {"is_room": True, "profile": "ok"})
        self.assertEqual(obj["seatbelt"], "on")
        self.assertEqual(obj["worker"], {"set": True, "reachable": True})
        self.assertEqual(obj["month"], {"pct": 0, "estimated": True})    # statusline 기록이 아직 없다

    def test_full_state(self):
        now = datetime.datetime.now().astimezone().replace(microsecond=0)
        audit.record(self.home, "J-0007", "dispatch", "instruction", "worker", "sent",
                     text="지시 CANARYINSTRUCTION", now=now)
        audit.record(self.home, "J-0008", "dispatch", "instruction", "worker", "sent", text="지시", now=now)
        audit.record(self.home, "J-0008", "out", "report", "room", "sent", text=SEALED,
                     model=PLAN_MODEL, effort="high", now=now)
        with open(os.path.join(self.room, "outbox", "J-0008.md"), "w", encoding="utf-8") as f:
            f.write(SEALED)
        with open(os.path.join(self.room, "outbox", "J-0009.md"), "w", encoding="utf-8") as f:
            f.write(SEALED)
        with open(os.path.join(self.room, "inbox", "J-0008.md"), "w", encoding="utf-8") as f:
            f.write(ANSWER)
        fields = status.read_statusline(json.dumps({
            "session_id": "fake-session-1", "model": {"id": SESSION_MODEL}, "effort": {"level": "xhigh"},
            "cost": {"total_cost_usd": 6.0},
            "context_window": {"total_input_tokens": 10, "total_output_tokens": 5}}).encode("utf-8"))
        status.record_usage(self.home, fields)
        code, out, _ = self.status()
        obj = json.loads(out)
        self.assertEqual(contract_errors(obj), [])
        self.assertEqual(obj["jobs"], [{"job": "J-0007", "state": "working"}, {"job": "J-0008", "state": "reported"}])
        self.assertEqual(obj["queue"], {"confirm": 0, "outbox": 1, "inbox": 1})
        self.assertEqual(obj["month"], {"pct": 12, "estimated": False})
        self.assertEqual(obj["last"], {"effort": "xhigh"})
        # 내주지 않는 것 (SP-12)
        for bad in (WORD, "CANARYSEALEDTEXT", ANSWER, "CANARYINSTRUCTION", PATTERN, "CANARYPATTERN",
                    JUDGE_MODEL, PLAN_MODEL, SESSION_MODEL, "PH_", "judge.example.local", self.raw, "sha256",
                    "fake-session-1"):
            self.assertNotIn(bad, out, bad)

    def test_room_states(self):
        code, out, _ = self.status(["--json", "--room", os.path.join(self.tmp, "nowhere")])
        self.assertEqual(json.loads(out)["room"], {"is_room": False, "profile": "missing"})
        self.assertEqual(json.loads(out)["queue"], {"confirm": 0, "outbox": 0, "inbox": 0})
        write_json(os.path.join(self.room, ".claude", "settings.json"), {"changed": True})
        code, out, _ = self.status()
        self.assertEqual(json.loads(out)["room"], {"is_room": True, "profile": "changed"})

    def test_room_inside_raw_is_changed(self):
        inner = os.path.join(self.raw, "room")
        make_room(inner)
        code, out, _ = self.status(["--json", "--room", inner])
        self.assertEqual(json.loads(out)["room"]["profile"], "changed")

    def test_seatbelt_values(self):
        self.assertEqual(json.loads(self.status(home_is_default=False)[1])["seatbelt"], "unknown")
        cfg = dict(self.cfg)
        cfg["policy"] = {"raw_dirs": []}
        write_json(os.path.join(self.home, "config.json"), cfg)
        self.assertEqual(json.loads(self.status()[1])["seatbelt"], "off")
        with open(os.path.join(self.home, "config.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        obj = json.loads(self.status()[1])
        self.assertEqual(obj["seatbelt"], "unknown")
        self.assertNotIn("month", obj)
        self.assertEqual(contract_errors(obj), [])
        shutil.rmtree(self.home)
        self.assertEqual(json.loads(self.status()[1])["seatbelt"], "off")      # 처음 설치 (unset)

    def test_worker(self):
        self.assertEqual(json.loads(self.status(probe=lambda p: False)[1])["worker"], {"set": True, "reachable": False})

        def boom(p):
            raise OSError("no")
        self.assertEqual(json.loads(self.status(probe=boom)[1])["worker"]["reachable"], False)
        with mock.patch.dict(os.environ, {"DIODE_WORKER_URL": "http://worker.example.com:4096"}):
            self.assertEqual(json.loads(self.status()[1])["worker"], {"set": False, "reachable": False})

    def test_no_budget_no_month(self):
        cfg = dict(self.cfg)
        cfg["claude"] = {"monthly_budget_usd": 0}
        write_json(os.path.join(self.home, "config.json"), cfg)
        self.assertNotIn("month", json.loads(self.status()[1]))

    def test_usage_errors(self):
        for argv in (["--status"], ["--json", "--room"], ["--json", "--bogus"], ["--json", "--json"],
                     ["--json", "--room", self.room, "--room", self.room]):
            code, out, err = self.status(argv)
            self.assertEqual(code, 2, argv)
            self.assertEqual(out, "")

    def test_failure_writes_no_json(self):
        with mock.patch.object(status, "build_status", side_effect=RuntimeError("boom")):
            code, out, err = self.status()
        self.assertEqual((code, out), (1, ""))
        self.assertNotIn("boom", err)

    def test_read_only(self):
        before = sorted(os.path.join(r, f) for r, _, fs in os.walk(self.tmp) for f in fs)
        self.status()
        after = sorted(os.path.join(r, f) for r, _, fs in os.walk(self.tmp) for f in fs)
        self.assertEqual(before, after)


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diode-statusline-")
        self.home = os.path.join(self.tmp, "home")
        self.room = os.path.join(self.tmp, "room")
        make_room(self.room)
        write_json(os.path.join(self.home, "config.json"), {"format": 1, "claude": {"monthly_budget_usd": 50}})
        self.transcript = os.path.join(self.tmp, "transcript.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write("{}\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, **kw):
        d = {"session_id": "fake-session-2", "transcript_path": self.transcript, "cwd": self.tmp,
             "model": {"id": SESSION_MODEL, "display_name": "Fake"}, "effort": {"level": "high"},
             "cost": {"total_cost_usd": 6.0},
             "context_window": {"total_input_tokens": 1000, "total_output_tokens": 200}}
        d.update(kw)
        return json.dumps(d).encode("utf-8")

    def run_line(self, data):
        out = io.StringIO()
        code = status.main_statusline(data, out, self.home, room_dir=self.room)
        return code, out.getvalue()

    def usage_files(self):
        d = os.path.join(self.home, "usage")
        return sorted(os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs)

    def test_line_and_record(self):
        code, out = self.run_line(self.payload())
        self.assertEqual(code, 0)
        self.assertEqual(out, "DIODE  room ok  effort high  month 12%\n")
        files = self.usage_files()
        self.assertEqual(len(files), 1)
        month = datetime.datetime.now().strftime("%Y-%m")
        want = hashlib.sha256(b"fake-session-2").hexdigest()[:16] + ".json"
        self.assertEqual(files[0], os.path.join(self.home, "usage", month, want))
        with open(files[0], encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual(set(rec), {"format", "at", "month", "model", "effort", "cost_usd", "input_tokens",
                                    "output_tokens"})
        self.assertEqual((rec["cost_usd"], rec["input_tokens"], rec["output_tokens"]), (6.0, 1000, 200))
        self.assertNotIn(self.transcript, json.dumps(rec))
        self.assertNotIn("fake-session-2", json.dumps(rec))
        self.assertNotIn(SESSION_MODEL, out)

    def test_overwrites_same_session_and_sums_month(self):
        self.run_line(self.payload())
        self.run_line(self.payload(cost={"total_cost_usd": 10.0}))
        self.assertEqual(len(self.usage_files()), 1)
        code, out = self.run_line(self.payload(session_id="fake-session-3", cost={"total_cost_usd": 5.0}))
        self.assertEqual(out, "DIODE  room ok  effort high  month 30%\n")
        self.assertEqual(len(self.usage_files()), 2)
        self.assertFalse([f for f in self.usage_files() if f.endswith(".tmp")])

    def test_newer_format_not_overwritten(self):
        self.run_line(self.payload())
        p = self.usage_files()[0]
        write_json(p, {"format": 2, "cost_usd": 1})
        self.run_line(self.payload(cost={"total_cost_usd": 9.0}))
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["format"], 2)

    def test_transcript_never_opened(self):
        opened = []
        real_open = builtins.open
        real_os_open = os.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real_open(path, *a, **k)

        def spy_os(path, *a, **k):
            opened.append(str(path))
            return real_os_open(path, *a, **k)
        with mock.patch("builtins.open", spy), mock.patch("os.open", spy_os), mock.patch("io.open", spy):
            code, out = self.run_line(self.payload())
        self.assertEqual(code, 0)
        self.assertTrue(opened)                         # 무엇이든 열었다 (설정 · 방)
        self.assertFalse([p for p in opened if os.path.basename(p) == "transcript.jsonl"])

    def test_no_budget_no_month(self):
        write_json(os.path.join(self.home, "config.json"), {"format": 1, "claude": {"monthly_budget_usd": 0}})
        self.assertEqual(self.run_line(self.payload())[1], "DIODE  room ok  effort high\n")
        os.remove(os.path.join(self.home, "config.json"))
        self.assertEqual(self.run_line(self.payload())[1], "DIODE  room ok  effort high\n")

    def test_unknown_values(self):
        code, out = self.run_line(self.payload(effort={"level": "turbo"}, cost={"total_cost_usd": "lots"}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "DIODE  room ok  effort -  month 0%\n")
        code, out = self.run_line(json.dumps({"effort": {"level": "low"}}).encode("utf-8"))
        self.assertEqual(out, "DIODE  room ok  effort low  month 0%\n")

    def test_room_missing(self):
        out = io.StringIO()
        status.main_statusline(self.payload(), out, self.home, room_dir=os.path.join(self.tmp, "nowhere"))
        self.assertTrue(out.getvalue().startswith("DIODE  room missing  effort high"))

    def test_broken_input_still_zero(self):
        for data in (b"", b"not json", b"[1, 2]", b"\xff\xfe\x00", b"null", b"{" * 100000,
                     b"x" * (status.MAX_STDIN + 1), None, "문자열"):
            code, out = self.run_line(data)
            self.assertEqual(code, 0, data[:10] if data else data)
            self.assertEqual(out, "DIODE  -\n")
        self.assertEqual(self.usage_files(), [])

    def test_unwritable_home_still_line(self):
        bad_home = os.path.join(self.tmp, "file-not-dir")
        with open(bad_home, "w") as f:
            f.write("x")
        out = io.StringIO()
        code = status.main_statusline(self.payload(), out, bad_home, room_dir=self.room)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().count("\n"), 1)
        self.assertTrue(out.getvalue().startswith("DIODE  room ok"))

    def test_fast(self):
        t0 = time.time()
        for _ in range(5):
            self.run_line(self.payload())
        self.assertLess((time.time() - t0) / 5, 1.0)     # SP-13 의 200 ms 는 [제안] — 시험은 넉넉히


if __name__ == "__main__":
    unittest.main()
