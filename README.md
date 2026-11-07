> **개발 중 (v0.0) — 합성 자료로만 시험했습니다. 사내 자체 검증을 마치기 전에는 real data 에 쓰지 마세요.**<br>
> 이름은 비유입니다 — 하드웨어 데이터 다이오드가 아닙니다. 일방향 망연계 장비와 같은 보증을 주지 않습니다.

# Diode

<h3 align="center">한쪽으로만 흐르게.</h3>

<p align="center">
<img src="docs/img/diode-banner.png" alt="왼쪽 Claude (바깥) 에서 지시가 Diode 를 지나 오른쪽 opencode (안쪽) 로 흐르고, 거꾸로 나가려는 raw data 는 Diode 에서 막히는 그림" width="100%">
<br>
<sub>바깥 (Claude CLI) · 접합 (Diode) · 안쪽 (in-house LLM) — 지시는 안으로 흐르고, raw data 는 밖으로 나가지 못한다.<br>
그림 속 Claude · Opencode 는 설명을 위한 표현이며 각 제품의 공식 그림이 아닙니다.</sub>
</p>

<p align="center"><sub>
CLAUDE CODE 플러그인 · 저장소 하나 = 플러그인 하나 = 마켓플레이스 하나<br>
파이썬 3.8+ · 표준 라이브러리만<br>
테스트 994 · WINDOWS + UBUNTU CI
</sub></p>

## Diode 는 무엇인가

Diode 는 Claude Code 에 설치하는 플러그인이다. 스킬 하나와 훅, MCP 허브, 확정 창이 한 묶음으로 들어 있다.

회사의 raw data 는 Claude 에게 넘어가면 안 된다. 그렇다고 기획과 화면 설계까지 사내 LLM 에만 맡기면 Claude 의 장점을 쓰지 못한다. Diode 는 일을 둘로 나눈다. Claude 는 앞에서 기획하고 지시하고, raw data 를 만지는 일은 in-house LLM (opencode) 이 맡는다. Diode 는 그 둘 사이에 놓여 무엇이 어느 쪽으로 흐를 수 있는지를 정한다.

## PN 접합 다이오드처럼 작동한다

PN 접합 다이오드는 전류를 한쪽으로만 흘린다. 순방향으로 문턱 전압을 넘기면 전류가 흐르고, 역방향으로는 아주 작은 누설 전류만 흐른다. Diode 는 정보에 대해 같은 일을 한다.

```text
   애노드 (p)                      접합 · 공핍층                      캐소드 (n)
   바깥: Claude CLI   ─────────────▶|─────────────   안쪽: in-house LLM · raw data
                      clean room · 허브 · 검사기 · 확정 창

   순방향 (밖 → 안): Claude 의 지시가 들어간다
   역방향 (안 → 밖): raw data 는 막힌다 — 설계로 정한 작은 누설만 흐른다
```

| PN 접합 다이오드 | Diode |
|---|---|
| n 영역의 다수 캐리어 | raw data — 안쪽에 넘치고, 바깥으로 넘어가면 안 된다 |
| 공핍층 | clean room 과 허브 — raw data 가 하나도 없는 영역 |
| 내부 전위 장벽 | 결정적 검사기 D1–D8 과 닫힌 형식 (brief) |
| 문턱 전압 | 사람의 확정 — 확정 창에서 눌러야 넘어간다 |
| 역포화 전류 (누설) | 봉인 보고 — 사람이 확인하고 보낸 짧은 보고 |

- **순방향은 열려 있다.** Claude 가 `dispatch` 로 넘긴 지시는 사람이 확정 창에서 한 번 본 뒤 in-house LLM 에 들어간다. Claude 에게 돌아오는 것은 `{"sent": true, "job": "J-0001"}` 한 줄뿐이다. in-house LLM 의 응답이나 로그는 이 길로 되돌아오지 않는다.
- **역방향은 막혀 있다.** raw data 폴더에서 연 세션, 사내 단어가 든 프롬프트, raw data 를 읽으려는 도구 호출은 훅이 막는다. 훅이 고장 나도 열리지 않고 닫힌다.
- **문턱은 화면에 그대로 보인다.** 검사를 모두 통과한 글은 `DIODE V>Vth 통과`, 하나라도 걸린 글은 `DIODE V<Vth 막힘 · D2 x2 @ask` 로 표시된다.

## 역방향으로 보내려면 가리고 정규화한다

역방향으로 나갈 수 있는 것은 봉인 보고 하나뿐이다. raw data 를 그대로 내보내는 길은 없다. 무언가를 밖으로 보내려면 이름은 가리고(masking) 내용은 정규화해서(normalize) 일의 모양만 남겨야 한다.

1. **masking — 이름을 가명 토큰으로 바꾼다.** 제품·공정·과제·고객 이름처럼 사전에 올린 사내 단어는 `PH_K7Q2` 같은 토큰이 된다. 토큰은 자문마다 새로 뽑고, 진짜 이름과 짝지은 표는 메모리에만 둔다. Claude 의 답이 돌아오면 아는 토큰만 안쪽에서 진짜 이름으로 되돌린다. 사람이 사내 말로 Claude 에게 물을 때도 같은 일을 `/diode:speak` 창이 한다.
2. **normalize — 내용을 모양으로 바꾼다.** in-house LLM 은 결과를 닫힌 양식(brief)으로 다시 쓴다. 자유 글은 일반적인 말로만 쓰고, 숫자·경로·주소·코드 원문·로그를 적을 칸은 처음부터 없다. 표가 꼭 필요하면 `diode.py derive` 가 값을 bucket(0–4)·rank(0–9)·category 토큰으로 아주 거칠게 줄인 표본만 만든다. 이 기능은 기본으로 꺼져 있다.
3. **검사한다.** 결정적 검사기 D1–D6 이 형식, 사전 단어와 그 변형, 경로·주소 꼴, 숫자, 코드 덩어리, 토큰을 보고, D7 에서 in-house LLM 이 한 번 더 판정한다. 하나라도 걸리면 보내지 않는다.
4. **사람이 확정한다.** 확정 창(D8)에 보낼 바이트가 그대로 보이고, 사람이 눌러야 나간다. 보낸 것은 모두 감사 기록에 남는다.

가려도 뜻은 남을 수 있다. brief 가 너무 구체적이면 Claude 가 가린 이름을 맞힐 수 있고(터널링), 여러 번 보낸 것을 모으면 원래 그림이 드러난다(모자이크). 그래서 Claude 의 답에 보낸 적 없는 사전 단어가 나오면 그 주제를 멈추고, 파생 표본은 재식별 시뮬레이션으로 정한 한도 안에서만 만든다. 그래도 재식별이 불가능하다고 증명하지는 못한다. 같은 PC 에서 셸을 쥔 쪽 앞에서는 어떤 장치도 단단한 벽이 아니라는 점도 같다.

## 더 읽을 것

<table align="center">
<tr><td width="620"><a href="INSTALL.md">설치</a> <sub>· Claude Code 가 그대로 따라 하는 단계별 안내</sub></td><td align="right" width="40">›</td></tr>
<tr><td><a href="docs/BLUEPRINT.md">청사진</a> <sub>· PN 접합으로 읽는 설계 · 데이터시트</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/PLAN.md">기획서</a> <sub>· 설계의 까닭 · 불변식 · 새는 길</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/SPEC.md">명세</a> <sub>· 칸 · 판정 · 출력 꼴 · 오류 번호</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/MANUAL.md">매뉴얼</a> <sub>· 명령 · 알려진 한계</sub></td><td align="right">›</td></tr>
<tr><td><a href="RULES.md">규칙</a> <sub>· 이 저장소가 지키는 헌법 열두 조</sub></td><td align="right">›</td></tr>
</table>

<p align="center"><sub>
Diode · MIT 라이선스<br>
화면 문법은 소형 하드웨어 계측기(Teenage Engineering 류)에서 영감을 받았고, 해당 회사와는 관련이 없습니다.
</sub></p>
