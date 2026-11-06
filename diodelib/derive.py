# -*- coding: utf-8 -*-
"""파생 표본 (L2) - 표 파일에서 실값이 아니라 아주 거칠게 줄인 값만 brief 의 닫힌 칸 `sample` 로 만든다
(docs/PROPOSAL-derived.md › 3.2 · 4 · SP-02 · SP-05 · SP-15 · 표준 라이브러리 · Python 3.8).

`python diode.py derive <csv 경로> --out <brief 초안 json 경로>` 가 부른다 - 사람이 안쪽 터미널에서 직접 돌린다.

변환은 이 셋뿐이고 결정적 코드가 한다 (사내 LLM 이 값을 보고 쓰지 않는다)
  bucket    수치 열 -> 사람이 허락한 분위수 경계로 0-4 다섯 칸 중 하나의 정수 (경계값은 나가지 않는다)
  rank      수치 열 -> 순위 백분위를 0-9 열 칸으로 (동률은 같은 칸 · 무작위 동점 깨기 없음)
  category  범주 열 -> 이 자문의 PseudonymTable 토큰 (메모리에만 · AL-05). 행이 k 미만인 값은 PH_other 하나로 묶는다
열 이름은 토큰 (PH_ 꼴) 과 종류 (수치 · 범주) 만 나간다. 고르지 않은 열은 나가지 않는다 (기본 전부 거부).
출력 행은 칸 값으로 정렬한다 - 원래 표의 행 순서 (시간 순서 · 크기 순서) 가 새지 않게 한다.

문 (AL-10 · AL-12 정신)
  - 설정 policy.derived_level 이 1 이고 policy.real_data 가 참일 때만 돈다 (effective_level). 켜는 곳은 정책 창뿐이다 -
    이 모듈은 설정을 읽기만 하고, 환경 변수 · 명령줄 인자 · 시험용 우회로 켜는 길이 없다.
  - 데이터 폴더가 기본 자리가 아니면 (DIODE_HOME) 돌지 않는다. 표준 입력이 터미널이 아니면 (파이프 · Claude 의 Bash) 돌지 않는다
    (run_command - 벽은 아니다 · 같은 계정의 셸 앞에서는 PC 안의 어떤 장치도 단단한 벽이 아니다 L-11).
  - 열 · 변환은 사람이 터미널에서 직접 고른다 (표준 입력). 고른 것은 파일에 저장하지 않는다.

한도 (넘으면 거절): 열 8 · 행 50 · 행 수 k x 2 미만 거절 (작은 표는 한 행이 곧 식별) · 한 주제 (job) 의 파생 누계 행 200 (L-05).
감사 기록에는 변환 종류별 열 수 · 행 수 · 토큰 수 · 표 글의 sha256 만 남긴다 (audit.derive_record - 값 · 열 이름 · 토큰 없음).

만든 초안이 나가는 길 (propose · 허브 · SP-18): 초안의 sample 표 글이 위 감사 기록의 sha256 과 맞아야 한다 (check_draft).
가명 표는 이 프로세스의 메모리에만 있다가 사라지므로 (D6) 허브의 표에는 이 토큰이 없다 - 그래서 이 초안의 토큰은 "일방향 토큰" 이다:
되돌릴 진짜 단어가 없고 (U1 에서는 모르는 토큰), D6 은 기록에 적힌 토큰 수 안의 정확한 꼴이면 통과시킨다.

출력은 코드 · 개수뿐이다 (AL-11) - 열 이름 · 값 · 경로 · 입력한 글을 찍지 않는다. 사람에게 묻는 글에도 열 이름은 없다.
종료 코드 (S-03): 0 만듦 · 1 점검 실패 (그 밖의 예외) · 2 사용법 · 꼴 오류 (검사에 걸림 포함) · 3 사람 확인 필요 (꺼짐 · 터미널 아님).
"""

import csv
import io
import json
import math
import os
import re
from collections import OrderedDict
from fractions import Fraction

from . import audit, config, scan
from .render import SAMPLE_OTHER
from .seal import PseudonymTable, seal
from .unseal import write_new

# ---------------------------------------------------------------- 상수 (코드가 정한다 · 설정 키로 풀리지 않는다)

MAX_COLUMNS = 8                 # 한 sample 의 열
MAX_ROWS = 50                   # 한 sample 의 행
MAX_TOPIC_ROWS = 200            # 한 주제 (job) 의 파생 자료 누계 행 (L-05)
DEFAULT_K = 10                  # 범주 억제 · 최소 셀 크기
MIN_K = 5
MAX_K = 25                      # 행 50 이 k x 2 이상이어야 한다
MAX_FILE_BYTES = 1024 * 1024    # 읽을 표 파일의 상한 (넘으면 행 한도 전에 거절)
MAX_FILE_COLUMNS = 256          # 표 파일의 열 상한 (고르는 열은 8 까지)
DEFAULT_QUANTILES = ("0.2", "0.4", "0.6", "0.8")
QUANTILE_MIN, QUANTILE_MAX, QUANTILE_GAP = Fraction(1, 10), Fraction(9, 10), Fraction(1, 10)     # 한 칸이 너무 작아 한 행을 가리키지 않게
TRANSFORMS = ("bucket", "rank", "category")
KIND_OF = {"bucket": "수치", "rank": "수치", "category": "범주"}

# 초안의 고정 글 - 숫자 · 단어가 없다 (사내 LLM 또는 사람이 고쳐 쓴다)
DRAFT_GOAL = "거칠게 줄인 표본으로 표의 열 구성을 이해한다"
DRAFT_ASK = "표본을 보고 화면에서 쓸 열 구성을 제안해 주세요"

JOB_RE = re.compile(r"^J-[0-9]{4}\Z")
_NUMBER_RE = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_PICK_RE = re.compile(r"^(.*)=(bucket|rank|category)(?::([0-9.,\s]+))?\Z")

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CONFIRM = 0, 1, 2, 3

# 오류 코드 (SP-08 의 오류 번호 표)
E_SHAPE = "E-04"                # 표 · 입력이 꼴 · 길이를 벗어남
E_OFF = "E-30"                  # 파생 표본이 꺼져 있다 (또는 허락 밖의 자리)
E_LIMIT = "E-31"                # 한도 (열 · 행 · 작은 표 · 주제 누계)
E_INTERNAL = "E-20"


class DeriveError(Exception):
    """코드만 담는다 (E-04 · E-30 · E-31 · E-20). 글 · 값 · 열 이름은 담지 않는다 (AL-11)."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


# ---------------------------------------------------------------- 문 (설정은 읽기만 한다)

def effective_level(home, home_is_default=True):
    """파생 표본의 실제 단계: 1 이면 돈다. policy.derived_level 이 정수 1 이고 policy.real_data 가 참 (bool) 일 때만 1.

    설정을 못 읽거나 · 모르는 값이거나 · 실데이터 승인이 없으면 0. 데이터 폴더가 기본 자리가 아니면 0 (AL-12).
    읽기만 한다 - 설정을 쓰는 길은 정책 창 (config.apply_state) 뿐이다.
    """
    if not home_is_default:
        return 0
    try:
        cfg = config.read_config(home)
    except Exception:
        return 0
    pol = cfg.get("policy")
    if not isinstance(pol, dict):
        return 0
    dl = pol.get("derived_level")
    if pol.get("real_data") is True and type(dl) is int and dl == 1:
        return 1
    return 0


# ---------------------------------------------------------------- 표 읽기

def _number(text):
    """표의 글 한 칸 -> 유한한 수 (ASCII 숫자 꼴만). 아니면 DeriveError(E-04)."""
    t = text.strip()
    if not _NUMBER_RE.match(t):
        raise DeriveError(E_SHAPE)
    v = float(t)
    if not math.isfinite(v):
        raise DeriveError(E_SHAPE)
    return v


def read_table(path):
    """CSV (UTF-8 · 첫 줄은 머리) -> (머리 목록, 행 목록). 행은 MAX_ROWS 개까지 - 넘으면 E-31. 꼴이 틀리면 E-04."""
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            raise DeriveError(E_LIMIT)
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
        text = raw.decode("utf-8-sig")
    except DeriveError:
        raise
    except Exception:
        raise DeriveError(E_SHAPE)
    if "\x00" in text:
        raise DeriveError(E_SHAPE)
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except Exception:
        raise DeriveError(E_SHAPE)
    rows = [r for r in rows if r]
    if len(rows) < 2:
        raise DeriveError(E_SHAPE)
    header, body = rows[0], rows[1:]
    if not header or len(header) > MAX_FILE_COLUMNS or any(len(r) != len(header) for r in body):
        raise DeriveError(E_SHAPE)
    if len(body) > MAX_ROWS:
        raise DeriveError(E_LIMIT)
    return header, body


# ---------------------------------------------------------------- 변환 셋 (결정적)

def parse_quantiles(text):
    """분위수 수준 글 ("0.2,0.4,0.6,0.8") -> Fraction 네 개. 꼴 · 범위 · 간격이 틀리면 E-04. 비면 기본값."""
    parts = [p.strip() for p in (text or ",".join(DEFAULT_QUANTILES)).split(",")]
    if len(parts) != 4:
        raise DeriveError(E_SHAPE)
    qs = []
    for p in parts:
        if not re.match(r"^0\.[0-9]{1,4}\Z", p):
            raise DeriveError(E_SHAPE)
        qs.append(Fraction(p))
    if qs[0] < QUANTILE_MIN or qs[-1] > QUANTILE_MAX or any(b - a < QUANTILE_GAP for a, b in zip(qs, qs[1:])):
        raise DeriveError(E_SHAPE)
    return qs


def bucket_cells(values, quantiles):
    """수치 -> 0-4 정수. 경계 b_i = 정렬한 값의 [floor(q_i x n)] 번째 (0부터) · 칸 = x 이상인 경계의 개수.

    경계값은 돌려주지 않는다 (칸 번호만). 같은 입력 -> 같은 출력.
    """
    n = len(values)
    srt = sorted(values)
    bounds = [srt[min(n - 1, int(q * n))] for q in quantiles]
    return [sum(1 for b in bounds if x >= b) for x in values]


def rank_cells(values):
    """수치 -> 0-9 정수. 순위 백분위 = (x 보다 작은 수 + 같은 수 / 2) / n 을 열 칸으로 (동률은 같은 칸 · 정수 셈이라 결정적)."""
    n = len(values)
    out = []
    for x in values:
        less = sum(1 for v in values if v < x)
        equal = sum(1 for v in values if v == x)
        out.append(min(9, ((2 * less + equal) * 10) // (2 * n)))
    return out


def category_cells(values, k, table):
    """범주 -> 토큰 (PseudonymTable · 이 자문의) 또는 PH_other. 행이 k 미만인 값은 모두 PH_other 로 묶는다.

    묶음 (PH_other) 도 k 미만이면 (0 < 묶음 < k) 가장 작은 값을 하나씩 더 묶어 k 이상이 되게 한다 - 묶음이 곧 식별이 되지 않게.
    묶인 값에는 토큰을 만들지 않는다. 값의 순서 (같은 크기) 는 처음 나온 자리로 가르지만 출력에는 자리가 나가지 않는다.
    """
    vals = [v.strip() for v in values]
    if any(not v for v in vals):
        raise DeriveError(E_SHAPE)
    groups = OrderedDict()
    for i, v in enumerate(vals):
        g = groups.get(v)
        if g is None:
            groups[v] = [1, i]
        else:
            g[0] += 1
    other = set(v for v, g in groups.items() if g[0] < k)
    other_n = sum(groups[v][0] for v in other)
    while 0 < other_n < k:
        rest = [v for v in groups if v not in other]
        if not rest:
            break
        small = min(rest, key=lambda v: (groups[v][0], groups[v][1]))
        other.add(small)
        other_n += groups[small][0]
    return [SAMPLE_OTHER if v in other else table.token_for(v, "word") for v in vals]


# ---------------------------------------------------------------- 고른 것으로 sample 만들기

def build_sample(header, rows, picks, k, table):
    """(머리, 행, 고른 것 [(열 번호 0부터, 변환, 분위수 또는 None)], k, 가명 표) -> (sample dict, 변환별 열 수).

    열 수 · 행 수 · 작은 표를 여기서 거절한다 (E-31). 열 이름은 가명 표에서 토큰을 받는다 (kind field).
    """
    n = len(rows)
    if not picks or len(picks) > MAX_COLUMNS or n > MAX_ROWS or not MIN_K <= k <= MAX_K:
        raise DeriveError(E_LIMIT)
    if n < 2 * k:
        raise DeriveError(E_LIMIT)
    if len(set(p[0] for p in picks)) != len(picks):
        raise DeriveError(E_SHAPE)
    columns, cells, counts = [], [], dict((t, 0) for t in TRANSFORMS)
    for col, transform, quantiles in picks:
        column = [r[col] for r in rows]
        if transform == "bucket":
            cells.append(bucket_cells([_number(c) for c in column], quantiles or parse_quantiles(None)))
        elif transform == "rank":
            cells.append(rank_cells([_number(c) for c in column]))
        elif transform == "category":
            cells.append(category_cells(column, k, table))
        else:
            raise DeriveError(E_SHAPE)
        counts[transform] += 1
        columns.append({"token": table.token_for(header[col], "field"), "kind": KIND_OF[transform]})
    out_rows = [list(r) for r in zip(*cells)]
    out_rows.sort(key=lambda r: [(0, c, "") if isinstance(c, int) else (1, 0, c) for c in r])
    return {"columns": columns, "rows": out_rows}, counts


def make_draft(sample):
    """plan 초안 (SP-02a) - 파생 자료도 실값에서 나오므로 data_class 는 real (AL-10)."""
    return {"format": 1, "kind": "plan", "data_class": "real", "goal": DRAFT_GOAL, "ask": DRAFT_ASK, "sample": sample}


# ---------------------------------------------------------------- 만든 초안이 나가는 길 (propose · 허브가 쓴다)

SAMPLE_KINDS = ("plan", "ui")   # sample 을 가질 수 있는 종류 (SP-02)
DRAFT_KEYS = frozenset(["format", "kind", "data_class", "goal", "ask", "sample"])     # derive 가 만드는 초안의 칸 그대로


def draft_shape_ok(draft):
    """derive 가 만든 초안의 꼴인가: plan · ui · 칸이 DRAFT_KEYS 뿐 (entities · fields · context 없음) · data_class real · sample 이 사전.

    일꾼 (사내 LLM) 이 쓴 plan · ui 를 받는 문이 아니다 - 칸이 이보다 많거나 sample 이 없으면 거절한다. 글 · 값을 담지 않는다.
    """
    return isinstance(draft, dict) and set(draft) == DRAFT_KEYS and draft.get("kind") in SAMPLE_KINDS \
        and draft.get("data_class") == "real" and isinstance(draft.get("sample"), dict) and draft.get("format") == 1


def draft_table_sha256(draft):
    """초안의 sample 이 펼쳐질 표 글의 sha256. sample 의 꼴이 틀려 펼칠 수 없으면 DeriveError(E-04)."""
    try:
        return audit.table_sha256(draft["sample"])
    except Exception:
        raise DeriveError(E_SHAPE)


def sample_tokens(sample):
    """sample 에 나온 가명 토큰 (열 이름 · 범주 칸 · PH_other 는 묶음 표지라 뺀다) 의 집합. 정확한 꼴이 아니면 DeriveError(E-04)."""
    try:
        out = set()
        for c in sample["columns"]:
            out.add(c["token"])
        for row in sample["rows"]:
            for cell in row:
                if isinstance(cell, str) and cell != SAMPLE_OTHER:
                    out.add(cell)
        if any(not isinstance(t, str) or not scan.TOKEN_RE.fullmatch(t) for t in out):
            raise DeriveError(E_SHAPE)
        return frozenset(out)
    except DeriveError:
        raise
    except Exception:
        raise DeriveError(E_SHAPE)


def check_draft(draft, rec):
    """초안이 derive 의 감사 기록 rec (audit.derive_find 의 결과) 과 맞는가 -> 일방향 토큰의 집합. 아니면 DeriveError(E-04).

    표 글의 sha256 은 찾을 때 이미 맞았다. 여기서는 열 수 · 행 수 · 열 종류 · 토큰 수가 기록 안인지 한 번 더 본다 (기록이 틀어졌을 때를 위한 겹).
    """
    if not draft_shape_ok(draft) or not isinstance(rec, dict):
        raise DeriveError(E_SHAPE)
    sample = draft["sample"]
    tokens = sample_tokens(sample)
    try:
        cols, rows = sample["columns"], sample["rows"]
        numeric = sum(1 for c in cols if c["kind"] == "수치")
        categoric = sum(1 for c in cols if c["kind"] == "범주")
        tf = rec["transforms"]
        ok = len(cols) == rec["columns"] and len(rows) == rec["rows"] \
            and numeric == tf["bucket"] + tf["rank"] and categoric == tf["category"] \
            and 0 < len(tokens) <= rec["tokens"] <= audit.MAX_DERIVE_TOKENS
    except Exception:
        ok = False
    if not ok:
        raise DeriveError(E_SHAPE)
    return tokens


# ---------------------------------------------------------------- 터미널 대화 (고른 것은 저장하지 않는다)

def _read_line(stream):
    line = stream.readline()
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    if line == "":
        return None
    return line.rstrip("\r\n")


def parse_pick(line, header):
    """`<열>=<변환>[:<분위수>]` 한 줄 -> (열 번호 0부터, 변환, 분위수 또는 None). 열은 머리 글 그대로 · 아니면 1부터의 번호.

    머리 글이 겹치면 (같은 이름이 둘) 글로는 못 고른다 - 번호로 고른다. 못 읽으면 E-04. 글 · 열 이름을 되풀이하지 않는다.
    """
    m = _PICK_RE.match(line.strip())
    if not m:
        raise DeriveError(E_SHAPE)
    name, transform, qtext = m.group(1).strip(), m.group(2), m.group(3)
    hits = [i for i, h in enumerate(header) if h.strip() == name]
    if len(hits) == 1:
        col = hits[0]
    elif not hits and re.match(r"^[0-9]{1,3}\Z", name) and 1 <= int(name) <= len(header):
        col = int(name) - 1
    else:
        raise DeriveError(E_SHAPE)
    if qtext is not None and transform != "bucket":
        raise DeriveError(E_SHAPE)
    return col, transform, (parse_quantiles(qtext) if transform == "bucket" else None)


PROMPT_JOB = "주제 job 번호 (예 J-0007) - 파생 자료 누계를 이 번호로 셉니다: "
PROMPT_K = "k - 범주에서 이보다 적은 행에만 나온 값은 묶습니다 (5 이상 · 비우면 10): "
PROMPT_PICKS = ("열마다 `열=변환` 을 한 줄에 하나씩 적고 빈 줄로 끝내세요 (열은 머리 글 그대로 또는 1부터의 번호 · 열은 %d개 · "
                "변환은 bucket · rank · category · bucket 은 `열=bucket:0.2,0.4,0.6,0.8` 처럼 분위수를 고를 수 있습니다 · "
                "적지 않은 열은 나가지 않습니다)\n")
PROMPT_GO = "%d열 x %d행을 만듭니다 - 계속하려면 y: "


def ask(inp, err):
    """표준 입력으로 (job, k, 고른 줄 목록) 를 받는다. 입력이 끊기면 DeriveError(E-04). 열 이름 · 값을 묻는 글에 쓰지 않는다."""
    def line(prompt):
        err.write(prompt)
        err.flush()
        got = _read_line(inp)
        if got is None:
            raise DeriveError(E_SHAPE)
        return got.strip()
    job = line(PROMPT_JOB)
    if not JOB_RE.match(job):
        raise DeriveError(E_SHAPE)
    ktext = line(PROMPT_K)
    if ktext == "":
        k = DEFAULT_K
    elif re.match(r"^[0-9]{1,3}\Z", ktext):
        k = int(ktext)
    else:
        raise DeriveError(E_SHAPE)
    return job, k


def ask_picks(inp, err, ncols):
    err.write(PROMPT_PICKS % MAX_COLUMNS)
    err.flush()
    lines = []
    while True:
        got = _read_line(inp)
        if got is None or got.strip() == "":
            break
        lines.append(got)
        if len(lines) > MAX_COLUMNS:
            raise DeriveError(E_LIMIT)
    if not lines:
        raise DeriveError(E_SHAPE)
    return lines


def confirm_go(inp, err, columns, rows):
    err.write(PROMPT_GO % (columns, rows))
    err.flush()
    got = _read_line(inp)
    if got is None or got.strip().lower() != "y":
        raise DeriveError(E_SHAPE)


# ---------------------------------------------------------------- 명령

def _line(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def main_derive(home, home_is_default, csv_path, out_path, inp, err):
    """표 -> 초안. (종료 코드, 표준 출력 한 줄). 출력은 개수 · 코드뿐이다.

    순서: 문 -> 표 읽기 -> 사람이 job · k · 열 · 변환을 고름 -> 한도 · 누계 -> sample -> seal 로 미리 검사 (D1-D6) ->
    사람이 y -> 감사 기록 (먼저) -> 초안을 새 파일로 (덮어쓰지 않는다). 하나라도 어긋나면 만들지 않는다 (AL-03).
    """
    try:
        if effective_level(home, home_is_default) != 1:
            return EXIT_CONFIRM, _line({"derived": False, "error": E_OFF})
        if not isinstance(csv_path, str) or not os.path.isfile(csv_path) or not isinstance(out_path, str) or not out_path:
            return EXIT_USAGE, _line({"derived": False, "error": E_SHAPE})
        header, rows = read_table(csv_path)
        if len(rows) < 2 * MIN_K:
            return EXIT_USAGE, _line({"derived": False, "error": E_LIMIT})
        job, k = ask(inp, err)
        if len(rows) < 2 * k:
            return EXIT_USAGE, _line({"derived": False, "error": E_LIMIT})
        picks = [parse_pick(x, header) for x in ask_picks(inp, err, len(header))]
        if audit.derived_rows(home, job) + len(rows) > MAX_TOPIC_ROWS:
            return EXIT_USAGE, _line({"derived": False, "error": E_LIMIT})
        table = PseudonymTable()
        sample, counts = build_sample(header, rows, picks, k, table)
        draft = make_draft(sample)
        policy = scan.policy_from_home(home)
        res = seal(draft, table, policy)
        if not res.get("ok"):
            return EXIT_USAGE, _line({"derived": False, "hits": res.get("hits", [])})
        confirm_go(inp, err, len(sample["columns"]), len(sample["rows"]))
        audit.derive_record(home, job, counts, len(rows), tokens=len(sample_tokens(sample)),
                            table_sha256=audit.table_sha256(sample))
        write_new(out_path, json.dumps(draft, ensure_ascii=False, indent=1) + "\n")
        return EXIT_OK, _line({"derived": True, "columns": len(sample["columns"]), "rows": len(sample["rows"]),
                               "transforms": counts})
    except DeriveError as e:
        return EXIT_USAGE, _line({"derived": False, "error": e.code})
    except Exception:
        return EXIT_FAIL, _line({"derived": False, "error": E_INTERNAL})


def run_command(csv_path, out_path, home_info, inp, out, err):
    """diode.py 의 분배. home_info 는 (데이터 폴더, 기본 자리인가). 표준 입력이 터미널이 아니면 (inp 가 없는데 파이프) 돌지 않는다."""
    import sys
    home, default = home_info
    if inp is None:
        stdin = sys.stdin
        if not getattr(stdin, "isatty", lambda: False)():
            out.write(_line({"derived": False, "error": E_OFF}) + "\n")
            return EXIT_CONFIRM
        inp = stdin
    code, line = main_derive(home, default, csv_path, out_path, inp, err)
    out.write(line + "\n")
    return code
