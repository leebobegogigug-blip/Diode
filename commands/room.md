---
description: Diode 방 만들기 - 원자료가 없는 깨끗한 작업 폴더 (이미 있으면 덮어쓰지 않고 상태만 알린다)
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/diode.py" room --report`

위는 방을 만든 결과다. 한국어로 짧게 전한다.

- 만들었으면 "방에서 Claude 를 새로 여세요" 라고 안내한다. 거부되었으면 까닭 한 줄과 어떻게 하면 되는지만 말한다.
- 방이 changed 라고 나오면 설정이 바뀌어 막힌 것이다 - 사람이 보고 지우고 다시 만들게 한다. 직접 고치지 않는다.
