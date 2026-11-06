"""statusLine 의 표준 입력 JSON 에서 **칸 이름만** 뽑아 한 줄로 찍는다 (값은 찍지 않는다 · 사내에서 옮겨 적기 좋게).

쓰는 법: 방 폴더의 .claude/settings.json 에
    {"statusLine": {"type": "command", "command": "python D:\\claude\\diode\\kit\\statusline_keys.py"}}
를 걸고 Claude Code 를 열어 말 한 마디를 하면 상태줄에 칸 이름 목록이 나온다. 그 한 줄을 옮겨 적는다.
이 도구를 지운 뒤 방 설정을 되돌린다 (방 표지의 해시가 어긋나면 방이 changed 로 막힌다 — /diode:room 으로 새로 만든다).

이름은 점으로 이어 (`effort.level`) 쉼표로 나눈다. 목록은 `[]` 로 줄인다. 값 · 글 · 경로는 어디에도 쓰지 않는다.
Python 3.8 이상 · 표준 라이브러리만 · 어떤 입력에도 종료 코드 0 (statusLine 은 보안 경계가 아니다).
"""
import json
import sys

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 6


def key_paths(obj, prefix="", depth=0):
    """JSON 값에서 칸 이름의 점 경로 목록 (이름만). 값은 쓰지 않는다."""
    out = []
    if depth > MAX_DEPTH:
        return [prefix.rstrip(".")] if prefix else []
    if isinstance(obj, dict):
        for k in sorted(obj, key=str):
            name = str(k)
            if isinstance(obj[k], dict):
                sub = key_paths(obj[k], prefix + name + ".", depth + 1)
                out.extend(sub if sub else [prefix + name])
            elif isinstance(obj[k], list):
                out.append(prefix + name + "[]")
                if obj[k] and isinstance(obj[k][0], dict):
                    out.extend(key_paths(obj[k][0], prefix + name + "[].", depth + 1))
            else:
                out.append(prefix + name)
    return out


def main(stdin=None, stdout=None):
    stdin = stdin or getattr(sys.stdin, "buffer", sys.stdin)
    stdout = stdout or sys.stdout
    try:
        data = stdin.read(MAX_BYTES + 1)
        if isinstance(data, str):
            data = data.encode("utf-8")
        if len(data) > MAX_BYTES:
            stdout.write("ERR too-big\n")
            return 0
        obj = json.loads(data.decode("utf-8"))
        stdout.write(",".join(key_paths(obj)) + "\n")
    except Exception:
        stdout.write("ERR\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
