# -*- coding: utf-8 -*-
"""건네기 (PLAN 07 · SP-10) — 계약과 room · clipboard. 표준 라이브러리 · Python 3.8.

계약 (어댑터도 같다)
  name                     "room" · "clipboard" · "adapter"
  check() -> dict          {"ok": bool, "effort": bool, ...} — 쓸 수 있는가 · effort 를 받는가
  put(job, sealed_text, route)
                           확정한 봉인 글 하나를 건넨다. route 는 {"model", "effort"} 두 값뿐이고
                           봉인 글에 섞지 않는다. 원문 · 가명 표에 닿는 인자가 없다.
  get(job) -> str | None   그 job 의 답 (없으면 None)

room
  put  → 방 outbox/<job>.md 에 봉인 글 바이트 그대로 (UTF-8). 임시 파일 → 링크 (있으면 실패 · 덮어쓰지 않음).
         방 상태가 ok 가 아니면 쓰지 않는다 (AL-03).
  put_bundle(job, manifest_text, files)
       → 가린 파일 묶음 (SP-20): 방 outbox/.J-0007.tmp-<무작위>/ 에 파일들 + MANIFEST.md 를 다 쓴 뒤 os.rename 으로
         outbox/J-0007/ 에 한 번에 이름을 붙인다 (있으면 실패 · 덮어쓰지 않음 · 남은 임시 폴더는 지운다).
         files 는 확정 창 요청의 files 칸 그대로 ([{"name": "F01.md", "type", "text"}]) — 확정 창이 보인 바이트만 쓴다.
  get  → 방 inbox/<job>.md 를 읽는다. 답의 검사 (U1–U4) · 되돌리기는 부르는 쪽 (unseal) 이 한다.
         가린 묶음의 답은 inbox 로 오지 않는다 (Claude 가 dispatch 의 첨부로 돌려보낸다) — get 은 그대로다.
  [제안] 자문마다 방 설정에 model · effortLevel 을 쓰는 일 (PLAN 07) 은 여기서 하지 않는다 —
         방 설정을 바꾸면 표지의 해시와 달라져 방이 changed 가 된다. /diode:room 이 표지와 같이 다시 쓰는 길로 정한다.
clipboard
  확정 창 (diodelib.confirm) 이 복사한다. 여기에는 이름 · check 만 있다.
"""

import errno
import os
import re
import shutil
import tempfile

from .room import room_state

JOB_RE = re.compile(r"^J-[0-9]{4,6}\Z")
EFFORTS = ("", "auto", "low", "medium", "high", "xhigh", "max")
ROUTE_KEYS = frozenset(["model", "effort"])
MAX_SEALED_BYTES = 8192          # 펼친 글 상한 (SP-02)
MAX_ANSWER_BYTES = 524288        # 답 상한 (U4 의 ui 상한) [제안]
# 가린 파일 묶음 (SP-20 · 확정 창 confirm.py 의 한도와 같다)
MANIFEST_NAME = "MANIFEST.md"
BUNDLE_FILE_RE = re.compile(r"^F[0-9]{2,4}\.[A-Za-z0-9]{1,8}\Z")
BUNDLE_FILE_TYPES = ("doc", "table", "code")
MAX_BUNDLE_FILES = 20
MAX_BUNDLE_FILE_BYTES = 256 * 1024
MAX_BUNDLE_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024


class TransportError(Exception):
    """건네지 못했다 — 부르는 쪽은 보냈다고 기록하지 않는다 (AL-03). 글 · 경로를 담지 않는다."""


def check_job(job):
    if not isinstance(job, str) or not JOB_RE.match(job):
        raise TransportError("job 꼴")
    return job


def check_route(route):
    """route → {"model": str, "effort": str}. 두 값 밖의 칸이 있으면 TransportError."""
    if route is None:
        route = {}
    if not isinstance(route, dict) or set(route) - ROUTE_KEYS:
        raise TransportError("route 꼴")
    model = route.get("model", "")
    effort = route.get("effort", "")
    if not isinstance(model, str) or len(model) > 200 or any(ch in model for ch in "\r\n\x00"):
        raise TransportError("route 꼴")
    if effort not in EFFORTS:
        raise TransportError("route 꼴")
    return {"model": model, "effort": effort}


def _write_exclusive(path, data):
    """path 에 새 파일로 쓴다 — 있으면 TransportError (덮어쓰지 않음). 임시 파일 → 링크 · 안 되면 xb."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".diode-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
            return
        except FileExistsError:
            raise TransportError("이미 있음")
        except OSError as e:
            if e.errno == errno.EEXIST:
                raise TransportError("이미 있음")
        try:
            with open(path, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            raise TransportError("이미 있음")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


class RoomTransport(object):
    name = "room"

    def __init__(self, room_dir):
        self.room_dir = room_dir

    def check(self):
        st = room_state(self.room_dir)
        ok = st == "ok" and os.path.isdir(os.path.join(self.room_dir, "outbox")) \
            and os.path.isdir(os.path.join(self.room_dir, "inbox"))
        return {"ok": ok, "room": st, "effort": True}

    def put(self, job, sealed_text, route):
        check_job(job)
        check_route(route)              # 받기만 한다 — 봉인 글에도 파일에도 쓰지 않는다
        if not isinstance(sealed_text, str) or not sealed_text:
            raise TransportError("봉인 글 꼴")
        data = sealed_text.encode("utf-8")
        if len(data) > MAX_SEALED_BYTES:
            raise TransportError("봉인 글이 너무 크다")
        if room_state(self.room_dir) != "ok":
            raise TransportError("방이 ok 가 아님")
        box = os.path.join(self.room_dir, "outbox")
        if not os.path.isdir(box) or os.path.islink(box):
            raise TransportError("outbox 없음")
        _write_exclusive(os.path.join(box, job + ".md"), data)

    def put_bundle(self, job, manifest_text, files):
        """확정한 가린 묶음을 방 outbox/<job>/ 에 쓴다 (파일들 + MANIFEST.md). 하나라도 틀리면 TransportError · 아무것도 남기지 않는다.

        임시 폴더 (outbox/.<job>.tmp-<무작위>/ · 점으로 시작해 inbox 목록에 끼지 않는다) 에 파일마다 새로 쓰고 (fsync) →
        os.rename 으로 outbox/<job>/ 에 한 번에 이름을 붙인다. 이름이 이미 있으면 (폴더 · 파일 · 링크) 실패한다 — 미리 보고,
        그 사이에 생긴 것도 rename 이 덮어쓰지 않는다 (Windows 는 있으면 실패 · POSIX 는 비지 않은 폴더 · 파일 위로는 실패.
        빈 폴더 하나는 POSIX 가 바꿔치기할 수 있으나 잃는 내용이 없다). 실패하면 남은 임시 폴더를 지운다.
        """
        check_job(job)
        entries = _bundle_entries(manifest_text, files)
        if room_state(self.room_dir) != "ok":
            raise TransportError("방이 ok 가 아님")
        box = os.path.join(self.room_dir, "outbox")
        if not os.path.isdir(box) or os.path.islink(box):
            raise TransportError("outbox 없음")
        target = os.path.join(box, job)
        if os.path.lexists(target):
            raise TransportError("이미 있음")
        tmp = tempfile.mkdtemp(prefix="." + job + ".tmp-", dir=box)
        try:
            for name, data in entries:
                fd = os.open(os.path.join(tmp, name), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                             0o644)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            if os.path.lexists(target):
                raise TransportError("이미 있음")
            try:
                os.rename(tmp, target)
            except OSError:
                raise TransportError("이미 있음")
        except OSError:
            raise TransportError("쓰지 못함")
        finally:
            if os.path.isdir(tmp) and not os.path.islink(tmp):
                shutil.rmtree(tmp, ignore_errors=True)

    def get(self, job):
        check_job(job)
        path = os.path.join(self.room_dir, "inbox", job + ".md")
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            raw = f.read(MAX_ANSWER_BYTES + 1)
        if len(raw) > MAX_ANSWER_BYTES:
            raise TransportError("답이 너무 크다")
        return raw.decode("utf-8")


def _bundle_entries(manifest_text, files):
    """put_bundle 의 입력 → [(이름, 바이트)] (MANIFEST.md 가 마지막). 꼴 · 한도 (확정 창과 같다) 가 틀리면 TransportError."""
    if not isinstance(manifest_text, str) or not manifest_text:
        raise TransportError("MANIFEST 꼴")
    try:
        manifest = manifest_text.encode("utf-8")
    except UnicodeEncodeError:
        raise TransportError("MANIFEST 꼴")
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise TransportError("MANIFEST 가 너무 크다")
    if not isinstance(files, (list, tuple)) or not 1 <= len(files) <= MAX_BUNDLE_FILES:
        raise TransportError("묶음 꼴")
    out, seen, total = [], set(), 0
    for f in files:
        if not isinstance(f, dict) or set(f) != {"name", "type", "text"}:
            raise TransportError("묶음 꼴")
        name, text = f["name"], f["text"]
        if not isinstance(name, str) or not BUNDLE_FILE_RE.match(name) or name.lower() in seen \
                or f["type"] not in BUNDLE_FILE_TYPES or not isinstance(text, str) or not text:
            raise TransportError("묶음 꼴")
        seen.add(name.lower())
        try:
            data = text.encode("utf-8")
        except UnicodeEncodeError:
            raise TransportError("묶음 꼴")
        total += len(data)
        if len(data) > MAX_BUNDLE_FILE_BYTES or total > MAX_BUNDLE_BYTES:
            raise TransportError("묶음이 너무 크다")
        out.append((name, data))
    out.append((MANIFEST_NAME, manifest))
    return out


class ClipboardTransport(object):
    """확정 창이 복사 단추로 건넨다 (다른 작업 T10). 여기서는 계약의 이름 · check 만."""
    name = "clipboard"

    def check(self):
        return {"ok": True, "effort": True, "copy": "confirm"}

    def put(self, job, sealed_text, route):
        raise TransportError("clipboard 는 확정 창이 복사한다")

    def put_bundle(self, job, manifest_text, files):
        raise TransportError("가린 묶음은 방으로만 간다")

    def get(self, job):
        raise TransportError("clipboard 의 답은 확정 창의 답 칸으로 받는다")


def get_transport(name, room_dir=None):
    """설정 transport.default 의 이름 → 구현. 모르는 이름 · 방 자리 없음 → TransportError (adapter 는 사내에서)."""
    if name == "room":
        if not room_dir:
            raise TransportError("방 자리 없음")
        return RoomTransport(room_dir)
    if name == "clipboard":
        return ClipboardTransport()
    raise TransportError("모르는 건네기")
