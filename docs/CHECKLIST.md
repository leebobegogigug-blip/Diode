# Diode 사내 검증 체크리스트 — 에이전트용

> **개발 중 (v0.0) — 이 체크리스트를 다 통과하기 전에는 real data(실데이터)를 쓰지 않습니다.** 모든 확인은 synthetic data(지어낸 자료)로만 합니다.

**사용자용 한 줄 프롬프트:** 회사 Claude Code 에 아래 문장을 그대로 붙여 넣으면, 이 문서 순서대로 검증을 진행합니다.
"`D:\claude\diode\docs\CHECKLIST.md` 를 끝까지 읽고 순서대로만 진행해. 사내 단어 · 사내 경로 · 사내 주소 · 키는 출력하지 말고, [질문] 표시가 있는 곳에서는 멈추고 나한테 물어봐. 마지막에 9번 보고 양식으로만 보고해."

이 문서는 **에이전트가 순서대로 따라 하는 점검표**입니다. 에이전트 = 사람 대신 명령을 실행하는 AI 도우미입니다. 각 단계는 `명령 → 확인 → 실패하면` 순서입니다. 설치 자체는 [INSTALL.md](../INSTALL.md) 가 다루고, 이 문서는 **설치가 이 PC 에서 정말 지켜지는지** 를 봅니다. 왜 이런 단계가 있는지는 [사내 마무리 경계](INHOUSE.md) 에 있습니다.

## 0. 목표와 규칙

**목표**: Diode 가 이 PC 의 **모든 Claude Code 세션에서 꺼지지 않고 켜져 있는지** (전역) 확인하고, 사외에서는 확인할 수 없었던 것 (사내 판 · 창 · 가명 금고 · 사내 LLM 판정 · opencode 표시) 을 하나씩 확인한 뒤 **숫자와 y/n 만** 보고합니다.

**규칙 — 반드시 지킵니다**

1. **명령은 이 문서에 적힌 것만** 실행합니다. 명령은 한 번에 하나씩, 결과를 보고 다음으로 갑니다.
2. **합성 자료만** 씁니다. 사내 파일 · 사내 코드 · 사내 단어를 시험에 넣지 않습니다. 사전 (`%LOCALAPPDATA%\diode\dictionary.json`) · 설정 · 금고 (`vault\`) 는 열지도 출력하지도 않습니다.
3. **출력하지 않는 것**: 사내 단어 · 사내 경로 · 사내 호스트 · 사용자 이름 · 키 · 토큰 · `kit\out\` 안의 파일 (시스템 프롬프트 원문이 있습니다). 보고에는 **OK/실패 줄과 숫자 · y/n** 만 씁니다.
4. **관리자 권한을 쓰지 않습니다.** 3단계의 관리형 설정 (managed settings) 은 회사 IT 가 하는 일입니다. 에이전트는 파일 내용만 보여 주고 **[질문]** 으로 사람에게 넘깁니다.
5. **보호를 끄거나 우회하지 않습니다.** 실패하면 출력을 그대로 보여 주고 멈춥니다. `policy.real_data` (실데이터 켜기) 는 에이전트가 절대 켜지 않습니다.
6. 종료 코드: `0` OK · `1` 점검 실패 · `2` 사용법 오류 · `3` 사람 확인 필요. 시험 출력은 `결과: OK` · `결과: 확인 필요` · `결과: 점검 실패` 줄로 끝납니다.
7. 시험 명령 (`kit\run_*.py`) 은 **임시 폴더와 127.0.0.1 의 가짜 서버** 만 씁니다 — 이 PC 의 Claude 설정을 바꾸지 않고, 회사 밖으로 요청을 보내지 않습니다.
8. 이 체크리스트는 **`D:\claude\diode` 에서 연 Claude Code 세션** 에서 합니다. 방 (`D:\claude\room`) 에서는 셸이 막혀 있고, `D:\claude` 나 원자료 폴더에서는 열지 않습니다.
9. 에이전트는 안쪽 도구 (opencode · 사내 LLM) 를 직접 부르지 않습니다 — Diode 훅이 막는 길이고, 막는 것이 맞습니다. 안쪽에서 할 일은 **[질문]** 으로 사람에게 넘깁니다.

## 1. 설치가 끝났는지

```text
python "D:\claude\diode\diode.py" version
claude plugin list
python "D:\claude\diode\diode.py" setup --check --report
```

- **확인**: `claude plugin list` 에 `diode@diode` 가 있고 `Status:` 가 `enabled` · `Read from:` 이 `D:\claude\diode` 입니다. 점검의 마지막 줄이 `결과: OK` 입니다 (출력은 개수 · 참거짓뿐입니다).
- **실패하면**: 설치가 안 끝난 것입니다. [INSTALL.md](../INSTALL.md) 1–6단계를 먼저 마치고 돌아옵니다. `결과: 확인 필요` 면 출력의 `‼` 줄을 그대로 보여 주고 **[질문]** 합니다.

## 2. 전역 확인 — 지금 이 PC 에서 Diode 를 끌 수 있나

사용자 범위 설치는 "새 세션마다 켜짐" 이지만, **끄는 길이 남아 있습니다** (사외에서 진짜 Claude Code 2.1.318 로 확인 · 2026-11-28). 이 시험은 그 길들로 꺼 보고 사전 단어가 그래도 막히는지 봅니다 (임시 HOME · 가짜 서버 · 지어낸 단어).

```text
python "D:\claude\diode\kit\run_global.py"
```

| 줄 | 끄는 길 |
|---|---|
| G1 | (대조) 끄는 설정 없음 — **막힘** 이어야 합니다 |
| G2 | 어떤 폴더의 `.claude\settings.json` 에 `"enabledPlugins": {"diode@diode": false}` 한 줄 |
| G3 | 같은 줄을 `.claude\settings.local.json` 에 |
| G4 | 어떤 폴더의 `.claude\settings.json` 에 `"disableAllHooks": true` |
| G5 | Claude Code 를 `--settings` 로 열며 끔 |
| G6 | 사용자 설정 (`/plugin` 화면에서 끄는 것과 같은 자리) |
| G7 | `claude plugin uninstall diode@diode` 로 지움 |

- **확인**: 관리형 설정이 없는 PC 라면 `G1 막힘` 이고 G2–G7 은 `꺼짐` 이며 마지막 줄이 `결과: 확인 필요` (종료 코드 3) 입니다 — **이것이 지금의 정상이고, 3단계가 필요하다는 뜻입니다.** 이미 모두 `막힘` 이고 `결과: OK` 면 회사에 관리형 설정이 이미 있는 것입니다 → 4단계로 갑니다.
- **실패하면**: `G0 실패` 면 마켓플레이스 추가 · 설치부터 막힌 것입니다 (회사 정책일 수 있습니다) — 출력을 보여 주고 **[질문]**. `G1 꺼짐` 이나 `결과: 점검 실패 (G1 …)` 면 설치 · 설정 · `python` 명령이 잘못된 것입니다 → 1단계로 돌아갑니다.

## 3. 관리형 설정으로 Diode 를 늘 켜 두기 — 회사 IT 가 합니다

Claude Code 의 설정은 **관리형 설정 > 명령줄 > 프로젝트 로컬 > 프로젝트 > 사용자** 순서로 이깁니다 ([문헌: Claude Code settings 문서](https://code.claude.com/docs/en/settings) · 2026-11-28). 관리형 설정에서 Diode 를 켜 두면, 2단계의 G2–G7 어느 길로도 끌 수 없습니다. **사외에서 2.1.318 로 아래 최소 설정을 걸고 2단계 시험을 돌려 G2–G7 이 모두 막히는 것을 확인했습니다** (리눅스 · 격리한 시험 환경).

**[질문]** 에이전트는 아래를 사람에게 보여 주고 멈춥니다: "Diode 를 이 PC 의 모든 Claude Code 세션에서 끌 수 없게 하려면, 회사 IT 가 관리형 설정에 아래 두 키를 넣어야 합니다. 관리자 권한이 필요해서 저는 하지 않습니다. IT 에 요청해 주시겠어요? 넣은 뒤 알려 주시면 4단계로 확인하겠습니다."

**최소 설정** (Windows 파일 자리: `C:\Program Files\ClaudeCode\managed-settings.json`)

```json
{
  "extraKnownMarketplaces": {
    "diode": { "source": { "source": "directory", "path": "D:\\claude\\diode" } }
  },
  "enabledPlugins": { "diode@diode": true }
}
```

- `extraKnownMarketplaces` — 이 PC 의 `D:\claude\diode` 를 마켓플레이스 `diode` 로 등록합니다. 이름은 꼭 `diode` 로 둡니다 (사용자 범위의 같은 이름 항목을 대신합니다).
- `enabledPlugins` 의 `"diode@diode": true` — Diode 를 강제로 켭니다. 어떤 프로젝트 · 사용자 설정 · 명령줄도 끄지 못합니다. 사용자가 지워도 다음 세션에 다시 실립니다 (G7).

**IT 가 꼭 알아야 할 것**

- **관리형 설정이 오는 길은 한 PC 에 하나만 쓰입니다.** 서버 관리 설정 (claude.ai 관리 콘솔) → MDM · 레지스트리 (`HKLM\SOFTWARE\Policies\ClaudeCode` 의 `Settings` 값) → 위 파일 순서로, **먼저 정책이 있는 하나만** 씁니다 ([문헌: plugins/org 문서](https://code.claude.com/docs/en/plugins/org)). 회사가 이미 콘솔이나 레지스트리로 관리형 설정을 내리고 있다면, 위 두 키를 **그 자리에** 넣어야 합니다 — 파일에 넣으면 무시됩니다. 여러 곳을 합치려면 `"managedSourcesBehavior": "merge"` (2.1.242 이상) 를 씁니다. `HKCU` (사용자 쪽 레지스트리) 는 사용자가 고칠 수 있어 관리 수단이 아닙니다.
- **JSON 이 틀리면 Claude Code 가 아예 켜지지 않습니다.** 넣기 전에 JSON 검사기로 확인합니다. 경로의 `\` 는 `\\` 로 씁니다.
- **선택 (회사가 정할 일 · 필요 없으면 넣지 않습니다)**:
  - `"strictKnownMarketplaces": [{ "source": "directory", "path": "D:\\claude\\diode" }]` — 이 마켓플레이스 말고는 아무것도 못 더하게 합니다 (다른 플러그인을 쓰는 사람은 막힙니다).
  - `"disableSideloadFlags": true` — `--plugin-dir` 로 다른 플러그인을 몰래 싣지 못하게 합니다.
  - `"allowManagedHooksOnly": true` — 관리형 훅과 강제로 켠 플러그인 (Diode) 의 훅만 돌고, **사용자 · 프로젝트의 다른 훅은 모두 막힙니다**. Diode 를 지키는 데는 필요 없습니다 (최소 설정만으로 G2–G7 이 막혔습니다).
  - `"disableAllHooks"` 는 관리형 설정에 **넣지 않습니다** — 넣으면 Diode 의 훅까지 모두 꺼집니다.
- **되돌리기**: IT 가 위 파일 (또는 그 키) 을 지우면 사용자 범위 설치 상태로 돌아갑니다.
- **확인되지 않은 것 [미확인]**: Windows 에서 `directory` 마켓플레이스 경로 (`D:\\claude\\diode`) 를 어떻게 맞춰 보는지는 문서에 없습니다 — 4단계 시험으로 확인합니다.

## 4. 관리형 설정이 걸린 뒤 — 전역 확인을 다시

```text
python "D:\claude\diode\kit\run_global.py" --expect locked
claude plugin list
```

- **확인**: G1–G7 이 모두 `막힘` 이고 마지막 줄이 `결과: OK` 입니다. `claude plugin list` 에서 `diode@diode` 가 관리형 설정 (managed) 에서 켜졌다는 표시가 보일 수 있습니다 (문구는 판마다 다를 수 있습니다). 대화형 Claude Code 에서 `/status` 를 열면 설정 출처에 관리형 설정 (Enterprise managed settings) 이 보입니다.
- **실패하면**: `꺼짐` 이 남은 줄 번호만 보고하고 멈춥니다. 대부분 관리형 설정이 이 PC 에 닿지 않은 것입니다 (다른 출처가 먼저 쓰임 · 파일 자리 · JSON 오류 · 경로 표기). **[질문]** 으로 IT 에 넘깁니다.

## 5. 사내 판에서 시험 다시 돌리기

사외의 CI 가 Windows 에서 이미 돌린 시험입니다 ([kit/results-ci.md](../kit/results-ci.md)). 사내 PC 에서는 **달라지는 곳만** 찾습니다 — 달라지면 그것이 사내 환경의 차이 (관리형 설정 · 단말 보안 · 프록시 · 사내 판) 입니다.

```text
python "D:\claude\diode\kit\run_install.py"
python "D:\claude\diode\kit\run_hooks.py"
python "D:\claude\diode\kit\run_opencode.py" --opencode "<사내 opencode 명령>"
```

- **확인**: 각 줄이 `OK` 이고 마지막 줄이 `결과: OK` 입니다 — `run_install` 은 I1–I6, `run_hooks` 는 R01–R33 (화면이 없으면 창 시나리오 몇 개는 건너뜁니다), `run_opencode` 는 R1–R4 (opencode 가 `.cmd` 껍데기면 R5 도).
- **실패하면**: 실패한 **줄 번호만** 보고합니다. `I1` 은 설치가 막힌 것 · `R17` 은 Git Bash 에서 `${CLAUDE_PLUGIN_ROOT}` 가 안 풀린 것 · `R5` 는 명령 주입 방어가 뚫린 것입니다 (`R5` 실패면 opencode 를 일꾼으로 달지 않습니다). `<사내 opencode 명령>` 은 사람에게 **[질문]** 으로 받고, 보고에는 쓰지 않습니다.

## 6. 눈으로 확인 — 사람이 합니다

**[질문]** "창 세 개를 직접 열어 확인해 주세요: (1) 정책 창 `/diode:dict` (2) 말 봉인 창 `/diode:speak` (3) 확정 창 (가린 묶음을 한 번 보낼 때 뜹니다 — 7단계 C). 각 창에서 ① 화면 맨 위에 보이는지 ② 한글이 입력되는지 ③ 글자가 읽을 만한 크기인지 y/n 으로 알려 주세요." — CI 는 "창 프로세스가 떴다" 까지만 압니다.

## 7. 가린 왕복 (9판) 확인

따라 하는 자세한 순서는 [MANUAL › 작업 묶음](MANUAL.md#파일을-가려서-claude-에게-보내기--작업-묶음-9판) 에 있습니다. **여기서 쓰는 이름 · 수치 · 호스트는 모두 지어낸 것** (예: `노을공정` · `350` · `db01.example.corp`) 이어야 하고, 사전에도 지어낸 단어 몇 개만 넣습니다 (정책 창 · 사람이).

**A. 가명 금고가 암호화되는가** — 사람이 안쪽 터미널에서 직접 칩니다 (에이전트가 부르면 `E-30` 으로 거절됩니다).

```text
python "D:\claude\diode\diode.py" project open
python "D:\claude\diode\diode.py" project status
```

- **확인**: `project status` 의 `"protected": true` (Windows DPAPI 로 암호화했다는 뜻). 그리고 **[질문]** "`%LOCALAPPDATA%\diode\` 폴더가 동기화 · 백업 · 단말 보안 (EDR) 수집 대상인가요?" — 대상이면 금고가 다른 곳으로 복사될 수 있으니 사내에서 정합니다 (수집에서 빼거나 작업 묶음을 쓰지 않음).
- **실패하면**: `E-20` 이면 이 PC 에서 DPAPI 를 못 쓰는 것입니다 → 작업 묶음을 쓰지 않습니다.

**B. 사내 LLM 이 가린 조각을 제대로 가르는가 (D7)** — 에이전트는 아래 합성 조각과 [SPEC 부록 A2](SPEC.md#부록-a2--가린-파일-묶음-조각의-판정-프롬프트-sp-20--고정-글) 의 프롬프트를 글로 준비만 하고, **[질문]** "이 프롬프트에 조각을 하나씩 넣어 사내 LLM 에 물어보고, 조각마다 `pass` / `block` 과 답이 한 줄 JSON 이었는지 알려 주세요" 로 사람에게 넘깁니다 (안쪽 도구는 에이전트가 부르지 않습니다 · 규칙 9).

- 깨끗한 조각 5개 이상: 이름 · 수치 · 경로를 모두 `PH_K7Q2` 같은 토큰으로 바꾼 짧은 코드 · 표 · 글 (예: `host = "PH_K7Q2"` · `temp = PH_M3X9`).
- 새는 조각 5개 이상: 같은 모양인데 지어낸 이름 · 수치 · 호스트를 일부러 남긴 것 (예: `host = "db01.example.corp"` · `temp = 350` · `노을공정 수율`).
- **확인**: 깨끗한 조각은 `pass`, 새는 조각은 `block`, 답은 한 줄 JSON. **새는 조각을 `pass` 로 놓친 수가 0** 이어야 합니다 [제안].
- **실패하면**: 새는 조각이 `pass` 로 나오면 D7 은 참고로만 보고 사람의 확정 (D8) 이 마지막 문입니다 — 숫자를 그대로 보고합니다.

**C. opencode 가 가릴 곳을 제대로 표시하는가** — 합성 파일 몇 개 (문서 · 표 · 코드) 로 opencode 에게 "이 파일들을 가려서 Claude 에게 보내 줘" 라고 시킵니다.

- **확인**: 확정 창이 뜹니다. 창 맨 위의 FILES · TOKENS · **AUTO** (Diode 가 자동으로 가린 곳 — 많을수록 opencode 가 표시를 빠뜨린 것) 와, 잔여 검사 (R1–R6) 에 걸려 다시 낸 횟수를 적습니다. 보내지 않고 [버리기] 해도 됩니다.
- 끝나면 사람이 `python "D:\claude\diode\diode.py" project close` 로 묶음을 닫습니다 (금고를 지웁니다).

## 8. 끝내기 전에

- 공개 저장소로 가져가는 것은 **9번 보고의 줄** 뿐입니다. 사내 이름 · 경로 · 주소 · `kit\out\` 파일은 옮기지 않습니다.
- 사내에서 일반 코드를 고쳤다면, 되가져가기 전에 사내 PC 에서 `python "D:\claude\diode\tools\diode_check.py" --strict --internal-words "<사내 낱말 목록 파일>"` 이 위반 0 인지 봅니다 (낱말 목록은 사내 자리에만 둡니다 · 검사기는 낱말을 찍지 않습니다).
- 이 체크리스트를 모두 통과해도 실데이터를 켜는 것은 **사람의 결정** 입니다 (정책 창에서 확인 문구를 직접 입력 · 에이전트는 켜지 않습니다).

## 9. 보고 양식

아래 형식으로만 보고합니다. **사내 단어 · 경로 · 주소 · 키 · 사용자 이름은 쓰지 않습니다.**

```text
Diode 사내 검증 보고
- 1 설치            : OK | 실패 (줄)
- 2 전역 (설정 전)  : G1 막힘 · 꺼짐 줄 [G2 … G7] | 모두 막힘
- 3 관리형 설정     : IT 가 넣음 (최소 | 최소 + 선택 [키 이름]) | 아직 | 못 함 (까닭 한 줄 · 이름 없이)
- 4 전역 (설정 뒤)  : OK | 꺼짐 줄 [G..]
- 5 사내 판 시험    : run_install OK | 실패 줄 [I..] · run_hooks OK | 실패 줄 [R..] · run_opencode OK | 실패 줄 [R..] | 안 함
- 6 창 (정책 · 말 봉인 · 확정) : 맨 위 y/n · 한글 y/n · 글자 크기 y/n (창마다)
- 7A 금고            : protected y/n · 수집 대상 y/n/?
- 7B 사내 LLM 판정   : 깨끗한 __ 중 pass __ · 새는 __ 중 block __ · 한 줄 JSON __ / __
- 7C opencode 표시   : 파일 __ · TOKENS __ · AUTO __ · 다시 낸 횟수 __
- 멈춘 곳            : 없음 | n단계 — 까닭 (이름 · 경로 없이)
```
