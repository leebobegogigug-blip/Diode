# kit/ — M0 정찰 키트

이 폴더는 M0 단계 (앱 코드 0줄 · 지어낸 자료만 쓰는 정찰 단계) 동안만 쓴다. M0 가 끝나면 지운다 ([docs/PLAN.md](../docs/PLAN.md) › 10).

| 파일 | 무엇 |
|---|---|
| `security-brief.md` | 보안 부서에 보여 줄 한 장 (T4 · KIT-5) |
| `results-linux.md` | 리눅스에서 돌린 결과 (KIT-1 · KIT-2 · KIT-7) |
| `results-ci.md` | CI 의 Windows · Linux 에서 진짜 Claude CLI 로 돌린 시험 결과 (I1–I6 · R01–R25 · S01–S18) 와, 그 결과가 증명하지 않는 것 |
| `run_kit.py` | 시나리오 S01–S18 을 돌린다 (S18 은 DISPLAY 가 있을 때만). 지어낸 자리 · 가짜 서버 · 빈 환경의 Claude CLI 를 쓴다 |
| `corpus/` · `canary_variants.py` · `leak_rate.py` · `test_corpus.py` | KIT-3 합성 말뭉치 (지어낸 시험 자료 묶음) 40과제 (plan 15 · ui 15 · lib 10 · 카나리아 361) · 카나리아 변형 · 검사기 전후 새는 비율 · 시험. 사내에서 돌리는 절차와 G3 채점표는 `corpus/README.md` (T3) 에 있다 |
| `run_opencode.py` | 진짜 opencode 로 일꾼 부품 · 셸 권한을 시험한다 (가짜 로컬 모델 · 꼭 돌릴 필요는 없다 · `--opencode <경로>`) |
| `inhouse-questions.md` | **사내 확인 질문지** — 1부는 사내 Claude 에게 붙여 넣는다 (예 · 아니오 · 숫자 · 보기로만 답하게 해서 이름 · 주소 · 경로가 바깥으로 안 나오게 한다). 2부는 사람이 직접 돌린다 (옮겨 적을 줄이 정해져 있다) |
| `reid_sim.py` · `results-reid.md` | **L2 파생 표본 재식별 위험 시뮬레이션** (T3b · 방어 평가) — 지어낸 표로 "보조 열을 아는 공격자가 파생 행을 몇 % 가려내나" 를 잰다 (`--quick` 은 CI 용). 숫자 · 쉬운 말 해석 · 제안 합격선 · 권고 표는 `results-reid.md` |
| `statusline_keys.py` | statusLine (화면 아래 상태줄) 입력 JSON 의 **칸 이름만** 찍는 도구 (값은 찍지 않는다 · 질문지 H4) |
| `run_install.py` | **처음부터 끝까지** — 마켓플레이스로 설치 → 정책 입력 → `/diode:setup` 이 방을 만듦 → 방 안 세션이 훅 · 허브 아래에서 도는지 확인 (I1–I6 · 임시 HOME · 가짜 서버) |
| `run_hooks.py` | 진짜 훅 (저장소의 `hooks/hooks.json` · `diode.py hook`) 으로 KIT-2 를 다시 시험한다 R01–R23 (T12 · T19 — 훅 · 허브 · 슬래시 명령 · 데이터 폴더 보호) |
| `run_tui.py` | 대화형 (TUI) 세션을 한 번 돌린다 — 의사 터미널 (리눅스 · macOS) · statusLine 입력 칸 · `safeguards` 칸 |
| `fake_anthropic.py` | 가짜 Anthropic Messages API 서버 (127.0.0.1 · 받은 요청을 파일로 덤프 · 키는 남기지 않는다) |
| `probe_plugin/` | 아주 작은 시험용 플러그인 — 허브 (`hub_min.py` · 표준 입출력 MCP) · 훅 (`hook_min.py` · 모드 셋) |

## 돌리기

```text
python run_kit.py                      리눅스 (python3)
python run_kit.py --python python      Windows — 훅 · 허브를 돌릴 Python 명령 이름
python run_kit.py --only S05,S14       일부만
```

- Claude CLI (`claude`) 와 Python 3.8 이상이 있어야 한다. 그 밖에 깔 것은 없다.
- 진짜 Anthropic 으로는 아무것도 가지 않는다. Claude CLI 를 빈 환경 (허용한 것만 있는 환경) · 임시 HOME · 임시 `CLAUDE_CONFIG_DIR` 로 띄우고, `ANTHROPIC_BASE_URL` 을 127.0.0.1 의 가짜 서버로 돌려 둔다. 이 PC 의 Claude 설정 · 로그인 · 기록은 건드리지 않는다.
- 결과는 이렇게 남는다: `out/report.md` · `out/report.json` · 시나리오별 덤프 (`out/S01/001.json` …). `out/` 은 커밋하지 않는다 (Claude Code 시스템 프롬프트 원문이 들어 있기 때문이다).
- 사내에서 돌린 결과를 공개 저장소로 가져올 때는 판정과 숫자만 옮긴다. 덤프 · 사내 경로 · 사내 모델 이름은 옮기지 않는다.
