# -*- coding: utf-8 -*-
"""JSON Schema 의 작은 부분집합을 표준 라이브러리로 판정한다 (D1 형식 검사 · SP-02).

schema/brief.schema.json 이 쓰는 키워드만 안다. 모르는 키워드가 스키마에 있으면
SchemaUnsupported 를 던진다 — 부르는 쪽은 막는 쪽으로 끝낸다 (AL-03 · E-20).

오류의 자리 (path) 는 스키마가 아는 칸 이름과 목록 번호로만 만든다.
글 속의 모르는 키 이름 · 값은 자리에 넣지 않는다 (AL-11 — 키 이름에도 단어가 있을 수 있다).
"""

import json
import os
import re

_KNOWN = frozenset([
    "$schema", "$id", "title", "description", "$defs", "$ref",
    "type", "const", "enum", "required", "properties", "additionalProperties",
    "allOf", "if", "then", "else",
    "pattern", "minLength", "maxLength", "minItems", "maxItems", "items",
    "minimum", "maximum",
])


class SchemaUnsupported(Exception):
    """스키마에 이 판정기가 모르는 키워드 · 꼴이 있다."""


def load_schema(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def default_schema_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "schema", "brief.schema.json")


def format_path(parts):
    """["context", 1] → "context[1]" · ["entities", 0, "note"] → "entities[0].note" · [] → "(root)"."""
    if not parts:
        return "(root)"
    out = ""
    for p in parts:
        if isinstance(p, int):
            out += "[%d]" % p
        elif out:
            out += "." + p
        else:
            out = p
    return out


_PATTERN_CACHE = {}


def _compile(pattern):
    rx = _PATTERN_CACHE.get(pattern)
    if rx is None:
        p = pattern
        # Python 의 "$" 는 끝의 줄바꿈 앞에서도 맞는다. 끝의 "$" 는 "\Z" 로 바꾼다.
        if p.endswith("$") and not p.endswith("\\$"):
            p = p[:-1] + r"\Z"
        rx = re.compile(p)
        _PATTERN_CACHE[pattern] = rx
    return rx


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float))) and not isinstance(v, bool)


def _type_ok(v, t):
    if isinstance(t, list):
        return any(_type_ok(v, x) for x in t)
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return _is_int(v)
    if t == "number":
        return _is_num(v)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    raise SchemaUnsupported("type")


def _equal(a, b):
    # JSON 의 같음: true 와 1 은 다르다 (Python 은 같다고 본다).
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_equal(a[k], b[k]) for k in a)
    if _is_num(a) and _is_num(b):
        return a == b
    return type(a) is type(b) and a == b


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise SchemaUnsupported("$ref")
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SchemaUnsupported("$ref")
        node = node[part]
    return node


def _check(inst, sch, path, root, errs, depth=0):
    if depth > 64:
        raise SchemaUnsupported("depth")
    if sch is True:
        return
    if sch is False:
        errs.append((list(path), "false"))
        return
    if not isinstance(sch, dict):
        raise SchemaUnsupported("schema")
    for k in sch:
        if k not in _KNOWN:
            raise SchemaUnsupported(k)

    if "$ref" in sch:
        _check(inst, _resolve(root, sch["$ref"]), path, root, errs, depth + 1)

    if "type" in sch and not _type_ok(inst, sch["type"]):
        errs.append((list(path), "type"))
        return
    if "const" in sch and not _equal(inst, sch["const"]):
        errs.append((list(path), "const"))
    if "enum" in sch and not any(_equal(inst, e) for e in sch["enum"]):
        errs.append((list(path), "enum"))

    if isinstance(inst, str):
        if "minLength" in sch and len(inst) < sch["minLength"]:
            errs.append((list(path), "minLength"))
        if "maxLength" in sch and len(inst) > sch["maxLength"]:
            errs.append((list(path), "maxLength"))
        if "pattern" in sch and not _compile(sch["pattern"]).search(inst):
            errs.append((list(path), "pattern"))

    if _is_num(inst):
        if "minimum" in sch and inst < sch["minimum"]:
            errs.append((list(path), "minimum"))
        if "maximum" in sch and inst > sch["maximum"]:
            errs.append((list(path), "maximum"))

    if isinstance(inst, list):
        if "minItems" in sch and len(inst) < sch["minItems"]:
            errs.append((list(path), "minItems"))
        if "maxItems" in sch and len(inst) > sch["maxItems"]:
            errs.append((list(path), "maxItems"))
        if "items" in sch:
            for i, v in enumerate(inst):
                _check(v, sch["items"], path + [i], root, errs, depth + 1)

    if isinstance(inst, dict):
        props = sch.get("properties", {})
        for req in sch.get("required", []):
            if req not in inst:
                errs.append((path + [req], "required"))
        for k, v in inst.items():
            if k in props:
                _check(v, props[k], path + [k], root, errs, depth + 1)
            elif "additionalProperties" in sch:
                ap = sch["additionalProperties"]
                if ap is False:
                    # 모르는 키의 이름은 자리에 넣지 않는다
                    errs.append((list(path), "additionalProperties"))
                else:
                    _check(v, ap, path + ["?"], root, errs, depth + 1)

    for sub in sch.get("allOf", []):
        _check(inst, sub, path, root, errs, depth + 1)

    if "if" in sch:
        probe = []
        _check(inst, sch["if"], path, root, probe, depth + 1)
        if not probe:
            if "then" in sch:
                _check(inst, sch["then"], path, root, errs, depth + 1)
        elif "else" in sch:
            _check(inst, sch["else"], path, root, errs, depth + 1)


def validate(instance, schema):
    """오류 목록 [(자리 목록, 키워드)] 을 돌려준다. 비면 통과.

    모르는 키는 키마다 하나씩 남는다 (자리는 그 키를 가진 객체 · 키 이름은 없음).
    """
    errs = []
    _check(instance, schema, [], schema, errs)
    return errs
