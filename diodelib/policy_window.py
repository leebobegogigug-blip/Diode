# -*- coding: utf-8 -*-
"""정책 편집 창 (T19 · SP-15 · AL-10 · AL-12) - 사전 · 원자료 폴더 · 안쪽 도구 · 일꾼 같은 정책은 사람이 이 창에서 직접
입력해야만 바뀐다 (표준 라이브러리 · Python 3.8).

`python diode.py policy` 가 부른다 (따로 된 프로세스). Claude 에게 사내 단어를 쳐서 사전에 넣게 하면 그 단어가 곧바로
Claude 로 나가므로 단어는 이 창에서만 입력하고, 창을 연 명령에는 개수와 켜짐 여부만 돌려준다 (AL-11).
저장은 diodelib.config 가 한다 (load_state · validate_state · apply_state · counts) - 이 창은 그것만 부른다.

결과 (표준 출력 한 줄 JSON · 단어 · 경로 · 일꾼 명령은 넣지 않는다 - 코드 · 개수 · 참거짓뿐)
  {"saved": true, "counts": <config.counts>, "warnings": [<경고 코드>]}        종료 코드 0  저장했다
  {"saved": false}                                                            종료 코드 3  저장하지 않고 닫았다
  {"saved": false, "error": "E-07"}                                           종료 코드 1  창을 못 띄움
  {"saved": false, "error": "E-20", "code": "newer"}                          종료 코드 1  설정이 더 새 format 이라 열지 않음
  {"saved": false, "error": "E-20"}                                           종료 코드 1  그 밖의 예외 (설정을 읽지 못함 포함)
  counts 의 칸: dictionary · raw_dirs · inner_tools · lib_allow · patterns (개수) · web_search · real_data · derived_level · worker ·
  llm · room_path (참거짓). 경고 코드: short · raw_missing · words_empty · raw_empty.

구조 - 논리와 화면을 나눈다 (confirm.py 와 같다).
  to_text / to_value  칸마다 글 <-> 값 바꾸기 (한 곳에 둔다). 화면을 모른다.
  PolicySession       칸의 글 · 켜짐 칸 · 검증 · 저장 · 닫기. 화면을 모른다.
  TkView              tkinter 화면. 그리기만 하고, 칸의 글이 바뀔 때마다 session 에 알린다.
  create_view()       화면 백엔드를 만드는 곳. 시험은 이 이름을 바꿔 끼워 가짜 화면으로 논리를 본다 (AL-12).
  launch_detached()   창을 따로 떼어 띄운다 (부른 쪽을 기다리게 하지 않는다).

지키는 것
- 건너뛰는 길이 없다 (AL-12): 환경 변수 · 명령줄 인자 · 파일로 값을 밀어 넣는 길도, 조용히 저장하는 길도 없다.
  읽는 환경 변수는 창을 띄울 화면이 있는지 보는 DISPLAY · WAYLAND_DISPLAY 둘뿐이다 (E-07 쪽으로만 작용한다).
  이 모듈은 파일을 직접 열지 않는다 - 쓰는 것은 config.apply_state 하나뿐이고, 사람이 [저장] 을 눌러야 부른다.
- 막은 까닭 · 오류 글에는 단어 · 경로를 쓰지 않는다 - 칸 이름 · 줄 번호 · 코드 · 개수만 (AL-11).
- 보이지 않는 글자가 든 글은 저장하지 않고 [U+XXXX] 꼴로 알린다. 실데이터 (AL-10) 는 확인 글을 쳐야 켜진다.
- 저장된 llm 키 · 헤더 값은 화면에도 `설정됨 (n자 · 값은 표시 안 함)` 으로만 보이고 (works SPEC-llm › 04 · W-04) 저장해도
  그대로 남는다. 새로 글자 그대로 적는 키 · 헤더 값은 막고 {file:경로} 참조만 받는다.
- 화면 문구는 한국어, 색은 works DESIGN.md 의 네이비 · 라임 · 회색뿐이다 - 빨강 없음 (W-10).
"""

import collections
import json
import os
import re
import subprocess
import threading
import time

from . import config, confirm, scan

# ---------------------------------------------------------------- 상수

EXIT_SAVED, EXIT_FAILED, EXIT_NOT_SAVED = 0, 1, 3
POLICY_COMMAND = "policy"           # launch_detached 가 diode.py 에 주는 명령 이름
REAL_DATA_PHRASE = "사내 자체 검증 완료"   # 실데이터를 켜려면 확인 글 칸에 정확히 이 글을 쳐야 한다 (AL-10)
WORKER_EXAMPLE = '["opencode","run","--dir","{cwd}","{prompt}"]'      # [예시 넣기] - SP-15 의 예
REF_RE = re.compile(r"\A\{(?:file|env):.+\}\Z")          # 키 · 헤더 값의 참조 꼴 - 비밀이 아니라 가리키는 글이라 그대로 보인다
MASK_TEXT = "설정됨 (%d자 · 값은 표시 안 함)"                   # works SPEC-llm › 04 - 저장된 키 값은 화면에도 이렇게만 보인다 (W-04)
MASK_RE = re.compile(r"\A설정됨 \([0-9]+자 · 값은 표시 안 함\)\Z")

POLL_S = 0.05                       # 화면을 돌보는 간격
SCREEN_MARGIN_PX = 120              # 창 제목줄 · 작업 표시줄 몫
WRAP_MARGIN_PX = 40                 # 줄을 감는 너비 = 본문 너비 - 이 여백 (구역 안쪽 여백 몫)
TOPMOST_MS = 400                    # 처음 뜰 때 맨 앞으로 올린 뒤 이만큼 있다가 맨 앞 고정을 푼다 (오래 붙들지 않는다)
DETACHED_PROCESS = 0x00000008       # Windows CreateProcess 의 플래그 - 다른 OS 의 subprocess 에는 이 이름이 없다
CREATE_NEW_PROCESS_GROUP = 0x00000200
MAX_HIDDEN_SHOWN = 4                # 상태 줄에 적는 보이지 않는 글자의 자리 수 (나머지는 "외 N곳")
MAX_LINES_SHOWN = 5                 # 상태 줄에 적는 틀린 줄 번호의 수 (나머지는 "외 N곳")

PALETTE = confirm.PALETTE           # works DESIGN.md › 02 - 네이비 · 라임 · 무채색뿐 (빨강 없음)
WindowUnavailable = confirm.WindowUnavailable       # 창을 띄울 수 없다 (E-07) - 확정 창과 같은 예외
WINDOW_TITLE = "Diode - 정책"

# 칸 이름 (글 칸의 열쇠 = config 상태 dict 의 열쇠). 창에 보이는 순서.
LIST_KEYS = ("words", "raw_dirs", "inner_tools", "lib_allow", "patterns")           # 여러 줄 - 한 줄에 하나
LINE_KEYS = ("worker_command", "worker_cwd", "monthly_budget_usd", "room_path")     # 한 줄
TEXT_KEYS = ("words", "raw_dirs", "inner_tools", "worker_command", "worker_cwd", "lib_allow", "patterns",
             "monthly_budget_usd", "room_path", "llm")
FIELD_LABEL = {
    "words": "01 사전", "raw_dirs": "02 원자료 폴더", "inner_tools": "03 안쪽 도구",
    "worker_command": "04 일꾼 명령", "worker_cwd": "04 일꾼 작업 폴더",
    "lib_allow": "05 라이브러리 허용", "patterns": "05 정규식",
    "web_search": "06 웹 검색", "real_data": "06 실데이터", "real_confirm": "06 실데이터 확인 글",
    "derived_level": "06 파생 표본",
    "monthly_budget_usd": "06 월 예산", "room_path": "06 방 자리", "llm": "06 llm",
}
# 오류 영역 코드 (config.ConfigError 의 코드 + 창이 따로 보는 것) -> 틀린 칸
AREA_FIELD = {
    "words": "words", "raw_dirs": "raw_dirs", "inner_tools": "inner_tools", "lib_allow": "lib_allow",
    "patterns": "patterns", "worker": "worker_command", "budget": "monthly_budget_usd", "room_path": "room_path",
    "llm": "llm", "llm_key": "llm", "flags": "real_data", "state": "words", "real_data": "real_confirm",
    "derived": "derived_level",
}

# 화면 문구 (한국어 · 이모지 없음 · DESIGN.md › 03 의 기호만)
TEXT_SUBTITLE = "이 창에서만 바뀝니다 · 단어는 화면 밖으로 나가지 않습니다"
TEXT_IDLE = "고친 뒤 [저장] 을 누르면 이 PC 의 설정에 씁니다"
TEXT_BLANK_OPEN = "설정 파일이 깨져 있어 읽지 못한 칸은 비어 있습니다 - 저장하면 깨진 파일은 .broken 으로 옮겨 둡니다"
TEXT_SAVED = "저장했습니다"
TEXT_UNCHANGED = "바뀐 것 없음 - 설정은 그대로입니다"
TEXT_CLOSE_ASK = "‼ 저장하지 않고 닫을까요 - 닫으려면 [닫기] 를 한 번 더 누르세요"
TEXT_HIDDEN = "보이지 않는 글자 %d개 - %s - 지우고 다시 저장하세요"
TEXT_REAL_NEED = ("실데이터는 사내에서 자체 검증을 마친 뒤에만 켭니다 - 켜려면 확인 글 칸에 정확히 '%s' 을 치세요" % REAL_DATA_PHRASE)
TEXT_WRITE_FAILED = "파일에 쓰지 못했습니다 - 디스크 · 권한을 확인한 뒤 다시 저장하세요"
TEXT_NEWER = "설정이 더 새 형식이라 덮어쓰지 않습니다 - Diode 를 올린 뒤 다시 여세요"
TEXT_READBACK = "저장한 설정을 다시 읽지 못했습니다 - 다시 저장해 보세요"
TEXT_EXAMPLE_KEPT = "04 일꾼 명령이 이미 적혀 있어 예시를 넣지 않았습니다 - 지운 뒤 다시 누르세요"
TEXT_EXAMPLE_DONE = "예시를 넣었습니다 - 자기 환경에 맞게 고치세요"
TEXT_LINE_ADDED = "%s 에 한 줄 더했습니다"
TEXT_LINE_DUP = "이미 있는 줄입니다"
TEXT_WARN_MARK = "‼ "
TEXT_RISKY = ("짧은 단어 %d개 - 평범한 말이 막힐 수 있습니다 (오탐). 별칭이나 더 긴 이름으로 바꾸는 것을 권합니다")

# 경고 코드 (config.validate_state) -> 한국어 한 줄. 저장은 막지 않는다.
WARN_TEXT = {
    "short": "두 글자 미만인 사전 항목은 쓰이지 않아 뺐습니다",
    "raw_missing": "지금 없는 원자료 폴더가 있습니다 (그대로 저장했습니다)",
    "words_empty": "사전이 비어 있습니다 - 이대로면 보내기를 막습니다",
    "raw_empty": "원자료 폴더 목록이 비어 있습니다 - 이대로면 보내기를 막습니다",
}
# 오류 영역 코드 -> 한국어 한 줄. 틀린 값은 쓰지 않는다 (AL-11).
ERROR_TEXT = {
    "words": "사전 항목은 %d자 이하 · %d개 이하여야 합니다" % (config.MAX_WORD_LEN, config.MAX_WORDS),
    "raw_dirs": "원자료 폴더는 전체 경로 (드라이브 글자나 / 로 시작) 여야 하고 %d개 · 한 줄 %d자 이하입니다"
                % (config.MAX_LIST, config.MAX_PATH_LEN),
    "inner_tools": "안쪽 도구 이름은 한 줄에 하나씩, 개수 · 길이 한도 안이어야 합니다",
    "lib_allow": "라이브러리 이름은 영문자로 시작하고 영문 · 숫자 · _ . - 만 쓴 짧은 이름이어야 합니다",
    "patterns": "정규식으로 읽히지 않는 줄이 있습니다 (개수 · 길이 한도도 지켜야 합니다)",
    "flags": "켜짐 · 꺼짐 칸의 값이 맞지 않습니다",
    "budget": "월 예산은 0 이상의 수 (예 120 · 12.5) 여야 합니다",
    "worker": "일꾼 명령은 문자열 JSON 목록이고 {prompt} 는 한 곳만이어야 합니다 (작업 폴더만 적을 수는 없습니다)",
    "room_path": "방 자리는 전체 경로 한 줄이어야 합니다",
    "llm": "llm 설정이 맞지 않습니다 (JSON 객체 · base_url 은 http(s) 주소 · 키는 {file:경로} 꼴이고 그 파일이 있어야 합니다)",
    "llm_key": "llm 의 api_key · extra_headers 값은 {file:경로} 꼴로만 적습니다 (키 값을 글자 그대로 적지 않습니다)",
    "state": "창의 값이 맞지 않습니다",
    "real_data": TEXT_REAL_NEED,
    "derived": "파생 표본은 실데이터를 허용한 뒤에만 켤 수 있습니다 - 실데이터 칸을 먼저 켜세요",
    "hidden": "보이지 않는 글자가 있습니다 - [U+XXXX] 로 알린 자리를 지우세요",
}
COUNT_LABELS = (("dictionary", "사전"), ("raw_dirs", "원자료 폴더"), ("inner_tools", "안쪽 도구"),
                ("lib_allow", "라이브러리"), ("patterns", "정규식"))
FLAG_LABELS = (("web_search", "웹 검색", "켜짐", "꺼짐"), ("real_data", "실데이터", "켜짐", "꺼짐"),
               ("worker", "일꾼", "있음", "없음"), ("llm", "llm", "있음", "없음"), ("room_path", "방 자리", "있음", "없음"))


class FieldProblem(Exception):
    """칸의 글을 값으로 바꾸지 못했다. area 는 오류 영역 코드 · field 는 틀린 칸. 글 · 값은 담지 않는다 (AL-11)."""

    def __init__(self, area, field):
        Exception.__init__(self, area)
        self.area = area
        self.field = field


# ---------------------------------------------------------------- 글 <-> 값 (칸마다 한 곳)

def _breaks(text):
    """붙여 넣은 글의 줄 끝 (\\r\\n · \\r) 을 \\n 하나로. 줄을 나누는 것은 \\n 뿐이다 (splitlines 는 보이지 않는 글자에서도 나눈다)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("같은 키 두 번")
        out[k] = v
    return out


def _no_constant(name):
    raise ValueError("NaN · Infinity")


def _loads(text):
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)


def lines_of(text):
    """여러 줄 칸의 글 -> 한 줄에 하나인 목록. 빈 줄 · 앞뒤 빈칸은 무시하고, # 로 시작하는 줄도 줄이다 (사전 단어일 수 있다)."""
    return [line.strip() for line in _breaks(text).split("\n") if line.strip()]


def _one_line(text, area, field):
    text = _breaks(text).strip()
    if "\n" in text:
        raise FieldProblem(area, field)
    return text


def _fmt_lines(value):
    return "\n".join(value or [])


def _fmt_text(value):
    return value or ""


def _parse_lines(text):
    return lines_of(text)


def _fmt_command(value):
    return "" if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_command(text):
    text = _one_line(text, "worker", "worker_command")
    if not text:
        return None
    try:
        value = _loads(text)
    except (ValueError, RecursionError):
        raise FieldProblem("worker", "worker_command")
    if not isinstance(value, list):
        raise FieldProblem("worker", "worker_command")
    return value


def _parse_cwd(text):
    return _one_line(text, "worker", "worker_cwd") or None


def _parse_room(text):
    return _one_line(text, "room_path", "room_path") or None


def _fmt_budget(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


_NUMBER_RE = re.compile(r"[0-9]{1,12}(\.[0-9]{1,6})?\Z")


def _parse_budget(text):
    text = _one_line(text, "budget", "monthly_budget_usd")
    if not text:
        return 0
    if not _NUMBER_RE.match(text):
        raise FieldProblem("budget", "monthly_budget_usd")
    return float(text) if "." in text else int(text)


def _is_secret(value):
    """참조 ({file:..} · {env:..}) 도 빈 글도 아닌 글 = 글자 그대로 적힌 키 · 헤더 값 (비밀)."""
    return isinstance(value, str) and value != "" and not REF_RE.match(value)


def _secrets_of(llm):
    """llm 설정에서 글자 그대로 적힌 키 · 헤더 값 -> {자리: 값}. 자리는 ("api_key",) · ("extra_headers", 이름)."""
    out = {}
    if isinstance(llm, dict):
        if _is_secret(llm.get("api_key")):
            out[("api_key",)] = llm["api_key"]
        headers = llm.get("extra_headers")
        if isinstance(headers, dict):
            for name, value in headers.items():
                if _is_secret(value):
                    out[("extra_headers", name)] = value
    return out


def _fmt_llm(value):
    """llm 설정 -> 창에 보일 JSON. 글자 그대로 적힌 키 · 헤더 값은 가려서 보인다 (SPEC-llm › 04 · W-04) - 원래 값은 session 이 쥔다."""
    if value is None:
        return ""
    shown = dict(value)
    if _is_secret(shown.get("api_key")):
        shown["api_key"] = MASK_TEXT % len(shown["api_key"])
    if isinstance(shown.get("extra_headers"), dict):
        shown["extra_headers"] = dict((k, MASK_TEXT % len(v) if _is_secret(v) else v) for k, v in shown["extra_headers"].items())
    return json.dumps(shown, ensure_ascii=False, indent=2, sort_keys=True)


def _parse_llm(text):
    """글 -> JSON 객체 (가린 표시는 그대로 둔다 - 되돌리고 키를 따지는 것은 PolicySession). 비우면 None."""
    text = _breaks(text).strip()
    if not text:
        return None                      # 비우면 None - config.apply_state 는 llm 을 바꾸지 않는다
    try:
        value = _loads(text)
    except (ValueError, RecursionError):
        raise FieldProblem("llm", "llm")
    if not isinstance(value, dict):
        raise FieldProblem("llm", "llm")
    return value


# 칸 -> (값 -> 글, 글 -> 값). 글 <-> 값 바꾸기는 여기 한 곳에만 있다.
CODECS = {
    "words": (_fmt_lines, _parse_lines),
    "raw_dirs": (_fmt_lines, _parse_lines),
    "inner_tools": (_fmt_lines, _parse_lines),
    "lib_allow": (_fmt_lines, _parse_lines),
    "patterns": (_fmt_lines, _parse_lines),
    "worker_command": (_fmt_command, _parse_command),
    "worker_cwd": (_fmt_text, _parse_cwd),
    "monthly_budget_usd": (_fmt_budget, _parse_budget),
    "room_path": (_fmt_text, _parse_room),
    "llm": (_fmt_llm, _parse_llm),
}


def to_text(key, value):
    """칸의 값 -> 창에 보일 글."""
    return CODECS[key][0](value)


def to_value(key, text):
    """칸의 글 -> 값 (config 상태 dict 의 그 칸). 못 바꾸면 FieldProblem (영역 코드 · 칸 이름)."""
    return CODECS[key][1](text)


# ---------------------------------------------------------------- 보이는 것 (화면과 무관한 내용)

HiddenHit = collections.namedtuple("HiddenHit", "field line code")           # code 는 "U+200B" 꼴


def hidden_hits_in(key, text):
    """key 칸의 글에서 보이지 않는 글자 (제어 · 서식 · 영폭 공백 · 다른 빈칸 ...) 의 자리. 확정 창과 같은 판정이다."""
    hits = []
    for n, line in enumerate(_breaks(text).split("\n"), 1):
        for ch in line:
            if confirm.is_hidden_char(ch):
                hits.append(HiddenHit(key, n, "U+%04X" % ord(ch)))
    return hits


def describe_hits(hits):
    """보이지 않는 글자의 자리 -> 상태 줄의 글 ([U+XXXX] 꼴). 칸 이름 · 줄 번호 · 코드뿐이다 (같은 줄의 같은 글자는 x개수로 묶는다)."""
    places = collections.OrderedDict()
    for h in hits:
        places[(h.field, h.line, h.code)] = places.get((h.field, h.line, h.code), 0) + 1
    shown = []
    for (field, line, code), n in list(places.items())[:MAX_HIDDEN_SHOWN]:
        shown.append("%s %d째 줄 [%s]%s" % (FIELD_LABEL[field], line, code, " x%d" % n if n > 1 else ""))
    more = len(places) - MAX_HIDDEN_SHOWN
    return TEXT_HIDDEN % (len(hits), " · ".join(shown) + (" 외 %d곳" % more if more > 0 else ""))


def summarize(counts):
    """config.counts -> 한 줄 개수 요약 (단어 · 경로 · 이름 없음)."""
    parts = ["%s %d" % (label, counts.get(key, 0)) for key, label in COUNT_LABELS]
    parts += ["%s %s" % (label, on if counts.get(key) else off) for key, label, on, off in FLAG_LABELS]
    return " · ".join(parts)


# ---------------------------------------------------------------- 창의 논리 (화면을 모른다)

Checked = collections.namedtuple("Checked", "ok state warnings area field message lines")
Saved = collections.namedtuple("Saved", "ok changed counts warnings area field message")
Snapshot = collections.namedtuple("Snapshot", "message level locked save_enabled close_label real_data web_search lines derived")


def _blank_state():
    return {"words": [], "raw_dirs": [], "inner_tools": [], "lib_allow": [], "patterns": [], "web_search": True,
            "real_data": False, "derived_level": 0, "monthly_budget_usd": 0, "worker_command": None, "worker_cwd": None, "room_path": None,
            "llm": None}


def _load(home):
    """현재 값 -> (상태, 깨져서 빈 값으로 연 칸이 있나). 더 새 format 이면 ConfigError 그대로 (창을 열지 않는다).

    파일마다 따로 읽는다 (config.load_state_tolerant) - 한쪽만 깨졌으면 멀쩡한 쪽의 값은 살려서 연다.
    저장하면 config 가 깨진 파일을 .broken 으로 옮기고 새로 쓴다. 멀쩡한 파일을 빈 값으로 덮어 잃지 않는다.
    """
    state, broken = config.load_state_tolerant(home)
    return state, bool(broken)


class PolicySession(object):
    """칸의 글 · 켜짐 칸 · 검증 · 저장 · 닫기. 화면 (TkView 나 시험의 가짜 화면) 이 부른다.

    칸의 글은 set_text 로 받고 (화면이 바뀔 때마다 알린다), 값으로 바꾸는 것은 to_value 가 한다.
    저장은 save() 에서만 일어난다 - 검증을 지나야 config.apply_state 를 부른다. 한 번 저장하면 더 고치지 않는다.
    """

    def __init__(self, home):
        self.home = home
        self.saved = False
        self.finished = False
        self.counts = None              # 저장한 뒤의 config.counts
        self.warnings = []              # 저장할 때의 경고 코드
        self._message, self._level, self._message_field = "", "", ""
        self._focus = None
        self._close_asked = False
        self._last_save = None
        self._bad = {}                  # 칸 -> 마지막 저장 시도에서 틀린 줄 번호
        state, self.opened_blank = _load(home)
        self._secrets = _secrets_of(state["llm"])       # 저장된 키 · 헤더 값 (화면에는 가려서만 보인다 · 어디에도 찍지 않는다)
        self._texts = dict((key, to_text(key, state[key])) for key in TEXT_KEYS)
        self._lines = dict((key, len(lines_of(self._texts[key]))) for key in LIST_KEYS)
        self._web = state["web_search"]
        self._real = state["real_data"]
        self._initial_real = state["real_data"]
        self._derived = state["derived_level"] == 1            # 파생 표본 (L2) - 실데이터가 켜져 있을 때만 쓰인다
        self._initial_derived = self._derived
        self._real_confirm = ""
        self._initial = self._fingerprint()
        if self.opened_blank:
            self._say(TEXT_BLANK_OPEN, "info")

    # -- 보기

    def text(self, key):
        return self._texts[key]

    def line_count(self, key):
        """여러 줄 칸의 줄 수 (빈 줄 뺀 것 · 저장하면 단어는 중복 · 한 글자가 빠질 수 있다)."""
        return self._lines[key]

    @property
    def web_search(self):
        return self._web

    @property
    def real_data(self):
        return self._real

    @property
    def derived_level(self):
        return self._derived

    @property
    def real_confirm(self):
        return self._real_confirm

    @property
    def real_confirm_ok(self):
        return self._real_confirm == REAL_DATA_PHRASE

    def _fingerprint(self):
        fp = {}
        for key in TEXT_KEYS:
            try:
                fp[key] = ("v", to_value(key, self._texts[key]))
            except FieldProblem:
                fp[key] = ("t", self._texts[key].strip())
        fp["web_search"], fp["real_data"] = self._web, self._real
        fp["derived_level"] = self._derived
        return fp

    @property
    def dirty(self):
        """처음 연 뒤 고친 것이 있나 (빈 줄 · 앞뒤 빈칸 · 쓰다 지운 글은 고친 것이 아니다)."""
        return self._fingerprint() != self._initial

    def hidden_hits(self):
        hits = []
        for key in TEXT_KEYS:
            hits.extend(hidden_hits_in(key, self._texts[key]))
        return hits

    def risky_count(self):
        """사전 칸의 짧은 단어 + 겹침 항목 수 (오탐 위험 - 개수만). 지금 칸의 글로 센다."""
        return sum(scan.risky_counts(lines_of(self._texts["words"])))

    def risky_notice(self):
        """오탐 위험 알림 한 줄 (없으면 빈 글). 단어 · 값은 쓰지 않는다. 저장을 막지 않는다."""
        n = self.risky_count()
        return TEXT_WARN_MARK + TEXT_RISKY % n if n else ""

    def bad_lines(self, key):
        """key 칸에서 마지막 저장 시도가 틀렸다고 한 줄 번호 (1부터). 그 칸을 고치면 비운다."""
        return list(self._bad.get(key, ()))

    def hidden_lines(self, key):
        """key 칸에서 보이지 않는 글자가 든 줄 번호 (1부터). 화면이 그 줄을 눈에 띄게 한다."""
        return sorted(set(h.line for h in hidden_hits_in(key, self._texts[key])))

    # -- 상태 줄

    def _say(self, message, level, field=""):
        """상태 줄의 글 · 꼴 · 그 글이 가리키는 칸 (그 칸을 바로잡으면 지운다)."""
        self._message, self._level, self._message_field = message, level, field

    def _touched(self):
        """칸이 바뀌었다 - 닫기 확인은 처음부터 다시."""
        if self._close_asked:
            self._close_asked = False
            self._say("", "")

    def take_focus(self):
        """틀린 칸 (또는 눌러야 할 칸) 의 이름을 한 번만 알려 준다. 화면이 그 칸으로 초점을 옮긴다."""
        key, self._focus = self._focus, None
        return key

    # -- 고치기 (화면이 알린다)

    def set_text(self, key, text):
        """key 칸의 글을 text 로. 바뀌었으면 True. 저장한 뒤에는 고치지 않는다."""
        if key not in TEXT_KEYS:
            raise KeyError(key)
        if type(text) is not str:
            raise TypeError("글이 아님")
        if self.saved or text == self._texts[key]:
            return False
        self._texts[key] = text
        self._bad.pop(key, None)
        if key in self._lines:
            self._lines[key] = len(lines_of(text))
        if self._level == "alert" and self._message_field == key:        # 틀렸다고 한 칸을 고치기 시작했다 - 묵은 오류는 거둔다
            self._say("", "")
        self._touched()
        return True

    def append_line(self, key, line):
        """여러 줄 칸에 한 줄 더한다 ([폴더 고르기]). 이미 있는 줄이면 더하지 않는다."""
        if key not in LIST_KEYS:
            raise KeyError(key)
        line = line.strip()
        if self.saved or not line or "\n" in _breaks(line):
            return False
        if line in lines_of(self._texts[key]):
            self._say(TEXT_LINE_DUP, "info")
            return False
        old = self._texts[key].rstrip()
        self.set_text(key, (old + "\n" if old else "") + line)
        self._say(TEXT_LINE_ADDED % FIELD_LABEL[key], "info")
        return True

    def fill_example(self):
        """[예시 넣기] - 일꾼 명령 칸이 비어 있을 때만 (적어 둔 것을 지우지 않는다)."""
        if self.saved:
            return False
        if self._texts["worker_command"].strip():
            self._say(TEXT_EXAMPLE_KEPT, "info")
            return False
        self.set_text("worker_command", WORKER_EXAMPLE)
        self._say(TEXT_EXAMPLE_DONE, "info")
        return True

    def set_web_search(self, on):
        if self.saved:
            return self._web
        self._web = bool(on)
        self._touched()
        return self._web

    def set_real_confirm(self, text):
        """실데이터 확인 글 칸. 고친 것으로 세지 않는다 (켜는 데 쓰일 뿐 저장하지 않는다)."""
        if type(text) is not str:
            raise TypeError("글이 아님")
        self._real_confirm = text
        if self._message_field in ("real_data", "real_confirm") and self.real_confirm_ok:      # 안내받은 글을 쳤다
            self._say("", "")

    def toggle_real_data(self, want):
        """실데이터 칸을 want 로. 새로 켜려면 확인 글 칸에 정확히 REAL_DATA_PHRASE 를 쳐야 한다 - 아니면 켜지지 않고 안내한다.
        끄는 것 (이미 켜져 있던 것을 포함) 은 확인이 필요 없고, 처음에 켜져 있던 것을 다시 켜는 것도 그렇다.
        칸이 want 대로 되었으면 True. 칸의 지금 값은 real_data 로 본다."""
        if self.saved:
            return self._real == bool(want)
        want = bool(want)
        if want and not self._initial_real and not self.real_confirm_ok:
            self._real = False
            self._say("%s - %s" % (FIELD_LABEL["real_data"], TEXT_REAL_NEED), "alert", "real_data")
            self._focus = "real_confirm"
            return False
        self._real = want
        if not want:
            self._derived = False                           # 실데이터를 끄면 파생 표본도 꺼진다 (실데이터 승인 없이 켜져 있지 않게)
        if self._message_field in ("real_data", "real_confirm"):        # 안내받은 대로 바로잡았다
            self._say("", "")
        self._touched()
        return True

    def toggle_derived_level(self, want):
        """파생 표본 (L2) 칸을 want 로. 새로 켜려면 실데이터가 켜져 있어야 하고 확인 글 칸에 정확히 REAL_DATA_PHRASE 를 쳐야 한다.
        끄는 것은 확인이 필요 없다. 환경 변수 · 명령줄로 켜는 길은 없다 - 이 칸이 켜는 유일한 곳이다. 칸이 want 대로 되었으면 True."""
        if self.saved:
            return self._derived == bool(want)
        want = bool(want)
        if want and not self._initial_derived:
            if not self._real:
                self._derived = False
                self._say("%s - %s" % (FIELD_LABEL["derived_level"], ERROR_TEXT["derived"]), "alert", "derived_level")
                return False
            if not self.real_confirm_ok:
                self._derived = False
                self._say("%s - %s" % (FIELD_LABEL["derived_level"], TEXT_REAL_NEED), "alert", "derived_level")
                self._focus = "real_confirm"
                return False
        self._derived = want
        if self._message_field in ("derived_level", "real_confirm"):
            self._say("", "")
        self._touched()
        return True

    # -- 검증 · 저장

    def _unmask_llm(self, llm):
        """llm 글에서 가린 표시는 저장된 값으로 되돌리고, 새로 글자 그대로 적은 키 · 헤더 값은 막는다 (참조만 받는다)."""
        if llm is None:
            return None
        out = dict(llm)
        if "api_key" in out:
            out["api_key"] = self._unmask(("api_key",), out["api_key"])
        if isinstance(out.get("extra_headers"), dict):
            out["extra_headers"] = dict((k, self._unmask(("extra_headers", k), v)) for k, v in out["extra_headers"].items())
        return out

    def _unmask(self, where, value):
        if isinstance(value, str) and MASK_RE.match(value):
            if where in self._secrets:
                return self._secrets[where]
            raise FieldProblem("llm_key", "llm")                # 가린 표시를 다른 자리에 옮겨 적었다
        if _is_secret(value):
            raise FieldProblem("llm_key", "llm")
        return value

    def _build_state(self):
        state = dict((key, to_value(key, self._texts[key])) for key in TEXT_KEYS)
        state["llm"] = self._unmask_llm(state["llm"])
        state["web_search"] = self._web
        state["real_data"] = self._real
        state["derived_level"] = 1 if self._derived else 0
        return state

    def _bad_lines(self, area, field):
        """여러 줄 칸에서 영역 area 로 틀린 줄 번호 (1부터). 줄 하나씩 config 에 보여 가려낸다 - 규칙을 따로 베끼지 않는다.
        줄 하나가 틀린 것이 아니면 (개수 한도 · 한 칸 값) 빈 목록."""
        if field not in LIST_KEYS:
            return []
        bad = []
        for n, line in enumerate(_breaks(self._texts[field]).split("\n"), 1):
            if not line.strip():
                continue
            probe = _blank_state()
            probe[field] = [line.strip()]
            try:
                config.validate_state(probe)
            except config.ConfigError as e:
                if e.code == area:
                    bad.append(n)
        return bad

    def _failed(self, area, field):
        text = ERROR_TEXT.get(area, ERROR_TEXT["state"])
        lines = self._bad_lines(area, field)
        where = ""
        if lines:
            where = " (%s%s)" % (" · ".join("%d째 줄" % n for n in lines[:MAX_LINES_SHOWN]),
                                 " 외 %d곳" % (len(lines) - MAX_LINES_SHOWN) if len(lines) > MAX_LINES_SHOWN else "")
        return Checked(False, None, [], area, field, "%s - %s%s" % (FIELD_LABEL.get(field, "정책"), text, where), tuple(lines))

    def validate(self):
        """칸의 글을 값으로 바꿔 config.validate_state 에 보인다 -> Checked.

        ok 면 state (정리한 값) · warnings (경고 코드). 아니면 area (오류 영역 코드) · field (틀린 칸) · message (칸 이름이
        든 한 줄 - 틀린 값은 쓰지 않는다). 아무것도 쓰지 않는다."""
        hits = self.hidden_hits()
        if hits:
            return Checked(False, None, [], "hidden", hits[0].field, describe_hits(hits), ())
        try:
            state = self._build_state()
        except FieldProblem as e:
            return self._failed(e.area, e.field)
        if state["real_data"] and not self._initial_real and not self.real_confirm_ok:
            return self._failed("real_data", AREA_FIELD["real_data"])
        if state["derived_level"] == 1:
            if not state["real_data"]:
                return self._failed("derived", AREA_FIELD["derived"])
            if not self._initial_derived and not self.real_confirm_ok:
                return self._failed("real_data", AREA_FIELD["real_data"])
        if state["worker_cwd"] is not None and state["worker_command"] is None:
            return self._failed("worker", "worker_cwd")         # 작업 폴더만 적은 칸 - 명령 칸이 아니라 그 칸을 가리킨다
        try:
            clean, warn = config.validate_state(state)
        except config.ConfigError as e:
            return self._failed(e.code, AREA_FIELD.get(e.code, ""))
        return Checked(True, clean, list(warn), "", "", "", ())

    def save(self):
        """검증하고 config.apply_state 로 쓴다 -> Saved. 틀린 데가 있으면 아무것도 쓰지 않고 상태 줄에 알린다.
        한 번도 고치지 않았어도 막지 않는다 - 쓰되 "바뀐 것 없음" 으로 알린다."""
        if self.saved:
            return self._last_save
        self._close_asked = False
        checked = self.validate()
        if not checked.ok:
            self._say(checked.message, "alert", checked.field)
            self._focus = checked.field
            self._bad = {checked.field: list(checked.lines)} if checked.lines else {}
            return Saved(False, False, None, [], checked.area, checked.field, checked.message)
        changed = self.dirty or self.opened_blank
        try:
            # 검증한 그 입력 그대로 넘긴다 - 정리한 값을 넘기면 정리 중에 빠진 것 (두 글자 미만 항목) 의 경고가 사라진다
            counts, warn = config.apply_state(self.home, self._build_state())
        except config.ConfigError as e:
            if e.code == "newer":
                return self._failed_write(e.code, TEXT_NEWER)
            return self._failed_write(e.code, self._failed(e.code, AREA_FIELD.get(e.code, "")).message)
        except OSError:
            return self._failed_write("write", TEXT_WRITE_FAILED)
        if not isinstance(counts, dict) or "error" in counts:
            return self._failed_write("read", TEXT_READBACK)
        self.saved = True
        self.counts, self.warnings = counts, list(warn)
        lines = [TEXT_SAVED if changed else TEXT_UNCHANGED, summarize(counts)]
        lines += [TEXT_WARN_MARK + WARN_TEXT.get(code, code) for code in warn]
        if self.risky_notice():
            lines.append(self.risky_notice())
        self._message, self._level = "\n".join(lines), "ok"
        self._last_save = Saved(True, changed, counts, list(warn), "", "", self._message)
        return self._last_save

    def _failed_write(self, area, message):
        self._say(message, "alert")
        return Saved(False, False, None, [], area, "", message)

    # -- 닫기

    def request_close(self):
        """[닫기] · 창 닫기 (X). 닫아도 되면 True (finished). 저장 안 한 변경이 있으면 한 번 묻고 (다시 누르면 닫는다) False."""
        if self.finished:
            return True
        if self.saved or self._close_asked or not self.dirty:
            self.finished = True
            return True
        self._close_asked = True
        self._say(TEXT_CLOSE_ASK, "ask")
        return False

    def snapshot(self):
        return Snapshot(
            message=self._message or TEXT_IDLE, level=self._level, locked=self.saved, save_enabled=not self.saved,
            close_label="저장 안 하고 닫기" if self._close_asked else "닫기", real_data=self._real, web_search=self._web,
            lines=tuple((key, self._lines[key]) for key in LIST_KEYS), derived=self._derived)


# ---------------------------------------------------------------- 화면 (tkinter)

def _tkinter_font():
    """tkinter 를 import 한 것만으로는 font 하위 모듈이 붙지 않는다."""
    import tkinter.font
    return tkinter.font


def _tkinter_filedialog():
    import tkinter.filedialog
    return tkinter.filedialog


# 상태 줄의 칩: (글, 바탕, 글자) - 경고 · 오류는 가장 밝은 글자색 + ERR 칩 (DESIGN.md › 02)
_CHIPS = {"": ("EDIT", "navy2", "white"), "info": ("EDIT", "navy2", "white"), "ok": ("OK", "lime", "black"),
          "alert": ("ERR", "white", "black"), "ask": ("ASK", "lime3", "black")}
_STATUS_FG = {"": "navy5", "info": "white", "ok": "lime3", "alert": "white", "ask": "lime3"}


class TkView(object):
    """tkinter 화면 백엔드 - 그리기만 한다. 칸의 글이 바뀔 때마다 session 에 알리고 상태는 session 이 정한다.

    run(session) 이 보통의 길이다. 시험은 open / pump / close 를 따로 불러 위젯을 눌러 본다 (widgets).
    """

    def __init__(self, tk_module):
        self._tk = tk_module
        self._root = None
        self._session = None
        self._error = None
        self._last = None
        self._tkfont = None
        self._family = None
        self._fonts = {}
        self._wrapped = []
        self._vars = {}
        self._toggle_text = {}
        self._jobs = []
        self._pushing = False
        self._locked = False
        self.widgets = {}

    @property
    def root(self):
        return self._root

    def run(self, session):
        self.open(session)
        try:
            while not session.finished:
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

    def pump(self):
        """한 바퀴: 눌림을 처리하고 상태 줄 · 단추를 그린다."""
        self._root.update()
        if self._error is not None:
            raise self._error
        self._render(self._session.snapshot())

    def close(self):
        root, self._root = self._root, None
        if root is not None:
            for job in self._jobs:                  # 남은 예약을 거둔다 (창이 없어진 뒤에 돌아 "invalid command name" 이 뜨지 않게)
                try:
                    root.after_cancel(job)
                except self._tk.TclError:
                    pass
            self._jobs = []
            try:
                root.destroy()
            except self._tk.TclError:
                pass

    def _after(self, ms, func):
        """창이 살아 있는 동안만 도는 예약."""
        job = self._root.after(ms, func)
        self._jobs.append(job)
        return job

    # -- 눌림

    def _on_callback_error(self, exc, val, tb):
        self._error = val

    def _push_all(self):
        """칸의 글을 모두 session 에 알린다 (저장 · 닫기 직전 - 이벤트가 아직 안 온 글도 놓치지 않게)."""
        s = self._session
        for key in TEXT_KEYS:
            widget = self.widgets[key]
            if key in self._vars:
                s.set_text(key, self._vars[key].get())
            else:
                s.set_text(key, widget.get("1.0", "end-1c"))
        s.set_real_confirm(self._vars["real_confirm"].get())

    def _on_text(self, key):
        """여러 줄 칸의 글이 바뀜 (<<Modified>>)."""
        text = self.widgets[key]
        if self._pushing or not text.edit_modified():
            return
        text.edit_modified(False)
        self._session.set_text(key, text.get("1.0", "end-1c"))
        self._refresh(key)

    def _on_var(self, key):
        """한 줄 칸의 글이 바뀜."""
        if self._pushing:
            return
        if key == "real_confirm":
            self._session.set_real_confirm(self._vars[key].get())
        else:
            self._session.set_text(key, self._vars[key].get())

    def _refresh(self, key):
        """줄 수와 보이지 않는 글자가 든 줄 표시를 다시 그린다."""
        w = self.widgets
        s = self._session
        if "count_" + key in w:
            w["count_" + key].configure(text="%d줄" % s.line_count(key))
        text = w[key]
        if text.winfo_class() == "Text":
            for tag, numbers in (("hidden", s.hidden_lines(key)), ("bad", s.bad_lines(key))):
                text.tag_remove(tag, "1.0", "end")
                for n in numbers:
                    text.tag_add(tag, "%d.0" % n, "%d.end" % n)

    def _put(self, key, text):
        """session 이 정한 글을 칸에 넣는다 (화면 -> session 알림을 되풀이하지 않게 막고)."""
        self._pushing = True
        try:
            if key in self._vars:
                self._vars[key].set(text)
            else:
                widget = self.widgets[key]
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
                widget.edit_modified(False)
                widget.edit_reset()
        finally:
            self._pushing = False
        self._refresh(key)

    def _on_save(self):
        self._push_all()
        self._session.save()
        for key in TEXT_KEYS:                       # 틀린 줄 표시를 새로 그린다
            self._refresh(key)
        self._after_action()

    def _on_close(self):
        if self._root is None:
            return
        self._push_all()
        self._session.request_close()
        self._render(self._session.snapshot())

    def _on_real_toggle(self):
        s = self._session
        s.toggle_real_data(self._vars["real_data"].get())
        self._vars["real_data"].set(s.real_data)            # 켜지지 않았으면 칸을 되돌린다
        self._after_action()

    def _on_derived_toggle(self):
        s = self._session
        s.toggle_derived_level(self._vars["derived_level"].get())
        self._vars["derived_level"].set(s.derived_level)    # 켜지지 않았으면 칸을 되돌린다
        self._after_action()

    def _on_web_toggle(self):
        self._session.set_web_search(self._vars["web_search"].get())
        self._after_action()

    def _on_pick(self):
        """[폴더 고르기] - 사람이 고른 폴더를 02 원자료 폴더에 한 줄 더한다."""
        path = self._ask_directory()
        if path:
            self._session.append_line("raw_dirs", os.path.normpath(path))
            self._put("raw_dirs", self._session.text("raw_dirs"))
            self.widgets["raw_dirs"].see("end")
            self._after_action()

    def _ask_directory(self):
        """폴더 고르기 대화상자. 대화상자가 못 열리면 고르지 않은 것으로 본다 (창을 죽이지 않는다)."""
        try:
            return _tkinter_filedialog().askdirectory(parent=self._root, title="원자료 폴더 고르기", mustexist=True)
        except self._tk.TclError:
            return ""

    def _on_example(self):
        if self._session.fill_example():
            self._put("worker_command", self._session.text("worker_command"))
        self._after_action()

    def _after_action(self):
        """누른 뒤 - 상태 줄을 새로 그리고, 틀린 칸이 있으면 그 칸으로 초점을 옮긴다."""
        self._render(self._session.snapshot())
        key = self._session.take_focus()
        if key and self._root is not None:
            widget = self.widgets.get(key)
            if widget is not None:
                self._reveal(widget)
                try:
                    widget.focus_set()
                except self._tk.TclError:
                    pass

    def _focus_next(self, event):
        event.widget.tk_focusNext().focus_set()
        return "break"

    def _focus_prev(self, event):
        event.widget.tk_focusPrev().focus_set()
        return "break"

    def _on_wheel(self, event):
        """바퀴: 글 칸 위에서는 그 칸이 스스로 굴리고, 그 밖에서는 본문을 굴린다."""
        try:
            if event.widget.winfo_class() == "Text":
                return None
        except Exception:                   # 이 창의 위젯이 아닌 곳 (이미 닫힌 위젯 · 대화상자) 에서 온 바퀴
            return None
        canvas = self.widgets["canvas"]
        delta = getattr(event, "delta", 0)
        up = event.num == 4 or delta > 0
        canvas.yview_scroll(-3 if up else 3, "units")
        return "break"

    def _on_focus_in(self, event):
        self._reveal(event.widget)

    def _reveal(self, widget):
        """widget 이 본문의 보이는 자리 밖이면 그 자리로 굴린다."""
        w = self.widgets
        canvas, body = w["canvas"], w["body"]
        try:
            top = widget.winfo_rooty() - body.winfo_rooty()
            bottom = top + widget.winfo_height()
            seen_top = canvas.canvasy(0)
            seen = canvas.winfo_height()
            total = max(1, body.winfo_height())
            if top < seen_top:
                canvas.yview_moveto(max(0.0, (top - 8) / float(total)))
            elif bottom > seen_top + seen:
                canvas.yview_moveto(min(1.0, (bottom - seen + 8) / float(total)))
        except self._tk.TclError:
            pass

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
        if confirm.UNIFONT in have:
            return confirm.UNIFONT, (16, 16, 32)
        for name in confirm.MONO_FAMILIES:
            if name in have:
                return name, (15, 13, 26)
        return self._tkfont.Font(root=self._root, name="TkFixedFont", exists=True).actual("family"), (15, 13, 26)

    def _label(self, parent, text, font, bg, fg, side=0, **options):
        """줄을 감는 라벨 하나 - 본문 너비에서 side (옆에 붙는 것의 너비) 와 여백을 뺀 만큼에서 줄을 바꾼다."""
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

    def _style(self, button, enabled, label=None, accent=False):
        """켜진 단추는 네이비 바탕 (accent 는 라임 글자) · 꺼진 단추는 꺼진 LED 회색."""
        c = PALETTE
        options = {} if label is None else {"text": label}
        if enabled:
            button.configure(state="normal", bg=c["navy2"], fg=c["lime3"] if accent else c["white"],
                             activebackground=c["lime1"], activeforeground=c["white"], **options)
        else:
            button.configure(state="disabled", bg=c["gray0"], fg=c["gray1"], disabledforeground=c["gray1"], **options)

    def _zone(self, parent, code, title, hint, key=None, extra=None):
        """구역 하나 (칩 = 번호 + 영문 이름 · 한국어 이름 · 줄 수 · 설명). 구역 틀을 돌려준다."""
        tk = self._tk
        c = PALETTE
        zone = tk.Frame(parent, bg=c["black"], padx=16, pady=8)
        zone.pack(fill="x")
        zone.columnconfigure(0, weight=1)
        bar = tk.Frame(zone, bg=c["black"])
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._chip(bar, code).pack(side="left")
        tk.Label(bar, text=title, font=self._fonts["strong"], bg=c["black"], fg=c["white"]).pack(side="left", padx=8)
        if key is not None:
            self.widgets["count_" + key] = tk.Label(bar, text="0줄", font=self._fonts["small"], bg=c["black"], fg=c["gray2"])
            self.widgets["count_" + key].pack(side="left")
        if extra is not None:
            extra(bar)
        if hint:
            self._label(zone, hint, "small", c["black"], c["gray2"]).grid(row=1, column=0, sticky="w", pady=(0, 4))
        return zone

    def _sub(self, zone, row, title, key=None):
        """구역 안의 작은 이름줄 (한 구역에 칸이 둘 이상일 때)."""
        tk = self._tk
        c = PALETTE
        bar = tk.Frame(zone, bg=c["black"])
        bar.grid(row=row, column=0, sticky="ew", pady=(6, 2))
        self._label(bar, title, "small", c["black"], c["gray4"], side=60).pack(side="left")
        if key is not None:
            self.widgets["count_" + key] = tk.Label(bar, text="0줄", font=self._fonts["small"], bg=c["black"], fg=c["gray2"])
            self.widgets["count_" + key].pack(side="left", padx=8)
        return bar

    def _text_box(self, zone, row, key, height):
        """여러 줄 글 칸 (세로 줄 · 줄 수 · 보이지 않는 글자가 든 줄 표시)."""
        tk = self._tk
        c = PALETTE
        frame = tk.Frame(zone, bg=c["black"])
        frame.grid(row=row, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, wrap="char", width=84, height=height, font=self._fonts["body"], bg=c["black"], fg=c["gray4"],
                       insertbackground=c["lime"], insertwidth=2, relief="flat", bd=0, padx=10, pady=8, highlightthickness=1,
                       highlightbackground=c["navy3"], highlightcolor=c["lime"], selectbackground=c["navy3"],
                       selectforeground=c["white"], undo=True, maxundo=200, takefocus=1)
        text.grid(row=0, column=0, sticky="ew")
        scroll = tk.Scrollbar(frame, orient="vertical", command=text.yview, bg=c["navy2"], troughcolor=c["black"],
                              activebackground=c["navy3"], relief="flat", bd=0)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("hidden", background=c["white"], foreground=c["navy"])
        text.tag_configure("bad", background=c["lime"], foreground=c["black"])
        text.insert("1.0", self._session.text(key))
        text.edit_modified(False)
        text.edit_reset()
        text.bind("<<Modified>>", lambda event, k=key: self._on_text(k))
        text.bind("<Tab>", self._focus_next)
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):          # 키 이름이 없는 곳 (Windows) 에서는 건너뛴다
            try:
                text.bind(sequence, self._focus_prev)
            except self._tk.TclError:
                pass
        text.bind("<FocusIn>", self._on_focus_in)
        self.widgets[key] = text
        return text

    def _entry(self, zone, row, key):
        """한 줄 글 칸."""
        tk = self._tk
        c = PALETTE
        var = tk.StringVar(master=self._root)
        entry = tk.Entry(zone, textvariable=var, font=self._fonts["body"], bg=c["black"], fg=c["gray4"],
                         insertbackground=c["lime"], insertwidth=2, relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=c["navy3"], highlightcolor=c["lime"], selectbackground=c["navy3"],
                         selectforeground=c["white"], disabledbackground=c["black"], disabledforeground=c["gray1"],
                         readonlybackground=c["black"], takefocus=1)
        entry.grid(row=row, column=0, sticky="ew", ipady=4)
        entry.bind("<FocusIn>", self._on_focus_in)
        self.widgets[key] = entry
        self._vars[key] = var
        return entry

    def _set_entry(self, key, text):
        self._pushing = True
        try:
            self._vars[key].set(text)
        finally:
            self._pushing = False

    def _toggle(self, zone, row, key, text, command, value):
        """켜짐 · 꺼짐 칸 - 키캡 꼴 (켜짐은 네이비 바탕 · 라임 글자 · ● / 꺼짐은 꺼진 LED 회색 · ○). 어느 OS 에서도 같게 보인다."""
        tk = self._tk
        c = PALETTE
        var = tk.BooleanVar(master=self._root, value=value)
        box = tk.Checkbutton(zone, text=text, variable=var, command=command, indicatoron=False, font=self._fonts["body"],
                             bg=c["gray0"], fg=c["gray"], selectcolor=c["navy2"], activebackground=c["navy3"],
                             activeforeground=c["white"], disabledforeground=c["gray1"], highlightthickness=2,
                             highlightbackground=c["black"], highlightcolor=c["lime"], anchor="w", justify="left", bd=0,
                             relief="flat", padx=12, pady=4, takefocus=1)
        box.grid(row=row, column=0, sticky="w", pady=2)
        box.bind("<FocusIn>", self._on_focus_in)
        self.widgets[key] = box
        self._vars[key] = var
        self._toggle_text[key] = text
        self._sync_toggle(key)
        return box

    def _sync_toggle(self, key):
        """켜짐 · 꺼짐 칸의 모양을 변수 값에 맞춘다."""
        on = bool(self._vars[key].get())
        self.widgets[key].configure(text="%s %s" % ("●" if on else "○", self._toggle_text[key]),
                                    fg=PALETTE["lime3"] if on else PALETTE["gray"])

    def _build(self):
        tk = self._tk
        root = self._root
        s = self._session
        c = PALETTE
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
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(sequence, self._on_wheel)

        # 00 - 맨 위 큰 글자
        head = tk.Frame(root, bg=c["navy"], padx=16, pady=12)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._chip(head, "POLICY", c["navy3"], c["white"]).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 16))
        w["title"] = tk.Label(head, text="정책 편집", font=self._fonts["title"], bg=c["navy"], fg=c["white"], anchor="w")
        w["title"].grid(row=0, column=1, sticky="w")
        w["subtitle"] = self._label(head, TEXT_SUBTITLE, "small", c["navy"], c["navy5"])
        w["subtitle"].grid(row=1, column=1, sticky="w")

        # 본문 - 세로로 굴러가는 구역들
        canvas = tk.Canvas(root, bg=c["black"], highlightthickness=0, bd=0)
        canvas.grid(row=1, column=0, sticky="nsew")
        vbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview, bg=c["navy2"], troughcolor=c["black"],
                            activebackground=c["navy3"], relief="flat", bd=0)
        vbar.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vbar.set)
        inner = tk.Frame(canvas, bg=c["black"])
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: self._on_canvas(event.width, window))
        w["canvas"], w["body"], w["vbar"] = canvas, inner, vbar

        # 01 사전
        zone = self._zone(inner, "01 DICT", "사전", "사내 단어를 한 줄에 하나씩 적습니다. # 로 시작하는 줄도 단어입니다 "
                          "(주석이 아닙니다). 두 글자 미만은 쓰이지 않고, 같은 단어는 하나로 합칩니다.", key="words")
        self._text_box(zone, 2, "words", 9)

        # 02 원자료 폴더
        def pick(bar):
            w["pick_dir"] = self._button(bar, "폴더 고르기", self._on_pick)
            w["pick_dir"].pack(side="right")
            self._style(w["pick_dir"], True)
        zone = self._zone(inner, "02 RAW", "원자료 폴더", "원자료가 있는 폴더의 전체 경로를 한 줄에 하나씩 적습니다. "
                          "목록이 비면 보내기를 막습니다.", key="raw_dirs", extra=pick)
        self._text_box(zone, 2, "raw_dirs", 4)

        # 03 안쪽 도구
        zone = self._zone(inner, "03 TOOLS", "안쪽 도구", "Claude 가 직접 부르면 막을 안쪽 도구의 이름 조각을 한 줄에 하나씩 적습니다. "
                          "opencode 는 늘 들어 있습니다.", key="inner_tools")
        self._text_box(zone, 2, "inner_tools", 3)

        # 04 일꾼
        def example(bar):
            w["example"] = self._button(bar, "예시 넣기", self._on_example)
            w["example"].pack(side="right")
            self._style(w["example"], True)
        zone = self._zone(inner, "04 WORKER", "일꾼", "일꾼을 띄우는 명령을 한 줄 JSON 목록으로 적습니다. {prompt} 는 한 곳만, "
                          "{cwd} 는 작업 폴더로 바뀝니다. 경로의 \\ 는 \\\\ 로 적습니다. 비우면 일꾼이 없는 것입니다.", extra=example)
        self._sub(zone, 2, "명령 (JSON 목록)")
        self._entry(zone, 3, "worker_command")
        self._sub(zone, 4, "작업 폴더 (비우면 데이터 폴더의 work 아래)")
        self._entry(zone, 5, "worker_cwd")

        # 05 라이브러리
        zone = self._zone(inner, "05 LIB", "라이브러리", "허용할 라이브러리 이름과, D3 에 더해 막을 정규식을 한 줄에 하나씩 적습니다.")
        self._sub(zone, 2, "허용 목록", "lib_allow")
        self._text_box(zone, 3, "lib_allow", 3)
        self._sub(zone, 4, "정규식", "patterns")
        self._text_box(zone, 5, "patterns", 3)

        # 06 선택
        zone = self._zone(inner, "06 OPTION", "선택", "")
        self._toggle(zone, 1, "web_search", "방 세션의 웹 검색을 허용합니다", self._on_web_toggle, s.web_search)
        self._toggle(zone, 2, "real_data", "실데이터를 허용합니다 (보안 부서 승인 뒤에만)", self._on_real_toggle, s.real_data)
        self._sub(zone, 3, "실데이터 확인 글 - 새로 켜려면 정확히 '%s' 을 치세요 (끄는 데는 필요 없습니다)" % REAL_DATA_PHRASE)
        self._entry(zone, 4, "real_confirm")
        self._sub(zone, 5, "월 예산 (USD · 비우면 0 = 없음)")
        self._entry(zone, 6, "monthly_budget_usd")
        self._sub(zone, 7, "방 자리 (전체 경로 · 비우면 기본)")
        self._entry(zone, 8, "room_path")
        self._sub(zone, 9, "llm 설정 (JSON 객체 · 키 · 헤더 값은 {file:경로} 로만 · 경로의 \\ 는 \\\\ 로 · 이미 저장된 값은 가려서 보이고 그대로 둡니다 · "
                   "비우면 지금 설정을 그대로 둡니다)")
        self._text_box(zone, 10, "llm", 5)
        self._toggle(zone, 11, "derived_level", "파생 표본 (L2) 을 허용합니다 (실데이터를 허용한 뒤 · 위 확인 글이 있어야 켜집니다)",
                     self._on_derived_toggle, s.derived_level)

        for key in ("worker_command", "worker_cwd", "monthly_budget_usd", "room_path"):
            self._set_entry(key, s.text(key))
            self._vars[key].trace_add("write", lambda *args, k=key: self._on_var(k))
        self._vars["real_confirm"].trace_add("write", lambda *args: self._on_var("real_confirm"))

        # 아래 줄 - 상태 한 줄 · 단추
        foot = tk.Frame(root, bg=c["navy"], padx=16, pady=10)
        foot.grid(row=2, column=0, columnspan=2, sticky="ew")
        foot.columnconfigure(1, weight=1)
        w["status_chip"] = self._chip(foot, "EDIT")
        w["status_chip"].grid(row=0, column=0, sticky="nw", padx=(0, 12))
        w["status"] = self._label(foot, TEXT_IDLE, "small", c["navy"], c["white"], side=110)
        w["status"].grid(row=0, column=1, sticky="w")
        w["save"] = self._button(foot, "저장", self._on_save)
        w["close"] = self._button(foot, "닫기", self._on_close)
        w["save"].grid(row=1, column=0, pady=(10, 0), padx=(0, 8))
        w["close"].grid(row=1, column=1, pady=(10, 0), sticky="w")
        self._style(w["close"], True)
        for key in TEXT_KEYS:
            self._refresh(key)
        self._render(s.snapshot())

        # 화면에 앉히기 - 본문은 화면에 들게 줄이고 (세로 줄로 굴린다) · 가운데 · 맨 앞 · 처음 초점은 사전 칸
        root.update_idletasks()
        for label, side in self._wrapped:
            label.configure(wraplength=max(240, inner.winfo_reqwidth() - WRAP_MARGIN_PX - side))
        root.update_idletasks()
        room = root.winfo_screenheight() - SCREEN_MARGIN_PX - head.winfo_reqheight() - foot.winfo_reqheight()
        canvas.configure(width=inner.winfo_reqwidth(), height=max(160, min(inner.winfo_reqheight(), room)))
        root.update_idletasks()
        root.minsize(min(root.winfo_reqwidth(), 480), head.winfo_reqheight() + foot.winfo_reqheight() + 160)
        width, height = root.winfo_reqwidth(), root.winfo_reqheight()
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 3)
        root.geometry("%dx%d+%d+%d" % (width, height, x, y))     # 크기를 못 박아 둔다 - 상태 줄이 길어지면 창이 아니라 본문이 줄어든다
        try:
            root.attributes("-topmost", True)
            self._after(TOPMOST_MS, self._release_topmost)
        except tk.TclError:
            pass
        root.lift()
        try:
            w["words"].focus_force()
        except tk.TclError:
            w["words"].focus_set()

    def _release_topmost(self):
        if self._root is not None:
            try:
                self._root.attributes("-topmost", False)
            except self._tk.TclError:
                pass

    def _on_canvas(self, width, window):
        """본문의 너비를 창에 맞추고 줄 감는 글의 너비도 다시 맞춘다."""
        canvas = self.widgets["canvas"]
        canvas.itemconfigure(window, width=width)
        for label, side in self._wrapped:
            label.configure(wraplength=max(240, width - WRAP_MARGIN_PX - side))

    def _lock(self):
        """저장을 마쳤다 - 칸은 더 고치지 못하게 잠그고 [닫기] 만 남긴다."""
        self._locked = True
        w = self.widgets
        for key in TEXT_KEYS + ("real_confirm", "web_search", "real_data", "derived_level"):
            try:
                w[key].configure(state="disabled")
            except self._tk.TclError:
                pass
        for key in ("pick_dir", "example"):
            self._style(w[key], False)
        w["save"].grid_remove()
        try:
            w["close"].focus_set()
        except self._tk.TclError:
            pass

    def _render(self, snap):
        """상태 줄 · 단추 · 켜짐 칸을 snap 대로 맞춘다 (바뀐 때만)."""
        if snap == self._last:
            return
        self._last = snap
        w = self.widgets
        c = PALETTE
        chip, chip_bg, chip_fg = _CHIPS[snap.level]
        w["status_chip"].configure(text=" %s " % chip, bg=c[chip_bg], fg=c[chip_fg])
        strong = snap.level in ("alert", "ask")
        w["status"].configure(text=snap.message, fg=c[_STATUS_FG[snap.level]], font=self._fonts["strong" if strong else "small"])
        w["close"].configure(text=snap.close_label)
        self._style(w["save"], snap.save_enabled, accent=True)
        for key in ("web_search", "real_data", "derived_level"):
            value = {"web_search": snap.web_search, "real_data": snap.real_data, "derived_level": snap.derived}[key]
            if self._vars[key].get() != value:
                self._vars[key].set(value)
            self._sync_toggle(key)
        for key, n in snap.lines:
            w["count_" + key].configure(text="%d줄" % n)
        if snap.locked and not self._locked:
            self._lock()


# ---------------------------------------------------------------- 창 띄우기 (E-07)

def _is_windows():
    return os.name == "nt"


def create_view():
    """화면 백엔드를 만든다. 시험은 이 이름을 바꿔 끼워 가짜 화면으로 논리를 본다 (AL-12: 건너뛰는 길은 따로 없다)."""
    if confirm.display_missing(os.environ, _is_windows()):
        raise WindowUnavailable("display")
    try:
        import tkinter
        import tkinter.font  # noqa: F401  - TkView 가 쓴다
        import tkinter.filedialog  # noqa: F401  - [폴더 고르기] 가 쓴다
    except ImportError:
        raise WindowUnavailable("tkinter")
    return TkView(tkinter)


def can_open():
    """이 프로세스가 정책 창을 띄울 수 있나 (화면 · tkinter) - 따로 떼어 띄우면 부른 쪽이 실패를 모르므로 띄우기 전에 본다.

    창 프로세스는 같은 파이썬이라 (launch_detached 의 python) 여기서 되면 거기서도 된다.
    """
    if confirm.display_missing(os.environ, _is_windows()):
        return False
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def launch_detached(python, diode_py):
    """정책 창을 따로 떼어 띄운다 - 부른 쪽을 기다리게 하지 않는다 (결과 줄은 버려진다 · 저장했는지는 config.counts 로 본다).

    명령은 [python, diode_py, "policy"] 뿐이다. Windows 는 DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (콘솔도 부모의
    Ctrl+C 도 이어받지 않는다) · 그 밖은 새 세션 (start_new_session). 표준 입출력은 모두 버린다. 새 프로세스의 pid 를 돌려주고,
    띄우지 못하면 OSError 가 그대로 올라간다. 끝난 창은 따로 거둔다 (worker.py 와 같다 - 좀비를 남기지 않는다)."""
    argv = [python, diode_py, POLICY_COMMAND]
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if _is_windows():
        options["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", DETACHED_PROCESS)
                                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", CREATE_NEW_PROCESS_GROUP))
    else:
        options["start_new_session"] = True
    proc = subprocess.Popen(argv, **options)
    try:
        waiter = threading.Thread(target=proc.wait)
        waiter.daemon = True
        waiter.start()
    except RuntimeError:                        # 쓰레드를 못 만들어도 창은 이미 떴다
        pass
    return proc.pid


# ---------------------------------------------------------------- diode.py policy 의 몸통

def _result_line(obj):
    return json.dumps(obj)


def main_policy(home):
    """데이터 폴더 (home) 의 정책을 고치는 창을 띄우고 결과를 돌려준다 -> (종료 코드, 표준 출력 한 줄).

    사람이 [저장] 을 눌러야만 쓴다. 출력에는 단어 · 경로 · 일꾼 명령이 없다 (코드 · 개수 · 참거짓뿐). 어떤 예외도
    saved 가 참인 줄로 끝나지 않는다."""
    try:
        session = PolicySession(home)
        view = create_view()
        view.run(session)
        if not session.finished:                # 사람이 닫기 전에 끝난 화면 - 정상이 아니다
            return EXIT_FAILED, _result_line({"saved": False, "error": "E-20"})
        if not session.saved:
            return EXIT_NOT_SAVED, _result_line({"saved": False})
        counts = config.counts(home)
        if "error" in counts:
            return EXIT_FAILED, _result_line({"saved": False, "error": "E-20"})
        return EXIT_SAVED, _result_line({"saved": True, "counts": counts, "warnings": list(session.warnings)})
    except WindowUnavailable:
        return EXIT_FAILED, _result_line({"saved": False, "error": "E-07"})
    except config.ConfigError as e:
        if e.code == "newer":
            return EXIT_FAILED, _result_line({"saved": False, "error": "E-20", "code": "newer"})
        return EXIT_FAILED, _result_line({"saved": False, "error": "E-20"})
    except (Exception, KeyboardInterrupt):
        return EXIT_FAILED, _result_line({"saved": False, "error": "E-20"})
