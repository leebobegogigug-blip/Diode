# diode — 에이전트 규칙

> **적용 범위.** 이 파일은 diode 저장소의 코드 · 문서를 **고치는** 작업에만 적용한다.
> 앱 설치 (`INSTALL.md` 따라 하기) · 앱 사용 중이라면 이 파일을 무시하고 원래 지시를 따른다.
> 이 저장소에는 `CLAUDE.md` 가 없다 — 플러그인 루트의 `CLAUDE.md` 는 `claude plugin validate` 가 경고한다. Claude Code v2.1.277 이상은 작업 폴더나 그 위에 `CLAUDE.md` 가 없으면 `AGENTS.md` 를 직접 읽는다 ([문헌: Claude Code memory 문서 · 2026-11-05](https://code.claude.com/docs/en/memory)). 그보다 낮은 판이거나 위 폴더에 `CLAUDE.md` 가 있어서 이 파일이 읽히지 않으면 시작할 때 직접 읽는다.

## 시작하기 전에

1. 읽는 순서: **AGENTS.md → [RULES.md](RULES.md) → [docs/SPEC.md](docs/SPEC.md) → [docs/PLAN.md](docs/PLAN.md)**. 계약 (칸 · 판정 · 출력 꼴 · 오류 번호) 은 SPEC 이 정본이고, 설계의 까닭 · 불변식 AL · 새는 길 L · 리스크 R 은 PLAN 이 정본이다. PLAN 은 길어서 일에 걸린 절을 끝까지 읽는다.
2. README · 소개 문서를 쓰면 **[docs/BLUEPRINT.md](docs/BLUEPRINT.md) 를 비유 (PN 접합) 의 정본으로 쓴다.** 그 문서와 다른 비유를 새로 만들지 않는다.
3. 화면 · 문서 · 이미지를 만지면 works 의 [DESIGN.md](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DESIGN.md) 도 읽는다.
4. 규칙과 부딪히는 요청을 받으면, 하기 전에 어느 조항과 부딪히는지 사용자에게 말하고 답을 기다린다 ([works DEVELOP D-02](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DEVELOP.md#d-02-부딪히면-멈추고-말한다)). 검사기에 안 걸리게 문자열을 쪼개거나 테스트를 약하게 하는 것은 비켜 가기라서 하지 않는다.

## 헌법 요약 — 정본은 RULES.md

- W-01 **저장소 하나 = 플러그인 하나 = 마켓플레이스 하나** — 이름은 번호 없이 `diode` · `bin/` 과 루트 `CLAUDE.md` 없음
- W-02 **의존성 0** — 실행은 Python 3.8+ 표준 라이브러리만
- W-03 **내 PC 에서만** — `127.0.0.1` 바인딩 · 외부 CDN · 웹 폰트 금지
- W-04 **비밀은 어디에도 찍지 않는다** — 출력 · 로그 · 명령줄 · 커밋 모두
- W-05 **사용자 원문은 메모리에만** — 원문 · 가명 표는 디스크에 쓰지 않는다
- W-06 **저장은 깨지지 않게** — 버전 · 원자적 쓰기 · `%LOCALAPPDATA%\diode` · 테스트는 `DIODE_HOME`
- W-07 **바꾸기 전에 보여 준다** — 확정 창이 전부다
- W-08 **설치는 에이전트가, 되돌릴 수 있게** — INSTALL.md 필수 절 · 관리자 권한 금지
- W-09 **이름을 바꾸면 데려간다** — 공개한 뒤에는 `diode` 를 바꾸지 않는다
- W-10 **디자인은 하나** — works DESIGN.md · 네이비 · 라임 · 회색 · 빨강 없음 (예외: README 대표 그림 `docs/img/diode-banner.png` 한 장)
- W-11 **약속은 CI 가 지킨다** — 자기 검사기 · 가짜 서버 · 검증 가능한 숫자만
- W-12 **공개 저장소다** — 사내 정보 금지 · 영감 고지문

## 공개 저장소다 (W-12)

- 사내 이름 (회사 · 제품 · 공정 · 고객 · 사람 · 시스템) · 사내 경로 · 사내 주소 · 사내 모델 이름 · 사내 TUI 이름 · **실데이터를 쓰지 않는다.** 코드 · 테스트 · 문서 · 커밋 메시지 · 보고 모두 같다.
- 예시와 테스트 자료는 지어낸 것만 쓴다. 주소는 `example.com` · `*.local` 처럼 실재하지 않는 것이다. 사설 IP 꼴의 지어낸 값은 `docs/SPEC.md` 와 `tests/vectors/` 밖에 쓰지 않는다 (검사기가 잡는다). 키 · 토큰처럼 보이는 값은 시험 코드에서도 이어 붙여 만든다 (파일에 그대로 쓰면 검사기가 잡는다).
- 사내 단어 목록 파일은 저장소 밖에 둔다. 그 파일은 열어 보거나 출력하지 않고, 검사기의 `--internal-words <파일>` 로만 쓴다 (낱말은 찍히지 않고 개수만 나온다).
- `kit/out/` 은 커밋하지 않는다 (M0 정찰 산출물 · `.gitignore` 가 막는다). `-f` 로 넣지 않는다.

## 쓰는 법

- **Python 3.8 에서 도는 것만** 쓴다. 자주 틀리는 것: 사전 합치기 `a | b` · `str.removeprefix` · 실행되는 곳의 `list[int]` · `match` · 괄호로 묶은 여러 `with` · `zoneinfo` · `functools.cache` · `ast.unparse`. 표는 [works DEVELOP D-05](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DEVELOP.md#d-05-둘레-코드처럼-쓴다).
- 실행 코드 (`diode.py` · `diodelib/`) 에는 표준 라이브러리 밖의 import 를 쓰지 않는다 — 함수 안 · `try` 안도 같다 (W-02). `tests/` · `tools/` 는 외부 패키지를 써도 된다.
- 주석 · 화면 문구 · 오류 글은 한국어, 코드 이름 (변수 · 함수 · 파일) 은 영어다. 이모지와 폭 2칸 기호를 넣지 않는다.
- 훅의 Python 명령은 이름만 적는다 (`python`) — 절대 경로를 적으면 훅이 고장 났을 때 사용자 이름이 든 경로가 Claude 에게 간다 (L-30).
- 막은 까닭 · 로그 · 출력에 사전 단어 · 사내 단어 · 경로를 쓰지 않는다. 개수 · 검사 번호만 쓴다 (AL-11).
- 새 한도 · 이름 · 경로는 모듈 위의 상수로 둔다. 요청에 없는 새 파일 · 설정 키 · 명령 · 옵션을 만들지 않는다.

## 이미 막고 도는 것 - 함부로 건드리지 않는다 (v0.0)

- `hooks/hooks.json` · `.mcp.json` · `commands/` 와 훅 (`diodelib/hook.py`) · 허브 (`diodelib/hub.py`) · 확정 창 · 정책 창은 **실제로 막고 돈다**. 새 훅 규칙 · 허브 도구 · 명령을 더하면 막는 시험 (`tests/test_hook.py` 류) 과 진짜 CLI 시나리오 (`kit/run_hooks.py`) 를 같은 커밋에서 더한다 - 먼저 문서에만 적으면 막지도 못하면서 막는 것처럼 보인다.
- 세션 중에는 훅이 플러그인 소스를 쓰지 못하게 막는다 (AL-12). 이 저장소를 Claude Code 로 고칠 때는 이 플러그인을 끄고 연다.
- `diodelib/__init__.py` 에는 이름 · 버전 상수만 둔다. 모듈은 옆에 하나씩 더한다.
- `SKILL.md` 는 안내일 뿐 벽이 아니다 (AL-09). 막는 일은 코드 · 권한 · 확정 창이 한다. 스킬에 Claude 에 닿는 다른 길을 적지 않는다 (AL-01).
- 훅 · 검사기를 고치기 전에 [docs/MANUAL.md › 알려진 한계](docs/MANUAL.md#알려진-한계) 를 읽는다 - 이미 알려진 한계를 새 발견으로 다루지 않고, 확정적으로 막을 수 있는 것과 사람 확정 (D8) · 사내 LLM 판정 (D7) 에 기대는 것을 구별한다.

## 같이 바꿀 곳

| 바꾸는 것 | 같은 커밋에서 같이 | 빠뜨리면 잡는 것 |
|---|---|---|
| `VERSION` (`diodelib/__init__.py`) | `.claude-plugin/plugin.json` 의 `version` | 시험 |
| 테스트를 더하거나 지움 | README 의 `테스트 N` (돌려서 얻은 수) | `tools/diode_check.py` |
| 명령 · 옵션 · 출력 · 종료 코드 | `docs/MANUAL.md` · `docs/SPEC.md` (SP-16) · README 사양 | 시험 · 사람 |
| 칸 · 형식 · 설정 키 | `docs/SPEC.md` · `schema/` · 형식 버전 (`format`) | 시험 |
| RULES.md 조항 | 이 파일의 헌법 요약 · 검사기 | 시험 |
| 플러그인 파일 (`.claude-plugin/` · `skills/` · 훅 · 허브) | `claude plugin validate .` 를 돌려 경고 0 으로 | 사람 · `tools/diode_check.py` 가 이름 · JSON 만 본다 |

## 끝내기 전에

- `python -m unittest discover -s tests` — 실패 0. Python 3.8 이 있으면 3.8 에서도 돌린다 (없으면 "3.8 은 CI 에 맡김" 이라고 보고에 적는다).
- `python tools/diode_check.py --strict` — 위반 0 (마지막 줄 `결과: OK`).
- 플러그인 파일을 고쳤으면 `claude plugin validate .` — 경고 없이 통과. `claude` 명령이 없으면 못 돌렸다고 쓴다.
- 돌리지 못한 검사는 못 돌렸다고 까닭과 함께 쓴다. 실패는 출력 그대로 보인다.

## 커밋 · 보고

- 커밋은 한국어로 `diode: 무엇 · 무엇` ([RULES.md › S-08](RULES.md#규약)). `무엇` 은 고친 결과를 사용자가 알아듣는 말로 쓴다 — "버그 수정" · "업데이트" 한 낱말로 끝내지 않는다. 본문은 빈 줄 → 왜 → `- ` 목록으로 무엇. 커밋 전에 `git status` · `git diff --staged` 로 의도한 파일만 들어갔는지 본다. 작업 가지에서 내고, 머지는 사람이 한다.
- 보고는 [works DEVELOP D-11](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DEVELOP.md#d-11-보고는-한-모양으로) 틀 그대로 한다: 한 일 · 고친 곳 · 테스트 · 검사 · 부딪힌 조항 · 남은 위험. 칸을 빼지 않고 — 없으면 `없음`. 보고에 키 · 토큰 · 사내 이름을 넣지 않는다.
