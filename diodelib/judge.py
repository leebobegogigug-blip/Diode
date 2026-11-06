# -*- coding: utf-8 -*-
"""D7 사내 LLM 판정 (SP-05 · 부록 A) — 표준 라이브러리 urllib · Python 3.8.

- 설정은 데이터 폴더 config.json 의 llm (works SPEC-llm 의 키). 환경 변수 덮어쓰기 (<접두어>_BASE_URL 등) 는
  받지 않는다 (RULES S-09 · AL-12). 프록시도 환경 변수에서 읽지 않는다 — ProxyHandler 는 빈 사전이고,
  설정 llm.proxy 에 주소를 적었을 때만 그 주소를 쓴다 (null · "" 는 프록시 없음).
- 보내는 것: 부록 A 의 고정 프롬프트 + 펼친 글. 그 밖의 글은 보내지 않는다.
- pass 는 답이 정확히 {"verdict": "pass", "reason": "none"} 한 줄 JSON 일 때뿐이다.
  그 밖의 답 · 오류 · 시간 초과 (60초) · 설정 없음 → block (AL-03).
- 결과는 {"check": "D7", "verdict": "pass"|"block", "reason": "<닫힌 번호>"} 하나. 판정 글 · 답 원문 ·
  키 · 주소는 결과 · 로그 · 예외 글에 넣지 않는다 (AL-11 · W-04). 이 모듈은 아무것도 찍지 않는다.
"""

import json
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.request

CHECK = "D7"
TIMEOUT_SEC = 60                 # SP-05 — 이보다 길게 기다리지 않는다
MAX_ANSWER_BYTES = 1048576       # 응답 본문 상한 [제안]
MAX_TEXT_BYTES = 8192            # 펼친 글 상한 (SP-02 와 같다)
# 사내 LLM 이 답하는 까닭 번호 (부록 A)
LLM_REASONS = ("name", "number", "path", "code", "other", "none")
# 판정을 못 해 막은 까닭 번호 [제안] — 설정 없음 · 설정 꼴 · 시간 초과 · 연결 · HTTP 오류 · 답 꼴
FAIL_REASONS = ("unset", "config", "timeout", "error", "answer")

PROMPT = (
    "당신은 사내 보안 판정기다. 아래 [글] 이 회사 밖으로 나가도 되는지 판정한다.\n"
    "다음 중 하나라도 있으면 block 이다: 특정 회사 · 제품 · 공정 · 장비 · 고객 · 사람 · 사내 시스템을 알아볼 수 있는 말,\n"
    "수치 (숫자 · 풀어 쓴 수 · 범위 · 비율), 경로 · 주소 · 식별 번호, 코드 원문 · 로그 · 오류 원문.\n"
    "PH_ 로 시작하는 토큰은 가린 이름이므로 그 자체로는 문제가 아니다.\n"
    "답은 JSON 한 줄만: {\"verdict\": \"pass\" 또는 \"block\", \"reason\": \"name|number|path|code|other|none\"}\n"
    "[글]\n"
    "%s\n"
    "[/글]"
)
# 펼친 글이 프롬프트의 틀을 닫거나 새로 여는 꼴 — 보내지 않고 막는다
_FRAME_RE = re.compile(r"\[\s*/?\s*글\s*\]")
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9\-]{1,64}\Z")
_FILE_REF_RE = re.compile(r"^\{file:(.+)\}\Z")
_ENV_REF_RE = re.compile(r"^\{env:.*\}\Z")


def verdict(v, reason):
    return {"check": CHECK, "verdict": v, "reason": reason}


def _block(reason):
    return verdict("block", reason)


def as_result(check):
    """D7 결과 하나 → SP-05 꼴 {"ok", "hits"}. pass 가 아니면 모두 막음."""
    if isinstance(check, dict) and check.get("check") == CHECK and check.get("verdict") == "pass":
        return {"ok": True, "hits": []}
    reason = check.get("reason") if isinstance(check, dict) else None
    if reason not in LLM_REASONS + FAIL_REASONS:
        reason = "error"
    return {"ok": False, "hits": [{"check": CHECK, "count": 1, "where": ["*"], "reason": reason}]}


class _ConfigError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """다른 주소로 넘기는 답을 따르지 않는다 (판정 글이 설정 밖 주소로 가지 않게)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _resolve_secret(v):
    """키 · 인증 헤더 값. {file:경로} 는 파일 내용 (앞뒤 공백 제거). {env:이름} 은 받지 않는다 (환경 변수를 읽지 않음)."""
    if not isinstance(v, str):
        raise _ConfigError()
    if _ENV_REF_RE.match(v):
        raise _ConfigError()        # [제안] SPEC-llm 의 {env:} 참조는 쓰지 않는다 — 환경 변수로 판정을 흔들지 못하게
    m = _FILE_REF_RE.match(v)
    if m:
        with open(os.path.expanduser(m.group(1)), "r", encoding="utf-8") as f:
            v = f.read().strip()
    if any(ch in v for ch in "\r\n\x00"):
        raise _ConfigError()
    return v


def _settings(llm):
    """llm 설정 → 요청에 쓸 값. 없으면 None (unset) · 꼴이 틀리면 _ConfigError."""
    if not isinstance(llm, dict):
        return None
    base = llm.get("base_url", "")
    model = llm.get("model", "")
    if not base or not model:
        return None
    if not isinstance(base, str) or not isinstance(model, str):
        raise _ConfigError()
    if not re.match(r"^https?://[^\s/@]+(/[^\s]*)?\Z", base) or len(model) > 200 \
            or any(ch in model for ch in "\r\n\x00"):
        raise _ConfigError()
    s = {"url": base.rstrip("/") + "/chat/completions", "model": model, "headers": {}}
    key = llm.get("api_key", "")
    key = _resolve_secret(key) if key else ""
    if key:
        s["headers"]["Authorization"] = "Bearer " + key
    extra = llm.get("extra_headers", {}) or {}
    if not isinstance(extra, dict):
        raise _ConfigError()
    for name, val in extra.items():
        if not isinstance(name, str) or not _HEADER_NAME_RE.match(name):
            raise _ConfigError()
        s["headers"][name] = _resolve_secret(val)
    temp = llm.get("temperature", 0.2)
    mt = llm.get("max_tokens", 2048)
    if isinstance(temp, bool) or not isinstance(temp, (int, float)) or isinstance(mt, bool) \
            or not isinstance(mt, int) or mt <= 0:
        raise _ConfigError()
    s["temperature"], s["max_tokens"] = temp, mt
    to = llm.get("timeout_sec", TIMEOUT_SEC)
    if isinstance(to, bool) or not isinstance(to, (int, float)) or to <= 0:
        raise _ConfigError()
    s["timeout"] = min(float(to), float(TIMEOUT_SEC))
    proxy = llm.get("proxy")
    if proxy is None or proxy == "":
        s["proxies"] = {}
    elif isinstance(proxy, str) and re.match(r"^https?://[^\s]+\Z", proxy):
        s["proxies"] = {"http": proxy, "https": proxy}
    else:
        raise _ConfigError()
    ca = llm.get("ca_file", "")
    if ca and not isinstance(ca, str):
        raise _ConfigError()
    s["ca_file"] = ca or ""
    return s


def _opener(s):
    handlers = [urllib.request.ProxyHandler(dict(s["proxies"])), _NoRedirect()]
    if s["url"].startswith("https://"):
        ctx = ssl.create_default_context(cafile=s["ca_file"] or None)
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("같은 키")
        d[k] = v
    return d


def _bad_constant(_):
    raise ValueError("NaN")


def parse_answer(content):
    """사내 LLM 의 답 글 → (verdict, reason) 또는 None (꼴이 틀림). pass 는 reason none 일 때만."""
    if not isinstance(content, str):
        return None
    s = _THINK_RE.sub("", content).strip()
    if not s or "\n" in s or "\r" in s:
        return None
    try:
        obj = json.loads(s, object_pairs_hook=_no_dupes, parse_constant=_bad_constant)
    except Exception:
        return None
    if not isinstance(obj, dict) or set(obj) != {"verdict", "reason"}:
        return None
    v, r = obj["verdict"], obj["reason"]
    if v not in ("pass", "block") or r not in LLM_REASONS:
        return None
    if v == "pass" and r != "none":
        return ("block", r)          # 앞뒤가 맞지 않는 답은 막는다
    return (v, r)


def _ask(s, text, timeout, box):
    """한 번 묻는다 → box["out"] = (verdict, reason). 예외는 막는 까닭 번호로."""
    try:
        body = json.dumps({"model": s["model"], "stream": False, "temperature": s["temperature"],
                           "max_tokens": s["max_tokens"],
                           "messages": [{"role": "user", "content": PROMPT % text}]},
                          ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(s["headers"])
        req = urllib.request.Request(s["url"], data=body, headers=headers, method="POST")
        with _opener(s).open(req, timeout=timeout) as resp:
            if resp.status != 200:
                box["out"] = ("block", "error")
                return
            raw = resp.read(MAX_ANSWER_BYTES + 1)
        if len(raw) > MAX_ANSWER_BYTES:
            box["out"] = ("block", "answer")
            return
        try:
            data = json.loads(raw.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except Exception:
            box["out"] = ("block", "answer")
            return
        got = parse_answer(content)
        box["out"] = got if got else ("block", "answer")
    except Exception as e:          # 오류 글 · 주소는 남기지 않는다 — 번호만
        box["out"] = ("block", "timeout" if _is_timeout(e) else "error")


def _is_timeout(e):
    if isinstance(e, socket.timeout):
        return True
    if isinstance(e, urllib.error.URLError) and isinstance(getattr(e, "reason", None), socket.timeout):
        return True
    return False


def judge(text, llm, timeout=None):
    """펼친 글 text 를 사내 LLM 에 묻는다 → {"check": "D7", "verdict", "reason"}. 예외를 내지 않는다.

    timeout 은 시험용 (초) — 설정 timeout_sec 과 60초 중 작은 것보다 짧게만 줄일 수 있다.
    """
    try:
        if not isinstance(text, str) or not text.strip():
            return _block("other")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES or _FRAME_RE.search(text):
            return _block("other")
        try:
            s = _settings(llm)
        except Exception:
            return _block("config")
        if s is None:
            return _block("unset")
        limit = s["timeout"]
        if timeout is not None:
            limit = min(limit, float(timeout))
        box = {}
        t = threading.Thread(target=_ask, args=(s, text, limit, box), name="diode-d7")
        t.daemon = True
        t.start()
        t.join(limit + 0.5)          # 전체 시간도 묶는다 (조금씩 흘려 보내는 답)
        if t.is_alive() or "out" not in box:
            return _block("timeout")
        v, r = box["out"]
        return verdict("pass", "none") if v == "pass" and r == "none" else _block(r)
    except Exception:
        return _block("error")


def load_llm(home):
    """데이터 폴더 config.json 의 llm 칸. 없으면 None. 꼴이 틀리면 예외."""
    path = os.path.join(home, "config.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict) or cfg.get("format") != 1:
        raise ValueError("설정 꼴")
    return cfg.get("llm")


def judge_home(home, text, timeout=None):
    """데이터 폴더의 설정으로 판정한다. 설정을 못 읽으면 block (config)."""
    try:
        llm = load_llm(home)
    except Exception:
        return _block("config")
    return judge(text, llm, timeout=timeout)
