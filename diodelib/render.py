# -*- coding: utf-8 -*-
"""brief 를 정해진 틀로 펼친다 (SP-03). 바깥으로 가는 바이트는 이 함수가 만든 글뿐이다.

- 사내 LLM 은 펼친 글을 쓰지 않는다. 다이오드만 펼친다.
- 자유 글은 textnorm.prepare 로 손질한 뒤 넣는다 (검사기도 같은 손질을 본다).
- route 칸은 펼치지 않는다 (안쪽 전용).
- 이 함수는 검사하지 않는다. 검사는 scan.check_brief 가 하고, 펼친 글의 크기도 거기서 본다.
"""

from .textnorm import prepare

_COUNT_KEYS = ("changed_files", "tests_passed", "tests_failed", "tests_skipped")

# 파생 표본 (sample) 의 닫힌 틀 (SP-03) - 칸은 한 자리 정수 · 토큰 · PH_other 뿐이다. scan 이 같은 글을 다시 읽어 맞춘다.
SAMPLE_HEAD = "SAMPLE: coarse cells (bucket or rank class, not values; PH_other = pooled rare group)"
SAMPLE_OTHER = "PH_other"


def sample_lines(sample):
    """sample (스키마를 통과한 dict) -> 펼친 줄 목록. 머리 줄 · 표 머리 · 구분줄 · 행."""
    cols = sample["columns"]
    out = [SAMPLE_HEAD]
    out.append("| " + " | ".join("%s (%s)" % (c["token"], c["kind"]) for c in cols) + " |")
    out.append("|" + "---|" * len(cols))
    for row in sample["rows"]:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


def _t(s):
    return prepare(s)


def _entity_line(e):
    head = "- %s (%s)" % (e["token"], e["type"])
    note = e.get("note")
    if note:
        return head + ": " + _t(note)
    return head


def _field_line(f):
    parts = [f["kind"]]
    unit = f.get("unit")
    if unit is not None:
        parts.append("단위 " + unit)
    if "count" in f:
        parts.append("값 %d개" % f["count"])
    return "- %s (%s)" % (f["token"], ", ".join(parts))


def _list(lines, title, items):
    if items:
        lines.append(title + ":")
        for x in items:
            lines.append("- " + _t(x))


def render(brief):
    """brief (스키마를 통과한 dict) → 펼친 글 (str · 줄바꿈 \\n · 끝에 줄바꿈 하나)."""
    kind = brief["kind"]
    lines = []
    if kind == "report":
        lines.append("[diode report format=1 job=%s status=%s]" % (brief["job"], brief["status"]))
        counts = brief.get("counts") or {}
        pairs = ["%s=%d" % (k, counts[k]) for k in _COUNT_KEYS if k in counts]
        if pairs:
            lines.append("COUNTS: " + " ".join(pairs))
        _list(lines, "SUMMARY", brief.get("summary") or [])
        ents = brief.get("entities") or []
        if ents:
            lines.append("ENTITIES:")
            lines.extend(_entity_line(e) for e in ents)
        _list(lines, "QUESTIONS", brief.get("questions") or [])
        lines.append("[/diode report]")
        return "\n".join(lines) + "\n"

    lines.append("[diode brief format=1 kind=%s data=%s]" % (kind, brief["data_class"]))
    if kind == "lib":
        lib = brief["library"]
        if lib.get("version"):
            lines.append("LIBRARY: %s %s" % (lib["name"], lib["version"]))
        else:
            lines.append("LIBRARY: %s" % lib["name"])
        if brief.get("language"):
            lines.append("LANGUAGE: " + brief["language"])
        lines.append("GOAL: " + _t(brief["goal"]))
        repro = brief.get("repro")
        if repro:
            code = repro.replace("\r\n", "\n").rstrip("\n")
            lines.append("REPRO:")
            lines.append("```python")
            lines.extend(code.split("\n"))
            lines.append("```")
        err = brief.get("error")
        if err:
            if err.get("message"):
                lines.append("ERROR: %s: %s" % (err["type"], _t(err["message"])))
            else:
                lines.append("ERROR: " + err["type"])
        lines.append("ASK: " + _t(brief["ask"]))
        lines.append("[/diode brief]")
        return "\n".join(lines) + "\n"

    # plan · ui
    lines.append("GOAL: " + _t(brief["goal"]))
    _list(lines, "CONTEXT", brief.get("context") or [])
    ents = brief.get("entities") or []
    if ents:
        lines.append("ENTITIES:")
        lines.extend(_entity_line(e) for e in ents)
    fields = brief.get("fields") or []
    if fields:
        lines.append("FIELDS:")
        lines.extend(_field_line(f) for f in fields)
    if brief.get("sample"):
        lines.extend(sample_lines(brief["sample"]))
    _list(lines, "CONSTRAINTS", brief.get("constraints") or [])
    lines.append("ASK: " + _t(brief["ask"]))
    lines.append("[/diode brief]")
    return "\n".join(lines) + "\n"
