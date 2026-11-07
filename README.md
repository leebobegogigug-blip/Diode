> **개발 중 (v0.0) — synthetic data 로만 시험했다. 사내 자체 검증을 마치기 전에는 real data 에 쓰지 않는다.**<br>
> 이름은 비유다 — hardware data diode 가 아니다. one-way gateway 와 같은 보증을 주지 않는다.

# Diode

<h3 align="center">한쪽으로만 흐르게.</h3>

<p align="center">
<img src="docs/img/diode-banner.png" alt="왼쪽 Claude (outside) 에서 instruction 이 Diode 를 지나 오른쪽 opencode (inside) 로 흐르고, 거꾸로 나가려는 raw data 는 Diode 에서 막히는 그림" width="100%">
<br>
<sub>outside (Claude CLI) · junction (Diode) · inside (in-house LLM) — instruction 은 안으로 흐르고, raw data 는 밖으로 나가지 못한다.<br>
그림 속 Claude · Opencode 는 설명을 위한 표현이며 각 제품의 공식 그림이 아니다.</sub>
</p>

<p align="center"><sub>
CLAUDE CODE PLUGIN · REPO 하나 = PLUGIN 하나 = MARKETPLACE 하나<br>
Python 3.8+ · standard library only<br>
테스트 994 · WINDOWS + UBUNTU CI
</sub></p>

## Diode 는 무엇인가

Diode 는 Claude Code 에 설치하는 plugin 이다. skill 하나와 hook, MCP hub, confirm window 가 한 묶음으로 들어 있다.

회사의 raw data 는 Claude 에게 넘어가면 안 된다. 그렇다고 기획과 화면 설계까지 in-house LLM 에만 맡기면 Claude 의 장점을 살리지 못한다. Diode 는 일을 둘로 나눈다. Claude 는 앞에서 기획하고 instruction 을 내리고, raw data 를 다루는 일은 in-house LLM (opencode) 이 맡는다. Diode 는 그 둘 사이에 놓여 무엇이 어느 쪽으로 흐를 수 있는지를 정한다.

한 번 설치하면 매번 부를 필요가 없다. plugin 은 user scope 로 설치되어 이 PC 의 모든 Claude Code session 에서 기본으로 켜지고, hook 이 session 시작 · 모든 prompt · 모든 tool call 을 먼저 거친다. slash command (`/diode:setup` · `/diode:status` · `/diode:speak` 등) 는 설정이나 확인처럼 사람이 할 일이 있을 때만 쓴다. 다만 처음 설정 (`/diode:setup`) 을 마치기 전이나 plugin 을 끄면 지켜지지 않는다 — 자세한 것은 [Manual](docs/MANUAL.md#매번-부르지-않아도-됩니다--설치하면-늘-거칩니다) 에 있다.

## PN junction diode 처럼 작동한다

PN junction diode 는 current 를 한쪽으로만 흘린다. forward bias 에서 threshold voltage 를 넘기면 current 가 흐르고, reverse bias 에서는 아주 작은 leakage current 만 흐른다. Diode 는 정보에 대해 같은 일을 한다.

```text
   anode (p)                 junction · depletion layer                cathode (n)
   outside: Claude CLI  ─────────────▶|─────────────  inside: in-house LLM · raw data
                        clean room · hub · checker · confirm window

   forward (out → in): Claude 의 instruction 이 들어간다
   reverse (in → out): raw data 는 막힌다 — 설계로 정한 작은 leakage 만 흐른다
```

| PN junction diode | Diode |
|---|---|
| majority carrier (n-region) | raw data — 안쪽에 넘치고, 바깥으로 넘어가면 안 된다 |
| depletion layer | clean room 과 hub — raw data 가 하나도 없는 영역 |
| built-in potential barrier | deterministic checker D1–D8 과 closed format (brief) |
| threshold voltage | human confirmation — confirm window 에서 눌러야 넘어간다 |
| reverse saturation current (leakage) | sealed report — 사람이 확인하고 보낸 짧은 보고 |

- **forward 는 열려 있다.** Claude 가 `dispatch` 로 넘긴 instruction 은 사람이 confirm window 에서 한 번 본 뒤 in-house LLM 에 들어간다. Claude 에게 돌아오는 것은 `{"sent": true, "job": "J-0001"}` 한 줄뿐이다. in-house LLM 의 response 나 log 는 이 길로 되돌아오지 않는다.
- **reverse 는 막혀 있다.** raw data folder 에서 연 session, in-house term 이 든 prompt, raw data 를 읽으려는 tool call 은 hook 이 막는다. hook 이 고장 나도 열리지 않고 닫힌다 (fail-closed).
- **threshold 는 화면에 그대로 보인다.** check 를 모두 통과한 글은 `DIODE V>Vth 통과`, 하나라도 걸린 글은 `DIODE V<Vth 막힘 · D2 x2 @ask` 로 표시된다.

## Make it leak — 단, 가리고 정규화해서

실제 PN junction diode 도 reverse 로 아주 조금은 샌다. Diode 는 그 leakage 를 일부러 만든다. **Make it leak — but only by design.** reverse 로 나갈 수 있는 것은 sealed report 하나뿐이고, raw data 를 그대로 내보내는 길은 없다. 무언가를 밖으로 흘리려면 이름은 가리고 (masking) 내용은 정규화해서 (normalize) 일의 모양만 남겨야 한다.

1. **masking — 이름을 pseudonym token 으로 바꾼다.** 제품·공정·과제·고객 이름처럼 dictionary 에 올린 in-house term 은 `PH_K7Q2` 같은 token 이 된다. token 은 자문마다 새로 뽑고, 진짜 이름과 짝지은 pseudonym table 은 memory 에만 둔다. Claude 의 답이 돌아오면 아는 token 만 안쪽에서 진짜 이름으로 되돌린다. 사람이 사내 말로 Claude 에게 물을 때는 `/diode:speak` window 가 같은 일을 한다.
2. **normalize — 내용을 모양으로 바꾼다.** in-house LLM 은 결과를 closed format 의 brief 로 다시 쓴다. free text 는 일반적인 말로만 쓰고, 숫자·path·address·source code·log 를 적을 field 는 처음부터 없다. 표가 꼭 필요하면 `diode.py derive` 가 값을 bucket (0–4) · rank (0–9) · category token 으로 아주 거칠게 줄인 derived sample 만 만든다. 이 기능은 기본으로 꺼져 있다.
3. **검사한다.** deterministic checker D1–D6 이 format, dictionary term 과 그 variant, path·address pattern, 숫자, code block, token 을 보고, D7 에서 in-house LLM 이 한 번 더 판정한다. 하나라도 걸리면 흘리지 않는다.
4. **사람이 확정한다.** confirm window (D8) 에 보낼 byte 가 그대로 보이고, 사람이 눌러야 나간다. 흘린 것은 모두 audit log 에 남는다.

가려도 뜻은 남을 수 있다. brief 가 너무 구체적이면 Claude 가 가린 이름을 맞힐 수 있고 (tunneling), 여러 번 보낸 것을 모으면 원래 그림이 드러난다 (mosaic). 그래서 Claude 의 답에 보낸 적 없는 dictionary term 이 나오면 그 주제를 멈추고, derived sample 은 re-identification simulation 으로 정한 limit 안에서만 만든다. 그래도 re-identification 이 불가능하다고 증명하지는 못한다. 같은 PC 에서 shell 을 쥔 쪽 앞에서는 어떤 장치도 단단한 벽이 아니라는 점도 같다.

## 더 읽을 것

<table align="center">
<tr><td width="620"><a href="INSTALL.md">Install</a> <sub>· Claude Code 가 그대로 따라 하는 단계별 안내</sub></td><td align="right" width="40">›</td></tr>
<tr><td><a href="docs/BLUEPRINT.md">Blueprint</a> <sub>· PN junction 으로 읽는 design · datasheet</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/PLAN.md">Plan</a> <sub>· design rationale · invariant · leak path</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/SPEC.md">Spec</a> <sub>· field · verdict · output format · error code</sub></td><td align="right">›</td></tr>
<tr><td><a href="docs/MANUAL.md">Manual</a> <sub>· command · known limitation</sub></td><td align="right">›</td></tr>
<tr><td><a href="RULES.md">Rules</a> <sub>· 이 repo 가 지키는 12 articles</sub></td><td align="right">›</td></tr>
</table>

<p align="center"><sub>
Diode · MIT License<br>
UI 문법은 소형 hardware instrument (Teenage Engineering 류) 에서 영감을 받았으며, 해당 회사와는 관련이 없다.
</sub></p>
