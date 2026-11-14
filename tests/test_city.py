"""에이전시티 도시 U-12 시험: 나라(profile.country)·공개 미리보기 지문·자동 올리기 간격·설치 없이 올리는 명령·
명령 태그와 VERSION·화면 글의 token-meter 이름. U-40: 도시 화면(숫자 거르기·'나' 표시·참가 처리 중·순위 줄·순위표·카드·참가 창).

python3 -m unittest tests/test_city.py -v      (저장소 맨 위에서)

진짜 GitHub·gist·도시 명단은 쓰지 않아요. 127.0.0.1의 빈 포트(9400번대)에 가짜 GitHub(gist API·기기 로그인)과 가짜 명단을 띄우고,
저장소를 임시 폴더(/private/tmp 아래)에 복사해 그 안에서 서버(office_server.py)·공개 도우미(bin/office_public.py)·
명령(bin/city_join.py)을 돌려요. HOME도 임시 폴더라 이 컴퓨터의 Claude 기록·설정은 읽지 않아요.
도시 화면 시험은 city.html의 함수를 그대로 꺼내 node에서 가짜 주변과 함께 돌려요(node가 없으면 건너뛰어요. 포트를 열지 않아요).
파이썬 표준 라이브러리만 써요.
"""
import glob
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
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
with open(os.path.join(ROOT, "city.html"), encoding="utf-8") as _f:
    CITY = _f.read()


def city_js(*names):
    """city.html의 맨 위 함수(function·async function)와 const·let을 이름으로 꺼내요(여러 줄 const는 괄호가 닫히는 ;까지)."""
    out = []
    for name in names:
        m = re.search(r"\n((?:async )?function " + re.escape(name) + r"\()", CITY)
        if m:
            i = CITY.index("{", CITY.index(")", m.end()))
            depth, j = 0, i
            while True:
                depth += {"{": 1, "}": -1}.get(CITY[j], 0)
                if depth == 0:
                    break
                j += 1
            out.append(CITY[m.start(1):j + 1])
            continue
        m = re.search(r"\n((?:const|let) " + re.escape(name) + r" = )", CITY)
        if not m:
            raise AssertionError(f"city.html에 {name}이 없어요")
        lines, depth = [], 0
        for line in CITY[m.start(1):].split("\n"):
            lines.append(line)
            depth += sum(line.count(c) for c in "([{") - sum(line.count(c) for c in ")]}")
            if depth <= 0 and re.search(r";\s*(//.*)?$", line):
                break
        out.append("\n".join(lines))
    return "\n".join(out)


def run_node(code):
    r = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(r.stderr[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def free_port(lo=9400, hi=9499):
    for p in range(lo, hi + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("9400번대에 빈 포트가 없어요")


class _OneServer(ThreadingHTTPServer):
    allow_reuse_address = False   # 다른 시험 실행이 이미 쓰는 포트에는 붙지 않아요


class FakeGitHub:
    """gist API 일부(user, gists 목록·하나·만들기·고치기), 기기 로그인, 도시 명단(/tm/members.json),
    설치 없이 돌릴 때 받는 파일(/raw/<저장소 안 경로>, raw에 없으면 404).
    포트는 9400번대에서 고르되 확인하고 놓지 않고 그 자리에서 바로 열어요(동시에 도는 다른 시험과 겨루지 않게).
    calls에는 다른 시험 실행이 잘못 보낸 요청이 섞일 수 있어서, 엄격히 볼 때는 ours()(이 가짜가 아는 경로만)를 봐요."""

    PATHS = ("/login/", "/user", "/gists", "/tm/", "/raw/")

    def __init__(self):
        self.gists, self.calls, self.members, self.seq, self.raw = {}, [], [], 0, {}
        self.port = 0
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

        self.srv = None
        for port in range(9400, 9500):
            try:
                self.srv = _OneServer(("127.0.0.1", port), H)
                break
            except OSError:
                continue
        if self.srv is None:
            raise RuntimeError("9400번대에 빈 포트가 없어요")
        self.port = self.srv.server_address[1]
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

    def ours(self):
        """이 가짜가 아는 경로로 온 요청만(다른 시험 실행이 잘못 보낸 GET / 같은 건 빼요)."""
        return [c for c in self.calls if c[1] == "/user" or c[1].startswith(self.PATHS)]

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

    def test_public_copy_says_all_that_goes_up(self):
        """토큰 수만 올라가는 것처럼 좁게 쓰지 않아요. 횟수와 환산액도 올라가요. 로그는 읽으니 '읽지 않아요'라고 하지 않아요."""
        narrow = ("토큰 수만", "토큰 숫자만 ", "토큰 수·모델 이름·시각만", "나가는 것: 토큰 수", "토큰 숫자와 고른 나라만", "토큰 숫자(와 고른 나라)만", "숫자(와 고른 나라)만", "토큰 수, 날짜별", "대화 글은 읽지 않아요", "세션 정보는 올리지",
                  "Only token counts", "token numbers only", "Token numbers", "token count", "chat text is not read", "session details", "**숫자만**", "(숫자만)", "숫자만 올려")
        for name in ("README.md", "city.html", "office.src.html", "office_server.py", os.path.join("bin", "city_join.py"), os.path.join("docs", "GUIDE.md"), os.path.join("docs", "VISION.md")):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                text = f.read()
            self.assertEqual([x for x in narrow if x in text], [], name)
        with open(os.path.join(ROOT, "office.src.html"), encoding="utf-8") as f:
            self.assertIn("나가는 것: 숫자(토큰·횟수·환산액)", f.read())
        with open(os.path.join(ROOT, "city.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("숫자(토큰·횟수·환산액)", page)
        self.assertIn("numbers (tokens, counts, cost estimate)", page)

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


COUNTRY_ASK = ("= 빼기): ".encode("utf-8"), b"= remove): ")   # city_join.py의 나라 물음 끝(한국어·English)


def run_tty(args, env, answer=None, timeout=90, country=""):
    """가짜 터미널에서 돌려요(명령이 /dev/tty로 나라와 [y/N]을 묻는 걸 시험). (종료 코드, 화면 글)
    answer: '[y/N]'에 한 번 칠 답. country: 나라 물음에 칠 답(목록이면 물을 때마다 차례로, 모자라면 엔터). None이면 답하지 않아요.
    시간이 다 되면 명령을 끝내요(물음에 답하지 않아 멈춰 있어도 시험이 끝나요)."""
    replies = [] if country is None else list(country) if isinstance(country, (list, tuple)) else [country]
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execve(sys.executable, [sys.executable, "-I"] + args, env)
        finally:
            os._exit(127)
    out, asked, n_c, end = b"", False, 0, time.time() + timeout
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
        if country is not None:
            while n_c < sum(out.count(m) for m in COUNTRY_ASK):
                os.write(fd, ((replies[n_c] if n_c < len(replies) else "") + "\n").encode())
                n_c += 1
        if answer is not None and not asked and b"[y/N]" in out:
            os.write(fd, (answer + "\n").encode())
            asked = True
    if time.time() >= end:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace")


PAGE_URL = "https://min-heee.github.io/agencity/"   # city.html의 PUBLIC_URL, city_join.py의 CITY_URL


class CityJoin(unittest.TestCase):
    """bin/city_join.py(U-40 순서): 세기(로그인 없이) → 내 총 토큰 → (--country가 없으면) 나라 한 번 묻기 → [y/N] → 기기 로그인
    → gist 만들기·고치기 → 참가 안내와 내 도시 주소(?who=<아이디>#me) 열기(가짜 GitHub·명단·브라우저)."""

    def setUp(self):
        self.gh = FakeGitHub()
        self.tmp = tempfile.mkdtemp(prefix="agencity-u12-join-", dir=TMP_BASE)
        self.home = os.path.join(self.tmp, "home")
        fake_logs(self.home)
        # 가짜 브라우저: webbrowser는 BROWSER를 먼저 써요. 연 주소를 파일에 적기만 해요(진짜 브라우저는 열지 않아요)
        self.opened = os.path.join(self.tmp, "opened.txt")
        browser = os.path.join(self.tmp, "browser.sh")
        with open(browser, "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\nprintf '%s\\n' \"$1\" >> '{self.opened}'\nexit 0\n")
        os.chmod(browser, 0o755)
        self.env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "LANG": "ko_KR.UTF-8", "TZ": "Asia/Seoul", "BROWSER": browser,
                    "AGENCITY_GITHUB_API": self.gh.url, "AGENCITY_GITHUB_BASE": self.gh.url, "AGENCITY_TOKEN_METER_BASE": self.gh.url + "/tm",
                    "AGENCITY_GITHUB_CLIENT_ID": "testclientid"}
        self.cmd = [os.path.join(ROOT, "bin", "city_join.py"), "--no-open"]

    def tearDown(self):
        self.gh.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def only_gist(self):
        self.assertEqual(len(self.gh.gists), 1)
        return next(iter(self.gh.gists))

    def opened_urls(self):
        try:
            with open(self.opened, encoding="utf-8") as f:
                return f.read().split()
        except FileNotFoundError:
            return []

    def test_new_gist_with_country_then_nothing(self):
        code, out = run_tty(self.cmd + ["--country", "kr"], self.env, "y")
        self.assertEqual(code, 0, out)
        gid = self.only_gist()
        self.assertTrue(self.gh.gists[gid]["public"])
        meter = self.gh.doc(gid, "token-meter.json")
        self.assertEqual(meter["login"], ME)
        self.assertEqual(meter["app"], "token-meter")
        self.assertEqual(list(meter)[:5], ["schema", "app", "login", "updatedAt", "entries"])   # 로그인한 뒤 넣은 아이디도 제자리예요
        office = self.gh.doc(gid, "agencity.json")
        self.assertEqual(office["profile"], {"country": "KR"})
        self.assertEqual(office["floors"], [])
        self.assertIn("도시 참가 신청", out)
        self.assertIn("issues/new", out)
        self.assertNotIn("나라를 고를까요", out)   # --country가 있으면 묻지 않아요
        self.assertNotIn("faketoken", out)   # 토큰은 화면에 내지 않아요
        self.assertFalse([n for n in os.listdir(self.home) if n not in (".claude",)])   # 토큰·설정 파일을 남기지 않아요
        # 숫자도 나라도 그대로면 아무것도 올리지 않아요(명단에도 있어요)
        self.gh.members = [{"login": ME, "gist": gid}]
        n = len(self.gh.writes())
        code, out = run_tty(self.cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        self.assertIn("아무것도 올리지 않았어요", out)
        self.assertIn("도시 명단에 있어요", out)
        self.assertIn(f"내 도시 주소: {PAGE_URL}?who={ME}#me", out)
        self.assertEqual(len(self.gh.writes()), n)

    def test_order_count_then_ask_then_login(self):
        """로그인 전에 세어서 내 총 토큰을 보여 주고, [y/N]에 y를 받은 뒤에야 로그인해요."""
        code, out = run_tty(self.cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        total = out.index("내 총 토큰: ")
        self.assertRegex(out[total:], r"^내 총 토큰: [\d,]+\r?\n")
        self.assertLess(total, out.index("[y/N]"))
        self.assertLess(out.index("[y/N]"), out.index("ABCD-1234"))   # 기기 코드는 y 다음
        self.assertLess(out.index("ABCD-1234"), out.index("올렸어요"))
        self.assertEqual(self.gh.ours()[0][:2], ("POST", "/login/device/code"))   # 묻기 전에는 GitHub·명단에 닿지 않아요
        # 동의 전 글: 시간대는 '올리면' 공개, 로그인 권한은 gh 계정이 아닐 때(기기 코드)만 gist 하나라고 말해요
        self.assertIn("시간대: Asia/Seoul (올리면 나라와 따로, 늘 공개돼요)", out)
        self.assertIn("gh에 로그인돼 있으면 그 계정, 아니면 기기 코드로 gist 권한 하나만 받아요", out)
        self.assertNotIn("(권한은 gist 하나). 엔터만", out)

    def test_enter_uploads_nothing(self):
        """[y/N]에 엔터면 아무것도 안 올리고 로그인도 안 해요. 그래도 내 총 토큰은 보여요(나라도 물었어요)."""
        code, out = run_tty(self.cmd, self.env, "")
        self.assertEqual(code, 0, out)
        self.assertIn("내 총 토큰: ", out)
        self.assertIn("나라를 고를까요?", out)
        self.assertIn("올리지 않았어요", out)
        self.assertNotIn("ABCD-1234", out)
        self.assertEqual(self.gh.ours(), [])   # 기기 로그인·아이디·gist·명단 어디에도 닿지 않았어요
        self.assertEqual(self.opened_urls(), [])

    def test_no_tty_uploads_nothing(self):
        r = subprocess.run([sys.executable, "-I"] + self.cmd, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=90, start_new_session=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("내 총 토큰: ", r.stdout)   # 세기는 터미널 없이도 돼요
        self.assertIn("터미널", r.stderr)
        self.assertEqual(self.gh.ours(), [])

    def test_stray_requests_ignored(self):
        """같은 포트를 잠깐 쓴 다른 시험 실행이 보낸 요청(GET / 같은)은 ours()에 들어가지 않아요(엄격한 시험이 흔들리지 않게)."""
        try:
            LOCAL.open(self.gh.url + "/", timeout=10).close()
        except urllib.error.HTTPError as e:   # 가짜 GitHub은 로그인 없는 요청에 401이에요
            e.close()
        self.assertEqual(self.gh.calls[-1][:2], ("GET", "/"))
        self.assertEqual(self.gh.ours(), [])

    def test_country_asked_once(self):
        """--country가 없으면 한 번 물어요: 목록에 없는 값이면 다시 묻고(짐작하지 않아요), 소문자도 받아요. none이면 빼요."""
        code, out = run_tty(self.cmd, self.env, "y", country=["XX", "jp"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("나라를 고를까요?"), 2)
        self.assertIn("목록에 없는 나라 코드예요(XX)", out)
        self.assertIn("나라: JP(으)로 올려요", out)
        self.assertLess(out.index("내 총 토큰: "), out.index("나라를 고를까요?"))
        self.assertLess(out.index("나라를 고를까요?"), out.index("[y/N]"))
        gid = self.only_gist()
        self.assertEqual(self.gh.doc(gid, "agencity.json")["profile"], {"country": "JP"})
        code, out = run_tty(self.cmd, self.env, "y", country="none")
        self.assertEqual(code, 0, out)
        self.assertIn("나라: 빼요", out)
        self.assertEqual(self.gh.doc(gid, "agencity.json")["profile"], {})
        env = dict(self.env, LANG="en_US.UTF-8")   # 영어도 같은 물음이에요. 엔터면 고르지 않아요(나라는 그대로)
        code, out = run_tty(self.cmd, env, "n", country="")
        self.assertEqual(code, 0, out)
        self.assertIn("Pick your country for country ranks (public)? Type a code like KR (Enter = skip, keeps any country you picked before"
                      " · none = remove): ", out)
        self.assertIn("Country: not picked (keeps any you picked before)", out)
        self.assertNotIn("Country: unchanged (now: none)", out)   # gist에도 나라가 없으면 '그대로(지금: 없음)'를 또 쓰지 않아요

    def test_opens_me_url(self):
        """명단에 없으면 참가 신청 화면을 열고, 그 직후 내 도시 주소(?who=<아이디>#me)도 열어요(정해진 순서).
        공유 주소는 명단에 들어오기 전에는 보여 주지 않고, 끝 줄은 남은 일(Submit new issue) 하나예요.
        명단에 있으면 내 도시 주소만 열고 공유 주소(#me 없음)를 보여 줘요."""
        cmd = [x for x in self.cmd if x != "--no-open"]
        code, out = run_tty(cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        gid = self.only_gist()
        urls = self.opened_urls()
        mine = f"{PAGE_URL}?who={ME}#me"
        self.assertEqual(len(urls), 3, urls)
        self.assertTrue(urls[0].startswith(self.gh.url + "/login/device"), urls)   # 기기 로그인 화면
        self.assertIn("/issues/new?", urls[1])                                     # 신청 화면을 먼저
        self.assertTrue(urls[1].endswith("gist=" + gid), urls)
        self.assertEqual(urls[2], mine)                                            # 그 직후 내 도시 주소
        self.assertLess(out.index("도시 참가 신청 화면을 브라우저로 열었어요"), out.index("내 도시 주소를 브라우저로 열었어요"))
        self.assertIn("참가 처리 중", out)
        self.assertNotIn("공유 주소: ", out)                                       # 명단에 들어오기 전에는 공유 주소가 없어요
        self.assertEqual(out.strip().splitlines()[-1].strip(), "남은 일 하나: 열린 GitHub 신청 화면에서 Submit new issue를 눌러요. 몇 분 뒤 내 도시 주소에 내 카드가 열려요.")
        # 명단에 들어온 뒤: 내 도시 주소만 열어요(신청 화면은 열지 않아요). 공유 주소에는 #me가 없어요.
        self.gh.members = [{"login": ME, "gist": gid}]
        code, out = run_tty(cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        urls = self.opened_urls()[3:]
        self.assertEqual(len(urls), 2, urls)
        self.assertEqual(urls[1], mine)
        self.assertNotIn("참가 처리 중", out)
        self.assertNotIn("도시 참가 신청", out)
        self.assertNotIn("남은 일 하나", out)
        share = re.search(r"공유 주소: (\S+)", out).group(1)
        self.assertEqual(share, f"{PAGE_URL}?who={ME}")
        self.assertNotIn("#", share)
        self.assertNotEqual(share, mine)

    def test_no_open_prints_addresses(self):
        """--no-open이면 아무것도 열지 않고 신청 주소·내 도시 주소(#me)를 보여 주고, 끝 줄은 남은 일 하나(위 주소에서 Submit)예요.
        명단에 들어온 뒤에는 공유 주소(#me 없음)도 보여 줘요."""
        code, out = run_tty(self.cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        gid = self.only_gist()
        self.assertEqual(self.opened_urls(), [])
        self.assertNotIn("브라우저로 열었어요", out)
        self.assertRegex(out, r"도시 참가 신청: https://github\.com/\S+/issues/new\?\S*gist=" + gid)
        self.assertIn(f"내 도시 주소: {PAGE_URL}?who={ME}#me", out)
        self.assertNotIn("공유 주소: ", out)
        self.assertLess(out.index("도시 참가 신청: "), out.index("내 도시 주소: "))
        self.assertLess(out.index("숫자를 새로 올리려면"), out.index("남은 일 하나"))
        self.assertEqual(out.strip().splitlines()[-1].strip(), "남은 일 하나: 위의 ‘도시 참가 신청’ 주소를 열어 Submit new issue를 눌러요. 몇 분 뒤 내 도시 주소에 내 카드가 열려요.")
        self.gh.members = [{"login": ME, "gist": gid}]
        code, out = run_tty(self.cmd + ["--country", "KR"], self.env, "y")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, "공유 주소: " + re.escape(f"{PAGE_URL}?who={ME}") + r"\r?\n")

    def test_members_unknown_hides_share(self):
        """명단을 못 읽으면(들어왔는지 몰라요) 신청 주소와 내 도시 주소만 보여 주고 공유 주소는 보여 주지 않아요."""
        env = dict(self.env, AGENCITY_TOKEN_METER_BASE=self.gh.url + "/nope")   # 가짜 명단 자리가 404예요
        code, out = run_tty(self.cmd + ["--country", "KR"], env, "y")
        self.assertEqual(code, 0, out)
        self.assertIn("도시 명단을 확인하지 못했어요", out)
        self.assertIn(f"내 도시 주소: {PAGE_URL}?who={ME}#me", out)
        self.assertNotIn("공유 주소: ", out)
        self.assertIn(("GET", "/nope/members.json", None), self.gh.calls)

    def test_page_and_command_agree(self):
        """명령이 여는 주소와 도시 페이지가 같은 꼴이에요: 같은 사이트 주소, #me는 명령이 여는 주소에만, 공유 주소는 ?who=만."""
        self.assertIn(f"const PUBLIC_URL = '{PAGE_URL}';", CITY)
        with open(os.path.join(ROOT, "bin", "city_join.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn(f'CITY_URL = "{PAGE_URL}"', src)
        self.assertIn("location.hash === '#me'", CITY)
        self.assertIn("const shareURL = login => `${PUBLIC_URL}?who=${encodeURIComponent(login)}", CITY)
        self.assertNotIn("#me", re.search(r"const shareURL = [^\n]+", CITY).group(0))

    def test_country_none_keeps_app_summary(self):
        """앱으로 올린 요약(소개·층)이 있으면 나라만 빼고 나머지는 그대로예요. 숫자가 같으면 숫자 파일은 보내지 않아요."""
        code, out = run_tty(self.cmd, self.env, "y")   # 먼저 숫자만 올려요(나라 물음에 엔터: 나라는 건드리지 않아요)
        self.assertEqual(code, 0, out)
        self.assertIn("나라를 고를까요? 나라 순위에 쓰이고 공개돼요. KR처럼 두 글자로 적어요(엔터 = 안 고름, 전에 고른 나라는 그대로 · none = 빼기): ", out)
        self.assertIn("나라: 안 고름(전에 고른 나라가 있으면 그대로)", out)
        self.assertNotIn("그대로 둬요(지금: 고르지 않음)", out)   # gist에 나라가 없으면 '그대로(지금: 없음)'을 또 쓰지 않아요
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
        self.assertEqual(self.gh.ours(), [])

    def test_english(self):
        env = dict(self.env, LANG="en_US.UTF-8")
        code, out = run_tty(self.cmd + ["--country", "JP"], env, "n")
        self.assertEqual(code, 0, out)
        self.assertLess(out.index("Your total tokens: "), out.index("Upload? [y/N]"))
        self.assertNotIn("Pick your country?", out)
        self.assertIn("Country: JP", out)
        self.assertIn("Type y to sign in to GitHub and post (your gh login if you have one, otherwise a device code with gist permission only)", out)
        self.assertIn("Press Enter to stop here: nothing is posted and you won't sign in.", out)
        self.assertIn("(published when you post, even without a country)", out)
        self.assertIn("Nothing was posted", out)
        self.assertNotIn("token-meter", out.replace("token-meter.json", ""))
        self.assertEqual(self.gh.ours(), [])

    def meter_and_office(self, profile):
        return self.gh.add({"token-meter.json": json.dumps({"schema": 1, "app": "token-meter", "login": ME, "entries": []}),
                            "agencity.json": json.dumps({"schema": 1, "app": "agencity", "login": ME, "profile": profile, "floors": []})})

    def test_country_none_removes_unlisted_value(self):
        """gist의 나라가 목록에 없는 값(kr)이어도 로그인한 뒤 지금 값을 그대로 보여 주고(나라 물음에 엔터면 그대로), --country none이면 빼요."""
        gid = self.meter_and_office({"intro": "x", "country": "kr"})
        code, out = run_tty(self.cmd, self.env, "y")
        self.assertEqual(code, 0, out)
        self.assertIn("나라: 그대로 둬요(지금: kr)", out)
        self.assertEqual(self.gh.doc(gid, "agencity.json")["profile"], {"intro": "x", "country": "kr"})
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
        # 나라 목록이 없으면 나라를 묻지 않아요(그대로 둬요)
        code, out = run_tty([os.path.join(solo, "city_join.py"), "--no-open"], env, "n")
        self.assertEqual(code, 0, out)
        self.assertIn("나라 목록을 받지 못해서 나라는 묻지 않았어요", out)
        self.assertNotIn("나라를 고를까요?", out)

    def test_dry_run_shows_country(self):
        """--dry-run은 로그인도 올리기도 안 하고, 준 나라를 보여 줘요. 하루면 'active day'(단수)예요."""
        home = os.path.join(self.tmp, "home1")
        fake_logs(home, days=(("2026-10-24T05:10:00.000Z", 1000, 160),))
        env = dict(self.env, HOME=home, LANG="en_US.UTF-8")
        r = subprocess.run([sys.executable, "-I"] + self.cmd + ["--dry-run", "--country", "KR"], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"Your total tokens: [\d,]+\n")
        self.assertRegex(r.stdout, r"\b1 active day(?!s)")
        self.assertIn("Country: KR", r.stdout)
        self.assertIn("--dry-run", r.stdout)
        self.assertEqual(self.gh.ours(), [])

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


# ── U-40 도시 화면 ───────────────────────────────────────────────────────
def honest_doc(base, codex_no_cached=False, stray=False):
    """bin/token_meter.py가 가짜 기록(Claude·Codex·Gemini)을 그대로 센 공개 문서(TZ=Asia/Seoul).
    스트리밍 중간값(같은 id)과 날짜 없는 기록도 있어요. HOME은 임시 폴더라 이 컴퓨터의 기록은 읽지 않아요.
    codex_no_cached: Codex 기록 하나에 cached_input_tokens 칸이 없어요(그런 판이 있으면 셈이 입력·캐시 읽기를 0으로 올려요).
    stray: 시각이 null인 기록(셈이 1970-01-01로 적어요)과 시계가 2001년으로 돌아간 기록이 하나씩 더 있어요."""
    home = os.path.join(base, "home")
    claude = os.path.join(home, "claude")
    os.makedirs(os.path.join(claude, "p1"))
    with open(os.path.join(claude, "p1", "s.jsonl"), "w", encoding="utf-8") as f:
        for i in range(30):
            ts = f"2026-10-{3 + i % 10:02d}T{(i * 5) % 24:02d}:{i % 60:02d}:00.000Z"
            u = {"input_tokens": 1000 + i * 37, "output_tokens": 300 + i, "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 50000 + i * 1000}
            if i % 7 == 0:   # 스트리밍 중간값(같은 id, 작은 값)이 먼저 와요
                f.write(json.dumps({"type": "assistant", "timestamp": ts, "sessionId": "s1", "message": {"id": f"m{i}", "model": "claude-opus-4-5",
                                                                                                         "usage": {"input_tokens": 10, "output_tokens": 1}}}) + "\n")
            f.write(json.dumps({"type": "assistant", "timestamp": ts, "sessionId": f"s{i % 3}", "requestId": f"r{i}",
                                "message": {"id": f"m{i}", "model": "claude-opus-4-5", "usage": u}}) + "\n")
        f.write(json.dumps({"type": "assistant", "sessionId": "s9", "message": {"id": "mx", "model": "claude-opus-4-5",
                                                                                "usage": {"input_tokens": 120, "output_tokens": 30}}}) + "\n")   # 날짜 없는 기록
        if stray:
            f.write(json.dumps({"type": "assistant", "timestamp": None, "sessionId": "s8", "requestId": "rn",
                                "message": {"id": "mn", "model": "claude-opus-4-5", "usage": {"input_tokens": 900, "output_tokens": 40}}}) + "\n")
            f.write(json.dumps({"type": "assistant", "timestamp": "2001-09-09T01:46:40.000Z", "sessionId": "s8", "requestId": "ro",
                                "message": {"id": "mo", "model": "claude-opus-4-5", "usage": {"input_tokens": 700, "output_tokens": 20}}}) + "\n")
    codex = os.path.join(home, "codex")
    os.makedirs(os.path.join(codex, "sessions", "2026", "10", "20"))
    with open(os.path.join(codex, "sessions", "2026", "10", "20", "rollout-2026-10-20T01-00-00-c1.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2026-10-20T01:00:00.000Z", "type": "session_meta", "payload": {"id": "c1"}}) + "\n")
        f.write(json.dumps({"timestamp": "2026-10-20T01:00:01.000Z", "type": "turn_context", "payload": {"model": "gpt-5-codex"}}) + "\n")
        for i, (ts, a, c, o) in enumerate((("2026-10-20T01:00:05.000Z", 12000, 8000, 900), ("2026-10-20T02:00:05.000Z", 30000, 21000, 2500),
                                           ("2026-10-21T03:00:05.000Z", 52000, 40000, 4000))):
            tu = {"input_tokens": a, "cached_input_tokens": c, "output_tokens": o, "total_tokens": a + o}
            if codex_no_cached and i == 1:
                del tu["cached_input_tokens"]
            f.write(json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": tu, "last_token_usage": tu}}}) + "\n")
    gemini = os.path.join(home, "gemini")
    os.makedirs(os.path.join(gemini, "tmp", "abc123", "chats"))
    with open(os.path.join(gemini, "tmp", "abc123", "chats", "session-1.json"), "w", encoding="utf-8") as f:
        json.dump({"sessionId": "g1", "projectHash": "abc123", "messages": [
            {"id": "u1", "type": "user", "timestamp": "2026-10-22T02:59:00.000Z", "content": "x"},
            {"id": "a1", "type": "gemini", "timestamp": "2026-10-22T03:00:00.000Z", "model": "gemini-2.5-pro", "tokens": {"input": 5000, "cached": 1000, "output": 300, "thoughts": 120}},
            {"id": "a2", "type": "gemini", "timestamp": "2026-10-23T15:30:00.000Z", "model": "gemini-2.5-pro", "tokens": {"input": 9000, "cached": 4000, "output": 700, "thoughts": 0}}]}, f)
    env = {"HOME": home, "PATH": "/usr/bin:/bin", "TZ": "Asia/Seoul", "LANG": "en_US.UTF-8"}
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "token_meter.py"), "--json", "--login", ME, "--dir", claude, "--codex-dir", codex,
                        "--gemini-dir", gemini], env=env, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "node가 없어요(도시 화면 시험은 node로 돌려요)")
class CityFilter(unittest.TestCase):
    """숫자 거르기(U-40 5-2 ①): 지어낸 숫자는 '확인 안 됨', token_meter.py가 정직하게 센 숫자는 늘 통과."""

    NOW = "2026-11-12T12:00:00Z"   # 지구에서 가장 이른 시간대(UTC+14)는 13일 새벽 2시: 그 내일(14일)까지 괜찮고 15일은 미래 날짜예요

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="agencity-u40-filter-", dir=TMP_BASE)
        cls.doc = honest_doc(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def judge(self, docs):
        code = ("const DEMO = false, NOW = Date.parse(%s), now = () => new Date(NOW);\n" % json.dumps(self.NOW)
                + city_js("own", "num", "str", "TOOLS", "DAY_RE", "TZ_RE", "DAY_FIRST", "dayKey", "family", "cleanMeter", "verifyMeter", "realDay", "lastDay", "okDay")
                + "\nconst docs = %s;\n" % json.dumps(docs)
                + "console.log(JSON.stringify(Object.fromEntries(Object.entries(docs).map(([k, d]) => { const m = cleanMeter(d, %s); return [k, [verifyMeter(d, NOW), m && m.ok]]; }))));" % json.dumps(ME))
        return run_node(code)

    def variant(self, change):
        d = json.loads(json.dumps(self.doc))
        change(d, next(e for e in d["entries"] if e["tool"] == "claude"))
        return d

    def test_honest_passes(self):
        tools = {e["tool"]: e for e in self.doc["entries"]}
        self.assertEqual(set(tools), {"claude", "codex", "gemini"})
        cl = tools["claude"]
        self.assertLess(sum(v[0] for v in cl["byDay"].values()), cl["totals"]["total"])   # 날짜 없는 기록은 total에만 있어요
        self.assertEqual(self.judge({"honest": self.doc}), {"honest": ["", True]})

    def move_day(self, to):
        def change(d, e):
            first = sorted(e["byDay"])[0]
            e["byDay"][to] = e["byDay"].pop(first)   # 합은 그대로, 날짜만 옮겨요
        return self.variant(change)

    def test_forged_numbers_are_unverified(self):
        def total_only(d, e):
            e["totals"]["total"] *= 1000

        def total_and_input(d, e):
            e["totals"]["total"] += 5 * 10 ** 9
            e["totals"]["input"] += 5 * 10 ** 9

        def add_day(day, n):
            def change(d, e):
                for k in ("total", "input"):
                    e["totals"][k] += n
                e["byDay"].setdefault(day, [0, 0, 0])[0] += n   # 셈이 하듯 total과 그날에 같은 값을 더해요
            return change

        day_over_cap = add_day("2026-10-05", 2 * 10 ** 11)   # 하루 1000억 넘음: 망가진 값
        heavy_day_ok = add_day("2026-10-05", 5 * 10 ** 10)   # 하루 500억: 에이전트를 여럿 돌린 날도 걸리지 않아요
        def two_tools_heavy_ok(d, e):   # 같은 날 Claude 600억 + Codex 350억: 도구를 더해도 1000억 밑이라 괜찮아요
            add_day("2026-10-20", 6 * 10 ** 10)(d, e)
            add_day("2026-10-20", 35 * 10 ** 9)(d, next(x for x in d["entries"] if x["tool"] == "codex"))

        def two_tools_over_cap(d, e):   # 같은 날 600억 + 500억: 도구 하나로는 넘지 않아도 더하면 넘어요
            add_day("2026-10-20", 6 * 10 ** 10)(d, e)
            add_day("2026-10-20", 5 * 10 ** 10)(d, next(x for x in d["entries"] if x["tool"] == "codex"))
        stray_1970 = add_day("1970-01-01", 15)   # 시각이 빈 기록 한 줄(셈이 1970년으로 적어요): 그 몫이 작으면 괜찮아요
        stray_2001 = add_day("2001-09-09", 4000)
        stray_future = add_day("2027-03-01", 4000)   # 시계가 잠깐 틀린 기록

        def days_over_total(d, e):
            e["byDay"][sorted(e["byDay"])[0]][0] += 10 ** 6

        def same_tool_twice(d, e):
            d["entries"].insert(1, json.loads(json.dumps(e)))

        r = self.judge({
            "total_only": self.variant(total_only),
            "total_and_input": self.variant(total_and_input),
            "day_over_cap": self.variant(day_over_cap),
            "heavy_day_ok": self.variant(heavy_day_ok),
            "two_tools_heavy_ok": self.variant(two_tools_heavy_ok),
            "two_tools_over_cap": self.variant(two_tools_over_cap),
            "stray_1970": self.variant(stray_1970),
            "stray_2001": self.variant(stray_2001),
            "stray_future": self.variant(stray_future),
            "days_over_total": self.variant(days_over_total),
            "same_tool_twice": self.variant(same_tool_twice),
            "future": self.move_day("2026-11-15"),
            "utc14_tomorrow_ok": self.move_day("2026-11-14"),
            "before_2023": self.move_day("2022-12-31"),
            "tomorrow_ok": self.move_day("2026-11-13"),
            "first_day_ok": self.move_day("2023-01-01"),
            "feb_30": self.move_day("2025-02-30"),     # 달력에 없는 날짜
            "month_13": self.move_day("2024-13-01"),
            "day_00": self.move_day("2025-01-00"),
        })
        self.assertEqual(r, {
            "total_only": ["sum", False], "total_and_input": ["days", False], "day_over_cap": ["day", False],
            "heavy_day_ok": ["", True], "two_tools_heavy_ok": ["", True], "two_tools_over_cap": ["day", False],
            "stray_1970": ["", True], "stray_2001": ["", True], "stray_future": ["", True],
            "days_over_total": ["days", False], "same_tool_twice": ["sum", False],
            "future": ["date", False], "utc14_tomorrow_ok": ["", True], "before_2023": ["date", False],
            "tomorrow_ok": ["", True], "first_day_ok": ["", True],
            "feb_30": ["date", False], "month_13": ["date", False], "day_00": ["date", False]})

    def test_codex_without_cached_field_passes(self):
        """Codex 기록에 cached_input_tokens 칸이 빠진 판이 섞여도 token_meter.py가 정직하게 센 숫자는 걸리지 않아요
        (셈이 입력·캐시 읽기를 0으로 올려 칸 합이 total과 달라져요). 그 꼴에서 total을 부풀리면 날짜별 합 검사가 잡아요."""
        doc = honest_doc(os.path.join(self.tmp, "nocache"), codex_no_cached=True)
        cx = next(e for e in doc["entries"] if e["tool"] == "codex")
        self.assertEqual((cx["totals"]["input"], cx["totals"]["cacheRead"], cx["totals"]["cacheWrite"]), (0, 0, 0))
        self.assertNotEqual(cx["totals"]["output"], cx["totals"]["total"])   # 칸 합 ≠ total인 꼴이에요

        def codex(change):
            d = json.loads(json.dumps(doc))
            change(next(e for e in d["entries"] if e["tool"] == "codex"))
            return d

        def blow_up(e):
            e["totals"]["total"] *= 1000

        def cache_back(e):   # 캐시 읽기만 다시 넣은(입력은 0) 꼴은 예외가 아니에요: 칸 합을 봐요
            e["totals"]["cacheRead"] = 5

        r = self.judge({"honest": doc, "blow_up": codex(blow_up), "cache_back": codex(cache_back)})
        self.assertEqual(r, {"honest": ["", True], "blow_up": ["days", False], "cache_back": ["sum", False]})

    def test_stray_bad_dates_pass(self):
        """기록 한 줄의 시각이 비었거나(셈이 1970년으로 적어요) 시계가 틀려도 그 사람 전체가 '확인 안 됨'이 되지 않아요.
        그런 날짜는 날짜 없는 기록처럼 쳐서, 활동한 날·가장 많이 쓴 날에도 들어가지 않아요."""
        doc = honest_doc(os.path.join(self.tmp, "stray"), stray=True)
        cl = next(e for e in doc["entries"] if e["tool"] == "claude")
        self.assertIn("1970-01-01", cl["byDay"])   # 셈(token_meter.py)이 그렇게 적는지부터 봐요
        self.assertIn("2001-09-09", cl["byDay"])
        code = ("const DEMO = false, NOW = Date.parse(%s), now = () => new Date(NOW);\n" % json.dumps(self.NOW)
                + city_js("own", "num", "str", "TOOLS", "DAY_RE", "TZ_RE", "DAY_FIRST", "dayKey", "family", "cleanMeter", "verifyMeter", "realDay",
                          "lastDay", "okDay")
                + "\nconst a = cleanMeter(%s, %s), b = cleanMeter(%s, %s);\n" % (json.dumps(doc), json.dumps(ME), json.dumps(self.doc), json.dumps(ME))
                + "console.log(JSON.stringify([a.ok, a.why, Object.keys(a.days).filter(d => d < '2023'), a.active === b.active, a.best === b.best]));")
        self.assertEqual(run_node(code), [True, "", [], True, True])

    def test_my_record_counts_all_days(self):
        """내 기록(활동한 날, 가장 많이 쓴 날)은 400일로 자르기 전 byDay 전부로 세요. 건물에 쓰는 days만 최근 400일이에요."""
        import datetime
        d0, by = datetime.date(2024, 1, 1), {}
        for i in range(600):
            by[(d0 + datetime.timedelta(days=i)).isoformat()] = [5 * 10 ** 9 if i == 10 else 1000, 0, 0]
        tot = sum(v[0] for v in by.values())
        doc = {"schema": 1, "app": "token-meter", "login": ME, "updatedAt": "2026-11-01T00:00:00Z", "entries": [
            {"tool": "claude", "tz": "Asia/Seoul", "totals": {"input": tot, "output": 0, "cacheWrite": 0, "cacheRead": 0, "total": tot}, "byDay": by}]}
        code = ("const DEMO = false, NOW = Date.parse(%s), now = () => new Date(NOW);\n" % json.dumps(self.NOW)
                + city_js("own", "num", "str", "TOOLS", "DAY_RE", "TZ_RE", "DAY_FIRST", "dayKey", "family", "cleanMeter", "verifyMeter", "realDay", "lastDay", "okDay",
                          "activeDays", "bestDay")
                + "\nconst m = cleanMeter(%s, %s);\n" % (json.dumps(doc), json.dumps(ME))
                + "console.log(JSON.stringify([m.ok, m.active, m.best, Object.keys(m.days).length, activeDays(m), bestDay(m)]));")
        self.assertEqual(run_node(code), [True, 600, 5 * 10 ** 9, 400, 600, 5 * 10 ** 9])

    def test_demo_data_passes_but_one(self):
        """예시 데이터(?demo=1)도 걸리지 않아요. demo-zed 하나만 '확인 안 됨' 예시예요."""
        with open(os.path.join(ROOT, "examples", "city", "demo.json"), encoding="utf-8") as f:
            ppl = json.load(f)["people"]
        code = ("const DEMO = true, NOW = Date.parse('2026-10-21T09:00:00+09:00'), now = () => new Date(NOW);\n"
                + city_js("own", "num", "str", "TOOLS", "DAY_RE", "TZ_RE", "DAY_FIRST", "dayKey", "family", "cleanMeter", "verifyMeter", "realDay", "lastDay", "okDay")
                + "\nconst ppl = %s;\nconsole.log(JSON.stringify(ppl.filter(p => !cleanMeter(p.meter, p.login).ok).map(p => p.login)));" % json.dumps(ppl))
        self.assertEqual(run_node(code), ["demo-zed"])


@unittest.skipUnless(shutil.which("node"), "node가 없어요(도시 화면 시험은 node로 돌려요)")
class CityMe(unittest.TestCase):
    """'나' 표시: 참가 명령이 여는 ?who=<아이디>#me만 이 브라우저의 '나'가 돼요. 공유 주소에는 #me가 없어요."""

    def test_me_from_join_link_only(self):
        code = city_js("LOGIN_RE", "ME_KEY", "PUBLIC_URL") + """
let lang = 'ko', meFrom = '';
const CONFIG = { me: '' }, store = {};
const okStore = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } };
const badStore = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
function open(search, hash, localStorage) {
  const location = { search, hash, pathname: '/agencity/' }, urls = [];
  const history = { state: null, replaceState: (s, t, u) => { urls.push(u); } };
""" + city_js("takeMe") + """
  return [takeMe(), urls];
}
function forget(from, localStorage) {
  meFrom = from; CONFIG.me = 'Alice';
""" + city_js("forgetMe") + """
  forgetMe();
  return [CONFIG.me, meFrom];
}
""" + city_js("shareURL") + """
const out = {};
out.first = open('?who=Alice', '#me', okStore); out.stored1 = store[ME_KEY];
out.others = open('?who=bob', '', okStore); out.stored2 = store[ME_KEY];
out.notExact = open('?who=bob', '#mine', okStore);
out.badLogin = open('?who=-x', '#me', okStore); out.stored3 = store[ME_KEY];
out.noWho = open('', '#me', okStore);
out.blocked = open('?who=Carol', '#me', badStore);
out.blockedPlain = open('?who=Carol', '', badStore);
out.share = [shareURL('Alice')]; lang = 'en'; out.share.push(shareURL('Alice'));
out.forgetLocal = forget('local', okStore); out.stored4 = store[ME_KEY] || null;
out.forgetBrowser = forget('browser', okStore); out.stored5 = store[ME_KEY] || null;
out.forgetBlocked = forget('browser', badStore);
store[ME_KEY] = 'bob'; out.forgetOther = forget('browser', okStore); out.stored6 = store[ME_KEY] || null;   // 다른 탭이 그사이 bob을 기억했어요
store[ME_KEY] = 'alice'; out.forgetSame = forget('browser', okStore); out.stored7 = store[ME_KEY] || null;   // 대소문자만 다르면 같은 사람
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        self.assertEqual(r["first"], ["Alice", ["/agencity/?who=Alice"]])      # 기억하고 #me만 지워요(?who=는 둬요)
        self.assertEqual(r["stored1"], "Alice")
        self.assertEqual(r["others"], ["Alice", []])                           # 남의 공유 링크: '나'는 그대로, 주소도 그대로
        self.assertEqual(r["stored2"], "Alice")
        self.assertEqual(r["notExact"], ["Alice", []])
        self.assertEqual(r["badLogin"], ["Alice", ["/agencity/?who=-x"]])     # 아이디 꼴이 아니면 기억하지 않아요
        self.assertEqual(r["stored3"], "Alice")
        self.assertEqual(r["noWho"], ["Alice", ["/agencity/"]])
        self.assertEqual(r["blocked"], ["Carol", ["/agencity/?who=Carol"]])   # 저장소가 막혀도 이번 화면에서는 '나'
        self.assertEqual(r["blockedPlain"], ["", []])
        self.assertEqual(r["share"], ["https://min-heee.github.io/agencity/?who=Alice", "https://min-heee.github.io/agencity/?who=Alice&lang=en"])
        self.assertEqual(r["forgetLocal"], ["Alice", "local"])                 # 앱의 '나'는 '내가 아니에요'로 바뀌지 않아요
        self.assertEqual(r["stored4"], None)
        self.assertEqual(r["forgetBrowser"], ["", ""])
        self.assertEqual(r["forgetBlocked"], ["", ""])
        self.assertEqual(r["forgetOther"], ["", ""])                           # 이 탭의 '나'는 지우고
        self.assertEqual(r["stored6"], "bob")                                  # 다른 탭이 기억한 '나'는 그대로
        self.assertEqual(r["forgetSame"], ["", ""])
        self.assertIsNone(r["stored7"])

    def test_me_follows_other_tabs(self):
        """다른 탭에서 '나'를 바꾸거나 지우면(storage 이벤트) 이 탭도 따라가요. 불러오는 중이거나 앱의 '나'면 그대로예요."""
        code = city_js("LOGIN_RE") + """
let meFrom = '';
const CONFIG = { me: '' };
""" + city_js("meReady", "meChanged") + """
const out = {};
out.notReady = [meChanged('bob'), CONFIG.me];
meReady = true;
meFrom = 'local'; CONFIG.me = 'App'; out.local = [meChanged('bob'), CONFIG.me, meFrom];
meFrom = 'browser'; CONFIG.me = 'Alice'; out.same = meChanged('alice');
out.other = [meChanged('bob'), CONFIG.me, meFrom];
out.cleared = [meChanged(''), CONFIG.me, meFrom];
out.bad = [meChanged('-x'), CONFIG.me];
out.fromNone = [meChanged('carol'), CONFIG.me, meFrom];
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        self.assertEqual(r["notReady"], [False, ""])
        self.assertEqual(r["local"], [False, "App", "local"])
        self.assertFalse(r["same"])
        self.assertEqual(r["other"], [True, "bob", "browser"])
        self.assertEqual(r["cleared"], [True, "", ""])
        self.assertEqual(r["bad"], [False, ""])
        self.assertEqual(r["fromNone"], [True, "carol", "browser"])
        self.assertIn("addEventListener('storage'", CITY)
        self.assertIn("if (!meChanged(v)) return;", CITY)

    def test_me_order_in_page(self):
        """#me는 첫 syncURL(setView)보다 먼저 지우고, 앱의 '나'(org.json·로그인)가 브라우저 기억보다 앞서요. 공유 주소에는 #me를 붙이지 않아요."""
        self.assertLess(CITY.index("const browserMe = takeMe();"), CITY.index("setView(view, false);"))
        self.assertIn("if (CONFIG.me) meFrom = 'local';\n  else if (browserMe) { CONFIG.me = browserMe; meFrom = 'browser'; }", CITY)
        self.assertNotIn("#me`", CITY)
        self.assertEqual(re.findall(r"'#me'", CITY), ["'#me'"])   # 주소의 #me를 읽는 곳 하나뿐


@unittest.skipUnless(shutil.which("node"), "node가 없어요(도시 화면 시험은 node로 돌려요)")
class CityPending(unittest.TestCase):
    """명단에 없는 ?who=: 참가 처리 중 → 30초마다 ?t=로 다시 읽기 → 들어오면 카드, 10분이면 멈춤."""

    def test_pending_then_joined_or_late(self):
        code = "(async () => {\n" + city_js("LOGIN_RE", "GIST_RE", "MAX_BYTES", "POLL_MS") + """
const DEMO = false, CONFIG = { registry: 'https://example.test/tm/' };
let clock = 1000000; Date.now = () => clock;
const timers = []; let tid = 0;
const setTimeout = (fn, ms) => { timers.push({ id: ++tid, at: clock + ms, fn }); return tid; };
const clearTimeout = id => { const i = timers.findIndex(x => x.id === id); if (i >= 0) timers.splice(i, 1); };
let members = [];
const urls = [], cards = [], joinedList = [];
const getCapped = async url => { urls.push(url); return JSON.stringify({ members }); };
const loadOne = async m => ({ login: m.login, gist: m.gist, meter: {} });
const waitCard = () => cards.push(wait ? (wait.late ? 'late' : 'wait') : 'none');
const joined = (got, open) => joinedList.push([got.login, open]);
const cardEl = { hidden: false, dataset: { kind: 'wait' } }, $ = s => cardEl;   // 지금 떠 있는 카드
""" + city_js("citizens", "wait", "listURL", "readList", "setCitizens", "findJoined", "waitFor", "stopWait", "waitShown", "pollWait") + """
async function tick() { timers.sort((a, b) => a.at - b.at); const t = timers.shift(); clock = t.at; await t.fn(); }
const out = {};
waitFor('newbie');
out.start = [cards.slice(), timers.length, timers[0].at - 1000000];
await tick();
out.miss = [urls.slice(), timers.length, joinedList.length];
members = [{ login: 'Old-One', gist: 'abcdef12', joinedAt: '2026-10-01T00:00:00Z' }, { login: 'NewBie', gist: 'abcdef34', joinedAt: '2026-11-12T00:00:00Z' }, { login: 'bad', gist: 'zz' }];
await tick();
out.found = [joinedList.slice(), timers.length, wait, citizens.get('newbie'), citizens.get('old-one'), citizens.has('bad')];
cards.length = 0; urls.length = 0; members = [];
const t0 = clock;
waitFor('ghost');
let n = 0;
while (timers.length) { await tick(); n++; }
out.late = [n, cards[cards.length - 1], wait.late, clock - t0, urls.every(u => /^https:\\/\\/example\\.test\\/tm\\/members\\.json\\?t=\\d+$/.test(u))];
waitFor('closer'); stopWait();
out.closed = [timers.length, wait];
members = [{ login: 'racer', gist: 'abcdef56' }]; joinedList.length = 0;
waitFor('racer');
const t = timers.shift(); clock = t.at; const pr = t.fn(); stopWait(); await pr;
out.race = [joinedList.length, timers.length];
// 다른 카드가 기다림 카드를 덮었어요: 10분이 지나면 조용히 멈추고(그 카드를 덮어쓰지 않아요), 들어오면 도시에만 세워요(open = false)
cards.length = 0; members = [];
waitFor('hidden1'); cardEl.dataset.kind = 'person';
while (timers.length) await tick();
out.coveredLate = [cards.slice(), wait];
cardEl.dataset.kind = 'wait'; joinedList.length = 0;
waitFor('hidden2'); cardEl.dataset.kind = 'person';
members = [{ login: 'hidden2', gist: 'abcdef78' }];
await tick();
out.coveredJoin = [joinedList.slice(), wait];
// 다른 카드도 닫혀 있으면(카드 숨김) 열지 않아요
cardEl.dataset.kind = 'wait'; joinedList.length = 0;
waitFor('hidden3'); cardEl.hidden = true; cardEl.dataset.kind = '';
members = [{ login: 'hidden3', gist: 'abcdef90' }];
await tick();
out.closedJoin = joinedList.slice();
console.log(JSON.stringify(out));
})();
"""
        r = run_node(code)
        self.assertEqual(r["start"], [["wait"], 1, 30000])
        self.assertEqual(r["miss"], [["https://example.test/tm/members.json?t=1030000"], 1, 0])   # 캐시 피하기 ?t=
        self.assertEqual(r["found"], [[["NewBie", True]], 0, None, 2, 1, False])                # 들어오면 카드(다시 읽기는 끝)
        self.assertEqual(r["late"], [20, "late", True, 600000, True])                           # 10분(20번) 뒤 'Submit했는지'로 멈춰요
        self.assertEqual(r["closed"], [0, None])
        self.assertEqual(r["race"], [0, 0])                                                     # 읽는 사이 닫았으면 열지 않아요
        self.assertEqual(r["coveredLate"], [["wait"], None])                                    # 덮였으면 'late'로 덮어쓰지 않고 멈춰요
        self.assertEqual(r["coveredJoin"], [[["hidden2", False]], None])                        # 들어오면 도시에만(카드는 그대로)
        self.assertEqual(r["closedJoin"], [["hidden3", False]])

    def test_pending_only_when_not_listed(self):
        self.assertIn("const pending = LOGIN_RE.test(want) && !res.logins.includes(want.toLowerCase());", CITY)
        self.assertIn("if (p) card(p);\n    else if (pending) waitFor(want);", CITY)
        self.assertIn("if (pending) waitFor(want);\n      return;", CITY)   # 명단이 비어 있어도(첫 참가자) 기다려요
        for k in ("ko", "en"):
            self.assertIn({"ko": "참가 처리 중이에요 · 잠시 뒤 저절로 다시 볼게요", "en": "Your join is being processed"}[k], CITY)
        self.assertIn("참가 신청을 Submit했는지 봐 주세요", CITY)


@unittest.skipUnless(shutil.which("node"), "node가 없어요(도시 화면 시험은 node로 돌려요)")
class CityWaitCard(unittest.TestCase):
    """기다림 카드 글은 '나'에게만 2인칭(할 일 포함), 남에게는 3인칭. 들어오면 순위를 다시 매긴 뒤에 열린 카드·순위표를 그려요."""

    def test_wait_text_me_or_other(self):
        code = city_js("T", "esc", "t", "cname", "flag", "isMe", "letterAv", "avatarBig", "waitCard") + """
let lang = 'ko', selected = null, wait = null, shown = null;
const DEMO = false, CONFIG = { me: 'newbie' }, applySel = () => {};
const showCard = (kind, html) => { shown = [kind, html]; };
const text = () => shown[1].replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim();
const out = {};
wait = { login: 'NewBie', late: false }; waitCard(); out.me = [shown[0], text(), shown[1].includes('avatars.githubusercontent.com')];
wait.late = true; waitCard(); out.meLate = [text(), shown[1].includes('wait-again')];
wait = { login: 'stranger', late: false }; waitCard(); out.other = [text(), shown[1].includes('avatars.')];
wait.late = true; waitCard(); out.otherLate = text();
lang = 'en'; wait = { login: 'NewBie', late: false }; waitCard(); out.en = text();
wait = { login: 'stranger', late: false }; waitCard(); out.enOther = text();
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        kind, me, av = r["me"]
        self.assertEqual(kind, "wait")
        self.assertIn("참가 처리 중이에요 · 잠시 뒤 저절로 다시 볼게요", me)              # 정해진 문구는 그대로
        self.assertIn("GitHub 신청 화면에서 Submit new issue를 누르면 보통 몇 분 안에 들어와요", me)   # 할 일과 걸리는 때
        self.assertIn("30초마다", me)
        self.assertTrue(av)                                                            # '나'면 GitHub 아바타
        late, again = r["meLate"]
        self.assertIn("참가 신청을 Submit했는지 봐 주세요", late)
        self.assertIn("터미널에 나온 ‘도시 참가 신청’ 주소를 열어 Submit new issue를 눌러요", late)
        self.assertTrue(again)
        other, av = r["other"]
        self.assertIn("‘stranger’는 아직 도시에 없어요 · 참가 신청 중이면 몇 분 뒤 들어와요", other)
        for gone in ("Submit", "참가 처리 중이에요", "참가 처리 중"):                       # 남에게는 2인칭·Submit 안내가 없어요
            self.assertNotIn(gone, other)
            self.assertNotIn(gone, r["otherLate"])
        self.assertFalse(av)
        self.assertIn("10분 동안 다시 봤지만 아직 명단에 없어요", r["otherLate"])
        self.assertIn("Your join is being processed · this page checks again on its own", r["en"])
        self.assertIn("Click Submit new issue on the GitHub request page", r["en"])
        self.assertNotIn("Submit", r["enOther"])
        self.assertNotIn("Your", r["enOther"])

    def test_joined_reranks_before_drawing(self):
        code = city_js("T", "COUNTRY_FROM", "RANK_FROM", "esc", "t", "cname", "flag", "fmt", "ranked", "okN", "rerank", "joined") + """
let lang = 'ko', ZONES = [], people = [], view = 'numbers', selected = null, msgArgs = null;
const cardEl = { hidden: false, dataset: { kind: 'person' } }, msgEl = { dataset: {}, hidden: true };
const $ = s => s === '#card' ? cardEl : msgEl;
const calls = [], addPerson = m => { people.push(m); }, ctryOptions = () => {}, fillFind = () => {};
const snap = () => people.map(p => [p.login, p.rankAll]).sort();
const card = (p, focus, move) => calls.push(['card', p.login, focus, move === undefined ? 'move' : move, snap()]);
const drawNumbers = () => calls.push(['numbers', snap()]);
const P = (login, total) => ({ login, c: 'JP', total, ok: true });
people = [P('alice', 3e4), P('bob', 2e4)]; rerank();
const out = {};
selected = people[0];                                     // 숫자 보기에서 alice 카드가 열려 있어요
joined(P('newbie', 5e4), false); out.other = calls.splice(0);
selected = null; cardEl.hidden = true;                    // 카드가 닫혀 있어요
joined(P('carol', 1e4), false); out.closed = calls.splice(0);
cardEl.hidden = false; cardEl.dataset.kind = 'wait';      // 기다림 카드가 떠 있어요
joined(P('dave', 9e4), true); out.open = calls.splice(0);
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        self.assertEqual(r["other"], [["card", "alice", False, False, [["alice", 2], ["bob", 3], ["newbie", 1]]]])   # 순위를 매긴 뒤, 자리는 그대로
        self.assertEqual(r["closed"], [["numbers", [["alice", 2], ["bob", 3], ["carol", 4], ["newbie", 1]]]])           # 닫혀 있으면 열지 않고 순위표만
        self.assertEqual(r["open"], [["card", "dave", False, "move", [["alice", 3], ["bob", 4], ["carol", 5], ["dave", 1], ["newbie", 2]]]])
        # 한 사람씩 불러올 때도 순위를 다시 매긴 뒤에 순위표를 그려요
        self.assertIn("rerank(); layout(); draw(); if (!moved) fit(); refreshChrome(); if (view === 'numbers') drawNumbers(); });", CITY)


RANK_SETUP = city_js("T", "COUNTRY_FROM", "RANK_FROM", "esc", "t", "cname", "flag", "fmt", "ranked", "activeDays", "bestDay", "citizens", "setCitizens",
                     "okN", "rerank", "topPct", "rankLines") + """
let lang = 'ko', ZONES = [], people = [];
const P = (login, c, total, ok = true) => ({ login, c, total, ok, stale: 0, demo: true, meter: { days: { '2026-10-01': total * 0.75, '2026-10-02': total * 0.25 } } });
const lines = p => { const r = rankLines(p); return r && [r.head, r.tail]; };
"""


@unittest.skipUnless(shutil.which("node"), "node가 없어요(도시 화면 시험은 node로 돌려요)")
class CityRanks(unittest.TestCase):
    """순위 줄(R2)·나라 5명 규칙·순위표 칸·카드 한 숫자·건물 높이·참가 창."""

    def test_rank_lines_before_and_after_20(self):
        code = RANK_SETUP + """
const out = {};
// 확인된 8명(대한민국 4명) + 확인 안 됨 1명
people = [P('kr-a', 'KR', 4e8), P('kr-b', 'KR', 3e8), P('kr-c', 'KR', 2e8), P('kr-d', 'KR', 1e8), P('kr-x', 'KR', 9e14, false),
  P('jp-a', 'JP', 5e8), P('jp-b', 'JP', 5e7), P('no-a', '', 6e8), P('no-b', '', 1e6)];
setCitizens(people.map((p, i) => ({ login: p.login, joinedAt: `2026-10-${String(20 - i).padStart(2, '0')}T00:00:00Z` })));
rerank();
out.few = [okN, lines(people[1]), lines(people[7]), lines(people[4]), people[4].rankAll];
people.push(P('kr-e', 'KR', 5e7));
rerank();
out.five = lines(people[1]);
// 확인된 20명: 대한민국 6명, 일본 2명
people = [];
for (let i = 0; i < 20; i++) people.push(P(`p-${String(i).padStart(2, '0')}`, i < 6 ? 'KR' : i < 8 ? 'JP' : 'US', (20 - i) * 1e8));
people.push(P('x-1', 'KR', 1e15, false));
setCitizens(people);
rerank();
out.twenty = [lines(people[0]), lines(people[6]), lines(people[19])];
lang = 'en'; out.en = lines(people[0]); lang = 'ko';
people.pop(); people.pop(); rerank();
out.nineteen = lines(people[0])[0][0];
// 내 기록은 cleanMeter가 자르기 전 byDay 전부로 센 값(active·best)을 써요(400일 넘게 써도 줄지 않아요)
const big = P('big', '', 1e9); big.meter = { days: { '2026-10-01': 1e9 }, active: 600, best: 5e9 };
people = [big]; setCitizens([big]); rerank();
out.allDays = lines(big)[0];
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        ok_n, kr_b, no_a, bad, bad_rank = r["few"]
        self.assertEqual(ok_n, 8)                                           # 확인 안 됨은 N에 안 들어가요
        self.assertEqual(kr_b, [["8번째 시민", "가장 많이 쓴 날 2.3억 토큰", "활동한 날 2일"], ["세계 4등 · 8명 중", "나라 순위는 5명부터"]])
        self.assertEqual(no_a, [["2번째 시민", "가장 많이 쓴 날 4.5억 토큰", "활동한 날 2일"], ["세계 1등 · 8명 중"]])   # 나라를 안 골랐으면 나라 말이 없어요
        self.assertIsNone(bad)
        self.assertIsNone(bad_rank)
        self.assertEqual(r["five"][1], ["세계 4등 · 9명 중", "대한민국 2등 · 5명 중"])
        top, jp, last = r["twenty"]
        self.assertEqual(top, [["세계 1등 · 20명 중 · 상위 5%", "대한민국 1등 · 6명 중"], []])
        self.assertEqual(jp, [["세계 7등 · 20명 중 · 상위 35%"], ["나라 순위는 5명부터"]])
        self.assertEqual(last, [["세계 20등 · 20명 중 · 상위 100%", "미국 12등 · 12명 중"], []])
        self.assertEqual(r["en"], [["#1 of 20 worldwide · top 5%", "#1 of 6 in South Korea"], []])
        self.assertEqual(r["nineteen"], "첫 번째 시민")   # 19명이면 다시 'n번째 시민'이 앞에(1이면 '첫 번째')
        self.assertEqual(r["allDays"], ["첫 번째 시민", "가장 많이 쓴 날 50억 토큰", "활동한 날 600일"])

    TABLE = RANK_SETUP + city_js("PAGE", "FEW", "OLD_DAYS", "VISION_URL", "INSTALL_URL", "avatar", "inZone", "canJoin", "joinBtn", "scopeName", "isMe",
                                 "rowHTML", "drawNumbers") + """
const LOCAL = false, CONFIG = { me: 'kr-b' };
let zone = 'ALL', shown = PAGE, selected = null, loaded = true, meMissing = false;
const els = {}, $ = s => els[s] || (els[s] = { textContent: '', innerHTML: '', hidden: false });
people = [P('kr-a', 'KR', 4e8), P('kr-b', 'KR', 3e8), P('kr-c', 'KR', 2e8), P('kr-d', 'KR', 1e8), P('kr-x', 'KR', 9e14, false),
  P('jp-a', 'JP', 5e8), P('jp-b', 'JP', 5e7), P('no-a', '', 6e8)];
rerank();
const snap = () => ({ sub: $('#numSub').textContent, self: $('#numSelf').textContent, table: $('#table').innerHTML, foot: $('#numFoot').innerHTML, tiles: $('#tiles').innerHTML });
const out = {};
drawNumbers(); out.all = snap();
zone = 'KR'; drawNumbers(); out.kr4 = snap();
people.push(P('kr-e', 'KR', 5e7)); rerank(); drawNumbers(); out.kr5 = snap();
console.log(JSON.stringify(out));
"""

    def test_table_columns_and_country_rule(self):
        r = run_node(self.TABLE)
        cells = lambda html, cls: [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r'<td class="' + cls + r'[^"]*"[^>]*>(.*?)</td>', html, re.S)]   # noqa: E731
        heads = [re.sub(r"<[^>]+>", "", x) for x in re.findall(r"<th[^>]*>(.*?)</th>", r["all"]["table"], re.S)]
        self.assertEqual(heads, ["순위", "아이디", "나라", "총 토큰"])   # '오늘'·'마지막으로 올린 때' 칸은 없어요
        self.assertNotIn("오늘", r["all"]["table"] + r["all"]["tiles"])
        self.assertEqual(r["all"]["self"], "스스로 올린 숫자(자기 신고) · 각자 컴퓨터에 남은 기록 기준")
        self.assertEqual(cells(r["all"]["table"], "c-rk"), ["1", "2", "3", "4", "5", "6", "7", "—"])   # 확인 안 됨은 등수 없이 맨 아래
        self.assertIn("확인 안 됨 · 1명", r["all"]["table"])
        self.assertEqual(cells(r["all"]["table"], "c-tot r")[-1], "확인 안 됨")
        self.assertIn('class="me', r["all"]["table"])
        self.assertIn("에이전시티 설치", r["all"]["foot"])
        # 대한민국 4명(확인된): 나라 순위 대신 세계 순위와 '나라 순위는 5명부터'
        self.assertTrue(r["kr4"]["sub"].endswith("나라 순위는 5명부터"), r["kr4"]["sub"])
        # 부제의 사람 수는 확인된 사람(5명 규칙·'N명 중'과 같은 수), 확인 안 됨은 따로
        self.assertEqual(r["all"]["sub"], "모든 나라 · 7명 · 확인 안 됨 1명")
        self.assertEqual(r["kr4"]["sub"], "🇰🇷 대한민국 · 4명 · 확인 안 됨 1명 · 나라 순위는 5명부터")
        self.assertEqual(r["kr5"]["sub"], "🇰🇷 대한민국 · 5명 · 확인 안 됨 1명")
        # 5명 전 나라는 세계 순위 그대로, 칸마다 작게 '세계 순위'(확인 안 됨 줄은 등수도 말도 없어요)
        self.assertEqual(cells(r["kr4"]["table"], "c-rk"), ["3세계 순위", "4세계 순위", "5세계 순위", "6세계 순위", "—"])
        # 5명이면 나라 안 순위(1부터)와 작게 전체 순위
        self.assertNotIn("5명부터", r["kr5"]["sub"])
        self.assertEqual(cells(r["kr5"]["table"], "c-rk")[:2], ["1전체 3위", "2전체 4위"])

    def test_world_rank_label_before_five(self):
        """5명 전 나라와 '나라 안 고름'을 고르면 순위 칸의 숫자가 세계 순위라는 게 칸에서 바로 보여요(작게 '세계 순위'). 모든 나라·5명부터는 그대로."""
        code = self.TABLE.replace("console.log(JSON.stringify(out));", """
const rk = () => [...$('#table').innerHTML.matchAll(/<td class="c-rk">(.*?)<\\/td>/gs)].map(m => m[1].replace(/<[^>]+>/g, '|').replace(/\\|+/g, '|').replace(/^\\||\\|$/g, ''));
const res = {};
zone = 'JP'; drawNumbers(); res.jp = rk();
zone = ''; drawNumbers(); res.none = rk();
zone = 'ALL'; drawNumbers(); res.all = rk();
zone = 'KR'; drawNumbers(); res.kr5 = rk().slice(0, 2);
lang = 'en'; zone = 'JP'; drawNumbers(); res.jpEn = rk();
console.log(JSON.stringify(res));""")
        r = run_node(code)
        self.assertEqual(r["jp"], ["2|세계 순위", "7|세계 순위"])                 # 일본 2명: 세계 2위·7위라고 칸에서 보여요
        self.assertEqual(r["none"], ["1|세계 순위"])                               # '나라 안 고름'도 세계 순위예요
        self.assertEqual(r["jpEn"], ["2|World rank", "7|World rank"])
        self.assertEqual(r["all"][:3], ["1", "2", "3"])                            # 모든 나라 보기는 그대로(숫자만)
        self.assertEqual(r["kr5"], ["1|전체 3위", "2|전체 4위"])                   # 5명부터는 그대로(나라 순위와 작게 전체 순위)

    def test_card_one_number(self):
        code = RANK_SETUP + city_js("OLD_DAYS", "TOOLS", "cacheOf", "isMe", "avatarBig", "letterAv", "hash", "dayKey", "PUBLIC_URL", "SITE", "shareURL",
                                    "cardArt", "shareText", "card") + """
const LOCAL = false, CONFIG = { me: 'kr-b' }, now = () => new Date('2026-10-21T09:00:00+09:00');
let meFrom = 'browser', view = 'numbers', selected = null, html = '';
const els = {}, $ = s => els[s] || (els[s] = { addEventListener(ev, fn) { this.fn = fn; } });
const showCard = (kind, h) => { html = h; }, applySel = () => {}, drawNumbers = () => {}, bringIntoView = () => {}, rel = () => '방금', dayRel = () => '오늘';
const prepped = [], copied = [], prepArt = p => { prepped.push(p.login); }, saveCard = () => {}, copy = s => { copied.push(s); };
const M = (total, ok = true) => ({ tools: { claude: { total, cacheRead: total * 0.86 } }, models: { Opus: total }, days: { '2026-10-01': total }, updatedAt: '', ok });
people = [{ login: 'kr-a', c: 'KR', total: 4e8, ok: true, meter: M(4e8), office: null },
  { login: 'kr-b', c: 'KR', total: 3e8, ok: true, meter: M(3e8), office: { intro: '', district: '', floors: [], updatedAt: '' } },
  { login: 'kr-b2', c: 'KR', total: 9e14, ok: false, meter: M(9e14, false), office: null }];
setCitizens(people);
rerank();
const out = {};
card(people[1]); out.me = html; els['#cardShare'].fn(); out.share = copied.pop();
card(people[0]); out.other = html;
meFrom = 'local'; card(people[1]); out.local = html;
CONFIG.me = 'kr-b2'; meFrom = 'browser'; card(people[2]); out.bad = html;
CONFIG.me = 'kr-a'; card(people[2]); out.badOther = html;
out.prepped = prepped;
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        me = r["me"]
        self.assertIn('id="cardSave"', me)                                      # '나'이고 확인됐으면 카드 저장
        self.assertNotIn('id="cardSave"', r["other"])                          # 남의 카드(#me로 정한 '나'가 아님)에는 없어요
        self.assertNotIn('id="cardShare"', r["other"])
        self.assertIn('id="cardSave"', r["local"])                             # 앱의 '나'도 저장할 수 있어요
        self.assertNotIn('id="cardSave"', r["bad"])                            # 확인 안 됨이면 단추가 없어요
        self.assertEqual(r["prepped"], ["kr-b", "kr-b"])                       # 그림은 '나'의 카드를 열 때만 미리 만들어요
        # 공유 글: 순위 줄의 등수·'N명 중'은 그대로, 규칙 안내('나라 순위는 5명부터')만 빼요
        self.assertEqual(r["share"], "에이전시티 도시에 내 건물이 섰어요 · 총 토큰 3억 · 2번째 시민 · 가장 많이 쓴 날 3억 토큰 · 활동한 날 1일"
                                     " · 세계 2등 · 2명 중 · 나도 세어 보기 → https://min-heee.github.io/agencity/?who=kr-b")
        self.assertIn("나라 순위는 5명부터", me)                                 # 화면 카드에는 규칙 안내가 있어요
        self.assertIn('<div class="cbig"><span>총 토큰</span><b>3억</b><small>그중 캐시 읽기 86%</small>', me)    # 총 토큰을 가장 크게, 캐시 읽기는 작게
        for gone in ("작업량", "Lv.", "건물 높이", "공개한 층", "오늘"):        # 작업량·Lv·높이 안내 없음, 공개한 층이 없으면 그 칸도 숨겨요
            self.assertNotIn(gone, me)
        self.assertIn("스스로 올린 숫자(자기 신고) · 각자 컴퓨터에 남은 기록 기준", me)
        self.assertIn("2번째 시민", me)
        self.assertIn('data-act="not-me"', me)
        self.assertIn('id="cardShare"', me)
        self.assertNotIn('data-act="not-me"', r["local"])                      # 앱의 '나'는 이 단추로 지우지 않아요
        bad = r["bad"]
        self.assertIn("확인 안 됨", bad)
        self.assertNotIn("900조", bad)                                        # 지어낸 숫자를 크게 보여 주지 않아요
        self.assertNotIn('id="cardShare"', bad)                                # 확인 안 됨이면 순위 줄도 공유도 없어요
        self.assertNotIn('class="rl"', bad)
        self.assertIn("같은 명령을 다시 실행해 이 컴퓨터에서 새로 세어 올리면 다시 확인해요.", bad)   # '나'의 확인 안 됨: 다음에 할 일
        self.assertNotIn("같은 명령을 다시 실행해", r["badOther"])                                   # 남의 카드에는 없어요

    def test_height_follows_total(self):
        code = city_js("totalOf", "heightOf", "hash", "activeDays", "addPerson") + """
let people = [], view = 'buildings';
const scheduleDraw = () => {}, recentDays = () => 0, daysAgo = () => 0, drawNumbers = () => {};
const M = (total, ok = true) => ({ tools: { claude: { total, cacheRead: total * 0.9 } }, days: {}, ok });
for (const [login, total, ok] of [['a', 1.00e9, true], ['b', 1.01e9, true], ['c', 5e11, true], ['d', 2e6, true], ['z', 9e15, false]]) addPerson({ login, meter: M(total, ok), office: null });
const byH = [...people].sort((x, y) => y.height - x.height).map(p => p.login);
console.log(JSON.stringify({ byH, z: [people[4].height, people[4].ok], ab: people[1].height > people[0].height, floors: people.map(p => p.floors) }));
"""
        r = run_node(code)
        self.assertEqual(r["byH"][:4], ["c", "b", "a", "d"])   # 가장 높은 건물이 총 토큰 1등(반올림 없이 조금만 많아도 더 높아요)
        self.assertEqual(r["z"], [1, False])                    # 확인 안 됨은 가장 낮게
        self.assertTrue(r["ab"])
        self.assertEqual(r["floors"], [20, 20, 33, 7, 1])

    def test_join_panel_folds_details(self):
        code = city_js("T", "esc", "t", "cname", "flag", "JOIN_REF", "JOIN_SCRIPT", "JOIN_SOURCE", "joinCountry", "joinCmd", "joinOpts", "openJoin") + """
let lang = 'ko', COUNTRIES = new Set(['KR', 'JP']);
const document = { activeElement: null };
const els = {}, $ = s => els[s] || (els[s] = { innerHTML: '', hidden: true, textContent: '', contains: () => false, addEventListener() {}, focus() {} });
openJoin();
console.log(JSON.stringify({ html: els['#joinBox'].innerHTML, T: T.ko }));
"""
        r = run_node(code)
        shown, _, folded = r["html"].partition("<details>")
        ko = r["T"]
        # 나라 고르기·명령·복사·무엇이 올라가는지(공개 gist·수정 기록), 그리고 '먼저 세기만 하고 올리기 전에 물어요'는 보여요
        for s in (ko["joinWhat"], ko["joinFirst"], "joinCode", "joinCopy", "joinC", ko["joinCmd"]):
            self.assertIn(s, shown)
        self.assertLess(shown.index("joinCode"), shown.index(ko["joinFirst"]))   # 명령 상자 바로 아래
        # 명령과 복사가 맨 위(할 일), 나라 고르기(안 골라도 돼요)와 찾기 칸은 그 아래예요
        self.assertLess(shown.index('id="joinCopy"'), shown.index('id="joinQ"'))
        self.assertLess(shown.index('id="joinQ"'), shown.index('id="joinC"'))
        self.assertEqual(ko["joinOpt"], "(안 골라도 돼요 · 안 고르면 터미널에서 물어봐요)")
        self.assertIn(f'aria-label="{ko["joinSearch"]}"', shown)                   # 찾기 칸은 보이는 이름 대신 aria-label
        self.assertIn("공개 gist", ko["joinWhat"])
        self.assertIn("수정 기록", ko["joinWhat"])
        self.assertIn("로그인 없이", ko["joinFirst"])
        self.assertIn("한 번 더 물어봐요", ko["joinFirst"])
        self.assertEqual(ko["joinH"], "내 토큰 세어 보기")                             # 제목은 짧게, '터미널 한 줄'은 작은 부제
        self.assertIn(ko["joinSub"], shown)
        for s in [ko["joinCountryNote"], ko["joinNeed"], ko["joinAgain"]] + ko["joinSteps"]:   # 나라 안내·준비물·다시 올리기·단계는 '자세히'로
            self.assertNotIn(s, shown)
            self.assertIn(s, folded)

    def test_front_door(self):
        """방문자 첫 단추는 '내 토큰 세어 보기'(참가 창), 설치 링크는 위 막대에서 빼서 아래 안내 줄에. 아이디 찾기 칸은 위 막대에."""
        top = re.search(r'<header class="top" id="top">(.*?)</header>', CITY, re.S).group(1)
        self.assertRegex(top, r'<button type="button" class="chip cta visit-only" data-act="join" data-t="countMine">')
        self.assertIn('id="findQ"', top)
        self.assertNotIn("#설치", top)
        self.assertIn("const INSTALL_URL = 'https://github.com/Min-heee/agencity#설치';", CITY)
        self.assertEqual(len(re.findall(r'href="\$\{INSTALL_URL\}"', CITY)), 2)   # 아래 안내 줄과 순위표 아래
        self.assertIn("countMine: '내 토큰 세어 보기'", CITY)
        self.assertIn("countMine: 'Count my tokens'", CITY)

    def test_hint_keeps_install_link_when_few(self):
        """사람이 적어(3명 이하) 아래 안내 줄이 크게 바뀌어도 공개 도시에는 '도시 규칙 · 에이전시티 설치 ↗'가 그 줄 끝에 작게 남아요."""
        code = city_js("T", "esc", "t", "FEW", "VISION_URL", "INSTALL_URL", "canJoin", "joinBtn", "refreshChrome") + """
let lang = 'ko', ZONES = [{ c: 'KR' }], people = [], loaded = true, loadState = { failed: 0, cut: 0, error: false }, view = 'buildings', zone = 'ALL', meMissing = false;
const DEMO = false, LOCAL = false, els = {};
const $ = s => els[s] || (els[s] = { textContent: '', innerHTML: '', hidden: false, options: [1, 2], dataset: {}, cls: [],
  classList: { toggle(c, on) { this.on = this.on || new Set(); if (on) this.on.add(c); else this.on.delete(c); } } });
const ctryOptions = () => {}, topH = () => 64, document = { documentElement: { style: { setProperty() {} } } };
const run = n => { people = Array.from({ length: n }, (_, i) => ({ login: 'p' + i })); refreshChrome(); const h = $('#hint'); return [h.innerHTML, [...(h.classList.on || [])]]; };
console.log(JSON.stringify({ one: run(1), five: run(5) }));
"""
        r = run_node(code)
        for k in ("one", "five"):
            html, cls = r[k]
            self.assertIn('href="https://github.com/Min-heee/agencity#설치"', html, k)
            self.assertIn("에이전시티 설치 ↗", html)
            self.assertIn("도시 규칙", html)
        self.assertEqual(r["one"][1], ["big"])
        self.assertTrue(r["one"][0].startswith("아직 1명이에요 · "), r["one"][0])
        self.assertIn('data-act="join"', r["one"][0])

    def test_card_number_class_does_not_hit_hint(self):
        """카드의 한 숫자 상자(.cbig)는 아래 안내 줄(.hint.big)과 이름이 겹치지 않아요: 겹치면 안내 줄 배경이 밝아져 흰 글이 안 보였어요."""
        style = re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", CITY, re.S).group(1), flags=re.S)
        sels = [x.strip() for sel in re.findall(r"([^{}]+)\{", style) for x in sel.split(",")]
        big = [x for x in sels if re.search(r"\.big\b", x)]
        self.assertTrue(big)
        self.assertEqual([x for x in big if ".hint.big" not in x], [])   # .big은 아래 안내 줄에만 붙어요
        hint = re.search(r"\n\.hint\{([^}]*)\}", style).group(1)
        self.assertIn("background:rgba(10,14,20,.72)", hint)               # 어두운 바탕 위에
        self.assertNotIn("background", re.search(r"\n\.hint\.big\{([^}]*)\}", style).group(1))
        self.assertIn("color:#F3F5F8", re.search(r"\n\.hint\.big\{([^}]*)\}", style).group(1))   # 밝은 글
        self.assertIn('<div class="cbig${p.ok ? \'\' : \' bad\'}">', CITY)
        self.assertNotIn('class="big', CITY)

    def test_phone_card_keeps_building_below_top_bar(self):
        """휴대폰에서 카드를 열면 고른 건물을 위 막대(줄이 늘어 높아져도) 아래, 카드 위의 빈 곳으로 옮겨요."""
        code = city_js("freeY", "bringIntoView") + """
let pan = { x: 0, y: 0, k: 0.8 }, moved = false, view = 'buildings';
const svg = { clientWidth: 375, clientHeight: 812 }, narrow = () => true, topH = () => 150, applyView = () => {};
const at = p => [p.box.top * pan.k + pan.y, p.box.maxY * pan.k + pan.y];
const out = {};
const short = { box: { top: -100, maxY: 0, cx: 0 } }; bringIntoView(short); out.short = at(short);
pan = { x: 0, y: 0, k: 0.8 };
const tall = { box: { top: -600, maxY: 0, cx: 0 } }; bringIntoView(tall); out.tall = at(tall);
console.log(JSON.stringify(out));
"""
        r = run_node(code)
        top, bottom = r["short"]
        self.assertGreaterEqual(top, 150 + 28 - 0.01)          # 지붕(이름표 자리 포함)이 위 막대 아래
        self.assertLessEqual(bottom, 812 * 0.42 - 8 + 0.01)    # 카드(화면 아래 58%) 위
        self.assertAlmostEqual(r["tall"][0], 150 + 28, places=3)   # 큰 건물은 지붕을 위 막대 바로 아래에

    def test_guide_matches_page(self):
        """GUIDE 도시 절이 화면과 같은 말을 해요: 나라 순위 5명 규칙, 높이 눈금 양 끝, 참가 명령이 여는 순서."""
        with open(os.path.join(ROOT, "docs", "GUIDE.md"), encoding="utf-8") as f:
            guide = f.read()
        self.assertIn("순위표는 그 나라에 확인된 사람이 **5명부터** 그 나라 안 1위부터 매기고(작게 전체 순위), 그 전에는 세계 순위를 그대로 두고(순위 칸마다 작게 ‘세계 순위’) ‘나라 순위는 5명부터’를 보여요.", guide)
        self.assertIn("rankWorld: '세계 순위'", CITY)                                  # GUIDE의 ‘세계 순위’가 화면 글과 같아요
        self.assertIn("(바닥이 화면에 조금만 걸친 구역의 이름판과 놓을 빈자리가 없는 이름판은 숨겨요. 고른 나라 판은 바닥이 조금만 보여도 남겨요. 다른 나라는 **[나라 ▾]**로 가요)", guide)
        self.assertNotIn("순위표는 그 나라 안에서 1위부터 다시 매겨요", guide)
        self.assertNotIn("총 토큰이 많을수록 늘 더 높아요", guide)
        self.assertIn("약 16만 토큰 이하는 모두 1층, 10조 이상은 모두 40층", guide)
        self.assertNotIn("신청 화면이 맨 앞에 와요", guide)
        self.assertIn("**도시 참가 신청** 화면을 열고, 그 직후 내 도시 주소(`?who=<아이디>#me`)도 열어 줘요", guide)
        self.assertIn("**에이전시티 설치 ↗**는 아래 안내 줄 끝(사람이 적을 때도)과 순위표 아래", guide)


# 결과 카드 그림 시험의 바탕: 가짜 canvas(그린 글·그림·글꼴·정렬을 적어 둬요). 글 너비는 한글·깃발은 글자 크기만큼, 나머지는 0.6배로 재요.
ART_SETUP = RANK_SETUP + city_js("OLD_DAYS", "TOOLS", "cacheOf", "hash", "dayKey", "PUBLIC_URL", "shareURL", "ART", "SITE", "FONT_D", "FONT_B", "FONT_M",
                                 "cardArt", "shareText", "fitText", "shade", "drawArt") + """
const now = () => new Date('2026-10-21T10:00:00Z');   // 어느 시간대에서 돌려도 10월 21일(UTC−10 ~ UTC+13)
const M = (total, ok = true) => ({ tools: { claude: { total, cacheRead: total * 0.86 } }, days: { '2026-10-01': total * 0.6, '2026-10-02': total * 0.4 }, ok,
  updatedAt: '2026-10-20T12:00:00Z', tz: 'Asia/Seoul' });   // 서울 10월 20일 밤 9시에 올렸어요
const Q = (login, c, total, ok = true) => ({ login, c, total, ok, height: 20, stale: 0, meter: M(total, ok) });
const wide = ch => ch.codePointAt(0) > 0x2e80;
const widthOf = (s, font) => { const sz = parseFloat(/([\\d.]+)px/.exec(font)[1]); return [...String(s)].reduce((w, ch) => w + (wide(ch) ? sz : sz * 0.6), 0); };
function fakeCtx() {
  const st = { font: '10px x', textAlign: 'start', fillStyle: '', calls: [] };
  const ctx = new Proxy(st, {
    get(o, k) {
      if (k in o) return o[k];
      if (k === 'measureText') return s => ({ width: widthOf(s, o.font) });
      if (k === 'createLinearGradient') return () => ({ addColorStop() {} });
      if (k === 'fillText') return (s, x, y) => o.calls.push(['fillText', s, x, y, o.font, o.textAlign, o.fillStyle]);
      if (k === 'drawImage') return (im, ...xy) => o.calls.push(['drawImage', im && im.id, ...xy]);
      return () => {};
    },
    set(o, k, v) { o[k] = v; return true; }
  });
  return { ctx, st };
}
const texts = st => st.calls.filter(c => c[0] === 'fillText').map(c => c[1]);
// 넘치는 글: 왼쪽 정렬은 오른쪽 84px 안, 오른쪽 정렬은 왼쪽 84px 안, 가운데(첫 글자)는 아바타 안
const spills = st => st.calls.filter(c => c[0] === 'fillText').filter(([, s, x, y, font, align]) => {
  const w = widthOf(s, font);
  return align === 'right' ? x - w < 84 - 0.5 : align === 'center' ? Math.abs(x - 164) + w / 2 > 80 : x < 84 || x + w > 1080 - 84 + 0.5;
}).map(c => c[1]);
"""


@unittest.skipUnless(shutil.which("node"), "node가 없어요(도시 화면 시험은 node로 돌려요)")
class CityCardArt(unittest.TestCase):
    """결과 카드 그림(5-3 ②): 그릴 글·순위 줄·자기 신고 줄, 아바타를 못 받으면 첫 글자, 넘치지 않기, 폰 공유·내려받기."""

    def test_art_lines_and_drawing(self):
        code = "(() => {\n" + ART_SETUP + """
const out = {};
people = [Q('kr-a', 'KR', 4e8), Q('kr-b', 'KR', 3.4e8), Q('no-a', '', 6e7), Q('bad', 'KR', 9e14, false)];
setCitizens(people);
rerank();
const a = cardArt(people[1]);
out.art = a;
out.bad = [cardArt(people[3]), shareText(people[3])];
let f = fakeCtx(); drawArt(f.ctx, a, null);
out.letter = [texts(f.st), spills(f.st), f.st.calls.some(c => c[0] === 'drawImage')];
f = fakeCtx(); drawArt(f.ctx, a, { id: 'avatar' });
out.img = [texts(f.st), f.st.calls.filter(c => c[0] === 'drawImage')];
f = fakeCtx(); drawArt(f.ctx, cardArt(people[2]), null);
out.noCountry = [f.st.calls.filter(c => c[1] === 'no-a').map(c => c[3]), texts(f.st).filter(s => s.includes('🌐') || s.includes('나라 안 고름'))];
// 올린 때를 모르면(없거나 미래) 만든 날로 적어요('기준'이라고 하지 않아요)
people[2].meter.updatedAt = ''; out.made = cardArt(people[2]).date;
people[2].meter.updatedAt = '2027-01-01T00:00:00Z'; out.future = cardArt(people[2]).date;
// 20명부터: 세계 등수·상위 %와 나라 순위가 굵은 줄. 아주 긴 아이디와 영어도 넘치지 않아요.
people = [];
for (let i = 0; i < 20; i++) people.push(Q(i ? `p${i}` : 'a'.repeat(39), i < 6 ? 'KR' : 'US', (20 - i) * 1e9));
rerank();
out.twenty = cardArt(people[0]);
lang = 'en';
const en = cardArt(people[0]);
f = fakeCtx(); drawArt(f.ctx, en, null);
out.en = [en, texts(f.st), spills(f.st), shareText(people[0])];
console.log(JSON.stringify(out));
})();
"""
        r = run_node(code)
        a = r["art"]
        self.assertEqual({k: a[k] for k in ("title", "date", "login", "letter", "place", "label", "total", "cache", "head", "tail", "self", "site")}, {
            "title": "에이전시티 도시", "date": "2026년 10월 20일에 올린 숫자", "login": "kr-b", "letter": "K", "place": "🇰🇷 대한민국",
            "label": "총 토큰", "total": "3.4억", "cache": "그중 캐시 읽기 86%",
            "head": ["2번째 시민", "가장 많이 쓴 날 2억 토큰", "활동한 날 2일"], "tail": "세계 2등 · 3명 중",   # 규칙 안내('나라 순위는 5명부터')는 빼요
            "self": "스스로 올린 숫자(자기 신고) · 각자 컴퓨터에 남은 기록 기준", "site": "min-heee.github.io/agencity"})
        self.assertEqual(r["bad"], [None, ""])                                   # 확인 안 됨이면 그림도 공유 글도 없어요
        drawn, spilled, has_img = r["letter"]
        for s in [a[k] for k in ("title", "date", "login", "place", "label", "total", "cache", "tail", "self", "site")] + a["head"]:
            self.assertIn(s, drawn)
        self.assertFalse([s for s in drawn if "5명부터" in s])                    # 그림에 규칙 안내가 없어요(화면 카드에만)
        self.assertIn("K", drawn)                                                # 아바타가 없으면 첫 글자
        self.assertFalse(has_img)
        self.assertEqual(spilled, [])
        drawn, imgs = r["img"]
        self.assertNotIn("K", drawn)                                             # 아바타를 받았으면 그 그림을 그려요
        self.assertEqual(imgs, [["drawImage", "avatar", 84, 170, 160, 160]])
        self.assertEqual(r["noCountry"], [[276], []])                            # 나라를 안 골랐으면 나라 줄 없이 아이디를 가운데에
        self.assertEqual(r["made"], "만든 날 2026년 10월 21일")
        self.assertEqual(r["future"], "만든 날 2026년 10월 21일")
        self.assertEqual(r["twenty"]["head"], ["세계 1등 · 20명 중 · 상위 5%", "대한민국 1등 · 6명 중"])
        self.assertEqual(r["twenty"]["tail"], "")
        en, drawn, spilled, share = r["en"]
        self.assertEqual(en["head"], ["#1 of 20 worldwide · top 5%", "#1 of 6 in South Korea"])
        self.assertEqual(en["self"], "Self-reported numbers · based on the logs left on each person’s computer")
        self.assertEqual(en["date"], "Posted October 20, 2026")
        self.assertEqual(spilled, [])
        self.assertTrue(any(s.endswith("…") or s == "a" * 39 for s in drawn if s.startswith("aaaa")))
        self.assertEqual(share, "My building is up in Agencity City · 20B total tokens · #1 of 20 worldwide · top 5% · #1 of 6 in South Korea"
                                " · Count yours → https://min-heee.github.io/agencity/?who=" + "a" * 39 + "&lang=en")

    def test_avatar_png_and_share(self):
        code = "(async () => {\n" + ART_SETUP + city_js("AVATAR_URL", "loadAvatar", "artFonts", "makePNG", "artJob", "prepArt", "deliver", "saveCard") + """
const out = {};
// 아바타: crossOrigin='anonymous'인 새 Image. 오류·빈 그림·시간 초과면 null
let mode = 'ok';
const made = [];
class Image {
  constructor() { made.push(this); this.naturalWidth = 0; }
  set src(v) { this._s = v; if (mode === 'ok') setTimeout(() => { this.naturalWidth = 320; this.onload(); }, 1); else if (mode === 'err') setTimeout(() => this.onerror(), 1); else if (mode === 'empty') setTimeout(() => this.onload(), 1); }
  get src() { return this._s; }
}
const got = await loadAvatar('Ann-Lee');
out.avatar = [got === made[0], made[0].crossOrigin, made[0].referrerPolicy, made[0].src];
mode = 'err'; out.err = await loadAvatar('x');
mode = 'empty'; out.empty = await loadAvatar('x');
mode = 'hang'; out.hang = await loadAvatar('x', 20);
// PNG: 아바타 때문에 canvas가 막히면 새 canvas에 첫 글자로 다시 그려요. 예시 사람은 아바타를 받지 않아요.
let taint = true;
const canvases = [], avatars = [];
const document = { fonts: { load: async () => [] }, createElement: tag => {
  const c = { width: 0, height: 0, getContext() { this.f = fakeCtx(); return this.f.ctx; },
    toBlob(cb, type) { if (taint && this.f.st.calls.some(x => x[0] === 'drawImage')) throw new Error('SecurityError'); setTimeout(() => cb({ type, size: this.width * this.height }), 1); } };
  canvases.push(c); return c; } };
people = [Q('kr-a', 'KR', 4e8), Q('kr-b', 'KR', 3.4e8)];
setCitizens(people); rerank();
const a = cardArt(people[1]);
loadAvatar = async login => { avatars.push(login); return { id: 'av' }; };   // function 선언이라 바꿔 끼울 수 있어요(makePNG가 부르는 것)
let b = await makePNG(a, false);
out.taint = [b, canvases.length, canvases.map(c => [c.width, c.height, c.f.st.calls.some(x => x[0] === 'drawImage'), texts(c.f.st).includes('K')])];
taint = false; canvases.length = 0;
b = await makePNG(a, false);
out.clean = [b, canvases.length, texts(canvases[0].f.st).includes('K')];
canvases.length = 0;
await makePNG(a, true);
out.demo = [avatars.slice(), texts(canvases[0].f.st).includes('K')];
// 폰(손가락)에서 파일 공유가 되면 공유 창, 아니면 내려받기. 취소면 아무것도 안 해요.
let coarse = true, can = true, shareRes = 'ok';
const shares = [], downloads = [];
const matchMedia = q => ({ matches: q === '(pointer: coarse)' && coarse });
const navigator = { canShare: d => can && Array.isArray(d.files) && d.files.every(f => f.type === 'image/png'),
  share: d => { shares.push(d.files.map(f => f.name)); return shareRes === 'ok' ? Promise.resolve() : Promise.reject(Object.assign(new Error('no'), { name: shareRes })); } };
class File { constructor(parts, name, o) { this.name = name; this.type = o.type; } }
function download(blob, name) { downloads.push(name); }
const blob = { type: 'image/png' };
const run = async () => { shares.length = 0; downloads.length = 0; const r = await deliver(blob, 'agencity-kr-b.png'); return [r, shares.length, downloads.length]; };
out.deliver = {};
out.deliver.phone = await run();
shareRes = 'AbortError'; out.deliver.cancel = await run();
shareRes = 'NotAllowedError'; out.deliver.blocked = await run();
shareRes = 'ok'; can = false; out.deliver.noFiles = await run();
can = true; coarse = false; out.deliver.desktop = await run();
// 카드 저장: 미리 만든 그림이 있으면 누른 그 순간(기다리기 전)에 공유 창을 불러요. 없으면 '만드는 중'으로 기다려요.
coarse = true; shares.length = 0;
const els = {}, $ = s => els[s] || (els[s] = { textContent: '' });
const btn = { disabled: false, textContent: '카드 저장', isConnected: true };
const job = prepArt(people[1]);
out.same = prepArt(people[1]) === job;
await job.promise;
const pr = saveCard(people[1], btn);
out.sync = shares.length;
await pr;
lang = 'en';
const pr2 = saveCard(people[1], btn);
out.waiting = [btn.disabled, btn.textContent, shares.length];
await pr2;
out.after = [btn.disabled, btn.textContent, shares.length];
btn.isConnected = false;
console.log(JSON.stringify(out));
})();
"""
        r = run_node(code)
        self.assertEqual(r["avatar"], [True, "anonymous", "no-referrer", "https://avatars.githubusercontent.com/Ann-Lee?s=320"])
        self.assertIsNone(r["err"])
        self.assertIsNone(r["empty"])
        self.assertIsNone(r["hang"])
        blob, n, cvs = r["taint"]
        self.assertEqual(blob, {"type": "image/png", "size": 1080 * 1080})
        self.assertEqual(n, 2)
        self.assertEqual(cvs, [[1080, 1080, True, False], [1080, 1080, False, True]])   # 막히면 첫 글자로 다시
        self.assertEqual(r["clean"], [{"type": "image/png", "size": 1080 * 1080}, 1, False])
        self.assertEqual(r["demo"], [["kr-b", "kr-b"], True])                           # 예시 사람(true)은 아바타를 받지 않아요
        self.assertEqual(r["deliver"], {"phone": ["shared", 1, 0], "cancel": ["cancel", 1, 0], "blocked": ["saved", 1, 1],
                                        "noFiles": ["saved", 0, 1], "desktop": ["saved", 0, 1]})
        self.assertTrue(r["same"])
        self.assertEqual(r["sync"], 1)                                                  # 기다리지 않고 바로 공유 창
        self.assertEqual(r["waiting"], [True, "Making card…", 1])
        self.assertEqual(r["after"], [False, "Save card", 2])

    def test_card_art_rules_in_page(self):
        """그림은 1080×1080 PNG, 아바타는 crossOrigin, 화면의 img(crossOrigin 없음)는 쓰지 않아요. 확인 안 됨·남의 카드엔 단추가 없어요."""
        self.assertIn("const ART = 1080;", CITY)
        self.assertIn("cv.width = ART; cv.height = ART;", CITY)
        self.assertIn("cv.toBlob(b => res(b || null), 'image/png');", CITY)
        self.assertIn("im.crossOrigin = 'anonymous';", CITY)
        self.assertIn("const mine = me && !!rl;", CITY)
        self.assertIn("navigator.canShare({ files: [file] })", CITY)
        for k in ("saveCard: '카드 저장'", "saveCard: 'Save card'"):
            self.assertIn(k, CITY)


# 헤드리스 셸(Playwright·Puppeteer가 받아둬요)을 먼저 써요. 앱 Chrome은 켤 때마다 Dock에 빈 아이콘이 잠깐 떠요
SHELLS = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"))
                + glob.glob(os.path.expanduser("~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell")), reverse=True)
CHROME = next((c for c in (shutil.which("chrome-headless-shell"), *SHELLS, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           shutil.which("google-chrome"), shutil.which("chromium")) if c and os.path.exists(c)), None)

# 진짜 브라우저로 화면 자리를 재는 node 운전기. 헤드리스 셸을 --remote-debugging-pipe로 켜서(크롬은 포트를 열지 않아요)
# 경우마다 창 크기(폰 390·데스크톱 1280)를 정하고 city.html?demo=1을 열어, 이름판·위 막대·아래 안내 줄·확대 단추·순위표 사각형과
# 칸 바탕색을 재요. '나'(#me로 기억한 아이디)는 같은 주소의 빈 페이지에서 localStorage에 미리 넣어 둬요(휴대폰은 내 나라 구역부터 열어요).
# steps: 재기 전에 할 일(끌기 drag·휠 wheel·막대 띠 누르기 tapband·페이지 안 js). 이름판마다 그 구역 바닥이 화면에 보이는 몫(seen)도 재요.
SCREEN_DRIVER = r"""
const { spawn } = require('child_process');
const [CHROME, BASE, UDD, HOST, CASES] = __ARGS__;
const ch = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--use-mock-keychain', '--password-store=basic', '--user-data-dir=' + UDD,
  '--no-proxy-server', `--host-resolver-rules=MAP ${HOST} 127.0.0.1, MAP * ~NOTFOUND`, '--disable-background-networking', '--disable-component-update',
  '--disable-sync', '--disable-default-apps', '--hide-scrollbars', '--remote-debugging-pipe', 'about:blank'], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
let buf = Buffer.alloc(0), id = 0;
const pend = new Map();
ch.stdio[4].on('data', d => {
  buf = Buffer.concat([buf, d]);
  for (let i; (i = buf.indexOf(0)) >= 0;) {
    const m = JSON.parse(buf.subarray(0, i).toString('utf8')); buf = buf.subarray(i + 1);
    if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); if (m.error) p.rej(new Error(p.method + ' ' + JSON.stringify(m.error))); else p.res(m.result); }
  }
});
const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
  const m = { id: ++id, method, params }; if (sessionId) m.sessionId = sessionId;
  pend.set(m.id, { res, rej, method }); ch.stdio[3].write(JSON.stringify(m) + '\0');
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
const MEASURE = `(async () => {
  const d = document, w = window, sleep = ms => new Promise(r => setTimeout(r, ms));
  const R = n => { const r = n.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(v => Math.round(v * 10) / 10); };
  const vis = s => { const n = d.querySelector(s); return n && !n.hidden && n.getClientRects().length ? R(n) : null; };
  const tb = d.querySelector('#top').getBoundingClientRect().bottom, plates = [...d.querySelectorAll('#world .zone .zone-plate')];
  // 구역 바닥이 화면(위 막대 아래)에 보이는 몫: 바닥 다각형 안의 점 중 화면 안에 든 비율
  const seen = pl => {
    if (!pl) return 0;
    const m = pl.getScreenCTM(), P = [...pl.points].map(p => [p.x * m.a + p.y * m.c + m.e, p.x * m.b + p.y * m.d + m.f]);
    const inside = (x, y) => { let c = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const a = P[i], b = P[j]; if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) c = !c; } return c; };
    const xs = P.map(p => p[0]), ys = P.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    let all = 0, on = 0;
    for (let i = 0; i < 30; i++) for (let j = 0; j < 30; j++) { const x = x0 + (i + .5) * (x1 - x0) / 30, y = y0 + (j + .5) * (y1 - y0) / 30; if (!inside(x, y)) continue; all++; if (x > 0 && x < w.innerWidth && y > tb && y < w.innerHeight) on++; }
    return all ? Math.round(on / all * 100) / 100 : 0;
  };
  const ae = d.activeElement, sel = d.querySelector('#world .bld.sel');
  const out = { zone: d.querySelector('#ctry').value, W: w.innerWidth, H: w.innerHeight,
    tags: [...d.querySelectorAll('#tags .zone-tag')].map((g, i) => ({ zone: g.dataset.zone, shown: g.style.display !== 'none' && !!g.getClientRects().length,
      tab: g.getAttribute('tabindex'), aria: g.getAttribute('aria-hidden'), r: R(g.querySelector('rect')), seen: seen(plates[i]) })),
    top: vis('#top'), hint: vis('#hint'), zoom: vis('#zoom'), card: vis('#card'), numbers: vis('#numbers'), sel: sel ? R(sel) : null,
    active: ae && ae.closest && ae.closest('.zone-tag') ? 'zone:' + ae.closest('.zone-tag').dataset.zone : ae ? ae.tagName : '',
    cssTop: w.getComputedStyle(d.documentElement).getPropertyValue('--top').trim(), topH: d.querySelector('#top').offsetHeight,
    opened: w.__opened === undefined ? null : w.__opened, taps: w.__taps || 0, selText: String(w.getSelection() || ''),
    bg: Object.fromEntries(['#top', '#count', '#viewGroup', '#langGroup', '#ctry', '#findQ'].map(s => [s, w.getComputedStyle(d.querySelector(s)).backgroundColor])) };
  if (out.numbers) {
    const nb = d.querySelector('#numbers');
    nb.scrollTop = SCROLL; await sleep(250);
    out.scrollTop = nb.scrollTop;
    // 위 막대 자리의 점마다 맨 위에 있는 것: 순위표 안이면 막대 사이로 순위표가 보이는 거예요. 지도(#stage) 안이면 띠를 눌러도 숨은 건물에 닿아요
    const leak = [], stage = [];
    for (let x = 1; x < out.W; x += 6) for (let y = 1; y < tb; y += 4) { const e = d.elementFromPoint(x, y); if (e && e.closest('#numbers')) leak.push([x, y]); if (e && e.closest('#stage')) stage.push([x, y]); }
    out.leak = leak.slice(0, 5); out.leakN = leak.length; out.stage = stage.slice(0, 5); out.stageN = stage.length;
    out.rk = [...d.querySelectorAll('#numbers tbody tr:not(.sep):not(.gap) td.c-rk')].map(td => {
      const s = td.querySelector('.rk-all'); return [td.querySelector('.rk').textContent, s ? s.textContent : '', s ? s.getBoundingClientRect().height : 0]; });
  }
  return out;
})()`;
const LOADED = `(() => { const c = document.querySelector('#count'), t = c ? c.textContent : '';
  return /\\d/.test(t) && !/불러오는|oading/.test(t) && document.querySelectorAll('#tags .zone-tag').length > 0; })()`;
(async () => {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  const S = (m, p) => send(m, p, sessionId);
  await S('Page.enable'); await S('Runtime.enable');
  const ev = async e => { const r = await S('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 600)); return r.result.value; };
  const until = async (e, ms = 20000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await ev(e)) return true; } catch (x) {} await sleep(100); } throw new Error('timeout: ' + e.slice(0, 80)); };
  const out = [];
  for (const c of CASES) {
    try {
      await S('Emulation.setDeviceMetricsOverride', { width: c.w, height: c.h, deviceScaleFactor: 1, mobile: c.w < 600 });
      await S('Page.navigate', { url: BASE + 'blank.html' });
      await until(`location.pathname === '/blank.html' && document.readyState === 'complete'`);
      await ev(`(() => { try { ${c.me ? `localStorage.setItem('agencity.me', ${JSON.stringify(c.me)})` : `localStorage.removeItem('agencity.me')`} } catch (e) {} return 1; })()`);
      await S('Page.navigate', { url: BASE + 'city.html?' + c.q });
      await until(`location.pathname === '/city.html' && ` + LOADED);
      await sleep(800);   // 맞춤과 이름판 자리(다음 그림 때)가 끝나게
      for (const [k, ...a] of c.steps || []) {
        const mouse = (type, x, y) => S('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1 });
        if (k === 'drag' || k === 'dragfrom') {
          // dragfrom: 선택자로 찾은 보이는 첫 요소 가운데에서 누른 채 끌어요
          const [x, y, dx, dy] = k === 'drag' ? a : (await ev(`(() => { const n = [...document.querySelectorAll(${JSON.stringify(a[0])})].find(n => n.getClientRects().length);
            const r = n.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()`)).concat(a.slice(1));
          await S('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y }); await mouse('mousePressed', x, y);
          for (let i = 1; i <= 8; i++) await mouse('mouseMoved', x + dx * i / 8, y + dy * i / 8);
          await mouse('mouseReleased', x + dx, y + dy); }
        else if (k === 'wheel') { const [x, y, dy, n] = a; for (let i = 0; i < n; i++) { await S('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY: dy }); await sleep(40); } }
        else if (k === 'tapband') {
          // 숫자 보기 위 막대 띠의 빈 곳(단추·고르기 칸이 아닌 곳)을 여러 번 눌러요. 카드가 열린 횟수를 세요.
          await ev(`(() => { window.__opened = 0; new MutationObserver(() => { if (!document.querySelector('#card').hidden) window.__opened++; })
            .observe(document.querySelector('#card'), { attributes: true, attributeFilter: ['hidden'] }); return 1; })()`);
          const pts = await ev(`(() => { const t = document.querySelector('#top'), b = t.getBoundingClientRect().bottom, out = [];
            for (let y = 3; y < b - 1; y += 7) for (let x = 3; x < innerWidth; x += 9) { const e = document.elementFromPoint(x, y); if (e && (e === t || e.closest('#stage'))) out.push([x, y]); }
            return out; })()`);
          const pick = pts.filter((p, i) => i % Math.max(1, Math.floor(pts.length / 40)) === 0);
          for (const [x, y] of pick) { await mouse('mousePressed', x, y); await mouse('mouseReleased', x, y); await sleep(30); }
          await ev(`window.__taps = ${pick.length}`);
        }
        else if (k === 'js') await ev(a[0]);
        await sleep(400);
      }
      out.push(Object.assign({ name: c.name }, await ev(MEASURE.replace('SCROLL', String(c.scroll || 0)))));
    } catch (e) { out.push({ name: c.name, error: String(e && e.stack || e) }); }
  }
  console.log(JSON.stringify(out));
})().catch(e => console.log(JSON.stringify([{ name: 'driver', error: String(e && e.stack || e) }]))).finally(() => { ch.kill('SIGTERM'); setTimeout(() => process.exit(0), 300); });
"""


def css_alpha(color):
    """getComputedStyle 바탕색의 알파(rgb(...)는 1)."""
    m = re.match(r"rgba?\(([^)]*)\)", color.strip())
    parts = [x.strip() for x in m.group(1).replace("/", ",").split(",")]
    return float(parts[3]) if len(parts) > 3 else 1.0


def overlaps(a, b, eps=0.5):
    return a[0] < b[2] - eps and b[0] < a[2] - eps and a[1] < b[3] - eps and b[1] < a[3] - eps


@unittest.skipUnless(CHROME, "헤드리스 Chrome이 없어요(화면 자리는 진짜 브라우저로 재요)")
class CityScreen(unittest.TestCase):
    """진짜 브라우저로 잰 화면 자리: 나라 이름판이 서로·위 막대·아래 안내 줄·확대 단추·카드와 겹치지 않고(폰 #me 내 나라·나라 고름·모든 나라, 1280),
    바닥이 보이는 구역의 판은 남고(끌기·줄이기 뒤에도), 초점이 있는 판은 숨지 않고, 숫자 보기에서 나라를 바꾸면 지도도 맞춰요.
    위 막대 칸은 불투명하고, 숫자 보기 순위표는 막대 아래에서만 스크롤되고, 띠를 눌러도 뒤의 지도에 닿지 않고, --top은 막대 높이를 따라가요.
    5명 전 나라 순위 칸에 '세계 순위'가 보여요.
    예시 도시(examples/city/demo.json)만 써요. 서버는 127.0.0.1의 9740번대 빈 포트, 브라우저는 그 밖의 이름을 모두 막아요(글꼴·아바타도 바깥에 닿지 않아요)."""

    CASES = [
        {"name": "me390", "q": "demo=1&lang=ko", "me": "demo-hana", "w": 390, "h": 844},        # #me로 기억한 '나'(대한민국): 휴대폰은 내 나라 구역부터
        {"name": "us390", "q": "demo=1&lang=ko&country=US", "w": 390, "h": 844},              # 나라 고름
        {"name": "all390", "q": "demo=1&lang=en&country=all", "w": 390, "h": 844},            # 모든 나라(가장 큰 건물부터)
        {"name": "all1280", "q": "demo=1&lang=ko", "w": 1280, "h": 860},                      # 첫 화면: 판이 모두 보여요
        {"name": "kr1280", "q": "demo=1&lang=en&country=KR", "w": 1280, "h": 860},
        {"name": "num390", "q": "demo=1&lang=ko&view=numbers", "w": 390, "h": 844, "scroll": 260},
        {"name": "num1280", "q": "demo=1&lang=ko&view=numbers", "w": 1280, "h": 560, "scroll": 260},
        {"name": "jp390", "q": "demo=1&lang=ko&view=numbers&country=JP", "w": 390, "h": 844},   # 일본: 확인된 사람 1명(5명 전)
        {"name": "jp1280en", "q": "demo=1&lang=en&view=numbers&country=JP", "w": 1280, "h": 860},
        # 대한민국을 고르고 지도를 아래로 끌면 앞 꼭짓점(판 제자리)은 화면 밖이지만 바닥은 보여요: 판은 화면 안 빈자리로 옮겨 남아요
        {"name": "drag1280", "q": "demo=1&lang=en&country=KR", "w": 1280, "h": 860, "steps": [["drag", 640, 300, 0, 330]]},
        {"name": "drag390", "q": "demo=1&lang=ko&country=all", "w": 390, "h": 844, "steps": [["drag", 195, 500, 150, 60]]},
        {"name": "zout390", "q": "demo=1&lang=ko&country=all", "w": 390, "h": 844, "steps": [["js", "document.querySelector('#zout').click()"]] * 6},
        # 키보드 초점이 있는 대한민국 판: 휠로 키워 구역이 화면 밖으로 가도 판과 초점이 남아요
        {"name": "focus1280", "q": "demo=1&lang=ko&country=KR", "w": 1280, "h": 860,
         "steps": [["js", "document.querySelector('#tags .zone-tag[data-zone=\"KR\"]').focus()"], ["wheel", 60, 120, -240, 6]]},
        # 일본 빌딩 → 숫자 보기에서 대한민국으로 바꾸고 → 빌딩으로 돌아오면 지도가 대한민국에 맞춰져 있어요
        {"name": "refit390", "q": "demo=1&lang=ko&country=JP", "w": 390, "h": 844,
         "steps": [["js", "document.querySelector('#viewGroup button[data-view=\"numbers\"]').click()"],
                   ["js", "(s => { s.value = 'KR'; s.dispatchEvent(new Event('change')); })(document.querySelector('#ctry'))"],
                   ["js", "document.querySelector('#viewGroup button[data-view=\"buildings\"]').click()"]]},
        # 글꼴이 늦게 바뀌어 위 막대가 높아진 셈(refreshChrome·resize 없이): --top과 순위표 시작이 따라와요
        {"name": "font390", "q": "demo=1&lang=en&view=numbers", "w": 390, "h": 844,
         "steps": [["js", "document.head.appendChild(Object.assign(document.createElement('style'), { textContent: '.plate{font-size:30px}' }))"]]},
        # 숫자 보기 위 막대 띠의 빈 곳을 여러 번 눌러요: 뒤에 숨은 지도의 건물 카드가 열리거나 나라가 바뀌면 안 돼요
        {"name": "band390", "q": "demo=1&lang=ko&view=numbers&country=all", "w": 390, "h": 844, "steps": [["tapband"]]},
        {"name": "band1280", "q": "demo=1&lang=ko&view=numbers&country=KR", "w": 1280, "h": 860, "steps": [["tapband"]]},
        # 폰에서 '나'의 카드를 연 때: 이름판이 카드와 카드를 연 건물을 가리지 않아요
        {"name": "card390", "q": "demo=1&lang=ko", "me": "demo-hana", "w": 390, "h": 844,
         "steps": [["js", "(b => { b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); })(document.querySelector('#world .bld[data-login=\"demo-hana\"]'))"]]},
        # 숫자 보기에서 마우스로 끌어 고를 때: 띠의 빈 곳에서 끌어도, 순위표 제목에서 막대 쪽으로 끌어 올려도 막대 글자와 숨은 지도의 이름판 글자가 골라지지 않아요
        {"name": "selband1280", "q": "demo=1&lang=ko&view=numbers&country=KR", "w": 1280, "h": 860, "steps": [["drag", 400, 60, 700, 0]]},
        {"name": "selbanddown1280", "q": "demo=1&lang=ko&view=numbers&country=KR", "w": 1280, "h": 860, "steps": [["drag", 400, 60, 120, 72]]},
        {"name": "selup1280", "q": "demo=1&lang=ko&view=numbers&country=KR", "w": 1280, "h": 860, "steps": [["dragfrom", "#numH", -150, -90]]},
    ]

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node가 없어요(브라우저는 node로 움직여요)")
        files = {"/city.html": os.path.join(ROOT, "city.html"), "/city/countries.json": os.path.join(ROOT, "city", "countries.json"),
                 "/examples/city/demo.json": os.path.join(ROOT, "examples", "city", "demo.json")}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/blank.html":
                    body, ctype = b"<!doctype html><title>blank</title>", "text/html; charset=utf-8"
                elif path in files:
                    with open(files[path], "rb") as f:
                        body = f.read()
                    ctype = "text/html; charset=utf-8" if path.endswith(".html") else "application/json"
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        srv = None
        for port in range(9740, 9750):
            try:
                srv = _OneServer(("127.0.0.1", port), H)
                break
            except OSError:
                continue
        if not srv:
            raise unittest.SkipTest("9740번대에 빈 포트가 없어요")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        # 127.0.0.1이 아닌 이름으로 열어야 공개 도시(방문자) 모습이에요. 그 이름만 이 서버로, 다른 이름은 모두 못 찾게 해요.
        host = "city-screen.test"
        try:
            with tempfile.TemporaryDirectory(dir=TMP_BASE) as d:
                args = json.dumps([CHROME, f"http://{host}:{srv.server_port}/", os.path.join(d, "c"), host, cls.CASES])
                r = subprocess.run([shutil.which("node"), "-e", SCREEN_DRIVER.replace("__ARGS__", args)], capture_output=True, text=True, timeout=240)
        finally:
            srv.shutdown()
            srv.server_close()
        lines = r.stdout.strip().splitlines()
        if not lines:
            raise AssertionError("운전기가 결과를 적지 못했어요: " + r.stderr[-1500:])
        cls.res = {x["name"]: x for x in json.loads(lines[-1])}
        if "driver" in cls.res:
            raise AssertionError(cls.res["driver"]["error"])

    def case(self, name):
        x = self.res[name]
        self.assertNotIn("error", x, x.get("error"))
        return x

    def test_zone_tags_do_not_overlap(self):
        """이름판끼리, 그리고 위 막대·아래 안내 줄·확대 단추와 겹치지 않아요. 화면 밖 판은 숨기고 초점·화면 읽기도 닿지 않아요."""
        for name in ("me390", "us390", "all390", "all1280", "kr1280", "drag1280", "drag390", "zout390", "refit390", "card390"):
            with self.subTest(name):
                x = self.case(name)
                shown = [t for t in x["tags"] if t["shown"]]
                self.assertTrue(shown, x)
                for t in x["tags"]:
                    self.assertEqual((t["tab"], t["aria"]), ("0", None) if t["shown"] else ("-1", "true"), t)
                for i, a in enumerate(shown):
                    for b in shown[i + 1:]:
                        self.assertFalse(overlaps(a["r"], b["r"]), (a, b))
                    for k in ("top", "hint", "zoom"):
                        if x[k]:
                            self.assertFalse(overlaps(a["r"], x[k]), (k, a, x[k]))
                    self.assertGreaterEqual(a["r"][0], 0, a)
                    self.assertLessEqual(a["r"][2], x["W"], a)
                    self.assertGreaterEqual(a["r"][1], x["top"][3], a)       # 위 막대 아래
                    self.assertLessEqual(a["r"][3], x["H"], a)
                    for k in ("card", "sel"):                                   # 열린 카드와 카드를 연 건물도 가리지 않아요
                        if x[k]:
                            self.assertFalse(overlaps(a["r"], x[k]), (k, a, x[k]))
                if x["zone"] != "ALL":
                    self.assertIn(x["zone"], [t["zone"] for t in shown])     # 고른(내) 나라 판은 보여요
        self.assertEqual(self.case("me390")["zone"], "KR")                    # #me로 기억한 '나'의 나라 구역부터 열었어요
        self.assertEqual(self.case("us390")["zone"], "US")
        first = self.case("all1280")
        self.assertEqual([t["zone"] for t in first["tags"] if not t["shown"]], [])   # 1280 모든 나라 첫 화면은 판이 모두 보여요
        self.assertGreaterEqual(len(first["tags"]), 5)
        self.assertIsNotNone(self.case("card390")["card"])
        self.assertIsNotNone(self.case("card390")["sel"])

    def test_visible_zone_keeps_its_tag(self):
        """판을 보일지는 판 제자리가 아니라 구역 바닥이 화면에 보이는지로 정해요. 제자리가 화면 밖이거나 확대 단추·안내 줄에 막히면
        옆이나 보이는 바닥 안의 빈자리로 옮겨요. 바닥이 반 넘게 보이는 구역은 판이 있고, 고른 나라는 바닥이 조금만 보여도 판이 있어요."""
        for name in ("me390", "us390", "all390", "all1280", "kr1280", "drag1280", "drag390", "zout390", "refit390"):
            with self.subTest(name):
                x = self.case(name)
                for t in x["tags"]:
                    if t["seen"] >= 0.5 or (t["zone"] == x["zone"] and t["seen"] > 0.05):
                        self.assertTrue(t["shown"], (t, [(q["zone"], q["seen"], q["shown"]) for q in x["tags"]]))
                    if not t["seen"]:
                        self.assertFalse(t["shown"], t)                         # 바닥이 화면 밖인 구역 판은 가장자리에 쌓지 않아요
        kr = next(t for t in self.case("drag1280")["tags"] if t["zone"] == "KR")
        self.assertTrue(0.3 < kr["seen"] < 1, kr)                               # 정말 앞쪽이 화면 밖으로 나간 경우예요

    def test_numbers_country_change_refits_map(self):
        """숫자 보기에서 나라를 바꾼 뒤 빌딩 보기로 돌아오면 지도는 새로 고른 나라에 맞춰져 있고 그 판이 보여요."""
        x = self.case("refit390")
        self.assertEqual(x["zone"], "KR")
        kr = next(t for t in x["tags"] if t["zone"] == "KR")
        self.assertGreaterEqual(kr["seen"], 0.9, kr)
        self.assertTrue(kr["shown"], kr)

    def test_focused_tag_keeps_focus(self):
        """키보드 초점이 있는 판은 구역이 화면 밖으로 가도 숨지 않고 가장자리에 남아요(초점이 body로 빠지지 않아요)."""
        x = self.case("focus1280")
        self.assertEqual(x["active"], "zone:KR", x["active"])
        kr = next(t for t in x["tags"] if t["zone"] == "KR")
        self.assertTrue(kr["shown"], kr)
        self.assertEqual((kr["tab"], kr["aria"]), ("0", None))
        self.assertLess(kr["seen"], 0.3, kr)                                    # 정말 구역이 (거의) 화면 밖이에요
        self.assertGreaterEqual(kr["r"][0], 0)
        self.assertLessEqual(kr["r"][2], x["W"])
        self.assertGreaterEqual(kr["r"][1], x["top"][3])

    def test_top_bar_is_opaque(self):
        """위 막대의 단추·고르기·찾기 칸 뒤로 지도·이름판이 비치지 않아요(바탕 알파 1). 숫자 보기에서는 막대 자리 전체가 불투명 띠예요."""
        for name in ("me390", "all1280", "num390"):
            with self.subTest(name):
                bg = self.case(name)["bg"]
                for s in ("#count", "#viewGroup", "#langGroup", "#ctry", "#findQ"):
                    self.assertEqual(css_alpha(bg[s]), 1.0, (s, bg[s]))
        self.assertEqual(css_alpha(self.case("all1280")["bg"]["#top"]), 0.0)   # 빌딩 보기에서는 막대 칸 사이로 지도가 보여요(띠 없음)
        for name in ("num390", "num1280"):
            self.assertEqual(css_alpha(self.case(name)["bg"]["#top"]), 1.0, name)

    def test_numbers_scroll_below_top_bar(self):
        """숫자 보기 순위표는 위 막대 아래에서 시작해 그 안에서만 스크롤돼요. 스크롤해도 줄이 막대 칸 사이·뒤로 지나가지 않아요."""
        for name in ("num390", "num1280"):
            with self.subTest(name):
                x = self.case(name)
                self.assertGreater(x["scrollTop"], 0, x)                      # 정말 스크롤했어요
                self.assertGreaterEqual(x["numbers"][1], x["top"][3] - 0.5, (x["numbers"], x["top"]))
                self.assertEqual(x["leakN"], 0, x["leak"])

    def test_numbers_band_does_not_reach_map(self):
        """숫자 보기 위 막대 띠의 빈 곳(칸 사이·끝·아래 여백)은 누름을 받아요. 뒤에 숨은 지도의 건물·이름판에 닿지 않아 카드가 열리거나 나라가 바뀌지 않아요."""
        for name in ("num390", "num1280", "jp390", "band390", "band1280"):
            with self.subTest(name):
                x = self.case(name)
                self.assertEqual(x["stageN"], 0, x["stage"])
        for name, zone in (("band390", "ALL"), ("band1280", "KR")):
            with self.subTest(name):
                x = self.case(name)
                self.assertGreater(x["taps"], 10, x["taps"])                  # 정말 띠를 여러 번 눌렀어요
                self.assertEqual(x["opened"], 0)
                self.assertIsNone(x["card"])
                self.assertEqual(x["zone"], zone)
                self.assertIsNotNone(x["numbers"])                             # 숫자 보기 그대로

    def test_mouse_drag_selects_no_hidden_text(self):
        """숫자 보기에서 마우스로 끌어 골라도 위 막대 글자와 뒤에 숨은 지도의 이름판·건물 이름은 골라지지 않아요(순위표 글자는 골라도 돼요)."""
        for name in ("selband1280", "selbanddown1280"):
            with self.subTest(name):
                self.assertEqual(self.case(name)["selText"], "")
        up = self.case("selup1280")["selText"]
        self.assertIn("순위", up)                                               # 정말 순위표 제목부터 골랐어요
        for word in ("브라질", "일본", "아이디 찾기", "숫자"):                    # 대한민국 순위표에는 없는 지도 판·막대 글자
            self.assertNotIn(word, up)
        for name in ("selband1280", "selbanddown1280", "selup1280"):
            self.assertIsNotNone(self.case(name)["numbers"])                      # 숫자 보기 그대로

    def test_top_offset_follows_bar_height(self):
        """위 막대 높이가 refreshChrome·창 크기 말고 다른 일(늦게 바뀐 글꼴)로 바뀌어도 --top과 순위표 시작이 따라와요."""
        x = self.case("font390")
        base = self.case("num390")
        self.assertNotEqual(x["topH"], base["topH"])                            # 정말 막대 높이가 바뀌었어요
        for name in ("font390", "num390", "num1280", "all1280", "me390"):
            with self.subTest(name):
                y = self.case(name)
                self.assertEqual(y["cssTop"], f'{y["topH"]}px')
        self.assertAlmostEqual(x["numbers"][1], x["top"][3], delta=0.6)

    def test_world_rank_label_on_screen(self):
        """5명 전 나라(일본)를 고르면 순위 칸에 작게 '세계 순위'가 보여요. 폰의 카드형 줄에서도 보여요(칸 머리는 폰에서 숨어요)."""
        for name, word in (("jp390", "세계 순위"), ("jp1280en", "World rank")):
            with self.subTest(name):
                rk = self.case(name)["rk"]
                self.assertTrue(rk)
                for num, sub, h in rk:
                    if num == "—":
                        continue
                    self.assertEqual(sub, word)
                    self.assertGreater(h, 0)                                    # 숨지 않고 보여요
        self.assertEqual([x[1] for x in self.case("num390")["rk"] if x[0] != "—"], [""] * len([x for x in self.case("num390")["rk"] if x[0] != "—"]))   # 모든 나라는 숫자만


if __name__ == "__main__":
    unittest.main()
