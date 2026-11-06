# -*- coding: utf-8 -*-
"""사내 질문지 (kit/inhouse-questions.md) · statusLine 칸 이름 도구 (kit/statusline_keys.py).

질문지는 사내 Claude 의 답이 바깥으로 옮겨지는 길이다 — 질문 번호 · 답 양식이 어긋나지 않고, 판정 프롬프트가 SPEC 부록 A 와
같고, 이름 · 주소를 묻지 않으며, 칸 이름 도구가 값을 찍지 않는지 지킨다.
"""

import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "kit"))

import statusline_keys  # noqa: E402


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


QUESTIONS = read("kit/inhouse-questions.md")


def block(after_heading, open_fence, close_fence):
    """제목 뒤의 첫 울타리 블록 안의 글."""
    i = QUESTIONS.index(after_heading)
    start = QUESTIONS.index(open_fence, i) + len(open_fence)
    end = QUESTIONS.index(close_fence, start)
    return QUESTIONS[start:end].strip("\n")


PASTE = block("## 1부", "````text", "\n````")
SAMPLE = block("### 답 양식", "```text", "\n```")


class Structure(unittest.TestCase):
    def test_question_numbers_are_contiguous(self):
        nums = [int(m.group(1)) for m in re.finditer(r"^Q(\d\d) ", PASTE, re.M)]
        self.assertEqual(nums, list(range(1, len(nums) + 1)))
        self.assertGreaterEqual(len(nums), 30)

    def test_sample_answers_match_the_questions(self):
        q = [int(m.group(1)) for m in re.finditer(r"^Q(\d\d) ", PASTE, re.M)]
        a = [int(m.group(1)) for m in re.finditer(r"^Q(\d\d)=", SAMPLE, re.M)]
        self.assertEqual(q, a)
        self.assertEqual(SAMPLE.splitlines()[-1], "점검=금지 항목 없음")
        for line in SAMPLE.splitlines():
            self.assertLess(len(line), 90, line)                       # 옮겨 적기 좋게 한 줄에 짧게

    def test_rules_are_in_the_paste_block(self):
        for needle in ("읽기만 한다", "금지", "점검=금지 항목 없음", "모르면 `?`", "이름", "주소", "경로", "키"):
            self.assertIn(needle, PASTE)

    def test_the_questions_do_not_ask_for_names_or_addresses(self):
        # 질문 줄에는 "이름은 쓰지 않는다" 류의 금지만 있고, 이름 · 주소 · 경로 · 키 그 자체를 요구하는 말이 없다
        asks = [l for l in PASTE.splitlines() if re.match(r"^Q\d\d ", l)]
        for l in asks:
            for bad in ("주소를", "경로를", "키를", "이름을 적", "URL", "토큰을", "모델 이름", "api_key", "base_url"):
                self.assertNotIn(bad, l)

    def test_exceptions_to_read_only_are_only_the_write_tests(self):
        self.assertIn("Q08 · Q09 만 예외", PASTE)
        writers = [l.split()[0] for l in PASTE.splitlines() if re.match(r"^Q\d\d ", l) and "만들고 지울" in l]
        self.assertEqual(writers, ["Q08", "Q09"])

    def test_no_ip_or_secret_shaped_text(self):
        ips = [m.group(0) for m in re.finditer(r"\b\d{1,3}(\.\d{1,3}){3}\b", QUESTIONS)]
        self.assertEqual([i for i in ips if i != "127.0.0.1"], [])              # 루프백만 (Q26 의 보기)
        self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{8,}|ghp_|AKIA", QUESTIONS))


class JudgePrompt(unittest.TestCase):
    def test_same_as_spec_appendix_a(self):
        spec = read("docs/SPEC.md")
        i = spec.index("## 부록 A")
        body = spec[spec.index("```text", i) + len("```text"):]
        body = body[:body.index("```")].strip("\n").splitlines()
        want = [l for l in body if l not in ("<펼친 글>",)]
        got = PASTE[PASTE.index("\n[판정 프롬프트]\n"):PASTE.index("\n[글 P]\n")].splitlines()[2:]
        got = [l for l in got if l.strip() and l != "(여기에 글 P 또는 글 B)"]
        self.assertEqual([l for l in want if l.strip()], got)

    def test_p_and_b_are_synthetic_and_distinct(self):
        p = PASTE[PASTE.index("\n[글 P]\n"):PASTE.index("\n[글 B]\n")]
        b = PASTE[PASTE.index("\n[글 B]\n"):]
        self.assertNotIn("350", p)
        self.assertIn("350", b)
        self.assertIn("synthetic", p + b)


class StatuslineKeys(unittest.TestCase):
    def run_tool(self, data):
        out = io.StringIO()
        code = statusline_keys.main(stdin=io.BytesIO(data), stdout=out)
        return code, out.getvalue().strip()

    def test_names_only_never_values(self):
        data = (b'{"session_id": "s-secret-123", "model": {"id": "internal-model-x"}, "effort": {"level": "high"},'
                b' "cost": {"total_cost_usd": 1.2}, "workspace": {"current_dir": "C:\\\\Users\\\\me", "added_dirs": ["a"]},'
                b' "list": [{"k": 1}], "empty": {}}')
        code, line = self.run_tool(data)
        self.assertEqual(code, 0)
        self.assertEqual(line, "cost.total_cost_usd,effort.level,empty,list[],list[].k,model.id,session_id,"
                               "workspace.added_dirs[],workspace.current_dir")
        for v in ("secret", "internal-model", "high", "Users", "1.2"):
            self.assertNotIn(v, line)

    def test_always_exit_zero_and_one_line(self):
        for data in (b"{", b"", b"\xff\xfe", b"[]", b'"x"', b"x" * (statusline_keys.MAX_BYTES + 1)):
            code, line = self.run_tool(data)
            self.assertEqual(code, 0)
            self.assertTrue(line.startswith("ERR") or line == "", (data[:10], line))
            self.assertNotIn("\n", line)

    def test_depth_is_bounded(self):
        deep = b'{"a":' * 12 + b'1' + b'}' * 12
        code, line = self.run_tool(deep)
        self.assertEqual(code, 0)
        self.assertLess(line.count("."), 10)


if __name__ == "__main__":
    unittest.main()
