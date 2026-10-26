#!/usr/bin/env python3
"""에이전시티 도시에 설치 없이 내 건물 세우기 — 토큰 숫자(와 고른 나라)만 내 공개 gist에 올려요.

  curl -fsSL https://raw.githubusercontent.com/Min-heee/agencity/<태그>/bin/city_join.py | python3 -I - --country KR
  python3 bin/city_join.py [--country KR|none] [--lang ko|en] [--no-open] [--dry-run]   # 저장소를 받은 폴더에서

- 이 컴퓨터의 Claude Code·Codex·Gemini CLI 로그에서 토큰 수·모델 이름·시각만 세요(대화 글은 읽지 않아요). 세는 건
  bin/token_meter.py예요. 저장소 밖에서 돌리면 같은 판(REF 태그)의 그 파일과 나라 목록(city/countries.json)만
  임시 폴더에 받아 쓰고 끝나면 지워요. 설치 폴더를 만들지 않아요.
- 올라갈 내용을 보여 주고 '올릴까요? [y/N]'을 물어요. 엔터만 누르면 아무것도 안 올라가요. curl … | python3 안에서도
  터미널(/dev/tty)에서 물어요. 물을 수 없으면(터미널이 없으면) 올리지 않아요.
- GitHub 로그인: gh에 로그인돼 있으면 그 계정을, 아니면 기기 코드(github.com/login/device에 코드를 넣어요, 권한은 gist 하나)를 써요.
  토큰은 이 프로세스의 메모리에만 두고 파일로 남기지 않아요.
- 올리는 곳: 내 공개 gist 하나(도시 명단에 있는 gist → token-meter.json이 든 내 공개 gist 중 가장 최근 것, 없으면 새로 만들어요).
  token-meter.json(숫자)을 만들거나 고쳐요. --country를 주면 같은 gist의 agencity.json에서 profile.country만 고쳐요
  (소개·동네·층 등 나머지는 그대로, 파일이 없으면 나라만 든 작은 파일을 만들어요). --country none이면 나라를 빼요
  (gist의 나라 값이 목록에 없거나 나라 목록을 못 받았어도 빼요). --country를 안 주면 나라는 건드리지 않아요.
  나라는 본인이 고른 것만, city/countries.json 목록의 두 글자 코드만 받아요(결재 20261024-U-14-1).
- 숫자도 나라도 그대로면 아무것도 올리지 않아요(gist 공개 수정 기록이 늘지 않게).
- 아직 도시 명단에 없으면 도시 참가 신청 화면을 열어 줘요(제출은 본인이 눌러요).
- 화면 글에는 token-meter 이름을 쓰지 않아요(도시 명단·참가 신청 화면·gist 파일 이름에는 보여요).
- 맥·리눅스 터미널에서 돌려요(윈도는 WSL). [y/N]을 /dev/tty로 묻기 때문이에요.
- 시험할 때만: AGENCITY_GITHUB_API·AGENCITY_GITHUB_BASE(가짜 GitHub), AGENCITY_TOKEN_METER_BASE(가짜 명단),
  AGENCITY_CITY_RAW(파일을 받을 곳), AGENCITY_GITHUB_CLIENT_ID. 주소는 이 컴퓨터(127.0.0.1·localhost)의 것만 받아요
  (토큰이 다른 곳으로 가거나 다른 곳의 파일을 받아 돌리지 않게). 가짜 GitHub을 쓸 때는 gh를 쓰지 않아요(gh는 진짜 GitHub에만 붙어요).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from urllib.parse import urlencode, urlsplit

# 받은 스크립트가 같은 판의 파일만 쓰게 태그에 고정해요. 릴리스할 때 VERSION, city.html의 JOIN_REF, docs/GUIDE.md의 명령과
# 같이 바꿔요(tests/test_city.py가 봐요).
REF = "v0.9.1"
REPO = "Min-heee/agencity"
CITY_URL = "https://min-heee.github.io/agencity/"


def _url(name, default):
    """시험용 주소: 이 컴퓨터(127.0.0.1·localhost)의 http·https만 받아요. 아니면 기본값."""
    v = (os.environ.get(name) or "").rstrip("/")
    if v:
        u = urlsplit(v)
        if u.scheme in ("http", "https") and u.hostname in ("127.0.0.1", "localhost"):
            return v
    return default.rstrip("/")


API = _url("AGENCITY_GITHUB_API", "https://api.github.com")
BASE = _url("AGENCITY_GITHUB_BASE", "https://github.com")
TM_BASE = _url("AGENCITY_TOKEN_METER_BASE", "https://min-heee.github.io/token-meter")
RAW = _url("AGENCITY_CITY_RAW", f"https://raw.githubusercontent.com/{REPO}/{REF}")
REAL_GITHUB = API == "https://api.github.com"
METER_FILE = "token-meter.json"
OFFICE_FILE = "agencity.json"
MAX_READ = 4 * 1024 * 1024
GIST_RE = re.compile(r"^[0-9a-f]{5,64}\Z", re.I)
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
COUNTRY_RE = re.compile(r"^[A-Z]{2}\Z")

# 화면 글: 한국어(LANG이 ko…일 때)와 English. 사람에게 보이는 글에는 token-meter 이름을 쓰지 않아요.
MSG = {
    "ko": {
        "py": "파이썬 3.9 이상이 필요해요.",
        "windows": "윈도에서는 올리기 전에 물어볼 수 없어서 아무것도 올리지 않았어요. WSL(리눅스) 터미널에서 실행해 주세요.",
        "fetch": "도움 파일을 받는 중이에요…",
        "fetch_fail": "도움 파일({0})을 받지 못했어요. 인터넷 연결을 확인하고 다시 실행해 주세요.",
        "bad_country": "나라는 두 글자 나라 코드(예: KR, JP, US)나 none(빼기)으로 적어요: {0}",
        "no_countries": "나라 목록을 읽지 못해서 나라는 고를 수 없어요. --country 없이 다시 실행해 주세요.",
        "login_gh": "GitHub: gh에 로그인된 @{0} 계정으로 올려요.",
        "login_need": "GitHub에 로그인해야 올릴 수 있어요. 기기 코드로 로그인해요(권한은 gist 하나).",
        "login_code": "  1) 이 주소를 열어요: {0}\n  2) 이 코드를 넣고 승인해요: {1}",
        "login_wait": "  승인을 기다리는 중이에요…(그만두려면 Ctrl-C)",
        "login_fail": "GitHub 로그인을 하지 못했어요({0}). 다시 실행하거나, gh를 설치해 gh auth login 뒤 실행해 주세요.",
        "login_no_app": "기기 코드 로그인을 쓸 수 없어요. gh를 설치해 gh auth login 뒤 다시 실행해 주세요.",
        "login_ok": "GitHub: @{0} 계정으로 로그인했어요.",
        "user_fail": "GitHub 아이디를 확인하지 못했어요. 잠시 뒤 다시 해 주세요.",
        "count": "이 컴퓨터의 로그에서 토큰 숫자를 세는 중이에요(대화 글은 읽지 않아요)…",
        "no_logs": "Claude Code·Codex·Gemini CLI 로그를 찾지 못했어요. 그 도구를 쓴 컴퓨터에서 실행해 주세요.",
        "too_big": "올릴 숫자가 gist 상한 256KB를 넘어요.",
        "gists_fail": "내 gist를 읽지 못했어요({0}). 잠시 뒤 다시 해 주세요.",
        "office_bad": "gist에 있는 agencity.json을 읽지 못해서, 그 안의 다른 내용을 지키려고 올리지 않았어요.",
        "where_new": "올라갈 곳: 내 공개 gist(새로 만들어요)",
        "where": "올라갈 곳: 내 공개 gist {0}",
        "nums": "숫자: 모두 {0} 토큰 · {1}{2} · {3}",
        "days": "활동한 날 {0}일",
        "day1": "활동한 날 1일",
        "tz": "시간대: {0} (나라와 따로, 늘 공개돼요)",
        "c_set": "나라: {0}(으)로 올려요",
        "c_drop": "나라: 빼요",
        "c_dry": "나라: {0}(올릴 때 이 값으로)",
        "c_dry_drop": "나라: 올릴 때 빼요",
        "c_keep": "나라: 그대로 둬요(지금: {0})",
        "c_none": "고르지 않음",
        "c_odd": "목록에 없는 값",
        "same_meter": "숫자는 지난번에 올린 것과 같아요.",
        "what": "올라가는 건 숫자(토큰·횟수·환산액)·모델 이름·날짜·시간대와 고른 나라뿐이에요. 대화·경로·프로젝트 이름은 올라가지 않아요.",
        "public": "gist는 누구나 볼 수 있고, 지난 수정 기록까지 공개로 남아요.",
        "ask": "올릴까요? [y/N] (v = 올라갈 글 전부 보기) ",
        "no_tty": "확인을 받을 터미널이 없어서 올리지 않았어요. 터미널에서 직접 실행해 주세요.",
        "declined": "올리지 않았어요.",
        "nothing": "숫자도 나라도 그대로라서 아무것도 올리지 않았어요.",
        "dry": "--dry-run이라 아무것도 올리지 않았어요.",
        "up_fail": "올리지 못했어요({0}). 로그인과 인터넷 연결을 확인한 뒤 다시 해 주세요.",
        "done": "올렸어요: {0}",
        "member": "도시 명단에 있어요. 몇 분 뒤 도시에 반영돼요: {0}",
        "member_old": "예전 gist로 도시에 참가돼 있어요. 다시 신청하면 이 gist로 바뀌어요.",
        "join": "도시 참가 신청: {0}\n  GitHub에서 Submit new issue를 누르면 몇 분 안에 명단에 들어가요(신청 화면에는 도시 명단을 맡은 저장소 이름이 보여요).",
        "join_open": "도시 참가 신청 화면을 브라우저로 열었어요.",
        "members_unknown": "도시 명단을 확인하지 못했어요. 아직 참가하지 않았다면 이 주소에서 신청해요: {0}",
        "again": "숫자를 새로 올리려면 같은 줄을 다시 실행해요. 저절로 올라가지는 않아요.",
        "ssl": "GitHub 인증서를 확인하지 못했어요. python.org에서 받은 파이썬이면 'Install Certificates.command'를 한 번 실행해 주세요.",
        "net": "GitHub에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.",
        "bye": "그만뒀어요. 아무것도 올리지 않았어요.",
    },
    "en": {
        "py": "Python 3.9 or newer is required.",
        "windows": "On Windows it can't ask you before posting, so nothing was posted. Run it in a WSL (Linux) terminal.",
        "fetch": "Downloading helper files…",
        "fetch_fail": "Couldn't download a helper file ({0}). Check your connection and run it again.",
        "bad_country": "Use a two-letter country code (e.g. KR, JP, US) or none to remove it: {0}",
        "no_countries": "Couldn't read the country list, so you can't pick a country. Run it again without --country.",
        "login_gh": "GitHub: posting as @{0} (your gh login).",
        "login_need": "You need to sign in to GitHub to post. Signing in with a device code (gist permission only).",
        "login_code": "  1) Open: {0}\n  2) Enter this code and approve: {1}",
        "login_wait": "  Waiting for approval… (Ctrl-C to stop)",
        "login_fail": "Couldn't sign in to GitHub ({0}). Run it again, or install gh, run gh auth login, then try again.",
        "login_no_app": "Device-code sign-in isn't available. Install gh, run gh auth login, then try again.",
        "login_ok": "GitHub: signed in as @{0}.",
        "user_fail": "Couldn't confirm your GitHub username. Try again in a bit.",
        "count": "Counting tokens from this computer's logs (chat text is not read)…",
        "no_logs": "No Claude Code, Codex or Gemini CLI logs found. Run this on the computer where you use them.",
        "too_big": "Your numbers are over the 256KB gist limit.",
        "gists_fail": "Couldn't read your gists ({0}). Try again in a bit.",
        "office_bad": "Couldn't read the agencity.json in your gist, so nothing was posted (to keep what's in it).",
        "where_new": "Posting to: a new public gist of yours",
        "where": "Posting to: your public gist {0}",
        "nums": "Numbers: {0} tokens · {1}{2} · {3}",
        "days": "{0} active days",
        "day1": "1 active day",
        "tz": "Time zone: {0} (published separately from your country)",
        "c_set": "Country: {0}",
        "c_drop": "Country: removed",
        "c_dry": "Country: {0} (when posted)",
        "c_dry_drop": "Country: removed when posted",
        "c_keep": "Country: unchanged (now: {0})",
        "c_none": "none",
        "c_odd": "a value not on the list",
        "same_meter": "Your numbers are the same as last time.",
        "what": "Only token counts, daily totals, model names, dates, your time zone and the country you pick are posted. No chats, paths or project names.",
        "public": "Gists are public, and their revision history stays public too.",
        "ask": "Upload? [y/N] (v = show everything that will be posted) ",
        "no_tty": "There's no terminal to ask you on, so nothing was posted. Run it in a terminal.",
        "declined": "Nothing was posted.",
        "nothing": "Your numbers and country are unchanged, so nothing was posted.",
        "dry": "--dry-run: nothing was posted.",
        "up_fail": "Couldn't post ({0}). Check your sign-in and connection, then try again.",
        "done": "Posted: {0}",
        "member": "You're on the city's member list. The city updates in a few minutes: {0}",
        "member_old": "You joined the city with an older gist. Join again to switch to this one.",
        "join": "Join the city: {0}\n  Click Submit new issue on GitHub and you'll be on the list in a few minutes (the request page shows the name of the repo that runs the member list).",
        "join_open": "Opened the Join the city page in your browser.",
        "members_unknown": "Couldn't check the city's member list. If you haven't joined yet, request it here: {0}",
        "again": "To post new numbers, run the same line again. Nothing uploads on its own.",
        "ssl": "Couldn't verify GitHub's certificate. If you installed Python from python.org, run 'Install Certificates.command' once.",
        "net": "Couldn't reach GitHub. Check your connection.",
        "bye": "Stopped. Nothing was posted.",
    },
}
L = MSG["ko"]


def say(key, *a):
    print(L[key].format(*a), flush=True)


def fail(key, *a):
    print(L[key].format(*a), file=sys.stderr, flush=True)
    sys.exit(1)


class NetError(Exception):
    pass


def http(method, url, body=None, form=None, token=None, limit=MAX_READ):
    """(상태 코드, JSON dict·list 또는 None). 토큰은 Authorization 머리글로만 보내요. 127.0.0.1(시험)은 프록시를 거치지 않아요."""
    headers = {"Accept": "application/json", "User-Agent": "agencity-city-join"}
    data = None
    if form is not None:
        data = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers.update({"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"})
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    local = urlsplit(url).hostname in ("127.0.0.1", "localhost")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=30) as r:
            code, raw = r.status, r.read(limit + 1)
    except urllib.error.HTTPError as e:
        code, raw = e.code, (e.read(limit + 1) if e.fp else b"")
    except (urllib.error.URLError, OSError, ValueError) as e:
        if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):
            fail("ssl")
        raise NetError(str(e)) from None
    if len(raw) > limit:
        return code, None
    try:
        return code, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return code, None


def get_text(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": "agencity-city-join", "Cache-Control": "no-cache"})
    local = urlsplit(url).hostname in ("127.0.0.1", "localhost")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=30) as r:
            raw = r.read(limit + 1)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):
            fail("ssl")
        return None
    except (OSError, ValueError):
        return None
    return None if len(raw) > limit else raw.decode("utf-8", "replace")


# ── 도움 파일: 저장소 안이면 옆 파일, 아니면 같은 판의 파일을 임시 폴더에 받아요 ──────────
def helpers(tmp):
    """(token_meter 모듈, 나라 코드 집합, 기기 로그인 client id)."""
    here = os.path.dirname(os.path.realpath(__file__)) if "__file__" in globals() and os.path.isfile(__file__) else ""
    tm_path = os.path.join(here, "token_meter.py") if here else ""
    if tm_path and os.path.isfile(tm_path):
        root = os.path.dirname(here)
        countries = _read(os.path.join(root, "city", "countries.json"))
        cid = _read(os.path.join(root, "github_client_id"))
    else:
        say("fetch")
        files = {}
        for name, path, limit in (("token_meter.py", "bin/token_meter.py", 1024 * 1024), ("countries.json", "city/countries.json", 16 * 1024),
                                  ("github_client_id", "github_client_id", 1024)):
            txt = get_text(f"{RAW}/{path}", limit)
            if txt is None and name == "token_meter.py":
                fail("fetch_fail", path)
            files[name] = txt
        tm_path = os.path.join(tmp, "token_meter.py")
        with open(tm_path, "w", encoding="utf-8") as f:
            f.write(files["token_meter.py"])
        countries, cid = files["countries.json"], files["github_client_id"]
    spec = importlib.util.spec_from_file_location("agencity_token_meter", tm_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 — 받은 파일이 깨졌으면 알려요
        fail("fetch_fail", "bin/token_meter.py")
    if not all(callable(getattr(mod, k, None)) for k in ("build_doc", "serialize", "summary", "JOIN_URL")):
        fail("fetch_fail", "bin/token_meter.py")
    try:
        c = json.loads(countries) if countries else []
    except ValueError:
        c = []
    codes = {x for x in c if isinstance(x, str) and COUNTRY_RE.match(x)} if isinstance(c, list) else set()
    cid = (os.environ.get("AGENCITY_GITHUB_CLIENT_ID") or "").strip() or ((cid or "").strip().splitlines() or [""])[0].strip()
    return mod, codes, cid if re.match(r"^[A-Za-z0-9._-]{4,100}\Z", cid) else ""


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# ── GitHub: gh 로그인이 있으면 gh로, 아니면 기기 코드로 받은 토큰(메모리에만)으로 ──────────
class Hub:
    def __init__(self, cid, no_open):
        self.token = None
        self.gh = REAL_GITHUB and bool(shutil.which("gh")) and self._gh_ok()
        if self.gh:
            return
        if not cid:
            fail("login_no_app")
        say("login_need")
        self.token = device_login(cid, no_open)

    @staticmethod
    def _gh_ok():
        try:
            r = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"], stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0

    def call(self, method, path, body=None):
        """(상태 코드, JSON). gh의 오류 글·토큰은 화면에 내지 않아요."""
        if not self.gh:
            return http(method, f"{API}/{path}", body=body, token=self.token)
        env = {k: v for k, v in os.environ.items() if k not in ("GH_DEBUG", "DEBUG", "GH_HOST")}
        env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
        args = ["gh", "api", "--hostname", "github.com", "-X", method, path] + (["--input", "-"] if body is not None else [])
        try:
            r = subprocess.run(args, input=json.dumps(body, ensure_ascii=False) if body is not None else "", capture_output=True,
                               text=True, timeout=60, env=env)
        except (OSError, subprocess.TimeoutExpired):
            raise NetError("gh") from None
        if r.returncode == 0:
            try:
                return (201 if method == "POST" else 200), json.loads(r.stdout or "null")
            except ValueError:
                return 200, None
        m = re.search(r"\(HTTP (\d{3})\)", r.stderr or "")
        if m:
            return int(m.group(1)), None
        raise NetError("gh")


def device_login(cid, no_open):
    code, res = http("POST", f"{BASE}/login/device/code", form={"client_id": cid, "scope": "gist"})
    res = res if isinstance(res, dict) else {}
    dc, uc = str(res.get("device_code") or ""), str(res.get("user_code") or "")
    if code != 200 or not re.match(r"^[A-Za-z0-9._-]{8,200}\Z", dc) or not re.match(r"^[A-Z0-9-]{4,20}\Z", uc):
        fail("login_fail", res.get("error") or code)
    uri = str(res.get("verification_uri") or "")
    uri = uri if uri.startswith(BASE + "/") and len(uri) < 200 else BASE + "/login/device"
    interval = max(1, min(60, int(res.get("interval") or 5))) if str(res.get("interval") or "5").isdigit() else 5
    until = time.time() + max(60, min(1800, int(res.get("expires_in") or 900) if str(res.get("expires_in") or "900").isdigit() else 900))
    say("login_code", uri, uc)
    if not no_open:
        try:
            webbrowser.open(uri)
        except Exception:  # noqa: BLE001 — 못 열면 주소를 직접 열어요
            pass
    say("login_wait")
    while time.time() < until:
        time.sleep(interval)
        code, res = http("POST", f"{BASE}/login/oauth/access_token",
                         form={"client_id": cid, "device_code": dc, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        res = res if isinstance(res, dict) else {}
        tok, err = res.get("access_token"), str(res.get("error") or "")
        if isinstance(tok, str) and re.match(r"^[A-Za-z0-9_.-]{10,255}\Z", tok):
            return tok
        if err == "slow_down":
            interval += 5
        elif err != "authorization_pending":
            fail("login_fail", err or code)
    fail("login_fail", "expired_token")


# ── 숫자·gist ────────────────────────────────────────────────────────────
def plain(doc):
    """시각(updatedAt, 기록마다 generatedAt)을 뺀 비교용 글: 숫자가 바뀌었는지 볼 때(앱의 tm_plain과 같아요)."""
    if not isinstance(doc, dict):
        return None
    d = dict(doc, updatedAt=None)
    if isinstance(d.get("entries"), list):
        d["entries"] = [dict(e, generatedAt=None) if isinstance(e, dict) else e for e in d["entries"]]
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def owner_is(g, me):
    o = g.get("owner") if isinstance(g, dict) else None
    return isinstance(o, dict) and str(o.get("login") or "").lower() == me.lower()


def members():
    """도시 명단 {아이디 소문자: gist id 소문자}. 못 읽으면 None."""
    txt = get_text(f"{TM_BASE}/members.json?t={int(time.time() * 1000)}", MAX_READ)
    try:
        doc = json.loads(txt) if txt else None
    except ValueError:
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("members"), list):
        return None
    return {str(m["login"]).lower(): str(m["gist"]).lower() for m in doc["members"][:5000]
            if isinstance(m, dict) and LOGIN_RE.match(str(m.get("login") or "")) and GIST_RE.match(str(m.get("gist") or ""))}


def my_gist(hub, me, listed):
    """올릴 내 gist: {id, url, files} 또는 None(새로 만들어요). 명단에 있는 내 gist가 먼저, 그다음 token-meter.json이 든 내 공개 gist 중 가장 최근 것."""
    cands = [listed] if listed else []
    found = []
    for page in range(1, 11):
        code, lst = hub.call("GET", f"gists?per_page=100&page={page}")
        if code != 200 or not isinstance(lst, list):
            fail("gists_fail", code)
        for g in lst:
            if isinstance(g, dict) and GIST_RE.match(str(g.get("id") or "")) and g.get("public") is True and owner_is(g, me) \
                    and isinstance(g.get("files"), dict) and METER_FILE in g["files"]:
                found.append((str(g.get("updated_at") or ""), str(g["id"])))
        if len(lst) < 100:
            break
    found.sort(reverse=True)
    for gid in cands + [x[1] for x in found]:
        code, g = hub.call("GET", f"gists/{gid}")
        if code == 200 and isinstance(g, dict) and owner_is(g, me) and g.get("public") is True and isinstance(g.get("files"), dict) \
                and METER_FILE in g["files"]:
            url = str(g.get("html_url") or "")
            return {"id": gid, "url": url if re.match(r"^https://gist\.github\.com/[\w./-]+\Z", url) else f"https://gist.github.com/{me}/{gid}",
                    "files": g["files"]}
        if code not in (200, 404):
            fail("gists_fail", code)
    return None


def file_doc(g, name):
    """gist 파일의 JSON(dict). 없으면 None, 있는데 못 읽으면 False."""
    f = (g or {}).get("files", {}).get(name)
    if f is None:
        return None
    raw = f.get("content") if isinstance(f, dict) and f.get("truncated") is not True else None
    try:
        doc = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        doc = None
    return doc if isinstance(doc, dict) else False


def ask_tty(texts):
    """터미널에서 [y/N]을 물어요(curl | python3 안에서도). 'v'면 올라갈 글을 다 보여 주고 다시 물어요."""
    try:   # 터미널은 앞뒤로 움직일 수 없어서(r+ 글 모드가 안 돼요) 읽기·쓰기를 따로 열어요
        tin, tout = open("/dev/tty", "r", encoding="utf-8", errors="replace"), open("/dev/tty", "w", encoding="utf-8")
    except OSError:
        fail("no_tty")
    with tin, tout:
        while True:
            tout.write(L["ask"])
            tout.flush()
            a = tin.readline()
            if not a:
                return False
            a = a.strip().lower()
            if a == "v":
                for name, text in texts:
                    tout.write(f"\n── {name} ──\n{text}\n")
                tout.write("\n")
                continue
            return a in ("y", "yes", "네", "예", "ㅇ")


def main():
    global L
    ap = argparse.ArgumentParser(description="에이전시티 도시에 설치 없이 내 건물 세우기(토큰 숫자와 고른 나라만 올려요, 올리기 전에 물어봐요)")
    ap.add_argument("--country", help="두 글자 나라 코드(예: KR). none이면 나라를 빼요. 안 주면 나라는 그대로예요")
    ap.add_argument("--lang", choices=("ko", "en"), help="화면 글 언어(기본은 LANG 환경 변수)")
    ap.add_argument("--no-open", action="store_true", help="브라우저를 열지 않아요(주소만 보여 줘요)")
    ap.add_argument("--dry-run", action="store_true", help="숫자만 세어 보여 주고 아무것도 올리지 않아요(로그인도 안 해요)")
    a = ap.parse_args()
    lang = a.lang or ("ko" if re.match(r"^ko", os.environ.get("LC_ALL") or os.environ.get("LANG") or "") else "en")
    L = MSG[lang]
    if sys.version_info < (3, 9):
        fail("py")
    if os.name == "nt" and not a.dry_run:   # /dev/tty가 없어서 [y/N]을 물을 수 없어요. 로그인 전에 알려요
        fail("windows")
    want = None   # None: 나라는 그대로 · "": 빼기 · "KR": 그 나라로
    with tempfile.TemporaryDirectory(prefix="agencity-city-") as tmp:
        tm, codes, cid = helpers(tmp)
        if a.country is not None:
            v = a.country.strip().upper()
            if v == "NONE":
                want = ""
            elif not codes:
                fail("no_countries")
            elif COUNTRY_RE.match(v) and v in codes:
                want = v
            else:
                fail("bad_country", a.country[:20])
        try:
            if a.dry_run:
                say("count")
                doc = tm.build_doc(None)
                if not doc.get("entries"):
                    fail("no_logs")
                show_numbers(tm, doc)
                if want is not None:   # 로그인하지 않아서 지금 gist의 나라는 몰라요. 준 값만 보여 줘요
                    say("c_dry", want) if want else say("c_dry_drop")
                say("dry")
                return
            hub = Hub(cid, a.no_open)
            code, u = hub.call("GET", "user")
            me = str(u.get("login") or "") if isinstance(u, dict) else ""
            if code != 200 or not LOGIN_RE.match(me):
                fail("user_fail")
            say("login_gh" if hub.gh else "login_ok", me)
            say("count")
            doc = tm.build_doc(me)
            if not doc.get("entries"):
                fail("no_logs")
            try:
                text = tm.serialize(doc)
            except ValueError:
                fail("too_big")
            lst = members()
            listed = (lst or {}).get(me.lower())
            g = my_gist(hub, me, listed)
            old_meter = file_doc(g, METER_FILE) if g else None
            meter_changed = not (old_meter and plain(old_meter) == plain(json.loads(text)))
            # 나라: agencity.json에서 profile.country만 바꿔요. 다른 칸(소개·동네·층)은 그대로예요.
            office = file_doc(g, OFFICE_FILE) if g else None
            if office is False and want is not None:
                fail("office_bad")
            # 지금 값은 목록에 있든 없든 gist에 적힌 그대로 봐요. 빼기는 나라 칸이 있으면 빼요
            # (목록에 없는 값이거나 나라 목록을 못 받았어도, 공개된 나라가 남지 않게).
            now_c, has_c = None, False
            if isinstance(office, dict) and isinstance(office.get("profile"), dict):
                has_c = "country" in office["profile"]
                now_c = office["profile"].get("country")
            office_text = None
            if want is not None and (want != now_c if want else has_c):
                if isinstance(office, dict) and office.get("app") == "agencity" and str(office.get("login") or "").lower() == me.lower():
                    new = dict(office)
                    prof = dict(office["profile"]) if isinstance(office.get("profile"), dict) else {}
                else:   # 없거나 다른 꼴이면 나라만 든 작은 요약을 새로 써요(층은 없어요)
                    new = {"schema": 1, "app": "agencity", "login": me, "updatedAt": doc.get("updatedAt"), "profile": {}, "floors": []}
                    prof = {}
                if want:
                    prof["country"] = want
                else:
                    prof.pop("country", None)
                new["profile"] = prof
                if want or isinstance(office, dict):   # 빼기인데 파일이 없으면 만들 필요가 없어요
                    office_text = json.dumps(new, ensure_ascii=False, indent=1)
            if not meter_changed and office_text is None:
                say("nothing")
                after(tm, g["id"] if g else None, me, lst, a.no_open)
                return
            # 올라갈 것 보여 주기
            say("where", g["url"]) if g else say("where_new")
            show_numbers(tm, doc)
            if not meter_changed:
                say("same_meter")
            if want is None or office_text is None:
                say("c_keep", shown_country(now_c, has_c))
            else:
                say("c_set", want) if want else say("c_drop")
            say("what")
            say("public")
            texts = ([(METER_FILE, text)] if meter_changed else []) + ([(OFFICE_FILE, office_text)] if office_text else [])
            if not ask_tty(texts):
                say("declined")
                return
            files = {name: {"content": t} for name, t in texts}
            desc = getattr(tm, "GIST_DESCRIPTION", "AI coding agent token usage (numbers only)")
            if g:
                code, res = hub.call("PATCH", f"gists/{g['id']}", {"description": desc, "files": files})
                gid, url = g["id"], g["url"]
            else:
                code, res = hub.call("POST", "gists", {"description": desc, "public": True, "files": files})
                gid = str(res.get("id") or "") if isinstance(res, dict) else ""
                url = str(res.get("html_url") or "") if isinstance(res, dict) else ""
                url = url if re.match(r"^https://gist\.github\.com/[\w./-]+\Z", url) else f"https://gist.github.com/{me}/{gid}"
            if code not in (200, 201) or not GIST_RE.match(gid):
                fail("up_fail", code)
            say("done", url)
            after(tm, gid, me, lst, a.no_open)
        except NetError:
            fail("net")
        except KeyboardInterrupt:
            print()
            fail("bye")


def show_numbers(tm, doc):
    s = tm.summary(doc)
    tools = " · ".join(f"{n} {s['tools'].get(k, 0):,}" for k, n in (("claude", "Claude"), ("codex", "Codex"), ("gemini", "Gemini")) if s["tools"].get(k))
    span = f" ({s['since']} ~ {s['until']})" if s.get("since") else ""
    say("nums", f"{s['total']:,}", L["day1"] if s["days"] == 1 else L["days"].format(s["days"]), span, tools)
    tz = next((e.get("tz") for e in doc.get("entries", []) if isinstance(e, dict) and isinstance(e.get("tz"), str)), "")
    if tz:
        say("tz", tz)


def shown_country(v, present):
    """화면에 보일 지금 나라: gist에 적힌 값이라 짧은 글자·숫자만 그대로 보여 줘요(터미널에 이상한 글자가 나가지 않게)."""
    if isinstance(v, str) and re.match(r"^[A-Za-z0-9-]{1,12}\Z", v):
        return v
    return L["c_odd"] if present else L["c_none"]


def after(tm, gid, me, lst, no_open):
    """도시 명단에 있는지 보고, 없으면 참가 신청 화면을 열어요(제출은 본인이)."""
    if not gid:
        return
    join = tm.JOIN_URL(gid)
    if lst is None:
        say("members_unknown", join)
    elif lst.get(me.lower()) == gid.lower():
        say("member", f"{CITY_URL}?who={me}")
    else:
        if lst.get(me.lower()):
            say("member_old")
        say("join", join)
        if not no_open:
            try:
                if webbrowser.open(join):
                    say("join_open")
            except Exception:  # noqa: BLE001 — 못 열면 주소를 직접 열어요
                pass
    say("again")


if __name__ == "__main__":
    main()
