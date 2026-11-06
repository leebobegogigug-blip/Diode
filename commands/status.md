---
description: Diode 상태 - 점검 결과와 상태 명령 (개수만 · 단어 없음)
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/diode.py" setup --check --report`

!`python "${CLAUDE_PLUGIN_ROOT}/diode.py" --status --json`

위는 점검 결과와 상태 JSON 이다. 한국어로 짧게 요약한다: 마지막 `결과:` 줄, 막힌 것이 있으면 무엇인지, 다음에 할 일 한 가지.
