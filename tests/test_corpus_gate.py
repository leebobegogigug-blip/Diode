# -*- coding: utf-8 -*-
"""검사기를 고칠 때마다 합성 말뭉치 (kit/corpus · 40과제) 로 두 가지를 본다 - 이 시험이 CI 의 문이다.

- good_brief 40건은 검사기를 통과해야 한다 (오탐이 늘면 사람이 도구를 끈다 - PLAN R6)
- leaky_briefs 120건은 검사기가 막아야 한다 (카나리아가 새면 안 된다 - G1)
"""

import os
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


if __name__ == "__main__":
    unittest.main()
