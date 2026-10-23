"""token-meter 숫자 세기 — token-meter의 collect.mjs(커밋 d76ad51)를 파이썬으로 옮긴 것.

python3 -I bin/token_meter.py                  # 내 토큰 요약(아무것도 올리지 않아요)
python3 -I bin/token_meter.py --json           # gist에 올라갈 token-meter.json 그대로(--login <아이디>를 주면 그 아이디로)
python3 -I bin/token_meter.py --dir <claude> --codex-dir <codex> --gemini-dir <gemini>   # 다른 폴더에서 세기

Node·gh 없이 에이전시티 안에서 token-meter에 참가하려고 옮겼어요. 기준은 늘 collect.mjs예요.
collect.mjs가 바뀌면 여기를 똑같이 고치고, 맨 위 커밋을 바꾸고, 아래처럼 다시 맞춰 봐요.
build_doc()은 collect.mjs --publish가 올릴 문서(dict), serialize()는 올릴 글(바이트까지 같아요)이에요.

읽는 것: ~/.claude/projects, ~/.codex/sessions·archived_sessions, ~/.gemini/tmp/…/chats 로그의
토큰 수·모델 이름·시각·세션 id뿐이에요. 대화 내용은 쓰지 않아요. 로그는 한 줄씩 흘려 읽어요
(구형 Gemini .json만 collect.mjs처럼 통째로, 256MB까지). 나가는 칸은 collect.mjs의 화이트리스트(sanitizeEntry)
그대로라 이름·경로·프로젝트·세션 id는 안 나가요. 이 파일은 아무것도 올리지 않아요.

다시 맞춰 보는 법(진짜 HOME·GitHub은 쓰지 않아요):
  1. 가짜 HOME에 로그 폴더(.claude/projects, .codex, .gemini)를 만들어요.
  2. env -i HOME=<가짜> TZ=<시간대> TOKEN_METER_GH=<가짜 gh> node collect.mjs --publish --json --base file:///없음/
     가짜 gh는 api user에 아이디, gists 목록에 [], POST gists에 {"id": …}를 답하고 받은 본문을 남겨요.
  3. 같은 HOME·TZ로 serialize(build_doc(<아이디>, now=<그 updatedAt>))를 만들어 남긴 token-meter.json과 바이트까지 견줘요.
     다른 것은 기록마다의 generatedAt(collect.mjs가 센 시각, updatedAt보다 몇 ms 앞)뿐이라 그것만 맞춰요.
JS와 일부러 맞춘 것: JSON.parse(NaN·Infinity 거절, 숫자는 모두 double), 없는 칸(undefined)과 null의 차이, Map·Set 열쇠,
모델 이름이 constructor·toString 같은 Object.prototype 이름일 때(모델별에서 빠지고 환산액이 0), 정렬 순서,
new Date(…).toLocaleDateString('sv-SE')(이 컴퓨터 시간대), 시간대 이름의 ICU 표기.
다른 것: V8의 옛 날짜 꼴('Aug 1, 2026'·'2026-08-01 10:00')은 못 읽은 날짜로, 1000단 넘게 겹친 JSON 줄은 건너뛰어요
(세 도구 로그에는 없는 꼴). 모델 이름이 __proto__이면 collect.mjs --publish는 gh를 못 띄우고 실패해요(d76ad51의 버그) —
여기서는 collect.mjs가 그때까지 센 값(--json-only)과 같게 셈해요.
"""
import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote

SCHEMA = 1
REPO = "Min-heee/token-meter"
GIST_FILE = "token-meter.json"
GIST_DESCRIPTION = "token-meter — AI coding agent token usage (numbers only)"
MAX_GIST_BYTES = 256 * 1024
MAX_MODELS = 100   # 순위판·참가 검사가 받는 모델 수 상한
TOOLS = ("claude", "codex", "gemini")
TOTAL_KEYS = ("input", "output", "cacheWrite", "cacheRead", "total", "cost", "messages")


def JOIN_URL(gist_id):
    """collect.mjs의 joinUrl: 참가 이슈 쓰기 화면(내가 Submit을 눌러요). encodeURIComponent처럼 적어요."""
    return f"https://github.com/{REPO}/issues/new?template=join.yml&title=join&gist=" + quote(str(gist_id), safe="!'()*")


# ── 단가 (USD / 1M tokens, collect.mjs 그대로) ──────────────────────────
CLAUDE_PRICES = {
    "claude-fable-5": {"in": 10, "out": 50},
    "claude-mythos-5": {"in": 10, "out": 50},
    "claude-opus-5": {"in": 5, "out": 25, "fast": {"in": 10, "out": 50}},
    "claude-opus-4-8": {"in": 5, "out": 25, "fast": {"in": 10, "out": 50}},
    "claude-opus-4-7": {"in": 5, "out": 25},
    "claude-opus-4-6": {"in": 5, "out": 25},
    "claude-opus-4-5": {"in": 5, "out": 25},
    "claude-sonnet-5": {"in": 3, "out": 15, "introUntil": "2026-08-31", "intro": {"in": 2, "out": 10}},
    "claude-sonnet-4-6": {"in": 3, "out": 15},
    "claude-sonnet-4-5": {"in": 3, "out": 15},
    "claude-haiku-4-5": {"in": 1, "out": 5},
}
CLAUDE_FALLBACK = {"in": 5, "out": 25}
CACHE_WRITE_5M, CACHE_WRITE_1H, CACHE_READ = 1.25, 2.0, 0.1
CODEX_PRICES = {
    "gpt-5.5": {"in": 5, "cached": 0.5, "out": 30},
    "gpt-5.4": {"in": 2.5, "cached": 0.25, "out": 15},
    "gpt-5.3-codex": {"in": 1.75, "cached": 0.175, "out": 14},
    "gpt-5.2": {"in": 1.75, "cached": 0.175, "out": 14},
    "gpt-5.1": {"in": 1.25, "cached": 0.125, "out": 10},
    "gpt-5": {"in": 1.25, "cached": 0.125, "out": 10},
}
CODEX_FALLBACK = {"in": 2.5, "cached": 0.25, "out": 15}
LONG_CTX = 272000
GEMINI_PRICES = {
    "gemini-2.5-pro": {"in": 1.25, "cached": 0.125, "out": 10},
    "gemini-2.5-flash": {"in": 0.3, "cached": 0.03, "out": 2.5},
    "gemini-2.5-flash-lite": {"in": 0.1, "cached": 0.01, "out": 0.4},
    "gemini-3.1-pro-preview": {"in": 2, "cached": 0.2, "out": 12},
    "gemini-3-flash-preview": {"in": 0.5, "cached": 0.05, "out": 3},
    "gemini-3.5-flash": {"in": 1.5, "cached": 0.15, "out": 9},
    "gemini-3.1-flash-lite": {"in": 0.25, "cached": 0.025, "out": 1.5},
}
GEMINI_FALLBACK = {"in": 1.25, "cached": 0.125, "out": 10}
GEMINI_LONG_CTX = 200000

# ── 공개 문서 검사 (collect.mjs 그대로) ─────────────────────────────────
DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
TZ_RE = re.compile(r"[A-Za-z0-9_+\-/]{1,64}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9_.:@+\-/() ]{1,64}\Z")
PATHLIKE_RE = re.compile(r"^(?:[/.]|[A-Za-z]:/)|//|(?:^|/)(?:users|home|root|private|tmp|var|volumes|mnt|opt)(?:/|\Z)", re.I)
EMAIL_RE = re.compile(r"@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\Z")
LOGIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")

# ── JS 흉내 ─────────────────────────────────────────────────────────────
_UNDEF = object()   # 칸이 없음(undefined). null(None)과 달라요: new Date(null)은 1970-01-01, null - 0은 0이에요.
_PROTO = frozenset(("constructor", "__defineGetter__", "__defineSetter__", "hasOwnProperty", "__lookupGetter__",
                    "__lookupSetter__", "isPrototypeOf", "propertyIsEnumerable", "toString", "valueOf", "__proto__",
                    "toLocaleString"))   # {}[이 이름]은 Object.prototype 것이 나와요
_NAN_RATE = {"in": math.nan, "out": math.nan, "cached": math.nan}   # 위 이름의 단가는 undefined → 환산액 NaN


def _no_const(s):
    raise ValueError(s)


_loads = json.JSONDecoder(parse_int=float, parse_constant=_no_const).decode   # JSON.parse처럼: 숫자는 모두 double
_OBJ = (dict, list)
_NOGET = {}.get   # 객체가 아닌 값의 칸은 늘 없음(undefined)
# 읽은 JSON 값의 JS 참거짓은 (v or type(v) in _OBJ)로 봐요: JSON에는 NaN이 없어 bool(v)와 같고, 빈 객체·배열만 JS에서 참이에요.


def _get(o, k):
    return o.get(k, _UNDEF) if type(o) is dict else _UNDEF


def _truthy(v):
    if v is None or v is _UNDEF:
        return False
    if isinstance(v, (bool, int, float, str)):
        return bool(v) and v == v   # NaN·0·""은 거짓
    return True   # 객체·배열은 비어도 참


def _num(v):
    return v if type(v) is float and v - v == 0 else 0.0   # 유한한 숫자만(inf - inf는 NaN)


def _cnt(v):
    return v if type(v) in (int, float) and math.isfinite(v) and v > 0 else 0


def _key(v):
    """Map·Set 열쇠(SameValueZero): 글자·숫자·참거짓은 값으로, 객체·배열은 매번 다른 것으로."""
    t = type(v)
    if t is str:
        return v
    if t is float:
        return (0, v)
    if t is bool:
        return (1, v)
    if v is None:
        return (2,)
    return object()


def _numstr(x):
    """Number.prototype.toString — repr이 JS와 같은 가장 짧은 자릿수를 줘요. 꼴만 JS대로."""
    if x != x:
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    if x < 0:
        return "-" + _numstr(-x)
    _, ds, ex = Decimal(repr(x)).as_tuple()
    s = "".join(map(str, ds)).rstrip("0")
    k = len(s)
    n = len(ds) + ex   # 소수점이 s의 몇 번째 자리 뒤에 오는지
    if k <= n <= 21:
        return s + "0" * (n - k)
    if 0 < n <= 21:
        return s[:n] + "." + s[n:]
    if -6 < n <= 0:
        return "0." + "0" * -n + s
    e = n - 1
    return (s if k == 1 else s[0] + "." + s[1:]) + "e" + ("+" if e >= 0 else "-") + str(abs(e))


def _str(v):
    """String(v) — 객체 칸 이름으로 쓸 때(byModel[model] 등)."""
    t = type(v)
    if t is str:
        return v
    if t is float:
        return _numstr(v)
    if t is bool:
        return "true" if v else "false"
    if v is None:
        return "null"
    if v is _UNDEF:
        return "undefined"
    if t is list:
        return ",".join("" if x is None or x is _UNDEF else _str(x) for x in v)
    return "[object Object]"


_WS = "\t\n\v\f\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"   # JS의 공백·줄 끝 글자(StrWhiteSpaceChar)
_DEC_RE = re.compile(r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\Z")
_RADIX_RE = re.compile(r"0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)\Z")


def _tonum(v):
    """ToNumber — Codex는 누적값을 num() 없이 그냥 빼서("100" - 0 = 100, undefined - 0 = NaN) 그대로 따라 해요."""
    t = type(v)
    if t is float:
        return v
    if t is bool:
        return 1.0 if v else 0.0
    if v is None:
        return 0.0
    if t is list:
        v = _str(v)
    elif t is not str:
        return math.nan
    s = v.strip(_WS)
    if not s:
        return 0.0
    if _DEC_RE.match(s):
        return float(s)
    if _RADIX_RE.match(s):
        try:
            return float(int(s[2:], {"x": 16, "o": 8, "b": 2}[s[1].lower()]))
        except OverflowError:
            return math.inf
    return math.nan


def _jsmin(a, b):
    return math.nan if a != a or b != b else (b if b < a else a)


def _jsmax(a, b):
    return math.nan if a != a or b != b else (b if b > a else a)


def _round(n):
    """Math.round(n * 100) / 100 (반올림은 +∞ 쪽)."""
    x = n * 100
    if not math.isfinite(x):
        return x
    r = math.floor(x)
    return float(r + 1 if x - r >= 0.5 else r) / 100


def _is_index(k):
    return k.isascii() and k.isdigit() and (k == "0" or k[0] != "0") and int(k) < 4294967295


def _js_items(d):
    """JS 객체 칸 순서: 배열 번호 꼴 이름(0~2³²-2)이 작은 차례로 먼저, 나머지는 넣은 차례로."""
    idx = sorted((k for k in d if _is_index(k)), key=int)
    if not idx:
        return list(d.items())
    return [(k, d[k]) for k in idx] + [(k, d[k]) for k in d if not _is_index(k)]


def _price(table, key, fallback):
    if key in table:
        return table[key]
    return _NAN_RATE if key in _PROTO else fallback


def _model_slot(by_model, key):
    """byModel[key] ||= blank(). Object.prototype 이름이면 모델별에 남지 않아요(None)."""
    if key in _PROTO:
        return None
    m = by_model.get(key)
    if m is None:
        m = by_model[key] = _blank()
    return m


def _blank():
    return {"input": 0.0, "output": 0.0, "cacheWrite": 0.0, "cacheRead": 0.0, "total": 0.0, "cost": 0.0, "messages": 0}


# ── 날짜: new Date(v).toLocaleDateString('sv-SE') ──────────────────────
# V8의 ISO 꼴: 소문자 t·z, +0900, 24:00, 31일까지(2월 31일은 3월로 넘어가요), 소수 자리는 몇 개든 ms까지 버려요.
_ISO_RE = re.compile(r"([+-][0-9]{6}|[0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?"
                     r"(?:[Tt]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?(?:([Zz])|([+-])([0-9]{2}):?([0-9]{2}))?|([Zz]))?\Z")


def _days_from_civil(y, m, d):
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def _from_local(t):
    """현지 시각(ms) → UTC ms. 없는 시각(서머타임 시작)·두 번 오는 시각(끝)은 바뀌기 전 오프셋으로 — V8/ICU와 같아요."""
    s = t // 1000
    before = time.localtime(s - 86400).tm_gmtoff
    after = time.localtime(s + 86400).tm_gmtoff
    for o in (before, after):
        if time.localtime(s - o).tm_gmtoff == o:
            return t - o * 1000
    return t - before * 1000


def _parse_date(s):
    m = _ISO_RE.match(s)
    if not m:
        return None
    ys, mo, da, hh, mi, ss, frac, z, sign, oh, om, _ = m.groups()   # 끝 칸: 날짜만 + Z(UTC)
    if ys == "-000000":
        return None
    y, mo, da = int(ys), int(mo or 1), int(da or 1)
    h, mi, ss = int(hh or 0), int(mi or 0), int(ss or 0)
    ms = int((frac or "0")[:3].ljust(3, "0"))
    if not (1 <= mo <= 12 and 1 <= da <= 31 and mi <= 59 and ss <= 59 and (h < 24 or (h == 24 and not (mi or ss or ms)))):
        return None
    t = _days_from_civil(y, mo, 1) + da - 1
    t = t * 86400000 + h * 3600000 + mi * 60000 + ss * 1000 + ms
    if sign:
        if int(oh) > 23 or int(om) > 59:
            return None
        t -= (1 if sign == "+" else -1) * (int(oh) * 60 + int(om)) * 60000
    elif hh is not None and not z:
        t = _from_local(t)   # 시각은 있는데 Z·오프셋이 없으면 현지 시각
    return t


def _sub(x, y):
    """x - y (JS 빼기: 숫자가 아니면 ToNumber)."""
    return (x if type(x) is float else _tonum(x)) - (y if type(y) is float else _tonum(y))


def _day(v):
    """이 컴퓨터 시간대의 날짜 'YYYY-MM-DD'(sv-SE 꼴: 1000년 전은 앞 0 없이, 기원전은 1-년). 못 읽으면 None."""
    t = type(v)
    if t is list:
        v, t = _str(v), str
    try:
        if t is str:
            ms = _parse_date(v)
        elif t is float:
            ms = v
        elif t is bool:
            ms = float(v)
        elif v is None:
            ms = 0
        else:
            return None
        if ms is None or ms != ms or abs(ms) > 8.64e15:
            return None
        lt = time.localtime(int(ms) // 1000)
    except (OverflowError, OSError, ValueError):
        return None
    y = lt.tm_year
    return f"{y if y > 0 else 1 - y}-{lt.tm_mon:02d}-{lt.tm_mday:02d}"


_MINUTE_RE = re.compile(r"((?:19[89][0-9]|[2-9][0-9]{3})-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9])(?::[0-5][0-9](?:\.[0-9]+)?)?Z\Z")


class _Days:
    """_day + 분 단위 기억. 1980년 뒤 'YYYY-MM-DDTHH:MM[:SS[.f]]Z'는 같은 분이면 날짜도 같아요
    (1972년 뒤로 모든 시간대의 오프셋과 바뀌는 시각이 분 단위예요). 나머지 꼴은 그때그때 셈해요."""

    def __init__(self):
        self.memo = {}

    def __call__(self, v):
        m = _MINUTE_RE.match(v) if type(v) is str else None
        if m is None:
            return _day(v)
        k = m.group(1)
        d = self.memo.get(k, _UNDEF)
        if d is _UNDEF:
            if len(self.memo) > 200000:
                self.memo.clear()
            d = self.memo[k] = _day(v)
        return d


# ── 시간대 이름: Intl.DateTimeFormat().resolvedOptions().timeZone ──────
# ICU가 다르게 부르는 이름(바뀐 이름<IANA 이름들). Node 26·ICU 78.3에서 zoneinfo의 모든 이름을 TZ로 돌려 뽑았어요.
_TZ_ALIAS = {src: dst for line in """
Africa/Asmera<Africa/Asmara Africa/Bamako<Africa/Timbuktu Africa/Cairo<Egypt Africa/Tripoli<Libya
America/Adak<America/Atka,US/Aleutian America/Anchorage<US/Alaska
America/Buenos_Aires<America/Argentina/Buenos_Aires
America/Catamarca<America/Argentina/Catamarca,America/Argentina/ComodRivadavia
America/Chicago<CST6CDT,US/Central America/Coral_Harbour<America/Atikokan
America/Cordoba<America/Argentina/Cordoba,America/Rosario
America/Denver<America/Shiprock,MST7MDT,Navajo,US/Mountain America/Detroit<US/Michigan
America/Edmonton<America/Yellowknife,Canada/Mountain America/Godthab<America/Nuuk
America/Halifax<Canada/Atlantic America/Havana<Cuba America/Indiana/Knox<America/Knox_IN,US/Indiana-Starke
America/Indianapolis<America/Fort_Wayne,America/Indiana/Indianapolis,US/East-Indiana
America/Iqaluit<America/Pangnirtung America/Jamaica<Jamaica America/Jujuy<America/Argentina/Jujuy
America/Los_Angeles<PST8PDT,US/Pacific America/Louisville<America/Kentucky/Louisville
America/Manaus<Brazil/West America/Mazatlan<Mexico/BajaSur America/Mendoza<America/Argentina/Mendoza
America/Mexico_City<Mexico/General America/New_York<EST5EDT,US/Eastern America/Noronha<Brazil/DeNoronha
America/Panama<EST America/Phoenix<MST,US/Arizona America/Regina<Canada/Saskatchewan
America/Rio_Branco<America/Porto_Acre,Brazil/Acre America/Santiago<Chile/Continental
America/Sao_Paulo<Brazil/East America/St_Johns<Canada/Newfoundland America/St_Thomas<America/Virgin
America/Tijuana<America/Ensenada,America/Santa_Isabel,Mexico/BajaNorte
America/Toronto<America/Montreal,America/Nipigon,America/Thunder_Bay,Canada/Eastern
America/Vancouver<Canada/Pacific America/Whitehorse<Canada/Yukon
America/Winnipeg<America/Rainy_River,Canada/Central Antarctica/McMurdo<Antarctica/South_Pole
Arctic/Longyearbyen<Atlantic/Jan_Mayen Asia/Ashgabat<Asia/Ashkhabad Asia/Calcutta<Asia/Kolkata
Asia/Dhaka<Asia/Dacca Asia/Hong_Kong<Hongkong Asia/Jerusalem<Asia/Tel_Aviv,Israel Asia/Katmandu<Asia/Kathmandu
Asia/Macau<Asia/Macao Asia/Makassar<Asia/Ujung_Pandang Asia/Nicosia<Europe/Nicosia Asia/Rangoon<Asia/Yangon
Asia/Saigon<Asia/Ho_Chi_Minh Asia/Seoul<ROK Asia/Shanghai<Asia/Chongqing,Asia/Chungking,Asia/Harbin,PRC
Asia/Singapore<Singapore Asia/Taipei<ROC Asia/Tehran<Iran Asia/Thimphu<Asia/Thimbu Asia/Tokyo<Japan
Asia/Ulaanbaatar<Asia/Choibalsan,Asia/Ulan_Bator Asia/Urumqi<Asia/Kashgar Atlantic/Faeroe<Atlantic/Faroe
Atlantic/Reykjavik<Iceland Australia/Adelaide<Australia/South Australia/Brisbane<Australia/Queensland
Australia/Broken_Hill<Australia/Yancowinna Australia/Darwin<Australia/North
Australia/Hobart<Australia/Currie,Australia/Tasmania Australia/Lord_Howe<Australia/LHI
Australia/Melbourne<Australia/Victoria Australia/Perth<Australia/West
Australia/Sydney<Australia/ACT,Australia/Canberra,Australia/NSW Europe/Athens<EET Europe/Brussels<CET,MET
Europe/Chisinau<Europe/Tiraspol Europe/Dublin<Eire Europe/Istanbul<Asia/Istanbul,Turkey
Europe/Kiev<Europe/Kyiv,Europe/Uzhgorod,Europe/Zaporozhye Europe/Lisbon<Portugal,WET
Europe/London<Europe/Belfast,GB,GB-Eire Europe/Moscow<W-SU Europe/Warsaw<Poland Pacific/Auckland<NZ
Pacific/Chatham<NZ-CHAT Pacific/Easter<Chile/EasterIsland Pacific/Enderbury<Pacific/Kanton
Pacific/Honolulu<HST,Pacific/Johnston,US/Hawaii Pacific/Kwajalein<Kwajalein
Pacific/Pago_Pago<Pacific/Samoa,US/Samoa Pacific/Ponape<Pacific/Pohnpei Pacific/Truk<Pacific/Chuuk,Pacific/Yap
UTC<Etc/GMT,Etc/GMT+0,Etc/GMT-0,Etc/GMT0,Etc/Greenwich,Etc/UCT,Etc/UTC,Etc/Universal,Etc/Zulu,GMT+0,GMT-0,GMT0,Greenwich,UCT,Universal,Zulu
""".split() for dst, _, srcs in [line.partition("<")] for src in srcs.split(",")}
_ZONEINFO = ("/usr/share/zoneinfo", "/var/db/timezone/zoneinfo", "/usr/lib/zoneinfo", "/usr/share/lib/zoneinfo")


def _tz_name():
    tz = os.environ.get("TZ")
    if tz is None:   # ICU처럼 /etc/localtime 링크에서 zoneinfo/ 뒤를 읽어요
        try:
            link = os.readlink("/etc/localtime")
        except OSError:
            return None
        i = link.find("/zoneinfo/")
        if i < 0:
            return None
        name = link[i + 10:]
    else:
        name = tz[1:] if tz.startswith(":") else tz
    if name in ("", "Factory"):
        return "Etc/Unknown"
    if name == "GMT":
        return "+00:00"   # Node가 TZ=GMT에 이렇게 답해요(공개할 때는 UTC로 바뀌어요)
    if name in _TZ_ALIAS:
        return _TZ_ALIAS[name]
    if name.startswith("/") or ".." in name.split("/") or name in ("posixrules", "leapseconds", "localtime"):
        return None
    for d in _ZONEINFO:
        try:
            with open(os.path.join(d, name), "rb") as f:
                if f.read(4) == b"TZif":
                    return name
        except OSError:
            pass
    return None   # POSIX 꼴(KST-9)·없는 이름: Node는 undefined → 공개할 때 UTC


# ── 파일 ────────────────────────────────────────────────────────────────
def _norm(p):
    p = os.path.normpath(p)
    return "/" + p.lstrip("/") if p.startswith("//") else p   # path.join처럼 // 도 하나로


def _ls(d):
    """fs.readdirSync(d) 순서(이름 바이트 순). 폴더와 보통 파일만 — 심볼릭 링크는 따라가지 않아요."""
    out = []
    try:
        with os.scandir(d) as it:
            for e in it:
                try:
                    kind = "d" if e.is_dir(follow_symlinks=False) else "f" if e.is_file(follow_symlinks=False) else None
                except OSError:
                    kind = None
                if kind:
                    out.append((os.fsencode(e.name), os.path.join(d, e.name), kind))
    except OSError:
        return []
    out.sort()
    return [(p, k) for _, p, k in out]


def _walk(top, exts):
    """collect.mjs의 walk: 깊이 우선, 폴더를 만나면 바로 들어가요."""
    out, stack = [], [_ls(top)[::-1]]
    while stack:
        if not stack[-1]:
            stack.pop()
            continue
        p, kind = stack[-1].pop()
        if kind == "d":
            stack.append(_ls(p)[::-1])
        elif p.endswith(exts):
            out.append(p)
    return out


def _jsonl(path, want=None):
    """한 줄씩 흘려 읽어 JSON 값을 내요. want(바이트 또는 바이트 정규식)가 있으면 그것이 든 줄만 — 글자로 풀기 전에
    바이트로 걸러도 같아요(ASCII는 풀어도 그대로라). 깨진 줄은 건너뛰어요."""
    try:
        f = open(path, "rb")
    except OSError:
        return
    one = want if type(want) is bytes else None
    with f:
        try:
            for raw in f:
                if one is not None:
                    if one not in raw:
                        continue
                elif want is not None and not want.search(raw):
                    continue
                try:
                    yield _loads(raw.decode("utf-8", "replace"))
                except (ValueError, RecursionError):
                    pass
        except OSError:
            return


def _read_doc(path, max_bytes=256 * 1024 * 1024):
    """구형 Gemini 세션(.json, 들여쓴 단일 문서) — collect.mjs처럼 통째로."""
    try:
        if os.stat(path).st_size > max_bytes:
            return None
        with open(path, "rb") as f:
            return _loads(f.read().decode("utf-8", "replace"))
    except (OSError, ValueError, RecursionError):
        return None


def _finish(tool, totals, by_model, by_day, sessions, subagents, split, estimated):
    for m in by_model.values():
        m["cost"] = _round(m["cost"])
    for b in by_day.values():
        b[2] = _round(b[2])
    totals["cost"] = _round(totals["cost"])
    return {"tool": tool, "totals": totals, "byModel": by_model, "byDay": by_day, "sessions": sessions,
            "subagents": subagents, "split": split, "estimated": estimated}


# ── Claude Code ─────────────────────────────────────────────────────────
# 한 응답이 여러 줄(message.id로 접기), resume·fork 복사본(전역 중복 제거), 스트리밍 스냅샷(합이 아니라 최대값)
def _claude(root):
    files = _walk(root, (".jsonl",))
    if not files:
        return None
    day_of, recs = _Days(), {}
    for file in files:
        for d in _jsonl(file, b'"usage"'):
            m = d.get("message") if type(d) is dict else None   # 배열·글자에는 message·usage 칸이 없어요
            u = m.get("usage") if type(m) is dict else None
            if type(u) not in _OBJ:
                continue
            model, err = m.get("model"), d.get("isApiErrorMessage")
            if not (model or type(model) in _OBJ) or model == "<synthetic>" or err or type(err) in _OBJ:
                continue
            rid = m.get("id")
            if not (rid or type(rid) in _OBJ):
                rid = d.get("requestId")
            if not (rid or type(rid) in _OBJ):
                rid = d.get("uuid")
            if not (rid or type(rid) in _OBJ):
                continue
            ug = u.get if type(u) is dict else _NOGET
            cc = ug("cache_creation")
            cg = cc.get if type(cc) is dict else _NOGET
            w1h, w5m = _num(cg("ephemeral_1h_input_tokens")), _num(cg("ephemeral_5m_input_tokens"))
            ses, agent, side = d.get("sessionId"), d.get("agentId"), d.get("isSidechain")
            # [모델, 날짜, fast, 세션, 서브에이전트, 에이전트 id, input, output, write5m, write1h, read]
            cur = [model if type(model) is str else _str(model), day_of(d.get("timestamp", _UNDEF)), ug("speed") == "fast",
                   _key(ses) if ses or type(ses) in _OBJ else None, bool(side or type(side) in _OBJ),
                   _key(agent) if agent or type(agent) in _OBJ else None,
                   _num(ug("input_tokens")), _num(ug("output_tokens")),
                   w5m if w1h + w5m > 0 else _num(ug("cache_creation_input_tokens")), w1h, _num(ug("cache_read_input_tokens"))]
            k = rid if type(rid) is str else _key(rid)
            prev = recs.get(k)
            if prev is None:
                recs[k] = cur
                continue
            for i in range(6, 11):
                if cur[i] > prev[i]:
                    prev[i] = cur[i]
            if not prev[1] and cur[1]:
                prev[1] = cur[1]
    if not recs:
        return None

    totals, by_model, by_day = _blank(), {}, {}
    sessions, agents, split, unknown = set(), set(), {"main": 0.0, "sub": 0.0}, 0.0
    for model, day, fast, ses, sub, agent, inp, out, w5, w1, rd in recs.values():
        p = _price(CLAUDE_PRICES, model, CLAUDE_FALLBACK)
        rt = p["fast"] if fast and "fast" in p else p["intro"] if "intro" in p and day and day <= p["introUntil"] else p
        cost = (inp / 1e6) * rt["in"] + (out / 1e6) * rt["out"] + (w5 / 1e6) * rt["in"] * CACHE_WRITE_5M \
            + (w1 / 1e6) * rt["in"] * CACHE_WRITE_1H + (rd / 1e6) * rt["in"] * CACHE_READ
        cw = w5 + w1
        total = inp + out + cw + rd
        m = _model_slot(by_model, model)
        for kk, v in (("input", inp), ("output", out), ("cacheWrite", cw), ("cacheRead", rd), ("total", total), ("cost", cost)):
            totals[kk] += v
            if m is not None:
                m[kk] += v
        totals["messages"] += 1
        if m is not None:
            m["messages"] += 1
        if model not in CLAUDE_PRICES and model not in _PROTO:
            unknown += total
        split["sub" if sub else "main"] += total
        if sub and agent is not None:
            agents.add(agent)
        if day:
            b = by_day.setdefault(day, [0.0, 0.0, 0.0])
            b[0] += total
            b[1] += out
            b[2] += cost
        if ses is not None:
            sessions.add(ses)
    return _finish("claude", totals, by_model, by_day, len(sessions), len(agents), split, unknown > 0)


# ── Codex ───────────────────────────────────────────────────────────────
# total_token_usage는 세션 누적값: 양수 델타만, 세션이 여러 파일에 걸치면 직전값을 이어받아요.
_ZERO_USAGE = {"input_tokens": 0.0, "cached_input_tokens": 0.0, "output_tokens": 0.0, "total_tokens": 0.0}
_CODEX_WANT = re.compile(rb'"(?:token_count|session_meta|turn_context|agent_message)"')


def _codex(root):
    files = [f for r in ("sessions", "archived_sessions") for f in _walk(os.path.join(root, r), (".jsonl",))
             if os.path.basename(f).startswith("rollout-")]
    if not files:
        return None
    files.sort(key=lambda s: s.encode("utf-16-be", "surrogatepass"))   # JS sort(): UTF-16 순

    totals, by_model, by_day = _blank(), {}, {}
    day_of, sessions, prev_by_session, unknown = _Days(), set(), {}, 0.0
    for file in files:
        sid, model, prev = os.path.basename(file), None, None
        for d in _jsonl(file, _CODEX_WANT):
            p = d.get("payload") if type(d) is dict else None
            if type(p) not in _OBJ:
                continue
            pg = p.get if type(p) is dict else _NOGET
            dt = d.get("type")
            if dt == "session_meta":
                pid = pg("id")
                if pid or type(pid) in _OBJ:
                    sid = _key(pid)
                prev = prev_by_session.get(sid)
                continue
            pm = pg("model")
            if dt == "turn_context" and (pm or type(pm) in _OBJ):
                model = pm
                continue
            pt = pg("type")
            if pt == "agent_message":
                totals["messages"] += 1
                continue
            info = pg("info")
            if pt != "token_count" or not (info or type(info) in _OBJ):
                continue
            ig = info.get if type(info) is dict else _NOGET
            tt, lt = ig("total_token_usage"), ig("last_token_usage")
            if not (tt or type(tt) in _OBJ):
                continue
            # 누적값은 num() 없이 그냥 빼요: 칸이 없으면 NaN이 되고, 그러면 Codex 전체가 빠져요(collect.mjs 그대로)
            base = _ZERO_USAGE if prev is None else prev   # prev || {0…}
            tg = tt.get if type(tt) is dict else _NOGET
            bg = base.get if type(base) is dict else _NOGET
            d_in = _sub(tg("input_tokens", _UNDEF), bg("input_tokens", _UNDEF))
            d_ca = _sub(tg("cached_input_tokens", _UNDEF), bg("cached_input_tokens", _UNDEF))
            d_out = _sub(tg("output_tokens", _UNDEF), bg("output_tokens", _UNDEF))
            prev = prev_by_session[sid] = tt
            if d_in < 0 or d_out < 0:
                continue   # 드문 하향 보정은 버려요
            if d_in == 0 and d_out == 0:
                continue
            day = day_of(d.get("timestamp", _UNDEF))
            sessions.add(sid)
            cached = _jsmax(0.0, _jsmin(d_ca, d_in))
            uncached = d_in - cached
            long = (lt or type(lt) in _OBJ) and _tonum(_get(lt, "input_tokens")) > LONG_CTX   # 272K 넘는 요청 할증
            rt = _price(CODEX_PRICES, _str(model), CODEX_FALLBACK)
            cost = (uncached / 1e6) * rt["in"] * (2 if long else 1) + (cached / 1e6) * rt["cached"] * (2 if long else 1) \
                + (d_out / 1e6) * rt["out"] * (1.5 if long else 1)
            total = d_in + d_out
            key = _str(model) if model is not None else "(unknown)"
            m = _model_slot(by_model, key)
            for kk, v in (("input", uncached), ("output", d_out), ("cacheRead", cached), ("total", total), ("cost", cost)):
                totals[kk] += v
                if m is not None:
                    m[kk] += v
            if key not in CODEX_PRICES and key not in _PROTO:
                unknown += total
            if day:
                b = by_day.setdefault(day, [0.0, 0.0, 0.0])
                b[0] += total
                b[1] += d_out
                b[2] += cost
    if not _truthy(totals["total"]):
        return None   # 0이나 NaN이면 Codex는 없는 셈(collect.mjs와 같아요)
    return _finish("codex", totals, by_model, by_day, len(sessions), 0, None, unknown > 0)


# ── Gemini CLI ──────────────────────────────────────────────────────────
# tmp/<해시>/chats/ 의 신형 .jsonl(레코드 흐름: 같은 id는 교체, $set은 통째로, $rewindTo는 그 id부터 잘라요)과
# 구형 .json(단일 문서). 같은 세션이 둘 다 있으면 .jsonl이 이겨요. tokens.input에는 cached가 들어 있어요.
def _gemini_rate(model):
    if model and (model in GEMINI_PRICES or model in _PROTO):
        return GEMINI_PRICES.get(model, _NAN_RATE)
    if model:
        for k, p in GEMINI_PRICES.items():
            if model.startswith(k):
                return p
    return GEMINI_FALLBACK


def _gemini(root):
    files = [f for f in _walk(os.path.join(root, "tmp"), (".jsonl", ".json")) if "chats" in f.split(os.sep)]
    if not files:
        return None
    sessions = {}   # 열쇠 → (kind, msgs, fmt)
    for file in files:
        sid, kind, msgs = None, "main", {}
        is_jsonl = file.endswith(".jsonl")
        if is_jsonl:
            for rec in _jsonl(file):
                if type(rec) is not dict:
                    continue
                rid = rec.get("id", _UNDEF)
                if _truthy(rec.get("sessionId")) and _truthy(rec.get("projectHash")) and not _truthy(rid):
                    sid, kind = rec["sessionId"], rec["kind"] if _truthy(rec.get("kind")) else "main"
                    continue
                st = rec.get("$set", _UNDEF)
                if _truthy(st):
                    ms = _get(st, "messages")
                    if type(ms) is list:
                        msgs.clear()
                        for m in ms:
                            if _truthy(_get(m, "id")):
                                msgs[_key(m["id"])] = m
                    continue
                rw = rec.get("$rewindTo", _UNDEF)
                if _truthy(rw):
                    k = _key(rw)
                    if k in msgs:
                        ks = list(msgs)
                        for kk in ks[ks.index(k):]:
                            del msgs[kk]
                    continue
                if _truthy(rid):
                    msgs[_key(rid)] = rec   # 다시 오면 스트리밍 갱신 → 자리는 그대로 두고 교체
        else:
            doc = _read_doc(file)
            if type(doc) is not dict or type(doc.get("messages")) is not list:
                continue
            sid = doc["sessionId"] if _truthy(doc.get("sessionId")) else file
            kind = doc["kind"] if _truthy(doc.get("kind")) else "main"
            for m in doc["messages"]:
                if _truthy(_get(m, "id")):
                    msgs[_key(m["id"])] = m
        if not msgs:
            continue
        key = _key(sid if _truthy(sid) else file)
        prev = sessions.get(key)
        if prev is not None and prev[2] == "jsonl" and not is_jsonl:
            continue
        sessions[key] = (kind, msgs, "jsonl" if is_jsonl else "json")
    if not sessions:
        return None

    totals, by_model, by_day, day_of = _blank(), {}, {}, _Days()
    session_ids, subs, split, unknown = set(), set(), {"main": 0.0, "sub": 0.0}, 0.0
    for sid, (kind, msgs, _) in sessions.items():
        touched = False
        for m in msgs.values():
            tk = m.get("tokens", _UNDEF)
            if m.get("type") != "gemini" or type(tk) not in _OBJ:
                continue
            raw_in = _num(_get(tk, "input"))
            cached = min(_num(_get(tk, "cached")), raw_in)
            inp = raw_in - cached
            out = _num(_get(tk, "output")) + _num(_get(tk, "thoughts"))   # 추론 포함
            if inp + cached + out == 0:
                continue
            day = day_of(m.get("timestamp", _UNDEF))
            touched = True
            model = m["model"] if type(m.get("model")) is str else "(gemini)"
            rt = _gemini_rate(model)
            long = "pro" in model and raw_in > GEMINI_LONG_CTX
            cost = (inp / 1e6) * rt["in"] * (2 if long else 1) + (cached / 1e6) * rt["cached"] * (2 if long else 1) \
                + (out / 1e6) * rt["out"] * (1.5 if long else 1)
            total = inp + cached + out
            bm = _model_slot(by_model, model)
            for kk, v in (("input", inp), ("output", out), ("cacheRead", cached), ("total", total), ("cost", cost)):
                totals[kk] += v
                if bm is not None:
                    bm[kk] += v
            totals["messages"] += 1
            if bm is not None:
                bm["messages"] += 1
            if model == "(gemini)" or (model not in GEMINI_PRICES and model not in _PROTO):
                unknown += total
            split["sub" if kind == "subagent" else "main"] += total
            if day:
                b = by_day.setdefault(day, [0.0, 0.0, 0.0])
                b[0] += total
                b[1] += out
                b[2] += cost
        if touched:
            (subs if kind == "subagent" else session_ids).add(sid)
    if not _truthy(totals["total"]):
        return None
    return _finish("gemini", totals, by_model, by_day, len(session_ids), len(subs),
                   split if split["sub"] > 0 else None, unknown > 0)


# ── 공개 문서 ───────────────────────────────────────────────────────────
def _public_model(name):
    ok = MODEL_RE.match(name) and name != "__proto__" and not PATHLIKE_RE.search(name) \
        and not EMAIL_RE.search(name) and name.count("/") <= 2
    return name if ok else "(other)"


def _pick(o):
    return {k: _cnt(o.get(k)) if type(o) is dict else 0 for k in TOTAL_KEYS}


def _sanitize(e, at, tz):
    """collect.mjs의 sanitizeEntry: 여기 적힌 칸만 나가요."""
    models = {}
    for name, v in _js_items(e["byModel"]):
        k, cur = _public_model(name), _pick(v)
        if k in models:
            for t in TOTAL_KEYS:
                models[k][t] += cur[t]
        else:
            models[k] = cur
    if len(models) > MAX_MODELS:   # 넘으면 작은 것부터 "(other)"로 — 하나라도 넘으면 순위판이 기록 전체를 거절해요
        ranked = sorted(models.items(), key=lambda kv: -kv[1]["total"])
        keep = dict([kv for kv in ranked if kv[0] != "(other)"][:MAX_MODELS - 1])
        other = _pick(None)
        for k, v in ranked:
            if k not in keep:
                for t in TOTAL_KEYS:
                    other[t] += v[t]
        keep["(other)"] = other
        models = keep
    by_day = {}
    for d in sorted(e["byDay"], key=lambda s: s.encode("utf-16-be", "surrogatepass")):
        v = e["byDay"][d]
        if DAY_RE.match(d):
            by_day[d] = [_cnt(v[0]), _cnt(v[1]), _cnt(v[2])]
    days = list(by_day)
    split = e["split"]
    return {
        "tool": e["tool"], "generatedAt": at, "tz": tz if isinstance(tz, str) and TZ_RE.match(tz) else "UTC",
        "range": {"from": days[0] if days else None, "to": days[-1] if days else None, "activeDays": len(days)},
        "totals": _pick(e["totals"]), "messages": _cnt(e["totals"]["messages"]), "sessions": _cnt(e["sessions"]),
        "subagents": _cnt(e["subagents"]),
        "split": {"main": _cnt(split["main"]), "sub": _cnt(split["sub"])} if split is not None else None,
        "byModel": dict(_js_items(models)), "byDay": by_day, "estimated": e["estimated"] is True,
    }


def _clean(v):
    """JSON으로 나갈 모양: 정수인 double은 int로, Infinity·NaN은 null(JSON.stringify처럼)."""
    if type(v) is float:
        return None if not math.isfinite(v) else int(v) if v.is_integer() else v
    if type(v) is dict:
        return {k: _clean(x) for k, x in v.items()}
    if type(v) is list:
        return [_clean(x) for x in v]
    return v


def _iso(now):
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def default_roots():
    home = os.path.expanduser("~")
    return {"claude": os.path.join(home, ".claude", "projects"), "codex": os.path.join(home, ".codex"),
            "gemini": os.path.join(home, ".gemini")}


def build_doc(login, roots=None, now=None):
    """collect.mjs --publish가 gist에 올릴 token-meter.json과 같은 dict.

    login: GitHub 아이디(미리보기만 할 때는 None). 아이디 꼴이 아니면 ValueError.
    roots: {"claude": 경로, "codex": 경로, "gemini": 경로}. 빠진 칸·None이면 collect.mjs의 기본 폴더예요.
    now: updatedAt·generatedAt에 쓸 시각(datetime, UTC). 없으면 지금.
    도구가 하나도 없으면 entries가 비어요 — collect.mjs는 이때 올리지 않아요(로그 없음).
    """
    if login is not None and not (isinstance(login, str) and LOGIN_RE.match(login)):
        raise ValueError("GitHub 아이디 꼴이 아니에요")
    base, roots = default_roots(), roots or {}
    at, tz = _iso(now), _tz_name()
    entries = []
    for tool, fn in (("claude", _claude), ("codex", _codex), ("gemini", _gemini)):
        e = fn(_norm(roots.get(tool) or base[tool]))
        if e is not None:
            entries.append(_sanitize(e, at, tz))
    return _clean({"schema": SCHEMA, "app": "token-meter", "login": login, "updatedAt": at, "entries": entries})


def summary(doc):
    """미리보기용 요약(문서만 봐요): 총 토큰, 활동한 날 수, 처음·마지막 날, 도구별 총 토큰."""
    tools, days = {t: 0 for t in TOOLS}, set()
    entries = doc.get("entries") if isinstance(doc, dict) else None
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or e.get("tool") not in tools:
            continue
        t = e["totals"].get("total") if isinstance(e.get("totals"), dict) else None
        tools[e["tool"]] += int(round(t)) if type(t) in (int, float) and math.isfinite(t) and t > 0 else 0
        if isinstance(e.get("byDay"), dict):
            days.update(d for d in e["byDay"] if isinstance(d, str) and DAY_RE.match(d))
    ds = sorted(days)
    return {"total": sum(tools.values()), "days": len(ds), "since": ds[0] if ds else None,
            "until": ds[-1] if ds else None, "tools": tools}


# ── gist 글 ─────────────────────────────────────────────────────────────
_FOLD_RE = re.compile(r"\[\n\s*(-?[\d.eE+-]+(?:,\n\s*-?[\d.eE+-]+)*)\n\s*\]", re.ASCII)


def _dump(v, ind, lv=0):
    """JSON.stringify(v, null, ind) — 숫자 꼴까지 JS와 같아요."""
    if v is None:
        return "null"
    if v is True or v is False:
        return "true" if v else "false"
    if type(v) in (int, float):
        return _numstr(float(v)) if math.isfinite(v) else "null"
    if type(v) is str:
        return json.dumps(v, ensure_ascii=False)
    if type(v) is dict:
        if not v:
            return "{}"
        parts = [json.dumps(k, ensure_ascii=False) + (": " if ind else ":") + _dump(x, ind, lv + 1) for k, x in v.items()]
        o, c = "{", "}"
    else:
        if not v:
            return "[]"
        parts = [_dump(x, ind, lv + 1) for x in v]
        o, c = "[", "]"
    if not ind:
        return o + ",".join(parts) + c
    pad = "\n" + " " * (ind * (lv + 1))
    return o + pad + ("," + pad).join(parts) + "\n" + " " * (ind * lv) + c


def serialize(doc):
    """gist에 올릴 글 — collect.mjs의 serializePayload와 바이트까지 같아요(날짜별 [총,출력,환산]은 한 줄로 접어요).
    256KB를 넘으면 줄바꿈 없는 꼴로, 그래도 넘으면 ValueError("gist_too_large …")."""
    pretty = _FOLD_RE.sub(lambda m: "[" + re.sub(r"\s+", "", m.group(1)) + "]", _dump(doc, 1))
    compact = _dump(doc, 0)
    for s in (pretty, compact):
        if len(s.encode("utf-8")) <= MAX_GIST_BYTES:
            return s
    raise ValueError(f"gist_too_large ({math.ceil(len(compact.encode('utf-8')) / 1024)}KB)")


# ── 실행 ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="내 토큰 숫자 세기(token-meter와 같은 셈). 아무것도 올리지 않아요.")
    ap.add_argument("--json", action="store_true", help="gist에 올라갈 token-meter.json 그대로 보기")
    ap.add_argument("--login", help="문서에 넣을 GitHub 아이디(--json과 같이)")
    ap.add_argument("--dir", help="Claude Code 로그 폴더(기본 ~/.claude/projects)")
    ap.add_argument("--codex-dir", help="Codex 폴더(기본 ~/.codex)")
    ap.add_argument("--gemini-dir", help="Gemini CLI 폴더(기본 ~/.gemini)")
    a = ap.parse_args()
    roots = {"claude": a.dir, "codex": a.codex_dir, "gemini": a.gemini_dir}
    try:
        doc = build_doc(a.login, roots)
    except ValueError as e:
        sys.exit(f"--login: {e}")
    if not doc["entries"]:
        r = {k: _norm(v or default_roots()[k]) for k, v in roots.items()}
        sys.exit(f"로그를 못 찾았어요 (Claude: {r['claude']} / Codex: {r['codex']}/sessions / Gemini: {r['gemini']}/tmp).")
    if a.json:
        try:
            print(serialize(doc))
        except ValueError:
            sys.exit("올릴 내용이 gist 상한 256KB를 넘어요.")
        return
    s = summary(doc)
    print(f"토큰 {s['total']:,}개 · {s['days']}일" + (f" ({s['since']} ~ {s['until']})" if s["days"] else ""))
    print("  " + " · ".join(f"{n} {s['tools'][t]:,}" for t, n in (("claude", "Claude"), ("codex", "Codex"), ("gemini", "Gemini"))))
    print("아무것도 올리지 않았어요. 올라갈 내용을 그대로 보려면 --json")


if __name__ == "__main__":
    main()
