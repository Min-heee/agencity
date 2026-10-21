"""총괄 세션이 Monitor로 돌리는 감시기.

outbox/에 새 '전달할 메시지'가 생기면, 서버가 만든 항목인지(/api/outbox/check, 내용 해시 비교) 확인한 뒤
`RELAY <파일>`을 찍어요. 서버가 만든 게 아니면 outbox/rejected/로 옮기고 `RELAY-REJECT <파일>`을 찍어요.
90초 넘게 남아 있는 항목은 `RELAY-STALE <파일>`로 다시 알려요(총괄이 놓쳤을 때).
서버에 닿을 때만 1초마다 outbox/.heartbeat를 고쳐서, 사이트가 '총괄 연결됨'을 알 수 있게 해요.
서버에 5초 넘게 닿지 않으면 `RELAY-ERROR 서버에 연결 못 함`을 한 번 찍어요.
포트는 OFFICE_PORT가 있으면 그것, 없으면 서버가 켜질 때 적어 두는 outbox/.port를 매번 다시 읽어요.
총괄은 RELAY 파일을 읽고 SendMessage로 전한 뒤 bin/relay_done.sh로 outbox/sent/에 옮겨요.
"""
import hashlib
import json
import os
import shutil
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUT = os.path.join(HERE, "outbox")
HOME_ID = hashlib.sha256(HERE.encode("utf-8")).hexdigest()[:12]   # office_server.py와 같은 방식
ENV_PORT = os.environ.get("OFFICE_PORT", "").strip()
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1은 프록시를 거치지 않게
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


def server_ok(port):
    st = ask(port, "/api/state")
    return bool(st) and st.get("ok") is True and st.get("home") == HOME_ID


def genuine(path, port):
    """True: 서버가 만든 그대로. False: 서버가 모르는 항목이거나 내용이 바뀜. None: 서버에 물어볼 수 없음."""
    try:
        with open(path, encoding="utf-8") as f:
            item = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(item, dict):
        return False
    res = ask(port, "/api/outbox/check?id=" + urllib.parse.quote(str(item.get("id", ""))))
    if res is None:
        return None
    h = hashlib.sha256(f"{item.get('to')}\n{item.get('text')}".encode("utf-8")).hexdigest()
    return bool(res.get("ok")) and res.get("sha") == h and f"{item.get('id')}.json" == os.path.basename(path)


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
            if server_ok(port):
                last_ok, down_said = t, False
            elif t - last_ok > 5 and not down_said:
                down_said = True
                print(f"RELAY-ERROR 서버에 연결 못 함 (포트 {port}). 사무실 서버가 켜져 있는지 확인해요.", flush=True)
        if t - last_ok <= 5:
            with open(os.path.join(OUT, ".heartbeat"), "w") as f:
                f.write(str(t))
        names = sorted(n for n in os.listdir(OUT) if n.endswith(".json"))
        for n in names:
            p = os.path.join(OUT, n)
            last = announced.get(n)
            if last is None:
                g = genuine(p, port)
                if g is None:
                    continue
                if not g:
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
