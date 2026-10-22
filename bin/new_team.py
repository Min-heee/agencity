"""내 팀(층) 등록 도우미.

python3 bin/new_team.py                      # 물어보며 한 층씩 등록해요
python3 bin/new_team.py --spec <명세.json>    # 물어보지 않고 명세대로 여러 층을 등록해요(앱의 처음 설정 화면이 써요)
python3 bin/new_team.py --spec -             # 명세를 표준 입력으로 받아요

물어보는 것: 팀 id, 팀 이름, 프로젝트 폴더, 업무 번호 머리글, 역할별 Claude Code 세션 id(모르면 비워 둬요),
처음이면 예시 팀을 뺄지와 총괄 세션 id. 다 물어본 뒤에야 파일을 만들어요(중간에 멈추면 아무것도 안 바뀌어요).
하는 일:
  1) <프로젝트>/.office/ 팀 사무실 폴더를 만들어요(team.json, status/, board.md, log.jsonl, reports/, meetings/,
     approvals/, chat/, RULES.md). 이미 있으면 다른 파일은 그대로 두고, team.json의 이름·머리글과 새로 적은 세션 id만 고쳐요.
  2) .office/.gitignore(내용 '*')를 둬서, 저장소가 어떤 구조든(하위 폴더, worktree, submodule) 팀 기록이 커밋되지 않게 해요.
  3) teams/<id> 를 그 폴더에 연결해요.
  4) org.json에 다음 층으로 넣어요. 고치기 전 내용은 org.json.bak에 남겨요.
세션 id는 각 세션에서 "이 세션 id 알려 줘"라고 물으면 local_… 로 알려 줘요. 나중에 team.json에서 고쳐도 돼요.

명세(--spec)는 이런 모양이에요. 검사는 물어볼 때와 같고, 문제가 있는 층은 만들지 않고 errors에 적어요.
{"boss": "local_…" 또는 null, "dropDemo": true,
 "floors": [{"id": "shop", "name": "쇼핑몰팀", "folder": "/Users/me/shop", "prefix": "SH-"(없어도 돼요),
             "roles": {"팀장": "local_…", "개발자": null, "디자이너": null, "기획": null}}]}
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
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ROLES = ["팀장", "개발자", "디자이너", "기획"]
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,19}$")
SESSION_RE = re.compile(r"^local_[0-9a-f-]{8,64}$")
PREFIX_RE = re.compile(r"^[A-Z]{1,4}-$")
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


def make_office(office, name, prefix, sids, boss_sid, old_team):
    """팀 사무실 폴더와 기본 파일을 만들어요. 이미 있던 파일은 team.json만 고치고 나머지는 그대로 둬요."""
    for d in ("status", "reports", "meetings", "approvals", "chat", "docs"):
        os.makedirs(os.path.join(office, d), exist_ok=True)
    gi = os.path.join(office, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write("# 에이전시티 팀 기록(대화·결재·세션 id)은 커밋하지 않아요\n*\n")
    tj = os.path.join(office, "team.json")
    if old_team is None:
        members = [{"role": r, "name": f"{name} {r}", "title": f"{name} · {r}", "sessionId": sids[r] or None} for r in ROLES]
        write_json(tj, {"team": name, "prefix": prefix, "members": members})
    else:
        old_team.update(team=name, prefix=prefix)
        members = old_team.setdefault("members", [])
        for r in ROLES:
            m = next((m for m in members if isinstance(m, dict) and m.get("role") == r), None)
            if m is None:
                members.append({"role": r, "name": f"{name} {r}", "title": f"{name} · {r}", "sessionId": sids[r] or None})
            elif sids[r]:
                m["sessionId"] = sids[r]
        write_json(tj, old_team)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for role in ROLES:
        sp = os.path.join(office, "status", role + ".json")
        if not os.path.exists(sp):
            write_json(sp, {"name": f"{name} {role}", "role": role, "state": "대기", "task": "", "say": "", "updated": now})
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
    sids = {}
    for role in ROLES:
        sids[role] = ask(f"{role} 세션 id(local_…, 모르면 엔터)", check=lambda v: v == "" or bool(SESSION_RE.match(v)),
                         hint="local_ 로 시작하는 id예요. 모르면 비워 두고 나중에 team.json에서 고쳐요.")
    demo = demo_teams(org)
    drop_demo = bool(demo) and ask("예시 팀을 층 안내에서 뺄까요? (y/n)", default="y", check=lambda v: v in ("y", "n")) == "y"
    boss = org.get("boss") if isinstance(org.get("boss"), dict) else {}
    boss_sid = str(boss.get("sessionId") or "")
    if not boss_sid or boss_sid.startswith(PLACEHOLDER):
        b = ask("총괄(코디네이터)로 쓸 세션 id(local_…, 모르면 엔터)", check=lambda v: v == "" or bool(SESSION_RE.match(v)))
        boss_sid = b or PLACEHOLDER + "-0000-0000-0000-000000000000"
        boss = dict(boss, name=boss.get("name") or "총괄", title="총괄", sessionId=boss_sid)

    # 여기서부터 파일을 만들어요
    make_office(office, name, prefix, sids, boss_sid, old_team)
    if old_team is not None:
        print("· 이미 있던 팀 사무실이에요. team.json의 이름·머리글과 새로 적은 세션 id만 고쳤어요.")
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
    print("- 세션 id를 비워 둔 자리는 화면에 '빈자리'로 보여요. 나중에 team.json에서 고쳐요.")
    if boss_sid.startswith(PLACEHOLDER):
        print("- 총괄 세션 id는 아직 비어 있어요. 정하면 org.json의 boss.sessionId에 넣어요(docs/COORDINATOR.md).")
    print("- 켜져 있는 사무실 페이지는 몇 초 안에 새 층을 보여 줘요. 꺼져 있으면 python3 start.py")


# ---------- 물어보지 않고 명세대로(--spec) ----------

def plain(e):
    """한 층의 문제는 그 층만 안 만든 것이라 '아무것도 바꾸지 않았어요'는 빼고 알려요."""
    return str(e).replace(NOTHING, "").strip()


def plan_floor(f, org, taken, folders):
    """명세의 한 층을 물어볼 때와 같은 기준으로 검사해요. 파일은 건드리지 않아요."""
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
    roles = f.get("roles") if f.get("roles") is not None else {}
    if not isinstance(roles, dict):
        raise TeamError("roles 모양이 이상해요({\"팀장\": \"local_…\", …}).")
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise TeamError(f"모르는 역할이에요: {', '.join(str(r)[:20] for r in bad)} (팀장·개발자·디자이너·기획만 돼요).")
    sids = {}
    for r in ROLES:
        v = roles.get(r)
        if v in (None, ""):
            sids[r] = ""
        elif isinstance(v, str) and SESSION_RE.match(v):
            sids[r] = v
        else:
            raise TeamError(f"{r} 세션 id가 local_… 모양이 아니에요.")
    tj = os.path.join(office, "team.json")
    old_team = read_json(tj, "team.json") if os.path.exists(tj) else None
    return {"id": tid, "name": name, "proj": proj, "office": office, "prefix": prefix, "sids": sids, "old": old_team}


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
    plans, errors = [], []
    for i, f in enumerate(spec.get("floors") or []):
        label = f.get("id") if isinstance(f, dict) and isinstance(f.get("id"), str) and f.get("id") else f"{i + 1}번째 층"
        try:
            p = plan_floor(f, org, taken, {p["office"] for p in plans})
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
            make_office(p["office"], p["name"], p["prefix"], p["sids"], boss_sid, p["old"])
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
