---
description: Diode 말 봉인 창 열기 - 사내 말은 창에서 쓰면 가명 토큰 글로 바꿔 보이고, 사람이 확인해 복사한다 (사내 말을 이 대화에 치지 않는다)
allowed-tools: Bash(python:*)
---
!`python "${CLAUDE_PLUGIN_ROOT}/diode.py" speak --detached`

말 봉인 창이 열렸다. 한국어로 한 줄만 전한다: 창에서 사내 말로 쓰고 [봉인] -> 봉인한 글을 눈으로 확인 -> [복사] 한 뒤 여기에 붙여 넣고, Claude 의 답은 창에 붙여 넣으면 되돌려 볼 수 있다.

- 사내 단어 · 사내 이야기를 사용자에게 묻거나 받아 적지 않는다. 이 대화에 쓰면 곧바로 Claude 로 나간다. 사내 말은 창 안에서만 쓴다.
