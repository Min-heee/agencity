"""내 사무실 → 에이전시티 도시 공개 요약(agencity.json) 만들기.

python3 -I bin/office_public.py                    # 미리보기만(아무것도 쓰거나 올리지 않음)
python3 -I bin/office_public.py --write <파일>      # 로컬 파일로 저장
python3 -I bin/office_public.py --publish           # 내 token-meter gist에 agencity.json으로 올리기(한 번 더 확인)
python3 -I bin/office_public.py --publish --yes     # 확인 없이 올리기(앱의 공개하기 버튼이 써요). 결과는 표준 출력에 JSON 한 줄

GitHub에는 이렇게 접속해요: 앱에서 GitHub 로그인(기기 코드)을 했으면 그 토큰(<설정 폴더>/github-token.json)을 쓰고
(gh가 있으면 GH_TOKEN으로 넘기고, 없으면 파이썬으로 GitHub API를 바로 불러요), 아니면 gh에 로그인된 계정을 써요.
토큰은 화면에 내지 않아요. public.json에 gist가 없으면 앱이 token-meter 숫자를 올린 gist(setup.json의 tokenMeter),
그것도 없으면 내 gist 중 token-meter.json이 든 것을 찾아 써요.
예전 이름(클로드 오피스) 때 올린 claude-office.json이 그 gist에 있으면 올릴 때 같이 지워요(도시는 agencity.json을 먼저 읽어요).

무엇을 공개할지는 public.json(이 폴더, git에 안 올라감)에 직접 적어요. 적지 않은 층은 공개하지 않아요.
{
  "login": "<내 GitHub 아이디>",
  "gist": "<token-meter gist id>",
  "profile": {"intro": "소개 한 줄", "district": "app|web|data|content|tool|game|etc"},
  "floors": {
    "<org.json의 팀 id>": {"public": "name|tour", "name": "공개용 층 이름(꼭 적기)", "summary": "공개용 소개",
                            "district": "app", "tasks": false, "board": false}
  }
}
- "name": 층 이름과 소개만. "tour": 여기에 책상(역할 이름)과 상태(일하는 중·대기 …)를 더해요.
  역할 이름은 층에서 지은 그대로 나가요(앱의 공개 확인 상자가 나갈 이름을 보여 줘요).
  "building"·"private": 층 정보는 내보내지 않아요(앱의 공개 범위 화면이 적어 둬요. 비공개로 바꾼 층도 손으로 적은 이름·소개는 지우지 않아요).
  건물(높이·등급·창문 불빛)은 이 파일과 상관없이 token-meter gist의 숫자로 서요.
- "tasks": true일 때만 책상마다 '지금 하는 일' 한 줄을, "board": true일 때만 업무판 제목을 넣어요(둘 다 기본 꺼짐).
  넣을 때도 경로·파일 이름·주소·메일·전화번호·주민번호·카드번호·키 모양 값·따옴표 속 인용은 지우거나 그 줄을 빼요.
  사람 이름은 자동으로 다 찾을 수 없으니, 켜기 전에 미리보기를 꼭 읽어 보세요.
- 대화·결재·보고서·회의록·로그 파일은 어떤 경우에도 읽지 않아요.
- 층 이름을 적지 않으면 내부 팀 이름 대신 "<n>층"으로 나가요.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ROLE_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣_·-]{0,11}\Z")   # 자리(역할) 이름: office_server.py와 같아요. 층마다 달라요
MAX_DESKS = 12
STATES = ["일하는 중", "대기", "회의 중", "막힘"]
DISTRICTS = ["app", "web", "data", "content", "tool", "game", "etc"]
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
GIST_RE = re.compile(r"^[0-9a-f]{5,64}$", re.I)
OWNER_ROWS = {"오너", "대표", "총괄", "사용자"}       # 사람(대표) 몫 업무는 공개하지 않아요
DEFAULT_API = "https://api.github.com"
API = (os.environ.get("AGENCITY_GITHUB_API") or DEFAULT_API).rstrip("/")   # 시험용 가짜 서버만 바꿔요
API = API if re.match(r"^https?://[^/\s]+", API) else DEFAULT_API
CONFIG_DIR = os.environ.get("AGENCITY_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".config", "agencity")
TOKEN_FILE = os.path.join(CONFIG_DIR, "github-token.json")   # office_server.py의 GitHub 기기 로그인이 만들어요(0600)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{10,255}$")
OUT_FILE = "agencity.json"         # gist에 올리는 공개 요약
OLD_FILE = "claude-office.json"    # 예전 이름 때 올린 요약. 올릴 때 같이 지워요
MAX_REPLY = 8 * 1024 * 1024
# 지우는 것: 바꿔 넣을 말
SCRUB = [
    (re.compile(r"eyJ[\w-]{10,}(?:\.[\w-]+){0,2}"), "(값)"),                                             # JWT
    (re.compile(r"\b(?:gh[pousr]_|github_pat_|xox[abprs]-|glpat-|hf_|npm_|sb_(?:secret|publishable)_|[spr]k_(?:live|test)_|ntn_|secret_|ya29\.|AKIA|AIza|sk-)[\w.-]{6,}", re.I), "(값)"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "(id)"),       # UUID
    (re.compile(r"local_[0-9a-f-]{8,}", re.I), "(세션)"),
    (re.compile(r"\b[0-9a-f]{24,}\b", re.I), "(id)"),                                                   # 긴 16진수(gist·노션 id 등)
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "(메일)"),
    (re.compile(r"\b[a-z][\w+.-]*://\S+", re.I), "(주소)"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "(주소)"),
    (re.compile(r"\b(?:localhost|127\.0\.0\.1)(?::\d+)?\S*", re.I), "(주소)"),
    (re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|app|so|kr|co|ai|me|xyz)\b\S*", re.I), "(주소)"),
    (re.compile(r"(?:[A-Za-z]:\\|\$HOME|~|/)[^\s]*"), "(경로)"),                                          # 절대·홈 경로
    (re.compile(r"(?:\+82[\s.-]?|\b0)1[016789][\s.-]?\d{3,4}[\s.-]?\d{4}\b"), "(전화)"),
    (re.compile(r"\b0\d{1,2}[\s.-]?\d{3,4}[\s.-]?\d{4}\b"), "(전화)"),
    (re.compile(r"\b\d{6}[\s-]?[1-4]\d{6}\b"), "(번호)"),                                              # 주민번호 꼴
    (re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b"), "(번호)"),                                             # 카드번호 꼴
]
# 이런 게 남아 있으면 그 줄은 통째로 빼요(파일·경로·인용).
DROP = re.compile(r"`|['\"“”‘’「」『』]|\b[\w.-]+/[\w./-]+|\.(?:md|json|jsonl|ts|tsx|js|mjs|py|sh|yml|yaml|env|sql|txt|html|png|mp4)\b|\((?:경로|주소|메일|값|세션|id|전화|번호)\)", re.I)


def clip(s, n):
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(" " if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") else ch for ch in s).strip()
    for rx, rep in SCRUB:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s)
    return s[:n]


def safe_line(s, n=80):
    """업무 제목·지금 하는 일: 지운 흔적이나 파일·인용이 있으면 그 줄은 내보내지 않아요."""
    s = clip(s, 200)
    if not s or DROP.search(s):
        return ""
    return s[:n]


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def board_titles(base):
    out = []
    try:
        with open(os.path.join(base, "board.md"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^-\s*\[ \]\s*(.+)$", line)            # 맨 앞 줄만(들여 쓴 하위 항목은 빼요)
                if not m:
                    continue
                parts = [p.strip() for p in m.group(1).split("|")]
                if len(parts) > 1 and parts[1] in OWNER_ROWS:
                    continue
                t = safe_line(parts[2] if len(parts) > 2 else parts[0])
                if t:
                    out.append(t)
    except OSError:
        pass
    return out[:10]


def build():
    cfg = load(os.path.join(HERE, "public.json"))
    if not isinstance(cfg, dict):
        sys.exit("public.json이 없거나 JSON이 아니에요. 이 파일 맨 위 설명대로 먼저 만들어 주세요.")
    login = str(cfg.get("login", ""))
    if not LOGIN_RE.match(login):
        sys.exit("public.json의 login이 GitHub 아이디 모양이 아니에요.")
    org = load(os.path.join(HERE, "org.json"), {})
    org = org if isinstance(org, dict) else {}
    floors_cfg = cfg.get("floors") if isinstance(cfg.get("floors"), dict) else {}
    prof = cfg.get("profile") if isinstance(cfg.get("profile"), dict) else {}
    floors, notes = [], []
    for t in org.get("teams", []) if isinstance(org.get("teams"), list) else []:
        if not isinstance(t, dict):
            continue
        c = floors_cfg.get(t.get("id"))
        if not isinstance(c, dict) or c.get("public") not in ("name", "tour") or not t.get("office"):
            continue
        try:
            num = int(t.get("floor"))
        except (TypeError, ValueError):
            notes.append(f"{t.get('id')}: 층 번호가 없어서 뺐어요")
            continue
        base = os.path.realpath(os.path.join(HERE, t["office"]))
        name = clip(c.get("name"), 40) if c.get("name") else ""
        if not name:
            name = f"{num}층"
            notes.append(f"{num}층: public.json에 name이 없어서 '{num}층'으로 내보내요(내부 팀 이름은 쓰지 않아요)")
        f = {"floor": num, "name": name, "public": c["public"], "summary": clip(c.get("summary", ""), 200)}
        if c.get("district") in DISTRICTS:
            f["district"] = c["district"]
        if c["public"] == "tour":
            team = load(os.path.join(base, "team.json"), {})
            members = team.get("members", []) if isinstance(team, dict) else []
            desks = []
            ms = [m for m in members if isinstance(m, dict) and isinstance(m.get("role"), str) and ROLE_RE.match(m["role"])
                  and m["role"] not in ("대표", "총괄")]
            ms = [m for m in ms if m["role"] == "팀장"][:1] + [m for m in ms if m["role"] != "팀장"]   # 팀장이 먼저, 나머지는 team.json 순서
            seen = set()
            for m in ms[:MAX_DESKS]:
                if m["role"] in seen:
                    continue
                seen.add(m["role"])
                st = load(os.path.join(base, "status", m["role"] + ".json"), {})
                st = st if isinstance(st, dict) else {}
                d = {"role": m["role"], "state": st.get("state") if st.get("state") in STATES else "대기"}
                if c.get("tasks") is True:
                    task = safe_line(st.get("task"))
                    if task:
                        d["task"] = task
                desks.append(d)
            f["desks"] = desks
            if c.get("board") is True:
                f["board"] = board_titles(base)
        floors.append(f)
    floors.sort(key=lambda f: f["floor"])
    doc = {"schema": 1, "app": "agencity", "login": login,
           "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
           "profile": {"intro": clip(prof.get("intro", ""), 120)}, "floors": floors}
    if prof.get("district") in DISTRICTS:
        doc["profile"]["district"] = prof["district"]
    return cfg, doc, notes


def meter_gist_saved(me):
    """앱의 ‘도시에 내 건물 세우기’가 token-meter 숫자를 올린 gist(setup.json의 tokenMeter, 같은 아이디일 때만). 없으면 ""."""
    c = load(os.path.join(HERE, "setup.json"), {})
    c = c.get("tokenMeter") if isinstance(c, dict) else None
    gist, login = (str(c.get("gist", "")), str(c.get("login", ""))) if isinstance(c, dict) else ("", "")
    return gist if GIST_RE.match(gist) and login.lower() == me.lower() else ""


def saved_token():
    """앱의 GitHub 기기 로그인으로 받은 토큰(없으면 None). 화면이나 로그에 내지 않아요."""
    t = load(TOKEN_FILE)
    tok = t.get("token") if isinstance(t, dict) else None
    return tok if isinstance(tok, str) and TOKEN_RE.match(tok) else None


class GitHub:
    """GitHub API를 부르는 길. 앱 토큰이 있으면 그걸로(gh가 있으면 GH_TOKEN으로 넘겨요), 없으면 gh에 로그인된 계정으로."""

    def __init__(self):
        self.token = saved_token()
        # gh는 진짜 GitHub에만 붙어요. 시험용 API 주소를 쓸 때는 토큰으로 바로 불러요.
        self.use_gh = bool(shutil.which("gh")) and (self.token is None or API == DEFAULT_API)
        if not self.token and not self.use_gh:
            sys.exit("GitHub에 로그인하지 않았어요. 에이전시티 앱에서 GitHub 로그인을 하거나, gh를 설치해 gh auth login 뒤 다시 해 주세요.")

    def call(self, method, path, body=None):
        """JSON 답(dict·list) 또는 실패하면 None."""
        data = None if body is None else json.dumps(body, ensure_ascii=False)
        if self.use_gh:
            env = dict(os.environ, GH_PROMPT_DISABLED="1")
            if self.token:   # 앱 토큰은 github.com 것이라 다른 호스트(GH_HOST)로 가지 않게 해요
                env["GH_TOKEN"] = self.token
                env.pop("GH_HOST", None)
            args = ["gh", "api", "-X", method, path] + (["--input", "-"] if data is not None else [])
            try:
                r = subprocess.run(args, input=data if data is not None else "", capture_output=True, text=True, env=env, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                return None
            if r.returncode != 0:
                return None
            raw = r.stdout
        else:
            req = urllib.request.Request(f"{API}/{path}", data=None if data is None else data.encode("utf-8"), method=method, headers={
                "Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json", "User-Agent": "agencity", "X-GitHub-Api-Version": "2022-11-28"})
            # 127.0.0.1(시험용)은 프록시를 거치지 않게
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if urlsplit(API).hostname in ("127.0.0.1", "localhost") \
                else urllib.request.build_opener()
            try:
                with opener.open(req, timeout=30) as resp:
                    raw = resp.read(MAX_REPLY).decode("utf-8")
            except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError):
                return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def meter_gist(self, me):
        """내 gist 중 token-meter.json이 든 것(가장 최근 것). 없으면 ""."""
        res = self.call("GET", "gists?per_page=100")
        for g in res if isinstance(res, list) else []:
            if isinstance(g, dict) and isinstance(g.get("files"), dict) and "token-meter.json" in g["files"] \
                    and str((g.get("owner") or {}).get("login", "")).lower() == me.lower() and GIST_RE.match(str(g.get("id", ""))):
                return str(g["id"])
        return ""


def publish(cfg, login, text, yes=False):
    hub = GitHub()
    me = hub.call("GET", "user")
    me = str(me.get("login", "")) if isinstance(me, dict) else ""
    if not LOGIN_RE.match(me):
        sys.exit("GitHub 계정을 확인하지 못했어요. 로그인이 끝났는지 확인해 주세요(gh를 쓰면 gh auth status).")
    gist = str(cfg.get("gist", ""))
    if not GIST_RE.match(gist):
        gist = meter_gist_saved(me) or hub.meter_gist(me)
        if not gist:
            sys.exit("아직 token-meter gist가 없어요. 앱의 설정 4단계 ‘도시에 내 건물 세우기’(또는 token-meter)로 내 숫자를 먼저 올려 주세요.")
        print(f"· public.json에 gist가 없어서 내 token-meter gist({gist})에 올려요.", file=sys.stderr)
    info = hub.call("GET", f"gists/{gist}")
    if not isinstance(info, dict):
        sys.exit(f"gist({gist})를 확인하지 못했어요. gist id와 로그인 상태를 확인해 주세요.")
    owner = str((info.get("owner") or {}).get("login", "")) if isinstance(info.get("owner"), dict) else ""
    files = info.get("files") if isinstance(info.get("files"), dict) else {}
    if owner.lower() != login.lower() or me.lower() != login.lower():
        sys.exit(f"gist 주인({owner})·GitHub 로그인({me})·public.json login({login})이 같지 않아요. 올리지 않았어요.")
    if "token-meter.json" not in files:
        sys.exit("이 gist에는 token-meter.json이 없어요. token-meter로 만든 gist만 써요.")
    if not yes:
        if not sys.stdin.isatty():
            sys.exit("확인을 받을 수 없어서 올리지 않았어요. 터미널에서 직접 실행해 주세요.")
        print("\n위 내용이 공개 gist에 올라가요. gist 수정 기록은 지울 수 없어요.", file=sys.stderr)
        if OLD_FILE in files:
            print(f"예전 이름 때 올린 {OLD_FILE}은 이번에 지워요.", file=sys.stderr)
        if input("올릴까요? 'yes'라고 입력하세요: ").strip().lower() != "yes":
            sys.exit("올리지 않았어요.")
    out = {OUT_FILE: {"content": text}}
    if OLD_FILE in files:   # 옛 파일이 남아 있으면 내린 층 정보가 옛 도시 페이지에 계속 보일 수 있어요
        out[OLD_FILE] = None
    res = hub.call("PATCH", f"gists/{gist}", {"files": out})
    if not isinstance(res, dict):
        sys.exit("올리지 못했어요. 로그인 상태와 인터넷 연결을 확인한 뒤 다시 해 주세요.")
    url = str(res.get("html_url") or "")
    if not re.match(r"^https://gist\.github\.com/[\w./-]+$", url):
        url = f"https://gist.github.com/{login}/{gist}"
    print(f"올렸어요: gist {gist}의 {OUT_FILE}", file=sys.stderr)
    if OLD_FILE in files:
        print(f"· 예전 이름 때 올린 {OLD_FILE}은 gist에서 지웠어요.", file=sys.stderr)
    return gist, url


def main():
    ap = argparse.ArgumentParser(description="에이전시티 도시 공개 요약 만들기(기본은 미리보기)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", metavar="파일", help="로컬 파일로 저장")
    g.add_argument("--publish", action="store_true", help="내 token-meter gist에 올리기(확인 후)")
    ap.add_argument("--yes", action="store_true", help="--publish를 확인 없이(앱이 써요)")
    a = ap.parse_args()
    if a.write and a.write.startswith("-"):
        sys.exit("저장할 파일 이름이 이상해요.")
    if a.yes and not a.publish:
        sys.exit("--yes는 --publish와 같이 써요.")
    cfg, doc, notes = build()
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    if not a.yes:
        print(text)
    for n in notes:
        print("· " + n, file=sys.stderr)
    print("— 공개될 층 " + str(len(doc["floors"])) + "개: " + (", ".join(f"{f['floor']}층 {f['name']}({f['public']})" for f in doc["floors"]) or "없음"), file=sys.stderr)
    if a.write:
        with open(a.write, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"저장했어요: {a.write}", file=sys.stderr)
    if a.publish:
        gist, url = publish(cfg, doc["login"], text, yes=a.yes)
        if a.yes:
            print(json.dumps({"ok": True, "gist": gist, "url": url, "floors": len(doc["floors"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
