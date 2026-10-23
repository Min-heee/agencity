#!/usr/bin/env python3
"""팀 간 대화(hq/teams.jsonl)를 대화(주제)별로 묶고, 한 대화의 왕복 횟수를 세서 막아요.

python3 -I talk_thread.py send <hq 폴더> auto|topic|re [<주제 또는 T-…>]   (bin/tell.sh가 써요)
  표준입력: 보낼 줄 {from: {floor, …}, to: {floor, …}, text}. 이을 대화를 정하고 t·thread·topic·n·cap을 더해 한 줄 덧붙인 뒤
  'T-xxxxxx n cap'을 찍어요. 한도를 넘으면 보내지 않고(끝 코드 1) 그 대화에 멈춤 줄을 한 번 남겨요.
  auto: 24시간 안에 같은 두 층(어느 쪽이 보냈든)이 나눈 마지막 대화를 이어요. 없으면 새 대화예요.
        그 대화가 한도에 닿았으면 새 대화로 넘어가지 않고 막아요(주제 없이 보내기만 되풀이해서 끝없이 오가지 않게).
office_server.py는 대표가 화면에서 [3번 더 하게 두기]를 누르면 allow()를 불러요(허락 줄).
세기와 덧붙이기는 늘 hq/.teams.lock(flock)을 잡은 채로 해요. 두 팀장이 한꺼번에 보내도 둘 다 한도를 넘지 못하고 줄이 섞이지 않아요.

줄 모양(한 줄에 하나):
  말   {t, from, to, text, thread: "T-xxxxxx", topic, n, cap}   n: 이 대화의 몇 번째 말(양쪽 다 세요), cap: 그때의 한도
  멈춤 {t, kind: "stop", thread, topic, from, to, n, cap}         한도를 넘겨 보내려다 막혔어요(글은 없어요)
  허락 {t, kind: "allow", thread, add, cap, by: "대표"}            대표가 왕복 3번을 더 열었어요
thread가 없는 예전 줄은 세지 않고 그대로 둬요. 0.8.x 화면은 글이 없는 멈춤·허락 줄을 건너뛰어요.
"""
import errno
import fcntl
import json
import os
import re
import secrets
import stat
import sys
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

ROUNDS = 3                  # 한 대화의 왕복 횟수. 대표가 허락할 때마다 이만큼 더해요
CAP = ROUNDS * 2            # 한 대화에 보낼 수 있는 말 수(양쪽 다 세요)
RECENT = 24 * 3600          # --topic·--re 없이 보내면 이 시간 안의 대화만 이어요
TAIL = 8 * 1024 * 1024      # teams.jsonl은 끝의 이만큼만 읽어요(아주 오래된 대화 번호는 못 찾아요)
TOPIC_MAX = 40
WAIT = 10                   # 잠금을 이만큼(초)까지 기다려요
THREAD_RE = re.compile(r"T-[0-9a-f]{6}\Z")
FILE, LOCK_FILE = "teams.jsonl", ".teams.lock"


class Refused(Exception):
    """보내지(고치지) 않았어요. 팀장·대표에게 보여 줄 한 줄이에요."""


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def when(v):
    try:
        return datetime.fromisoformat(v).timestamp() if isinstance(v, str) else 0.0
    except ValueError:
        return 0.0


def floor_id(x):
    return x["floor"] if isinstance(x, dict) and isinstance(x.get("floor"), str) else ""


def clean_topic(v):
    """주제: 줄바꿈은 빈칸으로, 제어·서식 문자는 빼고, 한 줄 TOPIC_MAX자까지."""
    v = unicodedata.normalize("NFC", v if isinstance(v, str) else "")
    v = "".join(" " if unicodedata.category(ch) in ("Zl", "Zp") or ch in "\t\n\r\v\f" else ch for ch in v)
    v = "".join(ch for ch in v if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co"))
    return " ".join(v.split())[:TOPIC_MAX].rstrip()


@contextmanager
def locked(hq):
    try:
        fd = os.open(os.path.join(hq, LOCK_FILE), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise Refused("hq/.teams.lock을 열지 못했어요. 보내지 않았어요")
    try:
        end = time.time() + WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK) or time.time() > end:
                    raise Refused("팀 간 대화 기록이 잠겨 있어요. 잠시 뒤 다시 해 주세요")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)   # 닫으면 잠금도 풀려요(도중에 죽어도 남지 않아요)


def rows_of(path):
    """teams.jsonl의 줄(dict)들. 없으면 []. 링크·보통 파일이 아닌 것은 막아요. 깨진 줄은 건너뛰어요."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    except OSError:
        raise Refused("hq/teams.jsonl을 읽지 못했어요(링크면 쓰지 않아요)")
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise Refused("hq/teams.jsonl이 보통 파일이 아니에요")
        cut = st.st_size > TAIL
        if cut:
            f.seek(st.st_size - TAIL)
        lines = f.read().split(b"\n")
    out = []
    for b in lines[1:] if cut else lines:
        try:
            r = json.loads(b.decode("utf-8")) if b.strip() else None
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def append(path, obj):
    """한 줄을 덧붙여요(O_APPEND, 잠금 안에서만). 앞 줄이 줄바꿈 없이 끊겨 있으면 줄을 바꾼 뒤에 써요."""
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")   # jq -c처럼 붙여 써요
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)   # 읽기도: 끝 글자를 봐요
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("hq/teams.jsonl이 보통 파일이 아니에요")
        if st.st_size and os.pread(fd, 1, st.st_size - 1) != b"\n":
            data = b"\n" + data
        while data:
            data = data[os.write(fd, data):]
    finally:
        os.close(fd)


def threads(rows):
    """대화 번호 → {pair, topic, n, cap, allow, stopped, last, at}. 말 줄만 세요(양쪽 다).
    stopped: 마지막 허락 뒤에 멈춤 줄이 있어요. 번호가 같아도 다른 두 층의 줄은 세지 않아요."""
    th = {}
    for i, r in enumerate(rows):
        tid, kind = r.get("thread"), r.get("kind")
        if not isinstance(tid, str) or not THREAD_RE.match(tid):
            continue
        s = th.get(tid)
        if kind in ("stop", "allow"):
            if s:
                s["stopped"] = kind == "stop"
                s["allow"] += kind == "allow"
            continue
        a, b = floor_id(r.get("from")), floor_id(r.get("to"))
        if kind is not None or not a or not b or a == b or not isinstance(r.get("text"), str):
            continue
        pair = frozenset((a, b))
        if s is None:
            topic = r.get("topic")
            s = th[tid] = {"pair": pair, "topic": topic if isinstance(topic, str) else "", "n": 0, "allow": 0, "stopped": False}
        elif s["pair"] != pair:
            continue
        s["n"] += 1
        s["last"], s["at"] = i, when(r.get("t"))
    for s in th.values():
        s["cap"] = CAP * (1 + s["allow"])
    return th


def capped_text(tid, cap):
    return f"멈췄어요: 대화 #{tid}는 왕복 {cap // 2}번을 다 했어요. 더 보내지 말고 총괄에게 [보고]로 올려요"


def send(hq, mode, arg, rec):
    """보낼 줄 rec을 알맞은 대화에 덧붙여요. (번호, n, cap). 못 보내면 Refused."""
    a, b = floor_id(rec.get("from")), floor_id(rec.get("to"))
    if not a or not b or a == b or not isinstance(rec.get("text"), str) or not rec["text"]:
        raise Refused("보낼 줄이 이상해요")
    pair, path, tid, topic = frozenset((a, b)), os.path.join(hq, FILE), "", ""
    if mode == "topic":
        topic = clean_topic(arg)
        if not topic:
            raise Refused("주제가 비었어요. --topic 뒤에 짧은 주제를 적어요")
    elif mode == "re":
        tid = arg[1:] if arg.startswith("#") else arg
        if not THREAD_RE.match(tid):
            raise Refused("대화 번호가 이상해요(T-와 여섯 글자예요. 받은 머리말의 #T-…)")
    elif mode != "auto":
        raise Refused("보내는 방법이 이상해요")
    with locked(hq):
        rows = rows_of(path)
        th = threads(rows)
        if mode == "re":
            if tid not in th:
                raise Refused(f"대화 #{tid}를 찾지 못했어요. 번호를 확인해 주세요")
            if th[tid]["pair"] != pair:
                raise Refused(f"#{tid}는 이 두 층의 대화가 아니에요. 번호를 확인해 주세요")
        elif mode == "auto":
            cut = time.time() - RECENT
            mine = [(s["last"], k) for k, s in th.items() if s["pair"] == pair and s["at"] >= cut]
            tid = max(mine)[1] if mine else ""
        if tid:
            s = th[tid]
            topic = s["topic"]
            if s["n"] >= s["cap"]:
                if not s["stopped"]:   # 화면이 ‘멈춤 · 대표 확인 필요’를 보여 줘요(대화마다 한 번)
                    append(path, {"t": now(), "kind": "stop", "thread": tid, "topic": topic,
                                  "from": rec["from"], "to": rec["to"], "n": s["n"], "cap": s["cap"]})
                raise Refused(capped_text(tid, s["cap"]))
            n, cap = s["n"] + 1, s["cap"]
        else:
            used = {r.get("thread") for r in rows}
            tid = "T-" + secrets.token_hex(3)
            while tid in used:
                tid = "T-" + secrets.token_hex(3)
            n, cap = 1, CAP
        append(path, {"t": now(), "from": rec["from"], "to": rec["to"], "text": rec["text"],
                      "thread": tid, "topic": topic, "n": n, "cap": cap})
    return tid, n, cap


def allow(hq, tid):
    """멈춘 대화에 왕복 ROUNDS번을 더 열어요(허락 줄). {thread, n, cap}. 멈춘 대화가 아니면 Refused."""
    if not isinstance(tid, str) or not THREAD_RE.match(tid):
        raise Refused("대화 번호가 이상해요")
    path = os.path.join(hq, FILE)
    with locked(hq):
        s = threads(rows_of(path)).get(tid)
        if not s:
            raise Refused("이 대화를 찾지 못했어요")
        if not s["stopped"]:
            if s["n"] >= s["cap"]:   # 한도에 닿았지만 아직 더 보내려 한 적이 없어요(마지막 말로 끝났을 수 있어요)
                raise Refused("이 대화는 아직 멈추지 않았어요(팀장이 더 보내려 할 때 멈춰요)")
            raise Refused("이미 더 하게 뒀어요" if s["allow"] else "이 대화는 멈춰 있지 않아요")
        cap = s["cap"] + CAP
        append(path, {"t": now(), "kind": "allow", "thread": tid, "add": CAP, "cap": cap, "by": "대표"})
    return {"thread": tid, "n": s["n"], "cap": cap}


def main(argv):
    if len(argv) not in (4, 5) or argv[1] != "send":
        print("사용: talk_thread.py send <hq 폴더> auto|topic|re [<주제 또는 T-…>]", file=sys.stderr)
        return 2
    try:
        rec = json.loads(sys.stdin.buffer.read(64 * 1024).decode("utf-8"))
        if not isinstance(rec, dict):
            raise ValueError
    except (UnicodeDecodeError, ValueError):
        print("보낼 줄을 읽지 못했어요", file=sys.stderr)
        return 1
    try:
        tid, n, cap = send(argv[2], argv[3], argv[4] if len(argv) > 4 else "", rec)
    except Refused as e:
        print(e, file=sys.stderr)
        return 1
    except OSError as e:
        print(f"팀 간 대화 기록을 쓰지 못했어요({e.strerror or type(e).__name__}). 보내지 않았어요", file=sys.stderr)
        return 1
    print(tid, n, cap)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
