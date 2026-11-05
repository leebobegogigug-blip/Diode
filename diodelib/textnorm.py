# -*- coding: utf-8 -*-
"""글 손질 두 가지 (표준 라이브러리 · Python 3.8).

prepare(s)  펼친 글에 넣기 전의 손질 (SP-03). NFKC 로 바꾸고 문장 부호 표로 바꾼다.
            검사 D1–D6 은 손질한 글을 본다 — 실제로 나가는 바이트와 같은 글이다.
dict_key(s) 사전 비교용 정규화 N(s) (SP-05 D2). 글자와 숫자만 남긴다.
            NFKD → 결합 부호 지움 → NFKC → casefold → 닮은 글자 접기 → 글자 · 숫자 밖은 지움.

이 모듈은 단어를 출력하지 않는다. 돌려준 글을 찍을지는 부르는 쪽의 책임이다 (AL-11).
"""

import unicodedata

# NFKC 뒤에 바꾸는 글자 (SP-03 표). 글머리 기호는 따로 (BULLETS).
PUNCT_MAP = {
    "…": "...",                       # …  (NFKC 가 이미 ... 로 바꾸지만 두 겹으로)
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "「": '"', "」": '"', "『": '"', "』": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "→": "->", "⇒": "->", "⟶": "->", "➔": "->", "➜": "->",
    "←": "<-", "⇐": "<-", "⟵": "<-",
    "↔": "<->", "⇔": "<->",
    "×": "x",
    "※": "*",
    "〜": "~",
}

# 글머리 기호: 줄 머리면 "-", 아니면 ", " (앞뒤 빈칸은 하나로).
BULLETS = frozenset("•·∙‧⋅・")

# 사전 비교에서 접는 닮은 글자 (키릴 · 그리스 → 라틴). casefold 뒤에 쓴다.
_CONFUSABLES = {
    # 키릴
    "а": "a", "в": "b", "с": "c", "ԁ": "d", "е": "e",
    "һ": "h", "н": "h", "і": "i", "ј": "j", "к": "k",
    "ӏ": "l", "м": "m", "о": "o", "р": "p", "ԛ": "q",
    "ѕ": "s", "т": "t", "у": "y", "х": "x", "ԝ": "w",
    # 그리스
    "α": "a", "β": "b", "ε": "e", "ζ": "z", "η": "h",
    "ι": "i", "κ": "k", "μ": "m", "ν": "n", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "y", "χ": "x",
    # 라틴 변형
    "ı": "i", "ɡ": "g", "ſ": "s",
}
_CONFUSABLE_TABLE = {ord(k): v for k, v in _CONFUSABLES.items()}


def nfkc(s):
    """NFKC 로만 바꾼다."""
    return unicodedata.normalize("NFKC", s)


def prepare(s):
    """펼친 글에 넣을 손질 (SP-03): NFKC → 문장 부호 표 → 글머리 기호.

    줄바꿈은 그대로 둔다 (자유 글 칸의 줄바꿈은 D1 이 막는다).
    """
    s = nfkc(s)
    out = []
    line_head = True          # 지금 줄에서 빈칸 밖의 글자가 아직 없다
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in BULLETS:
            if line_head:
                out.append("-")
                i += 1
                continue
            # 앞의 빈칸을 걷고 ", " 하나로, 뒤의 빈칸은 건너뛴다
            while out and out[-1] == " ":
                out.pop()
            out.append(", ")
            i += 1
            while i < n and s[i] == " ":
                i += 1
            line_head = False
            continue
        rep = PUNCT_MAP.get(ch)
        if rep is not None:
            out.append(rep)
            line_head = False
        else:
            out.append(ch)
            if ch == "\n":
                line_head = True
            elif ch not in " \t":
                line_head = False
        i += 1
    return "".join(out)


def dict_key(s):
    """사전 비교용 정규화 N(s). 글자 (유니코드 L*) 와 숫자 (N*) 만 남긴다."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))
    s = unicodedata.normalize("NFKC", s)
    s = s.casefold()
    s = s.translate(_CONFUSABLE_TABLE)
    return "".join(ch for ch in s if ch.isalnum())


# D1 의 글자 규칙 (SP-03): 손질한 뒤에 남아도 되는 글자.
_HANGUL_RANGES = (
    (0xAC00, 0xD7A3),   # 한글 음절
    (0x1100, 0x11FF),   # 한글 자모
    (0x3130, 0x318F),   # 호환 자모
    (0xA960, 0xA97F),   # 자모 확장 A
    (0xD7B0, 0xD7FF),   # 자모 확장 B
)


def is_hangul(ch):
    o = ord(ch)
    for lo, hi in _HANGUL_RANGES:
        if lo <= o <= hi:
            return True
    return False


def allowed_text_char(ch):
    """자유 글 칸 (한 줄) 에 남아도 되는 글자인가: ASCII 인쇄 글자 · 빈칸 · 완성형 한글 음절.

    낱자모 (ㄱ · ᄀ) 는 받지 않는다 — 자모로 풀어 쓴 사전 단어는 NFKC 로 다시 모이지 않는다.
    """
    o = ord(ch)
    if 0x20 <= o <= 0x7E:
        return True
    return 0xAC00 <= o <= 0xD7A3


def allowed_code_char(ch):
    """합성 재현 코드 (repro) 에 남아도 되는 글자인가: ASCII 인쇄 글자 · 줄바꿈 · 탭."""
    o = ord(ch)
    return 0x20 <= o <= 0x7E or ch == "\n" or ch == "\t"
