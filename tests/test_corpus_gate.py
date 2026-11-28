# -*- coding: utf-8 -*-
"""검사기를 고칠 때마다 합성 말뭉치 (kit/corpus · 40과제) 로 두 가지를 본다 - 이 시험이 CI 의 문이다.

- good_brief 40건은 검사기를 통과해야 한다 (오탐이 늘면 사람이 도구를 끈다 - PLAN R6)
- leaky_briefs 120건은 검사기가 막아야 한다 (카나리아가 새면 안 된다 - G1)

가린 묶음 (SP-20) 도 같은 문을 지난다 - kit/bundle_corpus.py 의 합성 묶음 코퍼스:
- good 38묶음 (문서 · 표 · 코드) 은 모두 통과하고, 금고로 되돌린 글이 원문 (표시 기호만 뺀 글) 과 같아야 한다
- leaky 103묶음 (표시를 빠뜨리거나 틀린 꼴) 은 모두 R1–R6 또는 E-04 로 막혀야 한다
- known-miss (SP-20 › 남는 위험의 꼴) 는 지나간 수를 기록만 한다 - 실패 조건이 아니다
"""

import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class CorpusGate(unittest.TestCase):
    def test_checker_passes_every_good_brief_and_blocks_every_leaky_one(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        p = subprocess.run([sys.executable, os.path.join(ROOT, "kit", "leak_rate.py"), "--self-test", "--with-checker"],
                           cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        out = p.stdout.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, out[-800:])
        self.assertIn("good_brief 통과 40/40", out)
        self.assertIn("leaky_briefs 막음 120/120", out)

    def test_bundle_corpus_passes_good_blocks_leaky_and_round_trips(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        outs = []
        for extra in (["--self-test"], []):
            p = subprocess.run([sys.executable, os.path.join(ROOT, "kit", "bundle_corpus.py")] + extra,
                               cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            out = p.stdout.decode("utf-8", "replace")
            self.assertEqual(p.returncode, 0, out[-800:])
            self.assertEqual(out.rstrip().splitlines()[-1], "결과: OK")
            # 글 · 단어 · 값을 찍지 않는다 (개수 · 비율 · 범주 · 검사 번호뿐)
            self.assertIsNone(re.search(r"PH_[2-9A-HJKMNP-TV-Z]{4}|KIT[A-Z_]{4,}|example\.|\u27e6|\u27e7", out))
            outs.append(out)
        self.assertIn("good 38개 · 통과 38/38 · 왕복 일치 38/38", outs[0])
        self.assertIn("leaky 103개 · 막음 103/103", outs[0])
        self.assertRegex(outs[0], r"known-miss [0-9]+개 · 지나감 [0-9]+/[0-9]+")     # 숫자만 남긴다 (합격 기준 밖)


if __name__ == "__main__":
    unittest.main()
