# M0 결과 — 리눅스판 (2026-11-05)

`kit/run_kit.py` 를 이 저장소를 만드는 세션 (Linux 컨테이너) 에서 돌린 결과다. 사내 Windows 판은 사내에서 같은 스크립트로 다시 돌린다 (`python run_kit.py --python python`).

- **조건**: Claude Code 2.1.318 (`claude -p` · print 모드) · 가짜 Anthropic 서버 (127.0.0.1 · `kit/fake_anthropic.py`) · 빈 환경 (허용 목록) · 임시 HOME · 임시 `CLAUDE_CONFIG_DIR` · 합성 자료와 카나리아만. 진짜 Anthropic 으로는 아무것도 가지 않았다 (가짜 서버에 모든 요청이 왔고, 부가 통신 끄는 환경 변수를 켰다).
- **원자료 덤프** (`kit/out/`) 는 커밋하지 않는다 — Claude Code 의 시스템 프롬프트 원문이 들어 있다. 이 문서에는 판정과 사실만 적는다.
- 표기: [실험] 이 실행에서 직접 본 것 · [문헌] 공개 문서 · [미확인] 아직 못 본 것.

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
| S16 | 방 설정 `permissions.blockReadsOutsideWorkingDirectories: true` · 플러그인 없이 | 방 밖 Read 가 **권한 층에서 막혔다** | 훅과 별개의 두 번째 벽 — 방 설정에 넣는다 (새로) |

## 02 기획에 주는 것 (8판 원고)

1. **방 설정 (`/diode:room` 이 쓰는 `.claude/settings.json`) 에 넷을 더한다** — `autoMemoryEnabled: false` · `claudeMdExcludes` (방 위 · 사용자 범위 `CLAUDE.md` · `AGENTS.md` · rules) · `permissions.blockReadsOutsideWorkingDirectories: true` · 권한 deny 규칙. 셋은 플러그인을 꺼도 방 설정으로 남는 벽이다.
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
| 대화형 TUI 세션 (print 모드와 시스템 프롬프트 · 폴더 신뢰 대화가 다를 수 있다) | 다음 — 리눅스 의사 터미널로 시도 · 사내 |
| Windows — exec 꼴 훅 (`python`) · 경로 꼴 · PowerShell 기본 셸 | 사내 (`python run_kit.py --python python`) |
| MCP 자식 프로세스에서 tkinter 확정 창 — Windows | 사내 (리눅스는 S18 로 확인) |
| statusLine 입력 칸 (대화형에서만 돈다) | 대화형과 같이 |
| opencode 일꾼에 지시 넣는 끝점 | 다음 — opencode 설치 · 가짜 사내 LLM 서버 |
| 회사 관리형 설정 (마켓플레이스 · 플러그인 묶음) · 사내 게이트웨이의 모델 이름 | 사내 |
