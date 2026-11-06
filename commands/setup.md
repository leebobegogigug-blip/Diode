---
description: Diode 처음 설정 - 점검하고, 사전 · 원자료 폴더는 창에서 직접 입력하고, 방을 만든다
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/diode.py" setup --report`

위는 Diode 가 이 PC 에서 낸 점검 결과다. 한국어로 짧게 전한다.

- 마지막 `결과:` 줄과, 사용자가 다음에 할 일 한두 가지만 말한다.
- 정책 창이 열렸다고 나오면 "창에서 직접 입력하고 [저장] 한 뒤 /diode:setup 을 다시 실행하세요" 라고만 안내한다.
- 사내 단어 · 폴더 이름 · 일꾼 명령을 사용자에게 묻거나 받아 적지 않는다 (입력하면 곧바로 Claude 로 나간다). 창에서만 입력한다.
