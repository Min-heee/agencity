"""전달 감시기(bin/relay_watch.py) 시험: --until-item(Bash run_in_background로 켜는 모드)과 총괄 지시 글.

python3 -m unittest tests/test_relay_watch.py -v      (저장소 맨 위에서)

감시기를 임시 폴더(/private/tmp 아래)의 bin/에 복사해 그 폴더를 설치 폴더로 돌려요. 서버는 127.0.0.1의 빈 포트(9500번대)에 띄운
가짜(/api/state·/api/outbox/check)라서 진짜 사무실(~/agencity)과 그 총괄 창은 건드리지 않아요. 파이썬 표준 라이브러리만 써요.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TMP_BASE = "/private/tmp" if os.path.isdir("/private/tmp") else None
BOSS = "local_11111111-2222-3333-4444-555555555555"


def free_port(lo=9500, hi=9599):
    for p in range(lo, hi + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("빈 포트가 없어요")


class FakeOffice:
    """사무실 서버 흉내: 이 설치 폴더의 home과, 서버가 만든 항목(id -> sha)만 맞다고 답해요."""

    def __init__(self, here):
        self.home = hashlib.sha256(here.encode("utf-8")).hexdigest()[:12]
        self.issued = {}
        office = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path == "/api/state":
                    res = {"ok": True, "home": office.home}
                elif u.path == "/api/outbox/check" and q.get("id") in office.issued:
                    res = {"ok": True, "sha": office.issued[q["id"]]}
                else:
                    res = {"ok": False}
                body = json.dumps(res).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.port = free_port()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


class UntilItem(unittest.TestCase):
    def setUp(self):
        self.here = os.path.realpath(tempfile.mkdtemp(prefix="relaywatch-", dir=TMP_BASE))
        os.makedirs(os.path.join(self.here, "bin"))
        shutil.copy(os.path.join(ROOT, "bin", "relay_watch.py"), os.path.join(self.here, "bin"))
        self.out = os.path.join(self.here, "outbox")
        os.makedirs(self.out)
        with open(os.path.join(self.here, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"boss": {"sessionId": BOSS}}, f)
        self.office = FakeOffice(self.here)
        with open(os.path.join(self.out, ".port"), "w") as f:
            f.write(str(self.office.port))
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
        self.office.stop()
        shutil.rmtree(self.here, ignore_errors=True)

    def start(self, *extra):
        env = {k: v for k, v in os.environ.items() if k not in ("OFFICE_PORT", "CLAUDE_CODE_HOST_SESSION_ID")}
        p = subprocess.Popen([sys.executable, "-I", "-u", os.path.join(self.here, "bin", "relay_watch.py"), "--boss", BOSS, *extra],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        self.procs.append(p)
        return p

    def item(self, iid, to=BOSS, text="안녕", genuine=True):
        with open(os.path.join(self.out, f"{iid}.json"), "w", encoding="utf-8") as f:
            json.dump({"id": iid, "to": to, "text": text}, f)
        if genuine:
            self.office.issued[iid] = hashlib.sha256(f"{to}\n{text}".encode("utf-8")).hexdigest()
        return os.path.join(self.out, f"{iid}.json")

    def wait_heartbeat(self, timeout=8):
        hb = os.path.join(self.out, ".heartbeat")
        end = time.time() + timeout
        while time.time() < end:
            if os.path.exists(hb) and abs(time.time() - os.path.getmtime(hb)) < 3:
                return
            time.sleep(0.2)
        self.fail("감시기가 .heartbeat를 고치지 않았어요")

    def finish(self, p, timeout=10):
        try:
            out, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.fail("감시기가 끝나지 않았어요")
        return out.splitlines()

    def still_running(self, p, secs):
        time.sleep(secs)
        self.assertIsNone(p.poll(), "감시기가 너무 일찍 끝났어요")

    def test_idle_keeps_running_with_heartbeat(self):
        p = self.start("--until-item")
        self.wait_heartbeat()
        self.still_running(p, 4)
        self.wait_heartbeat()   # 계속 고쳐요(사이트의 '총괄 연결됨')
        with open(os.path.join(self.out, ".watching"), encoding="utf-8") as f:
            self.assertEqual(f.read(), BOSS)

    def test_exits_with_item_and_hands_off(self):
        p = self.start("--until-item")
        self.wait_heartbeat()
        path = self.item("a1")
        t0 = time.time()
        lines = self.finish(p)
        self.assertEqual(lines, [f"RELAY {path}"])
        self.assertEqual(p.returncode, 0)
        self.assertLess(time.time() - t0, 8)
        for name in (".heartbeat", ".watching"):   # 총괄이 다시 켜는 사이에도 '총괄 연결됨'
            self.assertGreater(os.path.getmtime(os.path.join(self.out, name)) - time.time(), 20)
        with open(os.path.join(self.out, ".announced"), encoding="utf-8") as f:
            self.assertIn("a1.json", json.load(f))
        self.assertTrue(os.path.exists(path))   # 옮기는 건 총괄(relay_done.sh)이에요

    def test_items_together_one_wake(self):
        p = self.start("--until-item")
        self.wait_heartbeat()
        a = self.item("b1")
        b = self.item("b2", text="둘째")
        self.assertEqual(sorted(self.finish(p)), sorted([f"RELAY {a}", f"RELAY {b}"]))

    def test_restart_does_not_repeat_then_stale(self):
        p = self.start("--until-item")
        self.wait_heartbeat()
        path = self.item("c1")
        self.assertEqual(self.finish(p), [f"RELAY {path}"])
        p2 = self.start("--until-item")   # 총괄이 바로 다시 켠 감시기: 같은 항목을 또 깨우지 않아요
        self.still_running(p2, 4)
        p2.kill()
        p2.wait()
        with open(os.path.join(self.out, ".announced"), "w", encoding="utf-8") as f:
            json.dump({"c1.json": time.time() - 100}, f)   # 알린 지 90초가 지났어요
        p3 = self.start("--until-item")
        self.assertEqual(self.finish(p3), [f"RELAY-STALE {path}"])

    def test_delivered_items_are_forgotten(self):
        p = self.start("--until-item")
        self.wait_heartbeat()
        path = self.item("d1")
        self.finish(p)
        os.makedirs(os.path.join(self.out, "sent"))
        shutil.move(path, os.path.join(self.out, "sent", "d1.json"))   # relay_done.sh가 하는 일
        p2 = self.start("--until-item")
        self.wait_heartbeat()
        time.sleep(1.5)
        with open(os.path.join(self.out, ".announced"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {})
        self.assertIsNone(p2.poll())

    def test_forged_announced_is_checked(self):
        # .announced는 outbox에 쓸 수 있는 누구나 고칠 수 있어요. 거기 적힌 이름도 다시 알리기 전에 서버에 확인해요
        self.item("f1", genuine=False)
        with open(os.path.join(self.out, ".announced"), "w", encoding="utf-8") as f:
            json.dump({"f1.json": 0}, f)
        p = self.start("--until-item")
        rej = os.path.join(self.out, "rejected", "f1.json")
        self.assertEqual(self.finish(p), [f"RELAY-REJECT {rej}"])
        self.assertTrue(os.path.exists(rej))

    def test_exits_even_if_reject_keeps_failing(self):
        # 같은 바퀴의 뒤 항목에서 파일 오류가 계속 나도(rejected가 파일), 앞에서 알린 항목 때문에 꼭 끝나서 총괄을 깨워요
        with open(os.path.join(self.out, "rejected"), "w") as f:
            f.write("not a folder")
        p = self.start("--until-item")
        self.wait_heartbeat()
        a = self.item("g1")
        self.item("g2", genuine=False)
        lines = self.finish(p)
        self.assertIn(f"RELAY {a}", lines)
        self.assertEqual(p.returncode, 0)

    def test_reject_wakes(self):
        p = self.start("--until-item")
        self.wait_heartbeat()
        self.item("e1", genuine=False)
        rej = os.path.join(self.out, "rejected", "e1.json")
        self.assertEqual(self.finish(p), [f"RELAY-REJECT {rej}"])
        self.assertTrue(os.path.exists(rej))

    def test_server_down_waits_quietly(self):
        with open(os.path.join(self.out, ".port"), "w") as f:   # 아무도 듣지 않는 포트
            f.write(str(free_port(9600, 9699)))
        p = self.start("--until-item")
        self.still_running(p, 8)   # 5초 넘게 닿지 않아도 끝내지 않아요(끝내면 총괄이 깨어 턴을 써요)
        p.kill()
        out, _ = p.communicate()
        self.assertEqual(out, "")

    def test_other_boss_stops(self):
        with open(os.path.join(self.here, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"boss": {"sessionId": "local_99999999-2222-3333-4444-555555555555"}}, f)
        p = self.start("--until-item")
        lines = self.finish(p)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("RELAY-ERROR "))

    def test_monitor_mode_keeps_running(self):
        p = self.start()   # 예전 지시(Monitor)로 켠 감시기는 그대로예요
        self.wait_heartbeat()
        self.item("f1")
        self.still_running(p, 4)
        self.assertFalse(os.path.exists(os.path.join(self.out, ".announced")))


class CoordinatorText(unittest.TestCase):
    """총괄 지시(docs/COORDINATOR.md)·[다시 연결] 글이 --until-item을 Bash run_in_background로 켜게 하고, 첫 메시지가 길이 제한 안인지."""

    @classmethod
    def setUpClass(cls):
        cls.here = os.path.realpath(tempfile.mkdtemp(prefix="relaywatch-doc-", dir=TMP_BASE))
        cls.inst = os.path.join(cls.here, "아주 긴 설치 폴더 이름 " * 6).rstrip()   # 긴 경로에서도 6000자 안
        os.makedirs(os.path.join(cls.inst, "docs"))
        shutil.copy(os.path.join(ROOT, "office_server.py"), cls.inst)
        shutil.copy(os.path.join(ROOT, "docs", "COORDINATOR.md"), os.path.join(cls.inst, "docs"))
        with open(os.path.join(cls.inst, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"boss": {"sessionId": BOSS}}, f)
        sys.path.insert(0, cls.inst)
        try:
            import office_server
        finally:
            sys.path.remove(cls.inst)
        cls.srv = office_server
        sys.modules.pop("office_server", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.here, ignore_errors=True)

    def test_instruction_uses_background_bash(self):
        text = self.srv.coordinator_text()
        self.assertIn("run_in_background", text)
        self.assertIn("--until-item", text)
        self.assertNotIn("Monitor 도구로", text)   # 예전 지시(30분마다 다시 켜기)
        self.assertNotIn("최대 30분", text)

    def test_boss_prompt_fits(self):
        self.assertLess(len(self.srv.boss_prompt("AGC-0000abcd", BOSS)), self.srv.BOSS_PROMPT_MAX)

    def test_rearm_text(self):
        text = self.srv.rearm_text()
        self.assertIn("run_in_background", text)
        self.assertIn(f"--boss {BOSS} --until-item", text)
        self.assertNotIn("Monitor 도구로", text)   # 예전 지시(30분마다 다시 켜기)
        self.assertNotIn("최대 30분", text)


if __name__ == "__main__":
    unittest.main()
