# CI 에서 돌린 진짜 Claude CLI 시험 결과 (Windows · Linux)

`.github/workflows/diode.yml` 의 `real-cli` job 이 push 마다 돌린다. 진짜 Anthropic 으로는 아무것도 가지 않는다 (127.0.0.1 가짜 서버 · 가짜 키 · 임시 HOME 과 LOCALAPPDATA).

| 항목 | 값 |
|---|---|
| 실행기 | GitHub Actions `windows-latest` (Git for Windows 의 bash 가 셸) · `ubuntu-22.04` |
| Python | 3.13 |
| Claude Code | 2.1.318 (고정 · npm) |
| 기록한 날 | 2026-11-06 |

## Windows (windows-latest)

| 시험 | 결과 | 확인한 것 |
|---|---|---|
| `kit/run_install.py` I1–I6 | 모두 OK | 로컬 폴더 마켓플레이스 추가 · 설치 · `/diode:setup` 이 방을 만든다 · 방에서 깨끗한 말은 가고 사전 단어 변형은 모델 요청 0 · 허브가 떠서 `dispatch` 결과가 고정 꼴 · 방에서 원자료 읽기는 막힘 |
| `kit/run_hooks.py` R01–R25 | 모두 OK | 훅 모드(방 · 원자료 폴더 · 보통 폴더) · 훅이 죽으면 막음 · 방 설정 변조 · 권한 모드 · 사전 파일/플러그인 소스 보호 · 안내 파일 사전 검사 · `/diode:status` 의 `${CLAUDE_PLUGIN_ROOT}` 가 풀림 · 정책 창이 따로 떼어져 뜨고 기다리지 않음 · tkinter 가 없으면 E-07 |
| `kit/run_kit.py` S01–S18 | 모두 종료 코드 0 | 바이트 정찰 (판정 없음 — 무엇이 요청에 실리는지 기록) |
| `kit/run_opencode.py` R1–R5 (opencode 1.19.5 · npm 으로 깔린 `.cmd` 껍데기) | 모두 OK | 일꾼 부품이 진짜 opencode 를 띄운다(표준 입력) · 허락한 `propose` 는 돌고 허락하지 않은 명령은 안 돈다 · 일꾼 전용 에이전트(`diode-worker`)에만 권한이 걸리고 평소 설정은 그대로 · 일꾼이 작업 폴더 안에는 쓰고 방에는 못 쓴다 · **R5: `{prompt}` 인자는 거절되고 표준 입력의 `& \| ^ % ! \"` 는 명령이 되지 않고 모델에 그대로 닿는다** |

Windows 에서 처음 돌린 실행이 찾은 것 둘:
- 일꾼의 작업 폴더가 러너의 8.3 짧은 이름(`RUNNER~1`)이면 opencode 가 자기 작업 폴더를 "밖"(`external_directory`)으로 보아 쓰기가 거절됐다(R3a). 일꾼 부품이 정규 경로(`os.path.realpath`)를 넘기게 고쳐 해결됐다.
- 키트의 버그 하나: Windows 에서 `HOME` 만 임시 폴더로 바꾸면 데이터 폴더(`%LOCALAPPDATA%\diode`)가 이 PC 의 진짜 자리를 가리켜 시험과 플러그인이 서로 다른 폴더를 봤다 (`clean_env` 가 `LOCALAPPDATA` · `APPDATA` 도 임시 HOME 아래로).

## 이 결과가 증명하지 않는 것

- **사내 PC 가 아니다.** 관리형 설정 · 단말 보안 · 회사 프록시 · 사내 모델/게이트웨이 · 사내 판의 Claude CLI 에서는 따로 확인해야 한다 (`kit/inhouse-questions.md` 2부).
- **창이 눈에 보이는지는 모른다.** CI 의 Windows 는 사람이 보는 화면이 아니다. 정책 창 · 확정 창이 "뜬다" 는 것은 프로세스가 떴다는 뜻이고, 맨 위에 보이는지 · 글자 크기(DPI) · 한글 입력(IME) 은 사람이 본다.
- **`python` 이름.** 러너는 `python` 이 PATH 에 있다. 사내 PC 에서 Microsoft Store 별칭이나 `py` 만 있으면 훅이 죽고 (막는 쪽으로 실패) 쓸 수 없다 — INSTALL.md 1단계가 먼저 본다.
- 일꾼(opencode)을 부리는 **사내 모델/게이트웨이** 는 CI 에 없다 - 가짜 로컬 모델(127.0.0.1)로 도구 호출만 흉내 냈다. 사내 opencode 의 실제 권한 기본값(`bash` 가 `allow` 인지 `ask` 인지)은 사내 확인 질문지(Q27)가 받는다.
