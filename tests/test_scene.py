"""에이전시티 사무실 장면 U-23-3 시험: 장면이 #rooms 다시 그리기에서 살아남는지, 약속대로 값을 넘기는지, 누르면 책상과 같은 서랍이 열리는지.

python3 -m unittest tests/test_scene.py -v      (저장소 맨 위에서)

화면 코드(office.src.html)의 함수를 그대로 꺼내 node에서 가짜 주변(DOM·서버)과 함께 돌려요. node가 없으면 건너뛰어요.
파이썬 표준 라이브러리만 써요. 진짜 세션·파일은 건드리지 않아요.
"""
import datetime
import glob
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
with open(os.path.join(ROOT, "office.src.html"), encoding="utf-8") as f:
    SRC = f.read()


def page_js(*names):
    """맨 위 함수(function·async function)와 한 줄 const를 이름으로 꺼내요."""
    out = []
    for name in names:
        m = re.search(r"\n((?:async )?function " + name + r"\()", SRC)
        if m:
            i = SRC.index("{", SRC.index(")", m.end()))
            depth, j = 0, i
            while True:
                depth += {"{": 1, "}": -1}.get(SRC[j], 0)
                if depth == 0:
                    break
                j += 1
            out.append(SRC[m.start(1):j + 1])
            continue
        m = re.search(r"\n(const " + name + r" = [^\n]*)\n", SRC)
        if not m:
            raise AssertionError(f"office.src.html에 {name}이 없어요")
        out.append(m.group(1))
    return "\n".join(out)


def scene_code():
    return re.search(r'<script id="officeSceneCode">(.*?)</script>', SRC, re.S).group(1)


def scene_open():
    """시험에서만 장면 속을 들여다봐요. 실제 약속에는 없어요."""
    return scene_code().replace("const api = {", "const api = { _debug: () => S, _view: () => view, _nav: nav,")


def Date_ms(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000


REAL_FLOORS = {"3301157d380d77bbe7db26f6d8636f8e06a293d6", "f53228fa0dc29ff25b7e255f3b61df801d366233", "3dd0d0ca34ff0136b9ef31f01fe82f87e589a2c9", "d8565389a58cb5407a03807d0fca768185563106", "a232c11e3f1857e0521b1e38c37f9cc8630b7be5"}


def floor_names_in(text, digests=REAL_FLOORS):
    """낱말과 그 앞부분을 해시로 봐요. 이름 뒤에 토씨가 붙어도(이름을, 이름에서) 찾아요."""
    return [w[:n] for w in re.findall(r"[\w가-힣]+", text.lower()) for n in range(1, min(len(w), 40) + 1) if hashlib.sha1(w[:n].encode()).hexdigest() in digests]


# 헤드리스 셸(Playwright·Puppeteer가 받아둬요)을 먼저 써요. 앱 Chrome은 켤 때마다 Dock에 빈 아이콘이 잠깐 떠요
SHELLS = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")) + glob.glob(os.path.expanduser("~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell")), reverse=True)
CHROME = next((c for c in (shutil.which("chrome-headless-shell"), *SHELLS, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome"), shutil.which("chromium")) if c and os.path.exists(c)), None)


def in_browser(body, script, width=1280, height=None):
    """페이지 CSS로 작은 조각을 진짜 브라우저에서 재요. CSS는 node로 잴 수 없어요. 포트를 열지 않아요. height를 주면 낮은 창도 iframe으로 재요."""
    css = re.search(r"<style[^>]*>(.*?)</style>", SRC, re.S).group(1)
    page = f'<!doctype html><meta charset="utf-8"><style>{css}</style><body>{body}<pre id="out"></pre><script>{script}</script>'
    if width < 500 or height:   # 창은 500보다 좁아지지 않아요. 폰 폭과 낮은 창은 iframe 안에서 재요
        frame = html.escape(page, quote=True)
        # 안쪽 결과는 늦게(프레임을 기다리는 시험) 나올 수 있어서 onload 한 번이 아니라 짧게 계속 옮겨 와요
        page = f'<!doctype html><pre id="out"></pre><iframe id="f" style="border:0;width:{width}px;height:{height or 800}px" srcdoc="{frame}"></iframe><script>setInterval(() => {{ const t = f.contentDocument && f.contentDocument.getElementById("out"); if (t && t.textContent) out.textContent = t.textContent; }}, 40);</script>'
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "t.html")
        with open(f, "w", encoding="utf-8") as w:
            w.write(page)
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--use-mock-keychain", "--password-store=basic", f"--user-data-dir={d}/c", f"--window-size={max(width, 500)},900", "--virtual-time-budget=1500", "--dump-dom", "file://" + f], capture_output=True, text=True, timeout=60)
    return json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S).group(1)))


GLUE = ("STAGE_HOLD_KEY", "STAGE", "stageRest", "stageHostMake", "stageStop", "stageMount", "stageFaces", "stageSync", "stageSettle", "stageRun", "STAGE_FRAME", "stageCovered", "stageTick", "stageFail", "stageBadge", "stageRemake")


@unittest.skipUnless(shutil.which("node"), "node가 없어요(화면 코드 시험은 node로 돌려요)")
class SceneFrame(unittest.TestCase):
    def node(self, code):
        r = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    SEAT = """
const seats = {}, seatGet = k => seats[k], seatKey = (t, r) => t + '/' + r, isCx = m => !!m.codexId && !m.sessionId, exampleTeam = t => t === 'demo';
const liveFake = {}, seatLive = (t, r) => liveFake[r] || null;
""" + page_js("LIVE_TAIL", "liveOn", "STAFF_RE", "skOn", "isSk", "skView") + """
const cxInfo = (t, m) => ({ state: m.cxState || '대기', title: 'Codex 일', missing: !!m.cxMissing, at: 5 });
const NOW = Date.parse('2026-10-31T12:00:00Z'), ago = min => new Date(NOW - min * 60000).toISOString();
"""

    def test_seat_view_order(self):
        """기획 U-23-2 2-0의 판정 순서: 명단과 장면이 같은 값을 써요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView") + """
const m = { role: '개발자', sessionId: 'local_x' }, live = { status: '진행 중', participants: ['개발자'] }, done = { status: '정리 중', participants: ['개발자'] };
const v = (s, am, mm) => { const x = seatView('t', mm || m, s, am, NOW); return [x.kind, x.state, x.label, x.quiet, x.stale, x.say, x.invited]; };
console.log(JSON.stringify({
  cx: v(null, null, { role: 'c', codexId: 'abc', cxState: '일하는 중' }),
  cxMissing: v(null, null, { role: 'c', codexId: 'abc', cxMissing: true }),
  vacant: v(null, null, { role: 'q' }),
  noFile: v(null, null),
  work: v({ state: '일하는 중', updated: ago(5), say: '네' }),
  workShort: v({ state: '일하는 중', updated: ago(40) }),
  workLong: v({ state: '일하는 중', updated: ago(400) }),
  meetLive: v({ state: '회의 중', updated: ago(90), say: '말' }, live),
  meetNoSite: v({ state: '회의 중', updated: ago(5) }),
  meetOld: v({ state: '회의 중', updated: ago(90) }),
  meetWrapUp: v({ state: '회의 중', updated: ago(90) }, done),
  blocked: v({ state: '막힘', updated: ago(900) }),
  idle: v({ state: '대기', updated: ago(5) }),
  idleLong: v({ state: '대기', updated: ago(400), say: '옛말' }),
  typo: v({ state: '쉬는 중', updated: ago(5) }),
  invited: v({ state: '대기', updated: ago(5) }, live),
}));
"""
        r = self.node(code)
        self.assertEqual(r["cx"][:3], ["cx", "일하는 중", "일하는 중"])
        self.assertEqual(r["cxMissing"][:2], ["cx", "빈자리"])       # 기록을 못 찾으면 사람 없는 책상
        self.assertEqual(r["vacant"][:3], ["vacant", "빈자리", "빈자리"])
        self.assertEqual(r["noFile"][1:4], ["대기", "아직 소식 없음", "short"])   # 모르는 것을 대기라고 하지 않아요
        self.assertEqual(r["work"][1:6], ["일하는 중", "일하는 중", "", False, "네"])
        self.assertEqual(r["workShort"][1:5], ["일하는 중", "일하는 중", "short", True])
        self.assertEqual(r["workLong"][1:5], ["일하는 중", "일하는 중", "long", True])
        self.assertEqual(r["meetLive"][1:6], ["회의 중", "회의 중", "", False, ""])   # 진행 중 회의에서는 오래돼도 경고하지 않아요
        self.assertEqual(r["meetNoSite"][1], "회의 중")
        self.assertEqual(r["meetOld"][1:5], ["대기", "회의 중", "short", True])       # 사이트 회의 없이 30분 넘음: 회의실에서 나와요
        self.assertEqual(r["meetWrapUp"][1], "대기")                                  # 정리 중에는 회의실에 남지 않아요
        self.assertEqual(r["blocked"][1:5], ["막힘", "막힘", "", False])              # 막힘은 오래돼도 그대로
        self.assertEqual(r["idle"][1:5], ["대기", "대기", "", False])
        self.assertEqual(r["idleLong"][3:6], ["", False, ""])                         # 대기는 오래돼도 돌아다녀요(팀장 결정). 한마디는 6시간까지
        self.assertEqual(r["typo"][1:3], ["대기", "쉬는 중"])                          # 글은 원문 그대로
        self.assertTrue(r["invited"][6])

    def test_read_notes_name_the_log_folder(self):
        """긴 작업 때 대화 기록의 고친 시각을 본다는 말이 첫 화면 자세히, README, GUIDE 표에 있어요. 첫 화면 꼭 보일 줄은 그대로예요."""
        i = SRC.index('<details class="su-more"><summary>자세히</summary><p class="hint">읽는 것:')
        self.assertIn("<code>~/.claude/projects</code>", SRC[i:i + 900])
        self.assertIn("이 맥의 세션 목록(제목·폴더·마지막 활동)과 실행 상태만 읽어요.", SRC)
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            line = next(x for x in f if "실행 상태만 읽어요" in x)
        self.assertIn("`~/.claude/projects`", line)
        with open(os.path.join(ROOT, "docs", "GUIDE.md"), encoding="utf-8") as f:
            line = next(x for x in f if x.startswith("| Claude Code | 제목"))
        self.assertIn("`~/.claude/projects/`(고친 시각만)", line)

    def test_public_docs_have_no_real_floor_names(self):
        """저장소 글에 대표의 실제 층 이름이 없어요. 시험에 이름을 적지 않으려고 해시로 봐요."""
        names = ["README.md"] + [os.path.join("docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs"))) if n.endswith(".md")]
        found = []
        for name in names:
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                found += [(name, t) for t in floor_names_in(f.read())]
        self.assertEqual(found, [])
        made_up = {hashlib.sha1("쉬는층".encode()).hexdigest(), hashlib.sha1("mybuilding".encode()).hexdigest()}
        for text in ("쉬는층", "쉬는층을 봐요", "쉬는층의 일", "쉬는층에서 봐요", "MyBuilding에서"):
            self.assertTrue(floor_names_in(text, made_up), text)
        self.assertEqual(floor_names_in("쉬는 층을 봐요", made_up), [])

    def test_seat_view_follows_the_session(self):
        """세션이 일하면 상태 파일이 대기여도 일하는 중이에요. 회의 중과 막힘이 먼저예요. 신호는 파일의 일하는 중을 내리지 않아요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView") + """
const m = { role: '개발자', sessionId: 'local_x' }, room = { status: '진행 중', participants: ['개발자'] };
const sig = (s, sec) => ({ s, since: NOW - sec * 1000 });
const v = (s, x, am) => { delete liveFake['개발자']; if (x) liveFake['개발자'] = x; const r = seatView('t', m, s, am || null, NOW); return { state: r.state, label: r.label, quiet: r.quiet, stale: r.stale, hold: !!r.hold, task: r.task, say: r.say, when: r.updated, invited: r.invited, hours: r.hours === undefined ? null : r.hours }; };
const idle = { state: '대기', task: '옛 일', say: '옛말', updated: ago(5) }, work = { state: '일하는 중', task: 'TO-1 고치기', say: '곧', updated: ago(5) };
console.log(JSON.stringify({
  idleBusy: v(idle, sig('busy', 3)), idleWait: v(idle, sig('waiting', 3)), noFile: v(null, sig('busy', 3)), typo: v({ state: '쉬는 중', updated: ago(5) }, sig('busy', 3)),
  old: v({ state: '일하는 중', task: '옛 일', say: '옛말', updated: ago(420) }, sig('busy', 3)), oldMeet: v({ state: '회의 중', updated: ago(90) }, sig('busy', 3)),
  meetLive: v({ state: '회의 중', updated: ago(90) }, sig('busy', 3), room), meetNew: v({ state: '회의 중', updated: ago(5) }, sig('busy', 3)), stuck: v({ state: '막힘', updated: ago(5) }, sig('busy', 3)),
  workBusy: v(work, sig('busy', 3)), workIdle: v(work, sig('idle', 20)), workQuiet: v({ state: '일하는 중', task: 'x', updated: ago(40) }, sig('quiet', 2000)), idleQuiet: v(idle, sig('quiet', 2000)),
  tailIn: v(idle, sig('idle', 7.9)), tailOut: v(idle, sig('idle', 8.1)), waitIn: v(idle, sig('waiting', 7.9)), waitOut: v(idle, sig('waiting', 8.1)), invited: v(idle, sig('busy', 3), room),
  none: v(idle), vacant: (() => { liveFake['q'] = sig('busy', 3); const r = seatView('t', { role: 'q' }, null, null, NOW); return r.state; })(),
}));
"""
        r = self.node(code)
        self.assertEqual((r["idleBusy"]["state"], r["idleBusy"]["label"], r["idleBusy"]["task"], r["idleBusy"]["say"], r["idleBusy"]["hold"]), ("일하는 중", "일하는 중", "", "", False))
        self.assertLess(abs(Date_ms(r["idleBusy"]["when"]) - 1793448000000), 2000)      # 명단 시각은 방금이에요
        self.assertEqual(r["idleWait"]["state"], "일하는 중")
        self.assertEqual((r["noFile"]["state"], r["noFile"]["quiet"]), ("일하는 중", ""))
        self.assertEqual(r["typo"]["state"], "일하는 중")
        self.assertEqual((r["old"]["state"], r["old"]["quiet"], r["old"]["stale"], r["old"]["hours"], r["old"]["task"], r["old"]["say"]), ("일하는 중", "", False, None, "", ""))   # 7시간 된 파일
        self.assertEqual(r["oldMeet"]["state"], "일하는 중")
        self.assertEqual(r["meetLive"]["state"], "회의 중")
        self.assertEqual(r["meetNew"]["state"], "회의 중")
        self.assertEqual(r["stuck"]["state"], "막힘")
        self.assertEqual((r["workBusy"]["task"], r["workBusy"]["say"]), ("TO-1 고치기", "곧"))
        self.assertEqual(r["workIdle"]["state"], "일하는 중")                           # 쉬는 신호가 파일의 일하는 중을 내리지 않아요
        self.assertEqual((r["workQuiet"]["state"], r["workQuiet"]["quiet"], r["workQuiet"]["hold"]), ("일하는 중", "short", False))   # 지금 규칙 그대로
        self.assertEqual((r["idleQuiet"]["state"], r["idleQuiet"]["quiet"], r["idleQuiet"]["stale"], r["idleQuiet"]["hold"]), ("일하는 중", "short", True, True))
        self.assertEqual(r["tailIn"]["state"], "일하는 중")
        self.assertEqual(r["tailOut"]["state"], "대기")
        self.assertEqual((r["waitIn"]["hold"], r["waitIn"]["label"]), (False, "일하는 중"))
        self.assertEqual((r["waitOut"]["hold"], r["waitOut"]["label"]), (True, "확인 대기"))
        self.assertTrue(r["invited"]["invited"])
        self.assertEqual(r["none"]["state"], "대기")
        self.assertEqual(r["vacant"], "빈자리")

    def test_page_takes_the_signal_from_every_read(self):
        """load와 pollRelay가 받은 live를 페이지에 넘겨요. 이 길이 끊기면 판정 시험이 다 통과해도 사람이 앉지 않아요."""
        code = page_js("LIVE", "LIVE_FRESH", "liveTake", "seatLive", "load", "pollRelay") + """
let state = null, mode = '', orderGen = 0, pending = false, NE = null, answer = '{}';
const API = true, ORD = { want: null }, TALK_FILE = 't', TALK_SCAN = 9, orderTeams = () => null, jsonl = () => [], seatWaiting = () => false, seatPoll = () => {};
const getJSON = async () => ({ teams: [] }), loadTeam = async () => ({}), getText = async f => (f === 'api/state' ? answer : '');
const drawer = { hidden: true }, $ = q => (q === '#drawer' ? drawer : null), $$ = () => [], document = { visibilityState: 'visible', activeElement: null, hasFocus: () => false };
const stageSync = () => {}, countsPaint = () => {}, drawerPaint = () => {}, render = () => {}, relayPaint = () => {};
const seat = () => { const x = seatLive('t', '개발자', Date.now()); return x && x.s; };
const says = s => JSON.stringify({ live: { t: { 개발자: { s, since: 5 } } } });
(async () => {
  const out = { before: seat() };
  answer = says('busy'); await load(); out.load = seat();
  answer = says('idle'); await pollRelay(); out.poll = seat();
  const got = LIVE.got - 5000; LIVE.got = got;
  answer = JSON.stringify({ ok: true }); await load(); await pollRelay(); out.kept = [seat(), LIVE.got === got];   // live 칸이 없으면 앞 값을 쓰고, 시계는 가지 않아요
  answer = JSON.stringify({ live: {} }); await load(); out.empty = [seat(), LIVE.got > got];                       // 폴더가 없으면 빈 값이에요
  console.log(JSON.stringify(out));
})();
"""
        self.assertEqual(self.node(code), {"before": None, "load": "busy", "poll": "idle", "kept": ["idle", True], "empty": [None, True]})

    def test_live_signal_goes_stale(self):
        """신호는 받은 뒤 20초까지만 믿어요. 스냅샷에서는 켜지지 않아요. 모르는 값은 버려요."""
        code = page_js("LIVE", "LIVE_FRESH", "seatLive") + """
const NOW = 1793448000000; LIVE.seats = { t: { 개발자: { s: 'busy', since: NOW }, 기획: { s: '이상함', since: NOW }, 운영: 'busy' } };
LIVE.got = NOW - 19000; const fresh = seatLive('t', '개발자', NOW), odd = [seatLive('t', '기획', NOW), seatLive('t', '운영', NOW), seatLive('x', '개발자', NOW)];
LIVE.got = NOW - 21000; const old = seatLive('t', '개발자', NOW);
LIVE.got = 0; const snap = seatLive('t', '개발자', NOW);
console.log(JSON.stringify({ fresh: fresh && fresh.s, odd, old, snap }));
"""
        self.assertEqual(self.node(code), {"fresh": "busy", "odd": [None, None, None], "old": None, "snap": None})

    def test_seat_view_without_a_clock(self):
        """시각이 없거나 못 읽으면 시간을 세지 않아요. 'Infinity시간째'가 나오면 안 돼요. 예시 층은 오래됨을 재지 않아요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView") + """
const m = { role: '개발자', sessionId: 'local_x' };
const v = (s, tid) => { const x = seatView(tid || 't', m, s, null, NOW); return { state: x.state, quiet: x.quiet, stale: x.stale, hours: x.hours === undefined ? null : x.hours, say: x.say }; };
console.log(JSON.stringify({
  none: v({ state: '일하는 중', task: 'x', say: '네' }),
  empty: v({ state: '일하는 중', updated: '', say: '네' }),
  bad: v({ state: '일하는 중', updated: '어제', say: '네' }),
  demo: v({ state: '일하는 중', updated: ago(17520), say: '네' }, 'demo'),
  real: v({ state: '일하는 중', updated: ago(17520), say: '네' }),
}));
"""
        r = self.node(code)
        still = {"state": "일하는 중", "quiet": "", "stale": False, "hours": None, "say": "네"}
        self.assertEqual(r["none"], still)
        self.assertEqual(r["empty"], still)
        self.assertEqual(r["bad"], still)
        self.assertEqual(r["demo"], still)                    # 첫 실행의 예시 팀은 늘 일하는 중이에요
        self.assertEqual((r["real"]["quiet"], r["real"]["hours"]), ("long", 292))

    def test_snapshot_keeps_its_own_clock(self):
        """스냅샷은 찍은 때 기준으로 오래됨을 재요. 네 곳이 같은 시계를 써요."""
        code = """
let mode = 'snap', state = { at: '2026-10-31T12:00:00Z' };
""" + page_js("viewNow") + """
const snap = viewNow(); mode = 'live'; const live = viewNow(); mode = 'snap'; state = { at: '' }; const bad = viewNow();
console.log(JSON.stringify({ snap, live: Math.abs(live - Date.now()) < 5000, bad: Math.abs(bad - Date.now()) < 5000 }));
"""
        self.assertEqual(self.node(code), {"snap": 1793448000000, "live": True, "bad": True})
        self.assertEqual(re.findall(r"seatView\([^\n]*Date\.now\(\)|stageState\([^\n]*Date\.now\(\)|const nowMs = Date\.now\(\)", SRC), [])

    def test_focus_finds_the_same_control(self):
        """다시 그려도 키보드 초점이 같은 단추로 돌아와요. 연필과 줄 본체, 서류함 탭, 층 도구를 구별해요."""
        code = page_js("FOCUSABLE", "sigOf") + """
const n = (tag, d) => ({ tagName: tag, dataset: d, getAttribute: () => null });
const row = sigOf(n('BUTTON', { team: 'a', role: 'r' })), pen = sigOf(n('BUTTON', { team: 'a', role: 'r', nmEdit: '' }));
const rep = sigOf(n('BUTTON', { act: 'doc', doc: 'rep' })), min = sigOf(n('BUTTON', { act: 'doc', doc: 'min' }));
console.log(JSON.stringify({ pen: row !== pen, tab: rep !== min, summary: FOCUSABLE.split(/, */).includes('summary') }));
"""
        self.assertEqual(self.node(code), {"pen": True, "tab": True, "summary": True})

    def test_meeting_gone_quiet(self):
        """진행 중 회의의 마지막 대화가 30분을 넘으면 회의실 칸에 '회의가 조용해요'가 떠요. 알림 줄은 대화로 세지 않아요."""
        code = page_js("MEET_QUIET", "meetQuiet") + """
const NOW = Date.parse('2026-10-31T12:00:00Z'), ago = m => new Date(NOW - m * 60000).toISOString();
const live = { status: '진행 중', started: ago(120) };
console.log(JSON.stringify({
  talking: meetQuiet(live, [{ t: ago(29), text: '네' }], NOW),
  quiet: meetQuiet(live, [{ t: ago(31), text: '네' }], NOW),
  nudge: meetQuiet(live, [{ t: ago(31), text: '네' }, { t: ago(1), kind: 'nudge', text: '알림' }], NOW),
  silent: meetQuiet(live, [], NOW),
  fresh: meetQuiet({ status: '진행 중', started: ago(5) }, [], NOW),
  wrap: meetQuiet({ status: '정리 중', started: ago(120) }, [], NOW),
  blank: meetQuiet({ status: '진행 중' }, [], NOW),
  none: meetQuiet(null, [], NOW),
}));
"""
        self.assertEqual(self.node(code), {"talking": False, "quiet": True, "nudge": True, "silent": True, "fresh": False, "wrap": False, "blank": False, "none": False})
        self.assertIn("회의가 조용해요", SRC)

    def test_stage_state_contract(self):
        """scene.update에 넘기는 값이 약속(docs/U-23-일감.md)과 같아요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView", "meetNow", "stageState") + """
const LEAD = '팀장', leadFirst = ms => [...ms.filter(m => m.role === LEAD), ...ms.filter(m => m.role !== LEAD)], customName = m => m.name || '';
const toneOf = t => t.tone, lookOf = k => ({ hair: '#111', skin: '#222', style: 'bun', acc: '', tie: '#333', mug: '#444', prop: 'sticky', key: k }), stageTheme = () => 'dark';
const unread = (file, last) => !!last, mode = 'live', STAGE = { held: false };
const t = { id: 'shop', name: '쇼핑몰', tone: 'hq', floor: 2 };
const d = { base: 'teams/shop/', team: { team: '쇼핑몰', members: [{ role: '개발자', sessionId: 'local_a', name: '민수' }, { role: '팀장', sessionId: 'local_b' }, { role: 'QA', sessionId: null }, { role: 'cx', codexId: 'abc' }] },
  status: { '개발자': { state: '일하는 중', task: 'SH-1 고치기', say: '곧', updated: ago(1) }, '팀장': { state: '회의 중', updated: ago(1) } }, lastChat: { '개발자': { t: 1 } },
  metas: [{ id: 'M-1', status: '진행 중', topic: '주제', mode: '참석', participants: ['팀장'] }] };
const wrap = stageState(t, Object.assign({}, d, { metas: [], active: { status: '정리 중', topic: '주제', mode: '위임' } }), NOW).meeting;
const none = stageState(t, Object.assign({}, d, { metas: [] }), NOW).meeting;
liveFake['개발자'] = { s: 'waiting', since: NOW - 9000 }; const held = stageState(t, Object.assign({}, d, { metas: [] }), NOW).members.find(m => m.id === '개발자'); delete liveFake['개발자'];
console.log(JSON.stringify(Object.assign(stageState(t, d, NOW), { wrap, none, held })));
"""
        r = self.node(code)
        self.assertEqual((r["tone"], r["name"], r["theme"], r["live"]), ("a", "쇼핑몰", "dark", True))
        self.assertEqual((r["held"]["hold"], r["held"]["wait"], r["held"]["label"]), (True, True, "확인 대기"))
        self.assertLess(abs(Date_ms(r["held"]["when"]) - Date_ms("2026-10-31T12:00:00Z")), 2000)
        self.assertEqual(r["floor"], 2)
        for unused in ("colors", "fonts", "floors"):
            self.assertNotIn(unused, r)   # 장면이 읽지 않는 값은 넘기지 않아요
        self.assertEqual([m["id"] for m in r["members"]], ["팀장", "개발자", "QA", "cx"])
        lead, dev, qa, cx = r["members"]
        self.assertTrue(lead["lead"])
        self.assertEqual(lead["state"], "회의 중")
        self.assertEqual((dev["name"], dev["state"], dev["task"], dev["say"], dev["newReply"]), ("민수", "일하는 중", "SH-1 고치기", "곧", True))
        self.assertEqual((qa["state"], qa["newReply"]), ("빈자리", False))
        self.assertEqual((cx["codex"], cx["look"]["key"]), (True, "abc"))
        self.assertEqual(set(dev["look"]) - {"key"}, {"hair", "skin", "style", "acc", "tie", "mug", "prop"})
        for m in r["members"]:
            self.assertIn(m["state"], ("일하는 중", "대기", "회의 중", "막힘", "빈자리"))
        self.assertEqual(r["meeting"], {"active": True, "topic": "주제", "phase": "live", "mode": "boss"})   # 장면의 말로 바꿔서 넘겨요
        self.assertEqual(r["wrap"], {"active": True, "topic": "주제", "phase": "wrap", "mode": "team"})
        self.assertFalse(r["none"]["active"])

    FAKE = """
const logs = [], marks = new Set();
const mk = id => ({ id, isConnected: true, hidden: false, replaced: null, marks: new Set(), classList: { add(c) { marks.add(c); }, remove(c) { marks.delete(c); } }, replaceWith(x) { this.isConnected = false; this.replaced = x; x.isConnected = true; }, remove() { this.isConnected = false; } });
let slot = null, made = [];
let drawer = null, panel = null;
const $ = s => (s === '#rooms [data-stage-slot]' ? slot : s === '#drawer' ? drawer : s === '.drawer-panel' ? panel : null), $$ = () => [];
const document = { hidden: false, documentElement: { dataset: {} }, createElement: () => { const badge = { hidden: true }; return Object.assign(mk('host'), { firstChild: { setAttribute() {} }, lastChild: { hidden: false }, children: [null, badge] }); } };
const window = {}, requestAnimationFrame = fn => { logs.push('raf'); return 1; }, cancelAnimationFrame = () => {};
const hash = () => 7, stageStill = { matches: false }, stageDark = { matches: false }, SU = { open: false }, localStorage = { getItem: () => null }, stageAria = () => '';
const esc = s => String(s), put = (el, html) => { el.text = html; };
let state = { org: { teams: [{ id: 'a' }, { id: 'b' }] }, teams: { a: {}, b: {} } };
const stageState = (t, d, now) => ({ live: state.live !== false, members: [{ id: 'x', state: state.s || '대기', quiet: '' }], meeting: state.meeting || { active: false } });
const box = { setAttribute() {} };
const createOfficeScene = (el, o) => { const s = { o, ups: 0, steps: 0, draws: 0, gone: false, update() { s.ups++; }, on() {}, step() { s.steps++; }, draw() { s.draws++; }, destroy() { s.gone = true; } }; made.push(s); return s; };
const stageSelect = () => {}, stageHover = () => {}, viewNow = () => Date.now();
"""

    def test_stage_survives_redraw(self):
        """#rooms를 다시 그려도 장면은 같은 덩이·같은 장면으로 돌아가요. 층이 바뀔 때만 새로 만들어요. 자리표가 없으면(입주 예정) 멈춰요."""
        code = self.FAKE + page_js(*GLUE) + """
const t = id => state.org.teams.find(x => x.id === id), out = {};
slot = mk('slot'); stageMount(t('a'), state.teams.a);
const host = STAGE.host, sc = STAGE.scene;
out.first = { placed: slot.replaced === host, scenes: made.length, seed: sc.o.seed, updated: sc.ups > 0, steps: sc.steps };
slot = mk('slot'); host.isConnected = false; stageMount(t('a'), state.teams.a);       // put이 방을 다시 그렸어요: 새 자리표
out.again = { sameHost: slot.replaced === host, sameScene: STAGE.scene === sc, scenes: made.length, updates: sc.ups };
slot = null; stageMount(t('a'), state.teams.a);                                       // 같은 글이라 다시 안 그렸어요
out.same = { sameScene: STAGE.scene === sc, scenes: made.length };
slot = mk('slot'); stageMount(t('b'), state.teams.b);                                 // 층을 옮겼어요
out.floor = { old: sc.gone, scenes: made.length, tid: STAGE.tid };
slot = null; host.isConnected = false; stageMount(t('b'), null);                      // 입주 예정 층
out.vacant = { stopped: STAGE.scene === null, gone: made[1].gone };
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["first"], {"placed": True, "scenes": 1, "seed": 7, "updated": True, "steps": 0})   # 첫 그림은 update가 그려요
        self.assertEqual(r["again"]["sameHost"], True)
        self.assertEqual(r["again"]["sameScene"], True)
        self.assertEqual(r["again"]["scenes"], 1)
        self.assertGreaterEqual(r["again"]["updates"], 2)
        self.assertEqual(r["same"], {"sameScene": True, "scenes": 1})
        self.assertEqual(r["floor"], {"old": True, "scenes": 2, "tid": "b"})
        self.assertEqual(r["vacant"], {"stopped": True, "gone": True})

    def test_description_and_badge(self):
        """캔버스의 설명은 지워서 칸의 한국어 설명 하나만 남겨요. 회의가 있으면 장면 위에 회의실 칸과 같은 말을 띄워요."""
        code = self.FAKE.replace("$$ = () => [];", "$$ = s => (s === 'canvas' ? [cv] : []);") + """
const attrs = { role: 'img', 'aria-label': 'English' }, cv = { setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: k => { delete attrs[k]; } };
""" + page_js(*GLUE) + """
slot = mk('slot'); stageMount(state.org.teams[0], state.teams.a);
const b = () => [STAGE.badge.hidden, STAGE.badge.text], out = { attrs, none: b() };
state.meeting = { active: true, phase: 'live', mode: 'boss', topic: '주제' }; stageSync(); out.boss = b();
state.meeting = { active: true, phase: 'live', mode: 'team', topic: '주제' }; stageSync(); out.team = b();
state.meeting = { active: true, phase: 'wrap', mode: 'boss', topic: '주제' }; stageSync(); out.wrap = b();
state.meeting = { active: false }; stageSync(); out.gone = b();
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["attrs"], {"aria-hidden": "true"})
        self.assertEqual(r["none"], [True, ""])
        self.assertEqual(r["boss"], [False, "대표와 회의 중 · 주제"])
        self.assertEqual(r["team"], [False, "팀끼리 회의 중 · 주제"])
        self.assertEqual(r["wrap"], [False, "회의록 정리 중"])
        self.assertEqual(r["gone"], [True, ""])

    def test_portrait_or_default_face(self):
        """장면에 portrait가 있으면 명단 얼굴로 쓰고, 없거나 고장 나면 지금 그림 그대로예요."""
        code = """
const STAGE = { faces: new Map(), scene: null, view: { members: [{ id: 'a', look: { hair: '#1' } }, { id: 'b', look: { hair: '#2' } }, { id: 'c', look: {} }, { id: 'd', look: {} }] } };
const av = id => ({ id, on: false, url: '', classList: { add() { this.on = true; } }, style: {} });
const faces = {}, rows = ['a', 'b', 'c', 'd', 'vac'].map(id => ({ dataset: { member: id } }));
const $$ = () => rows, $ = (s, r) => { if (r.dataset.member === 'vac') return null; const x = faces[r.dataset.member] || (faces[r.dataset.member] = { style: {}, on: false }); x.classList = { add: () => { x.on = true; } }; return x; };
""" + page_js("stageFaces") + """
stageFaces();                                   // 장면 없음
const none = Object.keys(faces).length;
STAGE.scene = {}; stageFaces();                 // portrait 없음
const plain = Object.values(faces).some(x => x.on);
let calls = 0;
STAGE.scene = { portrait: id => { calls++; if (id === 'a') return 'data:image/png;base64,AA'; if (id === 'b') return { toDataURL: () => 'data:image/png;base64,BB' }; if (id === 'c') return 'javascript:alert(1)'; throw new Error('꽝'); } };
stageFaces(); const first = calls; stageFaces();
console.log(JSON.stringify({ none, plain, a: faces.a.style.backgroundImage, b: faces.b.style.backgroundImage, c: !!faces.c.on, d: !!faces.d.on, cached: calls - first }));
"""
        r = self.node(code)
        self.assertEqual(r["none"], 0)
        self.assertFalse(r["plain"])
        self.assertEqual(r["a"], 'url("data:image/png;base64,AA")')
        self.assertEqual(r["b"], 'url("data:image/png;base64,BB")')
        self.assertFalse(r["c"])            # data:image가 아니면 쓰지 않아요
        self.assertFalse(r["d"])            # 고장 나도 지금 그림
        self.assertEqual(r["cached"], 2)    # 받은 얼굴은 다시 묻지 않아요(못 받은 둘만 다시 물어요)

    def test_look_stays_the_same_object(self):
        """장면은 look 값이 달라질 때만 옷을 다시 지어요. 4초마다 새 값을 주면 사람마다 다시 지어요."""
        code = page_js("hash", "STYLES", "HAIRS", "SKINS", "MUGS", "ROLE_LOOK", "LOOKS", "lookOf") + """
console.log(JSON.stringify({ same: lookOf('local_a', '개발자') === lookOf('local_a', '개발자'), other: lookOf('local_a', '개발자') === lookOf('local_b', '개발자'), acc: lookOf('local_a', '개발자').acc }));
"""
        self.assertEqual(self.node(code), {"same": True, "other": False, "acc": "headphones"})

    def test_broken_scene_keeps_roster(self):
        """장면이 고장 나면 칸만 숨기고, 다시 그려도 자리표를 치워요(명단·서랍은 그대로). 명단은 줄이 다 보이는 높이를 가져요."""
        code = self.FAKE.replace("const createOfficeScene = (el, o) => {", "const createOfficeScene = (el, o) => { throw new Error('꽝');").replace("s === '.drawer-panel' ? panel : null", "s === '.drawer-panel' ? panel : s === '#rooms .hero' ? hero : null").replace("let drawer = null,", "const hero = mk('hero'); let drawer = null,") + page_js(*GLUE) + """
console.warn = () => {};
const t = state.org.teams[0];
slot = mk('slot'); stageMount(t, state.teams.a);
const off = STAGE.off, hidden = STAGE.host.hidden, cls = [...marks];
slot = mk('slot'); const s2 = slot; stageMount(t, state.teams.a);
console.log(JSON.stringify({ off, hidden, slotGone: !s2.isConnected, scene: STAGE.scene, cls }));
"""
        self.assertEqual(self.node(code), {"off": True, "hidden": True, "slotGone": True, "scene": None, "cls": ["no-stage"]})
        self.assertIn("""<div class="hero${stageGone() ? ' no-stage' : ''}">""", SRC)    # 다시 그려도 그대로예요
        if not CHROME:
            return
        rows = "".join('<li class="r" style="height:70px">줄</li>' for _ in range(8))
        room = lambda cls: f'<div class="{cls}"><section class="scene-card"><header class="sc-head"><h2>층</h2></header></section><aside class="roster"><div class="ro-in"><div class="ro-h"><h3>팀원</h3></div><ul class="ro-list">{rows}</ul></div></aside></div>'
        size = "const l = document.querySelector('.ro-list'); document.getElementById('out').textContent = JSON.stringify({ shown: l.getBoundingClientRect().height, need: l.scrollHeight });"
        fine, bad = in_browser(room("hero no-stage"), size), in_browser(room("hero"), size)
        self.assertGreaterEqual(fine["shown"], fine["need"])      # 1280폭에서 줄이 다 보여요
        self.assertLess(bad["shown"], 100)                        # 이 시험이 쪼그라듦을 잡는지 확인해요

    def test_narrow_header_says_what_is_wrong(self):
        """860px 이하에서 칩이 접혀도 끊김과 새 버전은 메뉴를 안 열어도 알아봐요. 메뉴 글은 화면 밖으로 안 나가요."""
        code = page_js("put", "hdrNote") + """
const els = {}, el = (k, hidden) => (els[k] = { hidden, _html: '', cls: new Set(), attrs: {}, classList: { toggle(c, on) { on ? els[k].cls.add(c) : els[k].cls.delete(c); } }, setAttribute(a, b) { els[k].attrs[a] = b; } });
const $ = q => els[q] || null, esc = s => String(s);
el('#hdrNote', true); el('#hdrMore', false);
const look = () => { hdrNote(); return { text: els['#hdrNote'].innerHTML || '', hidden: els['#hdrNote'].hidden, alert: els['#hdrMore'].cls.has('alert'), label: els['#hdrMore'].attrs['aria-label'] }; };
const quiet = look();
el('#live.lost', false); const lost = look();
el('#upd', false); const both = look();
delete els['#live.lost']; els['#upd'].hidden = true; const off = look();
console.log(JSON.stringify({ quiet, lost, both, off }));
"""
        r = self.node(code)
        self.assertEqual(r["quiet"], {"text": "", "hidden": True, "alert": False, "label": "메뉴 더 보기"})
        self.assertEqual(r["lost"], {"text": "연결 끊김", "hidden": False, "alert": True, "label": "메뉴 더 보기, 연결 끊김"})
        self.assertEqual(r["both"], {"text": "연결 끊김 +1", "hidden": False, "alert": True, "label": "메뉴 더 보기, 연결 끊김, 새 버전"})
        self.assertEqual(r["off"], r["quiet"])
        if not CHROME:
            return
        long = "총괄 창에서 붙여 넣고(⌘V) Enter를 눌러요"
        bar = f'<header class="hdr" style="position:relative"><span class="sp"></span><button class="live hdr-more alert"><span class="more-note" id="n">연결 끊김</span></button><div class="hdr-chips show"><span class="live alert" id="r">{long} <a href="#">총괄 창 다시 열기</a></span></div></header>'
        m = in_browser(bar, "const r = document.getElementById('r').getBoundingClientRect(); document.getElementById('out').textContent = JSON.stringify({ note: document.getElementById('n').getBoundingClientRect().width, right: r.right, page: innerWidth, over: document.documentElement.scrollWidth - innerWidth });", 720)
        self.assertGreater(m["note"], 0)
        self.assertLessEqual(m["right"], m["page"])
        self.assertEqual(m["over"], 0)

    def test_room_scroll_keeps_its_place(self):
        """다시 그려도 명단과 업무판을 내려 둔 위치가 그대로예요. 층을 바꾸면 맨 위부터예요."""
        self.assertEqual(re.search(r"const ROOM_SCROLLS = '([^']*)'", SRC).group(1).split(", "), ["#rooms .ro-list", "#rooms .board", "#rooms .feed", "#rooms .files"])
        self.assertIn("if (redrawn && sameRoom) $$(ROOM_SCROLLS)", SRC)

    def test_motion_rules(self):
        """움직임 줄이기·숨은 탭·화면 밖이면 돌리지 않아요. 고리는 페이지 것 하나예요. 설정이 덮거나 연결이 끊기면 쉬어요."""
        code = self.FAKE + page_js(*GLUE) + """
const t = state.org.teams[0], out = {}, raf = () => logs.filter(x => x === 'raf').length;
stageStill.matches = true;
slot = mk('slot'); stageMount(t, state.teams.a);
const sc = STAGE.scene;
out.still = { raf: raf(), steps: sc.steps, reduced: sc.o.reducedMotion };
state.s = '일하는 중'; stageSync(); out.changed = sc.steps;      // 움직임 줄이기: update만으로 제자리에 가요
stageStill.matches = false; STAGE.still = false; STAGE.held = true;
state.s = '막힘'; const u1 = sc.ups; stageSync(); out.held = { steps: sc.steps, updates: sc.ups - u1 };   // 멈춘 동안에는 시간이 안 가요
STAGE.held = false;
document.hidden = true; stageRun(); out.hidden = raf();
document.hidden = false; STAGE.seen = false; stageRun(); out.offscreen = raf();
STAGE.seen = true; stageRun(); out.running = raf();
const before = sc.steps; SU.open = true; stageTick(1000); out.setupOpen = sc.steps === before;
SU.open = false; STAGE.raf = 0; STAGE.last = 1000; sc.steps = 0; stageTick(1900);
out.capped = sc.steps;
STAGE.raf = 0; stageTick(1908); out.tooSoon = sc.steps;                 // 120Hz: 8ms 뒤에는 그리지 않아요
STAGE.raf = 0; stageTick(1934); out.next = sc.steps;                    // 초당 30장
drawer = { hidden: false }; panel = { getBoundingClientRect: () => ({ left: 0, right: 360 }) }; STAGE.host.getBoundingClientRect = () => ({ left: 16, right: 344 });
STAGE.raf = 0; stageTick(2000); out.covered = sc.steps;                 // 폰: 서랍이 다 덮음
panel.getBoundingClientRect = () => ({ left: 760, right: 1280 }); STAGE.host.getBoundingClientRect = () => ({ left: 16, right: 900 });
STAGE.raf = 0; STAGE.last = 2000; stageTick(2040); out.beside = sc.steps;   // 넓은 화면: 서랍 옆에 보여요
state.live = false; stageSync(); STAGE.raf = 0; STAGE.last = 2100; stageTick(2200); out.lost = sc.steps;   // 연결이 끊기면 그 자리에서 멈춰요
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["still"], {"raf": 0, "steps": 0, "reduced": True})
        self.assertEqual(r["changed"], 0)
        self.assertEqual(r["held"], {"steps": 0, "updates": 1})
        self.assertEqual(r["hidden"], 0)
        self.assertEqual(r["offscreen"], 0)
        self.assertEqual(r["running"], 1)
        self.assertTrue(r["setupOpen"])
        self.assertEqual(r["capped"], 1)
        self.assertEqual((r["tooSoon"], r["next"], r["covered"], r["beside"], r["lost"]), (1, 2, 2, 3, 3))

    def test_reduced_motion_change_remakes_scene(self):
        """움직임 줄이기를 켜고 끄면 장면을 그 값으로 다시 만들어요. 장면이 없으면 아무 일도 없어요."""
        code = self.FAKE + page_js(*GLUE) + """
stageRemake();
const none = made.length;
slot = mk('slot'); stageMount(state.org.teams[0], state.teams.a);
const first = STAGE.scene;
stageStill.matches = true; stageRemake();
console.log(JSON.stringify({ none, scenes: made.length, oldGone: first.gone, reduced: STAGE.scene.o.reducedMotion, tid: STAGE.tid, updated: STAGE.scene.ups > 0 }));
"""
        self.assertEqual(self.node(code), {"none": 0, "scenes": 2, "oldGone": True, "reduced": True, "tid": "a", "updated": True})

    def test_reduced_motion_seen_without_the_event(self):
        """change 이벤트가 사라져도 그림 고리나 다음 갱신에서 알아채요. 연결이 끊긴 채 탭에 돌아오면 재생하지 않아요."""
        code = self.FAKE + page_js(*GLUE) + """
slot = mk('slot'); stageMount(state.org.teams[0], state.teams.a);
const first = STAGE.scene;
stageRun(); stageStill.matches = true; stageTick(1000);
const tick = { scenes: made.length, reduced: STAGE.scene.o.reducedMotion, gone: first.gone };
stageStill.matches = false; stageSync();
const sync = { scenes: made.length, reduced: STAGE.scene.o.reducedMotion };
const sc = STAGE.scene; sc.steps = 0; state.live = false; stageSync(); stageSettle(); const lost = sc.steps;
state.live = true; stageSync(); stageSettle();
console.log(JSON.stringify({ tick, sync, lost, back: sc.steps }));
"""
        self.assertEqual(self.node(code), {"tick": {"scenes": 2, "reduced": True, "gone": True}, "sync": {"scenes": 3, "reduced": False}, "lost": 0, "back": 150})

    def test_hold_is_remembered(self):
        """[움직임 멈추기]는 이 브라우저에 기억해요. 풀면 지워요. 시간이 멈추고 사람만 들고 나요."""
        code = self.FAKE.replace("localStorage = { getItem: () => null }", "localStorage = { box: {}, getItem(k) { return k in this.box ? this.box[k] : null; }, setItem(k, v) { this.box[k] = v; }, removeItem(k) { delete this.box[k]; } }") + page_js(*GLUE) + page_js("stageHold") + """
const render = () => {}, saw = [];
slot = mk('slot'); stageMount(state.org.teams[0], state.teams.a);
stageHold(true); const on = [STAGE.held, localStorage.getItem(STAGE_HOLD_KEY)];
stageHold(false); const off = [STAGE.held, localStorage.getItem(STAGE_HOLD_KEY)];
console.log(JSON.stringify({ on, off }));
"""
        self.assertEqual(self.node(code), {"on": [True, "1"], "off": [False, None]})
        self.assertIn("still: STAGE.held", SRC)
        self.assertNotIn('data-act="stage-still" aria-pressed', SRC)    # 글자가 이미 다음 동작을 말해요

    def test_scene_description_counts_people(self):
        """장면 칸의 한국어 설명은 상태별 사람 수를 세어 줘요."""
        code = page_js("stageAria") + """
console.log(JSON.stringify(stageAria({ members: [{ state: '대기' }, { state: '대기' }, { state: '막힘' }, { state: '빈자리' }] })));
"""
        self.assertEqual(self.node(code), "사무실 장면. 대기 2명, 막힘 1명, 빈자리 1명. 같은 내용이 명단에 있어요.")

    def test_smooth_scroll_only_with_motion(self):
        """움직임 줄이기에서는 부드럽게 스크롤하지 않아요."""
        rows = re.findall(r"[^\n]*behavior: [^\n]*", SRC)
        self.assertGreater(len(rows), 1)
        for row in rows:
            self.assertRegex(row, r"behavior: (matchMedia\('\(prefers-reduced-motion: reduce\)'\)\.matches|stageStill\.matches) \? 'auto' : 'smooth'")

    def test_small_labels_read_right(self):
        """빈 서류함 말은 조사까지 맞아요. 층 칩은 막힌 사람을 말해요. 층 만들기는 층을 만드는 단계를 열어요."""
        self.assertNotRegex(SRC, r"아직 \$\{what\}가 없어요")
        self.assertIn("noDoc('회의록이')", SRC)
        self.assertRegex(SRC, r"act\.dataset\.act === 'floor-new'[^\n]*openSetup\((2|'floors', true)\)")
        code = page_js("floorAria") + """
console.log(JSON.stringify([floorAria('2층 쇼핑몰', 0, false), floorAria('2층 쇼핑몰', 2, false), floorAria('2층 쇼핑몰', 1, true)]));
"""
        self.assertEqual(self.node(code), ["2층 쇼핑몰", "2층 쇼핑몰, 막힘 2명", "2층 쇼핑몰, 막힘 1명, 새 답"])
        code = page_js("rowAria") + """
const l = (who, role, cx, chip, nw, when, task) => rowAria({ who, role, cx, chip, nw, when, task });
console.log(JSON.stringify([l('보안', '보안', false, '대기', false, '3분 전', '다음 일'), l('민수', '개발자', false, '일하는 중', true, '방금', 'TO-1 고치기'), l('봇', '코덱스', true, '대기', false, '', 'Codex 세션'), ]));
"""
        self.assertEqual(self.node(code), ["보안, 대기, 3분 전, 다음 일. 대화 열기", "민수, 개발자, 일하는 중, 방금, 새 답, TO-1 고치기. 대화 열기", "봇, 코덱스, Codex, 대기, Codex 세션. 자세히 보기"])
        self.assertIn('aria-label="${esc(rowAria({ who, role: m.role, cx: cxm, sk: skm, chip, nw: newReply, when, task }))}"', SRC)    # 명단 줄이 이 글을 써요
        self.assertIn('aria-label="${esc(floorAria(label, blocked, fresh))}"', SRC)
        self.assertIn("STAGE.box.setAttribute('aria-label', stageAria(v))", SRC)

    def test_tools_menu_closes_on_the_same_click(self):
        """[층 도구]를 연 채 다른 곳을 누르면 그 클릭의 다시 그리기에서도 닫혀 있어요."""
        i = SRC.index("const t = $('#floorTools');")
        self.assertIn("{ t.open = false; TOOLS_OPEN = false; }", SRC[i:i + 200])

    def test_stage_passes_hold_and_time(self):
        """장면과 호버 카드가 명단과 같은 값을 받아요. 카드는 열려 있으면 다음 갱신에서 글이 바뀌어요."""
        code = self.FAKE.replace("const stageState = (t, d, now) => ({ live: state.live !== false, members: [{ id: 'x', state: state.s || '대기', quiet: '' }]", "const stageState = (t, d, now) => ({ live: state.live !== false, members: [{ id: 'x', name: 'x', role: 'x', state: state.s || '대기', label: state.l || '대기', quiet: '', task: state.t || '', when: '2026-11-01T00:00:00Z' }]") + page_js(*GLUE) + page_js("seatLine", "seatChip", "stageTipHTML") + """
const API = true, ago = () => '방금';
slot = mk('slot'); stageMount(state.org.teams[0], state.teams.a);
STAGE.tip = { hidden: false, dataset: { id: 'x' }, innerHTML: '옛 글' }; state.s = '일하는 중'; state.l = '확인 대기'; stageSync();
const open = STAGE.tip.innerHTML; STAGE.tip = { hidden: true, dataset: { id: '' }, innerHTML: '옛 글' }; stageSync();
console.log(JSON.stringify({ open: open.includes('확인 대기 · 방금'), shut: STAGE.tip.innerHTML }));
"""
        self.assertEqual(self.node(code), {"open": True, "shut": "옛 글"})
        i = SRC.index("function stageState(")
        self.assertIn("hold: v.hold", SRC[i:i + 1400])
        self.assertIn("when: v.updated", SRC[i:i + 1400])

    def test_seat_line_never_tells_a_worker_to_wait(self):
        """일하는 사람에게 '다음 일을 기다리는 중'이 나오면 안 돼요. 명단과 호버 카드가 같은 말을 써요."""
        code = page_js("seatLine") + """
console.log(JSON.stringify([seatLine({ state: '일하는 중' }), seatLine({ state: '일하는 중', task: 'TO-1' }), seatLine({ state: '일하는 중', task: 'TO-1', wait: true }), seatLine({ state: '대기' })]));
"""
        self.assertEqual(self.node(code), ["", "TO-1", "Claude 창에서 확인해요", "다음 일을 기다리는 중"])
        row = page_js("seatRowHTML")
        self.assertIn("seatLine(v)", row)
        self.assertIn("""${esc(task || '—')}</span>""", row)     # 줄 높이는 그대로예요
        self.assertIn("nw: newReply, when, task })", row)                               # —는 스크린리더가 읽지 않아요
        self.assertIn("[line, v.say && `“${v.say}”`].filter(Boolean).join(' · ')", row)  # 한마디가 있으면 한마디만 보여요
        self.assertIn("seatLine(m)", page_js("stageTipHTML"))
        for name, part in (("seatRowHTML", "seatChip(v)"), ("stageTipHTML", "seatChip(m)"), ("drawerFacts", "seatChip(v)")):
            self.assertIn(part, page_js(name))

    def test_counts_follow_while_the_drawer_is_open(self):
        """서랍을 연 동안 명단은 닫을 때 따라오지만, 머리말 숫자는 장면과 같아요."""
        code = page_js("countsHTML") + """
console.log(JSON.stringify(countsHTML([{ state: '일하는 중' }, { state: '일하는 중' }, { state: '대기' }])));
"""
        html = self.node(code)
        self.assertIn("일하는 중 <b>2</b>", html)
        self.assertIn("대기 <b>1</b>", html)
        self.assertNotIn("막힘", html)
        self.assertIn("countsHTML(views)", page_js("roomHTML"))
        self.assertIn("put(box, countsHTML(", page_js("countsPaint"))

    def test_counts_and_line_follow_while_the_drawer_is_open(self):
        """서랍을 연 동안 지금 보고 있는 층의 머리말과 장면 아래 글이 같이 바뀌어요. 다들 기다린다는 글이 일하는 사람 옆에 남으면 안 돼요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView", "meetNow", "leadFirst", "countsHTML", "countsPaint", "stageLine") + """
const el = () => ({ innerHTML: '', hidden: false }), counts = el(), line = el(), room = { dataset: { team: 'b' } };
const $ = q => ({ '#rooms .counts': counts, '#rooms .sc-line': line, '#rooms .room': room })[q];
const LEAD = '팀장', esc = String, usgFloorHTML = () => '', stageStill = { matches: false }, viewNow = () => NOW, put = (e, h) => { e.innerHTML = h; };
const who = [{ role: '팀장', sessionId: 'local_a' }, { role: '개발자', sessionId: 'local_b' }], calm = { state: '대기', updated: ago(5) };
let state = { org: { teams: [{ id: 'a' }, { id: 'b', office: 'teams/b' }] }, teams: { a: { team: { members: [who[0]] }, status: { 팀장: { state: '막힘', updated: ago(5) } } }, b: { team: { members: who }, status: { 팀장: calm, 개발자: calm } } } };
const look = () => ({ counts: counts.innerHTML, line: line.innerHTML, hidden: line.hidden });
countsPaint(); const a = look();
liveFake['개발자'] = { s: 'busy', since: NOW - 1000 }; countsPaint(); const b = look();
delete liveFake['개발자']; countsPaint(); const c = look();
console.log(JSON.stringify({ a, b, c }));
"""
        r = self.node(code)
        self.assertIn("대기 <b>2</b>", r["a"]["counts"])
        self.assertEqual((r["a"]["line"], r["a"]["hidden"]), ("다들 다음 일을 기다려요.", False))
        self.assertIn("일하는 중 <b>1</b>", r["b"]["counts"])
        self.assertIn("대기 <b>1</b>", r["b"]["counts"])
        self.assertNotIn("막힘", r["b"]["counts"])                                  # 보고 있는 층의 숫자예요
        self.assertEqual((r["b"]["line"], r["b"]["hidden"]), ("", True))
        self.assertEqual(r["c"], r["a"])
        self.assertIn("""<p class="sc-line"${line ? '' : ' hidden'}>${esc(line)}</p>""", page_js("roomHTML"))     # 글이 없어도 자리는 늘 있어요
        self.assertIn("if (!redrawn) countsPaint();", page_js("render"))             # 방 글이 같아서 건너뛰어도 칠해 둔 값이 남지 않아요

    def test_open_drawer_repaints_its_own_cells(self):
        """팀원 서랍을 연 동안 머리의 상태 줄과 정보 탭의 세 칸만 따라와요. 닫은 뒤에는 건드리지 않아요."""
        code = self.SEAT.replace("ago = min =>", "old = min =>") + page_js("QUIET_SHORT", "seatView", "meetNow", "seatChip", "seatDot", "drawerFacts", "factLine", "MUST_LINE", "talkPane", "dHead", "drawerPaint", "memberDrawer") + """
let DF = null;
const ago = () => '방금', esc = String, viewNow = () => NOW, API = true, EX_NO_TALK = '', hm = String, picWaitPaint = () => {}, relayBand = () => '';
const cxDrawer = () => {}, customName = () => '', teamNames = () => [], seatHTML = (t, r) => r, chatLink = String, exampleSeat = () => true, composerHTML = () => '', openDrawer = () => {}, openThread = () => {};
const drawer = { hidden: false }, cells = { '#dfLine': {}, '#dfState': {}, '#dfTask': {}, '#dfSay': {} }, $ = q => (q === '#drawer' ? drawer : cells[q]), put = (e, h) => { e.text = h; };
let state = { teams: { t: { base: 't/', reports: [], log: [], team: { team: '가', members: [{ role: '개발자', sessionId: 'local_x', title: 'x' }] }, status: { 개발자: { state: '일하는 중', task: 'TO-1', say: '곧', updated: old(5) } } } } };
const look = () => ['#dfLine', '#dfState', '#dfTask', '#dfSay'].map(k => cells[k].text);
memberDrawer('t', '개발자'); drawerPaint(); const a = look();
liveFake['개발자'] = { s: 'waiting', since: NOW - 9000 }; drawerPaint(); const b = look();
drawer.hidden = true; delete liveFake['개발자']; drawerPaint(); const c = look();
console.log(JSON.stringify({ a, b, c }));
"""
        r = self.node(code)
        self.assertEqual(r["a"], ['<i class="dot d-work"></i>일하는 중 · 방금 · TO-1', "일하는 중 · 방금", "TO-1", "곧"])
        self.assertEqual(r["b"], ['<i class="dot d-work"></i>확인 대기 · 방금 · Claude 창에서 확인해요', "확인 대기 · 방금", "TO-1", "곧"])   # 명단 둘째 줄과 같은 말
        self.assertEqual(r["c"], r["b"])

    PICS = """
const NAME = 'a'.repeat(32) + '.png', NAME2 = 'b'.repeat(32) + '.jpg';
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'), hm = String, seatHTML = (t, r) => r, seatText = (t, r) => r + '님';
"""

    def test_thread_lines_show_pictures(self):
        """사진은 이름 규칙을 지난 값으로만 주소를 만들어요. 사진만 보낸 말은 서버가 채운 글을 그리지 않아요. 스냅샷에는 img가 없어요."""
        code = self.PICS + "let API = true, PIC_V = 3;\n" + page_js("PIC_NAME", "ATT", "picUrl", "linePics", "picsHTML", "mdLite", "TURN_GAP", "sameTurn", "lineHTML", "linesHTML", "threadHTML") + """
const line = (o) => Object.assign({ t: '10:00', from: '개발자', text: '글' }, o);
console.log(JSON.stringify({
  one: threadHTML([line({ img: [NAME] })], 't1'),
  me: threadHTML([line({ from: '대표', img: [NAME] })], 't1'),
  two: threadHTML([line({ img: [NAME, NAME2], text: '사진 2장' })], 't1'),
  bad: threadHTML([line({ img: ['../x.png', '<img src=x onerror=1>', 'A'.repeat(32) + '.png', NAME + '.key', 7, NAME] })], 't1'),
  str: threadHTML([line({ img: NAME })], 't1'),
  hq: threadHTML([line({ img: [NAME] })]),
  han: linesHTML([line({ img: [NAME] })], '한글층'),
  none: threadHTML([line({})], 't1'), empty: threadHTML([], 't1'), emptyLines: linesHTML([], 't1'),
  sys: threadHTML([line({ kind: '알림', img: [NAME] })], 't1'),
}));
"""
        r = self.node(code)
        self.assertIn(f'data-pic="api/image/team/t1/{"a" * 32}.png?v=3"', r["one"])         # 서랍을 열 때마다 바뀌어서 지운 사진이 메모리에서 안 나와요
        for part in ('class="pic"', 'loading="lazy"', 'decoding="async"', 'draggable="false"', 'alt=""', 'data-n="1"', 'aria-label="사진 크게 보기"', 'data-alt="개발자님 사진"'):
            self.assertIn(part, r["one"])
        self.assertIn("<p>글</p><span class=\"msg-pics\"", r["one"])                       # 세션 말은 글을 그린 뒤 사진이 붙어요
        self.assertIn(">글<span class=\"msg-pics\"", r["me"])                              # 대표 말은 pre-wrap이라 공백을 넣지 않아요
        self.assertIn('data-n="2"', r["two"])
        self.assertIn('aria-label="사진 2 크게 보기"', r["two"])
        self.assertNotIn(">사진 2장<", r["two"])                                            # 같은 말을 두 번 하지 않아요
        self.assertEqual(r["bad"].count('class="pic"'), 1)
        self.assertNotIn("onerror", r["bad"])
        self.assertNotIn("..", r["bad"])
        self.assertNotIn('class="pic"', r["str"])
        self.assertIn('data-pic="api/image/hq/', r["hq"])
        self.assertIn("api/image/team/%ED%95%9C%EA%B8%80%EC%B8%B5/", r["han"])
        self.assertNotIn("msg-pics", r["none"])
        self.assertIn("아직 주고받은 말이 없어요", r["empty"])
        self.assertEqual(r["emptyLines"], "")
        self.assertNotIn("msg-pics", r["sys"])

    def test_opening_a_drawer_asks_for_pictures_again(self):
        """같은 주소의 그림은 메모리에서 다시 나와요. 서랍을 열 때마다 주소가 달라야 지운 사진이 남아 보이지 않아요."""
        code = "let PIC_V = 0, live = null;\nconst refreshThread = () => {}, $ = () => null;\n" + page_js("picUrl", "openThread") + """
const a = picUrl('n.png', 't'); openThread('c'); const b = picUrl('n.png', 't'), hq = picUrl('n.png'); openThread('c');
console.log(JSON.stringify({ a, b, hq, c: picUrl('n.png', 't') }));
"""
        self.assertEqual(self.node(code), {"a": "api/image/team/t/n.png?v=0", "b": "api/image/team/t/n.png?v=1", "hq": "api/image/hq/n.png?v=1", "c": "api/image/team/t/n.png?v=2"})

    def test_snapshot_lines_have_no_picture_tags(self):
        code = self.PICS + "let API = false, PIC_V = 1;\n" + page_js("PIC_NAME", "ATT", "picUrl", "linePics", "picsHTML", "mdLite", "TURN_GAP", "sameTurn", "lineHTML", "linesHTML", "threadHTML") + """
const L = o => Object.assign({ t: '1', from: '대표', text: '글', imgs: 2 }, o);
console.log(JSON.stringify({ words: threadHTML([L({})]), bare: threadHTML([L({ text: '사진 2장' })]), name: threadHTML([L({ img: [NAME], imgs: 0 })]), them: threadHTML([L({ from: '개발자' })]), themBare: threadHTML([L({ from: '개발자', text: '사진 2장' })]) }));
"""
        r = self.node(code)
        self.assertNotIn("<img", r["words"] + r["bare"] + r["name"] + r["them"])
        self.assertIn("글\n사진 2장", r["words"])
        self.assertEqual(r["bare"].count("사진 2장"), 1)
        self.assertNotIn("a" * 32, r["name"])
        self.assertIn("<p>글<br>사진 2장</p>", r["them"])                                  # 세션 말은 줄바꿈을 그려요
        self.assertEqual(r["themBare"].count("사진 2장"), 1)

    REFRESH = """
const API = true, el = { innerHTML: '', added: [], scrollHeight: 100, scrollTop: 0, clientHeight: 100, closest: () => null, insertAdjacentHTML(w, h) { this.added.push([w, h]); } };
let draws = 0, file = '';
const drawer = { hidden: false }, $ = q => (q === '#thread' ? el : q === '#drawer' ? drawer : null), getText = async () => file, enc = String, markSeen = () => {}, picWaitPaint = () => {};
const jsonl = text => String(text || '').split('\\n').map(l => { try { return l.trim() ? JSON.parse(l) : null; } catch (e) { return null; } }).filter(Boolean);
const threadHTML = lines => { draws++; return `통째로 ${lines.length}줄`; }, linesHTML = lines => `덧붙임 ${lines.length}줄`, linePics = l => l.img || [];
let live = { file: 'c', last: null };
const L = t => JSON.stringify({ t, from: '개발자', text: t }) + '\\n';
"""

    def test_thread_appends_only_new_lines(self):
        """뒤에만 늘면 새 줄만 덧붙여요. 앞 사진을 다시 받지 않고 초점과 글 선택이 남아요."""
        code = self.REFRESH + page_js("thPinned", "talkSeen", "refreshThread") + """
(async () => {
  const out = {}, look = () => ({ draws, added: el.added.length, html: el.innerHTML });
  file = L('a'); await refreshThread(true); out.first = look();
  file += L('b'); await refreshThread(); out.grew = look();
  await refreshThread(true); out.sameForce = look();
  file += '\\n\\n'; await refreshThread(true); out.blank = look();
  file += L('c').slice(0, 5); await refreshThread(); out.tail = look();
  file += L('c').slice(5); await refreshThread(); out.afterTail = look();
  file = L('다른 글'); await refreshThread(); out.rewritten = look();
  console.log(JSON.stringify(out));
})();
"""
        r = self.node(code)
        self.assertEqual(r["first"], {"draws": 1, "added": 0, "html": "통째로 1줄"})
        self.assertEqual((r["grew"]["draws"], r["grew"]["added"]), (1, 1))
        self.assertEqual((r["sameForce"]["draws"], r["sameForce"]["added"]), (1, 1))        # 같은 글 + force는 그대로예요
        self.assertEqual((r["blank"]["draws"], r["blank"]["added"]), (1, 1))                # 새 줄이 0개면 DOM을 건드리지 않아요
        self.assertEqual((r["tail"]["draws"], r["tail"]["added"]), (1, 1))                  # 쓰는 중인 줄은 아직 없어요
        self.assertEqual((r["afterTail"]["draws"], r["afterTail"]["added"]), (2, 1))        # 끝이 깨졌던 글은 통째로 그려요
        self.assertEqual(r["rewritten"]["draws"], 3)

    def test_attach_limits_match_the_helper(self):
        """페이지가 먼저 막는 숫자와 형식이 bin/chat_image.py와 같아요."""
        ns = {}
        with open(os.path.join(ROOT, "bin", "chat_image.py"), encoding="utf-8") as f:
            exec(compile(f.read().split("class Bad", 1)[0], "chat_image", "exec"), ns)
        code = page_js("PIC_NAME", "ATT") + """
console.log(JSON.stringify({ max: ATT_MAX, bytes: ATT_BYTES, pixels: ATT_PIXELS, side: ATT_SIDE, longest: ATT_LONG, name: PIC_NAME.source, types: ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/heic', 'image/svg+xml', 'image/bmp', 'image/tiff'].filter(t => ATT_OK.test(t)) }));
"""
        r = self.node(code)
        self.assertEqual((r["max"], r["bytes"], r["pixels"], r["side"], r["longest"]), (ns["MAX_PER_MSG"], ns["MAX_BYTES"], ns["SAY_PIXELS"], 2400, ns["MAX_SIDE"]))
        self.assertEqual(sorted(r["types"]), sorted(ns["TYPES"].values()))
        self.assertEqual(r["name"].replace("$", "\\Z"), ns["NAME"].pattern)
        self.assertIn('"/api/image', open(os.path.join(ROOT, "office_server.py"), encoding="utf-8").read())

    ATTACH = """
const URL = { createObjectURL: b => 'blob:' + (b.name || 'x'), revokeObjectURL() {} }, picked = [];
const err = { textContent: '' }, ta = { name: 'text', value: '', required: true }, form = { dataset: { key: 'k' } };
const $ = (q, f) => (q === '.err' ? err : null), attFit = async () => {}, attAlso = () => {}, attFocus = () => {}, attPaint = f => picked.push(attList(f.dataset.key).length);
const file = (type, name, size = 10) => ({ type, name, size });
"""

    def test_attach_rules(self):
        """형식, HEIC, 장수를 붙일 때 막아요. 보내는 중에는 받지 않아요."""
        code = self.ATTACH + page_js("ATT", "ATT_SAY", "attList", "attAdd") + """
const out = {};
let ATT_SEQ = 0;
attAdd(form, [file('application/pdf', 'a.pdf')]); out.type = [err.textContent, attList('k').length];
attAdd(form, [file('image/heic', 'a.heic')]); out.heic = err.textContent;
attAdd(form, [file('', 'a.HEIC')]); out.heic2 = err.textContent;
attAdd(form, [file('image/svg+xml', 'a.svg')]); out.svg = err.textContent;
attAdd(form, [file('image/png', 'a.png'), file('image/jpeg', 'b.jpg')]); out.ok = [err.textContent, attList('k').length];
attAdd(form, [1, 2, 3].map(i => file('image/png', i + '.png'))); out.max = [err.textContent, attList('k').length];
SENDING.add('k'); err.textContent = ''; attAdd(form, [file('image/png', 'c.png')]); out.busy = [err.textContent, attList('k').length];
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["type"], ["PNG·JPG·GIF·WebP만 붙일 수 있어요.", 0])
        self.assertEqual(r["heic"], "HEIC는 안 돼요. JPG로 바꿔서 붙여요.")
        self.assertEqual(r["heic2"], r["heic"])
        self.assertEqual(r["svg"], r["type"][0])
        self.assertEqual(r["ok"], ["", 2])
        self.assertEqual(r["max"], ["사진은 한 번에 4장까지예요.", 4])
        self.assertEqual(r["busy"], ["보내는 중이에요. 끝난 뒤 붙여요.", 4])

    SEND = """
const calls = [], TOKEN = 't';
let answers = {};
const fetch = async (u, o) => {
  calls.push([u, o.headers['Content-Type'], typeof o.body === 'string' ? JSON.parse(o.body) : o.body]);
  const k = u.split('?')[0], a = (answers[k] || []).shift();
  if (a === 'net') throw new TypeError('Failed to fetch');
  const r = a || { ok: true, id: 'n' + calls.length };
  return { ok: !r.bad, status: r.bad || 200, json: async () => r };
};
const attRepaint = () => {};
const pic = n => ({ id: n, blob: { n }, st: '', name: '', job: Promise.resolve() });
"""

    def test_upload_then_say(self):
        """사진을 하나씩 올린 뒤 말을 보내요. 말이 실패해도 올린 이름을 남겨서 또 올리지 않아요."""
        code = self.SEND + page_js("ATT", "ATT_SAY", "attList", "post", "attUpload", "attSend") + """
(async () => {
  const out = {}, body = () => ({ team: '한글층', thread: 'chat:팀장', text: '' });
  ATT.set('k', [pic(1), pic(2)]);
  answers = { 'api/say': [{ bad: 429, error: '1분에 보낼 수 있는 양을 넘었어요.' }] };
  try { await attSend('k', body()); } catch (e) { out.err = e.message; }
  out.first = calls.map(c => c[0]); out.types = calls.map(c => c[1]); out.names = attList('k').map(a => a.name);
  calls.length = 0; answers = {};
  await attSend('k', body());
  out.again = calls.map(c => c[0]); out.images = calls[0][2].images;
  ATT.set('b', [pic(3)]); calls.length = 0; answers = { 'api/image': [{ bad: 507, error: '사진 보관함이 찼어요. Finder에서 지운 뒤 다시 보내요.' }] };
  try { await attSend('b', { thread: 'boss', team: 'hq', text: '글' }); } catch (e) { out.upErr = e.message; }
  out.upCalls = calls.map(c => c[0]); out.upSt = attList('b')[0].st;
  const gifA = pic(9); gifA.job = Promise.resolve().then(() => attList('g').splice(0, 1)); ATT.set('g', [gifA]); calls.length = 0;
  try { await attSend('g', { team: 't', thread: 'chat:개발자', text: '글' }); out.gifSent = true; } catch (e) { out.gifErr = e.message; }
  out.gifCalls = calls.length;
  ATT.set('c', [pic(4)]); calls.length = 0; answers = { 'api/image': ['net'] };
  try { await attSend('c', { team: 't', thread: 'meeting:m', text: '' }); } catch (e) { out.net = e.message; }
  out.netSt = attList('c')[0].st;
  attList('c')[0].st = ''; answers = { 'api/say': [{ bad: 400, error: '올리지 않은 사진이에요' }] };
  try { await attSend('c', { team: 't', thread: 'meeting:m', text: '' }); } catch (e) { out.gone = e.message; }
  out.goneName = attList('c')[0].name;
  console.log(JSON.stringify(out));
})();
"""
        r = self.node(code)
        self.assertEqual(r["first"], ["api/image?thread=chat%3A%ED%8C%80%EC%9E%A5&team=%ED%95%9C%EA%B8%80%EC%B8%B5"] * 2 + ["api/say"])
        self.assertEqual(r["types"][:2], ["application/octet-stream"] * 2)
        self.assertTrue(all(r["names"]))
        self.assertEqual(r["err"], "1분에 보낼 수 있는 양을 넘었어요.")
        self.assertEqual(r["again"], ["api/say"])
        self.assertEqual(r["images"], r["names"])
        self.assertEqual(r["upErr"], "사진 보관함이 찼어요. Finder에서 지운 뒤 다시 보내요.")
        self.assertEqual((r["upCalls"], r["upSt"]), (["api/image?thread=boss"], "bad"))     # say로 가지 않아요
        self.assertEqual(r["net"], "연결이 끊겼어요. 글과 사진은 그대로예요.")
        self.assertEqual(r["netSt"], "bad")
        self.assertEqual(r["gone"], "올리지 않은 사진이에요")
        self.assertEqual(r["goneName"], "")                                                 # 지워진 사진은 다시 올려요
        self.assertEqual((r.get("gifSent"), r["gifErr"], r["gifCalls"]), (None, "", 0))     # 붙인 사진이 판정에서 빠졌으면 보내지 않아요. 까닭은 이미 떠 있어요

    def test_submit_keeps_words_until_sent(self):
        """보내는 동안 글은 drafts에서 빠지고, 실패하면 돌아와요. 같은 작성창은 두 번 보내지 않아요."""
        code = self.SEND + page_js("ATT", "ATT_SAY", "attList", "attCount", "post", "attUpload", "attSend", "submitForm") + """
const drafts = new Map(), err = { textContent: '' }, btn = { disabled: false, isConnected: true };
const ta = { name: 'text', value: '그림 봐요', form: null, readOnly: false, closest: () => null }, form = { dataset: { form: 'say', key: 'k' }, isConnected: true, querySelector: () => ta };
ta.form = form;
const draftKey = t => 'd|' + t.name, hoGrow = () => {}, relayPaint = () => {}, dTab = () => {}, restoreDrafts = () => {}, attFormOf = () => form, attAlso = () => {}, attPaint = () => {};
const $ = (q, f) => (q === '.err' ? err : null), $$ = (q) => (q.includes('submit') ? [btn] : []);
class FormData { constructor() {} get(k) { return { team: 't', thread: 'chat:개발자', text: ta.value }[k]; } getAll() { return []; } }
let state = {}, live = null, refreshed = 0, seen = [];
const refreshThread = async () => { refreshed++; };
drafts.set('d|text', '그림 봐요');
ATT.set('k', [pic(1)]);
(async () => {
  const out = {};
  answers = { 'api/say': [{ bad: 429, error: '잠깐요' }] };
  const p = submitForm(form);
  out.during = [drafts.has('d|text'), SENDING.has('k'), ta.readOnly, form.dataset.busy];
  await p;
  out.failed = [drafts.get('d|text'), SENDING.has('k'), ta.readOnly, err.textContent, ta.value, attList('k').length];
  answers = {}; calls.length = 0;
  const q1 = submitForm(form); const q2 = submitForm(form);
  await q1; await q2;
  out.sent = [calls.map(c => c[0]), drafts.has('d|text'), ta.value, attList('k').length, refreshed];
  calls.length = 0; SENDING.add('k'); ta.value = '또'; await submitForm({ dataset: { form: 'say', key: 'k' }, isConnected: true, querySelector: () => ta });
  out.reopened = calls.length; SENDING.delete('k');
  console.log(JSON.stringify(out));
})();
"""
        r = self.node(code)
        self.assertEqual(r["during"], [False, True, True, "1"])
        self.assertEqual(r["failed"], ["그림 봐요", False, False, "잠깐요", "그림 봐요", 1])
        self.assertEqual(r["sent"], [["api/say"], False, "", 0, 1])
        self.assertEqual(r["reopened"], 0)                                                  # 보내는 중에 서랍을 다시 열어도 같은 말을 또 보내지 않아요

    def test_words_only_send_stays_simple(self):
        """사진이 없으면 올리기를 타지 않고, 글칸을 잠그지 않아요."""
        code = self.SEND + page_js("ATT", "ATT_SAY", "attList", "attCount", "post", "attUpload", "attSend", "submitForm") + """
const drafts = new Map(), err = { textContent: '' }, btn = { disabled: false, isConnected: true };
const ta = { name: 'text', value: '글만', form: null, readOnly: false }, form = { dataset: { form: 'say', key: 'k' }, isConnected: true, querySelector: () => ta };
ta.form = form;
const draftKey = t => 'd|' + t.name, hoGrow = () => {}, relayPaint = () => {}, dTab = () => {}, restoreDrafts = () => {}, attFormOf = () => form, attAlso = () => {}, attPaint = () => {};
const $ = (q, f) => (q === '.err' ? err : null), $$ = (q) => (q.includes('submit') ? [btn] : []);
class FormData { constructor() {} get(k) { return { team: 't', thread: 'chat:개발자', text: ta.value }[k]; } getAll() { return []; } }
let state = {}, live = null;
const refreshThread = async () => {};
(async () => {
  const p = submitForm(form); const locked = ta.readOnly; await p;
  answers = { 'api/say': ['net'] }; ta.value = '글'; await submitForm(form);
  console.log(JSON.stringify({ locked, urls: calls.map(c => c[0]), body: Object.keys(calls[0][2]).sort(), net: err.textContent }));
})();
"""
        r = self.node(code)
        self.assertEqual(r["locked"], False)
        self.assertEqual(r["urls"], ["api/say", "api/say"])
        self.assertEqual(r["body"], ["team", "text", "thread"])                             # images 칸이 없어요
        self.assertEqual(r["net"], "연결이 끊겼어요. 글과 사진은 그대로예요.")

    def test_pic_wait_needs_all_three(self):
        """마지막 대표 말에 사진이 있고, 답이 없고, 세션이 확인을 기다릴 때만 나와요."""
        code = self.SEAT + page_js("picWaitPaint") + """
const p = { hidden: true, innerHTML: '' }, $ = q => p, esc = String, chatLink = s => 'claude://' + s;
let live = { tid: 't', seat: '개발자', picAsk: true };
let state = { teams: { t: { team: { members: [{ role: '개발자', sessionId: 'local_x' }] } } } };
const look = () => { picWaitPaint(); return p.hidden; };
const out = {};
out.off = look();
liveFake['개발자'] = { s: 'waiting', since: Date.now() - 9000 }; out.on = look(); out.html = p.innerHTML;
live.picAsk = false; out.noPic = look(); live.picAsk = true;
liveFake['개발자'] = { s: 'busy', since: Date.now() }; out.busy = look();
liveFake['개발자'] = { s: 'waiting', since: Date.now() - 2000 }; out.short = look();
liveFake['개발자'] = { s: 'waiting', since: Date.now() - 9000 }; live.seat = undefined; out.boss = look();
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual((r["off"], r["on"], r["noPic"], r["busy"], r["short"], r["boss"]), (True, False, True, True, True, True))
        self.assertIn("세션이 확인을 기다려요. 사진은 아직 못 봤을 수 있어요.", r["html"])
        self.assertIn('href="claude://local_x"', r["html"])
        self.assertIn("Claude 창 열기", r["html"])

    def test_composer_and_viewer_markup(self):
        html = page_js("composerHTML")
        for part in ('<div class="att-band" hidden>', '<ul class="att" aria-label="보낼 사진">', "세션이 열면 Claude로 보내지고 기록에 남아요.", "복사한 사진은 안 붙였어요.", "data-att-also", 'class="pic-wait" hidden'):
            self.assertIn(part, html)
        self.assertLess(html.index("att-band"), html.index('name="text"'))                  # 띠는 글칸 위예요
        self.assertIn("SAY_KEYS = 'Enter 보내기 · Shift+Enter 줄바꿈 · ⌘V 사진 붙이기'", SRC)
        self.assertIn("@media (max-width:559px)", SRC)
        drawer, view = SRC.index('id="drawerBody"'), SRC.index('id="picView"')
        self.assertLess(drawer, view)
        self.assertNotIn(">세션 창 열기<", SRC)
        self.assertEqual(SRC.count(">Claude 창 열기</a>"), 1)                               # 사진 확인 대기 줄
        self.assertEqual(SRC.count("'Claude 창 열기 ↗'"), 1)                                # 서랍 머리(dHead) 하나를 팀원·총괄 서랍이 같이 써요(직원 서랍은 같은 자리에 [팀장 창 열기])
        self.assertIn("picClose()", page_js("closeDrawer"))

    def test_paste_takes_only_what_the_owner_meant(self):
        """글과 사진이 같이 복사되면 글만 넣어요. 대표가 모르는 사진이 Claude로 가면 안 돼요."""
        code = page_js("attOnPaste") + """
const calls = [], form = {}; let open = true;
const attForm = () => (open ? form : null), attAdd = (f, l) => calls.push('add' + l.length), attAlso = (f, l) => calls.push('also' + l.length);
const img = { type: 'image/png' }, pdf = { type: 'application/pdf' };
const run = (types, files) => { calls.length = 0; const e = { clipboardData: { types, files }, stopped: 0, preventDefault() { this.stopped++; } }; attOnPaste(e); return [calls.join(), e.stopped]; };
const out = { both: run(['text/plain', 'Files'], [img]), pic: run(['Files'], [img]), words: run(['text/plain'], []), pdfWords: run(['text/plain', 'Files'], [pdf]), pdf: run(['Files'], [pdf]) };
open = false; out.closed = run(['Files'], [img]);
console.log(JSON.stringify(out));
"""
        self.assertEqual(self.node(code), {"both": ["also1", 0], "pic": ["add1", 1], "words": ["", 0], "pdfWords": ["", 0], "pdf": ["add1", 1], "closed": ["", 0]})

    def test_drag_rules(self):
        """파일을 끌 때만 막고 서랍 안에서만 받아요. 글을 끄는 것은 그대로예요. 밖에 놓아도 페이지가 넘어가지 않아요."""
        code = page_js("attDrag", "attOnDrag", "attOnDrop", "attOnLeave") + """
const classes = new Set(), panel = { classList: { toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }, remove(c) { classes.delete(c); } } };
const $ = () => panel, form = {}, added = []; let open = true;
const attForm = () => (open ? form : null), attAdd = (f, l) => added.push(l.length);
const ev = (types, target, files = []) => ({ dataTransfer: { types, files, dropEffect: '' }, target, relatedTarget: null, stopped: 0, preventDefault() { this.stopped++; } });
const inside = { closest: () => panel }, outside = { closest: () => null }, F = ['Files'], drop = (t, g) => { const e = ev(t, g, [{}, {}]); attOnDrop(e); return e.stopped; };
const over = g => { const e = ev(F, g); attOnDrag(e); return [e.stopped, e.dataTransfer.dropEffect, classes.has('dropping')]; }, out = {};
out.inside = over(inside); out.outside = over(outside); out.again = over(inside);
attOnLeave({ relatedTarget: {} }); out.stay = classes.has('dropping'); attOnLeave({ relatedTarget: null }); out.left = classes.has('dropping');
const words = ev(['text/plain'], inside); attOnDrag(words); out.words = words.stopped;
over(inside); out.dropIn = [drop(F, inside), added.slice(), classes.has('dropping')];
out.dropOut = [drop(F, outside), added.length]; out.dropWords = [drop(['text/plain'], inside), added.length];
open = false; out.closed = [drop(F, inside), added.length, over(inside)[2]];
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual((r["inside"], r["outside"], r["again"]), ([1, "copy", True], [1, "none", False], [1, "copy", True]))
        self.assertEqual((r["stay"], r["left"], r["words"]), (True, False, 0))
        self.assertEqual(r["dropIn"], [1, [2], False])
        self.assertEqual(r["dropOut"], [1, 1])                                              # 막아요. 받지는 않아요
        self.assertEqual(r["dropWords"], [0, 1])
        self.assertEqual(r["closed"], [1, 1, False])

    def test_enter_sends_words_or_pictures(self):
        code = page_js("ATT", "attCount", "sayKey") + """
const IME_GAP = 100, performance = { now: () => 1000 }, btn = { disabled: false };
let sent = 0;
const form = { dataset: { key: 'k' }, querySelector: () => btn, requestSubmit() { sent++; } }, t = { value: '', form };
const press = (o = {}, setup = () => {}) => { sent = 0; t.value = ''; ATT.delete('k'); delete form.dataset.busy; btn.disabled = false; t._imeEnd = undefined; setup(); const e = Object.assign({ isComposing: false, keyCode: 13, shiftKey: false, repeat: false, stopped: 0, preventDefault() { this.stopped++; } }, o); sayKey(e, t); return [sent, e.stopped]; };
const chip = () => ATT.set('k', [{}]);
console.log(JSON.stringify({ empty: press(), words: press({}, () => { t.value = '글'; }), spaces: press({}, () => { t.value = '  '; }), pic: press({}, chip), shift: press({ shiftKey: true }, chip), ime: press({ isComposing: true }, chip), ime2: press({ keyCode: 229 }, chip), justIme: press({}, () => { chip(); t._imeEnd = 950; }), repeat: press({ repeat: true }, chip), busy: press({}, () => { chip(); form.dataset.busy = '1'; }), off: press({}, () => { chip(); btn.disabled = true; }) }));
"""
        r = self.node(code)
        self.assertEqual((r["empty"], r["words"], r["spaces"], r["pic"]), ([0, 1], [1, 1], [0, 1], [1, 1]))
        self.assertEqual((r["shift"], r["ime"], r["ime2"]), ([0, 0], [0, 0], [0, 0]))        # 줄바꿈과 조합 중에는 건드리지 않아요
        self.assertEqual((r["justIme"], r["repeat"], r["busy"], r["off"]), ([0, 1], [0, 1], [0, 1], [0, 1]))

    def test_picture_view_keeps_the_keyboard_inside(self):
        """크게 보기는 뒤 화면을 막아요. 첫 Esc는 크게 보기만 닫고 초점은 사진으로 돌아가요."""
        code = page_js("PV", "picOpen", "picClose", "picOnKey", "updInert") + """
let focused = '';
const el = name => ({ hidden: true, inert: false, focus() { focused = name; }, removeAttribute(k) { delete this[k]; } });
const els = { '#picView': el('view'), '#picBig': el('big'), '#picClose': el('close'), '#drawer': el('drawer'), '.wrap': el('wrap'), '#setup': el('setup'), '#drawerClose': el('drawerClose') };
const $ = q => els[q], SU = { open: false }, document = { body: { style: {} } }, btn = { dataset: { pic: 'u', alt: '대표 사진' }, isConnected: true, focus() { focused = 'btn'; } };
const key = (k = 'Escape', o = {}) => { const e = Object.assign({ key: k, isComposing: false, stopped: 0, killed: 0, preventDefault() { this.stopped++; }, stopImmediatePropagation() { this.killed++; } }, o); picOnKey(e); return e.killed; };
const look = () => ({ view: !els['#picView'].hidden, drawer: els['#drawer'].inert, wrap: els['#wrap'] ? 0 : els['.wrap'].inert, focused, src: els['#picBig'].src || '' }), out = {};
out.closedKey = key();
picOpen(btn); out.open = look(); out.alt = els['#picBig'].alt;
out.composing = key('Escape', { isComposing: true }); out.other = key('a');
out.first = key(); out.shut = look(); out.second = key();
SU.open = true; picOpen(btn); key(); out.setupOpen = els['.wrap'].inert; SU.open = false;
picOpen(btn); btn.isConnected = false; key(); out.gone = focused; btn.isConnected = true;
picOpen(btn); updInert(true); out.upd = { view: !els['#picView'].hidden, inert: els['#picView'].inert, drawer: els['#drawer'].inert, wrap: els['.wrap'].inert, setup: els['#setup'].inert };
updInert(false); out.back = { inert: els['#picView'].inert, drawer: els['#drawer'].inert, wrap: els['.wrap'].inert };
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["closedKey"], 0)
        self.assertEqual(r["open"], {"view": True, "drawer": True, "wrap": True, "focused": "close", "src": "u"})
        self.assertEqual(r["alt"], "대표 사진")
        self.assertEqual((r["composing"], r["other"], r["first"], r["second"]), (0, 0, 1, 0))
        self.assertEqual(r["shut"], {"view": False, "drawer": False, "wrap": False, "focused": "btn", "src": ""})
        self.assertTrue(r["setupOpen"])                                                     # 설정이 열려 있으면 뒤는 그대로 막혀 있어요
        self.assertEqual(r["gone"], "drawerClose")
        self.assertEqual(r["upd"], {"view": False, "inert": True, "drawer": True, "wrap": True, "setup": True})
        self.assertEqual(r["back"], {"inert": False, "drawer": False, "wrap": False})

    def test_refresh_knows_when_a_picture_waits(self):
        """마지막 줄이 대표의 사진일 때만 켜져요. 그 뒤 답이 오면 꺼져요."""
        code = self.REFRESH + page_js("thPinned", "talkSeen", "refreshThread") + """
const M = o => JSON.stringify(Object.assign({ t: 'x', from: '대표', text: '글' }, o)) + '\\n';
(async () => {
  const out = {};
  file = M({}); await refreshThread(true); out.words = live.picAsk;
  file += M({ img: ['a.png'] }); await refreshThread(); out.pic = live.picAsk;
  file += M({ from: '개발자' }); await refreshThread(); out.reply = live.picAsk;
  file += M({ from: '개발자', img: ['b.png'] }); await refreshThread(); out.theirs = live.picAsk;
  file = ''; await refreshThread(true); out.empty = live.picAsk;
  console.log(JSON.stringify(out));
})();
"""
        self.assertEqual(self.node(code), {"words": False, "pic": True, "reply": False, "theirs": False, "empty": False})

    STRIP = """
const SIZE = { line: 60 };
const ta = { required: true }, band = { _h: true, get hidden() { return this._h; }, set hidden(v) { if (v !== this._h) th.clientHeight += v ? SIZE.line : -SIZE.line; this._h = v; } };
const th = { scrollHeight: 1000, clientHeight: 300, _t: 700, get scrollTop() { return this._t; }, set scrollTop(v) { this._t = Math.max(0, Math.min(v, this.scrollHeight - this.clientHeight)); } };
let tall = false;   // 칩이 4장이면 칩 옆 글이 두 줄로 내려가 띠가 22px 높아져요(대화 칸이 그만큼 줄어요)
const ul = { _h: '', get innerHTML() { return this._h; }, set innerHTML(v) { const t = (v.match(/<li/g) || []).length >= 4; if (t !== tall) th.clientHeight += t ? -22 : 22; tall = t; this._h = v; }, closest: () => band };
const form = { dataset: { key: 'k' }, closest: () => true }, esc = String;
const $ = (q, f) => ({ '.att': ul, '#thread': th, 'textarea[name="text"]': ta })[q];
const pic = (n, st = '') => ({ id: n, url: 'blob:' + n, st, name: '' });
"""

    def test_chip_strip_keeps_the_last_line_in_view(self):
        """칩이 생겨 대화 칸이 줄어도 맨 아래를 따라가요. 위를 읽던 중이면 그대로 둬요."""
        code = self.STRIP + page_js("ATT", "thPinned", "attList", "attPaint") + """
const out = {};
const end = () => th.scrollHeight - th.scrollTop - th.clientHeight;
attList('k').push(pic(1)); attPaint(form);
out.one = { shown: !band.hidden, required: ta.required, end: end(), html: ul.innerHTML };
attList('k').push(pic(2, 'up'), pic(3, 'bad')); attPaint(form); out.three = ul.innerHTML;
attList('k').splice(0); attPaint(form); out.none = { shown: !band.hidden, required: ta.required };
th.scrollTop = 100; attList('k').push(pic(4)); attPaint(form); out.reading = th.scrollTop;
SENDING.add('k'); attPaint(form); out.busy = form.dataset.busy; SENDING.delete('k');
attList('k').splice(0); attPaint(form); th.scrollTop = 9999; attList('k').push(pic(5), pic(6), pic(7)); attPaint(form);
attList('k').push(pic(8)); attPaint(form); out.twoLines = end();   // 칩 옆 글이 아래로 내려가 띠가 높아져도 맨 아래예요
th.scrollTop = 0; attList('k').pop(); attPaint(form); attList('k').push(pic(9)); attPaint(form); out.readingTop = th.scrollTop;
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual((r["one"]["shown"], r["one"]["required"], r["one"]["end"]), (True, False, 0))
        self.assertIn('alt="붙인 사진 1"', r["one"]["html"])
        self.assertIn('aria-label="사진 빼기"', r["one"]["html"])
        self.assertIn('aria-label="사진 2 빼기"', r["three"])
        self.assertIn('data-st="up" aria-label="사진 올리는 중"', r["three"])
        self.assertIn('data-st="bad"', r["three"])
        self.assertEqual(r["none"], {"shown": False, "required": True})
        self.assertEqual(r["reading"], 100)
        self.assertEqual(r["busy"], "1")                                                    # 보내는 중에 다시 연 작성창도 잠겨요
        self.assertEqual(r["twoLines"], 0)
        self.assertEqual(r["readingTop"], 0)

    FIT = """
let size = [100, 100], broken = false, drawn = null, shrunk = 1000, n = 0;
const URL = { createObjectURL: () => 'u' + (++n), revokeObjectURL() {} }, err = { textContent: '' };
class Image { set src(v) { this.naturalWidth = size[0]; this.naturalHeight = size[1]; setTimeout(() => (broken ? this.onerror() : this.onload())); } }
const document = { createElement: () => ({ width: 0, height: 0, getContext: () => ({ fillRect() {}, drawImage(i, x, y, w, h) { drawn = [w, h]; tries.push([w, h]); } }), toBlob(cb, type) { cb({ size: Array.isArray(shrunk) ? shrunk.shift() : shrunk, type }); } }) };
let tries = [];
const attRepaint = () => {}, attPaint = () => {}, attFormOf = () => ({}), $ = () => err;
const MB = 1024 * 1024;
const run = async (type, bytes, w, h, o = {}) => {
  size = [w, h]; broken = !!o.broken; shrunk = o.shrunk || 1000; drawn = null; tries = []; err.textContent = '';
  const a = { id: 1, blob: { type, size: bytes }, url: 'u0', st: '', name: '' }; ATT.set('k', [a]);
  await attFit(a, 'k');
  return { kept: attList('k').length, type: a.blob.type, drawn, tries, err: err.textContent };
};
"""

    def test_attach_fit(self):
        """상한 안의 사진은 그대로 보내요. 크기, 픽셀, 긴 변 중 하나라도 넘으면 줄여요. GIF는 조용히 멈춘 그림으로 바꾸지 않아요."""
        code = self.FIT + page_js("ATT", "ATT_SAY", "attList", "attDrop", "attRefuse", "attFit") + """
(async () => console.log(JSON.stringify({
  small: await run('image/png', 2 * MB, 1000, 800), edge: await run('image/png', 2 * MB, 12000, 2000), side: await run('image/png', 2 * MB, 1000, 13000), wide: await run('image/png', 2 * MB, 12001, 100),
  pixels: await run('image/jpeg', 5 * MB, 6000, 5000), bytes: await run('image/png', 12 * MB, 3000, 2000), tiny: await run('image/png', 11 * MB, 800, 600),
  gifBig: await run('image/gif', 12 * MB, 800, 600), gifPixels: await run('image/gif', MB, 6000, 5000), gifOk: await run('image/gif', MB, 800, 600),
  brokenOk: await run('image/png', 2 * MB, 10, 10, { broken: true }), brokenBig: await run('image/png', 12 * MB, 10, 10, { broken: true }), stillBig: await run('image/png', 12 * MB, 3000, 2000, { shrunk: 11 * MB }),
  heavy: await run('image/png', 8 * MB, 6000, 5000, { shrunk: [11 * MB, MB] }),
})))();
"""
        r = self.node(code)
        for k in ("small", "edge", "gifOk", "brokenOk"):
            self.assertEqual((r[k]["kept"], r[k]["drawn"]), (1, None), k)                   # 그대로예요
        self.assertEqual((r["side"]["drawn"], r["side"]["type"]), ([923, 12000], "image/jpeg"))   # 긴 캡처는 글이 읽히게 긴 변 12000 안으로만 줄여요
        self.assertEqual(r["wide"]["drawn"], [12000, 99])
        self.assertEqual(r["pixels"]["drawn"], [5366, 4472])                                # 2400만 화소 안으로만
        self.assertLessEqual(5366 * 4472, 24000000)
        self.assertEqual(r["heavy"]["tries"], [[5366, 4472], [2400, 2000]])                 # 줄여도 10MB가 넘으면 긴 변 2400으로 한 번 더
        self.assertEqual(r["heavy"]["kept"], 1)
        self.assertEqual(r["bytes"]["drawn"], [2400, 1600])
        self.assertEqual(r["tiny"]["drawn"], [800, 600])                                    # 작은 그림을 키우지 않아요
        for k in ("gifBig", "gifPixels"):
            self.assertEqual((r[k]["kept"], r[k]["drawn"]), (0, None), k)
            self.assertEqual(r[k]["err"], "GIF가 너무 커서 안 붙였어요. 여기서 줄이면 움직임이 사라져요.")
        for k in ("brokenBig", "stillBig"):
            self.assertEqual((r[k]["kept"], r[k]["err"]), (0, "사진이 너무 커요. 10MB 안으로 줄여서 붙여요."), k)

    def test_focus_after_attach_and_remove(self):
        """붙이면 글칸으로 가서 Enter가 [닫기]를 누르지 않아요. 칩을 빼면 다음 ✕나 글칸으로 가요."""
        code = page_js("ATT", "ATT_SAY", "attList", "attFocus", "attAdd", "attDrop", "attRemove") + """
let ATT_SEQ = 0;
const URL = { createObjectURL: () => 'b', revokeObjectURL() {} }, err = { textContent: '' };
let focused = '', chips = [];
const box = name => ({ name, matches: q => q === 'textarea', closest: () => form, focus() { focused = name; } }), ta = box('글칸'), goal = box('목표'), form = { dataset: { key: 'k', ho: '0' } };
const closeBtn = { matches: () => false, closest: () => null };
const document = { activeElement: closeBtn };
const $ = (q, f) => (q === '.err' ? err : q === 'textarea[name="text"]' ? ta : q === 'textarea[data-ho="goal"]' ? goal : null), $$ = () => chips;
const attFit = async () => {}, attAlso = () => {}, attPaint = () => { chips = attList('k').map((a, i) => ({ focus() { focused = '✕' + i; } })); }, f = { type: 'image/png', name: 'a.png', size: 1 };
const out = {};
attAdd(form, [f]); out.closeBtn = focused;
focused = ''; form.dataset.ho = '1'; attAdd(form, [f]); out.ho = focused; form.dataset.ho = '0';
focused = ''; document.activeElement = goal; attAdd(form, [f]); out.alreadyTyping = focused;
document.activeElement = closeBtn; focused = ''; attList('k').push({ id: 9, url: 'x' });
const list = attList('k');
attRemove(form, list[0], true); out.next = focused;                                  // 키보드로 뺐어요
attRemove(form, list[list.length - 1], true); out.last = focused;
attRemove(form, list[0], true); attRemove(form, list[0], true); out.none = focused;
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual((r["closeBtn"], r["ho"], r["alreadyTyping"]), ("글칸", "목표", ""))
        self.assertEqual((r["next"], r["last"], r["none"]), ("✕0", "✕1", "글칸"))

    def test_chip_clicks(self):
        """마우스로 ✕를 누르면 글칸으로 가요(보이지 않는 ✕에 초점이 가면 친 글이 사라지고 Enter가 사진을 또 빼요). 키보드면 다음 ✕로 가요."""
        code = page_js("ATT", "ATT_SAY", "attList", "attFocus", "attDrop", "attRemove", "attOnClick") + """
const URL = { revokeObjectURL() {} }, err = { textContent: '' }, added = [], opened = [];
let focused = '', chips = [], ATT_ALSO = null;
const ta = { matches: q => q === 'textarea', closest: () => form, focus() { focused = '글칸'; } }, form = { dataset: { key: 'k', ho: '0' } };
const document = { activeElement: null }, picOpen = p => opened.push(p), picClose = () => {}, attAdd = (f, l) => added.push(l.length);
const $ = (q, f) => (q === '.err' ? err : q === 'textarea[name="text"]' ? ta : null), $$ = () => chips;
const attPaint = () => { chips = attList('k').map((a, i) => ({ focus() { focused = '✕' + i; } })); };
const target = (sel, el) => ({ id: '', closest: q => (q === sel ? el : null) });
const x = id => ({ dataset: { attX: String(id) }, closest: q => (q === 'form' ? form : null) });
const click = (id, detail) => { focused = ''; attOnClick({ target: target('[data-att-x]', x(id)), detail }); return [focused, attList('k').length]; };
ATT.set('k', [1, 2, 3, 4, 5].map(id => ({ id, url: 'b' })));
const out = { mouse: click(1, 1), key: click(2, 0), keyLast: click(5, 0) };
SENDING.add('k'); out.sending = click(3, 1); SENDING.delete('k');
ATT_ALSO = [{}, {}]; attOnClick({ target: target('[data-att-also]', { closest: () => form }), detail: 1 }); out.also = added;
const p = {}; attOnClick({ target: target('[data-pic]', p), detail: 1 }); out.pic = opened.length;
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["mouse"], ["글칸", 4])
        self.assertEqual(r["key"], ["✕0", 3])
        self.assertEqual(r["keyLast"], ["✕1", 2])
        self.assertEqual(r["sending"], ["", 2])                                             # 보내는 중에는 빠지지 않아요
        self.assertEqual((r["also"], r["pic"]), ([2], 1))

    def test_reopened_drawer_shows_its_chips(self):
        """다시 연 서랍에도 칩이 보여요. 안 보이는 사진이 다음 말에 같이 가면 안 돼요."""
        code = page_js("restoreDrafts") + """
const painted = [], drafts = new Map([['d', '쓰던 글']]), ta = { value: '' }, forms = [{ id: 1 }, { id: 2 }];
const $$ = q => (q.includes('textarea') ? [ta] : forms), draftKey = () => 'd', hoGrow = () => {}, attPaint = f => painted.push(f.id);
restoreDrafts();
console.log(JSON.stringify({ painted, text: ta.value }));
"""
        self.assertEqual(self.node(code), {"painted": [1, 2], "text": "쓰던 글"})

    def test_lost_picture_or_short_outage(self):
        """없는 사진(404)과 잠깐 끊긴 것을 나눠요. 끊긴 것은 다시 받아요."""
        code = page_js("PIC_RETRY", "picFail") + """
let answer = 404, later = [];
const setTimeout = fn => later.push(fn), fetch = async () => { if (answer === 'net') throw new TypeError('끊김'); return { status: answer }; };
const pic = () => { const b = { dataset: { pic: 'u?v=1' }, disabled: false, textContent: '', classList: { list: [], add(c) { this.list.push(c); } } }; return { b, isConnected: true, src: 'u?v=1', dataset: {}, closest: () => b, removed: 0, remove() { this.removed++; } }; };
(async () => {
  const out = {};
  let i = pic(); await picFail(i); out.gone = [i.b.classList.list, i.b.disabled, i.b.textContent, i.removed, later.length];
  later = []; answer = 'net'; i = pic(); await picFail(i); out.net = [[...i.b.classList.list], i.b.disabled, i.removed, later.length];
  later.shift()(); out.retried = i.src.startsWith('u?v=1&r=');
  answer = 503; await picFail(i); out.down = [i.b.classList.list.length, later.length];
  later.shift()(); await picFail(i); later.shift()(); await picFail(i); out.giveUp = [i.b.classList.list, i.b.textContent, later.length];
  later = []; answer = 'net'; i = pic(); i.isConnected = false; await picFail(i); out.closed = later.length;
  console.log(JSON.stringify(out));
})();
"""
        r = self.node(code)
        self.assertEqual(r["gone"], [["pic-miss"], True, "사진을 찾지 못했어요", 1, 0])
        self.assertEqual(r["net"], [[], False, 0, 1])                                       # 칸은 그대로 두고 다시 받아요
        self.assertTrue(r["retried"])
        self.assertEqual(r["down"], [0, 1])
        self.assertEqual(r["giveUp"], [["pic-miss"], "사진을 불러오지 못했어요. 서랍을 다시 열어요.", 0])
        self.assertEqual(r["closed"], 0)

    def test_drawer_facts_follow_the_session(self):
        """서랍의 상태, 맡은 일, 한마디는 명단과 같은 값이에요. 맡은 일이 없으면 —예요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView", "seatChip", "seatDot", "drawerFacts") + """
const esc = String, viewNow = () => NOW, meetNow = () => null, isCxx = 0;
let state = { teams: { t: { team: { members: [{ role: '개발자', sessionId: 'local_x' }] }, status: { 개발자: { state: '대기', task: '', say: '', updated: ago(5) } } } } };
const rel = iso => '방금'; const a = drawerFacts('t', '개발자', rel); liveFake['개발자'] = { s: 'busy', since: NOW }; const b = drawerFacts('t', '개발자', rel);
liveFake['개발자'] = { s: 'quiet', since: NOW - 2e6 }; const c = drawerFacts('t', '개발자', rel); delete liveFake['개발자'];
state.teams.t.status.개발자 = { state: '일하는 중', updated: ago(420) }; const d = drawerFacts('t', '개발자', rel);
console.log(JSON.stringify({ a, b, c, d }));
"""
        r = self.node(code)
        self.assertEqual(r["a"], {"state": "대기 · 방금", "task": "—", "say": "—", "dot": "d-idle", "wait": False})
        self.assertEqual(r["b"], {"state": "일하는 중 · 방금", "task": "—", "say": "—", "dot": "d-work", "wait": False})
        self.assertEqual(r["d"]["dot"], "")                                                  # 소식이 없으면 상태 색을 칠하지 않아요
        self.assertEqual(r["c"]["state"], "일하는 중 · 응답 없음? · 방금")          # 명단과 같은 칩이에요
        self.assertEqual(r["d"]["state"], "소식 없음 · 방금")
        for bit in ('id="dfState"', 'id="dfTask"', 'id="dfSay"', "drawerPaint()"):
            self.assertIn(bit, SRC)

    def test_tab_return_reads_before_it_settles(self):
        """숨겼던 탭에 돌아오면 새 상태를 읽은 뒤에 지금 자리로 옮겨요. 걸음을 재생하지 않아요. 끊겼으면 옮기지 않아요. load를 안 부르는 때는 바로 해요."""
        i, mark = SRC.index("if (!stageRest()) stageSettle()"), "document.addEventListener('visibilitychange', "
        back = SRC[SRC.rindex(mark, 0, i) + len(mark):SRC.index("\n});", i) + 2]
        code = self.FAKE + page_js(*GLUE) + """
const UPD = { ov: false }; let log = [], next = null, loads = 0;
const back = """ + back + """;
const load = async () => { loads++; await null; if (next) next(); stageSync(); };
const flush = () => new Promise(r => setTimeout(r, 5));
(async () => {
  slot = mk('slot'); stageMount(state.org.teams[0], state.teams.a);
  const sc = STAGE.scene, up = sc.update, go = sc.step;
  sc.update = v => { log.push(v.members[0].state); up(v); };
  sc.step = () => { if (log[log.length - 1] !== 'step') log.push('step'); go(); };
  const run = async (f) => { log = []; loads = 0; sc.steps = 0; next = f; await back(); await flush(); return { log: log.slice(), steps: sc.steps, loads }; };
  const out = {};
  out.news = await run(() => { state.s = '회의 중'; });
  out.lost = await run(() => { state.live = false; }); state.live = true;
  UPD.ov = true; out.update = await run(); UPD.ov = false;
  SU.open = true; out.setup = await run(); SU.open = false;
  out.again = await run(() => { document.hidden = true; }); document.hidden = false;
  console.log(JSON.stringify(out));
})();
"""
        r = self.node(code)
        self.assertEqual(r["news"]["log"][-2:], ["회의 중", "step"])        # 새 상태를 받은 뒤에 정산해요
        self.assertEqual(r["news"]["log"].count("step"), 1)
        self.assertEqual(r["news"]["steps"], 150)
        self.assertEqual(r["lost"]["steps"], 0)                             # 숨은 동안 서버가 꺼졌어요
        self.assertEqual((r["update"]["loads"], r["update"]["steps"]), (0, 150))
        self.assertEqual((r["setup"]["loads"], r["setup"]["steps"]), (0, 150))   # 지금처럼 바로 해요
        self.assertEqual(r["again"]["steps"], 0)                            # 읽는 사이 다시 숨겼어요

    def test_stage_line_only_when_special(self):
        """장면 아래 한 줄은 특별한 때만: 아무도 없음, 팀장 없음, 다 같이 회의·대기, 움직임 줄이기, 예시 팀."""
        code = page_js("stageLine") + """
const LEAD = '팀장', stageStill = { matches: false }, t = { office: 'a' }, ms = [{ role: '팀장' }, { role: '개발자' }];
const v = (a, b) => [a, b].map(s => ({ state: s, kind: s === '빈자리' ? 'vacant' : 'member' })), L = (a, b) => stageLine(t, ms, v(a, b));
const out = { empty: L('빈자리', '빈자리'), noLead: L('빈자리', '대기'), meet: L('회의 중', '회의 중'), idle: L('대기', '대기'), mixed: L('대기', '일하는 중'), example: stageLine({ office: 'examples/x' }, ms, v('대기', '대기')) };
stageStill.matches = true; out.reduced = L('대기', '일하는 중');
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["mixed"], "")
        self.assertEqual(r["meet"], "다들 회의실에 있어요.")
        self.assertEqual(r["idle"], "다들 다음 일을 기다려요.")
        self.assertEqual(r["reduced"], "기기 설정대로 움직임을 줄였어요.")
        self.assertIn("아직 아무도 없어요", r["empty"])
        self.assertIn("팀장이 없으면", r["noLead"])
        self.assertIn("예시 팀", r["example"])

    def test_select_opens_same_drawer(self):
        """사람이나 책상을 누르면 책상과 같은 서랍(memberDrawer), Codex도 같아요. 빈자리는 명단의 [세션 만들기]로."""
        code = page_js("stageSelect", "STAFF_RE", "skOn", "isSk") + """
const calls = [], isCx = m => !!m.codexId, stageStill = { matches: true };
const row = id => ({ dataset: { member: id }, focus() { calls.push(['focus', 'row', id]); }, scrollIntoView() { calls.push(['scroll', id]); } });
const seatBtn = { focus() { calls.push(['focus', 'seat']); } };
const $$ = () => ['개발자', 'cx', 'QA'].map(row), $ = (s, r) => (s.startsWith('[data-seat]') ? seatBtn : { focus() { calls.push(['focus', r.dataset.member]); } });
const memberDrawer = (t, r) => calls.push(['drawer', t, r]);
const state = { teams: { t: { team: { members: [{ role: '개발자', sessionId: 'local_a' }, { role: 'cx', codexId: 'abc' }, { role: 'QA' }] } } } };
for (const id of ['개발자', 'cx', 'QA', '없는 사람']) stageSelect('t', id);
console.log(JSON.stringify(calls));
"""
        self.assertEqual(self.node(code), [["focus", "개발자"], ["drawer", "t", "개발자"], ["focus", "cx"], ["drawer", "t", "cx"],
                                           ["scroll", "QA"], ["focus", "seat"]])

    SCENE = """
const said = [], listeners = {}, count = { bakes: 0 }, noop = () => {};
const calls = { measureText: x => ({ width: String(x).length * 7 }), getImageData: () => { count.bakes++; return { data: new Uint8ClampedArray(96 * 16 * 4) }; }, fillText: x => said.push(x) };
const ctx = () => new Proxy({}, { get: (t, k) => (k in t ? t[k] : calls[k] || noop), set: (t, k, v) => { t[k] = v; return true; } });
const canvas = () => ({ style: {}, width: 0, height: 0, getContext() { return this.c || (this.c = ctx()); }, toDataURL: () => 'data:image/png;base64,AA', setAttribute() {}, addEventListener(k, f) { listeners[k] = f; }, removeEventListener(k) { delete listeners[k]; }, remove() { this.gone = true; }, getBoundingClientRect: () => ({ left: 0, top: 0, width: 960, height: 538 }) });
const document = { createElement: canvas }, window = { devicePixelRatio: 1 };
const el = { appendChild(c) { this.cv = c; }, getBoundingClientRect: () => ({ width: 960, height: 538 }) };
"""

    STAFF = """
const m = (id, state, o) => Object.assign({ id, role: id, name: '', lead: false, codex: false, look: {}, state, task: '', say: '', newReply: false, quiet: '', hours: 0, missing: false, invited: false, waitingSeat: false }, o);
const st = (members, meeting) => ({ tone: 'a', name: 'x', floor: 2, theme: 'light', members, meeting: meeting || { active: false, topic: '', phase: 'live', mode: 'team' } });
const sc = window.createOfficeScene(el, { seed: 1, reducedMotion: false });
"""

    def test_voxel_scene_keeps_promise(self):
        """복셀 장면이 약속을 지켜요: 첫 update에서 바로 그리고, 같은 값을 다시 넘겨도 자리를 되돌리지 않고, 사람과 빈 책상을 알려 주고, portrait(id)로 얼굴을 줘요."""
        code = self.SCENE + scene_code() + self.STAFF + """
const picked = [], hov = [];
sc.on('select', id => picked.push(id)); sc.on('hover', (id, x, y) => hov.push([id, x, y]));
const team = () => [m('팀장', '일하는 중', { lead: true }), m('개발자', '대기'), m('QA', '빈자리')];
sc.update(st(team()));
const firstBake = count.bakes;
const heads = () => { hov.length = 0; for (let y = 4; y < 538; y += 8) for (let x = 4; x < 960; x += 8) listeners.pointermove({ clientX: x, clientY: y }); listeners.pointerleave(); const o = {}; for (const h of hov) if (h[0] && !o[h[0]]) o[h[0]] = [Math.round(h[1]), Math.round(h[2])]; return o; };
for (let i = 0; i < 300; i++) sc.step(0.05);
const before = heads();
sc.update(st(team())); sc.draw();
const after = heads();
for (let y = 4; y < 538; y += 8) for (let x = 4; x < 960; x += 8) listeners.click({ clientX: x, clientY: y });
const faces = [sc.portrait('개발자'), sc.portrait('없는 사람')];
sc.highlight('개발자'); sc.highlight(null);
const noOwnLoop = ['start', 'stop', 'pause', 'resume', '_debug'].filter(k => k in sc);
sc.destroy();
console.log(JSON.stringify({ firstBake, before, after, picked: [...new Set(picked)].sort(), faces, noOwnLoop, gone: Object.keys(listeners).length, removed: !!el.cv.gone }));
"""
        r = self.node(code)
        self.assertEqual(r["firstBake"], 1)                  # 첫 update에서 바로 그려요
        self.assertEqual(sorted(r["before"]), ["QA", "개발자", "팀장"])
        self.assertEqual(r["before"]["팀장"], r["after"]["팀장"])      # 같은 값: 자리를 되돌리지 않아요
        self.assertEqual(r["picked"], ["QA", "개발자", "팀장"])         # 빈 책상도 골라져요
        self.assertEqual(r["faces"], ["data:image/png;base64,AA", ""])
        self.assertEqual(r["noOwnLoop"], [])
        self.assertEqual(r["gone"], 0)
        self.assertTrue(r["removed"])

    def test_voxel_scene_says_what_the_page_says(self):
        """장면의 표지: 빈자리, 팀장 빈자리, Enter 기다림, 기록 없음, n시간째 소식 없음, 대표 자리, 아직 안 왔어요. 회의록 정리 중은 장면 칸의 배지 하나만 말해요."""
        code = self.SCENE + scene_code() + self.STAFF + """
sc.update(st([m('팀장', '빈자리', { lead: true }), m('A', '빈자리'), m('B', '빈자리', { waitingSeat: true }), m('C', '빈자리', { missing: true, codex: true }), m('D', '일하는 중', { quiet: 'long', hours: 7 }), m('E', '회의 중'), m('F', '대기', { invited: true })],
  { active: true, topic: '주제', phase: 'live', mode: 'boss' }));
const live = [...new Set(said)]; said.length = 0;
sc.update(st([m('팀장', '대기', { lead: true })], { active: true, topic: '주제', phase: 'wrap', mode: 'boss' }));
const wrap = [...new Set(said)]; said.length = 0;
sc.update(st([m('팀장', '회의 중', { lead: true })], { active: true, topic: '주제', phase: 'live', mode: 'team' }));
console.log(JSON.stringify({ live, wrap, team: said }));
"""
        r = self.node(code)
        for text in ("팀장 빈자리", "빈자리", "Enter를 기다려요", "Codex · 기록을 찾지 못했어요", "7시간째 소식 없음", "대표 자리", "F · 아직 안 왔어요"):
            self.assertIn(text, r["live"])
        self.assertNotIn("회의록 정리 중", r["wrap"])
        self.assertNotIn("대표 자리", r["wrap"])
        self.assertNotIn("대표 자리", r["team"])            # 위임 회의에는 대표 자리가 없어요

    def test_quiet_person_stays_at_desk(self):
        """6시간 넘게 소식 없는 사람은 사라지지 않고 자기 자리에 앉아 있어요(팀장 결정). 고개도 안 돌리고, 이름표 점은 회색이에요."""
        code = self.SCENE + scene_code() + self.STAFF + """
const hov = []; sc.on('hover', (id, x, y) => hov.push([id, x, y]));
const place = () => { hov.length = 0; for (let y = 4; y < 538; y += 8) for (let x = 4; x < 960; x += 8) listeners.pointermove({ clientX: x, clientY: y }); listeners.pointerleave(); const h = hov.find(q => q[0] === 'D'); return h ? [Math.round(h[1]), Math.round(h[2])] : null; };
const team = [m('팀장', '일하는 중', { lead: true }), m('D', '일하는 중', { quiet: 'long', hours: 7 })];
sc.update(st(team));
const first = place(); for (let i = 0; i < 200; i++) sc.step(0.05);
const later = place(); said.length = 0; sc.draw();
console.log(JSON.stringify({ first, later, said: [...new Set(said)] }));
"""
        r = self.node(code)
        self.assertIsNotNone(r["first"])                     # 사람이 있어요
        self.assertEqual(r["first"], r["later"])             # 돌아다니지 않아요
        self.assertIn("D", r["said"])
        self.assertIn("7시간째 소식 없음", r["said"])

    def test_quiet_person_bows_and_stays_still(self):
        """숙이는 동안만 움직이고, 숙인 뒤에는 숨쉬기 없이 멈춘 그림이에요. 움직임 줄이기는 step 없이 바로 그 자세예요."""
        code = self.SCENE + scene_code() + self.STAFF + """
let log = []; calls.setTransform = (...a) => log.push(a.map(v => v.toFixed(1)).join());   // 1에 다가가는 값이라 눈에 안 보이는 끝자리는 버려요
const shot = s => { log = []; s.draw(); return log.join('|'); };
const ms = q => [m('D', '일하는 중', q ? { quiet: 'long', hours: 7 } : {})], wide = () => st(ms(true));
sc.update(st(ms(false))); for (let i = 0; i < 40; i++) sc.step(0.05);
sc.update(wide());
const before = shot(sc); for (let i = 0; i < 240; i++) sc.step(0.05);
const bowed = shot(sc); for (let i = 0; i < 240; i++) sc.step(0.05);
const later = shot(sc);
const still = window.createOfficeScene(el, { seed: 1, reducedMotion: true });
still.update(st(ms(false))); const up = shot(still); still.update(wide());
const fast = shot(still);
const held = window.createOfficeScene(el, { seed: 1, reducedMotion: false });
held.update(wide());
console.log(JSON.stringify({ moved: before !== bowed, stopped: bowed === later, reducedAtOnce: up !== fast, firstPaintBowed: shot(held) === bowed }));
"""
        self.assertEqual(self.node(code), {"moved": True, "stopped": True, "reducedAtOnce": True, "firstPaintBowed": True})

    WATCH = """
const S = sc._debug(), P = () => S.plan, run = (secs, f) => { for (let i = 0, n = Math.round(secs * 30); i < n; i++) { sc.step(1 / 30); if (f) f(i / 30); } };
const floor = (n, state) => Array.from({ length: n }, (_, i) => m('사람' + i, state, { lead: !i }));
const boss = { active: true, topic: '주제', phase: 'live', mode: 'boss' };
"""

    def test_lamp_only_at_work(self):
        """등은 일하는 중과 막힘에만 켜요. 30분 넘은 일하는 중도 켜지고, 대기·회의 중·6시간 넘으면 꺼져요."""
        src = scene_code()
        rule = re.search(r"const lampOff = (.*?);", src).group(1)
        code = "const WORK = '일하는 중', STUCK = '막힘', lampOff = " + rule + """;
const t = (state, o) => lampOff(Object.assign({ state, quiet: '', missing: false }, o));
console.log(JSON.stringify({ work: t(WORK), stuck: t(STUCK), short: t(WORK, { quiet: 'short' }), idle: t('대기'), meet: t('회의 중'), vacant: t('빈자리'), long: t(WORK, { quiet: 'long' }), missing: t(WORK, { missing: true }) }));
"""
        self.assertEqual(self.node(code), {"work": False, "stuck": False, "short": False, "idle": True, "meet": True, "vacant": True, "long": True, "missing": True})

    def test_idle_people_talk_in_pairs(self):
        """대기가 둘 이상이면 마주 보고 이야기해요. 1분 안에 짝이 보이고, 혼자면 안 하고, Codex는 빠져요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const seen = (ms, secs) => { const a = window.createOfficeScene(el, { seed: 3 }), T = a._debug(); a.update(st(ms)); let talk = 0, swaps = 0, at = null; const who = new Set();
  for (let i = 0, n = secs * 30; i < n; i++) { a.step(1 / 30); const q = T.plan.pairs.find(x => x.a && x.a.at && x.b.at); if (q) { talk++; who.add(q.a.id).add(q.b.id); if (at && at !== q.who) swaps++; at = q.who; } }
  return { pct: Math.round(talk / (secs * 30) * 100), swaps, codex: [...who].some(id => id.startsWith('cx')) }; };
const six = seen(floor(6, '대기'), 60), one = seen(floor(1, '대기'), 60), withCx = seen([m('A', '대기'), m('B', '대기'), m('cx1', '대기', { codex: true }), m('cx2', '대기', { codex: true })], 120);
console.log(JSON.stringify({ six, one, withCx }));
"""
        r = self.node(code)
        self.assertGreater(r["six"]["pct"], 50)
        self.assertGreater(r["six"]["swaps"], 1)      # 3~6초마다 말하는 사람이 바뀌어요
        self.assertEqual(r["one"]["pct"], 0)
        self.assertFalse(r["withCx"]["codex"])

    def test_idle_people_spread_out(self):
        """대기 행동 아홉 가지가 다 나오고, 책상 사이에도 사람이 있고, 20명이어도 겹치지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const acts = new Set(); let desks = 0, back = 0, all = 0, over = 0;
const twelve = floor(12, '대기'); sc.update(st(twelve));
run(300, t => { for (const p of S.list) { if (p.at || p.path) acts.add(p.act); all++; if (p.y > 8.5 && p.x > 4.5) desks++; if (p.y < 3.2) back++; } });
const b = window.createOfficeScene(el, { seed: 9 }), T = b._debug(); b.update(st(floor(20, '대기')));
for (let i = 0; i < 120 * 30; i++) { b.step(1 / 30); if (i % 30) continue; for (let x = 0; x < T.list.length; x++) for (let y = x + 1; y < T.list.length; y++) { const p = T.list[x], q = T.list[y]; if (!p.path && !q.path && Math.hypot(p.x - q.x, p.y - q.y) < .5) over++; } }
console.log(JSON.stringify({ acts: [...acts].sort(), deskPct: Math.round(desks / all * 100), backPct: Math.round(back / all * 100), over }));
"""
        r = self.node(code)
        for act in ("drink", "talk", "sofa", "window", "read", "plant", "stretch", "stroll", "phone"):
            self.assertIn(act, r["acts"])
        self.assertGreater(r["deskPct"], 15)
        self.assertLess(r["backPct"], 30)
        self.assertEqual(r["over"], 0)

    def test_nobody_walks_through_chairs(self):
        """의자 칸은 막혀 있고, 자기 자리에는 옆으로 들어가고, 12·14명 회의에서 모두 제자리로 가요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const inChair = (T, p) => T.plan.desks.findIndex(d => p.x > d.x + .1 && p.x < d.x + .9 && p.y > d.y - .95 && p.y < d.y - .1);
const cross = n => { const a = window.createOfficeScene(el, { seed: 5 }), T = a._debug(); a.update(st(floor(n, '대기'))); let c = 0; const was = new Map();
  for (let i = 0; i < 300 * 30; i++) { a.step(1 / 30); for (const p of T.list) { const d = inChair(T, p); if (d >= 0 && d !== was.get(p.id)) c++; was.set(p.id, d); } } return c; };
const meet = n => { const a = window.createOfficeScene(el, { seed: 5 }), T = a._debug(); a.update(st(floor(n, '대기'))); for (let i = 0; i < 600; i++) a.step(1 / 30); a.update(st(floor(n, '회의 중'), boss)); for (let i = 0; i < 20 * 30; i++) a.step(1 / 30); return { seated: T.list.filter(p => p.at && p.sit >= 1).length, spots: new Set(T.list.map(p => p.want.x + ',' + p.want.y)).size }; };
sc.update(st([m('A', '대기')])); run(5); sc.update(st([m('A', '일하는 중')]));
const toDesk = []; run(12, () => { if (S.list[0].path) toDesk.push(S.list[0].path[S.list[0].path.length - 2]); });
console.log(JSON.stringify({ six: cross(6), twelve: cross(12), entry: toDesk[0], desk: [S.plan.desks[0].x, S.plan.desks[0].y], m12: meet(12), m14: meet(14) }));
"""
        r = self.node(code)
        self.assertEqual((r["six"], r["twelve"]), (0, 0))
        self.assertEqual(r["entry"], [r["desk"][0] + 1.5, r["desk"][1] - .5])   # 의자 옆에서 들어가요
        self.assertEqual(r["m12"], {"seated": 12, "spots": 12})
        self.assertEqual(r["m14"]["spots"], 14)                                 # 0번 의자는 대표 자리라 한 사람은 벽 쪽에 서요
        self.assertEqual(r["m14"]["seated"], 13)

    def test_every_place_can_be_reached(self):
        """층 크기마다 쉬는 자리, 이야기 자리, 책상, 회의 의자에 문에서 걸어갈 수 있어요. 자리끼리 겹치지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const out = {};
for (const n of [1, 6, 8, 10, 15, 20]) {
  const a = window.createOfficeScene(el, { seed: 1 }), T = a._debug(); a.update(st(floor(n, '대기'))); const Q = T.plan, none = new Set();
  const stops = Q.spots.map(s => s.in || [s.x, s.y]).concat(Q.pairs.flatMap(q => q.m.map(c => [c.x, c.y])), Q.seats.map(s => s.in), Q.desks.map(d => [d.x + 1.5, d.y - .5]));
  const stuck = stops.filter(c => !a._nav(Q, none, .5, 8, c[0], c[1])).length, blocked = stops.filter(c => Q.grid[Math.floor(c[1]) * Q.W + Math.floor(c[0])]).length;
  const places = Q.spots.filter(s => s.desk == null).concat(Q.pairs.flatMap(q => q.m)); let close = 0; for (let i = 0; i < places.length; i++) for (let j = i + 1; j < places.length; j++) if (Math.hypot(places[i].x - places[j].x, places[i].y - places[j].y) < .9) close++;
  out[n] = { stuck, blocked, close, spots: Q.spots.filter(s => s.desk == null).length, pairs: Q.pairs.length };
}
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        for n, row in r.items():
            self.assertEqual((row["stuck"], row["blocked"], row["close"]), (0, 0, 0), (n, row))
            self.assertGreaterEqual(row["pairs"], 3)

    def test_walks_are_calm_and_arrive(self):
        """대기 걸음은 분당 113~135걸음이고, 상태가 바뀌면 .6초 안에 걷고, 3.0칸/초를 안 넘기고, 8명 9초·12명 10초 안에 앉아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const trip = n => { const a = window.createOfficeScene(el, { seed: 11 }), T = a._debug(); a.update(st(floor(n, '대기'))); for (let i = 0; i < 25 * 30; i++) a.step(1 / 30);
  a.update(st(floor(n, '회의 중'), boss)); const done = new Map(), go = new Map(), was = new Map(T.list.map(p => [p.id, [p.x, p.y]])); let top = 0;
  for (let i = 0; i < 16 * 30; i++) { a.step(1 / 30); for (const p of T.list) { const q = was.get(p.id), v = Math.hypot(p.x - q[0], p.y - q[1]) * 30; was.set(p.id, [p.x, p.y]); top = Math.max(top, v); if (!go.has(p.id) && v > .05) go.set(p.id, i / 30); if (!done.has(p.id) && p.at && p.sit >= 1) done.set(p.id, i / 30); } }
  return { start: Math.max(...go.values()), end: Math.max(...done.values()), top, came: done.size }; };
sc.update(st(floor(12, '대기'))); const paces = new Set(); run(120, () => { for (const p of S.list) if (p.path && p.gait) paces.add(p.gait); });
const stroll = [...paces].map(g => [g.lo, g.hi, g.cyc]);
const solo = window.createOfficeScene(el, { seed: 3 }), T = solo._debug(), one = st0 => st([m('A', st0), m('B', '일하는 중')]); solo.update(one('일하는 중')); for (let i = 0; i < 90; i++) solo.step(1 / 30);
const p0 = T.people.get('A'), x0 = p0.x; solo.update(one('회의 중')); let began = 0; for (let i = 0; i < 90 && !began; i++) { solo.step(1 / 30); if (Math.abs(p0.x - x0) > .01) began = i / 30; }
console.log(JSON.stringify({ eight: trip(8), twelve: trip(12), stroll, one: began }));
"""
        r = self.node(code)
        self.assertEqual((r["eight"]["came"], r["twelve"]["came"]), (8, 12))   # 다 앉은 뒤에 시간을 봐요
        self.assertLess(r["eight"]["start"], 1.05)    # 여럿이면 물결처럼 일어나요(.45초)
        self.assertLess(r["one"], .6)                 # 혼자 바뀌면 .6초 안에 걸어요
        self.assertLess(r["eight"]["end"], 9)
        self.assertLess(r["twelve"]["end"], 10)
        self.assertLess(r["eight"]["top"], 3.01)
        self.assertEqual(len(r["stroll"]), 1)         # 대기 이동은 한 걸음이에요
        lo, hi, cyc = r["stroll"][0]
        self.assertAlmostEqual(lo / cyc * 120, 113, delta=1)
        self.assertAlmostEqual(hi / cyc * 120, 135, delta=1)

    def test_sitting_takes_half_a_second(self):
        """다 돈 다음에 앉아요. 앉는 데 .5초쯤 걸려요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
sc.update(st([m('A', '대기')])); run(4); sc.update(st([m('A', '일하는 중')]));
const p = S.list[0]; let first = 0, last = 0, far = 0;
run(14, t => { if (p.sit > 0 && !first) { first = t; far = Math.abs(Math.atan2(Math.sin(p.yaw - Math.PI / 2), Math.cos(p.yaw - Math.PI / 2))); } if (p.sit >= 1 && !last) last = t; });
console.log(JSON.stringify({ takes: +(last - first).toFixed(2), far: +far.toFixed(2) }));
"""
        r = self.node(code)
        self.assertGreater(r["takes"], .45)
        self.assertLess(r["takes"], .7)
        self.assertLess(r["far"], .4)

    def test_small_motion_stops_when_it_should(self):
        """앉은 사람도 움직여요. 움직임 줄이기면 그림이 그대로이고, 6시간 넘은 사람은 숙인 뒤 멈춰요."""
        code = self.SCENE + scene_open() + self.STAFF + """
let log = []; calls.setTransform = (...a) => log.push(a.map(v => v.toFixed(2)).join());
const shot = s => { log = []; s.draw(); return log.join('|'); };
const ms = o => [m('A', '일하는 중', o)];
sc.update(st(ms())); for (let i = 0; i < 300; i++) sc.step(.05);
const a = shot(sc); sc.step(.5); const moved = shot(sc) !== a;
const still = window.createOfficeScene(el, { seed: 1, reducedMotion: true }); still.update(st(ms()));
const b = shot(still); still._debug().t += 7.3; const same = shot(still) === b;   // 페이지는 움직임 줄이기에서 step을 안 불러요
const stale = window.createOfficeScene(el, { seed: 1 }); stale.update(st(ms({ quiet: 'short' }))); for (let i = 0; i < 100; i++) stale.step(.05);
const c = shot(stale); stale.step(1.3); const breathing = shot(stale) !== c;
console.log(JSON.stringify({ moved, same, breathing }));
"""
        self.assertEqual(self.node(code), {"moved": True, "same": True, "breathing": True})

    def test_name_tags_stay_put(self):
        """이름표는 지난 자리를 먼저 써요. 옮겨도 1초 안에 되돌아가지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
sc.update(st(floor(12, '대기'))); const was = new Map(), left = new Map(); let back = 0, moves = 0;
run(60, t => { sc.draw(); for (const p of S.list) { const i = p.tag && p.tag.i; if (was.has(p.id) && was.get(p.id) !== i) { moves++; const q = left.get(p.id); if (q && q[0] === i && t - q[1] < 1) back++; left.set(p.id, [was.get(p.id), t]); } was.set(p.id, i); } });
console.log(JSON.stringify({ back, moves }));
"""
        r = self.node(code)
        self.assertEqual(r["back"], 0)
        self.assertLess(r["moves"], 80)               # 고치기 전에는 분당 441번 튀었어요

    def test_one_bubble_at_a_time(self):
        """말풍선은 한 번에 하나, 6초씩 돌고 막힘이 먼저예요. 말한 사람이 하나면 그대로 있어요. 긴 글은 ‘…’로 끝나요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const long = '가나다라마바사아자차카타파하'.repeat(3);
sc.update(st([m('A', '일하는 중', { say: '첫째' }), m('B', '막힘', { say: '둘째' }), m('C', '일하는 중', { say: long })]));
const order = []; run(24, () => { if (order[order.length - 1] !== S.bubble) order.push(S.bubble); });
said.length = 0; S.bubble = 'C'; S.bubT = 3; sc.draw(); const text = said.filter(x => x.endsWith('…'));
const one = window.createOfficeScene(el, { seed: 2 }), T = one._debug(); one.update(st([m('A', '일하는 중', { say: '혼자' }), m('B', '일하는 중')]));
for (let i = 0; i < 40 * 30; i++) one.step(1 / 30);
console.log(JSON.stringify({ order, cut: text.length, width: text.length ? text[0].length * 7 : 0, stays: T.bubble }));
"""
        r = self.node(code)
        self.assertEqual(r["order"][:4], ["B", "A", "C", "B"])
        self.assertEqual(r["cut"], 1)
        self.assertLessEqual(r["width"], 212)
        self.assertEqual(r["stays"], "A")

    def test_meeting_seats_stay(self):
        """회의 자리는 들어올 때 정해요. 누가 나가도, 참석이 위임이 돼도 아무도 안 움직여요. 20명이어도 한 의자에 둘이 없어요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const team = { ...boss, mode: 'team' }, ms = out => floor(8, '회의 중').map((x, i) => (i === out ? m(x.id, '대기', { lead: !i }) : x));
sc.update(st(ms(-1), boss)); run(14);
const seats = () => S.list.map(p => p.want.x + ',' + p.want.y), a = seats(), zero = S.list.some(p => p.seatI === 0);
sc.update(st(ms(-1), team)); run(2); const b = seats(), up1 = S.list.filter(p => p.sit < 1).length;
sc.update(st(ms(3), team)); run(2); const c = seats(), up2 = S.list.filter(p => p.sit < 1 && p.m.state === '회의 중').length;
const big = window.createOfficeScene(el, { seed: 4 }), T = big._debug(); big.update(st(floor(20, '회의 중'), boss));
const each = T.list.map(p => p.want.x + ',' + p.want.y);
console.log(JSON.stringify({ same: a.join() === b.join(), up1, kept: c.filter((x, i) => i !== 3 && x === a[i]).length, up2, zero, unique: new Set(each).size, wall: T.list.filter(p => p.want.wall).length }));
"""
        r = self.node(code)
        self.assertTrue(r["same"])
        self.assertEqual((r["up1"], r["up2"], r["kept"]), (0, 0, 7))
        self.assertFalse(r["zero"])                   # 0번은 대표 자리예요
        self.assertEqual(r["unique"], 20)
        self.assertEqual(r["wall"], 7)                # 의자가 모자라면 벽 쪽에 서요

    def test_goals_match_the_table(self):
        """표 2-2·2-3·2-5: 오래된 회의 중, 상태 파일 없음, Codex 대기는 자기 책상이에요. 오래된 대기는 돌아다녀요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
sc.update(st([m('A', '대기', { quiet: 'short', label: '회의 중' }), m('B', '대기', { quiet: 'short', label: '아직 소식 없음' }), m('C', '대기', { codex: true }), m('D', '대기'), m('E', '일하는 중', { quiet: 'short', label: '일하는 중' })]));
const d = {}; for (const p of S.list) d[p.id] = p.want.sit && p.want.y === p.desk.y - .5; const moved = {};
const start = new Map(S.list.map(p => [p.id, [p.x, p.y]])); run(60, () => { for (const p of S.list) if (Math.hypot(p.x - start.get(p.id)[0], p.y - start.get(p.id)[1]) > .2) moved[p.id] = 1; });
said.length = 0; sc.draw();
console.log(JSON.stringify({ d, moved, said: [...new Set(said)] }));
"""
        r = self.node(code)
        self.assertEqual(r["d"], {"A": True, "B": True, "C": True, "D": False, "E": True})
        self.assertEqual(r["moved"], {"D": 1})
        self.assertIn("A · 응답 없음?", r["said"])
        self.assertIn("B · 아직 소식 없음", r["said"])
        self.assertNotIn("B · 응답 없음?", r["said"])

    def test_highlight_is_the_body(self):
        """강조는 네모가 아니라 몸 테두리예요. 사람이 없는 자리는 책상을 표시해요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
let boxes = 0, strokes = 0; calls.strokeRect = () => { boxes++; }; calls.stroke = () => { strokes++; };
sc.update(st([m('A', '일하는 중'), m('Q', '빈자리')])); run(.1); boxes = strokes = 0; sc.draw();
const plain = boxes; boxes = strokes = 0;
let images = 0; calls.drawImage = () => { images++; };
boxes = strokes = 0; sc.draw(); const rim = images, plainNow = boxes; images = 0; boxes = strokes = 0;
sc.highlight('A'); const a = [boxes - plainNow, strokes], glow = images; boxes = strokes = 0; images = 0;
sc.highlight('Q'); const q = [boxes - plain, strokes]; boxes = strokes = 0;
sc.highlight(null);
console.log(JSON.stringify({ a, q, none: [boxes - plain, strokes], more: glow - rim }));
"""
        r = self.node(code)
        self.assertEqual(r["a"][0], 0)
        self.assertEqual(r["more"], 4)                # 강조한 몸은 테두리를 네 번 더 찍어요(4방향 → 8방향)
        self.assertEqual(r["q"][1], 1)                # 책상 테두리 하나
        self.assertEqual(r["none"][1], 0)

    def test_tags_can_be_pressed(self):
        """이름표, 빈자리, 기록 없음, n시간째 소식 없음, 대기인 사람의 빈 책상을 눌러도 서랍이 열려요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const picked = []; sc.on('select', id => picked.push(id));
sc.update(st([m('A', '대기'), m('Q', '빈자리'), m('C', '빈자리', { missing: true, codex: true }), m('D', '일하는 중', { quiet: 'long', hours: 7 })])); run(.1); sc.draw();
const hit = S.hits.map(h => h.id).sort();
for (const h of S.hits) listeners.click({ clientX: h.x + 3, clientY: h.y + 3 });
const tags = picked.slice().sort();
const v = sc._view(), d = S.plan.desks[0], q = v.desk(d), far = S.people.get('A'); far.x = 2; far.y = 3; sc.draw(); picked.length = 0;
S.hits = []; listeners.click({ clientX: q[0], clientY: q[1] });
console.log(JSON.stringify({ hit, tags, desk: picked }));
"""
        r = self.node(code)
        self.assertEqual(r["hit"], ["A", "C", "D", "D", "Q"])   # D는 표지와 이름표 둘이에요
        self.assertEqual(r["tags"], r["hit"])                   # 누른 표마다 그 사람이 열려요
        self.assertEqual(r["desk"], ["A"])

    def test_phone_keeps_everyone_in_frame(self):
        """폰에서는 카메라가 따라가지 않고 고정이에요. 사람들 자리가 바뀌어도 화면이 그대로예요."""
        code = self.SCENE.replace("width: 960, height: 538", "width: 326, height: 245") + scene_open() + self.STAFF + self.WATCH + """
const v = sc._view(), rows = {};
for (const n of [6, 8, 12]) {
  const a = window.createOfficeScene(el, { seed: 3 }), T = a._debug(), w = a._view(); a.update(st(floor(n, '일하는 중')));
  const out = T.list.filter(p => { const h = w.head(p), f = w.foot(p); return h[0] < 0 || h[0] > 326 || h[1] < 0 || f[1] > 245; });
  rows[n] = out.length;
}
console.log(JSON.stringify(rows));
"""
        self.assertEqual(self.node(code), {"6": 0, "8": 0, "12": 0})

    def test_narrow_window_keeps_everyone_in_frame(self):
        """좁은 창에서는 책상뿐 아니라 회의 자리와 대기 자리에 선 사람의 몸 좌우 끝까지 화면 안이에요."""
        for w, h in ((326, 245), (286, 215), (500, 375)):
            code = self.SCENE.replace("width: 960, height: 538", f"width: {w}, height: {h}") + scene_open() + self.STAFF + self.WATCH + f"""
const W = {w}, H = {h}, out = {{}};
for (const n of [6, 8, 12, 14]) for (const kind of ['회의 중', '대기', '일하는 중']) {{
  const a = window.createOfficeScene(el, {{ seed: 3 }}), T = a._debug(), v = a._view();
  a.update(st(floor(n, kind), kind === '회의 중' ? boss : undefined));
  let side = 0, far = 0;
  for (const q of T.plan.seats.concat(T.plan.spots, T.plan.pairs.flatMap(c => c.m))) {{ const f = v.foot(q), b = v.bodyW(); if (f[0] - b < -.5 || f[0] + b > W + .5) {{ side++; far = Math.max(far, Math.round(Math.max(-(f[0] - b), f[0] + b - W))); }} }}   // 비어 있는 의자까지 봐요
  for (let i = 0; i < 40 * 30; i++) {{
    a.step(1 / 30); if (i % 6) continue;
    const b = v.bodyW();
    for (const p of T.list) {{ if (!p.at) continue; const f = v.foot(p), t = v.head(p); if (f[0] - b < -.5 || f[0] + b > W + .5) {{ side++; far = Math.max(far, Math.round(Math.max(-(f[0] - b), f[0] + b - W))); }} if (t[1] < 0 || f[1] > H) side++; }}
  }}
  out[n + kind] = side ? far || side : 0;
}}
console.log(JSON.stringify(out));
"""
            r = self.node(code)
            self.assertEqual({k: v for k, v in r.items() if v}, {}, f"{w}x{h}")

    def test_cut_name_stays_whole(self):
        """이름을 줄여도 이모지 가운데를 자르지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const lone = /[\\ud800-\\udbff](?![\\udc00-\\udfff])|(?<![\\ud800-\\udbff])[\\udc00-\\udfff]/, bad = [];
for (const lead of ['가', '가가']) { sc.update(st([m('A', '일하는 중', { lead: true, name: lead + '😀'.repeat(40) })])); said.length = 0; sc.draw(); bad.push(...said.filter(x => lone.test(x))); }
console.log(JSON.stringify({ bad: bad.length }));
"""
        self.assertEqual(self.node(code), {"bad": 0})

    def test_held_scene_adds_and_removes_at_once(self):
        """[움직임 멈추기] 중에도 나간 사람은 바로 사라지고 새 사람은 제자리에 있어요. 상태가 바뀐 사람은 시간이 멈춘 그대로예요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const base = [m('팀장', '일하는 중', { lead: true }), m('A', '대기'), m('B', '빈자리')];
sc.update(st(base)); run(3);
const a = S.people.get('A'), lead = S.people.get('팀장'), x0 = lead.x;
sc.update(Object.assign(st([m('팀장', '회의 중', { lead: true }), m('A', '빈자리'), m('B', '대기')]), { still: true }));
const b = S.people.get('B');
console.log(JSON.stringify({ gone: !S.people.has('A'), list: S.list.includes(a), inside: !!b && b.x > 0 && b.at, door: S.doorT > 0, stay: lead.x === x0 }));
"""
        self.assertEqual(self.node(code), {"gone": True, "list": False, "inside": True, "door": False, "stay": True})

    def test_still_meeting_keeps_name_tags(self):
        """움직임 줄이기에는 말하는 사람이 없어요. 6명 넘는 회의도 이름표가 있어요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const a = window.createOfficeScene(el, { seed: 1, reducedMotion: true }), T = a._debug(); a.update(st(floor(8, '회의 중'), boss));
said.length = 0; a.draw(); const still = floor(8, '회의 중').filter(q => said.some(x => x.startsWith(q.id))).length;
sc.update(st(floor(8, '회의 중'), boss)); run(20); said.length = 0; sc.draw(); const moving = floor(8, '회의 중').filter(q => said.some(x => x.startsWith(q.id))).length;
console.log(JSON.stringify({ still, moving, speaker: !!S.speaker }));
"""
        r = self.node(code)
        self.assertEqual(r["still"], 8)
        self.assertLessEqual(r["moving"], 2)          # 움직일 때는 말하는 사람만이에요
        self.assertTrue(r["speaker"])

    def test_idle_stay_is_long_enough(self):
        """대기 머무는 시간은 12~30초예요(팀장 결정). 처음 자리와 짧은 쉼은 세지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
sc.update(st(floor(6, '대기'))); const was = new Map(), stays = [];
run(300, t => { for (const p of S.list) { const w = was.get(p.id) || 0; if (t > 15 && p.wait > w + .1 && p.wait > 3) stays.push(p.wait); was.set(p.id, p.wait); } });
console.log(JSON.stringify({ n: stays.length, low: Math.min(...stays), high: Math.max(...stays) }));
"""
        r = self.node(code)
        self.assertGreater(r["n"], 5)
        self.assertGreaterEqual(r["low"], 12)
        self.assertLessEqual(r["high"], 30)

    def test_phone_gathers_desk_signs(self):
        """폰에서는 책상 표지를 왼쪽 아래 한 줄로 모아요. 책상을 덮지 않고, 누르면 그 줄의 첫 사람에게 가요. 넓은 화면은 그대로예요."""
        floor = """
const picked = []; sc.on('select', id => picked.push(id));
sc.update(st([m('팀장', '일하는 중', { lead: true }), m('A', '빈자리'), m('B', '빈자리'), m('C', '빈자리'), m('D', '일하는 중', { quiet: 'long', hours: 7 }), m('E', '빈자리', { missing: true, codex: true })])); run(.1); said.length = 0; sc.draw();
const signs = said.filter(x => /빈자리|기록|소식 없음/.test(x)).sort();
"""
        code = self.SCENE.replace("width: 960, height: 538", "width: 326, height: 245") + scene_open() + self.STAFF + self.WATCH + floor + """
const v = sc._view(), band = S.hits.filter(h => h.h === 25), box = band.find(h => h.id === 'A');
const covered = S.plan.desks.filter(d => { const q = v.deskSign(d); return band.some(h => q[0] > h.x && q[0] < h.x + h.w && q[1] > h.y && q[1] < h.y + h.h); }).length;
listeners.click({ clientX: box.x + 3, clientY: box.y + 3 });
console.log(JSON.stringify({ signs, picked, low: box.y > S.h - 40, left: box.x < 12, wide: Math.min(...band.map(h => h.w)) >= 44, covered }));
"""
        self.assertEqual(self.node(code), {"signs": ["기록 없음", "빈자리 3", "소식 없음"], "picked": ["A"], "low": True, "left": True, "wide": True, "covered": 0})
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + floor + "console.log(JSON.stringify(signs));"
        self.assertEqual(self.node(code), ["7시간째 소식 없음", "Codex · 기록을 찾지 못했어요", "빈자리", "빈자리", "빈자리"])

    def test_held_hands_stay_at_the_desk(self):
        """확인을 기다리는 세션은 책상에 앉은 채 손을 멈춰요. 등은 켜져 있어요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
sc.update(st([m('A', '일하는 중', { lead: true }), m('B', '일하는 중', { hold: true })])); run(3);
console.log(JSON.stringify({ a: S.people.get('A').act, b: S.people.get('B').act, sit: S.people.get('B').sit }));
"""
        self.assertEqual(self.node(code), {"a": "type", "b": "still", "sit": 1})

    def test_short_gaps_do_not_stand_people_up(self):
        """busy 20초, idle 5초, busy 20초에 일어나지 않아요. 턴이 끝나면 12초 안에 일어나요."""
        code = self.SEAT.replace("const NOW = Date.parse('2026-10-31T12:00:00Z'), ago", "let NOW = Date.parse('2026-10-31T12:00:00Z'); const ago") + page_js("QUIET_SHORT", "seatView") + self.SCENE.replace("const m = ", "const mm = ") + scene_open() + self.STAFF.replace("const m = ", "const mm = ") + self.WATCH + """
const seat = { role: 'A', sessionId: 'local_x' }, file = { state: '대기', updated: new Date(NOW).toISOString() };
const view = () => { const v = seatView('t', seat, file, null, NOW); return st([mm('L', '일하는 중', { lead: true }), mm('A', v.state, { hold: !!v.hold })]); };
const play = (secs, every = 4) => { for (let i = 0; i < secs * 30; i++) { sc.step(1 / 30); NOW += 1000 / 30; if (i % (every * 30) === 0) sc.update(view()); } };
sc.update(view()); play(10);
const start = NOW; liveFake.A = { s: 'busy', since: start }; play(14); const p = S.people.get('A'), seated = p.sit;
let ups = 0, was = p.sit;
const watch = secs => { for (let i = 0; i < secs * 30; i++) { sc.step(1 / 30); NOW += 1000 / 30; if (i % 120 === 0) sc.update(view()); if (was >= 1 && p.sit < 1) ups++; was = p.sit; } };
watch(6); liveFake.A = { s: 'idle', since: NOW }; watch(5); liveFake.A = { s: 'busy', since: NOW }; watch(20);
const during = ups; liveFake.A = { s: 'idle', since: NOW }; let up = 0; for (let i = 0; i < 14 * 30 && !up; i++) { watch(1 / 30); if (p.sit < 1) up = i / 30; }
console.log(JSON.stringify({ seated, during, up: up > 0 && up <= 13 }));
"""
        self.assertEqual(self.node(code), {"seated": 1, "during": 0, "up": True})

    def test_people_use_the_door(self):
        """새 사람은 문 밖에서 들어와 자기 책상에 한 번 앉아요. 대기여도요. 나가는 사람은 문까지 걸어가요. 움직임 줄이기에서는 걷지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const base = [m('팀장', '일하는 중', { lead: true }), m('A', '빈자리')];
sc.update(st(base)); run(1);
sc.update(st([base[0], m('A', '대기', { arriving: true })]));
const p = S.people.get('A'), start = [p.x, p.door = S.doorT > 0]; let sat = false, later = '';
run(30, () => { if (p.sit >= 1) sat = true; });
const roamed = p.idle;
sc.update(st(base)); const going = S.people.has('A'), fallback = said.length; let tagFirst = false; said.length = 0; sc.draw(); tagFirst = said.includes('빈자리');
run(20);
const still = window.createOfficeScene(el, { seed: 2, reducedMotion: true }), T = still._debug(); still.update(st([base[0], m('A', '대기')])); still.update(st(base));
console.log(JSON.stringify({ x: start[0], door: start[1], sat, roamed, going, tagFirst, gone: !S.people.has('A'), reduced: T.people.has('A') }));
"""
        self.assertEqual(self.node(code), {"x": -.6, "door": True, "sat": True, "roamed": True, "going": True, "tagFirst": True, "gone": True, "reduced": False})

    def test_seat_news_can_come_after_the_person(self):
        """서버는 team.json을 먼저 고치고, 앉힘 소식은 3초마다 물어 알아요. 소식이 사람보다 늦게 와도 한 번 앉아요. 소식이 없으면 앉히지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const base = [m('팀장', '일하는 중', { lead: true }), m('A', '빈자리'), m('B', '빈자리')];
sc.update(st(base)); run(1);
sc.update(st([base[0], m('A', '대기'), m('B', '대기')]));
const a = S.people.get('A'), b = S.people.get('B'); run(2.5);
const early = a.landed; let sat = false, desk = false;
sc.update(st([base[0], m('A', '대기', { arriving: true }), m('B', '대기')]));
run(12, () => { if (a.sit >= 1 && a.want && !a.want.idle && !a.path) { sat = true; desk = !!a.desk && Math.hypot(a.x - a.desk.x - .5, a.y - a.desk.y + .5) < .2; } });
sc.update(st([base[0], m('A', '대기'), m('B', '대기')])); run(8);
console.log(JSON.stringify({ early, sat, desk, up: a.landed && a.idle, other: b.landed }));
"""
        self.assertEqual(self.node(code), {"early": True, "sat": True, "desk": True, "up": True, "other": True})

    def test_idle_asides_stay_small(self):
        """혼잣말은 대기일 때만, 층 전체에서 한 번에 하나, 3초예요. 전화·Codex·진짜 한마디가 있는 사람과 움직임 줄이기에서는 없어요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
sc.update(st(floor(12, '대기'))); const spans = [], who = new Set(); let was = null, begin = 0, bad = 0, phone = 0, gaps = [], end = 0;
run(300, t => { const a = S.aside; if (a !== was) { if (was) { spans.push(t - begin); end = t; } if (a) { if (end) gaps.push(t - end); begin = t; who.add(a.p.id); } was = a; } if (a && !a.p.idle) bad++; if (a && a.p.act === 'phone' && !a.p.talk) phone++; });
const quiet = window.createOfficeScene(el, { seed: 8 }), T = quiet._debug(); quiet.update(st([m('A', '일하는 중'), m('C', '대기', { codex: true }), m('S', '대기', { say: '진짜 말' })]));
let heard = 0; for (let i = 0; i < 300 * 30; i++) { quiet.step(1 / 30); if (T.aside) heard++; }
const still = window.createOfficeScene(el, { seed: 8, reducedMotion: true }), R = still._debug(); still.update(st(floor(6, '대기'))); for (let i = 0; i < 90 * 30; i++) still.step(1 / 30);
const ph = window.createOfficeScene(el, { seed: 4 }), Q = ph._debug(); ph.update(st([m('A', '대기'), m('B', '일하는 중')])); for (let i = 0; i < 30; i++) ph.step(1 / 30);
const caller = Q.people.get('A'); let onPhone = 0, ask = 0; for (let i = 0; i < 120 * 30; i++) { caller.act = 'phone'; ph.step(1 / 30); if (Q.asideQ.length || Q.aside) { ask++; if (Q.aside && Q.aside.p === caller) onPhone++; } }
console.log(JSON.stringify({ lines: spans.length, span: Math.max(...spans), gap: Math.max(...gaps), near: Math.min(...gaps), bad, phone, heard, reduced: !!R.aside, onPhone }));
"""
        r = self.node(code)
        self.assertGreater(r["lines"], 5)
        self.assertLessEqual(r["span"], 3.1)
        self.assertLessEqual(r["gap"], 40.1)
        self.assertGreaterEqual(r["near"], .9)        # 짝 대화의 두 줄 사이 1초
        self.assertEqual((r["bad"], r["phone"], r["heard"], r["reduced"], r["onPhone"]), (0, 0, 0, False, 0))

    def test_aside_shape_follows_the_theme(self):
        """혼잣말은 밝음에서 옅은 밝은 판, 어두움에서 판 없이 글자 둘레만 있어요. .2초에 나타나고 .3초에 사라져요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const line = '커피 향 좋다', look = theme => {
  sc.update(Object.assign(st(floor(3, '대기')), { theme })); run(1);
  const alpha = [], ink = new Set(), plate = new Set(); let edge = 0;
  calls.strokeText = x => { if (x === line) edge++; };
  calls.fillText = function (x) { if (x === line) { alpha.push(+this.globalAlpha.toFixed(2)); ink.add(this.fillStyle); } };
  calls.fillRect = function () { plate.add(this.fillStyle); };
  S.aside = { p: S.list[0], text: line };
  for (const t of [3, 2.9, 1.5, .15]) { S.asideT = t; sc.draw(); }
  S.aside = null; S.asideT = 9; delete calls.strokeText; delete calls.fillRect; delete calls.fillText;
  return { alpha, ink: [...ink], plate: plate.has('rgba(240,238,232,.5)'), edge: edge > 0 };
};
console.log(JSON.stringify({ light: look('light'), dark: look('dark') }));
"""
        r = self.node(code)
        self.assertEqual(r["light"], {"alpha": [0, .5, 1, .5], "ink": ["#2A2D33"], "plate": True, "edge": False})
        self.assertEqual(r["dark"], {"alpha": [0, .5, 1, .5], "ink": ["rgba(236,234,227,.92)"], "plate": False, "edge": True})

    def test_asides_last_their_three_seconds(self):
        """사람이 몰린 층에서도 띄운 혼잣말은 3초를 채워요. 이름표가 자리를 다 막았으면 그 말은 띄우지 않아요."""
        code = self.SCENE + scene_open() + self.STAFF + self.WATCH + """
const seen = n => { const a = window.createOfficeScene(el, { seed: 3 }), T = a._debug(), lines = new Map(); a.update(st(floor(n, '대기')));
  for (let i = 0; i < 120 * 30; i++) {
    a.step(1 / 30); if (!T.aside && T.asideT > 1) T.asideT = .5;
    said.length = 0; a.draw(); const q = T.aside;
    if (q) { const o = lines.get(q) || { on: 0, all: 0 }; lines.set(q, o); o.all++; if (said.includes(q.text)) o.on++; }
  }
  const all = [...lines.values()].filter(o => o.all >= 85);
  return { n: all.length, full: all.filter(o => o.on >= o.all - 2).length, none: all.filter(o => o.on === 0).length }; };
console.log(JSON.stringify({ six: seen(6), twelve: seen(12) }));
"""
        r = self.node(code)
        for k in ("six", "twelve"):
            self.assertGreater(r[k]["n"], 10)
            self.assertEqual(r[k]["full"] + r[k]["none"], r[k]["n"], k)   # 3초를 채우거나 아예 안 떠요
        self.assertGreater(r["six"]["full"], r["six"]["n"] * .6)
        self.assertGreater(r["twelve"]["full"], r["twelve"]["n"] * .4)

    def test_aside_lines_never_reach_the_roster(self):
        """혼잣말 글은 장면 코드에만 있어요. 페이지의 명단·호버 카드 코드는 읽지 않아요."""
        page = SRC.replace(scene_code(), "")
        for bad in ("ASIDE", "커피 향 좋다", "물 드세요?"):
            self.assertNotIn(bad, page)

    def test_stuck_says_so_in_words(self):
        """막힘에는 글자 ‘막힘’이 붙어요. 다른 상태에는 없고, 폰은 ?만 둬요."""
        code = self.SCENE + scene_code() + self.STAFF + """
sc.update(st([m('A', '막힘'), m('B', '일하는 중')])); const page = said.filter(x => x === '막힘').length; said.length = 0;
sc.update(st([m('A', '일하는 중'), m('B', '일하는 중')])); const none = said.filter(x => x === '막힘').length; said.length = 0;
const small = Object.assign({}, el, { getBoundingClientRect: () => ({ width: 326, height: 245 }) }), ph = window.createOfficeScene(small, { seed: 1 }); ph.update(st([m('A', '막힘')]));
console.log(JSON.stringify({ page: page > 0, none, phone: said.filter(x => x === '막힘').length, mark: said.includes('?') }));
"""
        self.assertEqual(self.node(code), {"page": True, "none": 0, "phone": 0, "mark": True})

    def test_lamp_goes_off_with_quiet_person(self):
        """소식 없음 자리는 책상 등이 꺼져요. 대상이 바뀔 때만 다시 구워요."""
        code = self.SCENE + scene_code() + self.STAFF + """
const team = q => [m('팀장', '일하는 중', { lead: true }), m('D', '일하는 중', q ? { quiet: 'long', hours: 7 } : {})];
sc.update(st(team(false))); const a = count.bakes;
sc.update(st(team(false))); const same = count.bakes - a;
sc.update(st(team(true))); const off = count.bakes - a;
sc.update(st(team(true))); const again = count.bakes - a;
sc.update(st(team(false))); const on = count.bakes - a;
console.log(JSON.stringify({ same, off, again, on }));
"""
        self.assertEqual(self.node(code), {"same": 0, "off": 1, "again": 1, "on": 2})

    def test_voxel_scene_rebakes_when_desks_change(self):
        """같은 평면도 안에서 사람이 늘면 그 책상의 소품을 다시 구워요. 같은 수면 다시 굽지 않아요."""
        code = self.SCENE + scene_code() + self.STAFF + """
const two = [m('팀장', '대기', { lead: true }), m('A', '대기')];
sc.update(st(two)); const a = count.bakes;
sc.update(st(two)); const same = count.bakes - a;
sc.update(st(two.concat(m('B', '대기')))); const more = count.bakes - a;
console.log(JSON.stringify({ same, more }));
"""
        self.assertEqual(self.node(code), {"same": 0, "more": 1})


# 세션 답에 섞여 올 수 있는 조작한 글. 그리면 모두 글자로 남고, 정해진 여섯 태그 밖은 하나도 생기지 않아야 해요(U-29 7번)
HOSTILE = [
    '<img src=x onerror="globalThis.hit=1">',
    '<script>globalThis.hit=1</script>',
    '**<img src=x onerror=globalThis.hit=1>**',
    '- <svg onload="globalThis.hit=1"></svg>',
    '1. <iframe srcdoc="<script>parent.hit=1</script>"></iframe>',
    '[눌러요](javascript:globalThis.hit=1)',
    '<a href="javascript:globalThis.hit=1">눌러요</a>',
    '"><img src=x onerror=globalThis.hit=1>',
    "'><img src=x onerror=globalThis.hit=1>",
    '**a**"><b onmouseover=globalThis.hit=1>b</b>',
    '&lt;script&gt;globalThis.hit=1&lt;/script&gt;',
    '<style>*{display:none}</style>',
    '- **<b>굵게</b>**\n* 둘\n3) <u>셋</u>',
    '<details open ontoggle=globalThis.hit=1>',
    '1) <math><mi xlink:href="javascript:globalThis.hit=1">x</mi></math>',
    '<!-- 주석 --><p class="lead">문단</p>',
    '**`코드`** # 제목 ![그림](javascript:globalThis.hit=1)',
    '<p\nonclick=globalThis.hit=1>나눈 태그</p>',
]
MD_TAG = re.compile(r'</?(?:p|br|strong|ul|ol|li)(?: class="lead"| value="\d{1,3}")?>')


@unittest.skipUnless(shutil.which("node"), "node가 없어요(화면 코드 시험은 node로 돌려요)")
class ChatDrawer(unittest.TestCase):
    """U-29 대화창 B '대화 먼저': 머리 한 줄과 [대화 | 정보] 탭, 말 묶음, 굵게·목록만 그리기, 끊김 띠, 한 줄 작성창."""
    node = SceneFrame.node

    @staticmethod
    def thread_js():
        return page_js("esc") + """
let API = true, PIC_V = 0;
const hm = s => String(s).slice(11, 16), seatHTML = (t, r) => esc(r), seatText = (t, r) => r;
""" + page_js("PIC_NAME", "ATT", "picUrl", "linePics", "picsHTML", "mdLite", "TURN_GAP", "sameTurn", "lineHTML", "linesHTML", "VIA_BOSS", "threadHTML")

    @staticmethod
    def drawer_js():
        return page_js("esc") + """
let API = true, DF = null, html = '', opened = null, REARM = null, ex = false;
let state = { relay: null, org: { boss: { sessionId: 'local_b' } }, teams: { t: { base: 't/', reports: ['20261102-1730-팀장-TO-9.md', '20261102-1700-개발자-TO-8.md'], meetings: [], active: null,
  log: [{ t: '1', from: '팀장', to: '개발자', kind: '업무', text: '가' }, { t: '2', from: '디자이너', to: '팀장', kind: '보고', text: '나' }, { t: '3', from: '팀장', to: '디자이너', kind: '업무', text: '다' }, { t: '4', from: '개발자', to: '디자이너', kind: '협업', text: '라' }],
  team: { team: '가짜층', members: [{ role: '팀장', sessionId: 'local_x', title: '시험 팀장' }, { role: 'c', codexId: 'cx1' }] }, status: {},
  metas: [{ id: 'M-1', status: '진행 중', mode: '참석', topic: '단추 크기', participants: ['팀장', '개발자'] }] } } };
const isCx = m => !!m.codexId && !m.sessionId, customName = () => '', teamNames = () => [], seatHTML = (t, r) => esc(r), chatLink = id => 'claude://' + id, hm = s => String(s).slice(11, 16), ago = () => '방금';
const SID_RE = /^local_[0-9a-f-]{8,64}$/, exampleTeam = () => ex, cut = (s, n) => String(s).slice(0, n), skInfo = () => null;
""" + page_js("STAFF_RE", "skOn", "isSk", "skName", "skRole", "skLead", "SK_WHERE", "SK_VIA", "SK_NO_LEAD", "SK_BAD_NAME", "SK_RESTART", "SK_MUST", "SK_AGENT", "SKR", "skResult", "skAgentHTML",
               "skHeadText", "SK_DIFF", "skHeadHTML", "skFactsHTML") + """
const exampleSeat = () => ex, EX_NO_TALK = '예시 팀이에요. 설정에서 내 층을 만들면 말을 걸 수 있어요.', realBoss = () => true, LEAD = '팀장', CX_NO_TALK = '말 걸기는 아직 안 돼요';
const cxInfo = () => ({ state: '대기', title: 'Codex 일', at: 0, missing: false });
const drawerFacts = () => ({ state: '일하는 중 · 4분 전', task: 'TO-9 맞춰 보기', say: '거의', dot: 'd-work' });
const openDrawer = (h, team, chat) => { html = h; opened = { team, chat }; }, openThread = (f, o) => { opened.file = f; };
const $ = () => null, put = () => {}, getJSON = async () => ({}), getText = async () => '', enc = String;
""" + page_js("HO_FIELDS", "HO", "SAY_KEYS", "composerHTML", "REARM_MS", "rearmStep", "relayBtn", "relayStuck", "STUCK_STEP", "RELAY_DOWN", "relayWarn", "rearmBand", "relayBand", "relayBox",
              "VIA_BOSS", "MUST_LINE", "factLine", "talkPane", "dHead", "bossDrawer", "cxDrawer", "memberDrawer", "meetDrawer")

    def test_drawers_share_the_head(self):
        """팀원 서랍: 이름·상태 한 줄, [Claude 창 열기]·[닫기] 자리, 위험한 일 안내, [대화 | 정보] 탭, 끊김 띠. 세션 표·메시지·보고서는 정보 탭이에요(결정 1, 8번)."""
        code = self.drawer_js() + """
memberDrawer('t', '팀장'); const member = { html, opened };
ex = true; memberDrawer('t', '팀장'); const example = { html, opened }; ex = false;
bossDrawer(); const boss = { html, opened };
cxDrawer('t', state.teams.t.team.members[1]); const cx = { html, opened };
meetDrawer('t', 'M-1'); const meet = { html, opened };
console.log(JSON.stringify({ member, example, boss, cx, meet }));
"""
        r = self.node(code)
        m = r["member"]["html"]
        for part in ('<small class="d-team">가짜층 팀</small>', 'id="dfLine"', '<i class="dot d-work"></i>일하는 중 · 4분 전 · TO-9 맞춰 보기', 'href="claude://local_x"', 'Claude 창 열기',
                     'data-close-slot', '커밋·배포·업로드처럼 위험한 일의 마지막 확인은 세션 창에서 해요.', 'role="tablist"', '>대화</button>', '정보 <small>주고받은 메시지 3 · 보고서 1</small>', '<p class="hint d-via">보낸 말은 총괄이 받아서 이 세션에 전해요.</p>',
                     '총괄 연결이 끊겨 있어요. 보낸 말은 쌓여 있다가 총괄이 돌아오면 전해져요.', 'data-act="relay-rearm"', 'id="thread"',
                     'id="dfState"', 'id="dfTask"', 'id="dfSay"', '주고받은 메시지', 'data-file="t/reports/20261102-1730-팀장-TO-9.md"'):
            self.assertIn(part, m)
        self.assertRegex(m, r'<div class="d-info" id="dInfo"[^>]* hidden>')                  # 열면 대화 탭이에요
        self.assertRegex(m, r'id="dTab0"[^>]*aria-selected="true"')
        self.assertRegex(m, r'id="dTab1"[^>]*aria-selected="false"[^>]*tabindex="-1"')
        for gone in ('d-more', '바로 대화', 'd-eyebrow', '위쪽 [다시 연결]', '그 세션'):
            self.assertNotIn(gone, m)
        self.assertEqual(m.count("총괄이 받아서"), 1)                                         # 정보 탭 칸 아래 한 줄뿐(작성창 아래에는 없어요)
        order = [m.index(x) for x in ('class="d-head"', 'class="d-relay"', 'class="d-main"', '<form class="composer"')]
        self.assertEqual(order, sorted(order))
        self.assertEqual(r["member"]["opened"], {"team": "t", "chat": True, "file": "t/chat/팀장.jsonl"})
        e = r["example"]["html"]                                                            # 예시 층: 머리만 같고 대화가 없어요
        for part in ('data-close-slot', 'id="dfState"', '예시 팀이에요. 설정에서 내 층을 만들면 말을 걸 수 있어요.', '커밋·배포'):
            self.assertIn(part, e)
        for gone in ('role="tablist"', 'id="thread"', '<form', 'd-relay', 'd-via'):
            self.assertNotIn(gone, e)
        self.assertNotIn("file", r["example"]["opened"])
        b = r["boss"]["html"]                                                               # 총괄 서랍: 탭 없이 대화만
        for part in ('data-close-slot', 'href="claude://local_b"', 'id="thread"', 'aria-label="총괄과 대화"', 'class="d-relay"', '커밋·배포·업로드처럼 위험한 일의 마지막 확인은 세션 창에서 해요.', '무엇이든 총괄에게 말하면 팀에 나눠 시키거나 바로 답해요. 팀에서 올라온 보고도 여기에 정리돼요.'):
            self.assertIn(part, b)
        self.assertNotIn('role="tablist"', b)
        self.assertEqual(r["boss"]["opened"], {"team": None, "chat": True, "file": "hq/chat.jsonl"})
        c = r["cx"]["html"]                                                                 # Codex 서랍: 머리만 같아요
        for part in ('class="d-top"', 'data-close-slot', 'Codex 일'):
            self.assertIn(part, c)
        for gone in ('<form', 'role="tablist"', 'd-relay', 'claude://'):
            self.assertNotIn(gone, c)
        self.assertTrue(r["cx"]["opened"]["chat"])
        g = r["meet"]["html"]                                                               # 회의 서랍: 정보 탭에 주제와 참석자
        for part in ('role="tablist"', '<dt>주제</dt><dd>단추 크기</dd>', '<dt>참석자</dt>', 'id="meetLine"', 'id="meetCtl"', 'name="to"', 'class="d-relay"'):
            self.assertIn(part, g)
        self.assertLess(g.index('<dt>주제</dt>'), g.index('<form class="composer"'))

    def test_drawer_tabs(self):
        """[대화 | 정보]: 고른 탭만 Tab으로 가고 ←→ Home End로 옮겨요. 대화로 돌아오면 보던 자리, 맨 아래였으면 새 말까지 맨 아래예요."""
        code = """
let focused = '';
const mk = (id, ctl, sel) => ({ id, a: { 'aria-controls': ctl, 'aria-selected': sel }, tabIndex: sel === 'true' ? 0 : -1, setAttribute(k, v) { this.a[k] = String(v); }, getAttribute(k) { return this.a[k]; }, focus() { focused = id; } });
const t0 = mk('dTab0', 'dTalk', 'true'), t1 = mk('dTab1', 'dInfo', 'false'), talk = { hidden: false }, info = { hidden: true };
const th = { scrollHeight: 1000, clientHeight: 300, _t: 700, get scrollTop() { return this._t; }, set scrollTop(v) { this._t = Math.max(0, Math.min(v, this.scrollHeight - this.clientHeight)); } };
const $ = q => ({ '#dTalk': talk, '#dInfo': info, '#thread': th })[q], $$ = () => [t0, t1];
let seenCalls = 0; const talkSeen = () => { seenCalls++; };
""" + page_js("thPinned", "dTab", "dTabKey") + """
const look = () => [t0.a['aria-selected'], t1.a['aria-selected'], t0.tabIndex, t1.tabIndex, talk.hidden, info.hidden, focused];
const out = {};
dTab(1, true); out.info = look();
th.scrollHeight = 1300; dTab(0); out.low = th.scrollTop;                            // 정보를 보는 동안 새 말이 왔어요
th.scrollTop = 200; dTab(1); th.scrollHeight = 1500; dTab(0); out.kept = th.scrollTop;
dTab(5); out.none = look();
const key = (t, k) => { let stop = false; dTabKey({ target: t, key: k, preventDefault() { stop = true; } }); return stop; };
out.right = [key(t0, 'ArrowRight'), focused, t1.a['aria-selected']];
out.wrap = [key(t1, 'ArrowRight'), focused, t0.a['aria-selected']];
out.left = [key(t0, 'ArrowLeft'), focused];
out.end = [key(t1, 'Home'), focused, key(t0, 'End'), focused];
out.other = key(t1, 'a');
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["info"], ["false", "true", -1, 0, True, False, "dTab1"])
        self.assertEqual(r["low"], 1000)
        self.assertEqual(r["kept"], 200)
        self.assertEqual(r["none"][:6], ["true", "false", 0, -1, False, True])
        self.assertEqual(r["right"], [True, "dTab1", "true"])
        self.assertEqual(r["wrap"], [True, "dTab0", "true"])
        self.assertEqual(r["left"], [True, "dTab1"])
        self.assertEqual(r["end"], [True, "dTab0", True, "dTab1"])
        self.assertFalse(r["other"])
        self.assertIn("""const tb = e.target.closest('#drawerBody [role="tab"]');""", SRC)
        self.assertIn("dTabKey(e)", SRC)

    def test_open_drawer_puts_close_in_the_head(self):
        """[닫기]는 머리의 이름 줄 끝으로 옮겨요. 서랍 글을 바꾸기 전에 꺼내서 같이 지워지지 않아요. 머리가 없는 서랍은 맨 위 줄이에요."""
        code = """
let NE = null, pending = false, lastFocus = null, lastKey = null, state = null;
const document = { activeElement: null }, focusKey = () => '', toneOf = () => 'a', restoreDrafts = () => {}, armButtons = () => {};
const close = { at: 'bar', focus() { this.focused = true; } }, bar = { appendChild(x) { x.at = 'bar'; } }, slot = { appendChild(x) { x.at = 'slot'; } };
const body = { _h: '', set innerHTML(v) { if (close.at === 'slot') close.at = 'gone'; this._h = v; }, get innerHTML() { return this._h; } };
const panel = { classList: { toggle() {} }, dataset: {}, scrollTop: 5 }, dr = { hidden: true }, wrap = { inert: false }, SU = { open: false };
const $ = q => ({ '#drawerBody': body, '.drawer-panel': panel, '#drawer': dr, '#drawerClose': close, '.d-bar': bar, '.wrap': wrap, '#drawerBody [data-close-slot]': body._h.includes('data-close-slot') ? slot : null })[q];
let live = null;
const picClose = () => {}, render = () => {}, refocus = () => {};
""" + page_js("openDrawer", "closeDrawer") + """
const out = {};
openDrawer('<span data-close-slot></span>', 't', true); out.a = close.at; out.inert = wrap.inert;
openDrawer('<span data-close-slot></span>', 't', true); out.b = close.at;
openDrawer('<p>파일</p>'); out.c = close.at; out.focused = !!close.focused;
closeDrawer(); out.shut = wrap.inert;
SU.open = true; openDrawer('<p>파일</p>'); closeDrawer(); out.setup = wrap.inert;
console.log(JSON.stringify(out));
"""
        self.assertEqual(self.node(code), {"a": "slot", "b": "slot", "c": "bar", "focused": True, "inert": True, "shut": False, "setup": True})   # 서랍이 열린 동안 뒤 페이지는 Tab으로 못 가요(설정이 열려 있으면 그대로 막아요)

    def test_thread_turns_group_the_same_speaker(self):
        """같은 사람이 5분 안에 같은 사람에게 잇달아 말하면 이름과 시각을 한 번만 써요. 대표 말은 쓴 그대로, 세션 답만 그려요(결정 2, 7번)."""
        code = self.thread_js() + """
const t0 = Date.parse('2026-11-03T01:00:00Z'), at = m => new Date(t0 + m * 60000).toISOString();
const L = (m, from, text, o) => Object.assign({ t: at(m), from, text }, o || {});
const lines = [L(0, '대표', '**그대로** 단추 어때?'), L(2, '팀장', '**결론:** 됐어요'), L(3, '팀장', '- 하나\\n- 둘'), L(30, '팀장', '늦은 말'), L(31, '대표', '좋아'), L(32, '대표', '진행해'),
  L(33, '팀장', '알림', { kind: '알림' }), L(34, '팀장', '다시'), L(35, '대표', '가', { to: ['팀장'] }), L(36, '대표', '나', { to: ['개발자'] }), L(37, '대표', '다', { to: ['개발자'] }), L(38, '팀장', 'x', { t: 'bad' }), L(38, '팀장', 'y', { t: 'bad' })];
const html = threadHTML(lines, 't');
console.log(JSON.stringify({ html, turns: [...html.matchAll(/<li( class="msg[^"]*")>/g)].map(m => m[1]), more: linesHTML([L(36, '팀장', '이어')], 't', L(34, '팀장', '다시')), first: linesHTML([L(36, '팀장', '처음')], 't') }));
"""
        r = self.node(code)
        self.assertEqual(r["turns"], [' class="msg me"', ' class="msg"', ' class="msg cont"', ' class="msg"', ' class="msg me"', ' class="msg me cont"', ' class="msg sys"', ' class="msg"',
                                      ' class="msg me"', ' class="msg me"', ' class="msg me cont"', ' class="msg"', ' class="msg"'])
        self.assertEqual(r["html"].count('class="who"'), 5)                                  # 팀장 말 묶음 다섯(시각을 모르면 묶지 않아요)
        self.assertEqual(r["html"].count('class="t"'), 6)                                    # 대표 시각은 말마다 있고, 묶음의 마지막만 보여요(CSS)
        self.assertIn('<div class="b">**그대로** 단추 어때?</div>', r["html"])               # 대표 말은 쓴 그대로예요
        self.assertIn('<p><strong>결론:</strong> 됐어요</p>', r["html"])
        self.assertIn('<ul><li>하나</li><li>둘</li></ul>', r["html"])
        self.assertIn('<span>→ 개발자</span><time>', r["html"])                               # 회의에서는 받는 사람도 보여요
        self.assertTrue(r["more"].startswith('<li class="msg cont">'))                      # 새 줄만 덧붙일 때도 앞 말을 알아요
        self.assertTrue(r["first"].startswith('<li class="msg">'))

    def test_thread_append_knows_the_last_speaker(self):
        """뒤에 붙는 새 줄은 바로 앞 말을 알고 그려요. 비어 있던 대화에 첫 말이 오면 통째로 그려서 빈 대화 안내가 남지 않아요."""
        code = SceneFrame.REFRESH.replace("linesHTML = lines => `덧붙임 ${lines.length}줄`", "linesHTML = (lines, tid, prev) => { prevs.push(prev ? prev.text : null); return `덧붙임 ${lines.length}줄`; }") + "const prevs = [];\n" + page_js("thPinned", "talkSeen", "refreshThread") + """
(async () => {
  file = L('a'); await refreshThread(true);
  file += L('b') + L('c'); await refreshThread();
  file += '\\n'; await refreshThread();
  file += L('d'); await refreshThread();
  const kept = draws;
  file = '\\n'; await refreshThread(true); file += L('첫 말'); await refreshThread();
  console.log(JSON.stringify({ prevs, kept, empty: draws - kept, html: el.innerHTML }));
})();
"""
        r = self.node(code)
        self.assertEqual(r["prevs"], ["a", "c"])
        self.assertEqual(r["kept"], 1)
        self.assertEqual(r["empty"], 2)
        self.assertEqual(r["html"], "통째로 1줄")

    def test_empty_thread_says_how_it_works(self):
        """‘총괄이 받아서…’는 대화가 비었을 때만 대화 칸 가운데에 있어요. 작성창 아래와 ‘바로 대화’ 제목은 없어요(결정 6번)."""
        code = self.thread_js() + """
const out = { team: threadHTML([], 't', '개발자'), meet: threadHTML([], 't'), boss: threadHTML([]) };
API = false; out.snap = threadHTML([], 't', '개발자');
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertIn('class="msg sys t-empty"', r["team"])
        self.assertIn("아직 주고받은 말이 없어요.<br>보낸 말은 총괄이 받아서 이 세션에 전해요. 답은 여기에 올라와요.", r["team"])
        self.assertIn("아직 주고받은 말이 없어요.<br>보낸 말은 총괄이 받아서 받는 사람에게 전해요. 답은 여기에 올라와요.", r["meet"])   # 회의는 받는 사람이 여럿이에요
        self.assertNotIn("총괄이 받아서", r["boss"])                                         # 총괄 대화는 총괄이 받는 사람이에요
        self.assertIn("threadHTML(lines, cur.tid, cur.seat, cur.sk)", page_js("refreshThread"))   # sk: 직원 대화는 팀장 세션을 거친다고 알려요(U-31)
        self.assertNotIn("총괄이 받아서", r["snap"])
        self.assertNotIn("바로 대화</h3>", SRC)

    def test_md_lite_draws_bold_and_lists(self):
        """세션 답의 굵게, 목록, 줄바꿈만 그려요. 링크·제목·코드·표·그림은 쓴 글자 그대로예요(결정 7번)."""
        code = page_js("esc", "mdLite") + """
const cases = {
  mix: '**결론:** 단추를 키웠어요.\\n- 시험 12개 통과\\n- 넓은 화면은 그대로\\n배포는 아직이에요.',
  lead: '정리했어요.\\n\\n**꼭 볼 것**\\n1. 폰에서 누르기\\n2. 어두운 테두리\\n\\n**남은 것:**\\n* 배포 결정',
  lines: '첫 줄\\n둘째 줄\\r\\n\\r\\n새 문단',
  nums: '3) 셋\\n4) 넷\\n• 점',
  plain: '[링크](https://example.com) `코드` | 표 | ![그림](x.png) ** 빈칸 ** a**b\\n# 제목\\n1.5배 빨라요\\n---',
  amp: 'A & B < C > D "E"',
  empty: '',
};
console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([k, v]) => [k, mdLite(v)]))));
"""
        r = self.node(code)
        self.assertEqual(r["mix"], "<p><strong>결론:</strong> 단추를 키웠어요.</p><ul><li>시험 12개 통과</li><li>넓은 화면은 그대로</li></ul><p>배포는 아직이에요.</p>")
        self.assertEqual(r["lead"], '<p>정리했어요.</p><p class="lead"><strong>꼭 볼 것</strong></p><ol><li value="1">폰에서 누르기</li><li value="2">어두운 테두리</li></ol><p class="lead"><strong>남은 것:</strong></p><ul><li>배포 결정</li></ul>')
        self.assertEqual(r["lines"], "<p>첫 줄<br>둘째 줄</p><p>새 문단</p>")
        self.assertEqual(r["nums"], '<ol><li value="3">셋</li><li value="4">넷</li></ol><ul><li>점</li></ul>')     # 번호는 쓴 그대로예요
        self.assertEqual(r["plain"], "<p>[링크](https://example.com) `코드` | 표 | ![그림](x.png) ** 빈칸 ** a**b<br># 제목<br>1.5배 빨라요<br>---</p>")
        self.assertEqual(r["amp"], "<p>A &amp; B &lt; C &gt; D &quot;E&quot;</p>")
        self.assertEqual(r["empty"], "")

    def test_md_lite_makes_no_tags_from_words(self):
        """조작한 글: 그린 결과에는 정해진 여섯 태그(속성은 class="lead"와 숫자 value뿐)만 있고, 나머지 <와 >는 모두 글자예요. 대표 말과 세션 말 모두요."""
        code = self.thread_js() + f"\nconst H = {json.dumps(HOSTILE, ensure_ascii=False)};\n" + """
console.log(JSON.stringify({ md: H.map(mdLite), them: H.map(t => lineHTML({ t: '2026-11-03T01:00:00Z', from: '개발자', text: t }, 't')), me: H.map(t => lineHTML({ t: '2026-11-03T01:00:00Z', from: '대표', text: t }, 't')) }));
"""
        r = self.node(code)
        for src, out in zip(HOSTILE, r["md"]):
            left = MD_TAG.sub("", out)
            self.assertNotIn("<", left, src)
            self.assertNotIn(">", left, src)
        for out in r["them"] + r["me"]:
            body = re.search(r'<div class="b(?: md)?">(.*)</div>', out, re.S).group(1)
            self.assertNotRegex(MD_TAG.sub("", body), r"[<>]", out)
        for out in r["me"]:
            self.assertNotIn("<p>", out)                                                     # 대표 말은 그리지 않아요

    def test_composer_is_one_line_with_keys_below(self):
        """작성창: 한 줄 글칸 + [보내기], 그 아래 단축키 한 줄과 [일 맡기기] 글 단추. 칩 옆 사실 줄은 U-28 그대로예요(결정 5, 9번)."""
        code = page_js("esc", "HO_FIELDS", "HO", "SAY_KEYS", "composerHTML") + """
const API = true;
console.log(JSON.stringify({ ho: composerHTML('say', '', '여기에', 'k', true), plain: composerHTML('say', '', '여기에', 'b') }));
"""
        r = self.node(code)
        h = r["ho"]
        self.assertRegex(h, r'<div class="c-box"><textarea name="text" rows="1" [^>]*>')
        order = [h.index(x) for x in ('class="c-box"', '<textarea name="text"', '<fieldset class="ho"', 'type="submit"', 'class="row"', 'id="sayKeys"', 'data-ho-toggle')]
        self.assertEqual(order, sorted(order))
        self.assertIn('<p class="keys" id="sayKeys">Enter 보내기 · Shift+Enter 줄바꿈 · ⌘V 사진 붙이기</p>', h)
        self.assertIn('<button type="button" class="ho-tg" data-ho-toggle aria-pressed="false">일 맡기기</button>', h)
        self.assertIn('<p class="att-note">세션이 열면 Claude로 보내지고 기록에 남아요.</p>', h)
        for gone in ("relay-note", "총괄이 받아서", 'class="acts"', 'class="hint"'):
            self.assertNotIn(gone, h)
        self.assertNotIn("data-ho-toggle", r["plain"])

    def test_relay_band_is_the_header_button(self):
        """끊김 띠: 두 문장과 머리말과 같은 단추(같은 data-act, 같은 이름). 누른 뒤 3분은 띠 글도 할 일로 바뀌고, 멈춤이면 총괄 창 링크예요.
        셋째 문장('위쪽 [다시 연결]을…')은 어디에도 없어요. 회의 열기 서랍도 같은 띠예요(결정 4번, 마케팅 5-3장)."""
        code = page_js("esc") + """
let REARM = null, API = true, boss = true, state = { relay: null, org: { boss: { sessionId: 'local_b' } } };
const realBoss = () => boss, chatLink = id => 'claude://' + id;
""" + page_js("REARM_MS", "rearmStep", "relayBtn", "relayDownHTML", "relayStuck", "STUCK_STEP", "RELAY_DOWN", "relayWarn", "rearmBand", "relayBand", "relayBox") + """
const btn = h => (h.match(/data-act="relay-rearm">([^<]*)</) || [])[1] || null, out = {};
out.down = relayBand(); out.downHead = btn(relayDownHTML(state.relay)); out.box = relayBox();
REARM = { at: Date.now(), copied: true }; out.re = relayBand(); out.reHead = btn(relayDownHTML(state.relay)); out.reHeadText = relayDownHTML(state.relay);
REARM = { at: Date.now(), copied: false }; out.reNo = relayBand(); out.reNoHead = relayDownHTML(state.relay);
REARM = { at: Date.now() - 999999, copied: true }; out.old = btn(relayBand()); REARM = null;
state.relay = { relayAge: 3, pending: 2, oldestAge: 90 }; out.stuck = relayBand();
state.relay = { relayAge: 3, pending: 0 }; out.ok = relayBand(); out.okBox = relayBox();
state.relay = null; boss = false; out.noBoss = relayBand(); boss = true;
API = false; out.snap = relayBand(); API = true;
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertIn("<p>총괄 연결이 끊겨 있어요. 보낸 말은 쌓여 있다가 총괄이 돌아오면 전해져요.</p>", r["down"])
        self.assertEqual((re.search(r'data-act="relay-rearm">([^<]*)<', r["down"]).group(1), r["downHead"]), ("다시 연결", "다시 연결"))
        self.assertEqual(r["box"], '<div class="d-relay" role="status">' + r["down"] + '</div>')
        self.assertEqual(re.search(r'data-act="relay-rearm">([^<]*)<', r["re"]).group(1), r["reHead"])
        self.assertEqual(r["reHead"], "총괄 창 다시 열기")
        self.assertIn("<p>다시 켜는 말을 복사했어요. 총괄 창에 붙여 넣고(⌘V) Enter를 눌러요.</p>", r["re"])   # 클립보드를 바꿨다는 것도 알려요
        self.assertIn("총괄 창에서 붙여 넣고(⌘V) Enter를 눌러요", r["reHeadText"])
        self.assertIn("<p>총괄 창에서 “사이트 전달 감시 다시 켜 줘”라고 보내요.</p>", r["reNo"])
        self.assertIn("총괄 창에서 “사이트 전달 감시 다시 켜 줘”라고 보내요", r["reNoHead"])
        self.assertEqual(r["old"], "다시 연결")
        self.assertIn("총괄 창이 멈췄을 수 있어요(대기 2개).", r["stuck"])
        self.assertIn('href="claude://local_b"', r["stuck"])
        self.assertEqual((r["ok"], r["snap"], r["okBox"]), ("", "", '<div class="d-relay" role="status" hidden></div>'))
        self.assertIn("총괄 연결이 끊겨 있어요", r["noBoss"])
        self.assertNotIn("data-act", r["noBoss"])
        self.assertNotIn("위쪽 [다시 연결]", SRC)
        self.assertNotIn("relay-note", SRC)
        self.assertIn("${relayBox()}", page_js("meetStartDrawer"))                            # 회의 열기 서랍도 같은 띠와 단추
        for fn in ("pollRelay", "relayRearm", "submitForm"):
            self.assertIn("relayPaint();", page_js(fn), fn)
        self.assertIn("dTab(0);", page_js("submitForm"))                                     # 정보 탭에서 보내도 대화로 돌아와요

    # 코드 검토 지적 ①의 다섯 문장과 펜스: 쓴 글자 그대로 보여야 해요
    KEEP = ["`f(**kwargs)` 와 `g(**opts)` 를 고쳤어요", "https://example.com/**a**/b", "굵게(`**`)와 목록(`- `)을 그려요. 짝 없는 `**`는 그대로예요.",
            "`src/**/x` 와 `lib/**/y`", "x**2 + y**2 는 굵게가 아니에요"]
    FENCE = "고쳤어요.\n```py\ndef f(x, y):\n    return x**2 + y**2\n\n- 목록 아님\n1. 이것도\n```\n끝이에요."

    def test_md_lite_keeps_code_and_links(self):
        """백틱 코드, ``` 펜스, 주소 안의 **와 목록 기호는 쓴 글자 그대로예요. 펜스 안 들여쓰기와 빈 줄도 남아요(코드 검토 ①)."""
        code = page_js("esc", "mdLite") + f"\nconst KEEP = {json.dumps(self.KEEP, ensure_ascii=False)}, FENCE = {json.dumps(self.FENCE, ensure_ascii=False)};\n" + """
const text = h => h.replace(/<br>/g, '\\n').replace(/<\\/?(?:p|strong|ul|ol|li)[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const MORE = ['`a **b** c` 는 코드예요', 'https://x.com/-**b**-', '2**10** 은 1024예요'];   // 백틱·주소 안의 짝, 글자 바로 뒤의 짝
console.log(JSON.stringify({ keep: KEEP.map(k => [mdLite(k), text(mdLite(k))]), more: MORE.map(k => [mdLite(k), text(mdLite(k)), k]), pair: mdLite('**a** 그리고 **b**'), fence: mdLite(FENCE), open: mdLite('```\\n**a**\\n- b'), bold: mdLite('**결론**은 됐어요. 이건**중요**해요. "**따옴표**"'), sep: mdLite('- 앞\\u2028뒤').replace(/\\u2028/g, '[LS]') }));
"""
        r = self.node(code)
        for (html_, shown), want in zip(r["keep"], self.KEEP):
            self.assertEqual(shown, want, html_)
            self.assertNotIn("<strong>", html_)
        f = r["fence"]
        self.assertIn("<p>```py<br>def f(x, y):<br>    return x**2 + y**2<br><br>- 목록 아님<br>1. 이것도<br>```</p>", f)   # 펜스는 한 문단, 들여쓰기·빈 줄 그대로
        self.assertEqual((f.count("<li"), f.count("<strong>")), (0, 0))
        self.assertTrue(f.startswith("<p>고쳤어요.</p>") and f.endswith("<p>끝이에요.</p>"), f)
        self.assertEqual(r["open"], "<p>```<br>**a**<br>- b</p>")                              # 닫지 않은 펜스도 끝까지 글자 그대로
        self.assertEqual(r["bold"], '<p><strong>결론</strong>은 됐어요. 이건<strong>중요</strong>해요. &quot;<strong>따옴표</strong>&quot;</p>')   # 한국어 토씨와 따옴표 옆 굵게는 그대로 돼요
        self.assertEqual(r["sep"], "<ul><li>앞[LS]뒤</li></ul>")                              # U+2028이 있어도 목록이에요(출력은 [LS]로 바꿔 받아요)
        for html_, shown, want in r["more"]:
            self.assertEqual(shown, want, html_)
            self.assertNotIn("<strong>", html_)
        self.assertEqual(r["pair"], "<p><strong>a</strong> 그리고 <strong>b</strong></p>")   # 짝이 둘이면 작은 제목이 아니에요

    def test_md_lite_stays_fast(self):
        """목록 기호 뒤 긴 빈칸과 U+2028, 굵게가 많은 긴 글도 빨리 그려요(코드 검토 ②). 서랍을 열 때 페이지가 멈추지 않아요."""
        code = page_js("esc", "mdLite") + """
const time = s => { const t = process.hrtime.bigint(); mdLite(s); return Number(process.hrtime.bigint() - t) / 1e6; };
console.log(JSON.stringify({ sep: time('- ' + ' '.repeat(80000) + 'a\\u2028b'), nbsp: time('1. ' + '\\u00a0'.repeat(80000) + 'a\\u2029b'), bold: time('**a** '.repeat(40000)), stars: time('*'.repeat(80000)), ticks: time('`a**b` '.repeat(20000)), lines: time('- 줄\\n'.repeat(5000)) }));
"""
        r = self.node(code)
        for k, ms in r.items():
            self.assertLess(ms, 50, (k, r))

    def test_new_answer_while_reading_info(self):
        """정보 탭을 보는 동안 온 답은 읽은 걸로 하지 않고 [대화] 탭에 '새 답'을 달아요. 대화로 돌아오면 읽은 걸로 해요(코드 검토 5)."""
        code = """
const seen = [], tab = { html: '', insertAdjacentHTML(w, h) { this.html += h; } }, talk = { hidden: false };
const dot = { remove() { tab.html = ''; } }, $ = (q, r) => (q === '#dTab0' ? tab : q === '#dTalk' ? talk : q === '.new-dot' ? (tab.html.includes('new-dot') ? dot : null) : null);
const markSeen = (f, t) => seen.push(t);
let live = { file: 'c', lastT: 'a' };
""" + page_js("talkSeen") + """
const out = {};
talkSeen(); out.open = [seen.slice(), tab.html];
talk.hidden = true; live.lastT = 'b'; talkSeen(); out.away = [seen.slice(), tab.html];
talkSeen(); out.again = tab.html;
talk.hidden = false; talkSeen(); out.back = [seen.slice(), tab.html];
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        self.assertEqual(r["open"], [["a"], ""])
        self.assertEqual(r["away"], [["a"], '<span class="new-dot"><span class="su-sr"> </span>새 답</span>'])   # 탭 이름은 '대화 새 답'
        self.assertEqual(r["again"], r["away"][1])                                            # 한 번만 달아요
        self.assertEqual(r["back"], [["a", "b"], ""])
        self.assertIn("talkSeen();", page_js("refreshThread"))
        self.assertIn("if (i === 0) talkSeen();", page_js("dTab"))

    def test_drawer_names_read_apart(self):
        """서랍과 탭 목록 이름이 '팀장, 가짜층 팀'처럼 띄어 읽혀요. 따로 정한 이름도 '민수 개발자, …'예요(코드 검토 11)."""
        code = page_js("esc", "MUST_LINE", "dHead") + """
const relayBox = () => '', strip = h => h.match(/<h2[^>]*>(.*?)<\\/h2>/)[1].replace(/<[^>]+>/g, '');
console.log(JSON.stringify({ a: strip(dHead({ title: '팀장', team: '가짜층 팀' })), b: strip(dHead({ title: '민수<small class="rl">개발자</small>', team: '가짜층 팀' })) }));
"""
        self.assertEqual(self.node(code), {"a": "팀장, 가짜층 팀", "b": "민수 개발자, 가짜층 팀"})



@unittest.skipUnless(CHROME, "크롬이 없어요(CSS 시험은 진짜 브라우저로 재요)")
class PageFits(unittest.TestCase):
    """CSS는 node로 잴 수 없어요. 페이지 CSS로 진짜 브라우저에서 재요."""
    HDR = re.search(r'<header class="hdr">.*?</header>', SRC, re.S).group(0)
    SHOW = "const $ = q => document.querySelector(q), show = (q, t) => { const e = $(q); e.hidden = false; if (t) e.innerHTML = t; return e; }, say = o => { $('#out').textContent = JSON.stringify(o); };"

    def test_more_line_can_be_pressed(self):
        """폰에서 빈자리 줄의 [자세히]도 24 이상이에요(운영 ★D3)."""
        box = '<ul class="ro-list"><li class="r"><div class="seat"><details class="su-more"><summary>자세히</summary><p class="hint">글</p></details></div></li></ul>'
        for w in (360, 320):
            r = in_browser(box, self.SHOW + "const b = $('.su-more > summary').getBoundingClientRect(); say({ w: b.width, h: b.height });", w)
            self.assertGreaterEqual((r["w"], r["h"]), (24, 24), w)
            self.assertGreaterEqual(r["h"], 24, w)

    def test_vacant_note_only_on_first_row(self):
        """빈자리 안내 줄은 층의 첫 빈자리에만 있어요. 단추와 [자세히]가 한 줄이라 빈자리가 많아도 명단이 짧아요."""
        row = '<li class="r"><div class="r-main">자리</div><div class="seat"><div class="seat-acts"><button class="btn primary">세션 만들기</button></div><p class="hint" data-must>Claude 창에 첫 메시지를 채워 둬요. 읽어 보고 Enter를 눌러야 보내져요.</p><details class="su-more"><summary>자세히</summary><p class="hint">글</p></details></div></li>'
        box = '<ul class="ro-list"><li class="r"><div class="r-main">팀장</div></li>' + row * 3 + '</ul>'
        size = self.SHOW + """const seats = [...document.querySelectorAll('.r .seat')], tall = e => e.getBoundingClientRect().height, s = seats[1].querySelector('summary').getBoundingClientRect(), b = seats[1].querySelector('.btn').getBoundingClientRect();
say({ first: tall(seats[0].querySelector('[data-must]')), second: tall(seats[1].querySelector('[data-must]')), third: tall(seats[2].querySelector('[data-must]')), row: tall(seats[1].parentNode), same: Math.abs((s.top + s.bottom) / 2 - (b.top + b.bottom) / 2) < 8, press: s.height, over: document.documentElement.scrollWidth - innerWidth });"""
        wide, phone = in_browser(box, size), in_browser(box, size, 360)
        for r in (wide, phone):
            self.assertGreater(r["first"], 0)
            self.assertEqual((r["second"], r["third"], r["over"]), (0, 0, 0))
            self.assertTrue(r["same"])
        self.assertLess(wide["row"], 100)                   # 디자이너 값 92px, 전에는 190px
        self.assertGreaterEqual(phone["press"], 44)
        self.assertNotIn("""where === 'r' ? '<p class="seat-st">아직 세션이 없어요.</p>'""", SRC)
        self.assertIn("""${so ? '' : '<span class="r-task">아직 세션이 없어요.</span>'}""", SRC)

    def composer(self):
        code = page_js("HO_FIELDS", "HO", "SAY_KEYS", "composerHTML") + """
const API = true, esc = String, relayNote = () => '';
console.log(JSON.stringify(composerHTML('say', '', '여기에', 'k', true)));
"""
        r = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout).replace('<div class="att-band" hidden>', '<div class="att-band">').replace('<ul class="att" aria-label="보낼 사진"></ul>', '<ul class="att" aria-label="보낼 사진"><li></li><li></li><li></li><li></li></ul>')

    def test_note_beside_chips_stays_at_every_width(self):
        """사진이 붙어도 칩 옆 사실 한 줄은 어떤 폭에서도 남아요. 좁은 창(559 이하)은 단축키 줄을 늘 숨기고, 글칸은 한 줄이에요(U-29 5번). 진짜 작성창으로 재요."""
        box = f'<div class="drawer-panel chat"><div id="drawerBody">{self.composer()}</div></div>'
        script = self.SHOW + "const r = $('.att-note').getBoundingClientRect(), t = $('textarea[name=\"text\"]').getBoundingClientRect(), h = $('.ho-tg').getBoundingClientRect(); say({ note: r.width > 0 && r.height > 0, keys: getComputedStyle($('.keys')).display, box: Math.round(t.height), ho: Math.round(h.height), over: document.documentElement.scrollWidth - innerWidth });"
        for w, h, keys, ho in ((320, 568, "none", 44), (360, 740, "none", 44), (640, 460, "block", 44), (1000, None, "block", 24)):
            r = in_browser(box, script, w, h)
            self.assertTrue(r["note"], (w, h))
            self.assertEqual(r["keys"], keys, (w, h))
            self.assertEqual(r["box"], 46, (w, h))
            self.assertGreaterEqual(r["ho"], ho, (w, h))                                     # 폰에서는 [일 맡기기]도 44px예요
            self.assertEqual(r["over"], 0, (w, h))

    def drawer_box(self, ho=False):
        """진짜 팀원 서랍(memberDrawer)에 긴 대화를 넣은 조각. 끊김 띠도 떠 있어요. ho면 [일 맡기기]를 켠 작성창이에요."""
        code = ChatDrawer.drawer_js() + ("\nHO.add('t:팀장');" if ho else "") + "\nlet PIC_V = 0;\nconst seatText = (t, r) => r;\n" + page_js("PIC_NAME", "ATT", "picUrl", "linePics", "picsHTML", "mdLite", "TURN_GAP", "sameTurn", "lineHTML", "linesHTML", "threadHTML") + """
const t0 = Date.parse('2026-11-03T01:00:00Z'), at = m => new Date(t0 + m * 60000).toISOString(), L = (m, from, text) => ({ t: at(m), from, text });
const long = '진행 결과예요.\\n\\n**한 일**\\n- 어두운 테마 단추 테두리를 3.4:1에서 4.6:1로 올렸어요.\\n- 작은 창에서 단추가 한 줄에 들어가요.\\n- 첫 화면 시간을 다시 쟀어요.\\n\\n**남은 것**\\n1. 실제 폰 누르기\\n2. 배포 결정';
const lines = [L(0, '대표', '단추 크기 어떻게 됐어?'), L(3, '팀장', long), L(4, '팀장', '나머지는 오늘 끝내요.'), L(20, '대표', '좋아. 진행해'), L(40, '팀장', long), L(60, '대표', '고마워'), L(61, '팀장', long)];
memberDrawer('t', '팀장');
console.log(JSON.stringify({ html, thread: threadHTML(lines, 't') }));
"""
        r = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        empty, slot = '<ul class="thread" id="thread" aria-live="polite"></ul>', '<span class="d-x" data-close-slot></span>'
        self.assertEqual((out["html"].count(empty), out["html"].count(slot)), (1, 1))
        body = out["html"].replace(empty, empty.replace("</ul>", out["thread"] + "</ul>")).replace(slot, slot.replace("</span>", '<button class="d-close" id="drawerClose" type="button">닫기</button></span>'))
        return f'<div class="drawer"><div class="drawer-bg"></div><div class="drawer-panel chat" role="dialog"><div class="d-bar"></div><div id="drawerBody">{body}</div></div></div>'

    def test_chat_drawer_reads_well(self):
        """B '대화 먼저': 스크롤은 대화 칸 하나, 말은 15px / 24px, 대표 말풍선은 흑연색(어두움은 밝은 돌색), 위험한 일 줄과 머리 단추는 어떤 폭에서도 보여요(결정 2, 3, 5번)."""
        box = self.drawer_box()
        script = self.SHOW + """
if (window.DARK) document.documentElement.dataset.theme = 'dark';
const p = $('.drawer-panel'), th = $('#thread'), pb = p.getBoundingClientRect();
const scrolls = [p, ...p.querySelectorAll('*')].filter(e => { const s = getComputedStyle(e); return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 1 && e.clientHeight > 0; }).map(e => e.id || e.className);
const vis = q => { const e = $(q), b = e && e.getBoundingClientRect(); return !!b && b.height > 0 && b.top >= pb.top - 1 && b.bottom <= pb.bottom + 1 && b.right <= pb.right + 1 && getComputedStyle(e).display !== 'none'; };
const cs = q => { const s = getComputedStyle($(q)); return [s.fontSize, s.lineHeight, s.backgroundColor, s.color]; };
say({ scrolls, thread: Math.round(th.getBoundingClientRect().height), must: vis('.d-must'), close: vis('#drawerClose'), open: vis('.d-open'), relay: vis('.d-relay'), ho: vis('.ho-tg'), send: vis('button[type="submit"]'),
  keys: getComputedStyle($('.keys')).display, ta: Math.round($('textarea[name="text"]').getBoundingClientRect().height), me: cs('.msg.me .b'), them: cs('.msg:not(.me):not(.sys) .b'), p: cs('.md p').slice(0, 2), li: cs('.md li').slice(0, 2),
  indent: (() => { const li = document.createElement('li'); li.className = 'msg'; li.innerHTML = '<div class="b md"><p>```<br>    return x**2<br>```</p></div>'; th.appendChild(li); const t = li.innerText; li.remove(); return t.includes('    return x**2'); })(),
  tabs: [...document.querySelectorAll('[role="tab"]')].map(t => { const b = t.getBoundingClientRect(); return Math.min(b.width, b.height); }), tabH: Math.max(...[...document.querySelectorAll('[role="tab"]')].map(t => Math.round(t.getBoundingClientRect().height))), ul: getComputedStyle($('.md ul')).listStyleType, whoH: Math.round($('.msg .who').getBoundingClientRect().height), sendH: Math.round($('.c-box > button').getBoundingClientRect().height),
  over: document.documentElement.scrollWidth - innerWidth, pover: p.scrollWidth - p.clientWidth });
"""
        for w, h, tall in ((1280, 800, 480), (640, 460, 140), (375, 812, 360), (320, 568, 150)):
            r = in_browser(box, script, w, h)
            self.assertEqual(r["scrolls"], ["thread"], (w, h))
            self.assertGreaterEqual(r["thread"], tall, (w, h))
            for k in ("must", "close", "open", "relay", "ho", "send"):
                self.assertTrue(r[k], (k, w, h))
            self.assertEqual(r["keys"], "none" if w < 560 else "block", (w, h))
            self.assertEqual(r["ta"], 46, (w, h))
            self.assertEqual(r["me"], ["15px", "24px", "rgb(46, 50, 57)", "rgb(241, 239, 234)"], (w, h))
            self.assertEqual(r["them"][:3], ["15px", "24px", "rgb(230, 227, 220)"], (w, h))
            self.assertEqual((r["p"], r["li"]), (["15px", "24px"], ["15px", "24px"]), (w, h))
            self.assertEqual(r["ul"], "disc", (w, h))                                         # 점 목록은 채운 점이에요
            self.assertTrue(r["indent"], (w, h))                                              # 펜스 안 들여쓰기가 화면에서도 남아요(pre-wrap)
            self.assertGreaterEqual(min(r["tabs"]), 44 if w <= 720 else 24, (w, h))          # 탭도 누를 곳이 24px, 폰은 44px 이상(운영 ★D3)
            self.assertLessEqual(r["tabH"], 44, (w, h))                                       # '정보 주고받은 메시지 3 · 보고서 1'도 320폭에서 한 줄이에요
            self.assertLessEqual(r["whoH"], 20, (w, h))                                      # 이름과 시각은 한 줄이에요
            self.assertLessEqual(r["sendH"], 46, (w, h))                                     # [보내기]는 한 줄이에요
            self.assertEqual((r["over"], r["pover"]), (0, 0), (w, h))
        dark = in_browser(box, "window.DARK = 1;" + script, 1280, 800)
        self.assertEqual(dark["me"][2:], ["rgb(217, 213, 204)", "rgb(22, 24, 28)"])
        self.assertEqual(dark["them"][2], "rgb(37, 41, 48)")

    def test_hostile_words_run_no_script(self):
        """조작한 세션 답과 대표 말을 진짜 브라우저에 그려도 스크립트가 돌지 않고, 말풍선 안에는 정해진 여섯 태그만 생겨요(결정 7번)."""
        code = ChatDrawer.thread_js() + "\nconst H = " + json.dumps(HOSTILE, ensure_ascii=False).replace("<", "\\u003c") + ";\n" + """
const lines = H.flatMap((text, i) => [{ t: '2026-11-03T01:0' + (i % 10) + ':00Z', from: '개발자', text }, { t: '2026-11-03T02:0' + (i % 10) + ':00Z', from: '대표', text }]);
document.getElementById('thread').innerHTML = threadHTML(lines, 't');
setTimeout(() => {
  const tags = [...new Set([...document.querySelectorAll('#thread .b *')].map(e => [e.tagName.toLowerCase(), ...[...e.attributes].map(a => a.name)].join(' ')))].sort();
  const me = [...document.querySelectorAll('#thread .msg.me .b')].map(b => b.textContent);
  document.getElementById('out').textContent = JSON.stringify({ hit: globalThis.hit || 0, tags, me, them: [...document.querySelectorAll('#thread .msg:not(.me) .b')].map(b => b.textContent) });
}, 600);
"""
        r = in_browser('<ul class="thread" id="thread"></ul>', code)
        self.assertEqual(r["hit"], 0)
        self.assertLessEqual(set(r["tags"]), {"p", "p class", "br", "strong", "ul", "ol", "li", "li value"})
        self.assertEqual(r["me"], HOSTILE)                                                   # 대표 말은 쓴 글자 그대로 보여요
        self.assertIn('<img src=x onerror="globalThis.hit=1">', r["them"][0])
        self.assertIn("&lt;script&gt;", r["them"][10])                                       # 미리 바꿔 쓴 글도 글자 그대로예요

    def test_attach_also_button_is_big_enough_on_phones(self):
        """[사진도 붙이기]는 720폭 아래에서 44px예요. 뒤의 30px 규칙이 덮으면 안 돼요."""
        box = '<form class="composer"><p class="att-also">복사한 사진은 안 붙였어요. <button type="button" data-att-also>사진도 붙이기</button></p></form>'
        script = self.SHOW + "const b = $('[data-att-also]').getBoundingClientRect(); say({ h: Math.round(b.height), w: Math.round(b.width) });"
        self.assertEqual(in_browser(box, script, 375)["h"], 44)
        self.assertEqual(in_browser(box, script, 721)["h"], 30)

    def test_picture_cells_hold_their_place(self):
        """칸은 사진이 오기 전에 자리를 잡아요. 그래서 사진이 떠도 맨 아래가 어긋나지 않아요."""
        pics = lambda n: f'<span class="msg-pics" data-n="{n}">' + '<button class="pic"></button>' * n + '</span>'
        box = f'<div class="drawer-panel chat" style="margin:0"><div id="drawerBody"><div class="d-main"><div class="d-talk"><ul class="thread"><li class="msg"><div class="b md">{pics(1)}</div></li><li class="msg me"><div class="b">{pics(4)}</div></li></ul></div></div></div></div>'
        script = self.SHOW + "const s = e => { const b = e.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; }, c = document.querySelectorAll('.pic'); say({ one: s(c[0]), four: s(c[1]), over: document.documentElement.scrollWidth - innerWidth });"
        for w, h, one, four in ((1280, None, [200, 150], [148, 111]), (640, 460, [148, 111], [148, 111])):
            r = in_browser(box, script, w, h)
            self.assertEqual((r["one"], r["four"], r["over"]), (one, four, 0), (w, h))
        r = in_browser(box, script, 320, 800)                                               # 폰은 폭에 맞춰 줄어도 4:3이에요(실제 서랍 값은 Chrome 재기에 있어요)
        self.assertEqual(r["over"], 0)
        self.assertLess(r["four"][0], 148)
        self.assertLess(abs(r["four"][0] * 3 - r["four"][1] * 4), 6)

    def test_floor_tools_menu_stays_on_screen(self):
        """폰에서 [층 도구] 메뉴 전체가 화면 안이에요."""
        room = '<div class="wrap"><section class="scene-card"><header class="sc-head"><span class="fl">1층</span><h2>쉬는층</h2><div class="counts"><span>대기 <b>6</b></span></div><span class="sp"></span><button class="btn">움직임 멈추기</button><details class="tools" id="floorTools" open><summary class="btn">층 도구</summary><div class="tools-menu"><button class="notion">팀원 고치기</button><code>~/projects/my-app</code></div></details></header></section></div>'
        for w in (360, 320):
            r = in_browser(room, self.SHOW + "const b = $('.tools-menu').getBoundingClientRect(); say({ left: b.left, right: b.right, width: b.width, height: b.height, page: innerWidth, over: document.documentElement.scrollWidth - innerWidth });", w)
            self.assertGreater(r["width"], 200, w)        # 칸 폭으로 줄어들면 글자가 세로로 서요
            self.assertLess(r["height"], 200, w)
            self.assertGreaterEqual(r["left"], 0, w)
            self.assertLessEqual(r["right"], r["page"], w)
            self.assertEqual(r["over"], 0, w)

    def test_phone_header_keeps_its_buttons_whole(self):
        """폰 머리말에 결재함과 표시가 같이 있어도 [⋯]의 점이 테두리에 닿지 않아요."""
        for w in (360, 320):
            r = in_browser(self.HDR, self.SHOW + "show('#apprBtn'); show('#hdrNote', '총괄 끊김 +1'); const m = $('#hdrMore').getBoundingClientRect(), i = $('#hdrMore svg').getBoundingClientRect(); say({ gap: m.right - i.right, right: m.right, page: innerWidth, over: document.documentElement.scrollWidth - innerWidth });", w)
            self.assertGreaterEqual(r["gap"], 6, w)
            self.assertLessEqual(r["right"], r["page"], w)
            self.assertEqual(r["over"], 0, w)

    def test_wide_header_wraps_long_notes(self):
        """1000폭에서 총괄 멈춤 글과 새 버전 칩이 같이 떠도 가로로 넘치지 않고 [설정]이 화면 안이에요."""
        step = re.search(r"const STUCK_STEP = '([^']*)'", SRC).group(1)
        stuck = f'총괄 창이 멈췄을 수 있어요(전달 대기 <b>3</b>). {step} <a href="#">총괄 창 열기 ↗</a>'.replace('"', '\\"')
        r = in_browser(self.HDR, self.SHOW + f"""show('#apprBtn'); show('#relay', "{stuck}").className = 'live alert'; show('#upd', '새 버전 <b>0.10.1</b> 있어요 <button class="btn">업데이트</button> <a href="#">바뀐 점</a>'); show('#setupBtn');
const b = $('#setupBtn').getBoundingClientRect(); say({{ over: document.documentElement.scrollWidth - innerWidth, right: b.right, page: innerWidth }});""", 1000)
        self.assertEqual(r["over"], 0)
        self.assertLessEqual(r["right"], r["page"])

    def test_thread_follows_the_bottom_when_it_shrinks(self):
        """맨 아래를 보던 대화 칸은 끊김 띠, 여러 줄 글칸, [일 맡기기] 때문에 줄어도 맨 아래예요. 새 줄이 와도요. 위를 읽던 중이면 그대로 둬요(코드 검토 ②).
        헤드리스 크롬의 --dump-dom은 그리기 단계(ResizeObserver·scroll 사건)를 돌리지 않아서, 진짜 배치에서 그 두 길(thFollow·thMark)을 직접 불러요.
        두 길이 ResizeObserver와 scroll에 걸려 있는지는 아래 글자 검사로, 실제로 불리는지는 가짜 층 크롬 흐름(CDP)으로 봐요."""
        box = self.drawer_box()
        script = self.SHOW + "\n" + page_js("thPinned", "thMark", "thFollow") + """
const el = $('#thread'), band = $('.d-relay'), ta = $('textarea[name="text"]'), ho = $('.ho'), gap = () => Math.round(el.scrollHeight - el.scrollTop - el.clientHeight), out = {};
band.hidden = true; el.scrollTop = el.scrollHeight; thMark(el);
band.hidden = false; out.before = gap(); thFollow(el); out.band = gap();                    // 띠가 생겼어요(ResizeObserver가 부르는 길)
ta.value = '1\\n2\\n3\\n4\\n5\\n6'; thFollow(el); out.lines = gap();                          // 여러 줄 글칸
ta.hidden = true; ho.hidden = false; ho.disabled = false; thFollow(el); out.ho = gap();      // 일 맡기기
el.insertAdjacentHTML('beforeend', '<li class="msg"><div class="b md"><p>새 답</p></div></li>'); if (thPinned(el)) el.scrollTop = el.scrollHeight; out.append = gap();
el.scrollTop = 40; thMark(el); out.pin = el._pin; ho.hidden = true; ta.hidden = false; ta.value = ''; band.hidden = true; thFollow(el); out.reading = el.scrollTop;
say(out);
"""
        for w, h in ((1280, 800), (375, 812)):
            r = in_browser(box, script, w, h)
            self.assertGreater(r["before"], 40, (w, h))                                       # 따라가지 않으면 틈이 생겨요(코드 검토에서 잰 51px)
            self.assertEqual((r["band"], r["lines"], r["ho"], r["append"]), (0, 0, 0, 0), (w, h))
            self.assertFalse(r["pin"], (w, h))
            self.assertEqual(r["reading"], 40, (w, h))
        watch = page_js("thWatch")
        for part in ("new ResizeObserver(() => thFollow(th))", "TH_RO.observe(th)", "addEventListener('scroll', () => thMark(th)", "th._pin = true;"):
            self.assertIn(part, watch)
        for fn in ("refreshThread", "attPaint", "dTab"):
            self.assertIn("thPinned(", page_js(fn), fn)                                      # 그 순간의 거리 대신 기억한 값을 써요
        self.assertIn("if (th) thWatch(th);", page_js("openThread"))

    def test_handoff_fits_small_windows(self):
        """[일 맡기기] 네 칸을 채워도 [보내기]·[일 맡기기]·위험한 일 줄·[닫기]가 서랍 안에 보이고, 칸으로 초점이 가도 머리가 밀리지 않아요(코드 검토 ③)."""
        box = self.drawer_box(ho=True)
        # 초점을 옮긴 뒤 iframe 안에서는 헤드리스 크롬이 프레임을 멈춰서, 기다리지 않고 바로 재요(배치는 읽을 때 맞춰져요)
        script = self.SHOW + """
const p = $('.drawer-panel'), pb = () => p.getBoundingClientRect(), inside = q => { const b = $(q).getBoundingClientRect(), r = pb(); return b.height > 0 && b.top >= r.top - 1 && b.bottom <= r.bottom + 1; };
const fill = [80, 30, 20, 80].map(n => window.LONG ? 160 : n);
[...document.querySelectorAll('textarea[data-ho]')].forEach((t, i) => { t.value = '가나다라마 '.repeat(fill[i] / 6 + 1).slice(0, fill[i]); });
[...document.querySelectorAll('textarea[data-ho]')].pop().focus();
$('button[type="submit"]').focus();
say({ send: inside('button[type="submit"]'), toggle: inside('.ho-tg'), must: inside('.d-must'), close: inside('#drawerClose'), scroll: p.scrollTop + $('#drawerBody').scrollTop, clip: getComputedStyle(p).overflowY, thread: Math.round($('#thread').getBoundingClientRect().height), over: document.documentElement.scrollWidth - innerWidth });
"""
        for w, h, long_ in ((640, 432, False), (640, 460, False), (320, 568, False), (375, 812, True)):
            r = in_browser(box, ("window.LONG = 1;" if long_ else "") + script, w, h)
            for k in ("send", "toggle", "must", "close"):
                self.assertTrue(r[k], (k, w, h, r))
            self.assertEqual((r["scroll"], r["over"]), (0, 0), (w, h))
            self.assertEqual(r["clip"], "clip", (w, h))                                       # 넘쳐도 초점 때문에 서랍이 스크롤되지 않아요(머리가 밀리지 않게)
            self.assertGreaterEqual(r["thread"], 60, (w, h))                                 # 대화 칸도 두 줄쯤은 남아요

    def test_relay_band_keeps_keyboard_focus(self):
        """띠의 [다시 연결]을 키보드로 누르고 띠가 바뀌거나 숨어도 초점은 서랍 안이에요(코드 검토 ④)."""
        box = self.drawer_box()
        script = self.SHOW + "\nconst $$ = (s, r = document) => Array.from(r.querySelectorAll(s));\nlet REARM = null, API = true, state = { relay: null, org: { boss: { sessionId: 'local_b' } } };\nconst realBoss = () => true, chatLink = id => 'claude://' + id;\n" + page_js(
            "esc", "put", "REARM_MS", "rearmStep", "relayBtn", "relayStuck", "STUCK_STEP", "RELAY_DOWN", "relayWarn", "rearmBand", "relayBand", "relayPaint") + """
const at = () => { const a = document.activeElement; return [a.dataset.act || a.id || a.tagName, a.textContent.trim().slice(0, 12), !!a.closest('.drawer-panel')]; };
$('.d-relay [data-act="relay-rearm"]').focus(); const out = { start: at() };
REARM = { at: Date.now(), copied: true }; relayPaint(); out.rearm = at();
REARM = null; relayPaint(); out.back = at();
state.relay = { relayAge: 3, pending: 0 }; relayPaint(); out.hidden = [$('.d-relay').hidden, ...at()];
say(out);
"""
        r = in_browser(box, script)
        self.assertEqual(r["start"], ["relay-rearm", "다시 연결", True])
        self.assertEqual(r["rearm"], ["relay-rearm", "총괄 창 다시 열기", True])
        self.assertEqual(r["back"], ["relay-rearm", "다시 연결", True])
        self.assertEqual(r["hidden"][0], True)
        self.assertTrue(r["hidden"][3], r)                                                    # 띠가 숨으면 [대화] 탭이나 [닫기]로 가요

    def test_my_bubble_keeps_contrast(self):
        """대표 말풍선 안 '사진을 찾지 못했어요'는 4.5:1, 사진 초점 테두리는 3:1 이상이에요. 밝음·어두움 모두요(코드 검토 ⑤)."""
        box = '<div class="drawer-panel chat"><ul class="thread"><li class="msg me"><div class="b">글<span class="msg-pics" data-n="2"><button type="button" class="pic pic-miss" disabled>사진을 찾지 못했어요</button><button type="button" class="pic" id="pp"></button></span></div></li></ul></div>'
        script = self.SHOW + """
if (window.DARK) document.documentElement.dataset.theme = 'dark';
const rgb = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number), lum = c => { const [r, g, b] = rgb(c).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return Math.round((x + 0.05) / (y + 0.05) * 100) / 100; };
const bg = getComputedStyle($('.msg.me .b')).backgroundColor, miss = getComputedStyle($('.pic-miss'));
$('#pp').focus();
say({ text: ratio(miss.color, bg), edge: ratio(miss.borderTopColor, bg), seen: $('#pp').matches(':focus-visible'), focus: ratio($('#pp').matches(':focus-visible') ? getComputedStyle($('#pp')).outlineColor : getComputedStyle($('.msg.me .b')).color, bg) });
"""
        for dark in (False, True):
            r = in_browser(box, ("window.DARK = 1;" if dark else "") + script)
            self.assertGreaterEqual(r["text"], 4.5, (dark, r))
            self.assertGreaterEqual(r["edge"], 3, (dark, r))
            self.assertGreaterEqual(r["focus"], 3, (dark, r))                                  # 크롬이 :focus-visible을 안 주면 그 규칙의 색(--me-ink)으로 재요
        self.assertIn(".msg.me .pic:focus-visible{outline-color:var(--me-ink)}", SRC)



class ScenePage(unittest.TestCase):
    def test_wiring(self):
        self.assertIn("data-stage-slot", page_js("roomHTML"))
        # 방을 다시 그린 바로 뒤에 장면을 돌려놓아요(보던 위치를 읽기 전에), 글을 미룰 때도 장면은 갱신해요, 서랍이 열려 있어도 읽어요
        self.assertLess(SRC.index("stageMount(cur, cur && teams[cur.id])"), SRC.index("if (redrawn && sameRoom) $$(ROOM_SCROLLS)"))
        self.assertIn("pending = true; stageSync(); countsPaint(); drawerPaint(); return;", page_js("load"))
        self.assertIn("($('#drawer').hidden || STAGE.scene)", SRC)
        # 책상 카드에 기댔던 길은 명단 줄로 옮겼어요(누르기, 앉은 뒤 키보드). 버튼이라 Enter·Space는 저절로 돼요
        for sel in ("const seat = e.target.closest('.r-main[data-role]');\n  if (seat) { memberDrawer(seat.dataset.team, seat.dataset.role); return; }",
                    "$$('#rooms .r-main[data-role]').find(x => x.dataset.team === s.team && x.dataset.role === s.role)"):
            self.assertIn(sel, SRC)
        self.assertNotIn('.desk[data-role]', SRC)
        row = page_js("seatRowHTML")
        for part in ('data-member="${role}"', 'data-role="${role}"', 'data-nm-edit', "nameEditHTML(m, cx)", "seatBoxHTML(tid, m.role, 'r')", 'chatLink(m.sessionId)', "seatOk", '새 답', 'Codex'):
            self.assertIn(part, row)

    def test_page_follows_mockup(self):
        """시안의 순서·이름, 팀장 결정: 명단 제목 ‘팀원’, [움직임 멈추기], 지운 그림."""
        room = page_js("roomHTML")
        order = [room.index(x) for x in ('class="hero', 'data-stage-slot', 'class="roster"', 'class="grid3"', '서류함')]
        self.assertEqual(order, sorted(order))
        self.assertIn('<h3 id="rosterH">팀원</h3>', room)
        self.assertIn('data-act="stage-still"', room)
        for gone in ("function sceneSVG", "function meetingSVG", "function deskHTML", "곧 합류해요", "합류 전"):
            self.assertNotIn(gone, SRC)
        self.assertLess(SRC.index('id="rooms"'), SRC.index('id="talk"'))   # 팀 간 대화는 방 아래로

    def test_page_uses_voxel_frame(self):
        """돌·흑연색 토큰, 시스템 글꼴, 무늬 없음. 예전 크림·남보라와 그림 토큰은 없어요."""
        for value in ("--floor:#DEDBD4", "--surface:#F1EFEA", "--floor:#121419", "--surface:#1B1E24", "--a-a:#14694A", "--on-s:#FFFFFF", "--on-s:#14161B"):
            self.assertIn(value, SRC)
        self.assertEqual(SRC.count("--sc-bg:"), 3)          # 밝음 + 어두움 둘
        for gone in ("#FFF7EC", "#191630", "--floor-2", "--sc-floor", "--desk-top", "--screen", "--rack", "screenGlow", "Do Hyeon", "Do+Hyeon", "Nanum", "repeating-conic", ".cold", "IBM Plex", "googleapis", "gstatic", "document.fonts", "stageColors", "stageFloors", "stageFonts", "자리 비움"):
            self.assertNotIn(gone, SRC)
        self.assertIsNone(re.search(r"""(?:href|src)=["']https?://[^"']*\.(?:css|woff2?)""", SRC))   # 글꼴은 바깥에서 받지 않아요
        for pat in (r"border-radius:999px", r"border-radius:\d\d+px"):
            self.assertIsNone(re.search(pat, SRC))           # 각진 모서리: 2~4px

    def test_status_dots_match_dark_tokens(self):
        """장면 이름표는 어두운 판이라 상태 점이 어두움 토큰과 같은 값이에요."""
        dot = re.search(r"const DOT = \{(.*?)\};", scene_code()).group(1)
        dark = re.search(r':root\[data-theme="dark"\]\{(.*?)\}', SRC, re.S).group(1)
        for name in ("work", "ok", "meet", "err", "rest"):
            self.assertIn(re.search(r"--" + name + r":(#[0-9A-F]{6})", dark).group(1), dot)

    def test_scene_has_no_own_loop(self):
        """고리는 페이지 것 하나예요. 두 번 돌면 안 돼요."""
        code = scene_code()
        for bad in ("requestAnimationFrame", "cancelAnimationFrame", "IntersectionObserver", "ResizeObserver", "visibilitychange", "autostart", "start()", "stop()"):
            self.assertNotIn(bad, code)
        self.assertNotIn("sc.start", SRC)
        self.assertNotIn("sc.stop", SRC)
        self.assertNotIn("roundRect", code)                  # macOS 12에 없어요
        self.assertNotIn("OffscreenCanvas", code)

    def test_scene_code_is_ours(self):
        """그림은 코드로만: 장면 코드는 밖에서 아무것도 받지 않아요."""
        code = scene_code()
        for bad in ("http://", "https://", "fetch(", "import ", "new Image", "XMLHttpRequest", "<script", "fonts/"):
            self.assertNotIn(bad, code)


if __name__ == "__main__":
    unittest.main()
