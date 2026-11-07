# -*- coding: utf-8 -*-
"""파생 표본 (L2 · docs/PROPOSAL-derived.md) - 변환 셋 · 한도 · 문 · 출력에 값이 없음 · 스키마 · 검사. 모든 자료는 지어낸 것이다."""

import ast
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import diode  # noqa: E402
from diodelib import audit, briefschema, config, derive, policy_window as pw, scan  # noqa: E402
from diodelib.derive import DeriveError  # noqa: E402
from diodelib.render import render  # noqa: E402
from diodelib.seal import PseudonymTable  # noqa: E402

WORDS = ["KITWORDALPHA"]

# 합성 카나리아 - 출력 어디에도 있으면 안 된다 (열 이름 · 범주 값 · 수치 · 고르지 않은 열)
HEAD_NUM, HEAD_CAT, HEAD_SCORE, HEAD_SKIP = "kitc_metric_zeta", "kitc_group_beta", "kitc_score_gamma", "kitc_unpicked_delta"
CAT_VALUES = ["KITGRPXA"] * 20 + ["KITGRPXB"] * 18 + ["KITGRPXC"] * 8 + ["KITGRPXD"] * 4
SKIP_VALUE = "KITSECRETUNPICKED"


def csv_text(n=50, shuffle=True):
    """n 행의 합성 표 (4열). 수치는 여섯 자리 · 소수 (카나리아), 범주는 네 값."""
    cats = (CAT_VALUES * 3)[:n] if n != 50 else CAT_VALUES
    order = list(range(n))
    if shuffle:
        order = [(i * 17) % n for i in range(n)]       # 결정적인 섞기 (n 과 17 이 서로소일 때 한 번씩)
    lines = ["%s,%s,%s,%s" % (HEAD_NUM, HEAD_CAT, HEAD_SCORE, HEAD_SKIP)]
    for i in order:
        lines.append("%d,%s,%.3f,%s" % (731000 + i * 137, cats[i], 31.5 + i * 0.731, SKIP_VALUE))
    return "\n".join(lines) + "\n"


def canaries(n=50):
    out = [HEAD_NUM, HEAD_CAT, HEAD_SCORE, HEAD_SKIP, SKIP_VALUE, "KITGRPXA", "KITGRPXB", "KITGRPXC", "KITGRPXD"]
    out += ["%d" % (731000 + i * 137) for i in range(n)]
    out += ["%.3f" % (31.5 + i * 0.731) for i in range(n)]
    return out


def dialog(job="J-0007", k="", picks=None, go="y", source="10000"):
    """사람이 치는 순서: job -> 원본 표의 전체 행 수 -> k -> 열 줄들 (빈 줄로 끝) -> y. 원본 10,000행이면 표본 50행 · 누계 200행까지 쓸 수 있다."""
    picks = picks if picks is not None else ["%s=bucket" % HEAD_NUM, "2=category", "%s=rank" % HEAD_SCORE]
    return "%s\n%s\n%s\n%s\n\n%s\n" % (job, source, k, "\n".join(picks), go)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="diode-derive-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "data")
        self.raw = os.path.join(self.tmp, "kitraw")
        os.makedirs(self.raw)
        self.csv = os.path.join(self.tmp, "kit.csv")
        self.write_csv(csv_text())

    def write_csv(self, text):
        with open(self.csv, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def state(self, **kw):
        st = {"words": list(WORDS), "raw_dirs": [self.raw], "inner_tools": [], "lib_allow": [], "patterns": [],
              "web_search": True, "real_data": True, "derived_level": 1, "monthly_budget_usd": 0,
              "worker_command": None, "worker_cwd": None, "room_path": None, "llm": None}
        st.update(kw)
        return st

    def configure(self, **kw):
        config.apply_state(self.home, self.state(**kw))

    def out_path(self, name="draft.json"):
        return os.path.join(self.tmp, name)

    def run_derive(self, text=None, out=None, default=True, csv=None):
        err = io.StringIO()
        code, line = derive.main_derive(self.home, default, csv or self.csv, out or self.out_path(),
                                        io.StringIO(text if text is not None else dialog()), err)
        return code, line, err.getvalue()

    def all_home_text(self):
        chunks = []
        for base, _dirs, files in os.walk(self.home):
            for fn in files:
                with open(os.path.join(base, fn), "r", encoding="utf-8") as f:
                    chunks.append(f.read())
        return "\n".join(chunks)


# ---------------------------------------------------------------- 변환 셋

class Transforms(unittest.TestCase):
    def test_bucket_boundaries_and_sizes(self):
        vals = [float(i) for i in range(1, 101)]
        q = derive.parse_quantiles(None)
        cells = derive.bucket_cells(vals, q)
        self.assertEqual([cells.count(c) for c in range(5)], [20, 20, 20, 20, 20])
        # 경계: 정렬한 값의 [floor(q x n)] 번째 = 21 · 41 · 61 · 81 (이 값은 칸 번호로만 보인다)
        self.assertEqual([cells[19], cells[20], cells[39], cells[40], cells[79], cells[80], cells[99]], [0, 1, 1, 2, 3, 4, 4])

    def test_bucket_uses_the_quantiles_the_human_chose_and_exactly(self):
        vals = [float(i) for i in range(1, 101)]
        q = derive.parse_quantiles("0.29,0.4,0.6,0.9")          # 0.29 x 100 = 29 (부동소수점이면 28.99...)
        cells = derive.bucket_cells(vals, q)
        self.assertEqual((cells[28], cells[29]), (0, 1))
        self.assertEqual(sorted(set(cells)), [0, 1, 2, 3, 4])

    def test_bucket_is_deterministic_and_order_free(self):
        vals = [float((i * 37) % 101) for i in range(60)]
        q = derive.parse_quantiles(None)
        a = derive.bucket_cells(vals, q)
        self.assertEqual(a, derive.bucket_cells(list(vals), q))
        rev = derive.bucket_cells(list(reversed(vals)), q)
        self.assertEqual(list(reversed(rev)), a)

    def test_bucket_ties_share_a_cell(self):
        cells = derive.bucket_cells([5.0] * 12 + [9.0] * 12, derive.parse_quantiles(None))
        self.assertEqual(len(set(cells[:12])), 1)
        self.assertEqual(len(set(cells[12:])), 1)

    def test_quantile_checks(self):
        for bad in ("0.2,0.4,0.6", "0.2,0.4,0.6,0.8,0.9", "0.05,0.4,0.6,0.8", "0.2,0.4,0.6,0.95", "0.2,0.25,0.6,0.8",
                    "0.2,0.4,0.6,x", "1,2,3,4", "0.2,0.4,0.6,0.8e0"):
            with self.assertRaises(DeriveError, msg=bad):
                derive.parse_quantiles(bad)
        self.assertEqual(len(derive.parse_quantiles(None)), 4)

    def test_rank_deciles(self):
        cells = derive.rank_cells([float(i) for i in range(1, 11)])
        self.assertEqual(cells, list(range(10)))
        cells = derive.rank_cells([float(i) for i in range(1, 101)])
        self.assertEqual([cells.count(c) for c in range(10)], [10] * 10)
        self.assertTrue(all(0 <= c <= 9 for c in cells))

    def test_rank_ties_are_one_cell_without_random_break(self):
        self.assertEqual(set(derive.rank_cells([5.0] * 10)), {5})
        vals = [3.0, 1.0, 3.0, 2.0, 3.0, 1.0, 2.0, 3.0, 2.0, 1.0]
        a = derive.rank_cells(vals)
        self.assertEqual(a, derive.rank_cells(list(vals)))
        for v in set(vals):
            self.assertEqual(len(set(c for c, x in zip(a, vals) if x == v)), 1)

    def test_category_suppresses_small_values_under_one_token(self):
        t = PseudonymTable()
        cells = derive.category_cells(CAT_VALUES, 10, t)
        self.assertEqual(cells.count("PH_other"), 12)             # C 8 + D 4 -> 12 (k=10 이상이라 더 묶지 않는다)
        toks = [c for c in cells if c != "PH_other"]
        self.assertEqual(len(set(toks)), 2)
        self.assertEqual(len(t), 2)                              # 묶인 값에는 토큰을 만들지 않는다
        self.assertTrue(all(scan.TOKEN_RE.fullmatch(c) for c in toks))

    def test_category_pool_that_is_itself_too_small_absorbs_the_next_smallest(self):
        vals = ["a"] * 14 + ["b"] * 12 + ["c"] * 3 + ["d"] * 2 + ["e"] * 1          # 묶음 6 < 10 -> 가장 작은 a/b 쪽을 더 묶는다
        t = PseudonymTable()
        cells = derive.category_cells(vals, 10, t)
        self.assertGreaterEqual(cells.count("PH_other"), 10)
        kept = [c for c in set(cells) if c != "PH_other"]
        self.assertEqual(len(kept), 1)
        self.assertGreaterEqual(cells.count(kept[0]), 10)

    def test_category_every_kept_value_has_at_least_k_rows(self):
        vals = ["v%d" % (i % 7) for i in range(50)]
        t = PseudonymTable()
        cells = derive.category_cells(vals, 8, t)
        for c in set(cells):
            self.assertGreaterEqual(cells.count(c), 8)

    def test_category_empty_value_is_refused(self):
        with self.assertRaises(DeriveError):
            derive.category_cells(["a"] * 11 + [" "], 5, PseudonymTable())

    def test_number_parser_is_strict(self):
        for ok in ("12", "-3.5", "+7", "1e3", " 4 "):
            derive._number(ok)
        for bad in ("", "abc", "1_000", "nan", "inf", "1e999", "٣", "1,5", "0x10", "--1"):
            with self.assertRaises(DeriveError, msg=bad):
                derive._number(bad)


# ---------------------------------------------------------------- 표 읽기 · 한도

class Limits(Base):
    def test_more_than_fifty_rows_is_refused(self):
        self.write_csv("a,b\n" + "\n".join("%d,x" % i for i in range(51)) + "\n")
        with self.assertRaises(DeriveError) as cm:
            derive.read_table(self.csv)
        self.assertEqual(cm.exception.code, "E-31")

    def test_fifty_rows_is_fine(self):
        header, rows = derive.read_table(self.csv)
        self.assertEqual((len(header), len(rows)), (4, 50))

    def test_ragged_or_empty_or_binary_tables_are_refused(self):
        for text in ("a,b\n1,2,3\n", "a,b\n", "", "a,b\n1\x00,2\n"):
            self.write_csv(text)
            with self.assertRaises(DeriveError, msg=repr(text)) as cm:
                derive.read_table(self.csv)
            self.assertEqual(cm.exception.code, "E-04")
        with open(self.csv, "wb") as f:
            f.write(b"a,b\n\xff\xfe,2\n")
        with self.assertRaises(DeriveError):
            derive.read_table(self.csv)

    def test_a_huge_file_is_refused_before_reading_rows(self):
        with open(self.csv, "w") as f:
            f.write("a,b\n" + ("1," + "x" * 200 + "\n") * 6000)
        with self.assertRaises(DeriveError) as cm:
            derive.read_table(self.csv)
        self.assertEqual(cm.exception.code, "E-31")

    def test_more_than_eight_columns_is_refused(self):
        header = ["c%d" % i for i in range(10)]
        rows = [[str(i + j) for j in range(10)] for i in range(20)]
        picks = [(i, "rank" if i < derive.MAX_RANK_COLUMNS else "bucket", None) for i in range(9)]
        with self.assertRaises(DeriveError) as cm:
            derive.build_sample(header, rows, picks, 10, PseudonymTable())
        self.assertEqual(cm.exception.code, "E-31")
        sample, counts = derive.build_sample(header, rows, picks[:8], 10, PseudonymTable())
        self.assertEqual(len(sample["columns"]), 8)

    def test_no_pick_means_nothing_goes(self):
        with self.assertRaises(DeriveError):
            derive.build_sample(["a"], [["1"]] * 20, [], 5, PseudonymTable())

    def test_small_table_is_refused(self):
        header = ["a", "b"]
        rows = [[str(i), "x"] for i in range(19)]                 # k=10 이면 20 행 이상이어야 한다
        with self.assertRaises(DeriveError) as cm:
            derive.build_sample(header, rows, [(0, "rank", None)], 10, PseudonymTable())
        self.assertEqual(cm.exception.code, "E-31")
        derive.build_sample(header, rows + [["19", "x"]], [(0, "rank", None)], 10, PseudonymTable())

    def test_k_range(self):
        header, rows = ["a"], [[str(i)] for i in range(50)]
        self.assertEqual(derive.MIN_K, 10)
        self.assertGreaterEqual(derive.DEFAULT_K, derive.MIN_K)
        for k in (0, 4, 5, 9, 26, 100):                            # 5 도 거절 - 최소 k 는 10
            with self.assertRaises(DeriveError, msg=str(k)) as cm:
                derive.build_sample(header, rows, [(0, "rank", None)], k, PseudonymTable())
            self.assertEqual(cm.exception.code, "E-31")
        derive.build_sample(header, rows, [(0, "rank", None)], 10, PseudonymTable())
        derive.build_sample(header, rows, [(0, "rank", None)], 25, PseudonymTable())

    def test_same_column_twice_is_refused(self):
        with self.assertRaises(DeriveError):
            derive.build_sample(["a"], [[str(i)] for i in range(20)], [(0, "rank", None), (0, "bucket", None)], 10, PseudonymTable())

    def test_text_in_a_numeric_column_is_refused(self):
        rows = [[str(i)] for i in range(19)] + [["x"]]
        with self.assertRaises(DeriveError) as cm:
            derive.build_sample(["a"], rows, [(0, "rank", None)], 10, PseudonymTable())
        self.assertEqual(cm.exception.code, "E-04")

    def test_topic_cumulative_limit_is_two_hundred_rows(self):
        self.configure()
        for i in range(4):                                       # 50 x 4 = 200 까지 된다
            code, line, _ = self.run_derive(out=self.out_path("d%d.json" % i))
            self.assertEqual(code, 0, line)
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 200)
        code, line, _ = self.run_derive(out=self.out_path("d4.json"))
        self.assertEqual((code, json.loads(line)), (2, {"derived": False, "error": "E-31"}))
        self.assertFalse(os.path.exists(self.out_path("d4.json")))
        code, line, _ = self.run_derive(text=dialog(job="J-0008"), out=self.out_path("other.json"))      # 다른 주제는 따로 센다
        self.assertEqual(code, 0, line)
        self.assertEqual(audit.derived_rows(self.home, "J-0008"), 50)


# ---------------------------------------------------------------- 재식별 시뮬레이션의 권고 (kit/results-reid.md › 적용한 권고)

def numeric_csv(n=50, cols=4):
    """수치 열만 있는 합성 표 (rank 열 수 시험용). 머리 글은 지어낸 것."""
    lines = [",".join("kitn_col%d" % c for c in range(cols))]
    for i in range(n):
        lines.append(",".join(str(1000 + ((i * 37 + c * 11) % n) * (c + 3)) for c in range(cols)))
    return "\n".join(lines) + "\n"


class ReidRecommendations(Base):
    def setUp(self):
        Base.setUp(self)
        self.configure()

    def run_json(self, text, out="r.json"):
        code, line, err = self.run_derive(text=text, out=self.out_path(out))
        return code, json.loads(line), err

    # 1. 원본 행 수를 사람이 알려 준다
    def test_source_999_is_refused_and_1000_is_allowed(self):
        self.write_csv(csv_text(30))                              # 원본 5,000행 미만이면 표본 30행까지
        code, res, err = self.run_json(dialog(source="999"))
        self.assertEqual((code, res), (2, {"derived": False, "error": "E-31"}))
        self.assertIn(derive.NOTE_SOURCE_SMALL, err)
        self.assertFalse(os.path.exists(self.out_path("r.json")))
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 0)
        code, res, _ = self.run_json(dialog(source="1000"))
        self.assertEqual((code, res["derived"]), (0, True), res)
        code, res, _ = self.run_json(dialog(job="J-0008", source="1,000"), out="r2.json")      # 천 단위 쉼표는 받는다
        self.assertEqual((code, res["derived"]), (0, True), res)

    def test_source_rows_must_be_a_plain_integer(self):
        self.write_csv(csv_text(30))
        for bad in ("", "abc", "1000.5", "-1000", "1e4", "1,00", "1,0000", "10 000", "１０００", "9999999999", "0"):
            code, res, _ = self.run_json(dialog(source=bad))
            self.assertEqual(code, 2, bad)
            self.assertFalse(res["derived"], bad)
            self.assertFalse(os.path.exists(self.out_path("r.json")), bad)
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 0)

    def test_the_source_rows_prompt_is_asked_and_says_it_trusts_the_human(self):
        code, res, err = self.run_json(dialog())
        self.assertEqual(code, 0, res)
        self.assertIn("원본 표의 전체 행 수", err)
        self.assertIn("믿습니다", err)

    # 6. 표본 행 수 기본값
    def test_sample_rows_are_capped_at_30_below_5000_source_rows(self):
        self.assertEqual((derive.sample_row_cap(1000), derive.sample_row_cap(4999), derive.sample_row_cap(5000),
                          derive.sample_row_cap(10 ** 6)), (30, 30, 50, 50))
        self.assertEqual(derive.MAX_ROWS, 50)
        for source in ("1000", "4999"):                           # 50행 파일은 30행 상한에 걸린다
            code, res, _ = self.run_json(dialog(source=source))
            self.assertEqual((code, res), (2, {"derived": False, "error": "E-31"}), source)
        self.assertEqual(self.run_json(dialog(source="5000"))[0], 0)
        self.write_csv(csv_text(31))
        self.assertEqual(self.run_json(dialog(source="4999"), out="r2.json")[1], {"derived": False, "error": "E-31"})
        self.write_csv(csv_text(30))
        self.assertEqual(self.run_json(dialog(source="4999"), out="r3.json")[0], 0)

    # 2. 한 주제 누계 행 <= 원본의 10% (200 과 함께 작은 쪽)
    def test_topic_total_is_at_most_ten_percent_of_the_source(self):
        self.assertEqual((derive.topic_row_cap(1000), derive.topic_row_cap(1999), derive.topic_row_cap(2000),
                          derive.topic_row_cap(10000), derive.topic_row_cap(10 ** 6)), (100, 199, 200, 200, 200))
        self.write_csv(csv_text(30))
        for i in range(3):                                        # 30 x 3 = 90 <= 100
            code, res, _ = self.run_json(dialog(source="1000"), out="d%d.json" % i)
            self.assertEqual(code, 0, res)
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 90)
        code, res, _ = self.run_json(dialog(source="1000"), out="d3.json")          # 120 > 100
        self.assertEqual((code, res), (2, {"derived": False, "error": "E-31"}))
        self.assertFalse(os.path.exists(self.out_path("d3.json")))
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 90)
        code, res, _ = self.run_json(dialog(job="J-0008", source="1000"), out="o.json")      # 다른 주제는 따로 센다
        self.assertEqual(code, 0, res)

    def test_a_bigger_source_later_does_not_loosen_the_topic_limit(self):
        self.write_csv(csv_text(30))
        for i in range(3):
            self.assertEqual(self.run_json(dialog(source="1000"), out="d%d.json" % i)[0], 0)
        code, res, _ = self.run_json(dialog(source="100000"), out="late.json")      # 앞서 말한 1,000 보다 큰 수로 풀지 못한다
        self.assertEqual((code, res["error"]), (2, "E-31"))
        self.assertEqual(audit.derived_source_rows(self.home, "J-0007"), 1000)

    def test_topic_limit_stays_two_hundred_for_a_big_source(self):
        self.configure()
        for i in range(4):
            self.assertEqual(self.run_json(dialog(source="1000000"), out="d%d.json" % i)[0], 0)
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 200)
        self.assertEqual(self.run_json(dialog(source="1000000"), out="d4.json")[1]["error"], "E-31")

    # 3. rank 열은 최대 2개
    def test_three_rank_columns_are_refused_with_a_fixed_note_and_two_are_allowed(self):
        self.write_csv(numeric_csv())
        code, res, err = self.run_json(dialog(picks=["1=rank", "2=rank", "3=rank"]))
        self.assertEqual((code, res), (2, {"derived": False, "error": "E-31"}))
        self.assertIn(derive.NOTE_RANK, err)
        self.assertNotIn("kitn_col", err)                         # 안내에 열 이름이 없다
        self.assertFalse(os.path.exists(self.out_path("r.json")))
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 0)
        code, res, _ = self.run_json(dialog(picks=["1=rank", "2=rank", "3=bucket", "4=bucket"]))
        self.assertEqual((code, res["transforms"]), (0, {"bucket": 2, "rank": 2, "category": 0}), res)

    def test_build_sample_also_refuses_three_rank_columns(self):
        header = ["a", "b", "c"]
        rows = [[str(i), str(i * 3 % 50), str(i * 7 % 50)] for i in range(50)]
        with self.assertRaises(DeriveError) as cm:
            derive.build_sample(header, rows, [(0, "rank", None), (1, "rank", None), (2, "rank", None)], 10, PseudonymTable())
        self.assertEqual(cm.exception.code, "E-31")
        derive.build_sample(header, rows, [(0, "rank", None), (1, "rank", None), (2, "bucket", None)], 10, PseudonymTable())

    # 4. 기본 변환은 bucket
    def test_the_default_transform_is_bucket_and_rank_must_be_typed(self):
        header = ["alpha", "beta", "gamma"]
        self.assertEqual(derive.DEFAULT_TRANSFORM, "bucket")
        for line in ("alpha", "alpha=", " alpha ", "1", "1="):
            col, tf, q = derive.parse_pick(line, header)
            self.assertEqual((col, tf), (0, "bucket"), line)
            self.assertEqual(len(q), 4)                           # 기본 분위수
        self.assertEqual(derive.parse_pick("alpha=rank", header)[1], "rank")
        self.assertEqual(derive.parse_pick("alpha=category", header)[1], "category")
        with self.assertRaises(DeriveError):
            derive.parse_pick("nothere", header)
        with self.assertRaises(DeriveError):
            derive.parse_pick("alpha=ranks", header)             # 오타를 rank 나 bucket 으로 읽지 않는다 (열 이름 "alpha=ranks" 가 없다)

    def test_bare_column_lines_in_the_dialog_become_bucket(self):
        self.write_csv(numeric_csv())
        code, res, _ = self.run_json(dialog(picks=["1", "2=", "3=rank"]))
        self.assertEqual((code, res["transforms"]), (0, {"bucket": 2, "rank": 1, "category": 0}), res)
        self.write_csv(csv_text())
        code, res, _ = self.run_json(dialog(picks=["2"]), out="c.json")           # 범주 열을 변환 없이 적으면 bucket 이라 거절 (E-04)
        self.assertEqual((code, res["error"]), (2, "E-04"))

    # 5. MIN_K 10
    def test_min_k_is_ten_and_the_default_k_too(self):
        self.assertEqual((derive.MIN_K, derive.DEFAULT_K), (10, 10))
        code, res, err = self.run_json(dialog(k="9"))
        self.assertEqual((code, res["error"]), (2, "E-31"))
        code, res, _ = self.run_json(dialog(k=""), out="k.json")
        self.assertEqual(code, 0, res)
        self.assertIn("10 이상", derive.PROMPT_K)

    def test_a_table_under_twenty_rows_is_refused(self):
        self.write_csv(csv_text(19))
        code, res, _ = self.run_json(dialog())
        self.assertEqual((code, res["error"]), (2, "E-31"))

    # 감사 기록
    def test_the_audit_record_has_the_source_rows_as_an_integer_and_old_records_still_count(self):
        self.run_derive()
        files = glob.glob(os.path.join(self.home, "audit", "*", "J-0007-001-derive.json"))
        with open(files[0], encoding="utf-8") as f:
            rec = json.load(f)
        self.assertIs(type(rec["source_rows"]), int)
        self.assertEqual(rec["source_rows"], 10000)
        self.assertEqual(audit.derived_source_rows(self.home, "J-0007"), 10000)
        # 옛 기록 (source_rows 없음) 은 누계에는 세고 원본 행 수는 모른다 (호환)
        audit.derive_record(self.home, "J-0009", {"bucket": 1, "rank": 0, "category": 0}, 20)
        self.assertEqual(audit.derived_rows(self.home, "J-0009"), 20)
        self.assertIsNone(audit.derived_source_rows(self.home, "J-0009"))
        for bad in (True, 0, -5, "1000", 1000.0, 10 ** 10):
            with self.assertRaises(audit.AuditError, msg=repr(bad)):
                audit.derive_record(self.home, "J-0009", {"bucket": 1, "rank": 0, "category": 0}, 20, source_rows=bad)

    def test_the_old_record_without_source_rows_uses_the_declared_source_for_the_cap(self):
        audit.derive_record(self.home, "J-0007", {"bucket": 1, "rank": 0, "category": 0}, 40)       # 옛 기록 40행
        self.write_csv(csv_text(30))
        code, res, _ = self.run_json(dialog(source="1000"))                       # 40 + 30 = 70 <= 100
        self.assertEqual(code, 0, res)
        code, res, _ = self.run_json(dialog(source="1000"), out="r2.json")        # 70 + 30 = 100 (한도 그대로)
        self.assertEqual(code, 0, res)
        code, res, _ = self.run_json(dialog(source="1000"), out="r3.json")        # 100 + 30 > 100
        self.assertEqual((code, res["error"]), (2, "E-31"))

    # 7. 안내 · 출력에 값 · 열 이름이 없다
    def test_the_overlap_note_is_shown_and_nothing_secret_is_printed(self):
        code, line, err = self.run_derive()
        self.assertEqual(code, 0, line)
        self.assertIn(derive.NOTE_OVERLAP, err)
        self.assertIn("겹치지 않게", derive.NOTE_OVERLAP)
        self.assertIn("막지 못합니다", derive.NOTE_OVERLAP)                       # 자동으로 막는다고 말하지 않는다
        for c in canaries() + [self.tmp, self.csv, "kit.csv"]:
            self.assertNotIn(c, line + err)
        self.assertNotIn("10000", line)                                            # 표준 출력은 개수 · 코드뿐 (원본 행 수도 없다)

    def test_every_refusal_prints_no_value_or_column_name(self):
        self.write_csv(numeric_csv())
        for text in (dialog(source="999"), dialog(picks=["1=rank", "2=rank", "3=rank"]), dialog(k="9"), dialog(source="x")):
            code, line, err = self.run_derive(text=text, out=self.out_path("x.json"))
            self.assertEqual(code, 2, text)
            for c in ("kitn_col", "1000", self.tmp, self.csv):
                self.assertNotIn(c, line, text)
            self.assertNotIn("kitn_col", err, text)
            self.assertNotIn(self.tmp, err, text)


# ---------------------------------------------------------------- 문 (꺼짐 · 실데이터 · 환경 변수 · 명령줄)

class Gate(Base):
    def test_default_is_off_and_nothing_is_made(self):
        self.configure(derived_level=0)
        self.assertEqual(derive.effective_level(self.home), 0)
        code, line, err = self.run_derive()
        self.assertEqual((code, json.loads(line)), (3, {"derived": False, "error": "E-30"}))
        self.assertEqual(err, "")                                # 묻지도 않았다
        self.assertFalse(os.path.exists(self.out_path()))
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 0)

    def test_no_config_at_all_is_off(self):
        self.assertEqual(derive.effective_level(self.home), 0)
        self.assertEqual(self.run_derive()[0], 3)

    def test_level_one_without_real_data_is_ignored(self):
        config.apply_state(self.home, self.state(real_data=False))
        # 창은 이 조합을 만들지 않지만 (실데이터를 끄면 파생 표본도 꺼진다) 설정 파일을 손으로 고쳐도 0 으로 읽는다
        p = config.config_path(self.home)
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["policy"]["derived_level"] = 1
        cfg["policy"]["real_data"] = False
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.assertEqual(derive.effective_level(self.home), 0)
        self.assertEqual(self.run_derive()[0], 3)

    def test_both_on_is_one(self):
        self.configure()
        self.assertEqual(derive.effective_level(self.home), 1)

    def test_odd_values_are_zero(self):
        self.configure()
        p = config.config_path(self.home)
        for v in (True, 2, "1", 1.0, None, [1], -1):
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["policy"]["derived_level"] = v
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            self.assertEqual(derive.effective_level(self.home), 0, repr(v))
        with open(p, "w") as f:
            f.write("{broken")
        self.assertEqual(derive.effective_level(self.home), 0)

    def test_non_default_data_folder_is_off(self):
        self.configure()
        self.assertEqual(derive.effective_level(self.home, False), 0)
        code, line, _ = self.run_derive(default=False)
        self.assertEqual((code, json.loads(line)["error"]), (3, "E-30"))

    def test_environment_variables_cannot_turn_it_on(self):
        self.configure(derived_level=0)
        env = {"DIODE_DERIVED_LEVEL": "1", "DERIVED_LEVEL": "1", "DIODE_POLICY_DERIVED_LEVEL": "1", "DIODE_REAL_DATA": "1"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(derive.effective_level(self.home), 0)
            self.assertEqual(self.run_derive()[0], 3)

    def test_command_line_cannot_turn_it_on(self):
        self.configure(derived_level=0)
        for extra in (["--derived-level", "1"], ["--derived-level=1"], ["--set", "policy.derived_level=1"], ["--level", "1"]):
            out, err = io.StringIO(), io.StringIO()
            code = diode.main(["derive", self.csv, "--out", self.out_path()] + extra, out, err, io.StringIO(dialog()))
            self.assertEqual(code, 2, extra)
            self.assertEqual(out.getvalue(), "")
        self.assertEqual(derive.effective_level(self.home), 0)

    def test_the_cli_refuses_when_stdin_is_not_a_terminal_or_the_home_is_not_the_default(self):
        self.configure()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"DIODE_HOME": self.home}):
            code = diode.main(["derive", self.csv, "--out", self.out_path()], out, err, io.StringIO(dialog()))
        self.assertEqual((code, json.loads(out.getvalue())["error"]), (3, "E-30"))        # 기본 자리가 아니다
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"DIODE_HOME": self.home}), mock.patch.object(sys, "stdin", io.StringIO(dialog())):
            code = diode.main(["derive", self.csv, "--out", self.out_path()], out, err)
        self.assertEqual((code, json.loads(out.getvalue())["error"]), (3, "E-30"))        # 터미널이 아니다
        self.assertFalse(os.path.exists(self.out_path()))

    def test_it_is_in_the_help_and_requires_out(self):
        out = io.StringIO()
        diode.main(["help"], out, io.StringIO())
        self.assertIn("derive <csv> --out", out.getvalue())
        err = io.StringIO()
        self.assertEqual(diode.main(["derive", self.csv], io.StringIO(), err), 2)


class WindowIsTheOnlyWay(Base):
    """정책 창 (PolicySession) 이 켜는 유일한 곳이다 - 실데이터 승인과 확인 글이 있어야 켜지고, 실데이터를 끄면 같이 꺼진다."""

    def session(self, **kw):
        config.apply_state(self.home, self.state(real_data=kw.get("real", False), derived_level=kw.get("level", 0)))
        return pw.PolicySession(self.home)

    def test_turning_on_needs_real_data_first(self):
        s = self.session()
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertFalse(s.toggle_derived_level(True))
        self.assertFalse(s.derived_level)
        self.assertEqual(s.snapshot().level, "alert")
        self.assertEqual(s.snapshot().derived, False)

    def test_turning_on_needs_the_phrase(self):
        s = self.session(real=True)
        self.assertFalse(s.toggle_derived_level(True))
        self.assertEqual(s.take_focus(), "real_confirm")
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertTrue(s.toggle_derived_level(True))
        r = s.save()
        self.assertTrue(r.ok, r.message)
        self.assertTrue(r.counts["derived_level"])
        self.assertEqual(derive.effective_level(self.home), 1)

    def test_real_and_derived_on_in_one_session(self):
        s = self.session()
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        self.assertTrue(s.toggle_real_data(True))
        self.assertTrue(s.toggle_derived_level(True))
        self.assertTrue(s.save().ok)
        self.assertEqual(derive.effective_level(self.home), 1)

    def test_turning_real_data_off_turns_derived_off(self):
        s = self.session(real=True, level=1)
        self.assertTrue(s.derived_level)
        self.assertTrue(s.toggle_real_data(False))
        self.assertFalse(s.derived_level)
        self.assertTrue(s.save().ok)
        self.assertEqual(derive.effective_level(self.home), 0)
        self.assertEqual(config.load_state(self.home)["derived_level"], 0)

    def test_turning_it_off_needs_no_confirmation(self):
        s = self.session(real=True, level=1)
        self.assertTrue(s.toggle_derived_level(False))
        self.assertTrue(s.save().ok)
        self.assertEqual(derive.effective_level(self.home), 0)

    def test_the_phrase_cleared_after_turning_on_blocks_the_save(self):
        s = self.session(real=True)
        s.set_real_confirm(pw.REAL_DATA_PHRASE)
        s.toggle_derived_level(True)
        s.set_real_confirm("")
        r = s.save()
        self.assertFalse(r.ok)
        self.assertEqual(derive.effective_level(self.home), 0)

    def test_saving_something_else_keeps_the_setting(self):
        s = self.session(real=True, level=1)
        s.append_line("words", "KITWORDBETA")
        self.assertTrue(s.save().ok)
        self.assertEqual(derive.effective_level(self.home), 1)

    def test_config_rejects_odd_values(self):
        for bad in (2, -1, True, "1", 1.0):
            with self.assertRaises(config.ConfigError, msg=repr(bad)):
                config.validate_state(self.state(derived_level=bad))


class WhereTheSettingLives(unittest.TestCase):
    """AST 로 본다 - 켜는 곳 (쓰는 곳) 은 정책 창과 그 저장소 (config) 뿐이고, derive 는 읽기만 하며 환경 변수 · 명령줄을 읽지 않는다."""

    NAME = "derived_level"

    def files(self):
        out = sorted(glob.glob(os.path.join(ROOT, "diodelib", "*.py")))
        out.append(os.path.join(ROOT, "diode.py"))
        out += sorted(glob.glob(os.path.join(ROOT, "hooks", "*.py")))
        return out

    def parse(self, path):
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(src)

    def docstrings(self, tree):
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    skip.add(id(body[0].value))
        return skip

    def mentions(self, path):
        tree = self.parse(path)
        skip = self.docstrings(tree)
        return [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == self.NAME and id(n) not in skip]

    def write_sites(self, path):
        tree = self.parse(path)
        found = 0
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                found += sum(1 for k in n.keys if isinstance(k, ast.Constant) and k.value == self.NAME)
            elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store):
                sl = n.slice
                if isinstance(sl, ast.Constant) and sl.value == self.NAME:
                    found += 1
            elif isinstance(n, ast.keyword) and n.arg == self.NAME:
                found += 1
            elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and n.attr in (self.NAME, "_derived"):
                found += 1
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("update", "setdefault") \
                    and any(isinstance(a, ast.Constant) and a.value == self.NAME for a in n.args):
                found += 1
        return found

    def test_only_the_window_and_its_store_write_it(self):
        writers = set()
        for path in self.files():
            if self.write_sites(path):
                writers.add(os.path.basename(path))
        self.assertEqual(writers, {"config.py", "policy_window.py"})

    def test_only_these_modules_even_mention_it(self):
        mentioned = set(os.path.basename(p) for p in self.files() if self.mentions(p))
        self.assertEqual(mentioned, {"config.py", "policy_window.py", "derive.py"})
        self.assertFalse(self.mentions(os.path.join(ROOT, "diode.py")))

    def test_config_is_written_only_through_apply_state_called_by_the_window(self):
        callers = set()
        for path in self.files():
            for n in ast.walk(self.parse(path)):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "apply_state":
                    callers.add(os.path.basename(path))
        self.assertEqual(callers, {"policy_window.py"})

    def test_derive_reads_no_environment_and_no_command_line_and_writes_no_config(self):
        tree = self.parse(os.path.join(ROOT, "diodelib", "derive.py"))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                names.update(a.name.split(".")[-1] for a in n.names)
        for banned in ("environ", "getenv", "argv", "argparse", "apply_state", "_write_atomic", "write_config"):
            self.assertNotIn(banned, names)

    def test_no_stdlib_outside_the_standard_library_in_derive(self):
        tree = self.parse(os.path.join(ROOT, "diodelib", "derive.py"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.level == 0:
                mods.add((n.module or "").split(".")[0])
        self.assertEqual(mods - {"csv", "io", "json", "math", "os", "re", "collections", "fractions", "sys", "ctypes", "msvcrt"}, set())


# ---------------------------------------------------------------- 끝에서 끝 - 출력에 값이 없다

class EndToEnd(Base):
    def setUp(self):
        Base.setUp(self)
        self.configure()

    def test_makes_a_draft_and_the_output_has_counts_only(self):
        code, line, err = self.run_derive()
        self.assertEqual(code, 0, line)
        self.assertEqual(json.loads(line), {"derived": True, "columns": 3, "rows": 50,
                                            "transforms": {"bucket": 1, "rank": 1, "category": 1}})
        self.assertEqual(list(json.loads(line)), ["derived", "columns", "rows", "transforms"])
        with open(self.out_path(), encoding="utf-8") as f:
            draft = json.load(f)
        self.assertEqual((draft["kind"], draft["data_class"]), ("plan", "real"))
        self.assertEqual([c["kind"] for c in draft["sample"]["columns"]], ["수치", "범주", "수치"])
        self.assertEqual(len(draft["sample"]["rows"]), 50)

    def test_no_value_name_or_boundary_is_anywhere_in_the_output(self):
        code, line, err = self.run_derive()
        self.assertEqual(code, 0, line)
        with open(self.out_path(), encoding="utf-8") as f:
            draft_text = f.read()
        everything = "\n".join([draft_text, line, err, self.all_home_text()])
        for c in canaries():
            self.assertNotIn(c, everything, "새는 값이 있다")
        # 초안에 있는 글자 가운데 숫자는 한 자리 칸뿐이다 (경계값 · 정확한 수 없음)
        import re
        draft = json.loads(draft_text)
        for row in draft["sample"]["rows"]:
            for cell in row:
                self.assertTrue((isinstance(cell, int) and 0 <= cell <= 9) or cell == "PH_other" or scan.TOKEN_RE.fullmatch(cell))
        no_tokens = scan.remove_tokens(json.dumps(draft["sample"], ensure_ascii=False), " ")
        self.assertIsNone(re.search(r"[0-9]{2,}", no_tokens))
        self.assertEqual(set(draft), {"format", "kind", "data_class", "goal", "ask", "sample"})

    def test_the_prompts_do_not_show_column_names_or_paths(self):
        code, line, err = self.run_derive()
        self.assertEqual(code, 0, line)
        for c in canaries() + [self.tmp, self.csv, "kit.csv"]:
            self.assertNotIn(c, err)

    def test_the_picked_columns_are_not_stored_anywhere(self):
        self.run_derive()
        text = self.all_home_text()
        for c in [HEAD_NUM, HEAD_CAT, HEAD_SCORE, "bucket=", "=rank", "=category"]:
            self.assertNotIn(c, text)
        self.assertNotIn("sample", text)

    def test_audit_has_transform_kinds_counts_and_rows_only(self):
        self.run_derive()
        files = glob.glob(os.path.join(self.home, "audit", "*", "J-0007-001-derive.json"))
        self.assertEqual(len(files), 1)
        with open(files[0], encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual(set(rec), {"format", "at", "job", "direction", "kind", "transforms", "columns", "rows",
                                    "tokens", "table_sha256", "source_rows"})
        self.assertEqual(rec["source_rows"], 10000)                              # 사람이 알려 준 원본 행 수 (정수 하나 · 값이 아니다)
        self.assertEqual((rec["direction"], rec["kind"], rec["columns"], rec["rows"], rec["transforms"]),
                         ("derive", "derive", 3, 50, {"bucket": 1, "rank": 1, "category": 1}))
        with open(self.out_path(), encoding="utf-8") as f:
            sample = json.load(f)["sample"]
        self.assertEqual(rec["table_sha256"], audit.table_sha256(sample))        # 표 글의 해시 · 토큰 수 (값 · 이름 · 토큰은 없다)
        self.assertEqual(rec["tokens"], len(derive.sample_tokens(sample)))
        self.assertEqual(audit.confirmed_hashes(self.home), set())              # 보낸 것이 아니라서 확정 목록에 끼지 않는다
        self.assertEqual(audit.job_states(self.home), [])

    def test_same_input_gives_same_output_for_numbers(self):
        picks = ["%s=bucket" % HEAD_NUM, "%s=rank" % HEAD_SCORE]
        self.run_derive(text=dialog(picks=picks), out=self.out_path("a.json"))
        self.run_derive(text=dialog(job="J-0008", picks=picks), out=self.out_path("b.json"))
        with open(self.out_path("a.json"), encoding="utf-8") as f:
            a = f.read()
        with open(self.out_path("b.json"), encoding="utf-8") as f:
            b = f.read()
        self.assertEqual(json.loads(a)["sample"]["rows"], json.loads(b)["sample"]["rows"])
        self.assertEqual([c["kind"] for c in json.loads(a)["sample"]["columns"]], ["수치", "수치"])

    def test_same_input_same_table_gives_same_category_output(self):
        header, rows = derive.read_table(self.csv)
        t = PseudonymTable()
        picks = [(0, "bucket", None), (1, "category", None), (2, "rank", None)]
        a = derive.build_sample(header, rows, picks, 10, t)
        b = derive.build_sample(header, rows, picks, 10, t)
        self.assertEqual(a, b)

    def test_row_order_of_the_source_does_not_show(self):
        header, rows = derive.read_table(self.csv)
        t = PseudonymTable()
        picks = [(0, "bucket", None), (1, "category", None), (2, "rank", None)]
        a = derive.build_sample(header, rows, picks, 10, t)[0]
        b = derive.build_sample(header, list(reversed(rows)), picks, 10, t)[0]
        self.assertEqual(a["rows"], b["rows"])

    def test_column_tokens_are_per_run_random(self):
        self.run_derive(out=self.out_path("a.json"))
        self.run_derive(text=dialog(job="J-0008"), out=self.out_path("b.json"))
        with open(self.out_path("a.json"), encoding="utf-8") as f:
            a = [c["token"] for c in json.load(f)["sample"]["columns"]]
        with open(self.out_path("b.json"), encoding="utf-8") as f:
            b = [c["token"] for c in json.load(f)["sample"]["columns"]]
        self.assertNotEqual(a, b)                                   # 자문마다 새 토큰 (AL-05)

    def test_the_draft_passes_the_checker_with_the_run_tokens(self):
        self.run_derive()
        with open(self.out_path(), encoding="utf-8") as f:
            text = f.read()
        toks = set(scan.find_tokens(text))
        pol = scan.Policy(words=WORDS, real_data=True, tokens=toks)
        self.assertTrue(scan.check_brief(json.loads(text), pol)["ok"])
        self.assertFalse(scan.check_brief(json.loads(text), scan.Policy(words=WORDS, real_data=True))["ok"])      # 표에 없는 토큰
        self.assertFalse(scan.check_brief(json.loads(text), scan.Policy(words=WORDS, real_data=False, tokens=toks))["ok"])

    def test_refuses_without_the_human_saying_yes_or_with_a_bad_dialog(self):
        for text in (dialog(go="n"), dialog(go=""), dialog(job="J-7"), dialog(job=""), dialog(k="abc"), dialog(picks=["nonsense"]),
                     dialog(picks=["99=rank"]), dialog(picks=["2=bucket"]), dialog(picks=["1=rank:0.2,0.4,0.6,0.8"]),
                     dialog(picks=["1=bucket", "1=rank"]), dialog(picks=[]), "J-0007\n", ""):
            code, line, _ = self.run_derive(text=text, out=self.out_path("x.json"))
            self.assertEqual(code, 2, text)
            self.assertFalse(json.loads(line)["derived"])
            self.assertFalse(os.path.exists(self.out_path("x.json")), text)
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 0)

    def test_k_larger_than_the_table_allows_is_refused(self):
        code, line, _ = self.run_derive(text=dialog(k="30"))
        self.assertEqual((code, json.loads(line)["error"]), (2, "E-31"))

    def test_k_below_ten_is_refused(self):
        for k in ("4", "5", "9"):
            code, line, _ = self.run_derive(text=dialog(k=k))
            self.assertEqual((code, json.loads(line)["error"]), (2, "E-31"), k)
        self.assertEqual(self.run_derive(text=dialog(k="10"))[0], 0)

    def test_nine_picks_is_refused(self):
        picks = ["%s=bucket" % HEAD_NUM] * 9
        code, line, _ = self.run_derive(text=dialog(picks=picks))
        self.assertEqual((code, json.loads(line)["error"]), (2, "E-31"))

    def test_does_not_overwrite_an_existing_file(self):
        with open(self.out_path(), "w") as f:
            f.write("keep")
        code, line, _ = self.run_derive()
        self.assertEqual(code, 0)
        with open(self.out_path(), encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep")

    def test_a_missing_dictionary_blocks(self):
        os.unlink(config.dictionary_path(self.home))
        code, line, _ = self.run_derive()
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(self.out_path()))
        self.assertEqual(audit.derived_rows(self.home, "J-0007"), 0)

    def test_a_missing_csv_is_a_usage_error(self):
        code, line, _ = self.run_derive(csv=os.path.join(self.tmp, "nothing.csv"))
        self.assertEqual((code, json.loads(line)["error"]), (2, "E-04"))

    def test_the_real_column_name_in_the_dictionary_does_not_matter_for_the_cells(self):
        self.configure(words=WORDS + [HEAD_CAT])
        code, line, _ = self.run_derive()
        self.assertEqual(code, 0, line)

    def test_pick_by_header_text_or_by_number(self):
        header = ["alpha", "beta", "2"]
        self.assertEqual(derive.parse_pick("alpha=rank", header)[0], 0)
        self.assertEqual(derive.parse_pick("2=category", header)[0], 2)          # 머리 글이 먼저다
        self.assertEqual(derive.parse_pick("1=rank", header)[0], 0)
        self.assertEqual(derive.parse_pick("beta=bucket:0.1,0.3,0.5,0.7", header)[2][0], derive.Fraction(1, 10))
        with self.assertRaises(DeriveError):
            derive.parse_pick("alpha=rank", ["alpha", "alpha"])

    def test_corpus_self_test_still_passes_and_prints_no_canary(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        p = subprocess.run([sys.executable, os.path.join(ROOT, "kit", "leak_rate.py"), "--self-test", "--with-checker"],
                           cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        out = p.stdout.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, out[-800:])
        self.assertIn("good_brief 통과 40/40", out)
        self.assertIn("leaky_briefs 막음 120/120", out)
        words = set()
        for path in glob.glob(os.path.join(ROOT, "kit", "corpus", "tasks", "*.json")):
            with open(path, encoding="utf-8") as f:
                task = json.load(f)
            for c in task["canaries"]:
                words.add(c["value"])
                words.update(c.get("aliases", []))
        for w in words:
            self.assertNotIn(w, out)


# ---------------------------------------------------------------- 스키마 · check_brief

TOK_A, TOK_B, TOK_C = "PH_AB23", "PH_CD45", "PH_EF67"


def sample_brief(rows=None, columns=None, **extra):
    cols = columns if columns is not None else [{"token": TOK_A, "kind": "수치"}, {"token": TOK_B, "kind": "범주"}]
    rws = rows if rows is not None else [[i % 10, TOK_C if i % 3 else "PH_other"] for i in range(12)]
    b = {"format": 1, "kind": "plan", "data_class": "synthetic", "goal": "표의 열 구성을 이해한다",
         "ask": "화면 구성을 제안해 달라", "sample": {"columns": cols, "rows": rws}}
    b.update(extra)
    return b


def policy(**kw):
    args = dict(words=WORDS, tokens=[TOK_A, TOK_B, TOK_C])
    args.update(kw)
    return scan.Policy(**args)


def hit_checks(res):
    return set(h["check"] for h in res.get("hits", []))


class SchemaAndChecks(unittest.TestCase):
    def schema_errors(self, brief):
        return briefschema.validate(brief, briefschema.load_schema(briefschema.default_schema_path()))

    def test_a_good_sample_passes_schema_and_checker(self):
        b = sample_brief()
        self.assertEqual(self.schema_errors(b), [])
        self.assertTrue(scan.check_brief(b, policy())["ok"])

    def test_ui_kind_is_allowed_too(self):
        self.assertTrue(scan.check_brief(sample_brief(kind="ui"), policy())["ok"])

    def test_digits_zero_to_nine_are_the_only_numbers(self):
        for n in range(10):
            rows = [[n, TOK_C]] * 12
            self.assertEqual(self.schema_errors(sample_brief(rows=rows)), [], n)

    def test_cells_out_of_range_or_wrong_type_are_blocked_by_the_schema(self):
        for bad in (10, -1, 99, 100, 3.5, 3.0, 1e1, True, False, None, "7", "12", "abc", "PH_other ", " PH_other",
                    "ph_other", "PH_OTHER", "PH_K7Q", "PH_AB21", "3 4", "٣", "①", ["1"], {"a": 1}, "일반 글이다"):
            rows = [[bad, TOK_C]] + [[1, TOK_C]] * 11
            errs = self.schema_errors(sample_brief(rows=rows))
            self.assertTrue(errs, repr(bad))
            res = scan.check_brief(sample_brief(rows=rows), policy())
            self.assertFalse(res["ok"], repr(bad))
            self.assertIn("D1", hit_checks(res), repr(bad))

    def test_sample_shape_limits(self):
        ok_rows = [[1, TOK_C]] * 12
        too_many_cols = [{"token": "PH_%s" % (c * 4), "kind": "수치"} for c in "23456789A"]
        self.assertTrue(self.schema_errors(sample_brief(columns=too_many_cols, rows=[[1] * 9] * 12)))
        self.assertTrue(self.schema_errors(sample_brief(rows=[[1, TOK_C]] * 51)))
        self.assertTrue(self.schema_errors(sample_brief(rows=[[1, TOK_C]] * 9)))               # 작은 표 (k 최소 5 의 두 배 미만)
        self.assertTrue(self.schema_errors(sample_brief(rows=[])))
        self.assertTrue(self.schema_errors(sample_brief(columns=[])))
        self.assertTrue(self.schema_errors(sample_brief(columns=[{"token": TOK_A, "kind": "글"}], rows=[[1]] * 12)))
        self.assertTrue(self.schema_errors(sample_brief(columns=[{"token": "열이름", "kind": "수치"}, {"token": TOK_B, "kind": "범주"}])))
        b = sample_brief()
        b["sample"]["extra"] = 1
        self.assertTrue(self.schema_errors(b))
        b = sample_brief()
        b["sample"]["columns"][0]["name"] = "x"
        self.assertTrue(self.schema_errors(b))
        self.assertEqual(self.schema_errors(sample_brief(rows=ok_rows)), [])

    def test_sample_is_only_for_plan_and_ui(self):
        lib = {"format": 1, "kind": "lib", "data_class": "synthetic", "library": {"name": "pandas"}, "goal": "g", "ask": "a",
               "sample": sample_brief()["sample"]}
        rep = {"format": 1, "kind": "report", "data_class": "synthetic", "job": "J-0001", "status": "done", "summary": ["s"],
               "sample": sample_brief()["sample"]}
        self.assertTrue(self.schema_errors(lib))
        self.assertTrue(self.schema_errors(rep))

    def test_one_sample_per_brief(self):
        b = sample_brief()
        self.assertNotIn("samples", b)
        b["samples"] = [b["sample"]]
        self.assertTrue(self.schema_errors(b))

    def test_row_width_and_cell_kind_must_match_the_columns(self):
        rows = [[1, TOK_C]] * 11 + [[1]]
        res = scan.check_brief(sample_brief(rows=rows), policy())
        self.assertEqual(hit_checks(res), {"D1"})
        self.assertIn("sample.rows[11]", res["hits"][0]["where"])
        rows = [[1, TOK_C]] * 11 + [[TOK_C, 1]]                     # 수치 열에 토큰 · 범주 열에 숫자
        res = scan.check_brief(sample_brief(rows=rows), policy())
        self.assertIn("D1", hit_checks(res))
        res = scan.check_brief(sample_brief(rows=[[1, TOK_C, 2]] * 12), policy())
        self.assertIn("D1", hit_checks(res))

    def test_duplicate_column_token_is_blocked(self):
        cols = [{"token": TOK_A, "kind": "수치"}, {"token": TOK_A, "kind": "수치"}]
        res = scan.check_brief(sample_brief(columns=cols, rows=[[1, 2]] * 12), policy())
        self.assertIn("D1", hit_checks(res))

    def test_unknown_column_or_cell_tokens_are_blocked_by_d6(self):
        res = scan.check_brief(sample_brief(), policy(tokens=[TOK_A, TOK_B]))                   # TOK_C 가 표에 없다
        self.assertEqual(hit_checks(res), {"D6"})
        self.assertIn("sample.rows[1][1]", res["hits"][0]["where"])
        res = scan.check_brief(sample_brief(), policy(tokens=[TOK_B, TOK_C]))
        self.assertEqual(hit_checks(res), {"D6"})
        self.assertIn("sample.columns[0].token", res["hits"][0]["where"])
        self.assertTrue(scan.check_brief(sample_brief(), policy(tokens=[TOK_A, TOK_B, TOK_C]))["ok"])

    def test_pooled_marker_needs_no_table_entry(self):
        rows = [[1, "PH_other"]] * 12
        self.assertTrue(scan.check_brief(sample_brief(rows=rows), policy(tokens=[TOK_A, TOK_B]))["ok"])

    def test_numbers_hidden_in_cells_are_caught(self):
        # 두 자리 이상 수 · 소수점 · 공백 포함 글 · 전각 · 문자열 숫자 - 셀 하나로 수치를 옮기는 변형이 모두 걸린다
        for bad in (12, 350, 3.5, 0.5, "12", "3.5", "3 5", "3 5 0", "３", "３５", "1,2", "-1", "+1", "1e1", "PH_other 3", "3\n4"):
            rows = [[bad, TOK_C]] + [[1, TOK_C]] * 11
            res = scan.check_brief(sample_brief(rows=rows), policy())
            self.assertFalse(res["ok"], repr(bad))
            self.assertIn("D1", hit_checks(res), repr(bad))

    def test_a_value_split_across_cells_hits_the_dictionary(self):
        # 사전에 숫자 글 (실값) 이 있으면 한 행의 칸을 이어 붙여 만든 값도 D2 가 본다
        three = [{"token": t, "kind": "수치"} for t in ("PH_AB23", "PH_CD45", "PH_EF67")]
        b = sample_brief(columns=three, rows=[[3, 5, 0]] * 12)
        res = scan.check_brief(b, policy(words=WORDS + ["350"]))
        self.assertIn("D2", hit_checks(res))
        self.assertTrue(scan.check_brief(b, policy())["ok"])

    def test_free_text_still_blocks_digits_next_to_a_sample(self):
        b = sample_brief(goal="온도 350 의 표")
        res = scan.check_brief(b, policy())
        self.assertIn("D4", hit_checks(res))

    def test_data_class_real_needs_real_data(self):
        b = sample_brief(data_class="real")
        self.assertIn("D1", hit_checks(scan.check_brief(b, policy(real_data=False))))
        self.assertTrue(scan.check_brief(b, policy(real_data=True))["ok"])

    def test_render_has_a_closed_frame(self):
        text = render(sample_brief())
        lines = text.split("\n")
        i = lines.index("SAMPLE: coarse cells (bucket or rank class, not values; PH_other = pooled rare group)")
        self.assertEqual(lines[i + 1], "| %s (수치) | %s (범주) |" % (TOK_A, TOK_B))
        self.assertEqual(lines[i + 2], "|---|---|")
        self.assertEqual(lines[i + 3], "| 0 | PH_other |")
        self.assertEqual(lines[i + 4], "| 1 | %s |" % TOK_C)
        self.assertEqual(len(lines[i + 3:i + 15]), 12)
        self.assertTrue(lines[i + 15].startswith("ASK: "))
        self.assertLess(text.index("GOAL:"), text.index("SAMPLE:"))
        self.assertTrue(text.endswith("[/diode brief]\n"))

    def test_render_without_a_sample_is_unchanged(self):
        b = sample_brief()
        del b["sample"]
        self.assertNotIn("SAMPLE", render(b))

    def test_size_limit_still_applies(self):
        cols = [{"token": "PH_%s" % (c * 4), "kind": "수치"} for c in "23456789"]
        b = sample_brief(columns=cols, rows=[[1] * 8] * 50)
        self.assertLess(len(render(b).encode("utf-8")), scan.MAX_RENDERED_BYTES)
        self.assertTrue(scan.check_brief(b, policy(tokens=[c["token"] for c in cols]))["ok"])

    def test_the_frame_is_rechecked_on_the_rendered_text(self):
        # 펼친 글이 닫힌 틀이 아니면 (render 가 바뀌어 틀을 벗어나면) D1 - 다시 읽는 검사가 따로 있다
        b = sample_brief()
        with mock.patch.object(scan, "sample_lines", lambda s: ["SAMPLE: other", "| x |", "|---|"]):
            res = scan.check_brief(b, policy())
        self.assertIn("D1", hit_checks(res))
        real = scan.sample_lines

        def wide(sample):
            lines = real(sample)
            return lines[:3] + ["| 12 | PH_other |"] + lines[4:]
        with mock.patch.object(scan, "sample_lines", wide), mock.patch.object(scan, "render", lambda b: "\n".join(wide(b["sample"])) + "\n"):
            res = scan.check_brief(b, policy())
        self.assertIn("D1", hit_checks(res))


if __name__ == "__main__":
    unittest.main()
