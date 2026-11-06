> **개발 중 (v0.0) — 합성 자료로만 시험했습니다. 사내 확인 (Windows · 사내 CLI · 보안 부서의 답) 전이라 실데이터에는 쓰지 마세요.**

# Diode

<h3 align="center">한쪽으로만 흐르게.</h3>

<p align="center">
<img src="docs/img/diode-banner.png" alt="왼쪽 Claude (바깥) 에서 지시가 Diode 문을 지나 오른쪽 Opencode (안쪽) 로 흐르고, 거꾸로 가려는 원자료는 문에서 막히는 그림" width="100%">
<br>
<sub>바깥 (Claude CLI) · 문 (Diode) · 안쪽 (사내 LLM) — 지시는 안으로 흐르고, 원자료는 되돌아 나가지 못합니다.<br>
그림 속 Claude · Opencode 는 설명을 위한 표현이며 각 제품의 공식 그림이 아닙니다.</sub>
</p>

<p align="center">
Diode 는 회사 안 (사내 LLM · 원자료) 과 회사 밖 (Claude) 사이에 놓는 접합 하나입니다. (LLM 은 글로 대답하는 인공지능이고, 원자료는 가공하지 않은 원래 자료입니다.)<br>
순방향 — 지시는 안으로 흐릅니다. 역방향 — 원자료는 밖으로 막힙니다.<br>
밖으로 새어 나가는 것은 일부러 정해 둔 아주 작은 누설, 곧 사람이 확인하고 누른 봉인 보고뿐입니다.<br>
<a href="docs/BLUEPRINT.md">PN 접합으로 읽는 청사진 ›</a><br>
<br>
이름은 비유입니다 — 하드웨어 데이터 다이오드가 아닙니다.<br>
(일방향 망연계 장비와 같은 보증을 주지 않습니다.)<br>
전부는 아니고, 이 정도입니다:
</p>

<p align="center"><sub>
CLAUDE CODE 플러그인 · 저장소 하나 = 플러그인 하나 = 마켓플레이스 하나<br>
파이썬 3.8+ · 표준 라이브러리만<br>
테스트 963 · WINDOWS + UBUNTU CI
</sub></p>

<br>

<h3 align="center">지금은 이만큼입니다.</h3>

<p align="center">
훅 · 허브 · 확정 창 · 정책 창 · 설정 명령까지 만들어져 있습니다 (뜻은 아래 표에 풀어 두었습니다). 지어낸 자료로 진짜 Claude CLI 와 opencode 를 붙여 시험했습니다.<br>
사내에서 확인해야 할 것이 남아 있어서 진짜 자료에는 아직 쓰지 않습니다.
</p>

| 되는 것 | 아직 없는 것 (사내에서 확인할 것) |
|---|---|
| 훅 (도구를 쓰기 직전에 끼어들어 검사하는 장치) — 세션을 연 폴더를 보고 방(원자료가 없는 깨끗한 작업 폴더) · 원자료 폴더 · 그 밖으로 가릅니다. 사전 단어나 경로 꼴이 든 말, 방 밖이나 원자료 폴더를 건드리는 도구는 막습니다. 사내 단어가 든 파일은 어디에 있든 `Read` 가 막힙니다 (훅이 고장 나면 열어 두지 않고 막는 쪽으로 닫힙니다) | 사내 Windows · 사내 CLI 판 · 관리형 설정에서의 동작 ([질문지](kit/inhouse-questions.md)) |
| 허브 (MCP, Claude 와 안쪽 사이의 창구) — 일 넘기기 · 보고 받기 · 사내 LLM 판정 (D7) · 감사 기록 (보낸 것의 기록) · 확정 창 (보낼 내용을 사람이 눈으로 보고 누르는 창) · `propose` | 일꾼 연결 방식 확인 — 사내 opencode 가 어떻게 물려 있는지 |
| 정책 창 — 사전 (가릴 사내 단어 목록) · 원자료 폴더 · 안쪽 도구 · 일꾼을 사람이 직접 입력합니다 (Claude 는 읽지도 고치지도 못합니다) | 보안 부서의 답 — 그 전까지 실데이터는 0 입니다 |
| `/diode:setup` · `/diode:room` · `/diode:dict` · `/diode:status` — 점검 · 방 만들기 · 정책 창 열기 · 상태 보기. `/diode:speak` (또는 `diode.py speak`) 는 말 봉인 창을 엽니다 — 사내 말로 쓰면 사전 단어를 토큰(가짜 이름표) 글로 바꿔 보여 주고, 사람이 확인한 뒤 복사합니다 | 어림 비용 · 팀 사전 들여오기 |
| 검사기 D1–D6 · seal · unseal · 자기 검사기 · CI — Windows · Ubuntu × 파이썬 3.8 · 3.13 | |
| L2 파생 표본 — `diode.py derive` 가 표의 진짜 값 대신 아주 거칠게 줄인 값만 담은 초안을 만듭니다. 기본은 꺼져 있고 정책 창에서만 켭니다. 이 값으로 누군가를 다시 알아낼 수 있는지는 증명하지 못합니다 | |

앞으로 할 일의 순서는 [기획서](docs/PLAN.md) 의 로드맵에 있습니다. 진짜 자료(실데이터)는 보안 부서의 답이 나오기 전에는 쓰지 않습니다.

<br>

<h3 align="center">합성 자료로만 시험하세요.</h3>

<p align="center">
설치하면 훅이 걸리고 허브가 뜹니다. 그래도 사내 확인이 끝나기 전에는 진짜 자료를 맡기지 마세요 (보호받고 있다고 믿어 버리는 것이 가장 위험합니다).<br>
설치하는 방법은 <a href="INSTALL.md">INSTALL.md</a> 에 있습니다 — Claude Code 가 그대로 따라 하는 단계별 안내서입니다.
</p>

<br>

<table align="center">
<tr><td width="620"><a href="docs/PLAN.md">기획서</a> <sub>· 설계의 까닭 · 불변식 · 새는 길 · 로드맵</sub></td><td align="right" width="40">›</td></tr>
<tr><td><a href="docs/SPEC.md">명세</a> <sub>· 칸 · 판정 · 출력 꼴 · 오류 번호</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/BLUEPRINT.md">청사진</a> <sub>· PN 접합으로 읽기 · 비유의 정본</sub></td><td align="right">›</td></tr>
<tr><td><a href="RULES.md">규칙</a> <sub>· 이 저장소가 지키는 헌법 열두 조</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/MANUAL.md">매뉴얼</a> <sub>· 이 도구가 못 하는 것 · 명령 · 개발</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/INHOUSE.md">사내 마무리</a> <sub>· 공개 저장소와 사내 작업의 경계</sub></td><td align="right">›</td></tr>
<tr><td><a href="AGENTS.md">에이전트 규칙</a> <sub>· 이 저장소를 고치는 에이전트용</sub></td><td align="right">›</td></tr>
</table>

<br>

<p align="center"><sub>
Diode · 아직은 한쪽으로도 안 흐릅니다 · MIT 라이선스<br>
화면 문법은 소형 하드웨어 계측기(Teenage Engineering 류)에서 영감을 받았고, 해당 회사와는 관련이 없습니다.
</sub></p>
