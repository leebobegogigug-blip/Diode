# Diode — 에이전트 작업 규칙

> **적용 범위.** 이 파일은 diode 저장소의 코드와 문서를 **수정하는** 작업에만 적용됩니다.
> 앱을 설치하는 중(`INSTALL.md` 따라 하기)이거나 앱을 사용하는 중이라면 이 파일은 무시하고 원래 받은 지시를 따르세요.
> 이 저장소에는 `CLAUDE.md`가 없습니다. 플러그인 최상위 폴더에 `CLAUDE.md`가 있으면 `claude plugin validate`가 경고를 내기 때문입니다. Claude Code v2.1.277 이상은 작업 폴더나 상위 폴더에 `CLAUDE.md`가 없으면 `AGENTS.md`를 자동으로 읽습니다([문헌: Claude Code memory 문서 · 2026-11-05](https://code.claude.com/docs/en/memory)). 그보다 낮은 버전이거나 상위 폴더에 `CLAUDE.md`가 있어 이 파일이 자동으로 읽히지 않는다면, 작업을 시작할 때 직접 읽으세요.

## 시작하기 전에

1. 읽는 순서: **AGENTS.md → [RULES.md](RULES.md) → [docs/SPEC.md](docs/SPEC.md) → [docs/PLAN.md](docs/PLAN.md)**. 계약(필드 · 판정 · 출력 형식 · 오류 코드)은 `SPEC.md`가 기준 문서이고, 설계 배경 · 불변식(AL) · 유출 경로(L) · 리스크(R)는 `PLAN.md`가 기준 문서입니다. `PLAN.md`는 분량이 길므로 작업과 관련된 절을 끝까지 읽으면 됩니다.
2. README나 소개 문서를 쓸 때는 **[docs/BLUEPRINT.md](docs/BLUEPRINT.md)를 PN junction 비유의 공식 기준으로 삼습니다.** 해당 문서와 다른 비유를 새로 만들지 않습니다.
3. 화면 · 문서 · 이미지를 다룰 때는 works의 [DESIGN.md](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DESIGN.md)도 함께 읽습니다. 문서를 쓰거나 수정할 때는 [docs/STYLE.md](docs/STYLE.md)(문체 기준)를 먼저 읽습니다.
4. 규칙과 충돌하는 요청을 받으면, 작업 전에 어느 조항과 부딪히는지 사용자에게 알리고 답을 기다립니다([works DEVELOP D-02](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DEVELOP.md#d-02-부딪히면-멈추고-말한다)). 검증 스크립트에 걸리지 않으려고 문자열을 잘게 쪼개거나 테스트를 느슨하게 고치는 우회는 하지 않습니다.

## 헌법 요약 — 기준 문서는 RULES.md

- W-01 **저장소 하나 = 플러그인 하나 = 마켓플레이스 하나** — 이름은 번호 없이 `diode` · `bin/`과 루트 `CLAUDE.md` 없음
- W-02 **의존성 0** — 실행 코드는 Python 3.8+ 표준 라이브러리만 사용
- W-03 **내 PC에서만** — `127.0.0.1` 바인딩 · 외부 CDN · 웹 폰트 금지
- W-04 **비밀은 어디에도 찍지 않는다** — 출력 · 로그 · 명령줄 · 커밋 모두 금지
- W-05 **사용자 원문은 메모리에만** — 원문은 디스크에 저장하지 않음 · 가명 표는 작업 묶음 금고만 DPAPI로 암호화해 저장
- W-06 **저장은 깨지지 않게** — 버전 명시 · 원자적 쓰기 · `%LOCALAPPDATA%\diode` · 테스트는 `DIODE_HOME`
- W-07 **바꾸기 전에 보여 준다** — 승인 창(confirm window)이 유일한 관문
- W-08 **설치는 에이전트가, 되돌릴 수 있게** — `INSTALL.md` 필수 절 준수 · 관리자 권한 금지
- W-09 **이름을 바꾸면 데려간다** — 공개 후에는 `diode` 이름을 변경하지 않음
- W-10 **디자인은 하나** — works `DESIGN.md` 준수 · 네이비 · 라임 · 회색 · 빨강 금지(예외: README 대표 그림 `docs/img/diode-banner.png` 한 장)
- W-11 **약속은 CI가 지킨다** — 자체 검증 스크립트 · 모의 서버 · 검증 가능한 수치만 기재
- W-12 **공개 저장소다** — 사내 정보 금지 · 영감 고지문 유지

## 공개 저장소 원칙 (W-12)

- 사내 이름(회사 · 제품 · 공정 · 고객 · 사람 · 시스템) · 사내 경로 · 사내 주소 · 사내 모델 이름 · 사내 TUI 이름 · **실데이터는 절대 사용하지 않습니다.** 코드 · 테스트 · 문서 · 커밋 메시지 · 보고서 모두 마찬가지입니다.
- 예시와 테스트 데이터는 가상의 값만 씁니다. 주소는 `example.com` · `*.local`처럼 실제로 없는 도메인을 사용하고, 사설 IP 형식의 가상 값은 `docs/SPEC.md`와 `tests/vectors/` 밖에서는 쓰지 않습니다(검증 스크립트가 차단합니다). 키나 토큰처럼 보이는 값도 테스트 코드에서 문자열 조각을 이어 붙여 생성합니다(파일에 통째로 적으면 검증 스크립트에 걸립니다).
- 사내 단어 목록 파일은 저장소 밖에 둡니다. 해당 파일은 열어 보거나 출력하지 않고, 검증 스크립트의 `--internal-words <파일>` 옵션으로만 전달합니다(실제 단어는 출력되지 않고 개수만 나옵니다).
- `kit/out/`은 커밋하지 않습니다(M0 사전 검증 산출물이며 `.gitignore`로 차단됨). `-f` 옵션으로 강제 추가하지 않습니다.

## 코드 및 문서 작성 규칙

- **Python 3.8 호환 문법만** 사용합니다. 자주 실수하는 항목: 딕셔너리 병합 `a | b` · `str.removeprefix` · 런타임 환경의 `list[int]` · `match` · 괄호로 묶은 다중 `with` · `zoneinfo` · `functools.cache` · `ast.unparse`. 정리된 표는 [works DEVELOP D-05](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DEVELOP.md#d-05-둘레-코드처럼-쓴다)를 참고하세요.
- 실행 코드(`diode.py` · `diodelib/`)에는 표준 라이브러리 외의 import를 넣지 않습니다. 함수 내부나 `try` 블록 안에서도 마찬가지입니다(W-02). `tests/`와 `tools/`에서는 외부 패키지를 사용할 수 있습니다.
- 주석 · 화면 문구 · 오류 메시지는 한국어로, 코드 식별자(변수 · 함수 · 파일명)는 영어로 씁니다. 이모지와 전각(2칸 폭) 기호는 넣지 않습니다.
- hook의 Python 명령은 이름만 적습니다(`python`). 절대 경로를 적으면 hook 실패 시 사용자 이름이 포함된 경로가 Claude로 넘어갈 수 있기 때문입니다(L-30).
- 차단 사유 · 로그 · 출력에는 사전 단어 · 사내 단어 · 경로를 남기지 않고, 개수와 검사 번호만 표시합니다(AL-11).
- 새로운 한도 · 이름 · 경로는 모듈 최상단 상수로 둡니다. 요청에 없는 새 파일 · 설정 키 · 명령 · 옵션은 만들지 않습니다.

## 이미 동작 중인 보안 장치 — 임의로 건드리지 않습니다 (v0.0)

- `hooks/hooks.json` · `.mcp.json` · `commands/`와 hook(`diodelib/hook.py`) · hub(`diodelib/hub.py`) · 승인 창 · 정책 창은 **현재 실제로 동작하며 차단 역할을 수행하고 있습니다.** 새 hook 규칙 · hub 도구 · 커맨드를 추가할 때는 이를 검증하는 단위 테스트(`tests/test_hook.py` 등)와 실제 CLI 시나리오(`kit/run_hooks.py`)를 같은 커밋에 함께 포함해야 합니다. 문서에만 먼저 적어 두면 실제로 막지 못하면서 막는 것처럼 오해할 수 있습니다.
- 세션이 실행 중인 동안에는 hook이 플러그인 소스를 수정하지 못하도록 차단합니다(AL-12). 이 저장소를 Claude Code로 수정할 때는 해당 플러그인을 끄고 열어야 합니다.
- `diodelib/__init__.py`에는 이름과 버전 상수만 둡니다. 기능 모듈은 그 옆에 하나씩 추가합니다.
- `SKILL.md`는 안내문일 뿐 강제 수단(벽)이 아닙니다(AL-09). 실제 차단은 코드 · 권한 · 승인 창이 담당합니다. 스킬 파일에는 Claude로 닿는 우회 경로를 적지 않습니다(AL-01).
- hook이나 검사기를 수정하기 전에 [docs/MANUAL.md › 알려진 한계](docs/MANUAL.md#알려진-한계)를 먼저 읽습니다. 이미 알려진 한계를 새로 발견한 것처럼 다루지 않고, 코드로 확실히 차단할 수 있는 영역과 사람 승인(D8) · 사내 LLM 판정(D7)에 의존하는 영역을 구분합니다.

## 함께 수정해야 할 곳

| 수정 항목 | 같은 커밋에서 함께 수정할 곳 | 누락 시 잡는 곳 |
|---|---|---|
| `VERSION` (`diodelib/__init__.py`) | `.claude-plugin/plugin.json`의 `version` | 테스트 |
| 테스트 추가 또는 삭제 | `README.md`의 `테스트 N` (실제 실행 결과 수치) | `tools/diode_check.py` |
| 명령 · 옵션 · 출력 · 종료 코드 | `docs/MANUAL.md` · `docs/SPEC.md` (SP-16) · `README.md` 사양 | 테스트 · 리뷰 |
| 필드 · 형식 · 설정 키 | `docs/SPEC.md` · `schema/` · 형식 버전(`format`) | 테스트 |
| `RULES.md` 조항 | 이 파일의 헌법 요약 · 검증 스크립트 | 테스트 |
| 플러그인 파일(`.claude-plugin/` · `skills/` · hook · hub) | `claude plugin validate .` 실행해 경고 0 확인 | 리뷰 · `tools/diode_check.py`(이름·JSON만 확인) |

## 작업 완료 전 확인 사항

- `python -m unittest discover -s tests` — 실패 0건. Python 3.8 환경이 있으면 3.8에서도 실행합니다(없으면 보고서에 "3.8은 CI에 위임"이라고 적습니다).
- `python tools/diode_check.py --strict` — 위반 0건(마지막 줄이 `결과: OK`).
- 플러그인 파일을 수정했다면 `claude plugin validate .`가 경고 없이 통과해야 합니다. `claude` 명령이 없으면 실행하지 못했다고 명시합니다.
- 실행하지 못한 검사는 사유와 함께 명시하고, 실패한 경우에는 출력을 그대로 보여 줍니다.

## 커밋 · 보고 형식

- 커밋 메시지는 한국어로 `diode: 무엇 · 무엇` 형식으로 작성합니다([RULES.md › S-08](RULES.md#규약)). `무엇`에는 수정 결과를 사용자가 이해하기 쉽게 적고, "버그 수정" · "업데이트" 같은 단답으로 끝내지 않습니다. 본문은 빈 줄 → 변경 이유 → `-` 목록 순으로 작성합니다. 커밋 전 `git status`와 `git diff --staged`로 의도한 파일만 포함되었는지 확인합니다. 작업 브랜치에서 커밋하고, 메인 브랜치 병합(merge)은 사람이 진행합니다.
- 보고서는 [works DEVELOP D-11](https://github.com/leebobegogigug-blip/Works/blob/13e56a0a5801da56dc18523363cd219ebf6d2e21/docs/DEVELOP.md#d-11-보고는-한-모양으로) 형식을 그대로 따릅니다: 한 일 · 고친 곳 · 테스트 · 검사 · 부딪힌 조항 · 남은 위험. 항목을 빼지 않고, 해당 내용이 없으면 `없음`으로 적습니다. 보고서에 키 · 토큰 · 사내 이름은 절대 넣지 않습니다.
