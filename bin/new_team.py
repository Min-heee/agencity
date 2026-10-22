"""내 팀(층) 등록 도우미.

python3 bin/new_team.py                      # 물어보며 한 층씩 등록해요
python3 bin/new_team.py --spec <명세.json>    # 물어보지 않고 명세대로 여러 층을 등록해요(앱의 처음 설정 화면이 써요)
python3 bin/new_team.py --spec -             # 명세를 표준 입력으로 받아요

물어보는 것: 팀 id, 팀 이름, 프로젝트 폴더, 업무 번호 머리글, 기본 네 자리(팀장·개발자·디자이너·기획)의 Claude Code 세션 id(모르면 비워 둬요),
더 둘 역할(마케팅·QA처럼 쉼표로, 없으면 엔터)과 그 세션 id, 처음이면 예시 팀을 뺄지와 총괄 세션 id.
다 물어본 뒤에야 파일을 만들어요(중간에 멈추면 아무것도 안 바뀌어요).
하는 일:
  1) <프로젝트>/.office/ 팀 사무실 폴더를 만들어요(team.json, status/, board.md, log.jsonl, reports/, meetings/,
     approvals/, chat/, RULES.md). 이미 있으면 다른 파일은 그대로 두고, team.json의 이름·머리글과 새 자리·새로 적은 세션 id만 고쳐요
     (명세의 members로 보내면 팀원 목록을 그 목록으로 바꿔요). 자리마다 status/<역할>.json이 없으면 만들어요.
  2) .office/.gitignore(내용 '*')를 둬서, 저장소가 어떤 구조든(하위 폴더, worktree, submodule) 팀 기록이 커밋되지 않게 해요.
  3) teams/<id> 를 그 폴더에 연결해요.
  4) org.json에 다음 층으로 넣어요. 고치기 전 내용은 org.json.bak에 남겨요.
세션 id는 각 세션에서 "이 세션 id 알려 줘"라고 물으면 local_… 로 알려 줘요. 나중에 team.json에서 고쳐도 돼요.

명세(--spec)는 이런 모양이에요. 검사는 물어볼 때와 같고, 문제가 있는 층은 만들지 않고 errors에 적어요.
{"boss": "local_…" 또는 null, "dropDemo": true,
 "floors": [{"id": "shop", "name": "쇼핑몰팀", "folder": "/Users/me/shop", "prefix": "SH-"(없어도 돼요),
             "members": [{"role": "팀장", "sessionId": "local_…"}, {"role": "개발자", "sessionId": null},
                         {"role": "마케팅", "sessionId": "local_…"}]}]}
- members: 팀원 자리 목록. 맨 앞은 팀장(세션은 비워 둬도 돼요), 12자리까지예요. 역할 이름은 마음대로 짓되
  한글·영문·숫자로 12자까지(빈칸·/·. 없이, _ · - 는 돼요), 대표·총괄은 안 되고, 한 층 안에서 겹치지 않아요.
  한 세션은 한 자리에만, 한 층에만 앉혀요. 이미 있던 팀 사무실이면 team.json의 팀원 목록을 이 목록으로 바꿔요
  (빠진 팀원의 대화·상태 파일은 지우지 않아요).
- roles: 예전 모양({"팀장": "local_…", "개발자": null, "디자이너": null, "기획": null}). members가 없을 때만 봐요.
  네 자리를 늘 만들고, 이미 있던 팀 사무실이면 다른 자리는 두고 새로 적은 세션 id만 고쳐요.
- boss: 총괄 세션 id. 적으면 org.json의 총괄을 바꾸고, 비우면 그대로 둬요.
- dropDemo: 한 층이라도 만들면 예시 팀을 층 안내에서 빼요(기본 true).
결과는 표준 출력에 JSON 한 줄이에요: {"ok": true, "created": [{"id", "floor", "office"}], "errors": [{"id", "error"}]}
명세나 org.json을 읽지 못하면 {"ok": false, "error": "…"}를 내고 아무것도 바꾸지 않아요.
"""
import json
import os
import re
import shlex
import shutil
import sys
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LEAD = "팀장"
CLASSIC_ROLES = ["팀장", "개발자", "디자이너", "기획"]   # 물어볼 때 늘 묻는 네 자리, 예전 roles 모양의 자리
ROLE_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣_·-]{0,11}\Z")   # office_server.py와 같아요(파일 이름으로도 써요)
NOT_ROLES = ("대표", "총괄")
MAX_MEMBERS = 12
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,19}\Z")
SESSION_RE = re.compile(r"^local_[0-9a-f-]{8,64}\Z")
PREFIX_RE = re.compile(r"^[A-Z]{1,4}-\Z")
RESERVED = ("J-", "U-", "M-")   # 총괄 지시·사람이 시킨 일·회의 번호(docs/TEAM_RULES.md)
PLACEHOLDER = "local_00000000"
NOTHING = " 아무것도 바꾸지 않았어요."
MAX_SPEC = 64 * 1024


class TeamError(Exception):
    """여기서 멈춰야 하는 문제. 물어보는 방식은 이 글을 보여 주고 끝내요."""


def ask(q, default="", check=None, hint=""):
    while True:
        try:
            v = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
        except EOFError:
            sys.exit("\n입력이 끊겨서 멈췄어요. 아무것도 바꾸지 않았어요.")
        v = v or default
        if check is None or check(v):
            return v
        print("  " + (hint or "다시 입력해 주세요."))


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path, what):
    """있는 파일을 읽어요. 깨져 있으면 아무것도 바꾸지 않고 멈춰요."""
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except ValueError as e:
        raise TeamError(f"{what}을 읽지 못했어요: {path} ({e}). 고친 뒤 다시 실행해 주세요.{NOTHING}")
    except OSError as e:
        raise TeamError(f"{what}을 열지 못했어요: {path} ({e}).{NOTHING}")
    if not isinstance(obj, dict):
        raise TeamError(f"{what} 모양이 이상해요(맨 위가 {{…}}가 아니에요): {path}.{NOTHING}")
    return obj


def norm_dir(v, start):
    """입력한 폴더의 절대 경로. 상대 경로는 실행한 곳 기준이고, 끌어다 놓은 경로(\\ 이스케이프)나 따옴표도 받아요."""
    cands = [v]
    try:
        t = shlex.split(v)
        if len(t) == 1:
            cands.append(t[0])
    except ValueError:
        pass
    for c in cands:
        c = c.strip()
        p = os.path.join(start, os.path.expanduser(c))
        if c and os.path.isdir(p):
            return os.path.realpath(p)
    return None


def default_prefix(tid):
    base = re.sub("[^a-z]", "", tid).upper()[:2] or "T"
    if base + "-" in RESERVED:   # 한 글자 id가 j·u·m이면 JT-처럼
        base += "T"
    return base + "-"


def load_org():
    """org.json(없으면 예시)을 읽어요. 여기서는 아무 파일도 고치지 않아요."""
    if os.path.exists("org.json"):
        org = read_json("org.json", "org.json")
    else:
        org = read_json(os.path.join("examples", "org.example.json"), "예시 org.json")
    org.setdefault("teams", [])
    if not isinstance(org["teams"], list):
        raise TeamError(f"org.json의 teams가 목록([…])이 아니에요.{NOTHING}")
    return org


def check_project(org, proj):
    """proj(절대 경로)를 새 팀 프로젝트로 써도 되는지 보고, 팀 사무실(.office) 경로를 돌려줘요."""
    if proj == HERE or proj.startswith(HERE + os.sep):
        raise TeamError(f"에이전시티 폴더 안은 팀 프로젝트로 쓸 수 없어요.{NOTHING}")
    office = os.path.join(proj, ".office")
    # proj는 이미 실제 경로라 링크일 수 있는 건 .office뿐이에요. 링크면 사무실 서버가 그 대상 폴더를 보여 주게 되니 받지 않아요.
    if os.path.islink(office):
        raise TeamError(f"{office} 가 링크예요. 팀 사무실은 프로젝트 안의 진짜 폴더여야 해요.{NOTHING}")
    for t in org["teams"]:
        o = t.get("office") if isinstance(t, dict) else None
        if o and os.path.realpath(os.path.join(HERE, o)) == os.path.realpath(office):
            raise TeamError(f"이 프로젝트는 이미 '{t.get('name')}'({t.get('id')})로 등록돼 있어요.{NOTHING}")
    return office


def demo_teams(org):
    return [t for t in org["teams"] if isinstance(t, dict) and str(t.get("office") or "").startswith("examples/")]


def role_ok(v):
    """역할 이름으로 쓸 수 있으면 NFC로 맞춘 이름, 아니면 None."""
    if not isinstance(v, str):
        return None
    r = unicodedata.normalize("NFC", v.strip())
    return r if ROLE_RE.match(r) and r not in NOT_ROLES else None


ROLE_HINT = "역할 이름은 한글·영문·숫자로 12자까지예요(빈칸·/·. 없이, _ · - 는 돼요). 대표·총괄은 못 써요."


def parse_members(raw):
    """명세의 members 목록 → [{role, sessionId}]. office_server.py의 검사와 같아요."""
    if not isinstance(raw, list) or not raw:
        raise TeamError("members는 목록이어야 하고, 맨 앞은 팀장이에요.")
    if len(raw) > MAX_MEMBERS:
        raise TeamError(f"팀원은 한 층에 {MAX_MEMBERS}명까지예요(팀장 포함).")
    out, names, sids = [], set(), {}
    for m in raw:
        if not isinstance(m, dict):
            raise TeamError("팀원 모양이 이상해요({\"role\": …, \"sessionId\": …}).")
        r = role_ok(m.get("role"))
        if r is None:
            raise TeamError(ROLE_HINT)
        if r.casefold() in names:
            raise TeamError(f"이 층에 '{r}' 자리가 둘이에요. 역할 이름을 다르게 해 주세요.")
        names.add(r.casefold())
        v = m.get("sessionId")
        if v in (None, ""):
            v = ""
        elif not (isinstance(v, str) and SESSION_RE.match(v)):
            raise TeamError(f"{r} 세션 id가 local_… 모양이 아니에요.")
        elif v in sids:
            raise TeamError(f"같은 세션을 {sids[v]}·{r} 두 자리에 앉혔어요. 한 세션은 한 자리에만 앉혀요.")
        if v:
            sids[v] = r
        out.append({"role": r, "sessionId": v})
    if LEAD not in [m["role"] for m in out]:
        raise TeamError("팀장 자리가 없어요. 맨 앞에 팀장을 넣어 주세요(세션은 비워 둬도 돼요).")
    if out[0]["role"] != LEAD:
        raise TeamError("팀장 자리는 맨 앞이어야 해요.")
    return out


def seated_sessions(org):
    """내 층(예시 팀 빼고)에 이미 앉은 세션 id → 층 이름."""
    out = {}
    for t in org["teams"]:
        if not isinstance(t, dict) or not t.get("office") or str(t.get("office")).startswith("examples/"):
            continue
        try:
            with open(os.path.join(os.path.realpath(os.path.join(HERE, t["office"])), "team.json"), encoding="utf-8") as f:
                ms = json.load(f).get("members", [])
            for m in ms:
                if isinstance(m, dict) and isinstance(m.get("sessionId"), str) and SESSION_RE.match(m["sessionId"]):
                    out.setdefault(m["sessionId"], str(t.get("name") or t.get("id")))
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return out


def member_row(name, role, sid):
    return {"role": role, "name": f"{name} {role}", "title": f"{name} · {role}", "sessionId": sid or None}


def current_boss(org):
    """org.json에 정한 진짜 총괄 세션 id(자리 표시용 local_00000000…은 빼요). 없으면 ""."""
    boss = org.get("boss") if isinstance(org.get("boss"), dict) else {}
    sid = boss.get("sessionId")
    return sid if isinstance(sid, str) and SESSION_RE.match(sid) and not sid.startswith(PLACEHOLDER) else ""


def renamed_seats(old_team, members):
    """팀원 목록을 바꿀 때 이름만 바뀐 자리 [(예전 이름, 새 이름)]: 같은 세션이 앉아 있던 예전 자리가 새 목록에 없거나,
    대소문자만 바뀐 이름이에요(office_server.py의 rename_pairs와 같은 기준이에요. 화면이 알려 주는 was는 여기 없어요)."""
    old = old_team.get("members") if isinstance(old_team, dict) and isinstance(old_team.get("members"), list) else []
    by_key = {}
    for m in old:
        if isinstance(m, dict) and isinstance(m.get("role"), str) and role_ok(m["role"]) == m["role"]:
            by_key.setdefault(m["role"].casefold(), m)
    keys = {m["role"].casefold() for m in members}
    pairs = [(by_key[m["role"].casefold()]["role"], m["role"]) for m in members
             if m["role"].casefold() in by_key and by_key[m["role"].casefold()]["role"] != m["role"]]
    free = {k: o for k, o in by_key.items() if k not in keys}
    for m in members:
        if m["role"].casefold() in by_key or not m["sessionId"]:
            continue
        k = next((k for k, o in free.items() if o.get("sessionId") == m["sessionId"]), None)
        if k:
            pairs.append((free.pop(k)["role"], m["role"]))
    return pairs


def is_forward_link(path):
    """자리 이름을 바꿀 때 예전 대화 파일 이름에 남긴 링크(같은 폴더의 <새 이름>.jsonl을 가리켜요)인지."""
    try:
        t = os.readlink(path)
    except OSError:
        return False
    return "/" not in t and t.endswith(".jsonl")


def move_seat_files(office, pairs, old_name, name):
    """이름을 바꾼 자리의 chat/<이름>.jsonl·status/<이름>.json을 새 이름으로 옮겨요(office_server.py와 같아요, 지우지 않아요).
    새 이름의 파일이 이미 있으면 옮기지 않아요. 옮긴 대화 파일 자리에는 새 파일을 가리키는 링크를 남겨요(오가는 답이 새 자리에 붙게)."""
    cdir = os.path.join(office, "chat")
    for a, b in pairs:
        files = [(os.path.join(office, sub, a + ext), os.path.join(office, sub, b + ext)) for sub, ext in (("chat", ".jsonl"), ("status", ".json"))]
        files = [(s, d) for s, d in files if os.path.isfile(s) and not os.path.islink(s)]

        def same(s, d):   # 대소문자만 바꾼 이름이면 맥 디스크에서는 같은 파일이에요
            try:
                return os.path.samefile(s, d)
            except OSError:
                return False
        if not files or any(os.path.lexists(d) and not is_forward_link(d) and not same(s, d) for s, d in files):
            continue
        for s, d in files:
            if os.path.islink(d):
                os.unlink(d)   # 예전에 남긴 이어 주는 링크예요(대화 원본이 아니에요)
            os.replace(s, d)
        sp = os.path.join(office, "status", b + ".json")
        if any(d == sp for _, d in files):
            try:
                with open(sp, encoding="utf-8") as f:
                    st = json.load(f)
                if isinstance(st, dict):
                    st["role"] = b
                    if st.get("name") == f"{old_name} {a}":
                        st["name"] = f"{name} {b}"
                    write_json(sp, st)
            except (OSError, ValueError):
                pass
        if any(d == os.path.join(cdir, b + ".jsonl") for _, d in files):
            for n in os.listdir(cdir):   # 더 예전 이름에서 이어 주던 링크도 새 파일로
                p = os.path.join(cdir, n)
                if os.path.islink(p) and os.readlink(p) == a + ".jsonl":
                    os.unlink(p)
                    os.symlink(b + ".jsonl", p)
            if not os.path.lexists(os.path.join(cdir, a + ".jsonl")):
                os.symlink(b + ".jsonl", os.path.join(cdir, a + ".jsonl"))


def merged_rows(old_team, name, members, replace):
    """team.json에 쓸 팀원 줄. replace면 members가 곧 팀원 목록이에요(같은 역할 줄은 다른 칸을 살려요).
    아니면(예전 방식) 다른 자리는 두고, 없는 자리만 더하고, 새로 적은 세션 id만 고쳐요."""
    old = old_team.get("members") if isinstance(old_team, dict) and isinstance(old_team.get("members"), list) else []
    if replace or old_team is None:
        prev = {}
        for m in old:
            if isinstance(m, dict) and isinstance(m.get("role"), str):
                prev.setdefault(unicodedata.normalize("NFC", m["role"]).casefold(), m)
        rows = []
        for m in members:
            p = prev.get(m["role"].casefold())
            row = dict(p) if p else member_row(name, m["role"], m["sessionId"])
            row.update(role=m["role"], sessionId=m["sessionId"] or None)
            rows.append(row)
        return rows
    rows = [dict(m) if isinstance(m, dict) else m for m in old]
    for m in members:
        cur = next((x for x in rows if isinstance(x, dict) and x.get("role") == m["role"]), None)
        if cur is None:
            rows.append(member_row(name, m["role"], m["sessionId"]))
        elif m["sessionId"]:
            cur["sessionId"] = m["sessionId"]
    return rows


def make_office(office, name, prefix, members, boss_sid, old_team, replace=False):
    """팀 사무실 폴더와 기본 파일을 만들어요. 이미 있던 파일은 team.json만 고치고 나머지는 그대로 둬요.
    members: [{role, sessionId}](팀장이 맨 앞). 자리마다 status/<역할>.json이 없으면 만들어요(있던 파일은 지우지 않아요)."""
    for d in ("status", "reports", "meetings", "approvals", "chat", "docs"):
        os.makedirs(os.path.join(office, d), exist_ok=True)
    gi = os.path.join(office, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write("# 에이전시티 팀 기록(대화·결재·세션 id)은 커밋하지 않아요\n*\n")
    tj = os.path.join(office, "team.json")
    rows = merged_rows(old_team, name, members, replace)
    # 팀원 목록으로 바꿀 때 이름만 바뀐 자리(같은 세션)는 대화·상태 파일도 새 이름으로 옮겨요
    pairs = renamed_seats(old_team, members) if replace and old_team is not None else []
    old_name = str(old_team.get("team") or name) if isinstance(old_team, dict) else name
    if old_team is None:
        write_json(tj, {"team": name, "prefix": prefix, "members": rows})
    else:
        old_team.update(team=name, prefix=prefix, members=rows)
        write_json(tj, old_team)
    move_seat_files(office, pairs, old_name, name)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for m in rows:
        role = m.get("role") if isinstance(m, dict) else None
        if not isinstance(role, str) or role_ok(role) != role:   # 손으로 적은 이상한 역할 이름은 파일 이름으로 쓰지 않아요
            continue
        cp = os.path.join(office, "chat", role + ".jsonl")
        if os.path.islink(cp) and is_forward_link(cp):   # 예전 이름 바꾸기 때 남긴 링크: 이 이름의 자리는 새 대화로 시작해요
            os.unlink(cp)
        sp = os.path.join(office, "status", role + ".json")
        if not os.path.lexists(sp):
            write_json(sp, {"name": m.get("name") or f"{name} {role}", "role": role, "state": "대기", "task": "", "say": "", "updated": now})
    if not os.path.exists(os.path.join(office, "board.md")):
        with open(os.path.join(office, "board.md"), "w", encoding="utf-8") as f:
            f.write(f"# {name} 업무판\n\n")
    open(os.path.join(office, "log.jsonl"), "a", encoding="utf-8").close()
    rules = os.path.join(office, "RULES.md")
    if not os.path.exists(rules):
        with open(os.path.join("docs", "TEAM_RULES.md"), encoding="utf-8") as f:
            text = f.read()
        text = text.replace("`$O`(팀 사무실 폴더의 절대경로)", f"`$O`(= {office})").replace("`XX-`", f"`{prefix}`").replace("XX-n", f"{prefix}n")
        text = text.replace("<에이전시티>", HERE)
        # 총괄 id는 org.json에서 바뀔 수 있으니 거기를 가리켜요
        now_boss = "" if boss_sid.startswith(PLACEHOLDER) else f", 지금은 {boss_sid}"
        text = text.replace("보낸 세션이 총괄일 때만", f"보낸 세션이 총괄({HERE}/org.json의 boss.sessionId{now_boss})일 때만")
        with open(rules, "w", encoding="utf-8") as f:
            f.write(f"<!-- $O = {office} -->\n" + text)


def link_team(tid, office):
    os.makedirs("teams", exist_ok=True)
    link = os.path.join("teams", tid)
    if os.path.islink(link) or os.path.exists(link):
        if os.path.realpath(link) != os.path.realpath(office):
            raise TeamError(f"teams/{tid} 가 이미 다른 곳을 가리켜요. 지우거나 다른 id를 써 주세요. (팀 사무실 폴더는 만들어 뒀어요: {office})")
    else:
        os.symlink(office, link)


def add_floor(org, tid, name, proj):
    """org.json의 다음 층으로 넣고 층 번호를 돌려줘요."""
    floors = [int(t["floor"]) for t in org["teams"] if isinstance(t, dict) and str(t.get("floor", "")).isdigit()]
    floor = max(floors, default=0) + 1
    # '다음 팀' 같은 빈 자리(office 없음)보다 앞에 넣어요
    at = next((i for i, t in enumerate(org["teams"]) if not (isinstance(t, dict) and t.get("office"))), len(org["teams"]))
    org["teams"].insert(at, {"id": tid, "name": name, "state": "운영 중", "office": f"teams/{tid}", "floor": floor,
                             "folder": proj, "what": "", "notion": ""})
    return floor


def save_org(org):
    org.setdefault("city", {})
    if os.path.exists("org.json"):
        shutil.copy("org.json", "org.json.bak")
    write_json("org.json", org)


def main():
    start = os.getcwd()
    os.chdir(HERE)
    org = load_org()
    taken = {t.get("id") for t in org["teams"] if isinstance(t, dict)}

    print("에이전시티에 내 팀(층)을 등록해요. 엔터만 누르면 [ ] 안의 값으로 해요.\n")
    tid = ask("팀 id(영문 소문자, 예: shop)", check=lambda v: bool(ID_RE.match(v)) and v not in taken,
              hint="영문 소문자로 시작하는 20자 이내, 이미 있는 id는 안 돼요.")
    name = ask("팀 이름(화면에 보일 이름)", default=tid, check=lambda v: 0 < len(v) <= 30)
    proj = ask("프로젝트 폴더(폴더를 끌어다 놓아도 돼요)", check=lambda v: norm_dir(v, start) is not None,
               hint="있는 폴더를 적어 주세요.")
    proj = norm_dir(proj, start)
    office = check_project(org, proj)
    tj = os.path.join(office, "team.json")
    old_team = read_json(tj, "team.json") if os.path.exists(tj) else None
    prefix = ask("업무 번호 머리글(예: SH-)", default=default_prefix(tid),
                 check=lambda v: bool(PREFIX_RE.match(v)) and v not in RESERVED,
                 hint="영문 대문자 1~4자 + 하이픈이에요. J-·U-·M-은 총괄 지시·사람이 시킨 일·회의 번호라 못 써요.")
    seated = seated_sessions(org)
    members, used = [], set()

    boss_now = current_boss(org)   # 지금 총괄은 층의 자리에 앉힐 수 없어요(그 자리로 보낸 말이 아무에게도 닿지 않아요)

    def sid_ok(v):
        return v == "" or (bool(SESSION_RE.match(v)) and v not in used and v not in seated and v != boss_now)
    sid_hint = ("local_ 로 시작하는 id예요. 한 세션은 한 자리, 한 층에만 앉혀요(이미 앉은 세션과 총괄 세션은 안 돼요). "
                "모르면 비워 두고 나중에 설정 화면의 '팀원 고치기'나 team.json에서 고쳐요.")
    for role in CLASSIC_ROLES:
        v = ask(f"{role} 세션 id(local_…, 모르면 엔터)", check=sid_ok, hint=sid_hint)
        used.add(v)
        members.append({"role": role, "sessionId": v})
    old_ms = old_team.get("members") if isinstance(old_team, dict) and isinstance(old_team.get("members"), list) else []
    have = {r.casefold() for r in CLASSIC_ROLES} | {unicodedata.normalize("NFC", m["role"]).casefold() for m in old_ms
                                                    if isinstance(m, dict) and isinstance(m.get("role"), str)}
    room = max(MAX_MEMBERS - len(have), 0)   # 이미 있던 팀 사무실이면 그 자리들도 세요

    def extra(v):
        """쉼표로 적은 더 둘 역할들(없으면 []). 못 쓰는 이름·겹치는 이름·너무 많으면 None."""
        out = []
        for x in [x.strip() for x in v.replace("，", ",").split(",") if x.strip()]:
            r = role_ok(x)
            if r is None or r.casefold() in have or r.casefold() in {o.casefold() for o in out}:
                return None
            out.append(r)
        return out if len(out) <= room else None   # room이 0이면 빈 입력만 돼요
    more = extra(ask("추가 역할(쉼표로, 없으면 엔터. 예: 마케팅, QA)", check=lambda v: extra(v) is not None,
                     hint=f"{ROLE_HINT} 이미 있는 자리와 겹치지 않게, 이 층에는 {room}자리까지 더 둘 수 있어요."))
    for role in more:
        v = ask(f"{role} 세션 id(local_…, 모르면 엔터)", check=sid_ok, hint=sid_hint)
        used.add(v)
        members.append({"role": role, "sessionId": v})
    demo = demo_teams(org)
    drop_demo = bool(demo) and ask("예시 팀을 층 안내에서 뺄까요? (y/n)", default="y", check=lambda v: v in ("y", "n")) == "y"
    boss = org.get("boss") if isinstance(org.get("boss"), dict) else {}
    boss_sid = str(boss.get("sessionId") or "")
    if not boss_sid or boss_sid.startswith(PLACEHOLDER):
        b = ask("총괄(코디네이터)로 쓸 세션 id(local_…, 모르면 엔터)",
                check=lambda v: v == "" or (bool(SESSION_RE.match(v)) and v not in used and v not in seated),
                hint="local_ 로 시작하는 id예요. 층의 자리에 앉힌 세션은 총괄이 될 수 없어요.")
        boss_sid = b or PLACEHOLDER + "-0000-0000-0000-000000000000"
        boss = dict(boss, name=boss.get("name") or "총괄", title="총괄", sessionId=boss_sid)

    # 여기서부터 파일을 만들어요
    make_office(office, name, prefix, members, boss_sid, old_team)
    if old_team is not None:
        print("· 이미 있던 팀 사무실이에요. team.json의 이름·머리글, 새 자리와 새로 적은 세션 id만 고쳤어요.")
    link_team(tid, office)
    if drop_demo:
        org["teams"] = [t for t in org["teams"] if t not in demo]
    floor = add_floor(org, tid, name, proj)
    org["boss"] = boss
    save_org(org)

    print(f"\n등록했어요: {floor}층 · {name}")
    print(f"- 팀 사무실: {office}")
    print(f"- 각 세션이 규칙을 읽게 하려면 {os.path.join(proj, 'CLAUDE.local.md')} 에 이 줄을 넣어요:  @.office/RULES.md")
    rules = os.path.join(office, "RULES.md")
    home = os.path.realpath(os.path.expanduser("~"))
    rules = "~" + rules[len(home):] if rules.startswith(home + os.sep) else rules
    print(f"  이 폴더 밖에서 연 세션(폴더 없이 만든 세션 등)은 그 파일을 읽지 않아요. 그 세션 폴더의 CLAUDE.local.md에 넣거나"
          f" 세션 창에 한 번 보내요:  @{rules.replace(' ', chr(92) + ' ')}")
    print("- 세션 id를 비워 둔 자리는 화면에 '빈자리'로 보여요. 나중에 설정 화면의 '팀원 고치기'(또는 team.json)에서 채워요.")
    if boss_sid.startswith(PLACEHOLDER):
        print("- 총괄 세션 id는 아직 비어 있어요. 정하면 org.json의 boss.sessionId에 넣어요(docs/COORDINATOR.md).")
    print("- 켜져 있는 사무실 페이지는 몇 초 안에 새 층을 보여 줘요. 꺼져 있으면 python3 start.py")


# ---------- 물어보지 않고 명세대로(--spec) ----------

def plain(e):
    """한 층의 문제는 그 층만 안 만든 것이라 '아무것도 바꾸지 않았어요'는 빼고 알려요."""
    return str(e).replace(NOTHING, "").strip()


def plan_floor(f, org, taken, folders, seated, seats, boss=""):
    """명세의 한 층을 물어볼 때와 같은 기준으로 검사해요. 파일은 건드리지 않아요.
    seated: 이미 다른 층에 앉은 세션 → 층 이름, seats: 이 명세의 앞 층들에 앉힌 세션 → 층 이름, boss: 총괄 세션(자리에 못 앉혀요)."""
    if not isinstance(f, dict):
        raise TeamError("층 정보 모양이 이상해요({…}이어야 해요).")
    tid = f.get("id")
    if not isinstance(tid, str) or not ID_RE.match(tid):
        raise TeamError("팀 id는 영문 소문자로 시작하는 20자 이내예요(소문자·숫자·하이픈).")
    if tid in taken:
        raise TeamError(f"'{tid}'는 이미 있는 팀 id예요. 다른 id를 써 주세요.")
    name = f.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not 0 < len(name) <= 30 or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise TeamError("팀 이름은 한 줄로 1~30자예요.")
    folder = f.get("folder")
    proj = os.path.expanduser(folder.strip()) if isinstance(folder, str) else ""
    if not proj or not os.path.isabs(proj) or not os.path.isdir(proj):
        raise TeamError("프로젝트 폴더는 있는 폴더를 전체 경로로 적어 주세요.")
    proj = os.path.realpath(proj)
    office = check_project(org, proj)
    if office in folders:
        raise TeamError("같은 프로젝트 폴더를 두 층에 골랐어요.")
    prefix = f.get("prefix") or default_prefix(tid)
    if not isinstance(prefix, str) or not PREFIX_RE.match(prefix) or prefix in RESERVED:
        raise TeamError("업무 번호 머리글은 영문 대문자 1~4자 + 하이픈이에요. J-·U-·M-은 못 써요.")
    replace = f.get("members") is not None
    if replace:   # 팀원 목록(맨 앞은 팀장). 이미 있던 팀 사무실이면 팀원 목록을 이것으로 바꿔요
        members = parse_members(f["members"])
    else:         # 예전 모양: 네 자리 묶음
        roles = f.get("roles") if f.get("roles") is not None else {}
        if not isinstance(roles, dict):
            raise TeamError("roles 모양이 이상해요({\"팀장\": \"local_…\", …}).")
        bad = [r for r in roles if r not in CLASSIC_ROLES]
        if bad:
            raise TeamError(f"모르는 역할이에요: {', '.join(str(r)[:20] for r in bad)} "
                            "(roles는 팀장·개발자·디자이너·기획만 받아요. 다른 역할은 members로 보내요).")
        for r in CLASSIC_ROLES:
            v = roles.get(r)
            if v not in (None, "") and not (isinstance(v, str) and SESSION_RE.match(v)):
                raise TeamError(f"{r} 세션 id가 local_… 모양이 아니에요.")
        members = parse_members([{"role": r, "sessionId": roles.get(r) or None} for r in CLASSIC_ROLES])
    for m in members:
        v = m["sessionId"]
        if v and v == boss:
            raise TeamError(f"총괄 세션은 층의 자리에 앉힐 수 없어요({m['role']} 자리).")
        if v and v in seated:
            raise TeamError(f"{m['role']} 세션은 이미 '{seated[v]}' 층에 앉아 있어요. 한 세션은 한 층에만 앉혀요.")
        if v and v in seats:
            raise TeamError(f"{m['role']} 세션은 '{seats[v]}' 층에도 앉혔어요. 한 세션은 한 층에만 앉혀요.")
    tj = os.path.join(office, "team.json")
    old_team = read_json(tj, "team.json") if os.path.exists(tj) else None
    if len(merged_rows(old_team, name, members, replace)) > MAX_MEMBERS:
        raise TeamError(f"이미 있던 팀 사무실의 자리와 합치면 {MAX_MEMBERS}자리가 넘어요. members로 팀원 목록을 보내 주세요.")
    return {"id": tid, "name": name, "proj": proj, "office": office, "prefix": prefix, "members": members, "replace": replace,
            "old": old_team}


def run_spec(src):
    try:
        if src == "-":
            raw = sys.stdin.read(MAX_SPEC + 1)
        else:
            with open(src, encoding="utf-8") as fh:
                raw = fh.read(MAX_SPEC + 1)
        if len(raw) > MAX_SPEC:
            raise ValueError
        spec = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError):
        return {"ok": False, "error": f"명세(JSON)를 읽지 못했어요.{NOTHING}"}
    if not isinstance(spec, dict) or not isinstance(spec.get("floors", []), list):
        return {"ok": False, "error": f"명세 모양이 이상해요(floors는 목록이어야 해요).{NOTHING}"}
    boss_in = spec.get("boss")
    if boss_in not in (None, "") and not (isinstance(boss_in, str) and SESSION_RE.match(boss_in)):
        return {"ok": False, "error": f"총괄 세션 id가 local_… 모양이 아니에요.{NOTHING}"}
    os.chdir(HERE)
    try:
        org = load_org()
    except TeamError as e:
        return {"ok": False, "error": str(e)}
    taken = {t.get("id") for t in org["teams"] if isinstance(t, dict)}
    seated = seated_sessions(org)
    boss_now = boss_in or current_boss(org)   # 이번에 정할 총괄(없으면 지금 총괄)
    if boss_in and boss_in in seated:
        return {"ok": False, "error": f"총괄로 고른 세션은 이미 '{seated[boss_in]}' 층의 자리에 앉아 있어요.{NOTHING}"}
    plans, errors = [], []
    for i, f in enumerate(spec.get("floors") or []):
        label = f.get("id") if isinstance(f, dict) and isinstance(f.get("id"), str) and f.get("id") else f"{i + 1}번째 층"
        try:
            seats = {m["sessionId"]: p["name"] for p in plans for m in p["members"] if m["sessionId"]}
            p = plan_floor(f, org, taken, {p["office"] for p in plans}, seated, seats, boss_now)
        except TeamError as e:
            errors.append({"id": label[:40], "error": plain(e)})
            continue
        taken.add(p["id"])
        plans.append(p)

    boss = org.get("boss") if isinstance(org.get("boss"), dict) else {}
    boss_sid = str(boss.get("sessionId") or "")
    if boss_in:
        boss_sid = boss_in
        boss = dict(boss, name=boss.get("name") or "총괄", title="총괄", sessionId=boss_sid)
    elif not boss_sid or boss_sid.startswith(PLACEHOLDER):
        boss_sid = PLACEHOLDER + "-0000-0000-0000-000000000000"
        boss = dict(boss, name=boss.get("name") or "총괄", title="총괄", sessionId=boss_sid)
    before = list(org["teams"])
    if plans and spec.get("dropDemo", True) is not False:
        demo = demo_teams(org)
        org["teams"] = [t for t in org["teams"] if t not in demo]
    created = []
    for p in plans:
        try:
            make_office(p["office"], p["name"], p["prefix"], p["members"], boss_sid, p["old"], p["replace"])
            link_team(p["id"], p["office"])
        except TeamError as e:
            errors.append({"id": p["id"], "error": plain(e)})
            continue
        except OSError as e:
            errors.append({"id": p["id"], "error": f"팀 사무실 파일을 만들지 못했어요({e.strerror or type(e).__name__})."})
            continue
        created.append({"id": p["id"], "floor": add_floor(org, p["id"], p["name"], p["proj"]), "office": p["office"]})
    if not created:
        org["teams"] = before          # 한 층도 못 만들었으면 예시 팀도 그대로 둬요
    if created or boss_in:
        org["boss"] = boss
        save_org(org)
    return {"ok": True, "created": created, "errors": errors}


if __name__ == "__main__":
    if sys.argv[1:2] == ["--spec"]:
        if len(sys.argv) != 3:
            sys.exit("쓰는 법: python3 bin/new_team.py --spec <명세.json | ->")
        try:
            res = run_spec(sys.argv[2])
        except OSError as e:
            res = {"ok": False, "error": f"org.json을 쓰지 못했어요({e.strerror or type(e).__name__})."}
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("ok") else 1)
    try:
        main()
    except TeamError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit("\n멈췄어요.")
