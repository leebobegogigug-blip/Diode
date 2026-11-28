# M0 결과 — 리눅스판 (2026-11-05)

`kit/run_kit.py` 를 이 저장소를 만드는 세션 (Linux 컨테이너) 에서 돌린 결과다. 사내 Windows 에서는 사내에서 같은 스크립트로 다시 돌린다 (`python run_kit.py --python python`).

- **조건**: Claude Code 2.1.318 (`claude -p` · print 모드) · 가짜 Anthropic 서버 (127.0.0.1 · `kit/fake_anthropic.py`) · 빈 환경 (허용 목록) · 임시 HOME · 임시 `CLAUDE_CONFIG_DIR` · 합성 자료와 카나리아만. 진짜 Anthropic 으로는 아무것도 가지 않았다 (가짜 서버에 모든 요청이 왔고, 부가 통신 끄는 환경 변수를 켰다).
- **원자료 덤프** (`kit/out/`) 는 커밋하지 않는다. Claude Code 의 시스템 프롬프트 원문이 들어 있기 때문이다. 이 문서에는 판정과 사실만 적는다.
- 표기: [실험] 이 실행에서 직접 본 것 · [문헌] 공개 문서에 적힌 것 · [미확인] 아직 못 본 것.

## 01 결과 표

| # | 시나리오 | 결과 [실험] | 설계에 주는 것 |
|---|---|---|---|
| S01 | 방에서 연 세션 · 방 위 폴더에 `CLAUDE.md` | 위 폴더의 `CLAUDE.md` 내용이 **요청에 실렸다** (messages) · 작업 폴더 경로 · git 여부 · 플랫폼 · OS 판이 messages 의 환경 칸에 · **HOME 경로가 시스템 프롬프트에** (자동 메모리 자리) | `D:\claude` 에 `CLAUDE.md` 금지 (7판 그대로) · HOME 경로 = Windows 에서는 사용자 이름 → 방 설정으로 자동 메모리 끄기 (S13) |
| S02 | 방 위 폴더가 git 저장소 | **git 가지 이름이 실렸다** | `D:\claude` 를 git 저장소로 만들지 않는다 (7판 그대로) · `/diode:room` 이 방 위가 git 저장소면 거부 |
| S03 | `--effort low` · 모델 `claude-opus-5[1m]` | 요청 `output_config.effort` = `low` · 모델은 `claude-opus-5` (`[1m]` 은 빠져서 감) · 따로 1M 베타 헤더 없음 | effort 는 `--effort` 로 걸린다 |
| S17 | 방 설정 `effortLevel: "medium"` | 요청 effort = `medium` | `room` 건네기의 방 설정 쓰기가 통한다 (07 › 모델 · effort) |
| S01 | 기본 | effort `high` · thinking `adaptive` (display `omitted`) · max_tokens 64000 · 헤더에 Claude Code 판 · OS · CPU 종류 · 세션 id · `metadata.user_id` (해시꼴 150자) | 바깥으로 가는 기계 정보 — 보안 부서 설명에 적는다 |
| S04 | 플러그인 (`--plugin-dir`) · 허브 `.mcp.json` | 허브가 **자동으로 떴다** (initialize · tools/list) · 허브 환경에 `CLAUDE_PLUGIN_ROOT` · `CLAUDE_PLUGIN_DATA` · `CLAUDE_PROJECT_DIR` 있음 · Claude 를 띄운 환경의 `DIODE_WORKER_URL` 도 허브까지 옴 · 허브 도구는 **지연 로딩** (이름만 보이고 `ToolSearch` 로 불러야 함) · 이름은 `mcp__plugin_<플러그인>_<서버>__<도구>` | 허브 구조 (6판 A′) 가 선다 · Terminal–1 이 넘기는 일꾼 주소가 허브에 닿는다 · 스킬에 "다이오드 도구는 ToolSearch 로 먼저 불러라" 를 적는다 |
| S05 | ToolSearch → `dispatch` → `inbox` | `dispatch` 의 결과로 모델에 실린 것은 **고정 꼴 `{"sent": true, "job": "J-0001"}` 뿐** · 허브는 지시 글을 받았다 · `inbox` 의 봉인 글이 모델에 실렸다 | **AL-14 가 된다** — 안쪽 출력이 도구 결과로 새지 않게 만들 수 있다 |
| S06 | 사람이 친 말에 사전 단어 | `UserPromptSubmit` 종료 코드 2 → **모델 요청이 하나도 없었다** · 막은 까닭은 사람에게만 | 안전벨트 ① 이 된다 |
| S10 | 원자료 폴더에서 연 세션 | 첫 프롬프트부터 막힘 · 모델 요청 0 | 모드 '원자료 폴더' 가 된다 |
| S07 | 방에서 방 밖 (원자료) Read | 훅이 deny · Claude 가 본 까닭은 `DIODE: 방 밖 (AL-06)` 뿐 · 원자료 카나리아 없음 | 방 프로필이 된다 · 까닭 글에 단어를 쓰지 않는 규칙 (AL-11) 이 지켜진다 |
| S08 | 방에서 Bash | deny | 방에서 Bash 막기가 된다 |
| S11 | 보통 폴더에서 원자료 Read | deny (안전벨트) | 모드 '그 밖' 이 된다 |
| S09 | PreToolUse 훅이 죽음 (`onFailure: "block"`) | **막혔다** · Claude 가 본 글은 "hook … failed; blocking because onFailure is block" (훅 명령은 변수 꼴 그대로) | 막는 쪽 실패 (AL-03) 가 훅에서도 된다 |
| S12 | 대조 — 플러그인 없이 보통 폴더에서 원자료 Read | **그대로 읽혀 원자료 카나리아가 요청에 실렸다** | 시험이 진짜로 막고 있었다는 대조 · 플러그인을 끈 PC 의 위험 (R25) 이 실제다 |
| S15 | 대조 — 사용자 `~/.claude/CLAUDE.md` | **방 세션에 실렸다** | 사용자 범위 안내 파일도 새는 길 (새로 · L-29) |
| S13 | 방 설정 `autoMemoryEnabled: false` | 시스템 프롬프트에서 **HOME 경로가 빠졌다** | `/diode:room` 이 방 설정에 쓴다 (새로) |
| S14 | 방 설정 `claudeMdExcludes` (+ 자동 메모리 끔) | 위 폴더 · 사용자 `CLAUDE.md` 가 **모두 빠졌다** · 남은 것은 방 경로 (작업 폴더) 뿐 | `/diode:room` 이 방 설정에 쓴다 (새로) · 방 이름에 사내 말을 쓰지 않는다 (7판 그대로) |
| S18 | 허브 (MCP 자식) 가 `dispatch` 때 tkinter 창 프로세스를 띄움 · Xvfb | **창이 떴다** (199×62 · viewable) · 도구 결과는 그대로 고정 꼴 · Python 3.12 + 배포판 tkinter | 확정 창을 허브가 띄우는 구조가 선다 (리눅스) — Windows 는 사내 |
| S09′ | 같은 훅 고장을 훅 명령에 **절대 경로** (`/root/…/python3.8`) 를 적어 다시 | Claude 가 본 고장 글에 **훅 명령의 경로가 그대로** 실렸다 (사용자 이름 `root` 가 든 경로) · 명령을 이름만 (`python3.12`) 적으면 경로가 없다 | 훅 · 허브의 Python 명령은 **이름만** 적는다 — Windows 에서 `C:\Users\<이름>\…` 가 새지 않게 (새로 · L-30) |
| T01 | **대화형 (TUI)** 방 세션 (`run_tui.py` · 의사 터미널) · 방 설정에 statusLine · 자동 메모리 끔 · `claudeMdExcludes` · 권한 모드는 기본값 | 기본 권한 모드가 `auto` 였고, 요청 본문에 **`safeguards.classifier_context`** 가 실렸다 — 권한 모드 · 플랫폼 · 작업 폴더 · **HOME 경로** · 사용자 설정 자리 · 신뢰한 폴더 · **권한 규칙 내용** (deny 규칙에 넣은 카나리아 경로가 그대로) · git 상태. print 모드 (S01) 에는 이 칸이 없다 | 대화형 auto 모드는 HOME (= Windows 사용자 이름) · 권한 규칙의 경로를 내보낸다 (새로 · L-31) |
| T02 | T01 + 방 설정 `permissions.defaultMode: "default"` | **`safeguards` 칸이 없어졌다** · HOME 경로 · 규칙 카나리아 없음 · 남은 것은 방 경로뿐 | 방 설정은 권한 모드를 수동 (`default`) 으로 둔다 · 세션 중 auto 로 바꾸면 훅이 막는다 (훅 입력에 `permission_mode` 가 온다 [문헌]) · 권한 규칙에 원자료 폴더 이름을 쓰지 않는다 (원자료 폴더 목록은 Diode 설정에만) |
| T01 | statusLine 입력 JSON (칸 이름만 기록) | `effort.level` (= 방 설정의 `medium`) · `cost.total_cost_usd` · `context_window.total_input_tokens` · `total_output_tokens` · `model.id` · `session_id` · `transcript_path` · `workspace.*` · `prompt_cache.*` 등 | 방 statusLine 으로 실제 사용량 · 걸린 effort 를 받는 설계 (4판) 가 선다 |
| S16 | 방 설정 `permissions.blockReadsOutsideWorkingDirectories: true` · 플러그인 없이 | 방 밖 Read 가 **권한 층에서 막혔다** | 훅과 별개의 두 번째 벽 — 방 설정에 넣는다 (새로) |

## 02 기획에 주는 것 (8판 원고)

1. **방 설정 (`/diode:room` 이 쓰는 `.claude/settings.json`) 에 다섯을 더한다** — `autoMemoryEnabled: false` · `claudeMdExcludes` (방 위 · 사용자 범위 `CLAUDE.md` · `AGENTS.md` · rules) · `permissions.blockReadsOutsideWorkingDirectories: true` · `permissions.defaultMode: "default"` (T02) · 경로가 없는 권한 deny 규칙 (Bash · WebFetch). 넷은 플러그인을 꺼도 방 설정으로 남는 벽이다.
2′. **새는 길 L-31**: 대화형 auto 모드는 HOME 경로 · 권한 규칙 · 신뢰한 폴더 · git 상태를 요청에 싣는다 (T01) — 방은 수동 모드로 열고 (T02), 훅이 `permission_mode` 가 `auto` 인 프롬프트를 막는다. 회사 IT 가 관리형 설정으로 auto 모드를 끌 수 있는지 보안 부서 질문에 더한다.
2. **새는 길 L-29**: 사용자 범위 `~/.claude/CLAUDE.md` 가 모든 세션에 실린다 — 방에서는 `claudeMdExcludes` 로 빼고, 방 밖 세션을 위해 `/diode:setup` 이 그 파일을 사전으로 검사한다.
3. **허브 구조 (A′) 는 선다** (S04 · S05). 남은 확인은 Windows · 대화형 · tkinter 창.
4. **스킬**: 다이오드 도구는 지연 로딩이라 `ToolSearch` 로 먼저 불러야 한다는 것을 적는다.
5. **새는 길 L-30**: 훅이 고장 나면 훅 명령 글이 Claude 에게 간다 — 훅 · 허브의 Python 명령은 이름만 (`python`) 적고, 절대 경로를 쓰지 않는다. `/diode:setup` 이 그 이름으로 Python 3.8 이상을 찾는지 본다.
6. **확정 창은 따로 된 프로세스로** — 허브가 창 프로세스를 띄우고 결과를 받는다 (S18). 허브의 표준 입출력 고리와 tkinter 고리를 한 프로세스에 섞지 않는다.
7. **Python 판**: 훅 · 허브는 Python 3.8.20 (uv) 에서도 같은 결과였다. 다만 그 판의 tkinter 는 이 컨테이너의 Xvfb 와 맞지 않아 (xcb 오류 · 허브 밖에서도 같음) 창 시험은 Python 3.12 + 배포판 tkinter 로 했다 — 사내 Windows 의 Python 판으로 다시 본다.
8. **보안 부서 설명**: 바깥으로 가는 기계 정보 (Claude Code 판 · OS · CPU 종류 · 세션 id · 사용자 해시 id · 작업 폴더 경로 · OS 판) 를 적는다.

## 03 아직 못 본 것

| 무엇 | 어디서 |
|---|---|
| 대화형 TUI 세션 — Windows | 사내 (리눅스는 T01 · T02 로 확인 · Windows 에는 pty 가 없어 손으로) |
| Windows — exec 꼴 훅 (`python`) · 경로 꼴 · PowerShell 기본 셸 | 사내 (`python run_kit.py --python python`) |
| MCP 자식 프로세스에서 tkinter 확정 창 — Windows | 사내 (리눅스는 S18 로 확인) |
| opencode 일꾼에 지시 넣는 끝점 | 다음 — opencode 설치 · 가짜 사내 LLM 서버 |
| 회사 관리형 설정 (마켓플레이스 · 플러그인 묶음) · 사내 게이트웨이의 모델 이름 | 사내 |

## T12 — 진짜 훅으로 KIT-2 재시험 [2026-11-05 · Claude Code 2.1.318 · 리눅스]

`kit/run_hooks.py` 는 이 저장소를 `--plugin-dir` 로 싣는다 (진짜 `hooks/hooks.json` · `diode.py hook`). 방은 진짜 표지 · 방 설정 (SP-10 의 다섯) 으로 만들고, 데이터 폴더는 임시 HOME 아래 기본 자리에 지어낸 사전 · 설정을 둔다. 가짜 서버 · 빈 환경은 run_kit.py 와 같다.

| # | 무엇 | 결과 |
|---|---|---|
| R01 | 대조: 방 · 깨끗한 말 | 모델 요청 1 — 훅이 다 막지는 않는다 |
| R06 | 방 · 사전 단어 변형 (`kit-word alpha`) | 막힘 · 모델 요청 0 |
| R07 | 방 · 방 밖 (원자료) Read | 훅 deny · Claude 가 본 것은 `DIODE: 방 밖 (AL-06)` 뿐 · 원자료 카나리아 0 |
| R08 | 방 · Bash | 방 설정의 deny 가 **도구 목록에서 Bash 를 먼저 뺐다** (훅까지 가지 않음) · 카나리아 0 |
| R09 | `python` 이 늘 실패 (훅 고장) | 막힘 · 모델 요청 0 (`onFailure: block`) |
| R10 | 원자료 폴더에서 연 세션 | 막힘 · 모델 요청 0 |
| R11 | 보통 폴더 · 원자료 Read | 훅 deny (안전벨트) · 카나리아 0 |
| R12 | 방에 `settings.local.json` (changed) | 막힘 · 모델 요청 0 |
| R13 | 방 · `--permission-mode bypassPermissions` | 막힘 · 모델 요청 0 |
| R14 | 원자료 폴더를 **품은** 위 폴더에서 연 세션 | 막힘 · 모델 요청 0 |
| R15 | 한계 기록: 설정 전 (데이터 폴더 없음) 보통 폴더 · 사전 단어 | **지나간다** (모델 요청 1) — 설정 전에는 지켜지지 않는다 (MANUAL › 알려진 한계 · 세션 시작 때 알림) |
| R16 | 방 · 플러그인 허브가 뜨고 `dispatch` 결과가 고정 꼴 한 줄 (일꾼 없음) | `E-01` 한 줄 · 안쪽 글 없음 |
| R17 | 슬래시 명령 `/diode:status` (보통 폴더) | `${CLAUDE_PLUGIN_ROOT}` 가 풀림 · 점검 결과가 Claude 에게 한 번에 도착 · 사전 단어 없음 |
| R18 | 보통 폴더 · 데이터 폴더의 사전 파일 Read | 훅 deny · 사전 단어가 Claude 에게 가지 않음 |
| R27 | 보통 폴더 · 데이터 폴더의 가명 금고 (`vault/P-0001.vault`) Read | 훅 deny · 금고 안의 값이 Claude 에게 가지 않음 |
| R28 | 보통 폴더 · 셸이 데이터 폴더의 위 폴더로 옮긴 뒤 상대 경로로 금고를 `cat` | 훅 deny (폴더 이름 규칙 · 이 규칙이 없으면 통과했다) |
| R29 | 방 · 확정된 가린 묶음 파일 (`outbox/J-0001/F01.py` · 감사 기록에 파일마다 `out · bundle · sent`) Read [2026-11-27] | 허락 · 토큰 꼴 글 (합성) 이 도구 결과로 Claude 에게 닿음 · 모델 요청 2 |
| R30 | 방 · 같은 폴더의 확정 기록 없는 파일 (`F02.py` · 원자료 카나리아) Read [2026-11-27] | 훅 deny (`DIODE V<Vth: 확정되지 않은 outbox (AL-13)`) · 카나리아 0 |
| R31 | 방 · 허브 `inbox` (ToolSearch → inbox) · 데이터 폴더 금고에 사전 단어 · 원래 이름 (원자료 이름 카나리아) [2026-11-27] | 결과는 `{"reports":[{"job":"J-0001","kind":"bundle","files":[…]}]}` 한 줄 — `MANIFEST.md` (manifest · 115 바이트) · `F01.py` (code · 89 바이트) 뿐 · 원래 이름 · 경로 · 금고 값 0 · 모델 요청 3 |
| R19 | 보통 폴더 · 플러그인 소스 폴더에 새 파일 Write | 훅 deny · 파일이 안 생김 |
| R20 | 보통 폴더 · 원자료 폴더 목록 밖의 파일인데 사내 단어가 든 것 Read | 훅 deny (내용을 본다) · 단어가 Claude 에게 가지 않음 |
| R21 | `/diode:dict` (tkinter 있는 파이썬 · Xvfb) | 정책 창이 따로 떼어져 뜸 (명령은 기다리지 않고 끝남) · 단어 없는 한 줄이 Claude 에게 감 |
| R22 | `/diode:setup` 첫 실행 (정책 없음) | 정책 창이 뜸 · 방은 만들지 않음 · 점검 결과가 Claude 에게 감 |
| R23 | `/diode:dict` (tkinter 없는 파이썬) | 창을 열었다고 하지 않고 `E-07` 로 실패 · 모델 요청 0 · 창 프로세스 없음 |

**R29–R31 다시 돌림** [2026-11-27 · Claude Code 2.1.318 (npm 고정판) · 리눅스 · Python 3.13]: `python kit/run_hooks.py --only R18,R27,R28,R29,R30,R31` → 여섯 모두 OK · `결과: OK`. 같은 날 R01–R31 전체도 `결과: OK` (R21 · R22 · R23 · R26 은 DISPLAY 가 없어 건너뜀). 대조로 감사 기록 (`confirm`) 을 빼고 돌리면 R29 는 deny, R31 은 `{"reports":[]}` 로 실패한다 — 허락은 확정 기록에서만 온다. 같은 여섯을 Claude Code 2.1.332 (이 컨테이너에 깔린 판) 로도 돌려 모두 OK 였다 · 대조 (R29 에서 확정 기록을 뺌) 는 2.1.318 로 다시 돌려 실패 (deny) 를 확인했다.

**처음부터 끝까지** (`kit/run_install.py` · 리눅스 · Claude Code 2.1.318): 마켓플레이스 추가 · 설치 (I1) → 정책 입력 → `/diode:setup` 이 방을 만들고 점검 결과가 Claude 에게 감 · 사전 단어 없음 (I2) → 방에서 깨끗한 말은 감 (I3) · 사전 단어 변형은 모델 요청 0 (I4) · 허브가 뜨고 `dispatch` 가 고정 꼴 `E-01` (I5) · 원자료 읽기는 막히고 카나리아가 안 감 (I6) — 모두 OK.

- **`!` 명령은 종료 코드가 0 이 아니면 명령 전체를 실패로 본다** [실험 R17]. 출력은 나오지만 Claude 에게 넘기지 않고, 모델 요청도 0 이다. 그래서 슬래시 명령은 `--report` (종료 코드가 늘 0) 로 부른다. 상태는 결과 줄 (`결과: 확인 필요`) 이 알려 준다.
- **`Write` 는 이미 있는 파일을 읽지 않았으면 입력 검증에서 먼저 거절한다.** 훅까지 가지 않는다. 그래서 훅 시험은 새 파일로 해야 한다 [실험 R19 첫 시도].
- argparse 의 `REMAINDER` 는 첫 인자가 옵션 꼴 (`--check`) 이면 거부한다. 그래서 명령마다 인자를 하나하나 적는다 [실험].

- 방의 도구 목록에 `ListAgents` · `ReportFindings` · `ScheduleWakeup` · `Workflow` 처럼 판마다 다른 도구가 보였다. 이런 도구는 허용 목록 밖이라 훅이 deny 한다 (새 도구도 막는 쪽으로 간다).
- Windows 에서 다시 하는 시험은 사내에서 한다 (`python run_hooks.py` — 훅의 Python 명령은 `python`).

## 가린 묶음 코퍼스 (SP-20) [2026-11-27 · 리눅스 · Python 3.13 · 3.8]

`python kit/bundle_corpus.py` — 합성 묶음을 결정적으로 만들어 진짜 금고 (임시 데이터 폴더 · 평문) · 진짜 정책 (`scan.policy_from_home` · 합성 사전 다섯 낱말) 으로 `bundle.build_bundle` 에 돌린다. 묶음마다 새 작업 묶음을 열고 닫는다 (금고 값 재등장 범주만 앞 묶음을 먼저 보낸다). 코퍼스 `de917568de0eee19` (sha256 앞 16자). 3.13 · 3.8 의 숫자가 같았고, 세 번 돌려 출력이 같았다 (토큰은 무작위지만 개수는 같다).

| 무리 | 묶음 | 결과 |
|---|---|---|
| good — 표시를 제대로 한 문서 12 (md · txt) · 표 8 (csv · tsv) · 코드 16 (py 6 · js 5 · sql 5) · 여러 파일 2 | 38 | 통과 38/38 · 왕복 일치 38/38 (금고로 되돌린 글 = 원문에서 표시 기호만 뺀 글) · 자동 가림 1 (여러 파일 묶음에서 다른 파일이 표시한 값) |
| leaky — 표시를 빠뜨리거나 틀린 꼴 | 103 | 막음 103/103 (100.0%) |
| known-miss — SP-20 › 남는 위험의 꼴 (합격 기준 밖) | 21 | 지나감 19/21 (90.5%) |

leaky 범주별 (한 묶음을 여러 검사가 잡으면 모두 센다):

| 범주 | 막음 | 잡은 검사 |
|---|---|---|
| 사전 단어 변형 (전각 · 키릴 닮은 글자 · 보이지 않는 글자 · 자모 풀어쓰기 · 정규식 밖 구분자 · 1/0 닮은 꼴 · 결합 부호 · 줄 넘김 · 전각 밑줄) | 10/10 | R1 10 |
| 금고 값 재등장 (앞 묶음에서 표시한 값의 변형) | 7/7 | R2 7 · R4 1 |
| 드라이브 경로 | 6/6 | R3 6 |
| UNC | 5/5 | R3 5 |
| URL | 5/5 | R3 5 |
| IP (문서용 대역) | 5/5 | R3 5 · R4 5 |
| 메일 | 5/5 | R3 5 |
| 따옴표 안 호스트 (코드) | 5/5 | R3 5 · R5 1 |
| 주석 안 호스트 (코드) | 5/5 | R3 5 · R5 1 |
| 세 자리 수 | 5/5 | R4 5 |
| 소수 | 5/5 | R4 5 |
| 날짜 | 5/5 | R4 5 |
| 시각 (코드의 문자열 안) | 5/5 | R4 5 |
| base64 · hex 비밀 (실행할 때 해시로 만든 것) | 6/6 | R4 3 · R5 6 |
| 모르는 토큰 | 5/5 | R6 5 |
| 깨진 토큰 | 5/5 | R6 5 |
| 틀린 표시 (닫히지 않음 · 짝 없는 닫음 · 빈 값 · 모르는 머리 글자 · 겹침 · 줄바꿈 · 낱말에 붙음 · 512자 넘음) | 8/8 | E-04 8 |
| 설정 · 셸의 따옴표 없는 호스트 (yaml · ini · sh · env · toml · ps1 — type 을 code 라고 적음) | 6/6 | R3 6 · R5 1 |

known-miss 범주별 (지나간 수 그대로 — 숨기지 않는다):

| 범주 | 지나감 | 무엇 |
|---|---|---|
| 사전 · 금고에 없는 새 이름 | 5/5 | 표시도 사전도 금고도 없는 고유 명사는 R1–R6 이 모른다 |
| 이름 속 숫자 (code) | 4/4 | `temp_350` · `A350` 꼴 — code 규칙은 이름에 붙은 숫자를 세지 않는다 |
| 식별자로 쓴 호스트 (code) | 3/4 | 따옴표 밖의 점 찍은 이름 — 하나는 숫자가 든 20자 이름이라 R5 (덩어리) 가 우연히 잡았다 |
| 역슬래시 하나의 상대 경로 (code) | 3/3 | `data\a.csv` 꼴 — 정규식 이스케이프와 가릴 수 없어 세지 않는다 |
| 구역 판단이 틀리는 언어 (code) | 4/5 | heredoc · C# `@"…\"` · JS 정규식 글 안의 따옴표 · SQL 글의 역슬래시는 지나갔다. Rust `'a` 는 구역이 줄 끝까지 넓게 어긋나 R3 가 잡았다 |

- **증명하는 것**: 이 코퍼스의 꼴에서 잔여 검사 R1–R6 와 표시 꼴 검사 (E-04) 가 표시 빠뜨림 · 틀림을 모두 막고, 제대로 표시한 문서 · 표 · 코드는 헛걸림 없이 통과하며 되돌리기가 정확하다. `tests/test_corpus_gate.py` 가 이 합격 기준 (good 38/38 · 왕복 38/38 · leaky 103/103) 을 CI 에서 지킨다.
- **증명하지 않는 것**: known-miss 의 꼴 (위 표) 은 D7 (사내 LLM) 과 D8 (사람) 이 문이다. 코퍼스는 지어낸 짧은 묶음이라 실제 코드 · 문서의 헛걸림 비율은 따로 재야 한다 (SP-20 › 코드 파일의 R3 · R4 의 6.65% → 3.31% 는 이 저장소 코드 기준). 사내 사전 · 사내 모델의 표시 습관 (opencode 가 무엇을 빠뜨리나) 은 사내에서 본다.
