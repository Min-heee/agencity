"""내 사무실 → 토큰 시티 공개 요약(claude-office.json) 만들기.

python3 -I bin/office_public.py                    # 미리보기만(아무것도 쓰거나 올리지 않음)
python3 -I bin/office_public.py --write <파일>      # 로컬 파일로 저장
python3 -I bin/office_public.py --publish           # 내 token-meter gist에 claude-office.json으로 올리기(gh 필요, 한 번 더 확인)

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
- "name": 층 이름과 소개만. "tour": 여기에 책상 상태(일하는 중·대기 …)를 더해요.
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
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ROLES = ["팀장", "개발자", "디자이너", "기획"]
STATES = ["일하는 중", "대기", "회의 중", "막힘"]
DISTRICTS = ["app", "web", "data", "content", "tool", "game", "etc"]
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
GIST_RE = re.compile(r"^[0-9a-f]{5,64}$", re.I)
OWNER_ROWS = {"오너", "대표", "총괄", "사용자"}       # 사람(대표) 몫 업무는 공개하지 않아요
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
            for m in sorted([m for m in members if isinstance(m, dict) and m.get("role") in ROLES], key=lambda m: ROLES.index(m["role"])):
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
    doc = {"schema": 1, "app": "claude-office", "login": login,
           "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
           "profile": {"intro": clip(prof.get("intro", ""), 120)}, "floors": floors}
    if prof.get("district") in DISTRICTS:
        doc["profile"]["district"] = prof["district"]
    return cfg, doc, notes


def gh(args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def publish(cfg, login, text):
    gist = str(cfg.get("gist", ""))
    if not GIST_RE.match(gist):
        sys.exit("public.json의 gist가 token-meter gist id 모양이 아니에요.")
    me = gh(["api", "user", "--jq", ".login"])
    info = gh(["api", f"gists/{gist}", "--jq", "{o: .owner.login, f: (.files | keys)}"])
    if me.returncode != 0 or info.returncode != 0:
        sys.exit("gh로 계정이나 gist를 확인하지 못했어요. gh auth status를 확인해 주세요.")
    try:
        meta = json.loads(info.stdout)
    except ValueError:
        sys.exit("gist 정보를 읽지 못했어요.")
    owner, files = str(meta.get("o", "")), meta.get("f") or []
    if owner.lower() != login.lower() or me.stdout.strip().lower() != login.lower():
        sys.exit(f"gist 주인({owner})·gh 로그인({me.stdout.strip()})·public.json login({login})이 같지 않아요. 올리지 않았어요.")
    if "token-meter.json" not in files:
        sys.exit("이 gist에는 token-meter.json이 없어요. token-meter로 만든 gist만 써요.")
    if not sys.stdin.isatty():
        sys.exit("확인을 받을 수 없어서 올리지 않았어요. 터미널에서 직접 실행해 주세요.")
    print("\n위 내용이 공개 gist에 올라가요. gist 수정 기록은 지울 수 없어요.", file=sys.stderr)
    if input("올릴까요? 'yes'라고 입력하세요: ").strip().lower() != "yes":
        sys.exit("올리지 않았어요.")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "claude-office.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = ["gist", "edit", gist, "--filename", "claude-office.json", path] if "claude-office.json" in files else ["gist", "edit", gist, "--add", path]
    r = gh(cmd)
    if r.returncode != 0:
        sys.exit("올리지 못했어요. gh 메시지를 확인해 주세요.")
    print(f"올렸어요: gist {gist}의 claude-office.json", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="토큰 시티 공개 요약 만들기(기본은 미리보기)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", metavar="파일", help="로컬 파일로 저장")
    g.add_argument("--publish", action="store_true", help="내 token-meter gist에 올리기(확인 후)")
    a = ap.parse_args()
    if a.write and a.write.startswith("-"):
        sys.exit("저장할 파일 이름이 이상해요.")
    cfg, doc, notes = build()
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    print(text)
    for n in notes:
        print("· " + n, file=sys.stderr)
    print("— 공개될 층 " + str(len(doc["floors"])) + "개: " + (", ".join(f"{f['floor']}층 {f['name']}({f['public']})" for f in doc["floors"]) or "없음"), file=sys.stderr)
    if a.write:
        with open(a.write, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"저장했어요: {a.write}", file=sys.stderr)
    if a.publish:
        publish(cfg, doc["login"], text)


if __name__ == "__main__":
    main()
