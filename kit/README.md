# kit/ — M0 정찰 키트

M0 (앱 코드 0줄 · 합성 자료만) 동안만 쓰는 폴더다. M0 가 끝나면 지운다 ([docs/PLAN.md](../docs/PLAN.md) › 10).

| 파일 | 무엇 |
|---|---|
| `security-brief.md` | 보안 부서에 보일 한 장 (T4 · KIT-5) |
| `results-linux.md` | 리눅스판 결과 (KIT-1 · KIT-2 · KIT-7) |
| `run_kit.py` | 시나리오 S01–S18 을 돌린다 (S18 은 DISPLAY 가 있을 때만) — 합성 자리 · 가짜 서버 · 빈 환경의 Claude CLI |
| `corpus/` · `canary_variants.py` · `leak_rate.py` · `test_corpus.py` | KIT-3 합성 말뭉치 40과제 (plan 15 · ui 15 · lib 10 · 카나리아 361) · 카나리아 변형 · 검사기 전후 새는 비율 · 시험 — 사내 절차와 G3 채점표는 `corpus/README.md` (T3) |
| `run_opencode.py` | 진짜 opencode 로 일꾼 부품 · 셸 권한 시험 (가짜 로컬 모델 · 선택 · `--opencode <경로>`) |
| `inhouse-questions.md` | **사내 확인 질문지** — 1부는 사내 Claude 에게 붙여 넣고 (예 · 아니오 · 숫자 · 보기로만 답하게 해서 이름 · 주소 · 경로가 바깥으로 안 나오게), 2부는 사람이 직접 돌릴 것 (옮길 줄이 정해져 있다) |
| `statusline_keys.py` | statusLine 입력 JSON 의 **칸 이름만** 찍는 도구 (값은 안 찍음 · 질문지 H4) |
| `run_hooks.py` | 진짜 훅 (저장소의 `hooks/hooks.json` · `diode.py hook`) 으로 KIT-2 재시험 R01–R23 (T12 · T19 — 훅 · 허브 · 슬래시 명령 · 데이터 폴더 보호) |
| `run_tui.py` | 대화형 (TUI) 세션 한 번 — 의사 터미널 (리눅스 · macOS) · statusLine 입력 칸 · `safeguards` 칸 |
| `fake_anthropic.py` | 가짜 Anthropic Messages API 서버 (127.0.0.1 · 요청을 덤프 · 키는 남기지 않음) |
| `probe_plugin/` | 최소 플러그인 — 허브 (`hub_min.py` · 표준 입출력 MCP) · 훅 (`hook_min.py` · 모드 셋) |

## 돌리기

```text
python run_kit.py                      리눅스 (python3)
python run_kit.py --python python      Windows — 훅 · 허브를 돌릴 Python 명령 이름
python run_kit.py --only S05,S14       일부만
```

- Claude CLI (`claude`) 와 Python 3.8 이상이 있어야 한다. 그 밖의 의존은 없다.
- 진짜 Anthropic 으로는 아무것도 가지 않는다: Claude CLI 를 빈 환경 (허용 목록) · 임시 HOME · 임시 `CLAUDE_CONFIG_DIR` 로 띄우고 `ANTHROPIC_BASE_URL` 을 127.0.0.1 의 가짜 서버로 둔다. 이 PC 의 Claude 설정 · 로그인 · 기록을 건드리지 않는다.
- 결과: `out/report.md` · `out/report.json` · 시나리오별 덤프 (`out/S01/001.json` …). `out/` 은 커밋하지 않는다 (Claude Code 시스템 프롬프트 원문이 들어 있다).
- 사내에서 돌린 결과를 공개 저장소로 가져올 때는 판정과 숫자만 옮긴다 — 덤프 · 사내 경로 · 사내 모델 이름은 옮기지 않는다.
