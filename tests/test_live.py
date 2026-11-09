"""에이전시티 U-27 시험: 세션 실행 상태를 /api/state의 live로 줘요. 가짜 폴더만 써요. 진짜 세션 파일은 건드리지 않아요.

python3 -m unittest tests/test_live.py -v      (저장소 맨 위에서)

쓰는 칸(hostSessionId, pid, status, statusUpdatedAt, startedAt, sessionId) 밖의 값은 답에 나오지 않고, .key 파일은 열지 않아요.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_city import LOCAL, TMP_BASE, copy_repo, free_port   # noqa: E402
from test_scene import CHROME   # noqa: E402

LEAD, DEV, DES = ("local_aaaaaaaa-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3))
EXAMPLE, STRANGER = "local_aaaaaaaa-0000-4000-8000-000000000009", "local_bbbbbbbb-0000-4000-8000-000000000001"
ODD, PLACEHOLDER = "local_aaaaaaaa-0000-4000-8000-000000000004", "local_00000000-0000-4000-8000-000000000000"
SID = "11111111-2222-4333-8444-555555555555"
SECRET = ("가짜제목표시", "/private/tmp/가짜폴더표시", "/private/tmp/가짜소켓표시", "peerToken표시값")


class LiveState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="agencity-u27-", dir=TMP_BASE)
        cls.dir = copy_repo(os.path.join(cls.tmp, "app"))
        cls.home, cls.rundir = os.path.join(cls.tmp, "home"), os.path.join(cls.tmp, "run")
        cls.conf = os.path.join(cls.tmp, "conf")
        cls.projects = os.path.join(cls.home, ".claude", "projects")
        for d in (cls.conf, cls.rundir, cls.projects):
            os.makedirs(d)
        cls.floor("t1", "teams/t1", [{"role": "팀장", "sessionId": LEAD}, {"role": "개발자", "sessionId": DEV}, {"role": "디자이너", "sessionId": DES},
                                      {"role": "QA", "sessionId": None}, {"role": "코덱스", "codexId": "cccccccc-0000-4000-8000-000000000001"}])
        cls.floor("t2", "teams/t2", [{"role": "프론트 개발", "sessionId": ODD}, {"role": 7, "sessionId": ODD}, {"role": "자리표시", "sessionId": PLACEHOLDER}])
        cls.floor("ex", "examples/x", [{"role": "팀장", "sessionId": EXAMPLE}])
        with open(os.path.join(cls.dir, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"boss": {"name": "총괄", "title": "시험", "sessionId": "local_cccccccc-0000-4000-8000-000000000001"},
                       "teams": [{"id": "t1", "name": "층", "office": "teams/t1", "floor": 1}, {"id": "ex", "name": "예시", "office": "examples/x", "floor": 2},
                                 {"id": "bad", "name": "깨진 층", "office": "teams/bad", "floor": 3}, {"id": "t2", "name": "이름이 다른 층", "office": "teams/t2", "floor": 4}]}, f, ensure_ascii=False)
        with open(os.path.join(cls.dir, "setup.json"), "w", encoding="utf-8") as f:
            json.dump({"done": True}, f)
        subprocess.run([sys.executable, "-I", "build.py"], cwd=cls.dir, check=True, capture_output=True)
        os.makedirs(os.path.join(cls.dir, "teams", "bad", "status"))
        with open(os.path.join(cls.dir, "teams", "bad", "team.json"), "w", encoding="utf-8") as f:
            f.write("{깨진 파일")                                                                          # 층 하나가 깨져도 다른 층은 봐요
        cls.port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("AGENCITY_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"))}
        env.update(HOME=cls.home, OFFICE_PORT=str(cls.port), AGENCITY_CONFIG_DIR=cls.conf, AGENCITY_UPDATE_INTERVAL="999999999", AGENCITY_CLAUDE_RUN_DIR=cls.rundir,
                   AGENCITY_UPDATE_BASE="http://127.0.0.1:9", AGENCITY_UPDATE_RAW="http://127.0.0.1:9", AGENCITY_GITHUB_API="http://127.0.0.1:9", AGENCITY_GITHUB_BASE="http://127.0.0.1:9",
                   AGENCITY_SKILLS_BASE="http://127.0.0.1:9")
        cls.env = env
        cls.proc = subprocess.Popen([sys.executable, "-I", "office_server.py"], cwd=cls.dir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(100):
            try:
                page = LOCAL.open(cls.base + "/", timeout=2).read().decode("utf-8")
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("서버가 켜지지 않았어요")
        cls.token = re.search(r"const TOKEN = '([A-Za-z0-9_-]{20,})'", page).group(1)
        cls.sleepers = [subprocess.Popen(["sleep", "300"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(4)]

    @classmethod
    def floor(cls, tid, office, members):
        base = os.path.join(cls.dir, office)
        os.makedirs(os.path.join(base, "status"))
        with open(os.path.join(base, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": tid, "members": members}, f, ensure_ascii=False)

    @classmethod
    def tearDownClass(cls):
        for s in cls.sleepers:
            s.kill()
            s.wait()
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        for n in os.listdir(self.rundir):
            os.remove(os.path.join(self.rundir, n))

    def pid(self, i=0):
        return self.sleepers[i].pid

    def session(self, host, status, ago=0, i=0, **over):
        """가짜 pid 파일 하나. ago초 전에 status가 됐고 10분 전에 켜졌어요."""
        now = int(time.time() * 1000)
        rec = {"pid": self.pid(i), "hostSessionId": host, "status": status, "statusUpdatedAt": now - int(ago * 1000), "startedAt": now - int(ago * 1000) - 600000, "sessionId": SID,
               "name": SECRET[0], "cwd": SECRET[1], "messagingSocketPath": SECRET[2], "waitingFor": "권한", "kind": "interactive"}
        rec.update(over)
        with open(os.path.join(self.rundir, f"{self.pid(i)}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)

    def state(self, headers=None):
        req = urllib.request.Request(self.base + "/api/state", headers=headers or {})
        with LOCAL.open(req, timeout=10) as r:
            self.assertEqual(r.status, 200)
            return r.read().decode("utf-8")

    def live(self):
        return json.loads(self.state()).get("live")

    def test_status_reaches_floor_and_role(self):
        self.session(LEAD, "busy", 2, 0)
        self.session(DEV, "waiting", 3, 1)
        self.session(DES, "idle", 4, 2)
        live = self.live()
        self.assertEqual(set(live), {"t1"})
        self.assertEqual({r: x["s"] for r, x in live["t1"].items()}, {"팀장": "busy", "개발자": "waiting", "디자이너": "idle"})
        for x in live["t1"].values():
            self.assertEqual(set(x), {"s", "since"})          # 층, 역할, 상태 낱말, 시각만 나가요
            self.assertIsInstance(x["since"], int)

    def test_strange_files_are_left_out(self):
        gone = subprocess.Popen(["true"])
        gone.wait()
        self.session(LEAD, "busy", i=0)
        with open(os.path.join(self.rundir, f"{gone.pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": gone.pid, "hostSessionId": DEV, "status": "busy", "statusUpdatedAt": 1}, f)     # 죽은 프로세스
        with open(os.path.join(self.rundir, "123.json"), "w", encoding="utf-8") as f:
            f.write("{깨진 파일")
        self.session(DEV, "busy", i=1, hostSessionId=None)                                                   # 키 없음
        self.session(DES, "thinking", i=2)                                                                   # 모르는 status
        with open(os.path.join(self.rundir, "99999999.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": self.pid(3), "hostSessionId": DES, "status": "busy", "statusUpdatedAt": 1}, f)  # 파일 이름과 pid가 달라요
        with open(os.path.join(self.rundir, "9999999999.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": 9999999999, "hostSessionId": DES, "status": "busy"}, f)                         # 이름 규칙에 맞는 큰 pid
        with open(os.path.join(self.rundir, "0.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": 0, "hostSessionId": DES, "status": "busy"}, f)                                  # 0은 프로세스 번호가 아니에요
        with open(os.path.join(self.rundir, "97.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": True, "hostSessionId": DES, "status": "busy"}, f)
        with open(os.path.join(self.rundir, f"{self.pid(3)}.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"pid": self.pid(3), "hostSessionId": DES, "status": "busy"}) + " " * 70000)    # 64KB가 넘어요
        self.assertEqual(self.live(), {"t1": {"팀장": mock.ANY}})

    def test_links_are_left_out(self):
        """일반 파일만 열어요. 이름이 맞아도 링크는 따라가지 않아요."""
        other = os.path.join(self.tmp, "링크 대상.json")
        with open(other, "w", encoding="utf-8") as f:
            json.dump({"pid": self.pid(0), "hostSessionId": LEAD, "status": "busy"}, f)
        os.symlink(other, os.path.join(self.rundir, f"{self.pid(0)}.json"))
        self.assertEqual(self.live(), {})

    def test_files_with_other_names_stay_closed(self):
        """.key 파일과 이름이 다른 파일은 열지 않아요. 파일에 넣은 표시 글이 답에 없고, 열기 호출도 0번이에요."""
        self.session(LEAD, "busy", i=0)
        for name in (f"{self.pid(0)}.key", "abc.json", "12345678901.json", "12.json.bak", "12.json\n"):
            with open(os.path.join(self.rundir, name), "w", encoding="utf-8") as f:
                f.write(json.dumps({"peerToken": SECRET[3], "pid": self.pid(1), "hostSessionId": DEV, "status": "busy"}))
        body = self.state()
        self.assertNotIn(SECRET[3], body)
        self.assertEqual(set(json.loads(body)["live"]["t1"]), {"팀장"})
        code = f"""
import json, sys
seen = []
sys.addaudithook(lambda e, a: seen.append(str(a[0])) if e == "open" else None)
sys.path.insert(0, {self.dir!r})
import office_server as o
seen.clear()
o.run_states()
print(json.dumps([x for x in seen if {self.rundir!r} in x]))
"""
        out = subprocess.run([sys.executable, "-I", "-c", code], cwd=self.dir, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [os.path.join(self.rundir, f"{self.pid(0)}.json")])

    def test_private_values_stay_out(self):
        self.session(LEAD, "busy", i=0)
        body = self.state()
        for word in SECRET[:3] + (SID, "권한"):
            self.assertNotIn(word, body)
        live = json.dumps(json.loads(body)["live"], ensure_ascii=False)
        for word in SECRET[:3] + (SID, LEAD, str(self.pid(0)), "권한"):
            self.assertNotIn(word, live)

    def test_only_real_seats(self):
        self.session(EXAMPLE, "busy", i=0)
        self.session(STRANGER, "busy", i=1)
        self.assertEqual(self.live(), {})

    def test_seats_outside_the_name_rule(self):
        """다른 도구가 쓴 역할 이름도 명단에 있으니 같이 이어요. 글이 아닌 역할과 자리 표시용 세션은 빼요."""
        self.session(ODD, "busy", i=0)
        self.assertEqual({t: set(x) for t, x in self.live().items()}, {"t2": {"프론트 개발"}})
        self.session(PLACEHOLDER, "busy", i=0)
        self.assertEqual(self.live(), {})

    @unittest.skipUnless(CHROME, "Chrome이 없어요")
    def test_page_shows_the_signal(self):
        """진짜 서버와 진짜 페이지를 이어요. 상태 파일은 대기인데 세션이 일하면 명단이 일하는 중이에요."""
        with open(os.path.join(self.dir, "teams", "t1", "status", "개발자.json"), "w", encoding="utf-8") as f:
            json.dump({"state": "대기", "task": "", "say": "", "updated": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}, f, ensure_ascii=False)
        self.session(DEV, "busy", 1, 1)
        with tempfile.TemporaryDirectory(dir=self.tmp) as d:
            r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--use-mock-keychain", "--password-store=basic", f"--user-data-dir={d}/c", "--window-size=1280,900", "--virtual-time-budget=3000", "--dump-dom", self.base + "/"], capture_output=True, text=True, timeout=60)
        self.assertRegex(r.stdout, r'aria-label="개발자, 일하는 중')

    def test_live_only_on_the_page_read(self):
        self.session(LEAD, "busy", i=0)
        self.assertIn('"live"', self.state())
        self.assertNotIn('"live"', self.state({"Origin": "http://127.0.0.1:9"}))
        said = json.dumps({"team": "t1", "thread": "chat:개발자", "text": "안녕"}).encode("utf-8")      # 전달 상태가 붙는 POST예요
        req = urllib.request.Request(self.base + "/api/say", data=said, method="POST", headers={"Content-Type": "application/json", "Origin": self.base, "X-Office-Token": self.token})
        with LOCAL.open(req, timeout=10) as r:
            body = r.read().decode("utf-8")
        self.assertIn('"pending"', body)
        self.assertNotIn('"live"', body)
        code = f"""
import json, sys
sys.path.insert(0, {self.dir!r})
import office_server as o
print(json.dumps("live" in o.api_state()))
"""
        out = subprocess.run([sys.executable, "-I", "-c", code], cwd=self.dir, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "false", out.stderr)

    def test_long_idle_and_fresh_start_drop_out(self):
        self.session(LEAD, "idle", 31, 0)
        self.assertEqual(self.live(), {})
        now = int(time.time() * 1000)
        self.session(LEAD, "idle", i=0, statusUpdatedAt=now - 1000, startedAt=now - 1500)        # 켜지기만 한 세션
        self.assertEqual(self.live(), {})
        self.session(LEAD, "idle", i=0, statusUpdatedAt=now - 1000, startedAt=now - 31000)       # 일을 마친 세션
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "idle")

    def test_start_rule_is_for_idle_only(self):
        """켠 지 3초 안의 idle만 빼요. 금방 일을 시작한 세션은 앉아요."""
        now = int(time.time() * 1000)
        for status in ("busy", "waiting"):
            self.session(LEAD, status, i=0, statusUpdatedAt=now - 1000, startedAt=now - 2500)
            self.assertEqual(self.live()["t1"]["팀장"]["s"], status)
        self.session(LEAD, "idle", i=0, statusUpdatedAt=now - 1000, startedAt=now - 3900)
        self.assertEqual(self.live(), {})
        self.session(LEAD, "idle", i=0, statusUpdatedAt=now - 1000, startedAt=now - 4100)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "idle")

    def test_newest_state_wins_for_one_seat(self):
        self.session(LEAD, "idle", 20, 0)
        self.session(LEAD, "busy", 1, 1)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")

    def test_bad_time_uses_the_file_clock(self):
        self.session(LEAD, "busy", i=0, statusUpdatedAt="어제")
        then = time.time() - 600
        os.utime(os.path.join(self.rundir, f"{self.pid(0)}.json"), (then, then))
        x = self.live()["t1"]["팀장"]
        self.assertLess(abs(x["since"] - then * 1000), 2000)

    def write_log(self, sid, age, sub=None, sub_age=0):
        d = os.path.join(self.projects, "p" + sid[:6])
        os.makedirs(d, exist_ok=True)
        main = os.path.join(d, sid + ".jsonl")
        with open(main, "w", encoding="utf-8"):
            pass
        then = time.time() - age
        os.utime(main, (then, then))
        if sub:
            f = os.path.join(d, sid, "subagents", *sub)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding="utf-8"):
                pass
            os.utime(f, (time.time() - sub_age,) * 2)
            for x in (os.path.dirname(f), os.path.dirname(os.path.dirname(f)), os.path.join(d, sid, "subagents"), os.path.join(d, sid)):
                os.utime(x, (then, then))                                                                 # 폴더 시각은 오래됐어요

    def test_quiet_needs_a_quiet_log(self):
        sid = "22222222-2222-4333-8444-000000000001"
        self.write_log(sid, 3000)
        self.session(LEAD, "busy", 31 * 60, 0, sessionId=sid)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "quiet")
        fresh = "22222222-2222-4333-8444-000000000002"
        self.write_log(fresh, 3000, ("workflows", "x", "agent-a.jsonl"), 5)
        self.session(LEAD, "busy", 31 * 60, 0, sessionId=fresh)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")                                          # 서브에이전트가 깊은 곳에서 일해요
        self.session(LEAD, "busy", 31 * 60, 0, sessionId="33333333-2222-4333-8444-000000000001")
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")                                          # 기록을 못 찾으면 quiet로 치지 않아요
        side = os.path.join(self.projects, "옆 폴더", "기록.jsonl")
        os.makedirs(os.path.dirname(side))
        with open(side, "w", encoding="utf-8"):
            pass
        os.utime(side, (time.time() - 3000,) * 2)
        self.session(LEAD, "busy", 31 * 60, 0, sessionId="../옆 폴더/기록")
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")                                          # uuid 모양만 경로에 넣어요

    def test_quiet_needs_both_long_busy_and_old_logs(self):
        """busy가 30분을 넘고 메인 기록도 30분 넘게 그대로일 때만 quiet예요. waiting은 사람을 기다리는 중이라 quiet가 아니에요."""
        fresh = "22222222-2222-4333-8444-000000000003"
        self.write_log(fresh, 5)
        self.session(LEAD, "busy", 31 * 60, 0, sessionId=fresh)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")                                          # 메인 기록이 움직여요
        old = "22222222-2222-4333-8444-000000000004"
        self.write_log(old, 3000)
        self.session(LEAD, "busy", 29 * 60, 0, sessionId=old)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")                                          # 아직 30분이 안 됐어요
        self.session(LEAD, "busy", 60, 0, sessionId=old)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "busy")
        self.session(LEAD, "waiting", 31 * 60, 0, sessionId=old)
        self.assertEqual(self.live()["t1"]["팀장"]["s"], "waiting")

    def test_quiet_check_is_cached_for_a_minute(self):
        code = """
import json, os, sys
sys.path.insert(0, os.getcwd())
import office_server as o
calls = []
def fake(sid, now):
    calls.append(now)
    return len(calls) > 1
o.run_log_quiet = fake
sid, at = "22222222-2222-4333-8444-000000000005", 1000000000000
print(json.dumps([o.run_quiet(sid, at), o.run_quiet(sid, at + 59000), o.run_quiet(sid, at + 61000), len(calls)]))
"""
        out = subprocess.run([sys.executable, "-I", "-c", code], cwd=self.dir, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [False, False, True, 2])

    def test_nothing_is_written(self):
        base = os.path.join(self.dir, "teams", "t1")
        status, log = os.path.join(base, "status", "팀장.json"), os.path.join(base, "log.jsonl")
        for p, text in ((status, '{"state":"대기","updated":"2026-11-01T00:00:00+09:00"}'), (log, '{"t":"x"}\n')):
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
        before = [pathlib.Path(p).read_bytes() for p in (status, log)]
        self.session(LEAD, "busy", i=0)
        self.state()
        self.assertEqual([pathlib.Path(p).read_bytes() for p in (status, log)], before)

    def test_folder_trouble(self):
        """폴더가 없으면 빈 값이에요. 읽다가 실패하면 live 칸을 빼서 페이지가 20초 동안 앞 값을 써요."""
        code = """
import json, os, sys
sys.path.insert(0, os.getcwd())
import office_server as o
o.RUN_DIR = os.path.join(o.RUN_DIR, "없는 폴더")
empty = o.run_states()
def boom():
    raise OSError("읽기 실패")
o.os.listdir, keep = (lambda p: boom()), o.os.listdir
try:
    o.run_states()
    raised = False
except OSError:
    raised = True
print(json.dumps({"empty": empty, "raised": raised}))
"""
        out = subprocess.run([sys.executable, "-I", "-c", code], cwd=self.dir, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), {"empty": {}, "raised": True})
        moved = self.rundir + ".moved"
        os.rename(self.rundir, moved)
        try:
            self.assertEqual(self.live(), {})
            with open(self.rundir, "w", encoding="utf-8"):                                                # 읽기 실패: 답은 200이고 live 칸만 빠져요
                pass
            self.assertNotIn("live", json.loads(self.state()))
        finally:
            if os.path.isfile(self.rundir):
                os.remove(self.rundir)
            os.rename(moved, self.rundir)


if __name__ == "__main__":
    unittest.main()
