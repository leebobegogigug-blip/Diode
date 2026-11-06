# -*- coding: utf-8 -*-
"""데이터 폴더의 사전 · 설정 읽고 쓰기 (diodelib.config). 합성 자료만."""

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

from diodelib import config, scan  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-config-"))
        self.home = os.path.join(self.tmp, "data")
        self.raw = os.path.join(self.tmp, "kitraw")
        os.makedirs(self.raw)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, **kw):
        st = {"words": ["KITWORDALPHA", "가람소재"], "raw_dirs": [self.raw], "inner_tools": ["InnerX"],
              "lib_allow": ["pandas"], "patterns": ["(?i)kitlot-[a-z]+"], "web_search": True, "real_data": False,
              "monthly_budget_usd": 100, "worker_command": ["opencode", "run", "--dir", "{cwd}", "{prompt}"],
              "worker_cwd": None, "room_path": os.path.join(self.tmp, "room"), "llm": None}
        st.update(kw)
        return st


class RoundTrip(Base):
    def test_first_run_is_empty_defaults(self):
        st = config.load_state(self.home)
        self.assertEqual((st["words"], st["raw_dirs"], st["worker_command"]), ([], [], None))
        self.assertTrue(st["web_search"])
        self.assertFalse(st["real_data"])
        self.assertEqual(config.ready(self.home), (False, ["words_empty", "raw_empty"]))

    def test_apply_and_read_back(self):
        counts, warn = config.apply_state(self.home, self.state())
        self.assertEqual(warn, [])
        self.assertEqual((counts["dictionary"], counts["raw_dirs"], counts["worker"]), (2, 1, True))
        self.assertEqual(config.ready(self.home), (True, []))
        st = config.load_state(self.home)
        self.assertEqual(st["inner_tools"], ["innerx"])                      # 소문자로
        self.assertEqual(st["worker_command"][:2], ["opencode", "run"])
        # 훅 · 검사기가 읽는다
        p = scan.policy_from_home(self.home)
        self.assertEqual(scan.check_text("kit-word alpha", p, ("D2",))["hits"][0]["check"], "D2")
        self.assertEqual(scan.check_text("KITLOT-abc", p, ("D3",))["hits"][0]["check"], "D3")

    def test_counts_have_no_words_or_paths(self):
        config.apply_state(self.home, self.state())
        dumped = json.dumps(config.counts(self.home), ensure_ascii=False)
        for w in ("KITWORD", "가람", "kitraw", "innerx", "opencode"):
            self.assertNotIn(w, dumped)

    def test_unknown_keys_kept(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "llm": {"base_url": "http://127.0.0.1:1/v1"}, "transport": {"default": "room"},
                       "policy": {"daily_cap": 7}}, f)
        config.apply_state(self.home, self.state(llm=None))
        cfg = config.read_config(self.home)
        self.assertEqual(cfg["transport"], {"default": "room"})
        self.assertEqual(cfg["policy"]["daily_cap"], 7)
        self.assertEqual(cfg["llm"]["base_url"], "http://127.0.0.1:1/v1")

    def test_empty_worker_removes_keys(self):
        config.apply_state(self.home, self.state())
        config.apply_state(self.home, self.state(worker_command=None))
        self.assertNotIn("worker", config.read_config(self.home))

    def test_atomic_no_temp_left(self):
        config.apply_state(self.home, self.state())
        self.assertEqual(sorted(os.listdir(self.home)), ["config.json", "dictionary.json"])


class Validation(Base):
    def test_words_cleaning(self):
        clean, warn = config.validate_state(self.state(words=["  가람   소재 ", "가람 소재", "KITWORDALPHA", "kit-word alpha", "a", "", "-"]))
        self.assertEqual(clean["words"], ["가람 소재", "KITWORDALPHA"])        # 공백 정리 · 같은 N(w) 는 하나 · 한 글자는 뺌
        self.assertIn("short", warn)

    def test_warnings(self):
        _, warn = config.validate_state(self.state(words=[], raw_dirs=[]))
        self.assertEqual(warn, ["raw_empty", "words_empty"])
        _, warn = config.validate_state(self.state(raw_dirs=[os.path.join(self.tmp, "없는폴더")]))
        self.assertEqual(warn, ["raw_missing"])

    def test_bad_values(self):
        for key, bad in (("raw_dirs", ["상대/경로"]), ("raw_dirs", "문자열"), ("patterns", ["("]), ("lib_allow", ["bad name"]),
                         ("web_search", "yes"), ("real_data", 1), ("monthly_budget_usd", -1), ("monthly_budget_usd", True),
                         ("worker_command", "opencode run"), ("worker_command", ["a", "{prompt}", "{prompt}"]),
                         ("worker_cwd", ""), ("room_path", "room"), ("words", "단어"), ("words", [3]),
                         ("words", ["가" * 81]), ("llm", ["x"]), ("inner_tools", [3])):
            with self.assertRaises(config.ConfigError, msg=key):
                config.validate_state(self.state(**{key: bad}))
        with self.assertRaises(config.ConfigError):
            config.validate_state(self.state(worker_command=None, worker_cwd="/x"))
        with self.assertRaises(config.ConfigError):
            config.validate_state("x")

    def test_error_has_code_only(self):
        try:
            config.validate_state(self.state(raw_dirs=["상대/KITWORDALPHA"]))
        except config.ConfigError as e:
            self.assertEqual(e.code, "raw_dirs")
            self.assertNotIn("KITWORD", str(e))

    def test_llm_checked_by_judge_settings(self):
        with self.assertRaises(config.ConfigError):
            config.validate_state(self.state(llm={"base_url": "http://127.0.0.1:1/v1", "model": "m",
                                                  "api_key": "{env:SOME_KEY}"}))          # {env:} 는 받지 않는다 (D7)
        with self.assertRaises(config.ConfigError):
            config.validate_state(self.state(llm={"base_url": "ftp://x/v1", "model": "m"}))
        clean, _ = config.validate_state(self.state(llm={"base_url": "http://127.0.0.1:1/v1", "model": "m"}))
        self.assertEqual(clean["llm"]["model"], "m")


class Damaged(Base):
    def test_broken_config_is_set_aside(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        self.assertEqual(config.counts(self.home), {"error": "broken"})
        config.apply_state(self.home, self.state())
        self.assertTrue(os.path.exists(config.config_path(self.home) + ".broken"))
        self.assertEqual(config.counts(self.home)["dictionary"], 2)

    def test_newer_format_is_read_only(self):
        os.makedirs(self.home)
        with open(config.config_path(self.home), "w") as f:
            json.dump({"format": 2}, f)
        self.assertEqual(config.counts(self.home), {"error": "newer"})
        with self.assertRaises(config.ConfigError) as cm:
            config.apply_state(self.home, self.state())
        self.assertEqual(cm.exception.code, "newer")
        with open(config.config_path(self.home)) as f:
            self.assertEqual(json.load(f), {"format": 2})                              # 그대로

    def test_newer_dictionary_is_not_overwritten(self):
        os.makedirs(self.home)
        with open(config.dictionary_path(self.home), "w") as f:
            json.dump({"format": 2, "words": ["x"]}, f)
        with self.assertRaises(config.ConfigError):
            config.apply_state(self.home, self.state())

    def test_tolerant_load_keeps_the_intact_file(self):
        # 사전만 깨짐 → 설정의 값은 살린다 · 설정만 깨짐 → 사전은 살린다 (저장할 때 멀쩡한 파일을 빈 값으로 덮지 않게)
        config.apply_state(self.home, self.state())
        with open(config.dictionary_path(self.home), "w") as f:
            f.write("[]")
        st, broken = config.load_state_tolerant(self.home)
        self.assertEqual((broken, st["words"], len(st["raw_dirs"]), st["worker_command"][:2]),
                         (["dictionary"], [], 1, ["opencode", "run"]))
        config.apply_state(self.home, st)                                       # 저장해도 설정의 정책 값이 그대로
        self.assertEqual(config.counts(self.home)["raw_dirs"], 1)
        self.assertTrue(config.counts(self.home)["worker"])

        config.apply_state(self.home, self.state())
        with open(config.config_path(self.home), "w") as f:
            f.write("{")
        st, broken = config.load_state_tolerant(self.home)
        self.assertEqual((broken, len(st["words"]), st["raw_dirs"]), (["config"], 2, []))

    def test_tolerant_load_both_broken_and_newer(self):
        os.makedirs(self.home)
        for p in (config.config_path(self.home), config.dictionary_path(self.home)):
            with open(p, "w") as f:
                f.write("{")
        st, broken = config.load_state_tolerant(self.home)
        self.assertEqual((sorted(broken), st["words"]), (["config", "dictionary"], []))
        with open(config.config_path(self.home), "w") as f:
            json.dump({"format": 2}, f)
        with self.assertRaises(config.ConfigError) as cm:
            config.load_state_tolerant(self.home)
        self.assertEqual(cm.exception.code, "newer")

    def test_broken_dictionary_is_set_aside(self):
        os.makedirs(self.home)
        with open(config.dictionary_path(self.home), "w") as f:
            f.write("[]")
        config.apply_state(self.home, self.state())
        self.assertTrue(os.path.exists(config.dictionary_path(self.home) + ".broken"))


if __name__ == "__main__":
    unittest.main()
