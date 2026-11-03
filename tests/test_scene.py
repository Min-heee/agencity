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


def in_browser(body, script, width=1280):
    """페이지 CSS로 작은 조각을 진짜 브라우저에서 재요. CSS는 node로 잴 수 없어요. 포트를 열지 않아요."""
    css = re.search(r"<style[^>]*>(.*?)</style>", SRC, re.S).group(1)
    page = f'<!doctype html><meta charset="utf-8"><style>{css}</style><body>{body}<pre id="out"></pre><script>{script}</script>'
    if width < 500:   # 창은 500보다 좁아지지 않아요. 폰 폭은 iframe 안에서 재요
        frame = html.escape(page, quote=True)
        page = f'<!doctype html><pre id="out"></pre><iframe id="f" style="border:0;width:{width}px;height:800px" srcdoc="{frame}"></iframe><script>f.onload = () => {{ out.textContent = f.contentDocument.getElementById("out").textContent; }};</script>'
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
""" + page_js("LIVE_TAIL", "liveOn") + """
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
const stageSync = () => {}, countsPaint = () => {}, drawerPaint = () => {}, render = () => {}, relayNote = () => '';
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
        self.assertIn('aria-label="${esc(rowAria({ who, role: m.role, cx: cxm, chip, nw: newReply, when, task }))}"', SRC)    # 명단 줄이 이 글을 써요
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
        """팀원 서랍을 연 동안 세 칸만 따라와요. 닫은 뒤에는 건드리지 않아요."""
        code = self.SEAT.replace("ago = min =>", "old = min =>") + page_js("QUIET_SHORT", "seatView", "meetNow", "seatChip", "drawerFacts", "drawerPaint", "memberDrawer") + """
let DF = null;
const ago = () => '방금', esc = String, viewNow = () => NOW, API = true, EX_NO_TALK = '', hm = String;
const cxDrawer = () => {}, customName = () => '', teamNames = () => [], seatHTML = (t, r) => r, chatLink = String, exampleSeat = () => true, composerHTML = () => '', openDrawer = () => {}, openThread = () => {};
const drawer = { hidden: false }, cells = { '#dfState': {}, '#dfTask': {}, '#dfSay': {} }, $ = q => (q === '#drawer' ? drawer : cells[q]), put = (e, h) => { e.text = h; };
let state = { teams: { t: { base: 't/', reports: [], log: [], team: { members: [{ role: '개발자', sessionId: 'local_x', title: 'x' }] }, status: { 개발자: { state: '일하는 중', task: 'TO-1', say: '곧', updated: old(5) } } } } };
const look = () => ['#dfState', '#dfTask', '#dfSay'].map(k => cells[k].text);
memberDrawer('t', '개발자'); drawerPaint(); const a = look();
liveFake['개발자'] = { s: 'waiting', since: NOW - 9000 }; drawerPaint(); const b = look();
drawer.hidden = true; delete liveFake['개발자']; drawerPaint(); const c = look();
console.log(JSON.stringify({ a, b, c }));
"""
        r = self.node(code)
        self.assertEqual(r["a"], ["일하는 중 · 방금", "TO-1", "곧"])
        self.assertEqual(r["b"], ["확인 대기 · 방금", "TO-1", "곧"])
        self.assertEqual(r["c"], r["b"])

    def test_drawer_facts_follow_the_session(self):
        """서랍의 상태, 맡은 일, 한마디는 명단과 같은 값이에요. 맡은 일이 없으면 —예요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView", "seatChip", "drawerFacts") + """
const esc = String, viewNow = () => NOW, meetNow = () => null, isCxx = 0;
let state = { teams: { t: { team: { members: [{ role: '개발자', sessionId: 'local_x' }] }, status: { 개발자: { state: '대기', task: '', say: '', updated: ago(5) } } } } };
const rel = iso => '방금'; const a = drawerFacts('t', '개발자', rel); liveFake['개발자'] = { s: 'busy', since: NOW }; const b = drawerFacts('t', '개발자', rel);
liveFake['개발자'] = { s: 'quiet', since: NOW - 2e6 }; const c = drawerFacts('t', '개발자', rel); delete liveFake['개발자'];
state.teams.t.status.개발자 = { state: '일하는 중', updated: ago(420) }; const d = drawerFacts('t', '개발자', rel);
console.log(JSON.stringify({ a, b, c, d }));
"""
        r = self.node(code)
        self.assertEqual(r["a"], {"state": "대기 · 방금", "task": "—", "say": "—"})
        self.assertEqual(r["b"], {"state": "일하는 중 · 방금", "task": "—", "say": "—"})
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
        code = page_js("stageSelect") + """
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
