"""총괄 세션이 Monitor로 돌리는 감시기.

outbox/에 새 '전달할 메시지'가 생기면, 서버가 만든 항목인지(/api/outbox/check, 내용 해시 비교) 확인한 뒤
`RELAY <파일>`을 찍어요. 서버가 만든 게 아니면 outbox/rejected/로 옮기고 `RELAY-REJECT <파일>`을 찍어요.
90초 넘게 남아 있는 항목은 `RELAY-STALE <파일>`로 다시 알려요(총괄이 놓쳤을 때).
서버에 닿을 때만 1초마다 outbox/.heartbeat와 .watching(내 총괄 id)을 고쳐서, 사이트가 '총괄 연결됨'을 알 수 있게 해요.
총괄을 바꾼 뒤(outbox/.retired)에는 사이트가 .watching만 봐요(0.7.0 전에 켠 예전 총괄의 감시기도 .heartbeat는 계속 고쳐서요).
서버에 5초 넘게 닿지 않으면 `RELAY-ERROR 서버에 연결 못 함`을 한 번 찍어요.
포트는 OFFICE_PORT가 있으면 그것, 없으면 서버가 켜질 때 적어 두는 outbox/.port를 매번 다시 읽어요.
총괄은 RELAY 파일을 읽고 SendMessage로 전한 뒤 bin/relay_done.sh로 outbox/sent/에 옮겨요.
켤 때 org.json의 boss.sessionId를 내 총괄로 기억하고(총괄 바꾸기를 기다리는 중이어도 지금 총괄), 그 총괄이 다른 세션으로 바뀌면
`RELAY-ERROR 총괄이 바뀌었어요. 감시를 멈춰요.`를 찍고 끝나요(예전 총괄이 계속 전하지 않게). 총괄이 없을 때 켰으면 처음 정해진 총괄이에요.
--boss <세션 id>로 켜면 그 세션이 총괄이 될 때까지 알리지 않아요(기다리는 총괄 바꾸기도 없으면 끝나요).
총괄을 한 번이라도 바꾼 뒤(outbox/.retired가 있으면)에는 --boss도 CLAUDE_CODE_HOST_SESSION_ID도 없이 켠 감시는 바로 끝내요.
누가 켰는지 모르면 예전 총괄 창이 다시 켠 것일 수 있어서요(켤 때의 총괄을 내 총괄로 알면 새 총괄 몫을 가져가요).
감시기는 하나만 돌아요(outbox/.watch.lock). 이미 돌고 있으면 `RELAY-ERROR 전달 감시가 이미 켜져 있어요…`를 찍고 끝나요.
Claude 앱이 명령에 넘겨주는 CLAUDE_CODE_HOST_SESSION_ID(이 창의 local_… id, 문서로 정해진 값이 아니라 없을 수도 있어요)가 있으면
예전 총괄(outbox/.retired) 창에서 다시 켠 감시는 --boss에 무엇을 적었든 바로 끝내고, --boss가 이 창이 아니어도 끝내요.
총괄이 이 창으로 바뀌었을 때는 멈추지 않아요.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUT = os.path.join(HERE, "outbox")
HOME_ID = hashlib.sha256(HERE.encode("utf-8")).hexdigest()[:12]   # office_server.py와 같은 방식
ENV_PORT = os.environ.get("OFFICE_PORT", "").strip()
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1은 프록시를 거치지 않게
SESSION_ID = re.compile(r"^local_[0-9a-f-]{8,64}\Z")   # office_server.py와 같아요
HOST_SID = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", "")   # 이 감시기를 켠 Claude 창(알 때만, 위 설명)
HOST_SID = HOST_SID if SESSION_ID.match(HOST_SID) else None
RETIRED = os.path.join(OUT, ".retired")   # 바뀌기 전 총괄 id(한 줄에 하나). 서버가 총괄을 바꿀 때 적어요
CHANGED = "RELAY-ERROR 총괄이 바뀌었어요. 감시를 멈춰요."
WATCHING = os.path.join(OUT, ".watching")   # 0.7.0부터의 감시기만 고치는 heartbeat(내용은 내 총괄 id)
os.makedirs(OUT, exist_ok=True)
announced = {}   # 파일 이름 -> 마지막으로 알린 시각


def file_port():
    try:
        with open(os.path.join(OUT, ".port")) as f:
            p = f.read().strip()
        return p if p.isdigit() else None
    except OSError:
        return None


def ask(port, path):
    """서버에 물어본 답(dict). 닿지 않거나 에이전시티가 아니면 None."""
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            res = json.load(r)
    except Exception:  # noqa: BLE001 — 서버가 꺼져 있으면 다음에 다시
        return None
    return res if isinstance(res, dict) else None


def org_boss():
    """org.json의 진짜 총괄 id(자리 표시용 local_00000000…은 빼요). 없으면 None, 못 읽으면 False(다음에 다시 봐요)."""
    try:
        with open(os.path.join(HERE, "org.json"), encoding="utf-8") as f:
            b = json.load(f).get("boss")
    except (OSError, ValueError, AttributeError):
        return False
    sid = b.get("sessionId") if isinstance(b, dict) else None
    return sid if isinstance(sid, str) and SESSION_ID.match(sid) and not sid.startswith("local_00000000") else None


def boss_waiting():
    """총괄 만들기가 새 세션을 기다리는 중인지(setup.json의 pendingBoss, 기다릴 시간 안)."""
    try:
        with open(os.path.join(HERE, "setup.json"), encoding="utf-8") as f:
            p = json.load(f).get("pendingBoss")
        return isinstance(p, dict) and p.get("state") in ("waiting", "pick") and datetime.fromisoformat(p["expires"]).timestamp() > time.time()
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return False


def retired():
    try:
        with open(RETIRED, encoding="utf-8") as f:
            return [x for x in f.read().split() if SESSION_ID.match(x)]
    except (OSError, UnicodeDecodeError):
        return []


def retire(sid):
    """총괄이 바뀐 걸 보고 끝날 때 예전 총괄 id를 outbox/.retired에 더해요(손으로 org.json을 고친 경우도 남게, 최근 20개)."""
    ids = [x for x in retired() if x != sid][-19:] + [sid]
    tmp = f"{RETIRED}.tmp{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(ids) + "\n")
        os.replace(tmp, RETIRED)
    except OSError:
        pass


def take_lock():
    """outbox/.watch.lock을 잡아요(감시기는 하나만). 다시 켤 때 앞 감시기가 막 끝나는 중일 수 있어 6초까지 기다려요.
    못 잡으면 False. 잠글 수 없는 곳이면 예전처럼 그냥 돌아요."""
    global LOCK_FD
    try:
        fd = os.open(os.path.join(OUT, ".watch.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return True
    end = time.time() + 6
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            LOCK_FD = fd   # 끝날 때까지 열어 둬요(닫으면 풀려요)
            return True
        except BlockingIOError:
            if time.time() > end:
                os.close(fd)
                return False
            time.sleep(0.5)
        except OSError:
            return True


def locked_exit():
    print("RELAY-ERROR 전달 감시가 이미 켜져 있어요. 이 감시는 멈춰요.", flush=True)
    sys.exit(0)


def server_ok(port):
    st = ask(port, "/api/state")
    return bool(st) and st.get("ok") is True and st.get("home") == HOME_ID


def genuine(path, port, mine):
    """True: 서버가 만든 그대로. False: 서버가 모르는 항목이거나 내용이 바뀜. None: 서버에 물어볼 수 없음.
    이 설치 폴더의 서버가 아니면(다시 켜는 사이 다른 사무실이 그 포트에 있을 때) None이에요. 항목을 rejected/로 옮기지 않게요.
    mine(내 총괄, 모르면 '-')을 같이 보내요. 서버는 그게 지금 총괄이 아니면 답하지 않아요(409 → None)."""
    if not server_ok(port):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            item = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(item, dict):
        return False
    res = ask(port, "/api/outbox/check?id=" + urllib.parse.quote(str(item.get("id", ""))) + "&boss=" + urllib.parse.quote(mine or "-"))
    if res is None:
        return None
    h = hashlib.sha256(f"{item.get('to')}\n{item.get('text')}".encode("utf-8")).hexdigest()
    return bool(res.get("ok")) and res.get("sha") == h and f"{item.get('id')}.json" == os.path.basename(path)


ap = argparse.ArgumentParser(description="총괄 세션이 Monitor로 돌리는 전달 감시기")
ap.add_argument("--boss", help="내 총괄 세션 id(local_…). 그 세션이 총괄이 될 때까지 알리지 않아요. 없으면 켤 때 org.json의 boss.sessionId")
args = ap.parse_args()
if args.boss is not None and not SESSION_ID.match(args.boss):
    ap.error("--boss는 local_… 모양의 세션 id예요")
cur = org_boss()
if HOST_SID and HOST_SID in retired():   # 이 창이 바뀌기 전 총괄이에요(--boss에 새 총괄 id를 적었어도)
    print(CHANGED, flush=True)
    sys.exit(0)
if HOST_SID and args.boss and args.boss != HOST_SID:   # --boss에는 이 창의 id만 적어요
    print("RELAY-ERROR --boss에는 이 창의 세션 id를 적어요. 감시를 멈춰요.", flush=True)
    sys.exit(0)
me = args.boss or HOST_SID   # 이 감시기를 켠 창(알 때만)
if cur and me and me != cur and me in retired():   # 바뀌기 전 총괄 창이 감시를 다시 켰어요
    print(CHANGED, flush=True)
    sys.exit(0)
if not me and retired():   # 총괄을 바꾼 뒤, 누가 켰는지 모르는 감시(예전 지시로 다시 켠 예전 총괄 창일 수 있어요)
    print("RELAY-ERROR 총괄이 바뀌었어요. --boss 없이 켠 감시는 멈춰요. 내가 지금 총괄이면 --boss <내 세션 id>로 다시 켜요.", flush=True)
    sys.exit(0)
mine = args.boss or cur or None   # 내 총괄(아직 모르면 None). 총괄 바꾸기를 기다리는 중이어도 지금 총괄이에요
active = not args.boss            # --boss면 그 세션이 총괄이 될 때까지 알리지도, heartbeat를 고치지도 않아요
if active and not take_lock():
    locked_exit()
ppid = os.getppid()
last_ok = last_probe = 0.0
down_said = False
mismatch_said = None
while True:
    try:
        t = time.time()
        fp = file_port()
        port = ENV_PORT or fp or "8765"
        if ENV_PORT and fp and fp != ENV_PORT and mismatch_said != fp:
            mismatch_said = fp
            print(f"RELAY-ERROR 서버는 {fp} 포트에 켜져 있는데 OFFICE_PORT={ENV_PORT}로 감시 중이에요. OFFICE_PORT 없이 다시 켜요.", flush=True)
        if t - last_probe >= 3:
            last_probe = t
            if ppid != 1 and os.getppid() == 1:   # 켠 쪽(Monitor)이 끝나 혼자 남았어요. 잠금을 쥔 채 남지 않게 끝내요
                sys.exit(0)
            cur = org_boss()
            if not active:   # --boss: 그 세션이 총괄이 되면 시작하고, 총괄 바꾸기를 기다리는 중도 아니면 끝내요
                if cur == mine:
                    active = take_lock() or locked_exit()
                elif cur is not False and not boss_waiting():
                    print(CHANGED if mine in retired() else "RELAY-ERROR --boss로 적은 세션은 지금 총괄이 아니에요. 감시를 멈춰요.", flush=True)
                    sys.exit(0)
            elif cur:   # 못 읽었거나 총괄이 없으면 그대로 둬요
                if mine is None:
                    if not boss_waiting():
                        mine = cur
                elif cur != mine:
                    if args.boss or HOST_SID != cur:
                        retire(mine)
                        print(CHANGED, flush=True)
                        sys.exit(0)
                    mine = cur   # 총괄이 바로 이 창으로 바뀌었어요
            if active and server_ok(port):
                last_ok, down_said = t, False
            elif active and t - last_ok > 5 and not down_said:
                down_said = True
                print(f"RELAY-ERROR 서버에 연결 못 함 (포트 {port}). 사무실 서버가 켜져 있는지 확인해요.", flush=True)
        if not active:
            time.sleep(1)
            continue
        if t - last_ok <= 5:
            with open(os.path.join(OUT, ".heartbeat"), "w") as f:
                f.write(str(t))
            with open(WATCHING, "w") as f:
                f.write(mine or "-")
        names = sorted(n for n in os.listdir(OUT) if n.endswith(".json"))
        for n in names:
            p = os.path.join(OUT, n)
            last = announced.get(n)
            if last is None:
                g = genuine(p, port, mine)
                if g is None:
                    continue
                if not g:
                    if not os.path.exists(p):   # 그사이 서버가 켜지며 옮겼어요(앞 서버가 넘기지 않은 항목)
                        continue
                    os.makedirs(os.path.join(OUT, "rejected"), exist_ok=True)
                    shutil.move(p, os.path.join(OUT, "rejected", n))
                    print(f"RELAY-REJECT {os.path.join(OUT, 'rejected', n)}", flush=True)
                    continue
                announced[n] = t
                print(f"RELAY {p}", flush=True)
            elif t - last > 90:
                announced[n] = t
                print(f"RELAY-STALE {p}", flush=True)
        for n in list(announced):
            if n not in names:
                del announced[n]
    except OSError as e:
        print(f"RELAY-ERROR {e}", flush=True)
    time.sleep(1)
