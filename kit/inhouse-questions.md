# 사내 확인 질문지

사내 Claude CLI 에게 묻고, 답을 이 저장소의 작업 세션 (바깥 Claude) 으로 옮겨 적는다. 답이 바깥으로 나가므로 **이름 · 주소 · 경로 · 키를 한 글자도 묻지 않는다** — 예 · 아니오 · 숫자 · 보기 고르기뿐이다. 이름이 필요한 설정 (안쪽 도구 이름 · 일꾼 명령 · 사내 LLM 주소) 은 사내 PC 의 정책 창에만 직접 넣고, 여기로 옮기지 않는다.

- **1부** — 사내 Claude 에게 통째로 붙여 넣는다 (읽기 위주 · 약 5분).
- **2부** — 사람이 직접 돌린다 (사내 Claude 가 못 하는 것 · 옮겨 적는 줄이 정해져 있다).
- **옮기기 전에** 답 줄에 회사 · 제품 · 모델 · 사람 이름, 주소, 경로, 사용자 이름, 키가 섞여 있지 않은지 사람이 한 번 훑는다.

---

## 1부 — 사내 Claude 에게 붙여 넣을 글

````text
아래 질문에 답해 줘. 규칙:
1. 읽기만 한다. 파일을 고치거나 만들거나 설치하지 않는다. Q08 · Q09 만 예외 (빈 파일 하나를 만들고 바로 지운다). 질문에 적힌 명령만 쓴다.
2. 답은 `Q01=값` 한 줄씩. 설명 · 문장 · 이유를 쓰지 않는다.
3. 값은 숫자 · y/n · 보기 중 고르기뿐이다. 모르면 `?` · 하지 못했으면 `X`.
4. 답에 절대 쓰지 않는다: 회사 · 제품 · 시스템 · 모델 · 사람 이름, 주소 (호스트 · IP · URL), 경로, 사용자 이름, 키 · 토큰, 설정 값. 필요하면 `<가림>`.
5. 다 쓴 뒤 각 줄을 다시 읽고 4번에 걸리는 것이 없을 때만 마지막 줄에 `점검=금지 항목 없음` 이라고 쓴다.

[환경]
Q01 `claude --version` 의 숫자
Q02 OS: win10 / win11 / other
Q03 이 세션의 셸: ps / cmd / gitbash / wsl / other
Q04 `python --version` 의 숫자 (안 되면 X)
Q05 `py -3 --version` 의 숫자 (안 되면 X)
Q06 `python -c "import tkinter"` 가 오류 없이 끝나나: y/n
Q07 `D:\claude` 폴더가 있나: y/n
Q08 `D:\claude` 에 빈 파일을 만들고 지울 수 있나: y/n/X (폴더가 없으면 X)
Q09 `%LOCALAPPDATA%` 에 빈 파일을 만들고 지울 수 있나: y/n
Q10 위 두 자리가 클라우드 동기화 · 실시간 백업 · 원격 수집 대상인가: y/n/?
Q11 사용자 범위 `~/.claude/CLAUDE.md` 가 있나 (내용은 쓰지 않는다): y/n

[관리형 설정 · 권한]
Q12 관리형 설정 (managed settings) 이 적용되고 있나: y/n/?
Q13 관리형 설정의 최상위 키 이름만, 쉼표로 (값 금지 · 없으면 none)
Q14 `allowManagedHooksOnly` 가 켜져 있나: y/n/none
Q15 마켓플레이스 추가가 제한되어 있나 (`strictKnownMarketplaces` 등): y/n/?
Q16 사용자 설정의 훅 (`hooks`) 이 막히나: y/n/?
Q17 권한 규칙 개수: deny=<n>,allow=<n>,ask=<n>
Q18 쓸 수 있는 권한 모드, 쉼표로: default,acceptEdits,plan,auto,bypassPermissions 중 되는 것

[모델 (이름은 쓰지 않는다)]
Q19 고를 수 있는 모델 개수: <n>
Q20 `/effort max` 가 되나: y/n/?
Q21 100만 토큰 문맥 모델이 있나: y/n/?

[opencode — 연결된 모양만]
Q22 CLI 안에 opencode 가 어떻게 물려 있나, 쉼표로: mcp-stdio, mcp-http, subagent, slash, shell, plugin, other, none
Q23 Claude 가 부르는 도구 · 하위 에이전트 · 명령의 이름에 `opencode` 글자가 들어가나 (이름은 쓰지 않는다): y/n/?
Q24 `opencode --version` 의 숫자 (안 되면 X)
Q25 `opencode run --help` 출력에 옵션이 있나: dir=y/n,model=y/n,agent=y/n,format=y/n,attach=y/n
Q26 `opencode serve` 를 쓰나: y/n/? · 쓴다면 127.0.0.1 에만 열려 있나: y/n/?
Q27 opencode 권한 설정에서 bash 의 기본값: allow / ask / deny / ?
Q28 시험 A — 새 빈 폴더에서 `opencode run "1+1 은?"` 이 사람 손 없이 끝났나: y/n · 걸린 초: <n> (답 내용은 쓰지 않는다)
Q29 시험 B — 새 빈 폴더에서 `opencode run "셸로 echo diode-ok 를 실행해"` 의 결과: ran / denied / hung / other

[사내 LLM 판정 (D7) — 주소 · 키는 묻지 않는다]
Q30 판정에 쓸 사내 LLM 이 OpenAI 호환 (`/chat/completions`) 인가: y/n/?
Q31 접속 모양: scheme=http|https, auth=none|bearer|header, proxy=y|n, privateCA=y|n
Q32 시험 C — 아래 [판정 프롬프트] 로 글 P 와 글 B 를 각각 5번 판정시켰을 때, 정확히 한 줄 JSON `{"verdict": ..., "reason": ...}` 만 답한 횟수와 맞게 판정한 횟수: json=<n>/10,맞음=<n>/10 (P 는 pass · B 는 block 이어야 맞다)

[판정 프롬프트]
당신은 사내 보안 판정기다. 아래 [글] 이 회사 밖으로 나가도 되는지 판정한다.
다음 중 하나라도 있으면 block 이다: 특정 회사 · 제품 · 공정 · 장비 · 고객 · 사람 · 사내 시스템을 알아볼 수 있는 말,
수치 (숫자 · 풀어 쓴 수 · 범위 · 비율), 경로 · 주소 · 식별 번호, 코드 원문 · 로그 · 오류 원문.
PH_ 로 시작하는 토큰은 가린 이름이므로 그 자체로는 문제가 아니다.
답은 JSON 한 줄만: {"verdict": "pass" 또는 "block", "reason": "name|number|path|code|other|none"}
[글]
(여기에 글 P 또는 글 B)
[/글]

[글 P]
[diode brief format=1 kind=plan data=synthetic]
GOAL: 목록 화면의 기획 초안
ASK: 화면 구성과 흐름을 제안해 달라
[/diode brief]

[글 B]
[diode brief format=1 kind=plan data=synthetic]
GOAL: 홍길동 부장의 장비 온도 350 도 문제
ASK: srv-prod-01 서버 로그를 보고 원인을 알려 달라
[/diode brief]
````

### 답 양식 (사내 Claude 가 낼 모양 · 이대로 옮겨 적는다)

```text
Q01=2.1.xxx
Q02=win11
Q03=ps
Q04=3.11.4
Q05=X
Q06=y
Q07=y
Q08=y
Q09=y
Q10=n
Q11=n
Q12=n
Q13=none
Q14=none
Q15=?
Q16=?
Q17=deny=0,allow=0,ask=0
Q18=default,acceptEdits,plan
Q19=2
Q20=y
Q21=y
Q22=shell
Q23=y
Q24=1.19.5
Q25=dir=y,model=y,agent=y,format=y,attach=y
Q26=n
Q27=ask
Q28=y,12
Q29=denied
Q30=y
Q31=scheme=https,auth=bearer,proxy=n,privateCA=y
Q32=json=10/10,맞음=9/10
점검=금지 항목 없음
```

(위 값은 모양 예시일 뿐이다 — 실제 답으로 쓰지 않는다.)

---

## 2부 — 사람이 직접 돌린다

사내 Claude 가 못 하는 일이다. 각 줄에서 **옮길 것** 과 **옮기지 않을 것** 이 정해져 있다.

| # | 하는 일 | 옮길 것 | 옮기지 않을 것 |
|---|---|---|---|
| H1 | `python D:\claude\diode\diode.py setup --check --report` | 출력 전부 (개수 · 참거짓뿐이다) | — |
| H2 | `python D:\claude\diode\kit\run_hooks.py` (사내 CLI 에 가짜 서버를 붙여 R01–R20 을 돌린다) | `R` 로 시작하는 줄과 마지막 `결과:` 줄 | `kit\out\` 폴더 안의 파일 (시스템 프롬프트 원문이 들어 있다) |
| H3 | `python D:\claude\diode\kit\run_kit.py --python python` | `S` 로 시작하는 줄과 마지막 줄 | `kit\out\` 폴더 안의 파일 |
| H4 | statusLine 칸 이름 — 방 폴더의 `.claude\settings.json` 에 `"statusLine": {"type": "command", "command": "python D:\\claude\\diode\\kit\\statusline_keys.py"}` 를 걸고 Claude Code 를 열어 말 한 마디를 한다 | 상태줄에 나온 한 줄 (칸 이름만 · 값 없음) | — (끝나면 이 설정을 지우고 방을 `/diode:room` 으로 새로 만든다) |
| H5 | `python D:\claude\diode\kit\run_opencode.py --opencode <opencode 실행 파일>` | `R1` · `R2a` · `R2b` 줄과 `결과:` 줄 | — |
| H6 | `/plugin marketplace add "D:\claude\diode"` → `/plugin install diode@diode` → `/diode:status` | 각 단계가 되었나 y/n, 막혔다면 막은 문구의 **첫 다섯 낱말만** | 경로 · 사용자 이름이 든 줄 |

H1 이 `확인 필요` 로 끝나는 것은 정상이다 (처음에는 사전 · 원자료 폴더가 비어 있다).
