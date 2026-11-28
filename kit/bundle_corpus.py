#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""가린 묶음 코퍼스 (SP-20 · W-11) — 합성 묶음을 결정적으로 만들어 diodelib.bundle.build_bundle 에 돌린다.

진짜 금고 (vault.open_project · 임시 데이터 폴더 · 평문 - Windows 는 DPAPI) 와 진짜 정책 (scan.policy_from_home ·
합성 사전) 을 쓴다. propose 가 하는 것과 같은 길이다. 묶음마다 새 작업 묶음 (project) 을 열고 닫는다 - 앞 묶음의
금고 값이 뒤 묶음의 자동 가림에 끼지 않게. '금고 값 재등장' 범주만 같은 작업 묶음에서 앞 묶음 (prior) 을 먼저 보낸다.

세 무리
  good        표시를 제대로 한 문서 (md · txt) · 표 (csv · tsv) · 코드 (py · js · sql) - 모두 통과해야 하고,
              가린 글을 금고로 되돌린 글 (bundle.restore_text) 이 원문에서 표시 기호만 뺀 글과 같아야 한다 (왕복).
  leaky       표시를 빠뜨리거나 틀린 꼴 - 모두 막혀야 한다 (잔여 검사 R1–R6 또는 꼴 오류 E-04).
              범주마다 어느 검사가 잡았는지 센다 (한 묶음을 여러 검사가 잡으면 모두 센다).
  known-miss  SP-20 › 남는 위험의 꼴 - 몇 개가 지나가는지 그대로 센다 (기록용 · 합격 기준 밖 · 숨기지 않는다).

쓰는 법
    python kit/bundle_corpus.py                 표 (개수 · 비율 · 범주 · 검사 번호)
    python kit/bundle_corpus.py --json <파일>   JSON 보고도 쓴다 ('-' 이면 표 대신 표준 출력에)
    python kit/bundle_corpus.py --self-test     합격 기준만 (good 전부 통과 · leaky 전부 막힘 · 왕복 일치)

출력에는 묶음의 글 · 단어 · 값을 찍지 않는다 - 개수 · 비율 · 범주 이름 · 검사 번호 · 묶음 번호 (good-07) 만.
모든 자료는 지어낸 것이다 (주소는 example.com · *.corp 꼴 · IP 는 문서용 대역 · 비밀 꼴은 실행할 때 해시로 만든다).
종료 코드: 0 OK · 1 점검 실패 · 2 사용법 오류. 마지막 줄은 `결과: OK` · `결과: 점검 실패` (S-03).
표준 라이브러리만 · Python 3.8 이상.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import canary_variants as cv  # noqa: E402
from diodelib import bundle, config, scan, vault  # noqa: E402

# 합성 사전 (tests/vectors/policy.json 과 같은 지어낸 단어)
WORDS = ["KITWORDALPHA", "가람소재", "BX-7 라인", "KITC_ORBIT", "모래시계공정"]
MIN_GOOD = 30
MIN_LEAKY = 90
GOOD, LEAKY, MISS = "good", "leaky", "known-miss"
BLOCK_CHECKS = ("R1", "R2", "R3", "R4", "R5", "R6", "D1", "D2", "D3", "D4", "D5", "D6", "E-04")
CHECK_ORDER = BLOCK_CHECKS + ("E-20", "E-31", "E-33")

LEAKY_CATEGORIES = (
    ("dict_variant", "사전 단어 변형"),
    ("vault_reappear", "금고 값 재등장"),
    ("drive_path", "드라이브 경로"),
    ("unc", "UNC"),
    ("url", "URL"),
    ("ip", "IP"),
    ("email", "메일"),
    ("host_quoted", "따옴표 안 호스트"),
    ("host_comment", "주석 안 호스트"),
    ("number3", "세 자리 수"),
    ("decimal", "소수"),
    ("date", "날짜"),
    ("time_string", "시각 (문자열 안)"),
    ("secret_blob", "base64 · hex 비밀"),
    ("unknown_token", "모르는 토큰"),
    ("broken_token", "깨진 토큰"),
    ("bad_mark", "틀린 표시"),
    ("config_host", "설정 · 셸의 따옴표 없는 호스트 (type code)"),
)
MISS_CATEGORIES = (
    ("new_name", "사전 · 금고에 없는 새 이름"),
    ("ident_number", "이름 속 숫자"),
    ("ident_host", "식별자로 쓴 호스트"),
    ("backslash_relpath", "역슬래시 하나의 상대 경로"),
    ("zone_mismatch", "구역 판단이 틀리는 언어"),
)
GOOD_KINDS = (("doc", "문서"), ("table", "표"), ("code", "코드"), ("multi", "여러 파일"))

O, C = bundle.MARK_OPEN, bundle.MARK_CLOSE


# ───────────────────────────────────────────────────────── 표시 · 원문

def W(v: str) -> str:
    """word 표시 ⟦값⟧."""
    return O + v + C


def N(v: str) -> str:
    """number 표시 ⟦n:값⟧."""
    return O + "n:" + v + C


def P(v: str) -> str:
    """path 표시 ⟦p:값⟧."""
    return O + "p:" + v + C


def I(v: str) -> str:  # noqa: E743
    """ident 표시 ⟦i:값⟧."""
    return O + "i:" + v + C


def unmark(text: str) -> str:
    """표시 기호만 뺀 원문 - 되돌린 글이 이것과 같아야 한다."""
    out = []
    pos = 0
    for m in bundle.parse_marks(text):
        out.append(text[pos:m.start])
        out.append(m.value)
        pos = m.end
    out.append(text[pos:])
    return "".join(out)


def _blob(seed: str, kind: str) -> str:
    """비밀처럼 보이는 덩어리를 실행할 때 만든다 (파일에 통째로 두지 않는다 · 결정적)."""
    raw = hashlib.sha256(("kit-bundle-corpus:" + seed).encode("ascii")).digest()
    if kind == "hex":
        return raw.hex()[:32]
    if kind == "hex40":
        return (raw + hashlib.sha256(raw).digest()).hex()[:40]
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# ───────────────────────────────────────────────────────── 코퍼스 (결정적)

def _case(set_: str, cat: str, files: Sequence[Tuple[str, str, str]], prior: Optional[Sequence] = None) -> Dict[str, Any]:
    return {"set": set_, "cat": cat, "files": [list(f) for f in files], "prior": [list(f) for f in (prior or [])]}


def _good() -> List[Dict[str, Any]]:
    doc = [
        ("plan.md", "# 주간 계획\n\n%s 의 수율을 %s 로 올린다.\n담당 시스템: %s\n" % (W("노을공정"), N("93.5"), W("새벽라인"))),
        ("memo.md", "## 회의 메모\n\n- %s 점검은 %s 에 한다.\n- 자료: %s\n" % (W("노을공정"), N("2026-11-27"), P("D:\\kitdata\\yield.csv"))),
        ("supply.txt", "%s 납품 일정\n%s 까지 %s 개를 맞춘다.\n" % (W("가람소재"), N("2026-12-03"), N("1200"))),
        ("contact.md", "접속 주소는 %s 이다.\n문의: %s\n" % (P("https://kit-intra.example.com/plan"), P("kit.user@example.com"))),
        ("process.md", "%s 의 온도는 %s 도, 압력은 %s 이다.\n" % (W("모래시계공정"), N("350"), N("1.25"))),
        ("backup.txt", "서버 %s 의 백업은 %s 에 돈다.\n" % (P("kitdb01.example.corp"), N("03:30"))),
        ("line.md", "| 항목 | 값 |\n|---|---|\n| 라인 | %s |\n| 목표 | %s |\n" % (W("BX-7 라인"), N("98.2"))),
        ("code-notes.md", "함수 %s 는 %s 를 부른다.\n두 함수 모두 %s 에 있다.\n" % (I("calcYield"), I("kitLoader"),
                                                                     P("kitsrc/kit_mod.py"))),
        ("share.txt", "공유 폴더 %s 에 결과를 둔다.\n" % P("\\\\kitnas01\\share")),
        ("budget.md", "%s 과제의 예산은 %s 만 원이다.\n승인일: %s\n" % (W("KITC_ORBIT"), N("4500"), N("2026-10-01"))),
        ("network.md", "주소 %s 와 %s 는 막는다.\n" % (P("192.0.2.15"), P("2001:db8::15"))),
        ("week.md", "이번 주에는 %s 만 본다.\n다음 주에 다시 정한다.\n" % W("노을공정")),
    ]
    table = [
        ("yield.csv", "공정,수율,날짜\n%s,%s,%s\n%s,%s,%s\n" % (W("노을공정"), N("93.5"), N("2026-11-27"),
                                                           W("새벽라인"), N("88.1"), N("2026-11-28"))),
        ("target.csv", "line,target,owner\n%s,%s,%s\n" % (W("BX-7 라인"), N("120"), W("KITOWNERA"))),
        ("hosts.tsv", "host\tport\n%s\t%s\n%s\t%s\n" % (P("kitdb01.example.corp"), N("5432"),
                                                        P("kitdb02.example.corp"), N("5433"))),
        ("orders.csv", "id,name,amount\n%s,%s,%s\n%s,%s,%s\n" % (N("10021"), W("KITCLIENTA"), N("350000"),
                                                               N("10022"), W("KITCLIENTB"), N("125000"))),
        ("files.csv", "path,size\n%s,%s\n" % (P("D:\\kitdata\\a.csv"), N("2048"))),
        ("log.tsv", "날짜\t시각\t값\n%s\t%s\t%s\n" % (N("2026-11-27"), N("09:30"), N("3.5"))),
        ("owners.csv", "단계,담당\n준비,%s\n점검,%s\n" % (W("KITOWNERA"), W("KITOWNERB"))),
        ("links.csv", "mail,url\n%s,%s\n" % (P("kit.ops@example.com"), P("https://kit.example.com/a"))),
    ]
    code = [
        ("kitsrc/yield.py", "code",
         "import csv\n\n\ndef %s(rows):\n    total = 0\n    for row in rows:\n        total += row[\"%s\"]\n"
         "    return total / max(len(rows), 1)\n" % (I("calcYield"), I("kitQty"))),
        ("kitsrc/load.py", "code",
         "PATH = \"%s\"\nLIMIT = %s\n\n\ndef load():\n    with open(PATH, encoding=\"utf-8\") as f:\n"
         "        return f.read()[:LIMIT]\n" % (P("D:\\kitdata\\yield.csv"), N("350"))),
        ("kitsrc/adjust.py", "code",
         "# %s 의 온도 보정\nTEMP = %s\nGAIN = %s\n\n\ndef adjust(x):\n    return x * GAIN + TEMP\n"
         % (W("노을공정"), N("350"), N("1.25"))),
        ("kitsrc/conn.py", "code",
         "import logging\n\nlog = logging.getLogger(__name__)\nHOST = \"%s\"\n\n\ndef connect():\n"
         "    log.info(\"연결 시작\")\n    return HOST\n" % P("kitdb01.example.corp")),
        ("kitsrc/planner.py", "code",
         "class %s:\n    def __init__(self, start):\n        self.start = start\n\n    def due(self):\n"
         "        return \"%s\"\n" % (I("KitPlanner"), N("2026-11-27"))),
        ("kitsrc/report.py", "code",
         "def %s(to=\"%s\"):\n    url = \"%s\"\n    return url, to\n"
         % (I("sendReport"), P("kit.user@example.com"), P("https://kit-intra.example.com/api"))),
        ("web/api.js", "code",
         "const %s = \"%s\";\n\nfunction %s(id) {\n  return fetch(%s + \"?id=\" + id);\n}\n"
         % (I("kitApi"), P("https://kit-intra.example.com/api"), I("fetchPlan"), I("kitApi"))),
        ("web/yield.js", "code",
         "// %s 화면\nexport function %s(v) {\n  const limit = %s;\n  return v > limit ? \"높음\" : \"보통\";\n}\n"
         % (W("노을공정"), I("renderYield"), N("350"))),
        ("web/cfg.js", "code",
         "const cfg = {\n  host: \"%s\",\n  port: %s,\n};\nmodule.exports = cfg;\n"
         % (P("kitdb01.example.corp"), N("5432"))),
        ("web/time.js", "code",
         "const start = \"%s\";\nconst at = \"%s\";\nconsole.log(start, at);\n" % (N("2026-11-27"), N("09:30"))),
        ("web/ratio.js", "code",
         "function %s(a, b) {\n  return (a / b) * %s;\n}\n" % (I("calcRatio"), N("1.5"))),
        ("sql/yield.sql", "code",
         "-- %s 수율 집계\nSELECT line, AVG(yield) AS y\nFROM %s\nWHERE day >= '%s'\nGROUP BY line;\n"
         % (W("노을공정"), I("kit_yield"), N("2026-11-27"))),
        ("sql/plan.sql", "code",
         "UPDATE %s\nSET target = %s\nWHERE owner = '%s';\n" % (I("kit_plan"), N("350"), W("KITOWNERA"))),
        ("sql/hosts.sql", "code",
         "SELECT *\nFROM %s\nWHERE host = '%s'\nLIMIT 10;\n" % (I("kit_hosts"), P("kitdb01.example.corp"))),
        ("sql/log.sql", "code",
         "INSERT INTO %s (at, msg)\nVALUES ('%s', '%s 입고');\n" % (I("kit_log"), N("09:30"), W("가람소재"))),
        ("sql/lots.sql", "code",
         "CREATE TABLE %s (\n  id INTEGER PRIMARY KEY,\n  ratio REAL DEFAULT %s\n);\n" % (I("kit_lots"), N("0.75"))),
    ]
    out = []
    for path, text in doc:
        out.append(_case(GOOD, "doc", [(path, "doc", text)]))
    for path, text in table:
        out.append(_case(GOOD, "table", [(path, "table", text)]))
    for path, ftype, text in code:
        out.append(_case(GOOD, "code", [(path, ftype, text)]))
    # 여러 파일 - 한 파일에서 표시한 값이 다른 파일에 표시 없이 나오면 자동 가림이 같은 토큰으로 가린다 (왕복은 그대로)
    out.append(_case(GOOD, "multi", [
        ("notes.md", "doc", "%s 의 계산을 고친다.\n" % W("노을공정")),
        ("kitsrc/calc.py", "code", "def %s():\n    return %s\n" % (I("kitCalc"), N("731"))),
    ]))
    out.append(_case(GOOD, "multi", [
        ("plan.md", "doc", "%s 일정은 %s 이다.\n" % (W("노을공정"), N("2026-11-27"))),
        ("rows.csv", "table", "공정,값\n노을공정,%s\n" % N("93.5")),
        ("sql/q.sql", "code", "SELECT * FROM %s;\n" % I("kit_rows")),
    ]))
    return out


def _leaky() -> List[Dict[str, Any]]:
    hx, hx2, hx40 = _blob("hex-1", "hex"), _blob("hex-2", "hex"), _blob("hex40-1", "hex40")
    b1, b2, b3 = _blob("b64-1", "b64"), _blob("b64-2", "b64"), _blob("b64-3", "b64")
    nfd = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731
    prior = [("kitnotes.md", "doc", "%s · %s · %s · %s 를 쓴다.\n" % (W("KITVAULTWORDQ"), W("노을공정"), I("kitCalcYield"),
                                                                    N("731337")))]
    cases = {
        "dict_variant": [
            ("a.md", "doc", "\uff2b\uff29\uff34\uff37\uff2f\uff32\uff24\uff21\uff2c\uff30\uff28\uff21 의 일정\n"),  # 전각
            ("b.md", "doc", "K\u0406TW\u041eRDALPHA 의 일정\n"),                                # 키릴 닮은 글자
            ("c.py", "code", "# KIT\u200bWORD\u200bALPHA 계산\nx = 1\n"),                       # 보이지 않는 글자
            ("d.md", "doc", nfd("가람소재") + " 납품\n"),                                        # 자모 풀어쓰기
            ("e.csv", "table", "이름\nKIT+WORD+ALPHA\n"),                                         # 정규식 밖 구분자
            ("f.js", "code", "const name = \"K1TW0RDALPHA\";\n"),                                # 닮은 ASCII (1 · 0)
            ("g.md", "doc", "K\u0308ITWORDALPHA 의 일정\n"),                                    # 결합 부호
            ("h.md", "doc", "모래시계\n공정 의 온도\n"),                                          # 줄을 넘김
            ("i.sql", "code", "-- BX~7 라인 집계\nSELECT 1;\n"),
            ("j.txt", "doc", "KITC\uff3fORBIT 과제\n"),                                          # 전각 밑줄
        ],
        "vault_reappear": [
            ("a.md", "doc", "\uff2b\uff29\uff34\uff36\uff21\uff35\uff2c\uff34\uff37\uff2f\uff32\uff24\uff31 의 일정\n"),
            ("b.py", "code", "def k\u0456tCalcYield():\n    return 1\n"),
            ("c.md", "doc", nfd("노을공정") + " 점검\n"),
            ("d.md", "doc", "KITVAULT\u200bWORDQ 의 일정\n"),
            ("e.md", "doc", "KITVAULT\nWORDQ 는 다음 줄\n"),
            ("f.csv", "table", "값\n7\uff131337\n"),
            ("g.js", "code", "const x = k1tCalcYield;\n"),
        ],
        "drive_path": [
            ("a.md", "doc", "자료는 D:\\kitdata\\plan.csv 에 있다.\n"),
            ("b.md", "doc", "결과: C:/Users/kit/plan.xlsx\n"),
            ("c.py", "code", "OUT = \"E:\\\\kit\\\\out.txt\"\n"),
            ("d.js", "code", "const p = \"D:/kit/a.json\";\n"),
            ("e.csv", "table", "path\nF:\\kit\\b.csv\n"),
            ("f.sql", "code", "COPY t FROM 'G:\\kit\\c.csv';\n"),
        ],
        "unc": [
            ("a.md", "doc", "공유: \\\\kitsrv01\\share\\plan.txt\n"),
            ("b.py", "code", "SHARE = \"\\\\\\\\kitsrv01\\\\share\"\n"),
            ("c.csv", "table", "path\n\\\\kitnas\\data\n"),
            ("d.js", "code", "const s = \"//kitsrv02/share/x\";\n"),
            ("e.md", "doc", "공유 //kitnas/pub/ 에 둔다.\n"),
        ],
        "url": [
            ("a.md", "doc", "주소 https://kit-intra.example.com/plan 를 본다.\n"),
            ("b.py", "code", "URL = \"http://kit.example.local/api\"\n"),
            ("c.js", "code", "const ws = 'wss://kit.example.corp/ws';\n"),
            ("d.csv", "table", "url\nftp://kitfiles.example.com/a\n"),
            ("e.sql", "code", "SELECT 'https://kit.example.com/x';\n"),
        ],
        "ip": [
            ("a.md", "doc", "서버 192.0.2.15 에 붙는다.\n"),
            ("b.py", "code", "ADDR = \"198.51.100.7\"\n"),
            ("c.js", "code", "const a = '203.0.113.9';\n"),
            ("d.csv", "table", "addr\n2001:db8::15\n"),
            ("e.sql", "code", "WHERE ip = '192.0.2.200';\n"),
        ],
        "email": [
            ("a.md", "doc", "문의 kit.user@example.com\n"),
            ("b.py", "code", "TO = \"kit-ops@example.corp\"\n"),
            ("c.js", "code", "const to = 'kit.team@example.com';\n"),
            ("d.csv", "table", "mail\nkit.owner@example.com\n"),
            ("e.sql", "code", "WHERE mail = 'kit.a@example.local';\n"),
        ],
        "host_quoted": [
            ("a.py", "code", "HOST = \"kitdb01.example.corp\"\n"),
            ("b.js", "code", "const api = 'kit-api.example.local';\n"),
            ("c.sql", "code", "WHERE src = 'kitdb.example.internal';\n"),
            ("d.go", "code", "var addr = \"kitcache.example.lab\"\n"),
            ("e.java", "code", "String h = \"kitmq.example.svc\";\n"),
        ],
        "host_comment": [
            ("a.py", "code", "# 연결: kitdb02.example.corp\nx = 1\n"),
            ("b.js", "code", "// kit-cache.example.local 를 쓴다\nlet x = 1;\n"),
            ("c.sql", "code", "-- kitdb.example.corp 에서 읽는다\nSELECT 1;\n"),
            ("d.c", "code", "/* kitbuild.example.lab */\nint x = 1;\n"),
            ("e.py", "code", "\"\"\"kitdocs.example.intra 참고\"\"\"\nx = 1\n"),
        ],
        "number3": [
            ("a.md", "doc", "수량은 731 개다.\n"),
            ("b.py", "code", "LIMIT = 731\n"),
            ("c.js", "code", "const n = 4096;\n"),
            ("d.csv", "table", "qty\n731\n"),
            ("e.sql", "code", "SELECT * FROM t LIMIT 500;\n"),
        ],
        "decimal": [
            ("a.md", "doc", "비율은 0.731 이다.\n"),
            ("b.py", "code", "RATIO = 3.25\n"),
            ("c.js", "code", "const y = x * 1.5;\n"),
            ("d.csv", "table", "yield\n93.5\n"),
            ("e.sql", "code", "WHERE r >= 0.75;\n"),
        ],
        "date": [
            ("a.md", "doc", "2026-11-27 에 시작한다.\n"),
            ("b.py", "code", "DUE = \"2026-11-27\"\n"),
            ("c.js", "code", "const d = '2026/11/27';\n"),
            ("d.csv", "table", "day\n2026-11-27\n"),
            ("e.sql", "code", "WHERE day = '2026-11-27';\n"),
        ],
        "time_string": [
            ("a.py", "code", "START = \"09:30\"\n"),
            ("b.js", "code", "const t = '18:45:10';\n"),
            ("c.sql", "code", "WHERE at = '07:15';\n"),
            ("d.go", "code", "var end = \"23:59\"\n"),
            ("e.java", "code", "String t = \"06:05\";\n"),
        ],
        "secret_blob": [
            ("a.md", "doc", "키: %s\n" % hx),
            ("b.py", "code", "TOKEN = \"%s\"\n" % hx40),
            ("c.js", "code", "const k = \"%s\";\n" % b1),
            ("d.csv", "table", "key\n%s\n" % b2),
            ("e.sql", "code", "WHERE k = '%s';\n" % hx2),
            ("f.md", "doc", "비밀 %s\n" % b3),
        ],
        "unknown_token": [
            ("a.md", "doc", "PH_Z9Z9 의 일정\n"),
            ("b.py", "code", "x = PH_Z9Z9\n"),
            ("c.csv", "table", "이름\nPH_W8N4\n"),
            ("d.js", "code", "const a = \"PH_M3X9\";\n"),
            ("e.sql", "code", "SELECT PH_T4W5 FROM t;\n"),
        ],
        "broken_token": [
            ("a.md", "doc", "PH_K7Q 의 일정\n"),
            ("b.py", "code", "x = ph_k7q2\n"),
            ("c.csv", "table", "이름\nPH-K7Q2\n"),
            ("d.js", "code", "const a = \"PH K7Q2\";\n"),
            ("e.md", "doc", "PH_K7Q2X 의 일정\n"),
        ],
        "bad_mark": [
            ("a.md", "doc", O + "노을공정 의 일정\n"),                    # 닫히지 않음
            ("b.md", "doc", "노을공정" + C + " 의 일정\n"),               # 여는 표시 없이 닫음
            ("c.md", "doc", O + C + " 빈 표시\n"),                        # 빈 값
            ("d.md", "doc", O + "x:kitvalue" + C + "\n"),                 # 모르는 머리 글자
            ("e.md", "doc", O + "a" + O + "b" + C + C + "\n"),            # 겹침
            ("f.md", "doc", O + "노을\n공정" + C + "\n"),                 # 값에 줄바꿈
            ("g.py", "code", "TIMEOUT = " + N("350") + "ms\n"),          # 토큰이 앞뒤 낱말에 붙음
            ("h.md", "doc", W("가" * (bundle.MAX_MARK_VALUE + 1)) + "\n"),  # 512자 넘는 값
        ],
        "config_host": [
            ("deploy.yaml", "code", "db:\n  host: kitdb01.example.corp\n"),
            ("app.ini", "code", "[db]\nserver = kitdb.example.corp\n"),
            ("run.sh", "code", "ssh kitbox.example.corp uptime\n"),
            ("db.env", "code", "DB_HOST=kitdb.example.internal\n"),
            ("settings.toml", "code", "[db]\nhost = kitdb.example.lab\n"),
            ("start.ps1", "code", "Enter-PSSession -ComputerName kitbox.example.corp\n"),
        ],
    }
    out = []
    for cat, _label in LEAKY_CATEGORIES:
        for path, ftype, text in cases[cat]:
            out.append(_case(LEAKY, cat, [(path, ftype, text)], prior if cat == "vault_reappear" else None))
    return out


def _known_miss() -> List[Dict[str, Any]]:
    cases = {
        "new_name": [
            ("a.md", "doc", "KITNEWNAMEZETA 과제를 시작한다.\n"),
            ("b.md", "doc", "새벽공정 의 일정을 정한다.\n"),
            ("c.py", "code", "def kitHiddenPlanner():\n    return 1\n"),
            ("d.csv", "table", "고객\nKITNEWCLIENTQ\n"),
            ("e.sql", "code", "SELECT * FROM kit_secret_orders;\n"),
        ],
        "ident_number": [
            ("a.py", "code", "temp_350 = 1\n"),
            ("b.js", "code", "const A350 = 2;\n"),
            ("c.py", "code", "def model_A731():\n    return 1\n"),
            ("d.sql", "code", "SELECT lot_2026 FROM t;\n"),
        ],
        "ident_host": [
            ("a.py", "code", "db = kitdb01.example.corp\n"),
            ("b.js", "code", "const h = kitapi.example.local;\n"),
            ("c.py", "code", "conn = connect(kitdb.example.internal)\n"),
            ("d.java", "code", "Object o = kitmq.example.svc;\n"),
        ],
        "backslash_relpath": [
            ("a.py", "code", "P = r\"data\\kit_a.csv\"\n"),
            ("b.js", "code", "const p = String.raw`kitdata\\plan.csv`;\n"),
            ("c.cs", "code", "var p = @\"kitdata\\b.csv\";\n"),
        ],
        "zone_mismatch": [
            ("a.rs", "code", "fn f<'a>(x: &'a str) -> &'a str { \"kitdb.example.corp\" }\n"),   # 넓게 어긋남 (그 줄 끝까지 구역)
            ("b.rb", "code", "SQL = <<~EOS\n  kitdb.example.corp\nEOS\n"),                     # heredoc
            ("c.cs", "code", "var p = @\"kitdir\\\"; var h = \"kithost.example.corp\";\n"),     # 역슬래시가 이스케이프가 아닌 글
            ("d.js", "code", "const re = /\"/; const h = \"kitdb.example.corp\";\n"),          # 정규식 글 안의 따옴표
            ("e.sql", "code", "SELECT 'kit\\'; SELECT 'kitdb.example.corp';\n"),               # SQL 글의 역슬래시
        ],
    }
    out = []
    for cat, _label in MISS_CATEGORIES:
        for path, ftype, text in cases[cat]:
            out.append(_case(MISS, cat, [(path, ftype, text)]))
    return out


def corpus() -> List[Dict[str, Any]]:
    """코퍼스 전체 (결정적 · 같은 판이면 늘 같은 목록). 묶음 번호는 무리 안의 차례 (good-01 …)."""
    out = []
    for part in (_good(), _leaky(), _known_miss()):
        for i, c in enumerate(part, 1):
            c["id"] = "%s-%02d" % (c["set"], i)
            out.append(c)
    return out


# ───────────────────────────────────────────────────────── 돌리기

def _write_files(workdir: str, files: Sequence[Sequence[str]]) -> Dict[str, Any]:
    """작업 폴더에 원본을 바이트 그대로 쓰고 manifest 를 만든다."""
    os.makedirs(workdir)
    for path, _t, text in files:
        p = os.path.join(workdir, *path.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return {"format": 1, "kind": "bundle", "files": [{"path": f[0], "type": f[1]} for f in files], "note": ""}


def _checks_of(hits: Sequence[Dict[str, Any]]) -> List[str]:
    got = set(str(h.get("check")) for h in hits)
    return [c for c in CHECK_ORDER if c in got] + sorted(got - set(CHECK_ORDER))


def run_case(home: str, policy: Any, words: Sequence[str], case: Dict[str, Any], workroot: str) -> Dict[str, Any]:
    """묶음 하나 → {"id", "set", "cat", "ok", "checks", "roundtrip", "auto", "error"} (글 · 값 없음).

    새 작업 묶음을 열고 (prior 가 있으면 먼저 보내 보고) 묶음을 만든 뒤 닫는다."""
    res = {"id": case["id"], "set": case["set"], "cat": case["cat"], "ok": False, "checks": [], "roundtrip": None,
           "auto": 0, "error": None}  # type: Dict[str, Any]
    vault.open_project(home, False)
    try:
        if case["prior"]:
            man = _write_files(os.path.join(workroot, case["id"] + "-prior"), case["prior"])
            with vault.Vault.locked(home, False) as v:
                pr = bundle.build_bundle(man, os.path.join(workroot, case["id"] + "-prior"), v, policy, words)
            if not pr["ok"]:
                res["error"] = "prior"
                return res
        wd = os.path.join(workroot, case["id"])
        man = _write_files(wd, case["files"])
        try:
            with vault.Vault.locked(home, False) as v:
                out = bundle.build_bundle(man, wd, v, policy, words)
                if out["ok"]:
                    res["roundtrip"] = all(f["text"] is not None and bundle.restore_text(f["text"], v)[0] == unmark(src[2])
                                           for f, src in zip(out["files"], case["files"]))
        except bundle.BundleError as e:
            res["checks"] = [e.code]
            return res
        res["ok"] = bool(out["ok"])
        res["checks"] = _checks_of(out["hits"])
        res["auto"] = int(out["stats"]["auto"])
        return res
    finally:
        vault.close_project(home)


def run_corpus(cases: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """임시 데이터 폴더 (DIODE_HOME 자리 · 기본 자리가 아니라 평문 금고) 에 합성 사전을 두고 묶음마다 돌린다."""
    tmp = tempfile.mkdtemp(prefix="diode-bundle-corpus-")
    try:
        home = os.path.join(tmp, "data")
        os.makedirs(home)
        with io.open(os.path.join(home, "dictionary.json"), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "words": WORDS}, f, ensure_ascii=False)
        policy = scan.policy_from_home(home)
        words = config.read_words(home)
        workroot = os.path.join(tmp, "work")
        os.makedirs(workroot)
        return [run_case(home, policy, words, c, workroot) for c in cases]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────────────────────────────────────── 세기

def _rate(a: int, b: int) -> Optional[float]:
    return None if b == 0 else round(a / float(b), 4)


def _blocked_ok(r: Dict[str, Any]) -> bool:
    """leaky 가 '막혔다' 고 셀 수 있는가 - 잔여 검사 · note 검사 · 꼴 오류 (E-04) 로만 (E-20 같은 내부 오류는 아니다)."""
    return (not r["ok"]) and bool(r["checks"]) and all(c in BLOCK_CHECKS for c in r["checks"]) and not r["error"]


def summarize(cases: Sequence[Dict[str, Any]], results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    good = [r for r in results if r["set"] == GOOD]
    leaky = [r for r in results if r["set"] == LEAKY]
    miss = [r for r in results if r["set"] == MISS]
    by_kind = {}  # type: Dict[str, Dict[str, int]]
    for r in good:
        d = by_kind.setdefault(r["cat"], {"total": 0, "passed": 0})
        d["total"] += 1
        d["passed"] += 1 if r["ok"] and r["roundtrip"] else 0
    leaky_cat = {}  # type: Dict[str, Dict[str, Any]]
    for cat, _label in LEAKY_CATEGORIES:
        leaky_cat[cat] = {"total": 0, "blocked": 0, "checks": {}}
    for r in leaky:
        d = leaky_cat.setdefault(r["cat"], {"total": 0, "blocked": 0, "checks": {}})
        d["total"] += 1
        if _blocked_ok(r):
            d["blocked"] += 1
            for c in r["checks"]:
                d["checks"][c] = d["checks"].get(c, 0) + 1
    for d in leaky_cat.values():
        d["checks"] = dict((c, d["checks"][c]) for c in CHECK_ORDER if c in d["checks"])
    miss_cat = {}  # type: Dict[str, Dict[str, Any]]
    for cat, _label in MISS_CATEGORIES:
        miss_cat[cat] = {"total": 0, "passed": 0}
    for r in miss:
        d = miss_cat.setdefault(r["cat"], {"total": 0, "passed": 0})
        d["total"] += 1
        d["passed"] += 1 if r["ok"] else 0
    n_good_ok = sum(1 for r in good if r["ok"])
    n_rt = sum(1 for r in good if r["roundtrip"])
    n_blocked = sum(1 for r in leaky if _blocked_ok(r))
    n_miss_pass = sum(1 for r in miss if r["ok"])
    fails = []  # type: List[Dict[str, Any]]
    for r in good:
        if not r["ok"] or not r["roundtrip"]:
            fails.append({"id": r["id"], "why": "prior" if r["error"] else ("roundtrip" if r["ok"] else "blocked"),
                          "checks": list(r["checks"])})
    for r in leaky:
        if not _blocked_ok(r):
            fails.append({"id": r["id"], "why": "prior" if r["error"] else ("passed" if r["ok"] else "error"),
                          "checks": list(r["checks"])})
    for r in miss:
        if r["error"]:
            fails.append({"id": r["id"], "why": "error", "checks": list(r["checks"])})
    shape = []  # type: List[str]
    if len(good) < MIN_GOOD:
        shape.append("good %d < %d" % (len(good), MIN_GOOD))
    if len(leaky) < MIN_LEAKY:
        shape.append("leaky %d < %d" % (len(leaky), MIN_LEAKY))
    shape.extend("leaky 범주 %s 가 비었다" % c for c, d in leaky_cat.items() if not d["total"])
    if corpus_digest(corpus()) != corpus_digest(cases):
        shape.append("코퍼스가 결정적이지 않다")
    return {
        "format": 1,
        "corpus": {"good": len(good), "leaky": len(leaky), "known_miss": len(miss), "digest": corpus_digest(cases)},
        "good": {"total": len(good), "passed": n_good_ok, "roundtrip_ok": n_rt, "rate": _rate(n_good_ok, len(good)),
                 "auto": sum(r["auto"] for r in good), "by_kind": by_kind},
        "leaky": {"total": len(leaky), "blocked": n_blocked, "rate": _rate(n_blocked, len(leaky)), "by_category": leaky_cat},
        "known_miss": {"total": len(miss), "passed": n_miss_pass, "rate": _rate(n_miss_pass, len(miss)),
                       "by_category": miss_cat},
        "failures": fails,
        "shape_problems": shape,
    }


def corpus_digest(cases: Sequence[Dict[str, Any]]) -> str:
    """코퍼스의 sha256 앞 16자 - 같은 판 · 같은 코퍼스인지 보는 데만 쓴다 (글은 찍지 않는다)."""
    blob = json.dumps([[c["id"], c["cat"], c["files"], c["prior"]] for c in cases], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def verdict(report: Dict[str, Any]) -> Tuple[str, int]:
    g, lk = report["good"], report["leaky"]
    ok = (not report["failures"] and not report["shape_problems"] and g["passed"] == g["total"]
          and g["roundtrip_ok"] == g["total"] and lk["blocked"] == lk["total"])
    return ("OK", 0) if ok else ("점검 실패", 1)


# ───────────────────────────────────────────────────────── 사람이 읽는 표

def _pct(a: int, b: int) -> str:
    if b == 0:
        return "-"
    return "%d/%d (%.1f%%)" % (a, b, 100.0 * a / b)


def _pad(s: str, n: int) -> str:
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)
    return s + " " * max(0, n - w)


def render_table(report: Dict[str, Any]) -> str:
    c, g, lk, m = report["corpus"], report["good"], report["leaky"], report["known_miss"]
    lines = ["가린 묶음 코퍼스 - 묶음 %d (good %d · leaky %d · known-miss %d) · 코퍼스 %s" % (
        c["good"] + c["leaky"] + c["known_miss"], c["good"], c["leaky"], c["known_miss"], c["digest"]), ""]
    lines.append("good        통과 %s · 왕복 일치 %s · 자동 가림 %d" % (_pct(g["passed"], g["total"]),
                                                                _pct(g["roundtrip_ok"], g["total"]), g["auto"]))
    for kind, label in GOOD_KINDS:
        d = g["by_kind"].get(kind)
        if d:
            lines.append("  %s %s" % (_pad(label, 16), _pct(d["passed"], d["total"])))
    lines.append("")
    lines.append("leaky       막음 %s" % _pct(lk["blocked"], lk["total"]))
    for cat, label in LEAKY_CATEGORIES:
        d = lk["by_category"][cat]
        checks = " · ".join("%s %d" % kv for kv in d["checks"].items()) or "-"
        lines.append("  %s %s  잡은 검사 %s" % (_pad(label, 44), _pad("%d/%d" % (d["blocked"], d["total"]), 6), checks))
    lines.append("")
    lines.append("known-miss  지나감 %s - 기록용 · 합격 기준 밖 (SP-20 › 남는 위험)" % _pct(m["passed"], m["total"]))
    for cat, label in MISS_CATEGORIES:
        d = m["by_category"][cat]
        lines.append("  %s 지나감 %d/%d" % (_pad(label, 44), d["passed"], d["total"]))
    for f in report["failures"][:40]:
        lines.append("실패: %s %s%s" % (f["id"], f["why"], " (%s)" % ", ".join(f["checks"]) if f["checks"] else ""))
    for s in report["shape_problems"]:
        lines.append("실패: %s" % s)
    return "\n".join(lines)


def self_test_lines(report: Dict[str, Any]) -> List[str]:
    """--self-test 의 줄 (leak_rate --self-test 와 같은 꼴 · 개수만)."""
    g, lk, m = report["good"], report["leaky"], report["known_miss"]
    lines = ["good %d개 · 통과 %d/%d · 왕복 일치 %d/%d" % (g["total"], g["passed"], g["total"], g["roundtrip_ok"], g["total"]),
             "leaky %d개 · 막음 %d/%d" % (lk["total"], lk["blocked"], lk["total"]),
             "known-miss %d개 · 지나감 %d/%d (기록용 · 합격 기준 밖)" % (m["total"], m["passed"], m["total"])]
    for f in report["failures"][:40]:
        lines.append("실패: %s %s%s" % (f["id"], f["why"], " (%s)" % ", ".join(f["checks"]) if f["checks"] else ""))
    if len(report["failures"]) > 40:
        lines.append("실패 %d건 더 있음" % (len(report["failures"]) - 40))
    for s in report["shape_problems"]:
        lines.append("실패: %s" % s)
    return lines


# ───────────────────────────────────────────────────────── 명령줄

def _stdout_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _stdout_utf8()
    ap = argparse.ArgumentParser(description="가린 묶음 코퍼스: 합성 묶음을 build_bundle 에 돌려 통과 · 막힘 · 왕복을 센다.")
    ap.add_argument("--json", metavar="파일", help="JSON 보고를 이 파일에 쓴다 ('-' 이면 표 대신 표준 출력에)")
    ap.add_argument("--self-test", action="store_true", help="합격 기준만 본다 (good 전부 통과 · leaky 전부 막힘 · 왕복 일치)")
    args = ap.parse_args(argv)
    cases = corpus()
    report = summarize(cases, run_corpus(cases))
    word, code = verdict(report)
    if args.json and args.json != "-":
        with io.open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    if args.json == "-":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return code
    print("\n".join(self_test_lines(report) if args.self_test else [render_table(report)]))
    print("결과: " + word)
    return code


if __name__ == "__main__":
    cv.run_cli(main)
