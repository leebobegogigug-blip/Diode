> **개발 중 (v0.0) — 훅만 있습니다. 허브 · 확정 창이 없어 아직 쓸 수 없습니다. 설치하지 마세요.**

# Diode

<h3 align="center">한쪽으로만 흐르게.</h3>

<p align="center">
<img src="docs/img/diode-banner.png" alt="왼쪽 Claude (바깥) 에서 지시가 Diode 문을 지나 오른쪽 Opencode (안쪽) 로 흐르고, 거꾸로 가려는 원자료는 문에서 막히는 그림" width="100%">
<br>
<sub>바깥 (Claude CLI) · 문 (Diode) · 안쪽 (사내 LLM) — 지시는 안으로 흐르고, 원자료는 되돌아 나가지 못합니다.<br>
그림 속 Claude · Opencode 는 설명을 위한 표현이며 각 제품의 공식 그림이 아닙니다.</sub>
</p>

<p align="center">
Diode 는 회사 안 (사내 LLM · 원자료) 과 회사 밖 (Claude) 사이에 놓는 접합 하나입니다.<br>
순방향 — 지시는 안으로 흐릅니다. 역방향 — 원자료는 밖으로 막힙니다.<br>
새어 나가는 것은 설계로 정해 둔 작은 누설, 사람이 확정한 봉인 보고뿐입니다.<br>
<a href="docs/BLUEPRINT.md">PN 접합으로 읽는 청사진 ›</a><br>
<br>
이름은 비유입니다 — 하드웨어 데이터 다이오드가 아닙니다.<br>
(일방향 망연계 장비와 같은 보증을 주지 않습니다.)<br>
전부는 아니고, 이 정도입니다:
</p>

<p align="center"><sub>
CLAUDE CODE 플러그인 · 저장소 하나 = 플러그인 하나 = 마켓플레이스 하나<br>
파이썬 3.8+ · 표준 라이브러리만<br>
테스트 438 · WINDOWS + UBUNTU CI
</sub></p>

<br>

<h3 align="center">지금은 이만큼입니다.</h3>

<p align="center">
검사기 · 훅 · 허브 · 확정 창까지 있습니다. 처음 설정 (사전 · 원자료 폴더) 과 일꾼 연결이 아직 없어서 쓸 수 없습니다.
</p>

| 되는 것 | 아직 없는 것 (그래서 아직 쓸 수 없습니다) |
|---|---|
| 훅 — 세션 폴더로 방 · 원자료 폴더 · 그 밖을 가르고, 사전 단어 · 경로 꼴이 든 말과 방 밖 · 원자료 폴더의 도구를 막습니다 (고장 나면 막는 쪽) | 명령 — `/diode:setup` · `/diode:room` (사전 · 원자료 폴더 · 방 만들기) |
| 검사기 D1–D6 · 합성 재현 코드 검사 · `python diode.py scan` | 일꾼 연결 — 사내 LLM (opencode) 에 지시 넣기 |
| 허브 (MCP) — 일 넘기기 · 보고 받기 · 확정 창 · 감사 기록 · 사내 LLM 판정 (D7) · `propose` | 사람이 정책 (사전 · 원자료 폴더) 을 확정하는 창 |
| seal · unseal · 묶기 파일 · 자기 검사기 · CI — Windows · Ubuntu × 파이썬 3.8 · 3.13 | 실데이터 — 보안 부서의 답이 있을 때까지 0 |

순서는 [기획서](docs/PLAN.md) 의 로드맵에 있습니다. 실데이터는 보안 부서의 답이 있기 전에는 쓰지 않습니다.

<br>

<h3 align="center">설치하지 마세요.</h3>

<p align="center">
지금 설치해도 보호는 생기지 않고, 보호받는다는 착각만 생깁니다.<br>
설치 절차의 뼈대는 <a href="INSTALL.md">INSTALL.md</a> 에 있고, 단계는 v0.1 에서 채웁니다.
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
