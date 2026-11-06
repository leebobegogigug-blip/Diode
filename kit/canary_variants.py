#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카나리아 변형 만들기 (KIT-3 · 작업 T3).

카나리아는 원자료에 심은 지어낸 비밀 문자열이다. 사내 LLM 이 brief 를 쓸 때 카나리아를 글자 그대로 옮기지
않아도, 대소문자 · 빈칸 · 하이픈 · 전각 · 단위 표기만 바꿔 옮기면 새는 것이다. 이 모듈은 카나리아 하나에서
"같은 것을 다르게 쓴 꼴" 을 만든다. 만든 변형은 두 곳에서 쓴다.

  - kit/leak_rate.py       brief 안에 카나리아나 그 변형이 있는지 센다.
  - 검사기 (D2 · D3 · D4 · D5)  변형을 놓치지 않는지 시험하는 목록으로 부른다.

쓰는 법 (명령줄):
    python canary_variants.py "가람소재" --class name --alias "Garam Materials"
    python canary_variants.py "1,285도" --class number --families
    python canary_variants.py "kitc-mes01.example.com" --class host --json

쓰는 법 (코드):
    from canary_variants import variants, variant_items, normalize, normalize_loose
    variants("가람소재", "name", aliases=["Garam Materials"])   # -> List[str] (맨 앞이 원문)
    variant_items("1,285도", "number")                            # -> List[(가족, 글)]

변형의 가족 (variant_items 의 첫 칸)
    exact 원문 · case 대소문자 · space 빈칸 · hyphen 하이픈 · underscore 밑줄 · dot 점 · slash 빗금 ·
    middledot 가운뎃점 · fullwidth 전각 · invisible 보이지 않는 글자 · decomposed 자모 풀어쓰기 ·
    alias 별칭 · mixed 한영 혼용 · affix 앞뒤 낱말 · ident 코드 식별자 (snake · camel) · comment 주석 안 ·
    string 문자열 값 안 · numfmt 숫자 표기 · unit 단위 표기 · unitconv 단위 바꿈 (값을 다시 계산) ·
    hangul_num 한글 수사 · bare 단위 뗀 숫자 · pathsep 경로 구분자 · pathpart 경로 일부 ·
    hostpart 호스트 꼴 · idpart 번호 일부

이 모듈은 사람이 읽는 말을 만들 뿐 검사를 하지 않는다. 변형을 찾는 쪽 (leak_rate.py) 은 normalize / normalize_loose
로 양쪽을 같은 꼴로 접은 뒤 부분 문자열로 찾는다. 표준 라이브러리만 · Python 3.8 이상.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, Dict, List, Optional, Sequence, Tuple

CLASSES = ("name", "number", "path", "host", "id", "code")

FAMILY_LABELS = {
    "exact": "원문 그대로", "case": "대소문자", "space": "빈칸", "hyphen": "하이픈", "underscore": "밑줄",
    "dot": "점", "slash": "빗금", "middledot": "가운뎃점", "fullwidth": "전각", "invisible": "보이지 않는 글자",
    "decomposed": "자모 풀어쓰기", "alias": "별칭", "mixed": "한영 혼용", "affix": "앞뒤 낱말",
    "ident": "코드 식별자", "comment": "주석 안", "string": "문자열 값 안", "numfmt": "숫자 표기",
    "unit": "단위 표기", "unitconv": "단위 바꿈", "hangul_num": "한글 수사", "bare": "단위 뗀 숫자",
    "pathsep": "경로 구분자", "pathpart": "경로 일부", "hostpart": "호스트 꼴", "idpart": "번호 일부",
}


# ───────────────────────────────────────────────────────── 정규화

_D2_STRIP = re.compile(r"[\s\-_./·]")


def normalize(s: str) -> str:
    """D2 의 정규화 N(s): NFKC → casefold → 빈칸 · - · _ · . · / · 가운뎃점 을 지운다 (SPEC SP-05 D2)."""
    return _D2_STRIP.sub("", unicodedata.normalize("NFKC", s).casefold())


def normalize_loose(s: str) -> str:
    """느슨한 정규화: NFKC → casefold → 글자와 숫자만 남긴다 (역슬래시 · 따옴표 · 괄호 · 보이지 않는 글자도 지움).

    normalize 로 찾는 것은 모두 이것으로도 찾는다 (더 많이 지우므로). 검사기가 못 보는 꼴까지 센다.
    """
    t = unicodedata.normalize("NFKC", s).casefold()
    return "".join(ch for ch in t if ch.isalnum())


# ───────────────────────────────────────────────────────── 작은 도구

_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[가-힣]+|[^\W\d_]+", re.UNICODE)


def split_words(s: str) -> List[str]:
    """낱말로 쪼갠다: 구분자 · 대소문자 경계 · 글자와 숫자 경계 (BX-7 → BX 7 · KitWord → Kit Word)."""
    return _WORD_RE.findall(s)


def split_chunks(s: str) -> List[str]:
    """구분자 (빈칸 - _ . / \\ 가운뎃점) 로만 쪼갠다 (KITC-S20417 → KITC S20417)."""
    return [c for c in re.split(r"[\s\-_./\\·]+", s) if c]


def to_fullwidth(s: str) -> str:
    """ASCII 인쇄 글자를 전각으로 (빈칸은 U+3000). NFKC 로 되돌아온다."""
    out = []
    for ch in s:
        o = ord(ch)
        if ch == " ":
            out.append("　")
        elif 0x21 <= o <= 0x7E:
            out.append(chr(o + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


class _Bag(object):
    """(가족, 글) 을 먼저 나온 차례대로 모으고 같은 글은 한 번만 둔다."""

    def __init__(self) -> None:
        self.items = []  # type: List[Tuple[str, str]]
        self._seen = set()

    def add(self, family: str, text: str) -> None:
        if not isinstance(text, str) or not text.strip() or text in self._seen:
            return
        self._seen.add(text)
        self.items.append((family, text))


# ───────────────────────────────────────────────────────── 이름 · 코드 꼴의 변형

def _text_forms(bag: _Bag, s: str, label: Optional[str] = None, light: bool = False) -> None:
    """대소문자 · 빈칸 · 구분자 · 전각 · 보이지 않는 글자 · 자모 풀어쓰기. label 이 있으면 가족 이름을 그것으로 덮는다."""
    def fam(name: str) -> str:
        return label or name

    words = split_words(s)
    nospace = re.sub(r"\s+", "", s)
    for t in (s.upper(), s.lower(), s.title(), s.capitalize(), s.swapcase()):
        bag.add(fam("case"), t)
    bag.add(fam("space"), nospace)
    if len(words) >= 2:
        for sep in (" ", "  ", " ", "　", "\t"):
            bag.add(fam("space"), sep.join(words))
    if not light:
        if 2 <= len(nospace) <= 40:
            bag.add(fam("space"), " ".join(nospace))
        if 2 <= len(nospace) <= 24:
            for i in range(1, len(nospace)):
                bag.add(fam("space"), nospace[:i] + " " + nospace[i:])
        elif len(nospace) > 24:
            m = len(nospace) // 2
            bag.add(fam("space"), nospace[:m] + " " + nospace[m:])
    seps = (("hyphen", "-"), ("underscore", "_"), ("dot", "."), ("slash", "/"), ("middledot", "·"))
    for name, sep in seps:
        if len(words) >= 2:
            bag.add(fam(name), sep.join(words))
        if len(nospace) >= 2:
            m = len(nospace) // 2
            bag.add(fam(name), nospace[:m] + sep + nospace[m:])
            if not light and len(nospace) <= 16:
                bag.add(fam(name), sep.join(nospace))
        bag.add(fam(name), re.sub(r"[\s\-_./·]+", sep, s.strip()))
    for t in (s, s.lower(), s.upper(), "-".join(words), "_".join(words), " ".join(words)):
        bag.add(fam("fullwidth"), to_fullwidth(t))
    if len(nospace) >= 2:
        m = len(nospace) // 2
        for ch in ("​", "­", "‍"):
            bag.add(fam("invisible"), nospace[:m] + ch + nospace[m:])
    nfd = unicodedata.normalize("NFD", s)
    if nfd != s:
        bag.add(fam("decomposed"), nfd)


def _ident_forms(bag: _Bag, s: str, label: Optional[str] = None) -> None:
    """코드 식별자 꼴: snake · SCREAMING · kebab · camel · Pascal · 이어 붙임 · 점 · 앞머리 · 호출 꼴."""
    fam = label or "ident"
    words = split_words(s)
    if not words:
        return
    low = [w.lower() for w in words]
    snake = "_".join(low)
    pascal = "".join(w.capitalize() for w in low)
    camel = low[0] + "".join(w.capitalize() for w in low[1:])
    for t in (snake, "_".join(w.upper() for w in words), "-".join(low), camel, pascal, "".join(low), ".".join(low)):
        bag.add(fam, t)
    for pre in ("get_", "set_", "is_", "_", "__", "self.", "cfg.", "tbl_", "fn_"):
        bag.add(fam, pre + snake)
    for pre in ("get", "set", "is"):
        bag.add(fam, pre + pascal)
    for t in (snake, camel):
        bag.add(fam, t + "()")
        bag.add(fam, t + "(x)")
        bag.add(fam, "obj." + t)


def _wrap_forms(bag: _Bag, s: str) -> None:
    """주석 안 · 문자열 값 안에 넣은 꼴."""
    for t in ("# " + s, "#" + s, "// " + s, "/* " + s + " */", "<!-- " + s + " -->", '""" ' + s + ' """',
              "-- " + s, "; " + s, "% " + s, "# TODO: " + s, "// FIXME " + s):
        bag.add("comment", t)
    for t in ('"' + s + '"', "'" + s + "'", 'f"' + s + '"', '{"name": "' + s + '"}', 'x = "' + s + '"',
              'df["' + s + '"]', "df['" + s + "']", 'get("' + s + '")', '"' + s + '_total"', '"prefix_' + s + '"',
              'name="' + s + '"', "'" + s + "': 1"):
        bag.add("string", t)


_PREFIXES = ("주식회사 ", "주식회사", "(주)", "㈜", "신규 ", "구 ", "old_", "new_", "tmp_", "the ", "x")
_SUFFIXES = ("의", "은", "는", "이", "가", "을", "를", "에", "에서", "로", "와", "과", "도", " 팀", " 라인", " 공정",
             "_v2", "_old", "-prod", " Co.", " Inc.", "(가상)", "z")


def _affix_forms(bag: _Bag, s: str) -> None:
    """앞뒤에 낱말 · 글자를 붙인 꼴 (부분 문자열 찾기가 경계를 잘못 보지 않는지 본다)."""
    for p in _PREFIXES:
        bag.add("affix", p + s)
    for q in _SUFFIXES:
        bag.add("affix", s + q)
    for t in ("pre" + s + "post", "pre_" + s + "_post", "(" + s + ")", "[" + s + "]", "<" + s + ">", " " + s + ","):
        bag.add("affix", t)


def _alias_forms(bag: _Bag, s: str, aliases: Sequence[str]) -> None:
    """등록된 별칭 (한영 · 약어) 과 섞어 쓴 꼴. 별칭이 없으면 부르지 않는다 (자동 음역은 하지 않는다)."""
    sw = split_words(s)
    for a in aliases:
        bag.add("alias", a)
        _text_forms(bag, a, label="alias")
        _ident_forms(bag, a, label="alias")
        for t in (s + "(" + a + ")", a + "(" + s + ")", s + " " + a, a + " " + s, s + " / " + a, s + "·" + a):
            bag.add("mixed", t)
        aw = split_words(a)
        if len(sw) == len(aw) and 2 <= len(sw) <= 4:
            for mask in range(1, 2 ** len(sw) - 1):
                ws = [aw[i] if (mask >> i) & 1 else sw[i] for i in range(len(sw))]
                bag.add("mixed", " ".join(ws))
                bag.add("mixed", "-".join(ws))
                bag.add("mixed", "_".join(ws))


# ───────────────────────────────────────────────────────── 숫자 · 단위

class _Unit(object):
    """단위 하나: 가족 (dim) · 표기 목록 · 기준 단위로 바꾸는 식과 되돌리는 식."""

    def __init__(self, dim: str, key: str, spell: Sequence[str], to_base: Callable[[Decimal], Decimal],
                 from_base: Callable[[Decimal], Decimal], prefix: Sequence[str] = (), lead: Sequence[str] = ()) -> None:
        self.dim = dim
        self.key = key
        self.spell = list(spell)      # 숫자 뒤에 붙는 표기
        self.to_base = to_base
        self.from_base = from_base
        self.prefix = list(prefix)    # 숫자 앞에 붙는 표기 (₩ · KRW)
        self.lead = list(lead)        # "섭씨 {n}도" 처럼 낱말이 앞에 오는 틀


def _lin(dim: str, key: str, factor: str, spell: Sequence[str], prefix: Sequence[str] = ()) -> _Unit:
    f = Decimal(factor)
    return _Unit(dim, key, spell, lambda x: x * f, lambda x: x / f, prefix)


def _build_units() -> List[_Unit]:
    k = Decimal("273.15")
    nine, five, thirty2 = Decimal(9), Decimal(5), Decimal(32)
    units = [
        _Unit("temp", "C", ["도", "℃", "°C", "˚C", "ºC", "C", "degC", "deg C", "도씨"],
              lambda x: x, lambda x: x, lead=["섭씨 {n}도", "섭씨{n}도", "{n}도 C"]),
        _Unit("temp", "F", ["℉", "°F", "F", "degF", "deg F"],
              lambda x: (x - thirty2) * five / nine, lambda x: x * nine / five + thirty2, lead=["화씨 {n}도"]),
        _Unit("temp", "K", ["K", "켈빈"], lambda x: x - k, lambda x: x + k),
        _lin("pressure", "Pa", "1", ["Pa", "파스칼"]),
        _lin("pressure", "kPa", "1000", ["kPa", "킬로파스칼"]),
        _lin("pressure", "MPa", "1000000", ["MPa", "메가파스칼"]),
        _lin("pressure", "bar", "100000", ["bar", "바"]),
        _lin("pressure", "mbar", "100", ["mbar"]),
        _lin("pressure", "atm", "101325", ["atm", "기압"]),
        _lin("pressure", "psi", "6894.757293168", ["psi"]),
        _lin("pressure", "mmHg", "133.322387415", ["mmHg"]),
        _lin("length", "um", "0.000001", ["um", "µm", "μm", "마이크로미터"]),
        _lin("length", "mm", "0.001", ["mm", "밀리미터"]),
        _lin("length", "cm", "0.01", ["cm", "센티미터"]),
        _lin("length", "m", "1", ["m", "미터"]),
        _lin("length", "km", "1000", ["km", "킬로미터"]),
        _lin("length", "in", "0.0254", ["in", "inch", "인치", '"']),
        _lin("length", "ft", "0.3048", ["ft", "feet", "피트"]),
        _lin("mass", "mg", "0.001", ["mg", "밀리그램"]),
        _lin("mass", "g", "1", ["g", "그램"]),
        _lin("mass", "kg", "1000", ["kg", "킬로그램"]),
        _lin("mass", "t", "1000000", ["t", "ton", "톤"]),
        _lin("mass", "lb", "453.59237", ["lb", "lbs", "파운드"]),
        _lin("volume", "mL", "0.001", ["mL", "ml", "밀리리터"]),
        _lin("volume", "L", "1", ["L", "l", "ℓ", "리터"]),
        _lin("volume", "m3", "1000", ["m3", "m³", "세제곱미터"]),
        _lin("volume", "gal", "3.785411784", ["gal", "갤런"]),
        _lin("time", "ms", "0.001", ["ms", "밀리초"]),
        _lin("time", "s", "1", ["s", "sec", "초"]),
        _lin("time", "min", "60", ["min", "분"]),
        _lin("time", "h", "3600", ["h", "hr", "시간"]),
        _lin("time", "d", "86400", ["d", "일"]),
        _lin("freq", "Hz", "1", ["Hz", "헤르츠"]),
        _lin("freq", "kHz", "1000", ["kHz", "킬로헤르츠"]),
        _lin("freq", "MHz", "1000000", ["MHz", "메가헤르츠"]),
        _lin("power", "W", "1", ["W", "와트"]),
        _lin("power", "kW", "1000", ["kW", "킬로와트"]),
        _lin("power", "MW", "1000000", ["MW", "메가와트"]),
        _lin("energy", "Wh", "1", ["Wh"]),
        _lin("energy", "kWh", "1000", ["kWh", "킬로와트시"]),
        _lin("energy", "MWh", "1000000", ["MWh", "메가와트시"]),
        _lin("volt", "mV", "0.001", ["mV"]),
        _lin("volt", "V", "1", ["V", "볼트"]),
        _lin("volt", "kV", "1000", ["kV"]),
        _lin("amp", "mA", "0.001", ["mA"]),
        _lin("amp", "A", "1", ["A", "암페어"]),
        _lin("ratio", "%", "0.01", ["%", " %", "퍼센트", "프로"]),
        _lin("money", "원", "1", ["원", "KRW"], prefix=["₩", "KRW "]),
        _lin("money", "천원", "1000", ["천원"]),
        _lin("money", "만원", "10000", ["만원"]),
        _lin("money", "백만원", "1000000", ["백만원"]),
        _lin("money", "억원", "100000000", ["억원"]),
        _lin("conc", "ppm", "1", ["ppm", "PPM", "피피엠"]),
        _lin("rot", "rpm", "1", ["rpm", "RPM", "알피엠"]),
    ]
    return units


_UNITS = _build_units()
_BY_SPELL = {}  # type: Dict[str, _Unit]
for _u in _UNITS:
    for _s in _u.spell:
        _BY_SPELL.setdefault(_s.strip(), _u)

_NUM_RE = re.compile(
    r"^(?P<pre>[^\d+\-]*?)(?P<sign>[+\-]?)(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<unit>.*)$", re.S)

_KO_DIGIT = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_KO_SMALL = ["", "십", "백", "천"]
_KO_GROUP = ["", "만", "억", "조"]
_KO_DEC = "영일이삼사오육칠팔구"


def ko_int(n: int, omit_one_small: bool = True, omit_one_group: bool = False) -> str:
    """정수를 한자어 수사로 (350 → 삼백오십 · 1285 → 천이백팔십오). 10 의 16 제곱 미만."""
    if n == 0:
        return "영"
    if n < 0 or n >= 10 ** 16:
        raise ValueError("범위 밖")
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    parts = []
    for gi in range(len(groups) - 1, -1, -1):
        g = groups[gi]
        if g == 0:
            continue
        s = ""
        for pos in (3, 2, 1, 0):
            d = (g // 10 ** pos) % 10
            if d == 0:
                continue
            if pos > 0 and d == 1 and omit_one_small:
                s += _KO_SMALL[pos]
            else:
                s += _KO_DIGIT[d] + _KO_SMALL[pos]
        if gi > 0 and s == "일" and omit_one_group:
            s = ""
        parts.append(s + _KO_GROUP[gi])
    return "".join(parts)


def _plain(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _grouped(d: Decimal) -> str:
    ip, _, fp = _plain(d).partition(".")
    neg = ip.startswith("-")
    g = "{:,}".format(int(ip.lstrip("-") or "0"))
    return ("-" if neg else "") + g + ("." + fp if fp else "")


def _number_styles(d: Decimal) -> List[str]:
    """같은 값을 쓰는 여러 방식: 이어 쓰기 · 천 단위 쉼표 · 빈칸 · 유럽식 · 소수점 쉼표 · 끝 0 · 지수."""
    plain, grouped = _plain(d), _grouped(d)
    out = [plain, grouped, grouped.replace(",", " "), grouped.replace(",", " ")]
    out.append(grouped.replace(",", "X").replace(".", ",").replace("X", "."))
    out.append(plain.replace(".", ","))
    out.append(plain + ".0" if "." not in plain else plain + "0")
    try:
        out.append(format(d, "E").replace("E+", "E"))
        out.append(format(d, "e"))
    except Exception:
        pass
    seen = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


def _rounded(d: Decimal) -> List[Decimal]:
    """단위를 바꾼 값의 어림: 있는 그대로 (소수 넷) · 소수 둘 · 정수."""
    res = []
    for q in ("0.0001", "0.01", "1"):
        try:
            r = d.quantize(Decimal(q), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            continue
        if r not in res:
            res.append(r)
    return res


def _number_forms(bag: _Bag, value: str) -> None:
    s = unicodedata.normalize("NFKC", value).strip()
    m = _NUM_RE.match(s)
    bag.add("fullwidth", to_fullwidth(value))
    if not m:
        _text_forms(bag, value, light=True)
        return
    pre, sign = m.group("pre").strip(), m.group("sign")
    unit_txt = m.group("unit").strip()
    try:
        d = Decimal(m.group("num").replace(",", ""))
    except InvalidOperation:
        return
    if sign == "-":
        d = -d
    unit = _BY_SPELL.get(unit_txt) or _BY_SPELL.get(unit_txt.replace(" ", ""))
    spells = list(unit.spell) if unit else ([unit_txt] if unit_txt else [])
    if unit_txt and unit_txt not in spells:
        spells.insert(0, unit_txt)
    lead = (pre + " ") if pre else ""
    sg = "-" if sign == "-" else ""
    styles = _number_styles(abs(d))

    # 숫자 표기: 단위는 원문 그대로
    for ns in styles:
        for sep in ("", " "):
            bag.add("numfmt", lead + sg + ns + sep + unit_txt)
    # 단위 표기: 숫자는 원문 · 이어 쓰기 · 쉼표
    for sp in spells:
        for ns in styles[:2]:
            for sep in ("", " "):
                bag.add("unit", lead + sg + ns + sep + sp.strip())
    if unit:
        for tpl in unit.lead:
            for ns in styles[:2]:
                bag.add("unit", tpl.replace("{n}", ns))
        for pf in unit.prefix:
            for ns in styles[:2]:
                bag.add("unit", pf + ns)
        for sp in unit.spell[:3]:
            for ns in styles[:2]:
                bag.add("fullwidth", to_fullwidth(sg + ns + sp.strip()))
    # 전각 숫자 (단위 뗀 것 포함)
    for ns in styles[:2]:
        bag.add("fullwidth", to_fullwidth(sg + ns))
        bag.add("fullwidth", to_fullwidth(lead + sg + ns + unit_txt))
    # 단위 뗀 숫자: 숫자만 넉 자리 이상일 때 (짧으면 아무 글에나 걸린다)
    digits = re.sub(r"\D", "", _plain(abs(d)))
    if len(digits) >= 4:
        bag.add("bare", sg + styles[0])
        bag.add("bare", sg + styles[1])
    # 단위 바꿈: 값을 다시 계산해서 다른 단위로
    if unit:
        base = unit.to_base(d)
        for other in _UNITS:
            if other.dim != unit.dim or other is unit:
                continue
            try:
                conv = other.from_base(base)
            except (InvalidOperation, ZeroDivisionError):
                continue
            for r in _rounded(conv):
                for ns in (_plain(r), _grouped(r)):
                    for sp in other.spell[:3]:
                        for sep in ("", " "):
                            bag.add("unitconv", sg + ns + sep + sp.strip())
        if unit.dim == "ratio":
            frac = _plain(d * Decimal("0.01"))
            if len(re.sub(r"\D", "", frac)) >= 4:
                bag.add("unitconv", frac)
    # 한글 수사: 정수 부분 (+ 소수 자리는 "점" 뒤에 낱낱이)
    ip, _, fp = _plain(abs(d)).partition(".")
    if len(ip) <= 15:
        for omit_small, omit_group in ((True, False), (False, False), (True, True)):
            try:
                ko = ko_int(int(ip), omit_small, omit_group)
            except ValueError:
                continue
            if fp:
                ko += "점" + "".join(_KO_DEC[int(c)] for c in fp)
            ko = ("마이너스 " if sign == "-" else "") + ko
            bag.add("hangul_num", ko)
            for sp in spells[:6]:
                for sep in ("", " "):
                    bag.add("hangul_num", lead + ko + sep + sp.strip())
            if unit:
                for tpl in unit.lead:
                    bag.add("hangul_num", tpl.replace("{n}", ko))


# ───────────────────────────────────────────────────────── 경로 · 호스트 · 번호

def _path_forms(bag: _Bag, v: str) -> None:
    bs = v.replace("/", "\\")
    fs = v.replace("\\", "/")
    for t in (bs, fs, bs.replace("\\", "\\\\"), v.rstrip("\\/"), v.rstrip("\\/") + ("\\" if "\\" in v else "/")):
        bag.add("pathsep", t)
    if re.match(r"^[A-Za-z]:", v):
        bag.add("pathsep", v[0].lower() + v[1:])
        bag.add("pathsep", v[0].upper() + v[1:])
        bag.add("pathsep", "file:///" + fs)
        bag.add("pathsep", "\\\\?\\" + bs)
    elif v.startswith("\\\\"):
        bag.add("pathsep", "file:" + fs)
        bag.add("pathsep", "//" + v[2:].replace("\\", "/"))
    elif v.startswith("/"):
        bag.add("pathsep", "file://" + v)
    parts = [p for p in re.split(r"[\\/]+", v) if p]
    if parts:
        base = parts[-1]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        if len(normalize_loose(base)) >= 6:
            bag.add("pathpart", base)
        if len(normalize_loose(stem)) >= 6:
            bag.add("pathpart", stem)
        if len(parts) >= 2 and len(normalize_loose(parts[-2] + parts[-1])) >= 8:
            bag.add("pathpart", parts[-2] + "\\" + parts[-1])
            bag.add("pathpart", parts[-2] + "/" + parts[-1])
    _text_forms(bag, bs, light=True)
    _text_forms(bag, fs, light=True)


def _host_forms(bag: _Bag, v: str) -> None:
    core = v
    m = re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*://)?(?P<h>[^/:\s]+)(?::\d+)?(?:/.*)?$", v)
    if m:
        core = m.group("h")
    is_ip = bool(re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", core))
    for t in (core.upper(), core.lower(), core + ".", "http://" + core, "https://" + core, "//" + core):
        bag.add("hostpart", t)
    for port in ("80", "443", "8080", "8443", "5432", "3306", "9200"):
        bag.add("hostpart", core + ":" + port)
    for t in (core + "/api/v1", core + "/health", "batch@" + core, "host=" + core, "https://" + core + "/"):
        bag.add("hostpart", t)
    if is_ip:
        oct_ = core.split(".")
        n = [int(o) for o in oct_]
        bag.add("hostpart", ".".join("%03d" % x for x in n))
        for sep in ("-", "_", " ", " . ", "·"):
            bag.add("hostpart", sep.join(oct_))
        bag.add("hostpart", "0x%02X%02X%02X%02X" % tuple(n))
        bag.add("hostpart", ".".join("0x%02X" % x for x in n))
        bag.add("hostpart", str((n[0] << 24) + (n[1] << 16) + (n[2] << 8) + n[3]))
        bag.add("hostpart", "::ffff:" + core)
        bag.add("hostpart", to_fullwidth(core).replace("．", "．"))
    else:
        labels = core.split(".")
        if len(labels) >= 2:
            first = labels[0]
            if len(first) >= 5:
                bag.add("hostpart", first)
            bag.add("hostpart", "-".join(labels))
            bag.add("hostpart", "_".join(labels))
            bag.add("hostpart", " . ".join(labels))
            bag.add("hostpart", " ".join(labels))
            bag.add("hostpart", ".".join(labels[:-1]))
    bag.add("fullwidth", to_fullwidth(v))
    bag.add("fullwidth", to_fullwidth(core))
    _text_forms(bag, core, light=True)


def _id_forms(bag: _Bag, v: str) -> None:
    chunks = split_chunks(v)
    words = split_words(v)
    for sep in ("", " ", "-", "_", ".", "/"):
        if len(chunks) >= 2:
            bag.add("idpart", sep.join(chunks))
        if len(words) >= 2:
            bag.add("idpart", sep.join(words))
    for t in (v.upper(), v.lower(), v.title()):
        bag.add("case", t)
    for t in ("#" + v, "No. " + v, "NO." + v, "no " + v, "사번 " + v, "(" + v + ")", v + ".", "ID:" + v, "id=" + v):
        bag.add("idpart", t)
    if len(chunks) >= 2:
        tail = "".join(chunks[1:])
        if len(tail) >= 5 and re.search(r"\d", tail):
            bag.add("idpart", tail)
            bag.add("idpart", "-".join(chunks[1:]))
    runs = re.findall(r"\d+", v)
    for r in runs:
        if len(r) >= 5:
            bag.add("idpart", r)
    for t in (v, v.lower(), v.upper(), "-".join(chunks), "".join(chunks)):
        bag.add("fullwidth", to_fullwidth(t))
    _text_forms(bag, v, light=True)


# ───────────────────────────────────────────────────────── 공개 함수

def variant_items(value: str, cls: str = "name", aliases: Optional[Sequence[str]] = None) -> List[Tuple[str, str]]:
    """카나리아 하나의 변형을 (가족, 글) 목록으로. 맨 앞은 원문 ("exact"). 같은 글은 한 번만."""
    if cls not in CLASSES:
        raise ValueError("모르는 class: %r (name number path host id code 중 하나)" % (cls,))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("값이 비었다")
    bag = _Bag()
    bag.add("exact", value)
    alias_list = [a for a in (aliases or []) if isinstance(a, str) and a.strip()]
    if cls == "number":
        _number_forms(bag, value)
    elif cls == "path":
        _path_forms(bag, value)
    elif cls == "host":
        _host_forms(bag, value)
    elif cls == "id":
        _id_forms(bag, value)
    else:
        _text_forms(bag, value)
        _ident_forms(bag, value)
    _affix_forms(bag, value)
    _wrap_forms(bag, value)
    if alias_list:
        _alias_forms(bag, value, alias_list)
    return bag.items


def variants(value: str, cls: str = "name", aliases: Optional[Sequence[str]] = None) -> List[str]:
    """카나리아 하나의 변형 글 목록 (맨 앞은 원문). aliases 는 사전에 등록한 별칭 (한영 · 약어)."""
    return [t for _f, t in variant_items(value, cls, aliases)]


# ───────────────────────────────────────────────────────── 명령줄

def _stdout_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _stdout_utf8()
    ap = argparse.ArgumentParser(description="카나리아 하나에서 변형을 만든다 (KIT-3).")
    ap.add_argument("value", help="카나리아 값")
    ap.add_argument("--class", dest="cls", default="name", choices=CLASSES, help="카나리아의 종류 (기본 name)")
    ap.add_argument("--alias", action="append", default=[], help="등록된 별칭 (여러 번 쓸 수 있다)")
    ap.add_argument("--families", action="store_true", help="가족 이름을 앞에 붙여 보인다")
    ap.add_argument("--normalized", action="store_true", help="D2 정규화 결과도 보인다")
    ap.add_argument("--json", action="store_true", help="JSON 목록으로 낸다")
    ap.add_argument("--count", action="store_true", help="개수만 낸다")
    args = ap.parse_args(argv)
    try:
        items = variant_items(args.value, args.cls, args.alias)
    except ValueError as e:
        print("사용법 오류: %s" % e, file=sys.stderr)
        return 2
    if args.count:
        print(len(items))
        return 0
    if args.json:
        rows = []
        for fam, text in items:
            row = {"family": fam, "text": text}
            if args.normalized:
                row["normalized"] = normalize(text)
            rows.append(row)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for fam, text in items:
        cols = []
        if args.families:
            cols.append(FAMILY_LABELS.get(fam, fam))
        cols.append(text)
        if args.normalized:
            cols.append(normalize(text))
        print("\t".join(cols))
    return 0


def run_cli(main_func: Callable[[], int]) -> None:
    """명령줄 진입: 표준 출력이 `| head` 처럼 먼저 닫혀도 오류 글을 내지 않고 끝낸다."""
    try:
        code = main_func()
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except Exception:
            pass
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    run_cli(main)
