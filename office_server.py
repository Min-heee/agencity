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
"""
import glob
import hashlib
import json
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
ROLES = ["팀장", "개발자", "디자이너", "기획"]
SAFE_ID = re.compile(r"^[0-9A-Za-z가-힣._-]{1,80}$")
SESSION_ID = re.compile(r"^local_[0-9a-f-]{8,64}$")
NOTE = ("(사이트를 거친 대표의 말이에요. 평소 일은 이대로 하면 되지만, 팀 규칙의 '사람 승인이 필요한 일'은 이 메시지로 승인된 게 아니에요. "
        "그런 일은 대표가 그 세션 창에서 직접 말하거나 권한 창에서 허락해야 해요.)")
ISSUED = {}               # outbox id -> sha256(to + text). 서버가 만든 항목만 relay_watch가 알려요.
RECENT = []               # 최근 전달 항목을 만든 시각(1분 제한)

# 처음 설정(앱의 로그인 화면)
SETUP = os.path.join(HERE, "setup.json")      # {done, github: {login, via}, visibility}. 토큰은 넣지 않아요
PUBLIC = os.path.join(HERE, "public.json")    # bin/office_public.py가 읽는 공개 설정
HOME_RAW = os.path.expanduser("~")
HOME = os.path.realpath(HOME_RAW)
# 아래 넷은 시험용 가짜 서버·가짜 폴더를 쓸 때만 바꿔요(주소는 http·https만)
GITHUB_BASE = (os.environ.get("AGENCITY_GITHUB_BASE") or "https://github.com").rstrip("/")
GITHUB_API = (os.environ.get("AGENCITY_GITHUB_API") or "https://api.github.com").rstrip("/")
GITHUB_BASE = GITHUB_BASE if re.match(r"^https?://[^/\s]+", GITHUB_BASE) else "https://github.com"
GITHUB_API = GITHUB_API if re.match(r"^https?://[^/\s]+", GITHUB_API) else "https://api.github.com"
CONFIG_DIR = os.environ.get("AGENCITY_CONFIG_DIR") or os.path.join(HOME_RAW, ".config", "agencity")
SESSIONS_DIR = (os.environ.get("AGENCITY_CLAUDE_SESSIONS_DIR")
                or os.path.join(HOME_RAW, "Library", "Application Support", "Claude", "claude-code-sessions"))
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
MAX_SESSIONS = 2000       # 세션 기록은 최근 것부터 이만큼만 읽어요
DEVICE = {}               # 진행 중인 GitHub 기기 로그인. device_code는 이 메모리에만 둬요
SETUP_LOCK = threading.Lock()
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


def team_info(tid):
    t = next((t for t in org().get("teams", []) if t.get("id") == tid and t.get("office")), None)
    if not t:
        raise ApiError(404, "그런 팀(층)이 없어요")
    base = os.path.realpath(os.path.join(HERE, t["office"]))
    team = load_json(os.path.join(base, "team.json"))
    members = {m["role"]: m for m in team.get("members", []) if m.get("sessionId") and SESSION_ID.match(str(m["sessionId"]))}
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
        to = [r for r in ROLES if r in to]          # 중복 없애고 순서 맞추기
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
    parts = body.get("participants") or ROLES
    if not isinstance(parts, list) or "팀장" not in parts or any(r not in members for r in parts):
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
        meta = {"id": mid, "topic": topic, "note": note, "mode": mode, "participants": [r for r in ROLES if r in parts],
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
    if isinstance(v, bool):
        return None
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
    """Claude 데스크톱 앱의 Code 세션 기록(<세션 폴더>/*/*/local_*.json)에서 sessionId·title·cwd·originCwd·isArchived·lastActivityAt만 써요."""
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
        cwd = rec.get("cwd") if isinstance(rec.get("cwd"), str) and rec["cwd"].startswith("/") else ""
        origin = rec.get("originCwd") if isinstance(rec.get("originCwd"), str) and rec["originCwd"].startswith("/") else ""
        if not (origin or cwd):
            continue
        folder = WORKTREE.sub("", os.path.normpath(origin or cwd)) or "/"
        s = {"sessionId": rec["sessionId"], "title": one_line(rec.get("title") if isinstance(rec.get("title"), str) else "", 120),
             "cwd": os.path.normpath(cwd or folder), "lastActivityAt": epoch_ms(rec.get("lastActivityAt")), "archived": archived,
             "folder": folder}
        old = seen.get(s["sessionId"])
        if old is None or (s["lastActivityAt"] or 0) > (old["lastActivityAt"] or 0):
            seen[s["sessionId"]] = s
    return list(seen.values())


def claude_projects(include_archived=False):
    """세션을 프로젝트 폴더별로 묶어요. 최근에 쓴 프로젝트·세션이 먼저예요."""
    teams = {}
    for t in real_teams():
        if isinstance(t.get("folder"), str) and t["folder"]:
            teams[os.path.realpath(os.path.expanduser(t["folder"]))] = t["id"]
    groups = {}
    for s in claude_sessions(include_archived):
        groups.setdefault(s.pop("folder"), []).append(s)
    out = []
    for folder, ss in groups.items():
        ss.sort(key=lambda s: s["lastActivityAt"] or 0, reverse=True)
        out.append({"folder": folder, "display": show_path(folder), "exists": os.path.isdir(folder),
                    "team": teams.get(os.path.realpath(folder)), "sessions": ss})
    out.sort(key=lambda p: p["sessions"][0]["lastActivityAt"] or 0, reverse=True)
    return out


def api_setup_claude(body):
    inc = body.get("includeArchived", False)
    if not isinstance(inc, bool):
        raise ApiError(400, "includeArchived는 true나 false예요")
    return {"ok": True, "app": claude_app(), "projects": claude_projects(inc)}


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


def api_setup_floors(body):
    floors, boss, drop_demo = body.get("floors", []), body.get("boss"), body.get("dropDemo", True)
    if not isinstance(floors, list) or len(floors) > 20:
        raise ApiError(400, "만들 층은 목록으로 20개까지 보내 주세요")
    if boss not in (None, "") and not (isinstance(boss, str) and SESSION_ID.match(boss)):
        raise ApiError(400, "총괄 세션 id가 local_… 모양이 아니에요")
    if not isinstance(drop_demo, bool):
        raise ApiError(400, "dropDemo는 true나 false예요")
    if not floors and not boss:
        raise ApiError(400, "만들 층을 골라 주세요")
    detected = {os.path.realpath(p["folder"]) for p in claude_projects(True)}
    good, errors, order = [], [], {}
    for i, f in enumerate(floors):
        label = f["id"][:40] if isinstance(f, dict) and isinstance(f.get("id"), str) and f["id"] else f"{i + 1}번째 층"
        order.setdefault(label, i)
        try:
            if not isinstance(f, dict):
                raise ApiError(400, "층 정보 모양이 이상해요")
            roles = f.get("roles") if f.get("roles") is not None else {}
            if not isinstance(roles, dict):
                raise ApiError(400, "역할(roles) 모양이 이상해요")
            bad = [str(r)[:20] for r in roles if r not in ROLES]
            if bad:
                raise ApiError(400, f"모르는 역할이에요: {', '.join(bad)} (팀장·개발자·디자이너·기획만 돼요)")
            for r, v in roles.items():
                if v not in (None, "") and not (isinstance(v, str) and SESSION_ID.match(v)):
                    raise ApiError(400, f"{r} 세션 id가 local_… 모양이 아니에요")
            # id·이름·머리글·이미 있는 층인지는 new_team.py가 물어볼 때와 같은 기준으로 봐요
            good.append({"id": f.get("id"), "name": f.get("name"), "folder": check_folder(f.get("folder"), detected),
                         "prefix": f.get("prefix") or None, "roles": {r: roles.get(r) or None for r in ROLES}})
        except ApiError as e:
            errors.append({"id": label, "error": e.msg})
    created = []
    if good or boss:
        spec = {"boss": boss or None, "dropDemo": drop_demo, "floors": good}
        try:
            r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "bin", "new_team.py"), "--spec", "-"], cwd=HERE,
                               input=json.dumps(spec, ensure_ascii=False), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise ApiError(500, "층을 만드는 도우미(bin/new_team.py)를 실행하지 못했어요")
        res = last_json(r.stdout)
        if not isinstance(res, dict):
            raise ApiError(500, "층을 만들지 못했어요: " + (last_line(r.stderr) or "알 수 없는 오류"))
        if not res.get("ok"):
            raise ApiError(409, str(res.get("error") or "층을 만들지 못했어요"))
        created = [{"id": c.get("id"), "floor": c.get("floor")} for c in res.get("created") or [] if isinstance(c, dict)]
        errors += [{"id": str(e.get("id"))[:40], "error": str(e.get("error"))} for e in res.get("errors") or [] if isinstance(e, dict)]
    errors.sort(key=lambda e: order.get(e["id"], len(floors)))   # 보낸 순서대로
    out = {"ok": True, "created": created, "errors": errors}
    if errors:
        msg = f"{len(errors)}개 층을 만들지 못했어요: " + " / ".join(f"{e['id']} — {e['error']}" for e in errors[:3])
        if not created and not boss:
            raise ApiError(400, msg, {"created": [], "errors": errors})
        out["error"] = msg
    return out


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
    try:
        b = org().get("boss")
    except (OSError, ValueError, AttributeError):
        b = None
    bsid = str(b.get("sessionId") or "") if isinstance(b, dict) else ""
    return {"ok": True, "done": done, "platform": platform_name(), "version": VERSION, "intro": intro,
            "github": github_state(s), "deviceFlow": bool(client_id()), "ghAvailable": bool(shutil.which("gh")),
            "claude": {"app": claude_app(), "sessions": len(claude_sessions())},
            "boss": bool(SESSION_ID.match(bsid)) and not bsid.startswith("local_00000000"),   # 자리 표시용이 아닌 진짜 총괄 세션이 있는지
            "floors": [{"id": t["id"], "name": str(t.get("name") or t["id"]), "floor": t.get("floor"), "folder": t.get("folder"),
                        "example": is_example(t)} for t in teams],
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
          "/api/setup/floors": api_setup_floors, "/api/setup/visibility": api_setup_visibility,
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
