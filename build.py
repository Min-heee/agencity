"""클로드 오피스 페이지 만들기.

python3 -I build.py            -> index.html (로컬 실시간 페이지)
python3 -I build.py --snapshot -> artifact.html (claude.ai 게시용, 지금 상태를 스냅샷으로 담음)
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "office.src.html")
MARK = "/*@@SNAPSHOT@@*/"
HEAD = (
    '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    "<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
    "body{margin:0;font:14px/1.5 system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>\n"
)


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def snapshot():
    org = json.loads(read(os.path.join(HERE, "org.json"), "{}"))
    teams = {}
    for t in org.get("teams", []):
        if not t.get("office"):
            continue
        base_rel = t["office"].rstrip("/") + "/"
        base = os.path.join(HERE, base_rel)
        team = json.loads(read(base + "team.json", "{}"))
        status = {}
        for m in team.get("members", []):
            try:
                status[m["role"]] = json.loads(read(base + "status/" + m["role"] + ".json"))
            except ValueError:
                status[m["role"]] = None
        log = []
        for line in read(base + "log.jsonl").splitlines():
            try:
                if line.strip():
                    log.append(json.loads(line))
            except ValueError:
                pass
        def md_list(sub):
            try:
                return sorted(f for f in os.listdir(base + sub) if f.endswith(".md"))
            except OSError:
                return []
        meetings, reports = md_list("meetings"), md_list("reports")
        files = {}
        for sub, names in (("meetings", meetings), ("reports", reports)):
            for n in names:
                files[base_rel + sub + "/" + n] = read(base + sub + "/" + n)
        meeting = {"file": meetings[-1], "text": files[base_rel + "meetings/" + meetings[-1]]} if meetings else None

        def json_files(sub, pattern):
            out = []
            try:
                names = sorted(f for f in os.listdir(base + sub) if re.match(pattern, f))
            except OSError:
                return out
            for n in names:
                try:
                    obj = json.loads(read(base + sub + "/" + n, "null"))
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    obj.setdefault("id", n[:-5])
                    out.append(obj)
            return out
        metas = json_files("meetings", r"^\d{8}-M-\d+\.json$")[-12:]
        active = next((m for m in metas if m.get("status") in ("진행 중", "정리 중")), None)
        active_chat = []
        if active:
            for line in read(base + "meetings/" + active["id"] + ".chat.jsonl").splitlines():
                try:
                    if line.strip():
                        active_chat.append(json.loads(line))
                except ValueError:
                    pass
        approvals = json_files("approvals", r"^.+\.json$")
        teams[t["id"]] = {"team": team, "status": status, "board": read(base + "board.md"), "log": log,
                          "meetings": meetings, "reports": reports, "meeting": meeting, "base": base_rel, "files": files,
                          "metas": metas, "active": active, "activeChat": active_chat, "approvals": approvals}
    return {"org": org, "teams": teams, "at": datetime.now(timezone.utc).isoformat()}


def main():
    src = read(SRC)
    body_start = src.index("</style>") + len("</style>")
    head_part, body_part = src[:body_start], src[body_start:]
    if "--snapshot" in sys.argv:
        snap = json.dumps(snapshot(), ensure_ascii=False).replace("</", "<\\/")
        with open(os.path.join(HERE, "artifact.html"), "w", encoding="utf-8") as f:
            f.write(src.replace(MARK, snap))
        print("artifact.html")
    else:
        page = HEAD + head_part + "\n</head>\n<body>\n" + body_part.replace(MARK, "") + "\n</body>\n</html>\n"
        with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        print("index.html")


if __name__ == "__main__":
    main()
