"""에이전시티 처음 설정 U-19 시험: 처음 설정을 마칠 때까지 밖으로 나가는 요청은 새 버전 확인(github.com) 하나뿐이에요. 사무실 화면도 글꼴 등을 밖에서 받지 않아요.
처음 화면이 부르는 길(상태·Claude 찾기·추천·첫 메시지 허락·새 버전·사용량·층 만들기·규칙 줄·끝)을 차례로 부르고,
그동안 서버가 밖으로 낸 요청을 가짜 프록시로 모아 봐요. 처음 화면 코드에는 공개(publish)·로그인을 부르는 길이 없어야 해요.

python3 -m unittest tests/test_setup.py -v      (저장소 맨 위에서)

진짜 GitHub·gist에는 닿지 않아요. 서버의 HTTPS_PROXY를 127.0.0.1의 빈 포트(9400번대)에 띄운 가짜 프록시로 두고,
가짜 프록시는 받은 곳(호스트)만 적고 403으로 끊어요. 저장소는 임시 폴더(/private/tmp 아래)에 복사해 돌리고,
HOME도 임시 폴더라 이 컴퓨터의 Claude 기록·설정은 읽지 않아요. 파이썬 표준 라이브러리만 써요.
팀장 검토 1~5번(어느 화면으로 여는지, [사무실 열기], 체크 풀기, [다시 찾기])은 화면 코드의 함수를 꺼내 node로 돌려요(node가 없으면 건너뛰어요).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from test_city import LOCAL, ROOT, TMP_BASE, copy_repo, free_port   # noqa: E402


class RecordingProxy:
    """HTTPS(CONNECT host:443)와 HTTP(절대 주소 GET)를 받아 호스트만 적고 403으로 끊어요. 아무 데도 이어 주지 않아요."""

    def __init__(self):
        self.hosts, self.port = [], free_port()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def deny(self, host):
                fake.hosts.append(host)
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()

            def do_CONNECT(self):
                self.deny(self.path.rsplit(":", 1)[0])

            def do_GET(self):
                self.deny(urlsplit(self.path).hostname or self.headers.get("Host", ""))

            do_HEAD = do_POST = do_PATCH = do_GET

        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def make_sessions(home):
    """Claude 데스크톱 앱의 세션 기록 몇 개(쇼핑몰 팀 셋, 블로그 둘, 제목이 총괄인 세션 하나). → {제목: (세션 id, 폴더)}"""
    d = os.path.join(home, "Library", "Application Support", "Claude", "claude-code-sessions", "acct", "org")
    os.makedirs(d)
    code, now, out = os.path.join(home, "code"), int(time.time() * 1000), {}
    for i, (title, folder) in enumerate((("쇼핑몰 팀장", "shop"), ("쇼핑몰 개발", "shop"), ("쇼핑몰 디자인", "shop"),
                                         ("블로그 리드", "blog"), ("블로그 개발자", "blog"), ("총괄", None))):
        path = os.path.join(code, folder) if folder else home
        os.makedirs(path, exist_ok=True)
        sid = "local_" + str(uuid.uuid4())
        with open(os.path.join(d, sid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"sessionId": sid, "title": title, "cwd": path, "originCwd": path, "isArchived": False,
                       "lastActivityAt": now - (i + 1) * 60000}, f)
        out[title] = (sid, path)
    return out


class FirstSetupOutbound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proxy = RecordingProxy()
        cls.tmp = tempfile.mkdtemp(prefix="agencity-u19-", dir=TMP_BASE)
        cls.dir = copy_repo(os.path.join(cls.tmp, "app"))
        cls.home = os.path.join(cls.tmp, "home")
        cls.conf = os.path.join(cls.tmp, "conf")
        os.makedirs(cls.conf)
        cls.sessions = make_sessions(cls.home)
        shutil.copy(os.path.join(cls.dir, "examples", "org.example.json"), os.path.join(cls.dir, "org.json"))
        with open(os.path.join(cls.dir, "org.json"), encoding="utf-8") as f:
            cls.boss_before = json.load(f).get("boss")
        subprocess.run([sys.executable, "-I", "build.py"], cwd=cls.dir, check=True, capture_output=True)
        cls.port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("AGENCITY_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"))}
        # AGENCITY_UPDATE_BASE 등을 비워서 새 버전 확인은 진짜 주소(github.com)로 가려 하고, 프록시가 그걸 끊어요
        env.update(HOME=cls.home, OFFICE_PORT=str(cls.port), AGENCITY_CONFIG_DIR=cls.conf, AGENCITY_UPDATE_INTERVAL="0",
                   HTTPS_PROXY=cls.proxy.url, HTTP_PROXY=cls.proxy.url, https_proxy=cls.proxy.url, http_proxy=cls.proxy.url,
                   NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
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
        cls.page = page
        cls.token = re.search(r"const TOKEN = '([A-Za-z0-9_-]{20,})'", page).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.proxy.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json", "Origin": self.base, "X-Office-Token": self.token})
        try:
            with LOCAL.open(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def setup_json(self):
        with open(os.path.join(self.dir, "setup.json"), encoding="utf-8") as f:
            return json.load(f)

    def ok(self, path, body):
        code, res = self.post(path, body)
        self.assertEqual(code, 200, f"{path} {res}")
        return res

    def test_first_setup_goes_out_only_for_update_check(self):
        st = self.ok("/api/setup/state", {})
        self.assertFalse(st.get("done"))
        self.ok("/api/setup/claude", {})
        rec = self.ok("/api/setup/recommend", {})
        self.assertIsNone(rec["consent"])
        self.assertNotIn("readFirstMessages", self.setup_json() if os.path.exists(os.path.join(self.dir, "setup.json")) else {})
        rec = self.ok("/api/setup/recommend", {"consent": True})   # 처음 화면의 [첫 메시지도 읽기] 스위치를 켠 것
        self.assertIs(rec["consent"], True)
        self.assertIs(self.setup_json()["readFirstMessages"]["value"], True)
        self.ok("/api/update/state", {})
        self.ok("/api/usage/state", {})
        lead, folder = self.sessions["쇼핑몰 팀장"]
        dev, _ = self.sessions["쇼핑몰 개발"]
        made = self.ok("/api/setup/floors", {"boss": None, "floors": [{"id": "shop", "name": "쇼핑몰", "folder": folder, "existing": False,
                                                                       "members": [{"role": "팀장", "sessionId": lead}, {"role": "개발자", "sessionId": dev}]}]})
        self.assertEqual([c["id"] for c in made["created"]], ["shop"], made)
        self.ok("/api/floor/link-rules", {"team": "shop"})
        self.ok("/api/setup/done", {"done": True})
        for _ in range(50):   # 새 버전 확인은 뒤에서 돌아요
            if self.proxy.hosts:
                break
            time.sleep(0.1)
        time.sleep(0.5)
        self.assertIn("github.com", self.proxy.hosts)
        self.assertEqual(set(self.proxy.hosts), {"github.com"}, self.proxy.hosts)
        # 총괄은 보내지 않았으니 자리 표시 그대로(예시 팀이 빠지며 제목만 '총괄'로 바뀌어요), 규칙 줄은 이번에 만든 층 폴더에만
        with open(os.path.join(self.dir, "org.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["boss"]["sessionId"], self.boss_before["sessionId"])
        with open(os.path.join(folder, "CLAUDE.local.md"), encoding="utf-8") as f:
            self.assertIn("@.office/RULES.md", f.read())
        self.assertFalse(os.path.exists(os.path.join(self.sessions["블로그 리드"][1], "CLAUDE.local.md")))
        self.assertTrue(self.setup_json()["done"])


    def test_page_loads_nothing_from_outside(self):
        """사무실 화면을 열 때 브라우저도 127.0.0.1 말고는 가지 않아요(결재 20261025-U-19-2 A): 글꼴·스크립트·스타일·그림을 밖에서 받지 않아요.
        글꼴 파일도 없고 글씨는 모두 시스템 글꼴이에요. 밖으로 가는 주소는 사람이 누르는 링크(<a>)뿐이에요."""
        page = self.page
        self.assertNotRegex(page, r"fonts\.(googleapis|gstatic)\.com")
        self.assertNotIn("IBM Plex", page)
        outside = r"""(?:https?:)?//(?!127\.0\.0\.1[:/]|localhost[:/])"""
        for pat in (r"<link\b[^>]*\bhref=[\"']" + outside, r"<script\b[^>]*\bsrc=[\"']" + outside, r"<(?:img|iframe|source|video|audio|embed|object)\b[^>]*\b(?:src|data)=[\"']" + outside,
                    r"url\(\s*[\"']?" + outside, r"@import", r"\bfetch\(\s*[\"'`]" + outside, r"new (?:WebSocket|EventSource)\(\s*[\"'`]" + outside,
                    r"\bxlink:href=[\"']" + outside):
            self.assertIsNone(re.search(pat, page), pat)
        self.assertNotRegex(page, r"@font-face|\\.woff2?\\b|rel=[\"']preload")
        self.assertNotIn("Do Hyeon", page)
        with self.assertRaises(urllib.error.HTTPError) as cm:   # 글꼴 폴더는 없어요
            LOCAL.open(self.base + "/fonts/DoHyeon-Regular.woff2", timeout=10)
        self.assertEqual(cm.exception.code, 404)
        cm.exception.close()


class FirstScreenCode(unittest.TestCase):
    """처음 화면(firstHTML·firstOpen과 그 줄들)에는 공개·로그인·gist를 부르는 길이 없어요(결정 U-19 6장)."""

    def test_no_publish_or_login_path(self):
        with open(os.path.join(ROOT, "office.src.html"), encoding="utf-8") as f:
            src = f.read()
        names = ["firstHTML", "firstOpen", "firstRowHTML", "firstPickHTML", "firstBossHTML", "firstRulesHTML", "firstGoPaint"]
        for name in names:
            m = re.search(r"\n(?:async )?function " + name + r"\(.*?\n\}\n", src, re.S)
            self.assertIsNotNone(m, name)
            body = m.group(0)
            for bad in ("publish", "github/", "loginHTML", "visHTML", "mtHTML", "/api/meter"):
                self.assertNotIn(bad, body, f"{name}에 {bad}")


def page_js(*names):
    """office.src.html에서 맨 위 함수(function·async function)와 한 줄 const를 이름으로 꺼내요(검토 U-19 1~5번 시험용)."""
    with open(os.path.join(ROOT, "office.src.html"), encoding="utf-8") as f:
        src = f.read()
    out = []
    for name in names:
        m = re.search(r"\n((?:async )?function " + name + r"\()", src)
        if m:
            i = src.index("{", src.index(")", m.end()))
            depth, j = 0, i
            while True:
                depth += {"{": 1, "}": -1}.get(src[j], 0)
                if depth == 0:
                    break
                j += 1
            out.append(src[m.start(1):j + 1])
            continue
        m = re.search(r"\n(const " + name + r" = [^\n]*)\n", src)
        if not m:
            raise AssertionError(f"office.src.html에 {name}이 없어요")
        out.append(m.group(1))
    return "\n".join(out)


@unittest.skipUnless(shutil.which("node"), "node가 없어요(화면 코드 시험은 node로 돌려요)")
class FirstScreenLogic(unittest.TestCase):
    """팀장 검토 U-19 1~5번: 화면 코드의 함수를 그대로 꺼내 node에서 가짜 주변(서버 호출·그리기)과 함께 돌려요."""

    def node(self, code):
        r = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_1_3_first_open(self):
        """1: 설정을 안 끝냈어도 내 층이 있으면 새로 만들 게 없어도 done을 적고 닫아요. 3: 만들 층이 0개여도 고른 총괄은 보내고, 칸이 켜져 있으면 총괄 창을 열어요."""
        code = """
let SU, calls, picked, mine, FIRST_FAIL = null;
const FNOTE = new Map(), FLOORS_MAX = 20, API = true, BOSS_T = 'hq', BOSS_ROLE = '총괄';
const firstPicked = () => picked, myFloors = () => Array.from({ length: mine }, () => ({})), pickCheck = () => false, quiet = m => new Error(m);
const renderSetup = () => {}, refreshSetup = async () => {}, load = () => {}, linkRules = async () => {};
const recMakeSend = async (list, boss) => { calls.push(['recs', list.length, boss]); return { created: list.map(id => ({ id })), errors: [] }; };
const pickMakeSend = async (list, boss) => { calls.push(['picks', list.length, boss]); return { created: list.map(id => ({ id })), errors: [] }; };
const sp = async (path, body) => { calls.push([path, body]); return {}; };
const seatLink = (t, r) => calls.push(['seatLink', t, r]);
const closeSetup = () => { calls.push(['close']); SU.open = false; };
""" + page_js("firstPlan", "firstOpen") + """
async function run(o) {
  SU = { open: true, view: 'first', err: '', st: { boss: !!o.hasBoss, done: false }, first: { busy: false, use: o.use || '', boss: o.open !== false, far: null },
         rec: { errs: {} }, madeRun: [], rules: { on: true, res: {} } };
  calls = []; mine = o.mine || 0; picked = { recs: Array.from({ length: o.n || 0 }, (_, i) => 'r' + i), picks: [], n: o.n || 0 };
  await firstOpen();
  return { calls, done: SU.st.done };
}
(async () => {
  const out = {
    floorsNoNew: await run({ mine: 3, n: 0, hasBoss: true }),
    useNoFloors: await run({ mine: 0, n: 0, use: 'local_boss' }),
    openNoFloors: await run({ mine: 0, n: 0 }),
    nothing: await run({ mine: 0, n: 0, open: false }),
    make: await run({ mine: 0, n: 2, use: 'local_boss' }),
  };
  console.log(JSON.stringify(out));
})();
"""
        r = self.node(code)
        self.assertEqual(r["floorsNoNew"]["calls"], [["done", {"done": True}], ["close"]])
        self.assertTrue(r["floorsNoNew"]["done"])
        self.assertEqual(r["useNoFloors"]["calls"], [["floors", {"boss": "local_boss", "floors": []}], ["close"]])
        self.assertFalse(r["useNoFloors"]["done"])    # 내 층이 없으면 예시 팀으로 열고 설정은 끝내지 않아요
        self.assertEqual(r["openNoFloors"]["calls"], [["seatLink", "hq", "총괄"], ["close"]])
        self.assertEqual(r["nothing"]["calls"], [["close"]])
        self.assertEqual(r["make"]["calls"], [["recs", 2, "local_boss"], ["done", {"done": True}], ["close"]])

    def test_2_which_screen(self):
        """2: 처음 화면은 done=false일 때만. done=true면 층이 0개여도 탭이고, 가려는 탭이 정해진 요청은 done=false여도 그 탭이에요."""
        code = "const SU_TAB_KEYS = new Set(['floors', 'boss', 'city', 'alerts']);\n" + page_js("setupView") + """
console.log(JSON.stringify([setupView(false), setupView(false, 'floors'), setupView(true), setupView(true, 'alerts'), setupView(true, 'nope'),
  setupView(false, 'city', true), setupView(false, 'alerts', true), setupView(false, 'boss', true), setupView(false, 'floors', true), setupView(false, 'nope', true)]));
"""
        self.assertEqual(self.node(code), ["first", "first", "floors", "alerts", "floors", "city", "alerts", "boss", "floors", "first"])
        with open(os.path.join(ROOT, "office.src.html"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("setupView(!!SU.st.done, view, aim)", page_js("openSetup"))
        for aimed in ("openSetup('alerts', true)", "openSetup('boss', true)", "openSetup(view, true)", "openSetup('floors', true)"):
            self.assertIn(aimed, src)   # 알림 띠·총괄 띠·?setup=…·팀원 고치기는 그 탭으로

    def test_4_unpick_moved_rec(self):
        """4: [고치기]로 옮긴 추천의 체크를 풀면 목록으로 꺼진 채 돌아가요(보이는 20줄 안이든 [더 보기] 안이든)."""
        code = """
const FIRST_ROWS = 20, calls = [];
const recLive = () => true, seatsInUse = () => new Set(), renderSetup = () => {}, suSay = () => {}, ix = () => 0;
let SU;
""" + page_js("firstRecs", "firstOn", "recBackOff", "firstUnpick") + """
function check(i) {
  const list = Array.from({ length: 25 }, (_, k) => ({ key: 'k' + k }));
  SU = { picks: {}, rec: { data: { list }, drop: new Set(), done: new Set(), off: new Set(), on: new Set(['k' + i]), open: '' } };
  const p = SU.picks['rec|k' + i] = { key: 'rec|k' + i, kind: 'rec', recKey: 'k' + i, name: '팀', src: '팀' };
  SU.rec.open = 'pick|' + p.key;
  firstUnpick(p);
  const recs = firstRecs();
  return { back: recs.some(r => r.key === 'k' + i), on: recs.filter((r, j) => firstOn(r, j)).some(r => r.key === 'k' + i), open: SU.rec.open, pick: !!SU.picks[p.key] };
}
console.log(JSON.stringify([check(3), check(22)]));
"""
        for row in self.node(code):
            self.assertEqual(row, {"back": True, "on": False, "open": "", "pick": False})

    def test_5_reload_also_recommends(self):
        """5: [다시 찾기]는 세션 목록을 다시 읽은 뒤, 층을 고르는 화면이면 추천도 다시 받아요."""
        code = """
let SU, recs;
const loadClaude = async () => {}, ensureRec = force => recs.push(force);
""" + page_js("onFloors", "claudeReload") + """
(async () => {
  const out = [];
  for (const view of ['first', 'floors', 'city']) { SU = { open: true, view }; recs = []; await claudeReload(); out.push(recs); }
  console.log(JSON.stringify(out));
})();
"""
        self.assertEqual(self.node(code), [[True], [True], []])
        with open(os.path.join(ROOT, "office.src.html"), encoding="utf-8") as f:
            self.assertIn("else if (a === 'claude-reload') claudeReload();", f.read())   # 처음 화면·층 묶음의 [다시 찾기]가 모두 이 길로


if __name__ == "__main__":
    unittest.main()
