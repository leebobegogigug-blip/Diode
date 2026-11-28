# -*- coding: utf-8 -*-
"""가명 금고 (vault) 와 작업 묶음 (project) — SP-20 · AL-05 · W-05 · W-06 (표준 라이브러리 · Python 3.8).

작업 묶음 하나에 금고 하나다. 같은 묶음 안에서는 같은 (진짜 값, 종류) 가 같은 토큰이고, 묶음이 다르면 다른 토큰이다.
금고는 묶음을 닫을 때까지 데이터 폴더에 남는다 — 세션이 끝나도 되돌리기가 이어지게 (9판 · 사용자 결정 2026-11-26).

자리 (데이터 폴더 아래 · 훅의 데이터 폴더 보호가 덮는다 · SP-11 · AL-12)
  vault/P-0001.vault   금고 — 머리 `DIODE-VAULT-1\\n` · 표지 `dpapi\\n` 또는 `plain\\n` · 본문 (내용 JSON 을 감싼 것)
  vault/P-0001.lock    잠금 (O_EXCL · 안에 pid 와 시각) — 읽기-고치기-쓰기를 한 번에 하나만
  vault/active         열린 묶음의 번호 한 줄 (열린 묶음은 하나뿐)
  vault/next           다음 번호 (정수 한 줄) — 닫은 번호도 다시 쓰지 않게

내용 JSON (format 1)
  {"format": 1, "project": "P-0001", "entries": [{"token", "real", "kind"}], "files": [{"name", "real"}],
   "sent_bytes": n, "halted": false}

암호화 (W-05 — 평문 금고는 기본 자리에 쓰지 않는다)
  - Windows: DPAPI (`CryptProtectData` · 현재 사용자 범위 · CRYPTPROTECT_UI_FORBIDDEN · 보조 엔트로피 = 묶음 번호).
    DPAPI 는 계정 단위다 — 같은 Windows 계정으로 도는 프로그램은 금고를 풀 수 있다 (SP-20 › 남는 위험).
  - 그 밖의 OS: 데이터 폴더가 기본 자리가 아닐 때 (시험용 DIODE_HOME) 만 평문 (0600) 을 허락한다.
    기본 자리에서는 묶음을 열지도 (open_project) 금고를 쓰지도 (Vault.locked) 않는다 (E-20 · 이 OS 에서는 암호화할 수 없다).

깨짐 (W-06): 읽기 실패 · 모르는 머리 · 모르는 format · 풀리지 않는 암호문 · 꼴 틀림 → 금고를 `.broken` (덮어쓰지 않게 번호) 으로
옮기고 E-20. 새 금고를 조용히 만들지 않는다 — 되돌리기를 잃었다는 사실을 숨기지 않는다. 열린 묶음은 그대로 두므로
`project close` 로 닫고 새로 연다 (금고가 없는 묶음을 닫으면 토큰 수 0).

출력 · 예외에는 진짜 값 · 원래 파일 이름 · 경로가 없다 (AL-11 · AL-14) — 번호 · 개수 · 오류 번호 · 고정 문구뿐이다.
금고 객체는 직렬화 (pickle · copy) 를 막고 repr 은 개수만 보인다 (seal.PseudonymTable 과 같다).
"""

import contextlib
import json
import os
import re
import secrets
import sys
import tempfile
import time

from .scan import TOKEN_ALPHABET, TOKEN_RE
from .textnorm import dict_key

# ---------------------------------------------------------------- 상수 (코드가 정한다 · 설정 키로 풀리지 않는다)

FORMAT = 1
KINDS = ("word", "number", "path", "ident")
MAX_PROJECT_TOKENS = 20000              # 한 묶음의 토큰 상한 (SP-20)
MAX_PROJECT_BYTES = 8 * 1024 * 1024     # 한 묶음이 보낸 바이트 누계 상한 (넘으면 E-31 · SP-20 [제안])
MAX_PROJECT_FILES = 2000                # 한 묶음의 나가는 파일 이름 상한 (F01 … F2000)
MAX_REAL_CHARS = 512                    # 진짜 값 하나의 길이 (SP-20 › 가리기 표시와 같게)
MAX_FILE_REAL_CHARS = 1024              # 원래 상대 경로의 길이
MAX_PROJECT_NUMBER = 9999               # P-0001 … P-9999
MAX_VAULT_FILE_BYTES = 64 * 1024 * 1024  # 금고 파일을 이보다 크게 읽지 않는다 (넘으면 깨짐)

VAULT_DIR = "vault"
ACTIVE_NAME = "active"
NEXT_NAME = "next"
VAULT_SUFFIX = ".vault"
LOCK_SUFFIX = ".lock"
HEADER = b"DIODE-VAULT-1\n"
MARK_DPAPI = b"dpapi"
MARK_PLAIN = b"plain"

LOCK_WAIT_S = 10.0                      # 잠금을 이만큼 기다리면 E-20
LOCK_POLL_S = 0.1                       # 잠금을 다시 보는 간격
LOCK_STALE_S = 60.0                     # 잠금 파일의 시각이 이보다 오래면 끊긴 프로세스의 것으로 보고 지운다 (알린다)
REPLACE_TRIES = 10                      # Windows 에서 읽는 쪽이 파일을 잡고 있으면 바꿔치기가 잠깐 실패한다
REPLACE_PAUSE_S = 0.05
OPEN_TRIES = 5                          # 번호를 고르는 사이에 다른 프로세스가 그 번호를 쓰면 다시 고른다
TOKEN_TRIES = 1000

CRYPTPROTECT_UI_FORBIDDEN = 0x1

E_SHAPE = "E-04"                        # 꼴 · 이미 열린 묶음
E_INTERNAL = "E-20"                     # 검사 · 내부 오류 (막는 쪽으로)
E_LIMIT = "E-31"                        # 한도 (토큰 · 바이트 · 파일 · 번호)
E_NO_PROJECT = "E-33"                   # 열린 작업 묶음이 없음
E_OFF = "E-30"                          # 표준 입력이 터미널이 아님 (사람이 직접 여는 문)

PROJECT_RE = re.compile(r"^P-([0-9]{4})\Z")
FILE_NAME_RE = re.compile(r"^F[0-9]{2,4}\.[A-Za-z0-9]{1,8}\Z")
_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,8}\Z")
_NEXT_RE = re.compile(r"^[0-9]{1,5}\Z")
_NUMBERED = re.compile(r"^\.?P-([0-9]{4})")     # 번호가 쓰인 흔적 (금고 · .broken · 잠금 · 임시 파일)
_CONTENT_KEYS = frozenset(["format", "project", "entries", "files", "sent_bytes", "halted"])
_ENTRY_KEYS = frozenset(["token", "real", "kind"])
_FILE_KEYS = frozenset(["name", "real"])


class VaultError(Exception):
    """코드 (.code: E-04 · E-20 · E-31 · E-33) 와 닫힌 까닭 (.reason: 짧은 ASCII 낱말) 만 담는다. 값 · 경로는 담지 않는다 (AL-11)."""

    def __init__(self, code, reason=None):
        Exception.__init__(self, code)
        self.code = code
        self.reason = reason


class _Broken(Exception):
    """금고 파일의 꼴이 틀렸다 (안에서만 쓴다 — 밖으로는 VaultError(E-20, "broken"))."""


# ---------------------------------------------------------------- 자리

def vault_dir(home):
    return os.path.join(home, VAULT_DIR)


def vault_path(home, project):
    return os.path.join(vault_dir(home), project + VAULT_SUFFIX)


def lock_path(home, project):
    return os.path.join(vault_dir(home), project + LOCK_SUFFIX)


def _active_path(home):
    return os.path.join(vault_dir(home), ACTIVE_NAME)


def _next_path(home):
    return os.path.join(vault_dir(home), NEXT_NAME)


def _project_id(n):
    return "P-%04d" % n


def can_protect():
    """이 OS 에서 금고를 암호화할 수 있나 (Windows DPAPI)."""
    return os.name == "nt"


def _guard_os(home_is_default):
    """평문 금고를 기본 자리에 쓰는 길을 닫는다 (W-05)."""
    if not can_protect() and home_is_default:
        raise VaultError(E_INTERNAL, "os")


def _ensure_dir(home):
    d = vault_dir(home)
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError:
        raise VaultError(E_INTERNAL, "io")
    return d


# ---------------------------------------------------------------- 파일 쓰기 (원자적 · config.py 와 같은 방법)

def _write_atomic(path, data, prefix):
    """임시 파일 (같은 폴더 · 0600) → fsync → 바꿔치기. 쓰다 끊겨도 반쯤 쓴 파일이 남지 않는다."""
    d = os.path.dirname(path)
    try:
        fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=d)
    except OSError:
        raise VaultError(E_INTERNAL, "io")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for i in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if i == REPLACE_TRIES - 1:
                    raise
                time.sleep(REPLACE_PAUSE_S)
    except BaseException as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(e, OSError):
            raise VaultError(E_INTERNAL, "io")
        raise


def _set_aside(path):
    """깨진 파일을 .broken 으로 옮긴다 (이미 있으면 번호 · 덮어쓰지 않는다)."""
    n = 0
    while n < 1000:
        dst = path + ".broken" + ("" if n == 0 else str(n))
        if not os.path.exists(dst):
            try:
                os.replace(path, dst)
            except OSError:
                raise VaultError(E_INTERNAL, "io")
            return dst
        n += 1
    raise VaultError(E_INTERNAL, "io")


def _remove(path):
    """지운다 (없으면 그만). Windows 에서 다른 프로세스가 잠깐 열고 있으면 몇 번 다시 한다. 끝내 못 지우면 OSError."""
    for i in range(REPLACE_TRIES):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if i == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_PAUSE_S)


def _wipe_remove(path):
    """같은 길이의 0 으로 덮어쓰고 지운다.

    완벽한 지우기는 보장하지 못한다 — SSD 의 마모 평준화 · 저널링 파일 체계 · 볼륨 섀도 복사본 · 백업 · 동기화 폴더에는
    옛 바이트가 남을 수 있다. 덮어쓰기는 덤이고, 약속하는 것은 '이 자리에서 금고 파일이 없어진다' 뿐이다.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            left = size
            zero = b"\0" * 65536
            while left > 0:
                n = min(left, len(zero))
                f.write(zero[:n])
                left -= n
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        return
    except OSError:
        pass
    try:
        _remove(path)
    except OSError:
        raise VaultError(E_INTERNAL, "io")


# ---------------------------------------------------------------- 번호 파일 (active · next)

def _read_small(path):
    """작은 ASCII 파일 한 줄 → 글 (없으면 None). 못 읽으면 E-20."""
    try:
        with open(path, "rb") as f:
            raw = f.read(64)
    except FileNotFoundError:
        return None
    except OSError:
        raise VaultError(E_INTERNAL, "io")
    try:
        return raw.decode("ascii").strip()
    except UnicodeDecodeError:
        return ""


def _read_active(home):
    s = _read_small(_active_path(home))
    if s is None:
        return None
    m = PROJECT_RE.match(s)
    if not m or int(m.group(1)) < 1:
        raise VaultError(E_INTERNAL, "broken")
    return s


def active_project(home):
    """열린 묶음의 번호 ("P-0001") 또는 None. 읽기만 한다. active 파일의 꼴이 틀리면 VaultError(E-20)."""
    return _read_active(home)


def _used_max(home):
    """vault/ 에 번호가 쓰인 흔적 중 가장 큰 번호 (없으면 0)."""
    try:
        names = os.listdir(vault_dir(home))
    except FileNotFoundError:
        return 0
    except OSError:
        raise VaultError(E_INTERNAL, "io")
    used = [int(m.group(1)) for m in (_NUMBERED.match(n) for n in names if not n.endswith(LOCK_SUFFIX)) if m]
    return max(used) if used else 0


def _next_number(home):
    """다음에 쓸 번호: next 파일과 남은 흔적 중 큰 쪽. next 가 깨졌으면 .broken 으로 옮기고 E-20."""
    s = _read_small(_next_path(home))
    stored = 1
    if s is not None:
        if not _NEXT_RE.match(s) or not (1 <= int(s) <= MAX_PROJECT_NUMBER + 1):
            _set_aside(_next_path(home))
            raise VaultError(E_INTERNAL, "broken")
        stored = int(s)
    n = max(stored, _used_max(home) + 1)
    if n > MAX_PROJECT_NUMBER:
        raise VaultError(E_LIMIT, "number")
    return n


# ---------------------------------------------------------------- 잠금

class _Lock(object):
    """<vault>/P-0001.lock — O_CREAT|O_EXCL 로 만든 쪽이 잡는다. 안에 pid 와 시각을 적는다.

    LOCK_WAIT_S 동안 LOCK_POLL_S 간격으로 기다리고, 못 잡으면 E-20. 시각이 LOCK_STALE_S 보다 오래된 잠금은
    끊긴 프로세스의 것으로 보고 지우되 notice("stale_lock") 로 알린다 (숨기지 않는다).
    지우기 직전에 내용을 다시 읽어 같을 때만 지운다 — 그래도 두 프로세스가 같은 순간에 같은 오래된 잠금을 보면
    틈이 아주 짧게 남는다 (같은 계정의 PC 안 잠금은 벽이 아니다 · 일꾼 · 허브 · 사람 명령이 엇갈리는 것을 막는 장치다).
    잠금은 짧게 잡는다 — 확정 창 · D7 처럼 사람이나 바깥을 기다리는 일을 잠금 안에서 하지 않는다 (60초 넘으면 남이 지운다).
    """

    def __init__(self, path, notice=None):
        self.path = path
        self.notice = notice
        self.held = False
        self.stale_removed = False

    def _stale(self):
        """(오래됐나, 읽은 내용)."""
        try:
            with open(self.path, "rb") as f:
                raw = f.read(128)
        except FileNotFoundError:
            return False, None
        except OSError:
            return False, None
        t = None
        try:
            parts = raw.decode("ascii").split()
            if len(parts) == 2:
                t = float(parts[1])
        except (UnicodeDecodeError, ValueError):
            t = None
        if t is None:                                   # 막 만들어 아직 적지 않았거나 깨진 내용 → 파일 시각
            try:
                t = os.path.getmtime(self.path)
            except OSError:
                return False, None
        return abs(time.time() - t) > LOCK_STALE_S, raw

    def _remove_if_same(self, raw):
        try:
            with open(self.path, "rb") as f:
                if f.read(128) != raw:
                    return False
            _remove(self.path)
            return True
        except OSError:
            return False

    def acquire(self):
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
            except FileExistsError:
                stale, raw = self._stale()
                if stale and self._remove_if_same(raw):
                    self.stale_removed = True
                    if self.notice is not None:
                        try:
                            self.notice("stale_lock")
                        except Exception:
                            pass
                    continue
            except PermissionError:                     # Windows: 지우는 중인 파일
                pass
            except OSError:
                raise VaultError(E_INTERNAL, "io")
            else:
                try:
                    try:
                        os.write(fd, ("%d %.3f\n" % (os.getpid(), time.time())).encode("ascii"))
                    finally:
                        os.close(fd)
                except OSError:
                    try:
                        _remove(self.path)
                    except OSError:
                        pass
                    raise VaultError(E_INTERNAL, "io")
                self.held = True
                return self
            if time.monotonic() >= deadline:
                raise VaultError(E_INTERNAL, "lock")
            time.sleep(LOCK_POLL_S)

    def release(self):
        if self.held:
            self.held = False
            try:
                _remove(self.path)
            except OSError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


# ---------------------------------------------------------------- 암호화 (Windows DPAPI · ctypes)

class _DpapiError(Exception):
    pass


def _dpapi(data, entropy, protect):
    """CryptProtectData / CryptUnprotectData — 현재 사용자 범위 · 창을 띄우지 않음 · 보조 엔트로피.

    반환 버퍼는 LocalFree 로 돌려준다. 우리가 만든 평문 사본 버퍼는 돌려주기 전에 0 으로 덮는다 (덤 — Python 의 bytes 는 지울 수 없다).
    """
    if os.name != "nt":
        raise _DpapiError()
    import ctypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
    fn.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    in_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
    blob_in = _Blob(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_ent = _Blob(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    try:
        ok = fn(ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None,
                CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok or not blob_out.pbData:
            raise _DpapiError()
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            if not protect:
                ctypes.memset(blob_out.pbData, 0, blob_out.cbData)
            kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
    finally:
        if protect:
            ctypes.memset(in_buf, 0, len(data))


def protect(data, entropy):
    """DPAPI 로 감싼다 (Windows 만 · 아니면 _DpapiError)."""
    return _dpapi(data, entropy, True)


def unprotect(data, entropy):
    """DPAPI 로 푼다. 엔트로피 · 계정이 다르거나 깨졌으면 _DpapiError."""
    return _dpapi(data, entropy, False)


def _encode(project, payload):
    if can_protect():
        try:
            body = protect(payload, project.encode("ascii"))
        except Exception:
            raise VaultError(E_INTERNAL, "io")
        return HEADER + MARK_DPAPI + b"\n" + body
    return HEADER + MARK_PLAIN + b"\n" + payload


def _decode(raw, project):
    """파일 바이트 → (내용 dict, DPAPI 로 감쌌나). 꼴이 틀리면 _Broken."""
    if not raw.startswith(HEADER):
        raise _Broken()
    rest = raw[len(HEADER):]
    nl = rest.find(b"\n")
    if nl < 0:
        raise _Broken()
    mark, body = rest[:nl], rest[nl + 1:]
    if mark == MARK_DPAPI:
        if not can_protect():
            raise _Broken()
        try:
            payload = unprotect(body, project.encode("ascii"))
        except Exception:
            raise _Broken()
        protected = True
    elif mark == MARK_PLAIN:
        if can_protect():                       # Windows 에서는 평문을 쓰지 않는다 — 있으면 깨진 것으로
            raise _Broken()
        payload, protected = body, False
    else:
        raise _Broken()
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _Broken()
    return obj, protected


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _real_ok(s, limit):
    return isinstance(s, str) and bool(s.strip()) and len(s) <= limit and "\x00" not in s


def _parse(obj, project):
    """내용 dict 를 엄격하게 본다 → (by_token, by_real, files, sent, halted). 꼴이 틀리면 _Broken."""
    if not isinstance(obj, dict) or set(obj) != _CONTENT_KEYS:
        raise _Broken()
    if not _is_int(obj["format"]) or obj["format"] != FORMAT or obj["project"] != project:
        raise _Broken()
    entries, files, sent, halted = obj["entries"], obj["files"], obj["sent_bytes"], obj["halted"]
    if not isinstance(entries, list) or len(entries) > MAX_PROJECT_TOKENS:
        raise _Broken()
    if not isinstance(files, list) or len(files) > MAX_PROJECT_FILES:
        raise _Broken()
    if not _is_int(sent) or not (0 <= sent <= MAX_PROJECT_BYTES) or not isinstance(halted, bool):
        raise _Broken()
    by_token, by_real = {}, {}
    for e in entries:
        if not isinstance(e, dict) or set(e) != _ENTRY_KEYS:
            raise _Broken()
        tok, real, kind = e["token"], e["real"], e["kind"]
        if not isinstance(tok, str) or not TOKEN_RE.fullmatch(tok) or not _real_ok(real, MAX_REAL_CHARS) \
                or kind not in KINDS or tok in by_token or (real, kind) in by_real:
            raise _Broken()
        by_token[tok] = (real, kind)
        by_real[(real, kind)] = tok
    out_files, numbers, reals = [], set(), set()
    for f in files:
        if not isinstance(f, dict) or set(f) != _FILE_KEYS:
            raise _Broken()
        name, real = f["name"], f["real"]
        if not isinstance(name, str) or not FILE_NAME_RE.match(name) or not _real_ok(real, MAX_FILE_REAL_CHARS) \
                or _file_number(name) in numbers or real in reals:
            raise _Broken()
        numbers.add(_file_number(name))
        reals.add(real)
        out_files.append((name, real))
    return by_token, by_real, out_files, sent, halted


def _file_number(name):
    return int(name[1:name.index(".")])


def _load(home, project, move_broken=True):
    """금고 파일을 읽는다 → (내용 튜플, DPAPI 인가). 없으면 E-20 (missing · 새로 만들지 않는다).
    깨졌으면 move_broken 일 때 .broken 으로 옮기고 E-20 (broken) · 아니면 옮기지 않고 E-20 (unreadable)."""
    path = vault_path(home, project)
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_VAULT_FILE_BYTES + 1)
    except FileNotFoundError:
        raise VaultError(E_INTERNAL, "missing")
    except OSError:
        raise VaultError(E_INTERNAL, "io")
    try:
        if len(raw) > MAX_VAULT_FILE_BYTES:
            raise _Broken()
        obj, protected = _decode(raw, project)
        return _parse(obj, project), protected
    except _Broken:
        if move_broken:
            _set_aside(path)
            raise VaultError(E_INTERNAL, "broken")
        raise VaultError(E_INTERNAL, "unreadable")


# ---------------------------------------------------------------- 금고

_CREATE = object()


class Vault(object):
    """한 작업 묶음의 가명 금고. `with Vault.locked(home) as v:` 로만 연다 (잠금 안에서만 산다).

    with 블록을 나오면 (바뀌었으면) 원자적으로 저장하고 잠금을 풀고, 이 객체는 더 쓰지 못한다 (E-20).
    블록 안에서 예외가 나도 바뀐 것은 저장한다 — 이미 매긴 토큰 · 이름을 잃으면 되돌리기를 잃는다.
    저장이 실패하면 VaultError(E-20) — 부르는 쪽은 저장된 뒤에 바깥으로 쓴다 (outbox 는 with 블록을 나온 다음에).
    """

    __slots__ = ("_home", "_project", "_by_token", "_by_real", "_files", "_name_of", "_real_of_name",
                 "_sent", "_halted", "_dirty", "_open", "_protected", "stale_lock_removed")

    def __init__(self, key, home, project, parsed, protected):
        if key is not _CREATE:
            raise TypeError("금고는 Vault.locked 로만 연다")
        by_token, by_real, files, sent, halted = parsed
        self._home = home
        self._project = project
        self._by_token = by_token          # token -> (real, kind)
        self._by_real = by_real            # (real, kind) -> token
        self._files = list(files)          # [(name, real)] — 매긴 차례
        self._name_of = dict((r, n) for n, r in files)
        self._real_of_name = dict(files)
        self._sent = sent
        self._halted = halted
        self._dirty = False
        self._open = True
        self._protected = protected
        self.stale_lock_removed = False

    # ---- 직렬화 · 복사 막기 (PseudonymTable 과 같다)
    def __repr__(self):
        return "<Vault 토큰 %d개 · 파일 %d개>" % (len(self._by_token), len(self._files))

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("금고는 직렬화하지 않는다")

    def __reduce_ex__(self, protocol):
        raise TypeError("금고는 직렬화하지 않는다")

    def __copy__(self):
        raise TypeError("금고는 복사하지 않는다")

    def __deepcopy__(self, memo):
        raise TypeError("금고는 복사하지 않는다")

    def __len__(self):
        return len(self._by_token)

    def __contains__(self, token):
        return token in self._by_token

    def _check_open(self):
        if not self._open:
            raise VaultError(E_INTERNAL, "closed")

    # ---- 열기
    @classmethod
    @contextlib.contextmanager
    def locked(cls, home, home_is_default=True, notice=None):
        """잠금 → 읽기 → (블록) → 바뀌었으면 원자적 저장 → 잠금 풀기. 열린 묶음이 없으면 E-33.

        기본 자리 + 암호화할 수 없는 OS 면 E-20 (평문을 쓰지 않는다). 금고가 없거나 깨졌으면 E-20 (새로 만들지 않는다).
        halted 깃발이 서 있어도 연다 — 되돌리기를 막을지는 부르는 쪽이 정한다 (v.halted).
        """
        _guard_os(home_is_default)
        project = _read_active(home)
        if project is None:
            raise VaultError(E_NO_PROJECT, "none")
        _ensure_dir(home)
        lock = _Lock(lock_path(home, project), notice)
        with lock:
            if _read_active(home) != project:            # 기다리는 사이에 닫혔다
                raise VaultError(E_NO_PROJECT, "none")
            parsed, protected = _load(home, project)
            v = cls(_CREATE, home, project, parsed, protected)
            v.stale_lock_removed = lock.stale_removed
            failed = True
            try:
                yield v
                failed = False
            finally:
                try:
                    if v._dirty:
                        try:
                            v._save()
                        except Exception:
                            if not failed:
                                raise VaultError(E_INTERNAL, "io")
                finally:
                    v._close()

    def _payload(self):
        obj = {"format": FORMAT, "project": self._project,
               "entries": [{"token": t, "real": r, "kind": k} for t, (r, k) in self._by_token.items()],
               "files": [{"name": n, "real": r} for n, r in self._files],
               "sent_bytes": self._sent, "halted": self._halted}
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _save(self):
        _write_atomic(vault_path(self._home, self._project), _encode(self._project, self._payload()),
                      "." + self._project + "-")
        self._dirty = False

    def _close(self):
        self._open = False
        self._by_token = {}
        self._by_real = {}
        self._files = []
        self._name_of = {}
        self._real_of_name = {}

    # ---- 읽기
    @property
    def project(self):
        return self._project

    @property
    def sent_bytes(self):
        return self._sent

    @property
    def halted(self):
        return self._halted

    @property
    def protected(self):
        """DPAPI 로 감싼 금고인가."""
        return self._protected

    def tokens(self):
        self._check_open()
        return frozenset(self._by_token)

    def real_of(self, token):
        """안쪽 전용. (real, kind) 또는 None."""
        self._check_open()
        return self._by_token.get(token)

    def reals(self, min_len=2):
        """안쪽 전용 — 자동 가림 · 잔여 검사 R2 가 진짜 값을 사전처럼 보는 데만 쓴다.
        정규화한 글자 (dict_key) 가 min_len 이상인 서로 다른 값 · 긴 것부터."""
        self._check_open()
        vals = set(r for r, _ in self._by_token.values() if len(dict_key(r)) >= min_len)
        return sorted(vals, key=lambda s: (-len(s), s))

    def file_real(self, name):
        """나가는 이름 (F01.md) → 원래 상대 경로 · 모르면 None. 안쪽 전용."""
        self._check_open()
        return self._real_of_name.get(name) if isinstance(name, str) else None

    # ---- 고치기
    def _new_token(self):
        for _ in range(TOKEN_TRIES):
            t = "PH_" + "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4))
            if t not in self._by_token:
                return t
        raise VaultError(E_INTERNAL, "token")

    def token_for(self, real, kind="word"):
        """같은 (real, kind) → 같은 토큰. 처음이면 secrets 로 뽑는다 (해시 금지 · 금고 안에서 겹치지 않게).
        꼴이 틀리면 ValueError · 상한 (MAX_PROJECT_TOKENS) 이면 VaultError(E-31)."""
        self._check_open()
        if not _real_ok(real, MAX_REAL_CHARS):
            raise ValueError("값의 꼴")
        if kind not in KINDS:
            raise ValueError("종류")
        key = (real, kind)
        tok = self._by_real.get(key)
        if tok is not None:
            return tok
        if len(self._by_token) >= MAX_PROJECT_TOKENS:
            raise VaultError(E_LIMIT, "tokens")
        tok = self._new_token()
        self._by_token[tok] = key
        self._by_real[key] = tok
        self._dirty = True
        return tok

    def file_name(self, real_path, ext):
        """원래 상대 경로 → 나가는 이름 (F03.py). 같은 경로면 이미 매긴 이름 그대로 (확장자가 달라도),
        처음이면 다음 빈 번호 (F01 … F99 · F100 …). ext 는 점 없는 영숫자 1–8자 — 아니면 ValueError.
        상한 (MAX_PROJECT_FILES) 이면 VaultError(E-31)."""
        self._check_open()
        if not isinstance(ext, str) or not _EXT_RE.match(ext):
            raise ValueError("확장자의 꼴")
        if not _real_ok(real_path, MAX_FILE_REAL_CHARS):
            raise ValueError("경로의 꼴")
        name = self._name_of.get(real_path)
        if name is not None:
            return name
        if len(self._files) >= MAX_PROJECT_FILES:
            raise VaultError(E_LIMIT, "files")
        n = max([_file_number(x) for x, _ in self._files] or [0]) + 1
        name = "F%02d.%s" % (n, ext)
        if not FILE_NAME_RE.match(name):
            raise VaultError(E_LIMIT, "files")
        self._files.append((name, real_path))
        self._name_of[real_path] = name
        self._real_of_name[name] = real_path
        self._dirty = True
        return name

    def add_sent(self, n):
        """보낸 바이트를 누계에 더한다. 누계가 MAX_PROJECT_BYTES 를 넘으면 더하지 않고 VaultError(E-31)."""
        self._check_open()
        if not _is_int(n) or n < 0:
            raise ValueError("바이트 수")
        if self._sent + n > MAX_PROJECT_BYTES:
            raise VaultError(E_LIMIT, "bytes")
        if n:
            self._sent += n
            self._dirty = True

    def halt(self):
        """깃발을 세운다 (U2 — Claude 가 가린 값을 맞혔을 때 허브가 부른다 · 저장된다). 내리는 것은 사람의 `project resume` 뿐."""
        self._check_open()
        if not self._halted:
            self._halted = True
            self._dirty = True

    def _resume(self):
        self._check_open()
        if self._halted:
            self._halted = False
            self._dirty = True


# ---------------------------------------------------------------- 묶음 열기 · 닫기 · 상태

def _empty_parsed():
    return {}, {}, [], 0, False


def open_project(home, home_is_default, notice=None):
    """새 묶음을 열고 active 로 → 번호 ("P-0001"). 이미 열려 있으면 VaultError(E-04).

    기본 자리 + 암호화할 수 없는 OS 면 E-20 (파일을 하나도 만들지 않는다). 순서: next 를 먼저 올리고 → 빈 금고 → active.
    중간에 끊기면 번호 하나를 건너뛸 뿐이다 (빈 금고가 남을 수 있으나 진짜 값은 없다).
    """
    _guard_os(home_is_default)
    if _read_active(home) is not None:
        raise VaultError(E_SHAPE, "open")
    _ensure_dir(home)
    for _ in range(OPEN_TRIES):
        n = _next_number(home)
        project = _project_id(n)
        with _Lock(lock_path(home, project), notice):
            if _read_active(home) is not None:
                raise VaultError(E_SHAPE, "open")
            if _next_number(home) != n:                 # 기다리는 사이에 남이 이 번호를 썼다
                continue
            _write_atomic(_next_path(home), ("%d\n" % (n + 1)).encode("ascii"), ".next-")
            v = Vault(_CREATE, home, project, _empty_parsed(), can_protect())
            v._save()
            v._close()
            _write_atomic(_active_path(home), (project + "\n").encode("ascii"), ".active-")
            return project
    raise VaultError(E_INTERNAL, "lock")


def _temp_files(home, project):
    prefix = "." + project + "-"
    try:
        return [os.path.join(vault_dir(home), n) for n in os.listdir(vault_dir(home))
                if n.startswith(prefix) and n.endswith(".tmp")]
    except OSError:
        return []


def close_project(home, notice=None):
    """열린 묶음을 닫는다 → (번호, 토큰 수). 금고 파일 (과 남은 임시 파일) 을 0 으로 덮고 지운 뒤 active 를 지운다.
    이 묶음의 토큰은 다시 되돌릴 수 없게 된다. 열린 묶음이 없으면 E-33.

    금고가 없으면 (앞서 깨져 .broken 으로 옮겼거나) 토큰 수 0 으로 닫는다. 금고가 깨졌으면 .broken 으로 옮기고 E-20
    (다시 닫으면 닫힌다). .broken 파일은 지우지 않는다 (W-06).
    active 파일의 꼴이 틀리면 그것을 .broken 으로 옮기고 E-20 — 다음 open 이 새 번호로 연다.
    """
    try:
        project = _read_active(home)
    except VaultError as e:
        if e.reason == "broken":
            _set_aside(_active_path(home))
        raise
    if project is None:
        raise VaultError(E_NO_PROJECT, "none")
    with _Lock(lock_path(home, project), notice):
        if _read_active(home) != project:
            raise VaultError(E_NO_PROJECT, "none")
        path = vault_path(home, project)
        tokens = 0
        if os.path.exists(path):
            parsed, _ = _load(home, project)
            tokens = len(parsed[0])
            _wipe_remove(path)
        for tmp in _temp_files(home, project):
            _wipe_remove(tmp)
        try:
            _remove(_active_path(home))
        except OSError:
            raise VaultError(E_INTERNAL, "io")
    return project, tokens


def resume_project(home, home_is_default=True, notice=None):
    """halted 깃발을 내린다 (사람이 터미널에서 `project resume`) → 번호. 서 있지 않았어도 같은 답이다."""
    with Vault.locked(home, home_is_default, notice) as v:
        v._resume()
        return v.project


def project_status(home):
    """{"project": "P-0001" | None, "tokens", "files", "sent_bytes", "protected", "halted"} — 번호 · 개수 · 참거짓뿐.

    읽기만 한다 (잠그지 않는다 — 쓰는 쪽이 원자적으로 바꿔치기하므로 옛것이나 새것 하나를 본다). 금고가 없거나 깨졌으면
    옮기지 않고 VaultError(E-20) — 옮기는 일은 다음 Vault.locked · close 가 한다.
    """
    project = _read_active(home)
    if project is None:
        return {"project": None, "tokens": 0, "files": 0, "sent_bytes": 0, "protected": False, "halted": False}
    parsed, protected = _load(home, project, move_broken=False)
    by_token, _, files, sent, halted = parsed
    return {"project": project, "tokens": len(by_token), "files": len(files), "sent_bytes": sent,
            "protected": protected, "halted": halted}


# ---------------------------------------------------------------- 명령 (diode.py project open|close|status|resume)

ACTIONS = ("open", "close", "status", "resume")
TERMINAL_ACTIONS = ("open", "close", "resume")       # 사람이 안쪽 터미널에서만 (일꾼이 부르는 길이 아니다)
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CONFIRM = 0, 1, 2, 3
RESULT = {EXIT_OK: "결과: OK", EXIT_CONFIRM: "결과: 확인 필요", EXIT_FAIL: "결과: 점검 실패"}
EXIT_OF = {E_OFF: EXIT_CONFIRM, E_SHAPE: EXIT_CONFIRM, E_NO_PROJECT: EXIT_CONFIRM, E_INTERNAL: EXIT_FAIL, E_LIMIT: EXIT_FAIL}

# 사람에게 보이는 고정 안내 (표준 오류 · 번호 · 개수 · 값 · 경로 없음)
NOTE = {
    "terminal": "작업 묶음은 사람이 안쪽 PC 의 터미널에서 직접 열고 닫습니다 - 표준 입력이 터미널이 아닙니다 (E-30)",
    "open": "이미 열린 작업 묶음이 있습니다 - 먼저 project close 로 닫으세요 (E-04)",
    "none": "열린 작업 묶음이 없습니다 (E-33)",
    "os": "이 OS 에서는 금고를 암호화할 수 없습니다 - 작업 묶음은 Windows 에서 엽니다 (E-20)",
    "broken": "금고를 읽지 못해 .broken 으로 옮겼습니다 - 이 묶음의 가리기 · 되돌리기를 막습니다. project close 로 닫으세요 (E-20)",
    "unreadable": "금고를 읽지 못했습니다 - 이 묶음의 가리기 · 되돌리기를 막습니다. project close 로 닫으세요 (E-20)",
    "missing": "금고 파일이 없습니다 - 이 묶음의 가리기 · 되돌리기를 막습니다. project close 로 닫으세요 (E-20)",
    "lock": "금고 잠금을 얻지 못했습니다 - 다른 diode 가 쓰는 중입니다. 잠시 뒤에 다시 하세요 (E-20)",
    "io": "금고 자리를 읽거나 쓰지 못했습니다 (E-20)",
    "number": "작업 묶음 번호를 다 썼습니다 (E-31)",
    "stale_lock": "60초 넘은 금고 잠금을 지웠습니다 - 앞서 돌던 diode 가 끊겼을 수 있습니다",
    "closed": "금고를 지웠습니다 - 이 묶음의 토큰은 다시 되돌릴 수 없습니다 (디스크에 남은 옛 바이트까지 없앤다고 보장하지는 못합니다)",
    "halted": "이 묶음은 멈춰 있습니다 (Claude 의 글에 가린 값이 나왔습니다) - 확인한 뒤 project resume 으로 풉니다",
}


def _line(obj):
    return json.dumps(obj, ensure_ascii=False)


def _note(err, key):
    text = NOTE.get(key)
    if text:
        err.write(text + "\n")


def run_command(action, home_info, inp, out, err):
    """diode.py project 의 몸통 → 종료 코드. 표준 출력은 JSON 한 줄 + `결과:` 줄 (S-03), 표준 오류는 고정 안내.

    open · close · resume 은 표준 입력이 사람의 터미널이어야 한다 (derive.stdin_is_terminal — 아니면 E-30 · 3).
    출력에는 번호 · 개수 · 참거짓 · 오류 번호뿐이다 — 진짜 값 · 원래 파일 이름 · 경로가 없다 (AL-11).
    """
    from . import derive
    home, default = home_info
    if action not in ACTIONS:                       # diode.py 가 먼저 사용법 오류로 거른다
        err.write("project 는 open · close · status · resume 중 하나를 씁니다\n")
        return EXIT_USAGE

    def notice(key):
        _note(err, key)

    try:
        if action in TERMINAL_ACTIONS:
            stream = inp if inp is not None else sys.stdin
            if not derive.stdin_is_terminal(stream):
                out.write(_line({"project": False, "error": E_OFF}) + "\n" + RESULT[EXIT_CONFIRM] + "\n")
                _note(err, "terminal")
                return EXIT_CONFIRM
        if action == "open":
            obj = {"project": open_project(home, default, notice)}
        elif action == "close":
            project, tokens = close_project(home, notice)
            obj = {"closed": project, "tokens": tokens}
            _note(err, "closed")
        elif action == "resume":
            obj = {"resumed": resume_project(home, default, notice)}
        else:
            obj = project_status(home)
            if obj.get("halted"):
                _note(err, "halted")
    except VaultError as e:
        code = EXIT_OF.get(e.code, EXIT_FAIL)
        out.write(_line({"project": False, "error": e.code}) + "\n" + RESULT[code] + "\n")
        _note(err, e.reason)
        return code
    except Exception:
        out.write(_line({"project": False, "error": E_INTERNAL}) + "\n" + RESULT[EXIT_FAIL] + "\n")
        _note(err, "io")
        return EXIT_FAIL
    out.write(_line(obj) + "\n" + RESULT[EXIT_OK] + "\n")
    return EXIT_OK
