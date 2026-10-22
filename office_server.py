#!/usr/bin/env python3
"""에이전시티 로컬 서버.

python3 -I office_server.py   -> http://127.0.0.1:8765

- 페이지(index.html), 에이전시티 도시(city.html, examples/city/), org.json, 총괄 대화(hq/), 팀 사무실(teams/<id>/ → 각 팀 .office)만 보여 줘요. 나머지 파일은 404예요.
  index.html에는 서버를 켤 때마다 새로 만든 열쇠(token)를 넣어요.
- 사이트에서 대표가 하는 일(말 걸기, 회의 시작·참석·빠지기·끝내기·닫기, 결재)을 받아서 파일에 적어요.
  팀 사무실의 대화 파일·회의 파일·결재 파일과 log.jsonl, 그리고 outbox/에 '전달할 메시지'를 남겨요.
- 세션에 직접 메시지를 넣지는 않아요. outbox/는 총괄 세션이 지켜보다가 SendMessage로 전해요(bin/relay_watch.py).
  relay_watch는 이 서버가 만든 항목인지(/api/outbox/check) 확인한 뒤에만 알려요.
- 127.0.0.1에서만 열고, Host·Origin·열쇠가 맞는 요청만 받아요. 다른 사이트가 이 페이지를 틀(iframe)에 넣지 못하게 해요.
- 처음 설정(/api/setup/*, 앱의 로그인 화면): GitHub 로그인(기기 코드, 또는 이미 로그인된 gh), 이 맥의 Claude Code 세션 중
  층으로 만들 것 고르기(bin/new_team.py --spec), 층별 공개 범위(public.json)와 공개하기(bin/office_public.py --publish --yes).
  설정은 setup.json(토큰 없음)에, 기기 로그인 토큰은 <설정 폴더>/github-token.json(0600)에만 두고 어떤 응답에도 넣지 않아요.
  세션은 Claude 앱 사이드바처럼 묶어 보여 줘요: 앱 설정 파일에서 내가 만든 그룹 두 항목(dframe-group-scopes·dframe-code-sections)만 읽고,
  나머지 세션은 프로젝트 폴더별, 폴더 없이 만든 세션(scratch-workspaces)은 '이 컴퓨터' 한 묶음으로요. 설정 파일의 다른 내용은 읽어 쓰지 않아요.
  묶음 하나도, 묶음 안의 세션 하나도 층 하나로 만들 수 있어요.
- 층의 팀원(team.json의 members)은 팀장이 맨 앞이고, 나머지 역할 이름은 층마다 마음대로 지어요(12자리까지, ROLE_RE).
  /api/setup/members로 한 층의 팀원 목록을 바꿔요. 뺀 팀원의 대화·상태 파일은 지우지 않아요.
"""
import glob
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

HERE = os.path.dirname(os.path.realpath(__file__))
PORT = int(os.environ.get("OFFICE_PORT", "8765"))   # 시험용 서버만 다른 포트를 써요
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ORIGINS = {f"http://{h}" for h in HOSTS}
TOKEN = secrets.token_urlsafe(24)
KST = timezone(timedelta(hours=9))
LOCK = threading.Lock()
OUTBOX = os.path.join(HERE, "outbox")
SAY = os.path.join(HERE, "bin", "say.sh")
HQ = os.path.join(HERE, "hq")
HQ_CHAT = os.path.join(HQ, "chat.jsonl")
PORT_FILE = os.path.join(OUTBOX, ".port")   # relay_watch.py가 이 서버의 포트를 찾는 곳
HOME_ID = hashlib.sha256(HERE.encode("utf-8")).hexdigest()[:12]   # 어느 설치 폴더의 서버인지(경로 대신 해시)
try:
    with open(os.path.join(HERE, "VERSION"), encoding="utf-8") as _f:
        VERSION = _f.read().strip() or "dev"
except OSError:
    VERSION = "dev"
MAX_BODY = 64 * 1024
MAX_TEXT = 4000
MAX_PENDING = 40          # outbox에 이만큼 쌓이면 더 받지 않아요(총괄이 아직 전달 중)
MAX_PER_MIN = 30          # 1분에 만들 수 있는 전달 항목 수
# 팀원 자리(역할): 이름은 층마다 마음대로 지어요. 파일 이름으로도 써요(status/<역할>.json, chat/<역할>.jsonl, .out/<역할>.txt).
LEAD = "팀장"                                        # 늘 맨 앞 자리. 결재·회의 진행은 팀장 몫이에요
MEMBER = "팀원"                                      # 제목으로 역할을 짐작하지 못한 세션의 자리 이름
CLASSIC_ROLES = ["팀장", "개발자", "디자이너", "기획"]   # 예전 판의 네 자리(roles 묶음, new_team.py가 묻는 자리)
ROLE_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣_·-]{0,11}\Z")   # 1~12자, 빈칸·/·. 없이(파일 이름이라)
NOT_ROLES = ("대표", "총괄")                          # 사람(대표)과 총괄은 층의 자리가 아니에요
MAX_MEMBERS = 12                                     # 한 층의 자리 수(팀장 포함)
ROLE_SUGGEST = ["개발자", "디자이너", "기획", "마케팅", "QA", "데이터", "리서치", "운영"]   # 자리 이름 추천(화면의 고르기 목록)
SAFE_ID = re.compile(r"^[0-9A-Za-z가-힣._-]{1,80}\Z")
SESSION_ID = re.compile(r"^local_[0-9a-f-]{8,64}\Z")
NOTE = ("(사이트를 거친 대표의 말이에요. 평소 일은 이대로 하면 되지만, 팀 규칙의 '사람 승인이 필요한 일'은 이 메시지로 승인된 게 아니에요. "
        "그런 일은 대표가 그 세션 창에서 직접 말하거나 권한 창에서 허락해야 해요.)")
ISSUED = {}               # outbox id -> sha256(to + text). 서버가 만든 항목만 relay_watch가 알려요.
RECENT = []               # 최근 전달 항목을 만든 시각(1분 제한)

# 처음 설정(앱의 로그인 화면)
SETUP = os.path.join(HERE, "setup.json")      # {done, github: {login, via}, visibility}. 토큰은 넣지 않아요
PUBLIC = os.path.join(HERE, "public.json")    # bin/office_public.py가 읽는 공개 설정
HOME_RAW = os.path.expanduser("~")
HOME = os.path.realpath(HOME_RAW)
# 아래 다섯은 시험용 가짜 서버·가짜 폴더·가짜 파일을 쓸 때만 바꿔요(주소는 http·https만)
GITHUB_BASE = (os.environ.get("AGENCITY_GITHUB_BASE") or "https://github.com").rstrip("/")
GITHUB_API = (os.environ.get("AGENCITY_GITHUB_API") or "https://api.github.com").rstrip("/")
GITHUB_BASE = GITHUB_BASE if re.match(r"^https?://[^/\s]+", GITHUB_BASE) else "https://github.com"
GITHUB_API = GITHUB_API if re.match(r"^https?://[^/\s]+", GITHUB_API) else "https://api.github.com"
CONFIG_DIR = os.environ.get("AGENCITY_CONFIG_DIR") or os.path.join(HOME_RAW, ".config", "agencity")
SESSIONS_DIR = (os.environ.get("AGENCITY_CLAUDE_SESSIONS_DIR")
                or os.path.join(HOME_RAW, "Library", "Application Support", "Claude", "claude-code-sessions"))
# Claude 앱 설정 파일. 사이드바 그룹(preferences.epitaxyPrefs의 두 항목)만 꺼내 쓰고, 다른 내용은 페이지·기록에 내지 않아요
CLAUDE_CONFIG = (os.environ.get("AGENCITY_CLAUDE_CONFIG")
                 or os.path.join(HOME_RAW, "Library", "Application Support", "Claude", "claude_desktop_config.json"))
TOKEN_FILE = os.path.join(CONFIG_DIR, "github-token.json")
# 이 폴더들(로그인 토큰이 있는 곳) 안의 파일은 어떤 경로로 와도 보여 주지 않아요(설치 폴더를 그 안에 둔 드문 경우엔 토큰 파일만)
SECRET_DIRS = tuple({os.path.realpath(CONFIG_DIR), os.path.realpath(os.path.join(HOME_RAW, ".config", "agencity"))})
SECRET_FILES = tuple({os.path.join(d, "github-token.json") for d in SECRET_DIRS})
LEVELS = ("private", "building", "names", "tour")
PUBLIC_OF = {"private": "private", "building": "building", "names": "name", "tour": "tour"}   # public.json floors.<id>.public 값
LEVEL_OF = {v: k for k, v in PUBLIC_OF.items()}   # 거꾸로: public.json 값 → 공개 범위(모르는 값은 비공개)
OUT_LEVELS = ("names", "tour")   # 층 정보가 실제로 도시에 나가는 범위(office_public.py가 name·tour만 내보내요)
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
GIST_RE = re.compile(r"^[0-9a-f]{5,64}$", re.I)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{10,255}$")
WORKTREE = re.compile(r"/\.claude/worktrees/[^/]+(?:/.*)?$")   # worktree 세션은 원래 프로젝트 폴더로 묶어요
SCRATCH = re.compile(r"/Claude/scratch-workspaces(?:/|$)")      # 폴더 없이 만든 세션이 쓰는 앱의 임시 작업 폴더
SURROGATE = re.compile("[\ud800-\udfff]")   # 짝 없는 UTF-16 반쪽 글자: UTF-8로 못 바꿔서 응답·new_team.py 입력을 깨요
MAX_SESSIONS = 2000       # 세션 기록은 최근 것부터 이만큼만 읽어요
MAX_CONFIG = 8 * 1024 * 1024   # Claude 앱 설정 파일이 이보다 크면 그룹을 읽지 않고 폴더별로 묶어요
TEAM_ID = re.compile(r"^[a-z][a-z0-9-]{0,19}\Z")   # bin/new_team.py의 팀 id 규칙과 같아요
GROUP_KEY = re.compile(r"^(?:[gp]-[0-9a-f]{12}|scratch)\Z")
NEW_HOME = "agencity-teams"   # 폴더가 없는 그룹을 층으로 만들 때 새 폴더를 두는 곳(~/agencity-teams/<팀 id>)
SCRATCH_NAME = "이 컴퓨터"   # 폴더 없이 만든 세션 묶음(Claude 앱 사이드바와 같은 이름)
DEVICE = {}               # 진행 중인 GitHub 기기 로그인. device_code는 이 메모리에만 둬요
SETUP_LOCK = threading.Lock()
TEAM_LOCK = threading.Lock()   # 층 만들기·팀원 고치기(team.json을 쓰는 일)는 한 번에 하나씩
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1(시험용 가짜 서버)은 프록시를 거치지 않게


class ApiError(Exception):
    def __init__(self, code, msg, extra=None):
        super().__init__(msg)
        self.code, self.msg, self.extra = code, msg, extra or {}


def now():
    return datetime.now(KST).isoformat(timespec="seconds")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_line(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    with LOCK:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def one_line(s, limit=120):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def sha(to, text):
    return hashlib.sha256(f"{to}\n{text}".encode("utf-8")).hexdigest()


def org():
    return load_json(os.path.join(HERE, "org.json"))


def boss_sid():
    """org.json에 정한 진짜 총괄 세션 id(자리 표시용 local_00000000…은 빼요). 없거나 org.json을 못 읽으면 None."""
    try:
        b = org().get("boss")
    except (OSError, ValueError, AttributeError):
        return None
    sid = b.get("sessionId") if isinstance(b, dict) else None
    return sid if isinstance(sid, str) and SESSION_ID.match(sid) and not sid.startswith("local_00000000") else None


def under(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def office_roots():
    """팀 사무실 폴더들. 설치 폴더나 설정 폴더를 통째로 품는 곳(링크로 잘못 이어진 사무실)은 빼요."""
    roots = []
    try:
        for t in org().get("teams", []):
            if isinstance(t, dict) and isinstance(t.get("office"), str) and t["office"]:
                r = os.path.realpath(os.path.join(HERE, t["office"]))
                if not any(under(d, r) for d in (HERE,) + SECRET_DIRS):
                    roots.append(r)
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return roots


def is_role(r):
    """역할 이름으로 쓸 수 있는지(team.json에서 읽은 것도 이걸로 걸러요: 파일 이름이 되니까)."""
    return isinstance(r, str) and bool(ROLE_RE.match(r)) and r not in NOT_ROLES


def lead_first(roles):
    """팀장을 맨 앞으로, 나머지는 원래 순서대로."""
    roles = list(roles)
    return [r for r in roles if r == LEAD] + [r for r in roles if r != LEAD]


def team_info(tid):
    """(org.json의 층, 팀 사무실 실제 경로, {역할: 세션이 앉은 팀원}). 팀원은 팀장이 먼저, 그다음 team.json 순서예요."""
    t = next((t for t in org().get("teams", []) if t.get("id") == tid and t.get("office")), None)
    if not t:
        raise ApiError(404, "그런 팀(층)이 없어요")
    base = os.path.realpath(os.path.join(HERE, t["office"]))
    team = load_json(os.path.join(base, "team.json"))
    seated = {}
    for m in team.get("members", []) if isinstance(team.get("members"), list) else []:
        if isinstance(m, dict) and is_role(m.get("role")) and m["role"] not in seated and SESSION_ID.match(str(m.get("sessionId") or "")):
            seated[m["role"]] = m
    members = {r: seated[r] for r in lead_first(seated)}
    return t, base, members


def text_of(body, key="text", limit=MAX_TEXT, required=True):
    v = body.get(key, "")
    if not isinstance(v, str):
        raise ApiError(400, f"{key}는 글이어야 해요")
    v = v.strip()
    if required and not v:
        raise ApiError(400, "내용이 비었어요")
    if len(v) > limit:
        raise ApiError(400, f"너무 길어요({limit}자까지)")
    return v


def reply_hint(thread, who):
    """답 본문이 Bash 명령에 들어가지 않게, 파일로 쓴 뒤 say.sh --file로 남기게 해요(안전장치 훅이 본문 낱말에 걸리지 않게)."""
    out = os.path.join(os.path.dirname(thread), ".out", f"{who}.txt")
    return (f"\n\n답은 사이트에 남겨요(대표가 거기서 봐요). 짧게, 두 단계로:\n"
            f"1) Write 도구로 답을 이 파일에 써요: {out}\n"
            f"2) 실행: {SAY} '{thread}' {who} --file '{out}'")


def check_rate(n):
    t = time.time()
    with LOCK:
        RECENT[:] = [x for x in RECENT if t - x < 60]
        pending = sum(1 for f in os.listdir(OUTBOX) if f.endswith(".json")) if os.path.isdir(OUTBOX) else 0
        if pending + n > MAX_PENDING:
            raise ApiError(429, "총괄이 아직 앞의 말을 전달하고 있어요. 조금 뒤에 다시 보내 주세요")
        if len(RECENT) + n > MAX_PER_MIN:
            raise ApiError(429, "1분에 보낼 수 있는 양을 넘었어요. 조금 뒤에 다시 보내 주세요")
        RECENT.extend([t] * n)


def enqueue(session_id, label, text, thread):
    """총괄이 SendMessage로 전할 메시지를 outbox/에 남겨요."""
    item = {"id": f"{int(time.time() * 1000)}-{secrets.token_hex(3)}", "t": now(), "to": session_id, "label": label,
            "thread": thread, "text": text}
    with LOCK:
        ISSUED[item["id"]] = sha(session_id, text)
    write_json(os.path.join(OUTBOX, item["id"] + ".json"), item)
    return item["id"]


def log(base, to, kind, text):
    append_line(os.path.join(base, "log.jsonl"), {"t": now(), "from": "대표", "to": to, "kind": kind, "text": one_line(text, 200)})


def meeting_paths(base, mid):
    if not SAFE_ID.match(mid):
        raise ApiError(400, "회의 번호가 이상해요")
    meta = os.path.join(base, "meetings", mid + ".json")
    if not os.path.isfile(meta):
        raise ApiError(404, "그런 회의가 없어요")
    return meta, os.path.join(base, "meetings", mid + ".chat.jsonl")


def blocking_meeting(base):
    """새 회의를 막는 회의: '진행 중'인 사이트 회의."""
    d = os.path.join(base, "meetings")
    if not os.path.isdir(d):
        return None
    for f in sorted(os.listdir(d)):
        if re.match(r"^\d{8}-M-\d+\.json$", f):
            try:
                m = load_json(os.path.join(d, f))
            except (OSError, ValueError):
                continue
            if m.get("status") == "진행 중":
                return m
    return None


def options_of(a):
    """결재 선택지: [{key,label}] 또는 ["A안", ...] 둘 다 받아요. key는 글로 맞춰요."""
    out = []
    for o in a.get("options") or []:
        if isinstance(o, dict) and str(o.get("key", "")).strip():
            out.append({"key": str(o["key"]).strip(), "label": one_line(o.get("label", ""), 80)})
        elif isinstance(o, (str, int, float)) and str(o).strip():
            out.append({"key": str(o).strip(), "label": ""})
    return out


# ---------- API ----------

def api_say(body):
    thread = body.get("thread")
    text = text_of(body)
    if thread == "boss":
        boss = org().get("boss") or {}
        if not SESSION_ID.match(str(boss.get("sessionId", ""))):
            raise ApiError(404, "총괄 세션이 없어요")
        check_rate(1)
        append_line(HQ_CHAT, {"t": now(), "from": "대표", "text": text})
        enqueue(boss["sessionId"], "총괄", f"[대표·사이트] 총괄에게\n{text}{reply_hint(HQ_CHAT, '총괄')}", HQ_CHAT)
        return {"ok": True}
    t, base, members = team_info(body.get("team"))
    if isinstance(thread, str) and thread.startswith("chat:"):
        role = thread[5:]
        m = members.get(role)
        if not m:
            raise ApiError(404, "그 자리에 사람이 없어요")
        check_rate(1)
        path = os.path.join(base, "chat", role + ".jsonl")
        append_line(path, {"t": now(), "from": "대표", "text": text})
        log(base, role, "말", text)
        enqueue(m["sessionId"], f"{t['name']} · {role}",
                f"[대표·사이트] {t['name']} {role}에게 바로 말 걸기\n{text}{reply_hint(path, role)}\n"
                f"일을 시킨 거면 끝난 뒤 결과도 같은 방법으로 한 줄 남겨요.\n\n{NOTE}", path)
        return {"ok": True}
    if isinstance(thread, str) and thread.startswith("meeting:"):
        meta_path, chat = meeting_paths(base, thread[8:])
        meta = load_json(meta_path)
        if meta.get("status") != "진행 중":
            raise ApiError(409, "끝났거나 정리 중인 회의예요")
        if meta.get("mode") != "참석":
            raise ApiError(409, "먼저 회의에 참석해야 말할 수 있어요")
        parts = [r for r in meta.get("participants", []) if r in members]
        to = body.get("to") or parts
        if not isinstance(to, list) or not to or any(r not in parts for r in to):
            raise ApiError(400, "받는 사람이 회의 참석자가 아니에요")
        to = [r for r in members if r in to]        # 중복 없애고 자리 순서(팀장 먼저)로
        check_rate(len(to))
        append_line(chat, {"t": now(), "from": "대표", "to": to, "text": text})
        log(base, "회의", "회의", f"{meta['id']} {text}")
        for r in to:
            ask = "팀장은 늘 답하고 진행을 이끌어요." if r == "팀장" else "이름이 불렸거나 자기 분야일 때만 3문장 안으로 답해요. 할 말이 없으면 답하지 않아도 돼요."
            enqueue(members[r]["sessionId"], f"{t['name']} 회의 · {r}",
                    f"[대표·사이트] 회의 {meta['id']} (대표 참석 중) · 주제: {one_line(meta.get('topic'), 200)}\n받는 사람: {', '.join(to)}\n대표: {text}\n\n"
                    f"앞의 대화는 회의 파일에서 읽어요: {chat}\n{ask}{reply_hint(chat, r)}\n\n{NOTE}", chat)
        return {"ok": True}
    raise ApiError(400, "어디에 말할지 모르겠어요")


def api_meeting_start(body):
    t, base, members = team_info(body.get("team"))
    if "팀장" not in members:
        raise ApiError(409, "팀장이 없어서 회의를 열 수 없어요")
    topic = text_of(body, "topic", 300)
    mode = body.get("mode")
    if mode not in ("참석", "위임"):
        raise ApiError(400, "회의 방식은 참석 또는 위임이에요")
    parts = body.get("participants") or list(members)   # 안 보내면 세션이 앉은 팀원 모두
    if not isinstance(parts, list) or "팀장" not in parts or any(not isinstance(r, str) or r not in members for r in parts):
        raise ApiError(400, "참석자에는 팀장이 있어야 하고, 팀에 있는 사람만 넣을 수 있어요")
    note = text_of(body, "note", 2000, required=False)
    aid = str(body.get("approval") or "")
    if aid and not SAFE_ID.match(aid):
        raise ApiError(400, "결재 번호가 이상해요")
    check_rate(1)
    with LOCK:
        busy = blocking_meeting(base)
        if busy:
            raise ApiError(409, f"{busy.get('id')} 회의가 아직 진행 중이에요. 회의실에서 끝낸 뒤 새로 열어요")
        day = datetime.now(KST).strftime("%Y%m%d")
        d = os.path.join(base, "meetings")
        os.makedirs(d, exist_ok=True)
        n = 1 + max([int(m.group(1)) for f in os.listdir(d) for m in [re.match(rf"^{day}-M-(\d+)\.json$", f)] if m] or [0])
        mid = f"{day}-M-{n}"
        meta = {"id": mid, "topic": topic, "note": note, "mode": mode, "participants": [r for r in members if r in parts],
                "status": "진행 중", "started_by": "대표", "started": now(),
                "chat": f"meetings/{mid}.chat.jsonl", "minutes": f"meetings/{mid}.md"}
        if aid:
            meta["approval"] = aid
        write_json(os.path.join(d, mid + ".json"), meta)
    chat = os.path.join(d, mid + ".chat.jsonl")
    append_line(chat, {"t": now(), "from": "대표", "kind": "시작", "text": f"회의 시작 · {topic} ({mode})" + (f"\n{note}" if note else "")})
    log(base, "팀 전체", "회의", f"{mid} {topic} ({mode})")
    if aid:   # 팀장이 올린 '회의를 열어 주세요' 결재 → 이 회의로 승인
        ap = os.path.join(base, "approvals", aid + ".json")
        with LOCK:
            try:
                a = load_json(ap)
                if a.get("status") in ("결재 대기", "보류"):
                    a["status"] = "승인"
                    a["decision"] = {"choice": "회의 시작", "meeting": mid, "t": now(), "by": "대표"}
                    write_json(ap, a)
            except (OSError, ValueError):
                pass
    how = ("대표가 회의실에 들어와 있어요. 대표 말은 참석자에게 하나씩 전해져요. 팀장이 먼저 안건을 정리해 회의 파일에 남기고 진행을 이끌어요."
           if mode == "참석" else
           "대표 없이 진행하는 위임 회의예요. 팀 규칙의 위임 회의처럼 의견을 모으되, 오가는 말과 의견 요약을 회의 파일에 남겨 대표가 사이트에서 볼 수 있게 해요.")
    enqueue(members["팀장"]["sessionId"], f"{t['name']} 회의 · 팀장",
            f"[대표·사이트] 회의 시작 {mid} ({mode})\n주제: {topic}\n" + (f"대표 메모: {note}\n" if note else "") +
            f"참석: {', '.join(meta['participants'])}\n회의 정보: {os.path.join(d, mid + '.json')}\n회의 파일: {chat}\n\n{how}\n"
            f"끝나면 팀 규칙의 회의 끝 순서대로: 회의록 {os.path.join(d, mid + '.md')} → 회의 정보 status '끝' → 참석자에게 [회의 결과] → 대표가 정할 게 있으면 결재."
            f"{reply_hint(chat, '팀장')}\n\n{NOTE}", chat)
    return {"ok": True, "id": mid}


def api_meeting_mode(body):
    t, base, members = team_info(body.get("team"))
    mode = body.get("mode")
    if mode not in ("참석", "위임"):
        raise ApiError(400, "회의 방식은 참석 또는 위임이에요")
    meta_path, chat = meeting_paths(base, str(body.get("id", "")))
    with LOCK:
        meta = load_json(meta_path)
        if meta.get("status") != "진행 중":
            raise ApiError(409, "진행 중인 회의가 아니에요")
        if meta.get("mode") == mode:
            return {"ok": True}
        meta["mode"] = mode
        write_json(meta_path, meta)
    if mode == "위임":
        line, msg = "대표가 회의에서 빠졌어요. 남은 안건은 위임 회의로 계속해요.", "대표가 회의에서 빠졌어요. 남은 안건은 너희끼리 위임 회의로 계속하고 끝까지 마무리해요."
    else:
        line, msg = "대표가 회의에 들어왔어요.", "대표가 회의에 다시 들어왔어요. 지금까지 정리한 걸 회의 파일에 한 줄로 남기고 대표 말을 기다려요."
    append_line(chat, {"t": now(), "from": "대표", "kind": "참석" if mode == "참석" else "퇴장", "text": line})
    log(base, "회의", "회의", f"{meta['id']} {line}")
    if "팀장" in members:
        check_rate(1)
        enqueue(members["팀장"]["sessionId"], f"{t['name']} 회의 · 팀장",
                f"[대표·사이트] 회의 {meta['id']} · {msg}\n회의 파일: {chat}{reply_hint(chat, '팀장')}\n\n{NOTE}", chat)
    return {"ok": True}


def api_meeting_end(body):
    t, base, members = team_info(body.get("team"))
    meta_path, chat = meeting_paths(base, str(body.get("id", "")))
    with LOCK:
        meta = load_json(meta_path)
        if meta.get("status") != "진행 중":
            raise ApiError(409, "진행 중인 회의가 아니에요")
        meta["status"] = "정리 중"
        meta["end_requested"] = now()
        write_json(meta_path, meta)
    append_line(chat, {"t": now(), "from": "대표", "kind": "끝", "text": "대표가 회의를 끝냈어요. 팀장이 회의록을 정리해요."})
    log(base, "회의", "회의", f"{meta['id']} 끝내기")
    if "팀장" in members:
        check_rate(1)
        enqueue(members["팀장"]["sessionId"], f"{t['name']} 회의 · 팀장",
                f"[대표·사이트] 회의 {meta['id']}를 대표가 끝냈어요. 팀 규칙의 회의 끝 순서로: 회의록 {os.path.join(base, 'meetings', meta['id'] + '.md')} → "
                f"회의 정보 status '끝' → 참석자에게 [회의 결과](status 되돌리기) → 대표가 정할 게 있으면 결재.\n"
                f"회의 파일: {chat}\n마지막으로 회의 파일에 결론 한 줄을 남겨요.{reply_hint(chat, '팀장')}\n\n{NOTE}", chat)
    return {"ok": True}


def api_meeting_close(body):
    """'정리 중'에서 멈춘 회의를 대표가 직접 닫아요(새 회의를 열 수 있게)."""
    t, base, members = team_info(body.get("team"))
    meta_path, chat = meeting_paths(base, str(body.get("id", "")))
    with LOCK:
        meta = load_json(meta_path)
        if meta.get("status") != "정리 중":
            raise ApiError(409, "정리 중인 회의만 닫을 수 있어요")
        meta["status"] = "끝"
        meta["closed_by"] = "대표"
        meta["closed"] = now()
        write_json(meta_path, meta)
    append_line(chat, {"t": now(), "from": "대표", "kind": "끝", "text": "대표가 회의를 닫았어요."})
    log(base, "회의", "회의", f"{meta['id']} 닫기")
    if "팀장" in members:
        check_rate(1)
        enqueue(members["팀장"]["sessionId"], f"{t['name']} 회의 · 팀장",
                f"[대표·사이트] 회의 {meta['id']}는 대표가 닫았어요. 회의록·결재 등 남은 정리가 있으면 이어서 하되, 회의 정보 status는 다시 바꾸지 말아요.\n\n{NOTE}", chat)
    return {"ok": True}


def api_decide(body):
    t, base, members = team_info(body.get("team"))
    aid = str(body.get("id", ""))
    if not SAFE_ID.match(aid):
        raise ApiError(400, "결재 번호가 이상해요")
    path = os.path.join(base, "approvals", aid + ".json")
    if not os.path.isfile(path):
        raise ApiError(404, "그런 결재가 없어요")
    choice = str(body.get("choice") or "")
    comment = text_of(body, "comment", 2000, required=False)
    with LOCK:
        a = load_json(path)
        if a.get("status") not in ("결재 대기", "보류"):
            raise ApiError(409, f"이미 '{a.get('status')}'로 처리된 결재예요")
        opts = options_of(a)
        keys = [o["key"] for o in opts]
        allowed = (keys or ["승인"]) + ["반려", "보류"]
        if choice not in allowed:
            raise ApiError(400, "고를 수 없는 답이에요")
        status = choice if choice in ("반려", "보류") else "승인"
        a["status"] = status
        a["decision"] = {"choice": choice, "comment": comment, "t": now(), "by": "대표"}
        write_json(path, a)
    label = next((o["label"] for o in opts if o["key"] == choice), "")
    picked = f" · 선택 {choice}" + (f" {label}" if label else "") if keys and status == "승인" else ""
    log(base, "팀장", "결재", f"{aid} {status}{picked}")
    if "팀장" in members:
        check_rate(1)
        risky = ("\n이 결재는 팀 규칙의 '사람 승인이 필요한 일'이에요. 결재는 '하기로 정함'이고, 실제 실행은 그 일을 할 세션 창에서 대표가 직접 말하거나 권한 창을 눌러야 해요. "
                 "실행할 세션과 할 말을 대표에게 다시 알려 주세요.") if a.get("risky") else ""
        chat = os.path.join(base, "chat", "팀장.jsonl")
        append_line(chat, {"t": now(), "from": "대표", "kind": "결재", "text": f"결재 {aid} «{one_line(a.get('title'))}» {status}{picked}" + (f" · {comment}" if comment else "")})
        enqueue(members["팀장"]["sessionId"], f"{t['name']} 결재 · 팀장",
                f"[대표·사이트] 결재 {aid} «{one_line(a.get('title'))}»\n결과: {status}{picked}" +
                (f"\n대표 메모: {comment}" if comment else "") + f"\n결재 파일: {path}\n이어서 진행하고, 진행 결과를 아래 방법으로 사이트에 남긴 뒤 총괄에게 보고해요.{risky}"
                f"{reply_hint(chat, '팀장')}\n\n{NOTE}", chat)
    return {"ok": True, "status": status}


def api_state():
    pending, oldest = 0, 0
    if os.path.isdir(OUTBOX):
        for f in os.listdir(OUTBOX):
            if f.endswith(".json"):
                pending += 1
                try:
                    oldest = max(oldest, round(time.time() - os.path.getmtime(os.path.join(OUTBOX, f))))
                except OSError:
                    pass
    age = None
    try:
        age = max(0, round(time.time() - os.path.getmtime(os.path.join(OUTBOX, ".heartbeat"))))
    except OSError:
        pass
    return {"ok": True, "pending": pending, "oldestAge": oldest, "relayAge": age}


def api_outbox_check(q):
    oid = (q.get("id") or [""])[0]
    with LOCK:
        h = ISSUED.get(oid)
    return {"ok": h is not None, "sha": h}


# ---------- 처음 설정(앱의 로그인 화면) ----------
# 순서: GitHub 로그인 → 이 맥의 Claude Code 세션에서 층(팀)으로 만들 것 고르기 → 층별 공개 범위 → (원하면) 공개하기 → 끝.
# 'Claude 로그인'은 따로 없어요(외부 앱용 공식 로그인이 없어요). Claude 데스크톱 앱이 있는지와 그 앱의 Code 세션 목록을 봐요.

def platform_name():
    return "mac" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else "other"


def int_in(v, default, lo, hi):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def last_line(text):
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    return one_line(lines[-1], 300) if lines else ""


def last_json(text):
    """도우미 스크립트가 표준 출력 맨 끝에 남긴 JSON 한 줄."""
    for line in reversed(str(text or "").splitlines()):
        if line.strip():
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def load_setup():
    try:
        s = load_json(SETUP)
    except (OSError, ValueError):
        return {}
    return s if isinstance(s, dict) else {}


def real_teams():
    """org.json에서 사무실이 있는 층(예시 팀 포함)."""
    try:
        teams = org().get("teams", [])
    except (OSError, ValueError, AttributeError):
        return []
    if not isinstance(teams, list):
        return []
    return [t for t in teams if isinstance(t, dict) and t.get("office") and isinstance(t.get("id"), str)]


def is_example(t):
    return str(t.get("office") or "").startswith("examples/")


# GitHub 로그인 -------------------------------------------------------------

def client_id():
    """GitHub OAuth 앱의 client id: 환경 변수, 없으면 설치 폴더의 github_client_id 첫 줄. 없으면 기기 로그인을 못 써요."""
    v = os.environ.get("AGENCITY_GITHUB_CLIENT_ID", "").strip()
    if not v:
        try:
            with open(os.path.join(HERE, "github_client_id"), encoding="utf-8") as f:
                v = f.readline().strip()
        except OSError:
            v = ""
    return v if re.match(r"^[A-Za-z0-9._-]{1,100}$", v) else ""


def load_token():
    try:
        t = load_json(TOKEN_FILE)
    except (OSError, ValueError):
        return None
    if isinstance(t, dict) and LOGIN_RE.match(str(t.get("login", ""))) and TOKEN_RE.match(str(t.get("token", ""))):
        return t
    return None


def save_token(login, token, scope):
    """기기 로그인 토큰은 0700 폴더 안의 0600 파일에만 둬요."""
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    st = os.lstat(CONFIG_DIR)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise ApiError(500, "설정 폴더가 내 폴더가 아니거나 링크예요. 로그인 정보를 저장하지 않았어요")
    os.chmod(CONFIG_DIR, 0o700)
    tmp = f"{TOKEN_FILE}.tmp{os.getpid()}{threading.get_ident()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"login": login, "token": token, "scope": scope, "created": now()}, f)
        os.replace(tmp, TOKEN_FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def drop_token():
    try:
        os.remove(TOKEN_FILE)
    except FileNotFoundError:
        pass


def github_state(s=None):
    """로그인한 GitHub 아이디와 방법. 기기 로그인인데 토큰 파일이 없으면 로그아웃된 걸로 봐요."""
    g = (load_setup() if s is None else s).get("github")
    if not isinstance(g, dict) or not LOGIN_RE.match(str(g.get("login", ""))) or g.get("via") not in ("gh", "device"):
        return None
    if g["via"] == "device":
        t = load_token()
        if not t or t["login"].lower() != g["login"].lower():
            return None
    return {"login": g["login"], "via": g["via"]}


def set_github(login, via):
    s = load_setup()
    if login:
        s["github"] = {"login": login, "via": via}
    else:
        s.pop("github", None)
    write_json(SETUP, s)


def github_call(url, form=None, token=None):
    """GitHub(시험 때는 가짜 서버)에 묻고 (상태 코드, JSON dict)를 돌려줘요. 토큰은 Authorization 머리글로만 보내요."""
    headers = {"Accept": "application/json", "User-Agent": f"agencity/{VERSION}"}
    data = None
    if form is not None:
        data = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers.update({"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"})
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        if urlsplit(url).hostname in ("127.0.0.1", "localhost"):
            r = LOCAL.open(req, timeout=15)
        else:
            r = urllib.request.urlopen(req, timeout=15)
        with r:
            code, raw = r.status, r.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        try:
            code, raw = e.code, e.read(MAX_BODY)
        except OSError:
            code, raw = e.code, b""
    except (urllib.error.URLError, OSError, ValueError) as e:
        if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):
            raise ApiError(502, "GitHub 인증서를 확인하지 못했어요. python.org에서 받은 파이썬이면 'Install Certificates.command'를 한 번 실행해 주세요")
        raise ApiError(502, "GitHub에 연결하지 못했어요. 인터넷 연결을 확인해 주세요")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        obj = None
    return code, obj if isinstance(obj, dict) else {}


def gh_login():
    """gh에 이미 로그인된 계정의 아이디. gh의 토큰은 읽거나 내지 않아요. 안 되면 ""."""
    try:
        r = subprocess.run(["gh", "api", "user"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
                           env=dict(os.environ, GH_PROMPT_DISABLED="1", NO_COLOR="1"))
        login = str(json.loads(r.stdout).get("login", "")) if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return ""
    return login if LOGIN_RE.match(login) else ""


def api_setup_github_start(body):
    cid = client_id()
    if not cid:
        raise ApiError(409, "이 설치본에는 GitHub 앱 정보(client id)가 없어서 기기 코드 로그인을 쓸 수 없어요. gh로 로그인해 주세요")
    code, res = github_call(GITHUB_BASE + "/login/device/code", {"client_id": cid, "scope": "gist"})
    dc, uc = str(res.get("device_code") or ""), str(res.get("user_code") or "")
    if code != 200 or not re.match(r"^[A-Za-z0-9._-]{8,200}$", dc) or not re.match(r"^[A-Z0-9-]{4,20}$", uc):
        raise ApiError(502, f"GitHub 로그인을 시작하지 못했어요({one_line(res.get('error') or code, 60)})")
    interval = int_in(res.get("interval"), 5, 1, 60)
    expires = int_in(res.get("expires_in"), 900, 60, 1800)
    uri = str(res.get("verification_uri") or "")
    if not uri.startswith(GITHUB_BASE + "/") or len(uri) > 200:
        uri = GITHUB_BASE + "/login/device"
    t = time.time()
    with SETUP_LOCK:
        DEVICE.clear()
        DEVICE.update(code=dc, interval=interval, until=t + expires, next=t + interval)
    return {"ok": True, "userCode": uc, "verificationUri": uri, "interval": interval, "expiresIn": expires}


def api_setup_github_poll(body):
    with SETUP_LOCK:
        if not DEVICE:
            raise ApiError(409, "진행 중인 GitHub 로그인이 없어요. 로그인을 다시 시작해 주세요")
        t = time.time()
        if t > DEVICE["until"]:
            DEVICE.clear()
            return {"ok": True, "status": "expired"}
        if t < DEVICE["next"]:            # GitHub이 정한 간격보다 자주 묻지 않아요(페이지가 자주 물어도)
            return {"ok": True, "status": "pending", "interval": DEVICE["interval"]}
        DEVICE["next"] = t + DEVICE["interval"]
        dc = DEVICE["code"]
    code, res = github_call(GITHUB_BASE + "/login/oauth/access_token",
                            {"client_id": client_id(), "device_code": dc, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    token, err = res.get("access_token"), str(res.get("error") or "")
    if isinstance(token, str) and TOKEN_RE.match(token):
        with SETUP_LOCK:
            if DEVICE.get("code") == dc:
                DEVICE.clear()            # 한 번 쓴 기기 코드는 다시 묻지 않아요
        c2, user = github_call(GITHUB_API + "/user", token=token)
        login = str(user.get("login") or "")
        if c2 != 200 or not LOGIN_RE.match(login):
            raise ApiError(502, "GitHub 아이디를 확인하지 못했어요. 로그인을 다시 해 주세요")
        with SETUP_LOCK:
            save_token(login, token, one_line(res.get("scope"), 100))
            set_github(login, "device")
        return {"ok": True, "status": "ok", "login": login}
    with SETUP_LOCK:
        same = DEVICE.get("code") == dc
        if err == "authorization_pending":
            return {"ok": True, "status": "pending", "interval": DEVICE.get("interval", 5)}
        if err == "slow_down":
            if same:
                DEVICE["interval"] = min(60, max(DEVICE["interval"] + 5, int_in(res.get("interval"), 0, 0, 60)))
                DEVICE["next"] = time.time() + DEVICE["interval"]
            return {"ok": True, "status": "slow_down", "interval": DEVICE.get("interval", 10)}
        if same:
            DEVICE.clear()
    if err in ("expired_token", "token_expired", "incorrect_device_code"):
        return {"ok": True, "status": "expired"}
    if err == "access_denied":
        return {"ok": True, "status": "denied"}
    raise ApiError(502, f"GitHub 로그인에 실패했어요({one_line(err or code, 60)}). 다시 시작해 주세요")


def api_setup_github_gh(body):
    if not shutil.which("gh"):
        raise ApiError(409, "gh가 설치돼 있지 않아요. 기기 코드로 로그인해 주세요")
    login = gh_login()
    if not login:
        raise ApiError(409, "gh에 로그인돼 있지 않아요. 터미널에서 gh auth login 뒤 다시 눌러 주세요")
    with SETUP_LOCK:
        DEVICE.clear()
        drop_token()          # 로그인은 하나만: gh로 바꾸면 앱이 받아 둔 토큰은 지워요
        set_github(login, "gh")
    return {"ok": True, "login": login}


def api_setup_github_logout(body):
    with SETUP_LOCK:
        DEVICE.clear()
        drop_token()
        set_github(None, None)
    return {"ok": True}


# Claude Code 세션 ---------------------------------------------------------

def claude_app():
    return any(os.path.isdir(p) for p in ("/Applications/Claude.app", os.path.join(HOME_RAW, "Applications", "Claude.app"), SESSIONS_DIR))


def show_path(p):
    for h in (HOME, HOME_RAW):
        if p == h or p.startswith(h + os.sep):
            return "~" + p[len(h):]
    return p


def epoch_ms(v):
    """lastActivityAt(초·밀리초 숫자나 ISO 시각)를 밀리초 숫자로. 모르면 None."""
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if isinstance(v, bool) or (isinstance(v, float) and not math.isfinite(v)):
        return None   # Infinity·1e400은 int로 못 바꿔요
    if isinstance(v, (int, float)):
        return int(v if v > 1e11 else v * 1000) if v > 0 else None
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp() * 1000)
    return None


def claude_sessions(include_archived=False):
    """Claude 데스크톱 앱의 Code 세션 기록(<세션 폴더>/<계정>/<조직>/local_*.json)에서
    sessionId·title·cwd·originCwd·isArchived·lastActivityAt만 써요.
    scope(<계정>/<조직>, 기록이 있던 폴더)는 앱 그룹을 맞춰 보는 데만 쓰고 응답에는 넣지 않아요."""
    files = glob.glob(os.path.join(glob.escape(SESSIONS_DIR), "*", "*", "local_*.json"))

    def mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    files.sort(key=mtime, reverse=True)
    seen = {}
    for p in files[:MAX_SESSIONS]:
        try:
            if os.path.getsize(p) > 4 * 1024 * 1024:
                continue
            rec = load_json(p)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("sessionId"), str) or not SESSION_ID.match(rec["sessionId"]):
            continue
        archived = rec.get("isArchived") is True
        if archived and not include_archived:
            continue
        cwd, origin = (rec.get(k) if isinstance(rec.get(k), str) and rec[k].startswith("/") and not SURROGATE.search(rec[k]) else ""
                       for k in ("cwd", "originCwd"))
        if not (origin or cwd):
            continue
        folder = WORKTREE.sub("", os.path.normpath(origin or cwd)) or "/"
        s = {"sessionId": rec["sessionId"], "title": clean_name(rec.get("title"), 120),
             "cwd": os.path.normpath(cwd or folder), "lastActivityAt": epoch_ms(rec.get("lastActivityAt")), "archived": archived,
             "folder": folder, "scratch": bool(SCRATCH.search(folder)),
             "scope": os.path.relpath(os.path.dirname(p), SESSIONS_DIR).replace(os.sep, "/")}
        old = seen.get(s["sessionId"])
        if old is None or (s["lastActivityAt"] or 0) > (old["lastActivityAt"] or 0):
            seen[s["sessionId"]] = s
    return list(seen.values())


def recent(s):
    return s["lastActivityAt"] or 0


def floor_folders():
    """이미 층인 프로젝트 폴더(실제 경로) → 팀 id."""
    teams = {}
    for t in real_teams():
        if isinstance(t.get("folder"), str) and t["folder"]:
            teams[os.path.realpath(os.path.expanduser(t["folder"]))] = t["id"]
    return teams


def claude_projects(include_archived=False, sessions=None):
    """세션을 프로젝트 폴더별로 묶어요(‘폴더별 보기’). 최근에 쓴 프로젝트·세션이 먼저예요."""
    teams = floor_folders()
    groups = {}
    for s in claude_sessions(include_archived) if sessions is None else sessions:
        groups.setdefault(s["folder"], []).append({k: s[k] for k in ("sessionId", "title", "cwd", "lastActivityAt", "archived")})
    out = []
    for folder, ss in groups.items():
        ss.sort(key=recent, reverse=True)
        out.append({"folder": folder, "display": show_path(folder), "exists": os.path.isdir(folder),
                    "team": teams.get(os.path.realpath(folder)), "scratch": bool(SCRATCH.search(folder)), "sessions": ss})
    out.sort(key=lambda p: recent(p["sessions"][0]), reverse=True)
    return out


# Claude 앱 사이드바의 그룹 ---------------------------------------------------
# 앱이 문서로 정하지 않은 내부 설정이라 모양이 조금이라도 다르면 그 부분은 버리고 폴더별로 묶어요.

def as_obj(v):
    """dict, 또는 dict를 담은 JSON 글. 아니면 {}."""
    if isinstance(v, str) and len(v) <= MAX_CONFIG:
        try:
            v = json.loads(v)
        except (ValueError, RecursionError):
            return {}
    return v if isinstance(v, dict) else {}


def as_list(v):
    if isinstance(v, str) and len(v) <= MAX_CONFIG:
        try:
            v = json.loads(v)
        except (ValueError, RecursionError):
            return []
    return v if isinstance(v, list) else []


def clean_name(v, limit):
    """설정 파일에서 온 이름: 제어 문자·글 방향 바꾸는 문자를 빼고 한 줄로."""
    if not isinstance(v, str):
        return ""
    v = "".join(ch for ch in v[:1000] if unicodedata.category(ch) not in ("Cc", "Cs")
                and not 0x202A <= ord(ch) <= 0x202E and not 0x2066 <= ord(ch) <= 0x2069)
    return one_line(v, limit)


def num(v):
    """순서 숫자. 아주 큰 정수도 float로 바꾸지 않고 그대로 비교해요(math.isfinite(큰 int)는 OverflowError)."""
    if isinstance(v, bool):
        return None
    return v if isinstance(v, int) or (isinstance(v, float) and math.isfinite(v)) else None


def app_sidebar():
    """Claude 앱 설정 파일에서 사이드바 그룹 두 항목만 꺼내요: (dframe-group-scopes, dframe-code-sections).
    파일이 없거나 크거나 깨졌거나 항목이 없으면 None이에요. 다른 항목은 쓰지 않고, 무엇이 틀렸는지도 기록에 남기지 않아요."""
    try:
        if os.path.getsize(CLAUDE_CONFIG) > MAX_CONFIG:
            return None
        raw = load_json(CLAUDE_CONFIG)
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    ep = as_obj(as_obj(as_obj(raw).get("preferences")).get("epitaxyPrefs"))
    scopes, sections = as_obj(ep.get("dframe-group-scopes")), as_obj(ep.get("dframe-code-sections"))
    del raw, ep
    return (scopes, sections) if scopes else None


def scope_groups(gs, secs):
    """한 계정(scope)의 내가 만든 그룹. ({그룹 id: 정보}, {세션 id: 그룹 id}, {세션 id: 그룹 안 순서})
    없어진 그룹을 가리키는 배정, local_… 모양이 아닌 세션은 버려요."""
    gs, secs = as_obj(gs), as_obj(secs)
    groups = {}
    for i, g in enumerate(as_list(gs.get("groups"))[:500]):
        gid = g.get("id") if isinstance(g, dict) else None
        if isinstance(gid, str) and 0 < len(gid) <= 200 and gid not in groups:
            groups[gid] = {"id": gid, "name": clean_name(g.get("name"), 60), "idx": i, "order": None, "hidden": False, "collapsed": False}
    for sec in as_list(secs.get("sections"))[:1000]:
        if not isinstance(sec, dict) or sec.get("kind") != "manual" or not isinstance(sec.get("id"), str):
            continue
        g = groups.get(sec["id"])
        if g is None or g["order"] is not None:
            continue
        g["order"] = num(sec.get("order"))
        g["hidden"] = sec.get("shown") is False
        g["collapsed"] = sec.get("collapsed") is True
        if not g["name"]:
            g["name"] = clean_name(sec.get("name"), 60)
    assign = {}
    for k, v in list(as_obj(gs.get("assignments")).items())[:20000]:
        if isinstance(k, str) and k.startswith("code:") and SESSION_ID.match(k[5:]) and isinstance(v, str) and v in groups:
            assign[k[5:]] = v
    pos = {}
    for gid, lst in list(as_obj(gs.get("order")).items())[:500]:
        if gid not in groups:
            continue
        for j, k in enumerate(as_list(lst)[:20000]):
            if isinstance(k, str) and k.startswith("code:") and assign.get(k[5:]) == gid:
                pos.setdefault(k[5:], j)
    return groups, assign, pos


def _w(x):
    """영문 낱말은 앞뒤가 영문자가 아닐 때만 맞춰요(ui가 build·guide에, dev가 device에 걸리지 않게). 한글·숫자는 붙어 있어도 돼요."""
    return rf"(?<![a-z]){x}(?![a-z])"


# 세션 제목으로 자리 짐작하기: 위에서부터 처음 맞는 자리 하나(대소문자 무시). '그리드'의 '리드'는 팀장이 아니에요.
ROLE_WORDS = (
    ("팀장", re.compile("팀장|(?<!그)리드|" + _w("lead(?:er|ers|s)?"), re.I)),
    ("개발자", re.compile("개발|엔지니어|코딩|" + _w("dev(?:s|elop(?:er|ers|ment|ing)?)?") + "|"
                        + _w("engineer(?:s|ing)?") + "|" + _w("cod(?:e|es|er|ers|ing)"), re.I)),
    ("디자이너", re.compile("디자인|디자이너|" + _w("design(?:er|ers|s|ing)?") + "|" + _w("ui") + "|" + _w("ux"), re.I)),
    ("기획", re.compile("기획|" + _w("plan(?:s|ner|ners|ning)?") + "|" + _w("pms?"), re.I)),
    ("마케팅", re.compile("마케팅|마케터|홍보|광고|브랜딩|그로스|" + _w("marketing") + "|" + _w("marketers?") + "|" + _w("growth") + "|" + _w("seo"), re.I)),
    ("QA", re.compile("품질|검수|테스트|테스터|" + _w("qa") + "|" + _w("test(?:s|er|ers|ing)?"), re.I)),
    ("데이터", re.compile("데이터|통계|" + _w("data") + "|" + _w("analytics") + "|" + _w("analysts?") + "|" + _w("ml"), re.I)),
)
GUESS_ROLES = [r for r, _ in ROLE_WORDS]   # 제목으로 짐작하는 자리(나머지는 '팀원')
BOSS_WORDS = re.compile("총괄|코디네이터|" + _w("coordinator"), re.I)   # 자리가 아니라 총괄(코디네이터) 후보예요


def guess_role(title):
    """'boss'(총괄 후보), 자리 이름, 또는 None."""
    t = str(title or "")
    if BOSS_WORDS.search(t):
        return "boss"
    return next((r for r, rx in ROLE_WORDS if rx.search(t)), None)


def suggest_members(ss, guess, seated):
    """묶음을 층으로 고를 때 미리 넣어 둘 팀원 줄 [{role, sessionId}]. 맨 앞은 늘 팀장 자리(제목이 팀장 같은 세션, 없으면 빈 자리)예요.
    나머지는 제목으로 짐작한 역할(모르면 '팀원'), 같은 역할이 여럿이면 개발자·개발자2…처럼 이름을 나눠요.
    이미 다른 층에 앉은 세션과 총괄 같은 세션은 빼고, 보관한 세션은 뒤로, 같은 역할 안에서는 최근 세션이 먼저예요. 12줄까지."""
    pool = sorted((s for s in ss if s["sessionId"] not in seated and guess.get(s["sessionId"]) != "boss"),
                  key=lambda s: (s["archived"], -recent(s)))
    lead = next((s for s in pool if guess.get(s["sessionId"]) == LEAD), None)
    rows, used = [{"role": LEAD, "sessionId": lead["sessionId"] if lead else None}], {LEAD}
    rank = {r: k for k, r in enumerate(GUESS_ROLES + [MEMBER])}

    def base(s):
        r = guess.get(s["sessionId"])
        return r if r in GUESS_ROLES and r != LEAD else MEMBER
    for s in sorted((s for s in pool if s is not lead), key=lambda s: (s["archived"], rank[base(s)], -recent(s))):
        if len(rows) >= MAX_MEMBERS:
            break
        name, n = base(s), 2
        while name in used:
            name, n = f"{base(s)}{n}", n + 1
        used.add(name)
        rows.append({"role": name, "sessionId": s["sessionId"]})
    return rows


def usable_folder(f):
    """층 폴더로 고를 수 있는 진짜 프로젝트 폴더면 실제 경로, 아니면 None.
    앱의 임시 작업 폴더, 없어진 폴더, 홈 폴더 자체, 에이전시티 폴더·설정 폴더 안은 빼요(check_folder와 같은 기준)."""
    if not f or SCRATCH.search(f) or not os.path.isdir(f):
        return None
    real = os.path.realpath(f)
    if SCRATCH.search(real) or real in (HOME, "/") or under(real, HERE) or any(under(real, d) for d in SECRET_DIRS):
        return None
    return real


def slug(s):
    """영문 소문자·숫자·- 로만 된 팀 id 후보(로마자로 바꾸지는 않아요: 한글 이름이면 빈 글)."""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if unicodedata.category(ch) != "Mn")   # é → e
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    return re.sub(r"^[^a-z]+", "", s)[:20].rstrip("-")


def unique_id(base, taken):
    if base:
        tid, n = base, 2
        while tid in taken:
            suf = f"-{n}"
            tid, n = base[:20 - len(suf)].rstrip("-") + suf, n + 1
    else:
        n = 1
        while f"team-{n}" in taken:
            n += 1
        tid = f"team-{n}"
    taken.add(tid)
    return tid


def taken_ids():
    """이미 쓰는 팀 id: org.json의 층과 teams/ 아래 이름."""
    ids = {t["id"] for t in real_teams()}
    try:
        ids |= {t.get("id") for t in org().get("teams", []) if isinstance(t, dict) and isinstance(t.get("id"), str)}
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    try:
        ids |= set(os.listdir(os.path.join(HERE, "teams")))
    except OSError:
        pass
    return ids


def floor_members():
    """내 층(예시 팀 빼고)의 team.json에 앉힌 세션 id → 팀 id."""
    out = {}
    for t in real_teams():
        if is_example(t):
            continue
        try:
            team = load_json(os.path.join(os.path.realpath(os.path.join(HERE, t["office"])), "team.json"))
            for m in team.get("members", []):
                if isinstance(m, dict) and isinstance(m.get("sessionId"), str) and SESSION_ID.match(m["sessionId"]):
                    out.setdefault(m["sessionId"], t["id"])
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return out


def group_floors(teams):
    """이 화면에서 그룹으로 만든 층(setup.json의 groupFloors: 그룹 key → 팀 id). 지금도 있는 층만."""
    m = load_setup().get("groupFloors")
    ids = {t["id"] for t in teams}
    return {k: v for k, v in m.items() if isinstance(k, str) and GROUP_KEY.match(k) and v in ids} if isinstance(m, dict) else {}


def claude_groups(sessions):
    """Claude 앱 사이드바처럼 묶어요: 내가 만든 그룹(앱 순서) → 나머지는 프로젝트 폴더별(최근 순) → 폴더 없이 만든 세션 한 묶음.
    (groupSource, groups, suggestedBoss)를 돌려줘요. 그룹을 못 읽으면 groupSource는 'folder'예요."""
    scopes = {}
    try:
        side = app_sidebar()
        if side:
            for sc in {s["scope"] for s in sessions}:
                g, a, p = scope_groups(side[0].get(sc), side[1].get(sc))
                if g:
                    scopes[sc] = (g, a, p)
    except Exception:  # noqa: BLE001 — 앱 내부 설정이라 생각 못 한 모양이면 그룹 없이(폴더별로) 보여 줘요
        scopes = {}
    # 그룹이 있고 세션 배정도 읽었을 때만 'app'이에요(배정을 못 읽으면 결국 폴더별과 같아요)
    source = "app" if any(a for _, a, _ in scopes.values()) else "folder"

    custom, folders, scratch = {}, {}, []
    for s in sessions:
        sc = scopes.get(s["scope"])
        gid = sc[1].get(s["sessionId"]) if sc else None
        if gid:
            custom.setdefault((s["scope"], gid), []).append(s)
        elif s["scratch"]:
            scratch.append(s)
        else:
            folders.setdefault(s["folder"], []).append(s)

    rank = {}   # 계정이 여럿이면 최근에 쓴 계정의 그룹이 먼저
    for s in sessions:
        rank[s["scope"]] = max(rank.get(s["scope"], 0), recent(s))
    raw = []
    for (sc, gid), ss in custom.items():
        g, pos = scopes[sc][0][gid], scopes[sc][2]
        ss.sort(key=lambda s: (s["sessionId"] not in pos, pos.get(s["sessionId"], 0), -recent(s)))
        raw.append(({"key": "g-" + hashlib.sha256(f"{sc}\0{gid}".encode("utf-8")).hexdigest()[:12], "kind": "group",
                     "name": g["name"] or "이름 없는 그룹", "hidden": g["hidden"], "collapsed": g["collapsed"]}, ss,
                    (-rank[sc], g["hidden"], g["order"] is None, g["order"] or 0, g["idx"])))
    raw.sort(key=lambda x: x[2])
    projects = []
    for folder, ss in folders.items():
        ss.sort(key=recent, reverse=True)
        home = os.path.realpath(folder) == HOME   # 홈 폴더에서 연 세션(홈 폴더 자체는 층 폴더로 못 써요)
        projects.append(({"key": "p-" + hashlib.sha256(folder.encode("utf-8")).hexdigest()[:12], "kind": "project",
                          "name": "홈 폴더" if home else clean_name(os.path.basename(folder), 60) or folder,
                          "folder": folder, "display": show_path(folder), "exists": os.path.isdir(folder), "home": home}, ss, None))
    projects.sort(key=lambda x: recent(x[1][0]), reverse=True)
    raw = [(g, ss) for g, ss, _ in raw] + [(g, ss) for g, ss, _ in projects]
    if scratch:
        scratch.sort(key=recent, reverse=True)
        raw.append(({"key": "scratch", "kind": "scratch", "name": SCRATCH_NAME}, scratch))

    teams = real_teams()
    by_folder, by_member, by_group, taken = floor_folders(), floor_members(), group_floors(teams), taken_ids()
    out, boss, cur = [], None, boss_sid()   # cur: org.json에 정한 지금 총괄. 제목과 상관없이 총괄로 봐요(층의 자리에 미리 넣지 않게)
    for i, (g, ss) in enumerate(raw):
        sess = []
        guess = {s["sessionId"]: guess_role(s["title"]) for s in ss}
        if cur in guess:
            guess[cur] = "boss"
        # 미리 넣을 팀원 줄. 다툼이 있으면 보관하지 않은 세션, 그중 최근 세션이 그 이름을 가져요(다음 세션은 개발자2처럼).
        # 이미 다른 층에 앉은 세션은 넣지 않아요(한 세션은 한 층에만)
        rows = suggest_members(ss, guess, by_member)
        mine = {m["sessionId"]: m["role"] for m in rows if m["sessionId"]}
        roles = {r: next((m["sessionId"] for m in rows if m["role"] == r), None) for r in CLASSIC_ROLES}   # 예전 판 화면용 네 자리
        for s in ss:   # 총괄 후보: 지금 총괄이 맨 앞, 아니면 제목이 총괄 같은 세션 중 가장 최근 것(이미 층에 앉은 세션은 빼요)
            if (guess[s["sessionId"]] == "boss" and not s["archived"] and s["sessionId"] not in by_member
                    and (boss is None or (boss["sessionId"] != cur and (s["sessionId"] == cur or recent(s) > recent(boss))))):
                boss = s
        for s in ss:
            real = usable_folder(s["folder"])   # 세션 하나로 층을 만들 때 쓸 그 세션의 프로젝트 폴더(없으면 새 폴더)
            sess.append({"sessionId": s["sessionId"], "title": s["title"], "cwd": s["cwd"], "folder": s["folder"],
                         "lastActivityAt": s["lastActivityAt"], "archived": s["archived"], "scratch": s["scratch"],
                         "role": mine.get(s["sessionId"]), "guess": guess[s["sessionId"]] if guess[s["sessionId"]] in GUESS_ROLES else None,
                         "coordinator": guess[s["sessionId"]] == "boss", "seatedOn": by_member.get(s["sessionId"]),
                         "projectFolder": s["folder"] if real else None, "folderFloor": by_folder.get(real) if real else None})
        count, last, shown = {}, {}, {}
        for s in ss:
            real = usable_folder(s["folder"])
            if real:
                count[real] = count.get(real, 0) + 1
                last[real] = max(last.get(real, 0), recent(s))
                shown.setdefault(real, s["folder"])
        fs = [shown[r] for r in sorted(count, key=lambda r: (-count[r], -last[r]))]
        sug = fs[0] if fs else None
        # 이미 층인지: 이 화면에서 이 그룹으로 만든 층 → 그 폴더를 쓰는 층 → (폴더 없는 그룹이면) 그룹 세션을 앉힌 층
        team = by_group.get(g["key"])
        hits = {}   # 이 그룹 세션이 앉은 층 → 세션 수
        for s in ss:
            if s["sessionId"] in by_member:
                hits[by_member[s["sessionId"]]] = hits.get(by_member[s["sessionId"]], 0) + 1

        def most(t, hits=hits, n=len(ss)):   # 그룹 세션 절반 넘게 그 층에 앉음
            return bool(t) and hits.get(t, 0) * 2 > n
        # 세션 하나만 따로 층으로 만든 그룹은 아직 층이 아니에요: 그룹 세션 절반 넘게 앉은 층이거나,
        # (폴더 층이면) 그룹 세션이 아무 층에도 앉지 않았고 다른 그룹으로 만든 층도 아닐 때만 이 그룹의 층으로 봐요(예전 판·터미널로 만든 층)
        if team is None and g["kind"] == "project":
            team = by_folder.get(os.path.realpath(g["folder"]))
        elif team is None and g["kind"] == "group" and sug:
            t = by_folder.get(os.path.realpath(sug))
            team = t if t and ((not hits and t not in by_group.values()) or most(t)) else None
        elif team is None and g["kind"] == "group":
            top = max(hits, key=hits.get) if hits else None
            team = top if most(top) else None
        if team is None and g["kind"] == "group":
            # 아직 층이 아닌 그룹에는 다른 층이 쓰는 폴더를 추천하지 않아요(모두 쓰이면 새 폴더). 고르기 목록(fs)에는 그대로 둬요
            sug = next((f for f in fs if os.path.realpath(f) not in by_folder), None)
        name = "새 팀" if g["kind"] == "scratch" or g.get("home") else clean_name(g["name"], 30)
        g.update(order=i, sessions=sess, roles=roles, suggestedMembers=rows, folders=fs, suggestedFolder=sug,
                 suggestedDisplay=show_path(sug) if sug else None,
                 suggestedName=name or "새 팀", team=team, lastActivityAt=max((recent(s) for s in ss), default=0) or None)
        out.append(g)
    # 팀 id 후보(이미 층이면 그 층 id): 이름으로 만든 id를 먼저 나눠 주고, 한글 이름처럼 못 만든 그룹은 폴더 이름 → team-<n> 순서로
    for g in out:
        if g["team"]:
            g["suggestedId"] = g["team"]
        elif slug(g["name"]):
            g["suggestedId"] = unique_id(slug(g["name"]), taken)
    for g in out:
        if not g.get("suggestedId"):
            g["suggestedId"] = unique_id(slug(os.path.basename(g["suggestedFolder"] or "")), taken)
        g["newFolder"] = None if g["suggestedFolder"] else f"~/{NEW_HOME}/{g['suggestedId']}"
    # 세션 하나로 만드는 층: 이름은 세션 제목, 폴더는 그 세션의 프로젝트 폴더(없거나 이미 다른 층 폴더면 새 폴더).
    # 팀 id 후보는 묶음 후보와도, 서로도 겹치지 않게 나눠요
    for g in out:
        for s in g["sessions"]:
            sid = slug(s["title"]) or (slug(os.path.basename(s["projectFolder"])) if s["projectFolder"] else "")
            s["suggestedId"] = unique_id(sid, taken)
            s["suggestedName"] = clean_name(s["title"], 30) or "새 팀"
            s["newFolder"] = None if s["projectFolder"] and not s["folderFloor"] else f"~/{NEW_HOME}/{s['suggestedId']}"
    return source, out, boss["sessionId"] if boss else None


def api_setup_claude(body):
    inc = body.get("includeArchived", False)
    if not isinstance(inc, bool):
        raise ApiError(400, "includeArchived는 true나 false예요")
    ss = claude_sessions(inc)
    source, groups, boss = claude_groups(ss)
    return {"ok": True, "app": claude_app(), "projects": claude_projects(inc, ss),
            "groupSource": source, "groups": groups, "suggestedBoss": boss,
            "currentBoss": boss_sid(),   # 지금 총괄 세션(층의 자리에는 앉힐 수 없어요)
            "roleSuggestions": ROLE_SUGGEST, "maxMembers": MAX_MEMBERS}


# 층 만들기 -----------------------------------------------------------------

def check_folder(v, detected):
    """층으로 쓸 프로젝트 폴더: 홈 폴더 안(또는 Claude 세션에서 찾은 프로젝트)의 있는 폴더, 에이전시티 폴더 밖."""
    p = os.path.expanduser(v.strip()) if isinstance(v, str) else ""
    if not p or not os.path.isabs(p):
        raise ApiError(400, "프로젝트 폴더는 전체 경로로 보내 주세요")
    if not os.path.isdir(p):
        raise ApiError(400, "프로젝트 폴더가 없어요. 있는 폴더를 골라 주세요")
    real = os.path.realpath(p)
    if real == HERE or real.startswith(HERE + os.sep):
        raise ApiError(400, "에이전시티 폴더 안은 팀 프로젝트로 쓸 수 없어요")
    if real in (HOME, "/"):
        raise ApiError(400, "홈 폴더 자체는 팀 프로젝트로 쓸 수 없어요. 프로젝트 폴더를 골라 주세요")
    if not (real.startswith(HOME + os.sep) or real in detected):
        raise ApiError(400, "홈 폴더 안의 폴더나 Claude 세션에서 찾은 프로젝트 폴더만 쓸 수 있어요")
    return real


def new_folder_path(tid):
    """폴더가 없는 그룹의 새 층 폴더 ~/agencity-teams/<팀 id>가 쓸 만한지 봐요(여기서는 만들지 않아요).
    홈 폴더 안이어야 하고, 에이전시티 폴더·설정 폴더 안(이나 그 폴더들을 품는 곳)은 안 돼요. 이미 있으면 링크가 아닌 폴더여야 해요."""
    base = os.path.join(HOME_RAW, NEW_HOME)
    path = os.path.join(base, tid)
    shown = f"~/{NEW_HOME}/{tid}"
    if os.path.islink(path):
        raise ApiError(400, f"{shown} 가 링크예요. 다른 팀 id를 써 주세요")
    for p in (base, path):
        if os.path.lexists(p) and not os.path.isdir(p):
            raise ApiError(400, f"{show_path(p)} 가 폴더가 아니에요. 다른 팀 id를 쓰거나 그 파일을 옮겨 주세요")
    real = os.path.realpath(path)
    if (not under(real, HOME) or real == HOME or under(real, HERE) or under(HERE, real)
            or any(under(real, d) or under(d, real) for d in SECRET_DIRS)):
        raise ApiError(400, f"새 폴더({shown})는 홈 폴더 안, 에이전시티 폴더와 설정 폴더 밖에만 만들 수 있어요")
    return path


def plan_new_folder(f, taken, here):
    """newFolder로 보낸 층: 폴더를 만들기 전에 팀 id·이름·머리글을 new_team.py와 같은 기준으로 먼저 봐요(안 될 층에 빈 폴더를 남기지 않게)."""
    tid = f.get("id")
    if not isinstance(tid, str) or not TEAM_ID.match(tid):
        raise ApiError(400, "팀 id는 영문 소문자로 시작하는 20자 이내예요(소문자·숫자·하이픈). 새 폴더 이름으로도 써요")
    if tid in taken or tid in here:
        raise ApiError(400, f"'{tid}'는 이미 있는 팀 id예요. 다른 id를 써 주세요")
    prefix = f.get("prefix")
    if prefix not in (None, "") and not (isinstance(prefix, str) and re.match(r"^[A-Z]{1,4}-$", prefix) and prefix not in ("J-", "U-", "M-")):
        raise ApiError(400, "업무 번호 머리글은 영문 대문자 1~4자 + 하이픈이에요. J-·U-·M-은 못 써요")
    if os.path.lexists(os.path.join(HERE, "teams", tid)):
        raise ApiError(400, f"teams/{tid} 가 이미 있어요. 다른 id를 써 주세요")
    return new_folder_path(tid)


def make_new_folder(path):
    """새 층 폴더를 만들어요(0755). 이번에 새로 만든 폴더들을 돌려줘요(층을 못 만들면 빈 폴더만 다시 지워요)."""
    made = []
    try:
        for d in (os.path.dirname(path), path):
            try:
                os.mkdir(d, 0o755)
            except FileExistsError:
                continue
            made.append(d)
            os.chmod(d, 0o755)
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise ApiError(400, f"{show_path(path)} 가 내 폴더가 아니에요")
        new_folder_path(os.path.basename(path))   # 만드는 사이에 링크로 바뀌지 않았는지 한 번 더
    except BaseException:
        drop_dirs(made)
        raise
    return made


def drop_dirs(made):
    for d in reversed(made):
        try:
            os.rmdir(d)   # 비어 있을 때만 지워져요
        except OSError:
            pass


def remember_groups(ids, pairs):
    """그룹으로 만든 층을 setup.json의 groupFloors에 적어 둬요(다음에 그 그룹을 ‘이미 층’으로 보여 주려고).
    ids: 이번에 만든 팀 id 모두. 같은 id를 가리키던 예전 줄(지운 층의 id를 다시 쓴 경우)은 지우고, 없어진 층의 줄도 치워요."""
    if not ids:
        return
    with SETUP_LOCK:
        s = load_setup()
        m = s.get("groupFloors") if isinstance(s.get("groupFloors"), dict) else {}
        m = {k: v for k, v in m.items() if v not in ids}
        live = taken_ids()
        if ids <= live:   # org.json을 제대로 읽었을 때만 없어진 층의 줄을 치워요
            m = {k: v for k, v in m.items() if v in live}
        m.update(pairs)
        s["groupFloors"] = m
        write_json(SETUP, s)


def away_of(members, office, where):
    """층에 앉힌 세션 중 층 폴더 밖에서 연 세션(폴더 없이 만든 세션, 새 폴더로 만든 층 등).
    Claude Code는 세션 폴더와 그 위 폴더의 CLAUDE.local.md만 읽어서, 이 세션들은 층 폴더의 CLAUDE.local.md를 읽지 않아요.
    members: [{role, sessionId}]. {rules: 절대 경로로 가져오는 한 줄(@~/…/.office/RULES.md), rulesFile: 그 파일 경로, away: [{role, sessionId, title}]}"""
    if members is None or not office:
        return {}
    home = os.path.realpath(os.path.dirname(office))
    away = []
    for m in members:
        s = where.get(m.get("sessionId") or "")
        if s and not under(os.path.realpath(s["cwd"]), home):
            away.append({"role": m["role"], "sessionId": s["sessionId"], "title": s["title"]})
    shown = show_path(os.path.join(office, "RULES.md"))
    return {"rules": "@" + shown.replace(" ", "\\ "), "rulesFile": shown, "away": away}   # 가져오기 줄의 빈칸은 '\ '로 적어요


def role_name(v):
    """보낸 역할 이름(앞뒤 빈칸을 빼고 NFC로 맞춘 것). 쓸 수 없는 이름이면 ApiError."""
    if not isinstance(v, str) or not v.strip():
        raise ApiError(400, "역할 이름이 비었어요")
    r = unicodedata.normalize("NFC", v.strip())
    if r in NOT_ROLES:
        raise ApiError(400, "대표·총괄은 역할 이름으로 쓸 수 없어요(층 밖의 자리예요)")
    if not ROLE_RE.match(r):
        raise ApiError(400, f"역할 이름으로 쓸 수 없어요: '{clean_name(r, 20)}'. 한글·영문·숫자로 12자까지예요(빈칸·/·. 없이, _ · - 는 돼요)")
    return r


def check_members(raw):
    """층의 팀원 목록 [{role, sessionId|null}]을 검사해서 [{role, sessionId}]로 돌려줘요.
    맨 앞은 팀장, 역할 이름은 층 안에서 한 번씩(대소문자 무시), 12명까지, 한 세션은 한 자리에만."""
    if not isinstance(raw, list) or not raw:
        raise ApiError(400, "팀원(members)은 목록으로 보내 주세요. 맨 앞은 팀장이에요")
    if len(raw) > MAX_MEMBERS:
        raise ApiError(400, f"팀원은 한 층에 {MAX_MEMBERS}명까지예요(팀장 포함). 지금 {len(raw)}명이에요")
    out, names, sids = [], {}, {}
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise ApiError(400, f"{i + 1}번째 팀원 모양이 이상해요({{role, sessionId}}이어야 해요)")
        r = role_name(m.get("role"))
        if r.casefold() in names:
            raise ApiError(400, f"이 층에 '{r}' 자리가 둘이에요. 역할 이름을 다르게 해 주세요(예: {r}2)")
        names[r.casefold()] = r
        sid = m.get("sessionId")
        if sid in (None, ""):
            sid = None
        elif not (isinstance(sid, str) and SESSION_ID.match(sid)):
            raise ApiError(400, f"{r} 세션 id가 local_… 모양이 아니에요")
        elif sid in sids:
            raise ApiError(400, f"같은 세션을 {sids[sid]}·{r} 두 자리에 앉혔어요. 한 세션은 한 자리에만 앉혀요")
        if sid:
            sids[sid] = r
        out.append({"role": r, "sessionId": sid})
    if LEAD not in names.values():
        raise ApiError(400, "팀장 자리가 없어요. 맨 앞에 팀장을 넣어 주세요(세션은 비워 둬도 돼요)")
    if out[0]["role"] != LEAD:
        raise ApiError(400, "팀장 자리는 맨 앞이어야 해요")
    return out


def members_of_roles(roles):
    """예전 판의 roles 묶음({"팀장": "local_…", …})을 팀원 목록으로. 네 자리는 늘 다 만들어요(0.4.1과 같아요)."""
    if not isinstance(roles, dict):
        raise ApiError(400, "역할(roles) 모양이 이상해요")
    bad = [clean_name(str(r), 20) for r in roles if r not in CLASSIC_ROLES]
    if bad:
        raise ApiError(400, f"모르는 역할이에요: {', '.join(bad)} (roles는 팀장·개발자·디자이너·기획만 받아요. 다른 역할은 members로 보내요)")
    for r, v in roles.items():
        if v not in (None, "") and not (isinstance(v, str) and SESSION_ID.match(v)):
            raise ApiError(400, f"{r} 세션 id가 local_… 모양이 아니에요")
    return check_members([{"role": r, "sessionId": roles.get(r) or None} for r in CLASSIC_ROLES])


def check_seats(members, seated, seats, bosses=()):
    """다른 층에 이미 앉은 세션(seated: 세션 → 층 이름), 이번 요청의 다른 층에 앉힌 세션(seats), 총괄 세션(bosses)이면 ApiError.
    총괄을 자리에 앉히면 그 자리로 보낸 말을 총괄이 자기에게 전하게 돼서 아무에게도 닿지 않아요."""
    for m in members:
        v = m["sessionId"]
        if v and v in bosses:
            raise ApiError(400, f"총괄 세션은 층의 자리에 앉힐 수 없어요({m['role']} 자리). 다른 세션을 고르거나 비워 두세요")
        if v and v in seated:
            raise ApiError(400, f"{m['role']} 세션은 이미 '{seated[v]}' 층에 앉아 있어요. 한 세션은 한 층에만 앉혀요")
        if v and v in seats:
            raise ApiError(400, f"{m['role']} 세션은 '{seats[v]}' 층에도 앉혔어요. 한 세션은 한 층에만 앉혀요")


def api_setup_floors(body):
    with TEAM_LOCK:
        return setup_floors(body)


def setup_floors(body):
    floors, boss, drop_demo = body.get("floors", []), body.get("boss"), body.get("dropDemo", True)
    if not isinstance(floors, list) or len(floors) > 20:
        raise ApiError(400, "만들 층은 목록으로 20개까지 보내 주세요")
    if boss not in (None, "") and not (isinstance(boss, str) and SESSION_ID.match(boss)):
        raise ApiError(400, "총괄 세션 id가 local_… 모양이 아니에요")
    if not isinstance(drop_demo, bool):
        raise ApiError(400, "dropDemo는 true나 false예요")
    if not floors and not boss:
        raise ApiError(400, "만들 층을 골라 주세요")
    projs = claude_projects(True)
    detected = {os.path.realpath(p["folder"]) for p in projs}
    where = {s["sessionId"]: s for p in projs for s in p["sessions"]}   # 세션 id → 기록(제목·cwd): 층 폴더 밖에서 연 세션을 알려 주려고
    taken = taken_ids()
    names = {t["id"]: t.get("name") or t["id"] for t in real_teams()}
    seated = {sid: names.get(tid, tid) for sid, tid in floor_members().items()}   # 이미 다른 층에 앉은 세션 → 그 층 이름
    seats = {}   # 이번 요청에서 앉힌 세션 → 층(같은 세션을 두 층에 앉히지 않게)
    # 이번에 정할 총괄(안 보내면 지금 총괄)은 층의 자리에 앉힐 수 없고, 거꾸로 이미 층에 앉은 세션은 총괄로 정할 수 없어요
    cur = boss_sid()
    bosses = {boss} if boss else {cur} if cur else set()
    if boss and boss in seated:
        raise ApiError(400, f"총괄로 고른 세션은 이미 '{seated[boss]}' 층의 자리에 앉아 있어요. 그 층의 ‘팀원 고치기’에서 먼저 빼거나 다른 세션을 골라 주세요")
    good, errors, order, fresh, groups = [], [], {}, [], {}
    for i, f in enumerate(floors):
        label = f["id"][:40] if isinstance(f, dict) and isinstance(f.get("id"), str) and f["id"] else f"{i + 1}번째 층"
        order.setdefault(label, i)
        try:
            if not isinstance(f, dict):
                raise ApiError(400, "층 정보 모양이 이상해요")
            name = f.get("name").strip() if isinstance(f.get("name"), str) else ""
            if SURROGATE.search(name):
                raise ApiError(400, "팀 이름에 쓸 수 없는 글자가 있어요(잘린 이모지 같은 글자). 이름을 고쳐 주세요")
            if not 0 < len(name) <= 30 or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
                raise ApiError(400, "팀 이름은 한 줄로 1~30자예요")
            if any(isinstance(v, str) and SURROGATE.search(v) for v in (f.get("id"), f.get("folder"), f.get("prefix"), f.get("group"))):
                raise ApiError(400, "층 정보에 쓸 수 없는 글자가 있어요")
            # members(팀장이 맨 앞인 목록)가 있으면 그것, 없으면 예전 판의 roles 묶음(네 자리)
            listed = f.get("members") is not None
            if listed:
                members = check_members(f["members"])
            else:
                members = members_of_roles(f.get("roles") if f.get("roles") is not None else {})
            check_seats(members, seated, seats, bosses)
            new = f.get("newFolder")
            if new not in (None, True, False):
                raise ApiError(400, "newFolder는 true나 false예요")
            grp = f.get("group")
            if grp not in (None, "") and not (isinstance(grp, str) and GROUP_KEY.match(grp)):
                raise ApiError(400, "group(그룹 key) 모양이 이상해요")
            # newFolder: true면 folder 대신 ~/agencity-teams/<id>를 새로 만들어 써요(층을 실제로 만들 때만 만들어요)
            folder = plan_new_folder(f, taken, {g["id"] for g in good}) if new is True else check_folder(f.get("folder"), detected)
            # id·이름·머리글·이미 있는 층인지는 new_team.py가 물어볼 때와 같은 기준으로 봐요
            g = {"id": f.get("id"), "name": f.get("name"), "folder": folder, "prefix": f.get("prefix") or None}
            # members로 보내면 팀원 목록이 곧 그 목록이에요. 예전 roles 묶음이면 0.4.1처럼 보내요: 이미 있던 team.json이면
            # 다른 자리는 그대로 두고 보낸 세션 id만 채워요(new_team.py의 합치기)
            if listed:
                g["members"] = members
            else:
                g["roles"] = {m["role"]: m["sessionId"] for m in members}
            good.append(g)
            for m in members:
                if m["sessionId"]:
                    seats.setdefault(m["sessionId"], name)
            if new is True:
                fresh.append((g, label))
            # 같은 id가 여럿이면 new_team.py는 앞의 것만 만들어요. 폴더 없이 만든 세션 묶음은 늘 다시 고를 수 있게 적지 않아요
            groups.setdefault(label, grp if grp and grp != "scratch" else None)
        except ApiError as e:
            errors.append({"id": label, "error": e.msg})
    made = {}
    for g, label in fresh:
        try:
            made[label] = make_new_folder(g["folder"])
        except (ApiError, OSError) as e:
            good.remove(g)
            msg = e.msg if isinstance(e, ApiError) else f"새 폴더(~/{NEW_HOME}/{g['id']})를 만들지 못했어요({e.strerror or type(e).__name__})"
            errors.append({"id": label, "error": msg})
    created = []
    try:
        if good or boss:
            spec = {"boss": boss or None, "dropDemo": drop_demo, "floors": good}
            try:
                r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "bin", "new_team.py"), "--spec", "-"], cwd=HERE,
                                   input=json.dumps(spec, ensure_ascii=False), capture_output=True, text=True, timeout=60)
            except (OSError, UnicodeError, subprocess.TimeoutExpired):
                raise ApiError(500, "층을 만드는 도우미(bin/new_team.py)를 실행하지 못했어요")
            res = last_json(r.stdout)
            if not isinstance(res, dict):
                raise ApiError(500, "층을 만들지 못했어요: " + (last_line(r.stderr) or "알 수 없는 오류"))
            if not res.get("ok"):
                raise ApiError(409, str(res.get("error") or "층을 만들지 못했어요"))
            for c in res.get("created") or []:
                if isinstance(c, dict):
                    o = c.get("office")
                    o = o if isinstance(o, str) and o.startswith("/") else None
                    # 팀원은 실제로 쓴 team.json에서 읽어요(roles 묶음으로 이미 있던 사무실에 합쳤으면 그대로 둔 자리도 들어 있어요)
                    ms = office_members(o) if o else None
                    created.append(dict({"id": c.get("id"), "floor": c.get("floor"), "folder": show_path(os.path.dirname(o)) if o else None,
                                         "members": ms}, **away_of(ms, o, where)))
            errors += [{"id": str(e.get("id"))[:40], "error": str(e.get("error"))} for e in res.get("errors") or [] if isinstance(e, dict)]
    finally:
        done = {c["id"] for c in created}
        for label, dirs in made.items():
            if label not in done:
                drop_dirs(dirs)
    remember_groups({c["id"] for c in created if c.get("id")}, {groups[c["id"]]: c["id"] for c in created if groups.get(c["id"])})
    errors.sort(key=lambda e: order.get(e["id"], len(floors)))   # 보낸 순서대로
    out = {"ok": True, "created": created, "errors": errors}
    if errors:
        msg = f"{len(errors)}개 층을 만들지 못했어요: " + " / ".join(f"{e['id']} — {e['error']}" for e in errors[:3])
        if not created and not boss:
            raise ApiError(400, msg, {"created": [], "errors": errors})
        out["error"] = msg
    return out


# 팀원 고치기 ---------------------------------------------------------------

def office_members(office):
    """팀 사무실 폴더의 team.json 팀원 [{role, sessionId}](역할 이름으로 못 쓰는 줄은 빼요). 못 읽으면 None."""
    try:
        team = load_json(os.path.join(office, "team.json"))
        ms = team.get("members") if isinstance(team, dict) else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not isinstance(ms, list):
        return None
    return [{"role": m["role"], "sessionId": m["sessionId"] if SESSION_ID.match(str(m.get("sessionId") or "")) else None}
            for m in ms if isinstance(m, dict) and is_role(m.get("role"))]


def floor_team(t):
    """층의 team.json 팀원(office_members). 못 읽으면 None."""
    try:
        office = os.path.realpath(os.path.join(HERE, t["office"]))
    except (KeyError, TypeError, ValueError):
        return None
    return office_members(office)


def status_file(base, role, name):
    """새 자리의 상태 파일(status/<역할>.json). 있으면 그대로 둬요."""
    sp = os.path.join(base, "status", role + ".json")
    if not os.path.lexists(sp):
        write_json(sp, {"name": name, "role": role, "state": "대기", "task": "", "say": "", "updated": now()})


def rename_pairs(old_rows, members, hints=()):
    """이름을 바꾼 자리 [(예전 이름, 새 이름, 예전 줄)]. 예전 이름이 새 목록에 없을 때만이에요(대소문자 무시).
    어느 자리였는지는 1) 화면이 알려 준 예전 이름(hints[i], members[i]의 was) 2) 없으면 같은 세션이 앉아 있던 예전 자리로 알아봐요.
    대소문자만 바꾼 이름(qa → QA)도 넣어요(파일 이름을 맞추려고)."""
    by_key = {}
    for m in old_rows if isinstance(old_rows, list) else []:
        if isinstance(m, dict) and is_role(m.get("role")) and m["role"].casefold() not in by_key:
            by_key[m["role"].casefold()] = m
    pairs = [(by_key[m["role"].casefold()]["role"], m["role"], by_key[m["role"].casefold()]) for m in members
             if m["role"].casefold() in by_key and by_key[m["role"].casefold()]["role"] != m["role"]]
    free = {k: o for k, o in by_key.items() if k not in {m["role"].casefold() for m in members}}   # 새 목록에서 빠진 예전 자리
    todo = [(i, m) for i, m in enumerate(members) if m["role"].casefold() not in by_key]           # 새 이름의 자리
    done = set()
    for i, m in todo:
        w = hints[i] if i < len(hints) else None
        k = unicodedata.normalize("NFC", w.strip()).casefold() if isinstance(w, str) else None
        if k in free:
            o = free.pop(k)
            pairs.append((o["role"], m["role"], o))
            done.add(i)
    for i, m in todo:
        k = next((k for k, o in free.items() if m["sessionId"] and o.get("sessionId") == m["sessionId"]), None) if i not in done else None
        if k:
            o = free.pop(k)
            pairs.append((o["role"], m["role"], o))
    return pairs


def relink(path, target):
    tmp = f"{path}.tmp{os.getpid()}{threading.get_ident()}"
    os.symlink(target, tmp)
    os.replace(tmp, path)


def forward_link(path):
    """이름을 바꾼 자리의 예전 대화 파일 이름에 남겨 둔 링크(같은 chat 폴더의 <새 이름>.jsonl을 가리켜요)인지."""
    try:
        t = os.readlink(path)
    except OSError:
        return False
    return "/" not in t and t.endswith(".jsonl")


def move_seat_files(base, pairs, tname):
    """이름을 바꾼 자리의 대화(chat/<이름>.jsonl)·상태(status/<이름>.json) 파일을 새 이름으로 옮겨요(지우지 않아요).
    새 이름의 파일이 이미 있으면(예전에 뺀 자리 이름을 다시 쓴 경우 등) 그 자리는 옮기지 않고 kept로 알려요.
    옮긴 대화 파일 자리에는 새 파일을 가리키는 링크를 남겨요: 이미 오가는 답(예전 이름으로 say.sh를 불러요)도 새 자리 대화에 붙어요.
    (옮긴 것 [{from, to}], 못 옮긴 것 [{from, to}])을 돌려줘요."""
    moved, kept = [], []
    cdir = os.path.join(base, "chat")
    for a, b, _ in pairs:
        files = [(os.path.join(base, sub, a + ext), os.path.join(base, sub, b + ext)) for sub, ext in (("chat", ".jsonl"), ("status", ".json"))]
        files = [(s, d) for s, d in files if os.path.isfile(s) and not os.path.islink(s)]
        if not files:
            continue

        def same(s, d):   # 대소문자만 바꾼 이름이면 맥 디스크에서는 같은 파일이에요
            try:
                return os.path.samefile(s, d)
            except OSError:
                return False
        if any(os.path.lexists(d) and not (os.path.islink(d) and forward_link(d)) and not same(s, d) for s, d in files):
            kept.append({"from": a, "to": b})
            continue
        try:
            for s, d in files:
                if os.path.islink(d):
                    os.unlink(d)   # 예전에 남긴 이어 주는 링크예요(대화 원본이 아니에요)
                os.replace(s, d)
            sp = os.path.join(base, "status", b + ".json")
            if any(d == sp for _, d in files):
                try:
                    st = load_json(sp)
                    if isinstance(st, dict):
                        st["role"] = b
                        if st.get("name") == f"{tname} {a}":
                            st["name"] = f"{tname} {b}"
                        write_json(sp, st)
                except (OSError, ValueError):
                    pass
            if any(d == os.path.join(cdir, b + ".jsonl") for _, d in files):
                for n in os.listdir(cdir):   # 더 예전 이름에서 이어 주던 링크도 새 파일로
                    p = os.path.join(cdir, n)
                    if os.path.islink(p) and os.readlink(p) == a + ".jsonl":
                        relink(p, b + ".jsonl")
                if not os.path.lexists(os.path.join(cdir, a + ".jsonl")):
                    os.symlink(b + ".jsonl", os.path.join(cdir, a + ".jsonl"))
        except OSError:
            kept.append({"from": a, "to": b})
            continue
        moved.append({"from": a, "to": b})
    return moved, kept


def drop_forward_links(base, roles):
    """지금 자리 이름의 대화 파일이 예전 이름 바꾸기 때 남긴 링크면 치워요(그 이름의 새 자리는 새 대화로 시작해요)."""
    for r in roles:
        p = os.path.join(base, "chat", r + ".jsonl")
        if os.path.islink(p) and forward_link(p):
            try:
                os.unlink(p)
            except OSError:
                pass


def api_setup_members(body):
    """한 층의 팀원 목록을 바꿔요: {team, members: [{role, sessionId|null, was?}]}(맨 앞은 팀장).
    새 역할은 상태 파일을 만들고, 뺀 팀원의 대화·상태 파일은 지우지 않아요(다시 넣으면 이어서 보여요).
    자리 이름을 바꾸면(was: 그 자리의 예전 이름, 없으면 같은 세션이 앉아 있던 예전 자리) 대화·상태 파일도 새 이름으로 옮겨요."""
    tid = body.get("team")
    if not isinstance(tid, str) or not SAFE_ID.match(tid):
        raise ApiError(400, "층(team) id가 이상해요")
    members = check_members(body.get("members"))
    hints = [m.get("was") for m in body["members"]]   # check_members가 모양을 봤어요(같은 순서)
    with TEAM_LOCK:
        t = next((t for t in real_teams() if t["id"] == tid), None)
        if t is None:
            raise ApiError(404, "그런 층이 없어요")
        if is_example(t):
            raise ApiError(409, "예시 팀은 고칠 수 없어요. 내 층을 만든 뒤 고쳐 주세요")
        if os.path.realpath(os.path.join(HERE, t["office"])) not in office_roots():
            raise ApiError(409, "이 층의 팀 사무실 폴더를 쓸 수 없어요(링크로 이어졌거나 에이전시티 폴더를 품고 있어요)")
        base = os.path.realpath(os.path.join(HERE, t["office"]))
        tj = os.path.join(base, "team.json")
        try:
            team = load_json(tj)
        except (OSError, ValueError):
            raise ApiError(409, "이 층의 team.json을 읽지 못했어요. 파일을 고친 뒤 다시 해 주세요")
        if not isinstance(team, dict) or not isinstance(team.get("members", []), list):
            raise ApiError(409, "이 층의 team.json 모양이 이상해요(members가 목록이어야 해요)")
        names = {x["id"]: x.get("name") or x["id"] for x in real_teams()}
        seated = {sid: names.get(o, o) for sid, o in floor_members().items() if o != tid}
        cur = boss_sid()
        check_seats(members, seated, {}, {cur} if cur else ())
        old = {}
        for m in team.get("members", []):
            if isinstance(m, dict) and isinstance(m.get("role"), str):
                old.setdefault(unicodedata.normalize("NFC", m["role"]).casefold(), m)
        tname = str(team.get("team") or t.get("name") or tid)
        pairs = rename_pairs(team.get("members", []), members, hints)
        was = {b: (a, o) for a, b, o in pairs}   # 새 이름 → (예전 이름, 예전 줄)
        rows = []
        for m in members:
            a, prev = was.get(m["role"], (None, old.get(m["role"].casefold())))
            row = dict(prev) if prev else {"name": f"{tname} {m['role']}", "title": f"{tname} · {m['role']}"}
            if a:   # 이름을 바꾼 자리: 저절로 지은 이름·제목이면 새 이름으로
                for k, sep in (("name", " "), ("title", " · ")):
                    if row.get(k) == f"{tname}{sep}{a}":
                        row[k] = f"{tname}{sep}{m['role']}"
            row.update(role=m["role"], sessionId=m["sessionId"])
            rows.append(row)
        before = [m.get("role") for m in team.get("members", []) if isinstance(m, dict)]
        team["members"] = rows
        write_json(tj, team)
        moved, kept = move_seat_files(base, pairs, tname)
        drop_forward_links(base, [x["role"] for x in rows])
        for row in rows:
            status_file(base, row["role"], str(row.get("name") or f"{tname} {row['role']}"))
    renamed = {a for a, _, _ in pairs}
    gone = [r for r in before if isinstance(r, str) and r not in [x["role"] for x in rows] and r not in renamed]
    log(base, "팀 전체", "설정", "팀원을 고쳤어요: " + " · ".join(x["role"] for x in rows)
        + (f" (이름 바꾼 자리: {', '.join(f'{a}→{b}' for a, b, _ in pairs)})" if pairs else "")
        + (f" (뺀 자리: {', '.join(gone)})" if gone else ""))
    where = {s["sessionId"]: s for p in claude_projects(True) for s in p["sessions"]}
    out = [{k: row.get(k) for k in ("role", "name", "title", "sessionId")} for row in rows]
    return dict({"ok": True, "team": tid, "members": out, "moved": moved, "kept": kept}, **away_of(members, base, where))


# 공개 범위와 공개하기 -------------------------------------------------------

def load_public():
    """public.json(없거나 깨졌으면 {})."""
    try:
        cur = load_json(PUBLIC)
    except (OSError, ValueError):
        return {}
    return cur if isinstance(cur, dict) else {}


def saved_levels(s, tids):
    """층마다 지금 공개 범위. 실제로 나가는 걸 정하는 public.json(손으로 고친 것도)이 먼저고,
    거기 없는 층은 setup.json에 저장한 값, 둘 다 없으면 비공개예요. public.json의 name은 names, tour는 tour, building은 building."""
    pub = load_public().get("floors")
    pub = pub if isinstance(pub, dict) else {}
    vis = s.get("visibility") if isinstance(s.get("visibility"), dict) else {}
    out = {}
    for tid in tids:
        c = pub.get(tid)
        if isinstance(c, dict):
            out[tid] = LEVEL_OF.get(c.get("public"), "private")
        else:
            out[tid] = vis[tid] if vis.get(tid) in LEVELS else "private"
    return out


def public_digest(cur=None):
    """도시에 나가는 설정의 지문: public.json의 login·profile·공개 층(name·tour)과 그 층들의 org.json 층 번호.
    마지막으로 올린 것과 지금 설정이 같은지 볼 때 써요. 책상 상태처럼 늘 바뀌는 값은 넣지 않아요."""
    cur = load_public() if cur is None else cur
    fl = cur.get("floors") if isinstance(cur.get("floors"), dict) else {}
    out = {k: v for k, v in fl.items() if isinstance(v, dict) and v.get("public") in ("name", "tour")}
    nums = {t["id"]: t.get("floor") for t in real_teams() if t["id"] in out}
    doc = {"login": cur.get("login"), "profile": cur.get("profile"), "floors": out, "org": nums}
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def note_legacy(s):
    """예전 판(터미널의 office_public.py)으로 공개해 뒀을 수 있는 설치본: 앱이 공개 범위를 저장한 적이 없는데
    public.json에 공개 층(name·tour)이 있으면 '올린 적 있음(내용은 모름)'으로 적어 둬요. 그래야 모두 비공개로 바꾼 뒤에도 내릴 수 있어요.
    s를 고쳤으면 True."""
    if "published" in s or "visibility" in s:
        return False
    fl = load_public().get("floors")
    if isinstance(fl, dict) and any(isinstance(c, dict) and c.get("public") in ("name", "tour") for c in fl.values()):
        s["published"] = {"t": None, "legacy": True}
        return True
    return False


def published_state(s):
    """마지막으로 도시에 올린 것: {t, current(지금 설정과 같은지, 모르면 None), floors(올린 층 수)} 또는 올린 적 없으면 None."""
    p = s.get("published")
    if not isinstance(p, dict):
        return None
    h = p.get("hash")
    n = p.get("floors")
    return {"t": p.get("t") if isinstance(p.get("t"), str) else None,
            "current": (h == public_digest()) if isinstance(h, str) and h else None,
            "floors": n if isinstance(n, int) and not isinstance(n, bool) else None}


def write_public(vis, teams, gh, intro):
    """공개 범위를 public.json(bin/office_public.py가 읽는 파일)에 옮겨요. 손으로 적은 층 이름·소개는 두고
    (비공개로 바꾼 층도 지우지 않고 "public": "private"로만 바꿔요. office_public.py는 name·tour만 내보내요),
    업무판(board)·지금 하는 일(tasks)은 켜지 않아요."""
    cur = {}
    if os.path.exists(PUBLIC):
        try:
            cur = load_json(PUBLIC)
        except (OSError, ValueError):
            shutil.copy(PUBLIC, PUBLIC + ".bak")   # 깨진 파일은 남겨 두고 새로 써요
        cur = cur if isinstance(cur, dict) else {}
    old = cur.get("floors") if isinstance(cur.get("floors"), dict) else {}
    floors = {}
    for tid, t in teams.items():
        level = vis.get(tid, "private")
        level = level if level in PUBLIC_OF else "private"
        c = dict(old[tid]) if isinstance(old.get(tid), dict) else {}
        c["public"] = PUBLIC_OF[level]
        if level in OUT_LEVELS and not str(c.get("name") or "").strip():
            c["name"] = one_line(t.get("name") or tid, 40)
        c.update(tasks=False, board=False)
        floors[tid] = c
    prof = dict(cur["profile"]) if isinstance(cur.get("profile"), dict) else {}
    if intro is not None:
        prof["intro"] = intro
    login = gh["login"] if gh else str(cur.get("login") or "")
    gist = str(cur.get("gist") or "")
    write_json(PUBLIC, dict(cur, login=login if LOGIN_RE.match(login) else "", gist=gist if GIST_RE.match(gist) else "",
                            profile=prof, floors=floors))


def api_setup_visibility(body):
    vis = body.get("visibility")
    if not isinstance(vis, dict) or len(vis) > 100:
        raise ApiError(400, "공개 범위 모양이 이상해요")
    teams = {t["id"]: t for t in real_teams()}
    for k, v in vis.items():
        if k not in teams:
            raise ApiError(400, f"없는 층이에요: {one_line(k, 40)}")
        if v not in LEVELS:
            raise ApiError(400, "공개 범위는 private·building·names·tour 중 하나예요")
    intro = one_line(text_of(body, "intro", 120, required=False), 120) if body.get("intro") is not None else None
    with SETUP_LOCK:
        s = load_setup()
        note_legacy(s)                              # 처음 저장하기 전에: 예전에 터미널로 올려 둔 게 있을 수 있는지
        merged = saved_levels(s, list(teams))       # 보내지 않은 층은 지금 실제 범위(public.json)를 그대로 둬요
        merged.update(vis)
        write_public(merged, teams, github_state(s), intro)
        s["visibility"] = merged
        write_json(SETUP, s)
    return {"ok": True}


def api_setup_publish(body):
    """공개 요약을 내 token-meter gist에 올려요({preview: true}면 올리지 않고 나갈 내용만 보여 줘요)."""
    preview = body.get("preview") is True
    gh = github_state()
    if not gh:
        raise ApiError(409, "먼저 GitHub에 로그인해 주세요")
    if not os.path.isfile(PUBLIC):
        raise ApiError(409, "먼저 공개 범위를 정해 주세요")
    with SETUP_LOCK:
        try:
            cur = load_json(PUBLIC)
        except (OSError, ValueError):
            raise ApiError(409, "public.json을 읽지 못했어요. 공개 범위를 다시 저장해 주세요")
        if isinstance(cur, dict) and cur.get("login") != gh["login"]:   # 로그인을 바꿨으면 그 아이디로
            cur["login"] = gh["login"]
            write_json(PUBLIC, cur)
        digest = public_digest(cur if isinstance(cur, dict) else {})   # 올라가는 설정의 지문(나중에 '예전 내용'인지 볼 때)
    try:
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "bin", "office_public.py")] + ([] if preview else ["--publish", "--yes"]),
                           cwd=HERE, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise ApiError(502, "공개 도우미(bin/office_public.py)가 끝나지 않았어요. 잠시 뒤 다시 해 주세요")
    if r.returncode != 0:
        raise ApiError(409, last_line(r.stderr) or "올리지 못했어요")
    notes = [one_line(x[2:], 200) for x in r.stderr.splitlines() if x.startswith("· ")]
    if preview:
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            raise ApiError(500, "미리보기를 만들지 못했어요")
        return {"ok": True, "preview": doc, "notes": notes}
    res = last_json(r.stdout)
    if not isinstance(res, dict) or res.get("ok") is not True:
        raise ApiError(500, "올렸는지 확인하지 못했어요. gist를 직접 확인해 주세요")
    url = str(res.get("url") or "")
    n = res.get("floors") if isinstance(res.get("floors"), int) and not isinstance(res.get("floors"), bool) else None
    gist = str(res.get("gist") or "")
    with SETUP_LOCK:
        s = load_setup()
        s["published"] = {"t": now(), "gist": gist if GIST_RE.match(gist) else "", "hash": digest, "floors": n}
        write_json(SETUP, s)
    out = {"ok": True, "notes": notes, "floors": n}
    if re.match(r"^https://gist\.github\.com/[\w./-]+$", url):
        out["url"] = url
    return out


# 상태와 끝 -----------------------------------------------------------------

def api_setup_state(body):
    teams = real_teams()
    with SETUP_LOCK:
        s = load_setup()
        changed = note_legacy(s)
        if not isinstance(s.get("done"), bool):
            # 처음 물을 때 정해 둬요: 예전 설치본(이미 내 층이 있음)은 설정을 마친 걸로, 새 설치본은 처음 설정부터.
            s["done"] = any(not is_example(t) for t in teams)
            changed = True
        if changed:
            write_json(SETUP, s)
    done = s["done"]
    prof = load_public().get("profile")   # 저장해 둔 소개 한 줄(설정을 다시 열면 칸에 보여 줘요)
    intro = one_line(prof.get("intro"), 120) if isinstance(prof, dict) and isinstance(prof.get("intro"), str) else ""
    return {"ok": True, "done": done, "platform": platform_name(), "version": VERSION, "intro": intro,
            "github": github_state(s), "deviceFlow": bool(client_id()), "ghAvailable": bool(shutil.which("gh")),
            "claude": {"app": claude_app(), "sessions": len(claude_sessions())},
            "boss": boss_sid() is not None,   # 자리 표시용이 아닌 진짜 총괄 세션이 있는지
            "floors": [{"id": t["id"], "name": str(t.get("name") or t["id"]), "floor": t.get("floor"), "folder": t.get("folder"),
                        "example": is_example(t), "members": floor_team(t)} for t in teams],
            "roleSuggestions": ROLE_SUGGEST, "maxMembers": MAX_MEMBERS,
            "visibility": saved_levels(s, [t["id"] for t in teams]),
            "published": published_state(s)}


def api_setup_done(body):
    done = body.get("done")
    if not isinstance(done, bool):
        raise ApiError(400, "done은 true나 false예요")
    with SETUP_LOCK:
        s = load_setup()
        s["done"] = done
        write_json(SETUP, s)
    return {"ok": True}


ROUTES = {"/api/say": api_say, "/api/meeting/start": api_meeting_start, "/api/meeting/mode": api_meeting_mode,
          "/api/meeting/end": api_meeting_end, "/api/meeting/close": api_meeting_close, "/api/decide": api_decide,
          "/api/setup/state": api_setup_state, "/api/setup/github/start": api_setup_github_start,
          "/api/setup/github/poll": api_setup_github_poll, "/api/setup/github/gh": api_setup_github_gh,
          "/api/setup/github/logout": api_setup_github_logout, "/api/setup/claude": api_setup_claude,
          "/api/setup/floors": api_setup_floors, "/api/setup/members": api_setup_members, "/api/setup/visibility": api_setup_visibility,
          "/api/setup/publish": api_setup_publish, "/api/setup/done": api_setup_done}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, fmt, *args):
        # 대화 파일이 아직 없을 때 나는 404는 흔해서 적지 않아요(보낸 요청·거절·서버 오류만 적어요).
        if self.command == "POST" or (len(args) > 1 and (str(args[1])[:1] == "5" or str(args[1]) == "403")):
            super().log_message(fmt, *args)

    def host_ok(self):
        if self.headers.get("Host", "") in HOSTS:
            return True
        self.send_error(403, "Host not allowed")
        return False

    def allowed(self):
        """보여 줘도 되는 파일만: org.json, hq/, teams/<id>/ 아래(실제 팀 사무실 안)."""
        real = os.path.realpath(self.translate_path(self.path))
        # 로그인 토큰이 있는 설정 폴더는 어떤 링크로 와도 안 돼요
        if real in SECRET_FILES or any(under(real, d) and not under(HERE, d) for d in SECRET_DIRS):
            return False
        if real in (os.path.join(HERE, "org.json"), os.path.join(HERE, "city.html")):
            return True
        for root in [HQ, os.path.join(HERE, "examples", "city")] + office_roots():
            if under(real, root):
                return True
        return False

    def send_json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        super().end_headers()

    def do_GET(self):
        if not self.host_ok():
            return
        u = urlsplit(self.path)
        if u.path in ("/", "/index.html"):
            if self.headers.get("Sec-Fetch-Dest", "") in ("iframe", "frame", "embed", "object"):
                self.send_error(403)
                return
            try:
                with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                    page = f.read().replace("@@OFFICE_TOKEN@@", TOKEN)
            except OSError:
                self.send_error(404)
                return
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/api/state":
            self.send_json(200, dict(api_state(), version=VERSION, home=HOME_ID))
            return
        if u.path == "/api/outbox/check":
            self.send_json(200, api_outbox_check(parse_qs(u.query)))
            return
        if u.path.startswith("/api/") or not self.allowed():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if self.host_ok() and self.allowed():
            super().do_HEAD()
        elif self.headers.get("Host", "") in HOSTS:
            self.send_error(404)

    def do_POST(self):
        if not self.host_ok():
            return
        path = urlsplit(self.path).path
        fn = ROUTES.get(path)
        if not fn:
            self.send_json(404, {"ok": False, "error": "없는 주소예요"})
            return
        if self.headers.get("Origin") not in ORIGINS:
            self.send_json(403, {"ok": False, "error": "이 페이지에서만 보낼 수 있어요"})
            return
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self.send_json(415, {"ok": False, "error": "JSON만 받아요"})
            return
        if not secrets.compare_digest(self.headers.get("X-Office-Token", ""), TOKEN):
            self.send_json(403, {"ok": False, "error": "열쇠가 맞지 않아요. 페이지를 새로고침해 주세요"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.send_json(413, {"ok": False, "error": "너무 커요"})
            return
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"ok": False, "error": "JSON을 읽지 못했어요"})
            return
        try:
            res = fn(body)
            if not path.startswith("/api/setup/"):   # 처음 설정 답에는 전달 상태를 붙이지 않아요
                res.update({k: v for k, v in api_state().items() if k != "ok"})
            self.send_json(200, res)
        except ApiError as e:
            self.send_json(e.code, dict(e.extra, ok=False, error=e.msg))
        except Exception as e:  # noqa: BLE001 — 서버가 죽지 않게
            self.send_json(500, {"ok": False, "error": f"서버 오류: {type(e).__name__}"})


def main():
    os.makedirs(OUTBOX, exist_ok=True)
    os.makedirs(HQ, exist_ok=True)
    os.makedirs(os.path.join(HERE, "teams"), exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)

    def stop(*_):   # 종료 신호도 Ctrl-C처럼 받아서 outbox/.port를 치우고 끝내요
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    with open(PORT_FILE + ".tmp", "w") as f:
        f.write(str(PORT))
    os.replace(PORT_FILE + ".tmp", PORT_FILE)
    print(f"에이전시티: http://127.0.0.1:{PORT}  (끄려면 Ctrl-C)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            with open(PORT_FILE) as f:
                mine = f.read().strip() == str(PORT)
            if mine:
                os.remove(PORT_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
