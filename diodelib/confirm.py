# -*- coding: utf-8 -*-
"""확정 창 (D8 · SP-09) - 사람이 보낼 바이트 그대로를 보고 눌러야 나간다 (표준 라이브러리 · Python 3.8).

`python diode.py confirm <요청 파일>` 이 부른다. 허브 (MCP 서버) 가 따로 된 프로세스로 띄우고, 이 프로세스는
요청 파일을 읽어 창을 보이고, 사람의 결정을 표준 출력 한 줄 JSON 으로 돌려준다. 가명 표는 창에 오지 않는다.

요청 파일 (format 1) - UTF-8 JSON 객체 하나 · 256 KiB 이하 (가린 묶음 bundle 만 4 MiB 이하) [제안].
같은 키 두 번 · NaN · 모르는 칸은 오류다.
  {"format": 1, "direction": "out" | "dispatch", "job": "J-0007", "kind": "report" | "plan" | "ui" | "lib" | "bundle",
   "transport": "room" | "clipboard", "text": "<보낼 바이트 그대로 (UTF-8 글)>", "attachments": ["a.html"],
   "checks": {"ok": true, "hits": []}, "model": "<이름>", "effort": "high",
   "month": {"pct": 12, "estimated": false}, "effort_env_override": false, "timeout_s": 600}
  - direction  out = 바깥으로 보내기 (단추 [보내기]) · dispatch = 안쪽 일꾼에게 넘기기 (단추 [넘기기]).
               넘기는 지시는 토큰을 되돌린 글이라 사내 말이 보일 수 있다 - 이 창 안에서만.
  - job        J-0007 꼴 (J- 와 숫자 4-9자리)
  - text       비어 있지 않은 글 · UTF-8 로 64 KiB 이하 [제안]. 창은 이 글을 그대로 보이고, 결과의 sha256 은 이 글의 UTF-8 바이트다
               (bundle 이면 MANIFEST.md 글이고 sha256 은 묶음 다이제스트 - 아래)
  - attachments  글 20개 이하 (각 120자 이하 · 한 줄). 없으면 [] (bundle 은 반드시 [])
  - checks     SP-05 의 결과 꼴. ok 가 참이면 hits 는 비어 있고 거짓이면 비어 있지 않다. 거짓이면 보내기 단추는 끝까지 꺼져 있다
  - model      한 줄 글 (80자 이하 · 빈 글 가능 = 창에 "-")
  - effort     "" | auto | low | medium | high | xhigh | max
  - month      pct = 0-1000 의 수 또는 null (한도를 모름 = 창에 "-") · estimated = 어림이면 true (창에 "~12%")
  - effort_env_override  (없어도 됨 · 없으면 false) 참이면 "환경 변수 CLAUDE_CODE_EFFORT_LEVEL 이 effort 를 덮어씁니다" 알림
  - timeout_s  (없어도 됨 · 없으면 600) 1-600 으로 자른다 [제안]
  가린 파일 묶음 (SP-20 · kind "bundle") - direction "out" · transport "room" 일 때만. 아래 두 칸이 꼭 있다 (다른 kind 에는 없다).
  - files      [{"name": "F01.md", "type": "doc" | "table" | "code", "text": "<가린 바이트 그대로>"}] 1-20개.
               name 은 F + 숫자 2-4자리 + . + 영숫자 1-8자 · 이름이 겹치지 않음 (대소문자 무시) ·
               text 는 text 칸과 같은 규칙에 파일마다 256 KiB · 합계 1 MiB 이하
  - stats      {"files": n, "bytes": n, "tokens": n, "marked": n, "auto": n} 0 이상의 정수 (bool 아님) ·
               files = 파일 수 · bytes = 파일 글의 UTF-8 바이트 합 (둘 다 실제와 같아야 한다)
  되돌린 첨부 (SP-20 · 넘기기) - direction "dispatch" 에만 있을 수 있는 칸 하나.
  - restored   [{"name": "<되돌린 이름>", "tokens": n}] attachments 와 길이 · 차례 · 이름이 같다 · tokens 는 되돌린 토큰 수
모르는 format · 빠진 칸 · 꼴이 틀린 칸 · 읽을 수 없는 JSON -> 창을 띄우지 않고 E-04.

결과 (표준 출력 한 줄 JSON · 글 · 단어는 넣지 않는다 - sha256 만)
  {"decision": "send" | "discard" | "edit" | "timeout", "sha256": "<text 의 UTF-8 sha256 · bundle 은 bundle_sha256>"}
  {"decision": "error", "code": "E-04" | "E-07" | "E-20"}
  send = [보내기] / [넘기기] (clipboard 는 [보내기] 다음에 [복사] 가 성공한 뒤) · discard = [버리기] · 창 닫기 · Esc ·
  edit = [고치기] (허브가 다시 seal 한다) · timeout = 시간이 다 됨.
종료 코드: 0 send · 3 discard / edit / timeout (사람의 결정) · 2 요청 파일 꼴 오류 (E-04) ·
           1 창을 못 띄움 (E-07) 또는 그 밖의 예외 (E-20). 어떤 예외도 send 로 끝나지 않는다 (AL-03).

구조 - 논리와 화면을 나눈다.
  ConfirmSession  시간 · 단추 상태 · 결정 · (bundle) 연 항목. 화면을 모른다. 시각은 부르는 쪽이 now 로 준다.
  TkView          tkinter 화면. 그리기만 하고, 누른 것은 session 에 알린다.
  create_view()   화면 백엔드를 만드는 곳. 시험은 이 이름을 바꿔 끼워 가짜 화면으로 논리를 본다 (AL-02).

지키는 것
- 건너뛰는 길이 없다 (AL-02): 환경 변수 · 설정 · 명령줄 인자로 확정을 건너뛰지 않는다. 읽는 환경 변수는
  창을 띄울 화면이 있는지 보는 DISPLAY · WAYLAND_DISPLAY 둘뿐이다 (E-07 쪽으로만 작용한다).
- 보내기 단추는 창이 뜬 지 SEND_DELAY_S 뒤에 켜진다 · 기본 초점은 [버리기] · Enter 로 보내지 않는다 ·
  창 닫기 (X) 와 Esc 는 버리기 · 시간이 지나면 timeout.
- 가린 묶음은 MANIFEST 와 모든 파일을 한 번씩 글 칸에 열어 봐야 [보내기] 가 켜진다 (습관 확정 줄이기 · L-13).
- 요청 파일을 지우지 않고 아무 파일도 쓰지 않는다 (지우는 것은 허브). 출력 · 로그에 글을 쓰지 않는다 (AL-11).
- 화면 문구는 한국어, 색은 works DESIGN.md 의 네이비 · 라임 · 회색뿐이다 - 빨강 없음 (W-10).
"""

import collections
import hashlib
import json
import math
import os
import re
import time
import unicodedata

from . import scan
from .render import SAMPLE_HEAD

# ---------------------------------------------------------------- 상수

FORMAT = 1
DIRECTIONS = ("out", "dispatch")
KINDS = ("report", "plan", "ui", "lib", "bundle")
BUNDLE = "bundle"                   # 가린 파일 묶음 (SP-20) - 바깥으로 · 방으로만
FILE_TYPES = ("doc", "table", "code")
TRANSPORTS = ("room", "clipboard")
EFFORTS = ("", "auto", "low", "medium", "high", "xhigh", "max")
DECISIONS = ("send", "discard", "edit", "timeout")

MAX_REQUEST_BYTES = 4 * 1024 * 1024     # 요청 파일 상한 [제안] - 가린 묶음 (파일 합계 1 MiB) 의 JSON 이스케이프 몫까지
MAX_PLAIN_REQUEST_BYTES = 256 * 1024    # 묶음이 아닌 요청의 상한 [제안] (SP-09)
MAX_TEXT_BYTES = 64 * 1024          # 보낼 글 상한 [제안] - 펼친 글은 8 KiB (SP-02) · 되돌린 지시는 더 길 수 있다
MAX_ATTACHMENTS = 20                # 묶음의 파일 수와 같게 (SP-20 · 허브도 같다)
MAX_NAME_CHARS = 120                # SP-08
MAX_BUNDLE_FILES = 20               # SP-20 묶음 꼴의 한도
MAX_FILE_BYTES = 256 * 1024         # 파일마다 (SP-20)
MAX_BUNDLE_BYTES = 1024 * 1024      # 파일 합계 (SP-20)
MAX_STAT = 10 ** 9                  # stats 의 수 하나의 상한 - 창에 적을 수 있는 크기로 (있을 수 없는 값을 막는다)
MANIFEST_NAME = "MANIFEST.md"       # 묶음의 첫 항목 (허브가 만든 목록 글 = text)
MANIFEST_TYPE = "manifest"
STATS_KEYS = ("files", "bytes", "tokens", "marked", "auto")
MAX_MODEL_CHARS = 80
MAX_HITS = 32
MAX_WHERE = 50
MAX_WHERE_CHARS = 64

DEFAULT_TIMEOUT_S = 600             # 10 분 [제안] (SP-05 D8)
MIN_TIMEOUT_S = 1
MAX_TIMEOUT_S = 600
SEND_DELAY_S = 2.0                  # 창이 뜬 뒤 보내기 단추가 켜지기까지 [제안] - 습관으로 누르는 것을 줄인다
POLL_S = 0.05                       # 화면을 돌보는 간격
SCREEN_MARGIN_PX = 120              # 창 제목줄 · 작업 표시줄 몫 - 창이 이만큼 뺀 화면 높이를 넘으면 글 칸의 줄 수를 줄인다
TEXT_ROWS = 14                      # 글 칸 (와 묶음의 항목 목록) 의 처음 줄 수
ITEM_ROW = " %s %-14s %-8s %7d B %6d"                                   # 묶음 목록의 한 줄 (연 표시 · 이름 · 종류 · 바이트 · 줄)
ITEM_HEAD = "   %-14s %-8s %9s %6s" % ("NAME", "TYPE", "BYTES", "LINES")  # 그 위의 칸 이름 (같은 너비)
WRAP_MARGIN_PX = 70                 # 줄을 감는 너비 = 글 칸의 너비 - 이 여백

EXIT_SEND, EXIT_FAILED, EXIT_BAD_REQUEST, EXIT_HUMAN = 0, 1, 2, 3
ERROR_EXIT = {"E-04": EXIT_BAD_REQUEST, "E-07": EXIT_FAILED, "E-20": EXIT_FAILED}

# works DESIGN.md › 02 색 - 네이비 · 라임 두 계열과 무채색뿐 (빨강 없음). 값은 DESIGN.md 의 표 그대로.
PALETTE = {
    "navy": "#002341", "navy1": "#08365E", "navy2": "#1F507A", "navy3": "#3F77A6", "navy4": "#75A1C7", "navy5": "#B8CEE0",
    "lime0": "#2C4912", "lime1": "#45741B", "lime": "#6ABA23", "lime3": "#95D85A", "lime4": "#C0E79D",
    "black": "#000000", "gray0": "#35383B", "gray1": "#5C6166", "gray2": "#81888D", "gray": "#A5AAAE",
    "gray4": "#D4D6D8", "white": "#F2F2F3",
}
# 글꼴: DESIGN.md › 04 의 GNU Unifont 가 깔려 있으면 그것 (16px 정수배) · 없으면 고정폭 글꼴
UNIFONT = "Unifont"
MONO_FAMILIES = ("Consolas", "D2Coding", "DejaVu Sans Mono", "Liberation Mono")
WINDOW_TITLE = "Diode - 확정"

# 화면 문구 (한국어 · 이모지 없음 · DESIGN.md › 03 의 기호만)
TEXT_IRREVERSIBLE = {"out": "보내면 되돌릴 수 없습니다", "dispatch": "넘기면 되돌릴 수 없습니다"}
TEXT_AUDIT = "이 내용이 감사 기록에 남습니다"
TEXT_EFFORT_ENV = "‼ 환경 변수 CLAUDE_CODE_EFFORT_LEVEL 이 effort 를 덮어씁니다"
TEXT_INNER_WORDS = "이 글은 토큰을 되돌린 지시라 사내 말이 보일 수 있습니다 (이 창 안에서만)"
TEXT_HIDDEN = "‼ 보이지 않는 글자 %d개가 있어 [U+XXXX] 꼴로 표시했습니다"
TEXT_SAMPLE = ("‼ 표가 들어 있습니다 (%d열 · %d행) - 이 표는 실값에서 줄인 값이고, 재식별이 안 된다고 증명할 수 없습니다 "
               "(열 · 칸을 글 그대로 보세요)")
TEXT_CHECK_BLOCKED = "검사에 걸린 글이라 보낼 수 없습니다 - [고치기] 로 돌아가세요"
TEXT_APPROVED = "보내기를 눌렀습니다 - [복사] 를 누르면 클립보드에 넣고 끝납니다 (복사 = 보냄)"
TEXT_COPY_FAILED = "클립보드에 넣지 못했습니다 - 다시 눌러 보거나 [버리기] 를 누르세요"
# 가린 파일 묶음 (SP-20) · 되돌린 첨부
TEXT_BUNDLE_SUBTITLE = "가린 파일 %d개를 회사 밖 (Claude) 방으로 보냅니다"
TEXT_BUNDLE_ACT = "[보내기] 를 누르면 이 파일들이 그대로 방의 outbox/%s/ 에 쓰입니다"
TEXT_BUNDLE_SAFETY_NET = "‼ 자동 가림 %d개 - opencode 의 표시가 모자랐습니다. 파일을 꼼꼼히 보세요"
TEXT_BUNDLE_MARKS = "opencode 가 표시한 곳 %d개 · Diode 가 자동으로 가린 곳 %d개"
TEXT_UNVIEWED = "아직 안 본 파일 %d개 - 목록에서 하나씩 열어 보세요"
TEXT_BUNDLE_FILES = "MANIFEST.md + 파일 %d개 - 01 TEXT 의 목록에서 하나씩 엽니다"
TEXT_RESTORED = "첨부 %d개를 금고로 되돌려 넘깁니다 (진짜 값은 이 PC 안에만)"


class RequestError(Exception):
    """요청 파일의 꼴이 틀렸다 (E-04). 메시지에는 칸 이름만 쓴다 - 글을 쓰지 않는다."""


class WindowUnavailable(Exception):
    """창을 띄울 수 없다 (E-07): 화면이 없음 · tkinter 가 없음 · Tk 를 못 엶."""


# ---------------------------------------------------------------- 요청 파일 읽기 (E-04)

_JOB_RE = re.compile(r"J-[0-9]{4,9}\Z")
_CODE_RE = re.compile(r"E-[0-9]{2}\Z")
_CHECK_RE = re.compile(r"[A-Za-z0-9]{1,4}\Z")
_REQUIRED = ("format", "direction", "job", "kind", "transport", "text", "attachments", "checks", "model", "effort",
             "month")
_OPTIONAL = ("effort_env_override", "timeout_s")
_BUNDLE_ONLY = ("files", "stats")           # kind bundle 에는 꼭 있고 다른 kind 에는 없다
_DISPATCH_ONLY = ("restored",)              # direction dispatch 에만 있을 수 있다
_FILE_NAME_RE = re.compile(r"F[0-9]{2,4}\.[A-Za-z0-9]{1,8}\Z")      # 나가는 이름 (SP-20) - 원래 이름은 금고에만
_FILE_KEYS = frozenset(["name", "type", "text"])
_RESTORED_KEYS = frozenset(["name", "tokens"])

# 묶음의 항목 하나 (MANIFEST 또는 파일) - 이름 · 종류 · 글 · UTF-8 바이트 수 · 줄 수
BundleFile = collections.namedtuple("BundleFile", "name type text bytes lines")


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("같은 키 두 번")
        out[k] = v
    return out


def _no_constant(name):
    raise ValueError("NaN · Infinity")


def text_sha256(text):
    """보낼 글의 UTF-8 바이트의 sha256 (16진 소문자). 허브는 자기가 보낼 글로 이 값을 구해 결과와 맞춰 본다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bundle_sha256(manifest_text, files):
    """가린 묶음의 다이제스트 (16진 소문자) - 확정 창 결과의 sha256 (SP-20).

    sha256( json.dumps([MANIFEST 글, [[이름, 종류, 파일 글의 UTF-8 sha256 (16진 소문자)], ...]],
                       ensure_ascii=False, separators=(",", ":")) 의 UTF-8 ).
    files 는 요청의 files 칸 그대로 ({"name", "type", "text"} 의 목록 · 차례대로). 허브는 이 함수를 불러 자기가 쓸
    파일들로 값을 구해 결과와 맞춰 본다 - 한 파일의 한 바이트 · 이름 · 종류 · 차례가 달라도 값이 다르다.
    """
    rows = [[f["name"], f["type"], text_sha256(f["text"])] for f in files]
    blob = json.dumps([manifest_text, rows], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def line_count(text):
    """줄 수 - 마지막 줄바꿈 뒤의 빈 줄은 세지 않는다."""
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _line(v, name, limit, empty=False):
    """한 줄 글 칸: 글 · 길이 · 제어 문자 (줄바꿈 포함) 없음. 창의 한 줄 칸에 그대로 보이므로 겉모습을 속일 수 없게 막는다."""
    if type(v) is not str or len(v) > limit or (not v and not empty):
        raise RequestError(name)
    for ch in v:
        if unicodedata.category(ch)[0] == "C" or ch in "\u2028\u2029":
            raise RequestError(name)
    return v


def _flag(v, name):
    if type(v) is not bool:
        raise RequestError(name)
    return v


def _number(v, name, lo, hi):
    if type(v) not in (int, float) or not math.isfinite(v) or not lo <= v <= hi:
        raise RequestError(name)
    return v


def _choice(v, name, choices):
    if type(v) is not str or v not in choices:
        raise RequestError(name)
    return v


def _count(v, name):
    """0 이상의 정수 (bool 아님 · MAX_STAT 이하)."""
    if type(v) is not int or not 0 <= v <= MAX_STAT:
        raise RequestError(name)
    return v


def _utf8_text(v, name, limit):
    """비어 있지 않은 글 -> UTF-8 바이트 수. 홀로 선 서로게이트 (\\ud800) 는 바이트가 될 수 없다 · limit 바이트 이하."""
    if type(v) is not str or not v:
        raise RequestError(name)
    try:
        size = len(v.encode("utf-8"))
    except UnicodeEncodeError:
        raise RequestError(name)
    if size > limit:
        raise RequestError(name)
    return size


def _files(v):
    """가린 묶음의 파일들 (SP-20) -> (BundleFile, ...). 1-20개 · 이름 꼴 · 겹침 (대소문자 무시 - Windows 폴더에서 같은 파일) ·
    종류 · 글 (text 칸과 같은 규칙 · 파일마다 256 KiB) · 합계 1 MiB."""
    if type(v) is not list or not 1 <= len(v) <= MAX_BUNDLE_FILES:
        raise RequestError("files")
    out, seen, total = [], set(), 0
    for f in v:
        if type(f) is not dict or set(f) != _FILE_KEYS:
            raise RequestError("files")
        name = f["name"]
        if type(name) is not str or not _FILE_NAME_RE.match(name) or name.lower() in seen:
            raise RequestError("files")
        seen.add(name.lower())
        _choice(f["type"], "files", FILE_TYPES)
        size = _utf8_text(f["text"], "files", MAX_FILE_BYTES)
        total += size
        if total > MAX_BUNDLE_BYTES:
            raise RequestError("files")
        out.append(BundleFile(name, f["type"], f["text"], size, line_count(f["text"])))
    return tuple(out)


def _stats(v, files):
    """묶음의 수 (SP-20). 키 집합이 정확하고 · 모두 0 이상의 정수 · files 와 bytes 는 실제 파일과 같다."""
    if type(v) is not dict or set(v) != set(STATS_KEYS):
        raise RequestError("stats")
    for key in STATS_KEYS:
        _count(v[key], "stats")
    if v["files"] != len(files) or v["bytes"] != sum(f.bytes for f in files):
        raise RequestError("stats")
    return dict((key, v[key]) for key in STATS_KEYS)


def _restored(v, attachments):
    """되돌린 첨부 (넘기기) -> ((이름, 되돌린 토큰 수), ...). attachments 와 길이 · 차례 · 이름이 같아야 한다."""
    if type(v) is not list or len(v) != len(attachments):
        raise RequestError("restored")
    out = []
    for item, name in zip(v, attachments):
        if type(item) is not dict or set(item) != _RESTORED_KEYS:
            raise RequestError("restored")
        _line(item["name"], "restored", MAX_NAME_CHARS)
        if item["name"] != name:
            raise RequestError("restored")
        out.append((name, _count(item["tokens"], "restored")))
    return tuple(out)


def _checks(v):
    """SP-05 의 결과 꼴. 사람에게 보일 한 줄 (scan.format_line) 이 깨지지 않게 칸마다 꼴을 본다."""
    if type(v) is not dict or set(v) != {"ok", "hits"}:
        raise RequestError("checks")
    ok, hits = v["ok"], v["hits"]
    if type(ok) is not bool or type(hits) is not list or len(hits) > MAX_HITS or bool(hits) == ok:
        raise RequestError("checks")
    for h in hits:
        if type(h) is not dict:
            raise RequestError("checks")
        if set(h) == {"check", "code"}:
            if h["check"] != "E" or type(h["code"]) is not str or not _CODE_RE.match(h["code"]):
                raise RequestError("checks")
        elif set(h) == {"check", "count", "where"}:
            count, where = h["count"], h["where"]
            if type(h["check"]) is not str or not _CHECK_RE.match(h["check"]):
                raise RequestError("checks")
            if type(count) is not int or not 0 <= count <= 99999 or type(where) is not list or len(where) > MAX_WHERE:
                raise RequestError("checks")
            for w in where:
                _line(w, "checks", MAX_WHERE_CHARS)
                if not w.isascii():
                    raise RequestError("checks")
        else:
            raise RequestError("checks")
    return v


class Request(object):
    """검사를 마친 요청. 칸은 parse_request 가 모두 확인했다.

    bundle 이면 files (BundleFile 들) · stats (사전) 가 있고, items 는 MANIFEST (text) 를 첫 항목으로 한 창의 목록이다.
    sha256 은 bundle 이면 bundle_sha256 · 아니면 text 의 sha256. restored 는 넘기기의 ((이름, 토큰 수), ...) 또는 None.
    """

    def __init__(self, data, files=(), stats=None, restored=None):
        self.direction = data["direction"]
        self.job = data["job"]
        self.kind = data["kind"]
        self.transport = data["transport"]
        self.text = data["text"]
        self.text_bytes = len(self.text.encode("utf-8"))
        self.is_bundle = self.kind == BUNDLE
        self.files = tuple(files)
        self.stats = stats
        self.restored = restored
        if self.is_bundle:
            self.sha256 = bundle_sha256(self.text, [f._asdict() for f in self.files])
            manifest = BundleFile(MANIFEST_NAME, MANIFEST_TYPE, self.text, self.text_bytes, line_count(self.text))
            self.items = (manifest,) + self.files
        else:
            self.sha256 = text_sha256(self.text)
            self.items = ()
        self.attachments = tuple(data["attachments"])
        self.checks = data["checks"]
        self.checks_ok = data["checks"]["ok"]
        self.model = data["model"]
        self.effort = data["effort"]
        self.month_pct = data["month"]["pct"]
        self.month_estimated = data["month"]["estimated"]
        self.effort_env_override = data.get("effort_env_override", False)
        self.timeout_s = float(min(MAX_TIMEOUT_S, max(MIN_TIMEOUT_S, data.get("timeout_s", DEFAULT_TIMEOUT_S))))


def parse_request(raw):
    """요청 파일의 바이트 -> Request. 꼴이 틀리면 RequestError (E-04).

    크기: 4 MiB (MAX_REQUEST_BYTES) 까지 읽고, 묶음 (bundle) 이 아닌 요청은 256 KiB (MAX_PLAIN_REQUEST_BYTES) 를 넘으면 E-04.
    """
    size = len(raw)
    if size > MAX_REQUEST_BYTES:
        raise RequestError("size")
    try:
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, RecursionError, AttributeError):        # UnicodeDecodeError 는 ValueError
        raise RequestError("json")
    if type(data) is not dict:
        raise RequestError("json")
    if type(data.get("format")) is not int or data["format"] != FORMAT:
        raise RequestError("format")
    keys = set(data)
    if not set(_REQUIRED) <= keys:
        raise RequestError("missing")
    if not keys <= set(_REQUIRED) | set(_OPTIONAL) | set(_BUNDLE_ONLY) | set(_DISPATCH_ONLY):
        raise RequestError("unknown")
    _choice(data["direction"], "direction", DIRECTIONS)
    if type(data["job"]) is not str or not _JOB_RE.match(data["job"]):
        raise RequestError("job")
    _choice(data["kind"], "kind", KINDS)
    _choice(data["transport"], "transport", TRANSPORTS)
    bundle = data["kind"] == BUNDLE
    if bundle:
        if data["direction"] != "out" or data["transport"] != "room":       # 가린 묶음은 바깥으로 · 방으로만
            raise RequestError("kind")
        if not set(_BUNDLE_ONLY) <= keys:
            raise RequestError("missing")
    else:
        if size > MAX_PLAIN_REQUEST_BYTES:
            raise RequestError("size")
        if keys & set(_BUNDLE_ONLY):
            raise RequestError("unknown")
    if keys & set(_DISPATCH_ONLY) and data["direction"] != "dispatch":
        raise RequestError("unknown")
    _utf8_text(data["text"], "text", MAX_TEXT_BYTES)
    att = data["attachments"]
    if type(att) is not list or len(att) > MAX_ATTACHMENTS or (bundle and att):
        raise RequestError("attachments")
    for name in att:
        _line(name, "attachments", MAX_NAME_CHARS)
    files = _files(data["files"]) if bundle else ()
    stats = _stats(data["stats"], files) if bundle else None
    restored = _restored(data["restored"], att) if "restored" in keys else None
    _checks(data["checks"])
    _line(data["model"], "model", MAX_MODEL_CHARS, empty=True)
    _choice(data["effort"], "effort", EFFORTS)
    month = data["month"]
    if type(month) is not dict or set(month) != {"pct", "estimated"}:
        raise RequestError("month")
    if month["pct"] is not None:
        _number(month["pct"], "month", 0, 1000)
    _flag(month["estimated"], "month")
    if "effort_env_override" in data:
        _flag(data["effort_env_override"], "effort_env_override")
    if "timeout_s" in data:
        _number(data["timeout_s"], "timeout_s", -math.inf, math.inf)     # 수이기만 하면 된다 - 1-600 으로 자르는 것은 Request
    return Request(data, files, stats, restored)


def read_request(path):
    """요청 파일을 읽는다. path 가 글이 아니면 RequestError (사용법 오류) · 읽지 못하면 OSError (부르는 쪽이 E-20).

    4 MiB 하나 더까지만 읽는다 - 크기를 kind 에 따라 가르는 것은 parse_request."""
    if type(path) is not str or not path:
        raise RequestError("path")
    with open(path, "rb") as f:
        raw = f.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise RequestError("size")
    return parse_request(raw)


# ---------------------------------------------------------------- 보이는 것 (화면과 무관한 내용)

# 보이지 않거나 겉모습을 속일 수 있는 글자 - 글 그대로를 보이려면 이것들은 [U+XXXX] 로 드러내야 한다
_HIDDEN_CATEGORIES = frozenset(["Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs"])
_HIDDEN_OTHERS = frozenset([0x034F, 0x115F, 0x1160, 0x2800, 0x3164, 0xFFA0])      # 빈 모양의 글자 (한글 채움 글자 등)


def is_hidden_char(ch):
    """보통의 빈칸 · 줄바꿈 · 탭이 아닌데 보이지 않거나 모양을 바꾸는 글자 (제어 · 서식 · 다른 빈칸 · 변이 선택자 ...)."""
    if ch in (" ", "\n", "\t"):
        return False
    if unicodedata.category(ch) in _HIDDEN_CATEGORIES:
        return True
    o = ord(ch)
    return o in _HIDDEN_OTHERS or 0xFE00 <= o <= 0xFE0F or 0xE0100 <= o <= 0xE01EF


def _plain_segments(out, s):
    run = []
    for ch in s:
        if is_hidden_char(ch):
            if run:
                out.append(("".join(run), None))
                run = []
            out.append(("[U+%04X]" % ord(ch), "hidden"))
        else:
            run.append(ch)
    if run:
        out.append(("".join(run), None))


def display_segments(text):
    """보일 조각 [(글, 꼴)]. 꼴: None 보통 · "token" 가명 토큰 (강조) · "hidden" 보이지 않는 글자를 드러낸 표시.

    보통 · 토큰 조각을 이어 붙이고 hidden 표시를 원래 글자로 되돌리면 text 와 같다 (시험이 본다).
    """
    out = []
    pos = 0
    for m in scan.TOKEN_RE.finditer(text):
        _plain_segments(out, text[pos:m.start()])
        out.append((m.group(0), "token"))
        pos = m.end()
    _plain_segments(out, text[pos:])
    return out


# items · item_segments · stats · stats_note 는 가린 묶음 (bundle) 에만 찬다 (아니면 빈 것).
#   items          ((이름, 종류, 바이트, 줄 수), ...) - 첫 항목은 MANIFEST.md (종류 "manifest")
#   item_segments  항목마다의 display_segments - 화면이 고른 항목의 것을 글 칸에 그린다 (segments 는 첫 항목의 것)
#   stats          맨 위에 크게 적을 수 ((칩 이름, 글), ...) - 넷 (DESIGN.md › 01 의 원칙 1)
#   stats_note     그 밑의 작은 한 줄 (표시한 곳 · 자동으로 가린 곳)
Panels = collections.namedtuple(
    "Panels", "chip title subtitle text_info segments check_line check_ok files route notices act_note send_label "
              "items item_segments stats stats_note")


def sample_shape(text):
    """보낼 글 안의 파생 표본 표 (SP-03 의 닫힌 틀) -> (열 수, 행 수) 또는 None. 허브가 알려 주는 값이 아니라 글에서 직접 센다."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line != SAMPLE_HEAD:
            continue
        head = lines[i + 1] if i + 1 < len(lines) else ""
        if not (head.startswith("| ") and head.endswith(" |")):
            return None
        rows = 0
        for r in lines[i + 3:]:
            if not (r.startswith("| ") and r.endswith(" |")):
                break
            rows += 1
        return head.count(" | ") + 1, rows
    return None


def _mmss(seconds):
    return "%02d:%02d" % divmod(max(0, int(seconds)), 60)


def build_panels(req):
    """창에 적을 글 (화면 도구와 무관) - 시험이 화면 없이 문구를 본다. 걸린 단어 · 값은 어디에도 없다.

    보낼 글 (bundle 이면 MANIFEST 와 파일들의 글) 은 segments · item_segments 에만 있다 - 다른 칸에는 이름 · 수만 적는다.
    """
    out = req.direction == "out"
    bundle = req.is_bundle
    if bundle:
        item_segments = tuple(tuple(display_segments(item.text)) for item in req.items)
        items = tuple((item.name, item.type, item.bytes, item.lines) for item in req.items)
    else:
        item_segments, items = (), ()
    segments = item_segments[0] if bundle else tuple(display_segments(req.text))
    hidden = sum(1 for segs in (item_segments or (segments,)) for _, form in segs if form == "hidden")
    info = [req.job, req.kind] + ([req.transport] if out else [])
    if bundle:
        info += ["파일 %d개 + %s" % (len(req.files), MANIFEST_NAME), "%d B" % req.stats["bytes"],
                 "묶음 sha256 %s" % req.sha256[:16]]
    else:
        info += ["%d B" % req.text_bytes, "%d 줄" % line_count(req.text), "sha256 %s" % req.sha256[:16]]
    if req.month_pct is None:
        month = "-"
    else:
        month = "%s%d%%" % ("~" if req.month_estimated else "", int(round(req.month_pct)))
    route = "모델 %s · effort %s · 이번 달 %s" % (req.model or "-", req.effort or "-", month)
    notices = []
    if bundle and req.stats["auto"] > 0:
        notices.append((TEXT_BUNDLE_SAFETY_NET % req.stats["auto"], "alert"))
    if req.effort_env_override:
        notices.append((TEXT_EFFORT_ENV, "alert"))
    if hidden:
        notices.append((TEXT_HIDDEN % hidden, "alert"))
    shape = sample_shape(req.text) if out and req.kind in ("plan", "ui") else None
    if shape:
        notices.append((TEXT_SAMPLE % shape, "alert"))
    if not out:
        notices.append((TEXT_INNER_WORDS, "note"))
    if req.restored:
        notices.append((TEXT_RESTORED % len(req.restored), "note"))
    notices.append((TEXT_IRREVERSIBLE[req.direction], "strong"))
    notices.append((TEXT_AUDIT, "strong"))
    if not out:
        act = "[넘기기] 를 누르면 이 지시가 안쪽 일꾼에게 들어갑니다"
    elif bundle:
        act = TEXT_BUNDLE_ACT % req.job
    elif req.transport == "clipboard":
        act = "[보내기] 다음에 [복사] 를 눌러야 클립보드에 들어갑니다 (복사 = 보냄)"
    else:
        act = "[보내기] 를 누르면 이 글이 그대로 방의 outbox 에 쓰입니다"
    if bundle:
        files = TEXT_BUNDLE_FILES % len(req.files)                      # 이름은 01 의 목록에 하나씩 있다
    elif req.restored:
        files = " · ".join("%s (되돌린 토큰 %d)" % pair for pair in req.restored)
    else:
        files = " · ".join(req.attachments) if req.attachments else "없음"
    if bundle:
        s = req.stats
        stats = (("FILES", "%d" % s["files"]), ("BYTES", "%d" % s["bytes"]), ("TOKENS", "%d" % s["tokens"]),
                 ("AUTO", "%d" % s["auto"]))
        stats_note = TEXT_BUNDLE_MARKS % (s["marked"], s["auto"])
        subtitle = TEXT_BUNDLE_SUBTITLE % len(req.files)
    else:
        stats, stats_note = (), ""
        subtitle = "회사 밖 (Claude) 으로 나가는 글입니다" if out else "안쪽 일꾼 (사내 LLM) 에게 넘기는 지시입니다"
    return Panels(
        chip="OUT" if out else "IN",
        title="바깥으로 보내기" if out else "안쪽으로 넘기기",
        subtitle=subtitle,
        text_info=" · ".join(info), segments=segments,
        check_line=scan.format_line(req.checks), check_ok=req.checks_ok,
        files=files, route=route, notices=tuple(notices), act_note=act, send_label="보내기" if out else "넘기기",
        items=items, item_segments=item_segments, stats=stats, stats_note=stats_note)


# ---------------------------------------------------------------- 창의 논리 (화면을 모른다)

# unviewed  아직 글 칸에 열지 않은 항목 수 (bundle · 아니면 0) · viewed 항목마다 연 적이 있는가 · selected 글 칸의 항목 번호
Snapshot = collections.namedtuple(
    "Snapshot", "send_enabled copy_enabled approved check_ok delay_s remaining_s message decided unviewed viewed selected")


class ConfirmSession(object):
    """시간 · 단추 상태 · 결정. 화면 (TkView 나 시험의 가짜 화면) 이 now (초) 를 주며 부른다.

    첫 결정이 이긴다. 결정이 나면 단추를 눌러도 아무 일도 없다. 보내기는 send_enabled 일 때만 먹는다.
    가린 묶음 (bundle) 은 항목 (MANIFEST + 파일) 을 모두 한 번씩 view 해야 send_enabled 가 된다 (L-13).
    창이 뜰 때 (start) 글 칸에 있는 첫 항목 (MANIFEST) 은 연 것으로 센다.
    """

    def __init__(self, request, clipboard=None):
        self.request = request
        self._clipboard = clipboard          # 글을 클립보드에 넣는 함수 (화면이 준다) - 실패하면 예외
        self.decision = None
        self.approved = False                # clipboard: [보내기] 를 눌렀고 [복사] 를 기다림
        self.message = ""
        self._t0 = None
        self.items = tuple(item.name for item in request.items)
        self.selected = 0
        self._viewed = [False] * len(self.items)

    @property
    def needs_copy(self):
        """바깥으로 가는 길이 clipboard 면 [복사] 가 성공해야 send 다 (복사 = 보냄). 안쪽으로 넘기는 지시는 복사하지 않는다."""
        return self.request.transport == "clipboard" and self.request.direction == "out"

    @property
    def unviewed(self):
        """아직 글 칸에 연 적이 없는 항목 수 (bundle 이 아니면 0)."""
        return self._viewed.count(False)

    def start(self, now):
        """창이 화면에 뜬 때. 2초 · 남은 시간은 여기서부터 센다. 글 칸에 있는 항목 (처음에는 MANIFEST) 은 연 것으로 센다."""
        if self._t0 is None:
            self._t0 = now
            if self._viewed:
                self._viewed[self.selected] = True

    def view(self, item, now):
        """글 칸에 항목 하나를 연다 (bundle) - item 은 번호 (0 = MANIFEST) 나 이름. 먹었으면 True.

        창이 뜨기 전 · 결정이 난 뒤 · 시간 초과 뒤 · 모르는 항목이면 아무 일도 없다 (고른 항목도 연 것도 그대로).
        """
        if self._expired(now) or self._t0 is None:
            return False
        if type(item) is int and 0 <= item < len(self.items):
            index = item
        elif type(item) is str and item in self.items:
            index = self.items.index(item)
        else:
            return False
        self.selected = index
        self._viewed[index] = True
        return True

    def _expired(self, now):
        if self.decision is None and self._t0 is not None and now - self._t0 >= self.request.timeout_s:
            self.decision = "timeout"
        return self.decision is not None

    def tick(self, now):
        self._expired(now)

    def _can_send(self, now):
        return (self._t0 is not None and self.decision is None and not self.approved and self.request.checks_ok
                and self.unviewed == 0 and now - self._t0 >= SEND_DELAY_S)

    def _can_copy(self):
        return self.needs_copy and self.approved and self.decision is None

    def press_send(self, now):
        """[보내기] / [넘기기]. 먹었으면 True. 시간 초과 · 검사에 걸림 · 2초 전 · 이미 눌림 · 안 본 항목이 있음이면 아무 일도 없다."""
        if self._expired(now) or not self._can_send(now):
            return False
        if self.needs_copy:
            self.approved = True
            self.message = TEXT_APPROVED
            return True
        self.decision = "send"
        return True

    def press_copy(self, now):
        """[복사] (clipboard). 클립보드에 넣는 데 성공했을 때만 send."""
        if self._expired(now) or not self._can_copy():
            return False
        try:
            if self._clipboard is None:
                raise RuntimeError("클립보드 없음")
            self._clipboard(self.request.text)
        except Exception:
            self.message = TEXT_COPY_FAILED
            return False
        self.decision = "send"
        return True

    def _end(self, now, decision):
        if self._expired(now):
            return False
        self.decision = decision
        return True

    def press_edit(self, now):
        return self._end(now, "edit")

    def press_discard(self, now):
        return self._end(now, "discard")

    def close(self, now):
        """창 닫기 (X) = 버리기."""
        return self._end(now, "discard")

    def key(self, name, now):
        """글쇠. Esc = 버리기 · Enter 를 비롯한 나머지는 아무 일도 하지 않는다 (Enter 로 보내지 않는다)."""
        if name == "Escape":
            return self._end(now, "discard")
        return False

    def snapshot(self, now):
        started = self._t0 is not None
        elapsed = now - self._t0 if started else 0.0
        self._expired(now)
        unviewed = self.unviewed
        if self.message:
            message = self.message
        elif not self.request.checks_ok:
            message = TEXT_CHECK_BLOCKED
        elif unviewed and self.decision is None:
            message = TEXT_UNVIEWED % unviewed
        else:
            message = ""
        return Snapshot(
            send_enabled=self._can_send(now), copy_enabled=self._can_copy(), approved=self.approved,
            check_ok=self.request.checks_ok,
            delay_s=int(math.ceil(max(0.0, SEND_DELAY_S - elapsed))),
            remaining_s=int(math.ceil(max(0.0, self.request.timeout_s - elapsed))),
            message=message, decided=self.decision is not None,
            unviewed=unviewed, viewed=tuple(self._viewed), selected=self.selected)


# ---------------------------------------------------------------- 화면 (tkinter)

def _tkinter_font():
    """tkinter 를 import 한 것만으로는 font 하위 모듈이 붙지 않는다."""
    import tkinter.font
    return tkinter.font


class TkView(object):
    """tkinter 화면 백엔드 - 그리기만 한다. 누른 것은 session 에 알리고 상태는 session 이 정한다.

    run(session) 이 보통의 길이다. 시험은 open / pump / close 를 따로 불러 위젯을 눌러 본다 (widgets).
    clock 은 시각 (초) 을 주는 함수 - 기본은 time.monotonic.
    """

    def __init__(self, tk_module, clock=None):
        self._tk = tk_module
        self._clock = clock or time.monotonic
        self._root = None
        self._session = None
        self._panels = None
        self._error = None
        self._last = None
        self._tkfont = None
        self._family = None
        self._fonts = {}
        self._wrapped = []
        self._shown = None                   # 글 칸에 그린 항목 번호 (묶음)
        self._drawn = None                   # 목록에 그린 연 표시 (묶음)
        self.widgets = {}

    @property
    def root(self):
        return self._root

    def run(self, session):
        self.open(session)
        try:
            while session.decision is None:
                self.pump()
                time.sleep(POLL_S)
        finally:
            self.close()

    def open(self, session):
        tk = self._tk
        try:
            self._tkfont = getattr(tk, "font", None) or _tkinter_font()
        except ImportError:
            raise WindowUnavailable("tkinter.font")
        try:
            self._root = tk.Tk()
        except tk.TclError:
            raise WindowUnavailable("tk")
        self._session = session
        try:
            self._build()
            self._root.update()
        except tk.TclError:
            self.close()
            raise WindowUnavailable("build")
        except Exception:
            self.close()
            raise
        now = self._clock()
        session.start(now)
        self._render(session.snapshot(now))                 # 뜬 때의 상태 (묶음이면 첫 항목을 연 것으로)

    def pump(self):
        """한 바퀴: 눌림을 처리하고 시간을 흘리고 단추를 그린다."""
        self._root.update()
        if self._error is not None:
            raise self._error
        now = self._clock()
        self._session.tick(now)
        self._render(self._session.snapshot(now))

    def close(self):
        root, self._root = self._root, None
        if root is not None:
            try:
                root.destroy()
            except self._tk.TclError:
                pass

    def set_clipboard(self, text):
        """글을 클립보드에 넣고 되읽어 본다 (줄 끝 \\r\\n 만 같게 보고 비교). 맞지 않으면 예외."""
        root = self._root
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        if root.clipboard_get().replace("\r\n", "\n") != text.replace("\r\n", "\n"):
            raise ValueError("클립보드에 들어간 글이 다름")

    # -- 눌림

    def _on_callback_error(self, exc, val, tb):
        self._error = val

    def _on_enter(self, event):
        self._session.key("Return", self._clock())
        return "break"

    def _on_escape(self, event):
        self._session.key("Escape", self._clock())
        return "break"

    # -- 짓기

    def _font(self, key, size, bold=False):
        """글꼴 하나 (크기는 픽셀 - Unifont 는 16px 정수배에서 가장 선명하다). 같은 key 는 한 번만 만든다."""
        if key not in self._fonts:
            self._fonts[key] = self._tkfont.Font(root=self._root, family=self._family, size=-size,
                                                 weight="bold" if bold else "normal")
        return self._fonts[key]

    def _pick_family(self):
        """(글꼴 이름, (본문, 작은 글, 제목) 픽셀 크기). Unifont 가 깔려 있으면 그것 (16px 정수배)."""
        have = set(self._tkfont.families(root=self._root))
        if UNIFONT in have:
            return UNIFONT, (16, 16, 32)
        for name in MONO_FAMILIES:
            if name in have:
                return name, (15, 13, 26)
        return self._tkfont.Font(root=self._root, name="TkFixedFont", exists=True).actual("family"), (15, 13, 26)

    def _label(self, parent, text, font, bg, fg, side=0, **options):
        """줄을 감는 라벨 하나 - 글 칸의 너비에서 side (옆에 붙는 칩 · 여백의 너비) 를 뺀 만큼에서 줄을 바꾼다."""
        label = self._tk.Label(parent, text=text, font=self._fonts[font], bg=bg, fg=fg, anchor="w", justify="left", **options)
        self._wrapped.append((label, side))
        return label

    def _chip(self, parent, text, bg=None, fg=None):
        c = PALETTE
        return self._tk.Label(parent, text=" %s " % text, font=self._fonts["chip"], bg=bg or c["navy2"], fg=fg or c["white"])

    def _button(self, parent, text, command):
        c = PALETTE
        return self._tk.Button(parent, text=text, command=command, font=self._fonts["button"], bd=0, relief="flat",
                               padx=18, pady=6, highlightthickness=2, highlightbackground=c["navy"],
                               highlightcolor=c["lime"], takefocus=1, cursor="hand2")

    def _build(self):
        tk = self._tk
        root = self._root
        session = self._session
        req = session.request
        c = PALETTE
        p = self._panels = build_panels(req)
        w = self.widgets

        self._family, (body, small, title) = self._pick_family()
        self._fonts = {}
        self._font("body", body)
        self._font("small", small)
        self._font("strong", body, bold=True)
        self._font("chip", small, bold=True)
        self._font("button", body, bold=True)
        self._font("title", title, bold=True)

        root.title(WINDOW_TITLE)
        root.configure(bg=c["black"])
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.report_callback_exception = self._on_callback_error
        root.protocol("WM_DELETE_WINDOW", lambda: session.close(self._clock()))
        for sequence in ("<Return>", "<KP_Enter>"):
            root.bind(sequence, self._on_enter)
        root.bind("<Escape>", self._on_escape)

        # 00 방향 - 맨 위 큰 글자
        head = tk.Frame(root, bg=c["navy"], padx=16, pady=12)
        head.grid(row=0, column=0, sticky="ew")
        chip_bg, chip_fg = (c["lime"], c["black"]) if req.direction == "out" else (c["navy3"], c["white"])
        self._chip(head, p.chip, chip_bg, chip_fg).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 16))
        w["title"] = tk.Label(head, text=p.title, font=self._fonts["title"], bg=c["navy"], fg=c["white"], anchor="w")
        w["title"].grid(row=0, column=1, sticky="w")
        self._label(head, p.subtitle, "small", c["navy"], c["navy5"]).grid(row=1, column=1, sticky="w")
        if p.stats:                                         # 가린 묶음의 수 - 맨 위에 크게 (넷까지 · DESIGN.md › 01 원칙 1)
            counts = tk.Frame(head, bg=c["navy"])
            counts.grid(row=2, column=1, sticky="w", pady=(10, 0))
            for i, (name, value) in enumerate(p.stats):
                cell = tk.Frame(counts, bg=c["navy1"], padx=8, pady=4)
                cell.grid(row=0, column=i, sticky="w", padx=(0, 8))
                self._chip(cell, name).pack(side="left")
                w["stat_" + name.lower()] = tk.Label(cell, text=value, font=self._fonts["title"], bg=c["navy1"], fg=c["white"])
                w["stat_" + name.lower()].pack(side="left", padx=(8, 0))
                if name == "AUTO" and value != "0":         # 자동으로 가린 곳이 있다 = 표시가 모자랐다 (가장 밝은 칩)
                    self._chip(cell, "‼", c["white"], c["black"]).pack(side="left", padx=(8, 0))
            w["marks"] = self._label(head, p.stats_note, "small", c["navy"], c["navy5"])
            w["marks"].grid(row=3, column=1, sticky="w", pady=(4, 0))

        # 01 글 - 보낼 바이트 그대로 (가린 묶음이면 왼쪽 목록에서 고른 항목의 바이트)
        zone = tk.Frame(root, bg=c["black"], padx=16, pady=8)
        zone.grid(row=1, column=0, sticky="nsew")
        tc = 1 if p.items else 0                            # 글 칸의 열 - 묶음이면 0 열에 항목 목록
        zone.columnconfigure(tc, weight=1)
        zone.rowconfigure(1, weight=1)
        bar = tk.Frame(zone, bg=c["black"])
        bar.grid(row=0, column=0, columnspan=tc + 2, sticky="ew", pady=(0, 6))
        self._chip(bar, "01 TEXT").pack(side="left")
        w["item"] = None
        if p.items:
            w["item"] = tk.Label(bar, text="", font=self._fonts["strong"], bg=c["black"], fg=c["lime3"])
            w["item"].pack(side="left", padx=(8, 0))
        w["info"] = tk.Label(bar, text=p.text_info, font=self._fonts["small"], bg=c["black"], fg=c["gray2"])
        w["info"].pack(side="left", padx=8)
        text = tk.Text(zone, wrap="word", width=84, height=TEXT_ROWS, font=self._fonts["body"], bg=c["black"],
                       fg=c["gray4"], insertwidth=0, relief="flat", bd=0, padx=10, pady=8, highlightthickness=1,
                       highlightbackground=c["navy3"], highlightcolor=c["lime"], selectbackground=c["navy3"],
                       selectforeground=c["white"], takefocus=1)
        text.grid(row=1, column=tc, sticky="nsew")
        scroll = tk.Scrollbar(zone, orient="vertical", command=text.yview, bg=c["navy2"], troughcolor=c["black"],
                              activebackground=c["navy3"], relief="flat", bd=0)
        scroll.grid(row=1, column=tc + 1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("token", background=c["lime"], foreground=c["black"])
        text.tag_configure("hidden", background=c["white"], foreground=c["navy"], font=self._fonts["strong"])
        w["text"] = text
        self._fill_text(p.segments)                         # 읽기 전용 (묶음이면 첫 항목 MANIFEST)
        w["items"] = None
        if p.items:
            self._build_items(zone)

        # 02 검사 · 03 첨부 · 04 모델
        spec = tk.Frame(root, bg=c["black"], padx=16)
        spec.grid(row=2, column=0, sticky="ew")
        spec.columnconfigure(1, weight=1)
        rows = (("02 CHECK", p.check_line, "check"), ("03 FILES", p.files, "files"), ("04 ROUTE", p.route, "route"))
        for i, (name, value, key) in enumerate(rows):
            self._chip(spec, name).grid(row=i, column=0, sticky="w", pady=2)
            cell = tk.Frame(spec, bg=c["navy1"])
            cell.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=2)
            fg = c["lime3"] if key == "check" and p.check_ok else c["white"]
            w[key] = self._label(cell, value, "body", c["navy1"], fg, side=170, padx=8)
            w[key].pack(side="left")
            if key == "check" and not p.check_ok:
                self._chip(cell, "V<Vth", c["white"], c["black"]).pack(side="left", padx=4)   # 문턱을 못 넘음

        # 05 알림 · 단추
        foot = tk.Frame(root, bg=c["navy"], padx=16, pady=10)
        foot.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        foot.columnconfigure(5, weight=1)
        colors = {"alert": (c["lime3"], "strong"), "strong": (c["white"], "strong"), "note": (c["navy5"], "small")}
        self._chip(foot, "05 CONFIRM", c["navy3"]).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        r = 1
        for note, level in p.notices:
            fg, font_key = colors[level]
            self._label(foot, note, font_key, c["navy"], fg).grid(row=r, column=0, columnspan=6, sticky="w")
            r += 1
        self._label(foot, p.act_note, "small", c["navy"], c["navy5"]).grid(row=r, column=0, columnspan=6, sticky="w")
        w["message"] = self._label(foot, "", "small", c["navy"], c["lime3"])
        w["message"].grid(row=r + 1, column=0, columnspan=6, sticky="w", pady=(2, 0))

        def now():
            return self._clock()

        w["send"] = self._button(foot, p.send_label, lambda: session.press_send(now()))
        w["edit"] = self._button(foot, "고치기", lambda: session.press_edit(now()))
        w["discard"] = self._button(foot, "버리기", lambda: session.press_discard(now()))
        w["send"].grid(row=r + 2, column=0, pady=(10, 0), padx=(0, 8))
        w["edit"].grid(row=r + 2, column=1, pady=(10, 0), padx=(0, 8))
        w["discard"].grid(row=r + 2, column=2, pady=(10, 0), padx=(0, 8))
        w["copy"] = None
        if session.needs_copy:
            w["copy"] = self._button(foot, "복사", lambda: session.press_copy(now()))
            w["copy"].grid(row=r + 2, column=3, pady=(10, 0), padx=(0, 8))
        w["time"] = tk.Label(foot, text="", font=self._fonts["body"], bg=c["navy"], fg=c["lime3"], anchor="e")
        w["time"].grid(row=r + 2, column=5, sticky="e", pady=(10, 0))
        for key in ("send", "edit", "discard", "copy"):
            if w[key] is not None:
                for sequence in ("<Return>", "<KP_Enter>"):
                    w[key].bind(sequence, self._on_enter)
        self._style(w["edit"], True, "고치기")
        self._style(w["discard"], True, "버리기")
        self._render(session.snapshot(self._clock()))

        # 화면에 앉히기 - 가운데 · 맨 앞 · 기본 초점은 [버리기]
        root.update_idletasks()
        for label, side in self._wrapped:                   # 줄을 글 칸의 너비에 맞춰 감는다 (창이 옆으로 밀리지 않게)
            label.configure(wraplength=max(240, text.winfo_reqwidth() - WRAP_MARGIN_PX - side))
        self._fit_height(root.winfo_screenheight() - SCREEN_MARGIN_PX)
        root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
        x = max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2)
        y = max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 3)
        root.geometry("+%d+%d" % (x, y))
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        root.lift()
        try:
            w["discard"].focus_force()                      # 맨 앞으로 + 기본 초점은 [버리기] (Enter · 공백을 습관으로 눌러도 안 나간다)
        except tk.TclError:
            w["discard"].focus_set()

    def _build_items(self, zone):
        """가린 묶음의 항목 목록 (MANIFEST + 파일) - 고르면 session.view 를 부르고 글 칸을 그 항목으로 다시 그린다."""
        tk = self._tk
        c = PALETTE
        lines = [self._item_line(i, False) for i in range(len(self._panels.items))]
        side = tk.Frame(zone, bg=c["black"])
        side.grid(row=1, column=0, sticky="ns", padx=(0, 8))
        side.rowconfigure(1, weight=1)
        self.widgets["items_head"] = tk.Label(side, text=ITEM_HEAD, font=self._fonts["body"], bg=c["black"], fg=c["gray2"],
                                              anchor="w", padx=1)
        self.widgets["items_head"].grid(row=0, column=0, columnspan=2, sticky="ew")
        items = tk.Listbox(side, selectmode="browse", exportselection=False, activestyle="none",
                           width=max(len(line) for line in lines) + 1, height=min(len(lines), TEXT_ROWS),
                           font=self._fonts["body"], bg=c["black"], fg=c["white"], selectbackground=c["navy3"],
                           selectforeground=c["white"], disabledforeground=c["gray1"], highlightthickness=1,
                           highlightbackground=c["navy3"], highlightcolor=c["lime"], relief="flat", bd=0, takefocus=1)
        items.grid(row=1, column=0, sticky="ns")
        if len(lines) > TEXT_ROWS:
            bar = tk.Scrollbar(side, orient="vertical", command=items.yview, bg=c["navy2"], troughcolor=c["black"],
                               activebackground=c["navy3"], relief="flat", bd=0)
            bar.grid(row=1, column=1, sticky="ns")
            items.configure(yscrollcommand=bar.set)
        for line in lines:
            items.insert("end", line)
        items.bind("<<ListboxSelect>>", self._on_pick)
        for sequence in ("<Return>", "<KP_Enter>"):
            items.bind(sequence, self._on_enter)
        self.widgets["items"] = items

    def _item_line(self, index, viewed):
        """목록 한 줄: 연 적이 있으면 √ · 아니면 ○ + 이름 · 종류 · 바이트 · 줄 수 (글은 적지 않는다).
        ASCII 만 쓴다 - Unifont 의 한글은 목록의 줄 높이보다 커서 옆 줄을 덮는다 (칸 이름은 ITEM_HEAD 에)."""
        name, kind, size, lines = self._panels.items[index]
        return ITEM_ROW % ("√" if viewed else "○", name, kind, size, lines)

    def _fill_text(self, segments):
        """글 칸을 segments 로 다시 채우고 읽기 전용으로 둔다 (맨 위부터 보인다)."""
        text = self.widgets["text"]
        text.configure(state="normal")
        text.delete("1.0", "end")
        for piece, form in segments:
            if form:
                text.insert("end", piece, form)
            else:
                text.insert("end", piece)
        text.configure(state="disabled")
        text.yview_moveto(0.0)

    def _on_pick(self, event):
        picked = self.widgets["items"].curselection()
        now = self._clock()
        if picked:
            self._session.view(int(picked[0]), now)
        self._render(self._session.snapshot(now))

    def _render_items(self, snap):
        """고른 항목을 글 칸에 · 연 표시 (√) 를 목록에 · 목록의 고름을 session 의 것과 같게."""
        items = self.widgets["items"]
        c = PALETTE
        if snap.selected != self._shown:
            self._shown = snap.selected
            self._fill_text(self._panels.item_segments[snap.selected])
            name, kind, size, lines = self._panels.items[snap.selected]
            self.widgets["item"].configure(text="▶ %s · %s · %d B · %d 줄" % (name, kind, size, lines))
        for i, seen in enumerate(snap.viewed):
            if self._drawn is None or self._drawn[i] != seen:
                items.delete(i)
                items.insert(i, self._item_line(i, seen))
                items.itemconfigure(i, foreground=c["gray2"] if seen else c["white"])
        self._drawn = snap.viewed
        if tuple(int(i) for i in items.curselection()) != (snap.selected,):
            items.selection_clear(0, "end")
            items.selection_set(snap.selected)
        items.activate(snap.selected)

    def _fit_height(self, limit):
        """창이 limit 픽셀보다 크면 글 칸의 줄 수를 줄여 단추가 화면 안에 들게 한다 (글 칸은 끌어서 다시 키울 수 있다)."""
        root, text = self._root, self.widgets["text"]
        root.update_idletasks()
        over = root.winfo_reqheight() - limit
        if over > 0:
            line = max(1, self._fonts["body"].metrics("linespace"))
            text.configure(height=max(4, int(text.cget("height")) - (over + line - 1) // line))
            items = self.widgets.get("items")
            if items is not None:                           # 목록도 글 칸보다 길지 않게
                items.configure(height=min(int(items.cget("height")), int(text.cget("height"))))
            root.update_idletasks()

    def _style(self, button, enabled, label, accent=False):
        """켜진 단추는 네이비 바탕 (accent 는 라임 글자 = 보내는 쪽) · 꺼진 단추는 꺼진 LED 회색."""
        c = PALETTE
        if enabled:
            button.configure(state="normal", text=label, bg=c["navy2"], fg=c["lime3"] if accent else c["white"],
                             activebackground=c["lime1"], activeforeground=c["white"])
        else:
            button.configure(state="disabled", text=label, bg=c["gray0"], fg=c["gray1"], disabledforeground=c["gray1"])

    def _render(self, snap):
        """단추 · 시간 · 알림 (묶음이면 고른 항목 · 연 표시도) 을 snap 대로 맞춘다 (바뀐 때만)."""
        if snap == self._last:
            return
        self._last = snap
        w = self.widgets
        if w.get("items") is not None:
            self._render_items(snap)
        label = self._panels.send_label
        if snap.approved:
            label += " √"
        elif snap.delay_s > 0 and snap.check_ok and not snap.decided:
            label += " (%d)" % snap.delay_s
        self._style(w["send"], snap.send_enabled, label, accent=True)
        if w["copy"] is not None:
            self._style(w["copy"], snap.copy_enabled, "복사", accent=True)
        w["time"].configure(text="남은 시간 %s" % _mmss(snap.remaining_s))
        w["message"].configure(text=snap.message)


# ---------------------------------------------------------------- 창 띄우기 (E-07)

def _is_windows():
    return os.name == "nt"


def display_missing(environ, windows):
    """Windows 밖에서 DISPLAY · WAYLAND_DISPLAY 가 둘 다 없으면 참 - 창을 띄울 곳이 없다 (tkinter 를 부르지 않는다)."""
    if windows:
        return False
    return not (environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))


def create_view():
    """화면 백엔드를 만든다. 시험은 이 이름을 바꿔 끼워 가짜 화면으로 논리를 본다 (AL-02: 건너뛰는 길은 따로 없다)."""
    if display_missing(os.environ, _is_windows()):
        raise WindowUnavailable("display")
    try:
        import tkinter
        import tkinter.font  # noqa: F401  - TkView 가 쓴다
    except ImportError:
        raise WindowUnavailable("tkinter")
    return TkView(tkinter)


# ---------------------------------------------------------------- diode.py confirm 의 몸통

def _error_line(code):
    return json.dumps({"decision": "error", "code": code})


def main_confirm(path):
    """요청 파일 (path) 을 읽어 창을 띄우고 사람의 결정을 돌려준다 -> (종료 코드, 표준 출력 한 줄).

    아무것도 쓰거나 지우지 않는다. 어떤 예외도 send 로 끝나지 않는다 (결정이 났어도 그 뒤에 예외가 나면 E-20).
    """
    try:
        try:
            request = read_request(path)
        except RequestError:
            return EXIT_BAD_REQUEST, _error_line("E-04")
        view = create_view()
        session = ConfirmSession(request, clipboard=view.set_clipboard)
        view.run(session)
        decision = session.decision
        if decision not in DECISIONS:
            return EXIT_FAILED, _error_line("E-20")
        line = json.dumps({"decision": decision, "sha256": request.sha256})
        return (EXIT_SEND if decision == "send" else EXIT_HUMAN), line
    except WindowUnavailable:
        return EXIT_FAILED, _error_line("E-07")
    except (Exception, KeyboardInterrupt):
        return EXIT_FAILED, _error_line("E-20")


def parse_result(exit_code, stdout_text, expected_sha256):
    """창 프로세스의 (종료 코드, 표준 출력) 을 읽는다 (허브 쪽) -> (결정, 오류 번호).

    결정은 send · discard · edit · timeout · error (오류 번호는 error 일 때만). main_confirm 이 내는 꼴과
    정확히 같지 않으면 모두 ("error", "E-20") - send 는 종료 코드 0 · 한 줄 · 칸 둘 · sha256 이 허브가 보낼 글의
    sha256 (expected_sha256) 과 같을 때만 나온다. 사람이 본 바이트와 보낼 바이트가 같다는 확인이다.
    """
    bad = ("error", "E-20")
    try:
        lines = stdout_text.splitlines()
        if len(lines) != 1 or type(exit_code) is not int:
            return bad
        data = json.loads(lines[0], object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        if type(data) is not dict:
            return bad
        decision = data.get("decision")
        if decision == "error":
            code = data.get("code")
            if set(data) != {"decision", "code"} or code not in ERROR_EXIT or exit_code != ERROR_EXIT[code]:
                return bad
            return "error", code
        if decision not in DECISIONS or set(data) != {"decision", "sha256"}:
            return bad
        if type(expected_sha256) is not str or data["sha256"] != expected_sha256 or not re.match(r"[0-9a-f]{64}\Z", expected_sha256):
            return bad
        if exit_code != (EXIT_SEND if decision == "send" else EXIT_HUMAN):
            return bad
        return decision, None
    except (ValueError, RecursionError, AttributeError):
        return bad
