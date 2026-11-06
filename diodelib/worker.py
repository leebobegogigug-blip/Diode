# -*- coding: utf-8 -*-
"""일꾼 (안쪽 사내 LLM) 에게 지시를 넣는 부품 — 설정한 명령을 셸 없이 띄운다 (표준 라이브러리 · Python 3.8).

opencode 를 어떻게 설치했든 (명령줄 · 서버) 같은 자리에서 쓰도록, 설정 `worker.command` 에 인자 목록을 적는다:

    "worker": {"command": ["opencode", "run", "{prompt}"], "cwd": "<안쪽 작업 폴더 · 생략하면 데이터 폴더 work\\<job>>"}

- 목록 안의 `{prompt}` 자리에 일꾼 안내문 + 지시를 넣는다. `{prompt}` 가 없으면 표준 입력으로 준다.
- `{cwd}` 는 일꾼의 작업 폴더 (첨부가 복사되는 곳) 로 바뀐다 — 일꾼이 셸 명령을 돌리는 자리를 명시하려면 쓴다
  (진짜 opencode 는 프로세스의 작업 폴더가 아니라 `--dir` 을 따랐다 [실험]):
  `["opencode", "run", "--dir", "{cwd}", "{prompt}"]`
- 셸을 거치지 않는다 (인자 목록 · shell=False). 환경 변수는 그대로 물려받되 `DIODE_JOB` 만 더한다.
- 일꾼의 표준 출력 · 표준 오류는 읽지 않는다 — 버린다 (AL-14 · 일꾼의 응답은 Claude 에게 가지 않는다). 일은 백그라운드에서
  돌고, 결과는 일꾼이 `diode.py propose` 로만 낸다. 허브는 기다리지 않는다.
- 첨부는 방 `work\\` 의 파일 이름만 받아 안쪽 작업 폴더로 복사한다 (이름은 한 칸 · 덮어쓰지 않음). 바깥으로 부르는 코드
  (U3) 가 든 첨부는 확정 창 전에 허브가 막으므로 (hub.check_attachments) 여기서는 복사만 한다.
- `check()` 는 실행 파일이 PATH 에서 찾아지는지만 본다 (띄워 보지 않는다).
- **Windows 의 `.cmd` · `.bat` 껍데기 (npm 으로 깐 opencode 가 보통 그렇다)**: 이것을 부르면 `cmd.exe` 가 인자를 다시 해석한다 —
  프롬프트 (Claude 가 쓴 글) 의 `&` · `|` · `^` · `%` 가 명령이 된다 (명령 주입). 그래서 껍데기면 `{prompt}` 를 인자로 주는 설정을
  거절하고 (`command_problem` → "cmd_shim_prompt") 표준 입력만 쓰게 한다 (진짜 opencode 1.19.5 는 표준 입력으로 받는다 [실험]).
  `{cwd}` 도 껍데기가 해석하는 글자가 든 폴더면 거절한다. 실행 파일은 PATH 에서 찾은 전체 경로로 부른다 (`.cmd` 는 이름만으로 안 뜬다).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading

MAX_ARGS = 32
MAX_ARG_LEN = 4096


class WorkerConfigError(Exception):
    pass


_CMD_META = set('&|<>^%!"()')
_SHIM_EXT = (".cmd", ".bat")


def _resolve(executable, which=None):
    which = which or shutil.which
    return which(executable) or (executable if os.path.isfile(executable) else None)


def command_problem(command, os_name=None, which=None, cwd=None):
    """설정한 일꾼 명령의 문제 코드 (없으면 None): not_found · cmd_shim_prompt · cmd_shim_cwd. 띄워 보지 않는다.

    cmd_shim_prompt: Windows 에서 .cmd · .bat 껍데기를 `{prompt}` 인자로 부름 (명령 주입 길 · 표준 입력을 쓰라).
    cmd_shim_cwd: 껍데기를 부르는데 작업 폴더 이름에 cmd.exe 가 해석하는 글자가 있음.
    """
    exe = _resolve(command[0], which)
    if exe is None:
        return "not_found"
    if (os_name or os.name) == "nt" and exe.lower().endswith(_SHIM_EXT):
        if any("{prompt}" in x for x in command):
            return "cmd_shim_prompt"
        if cwd is not None and any(ch in _CMD_META for ch in cwd):
            return "cmd_shim_cwd"
        if any("{cwd}" in x for x in command) and cwd is None:
            return None          # 폴더는 보낼 때 본다
    return None


def load_command(cfg):
    """설정 dict (config.json 전체) 에서 (인자 목록, cwd 또는 None). 없거나 꼴이 틀리면 WorkerConfigError."""
    w = cfg.get("worker") if isinstance(cfg, dict) else None
    if not isinstance(w, dict):
        raise WorkerConfigError("worker")
    cmd = w.get("command")
    if not isinstance(cmd, list) or not cmd or len(cmd) > MAX_ARGS \
            or not all(isinstance(x, str) and x and len(x) <= MAX_ARG_LEN and "\x00" not in x for x in cmd):
        raise WorkerConfigError("command")
    if sum(1 for x in cmd if "{prompt}" in x) > 1:
        raise WorkerConfigError("command")
    cwd = w.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not cwd):
        raise WorkerConfigError("cwd")
    return list(cmd), cwd


class CommandWorker(object):
    """허브의 worker 부품 (check · send)."""

    def __init__(self, command, home, room_dir, cwd=None, popen=None, os_name=None, which=None):
        self.command = list(command)
        self.home = home
        self.room_dir = room_dir
        self.cwd = cwd
        self._popen = popen or subprocess.Popen
        self._os_name = os_name
        self._which = which
        self.children = []
        self._lock = threading.Lock()

    def problem(self, cwd=None):
        return command_problem(self.command, self._os_name, self._which, cwd)

    def check(self):
        return self.problem() is None

    def _work_dir(self, job):
        d = self.cwd or os.path.join(self.home, "work", job)
        os.makedirs(d, exist_ok=True)
        # 정규 경로로 넘긴다 - Windows 의 8.3 짧은 이름 (RUNNER~1) 과 긴 이름이 섞이면 일꾼 도구가 자기 작업 폴더를 "밖" 으로 본다
        return os.path.realpath(d)

    def _copy_attachments(self, job, names, dest):
        src = os.path.join(self.room_dir, "work")
        for n in names:
            if os.path.basename(n) != n or n in (".", ".."):
                raise ValueError("첨부 이름")
            s = os.path.join(src, n)
            if not os.path.isfile(s):
                raise ValueError("첨부 없음")
            target = os.path.join(dest, n)
            base, ext = os.path.splitext(target)
            k = 2
            while os.path.exists(target):          # 덮어쓰지 않는다
                target = "%s-%d%s" % (base, k, ext)
                k += 1
            shutil.copyfile(s, target)

    def send(self, job, text, attachments):
        """지시를 일꾼에게 넣는다 → 띄웠으면 True. 일꾼의 출력은 읽지 않는다."""
        try:
            dest = self._work_dir(job)
            if self.problem(dest) is not None:
                return False
            self._copy_attachments(job, attachments or [], dest)
            argv = [x.replace("{cwd}", dest).replace("{prompt}", text) for x in self.command]
            exe = _resolve(self.command[0], self._which)
            argv[0] = exe if exe else argv[0]                # PATH 에서 찾은 전체 경로 (Windows 의 .cmd 는 이름만으로 안 뜬다)
            use_stdin = not any("{prompt}" in x for x in self.command)
            env = dict(os.environ)
            env["DIODE_JOB"] = job
            p = self._popen(argv, cwd=dest, env=env, shell=False,
                            stdin=subprocess.PIPE if use_stdin else subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if use_stdin:
                try:
                    p.stdin.write(text.encode("utf-8"))
                    p.stdin.close()
                except (OSError, ValueError):
                    return False
            with self._lock:
                self.children = [c for c in self.children if c.poll() is None] + [p]
            t = threading.Thread(target=p.wait)          # 끝난 일꾼을 거둔다 (좀비를 남기지 않는다)
            t.daemon = True
            t.start()
            return True
        except Exception:
            return False
