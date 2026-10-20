"""총괄 세션이 Monitor로 돌리는 감시기.

outbox/에 새 '전달할 메시지'가 생기면, 서버가 만든 항목인지(/api/outbox/check, 내용 해시 비교) 확인한 뒤
`RELAY <파일>`을 찍어요. 서버가 만든 게 아니면 outbox/rejected/로 옮기고 `RELAY-REJECT <파일>`을 찍어요.
90초 넘게 남아 있는 항목은 `RELAY-STALE <파일>`로 다시 알려요(총괄이 놓쳤을 때).
1초마다 outbox/.heartbeat를 고쳐서, 사이트가 '총괄 연결됨'을 알 수 있게 해요.
총괄은 RELAY 파일을 읽고 SendMessage로 전한 뒤 bin/relay_done.sh로 outbox/sent/에 옮겨요.
"""
import hashlib
import json
import os
import shutil
import time
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outbox")
PORT = os.environ.get("OFFICE_PORT", "8765")   # 서버와 같은 포트
CHECK = f"http://127.0.0.1:{PORT}/api/outbox/check?id="
os.makedirs(OUT, exist_ok=True)
announced = {}   # 파일 이름 -> 마지막으로 알린 시각


def genuine(path):
    """True: 서버가 만든 그대로. False: 서버가 모르는 항목이거나 내용이 바뀜. None: 서버에 물어볼 수 없음."""
    try:
        with open(path, encoding="utf-8") as f:
            item = json.load(f)
    except (OSError, ValueError):
        return False
    try:
        with urllib.request.urlopen(CHECK + urllib.parse.quote(str(item.get("id", ""))), timeout=3) as r:
            res = json.load(r)
    except Exception:  # noqa: BLE001 — 서버가 꺼져 있으면 다음에 다시
        return None
    h = hashlib.sha256(f"{item.get('to')}\n{item.get('text')}".encode("utf-8")).hexdigest()
    return bool(res.get("ok")) and res.get("sha") == h and f"{item.get('id')}.json" == os.path.basename(path)


while True:
    try:
        with open(os.path.join(OUT, ".heartbeat"), "w") as f:
            f.write(str(time.time()))
        names = sorted(n for n in os.listdir(OUT) if n.endswith(".json"))
        t = time.time()
        for n in names:
            p = os.path.join(OUT, n)
            last = announced.get(n)
            if last is None:
                g = genuine(p)
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
