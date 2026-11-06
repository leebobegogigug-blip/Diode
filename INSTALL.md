# Diode 설치 가이드 — 에이전트용

> **개발 중 (v0.0) — 합성 자료로만 시험했습니다. 사내 확인 (Windows · 사내 CLI · 보안 부서의 답) 전이라 실데이터에는 쓰지 마세요.**
> 아래 절차는 합성 자료로 진짜 Claude Code CLI 에 붙여 시험한 흐름 (설치 → 설정 → 방 → 훅 · 허브) 을 옮긴 것입니다 (`kit/run_install.py` · 기록은 [kit/results-linux.md](kit/results-linux.md)). Windows 사내 PC 에서 직접 확인하지 못한 곳은 본문에 **[미확인]** 으로 적었습니다.
>
> **사람용 한 줄:** Claude Code 에 이렇게 붙여넣으면 이 문서대로 설치합니다. "Diode 를 설치해줘. 저장소를 `D:\claude\diode` 에 이미 받아 두었으면 그 폴더의 INSTALL.md 를, 아직이면 나한테 받는 방법을 물어본 뒤 받아서 그 INSTALL.md 를 끝까지 읽고 순서대로만 진행해. 키 · 토큰 · 사내 단어는 출력하지 말고, [질문] 표시가 있는 곳에서는 나한테 물어봐."

---

이 아래는 **에이전트가 실행할 절차**입니다.

## 0. 목표와 규칙

**목표**: 이 저장소를 `D:\claude\diode` 에 두고 로컬 마켓플레이스로 더하고, 플러그인 `diode` 를 설치하고, 처음 설정과 방 만들기를 끝낸 뒤 점검을 통과시킨다. 일꾼 (opencode) 연결은 선택이다 (7단계).

**지금은 합성 자료로만 설치해 시험한다 (v0.0).** 훅 · 허브 · 확정 창 · 정책 창 · 명령 (`/diode:setup` · `:room` · `:dict` · `:status`) 까지 있다. 그러나 사내 확인 (Windows · 사내 CLI 판 · 관리형 설정 · 보안 부서의 답) 전이라 **실데이터에는 쓰지 않는다** (`policy.real_data` 는 꺼져 있고, 켜려면 정책 창에서 확인 글을 쳐야 한다 — 에이전트는 켜지 않는다). 사내 확인 항목은 [kit/inhouse-questions.md](kit/inhouse-questions.md) 에 있다.

**규칙 — 반드시 지킬 것**

1. **명령은 이 문서에 적힌 것만** 실행한다. 모든 명령은 Git Bash · cmd · PowerShell 어디서나 그대로 동작하게 적었다 (경로는 항상 큰따옴표). `.ps1` · `.cmd` · `.bat` 파일을 새로 만들지 않는다.
2. **비밀 금지**: 설정 파일의 키 · 토큰과 사내 단어 사전 (`%LOCALAPPDATA%\diode\dictionary.json`) 을 읽기 도구나 `cat` · `type` · `Get-Content` 로 열거나 출력하지 않는다. 사전 · 원자료 폴더 · 일꾼 명령 · 사내 LLM 주소는 **사람이 정책 창에 직접 입력**한다 — 에이전트는 사내 단어를 묻지도, 받지도, 적지도 않는다. 사용자가 키나 사내 단어를 채팅에 치려 하면 말린다 (채팅에 쓴 글은 곧바로 Claude 로 나간다). 이미 썼다면 그 글은 이미 나간 것이니 되풀이하지 말고 그 사실만 알린다.
3. **관리자 권한 금지.** Claude Code 에 마켓플레이스 · 플러그인을 더하는 것은 사용자 범위 변경이므로 **[질문]** 으로 동의를 받은 뒤에만 하고, [제거](#제거) 절에 되돌리는 방법이 있을 때만 한다. 환경 변수 · PATH 도 에이전트가 고치지 않는다.
4. **[질문]** 표시가 있는 곳에서는 멈추고 사용자에게 묻는다. 사용자가 거절하면 그 단계를 건너뛰지 말고 멈춘 곳으로 보고한다.
5. 출력이 예상과 다르면 추측해서 우회하지 말고, 출력을 그대로 보여 주고 [문제 해결](#문제-해결) 표를 따른다. 표에 없으면 멈추고 보고한다.
6. 명령은 한 번에 하나씩 실행하고, 결과를 확인한 뒤 다음으로 간다. 단계마다 모양은 같다: 명령 → **확인** (기대하는 출력) → **실패하면** (할 일).
7. `D:\claude` 를 git 저장소로 만들지 않고 안내 파일 (`CLAUDE.md` · `AGENTS.md`) 을 두지 않는다 — 방 세션에 방 위 폴더의 안내 파일 · git 정보가 실리지 않게. 5단계가 이 둘을 보고 거절한다.
8. **슬래시 명령 대신 `python` 꼴로 부른다.** `/diode:setup` · `/diode:room` · `/diode:status` · `/diode:dict` 는 같은 `python "…\diode.py" …` 명령을 감싼 것이다 (슬래시 명령은 `--report` 를 붙여 종료 코드를 늘 0 으로 둔다는 점만 다르다). 플러그인은 설치한 뒤에 여는 세션부터 실리므로 (이 세션에 바로 실리는지는 **[미확인]**) 이 문서는 `python` 꼴을 쓴다 — 종료 코드도 그대로 보인다.
9. 종료 코드는 `0` OK · `1` 점검 실패 · `2` 사용법 오류 (`room` 에서는 방을 만들지 않았다는 뜻으로도 쓴다) · `3` 사람 확인 필요다. 점검 출력은 `결과: OK` · `결과: 확인 필요` · `결과: 점검 실패` 줄로 끝난다.

**자리**

| 자리 | 무엇 | 까닭 |
|---|---|---|
| `D:\claude\diode` | 이 저장소 = 플러그인 소스 = 로컬 마켓플레이스. `git clone` 으로 받거나, 압축 파일 · 복사로 옮겨 둔다 | 소스 · 업데이트가 한 자리 (`git pull`) |
| `D:\claude\room` | 깨끗한 방 — 원자료가 없는 Claude 작업 폴더. `D:\claude\diode` 안에 두지 않는다 | 경로에 사용자 이름이 없고, 방 세션이 소스를 보지 않는다 |
| `%LOCALAPPDATA%\diode` | 설정 · 사전 · 감사 기록 | 프로그램 자리와 데이터를 나눈다 — 플러그인을 지워도 남는다 |

이 자리를 쓸 수 없는 PC (예: `D:` 드라이브가 없다) 면 에이전트가 다른 자리를 정하지 않는다 — 멈추고 **[질문]**.

## 1. 파이썬 확인

훅 · 허브는 파이썬을 `python` 이라는 **이름 그대로** 부른다 (절대 경로를 적으면 훅이 고장 났을 때 사용자 이름이 든 경로가 Claude 에게 간다). 그러니 이 이름으로 3.8 이상이 찾아져야 한다. 정책 창 (4단계) 은 `tkinter` 가 있어야 뜬다.

```text
python --version
python -c "import sys; print(sys.version_info >= (3, 8))"
python -c "import tkinter"
```

- **확인**: 첫 명령은 `Python 3.<8 이상>.<수>` 꼴을 찍는다. 둘째는 `True`. 셋째는 아무것도 찍지 않고 끝난다.
- **실패하면**: 아래 어느 것이든 **[질문]** "이 PC 에서 `python` 이 3.8 이상으로 안 잡힙니다. 파이썬 3.8 이상을 설치하거나 `python` 이 PATH 에 오도록 해 주시겠어요?" 를 하고 멈춘다. 에이전트가 파이썬을 설치하거나 PATH 를 고치지 않는다.
  - 버전이 안 나오고 `command not found` · 인식되지 않는다는 글이 나온다.
  - Microsoft Store 가 열리거나 설치하라는 안내만 나온다 (Windows 의 `python` 앱 실행 별칭만 있고 파이썬은 없는 경우 — 정확한 문구는 Windows 판마다 달라 **[미확인]**).
  - 버전이 3.8 미만이거나 둘째 명령이 `False`.
  - `py -3 --version` 은 되는데 `python --version` 은 안 된다 — **실패로 본다.** 훅이 `py` 가 아니라 `python` 을 부르기 때문이다.
  - 셋째 명령이 `ModuleNotFoundError: No module named 'tkinter'` — 정책 창을 열 수 없다 (E-07). 파이썬을 다시 설치하되 tcl/tk 를 포함해 달라고 부탁한다.
  - Git Bash 에서는 되는데 Claude Code 를 연 다른 셸에서는 안 될 수 있다 (셸마다 PATH 가 다르다 — **[미확인]**). 6단계의 `python 명령 (훅 · 허브가 부름)` 줄이 이 길을 다시 본다.

## 2. 코드 받기

```text
python "D:\claude\diode\diode.py" version
```

- **확인**: `Diode <버전>` 한 줄. 이러면 이미 받아 둔 것이다 — **받기를 건너뛴다.** 이어서 git 으로 받은 것인지 본다.

  ```text
  git -C "D:\claude\diode" rev-parse --show-toplevel
  ```

  - `D:/claude/diode` 를 찍으면 (대소문자 무시) git 으로 받은 것이다. 최신으로 맞춘다:

    ```text
    git -C "D:\claude\diode" pull --ff-only
    python "D:\claude\diode\diode.py" version
    ```

    `Already up to date.` 또는 바뀐 파일 목록이 나오고, `version` 이 다시 `Diode <버전>` 을 찍으면 된다.
  - `fatal: not a git repository` 면 압축 파일 · 복사로 옮긴 것이다 — 그대로 쓴다 (새 판은 사용자가 다시 옮겨 두어야 한다).
  - `D:/claude/diode` 가 아닌 다른 폴더 (예: `D:/claude`) 를 찍으면 위 폴더가 git 저장소다 — 규칙 7 에 어긋난다. **[질문]** 사용자에게 알리고 멈춘다 (`.git` 을 에이전트가 지우지 않는다).
- **받아 둔 것이 없으면** (`python: can't open file … [Errno 2] No such file or directory`):
  **[질문]** "Diode 코드를 어떻게 받으시겠어요? ① git 으로 받기 (저장소 주소를 알려 주세요) ② 압축 파일 · 복사로 `D:\claude\diode` 에 직접 옮겨 두기"
  - ① 이면:

    ```text
    git --version
    git clone "<저장소 주소>" "D:\claude\diode"
    python "D:\claude\diode\diode.py" version
    ```

    주소는 사용자가 알려 준 것을 그대로 쓴다. 이 문서에는 주소가 없다. `git --version` 이 안 되면 ② 로 바꿀지 **[질문]**. 끝난 뒤 `Diode <버전>` 이 나오면 된다.
  - ② 이면: 옮겨 두었다고 알려 줄 때까지 멈춘다. 알려 주면 위 `version` 명령부터 다시 한다. 압축을 풀 때 폴더가 한 겹 더 생겨 `D:\claude\diode\diode\diode.py` 처럼 되면 안 된다 — `diode.py` 가 `D:\claude\diode` 바로 아래에 있어야 한다.
- **실패하면**:
  - `git clone` · `git pull` 이 이름 · 비밀번호를 묻거나 권한 오류를 내면 사용자가 터미널에서 직접 입력하게 하고, 토큰을 채팅에 붙이지 않게 한다. 되풀이해 막히면 ② 로 바꿀지 (또는 pull 을 건너뛸지) **[질문]**.
  - `pull` 이 `fatal: Not possible to fast-forward, aborting.` 이나 로컬 변경 때문에 덮어쓸 수 없다는 오류를 내면 소스 폴더에 로컬 변경이나 갈라진 기록이 있다. **[질문]** 사용자에게 알리고 멈춘다. `reset --hard` · `checkout --` 로 되돌리지 않는다.
  - git 이 `fatal: detected dubious ownership in repository at …` 를 내면 폴더 주인이 지금 사용자와 달라서 git 이 거절한 것이다 (다른 계정으로 풀거나 복사한 폴더에서 나온다). 사용자 git 설정을 바꾸는 일이라 에이전트가 `safe.directory` 를 임의로 더하지 않는다 — **[질문]** 하고 멈춘다.
  - `D:` 드라이브가 없거나 쓸 수 없어 폴더를 못 만들면 멈추고 **[질문]** (자리를 에이전트가 바꾸지 않는다 — 0단계).
  - 받은 뒤에도 `version` 이 `Diode <버전>` 을 못 찍으면 출력을 그대로 보여 주고 멈춘다.

## 3. 마켓플레이스 더하기 · 플러그인 설치

Claude Code 판이 훅의 `onFailure: block` (훅이 고장 나면 막는 설정) 을 아는 판이어야 한다 — 2.1.295 이상 (근거는 [docs/PLAN.md](docs/PLAN.md) 의 `[문헌]` 표시이고 이 저장소에서 직접 시험하지는 못했다).

```text
claude --version
claude plugin list
```

- **확인**: `claude --version` 의 첫 낱말이 `2.1.295` 이상. `claude plugin list` 는 이미 설치한 플러그인을 찍는다 (`diode@diode` 가 이미 있으면 `Read from:` 줄이 `D:\claude\diode` 인지 본다 — 다른 자리면 **[질문]**).
- **실패하면**: `claude` 가 없거나 `plugin` 을 모른다고 하거나 판이 낮으면 **[질문]** "Claude Code 를 업데이트해 주시겠어요?" 를 하고 멈춘다.

**[질문]** "Diode 플러그인을 이 PC 의 Claude Code 에 설치할까요? 설치하면 (1) Claude Code 의 사용자 설정 (`~/.claude` 아래 `settings.json`) 에 마켓플레이스 `diode` 와 플러그인 `diode@diode` 가 기록되고, (2) 이 PC 의 모든 Claude Code 세션에 Diode 의 훅 (막는 장치) 과 허브 (MCP) 가 걸립니다. 4단계 설정을 마치기 전에는 보호가 켜지지 않습니다. 되돌리는 방법은 '제거' 절에 있습니다." → 동의했을 때만 아래로 간다.

```text
claude plugin marketplace add "D:\claude\diode"
claude plugin install diode@diode
claude plugin list
claude plugin details diode
```

대화형 Claude Code 안에서는 같은 일을 `/plugin marketplace add "D:\claude\diode"` · `/plugin install diode@diode` 로 한다 (이 문서는 에이전트가 셸에서 바로 돌릴 수 있는 `claude plugin …` 꼴을 쓴다).

- **확인**:
  - `Successfully added marketplace: diode` 와 `Successfully installed plugin: diode@diode (scope: user)` 가 나오고 종료 코드가 0 이다. 이미 되어 있으면 `already on disk` · `already installed` 가 나오는데 종료 코드 0 이면 정상이다.
  - `claude plugin list` 에 `diode@diode` 가 보이고, `Version:` 이 2단계의 `diode.py version` 과 같고, `Read from:` 이 `D:\claude\diode`, `Scope: user`, `Status:` 줄이 enabled 다.
  - `claude plugin details diode` (모델을 부르지 않는다) 의 `Skills` 줄에 `dict` · `diode` · `room` · `setup` · `status`, `Hooks` 줄에 `SessionStart` · `UserPromptSubmit` · `PreToolUse`, `MCP servers` 줄에 `hub` 가 있다.
  - 문구는 Claude Code 판마다 조금 다를 수 있다. 종료 코드 0 과 위 이름들로 판단한다.
- **명령이 풀리는지 확인**: 슬래시 명령은 `python "${CLAUDE_PLUGIN_ROOT}/diode.py" …` 를 Git Bash 로 돌린다. `${CLAUDE_PLUGIN_ROOT}` 는 Claude Code 가 플러그인 폴더 (`D:\claude\diode`) 로 바꿔 넣는 자리표시라서, 풀려야 명령이 된다 (훅은 셸 없이 `python` 을 직접 부른다). 이 세션에는 플러그인이 아직 없을 수 있으므로 에이전트가 슬래시 명령을 칠 수 없다. 두 길 중 하나로 확인한다.
  - 사람이: 새 Claude Code 세션 (또는 `/reload-plugins`) 에서 `/diode:status` 를 쳐서 점검 결과가 나오는지 본다.
  - 에이전트가: **[질문]** "확인용으로 `claude -p "/diode:status"` 를 한 번 돌립니다. 요청 1건이 실제 Claude 로 나가고, 내용은 점검 결과 (개수 · 참거짓뿐) 입니다. 해도 될까요?" → 동의하면 그 명령을 돌린다.

  나온 답 (또는 화면) 에 점검 결과 (`결과:` 줄의 뜻) 가 있고 아래 오류 글이 없으면 된다. 4단계 전이라 `결과: 확인 필요` 쪽이 정상이다. Linux 에서는 이 흐름을 시험했고 (`kit/run_install.py` I2), **Windows 의 Git Bash 에서 풀리는지는 [미확인]** 이다 (사내에서 [kit/inhouse-questions.md](kit/inhouse-questions.md) H6 으로 확인한다).
- **실패하면**:
  - `Path does not exist: …` — 경로가 틀렸거나 2단계가 안 됐다. 2단계로 돌아간다.
  - `Failed to add marketplace: Marketplace file not found at …\.claude-plugin\marketplace.json` — 폴더는 있는데 저장소 루트가 아니다 (압축을 풀 때 한 겹 더 깊이 풀렸을 수 있다). `diode.py` 가 `D:\claude\diode` 바로 아래에 있는지 확인하고, 아니면 **[질문]**.
  - `Failed to install plugin "diode@diode": Plugin "diode" not found in marketplace "diode"` — `claude plugin marketplace update diode` 를 한 번 돌리고 설치를 다시 한다. 또 나오면 출력을 보여 주고 멈춘다.
  - 마켓플레이스 추가나 설치를 회사 설정이 막는 PC 라면 오류 글이 다를 수 있다 (**[미확인]** — 그때의 문구는 모른다). 출력을 그대로 보여 주고 멈춘다. 우회하지 않는다.
  - `hook … failed; blocking because onFailure is block` (Claude Code 가 내는 글 · 판마다 다를 수 있다) — 훅이 못 돌았다. 대개 `python` 이름이 안 찾아지는 것이다 → 1단계.
  - 슬래시 명령이 없다고 하거나 `${CLAUDE_PLUGIN_ROOT}` 글자가 그대로 보이거나 파일을 못 찾는다고 하면: `claude plugin list` 의 `Status:` 가 enabled 인지 보고, 세션을 새로 열거나 `/reload-plugins` 를 해 본다. 그래도 같으면 출력을 그대로 보여 주고 멈춘다.

설치만 하고 4단계를 마치기 전에는 보호가 없다. 새 세션을 열면 `DIODE: 아직 설정하지 않았습니다 …` 알림이 보이는 것이 정상이다 ([알려진 한계](docs/MANUAL.md#알려진-한계)).

## 4. 처음 설정

`/diode:setup` 이 하는 일은 이렇다 ([commands/setup.md](commands/setup.md) · [diodelib/setup.py](diodelib/setup.py)). 데이터 폴더 (`%LOCALAPPDATA%\diode`) 를 만들고, 점검하고, **사전 · 원자료 폴더가 비어 있으면 정책 창을 따로 떼어 연다** (기다리지 않는다). 사전 · 원자료 폴더가 채워져 있으면 방이 없을 때 방을 만들고 점검한다. 사전 · 원자료 폴더 · 일꾼 명령 · 사내 LLM 판정 설정은 **사람이 그 창에서 직접 입력**하고 [저장] 한다 — 슬래시 명령도 에이전트도 단어를 묻거나 받지 않는다.

**사전이나 원자료 폴더 목록이 비어 있으면 Diode 는 보내지 않는다.** 아무것도 입력하지 않고 창을 닫아도 설치가 망가지지는 않지만, 그 상태로는 쓸 수 없다. 설정을 마치기 전에는 방 밖의 폴더가 지켜지지 않는다는 점도 알린다.

```text
python "D:\claude\diode\diode.py" setup
```

종료 코드 3 (`결과: 확인 필요`) 은 첫 실행에서 정상이다. 이미 사전 · 원자료 폴더가 채워진 PC (다시 설치하는 경우) 는 창이 뜨지 않고 곧바로 방을 만들거나 `방이 이미 있고 ok 입니다` 를 찍은 뒤 점검 결과가 나온다 — 그때는 아래 창 안내를 건너뛰고 5단계에서 방 상태를 본다.

- **확인** (화면이 있는 PC): 출력이 이 세 줄로 시작하고 `결과: 확인 필요` 로 끝난다. 창은 따로 떠서 이 명령은 기다리지 않고 끝난다.

  ```text
  정책 (사전 · 원자료 폴더) 이 비어 있어 정책 창을 엽니다 — 창에서 직접 입력하고 [저장] 하세요
  단어는 이 대화로 보내지 않습니다 (입력하면 곧바로 Claude 로 나갑니다)
  저장한 뒤 /diode:setup 을 다시 실행하면 방을 만들고 점검합니다
  ```

  **[질문]** "정책 창 'Diode - 정책' 이 열렸습니다. 창에서 직접 입력하고 [저장] 하세요. `01 사전` 에는 사내 단어를 한 줄에 하나, `02 원자료 폴더` 에는 사내 자료가 든 폴더의 전체 경로를 한 줄에 하나 씁니다. `06 llm` 은 사내 LLM 판정 (D7) 설정 칸이고, 지금 몰라도 설치는 계속됩니다. 단어 · 폴더 이름 · 주소 · 키는 채팅에 쓰지 마세요 — 쓰는 즉시 Claude 로 나갑니다. 저장하셨으면 '저장했어요' 라고만 알려 주세요."

  사용자가 알려 주면 저장이 됐는지 개수로 확인한다 (읽기만 한다).

  ```text
  python "D:\claude\diode\diode.py" setup --check
  ```

  `사전 <n>개 · 원자료 폴더 <m>개 · 안쪽 도구 이름 <k>개 (+ 기본 opencode)` 줄에서 `<n>` · `<m>` 이 1 이상이다. 같은 줄에는 `실데이터 꺼짐 (기본)` 이 보여야 한다 — `실데이터 허용됨 (보안 승인 뒤에만)` 이 보이면 에이전트는 건드리지 않고 사용자에게 알려 **[질문]** "보안 부서의 승인이 있었습니까?" 를 한다.
- **실패하면**:
  - 개수가 0 이다 — 창을 [저장] 없이 닫았거나, 창이 둘 열려 나중에 저장한 쪽이 이겼을 수 있다. `python "D:\claude\diode\diode.py" dict` 로 창을 다시 열어 (`정책 창을 열었습니다 - …` 가 나온다) 입력을 부탁한다. 창에서 틀린 칸은 칸 이름과 줄 번호만 알려 주고 아무것도 쓰지 않는다 — 고치는 것은 사용자가 창에서 한다.
  - 창이 열렸다는데 화면에서 안 보인다 — 작업 표시줄 · 다른 모니터를 보게 하고, 그래도 없으면 `dict` 로 다시 연다 (Windows 에서 창이 뜨는 모습은 직접 못 봤다 — **[미확인]**).
  - 정책 창을 못 띄운다는 글 (`… 정책 창을 띄울 수 없습니다 (E-07) …`) — 화면이 없거나 `tkinter` 가 없는 파이썬이다. **[질문]** 화면이 있는 PC 에서 여는 것을 안내하고 멈춘다.
  - `설정을 읽지 못해 창을 열지 않았습니다 (broken)` · `(newer)` — [문제 해결](#문제-해결) 표를 따른다.
  - 사용자가 단어 · 폴더 이름 · 일꾼 명령 · 주소를 채팅에 치려 하면 말리고 창에서 입력하게 한다 (0단계 규칙 2).

(저장한 뒤 `python "D:\claude\diode\diode.py" setup` 을 다시 실행하면 5단계의 방 만들기까지 한꺼번에 한다. 이 문서는 5단계를 따로 둔다.)

## 5. 방 만들기

방은 원자료가 하나도 없는 Claude 작업 폴더다. `/diode:room` 은 방 폴더에 표지 (`.diode-room`) · 방 설정 (`.claude\settings.json`) · `outbox` · `inbox` · `work` 를 만든다. 이미 있는 방은 덮어쓰지 않는다. 기본 자리는 `D:\claude\room` 이다.

```text
python "D:\claude\diode\diode.py" room
python "D:\claude\diode\diode.py" setup --check
```

- **확인**: `room` 이 `방을 만들었습니다 (표지 · 방 설정 · outbox · inbox · work)` (처음) 또는 `방이 이미 있고 ok 입니다` 를 찍고 종료 코드 0. 이어서 `setup --check` 에 `방 ok` 줄이 있다.
- **실패하면**: `방을 만들지 않았습니다: …` (종료 코드 2) 의 까닭은 아래 표와 같다. 검사 순서도 이 표의 위에서 아래다. 모두 **[질문]** 으로 사용자에게 알리고 멈춘다 — 에이전트가 사용자의 폴더 · 안내 파일 · `.git` 을 지우거나 옮기지 않는다.

| 출력 | 뜻 | 할 일 |
|---|---|---|
| `방 자리가 절대 경로가 아닙니다` | 설정의 방 자리가 `D:\…` 꼴이 아니다 | 사용자가 정책 창의 `06 방 자리` 를 절대 경로로 고친다 |
| `방 자리가 플러그인 소스 폴더 안이거나 위입니다 — 다른 자리를 쓰세요` | 방이 `D:\claude\diode` 안이거나 그 위 폴더 (`D:\claude`, `D:\`) 다 | 방 자리를 소스 밖의 다른 폴더로 (기본 `D:\claude\room` 은 해당 없다) |
| `방 자리가 원자료 폴더와 겹칩니다 — 다른 자리를 쓰세요` | 원자료 폴더 목록의 어느 폴더가 방 안이거나 방 위다 | 에이전트는 목록을 읽을 수 없다. 사용자가 창의 `02 원자료 폴더` 와 `06 방 자리` 를 보고 고친다 |
| `방 자리가 git 저장소 안입니다 — 저장소 밖에 만드세요` | 방 폴더나 그 위 폴더에 `.git` 이 있다 (규칙 7) | `git -C "D:\claude" rev-parse --show-toplevel` 이 찍는 폴더가 저장소의 맨 위다. 그 `.git` 을 어떻게 할지는 사용자가 정한다 (`D:\claude` 를 저장소로 쓰지 않는 쪽이 이 도구의 전제다) |
| `방 자리나 그 위 폴더에 CLAUDE.md · AGENTS.md 가 있습니다 — 지우거나 다른 자리를 쓰세요` | 방 폴더 또는 위 폴더 (드라이브 맨 위까지) 에 `CLAUDE.md` · `.claude\CLAUDE.md` · `AGENTS.md` 중 하나가 있다 | 어느 폴더의 어느 파일인지는 사용자가 찾는다. 파일을 옮기거나 지우는 것도 사용자가 한다 |
| `방 자리가 비어 있지 않은 폴더입니다 — 빈 폴더나 새 자리를 쓰세요` | `D:\claude\room` 이 이미 있고 무언가 들어 있다 | 사용자가 비우거나 다른 자리를 정한다 |

그 밖의 결과:

| 출력 | 뜻 | 할 일 |
|---|---|---|
| `방이 이미 있는데 설정이 바뀌었습니다 (changed) — 덮어쓰지 않습니다. 지우고 다시 만들거나 되돌리세요` (종료 코드 3) | 방 설정의 해시가 표지와 다르거나, 방 안에 `.claude\settings.local.json` · `.mcp.json` 이 생겼다 | 사람이 방 폴더를 보고 결정한다 (에이전트는 방 안의 파일을 직접 고치지 않는다). `.claude\settings.local.json` · `.mcp.json` 때문이면 그 파일만 치워도 `ok` 로 돌아온다. 방 설정 자체가 고쳐졌으면 방을 지우고 `room` 을 다시 한다 |
| `diode.py room: 실패 (E-20)` (종료 코드 1) | 방 폴더를 만들 수 없는 자리다 (권한 · 읽기 전용 · 없는 드라이브 등). 까닭은 출력에 없다 | 사용자에게 알리고 자리를 정하게 한다. (Windows 에서 `D:` 가 없을 때 이렇게 나오는지는 **[미확인]** — 쓸 수 없는 자리로 시험했다) |

방 자리를 다른 곳으로 하고 싶으면 사용자가 정책 창의 `06 방 자리` 에 쓰고 `room` 을 다시 한다 (`room --path` 로만 만들면 `setup --check` 가 기본 자리를 보고 `방 없음` 이라고 한다).

방이 만들어지면 사용자에게 알린다: **"방 `D:\claude\room` 에서 Claude Code 를 새로 여세요."** 방은 수동 권한 모드로 쓴다 (auto 는 막힌다).

## 6. 점검

```text
python "D:\claude\diode\diode.py" check
python "D:\claude\diode\diode.py" setup --check
```

- **확인**: 둘 다 마지막 줄이 `결과: OK`. `check` 는 파이썬 판과 데이터 폴더 자리만 본다 (아무것도 만들지 않는다). `setup --check` 가 전체 점검이다 (읽기만 한다) — 모두 채워진 상태의 모양은 이렇다.

  ```text
  파이썬 (이 점검) <판> · OK
  python 명령 (훅 · 허브가 부름) <판> · OK
  데이터 폴더 있음
  사전 <n>개 · 원자료 폴더 <m>개 · 안쪽 도구 이름 <k>개 (+ 기본 opencode)
  일꾼 명령 없음 (일 넘기기는 E-01) · 사내 LLM 판정 (D7) 설정함
  실데이터 꺼짐 (기본)
  방 ok
  훅 자체 시험 OK
  결과: OK
  ```

  `결과: OK` 이려면 파이썬 · 훅 자체 시험이 통과하고, 사전 · 원자료 폴더 · 사내 LLM 판정 (D7) 이 모두 채워지고, 방이 ok 여야 한다. 일꾼 명령이 없는 것은 `확인 필요` 가 아니다 (일 넘기기만 `E-01` 이 된다).
- **실패하면**:
  - `결과: 확인 필요` (종료 코드 3) → 위의 `‼` 줄을 그대로 보여 주고 **[질문]**. 남은 `‼` 가 `사내 LLM 판정 (D7) 설정이 없음 — 보내기를 막습니다` 하나뿐이면 설치는 끝났고 보내기만 막힌 안전한 상태다 — 보고의 `점검` 줄에 그대로 쓰고, 지금 창에서 `06 llm` 을 채울지 묻는다.
  - `결과: 점검 실패` (종료 코드 1) → 위의 `×` 줄을 그대로 보여 주고 [문제 해결](#문제-해결).

## 7. (선택) 일꾼 (opencode) 연결

일꾼은 안쪽 일을 맡는 사내 LLM 도구 (opencode) 다. **선택이다** — 연결하지 않아도 방 · 점검은 쓸 수 있고, 일 넘기기 (`dispatch`) 만 `E-01` (일꾼 없음) 이 된다.

**[질문]** "일꾼 (opencode) 을 연결할까요? 연결하면 (1) Diode 정책 창의 `04 일꾼 명령` 칸에 사용자가 명령을 직접 넣고, (2) opencode 설정에 일꾼 전용 에이전트 `diode-worker` 를 더해 권한을 좁힙니다 (권하는 두 번째 층). 둘 다 '제거' 절로 되돌릴 수 있습니다." → 거절하면 이 단계를 건너뛰고 보고에 `일꾼: 연결 안 함 (선택)` 이라고 쓴다.

```text
opencode --version
```

- **확인**: 숫자 버전이 나온다.
- **실패하면**: 명령을 못 찾으면 **[질문]** 사용자에게 알리고 이 단계를 건너뛴다 (opencode 설치는 에이전트가 하지 않는다).

**7-1. 일꾼 명령 (Diode 쪽).** 명령은 **정책 창에서 사용자가 직접** 넣는다 — 에이전트는 실제 이름 · 경로 · 주소를 묻거나 적지 않는다. 창은 `python "D:\claude\diode\diode.py" dict` 로 연다. 바꾸기 전에 설정을 백업해 두고 싶으면 사용자가 데이터 폴더의 `config.json` 을 직접 복사해 둔다 (에이전트는 데이터 폴더를 열지 않는다). 쓰는 모양의 예는 [docs/MANUAL.md](docs/MANUAL.md#알려진-한계) 의 "일꾼은 설정 `worker.command` 가 있어야 돕니다" 항목에 있다.

Windows 에서 주의할 점을 쉬운 말로 말해 준다: npm 으로 깐 도구는 실행 파일이 아니라 `.cmd` 껍데기인 경우가 많다. 껍데기는 인자를 `cmd.exe` 가 한 번 더 읽는데, 그러면 Claude 가 쓴 지시문 속 `&` · `|` · `^` · `%` 같은 글자가 명령으로 실행될 수 있다 (명령 주입). 그래서 Diode 는 껍데기에 `{prompt}` 를 인자로 주는 설정을 거절하고 (`일꾼 명령 문제: …`) 지시문을 표준 입력으로 넘기게 한다 — 명령에 `{prompt}` 를 적지 않으면 된다. 창의 [예시 넣기] 버튼이 넣는 예시에는 `{prompt}` 가 들어 있으니, 껍데기일 때는 그 부분을 지우고 저장한다 ([docs/MANUAL.md](docs/MANUAL.md#알려진-한계) 의 Windows 항목 · [diodelib/worker.py](diodelib/worker.py) 머리말).

**7-2. 일꾼 전용 opencode 에이전트 (opencode 쪽).** 평소 쓰는 opencode 의 전역 권한은 건드리지 않고 `diode-worker` 에이전트에만 권한을 준다. 권한 예시는 [docs/MANUAL.md](docs/MANUAL.md#알려진-한계) 의 "일꾼 전용 opencode 에이전트를 하나 만들어 권한을 좁히세요" 항목에 있다 — 그 JSON 을 읽어 **한 글자도 바꾸지 말고** opencode 설정의 `agent` 칸에 합친다. 이미 `agent` 칸이 있으면 그 안에 `diode-worker` 만 더하고 다른 에이전트는 건드리지 않는다. `opencode run --auto` (권한 자동 승인) 는 쓰지 않는다.

1. **[질문]** "opencode 설정 파일은 어디에 있고, 그중 어느 파일에 `diode-worker` 를 둘까요?" 에이전트가 설정 파일 자리를 짐작해 찾지 않는다. 모르면 7-2 를 건너뛴다. 일꾼이 도는 폴더에서 그 설정이 읽히는지는 **[미확인]** 이고, 8단계의 `kit/run_opencode.py` (H5) 가 본다.
2. **백업**: 고치기 전에 같은 폴더에 `<설정 파일 이름>.diode-backup` 으로 복사한다. 이미 있으면 덮어쓰지 않고 멈춘다.

   ```text
   python -c "import os, shutil, sys; sys.exit('backup exists') if os.path.exists(sys.argv[2]) else shutil.copy2(sys.argv[1], sys.argv[2])" "<설정 파일>" "<설정 파일>.diode-backup"
   ```

   설정 파일이 아직 없으면 백업할 것이 없다 — 새로 만들고, 제거할 때 그 파일을 지울지 사용자에게 묻는다.
3. 합친다. 합친 파일이 JSON 으로 읽히는지 본다.

   ```text
   python -c "import json, sys; json.load(open(sys.argv[1], encoding='utf-8'))" "<설정 파일>"
   ```

   아무것도 찍지 않고 끝나면 된다. 파일에 주석이 있으면 이 확인이 실패할 수 있다 (opencode 설정이 주석을 허용하는지는 **[미확인]**) — 그때는 사용자에게 파일을 직접 보게 한다.

- **확인**: `python "D:\claude\diode\diode.py" setup --check` 에 `일꾼 명령 설정함` 이 있고 `일꾼 명령 문제:` 줄이 없다. 권한이 의도대로 닫혔는지의 정본 시험은 8단계의 `kit/run_opencode.py` (H5) 다.
- **실패하면**:
  - `일꾼 명령 문제: 실행 파일을 PATH 에서 찾지 못함` — 명령의 첫 낱말이 PATH 에 없다. 사용자가 창에서 고친다.
  - `일꾼 명령 문제: Windows .cmd 껍데기에 {prompt} 를 인자로 줌 (명령 주입 길 - 표준 입력으로 받게 {prompt} 를 빼세요)` — 사용자가 창의 `04 일꾼 명령` 에서 `{prompt}` 를 뺀다.
  - `일꾼 명령 문제: 설정을 읽지 못함` — 사용자가 창에서 `04 일꾼 명령` 을 다시 입력한다.
  - 모두 `‼ 일꾼 명령에 문제가 있음 (…) — 일 넘기기는 E-01` 이 같이 나온다. 안전한 쪽 (넘기지 않음) 이므로 고칠 때까지 일꾼 없이 둔다.

## 8. (선택) 사람이 해 볼 시험

진짜 Claude Code CLI 와 opencode 를 가짜 서버에 붙여 훅 · 방 · 일꾼을 처음부터 끝까지 보는 시험이 `kit/` 에 있다. **사람이 직접 돌린다** — 에이전트는 돌리지 않는다. 어떤 명령을 돌리고 무엇을 옮기고 무엇을 옮기지 않는지는 [kit/inhouse-questions.md](kit/inhouse-questions.md#2부--사람이-직접-돌린다) 2부 (H1–H7) 에 있고, 여기에 옮겨 적지 않는다. 예를 들어 훅 시험은 이렇게 돌린다.

```text
python "D:\claude\diode\kit\run_hooks.py"
```

**[질문]** "사람이 해 볼 시험이 있습니다 (선택). 지금 하시겠어요? 하신다면 `kit/inhouse-questions.md` 2부를 보세요." → 거절하면 건너뛴다.

- **확인**: 각 시험이 `R` · `S` · `I` 로 시작하는 줄들과 마지막 `결과: OK` 줄을 낸다.
- **실패하면**: 실패한 줄 (번호와 한 줄) 만 사용자에게 보여 주고 멈춘다. 에이전트가 고치지 않는다. `kit\out\` 폴더의 파일은 열지 않는다 (시스템 프롬프트 원문이 들어 있다).

## 9. 완료 보고

아래 형식으로 사용자에게 보고한다. **키 값 · 사전 단어 · 폴더 이름은 쓰지 않는다.**

```text
Diode 설치 완료
- 위치     : D:\claude\diode (버전 · python "D:\claude\diode\diode.py" version)
- 파이썬   : (1단계 결과 — 3.8 이상인지 · tkinter 가 되는지)
- 코드     : (2단계 결과 — 이미 있었음 | git 으로 받음 | 사용자가 옮겨 둠)
- 플러그인 : (3단계 결과 — claude plugin list 의 diode@diode 와 Status · 명령 풀림: 확인함 | 사람이 새 세션에서 확인하기로 함 | 못 함)
- 설정     : (4단계 결과 — 사전 n개 · 원자료 폴더 m개 · 사내 LLM 판정 설정함 | 없음. 값은 쓰지 않는다)
- 방       : (5단계 결과 — ok | 만들지 못함 + 까닭)
- 일꾼     : (7단계 결과 — 연결 안 함 (선택) | 설정함 · 문제 없음 | 문제 있음 + 코드)
- 점검     : (6단계 결과 — check 와 setup --check 의 마지막 줄)
- 멈춘 곳  : 없음 | n단계 — 이유와 사용자에게 필요한 조치
- 쓰는 법  : `D:\claude\room` 에서 Claude Code 를 새로 여세요 (플러그인은 새로 여는 세션부터 실립니다 · 권한 모드는 기본, auto 는 막힙니다). 사내 일은 안쪽 일꾼에게 넘기고, 사람이 확정 창에서 [넘기기] · [보내기] 를 누를 때만 나갑니다. 지금은 합성 자료로만 쓰세요.
```

---

## 문제 해결

출력에 나온 문구로 찾는다. 문구는 코드가 찍는 그대로다 (`<n>` 같은 꺾쇠는 자리표시). 고친 뒤에는 항상 `check` → `결과: OK` 와 `setup --check` 를 다시 돌린다. 방 만들기의 거절 문구는 [5단계](#5-방-만들기) 표에 있다.

**`diode.py check`**

| 출력에 보이는 것 | 조치 |
|---|---|
| `파이썬 3.8 이상이 필요합니다` | **[질문]** 사용자에게 파이썬 설치를 부탁하고 멈춘다 |
| `DIODE_HOME 이 설정되어 있습니다` (`결과: 확인 필요`) | 테스트용 환경 변수다. **[질문]** 사용자에게 이 PC 의 환경 변수에 있는지 묻고, 평소에는 지우도록 안내한다 (에이전트가 사용자 환경 변수를 고치지 않는다) |
| `데이터 폴더 자리에 파일이 있습니다` | `%LOCALAPPDATA%\diode` 가 폴더가 아니라 파일이다. **[질문]** 사용자에게 알리고 옮기거나 지울지 묻는다 |

**`diode.py setup` · `setup --check`**

| 출력에 보이는 것 | 조치 |
|---|---|
| `python 명령 (훅 · 허브가 부름) 못 찾음` 또는 `… <판> · 모자람` (`× python 명령`) | `python` 이름이 PATH 에 없거나 3.8 미만이다 → 1단계. 3단계를 이미 했다면 이 상태에서 훅이 고장 나 Claude Code 가 막힌다 — 사용자에게 알린다 |
| `사전 · 설정을 읽지 못함 (broken)` (`× 설정` · `× 훅`) | 데이터 폴더의 설정 · 사전 파일이 깨졌다. 에이전트는 열거나 고치지 않는다. **[질문]** 사용자가 `python "D:\claude\diode\diode.py" dict` 로 창을 열어 다시 입력하고 [저장] 한다 — 저장할 때 깨진 파일은 `.broken` 으로 옮겨 둔다. 이 경우 `setup` 은 창을 열지 않고 `설정을 읽지 못해 창을 열지 않았습니다 (broken)` 줄을 `결과:` 줄 **뒤에** 붙인다 (`결과:` 가 마지막 줄이 아닌 경우) |
| `사전 · 설정을 읽지 못함 (newer)` | 데이터가 이 코드보다 새 판이 만든 것이다. 덮어쓰지 않는다. 코드가 옛 판이니 [업데이트](#업데이트) 를 **[질문]** 한다 |
| `훅 자체 시험 실패` (`× 훅`) | 위에 `사전 · 설정을 읽지 못함` 이 같이 있으면 그것부터. 없으면 출력을 그대로 보여 주고 멈춘다. git 으로 받았다면 `git -C "D:\claude\diode" status --short` 로 소스가 바뀌었는지 본다 |
| `‼ 사전이 비어 있음 — 보내기를 막습니다` · `‼ 원자료 폴더 목록이 비어 있음 — 보내기를 막습니다` | 4단계가 안 끝났다. 정책 창에서 사람이 입력하게 한다 |
| `‼ 사내 LLM 판정 (D7) 설정이 없음 — 보내기를 막습니다` | 정책 창의 `06 llm` 이 비었다. 이것만 남았으면 설치는 끝난 것이고 보내기만 막힌 상태다. **[질문]** 지금 창에서 채울지 묻는다 |
| `정책 (사전 · 원자료 폴더) 이 비어 있는데 정책 창을 띄울 수 없습니다 (E-07) - 화면이 없거나 이 파이썬에 tkinter 가 없습니다` | 화면이 있는 PC 에서 `/diode:dict` 를 열어야 한다. **[질문]** 하고 멈춘다 |
| `일꾼 명령 문제: 실행 파일을 PATH 에서 찾지 못함` · `일꾼 명령 문제: Windows .cmd 껍데기에 {prompt} 를 인자로 줌 (명령 주입 길 - 표준 입력으로 받게 {prompt} 를 빼세요)` · `일꾼 명령 문제: 설정을 읽지 못함` (`‼ 일꾼 명령에 문제가 있음 (…) — 일 넘기기는 E-01`) | 7단계의 실패하면 목록을 따른다 |
| `안내 파일 (사용자 범위 · 이 폴더와 위 폴더의 CLAUDE.md · AGENTS.md) 에 사전 단어가 <n>개 있음 — Claude 가 모든 요청에 읽어 갑니다` (`‼ 안내 파일에 사전 단어가 있음 (L-29) — 지우거나 옮기세요 · 그 전에는 프롬프트가 막힙니다`) | 안내 파일은 모든 요청에 실려 간다. 에이전트는 그 파일을 열지 않는다. **[질문]** 사용자가 단어를 지우거나 옮긴다. 그 전에는 세션에서 프롬프트가 막힌다 |
| `‼ 안내 파일 (CLAUDE.md · AGENTS.md) 을 사전으로 검사하지 못함` | 검사가 실패했다. 출력을 그대로 보여 주고 **[질문]** |
| `방 없음 (/diode:room)` (`‼ 방이 ok 가 아님 (missing)`) | 5단계 |
| `방 changed (방 설정이 바뀜 — 막힘)` (`‼ 방이 ok 가 아님 (changed)`) | 5단계 표의 `changed` 행 |
| `diode.py setup: 실패 (E-20)` (표준 오류) | 내부 예외다. 출력을 그대로 보여 주고 멈춘다 |

**세션 안에서 Claude Code 화면에 보이는 알림** (훅이 내는 글)

| 보이는 것 | 뜻 · 조치 |
|---|---|
| `DIODE: 아직 설정하지 않았습니다 - 이 세션은 지켜지지 않습니다 · /diode:setup` | 4단계 전의 정상 상태다. 4단계를 마친다 |
| `DIODE V<Vth 막힘 · E-20 - 사전 · 설정을 읽지 못해 막았습니다 · /diode:setup` | 설정 · 사전이 깨졌거나 새 판이다 — 위 `broken` · `newer` 행 |
| `DIODE V<Vth: 방 설정이 바뀌었습니다 (changed) · 방의 .claude 설정을 되돌리거나 방을 지운 뒤 방 밖에서 /diode:room 을 다시 하세요` | 5단계 표의 `changed` 행. 이미 있는 방은 `/diode:room` 이 덮어쓰지 않으므로 사람이 먼저 방의 설정을 되돌리거나 방을 지운다 |
| `DIODE V<Vth: 원자료 폴더에서 Claude 를 열었습니다 · 방에서 여세요` | 원자료 폴더 안이거나 원자료 폴더를 품은 폴더에서 Claude Code 를 열었다. `D:\claude\room` 에서 연다 |
| `DIODE V<Vth: 방은 수동 권한 모드로 쓰세요 (auto 막음)` | 방에서는 auto 권한 모드를 쓰지 못한다. 기본 권한 모드로 다시 연다 |
| `DIODE V<Vth 막힘 · D2 x<개수> @안내파일 - CLAUDE.md · AGENTS.md 에 사내 단어가 있어 Claude 가 읽어 갑니다 - 지우거나 옮기세요 (/diode:status)` | 위 `안내 파일` 행 |
| `hook … failed; blocking because onFailure is block` (Claude Code 가 내는 글 · 판마다 다를 수 있다) | 훅이 못 돌았다. 대개 `python` 이름이 안 찾아지는 것이다 → 1단계 |

## 업데이트

**[질문]** "Diode 를 새 판으로 업데이트할까요? 코드가 바뀌면 이 PC 의 훅도 바뀝니다." → 동의했을 때만 한다. git 으로 받은 PC 는 아래 첫 줄부터 한다. 압축 파일 · 복사로 옮겨 둔 PC (2단계에서 `fatal: not a git repository`) 는 사용자가 새 판을 `D:\claude\diode` 에 다시 옮겨 둔 뒤 둘째 줄 (`version`) 부터 한다 — 에이전트가 폴더를 지우거나 덮어쓰지 않는다.

```text
git -C "D:\claude\diode" pull --ff-only
python "D:\claude\diode\diode.py" version
claude plugin marketplace update diode
claude plugin update diode@diode
python "D:\claude\diode\diode.py" check
python "D:\claude\diode\diode.py" setup --check
```

- **확인**: `pull` 이 `Already up to date.` 또는 바뀐 파일 목록을 찍는다. `claude plugin marketplace update diode` 가 `Successfully updated marketplace: diode`, `claude plugin update diode@diode` 가 `updated from <옛 판> to <새 판> … Restart to apply changes.` 를 찍는다 (바뀐 게 없으면 문구가 다를 수 있다 — **[미확인]**). `claude plugin list` 의 `Version:` 이 `diode.py version` 과 같고, 마지막 두 점검이 `결과: OK`.
- **Claude Code 쪽**: 플러그인은 `D:\claude\diode` 에서 그 자리로 읽히므로, 열려 있는 세션에는 다음 세션 시작이나 `/reload-plugins` 때 반영된다고 Claude Code 가 알린다. 열려 있는 Claude Code 를 모두 닫고 다시 시작하라고 사용자에게 안내한다. `git pull` 만 하고 위 두 `claude plugin` 명령을 건너뛰어도 되는지는 **[미확인]** 이다 (`claude plugin list` 의 버전은 `pull` 만으로도 바뀌어 보였지만, 훅이 새 코드로 도는 시점은 직접 확인하지 못했다).
- **실패하면**:
  - `fatal: Not possible to fast-forward, aborting.` 또는 로컬 변경 때문에 덮어쓸 수 없다는 오류 — 소스 폴더에 로컬 변경이나 갈라진 기록이 있다. **[질문]** 사용자에게 알리고 멈춘다. `reset --hard` · `checkout --` 로 되돌리지 않는다.
  - 네트워크 · 권한 오류 — 출력을 보여 주고 멈춘다 (주소를 에이전트가 바꾸지 않는다).
  - 업데이트 뒤 `사전 · 설정을 읽지 못함 (…)` — [문제 해결](#문제-해결) 표.

데이터 (`%LOCALAPPDATA%\diode\`) 는 저장소 밖에 있어서 업데이트로 바뀌지 않는다. 설정 · 사전을 다시 입력할 필요는 없다.

## 제거

되돌릴 수 있는 순서다. 제거하면 이 PC 의 Diode 훅 보호가 없어진다는 것을 먼저 알린다.

0. (7단계를 했다면) **[질문]** "일꾼 연결을 되돌릴까요?" → opencode 설정에서 `diode-worker` 항목만 지운다. 7-2 에서 만든 백업 (`<설정 파일 이름>.diode-backup`) 이 있어도, 그 뒤에 사용자가 설정을 바꿨을 수 있으니 통째로 덮어쓰지 않는다. 백업 파일은 사용자가 확인한 뒤 지운다. Diode 쪽 `04 일꾼 명령` 은 데이터 폴더를 지울 거면 따로 비울 필요가 없고, 남길 거면 사용자가 정책 창에서 칸을 비우고 [저장] 한다 (비운 칸은 설정에서 지워진다).
1. 플러그인을 지운다: `claude plugin uninstall diode@diode` → `Successfully uninstalled plugin: diode (scope: user)`.
2. 마켓플레이스를 뺀다: `claude plugin marketplace remove diode` → `Successfully removed marketplace: diode`.
   - **확인**: `claude plugin list` 에 `diode@diode` 가 없고, `claude plugin marketplace list` 에 `diode` 가 없다. 사용자 설정에 빈 `enabledPlugins` · `extraKnownMarketplaces` 칸이 남을 수 있고, Claude Code 의 캐시에 설치 때의 복사본이 남을 수 있다 — Claude Code 가 관리하는 자리라 손대지 않는다.
   - **실패하면**: `Marketplace 'diode' not found` 는 이미 빠져 있다는 뜻이다. 그 밖의 오류는 출력을 보여 주고 멈춘다.
3. **[질문]** "방 `D:\claude\room` 을 지울까요?" → 사용자 확인 후에만 지운다. 방의 상태줄 명령이 소스의 `diode.py` 를 부르므로, 소스를 지울 거면 방도 같이 지우는 것이 낫다. 방 안의 `inbox` · `outbox` 에 사용자가 아직 쓸 보고가 있는지도 묻는다.
4. **[질문]** "`%LOCALAPPDATA%\diode\` 에는 감사 기록 (보낸 것의 기록) 이 있습니다. 백업할까요?" → 사용자 확인 후에만 데이터 폴더를 지운다. 플러그인을 지워도 이 폴더는 남는다. 사전이 사내 단어 평문이므로 백업 자리도 안전한 곳이어야 한다. 플러그인이 실린 세션에서는 훅이 데이터 폴더를 가리키는 셸 명령을 막으므로, 지우는 일은 사용자가 직접 하게 안내한다.
5. **[질문]** "소스 `D:\claude\diode` 도 지울까요?" → 확인 후에만 지운다.

3 · 5 의 폴더를 지우는 명령은 이 문서에 적지 않는다 — 되돌릴 수 없는 일이라, 사용자가 확인한 폴더를 사용자가 직접 지우게 안내한다. 사용자가 에이전트에게 지워 달라고 하면 폴더 이름을 한 번 더 말하고 확인받은 뒤에 한다.

## 참고: 명령 모음

| 명령 | 하는 일 |
|---|---|
| `python "D:\claude\diode\diode.py" check` | 자가 점검 — 파이썬 판 · 데이터 폴더 자리 (마지막 줄 `결과: …`) |
| `python "D:\claude\diode\diode.py" setup --check` | 전체 점검 (읽기만 · 마지막 줄 `결과: …`) |
| `python "D:\claude\diode\diode.py" setup` | 처음 설정 (`/diode:setup`) — 정책이 비면 정책 창을 열고, 채워졌으면 방을 만들고 점검 |
| `python "D:\claude\diode\diode.py" room` | 방 만들기 (`/diode:room`) — 이미 있는 방은 덮어쓰지 않음 |
| `python "D:\claude\diode\diode.py" dict` | 정책 창을 따로 떼어 열기 (`/diode:dict`) |
| `python "D:\claude\diode\diode.py" version` · `help` | 버전 · 도움말 |
| `python "D:\claude\diode\diode.py" scan` | 표준 입력의 글 검사 (`0` 통과 · `2` 막음 · 사전이 없으면 `2`) |
| `python "D:\claude\diode\diode.py" --status --json` | 상태 (JSON 한 줄 · 읽기 전용 · `/diode:status` 가 점검과 함께 보여 줌) |

이 표에 없는 명령 (`mcp` · `hook` · `propose` · `confirm` · `lib` …) 은 설치 때 부르지 않는다. 전체 목록은 [docs/MANUAL.md](docs/MANUAL.md#명령) 에 있다.
