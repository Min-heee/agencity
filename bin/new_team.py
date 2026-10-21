"""내 팀(층) 등록 도우미.

python3 bin/new_team.py

물어보는 것: 팀 id, 팀 이름, 프로젝트 폴더, 업무 번호 머리글, 역할별 Claude Code 세션 id(모르면 비워 둬요),
처음이면 예시 팀을 뺄지와 총괄 세션 id. 다 물어본 뒤에야 파일을 만들어요(중간에 멈추면 아무것도 안 바뀌어요).
하는 일:
  1) <프로젝트>/.office/ 팀 사무실 폴더를 만들어요(team.json, status/, board.md, log.jsonl, reports/, meetings/,
     approvals/, chat/, RULES.md). 이미 있으면 다른 파일은 그대로 두고, team.json의 이름·머리글과 새로 적은 세션 id만 고쳐요.
  2) .office/.gitignore(내용 '*')를 둬서, 저장소가 어떤 구조든(하위 폴더, worktree, submodule) 팀 기록이 커밋되지 않게 해요.
  3) teams/<id> 를 그 폴더에 연결해요.
  4) org.json에 다음 층으로 넣어요. 고치기 전 내용은 org.json.bak에 남겨요.
세션 id는 각 세션에서 "이 세션 id 알려 줘"라고 물으면 local_… 로 알려 줘요. 나중에 team.json에서 고쳐도 돼요.
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
        sys.exit(f"{what}을 읽지 못했어요: {path} ({e}). 고친 뒤 다시 실행해 주세요. 아무것도 바꾸지 않았어요.")
    except OSError as e:
        sys.exit(f"{what}을 열지 못했어요: {path} ({e}). 아무것도 바꾸지 않았어요.")
    if not isinstance(obj, dict):
        sys.exit(f"{what} 모양이 이상해요(맨 위가 {{…}}가 아니에요): {path}. 아무것도 바꾸지 않았어요.")
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


def main():
    start = os.getcwd()
    os.chdir(HERE)
    if os.path.exists("org.json"):
        org = read_json("org.json", "org.json")
    else:
        org = read_json(os.path.join("examples", "org.example.json"), "예시 org.json")
    org.setdefault("teams", [])
    if not isinstance(org["teams"], list):
        sys.exit("org.json의 teams가 목록([…])이 아니에요. 아무것도 바꾸지 않았어요.")
    taken = {t.get("id") for t in org["teams"] if isinstance(t, dict)}

    print("클로드 오피스에 내 팀(층)을 등록해요. 엔터만 누르면 [ ] 안의 값으로 해요.\n")
    tid = ask("팀 id(영문 소문자, 예: shop)", check=lambda v: bool(ID_RE.match(v)) and v not in taken,
              hint="영문 소문자로 시작하는 20자 이내, 이미 있는 id는 안 돼요.")
    name = ask("팀 이름(화면에 보일 이름)", default=tid, check=lambda v: 0 < len(v) <= 30)
    proj = ask("프로젝트 폴더(폴더를 끌어다 놓아도 돼요)", check=lambda v: norm_dir(v, start) is not None,
               hint="있는 폴더를 적어 주세요.")
    proj = norm_dir(proj, start)
    if proj == HERE or proj.startswith(HERE + os.sep):
        sys.exit("클로드 오피스 폴더 안은 팀 프로젝트로 쓸 수 없어요. 아무것도 바꾸지 않았어요.")
    office = os.path.join(proj, ".office")
    for t in org["teams"]:
        o = t.get("office") if isinstance(t, dict) else None
        if o and os.path.realpath(os.path.join(HERE, o)) == os.path.realpath(office):
            sys.exit(f"이 프로젝트는 이미 '{t.get('name')}'({t.get('id')})로 등록돼 있어요. 아무것도 바꾸지 않았어요.")
    tj = os.path.join(office, "team.json")
    old_team = read_json(tj, "team.json") if os.path.exists(tj) else None
    prefix = ask("업무 번호 머리글(예: SH-)", default=default_prefix(tid),
                 check=lambda v: bool(PREFIX_RE.match(v)) and v not in RESERVED,
                 hint="영문 대문자 1~4자 + 하이픈이에요. J-·U-·M-은 총괄 지시·사람이 시킨 일·회의 번호라 못 써요.")
    sids = {}
    for role in ROLES:
        sids[role] = ask(f"{role} 세션 id(local_…, 모르면 엔터)", check=lambda v: v == "" or bool(SESSION_RE.match(v)),
                         hint="local_ 로 시작하는 id예요. 모르면 비워 두고 나중에 team.json에서 고쳐요.")
    demo = [t for t in org["teams"] if isinstance(t, dict) and str(t.get("office") or "").startswith("examples/")]
    drop_demo = bool(demo) and ask("예시 팀을 층 안내에서 뺄까요? (y/n)", default="y", check=lambda v: v in ("y", "n")) == "y"
    boss = org.get("boss") if isinstance(org.get("boss"), dict) else {}
    boss_sid = str(boss.get("sessionId") or "")
    if not boss_sid or boss_sid.startswith(PLACEHOLDER):
        b = ask("총괄(코디네이터)로 쓸 세션 id(local_…, 모르면 엔터)", check=lambda v: v == "" or bool(SESSION_RE.match(v)))
        boss_sid = b or PLACEHOLDER + "-0000-0000-0000-000000000000"
        boss = dict(boss, name=boss.get("name") or "총괄", title="총괄", sessionId=boss_sid)

    # 여기서부터 파일을 만들어요
    for d in ("status", "reports", "meetings", "approvals", "chat", "docs"):
        os.makedirs(os.path.join(office, d), exist_ok=True)
    gi = os.path.join(office, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write("# 클로드 오피스 팀 기록(대화·결재·세션 id)은 커밋하지 않아요\n*\n")
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
        print("· 이미 있던 팀 사무실이에요. team.json의 이름·머리글과 새로 적은 세션 id만 고쳤어요.")
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
        text = text.replace("<클로드 오피스>", HERE)
        # 총괄 id는 org.json에서 바뀔 수 있으니 거기를 가리켜요
        now_boss = "" if boss_sid.startswith(PLACEHOLDER) else f", 지금은 {boss_sid}"
        text = text.replace("보낸 세션이 총괄일 때만", f"보낸 세션이 총괄({HERE}/org.json의 boss.sessionId{now_boss})일 때만")
        with open(rules, "w", encoding="utf-8") as f:
            f.write(f"<!-- $O = {office} -->\n" + text)

    os.makedirs("teams", exist_ok=True)
    link = os.path.join("teams", tid)
    if os.path.islink(link) or os.path.exists(link):
        if os.path.realpath(link) != os.path.realpath(office):
            sys.exit(f"teams/{tid} 가 이미 다른 곳을 가리켜요. 지우거나 다른 id를 써 주세요. (팀 사무실 폴더는 만들어 뒀어요: {office})")
    else:
        os.symlink(office, link)

    if drop_demo:
        org["teams"] = [t for t in org["teams"] if t not in demo]
    floors = [int(t["floor"]) for t in org["teams"] if isinstance(t, dict) and str(t.get("floor", "")).isdigit()]
    floor = max(floors, default=0) + 1
    # '다음 팀' 같은 빈 자리(office 없음)보다 앞에 넣어요
    at = next((i for i, t in enumerate(org["teams"]) if not (isinstance(t, dict) and t.get("office"))), len(org["teams"]))
    org["teams"].insert(at, {"id": tid, "name": name, "state": "운영 중", "office": f"teams/{tid}", "floor": floor,
                             "folder": proj, "what": "", "notion": ""})
    org["boss"] = boss
    org.setdefault("city", {})
    if os.path.exists("org.json"):
        shutil.copy("org.json", "org.json.bak")
    write_json("org.json", org)

    print(f"\n등록했어요: {floor}층 · {name}")
    print(f"- 팀 사무실: {office}")
    print(f"- 각 세션이 규칙을 읽게 하려면 {os.path.join(proj, 'CLAUDE.local.md')} 에 이 줄을 넣어요:  @.office/RULES.md")
    print("- 세션 id를 비워 둔 자리는 화면에 '빈자리'로 보여요. 나중에 team.json에서 고쳐요.")
    if boss_sid.startswith(PLACEHOLDER):
        print("- 총괄 세션 id는 아직 비어 있어요. 정하면 org.json의 boss.sessionId에 넣어요(docs/COORDINATOR.md).")
    print("- 켜져 있는 사무실 페이지는 몇 초 안에 새 층을 보여 줘요. 꺼져 있으면 python3 start.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n멈췄어요.")
