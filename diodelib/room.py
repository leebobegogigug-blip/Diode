# -*- coding: utf-8 -*-
"""방 (SP-10) 과 데이터 폴더 자리 — 읽기만 한다 (표준 라이브러리 · Python 3.8).

방 상태
  ok       표지 (.diode-room) 가 있고, 방 설정 (.claude/settings.json) 의 sha256 이 표지와 같고,
           설정을 덮을 수 있는 파일 (.claude/settings.local.json · .mcp.json) 이 없다
  changed  표지는 있는데 위 중 하나가 어긋남 — 사람이 고쳤거나 바꿔치기 (원자료 폴더처럼 막는다 · SP-11)
  missing  표지가 없다 (방이 아니다)
"""

import hashlib
import json
import os
import re

MARKER = ".diode-room"
SETTINGS_REL = os.path.join(".claude", "settings.json")
# 방 설정을 덮거나 더하는 파일 — 있으면 changed (Claude Code 는 이것들을 settings.json 위에 얹는다)
OVERRIDES_REL = (os.path.join(".claude", "settings.local.json"), ".mcp.json")
# 방 안에서도 Claude 가 고치면 안 되는 자리 (훅이 쓰기 도구를 막는다)
PROTECTED_REL = (MARKER, ".claude", ".mcp.json", "outbox", "CLAUDE.md", "AGENTS.md")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def default_data_dir():
    """데이터 폴더의 기본 자리. 훅은 DIODE_HOME 을 받지 않는다 — 환경 변수로 다른 사전 · 설정을 물리지 않게.

    Windows: %LOCALAPPDATA%\\diode · 그 밖: ~/.local/share/diode (diode.py check 와 같은 자리).
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "diode")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "diode")


def norm(p):
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def inside(path, root):
    """path 가 root 와 같거나 그 아래인가 (진짜 경로 · 대소문자는 OS 대로)."""
    a, b = norm(path), norm(root)
    if a == b:
        return True
    return a.startswith(b.rstrip(os.sep) + os.sep)


def overlaps(a, b):
    """두 폴더가 겹치는가 — 한쪽이 다른 쪽 아래면 겹친다."""
    return inside(a, b) or inside(b, a)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def room_state(folder):
    """"ok" · "changed" · "missing". 읽다가 실패하면 changed (막는 쪽)."""
    marker = os.path.join(folder, MARKER)
    if not os.path.isfile(marker):
        return "missing"
    try:
        with open(marker, "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or m.get("format") != 1:
            return "changed"
        want = m.get("settings_sha256")
        if not isinstance(want, str) or not _HEX64.match(want):
            return "changed"
        settings = os.path.join(folder, SETTINGS_REL)
        if not os.path.isfile(settings) or sha256_file(settings) != want:
            return "changed"
        for rel in OVERRIDES_REL:
            if os.path.lexists(os.path.join(folder, rel)):
                return "changed"
        return "ok"
    except Exception:
        return "changed"


def is_protected(path, room):
    """방 안의 지켜야 할 자리 (표지 · .claude/ · .mcp.json · outbox/ · 안내 파일) 인가."""
    for rel in PROTECTED_REL:
        if inside(path, os.path.join(room, rel)):
            return True
    return False
