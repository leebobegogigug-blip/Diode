# -*- coding: utf-8 -*-
"""kit/reid_sim.py - 재식별 시뮬레이션의 지표가 맞는가 (손으로 셀 수 있는 작은 합성 표) ·
변환을 diodelib.derive 에서 그대로 불러 쓰는가 · --quick 이 10초 안 · 출력에 칸 값이 없음 · 같은 시드 = 같은 결과.
모든 자료는 지어낸 것이다."""

import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KIT = os.path.join(ROOT, "kit")
for p in (ROOT, KIT):
    if p not in sys.path:
        sys.path.insert(0, p)

import reid_sim  # noqa: E402
from diodelib import derive  # noqa: E402

SIM = os.path.join(KIT, "reid_sim.py")


def small_table(second):
    """20행. 0열 = 0..19 (수치) · 1열 = second 방식으로 만든 열. 표본 = 원본 전체 (행 20 · k 10 = 최소 k)."""
    n = 20
    a = [i for i in range(n)]
    if second == "cat":
        b = ["RVx" if i % 2 else "RVy" for i in range(n)]
        kinds = ["num", "cat"]
    else:
        b = [i % 4 for i in range(n)]
        kinds = ["num", "num"]
    return [a, b], kinds


def metrics(data, kinds, aux, transform="bucket", k=derive.MIN_K):
    idx = list(range(len(data[0])))
    job = reid_sim.build_job(data, kinds, idx, transform, k, aux)
    return reid_sim.evaluate_jobs([job], aux, len(kinds))


class ReidSimTest(unittest.TestCase):
    def test_hand_counted_candidates(self):
        # 0열 bucket: 20행 -> 경계 4 · 8 · 12 · 16 -> 칸마다 4행. 보조 = 0열 하나면 후보는 모두 4개, 유일 0%.
        data, kinds = small_table("cat")
        r = metrics(data, kinds, [0])
        self.assertEqual(r["raw"], [4] * 20)
        # 1열 범주 (두 값 x 10행, k=5 라 묶이지 않음) 까지 보조로 알면 칸마다 두 값이 둘씩 -> 후보 2개
        r = metrics(data, kinds, [0, 1])
        self.assertEqual(r["raw"], [2] * 20)
        # 숨은 열이 없으면 속성 추론은 없다 / 있으면 숫자 셋
        self.assertIsNone(r["attr"])
        self.assertIsNotNone(metrics(data, kinds, [0])["attr"])

    def test_unique_when_cells_separate_every_row(self):
        # 0열 칸 = i // 4 (5칸) · 1열 (값 i % 4 를 bucket 하면 칸 = 값 + 1) -> 두 칸 조합이 행마다 다르다 -> 20행 전부 유일
        data, kinds = small_table("num")
        r = metrics(data, kinds, [0, 1])
        self.assertEqual(r["raw"], [1] * 20)
        self.assertEqual(r["excl"], [1] * 20)
        # 보조 열이 없으면 후보는 원본 전체
        self.assertEqual(metrics(data, kinds, [])["raw"], [20] * 20)

    def test_uses_derive_functions_not_a_copy(self):
        self.assertIs(reid_sim.derive, derive)
        with open(SIM, encoding="utf-8") as f:
            src = f.read()
        for name in ("def bucket_cells", "def rank_cells", "def category_cells"):
            self.assertNotIn(name, src)
        # 열별 칸이 derive 함수의 결과와 같다 (build_job 이 build_sample 과도 맞춰 본다)
        data, kinds = small_table("num")
        job = reid_sim.build_job(data, kinds, list(range(20)), "bucket", 10, [0])
        self.assertEqual(job.cells[0], derive.bucket_cells([float(v) for v in data[0]], derive.parse_quantiles(None)))
        job = reid_sim.build_job(data, kinds, list(range(20)), "rank", 10, [0])
        self.assertEqual(job.cells[0], derive.rank_cells([float(v) for v in data[0]]))
        # derive 의 한도가 그대로 적용된다 (행 < 2k 면 거절)
        with self.assertRaises(derive.DeriveError):
            reid_sim.build_job(data, kinds, list(range(8)), "bucket", 10, [0])

    def test_mosaic_exclusion_never_widens_and_rates_ordered(self):
        rng = random.Random(7)
        data, kinds = reid_sim.make_table(rng, 40, 4, 5, "uniform", False)
        idx = list(range(40))
        rng.shuffle(idx)
        jobs = [reid_sim.build_job(data, kinds, idx[:20], "rank", 10, [0, 1]),
                reid_sim.build_job(data, kinds, idx[20:], "rank", 10, [0, 1])]
        r = reid_sim.evaluate_jobs(jobs, [0, 1], 4)
        self.assertEqual(len(r["raw"]), 40)
        self.assertTrue(all(1 <= e <= a for a, e in zip(r["raw"], r["excl"])))
        self.assertGreaterEqual(sum(1 for e in r["excl"] if e == 1), sum(1 for a in r["raw"] if a == 1))

    def test_deterministic_and_seed_sensitive(self):
        p = dict(n=1000, cols=4, aux=2, jobs=1)
        a = reid_sim.scenario(p, {}, 5, 1, 2)
        b = reid_sim.scenario(p, {}, 5, 1, 2)
        c = reid_sim.scenario(p, {}, 6, 1, 2)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertNotEqual(json.dumps(a, sort_keys=True), json.dumps(c, sort_keys=True))

    def test_quick_cli_fast_and_prints_numbers_only(self):
        with tempfile.TemporaryDirectory() as d:
            out_json = os.path.join(d, "r.json")
            t0 = time.time()
            proc = subprocess.run([sys.executable, SIM, "--quick", "--json", out_json],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            took = time.time() - t0
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
            self.assertLess(took, 10.0)
            text = proc.stdout.decode("utf-8")
            with open(out_json, encoding="utf-8") as f:
                raw = f.read()
            rep = json.loads(raw)
            self.assertTrue(rep["results"])
            # 합성 표의 범주 값 (RV 로 시작) 이나 칸 값 목록이 출력 · JSON 어디에도 없다
            for blob in (text, raw):
                self.assertNotIn("RV", blob)
                self.assertNotIn("PH_", blob)
            # 같은 시드로 한 번 더 -> 같은 JSON
            again = reid_sim.run(quick=True)
            self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(rep, sort_keys=True))

    def test_scenarios_obey_the_derive_limits(self):
        # rank 시나리오도 rank 열은 최대 2개 (나머지 수치 열은 bucket) - build_sample 의 한도를 통과해야 한다
        kinds = ["num", "cat"] * 4
        tfs = reid_sim.column_transforms(kinds, "rank")
        self.assertEqual(tfs.count("rank"), derive.MAX_RANK_COLUMNS)
        self.assertEqual(tfs.count("bucket"), 2)
        self.assertEqual(reid_sim.column_transforms(kinds, "bucket").count("rank"), 0)
        rng = random.Random(3)
        data, kinds = reid_sim.make_table(rng, 1000, 8, 20, "uniform", False)
        job = reid_sim.build_job(data, kinds, list(range(30)), "rank", derive.DEFAULT_K, [0, 2, 4])
        self.assertEqual(len(job.cells), 8)
        # 원본 1,000행: 표본 30행 · 누계 100행 -> job 3개까지. 4개는 건너뜀
        self.assertFalse(reid_sim.scenario(dict(n=1000, jobs=3), {}, 5, 1, 1)["skipped"])
        self.assertTrue(reid_sim.scenario(dict(n=1000, jobs=4), {}, 5, 1, 1)["skipped"])
        self.assertEqual(reid_sim.scenario(dict(n=1000), {}, 5, 1, 1)["rows"], 30)
        self.assertEqual(reid_sim.scenario(dict(n=10000), {}, 5, 1, 1)["rows"], 50)
        for params in reid_sim.scenarios_full() + reid_sim.scenarios_quick():
            self.assertGreaterEqual(params.get("n", 1000), derive.MIN_SOURCE_ROWS)
            self.assertGreaterEqual(params.get("k", derive.DEFAULT_K), derive.MIN_K)

    def test_bad_usage_exit_code(self):
        proc = subprocess.run([sys.executable, SIM, "--nope"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
