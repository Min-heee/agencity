"""에이전시티 도시 U-12 시험: 나라(profile.country)·공개 미리보기 지문·자동 올리기 간격·설치 없이 올리는 명령·
명령 태그와 VERSION·화면 글의 token-meter 이름.

python3 -m unittest tests/test_city.py -v      (저장소 맨 위에서)

진짜 GitHub·gist·도시 명단은 쓰지 않아요. 127.0.0.1의 빈 포트(9400번대)에 가짜 GitHub(gist API·기기 로그인)과 가짜 명단을 띄우고,
저장소를 임시 폴더(/private/tmp 아래)에 복사해 그 안에서 서버(office_server.py)·공개 도우미(bin/office_public.py)·
명령(bin/city_join.py)을 돌려요. HOME도 임시 폴더라 이 컴퓨터의 Claude 기록·설정은 읽지 않아요.
파이썬 표준 라이브러리만 써요.
"""
import hashlib
import json
import os
import pty
import re
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TMP_BASE = "/private/tmp" if os.path.isdir("/private/tmp") else None
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ME = "tester"


def free_port(lo=9400, hi=9499):
    for p in range(lo, hi + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("9400번대에 빈 포트가 없어요")


class FakeGitHub:
    """gist API 일부(user, gists 목록·하나·만들기·고치기), 기기 로그인, 도시 명단(/tm/members.json),
    설치 없이 돌릴 때 받는 파일(/raw/<저장소 안 경로>, raw에 없으면 404)."""

    def __init__(self):
        self.gists, self.calls, self.members, self.seq, self.raw = {}, [], [], 0, {}
        self.port = free_port()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, obj):
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode("utf-8") if n else ""
                if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
                    return {k: v[0] for k, v in parse_qs(raw).items()}
                return json.loads(raw or "{}")

            def authed(self):
                return self.headers.get("Authorization", "").startswith("Bearer ")

            def do_GET(self):
                u = urlsplit(self.path)
                fake.calls.append(("GET", u.path, None))
                if u.path.startswith("/raw/"):
                    txt = fake.raw.get(u.path[len("/raw/"):])
                    if txt is None:
                        return self.reply(404, {"message": "Not Found"})
                    data = txt.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                if u.path == "/tm/members.json":
                    return self.reply(200, {"members": fake.members})
                if not self.authed():
                    return self.reply(401, {"message": "Bad credentials"})
                if u.path == "/user":
                    return self.reply(200, {"login": ME})
                if u.path == "/gists":
                    return self.reply(200, [fake.view(g, False) for g in fake.gists.values()])
                m = re.match(r"^/gists/([0-9a-f]+)$", u.path)
                if m and m.group(1) in fake.gists:
                    return self.reply(200, fake.view(fake.gists[m.group(1)], True))
                return self.reply(404, {"message": "Not Found"})

            def do_POST(self):
                u, b = urlsplit(self.path), self.body()
                fake.calls.append(("POST", u.path, b))
                if u.path == "/login/device/code":
                    return self.reply(200, {"device_code": "devicecode123456", "user_code": "ABCD-1234", "verification_uri": f"http://127.0.0.1:{fake.port}/login/device",
                                            "interval": 1, "expires_in": 120})
                if u.path == "/login/oauth/access_token":
                    return self.reply(200, {"access_token": "faketoken_1234567890", "token_type": "bearer", "scope": "gist"})
                if u.path == "/gists" and self.authed():
                    fake.seq += 1
                    gid = f"{fake.seq:04d}abcdef0123456789"
                    fake.gists[gid] = {"id": gid, "public": b.get("public") is True, "description": b.get("description"),
                                       "files": {k: v["content"] for k, v in b["files"].items() if v}, "updated_at": f"2026-10-24T00:00:{fake.seq:02d}Z"}
                    return self.reply(201, fake.view(fake.gists[gid], True))
                return self.reply(404, {"message": "Not Found"})

            def do_PATCH(self):
                u, b = urlsplit(self.path), self.body()
                fake.calls.append(("PATCH", u.path, b))
                m = re.match(r"^/gists/([0-9a-f]+)$", u.path)
                if not (m and m.group(1) in fake.gists and self.authed()):
                    return self.reply(404, {"message": "Not Found"})
                g = fake.gists[m.group(1)]
                for k, v in b.get("files", {}).items():
                    if v is None:
                        g["files"].pop(k, None)
                    else:
                        g["files"][k] = v["content"]
                return self.reply(200, fake.view(g, True))

        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.port}"

    def view(self, g, content):
        files = {k: dict({"filename": k, "truncated": False}, **({"content": v} if content else {})) for k, v in g["files"].items()}
        return {"id": g["id"], "public": g["public"], "owner": {"login": ME}, "description": g.get("description"), "files": files,
                "updated_at": g["updated_at"], "html_url": f"https://gist.github.com/{ME}/{g['id']}"}

    def add(self, files):
        self.seq += 1
        gid = f"{self.seq:04d}fedcba9876543210"
        self.gists[gid] = {"id": gid, "public": True, "description": "x", "files": dict(files), "updated_at": f"2026-10-23T00:00:{self.seq:02d}Z"}
        return gid

    def doc(self, gid, name):
        t = self.gists[gid]["files"].get(name)
        return None if t is None else json.loads(t)

    def writes(self):
        return [c for c in self.calls if c[0] in ("PATCH",) or (c[0] == "POST" and c[1] == "/gists")]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def copy_repo(dst):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".claude", "org.json", "setup.json", "public.json", "teams",
                                                              "hq", "outbox", ".update", ".usage", "tests"))
    return dst


def fake_logs(home, days=(("2026-10-23T03:00:00.000Z", 1200, 340), ("2026-10-24T05:10:00.000Z", 5000, 900))):
    d = os.path.join(home, ".claude", "projects", "p1")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "s.jsonl"), "w", encoding="utf-8") as f:
        for i, (ts, inp, out) in enumerate(days):
            f.write(json.dumps({"type": "assistant", "timestamp": ts, "sessionId": "s1", "requestId": f"r{i}",
                                "message": {"id": f"m{i}", "model": "claude-opus-5-5", "usage": {"input_tokens": inp, "output_tokens": out,
                                                                                               "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000}}}) + "\n")


class CountryList(unittest.TestCase):
    def test_countries_file(self):
        with open(os.path.join(ROOT, "city", "countries.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertEqual(len(c), 249)
        self.assertEqual(c, sorted(set(c)))
        self.assertTrue(all(re.match(r"^[A-Z]{2}$", x) for x in c))
        for x in ("KR", "JP", "US", "DE", "GB", "TW", "PS", "XK" if "XK" in c else "KR"):
            self.assertIn(x, c)
        self.assertNotIn("XX", c)

    @staticmethod
    def join_ref():
        with open(os.path.join(ROOT, "city.html"), encoding="utf-8") as f:
            return re.search(r"const JOIN_REF = '([^']+)'", f.read()).group(1)

    def test_join_ref_matches(self):
        """city.html의 명령 태그(JOIN_REF), bin/city_join.py의 REF, GUIDE의 명령이 같아야 해요(받은 스크립트가 같은 판의 파일을 받게)."""
        ref_page = self.join_ref()
        with open(os.path.join(ROOT, "bin", "city_join.py"), encoding="utf-8") as f:
            ref_cmd = re.search(r'^REF = "([^"]+)"', f.read(), re.M).group(1)
        self.assertEqual(ref_page, ref_cmd)
        with open(os.path.join(ROOT, "docs", "GUIDE.md"), encoding="utf-8") as f:
            guide = f.read()
        refs = set(re.findall(r"/Min-heee/agencity/(?:blob/)?([^/\s]+)/bin/city_join\.py", guide))
        self.assertEqual(refs, {ref_page})

    def test_join_ref_is_version(self):
        """명령 태그는 릴리스한 판(VERSION)과 같아야 해요(태그가 없으면 공개 도시의 명령이 404예요).
        VERSION이 아직 태그보다 낮으면 릴리스 커밋 전이라 건너뛰어요. 그 뒤로는 꼭 같아야 해요."""
        ref = self.join_ref()
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            ver = f.read().strip()
        num = lambda v: tuple(int(x) for x in re.findall(r"\d+", v))   # noqa: E731
        if num(ver) < num(ref):
            self.skipTest(f"VERSION {ver}이 명령 태그 {ref}보다 낮아요. 릴리스 커밋에서 VERSION을 올려요")
        self.assertEqual("v" + ver, ref)

    def test_no_token_meter_name_on_screen(self):
        """대표 결정(2026-10-23): 도시 화면 글(city.html의 T)과 문서 본문에는 token-meter 이름을 쓰지 않아요.
        구조상 그대로인 것(주소, 파일 이름 token-meter.json)만 남아요."""
        with open(os.path.join(ROOT, "city.html"), encoding="utf-8") as f:
            words = re.search(r"\nconst T = \{\n(.*?)\n\};\n", f.read(), re.S).group(1)
        self.assertEqual([x.strip() for x in words.splitlines() if "token-meter" in x], [])
        docs = [os.path.join(ROOT, "README.md")] + [os.path.join(ROOT, "docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs")))
                                                    if n.endswith(".md")]
        for p in docs:
            with open(p, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    x = re.sub(r"https?://[^\s)\]>`]+", "", line).replace("token-meter.json", "")
                    self.assertNotIn("token-meter", x, f"{os.path.relpath(p, ROOT)}:{i}")

    def test_pages_ships_countries(self):
        with open(os.path.join(ROOT, ".github", "workflows", "city.yml"), encoding="utf-8") as f:
            self.assertIn("city/countries.json", f.read())

    def test_install_keeps_public_json(self):
        """나라는 public.json에 저장해요. 다시 설치해도 그 파일은 그대로여야 해요."""
        with open(os.path.join(ROOT, "install.sh"), encoding="utf-8") as f:
            line = next(x for x in f if x.strip().startswith("for x in org.json"))
        self.assertIn("public.json", line)


class OfficeServer(unittest.TestCase):
    """서버의 공개 범위·나라·미리보기 지문·올리기(가짜 GitHub)."""

    @classmethod
    def setUpClass(cls):
        cls.gh = FakeGitHub()
        cls.tmp = tempfile.mkdtemp(prefix="agencity-u12-", dir=TMP_BASE)
        cls.dir = copy_repo(os.path.join(cls.tmp, "app"))
        cls.home = os.path.join(cls.tmp, "home")
        cls.conf = os.path.join(cls.tmp, "conf")
        os.makedirs(cls.home)
        os.makedirs(cls.conf)
        shutil.copy(os.path.join(cls.dir, "examples", "org.example.json"), os.path.join(cls.dir, "org.json"))
        with open(os.path.join(cls.conf, "github-token.json"), "w") as f:
            json.dump({"login": ME, "token": "testtoken_1234567890", "scope": "gist"}, f)
        os.chmod(os.path.join(cls.conf, "github-token.json"), 0o600)
        cls.meter_gist = cls.gh.add({"token-meter.json": json.dumps({"schema": 1, "app": "token-meter", "login": ME, "entries": []}),
                                     "agencity.json": json.dumps({"schema": 1, "app": "agencity", "login": ME, "profile": {"intro": "", "country": "JP"}, "floors": []})})
        with open(os.path.join(cls.dir, "setup.json"), "w") as f:
            json.dump({"done": True, "github": {"login": ME, "via": "device"}, "tokenMeter": {"gist": cls.meter_gist, "login": ME},
                       "update": {"enabled": False}}, f)
        subprocess.run([sys.executable, "-I", "build.py"], cwd=cls.dir, check=True, capture_output=True)
        cls.port = free_port()
        env = dict(os.environ, HOME=cls.home, OFFICE_PORT=str(cls.port), AGENCITY_CONFIG_DIR=cls.conf, AGENCITY_GITHUB_API=cls.gh.url,
                   AGENCITY_GITHUB_BASE=cls.gh.url, AGENCITY_TOKEN_METER_BASE=cls.gh.url + "/tm", AGENCITY_UPDATE_INTERVAL="0")
        cls.proc = subprocess.Popen([sys.executable, "-I", "office_server.py"], cwd=cls.dir, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(100):
            try:
                page = LOCAL.open(cls.base + "/", timeout=2).read().decode("utf-8")
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("서버가 켜지지 않았어요")
        cls.token = re.search(r"const TOKEN = '([A-Za-z0-9_-]{20,})'", page).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.gh.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json", "Origin": self.base, "X-Office-Token": self.token})
        try:
            with LOCAL.open(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def get(self, path):
        try:
            with LOCAL.open(self.base + path, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""

    def public(self):
        with open(os.path.join(self.dir, "public.json"), encoding="utf-8") as f:
            return json.load(f)

    def gist_country(self):
        return (self.gh.doc(self.meter_gist, "agencity.json") or {}).get("profile", {}).get("country")

    def publish(self, expect_keep=None):
        code, pv = self.post("/api/setup/publish", {"preview": True})
        self.assertEqual(code, 200, pv)
        if expect_keep is not None:
            self.assertIs(pv["keepCountry"], expect_keep)
        code, res = self.post("/api/setup/publish", {"digest": pv["digest"]})
        self.assertEqual(code, 200, res)
        return pv, res

    def test_1_state_and_files(self):
        code, st = self.post("/api/setup/state", {})
        self.assertEqual(code, 200)
        self.assertEqual(len(st["countries"]), 249)
        self.assertIsNone(st["country"])
        self.assertEqual(self.get("/city/countries.json")[0], 200)
        self.assertEqual(self.get("/city/../setup.json")[0], 404)
        self.assertEqual(self.get("/city/")[0], 404)

    def test_2_keep_country_from_gist(self):
        """이 맥에서 나라를 정한 적이 없으면, 층을 올릴 때 gist에 있는 나라(JP)를 지우지 않아요."""
        code, _ = self.post("/api/setup/visibility", {"visibility": {"demo": "names"}})
        self.assertEqual(code, 200)
        self.assertNotIn("country", self.public().get("profile", {}))
        pv, res = self.publish(expect_keep=True)
        self.assertNotIn("country", pv["preview"]["profile"])
        self.assertEqual(self.gist_country(), "JP")
        self.assertEqual(res["country"], "JP")
        self.assertEqual(len(self.gh.doc(self.meter_gist, "agencity.json")["floors"]), 1)

    def test_3_digest_guard(self):
        code, res = self.post("/api/setup/publish", {})
        self.assertEqual(code, 409)
        code, pv = self.post("/api/setup/publish", {"preview": True})
        self.post("/api/setup/visibility", {"country": "KR"})   # 확인 상자를 띄운 뒤 다른 창에서 나라를 바꿨어요
        code, res = self.post("/api/setup/publish", {"digest": pv["digest"]})
        self.assertEqual(code, 409, res)
        self.assertIn("달라졌어요", res["error"])

    def test_4_pick_country(self):
        self.assertEqual(self.post("/api/setup/visibility", {"country": "KR"})[0], 200)
        self.assertEqual(self.post("/api/setup/state", {})[1]["country"], "KR")
        pv, res = self.publish(expect_keep=False)
        self.assertEqual(pv["preview"]["profile"]["country"], "KR")
        self.assertEqual(self.gist_country(), "KR")
        st = self.post("/api/setup/state", {})[1]
        self.assertEqual(st["published"]["country"], "KR")
        self.assertIs(st["published"]["current"], True)

    def test_5_bad_country(self):
        for v in ("kr", "XX", "KOR", 7, " KR"):
            self.assertEqual(self.post("/api/setup/visibility", {"country": v})[0], 400, v)

    def test_6_country_without_floors_still_publishes(self):
        """층을 모두 비공개로 해도 나라를 골랐으면 나라는 나가요(층 없이 건물만 세운 사람도 나라 구역에)."""
        self.post("/api/setup/visibility", {"visibility": {"demo": "private"}, "country": "DE"})
        pv, res = self.publish(expect_keep=False)
        self.assertEqual(pv["preview"]["floors"], [])
        self.assertEqual(self.gist_country(), "DE")
        self.assertEqual(res["floors"], 0)

    def test_7_take_down_removes_country(self):
        """도시에서 내리기(공개할 층도 고른 나라도 없음): 정한 적 없는 나라라도 gist의 나라를 같이 빼요(결재 20261024-U-14-1)."""
        g = self.gh.gists[self.meter_gist]
        doc = json.loads(g["files"]["agencity.json"])
        doc["profile"]["country"] = "JP"
        g["files"]["agencity.json"] = json.dumps(doc)
        self.post("/api/setup/visibility", {"visibility": {"demo": "private"}})
        cur = self.public()
        cur["profile"].pop("country", None)   # 정한 적 없음
        with open(os.path.join(self.dir, "public.json"), "w", encoding="utf-8") as f:
            json.dump(cur, f)
        pv, res = self.publish(expect_keep=False)
        self.assertIsNone(self.gist_country())
        self.assertEqual(self.gh.doc(self.meter_gist, "agencity.json")["floors"], [])
        self.assertIsNone(res["country"])

    def test_8_auto_setting_marks_hourly(self):
        self.assertEqual(self.post("/api/setup/meter/settings", {"auto": True})[0], 200)
        with open(os.path.join(self.dir, "setup.json"), encoding="utf-8") as f:
            tm = json.load(f)["tokenMeter"]
        self.assertIs(tm["auto"], True)
        self.assertIs(tm["hourly"], True)
        self.post("/api/setup/meter/settings", {"auto": False})
        with open(os.path.join(self.dir, "setup.json"), encoding="utf-8") as f:
            tm = json.load(f)["tokenMeter"]
        self.assertNotIn("hourly", tm)


class OfficePublicUnit(unittest.TestCase):
    """bin/office_public.py의 나라 걸러내기와 지문."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("op", os.path.join(ROOT, "bin", "office_public.py"))
        cls.op = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.op)

    def test_country_of(self):
        codes = self.op.countries()
        self.assertEqual(self.op.country_of("KR", codes), "KR")
        for v in ("kr", "XX", "KOR", "", None, 3, "K R", "KR\n"):
            self.assertIsNone(self.op.country_of(v, codes), v)

    def test_digest_ignores_time_and_desk_state(self):
        a = {"schema": 1, "updatedAt": "1", "profile": {"intro": ""}, "floors": [{"floor": 1, "desks": [{"role": "팀장", "state": "대기"}]}]}
        b = json.loads(json.dumps(a))
        b["updatedAt"] = "2"
        b["floors"][0]["desks"][0]["state"] = "일하는 중"
        self.assertEqual(self.op.digest_of(a, False), self.op.digest_of(b, False))
        self.assertNotEqual(self.op.digest_of(a, False), self.op.digest_of(a, True))
        b["floors"][0]["desks"][0]["role"] = "개발자"
        self.assertNotEqual(self.op.digest_of(a, False), self.op.digest_of(b, False))


class AutoUploadGap(unittest.TestCase):
    """자동으로 올리기: 이번 판에서 켠 사람은 1시간마다(55분), 예전 판에서 켠 하루 한 번은 20시간마다."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        cls.tmp = tempfile.mkdtemp(prefix="agencity-u12-auto-", dir=TMP_BASE)
        d = copy_repo(os.path.join(cls.tmp, "app"))
        os.environ.setdefault("AGENCITY_CONFIG_DIR", os.path.join(cls.tmp, "conf"))
        spec = importlib.util.spec_from_file_location("osrv", os.path.join(d, "office_server.py"))
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def started(self, hourly, minutes_ago):
        m, started = self.m, []
        t = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - minutes_ago * 60))
        m.tm_conf = lambda s=None: {"auto": True, "hourly": True if hourly else None, "t": t, "autoAt": None, "gist": "abc12", "login": ME,
                                    "hash": None, "autoErr": None, "joinAt": None}
        m.github_state = lambda s=None: {"login": ME, "via": "device"}
        m.TM_AUTO["running"] = False

        class T:
            def __init__(self, target=None, args=(), name=None, daemon=None):
                started.append(name)

            def start(self):
                pass
        real = m.threading.Thread
        m.threading.Thread = T
        try:
            m.tm_maybe_auto()
        finally:
            m.threading.Thread = real
        return bool(started)

    def test_hourly(self):
        self.assertFalse(self.started(True, 30))
        self.assertTrue(self.started(True, 56))

    def test_old_daily(self):
        self.assertFalse(self.started(False, 120))
        self.assertTrue(self.started(False, 21 * 60))


def run_tty(args, env, answer=None, timeout=90):
    """가짜 터미널에서 돌려요(명령이 /dev/tty로 [y/N]을 묻는 걸 시험). (종료 코드, 화면 글)"""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execve(sys.executable, [sys.executable, "-I"] + args, env)
        finally:
            os._exit(127)
    out, asked, end = b"", False, time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 1)
        if not r:
            try:
                done, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            if done:
                return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace")
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if answer is not None and not asked and b"[y/N]" in out:
            os.write(fd, (answer + "\n").encode())
            asked = True
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace")


class CityJoin(unittest.TestCase):
    """bin/city_join.py: 기기 로그인 → 세기 → [y/N] → gist 만들기·고치기 → 참가 안내(가짜 GitHub·명단)."""

    def setUp(self):
        self.gh = FakeGitHub()
        self.tmp = tempfile.mkdtemp(prefix="agencity-u12-join-", dir=TMP_BASE)
        self.home = os.path.join(self.tmp, "home")
        fake_logs(self.home)
        self.env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "LANG": "ko_KR.UTF-8", "TZ": "Asia/Seoul",
                    "AGENCITY_GITHUB_API": self.gh.url, "AGENCITY_GITHUB_BASE": self.gh.url, "AGENCITY_TOKEN_METER_BASE": self.gh.url + "/tm",
                    "AGENCITY_GITHUB_CLIENT_ID": "testclientid"}
        self.cmd = [os.path.join(ROOT, "bin", "city_join.py"), "--no-open"]

    def tearDown(self):
        self.gh.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def only_gist(self):
        self.assertEqual(len(self.gh.gists), 1)
        return next(iter(self.gh.gists))

    def test_new_gist_with_country_then_nothing(self):
        code, out = run_tty(self.cmd + ["--country", "kr"], self.env, "y")
        self.assertEqual(code, 0, out)
        gid = self.only_gist()
        self.assertTrue(self.gh.gists[gid]["public"])
        meter = self.gh.doc(gid, "token-meter.json")
        self.assertEqual(meter["login"], ME)
        self.assertEqual(meter["app"], "token-meter")
        office = self.gh.doc(gid, "agencity.json")
        self.assertEqual(office["profile"], {"country": "KR"})
        self.assertEqual(office["floors"], [])
        self.assertIn("도시 참가 신청", out)
        self.assertIn("issues/new", out)
        self.assertNotIn("faketoken", out)   # 토큰은 화면에 내지 않아요
        self.assertFalse([n for n in os.listdir(self.home) if n not in (".claude",)])   # 토큰·설정 파일을 남기지 않아요
        # 숫자도 나라도 그대로면 아무것도 올리지 않아요(명단에도 있어요)
        self.gh.members = [{"login": ME, "gist": gid}]
        n = len(self.gh.writes())
        code, out = run_tty(self.cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        self.assertIn("아무것도 올리지 않았어요", out)
        self.assertIn("도시 명단에 있어요", out)
        self.assertEqual(len(self.gh.writes()), n)

    def test_enter_uploads_nothing(self):
        code, out = run_tty(self.cmd, self.env, "")
        self.assertEqual(code, 0, out)
        self.assertIn("올리지 않았어요", out)
        self.assertEqual(self.gh.writes(), [])

    def test_no_tty_uploads_nothing(self):
        r = subprocess.run([sys.executable, "-I"] + self.cmd, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=90, start_new_session=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("터미널", r.stderr)
        self.assertEqual(self.gh.writes(), [])

    def test_country_none_keeps_app_summary(self):
        """앱으로 올린 요약(소개·층)이 있으면 나라만 빼고 나머지는 그대로예요. 숫자가 같으면 숫자 파일은 보내지 않아요."""
        code, out = run_tty(self.cmd, self.env, "y")   # 먼저 숫자만 올려요(나라는 건드리지 않아요)
        self.assertEqual(code, 0, out)
        gid = self.only_gist()
        self.assertIsNone(self.gh.doc(gid, "agencity.json"))
        app_doc = {"schema": 1, "app": "agencity", "login": ME, "updatedAt": "2026-10-20T00:00:00Z",
                   "profile": {"intro": "앱 세 개", "district": "app", "country": "JP"}, "floors": [{"floor": 1, "name": "가계부", "public": "name", "summary": ""}]}
        self.gh.gists[gid]["files"]["agencity.json"] = json.dumps(app_doc, ensure_ascii=False)
        code, out = run_tty(self.cmd + ["--country", "none"], self.env, "y")
        self.assertEqual(code, 0, out)
        last = self.gh.writes()[-1]
        self.assertEqual(last[0], "PATCH")
        self.assertEqual(set(last[2]["files"]), {"agencity.json"})
        doc = self.gh.doc(gid, "agencity.json")
        self.assertEqual(doc["profile"], {"intro": "앱 세 개", "district": "app"})
        self.assertEqual(doc["floors"], app_doc["floors"])
        self.assertEqual(doc["updatedAt"], app_doc["updatedAt"])

    def test_bad_country(self):
        for v in ("XX", "KOR", "1"):
            code, out = run_tty(self.cmd + ["--country", v], self.env)
            self.assertNotEqual(code, 0)
            self.assertIn("두 글자", out)
        self.assertEqual(self.gh.calls, [])

    def test_english(self):
        env = dict(self.env, LANG="en_US.UTF-8")
        code, out = run_tty(self.cmd + ["--country", "JP"], env, "n")
        self.assertEqual(code, 0, out)
        self.assertIn("Upload? [y/N]", out)
        self.assertIn("Country: JP", out)
        self.assertIn("Nothing was posted", out)
        self.assertNotIn("token-meter", out.replace("token-meter.json", ""))

    def meter_and_office(self, profile):
        return self.gh.add({"token-meter.json": json.dumps({"schema": 1, "app": "token-meter", "login": ME, "entries": []}),
                            "agencity.json": json.dumps({"schema": 1, "app": "agencity", "login": ME, "profile": profile, "floors": []})})

    def test_country_none_removes_unlisted_value(self):
        """gist의 나라가 목록에 없는 값(kr)이어도 지금 값을 그대로 보여 주고, --country none이면 빼요."""
        gid = self.meter_and_office({"intro": "x", "country": "kr"})
        code, out = run_tty(self.cmd, self.env, "n")
        self.assertEqual(code, 0, out)
        self.assertIn("지금: kr", out)
        code, out = run_tty(self.cmd + ["--country", "none"], self.env, "y")
        self.assertEqual(code, 0, out)
        self.assertIn("나라: 빼요", out)
        self.assertEqual(self.gh.doc(gid, "agencity.json")["profile"], {"intro": "x"})

    def test_no_install_removes_country_without_list(self):
        """스크립트만 받아 돌릴 때(설치 없이) 나라 목록을 못 받았어도 --country none이면 gist의 나라를 빼요."""
        solo = os.path.join(self.tmp, "solo")
        os.makedirs(solo)
        shutil.copy(os.path.join(ROOT, "bin", "city_join.py"), solo)
        with open(os.path.join(ROOT, "bin", "token_meter.py"), encoding="utf-8") as f:
            self.gh.raw = {"bin/token_meter.py": f.read()}   # city/countries.json·github_client_id는 404
        gid = self.meter_and_office({"country": "KR"})
        env = dict(self.env, AGENCITY_CITY_RAW=self.gh.url + "/raw")
        code, out = run_tty([os.path.join(solo, "city_join.py"), "--no-open", "--country", "none"], env, "y")
        self.assertEqual(code, 0, out)
        self.assertIn(("GET", "/raw/city/countries.json", None), self.gh.calls)
        self.assertIn("나라: 빼요", out)
        self.assertEqual(self.gh.doc(gid, "agencity.json")["profile"], {})
        self.assertEqual(os.listdir(solo), ["city_join.py"])   # 받은 도움 파일은 임시 폴더에만 있었어요

    def test_dry_run_shows_country(self):
        """--dry-run은 로그인도 올리기도 안 하고, 준 나라를 보여 줘요. 하루면 'active day'(단수)예요."""
        home = os.path.join(self.tmp, "home1")
        fake_logs(home, days=(("2026-10-24T05:10:00.000Z", 1000, 160),))
        env = dict(self.env, HOME=home, LANG="en_US.UTF-8")
        r = subprocess.run([sys.executable, "-I"] + self.cmd + ["--dry-run", "--country", "KR"], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\b1 active day(?!s)")
        self.assertIn("Country: KR", r.stdout)
        self.assertIn("--dry-run", r.stdout)
        self.assertEqual(self.gh.calls, [])

    def test_overrides_only_local(self):
        """시험용 주소는 이 컴퓨터(127.0.0.1·localhost)의 것만 받아요. 다른 곳이면 기본값(진짜 GitHub)이에요."""
        probe = ("import importlib.util, sys\ns = importlib.util.spec_from_file_location('cj', sys.argv[1])\nm = importlib.util.module_from_spec(s)\n"
                 "s.loader.exec_module(m)\nprint(m.API, m.BASE, m.RAW, m.TM_BASE, m.REAL_GITHUB)")
        path = os.path.join(ROOT, "bin", "city_join.py")
        names = ("AGENCITY_GITHUB_API", "AGENCITY_GITHUB_BASE", "AGENCITY_CITY_RAW", "AGENCITY_TOKEN_METER_BASE")
        far = dict({k: "https://example.invalid/x" for k in names}, HOME=self.home, PATH="/usr/bin:/bin")
        r = subprocess.run([sys.executable, "-I", "-c", probe, path], env=far, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("example.invalid", r.stdout)
        self.assertTrue(r.stdout.startswith("https://api.github.com https://github.com https://raw.githubusercontent.com/"), r.stdout)
        self.assertTrue(r.stdout.strip().endswith("True"), r.stdout)
        near = dict(far, AGENCITY_GITHUB_API="https://localhost:9/api", AGENCITY_CITY_RAW="http://127.0.0.1:9/raw")
        r = subprocess.run([sys.executable, "-I", "-c", probe, path], env=near, capture_output=True, text=True, timeout=30)
        self.assertIn("https://localhost:9/api https://github.com http://127.0.0.1:9/raw", r.stdout)
        self.assertTrue(r.stdout.strip().endswith("False"), r.stdout)


if __name__ == "__main__":
    unittest.main()
