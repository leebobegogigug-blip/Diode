# -*- coding: utf-8 -*-
"""말 봉인 창 (L-26 · SP-09 › 말 봉인 칸) - 사람이 사내 말로 쓴 글을 가명 토큰 글로 바꿔 보이고, 사람이 눈으로 확인한 뒤 복사한다
(표준 라이브러리 · Python 3.8).

`python diode.py speak` 이 부른다 (`/diode:speak` 는 `speak --detached` 로 창을 따로 떼어 연다). Claude 가 주 작업 자리라 사람이
사내 말을 Claude 에게 직접 치게 된다. 훅이 막기만 하면 사람은 도구를 끈다 (R6) - 그래서 사내 말은 이 창에서 쓰고, 사전 단어를
가명 토큰으로 바꾼 글만 복사해 Claude 에 붙여 넣는다. Claude 의 답을 이 창에 붙여 넣으면 토큰을 진짜 말로 되돌려 **이 창 안에서만**
보여 준다. 사내 말을 대화에 직접 치지 않으므로 슬래시 명령은 단어를 묻지도 받지도 않고 창을 열어 줄 뿐이다.

흐름 (사람이 하는 일 - 건너뛰는 길이 없다)
  쓰기 -> [봉인] (사전 단어를 긴 것부터 토큰으로 - seal.seal_speech - 바꾼 글을 D2 · D3 · D4 · D6 으로 다시 본다)
  -> 사람이 봉인한 글을 본다 -> [복사] (클립보드에 넣고 되읽어 같을 때만 성공) -> Claude 에 붙여 넣는다
  -> Claude 의 답을 붙여 넣고 [되돌려 보기] (U1 - U4 를 거쳐 아는 토큰만 진짜 말로 - 창 안에서만 보인다)

결과 (표준 출력 한 줄 JSON - 코드 · 개수 · 참거짓뿐. 단어 · 글 · 경로는 어디에도 없다 - AL-11)
  {"closed": true, "expired": false, "seals": 2, "copies": 1, "unseals": 1}          종료 코드 0  닫았다 (시간이 다 되어 닫혔어도 0)
  {"closed": false, "error": "E-07"}                                                 종료 코드 1  창을 못 띄움 (화면 · tkinter 없음)
  {"closed": false, "error": "E-20"}                                                 종료 코드 1  그 밖의 예외
  {"closed": false, "error": "E-20", "code": "words_empty" | "broken" | "newer"}     종료 코드 3  검사 불능 - 사전 · 설정을 못 읽거나 사전이 빔
                                                                                      (창을 열지 않는다 - 봉인할 수 없는 창은 거짓말이다)
  종료 코드 2 는 사용법 오류 (diode.py 가 낸다).

구조 - 논리와 화면을 나눈다 (confirm.py · policy_window.py 와 같다).
  SpeakSession   입력 글 · 봉인한 글 · 복사 가능 여부 · 되돌리기 · 닫기 · 시간. 화면을 모른다. 가명 표는 여기에만 있다.
  TkView         tkinter 화면. 그리기만 하고 누른 것은 session 에 알린다 (confirm.TkView 의 글꼴 · 칩 · 단추 부품을 쓴다).
  create_view()  화면 백엔드를 만드는 곳. 시험은 이 이름을 바꿔 끼워 가짜 화면으로 논리를 본다.
  open_detached  창을 따로 떼어 띄운다 (부른 쪽을 기다리게 하지 않는다 - /diode:speak).

지키는 것
- 가명 표 (PseudonymTable) 는 이 프로세스의 메모리에만 있다 (W-05 · AL-05). 디스크 · 로그 · 임시 파일 · 출력에 쓰지 않는다.
  창을 닫거나 손대지 않은 채 SpeakSession 의 IDLE_LIMIT_S 가 지나면 지운다 - 지운 뒤에는 답을 되돌릴 수 없다.
- 복사하는 것은 봉인한 토큰 글 한 가지뿐이다. 그 글이 검사를 통과하고, 입력이 바뀌지 않았고 (바뀌면 복사는 곧 꺼지고
  다시 봉인해야 켜진다), 보이지 않는 글자가 없고, 한도 안이고, 데이터 폴더가 기본 자리일 때만 켜진다 (AL-12).
- 되돌린 글에는 진짜 단어가 있다. 창 안에서만 보인다: 복사 단추 없음 · 클립보드에 넣지 않음 · 파일에 쓰지 않음 · 로그 없음
  (되돌린 글 칸은 복사 · 잘라내기 · 선택 내보내기도 막는다). 답에 사전 단어가 있으면 (U2) 되돌린 글을 만들지 않고 경보만 낸다.
- 건너뛰는 길이 없다 (AL-02): 검사를 끄는 옵션 · 환경 변수 · 설정 키가 없다. 읽는 환경 변수는 창을 띄울 화면이 있는지 보는
  DISPLAY · WAYLAND_DISPLAY 둘뿐이다 (E-07 쪽으로만 작용한다). 이 모듈이 파일을 여는 곳은 없다 - 사전 · 설정은
  config.read_words / scan.policy_from_home 이 읽고, 쓰는 파일은 하나도 없다.
- 막은 까닭 · 오류 글에는 단어 · 경로를 쓰지 않는다 - 검사 번호 · 줄 번호 · 개수 · 코드만 (AL-11).
- Enter 로 복사하지 않는다. 화면 문구는 한국어, 색은 works DESIGN.md 의 네이비 · 라임 · 회색뿐이다 - 빨강 없음 (W-10).
"""

import collections
import json
import os
import subprocess
import threading
import time

from . import config, confirm, scan
from . import unseal as unseal_checks
from .seal import PseudonymTable, seal_speech

# ---------------------------------------------------------------- 상수

EXIT_CLOSED, EXIT_FAILED, EXIT_UNAVAILABLE = 0, 1, 3       # 2 (사용법 오류) 는 diode.py 가 낸다
SPEAK_COMMAND = "speak"             # launch_detached 가 diode.py 에 주는 명령 이름
MAX_INPUT_BYTES = 64 * 1024         # 쓴 글 상한 [제안] - 확정 창 요청의 text 한도와 같다 (SP-09)
MAX_SEALED_BYTES = confirm.MAX_TEXT_BYTES       # 복사하는 토큰 글 상한 [제안] - 사전 단어가 토큰보다 짧으면 입력보다 길어질 수 있다
MAX_ANSWER_BYTES = 256 * 1024       # 붙여 넣는 Claude 의 답 상한 [제안]
IDLE_LIMIT_S = 30 * 60              # 손대지 않은 채 이만큼 지나면 가명 표를 지우고 닫는다 [제안]
MAX_LINES_SHOWN = 5                 # 상태 줄에 적는 줄 번호의 수 (나머지는 "외 N곳")
POLL_S = 0.05                       # 화면을 돌보는 간격
SCREEN_MARGIN_PX = 120              # 창 제목줄 · 작업 표시줄 몫 - 창이 이만큼 뺀 화면 높이를 넘으면 글 칸의 줄 수를 줄인다
WRAP_MARGIN_PX = 40                 # 줄을 감는 너비 = 글 칸의 너비 - 이 여백
TOPMOST_MS = 400                    # 처음 뜰 때 맨 앞으로 올린 뒤 이만큼 있다가 맨 앞 고정을 푼다 (붙여 넣으러 다른 창으로 가야 한다)
BOX_WIDTH = 64                      # 글 칸의 너비 (글자 수) - 왼쪽 (나가는 쪽) · 오른쪽 (돌아오는 쪽) 두 칸이 나란히 선다
MIN_BOX_CHARS = 30                  # 화면이 좁아도 글 칸은 이 글자 수 밑으로 줄이지 않는다
SCREEN_SIDE_PX = 40                 # 창 좌우 여백 몫
MIN_BOX_LINES = 3                   # 화면이 작아도 글 칸은 이 줄 수 밑으로 줄이지 않는다
DETACHED_PROCESS = 0x00000008       # Windows CreateProcess 의 플래그 - 다른 OS 의 subprocess 에는 이 이름이 없다
CREATE_NEW_PROCESS_GROUP = 0x00000200

PALETTE = confirm.PALETTE           # works DESIGN.md › 02 - 네이비 · 라임 · 무채색뿐 (빨강 없음)
WindowUnavailable = confirm.WindowUnavailable       # 창을 띄울 수 없다 (E-07) - 확정 창과 같은 예외
WINDOW_TITLE = "Diode - 말 봉인"

# 화면 문구 (한국어 · 이모지 없음 · DESIGN.md › 03 의 기호만). 어느 글에도 사전 단어 · 경로가 들어가지 않는다.
TEXT_SUBTITLE = "사내 말을 가명 토큰으로 바꾼 글만 복사합니다 · 가명 표는 이 창이 열려 있는 동안만 메모리에 있습니다"
TEXT_IDLE = "사내 말로 쓰고 [봉인] 을 누르세요"
TEXT_EMPTY = "쓴 글이 없습니다"
TEXT_TOO_LONG = "쓴 글이 너무 깁니다 (64 KiB 이하) - 나눠서 봉인하세요 (E-04)"
TEXT_BAD_CHARS = "글에 UTF-8 로 바꿀 수 없는 글자가 있습니다 (E-04)"
TEXT_SEALED_OK = "봉인했습니다 - 위 글만 나갑니다. 눈으로 확인한 뒤 [복사] 하세요"
TEXT_SEALED_BLOCKED = "검사에 걸려 복사할 수 없습니다 - 쓴 글을 고치고 다시 [봉인] 하세요"
TEXT_HIDDEN = "‼ 보이지 않는 글자 %d개 - 봉인한 글에 [U+XXXX] 로 드러냈습니다. 지우고 다시 봉인하세요 (복사 안 함)"
TEXT_SEALED_TOO_LONG = "봉인한 글이 너무 깁니다 (64 KiB 이하) - 나눠서 봉인하세요 (E-04)"
TEXT_HOME = "‼ 테스트용 데이터 폴더 (DIODE_HOME) 라 복사하지 않습니다 (E-20)"
TEXT_E20 = "검사 중 오류로 봉인하지 못했습니다 (E-20)"
TEXT_UNAVAILABLE = "사전 · 설정을 읽지 못했거나 사전이 비어 있어 쓸 수 없습니다 (E-20) - /diode:setup"
TEXT_STALE = "쓴 글이 바뀌었습니다 - 다시 [봉인] 하세요"
TEXT_STALE_LINE = "봉인한 뒤 글이 바뀌었습니다"
TEXT_NOT_SEALED = "아직 봉인하지 않았습니다"
TEXT_COPIED = "복사했습니다 - Claude 에 붙여 넣으세요. 답이 오면 아래에 붙여 넣고 [되돌려 보기] 를 누르세요"
TEXT_COPY_FAILED = "클립보드에 넣지 못했습니다 (넣은 글을 되읽어 맞지 않음) - 다시 눌러 보세요"
TEXT_COPY_OFF = "지금은 복사할 수 없습니다 - 먼저 [봉인] 하세요"
TEXT_CLEARED = "비웠습니다 - 가명 표는 그대로입니다 (창을 닫으면 사라집니다)"
TEXT_CLOSE_ASK = "‼ 닫으면 가명 표가 사라져 Claude 의 답을 되돌릴 수 없습니다 - 닫으려면 한 번 더 누르세요"
TEXT_ANSWER_EMPTY = "붙여 넣은 답이 없습니다"
TEXT_ANSWER_TOO_LONG = "붙여 넣은 답이 너무 깁니다 (256 KiB 이하) (E-04)"
TEXT_RESTORED = "되돌렸습니다 - 토큰 %d개 · 이 글은 이 창에서만 보입니다"
TEXT_RESTORED_HEAD = "되돌렸습니다 - 토큰 %d개"
TEXT_RESTORED_NOTES = "되돌렸습니다 - 토큰 %d개 · 확인할 줄이 있습니다 (단추 옆의 안내)"
TEXT_U2 = "‼ 답에 사전 단어가 있습니다 (U2 x%d) - Claude 가 진짜 단어를 맞혔을 수 있어 되돌린 글을 만들지 않습니다"
TEXT_U1 = "모르는 · 깨진 토큰이 있는 줄 %s - 그대로 둠 (U1)"
TEXT_U3 = "바깥 주소가 있는 줄 %s - 지움 (U3)"
TEXT_U4 = "답이 너무 깁니다 (U4)"
TEXT_RESTORED_HINT = "이 창에서만 보입니다"

# 상태 줄의 칩: (글, 바탕, 글자) - 경고 · 오류는 가장 밝은 글자색 + ERR 칩 (DESIGN.md › 02)
_CHIPS = {"": ("SPEAK", "navy2", "white"), "info": ("SPEAK", "navy2", "white"), "ok": ("OK", "lime", "black"),
          "alert": ("ERR", "white", "black"), "ask": ("ASK", "lime3", "black")}
_STATUS_FG = {"": "navy5", "info": "white", "ok": "lime3", "alert": "white", "ask": "lime3"}

# ---------------------------------------------------------------- 보이는 것 (화면과 무관한 내용)

Sealed = collections.namedtuple("Sealed", "text check line ok copyable reason hidden")
Snapshot = collections.namedtuple(
    "Snapshot", "state message level check_line check_kind seal_enabled copy_enabled unseal_enabled clear_enabled tokens remaining_s")


class Unsealed(object):
    """되돌려 본 결과. text 에는 진짜 단어가 있다 - 창이 화면에만 그린다 (repr · 로그에는 넣지 않는다).

    ok      되돌린 글을 만들었나 (U2 · 크기 · 오류면 거짓 - text 는 None)
    stop    U2 (답에 사전 단어) - Claude 가 진짜 단어를 맞혔을 수 있다는 경보
    issues  {"U1": [줄], "U2": 개수, "U3": [줄], "U4": 참거짓} 또는 {"E": "E-20"} - 단어 없음
    summary 사람에게 보이는 한 줄 (번호 · 개수뿐)
    reason  None 또는 empty · size · text · unavailable · e20 · u2 · u4
    """

    __slots__ = ("ok", "text", "stop", "issues", "summary", "reason", "level")

    def __init__(self, ok, text, stop, issues, summary, reason, level):
        self.ok, self.text, self.stop, self.issues = ok, text, stop, issues
        self.summary, self.reason, self.level = summary, reason, level

    def __repr__(self):
        return "<Unsealed ok=%s reason=%s>" % (self.ok, self.reason)

    __str__ = __repr__


def _mmss(seconds):
    return "%02d:%02d" % divmod(max(0, int(seconds)), 60)


def _places(numbers):
    """줄 번호 목록 -> "L2, L5 외 3곳" (번호뿐 - 단어 없음)."""
    shown = ", ".join("L%d" % n for n in numbers[:MAX_LINES_SHOWN])
    more = len(numbers) - MAX_LINES_SHOWN
    return shown + (" 외 %d곳" % more if more > 0 else "")


def _utf8_len(text):
    """UTF-8 바이트 수. 홀로 선 서로게이트처럼 바이트가 될 수 없는 글이면 None."""
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError:
        return None


# ---------------------------------------------------------------- 창의 논리 (화면을 모른다)

class SpeakSession(object):
    """말 봉인 창의 논리. 화면 (TkView 나 시험의 가짜 화면) 이 부른다.

    state   ready (쓸 수 있다) · unavailable (사전 · 설정을 못 읽음 - 봉인 · 되돌리기 모두 거절) · closed · expired (손대지 않아 닫힘)
    가명 표는 self._table 에만 있다 (메모리). 닫히면 (closed · expired) 입력 · 답 · 봉인한 글과 함께 지운다.
    clipboard_put(text) / clipboard_get() 은 화면이 주는 클립보드 접근 - 복사는 넣은 뒤 되읽어 같을 때만 성공이다.
    clock 은 시각 (초) 을 주는 함수 - 기본은 time.monotonic. home_is_default 가 거짓이면 (DIODE_HOME) 복사를 막는다 (AL-12).
    """

    def __init__(self, home, home_is_default=True, clipboard_put=None, clipboard_get=None, clock=None):
        self._put = clipboard_put
        self._get = clipboard_get
        self._clock = clock or time.monotonic
        self._home_ok = bool(home_is_default)
        self._table = PseudonymTable()
        self._policy = None
        self._words = ()
        self._state = "ready"
        self.code = ""                      # unavailable 일 때 까닭 코드: words_empty · broken · newer
        self._input = ""
        self._answer = ""
        self._sealed = None                 # 마지막 [봉인] 의 결과 (Sealed)
        self._sealed_source = None          # 그 봉인이 본 쓴 글 - 지금 쓴 글과 같을 때만 복사할 수 있다
        self._message, self._level = TEXT_IDLE, ""
        self._close_asked = False
        self._touched = self._clock()
        self.seals = 0
        self.copies = 0
        self.unseals = 0
        self._load(home)

    def __repr__(self):
        return "<SpeakSession %s 토큰 %d개>" % (self._state, len(self._table))

    __str__ = __repr__

    def __reduce_ex__(self, protocol):
        raise TypeError("말 봉인 창의 상태는 직렬화하지 않는다")

    def __copy__(self):
        raise TypeError("말 봉인 창의 상태는 복사하지 않는다")

    def __deepcopy__(self, memo):
        raise TypeError("말 봉인 창의 상태는 복사하지 않는다")

    def _load(self, home):
        """데이터 폴더의 사전 · 정책을 한 번 읽는다. 못 읽거나 사전이 비면 unavailable (E-20)."""
        try:
            words = config.read_words(home)
        except config.ConfigError as e:
            return self._fail("newer" if e.code == "newer" else "broken")
        except Exception:
            return self._fail("broken")
        if not words:
            return self._fail("words_empty")
        try:
            policy = scan.policy_from_home(home)
            if scan.Policy(words=words).word_keys != policy.word_keys:       # 두 번 읽는 사이에 사전이 바뀌었다 - 믿지 않는다
                return self._fail("broken")
        except Exception:
            return self._fail("broken")
        self._policy = policy
        self._words = tuple(words)

    def _fail(self, code):
        self._state = "unavailable"
        self.code = code
        self._message, self._level = TEXT_UNAVAILABLE, "alert"

    # -- 상태

    @property
    def state(self):
        return self._state

    @property
    def closed(self):
        return self._state in ("closed", "expired")

    @property
    def expired(self):
        return self._state == "expired"

    @property
    def tokens(self):
        return len(self._table)

    @property
    def sealed(self):
        return self._sealed

    def _ready(self):
        return self._state == "ready"

    def _say(self, message, level=""):
        self._message, self._level = message, level

    def _touch(self):
        self._touched = self._clock()
        self._close_asked = False

    def start(self, now=None):
        """창이 화면에 뜬 때 (손대지 않은 시간은 여기서부터 센다)."""
        self._touched = self._clock()

    def touch(self):
        """창을 만졌다 (글쇠 · 마우스) - 손대지 않은 시간을 다시 센다."""
        if self._ready():
            self._touched = self._clock()

    def tick(self, now=None):
        """손대지 않은 채 IDLE_LIMIT_S 가 지났으면 가명 표를 지우고 닫는다."""
        if self._ready() and self._clock() - self._touched >= IDLE_LIMIT_S:
            self._wipe("expired")

    def _wipe(self, state):
        """가명 표 · 입력 · 답 · 봉인한 글을 지운다 (닫을 때 · 시간이 다 됐을 때)."""
        self._table = PseudonymTable()
        self._policy = None
        self._words = ()
        self._input = self._answer = ""
        self._sealed = self._sealed_source = None
        self._state = state
        self._message, self._level = "", ""

    # -- 쓰기

    def set_input(self, text):
        """화면의 쓰는 칸의 글을 알린다. 봉인한 글과 달라지면 복사는 곧 꺼진다 (다시 봉인해야 켜진다)."""
        if not self._ready() or not isinstance(text, str):
            return
        text = text.replace("\r\n", "\n")
        if text == self._input:
            return
        self._input = text
        self._touch()
        if self._sealed is not None and text != self._sealed_source:
            self._say(TEXT_STALE, "info")

    def set_answer(self, text):
        """화면의 답 칸의 글을 알린다."""
        if not self._ready() or not isinstance(text, str):
            return
        if text != self._answer:
            self._answer = text
            self._touch()

    def hidden_lines(self):
        """쓴 글에서 보이지 않는 글자가 든 줄 번호 (화면이 표시한다)."""
        return [no for no, line in enumerate(self._input.split("\n"), 1)
                if any(confirm.is_hidden_char(ch) for ch in line)]

    # -- 봉인

    def _sealed_refused(self, reason, message, level="alert"):
        self._sealed = self._sealed_source = None
        self._say(message, level)
        return Sealed(None, None, "", False, False, reason, 0)

    def seal(self):
        """쓴 글을 봉인한다 - 사전 단어를 토큰으로 바꾸고 D2 · D3 · D4 · D6 으로 다시 본다 -> Sealed.

        copyable 은 검사를 통과하고 · 보이지 않는 글자 없고 · 한도 안이고 · 데이터 폴더가 기본 자리일 때만 참이다.
        돌려주는 글은 창에만 보이고, 사람이 [복사] 할 때만 밖으로 간다 (D8). 걸린 검사는 번호 · 줄 · 개수로만 알린다.
        """
        if not self._ready():
            return Sealed(None, None, "", False, False, "unavailable", 0)
        self._touch()
        text = self._input
        if not text.strip():
            return self._sealed_refused("empty", TEXT_EMPTY, "info")
        size = _utf8_len(text)
        if size is None:
            return self._sealed_refused("text", TEXT_BAD_CHARS)
        if size > MAX_INPUT_BYTES:
            return self._sealed_refused("size_in", TEXT_TOO_LONG)
        res = seal_speech(text, self._table, self._policy, self._words)
        out, check = res.get("text"), res.get("check")
        if not isinstance(out, str) or not isinstance(check, dict):
            return self._sealed_refused("e20", TEXT_E20)
        self.seals += 1
        ok = check.get("ok") is True
        hidden = sum(1 for ch in out if confirm.is_hidden_char(ch))
        out_size = _utf8_len(out)
        line = scan.format_line(check)
        if not ok:
            reason, message, level = "check", TEXT_SEALED_BLOCKED, "alert"
        elif hidden:
            reason, message, level = "hidden", TEXT_HIDDEN % hidden, "alert"
        elif out_size is None or out_size > MAX_SEALED_BYTES:
            reason, message, level = "size_out", TEXT_SEALED_TOO_LONG, "alert"
        elif not self._home_ok:
            reason, message, level = "home", TEXT_HOME, "alert"
        else:
            reason, message, level = None, TEXT_SEALED_OK, "ok"
        self._sealed = Sealed(out, check, line, ok, reason is None, reason, hidden)
        self._sealed_source = text
        self._say(message, level)
        return self._sealed

    @property
    def copy_enabled(self):
        """[복사] 가 켜지는 때: 봉인한 글이 복사해도 되고, 봉인한 뒤 쓴 글이 바뀌지 않았다."""
        return (self._ready() and self._sealed is not None and self._sealed.copyable
                and self._sealed_source == self._input)

    def copy(self):
        """봉인한 토큰 글 그대로 클립보드에 넣고 되읽어 같을 때만 성공 (True). 아니면 False - 실패라고 알린다.

        이 글이 이 창에서 클립보드로 가는 유일한 길이다 (되돌린 글은 여기로 오지 않는다).
        """
        if not self.copy_enabled:
            if self._ready():
                if self._sealed is None:
                    self._say(TEXT_COPY_OFF, "info")
                elif self._sealed_source != self._input:
                    self._say(TEXT_STALE, "info")           # 그 밖의 까닭 (검사 · 보이지 않는 글자 · 한도) 은 봉인할 때 알린 그대로다
            return False
        self._touch()
        shown = self._sealed.text
        try:
            if self._put is None or self._get is None:
                raise RuntimeError("클립보드 없음")
            self._put(shown)
            back = self._get()
            if not isinstance(back, str) or back.replace("\r\n", "\n") != shown.replace("\r\n", "\n"):
                raise ValueError("클립보드에 들어간 글이 다름")
        except Exception:
            self._say(TEXT_COPY_FAILED, "alert")
            return False
        self.copies += 1
        self._say(TEXT_COPIED, "ok")
        return True

    def clear(self):
        """쓴 글 · 봉인한 글 · 답 · 되돌린 글을 비운다. 가명 표는 그대로다 (같은 단어는 같은 토큰으로 이어진다)."""
        if not self._ready():
            return
        self._touch()
        self._input = self._answer = ""
        self._sealed = self._sealed_source = None
        self._say(TEXT_CLEARED, "info")

    # -- 되돌리기

    def _unsealed_refused(self, reason, message, level="alert", issues=None, stop=False):
        self._say(message, level)
        return Unsealed(False, None, stop, issues or {}, message, reason, level)

    def unseal(self):
        """붙여 넣은 Claude 의 답을 U1 - U4 로 보고 아는 토큰만 진짜 말로 되돌린다 -> Unsealed.

        돌려주는 text 에는 진짜 단어가 있다. 창이 화면에만 그리고 어디에도 보내지 않는다 (클립보드 · 파일 · 로그 없음).
        답에 사전 단어가 있으면 (U2) 되돌린 글을 만들지 않는다. 모르는 토큰 · 깨진 토큰은 줄 번호만 알린다.
        """
        if not self._ready():
            return Unsealed(False, None, False, {}, "", "unavailable", "alert")
        self._touch()
        answer = self._answer
        if not answer.strip():
            return self._unsealed_refused("empty", TEXT_ANSWER_EMPTY, "info")
        size = _utf8_len(answer)
        if size is None:
            return self._unsealed_refused("text", TEXT_BAD_CHARS)
        if size > MAX_ANSWER_BYTES:
            return self._unsealed_refused("size", TEXT_ANSWER_TOO_LONG)
        res = unseal_checks.unseal(answer, self._table, self._policy, "plan", md_limit=MAX_ANSWER_BYTES)
        issues = res.get("issues") or {}
        if "E" in issues:
            return self._unsealed_refused("e20", TEXT_E20)
        self.unseals += 1
        u1, u2, u3, u4 = issues.get("U1", []), issues.get("U2", 0), issues.get("U3", []), issues.get("U4", False)
        if u2:
            return self._unsealed_refused("u2", TEXT_U2 % u2, issues=issues, stop=True)
        if u4 or not res.get("ok") or not isinstance(res.get("text"), str):
            return self._unsealed_refused("u4", TEXT_U4, issues=issues)
        notes = []
        if u1:
            notes.append(TEXT_U1 % _places(u1))
        if u3:
            notes.append(TEXT_U3 % _places(u3))
        restored = sum(1 for t in scan.find_tokens(answer) if t in self._table)
        summary = " · ".join([TEXT_RESTORED_HEAD % restored] + notes)      # 단추 옆의 안내 (번호 · 개수뿐)
        level = "info" if notes else "ok"
        self._say((TEXT_RESTORED_NOTES if notes else TEXT_RESTORED) % restored, level)     # 상태 줄은 짧게
        return Unsealed(True, res["text"], False, issues, summary, None, level)

    # -- 닫기

    def request_close(self):
        """닫는다. 가명 표에 토큰이 있으면 한 번 묻는다 (닫으면 답을 되돌릴 수 없다). 닫혔으면 True."""
        if self.closed:
            return True
        if self._ready() and len(self._table) and not self._close_asked:
            self._close_asked = True
            self._say(TEXT_CLOSE_ASK, "ask")
            return False
        self._wipe("closed")
        return True

    def key(self, name, now=None):
        """글쇠. Esc = 닫기 · Enter 를 비롯한 나머지는 아무 일도 하지 않는다 (Enter 로 복사하지 않는다)."""
        if name == "Escape":
            return self.request_close()
        return False

    def snapshot(self, now=None):
        """화면이 단추 · 상태 줄을 그릴 때 보는 값 (바뀐 때만 다시 그리게 비교할 수 있다)."""
        ready = self._ready()
        s = self._sealed
        if s is None:
            kind, line = "none", TEXT_NOT_SEALED
        elif self._sealed_source != self._input:
            kind, line = "stale", TEXT_STALE_LINE
        elif s.line and not s.ok:
            kind, line = "block", s.line
        else:
            kind, line = "pass", s.line
        remaining = max(0.0, IDLE_LIMIT_S - (self._clock() - self._touched)) if ready else 0.0
        return Snapshot(
            state=self._state, message=self._message, level=self._level, check_line=line, check_kind=kind,
            seal_enabled=ready and bool(self._input.strip()), copy_enabled=self.copy_enabled,
            unseal_enabled=ready and bool(self._answer.strip()),
            clear_enabled=ready and bool(self._input or self._answer or self._sealed is not None),
            tokens=len(self._table), remaining_s=int(remaining + 0.999))


# ---------------------------------------------------------------- 화면 (tkinter)

# 칸 이름 (widgets 의 열쇠)
BOXES = ("input", "sealed", "answer", "restored")


class TkView(confirm.TkView):
    """tkinter 화면 백엔드 - 그리기만 한다. 누른 것은 session 에 알리고 상태는 session 이 정한다.

    확정 창의 글꼴 · 칩 · 단추 부품 (confirm.TkView) 을 이어받는다. run(session) 이 보통의 길이다.
    시험은 open / pump / close 를 따로 불러 위젯을 눌러 본다 (widgets).
    """

    def __init__(self, tk_module, clock=None):
        confirm.TkView.__init__(self, tk_module, clock)
        self._pushing = False
        self._jobs = []

    def run(self, session):
        self.open(session)
        try:
            while not session.closed:
                self.pump()
                time.sleep(POLL_S)
        finally:
            self.close()

    def pump(self):
        """한 바퀴: 눌림을 처리하고 시간을 흘리고 단추 · 상태 줄을 그린다."""
        self._root.update()
        if self._error is not None:
            raise self._error
        s = self._session
        s.tick()
        if not s.closed:
            self._render(s.snapshot())

    def close(self):
        root = self._root
        if root is not None:
            for job in self._jobs:                  # 남은 예약을 거둔다 (창이 없어진 뒤에 돌아 "invalid command name" 이 뜨지 않게)
                try:
                    root.after_cancel(job)
                except self._tk.TclError:
                    pass
            self._jobs = []
        confirm.TkView.close(self)

    def _after(self, ms, func):
        job = self._root.after(ms, func)
        self._jobs.append(job)
        return job

    # -- 클립보드 (세션이 부른다 - 봉인한 글을 복사할 때만)

    def clip_put(self, text):
        root = self._root
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

    def clip_get(self):
        return self._root.clipboard_get()

    # -- 눌림

    def _push(self):
        """칸의 글을 session 에 알린다 (단추를 누르기 직전 - 이벤트가 아직 안 온 글도 놓치지 않게)."""
        s, w = self._session, self.widgets
        s.set_input(w["input"].get("1.0", "end-1c"))
        s.set_answer(w["answer"].get("1.0", "end-1c"))

    def _on_modified(self, key):
        """쓰는 칸 · 답 칸의 글이 바뀜 (<<Modified>>)."""
        text = self.widgets[key]
        if self._pushing or not text.edit_modified():
            return
        text.edit_modified(False)
        if key == "input":
            self._session.set_input(text.get("1.0", "end-1c"))
            text.tag_remove("hidden", "1.0", "end")         # 지난 봉인의 표시는 글이 바뀌면 낡았다
        else:
            self._session.set_answer(text.get("1.0", "end-1c"))
        if not self._session.closed:
            self._render(self._session.snapshot())          # 복사는 글이 바뀐 즉시 꺼진다

    def _on_touch(self, event):
        s = self._session
        if s is not None:
            s.touch()

    def _on_seal(self):
        self._push()
        res = self._session.seal()
        self._show(self.widgets["sealed"], res.text)
        self._mark_hidden()
        self._render(self._session.snapshot())

    def _on_copy(self):
        self._push()
        self._session.copy()
        self._render(self._session.snapshot())

    def _on_clear(self):
        self._push()
        self._session.clear()
        self._pushing = True
        try:
            for key in ("input", "answer"):
                text = self.widgets[key]
                text.delete("1.0", "end")
                text.edit_modified(False)
                text.edit_reset()
        finally:
            self._pushing = False
        self._show(self.widgets["sealed"], None)
        self._show(self.widgets["restored"], None)
        self.widgets["unseal_note"].configure(text="")
        self._mark_hidden()
        self._render(self._session.snapshot())

    def _on_unseal(self):
        self._push()
        res = self._session.unseal()
        self._show(self.widgets["restored"], res.text)
        self.widgets["unseal_note"].configure(text=res.summary)
        self._render(self._session.snapshot())

    def _on_close(self):
        if self._root is None:
            return
        self._push()
        self._session.request_close()
        if not self._session.closed:
            self._render(self._session.snapshot())

    def _on_escape(self, event):
        self._push()
        self._session.key("Escape")
        if not self._session.closed:
            self._render(self._session.snapshot())
        return "break"

    def _on_enter(self, event):
        self._session.key("Return")
        return "break"

    def _no_copy(self, event):
        """되돌린 글 칸은 복사 · 잘라내기를 막는다 - 진짜 단어가 든 글은 이 창 밖으로 나가지 않는다."""
        return "break"

    def _copy_sealed(self, event):
        """봉인한 글 칸의 선택 복사는 [복사] 가 켜진 글일 때만 (검사에 걸린 글이 이 길로 새지 않게)."""
        return None if self._session.copy_enabled else "break"

    def _focus_next(self, event):
        event.widget.tk_focusNext().focus_set()
        return "break"

    def _focus_prev(self, event):
        event.widget.tk_focusPrev().focus_set()
        return "break"

    # -- 보이기

    def _show(self, text, content):
        """읽기 전용 글 칸에 글을 그린다 (토큰은 라임 · 보이지 않는 글자는 [U+XXXX] 로 드러냄 - 확정 창과 같다). None 이면 비운다."""
        text.configure(state="normal")
        text.delete("1.0", "end")
        if content:
            for piece, form in confirm.display_segments(content):
                if form:
                    text.insert("end", piece, form)
                else:
                    text.insert("end", piece)
        text.configure(state="disabled")
        text.yview_moveto(0.0)

    def _mark_hidden(self):
        """쓴 글에서 보이지 않는 글자가 든 줄을 표시한다."""
        text = self.widgets["input"]
        text.tag_remove("hidden", "1.0", "end")
        for n in self._session.hidden_lines():
            text.tag_add("hidden", "%d.0" % n, "%d.end" % n)

    # -- 짓기

    def _text_box(self, parent, key, height, editable):
        """글 칸 (세로 줄 포함). editable 이 아니면 읽기 전용이다 (state=disabled)."""
        tk = self._tk
        c = PALETTE
        frame = tk.Frame(parent, bg=c["black"])
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        options = {}
        if editable:
            options.update(insertbackground=c["lime"], insertwidth=2, undo=True, maxundo=200)
        else:
            options.update(insertwidth=0)
        if key == "restored":
            options["exportselection"] = False          # 선택해도 X11 의 선택 영역(PRIMARY)으로 내보내지 않는다
        text = tk.Text(frame, wrap="word", width=BOX_WIDTH, height=height, font=self._fonts["body"], bg=c["black"], fg=c["gray4"],
                       relief="flat", bd=0, padx=10, pady=8, highlightthickness=1, highlightbackground=c["navy3"],
                       highlightcolor=c["lime"], selectbackground=c["navy3"], selectforeground=c["white"], takefocus=1,
                       **options)
        text.grid(row=0, column=0, sticky="nsew")
        scroll = tk.Scrollbar(frame, orient="vertical", command=text.yview, bg=c["navy2"], troughcolor=c["black"],
                              activebackground=c["navy3"], relief="flat", bd=0)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("token", background=c["lime"], foreground=c["black"])
        text.tag_configure("hidden", background=c["white"], foreground=c["navy"])
        text.bind("<Tab>", self._focus_next)
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):          # 키 이름이 없는 곳 (Windows) 에서는 건너뛴다
            try:
                text.bind(sequence, self._focus_prev)
            except self._tk.TclError:
                pass
        if editable:
            text.bind("<<Modified>>", lambda event, k=key: self._on_modified(k))
        else:
            text.configure(state="disabled")
        self.widgets[key] = text
        return frame

    def _bar(self, parent, chip, title, note="", extra=None):
        """구역 이름줄 (칩 = 번호 + 영문 이름 · 한국어 이름 · 작은 설명 · 오른쪽 끝에 extra 가 단추를 붙인다)."""
        tk = self._tk
        c = PALETTE
        bar = tk.Frame(parent, bg=c["black"])
        self._chip(bar, chip).pack(side="left")
        tk.Label(bar, text=title, font=self._fonts["strong"], bg=c["black"], fg=c["white"]).pack(side="left", padx=8)
        if note:
            tk.Label(bar, text=note, font=self._fonts["small"], bg=c["black"], fg=c["gray2"]).pack(side="left")
        if extra is not None:
            extra(bar)
        return bar

    def _wide_label(self, parent, text, font, bg, fg, side=0, **options):
        """창 전체 너비에서 줄을 감는 라벨 (머리말 · 상태 줄). 칸 하나의 너비에서 감는 것은 _label 이다."""
        label = self._label(parent, text, font, bg, fg, side, **options)
        self._wide.append(label)
        return label

    def _build(self):
        tk = self._tk
        root = self._root
        session = self._session
        c = PALETTE
        w = self.widgets
        self._wide = []

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
        root.bind("<Escape>", self._on_escape)
        for sequence in ("<Key>", "<Button>", "<Motion>", "<MouseWheel>"):      # 창을 만지고 있으면 시간이 다 되지 않는다
            root.bind_all(sequence, self._on_touch, add="+")

        # 00 - 맨 위 큰 글자
        head = tk.Frame(root, bg=c["navy"], padx=16, pady=12)
        head.grid(row=0, column=0, sticky="ew")
        self._chip(head, "SPEAK", c["navy3"], c["white"]).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 16))
        w["title"] = tk.Label(head, text="말 봉인", font=self._fonts["title"], bg=c["navy"], fg=c["white"], anchor="w")
        w["title"].grid(row=0, column=1, sticky="w")
        w["subtitle"] = self._wide_label(head, TEXT_SUBTITLE, "small", c["navy"], c["navy5"], side=100)
        w["subtitle"].grid(row=1, column=1, sticky="w")

        # 본문 - 왼쪽은 나가는 쪽 (쓰기 -> 봉인 -> 복사) · 오른쪽은 돌아오는 쪽 (답 -> 되돌려 보기)
        zone = tk.Frame(root, bg=c["black"], padx=16, pady=8)
        zone.grid(row=1, column=0, sticky="nsew")
        zone.rowconfigure(0, weight=1)
        left = tk.Frame(zone, bg=c["black"])
        right = tk.Frame(zone, bg=c["black"])
        for column, side, pad in ((left, 0, (0, 8)), (right, 1, (8, 0))):
            zone.columnconfigure(side, weight=1, uniform="cols")
            column.grid(row=0, column=side, sticky="nsew", padx=pad)
            column.columnconfigure(0, weight=1)

        # 01 쓰기 · 02 봉인한 글 · 03 검사 · 단추
        self._bar(left, "01 WRITE", "사내 말로 쓰기", "이 창에서만 보입니다").grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._text_box(left, "input", 8, True).grid(row=1, column=0, sticky="nsew")
        self._bar(left, "02 SEALED", "봉인한 글 (이 글만 나갑니다)").grid(row=2, column=0, sticky="ew", pady=(8, 4))
        self._text_box(left, "sealed", 8, False).grid(row=3, column=0, sticky="nsew")
        w["sealed"].bind("<<Copy>>", self._copy_sealed)
        w["sealed"].bind("<<Cut>>", self._no_copy)
        spec = tk.Frame(left, bg=c["black"])
        spec.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        spec.columnconfigure(1, weight=1)
        self._chip(spec, "03 CHECK").grid(row=0, column=0, sticky="w")
        cell = tk.Frame(spec, bg=c["navy1"])
        cell.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        w["check"] = self._label(cell, TEXT_NOT_SEALED, "body", c["navy1"], c["white"], side=170, padx=8)
        w["check"].pack(side="left")
        w["check_chip"] = self._chip(cell, "V<Vth", c["white"], c["black"])           # 문턱을 못 넘음 (걸렸을 때만 보인다)
        buttons = tk.Frame(left, bg=c["black"])
        buttons.grid(row=5, column=0, sticky="w", pady=(8, 0))
        w["seal"] = self._button(buttons, "봉인", self._on_seal)
        w["copy"] = self._button(buttons, "복사", self._on_copy)
        w["clear"] = self._button(buttons, "비우기", self._on_clear)
        for i, key in enumerate(("seal", "copy", "clear")):
            w[key].grid(row=0, column=i, padx=(0, 8))

        # 04 Claude 의 답 · 05 되돌린 글
        def unseal_button(bar):
            w["unseal"] = self._button(bar, "되돌려 보기", self._on_unseal)
            w["unseal"].pack(side="right")
        self._bar(right, "04 ANSWER", "Claude 의 답 붙여 넣기", extra=unseal_button).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._text_box(right, "answer", 6, True).grid(row=1, column=0, sticky="nsew")
        w["unseal_note"] = self._label(right, "", "small", c["black"], c["gray4"], side=0, height=3)
        w["unseal_note"].grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._bar(right, "05 RESTORED", "되돌린 글", TEXT_RESTORED_HINT).grid(row=3, column=0, sticky="ew", pady=(8, 4))
        self._text_box(right, "restored", 10, False).grid(row=4, column=0, sticky="nsew")
        for key in ("<<Copy>>", "<<Cut>>"):
            w["restored"].bind(key, self._no_copy)
        for column, rows in ((left, (1, 3)), (right, (1, 4))):
            for row in rows:
                column.rowconfigure(row, weight=1)

        # 아래 줄 - 상태 한 줄 · 닫기
        foot = tk.Frame(root, bg=c["navy"], padx=16, pady=10)
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(1, weight=1)
        w["status_chip"] = self._chip(foot, "SPEAK")
        w["status_chip"].grid(row=0, column=0, sticky="nw", padx=(0, 12))
        w["status"] = self._wide_label(foot, "", "small", c["navy"], c["white"], side=100, height=2)
        w["status"].grid(row=0, column=1, columnspan=2, sticky="w")
        w["close"] = self._button(foot, "닫기", self._on_close)
        w["close"].grid(row=1, column=0, pady=(10, 0), padx=(0, 8))
        w["tokens"] = tk.Label(foot, text="", font=self._fonts["small"], bg=c["navy"], fg=c["navy5"], anchor="w")
        w["tokens"].grid(row=1, column=1, sticky="w", pady=(10, 0))
        w["time"] = tk.Label(foot, text="", font=self._fonts["small"], bg=c["navy"], fg=c["lime3"], anchor="e")
        w["time"].grid(row=1, column=2, sticky="e", pady=(10, 0))
        for key in ("seal", "copy", "clear", "unseal", "close"):
            for sequence in ("<Return>", "<KP_Enter>"):
                w[key].bind(sequence, self._on_enter)           # Enter 로는 어떤 단추도 눌리지 않는다
        self._render(session.snapshot())

        # 화면에 앉히기 - 가운데 위 · 맨 앞 (잠깐) · 처음 초점은 쓰는 칸
        root.update_idletasks()
        self._fit_width(root.winfo_screenwidth() - SCREEN_SIDE_PX)
        column_width, full_width = w["input"].winfo_reqwidth(), root.winfo_reqwidth()
        for label, side in self._wrapped:
            label.configure(wraplength=max(240, (full_width if label in self._wide else column_width) - WRAP_MARGIN_PX - side))
        self._fit_height(root.winfo_screenheight() - SCREEN_MARGIN_PX)
        root.minsize(min(root.winfo_reqwidth(), 720), root.winfo_reqheight() // 2)
        x = max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2)
        y = max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 3)
        root.geometry("+%d+%d" % (x, y))
        try:
            root.attributes("-topmost", True)
            self._after(TOPMOST_MS, self._release_topmost)
        except tk.TclError:
            pass
        root.lift()
        try:
            w["input"].focus_force()
        except tk.TclError:
            w["input"].focus_set()

    def _release_topmost(self):
        if self._root is not None:
            try:
                self._root.attributes("-topmost", False)
            except self._tk.TclError:
                pass

    def _fit_width(self, limit):
        """창이 limit 픽셀보다 넓으면 글 칸의 너비 (글자 수) 를 줄여 화면 안에 들게 한다 (창을 끌어서 다시 넓힐 수 있다)."""
        root = self._root
        boxes = [self.widgets[k] for k in BOXES]
        root.update_idletasks()
        while root.winfo_reqwidth() > limit:
            chars = int(boxes[0].cget("width"))
            if chars <= MIN_BOX_CHARS:
                break
            for box in boxes:
                box.configure(width=chars - 2)
            root.update_idletasks()

    def _fit_height(self, limit):
        """창이 limit 픽셀보다 크면 글 칸의 줄 수를 (가장 큰 칸부터) 줄여 단추가 화면 안에 들게 한다 (창을 끌어서 다시 키울 수 있다)."""
        root = self._root
        boxes = [self.widgets[k] for k in BOXES]
        root.update_idletasks()
        while root.winfo_reqheight() > limit:
            tallest = max(boxes, key=lambda box: int(box.cget("height")))
            lines = int(tallest.cget("height"))
            if lines <= MIN_BOX_LINES:
                break
            tallest.configure(height=lines - 1)
            root.update_idletasks()

    def _render(self, snap):
        """단추 · 검사 줄 · 상태 줄을 snap 대로 맞춘다 (바뀐 때만)."""
        if snap == self._last:
            return
        self._last = snap
        w = self.widgets
        c = PALETTE
        self._style(w["seal"], snap.seal_enabled, "봉인", accent=True)
        self._style(w["copy"], snap.copy_enabled, "복사", accent=True)
        self._style(w["clear"], snap.clear_enabled, "비우기")
        self._style(w["unseal"], snap.unseal_enabled, "되돌려 보기", accent=True)
        self._style(w["close"], True, "닫기")
        fg = {"pass": c["lime3"], "none": c["gray2"]}.get(snap.check_kind, c["white"])
        w["check"].configure(text=snap.check_line, fg=fg)
        if snap.check_kind == "block":
            w["check_chip"].pack(side="left", padx=4)
        else:
            w["check_chip"].pack_forget()
        chip, chip_bg, chip_fg = _CHIPS[snap.level]
        w["status_chip"].configure(text=" %s " % chip, bg=c[chip_bg], fg=c[chip_fg])
        strong = snap.level in ("alert", "ask")
        w["status"].configure(text=snap.message, fg=c[_STATUS_FG[snap.level]], font=self._fonts["strong" if strong else "small"])
        w["tokens"].configure(text="가명 표 %d개 (메모리에만)" % snap.tokens)
        w["time"].configure(text="손대지 않으면 %s 뒤 닫힘" % _mmss(snap.remaining_s))


# ---------------------------------------------------------------- 창 띄우기 (E-07)

def _is_windows():
    return os.name == "nt"


def create_view():
    """화면 백엔드를 만든다. 시험은 이 이름을 바꿔 끼워 가짜 화면으로 논리를 본다 (AL-02: 건너뛰는 길은 따로 없다)."""
    if confirm.display_missing(os.environ, _is_windows()):
        raise WindowUnavailable("display")
    try:
        import tkinter
        import tkinter.font  # noqa: F401  - TkView 가 쓴다
    except ImportError:
        raise WindowUnavailable("tkinter")
    return TkView(tkinter)


def can_open():
    """이 프로세스가 말 봉인 창을 띄울 수 있나 (화면 · tkinter) - 따로 떼어 띄우면 부른 쪽이 실패를 모르므로 띄우기 전에 본다.

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
    """말 봉인 창을 따로 떼어 띄운다 - 부른 쪽을 기다리게 하지 않는다 (결과 줄은 버려진다).

    명령은 [python, diode_py, "speak"] 뿐이다. Windows 는 DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (콘솔도 부모의
    Ctrl+C 도 이어받지 않는다) · 그 밖은 새 세션 (start_new_session). 표준 입출력은 모두 버린다. 새 프로세스의 pid 를 돌려주고,
    띄우지 못하면 OSError 가 그대로 올라간다. 끝난 창은 따로 거둔다 (policy_window 와 같다 - 좀비를 남기지 않는다)."""
    argv = [python, diode_py, SPEAK_COMMAND]
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


# ---------------------------------------------------------------- diode.py speak 의 몸통

def _result_line(obj):
    return json.dumps(obj)


def main_speak(home, home_is_default=True):
    """데이터 폴더 (home) 의 사전으로 말 봉인 창을 띄우고 닫힐 때까지 기다린다 -> (종료 코드, 표준 출력 한 줄).

    사전 · 설정을 읽지 못하거나 사전이 비면 창을 열지 않는다 (종료 코드 3 · E-20). 출력에는 단어 · 글 · 경로가 없다
    (코드 · 개수 · 참거짓뿐). 어떤 예외도 닫았다는 줄로 끝나지 않는다.
    """
    try:
        view = create_view()
        session = SpeakSession(home, home_is_default=home_is_default, clipboard_put=view.clip_put,
                               clipboard_get=view.clip_get)
        if session.state != "ready":
            return EXIT_UNAVAILABLE, _result_line({"closed": False, "error": "E-20", "code": session.code})
        view.run(session)
        if not session.closed:                  # 사람이 닫기 전에 끝난 화면 - 정상이 아니다
            return EXIT_FAILED, _result_line({"closed": False, "error": "E-20"})
        return EXIT_CLOSED, _result_line({"closed": True, "expired": session.expired, "seals": session.seals,
                                          "copies": session.copies, "unseals": session.unseals})
    except WindowUnavailable:
        return EXIT_FAILED, _result_line({"closed": False, "error": "E-07"})
    except (Exception, KeyboardInterrupt):
        return EXIT_FAILED, _result_line({"closed": False, "error": "E-20"})


TEXT_NO_WINDOW = ("말 봉인 창을 띄울 수 없습니다 (E-07) - 화면이 없거나 이 파이썬에 tkinter 가 없습니다. "
                  "사내 말은 이 창에서만 쓰므로 화면이 있는 PC 에서 여세요")
TEXT_NOT_READY = {
    "words_empty": "말 봉인을 쓸 수 없습니다 (E-20) - 사전이 비어 있습니다. /diode:dict 로 사전을 채운 뒤 다시 여세요",
    "newer": "말 봉인을 쓸 수 없습니다 (E-20) - 사전 · 설정이 더 새 형식입니다. Diode 를 올린 뒤 다시 여세요",
    "broken": "말 봉인을 쓸 수 없습니다 (E-20) - 사전 · 설정을 읽지 못했습니다. /diode:setup 으로 점검하세요",
}
TEXT_LAUNCH_FAILED = "말 봉인 창을 띄우지 못했습니다 (E-20)"
TEXT_OPENED = ("말 봉인 창을 열었습니다 - 창에서 사내 말로 쓰고 [봉인] -> 봉인한 글을 눈으로 확인 -> [복사] 한 뒤 Claude 에 붙여 넣으세요 "
               "(사내 말은 이 대화에 치지 않습니다). 창을 닫으면 가명 표가 사라져 답을 되돌릴 수 없습니다")


def open_detached(home, python, diode_py):
    """창을 따로 떼어 열고 바로 돌아온다 (/diode:speak) -> (종료 코드, 표준 출력 글, 표준 오류 글).

    띄우기 전에 화면 · tkinter 를 보고 (못 띄우면 E-07) 사전 · 설정을 읽어 보고 (못 읽으면 E-20 · 종료 코드 3) 띄우지 못하면
    OSError 를 E-20 으로 알린다 - 열었다고 거짓말하지 않는다. 글에 단어 · 경로가 없다.
    """
    if not can_open():
        return EXIT_FAILED, "", TEXT_NO_WINDOW
    probe = SpeakSession(home)
    if probe.state != "ready":
        return EXIT_UNAVAILABLE, "", TEXT_NOT_READY.get(probe.code, TEXT_NOT_READY["broken"])
    try:
        launch_detached(python, diode_py)
    except OSError:
        return EXIT_FAILED, "", TEXT_LAUNCH_FAILED
    return EXIT_CLOSED, TEXT_OPENED, ""
