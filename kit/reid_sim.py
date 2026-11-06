#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KIT-3b L2 파생 표본의 재식별 위험 시뮬레이션 (작업 T3b) - 방어 평가.

`diode.py derive` (diodelib/derive.py) 는 실값 표를 bucket (0-4) · rank (0-9) · category (가명 토큰 · k 미만은 PH_other) 로
거칠게 줄여 내보낸다. 문서는 "재식별이 안 된다고 증명할 수 없다" 고 인정한다 (SPEC SP-18). 이 도구는 **지어낸 표** 로
"공격자가 얼마나 맞히는가" 를 재서 보안 담당이 합격선을 정할 숫자를 만든다.

위협 모델 (공격자 하나)
  - 공격자는 원본 표의 일부 열 (보조 열 0-3개) 의 **정확한 값을 모든 원본 행에 대해** 안다 (예: 외부 명부). 나머지 열은 모른다.
  - 공격자는 내보낸 파생 표를 본다 (행 순서는 칸 값으로 정렬돼 원본 순서 정보가 없다).
  - 최악에 가깝게 잡는다: 칸 나눔 규칙 (경계) 과 가명 토큰이 어느 값인지도 안다고 본다.
  - 목표: 파생 행 하나가 원본의 어느 행인지 맞히기 (연결). 후보 = 원본 **전체** 중 그 파생 행과 호환되는 행
    (표본은 원본의 50행뿐이므로 후보는 표본이 아니라 원본 전체에서 센다).

잰 것
  1 유일 재식별률      후보가 정확히 1개인 파생 행의 비율 (후보에는 진짜 원본 행이 늘 들어 있으므로 1개면 곧 맞힌 것)
  2 후보 집합 크기     평균 · 중앙값 · 최소 (익명성 k)
  3 속성 추론          보조 열이 호환되는 파생 행들에서 숨은 열의 최빈값을 찍었을 때 맞는 비율 vs 아무것도 모를 때 (전체 최빈값)
  4 모자이크           서로 겹치지 않는 표본 50행 x job 1-4개 (누계 200행 한도) 를 모았을 때. "이미 다른 파생 행의 유일한 후보로 밝혀진
                      원본 행은 빼기" 를 되풀이하는 소거를 더한 숫자도 함께 낸다
  5 한계 점검          bucket vs rank · 열 수 · 원본 행 수 · 범주 가짓수 · 이상치 · 분포

변환은 diodelib.derive 의 함수를 **그대로 불러** 쓴다 (build_sample 로 한도 · 정렬까지 거친 표와 열별 변환 결과가 같은지 매번 맞춰 본다).
출력은 숫자 요약뿐이다 - 합성 표의 칸 값 · 범주 값을 찍지 않는다. 결정적 (고정 시드). 표준 라이브러리만 · Python 3.8 이상.

쓰는 법
    python kit/reid_sim.py [--quick] [--json 파일] [--seed 정수]

종료 코드: 0 끝남 · 2 사용법 오류.
"""
import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
from bisect import bisect_left, bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from diodelib import derive  # noqa: E402
from diodelib.render import SAMPLE_OTHER  # noqa: E402
from diodelib.seal import PseudonymTable  # noqa: E402

DEFAULT_SEED = 20260
SAMPLE_ROWS = derive.MAX_ROWS            # 표본 한 번의 행 (derive 의 한도 그대로)
TOPIC_LIMIT = derive.MAX_TOPIC_ROWS      # 한 주제의 누계 한도
BASE = {"n": 1000, "cols": 4, "transform": "bucket", "card": 20, "dist": "uniform",
        "aux": 2, "jobs": 1, "outlier": False, "rows": SAMPLE_ROWS, "k": derive.DEFAULT_K}


# ───────────────────────────────────────────────────────── 합성 표 (전부 난수 · 진짜 자료 없음)

def _seed_of(seed, label):
    h = hashlib.sha256(("%d|%s" % (seed, label)).encode("utf-8")).hexdigest()
    return int(h[:12], 16)


def make_table(rng, n, cols, card, dist, outlier):
    """(열 목록, 종류 목록). 열은 번갈아 수치 · 범주. 수치는 정수, 범주는 `RV###` 꼴의 지어낸 이름.

    outlier 면 0번 행이 이상치 한 건: 첫 수치 열이 최댓값의 1000배이고 범주 열은 이 표에 하나뿐인 값이다.
    """
    kinds = ["num" if i % 2 == 0 else "cat" for i in range(cols)]
    weights = None
    if dist == "skew":
        acc, tot = [], 0.0
        for i in range(card):
            tot += 1.0 / ((i + 1) ** 1.3)
            acc.append(tot)
        weights = acc
    data = []
    for kind in kinds:
        if kind == "num":
            if dist == "skew":
                col = [int(rng.lognormvariate(0, 1.2) * 100) for _ in range(n)]
            else:
                col = [rng.randint(0, 9999) for _ in range(n)]
        else:
            if weights is None:
                col = ["RV%03d" % rng.randrange(card) for _ in range(n)]
            else:
                col = ["RV%03d" % c for c in rng.choices(range(card), cum_weights=weights, k=n)]
        data.append(col)
    if outlier:
        first_num = True
        for ci, kind in enumerate(kinds):
            if kind == "num" and first_num:
                data[ci][0] = max(data[ci]) * 1000 + 7
                first_num = False
            elif kind == "cat":
                data[ci][0] = "RVxOUT%d" % ci
    return data, kinds


# ───────────────────────────────────────────────────────── 파생 한 번 (derive 의 함수를 그대로 부른다)

class Job(object):
    """job 하나의 파생 결과와, 공격자가 아는 보조 열의 호환 규칙."""

    def __init__(self, idx, cells, labels, okey, groups):
        self.idx = idx              # 표본의 원본 행 번호 (표본 안 순서)
        self.cells = cells          # 열마다 표본 순서의 칸 값
        self.labels = labels        # 열마다 표본 순서의 같은 뜻 이름표 (토큰 -> 원래 값. 숫자는 칸 번호)
        self.okey = okey            # 원본 행마다: 보조 열별 "이 원본이 낼 수 있는 칸" 집합의 튜플
        self.groups = groups        # okey -> 원본 행 번호 목록


def _allowed_numeric(values, cells, transform):
    """표본의 (값, 칸) 에서 임의의 원본 값 x 가 낼 수 있는 칸 집합을 만드는 함수.

    bucket 의 경계는 표본 값 중에 있으므로 x 의 칸은 'x 이하인 가장 큰 표본 값' 의 칸과 같다 (정확).
    rank 는 표본 안 순위라 이웃 표본 값 두 칸 사이로 잡는다 (공격자에게 너그러운 쪽: 후보를 줄이지 않는다).
    """
    pairs = sorted(set(zip(values, cells)))
    sv = [p[0] for p in pairs]
    sc = [p[1] for p in pairs]
    top = 4 if transform == "bucket" else 9
    memo = {}

    def allowed(x):
        got = memo.get(x)
        if got is None:
            p = bisect_right(sv, x)
            lo = sc[p - 1] if p > 0 else 0
            if transform == "bucket":
                got = frozenset((lo,))
            else:
                q = bisect_left(sv, x)
                hi = sc[q] if q < len(sv) else top
                got = frozenset(range(min(lo, hi), max(lo, hi) + 1))
            memo[x] = got
        return got
    return allowed


def build_job(data, kinds, idx, transform, k, aux):
    """원본 data 의 idx 행을 derive 로 파생하고, 보조 열 aux 에 대한 호환 규칙을 만든다."""
    header = ["c%d" % i for i in range(len(kinds))]
    picks = [(c, "category" if kinds[c] == "cat" else transform, None) for c in range(len(kinds))]
    table = PseudonymTable()
    rows_text = [[str(data[c][i]) for c in range(len(kinds))] for i in idx]
    sample, _counts = derive.build_sample(header, rows_text, picks, k, table)     # 한도 · 정렬까지 실제 경로

    cells, labels = [], []
    for c, kind in enumerate(kinds):
        vals = [data[c][i] for i in idx]
        if kind == "num":
            if transform == "bucket":
                cc = derive.bucket_cells([float(v) for v in vals], derive.parse_quantiles(None))
            else:
                cc = derive.rank_cells([float(v) for v in vals])
            lab = list(cc)
        else:
            cc = derive.category_cells(vals, k, table)
            lab = [SAMPLE_OTHER if t == SAMPLE_OTHER else v for v, t in zip(vals, cc)]
        cells.append(cc)
        labels.append(lab)
    # 열별 변환이 build_sample 이 낸 표와 같은 뜻인지 맞춰 본다 (복사본이 어긋나면 여기서 멈춘다)
    mine = sorted(repr(list(r)) for r in zip(*cells))
    ref = sorted(repr(list(r)) for r in sample["rows"])
    if mine != ref:
        raise RuntimeError("열별 변환이 build_sample 과 다르다")

    fns = []
    for a in aux:
        vals = [data[a][i] for i in idx]
        if kinds[a] == "num":
            fns.append(_allowed_numeric([float(v) for v in vals], cells[a], transform))
        else:
            vmap = {}
            for v, t in zip(vals, cells[a]):
                vmap[v] = t
            fns.append(_cat_allowed(vmap))
    okey, groups = [], {}
    n = len(data[0])
    for i in range(n):
        key = tuple(fn(data[a][i] if kinds[a] == "cat" else float(data[a][i])) for fn, a in zip(fns, aux))
        okey.append(key)
        groups.setdefault(key, []).append(i)
    return Job(idx, cells, labels, okey, groups)


def _cat_allowed(vmap):
    other = frozenset((SAMPLE_OTHER,))
    memo = {}

    def allowed(v):
        got = memo.get(v)
        if got is None:
            t = vmap.get(v)
            got = frozenset((t,)) if t is not None else other
            memo[v] = got
        return got
    return allowed


# ───────────────────────────────────────────────────────── 지표

def _compat(dkey, okey):
    for a, cell in enumerate(dkey):
        if cell not in okey[a]:
            return False
    return True


class Derived(object):
    __slots__ = ("job", "pos", "src", "dkey", "raw", "excl")


def _derived_rows(jobs, aux):
    out = []
    for j, job in enumerate(jobs):
        gcount = {}
        for p, i in enumerate(job.idx):
            d = Derived()
            d.job, d.pos, d.src = j, p, i
            d.dkey = tuple(job.cells[a][p] for a in aux)
            got = gcount.get(d.dkey)
            if got is None:
                got = sum(len(m) for key, m in job.groups.items() if _compat(d.dkey, key))
                gcount[d.dkey] = got
            d.raw = got
            d.excl = got
            out.append(d)
    return out


def _exclude(jobs, rows):
    """소거: 후보가 하나로 밝혀진 원본 행은 다른 파생 행의 후보에서 뺀다. 더 못 줄 때까지 되풀이.

    파생 행마다 원본 행이 다르다는 사실 (표본은 겹치지 않는다) 만 쓴다. 각 d.excl 을 채운다.
    """
    taken = {}                       # 원본 행 -> 그 행으로 밝혀진 파생 행
    changed = True
    while changed:
        changed = False
        for d in rows:
            if d in taken.values():
                continue
            gone = 0
            for o, dd in taken.items():
                if dd is not d and _compat(d.dkey, jobs[d.job].okey[o]):
                    gone += 1
            d.excl = d.raw - gone
            if d.excl == 1:
                for key, members in jobs[d.job].groups.items():
                    if not _compat(d.dkey, key):
                        continue
                    for o in members:
                        if o not in taken:
                            taken[o] = d
                            changed = True
                            break
                    else:
                        continue
                    break
    for d in rows:
        gone = 0
        for o, dd in taken.items():
            if dd is not d and _compat(d.dkey, jobs[d.job].okey[o]):
                gone += 1
        d.excl = d.raw - gone


def _mode(items):
    cnt = {}
    for x in items:
        cnt[x] = cnt.get(x, 0) + 1
    best = max(cnt.values())
    return sorted((x for x, c in cnt.items() if c == best), key=lambda x: (isinstance(x, str), x))[0]


def _attr_inference(jobs, rows, aux, ncols):
    """(맞힌 수 합, 기준선 맞힌 수 합, 시도 수 합). 표적 = 표본에 든 원본 행 (숨은 열마다 한 번씩)."""
    hidden = [c for c in range(ncols) if c not in aux]
    if not hidden:
        return None
    hit = base = tries = 0
    for h in hidden:
        pool = [jobs[d.job].labels[h][d.pos] for d in rows]
        bmode = _mode(pool)
        for t in rows:
            truth = jobs[t.job].labels[h][t.pos]
            near = [jobs[d.job].labels[h][d.pos] for d in rows
                    if _compat(d.dkey, jobs[d.job].okey[t.src])]
            guess = _mode(near) if near else bmode
            hit += 1 if guess == truth else 0
            base += 1 if bmode == truth else 0
            tries += 1
    return hit, base, tries


def evaluate_jobs(jobs, aux, ncols, force=None):
    """이미 만든 job 들을 한 번 평가한다 -> 지표 사전 (표 값 없음)."""
    rows = _derived_rows(jobs, aux)
    _exclude(jobs, rows)
    out = {"raw": [d.raw for d in rows], "excl": [d.excl for d in rows],
           "attr": _attr_inference(jobs, rows, aux, ncols), "outlier": None}
    if force is not None:
        for d in rows:
            if d.src == force:
                out["outlier"] = (d.raw, d.excl)
    return out


def aux_sets(seed, cols, aux_n, limit):
    """보조 열 조합. 가능한 조합이 limit 이하면 전부, 아니면 시드로 고정한 limit 개 (J · 변환이 달라도 같은 조합을 써서 비교가 공정하다)."""
    from itertools import combinations
    allc = list(combinations(range(cols), aux_n))
    if len(allc) <= limit:
        return [list(c) for c in allc]
    rng = random.Random(_seed_of(seed, "aux|%d|%d" % (cols, aux_n)))
    return [list(c) for c in sorted(rng.sample(allc, limit))]


def run_eval(data, kinds, jobs_n, rows_n, aux, transform, k, rng, force=None):
    n = len(data[0])
    if jobs_n * rows_n > min(n, TOPIC_LIMIT):
        return None
    rest = [i for i in range(n) if i != force]
    take = jobs_n * rows_n - (1 if force is not None else 0)
    chosen = rng.sample(rest, take)
    if force is not None:
        chosen = [force] + chosen
    jobs = [build_job(data, kinds, chosen[j * rows_n:(j + 1) * rows_n], transform, k, aux) for j in range(jobs_n)]
    return evaluate_jobs(jobs, aux, len(kinds), force)


def _stat(counts):
    s = sorted(counts)
    return {"unique": sum(1 for c in s if c == 1) / float(len(s)), "mean": sum(s) / float(len(s)),
            "median": float(statistics.median(s)), "min": s[0]}


def scenario(params, data_cache, seed, reps, aux_draws):
    """시나리오 하나 -> 숫자 사전. data_cache 는 같은 표를 여러 시나리오가 나눠 쓰게 한다."""
    p = dict(BASE)
    p.update(params)
    p["aux"] = min(p["aux"], p["cols"])
    tkey = (p["n"], p["cols"], p["card"], p["dist"], p["outlier"])
    if tkey not in data_cache:
        data_cache[tkey] = make_table(random.Random(_seed_of(seed, "table%r" % (tkey,))), p["n"], p["cols"],
                                      p["card"], p["dist"], p["outlier"])
    data, kinds = data_cache[tkey]
    label = "|".join("%s=%s" % (key, p[key]) for key in sorted(p))
    rng = random.Random(_seed_of(seed, "eval|" + label))
    raws, excls, hit, base, tries, outl = [], [], 0, 0, 0, []
    done = 0
    rows_n, k = p["rows"], p["k"]
    combos = aux_sets(seed, p["cols"], p["aux"], aux_draws)
    for aux in [c for c in combos for _ in range(reps)]:
        r = run_eval(data, kinds, p["jobs"], rows_n, aux, p["transform"], k, rng,
                     force=0 if p["outlier"] else None)
        if r is None:
            return dict(p, skipped=True, label=label)
        done += 1
        raws += r["raw"]
        excls += r["excl"]
        if r["attr"] is not None:
            hit += r["attr"][0]
            base += r["attr"][1]
            tries += r["attr"][2]
        if r["outlier"] is not None:
            outl.append(r["outlier"])
    s1, s2 = _stat(raws), _stat(excls)
    exposed = p["jobs"] * rows_n
    res = dict(p)
    res.update({
        "label": label, "skipped": False, "evals": done, "exposed_rows": exposed,
        "exposed_frac": exposed / float(p["n"]),
        "unique_rows": s2["unique"] * exposed,
        "unique_rate": s1["unique"], "cand_mean": s1["mean"], "cand_median": s1["median"], "cand_min": s1["min"],
        "unique_rate_excl": s2["unique"], "cand_mean_excl": s2["mean"], "cand_min_excl": s2["min"],
        "attr_acc": (hit / float(tries)) if tries else None,
        "attr_base": (base / float(tries)) if tries else None,
        "outlier_unique_rate": (sum(1 for o in outl if o[0] == 1) / float(len(outl))) if outl else None,
        "outlier_cand_mean": (sum(o[0] for o in outl) / float(len(outl))) if outl else None,
    })
    return res


# ───────────────────────────────────────────────────────── 시나리오 목록

def scenarios_full():
    out = []
    seen = set()

    def add(**kw):
        key = tuple(sorted(dict(BASE, **kw).items()))
        if key not in seen:
            seen.add(key)
            out.append(kw)
    # 가: 주 격자 - 원본 행 x 열 x 변환 x 범주 가짓수 (보조 열 2개 · job 1과 4)
    for n in (100, 1000, 10000):
        for cols in (2, 4, 8):
            for tr in ("bucket", "rank"):
                for card in (5, 20, 200):
                    for jobs in (1, 2, 4):
                        add(n=n, cols=cols, transform=tr, card=card, jobs=jobs)
    # 나: 보조 열 3개 (더 센 공격자)
    for n in (100, 1000, 10000):
        for cols in (4, 8):
            for tr in ("bucket", "rank"):
                for jobs in (1, 4):
                    add(n=n, cols=cols, transform=tr, aux=3, jobs=jobs)
    # 다: 기준 설정 한 칸씩 바꾸기
    for aux in (0, 1, 2, 3):
        for tr in ("bucket", "rank"):
            add(aux=aux, transform=tr)
    for jobs in (1, 2, 3, 4):
        for tr in ("bucket", "rank"):
            add(jobs=jobs, transform=tr)
    # 라: 권고의 근거 - 표본 행 수 · k 를 바꾸면 얼마나 줄어드나
    for n in (100, 1000):
        for tr in ("bucket", "rank"):
            for rows in (20, 30, 50):
                add(n=n, cols=8, transform=tr, aux=3, rows=rows)
                add(n=n, cols=4, transform=tr, aux=2, rows=rows, card=5)
            for kk in (5, 10, 25):
                add(n=n, cols=4, transform=tr, aux=2, card=5, k=kk)
    for tr in ("bucket", "rank"):
        for card in (5, 20, 200):
            add(dist="skew", card=card, transform=tr)
            add(dist="skew", card=card, transform=tr, jobs=4)
        add(outlier=True, transform=tr)
        add(outlier=True, transform=tr, aux=3)
        add(outlier=True, transform=tr, n=100)
    return out


def scenarios_quick():
    out = []
    for tr in ("bucket", "rank"):
        for aux in (0, 2):
            out.append(dict(n=1000, transform=tr, aux=aux, jobs=1))
        out.append(dict(n=1000, transform=tr, aux=2, jobs=4))
    out.append(dict(n=100, cols=4, aux=2, jobs=1))
    out.append(dict(n=100, cols=4, aux=2, jobs=2))
    out.append(dict(n=100, cols=8, transform="rank", aux=3, jobs=1))
    out.append(dict(n=100, cols=4, transform="rank", card=5, aux=2, jobs=2))
    out.append(dict(n=1000, cols=2, aux=2, card=5, jobs=1))
    out.append(dict(n=1000, cols=8, aux=3, card=200, jobs=1))
    out.append(dict(n=1000, dist="skew", aux=2, jobs=1))
    out.append(dict(n=1000, outlier=True, aux=2, jobs=1))
    return out


def run(quick=False, seed=DEFAULT_SEED, progress=None):
    reps, draws = (1, 3) if quick else (2, 6)
    cache = {}
    results = []
    for params in (scenarios_quick() if quick else scenarios_full()):
        results.append(scenario(params, cache, seed, reps, draws))
        if progress:
            progress(len(results))
    return {"seed": seed, "quick": bool(quick), "reps": reps, "aux_draws": draws, "results": results}


# ───────────────────────────────────────────────────────── 출력 (숫자 요약뿐)

def _pct(x):
    return "-" if x is None else "%5.1f%%" % (100.0 * x)


def _row(r):
    head = "%6d %3d %-6s %4d %-7s %3d %4d %4d %3d" % (
        r["n"], r["cols"], r["transform"], r["card"], r["dist"] + ("+이상치" if r["outlier"] else ""),
        r["aux"], r["jobs"], r["rows"], r["k"])
    if r.get("skipped"):
        return head + "  (누계 행이 원본 행 수나 200 한도를 넘어 건너뜀)"
    return head + " %7s %7s %8.1f %6.0f %5d %7s %7s%s" % (
        _pct(r["unique_rate"]), _pct(r["unique_rate_excl"]), r["cand_mean"], r["cand_median"], r["cand_min"],
        _pct(r["attr_acc"]), _pct(r["attr_base"]),
        ("  이상치 행 후보 평균 %.1f" % r["outlier_cand_mean"]) if r["outlier_cand_mean"] is not None else "")


HEADER = "%6s %3s %-6s %4s %-7s %3s %4s %4s %3s %7s %7s %8s %6s %5s %7s %7s" % (
    "원본행", "열", "변환", "범주", "분포", "보조", "job", "표본", "k", "유일", "소거후", "후보평균", "중앙값", "최소", "속성추론", "기준선")


def print_report(rep, out=None):
    out = out or sys.stdout
    out.write("재식별 시뮬레이션 (합성 표 · 시드 %d · %s · 시나리오마다 %d회 평균)\n" % (
        rep["seed"], "빠른 판" if rep["quick"] else "전체", rep["reps"] * rep["aux_draws"]))
    out.write("유일 = 후보 1개인 파생 행 비율 · 소거후 = 소거까지 한 유일 비율 · 후보 = 원본 전체 중 호환 행 수\n")
    out.write(HEADER + "\n")
    for r in rep["results"]:
        out.write(_row(r) + "\n")
    done = [r for r in rep["results"] if not r.get("skipped") and r["aux"] >= 1]     # 보조 열 0개는 기준선(대조)이라 순위에서 뺀다
    if done:
        top = sorted(done, key=lambda r: (-r["unique_rate_excl"], -r["unique_rate"], r["cand_mean_excl"]))
        out.write("\n가장 위험한 설정 3개 (소거 뒤 유일 재식별률 기준)\n")
        for r in top[:3]:
            out.write(_row(r) + "\n")
        out.write("가장 안전한 설정 3개\n")
        for r in sorted(done, key=lambda r: (r["unique_rate_excl"], r["unique_rate"], -r["cand_mean_excl"]))[:3]:
            out.write(_row(r) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="L2 파생 표본 재식별 위험 시뮬레이션 (합성 표 · 방어 평가)")
    ap.add_argument("--quick", action="store_true", help="CI 용 빠른 판 (10초 안)")
    ap.add_argument("--json", metavar="파일", help="숫자 요약을 JSON 으로 저장")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="난수 시드 (같은 시드 -> 같은 결과)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    t0 = time.time()
    rep = run(quick=args.quick, seed=args.seed)
    print_report(rep)
    sys.stdout.write("\n걸린 시간 %.1f초\n" % (time.time() - t0))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
