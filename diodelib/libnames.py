# -*- coding: utf-8 -*-
"""허용 라이브러리의 공개 이름 목록 만들기 — `diode.py lib names <이름>` (SP-05 D5a · SP-16 · 표준 라이브러리 · Python 3.8).

D5a (lib 의 합성 재현 코드) 와 `error.type` 검사는 허용 라이브러리의 공개 이름만 공개 이름으로 인정한다. 그 목록을 안쪽 PC 에
설치된 판에서 뽑아 데이터 폴더의 `libnames/<소문자 이름>.json` 으로 쓴다 (`scan.policy_from_home` 이 읽는다):

    {"format": 1, "library": "<이름>", "version": "<설치된 판 · 모르면 빈 글>", "names": [정렬된 목록], "truncated": false}

- 이름은 설정 `policy.lib_allow` 에 있는 것만 받는다 (대소문자 무시). 사람이 안쪽 PC 에서 돌리는 명령이다 - Claude 에게 노출되는 길이 아니다.
- 라이브러리는 **별도 프로세스** 에서 불러온다 (`sys.executable -E -c <코드>` · 인자 목록 · 셸 없음 · 시간 상한 · 출력 상한).
  부모는 그 프로세스의 표준 출력 한 줄만 읽고 검증한다. 하위 프로세스의 표준 오류는 버린다 (라이브러리가 경로를 찍을 수 있다).
  `-I` 대신 `-E` 를 쓰는 까닭: `-I` 는 사용자 site-packages (`pip install --user`) 를 빼서, 관리자 권한 없이 깐 라이브러리를 못 찾는다.
  환경 변수 (PYTHONPATH 등) 는 `-E` 가 막고, 작업 폴더가 검색 경로에 끼는 것은 하위 프로세스 코드가 직접 뺀다.
- 모으는 범위 (실행 범위를 좁게): 모듈의 공개 속성 (`_` 로 시작하지 않는 것) · 그 라이브러리 **안의**, **이미 불러와진** 하위 모듈과
  클래스의 공개 멤버 (깊이 `MAX_DEPTH` 까지 · 너비 우선 · 순환 방지) · 호출할 수 있는 것의 키워드 인자 이름 (`inspect.signature`,
  못 읽으면 건너뜀). 모든 하위 모듈을 불러오지 않는다 (`pkgutil.walk_packages` 없음) - 임의 코드가 도는 범위를 키우지 않는다.
  속성은 `inspect.getattr_static` 으로만 본다 (게으른 `__getattr__` · 속성 접근이 코드를 돌리지 않게).
- 결과에는 개수 · 코드만 쓴다 (AL-11) - 이름 목록도, 입력한 이름도 찍지 않는다.
- 쓰기는 원자적 (임시 파일 → fsync → 바꿔치기). 같은 이름의 파일만 새로 쓰고, 더 새 format 이면 덮어쓰지 않고, 깨져 있으면 `.broken` 으로 옮긴다 (W-06).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

FORMAT = 1
DIRNAME = "libnames"
MAX_NAMES = 20000                 # 이름 개수 상한 - 넘으면 자르고 truncated 로 알린다
MAX_DEPTH = 3                     # 모듈 -> 하위 모듈 · 클래스 -> 그 안 (루트가 0)
TIMEOUT_S = 60                    # 하위 프로세스 시간 상한 (초)
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
EXIT_NOT_INSTALLED = 3            # 하위 프로세스가 라이브러리를 불러오지 못했을 때의 종료 코드
KILL_WAIT_S = 5
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}\Z")             # 공개 이름 한 개의 꼴
LIB_ARG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}\Z")       # 명령에 주는 라이브러리 이름 (config.py 의 lib_allow 와 같은 꼴)
VERSION_RE = re.compile(r"^[0-9A-Za-z.+_!\-]{0,64}\Z")
# Windows 의 장치 이름 - 이 이름으로 시작하는 파일은 열 수 없다 (파일 이름으로 쓸 수 없는 라이브러리 이름)
RESERVED_BASES = frozenset(["con", "prn", "aux", "nul"] + ["com%d" % i for i in range(1, 10)] + ["lpt%d" % i for i in range(1, 10)])

# 사람에게 보이는 고정 문구 (입력한 이름을 되풀이하지 않는다). 2 는 사용법 오류, 나머지는 점검 실패 (1).
USAGE_TEXT = {
    "bad_name": "라이브러리 이름 꼴이 아닙니다 - 영문자로 시작하고 영문 · 숫자 · _ . - 만 쓴 짧은 이름이어야 합니다",
    "not_allowed": "허용 목록 (policy.lib_allow) 에 없는 이름입니다 - 정책 창 (/diode:dict) 에서 먼저 허용하세요",
}
FAIL_TEXT = {
    "config": "설정을 읽지 못했습니다 (config.json 이 깨졌거나 더 새 판입니다)",
    "not_installed": "라이브러리를 불러오지 못했습니다 (이 PC 에 설치되어 있지 않거나 불러오다 실패했습니다)",
    "timeout": "시간 안에 끝나지 않아 멈췄습니다",
    "too_large": "하위 프로세스의 출력이 상한을 넘어 멈췄습니다",
    "failed": "이름을 모으는 하위 프로세스가 실패했습니다",
    "bad_output": "하위 프로세스의 출력이 약속한 꼴이 아닙니다",
    "newer": "이미 있는 목록 파일이 더 새 형식이라 덮어쓰지 않았습니다",
    "write": "목록 파일을 쓰지 못했습니다",
}

# 하위 프로세스가 도는 코드. 인자: 이름 · 이름 상한 · 깊이 · 이름 꼴 (정규식 글) · 불러오기 실패 종료 코드.
_CHILD_CODE = r'''
import importlib
import inspect
import json
import os
import re
import sys
import types
from collections import deque

name, limit, max_depth = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
pattern, not_installed = re.compile(sys.argv[4]), int(sys.argv[5])

# 작업 폴더와 빈 경로를 검색 경로에서 뺀다 - 이름이 같은 파일이 라이브러리를 가리지 않게
try:
    here = os.path.normcase(os.path.abspath(os.getcwd()))
except OSError:
    here = None
sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.abspath(p)) != here]

# 표준 출력은 결과 한 줄만 쓴다 - 라이브러리가 불러오면서 찍는 글은 버린다 (파일 번호 1 을 비운다)
result_out = os.fdopen(os.dup(1), "w")
sink = os.open(os.devnull, os.O_WRONLY)
os.dup2(sink, 1)
os.close(sink)
sys.stdout = open(os.devnull, "w")

try:
    module = importlib.import_module(name)
except BaseException:
    os._exit(not_installed)

prefix = getattr(module, "__name__", None)
if not isinstance(prefix, str):
    prefix = name
names = set()
state = {"cut": False}


def own(owner):
    return isinstance(owner, str) and (owner == prefix or owner.startswith(prefix + "."))


def add(n):
    """이름 하나를 더한다. 상한을 넘기면 False (모으기를 멈춘다)"""
    if n in names or not pattern.match(n):
        return True
    if len(names) >= limit:
        state["cut"] = True
        return False
    names.add(n)
    return True


def keyword_params(func):
    """키워드 인자로 쓰일 수 있는 매개변수 이름 (위치 전용 · *args · **kwargs · self · cls 는 뺀다)"""
    try:
        params = list(inspect.signature(func).parameters.values())
    except Exception:
        return True
    for p in params:
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY) and p.name not in ("self", "cls"):
            if not add(p.name):
                return False
    return True


seen = set([id(module)])
queue = deque([(module, 0)])
while queue and not state["cut"]:
    obj, depth = queue.popleft()
    try:
        members = [m for m in dir(obj) if isinstance(m, str) and not m.startswith("_")]
    except Exception:
        continue
    for m in members:
        if not add(m):
            break
        try:
            val = inspect.getattr_static(obj, m)
            if isinstance(val, (staticmethod, classmethod)):
                val = val.__func__
            if isinstance(val, types.ModuleType):
                if depth < max_depth and own(val.__name__) and sys.modules.get(val.__name__) is val and id(val) not in seen:
                    seen.add(id(val))
                    queue.append((val, depth + 1))
            elif isinstance(val, type):
                if own(getattr(val, "__module__", None)):
                    if depth < max_depth and id(val) not in seen:
                        seen.add(id(val))
                        queue.append((val, depth + 1))
                    if not keyword_params(val):
                        break
            elif inspect.isroutine(val) and own(getattr(val, "__module__", None)):
                if not keyword_params(val):
                    break
        except Exception:
            continue


def installed_version():
    try:
        from importlib import metadata
    except ImportError:
        return ""
    top = prefix.split(".")[0]
    candidates = []
    mapping = getattr(metadata, "packages_distributions", None)
    if mapping is not None:
        try:
            candidates.extend(mapping().get(top, []))
        except Exception:
            pass
    candidates.append(top)
    for dist in candidates:
        try:
            v = metadata.version(dist)
        except Exception:
            continue
        if isinstance(v, str) and v:
            return v
    return ""


try:
    version = installed_version()
except Exception:
    version = ""
result_out.write(json.dumps({"version": version, "names": sorted(names), "truncated": state["cut"]}) + "\n")
result_out.flush()
os._exit(0)
'''


# ---------------------------------------------------------------- 이름 · 허용 목록

def name_problem(name):
    """명령에 준 이름이 파일 이름으로도 안전한 라이브러리 이름 꼴인가 -> 문제 코드 (없으면 None)."""
    if not isinstance(name, str) or not LIB_ARG_RE.match(name):
        return "bad_name"
    parts = name.split(".")
    if not all(parts) or parts[0].lower() in RESERVED_BASES:
        return "bad_name"
    return None


def is_allowed(home, name):
    """설정 policy.lib_allow 에 있나 (대소문자 무시). 설정이 없으면 빈 목록. 깨졌거나 더 새 판이면 config.ConfigError."""
    from . import config
    cfg = config.read_config(home)
    pol = cfg.get("policy")
    allow = pol.get("lib_allow") if isinstance(pol, dict) else None
    if not isinstance(allow, list):
        return False
    return name.lower() in set(x.lower() for x in allow if isinstance(x, str))


# ---------------------------------------------------------------- 하위 프로세스

def child_argv(name):
    """이름을 모으는 하위 프로세스의 인자 목록 (셸 없음). 이름은 코드에 끼우지 않고 인자로 준다."""
    return [sys.executable, "-E", "-c", _CHILD_CODE, name, str(MAX_NAMES), str(MAX_DEPTH), NAME_RE.pattern,
            str(EXIT_NOT_INSTALLED)]


def _stop(proc, reader):
    """하위 프로세스를 죽이고 읽기 스레드를 기다린다. 스레드가 아직 읽고 있으면 (손자 프로세스가 파이프를 쥠) 닫지 않는다."""
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=KILL_WAIT_S)
    except Exception:
        pass
    reader.join(KILL_WAIT_S)
    if not reader.is_alive():
        try:
            proc.stdout.close()
        except Exception:
            pass


def run_child(argv, timeout_s, max_bytes):
    """하위 프로세스를 띄워 표준 출력을 읽는다 -> (코드, 바이트).

    코드: "ok" · "not_installed" (종료 코드 EXIT_NOT_INSTALLED) · "timeout" · "too_large" · "failed".
    출력은 max_bytes 까지만 읽는다 (넘으면 죽인다) · 시간은 띄운 때부터 timeout_s 초 (넘으면 죽인다).
    """
    if not argv or not argv[0]:
        return "failed", b""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                shell=False)
    except (OSError, ValueError):
        return "failed", b""
    box = []

    def reader():
        try:
            box.append(proc.stdout.read(max_bytes + 1))
        except Exception:
            box.append(None)

    deadline = time.monotonic() + timeout_s
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        _stop(proc, t)
        return "timeout", b""
    data = box[0] if box else None
    if data is None:
        _stop(proc, t)
        return "failed", b""
    if len(data) > max_bytes:
        _stop(proc, t)
        return "too_large", b""
    try:
        proc.wait(timeout=max(deadline - time.monotonic(), 0.1))
    except subprocess.TimeoutExpired:
        _stop(proc, t)
        return "timeout", b""
    try:
        proc.stdout.close()
    except Exception:
        pass
    if proc.returncode == EXIT_NOT_INSTALLED:
        return "not_installed", b""
    if proc.returncode != 0:
        return "failed", b""
    return "ok", data


def _no_constant(_):
    raise ValueError("NaN · Infinity 는 받지 않는다")


def parse_output(data):
    """하위 프로세스의 출력을 검증한다 -> (판, 이름 목록, truncated) 또는 None. 약속한 꼴이 아니면 모두 거절."""
    try:
        obj = json.loads(data.decode("ascii"), parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict) or set(obj) != set(["version", "names", "truncated"]):
        return None
    names, version, truncated = obj["names"], obj["version"], obj["truncated"]
    if not isinstance(names, list) or not isinstance(truncated, bool) or not isinstance(version, str):
        return None
    if not all(isinstance(n, str) and NAME_RE.match(n) for n in names):
        return None
    names = sorted(set(names))
    if len(names) > MAX_NAMES:
        names, truncated = names[:MAX_NAMES], True
    return (version if VERSION_RE.match(version) else ""), names, truncated


def gather(name, argv=None, timeout_s=None, max_bytes=None):
    """라이브러리를 별도 프로세스에서 불러 공개 이름을 모은다 -> (코드, 결과). 코드가 "ok" 면 결과는 (판, 이름 목록, truncated).

    argv, timeout_s, max_bytes 는 시험이 가짜 하위 프로세스 · 짧은 상한으로 바꿔 끼우는 자리다 (명령줄에서는 받지 않는다).
    """
    code, data = run_child(argv if argv is not None else child_argv(name),
                           TIMEOUT_S if timeout_s is None else timeout_s,
                           MAX_OUTPUT_BYTES if max_bytes is None else max_bytes)
    if code != "ok":
        return code, None
    parsed = parse_output(data)
    if parsed is None:
        return "bad_output", None
    return "ok", parsed


# ---------------------------------------------------------------- 쓰기

def list_path(home, name):
    return os.path.join(home, DIRNAME, name.lower() + ".json")


def _set_aside(path):
    """깨진 파일을 .broken 으로 옮긴다 (이미 있으면 번호) - config.py 와 같은 방식 (W-06)."""
    n = 0
    while True:
        dst = path + ".broken" + ("" if n == 0 else str(n))
        if not os.path.exists(dst):
            os.replace(path, dst)
            return dst
        n += 1


def write_list(home, name, version, names, truncated):
    """libnames/<소문자 이름>.json 을 원자적으로 쓴다. 같은 이름의 파일만 새로 쓴다.

    이미 있는 파일이 더 새 format 이면 덮어쓰지 않고 "newer" · 보통 파일이 아니거나 (폴더 · 링크) 쓰기에 실패하면 "write" · 성공이면 None.
    깨져 있는 (JSON 이 아님 · 꼴이 틀림) 파일은 .broken 으로 옮기고 새로 쓴다.
    """
    d = os.path.join(home, DIRNAME)
    path = list_path(home, name)
    try:
        os.makedirs(d, exist_ok=True)
        if os.path.lexists(path):
            if os.path.islink(path) or not os.path.isfile(path):
                return "write"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if not isinstance(old, dict) or isinstance(old.get("format"), bool) or not isinstance(old.get("format"), int):
                    raise ValueError("꼴")
            except (OSError, ValueError):
                _set_aside(path)
            else:
                if old["format"] > FORMAT:
                    return "newer"
        body = {"format": FORMAT, "library": name, "version": version, "names": names, "truncated": truncated}
        fd, tmp = tempfile.mkstemp(prefix=".diode-", suffix=".tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(body, f)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            tmp = None
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except OSError:
        return "write"
    return None


# ---------------------------------------------------------------- 명령

def _fail(code):
    return 1, [json.dumps({"ok": False, "error": code}), "결과: 점검 실패"], FAIL_TEXT[code]


def main_names(home, name, argv=None, timeout_s=None, max_bytes=None):
    """diode.py lib names 의 몸통 -> (종료 코드, 표준 출력 줄 목록, 표준 오류 글).

    종료 코드: 0 OK · 1 점검 실패 (설정 · 설치 안 됨 · 시간 · 출력 · 쓰기) · 2 사용법 오류 (이름 꼴 · 허용 목록 밖).
    2 는 표준 출력이 비고 표준 오류에 고정 문구뿐이다. 어느 경우에도 입력한 이름 · 이름 목록을 찍지 않는다 (AL-11).
    """
    problem = name_problem(name)
    if problem:
        return 2, [], USAGE_TEXT[problem]
    try:
        allowed = is_allowed(home, name)
    except Exception:                  # 설정이 깨졌거나 (ConfigError) 더 새 판이거나 읽을 수 없음
        return _fail("config")
    if not allowed:
        return 2, [], USAGE_TEXT["not_allowed"]
    code, got = gather(name, argv=argv, timeout_s=timeout_s, max_bytes=max_bytes)
    if code != "ok":
        return _fail(code)
    version, names, truncated = got
    bad = write_list(home, name, version, names, truncated)
    if bad:
        return _fail(bad)
    line = json.dumps({"ok": True, "library": name, "names": len(names), "truncated": truncated})
    return 0, [line, "결과: OK"], ""
