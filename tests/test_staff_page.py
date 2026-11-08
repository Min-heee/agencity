"""에이전시티 U-31 시험(S2 페이지): 직원 줄(스킬이 곧 직원)을 페이지가 빈자리로 보지 않고, 명단·서랍·장면·회의·설정에서 직원으로 보여 줘요.

python3 -m unittest discover -s tests -p test_staff_page.py      (저장소 맨 위에서)

test_scene.py처럼 화면 코드(office.src.html)의 함수를 그대로 꺼내 node에서 가짜 주변과 함께 돌려요. node가 없으면 건너뛰어요.
직원 줄을 알아보는 기준은 서버(office_server.py)의 함수를 ast로 꺼내 같은 줄들에 돌려 견줘요(서버를 켜거나 모듈을 읽지 않아요).
파이썬 표준 라이브러리만 써요. 진짜 세션·파일은 건드리지 않아요.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import unicodedata
import unittest

import test_scene   # 모듈로만 읽어요(그 안의 시험 묶음을 이 파일에서 다시 돌리지 않게 클래스를 꺼내 오지 않아요)
from test_scene import CHROME, ROOT, SRC, in_browser, page_js, scene_code

with open(os.path.join(ROOT, "office_server.py"), encoding="utf-8") as f:
    SERVER_SRC = f.read()

LEAD_SID = "local_aaaaaaaa-0000-4000-8000-000000000001"
DEV_SID = "local_aaaaaaaa-0000-4000-8000-000000000002"
STRAY = "local_aaaaaaaa-0000-4000-8000-000000000009"   # 직원 줄에 잘못 적힌 세션 id(옛 서버가 써 넣은 것처럼)


def server_ns(*names):
    """office_server.py의 맨 위 정의(함수·이름 붙인 값) 중 names만 꺼내 따로 돌려요."""
    want, nodes = set(names), []
    for n in ast.parse(SERVER_SRC).body:
        if isinstance(n, ast.FunctionDef) and n.name in want:
            nodes.append(n)
        elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in want for t in n.targets):
            nodes.append(n)
    ns = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "office_server.py", "exec"), ns)
    return ns


def page_block(name):
    """여러 줄에 걸친 const(…;로 끝나는 줄까지)를 꺼내요. page_js는 한 줄 const만 꺼내요."""
    m = re.search(r"\n(const " + re.escape(name) + r" = .*?;)\n", SRC, re.S)
    if not m:
        raise AssertionError(f"office.src.html에 {name}이 없어요")
    return m.group(1)


# 서버와 같은 기준인지 견줄 줄들: 세션 줄, 빈자리, 직원 줄(이름 꼴이 맞는 것·틀린 것·sessionId가 잘못 적힌 것), 직원과 같은 역할의 세션 줄,
# 팀장 직원 줄(깨진 줄), staff 칸의 여러 빈 값과 빈 값이 아닌 것, 대소문자만 다른 직원 역할, 모양이 이상한 줄
ROWS = [
    {"role": "팀장", "sessionId": LEAD_SID},
    {"role": "개발자", "sessionId": DEV_SID},
    {"role": "기획", "staff": "ag-planner", "sessionId": None, "name": "기획 직원"},
    {"role": "기획", "sessionId": STRAY},
    {"role": "QA", "sessionId": None},
    {"role": "마케팅", "staff": "ag-marketer"},
    {"role": "운영", "staff": "Bad Name", "sessionId": None},
    {"role": "데이터", "staff": "ag-data", "sessionId": STRAY},
    {"role": "팀장", "staff": "ag-lead"},
    {"role": unicodedata.normalize("NFD", "디자인"), "staff": "ag-design"},
    {"role": "a", "staff": ""}, {"role": "b", "staff": "  "}, {"role": "c", "staff": None}, {"role": "d", "staff": False},
    {"role": "e", "staff": 0}, {"role": "f", "staff": []}, {"role": "g", "staff": {}},
    {"role": "h", "staff": True}, {"role": "i", "staff": 1}, {"role": "j", "staff": ["x"]}, {"role": "k", "staff": {"a": 1}},
    {"role": "l", "staff": "ag-x\n"}, {"role": "m", "staff": "ag-" + "a" * 24}, {"role": "n", "staff": "ag-" + "a" * 25},
    {"role": "o", "staff": "AG-x"}, {"role": "p", "staff": "ag--"},
    {"role": "UI/UX", "staff": "ag-ui"}, {"staff": "ag-norole"}, {"role": 5, "staff": "ag-num"},
    {"role": "Ops", "sessionId": None}, {"role": "ops", "staff": "ag-ops"},
    "줄이 아님", ["목록"],
]


@unittest.skipUnless(shutil.which("node"), "node가 없어요(화면 코드 시험은 node로 돌려요)")
class StaffPage(unittest.TestCase):
    node = test_scene.SceneFrame.node
    SEAT = test_scene.SceneFrame.SEAT

    ROWJS = page_js("LEAD", "leadFirst", "ROLE_RE", "ROLE_BAN", "SID_RE", "roleKey", "roleOk", "cut", "SHOWN_MAX", "hiddenLabel",
                    "STAFF_RE", "skOn", "isSk", "skName", "skRole", "skRows", "shownRows", "hiddenRows", "heldSessions", "fillEmpty")

    def test_staff_rows_match_the_server(self):
        """isSk·skName·skRole이 서버의 is_staff_row·staff_of·staff_role과 같아요. shownRows도 서버 shown_rows와 같은 줄을 보여요(직원 줄과 그 역할의 줄은 빼요)."""
        o = server_ns("LEAD", "ROLE_RE", "NOT_ROLES", "STAFF_RE", "SHOWN_MAX", "is_role", "is_staff_row", "staff_of", "staff_role", "staff_keys", "shown_rows")
        want = {"rows": [[o["is_staff_row"](m), o["staff_of"](m) or "", o["staff_role"](m) or ""] for m in ROWS],
                "shown": [[i, r] for i, r in o["shown_rows"](ROWS)]}
        seen = {i for i, _ in o["shown_rows"](ROWS)}
        want["kept"] = len([m for i, m in enumerate(ROWS) if i not in seen and not o["staff_role"](m)])   # 서버 existing_team의 kept와 같은 수
        code = "const isCx = () => false, LEAD_X = 0;\n" + self.ROWJS + f"""
const ROWS = {json.dumps(ROWS, ensure_ascii=False)};
console.log(JSON.stringify({{ rows: ROWS.map(m => [isSk(m), skName(m), skRole(m)]), shown: shownRows(ROWS).map(x => [x.i, x.role]), kept: hiddenRows(ROWS).length,
  hidden: hiddenRows(ROWS), held: [...heldSessions(ROWS)], fill: fillEmpty(ROWS).map(m => m.role), list: skRows(ROWS).map(skRole) }}));
"""
        r = self.node(code)
        self.assertEqual(r["rows"], want["rows"])
        self.assertEqual(r["shown"], want["shown"])
        self.assertEqual(r["kept"], want["kept"])
        self.assertEqual([x for x in r["rows"] if x[0]][:3], [[True, "ag-planner", "기획"], [True, "ag-marketer", "마케팅"], [True, "", "운영"]])
        self.assertEqual([x[1] for x in r["shown"]], ["팀장", "개발자", "QA", "a", "b", "c", "d", "e", "f", "g"])   # 직원 줄·직원과 같은 이름의 세션 줄(기획, Ops)은 세션 자리가 아니에요
        self.assertIn("기획", r["hidden"])          # 직원과 같은 역할의 세션 줄은 그대로 두는 줄이에요(서버 kept와 같아요)
        for gone in ("운영", "마케팅", "데이터"):
            self.assertNotIn(gone, r["hidden"])     # 직원 줄은 깨진 줄로 알리지 않아요
        self.assertEqual(r["held"], [[STRAY, "기획"]])   # 직원 줄(데이터)에 잘못 적힌 세션은 앉은 게 아니에요
        self.assertEqual(r["fill"], ["QA", "a", "b", "c", "d", "e", "f", "g"])   # 빈자리 채우기는 직원 줄을 건너뛰어요
        self.assertEqual(r["list"], ["기획", "마케팅", "운영", "데이터", "디자인", "h", "i", "j", "k", "l", "m", "n", "o", "p", "ops"])

    def test_staff_seat_view(self):
        """직원 자리는 빈자리가 아니에요. 서버 신호(live의 staff 칸)가 먼저고, 없으면 서버가 쓴 status예요. 진행 중 회의의 참석자면 회의실, ×n은 2부터예요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView") + """
const m = { role: '기획', staff: 'ag-planner', sessionId: null };
const v = (s, am, live, mm) => { if (live) liveFake['기획'] = live; else delete liveFake['기획']; const x = seatView('t', mm || m, s, am, NOW); return [x.kind, x.state, x.label, x.task, x.quiet, x.stale, x.runs, x.updated, x.invited]; };
const work = { state: '일하는 중', task: 'U-3-기획 조사', say: '말', updated: ago(90) }, idle = { state: '대기', task: '', updated: ago(5) };
console.log(JSON.stringify({
  noLive: v(work), noLiveIdle: v(idle), noFile: v(null),
  busy: v(idle, null, { s: 'busy', since: NOW - 60000, staff: true, n: 1 }),
  busyFiled: v(work, null, { s: 'busy', since: NOW - 60000, staff: true, n: 3 }),
  idleTail: v(work, null, { s: 'idle', since: NOW - 3000, staff: true, n: 0 }),
  idleNow: v(idle, null, { s: 'idle', since: NOW, staff: true, n: 0 }),
  idleLate: v(work, null, { s: 'idle', since: NOW - 60000, staff: true, n: 0 }),
  unknownSince: v(idle, null, { s: 'idle', since: 0, staff: true, n: 0 }),
  sessionShaped: v(idle, null, { s: 'busy', since: NOW - 1000 }),
  meet: v(idle, { status: '진행 중', participants: ['팀장', '기획'] }),
  meetBusy: v(idle, { status: '진행 중', participants: ['기획'] }, { s: 'busy', since: NOW - 1000, staff: true, n: 1 }),
  meetOther: v(idle, { status: '진행 중', participants: ['팀장'] }),
  wrap: v(idle, { status: '정리 중', participants: ['기획'] }),
  badName: v(null, null, null, { role: '운영', staff: 'Bad Name' }),
  vacant: v(null, null, null, { role: 'QA', sessionId: null }),
}));
"""
        r = self.node(code)
        iso = lambda ms: __import__("datetime").datetime.fromtimestamp(ms / 1000, __import__("datetime").timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        now = test_scene.Date_ms("2026-10-31T12:00:00Z")
        self.assertEqual(r["noLive"][:7], ["staff", "일하는 중", "일하는 중", "U-3-기획 조사", "", False, 0])   # 서버가 바뀔 때만 써서 오래돼도 ‘응답 없음?’이 아니에요
        self.assertEqual(r["noLiveIdle"][:4], ["staff", "대기", "대기", ""])
        self.assertEqual(r["noFile"][:5], ["staff", "대기", "대기", "", ""])                   # 직원은 ‘아직 소식 없음’이 아니라 대기예요
        self.assertEqual(r["busy"][:4], ["staff", "일하는 중", "일하는 중", ""])               # 신호가 먼저예요(파일이 아직 대기여도)
        self.assertEqual(r["busy"][7], iso(now - 60000))                                     # 그 상태가 된 때
        self.assertEqual(r["busyFiled"][3:7], ["U-3-기획 조사", "", False, 3])                # 일꾼 셋: 이름표에 ×3
        self.assertEqual(r["idleTail"][1:4], ["대기", "대기", ""])                             # 서버가 이어 쓰기 꼬리(20초)를 둔 뒤 내린 대기예요: 세션의 8초 꼬리를 더 붙이지 않아요
        self.assertEqual(r["idleNow"][1:3], ["대기", "대기"])                                  # 방금(since=지금) 대기가 된 직원도 대기
        self.assertNotIn("liveOn", page_js("skView"))
        self.assertEqual(r["idleLate"][1:4], ["대기", "대기", ""])                             # 신호가 대기면 파일의 일하는 중을 따르지 않아요
        self.assertEqual(r["unknownSince"][7], r["noLiveIdle"][7])                           # 모르는 시각(0)이면 파일 시각
        self.assertTrue(r["noLiveIdle"][7])
        self.assertEqual(r["sessionShaped"][1], "대기")                                       # staff 표시가 없는 신호는 직원 신호가 아니에요
        self.assertEqual(r["meet"][1:3], ["회의 중", "회의 중"])                               # 서버는 직원에게 ‘회의 중’을 안 써요: 참석자면 회의실
        self.assertEqual(r["meetBusy"][1], "회의 중")
        self.assertFalse(r["meet"][8])                                                       # ‘아직 안 왔어요’가 아니에요
        self.assertEqual(r["meetOther"][1], "대기")
        self.assertEqual(r["wrap"][1], "대기")
        self.assertEqual(r["badName"][:2], ["staff", "대기"])                                 # 이름 꼴이 틀려도 빈자리가 아니에요
        self.assertEqual(r["vacant"][:2], ["vacant", "빈자리"])

    # 명단 줄(seatRowHTML)을 돌리는 주변. 시각 글(ago)은 ‘방금’으로, 상태 파일 시각은 분으로 만들어요
    ROW = SEAT.replace("ago = min =>", "old = min =>") + page_js("QUIET_SHORT", "seatView", "esc", "seatChip", "seatLine", "rowAria", "SEAT_CHIP", "seatDot", "avHTML", "icon", "SK_WHERE", "seatRowHTML") + """
const ago = x => (typeof x === 'number' ? old(x) : '방금'), customName = () => '', NE = null, lookOf = () => ({ skin: '#111', hair: '#222' }), viewNow = () => NOW, chatLink = id => 'claude://x/' + id;
"""

    def test_chip_and_empty_thread(self):
        """칩의 ×n은 일하는 중일 때만이에요(회의실에서는 ‘회의 중’ 그대로). 직원 대화가 비었으면 팀장 세션을 거친다고 알려요."""
        code = test_scene.ChatDrawer.thread_js() + "\n" + page_js("SK_VIA", "seatChip") + """
console.log(JSON.stringify([seatChip({ state: '일하는 중', label: '일하는 중', runs: 3 }), seatChip({ state: '회의 중', label: '회의 중', runs: 3 }), seatChip({ state: '일하는 중', label: '일하는 중', runs: 1 }),
  threadHTML([], 't', '기획', true), threadHTML([], 't', '개발자'), threadHTML([], 't')]));
"""
        work, meet, one, sk, seat, meeting = self.node(code)
        self.assertEqual((work, meet, one), ("일하는 중 ×3", "회의 중", "일하는 중"))
        self.assertIn("보낸 말은 총괄이 받아서 팀장 세션에 전하고, 팀장이 이 직원의 일꾼에게 맡겨요. 답은 여기에 올라와요.", sk)
        self.assertIn("보낸 말은 총괄이 받아서 이 세션에 전해요.", seat)       # 세션 자리와 회의는 그대로예요
        self.assertIn("받는 사람에게 전해요.", meeting)
        self.assertIn("sk ? { tid, seat: role, sk: true } : { tid, seat: role }", page_js("memberDrawer"))

    def test_roster_row_opens_the_lead_window(self):
        """명단의 직원 줄: [Claude 창 열기] 대신 팀장 창 링크, ‘직원’ 표시, 대화 열기·이름 바꾸기는 그대로, 세션 만들기는 없어요."""
        code = self.ROW + """
const seatBoxHTML = () => '<i class="seatbox"></i>', nameEditHTML = () => '';
const sk = { role: '기획', staff: 'ag-planner', sessionId: null }, dev = { role: '개발자', sessionId: 'local_dev' }, vac = { role: 'QA', sessionId: null };
const cx = lead => ({ names: [], edit: new Set([sk, vac]), seat: true, lead });
liveFake['기획'] = { s: 'busy', since: NOW - 1000, staff: true, n: 2 };
console.log(JSON.stringify({ sk: seatRowHTML(sk, { state: '일하는 중', task: 'U-1-기획 조사', updated: ago(1) }, 't', true, cx('local_lead'), null),
  noLead: seatRowHTML(sk, null, 't', false, cx(''), null), dev: seatRowHTML(dev, { state: '대기', updated: ago(1) }, 't', false, cx('local_lead'), null),
  vac: seatRowHTML(vac, null, 't', false, cx('local_lead'), null) }));
"""
        r = self.node(code)
        s = r["sk"]
        for part in ('href="claude://x/local_lead"', '팀장 창 열기', '이 직원은 팀장 창에서 일해요.', '>직원</span>', 'data-role="기획"', 'data-nm-edit', '일하는 중 ×2', 'U-1-기획 조사', '새 답'):
            self.assertIn(part, s)
        for gone in ('Claude 창 열기', '빈자리', 'seatbox', '아직 세션이 없어요'):
            self.assertNotIn(gone, s)
        self.assertRegex(s, r'aria-label="[^"]*직원[^"]*대화 열기"')
        self.assertNotIn('<a class="ib"', r["noLead"])            # 팀장이 없으면 열 창이 없어요
        self.assertIn('data-role="기획"', r["noLead"])             # 그래도 대화 서랍은 열려요(까닭은 서랍이 알려요)
        self.assertIn('Claude 창 열기', r["dev"])                  # 세션 줄은 그대로예요
        self.assertNotIn('팀장 창 열기', r["dev"])
        self.assertIn('seatbox', r["vac"])                         # 빈자리는 그대로 세션 만들기예요

    def test_stage_gets_staff_and_runs(self):
        """장면에 넘기는 값: 직원은 사람이고(빈자리 아님), 신호대로 책상·돌아다니기, runs(일꾼 수), 새 답도 있어요."""
        code = self.SEAT + page_js("QUIET_SHORT", "seatView", "meetNow", "stageState") + """
const LEAD = '팀장', leadFirst = ms => [...ms.filter(m => m.role === LEAD), ...ms.filter(m => m.role !== LEAD)], customName = m => m.name || '';
const toneOf = t => t.tone, lookOf = k => ({ key: k }), stageTheme = () => 'light', unread = (file, last) => !!last, mode = 'live', STAGE = { held: false };
const t = { id: 'shop', name: '쇼핑몰', tone: 'a', floor: 2 };
const d = { base: 'teams/shop/', team: { team: '쇼핑몰', members: [{ role: '팀장', sessionId: 'local_b' }, { role: '기획', staff: 'ag-planner', sessionId: null, name: '하나' }, { role: '마케팅', staff: 'ag-marketer' }] },
  status: { '기획': { state: '대기', updated: ago(3) }, '마케팅': { state: '대기', updated: ago(3) } }, lastChat: { '기획': { t: 1 } }, metas: [] };
liveFake['기획'] = { s: 'busy', since: NOW - 5000, staff: true, n: 3 };
console.log(JSON.stringify(stageState(t, d, NOW).members));
"""
        lead, plan, mkt = self.node(code)
        self.assertEqual((plan["name"], plan["state"], plan["runs"], plan["staff"], plan["newReply"], plan["codex"]), ("하나", "일하는 중", 3, True, True, False))
        self.assertEqual((mkt["state"], mkt["runs"], mkt["staff"]), ("대기", 0, True))
        self.assertEqual((lead["staff"], lead["runs"]), (False, 0))

    def test_scene_name_tag_shows_runs(self):
        """이름표: 일꾼이 둘 이상이면 ‘×n’을 붙여요. 하나면 붙이지 않아요. 장면 엔진(goalOf·assign)은 그대로예요."""
        sf = test_scene.SceneFrame
        code = sf.SCENE + scene_code() + sf.STAFF + """
sc.update(st([m('팀장', '대기', { lead: true }), m('기획', '일하는 중', { runs: 3 }), m('마케팅', '일하는 중', { runs: 1 })]));
for (let i = 0; i < 200; i++) sc.step(0.05);
said.length = 0; sc.draw();
console.log(JSON.stringify([...new Set(said)]));
"""
        r = self.node(code)
        self.assertIn("기획 ×3", r)
        self.assertIn("마케팅", r)
        self.assertFalse([x for x in r if "×1" in x])
        self.assertIn("(m.runs > 1 ? ' ×' + Math.min(m.runs, 99) : '')", scene_code())
        self.assertIn("runs, staff }", scene_code())   # 약속(맨 위 설명)에 적었어요

    DRAWER = """
let INFO = {};
state.teams.t.team.members = [{ role: '팀장', sessionId: 'local_aaaaaaaa-0000' }, { role: '기획', staff: 'ag-planner', sessionId: null }, { role: '운영', staff: 'Bad Name' }, { role: '개발자', sessionId: 'local_dev' }];
const shot = role => { html = ''; opened = null; memberDrawer('t', role); return { html, opened }; };
"""

    def drawer(self, body):
        code = test_scene.ChatDrawer.drawer_js().replace("skInfo = () => null", "skInfo = (t, r) => INFO[r] || null") + self.DRAWER + body
        return self.node(code)

    def test_staff_drawer(self):
        """직원 서랍: 머리에 [팀장 창 열기]와 ‘이 직원은 팀장 창에서 일해요’, 대화·사진 작성창은 그대로, 정보 탭은 직원 스킬·경로·도구·모델·명찰 상태예요."""
        r = self.drawer("""
INFO['기획'] = { staff: 'ag-planner', skill_path: '~/p/.office/staff/ag-planner/SKILL.md', memory_path: '~/p/.office/staff/ag-planner/기억.md', tools: ['Read', 'Grep', 'Write'], model: 'sonnet', skills: ['probe-skill'], agent: '바뀜', missing_skills: ['probe-skill'],
  agent_tools: ['Read', 'Grep', 'Write', 'Bash'], agent_model: 'opus', agent_diff: true };
const changed = shot('기획');
const allTools = (INFO['기획'] = Object.assign({}, INFO['기획'], { agent_tools: ['*'] }), shot('기획'));
INFO['기획'] = Object.assign({}, INFO['기획'], { agent_tools: null, agent_model: null, agent_diff: false }); const noAgent = shot('기획');
INFO['기획'] = Object.assign({}, INFO['기획'], { agent: 'ok', missing_skills: [] }); const ok = shot('기획');
INFO['기획'] = Object.assign({}, INFO['기획'], { agent: '없음' }); const none = shot('기획');
delete INFO['기획']; const unknown = shot('기획');
INFO['운영'] = { staff: null, agent: '없음' }; const bad = shot('운영');
const dev = shot('개발자');
state.teams.t.team.members[0].sessionId = null; const noLead = shot('기획');
state.teams.t.team.members[0].sessionId = 'local_aaaaaaaa-0000'; ex = true; INFO['기획'] = { agent: '바뀜' }; const example = shot('기획');
console.log(JSON.stringify({ changed, ok, none, unknown, bad, dev, noLead, example, allTools, noAgent }));
""")
        c = r["changed"]["html"]
        for part in ('팀장 창 열기 ↗', 'href="claude://local_aaaaaaaa-0000"', '<p class="d-sub">이 직원은 팀장 창에서 일해요.</p>', '가짜층 팀 · 직원',
                     '<dt>직원 스킬</dt><dd><code>ag-planner</code>', '<code>~/p/.office/staff/ag-planner/SKILL.md</code>', '<code>~/p/.office/staff/ag-planner/기억.md</code>',
                     '<dt>도구</dt><dd>Read, Grep, Write</dd>', '<dt>모델</dt><dd>sonnet</dd>', 'id="dfAgent"', '>바뀜</span>', 'data-act="sk-rebuild"', 'data-role="기획"', '명찰 다시 만들기',
                     '못 찾은 쓸 스킬: probe-skill', '보낸 말은 총괄이 받아서 팀장 세션에 전하고, 팀장이 이 직원의 일꾼에게 맡겨요.',
                     '<form class="composer"', 'value="chat:기획"', 'id="dfState"', 'id="dfTask"', 'role="tablist"'):
            self.assertIn(part, c)
        for gone in ('Claude 창 열기', '<dt>세션</dt>', '보낸 말은 총괄이 받아서 이 세션에 전해요.'):
            self.assertNotIn(gone, c)
        must = '<p class="d-must">커밋·배포·업로드처럼 위험한 일은 팀장 본인이 팀장 창에서 해요. 팀장이 일꾼에게 하는 말은 승인이 아니에요.</p>'
        self.assertIn(must, c)                                                            # 직원에게는 세션 창이 없어요: 팀장 창에서
        self.assertNotIn('세션 창에서 해요', c)
        self.assertIn('<p class="d-must">커밋·배포·업로드처럼 위험한 일의 마지막 확인은 세션 창에서 해요.</p>', r["dev"]["html"])   # 세션 줄은 그대로
        self.assertIn('<dt id="dfHeadT">명찰의 도구</dt><dd id="dfHead">Read, Grep, Write, Bash · 모델 opus <span class="chip wait">SKILL.md와 달라요</span></dd>', c)   # 일꾼이 실제로 받는 도구
        self.assertIn('명찰이 고쳐져 도구가 이미 넓어졌을 수 있어요', c)
        self.assertIn('<dt id="dfHeadT">명찰의 도구</dt><dd id="dfHead">모든 도구(tools 줄 없음) · 모델 opus', r["allTools"]["html"])
        self.assertNotIn('명찰의 도구</dt>', r["noAgent"]["html"])                        # 명찰이 없거나 못 읽으면 그 줄이 없어요
        self.assertEqual(r["changed"]["opened"]["file"], "t/chat/기획.jsonl")   # 대화 파일은 지금처럼 chat/<역할>.jsonl
        self.assertIn('>맞음</span>', r["ok"]["html"])
        self.assertNotIn('sk-rebuild', r["ok"]["html"])                          # 맞으면 다시 만들 단추가 없어요
        self.assertIn('sk-rebuild', r["none"]["html"])
        self.assertIn('서버에서 아직 받지 못했어요', r["unknown"]["html"])
        self.assertNotIn('sk-rebuild', r["unknown"]["html"])
        b = r["bad"]["html"]                                                      # 이름 꼴이 틀린 직원: 서버도 409라 작성창 대신 까닭
        self.assertIn('이름 꼴이 틀렸어요', b)
        self.assertIn('명찰 이름(team.json의 staff 칸)이 ag-… 꼴이 아니라서 전할 수 없어요', b)
        self.assertNotIn('<form class="composer"', b)
        self.assertNotIn('sk-rebuild', b)                                         # 서버도 다시 못 만들어요(이름 꼴부터 고쳐요)
        n = r["noLead"]["html"]                                                   # 팀장이 없으면 열 창도, 전할 곳도 없어요
        self.assertIn('이 층에 팀장이 없어서 직원에게 전할 수 없어요', n)
        self.assertNotIn('<form class="composer"', n)
        self.assertNotIn('팀장 창 열기', n)
        self.assertIn('Claude 창 열기', r["dev"]["html"])                         # 세션 줄 서랍은 그대로예요
        self.assertNotIn('직원 스킬', r["dev"]["html"])
        e = r["example"]["html"]                                                  # 예시 층: 대화도 다시 만들기도 없어요
        self.assertNotIn('sk-rebuild', e)
        self.assertNotIn('<form', e)

    def test_drawer_rebuild_and_repaint(self):
        """[명찰 다시 만들기]는 /api/staff/rebuild를 부르고, 서랍이 열린 동안 명찰 칸만 다시 그려요. restart면 팀장 창을 다시 켜라고 알려요."""
        code = "const API = true;\n" + page_js("esc", "SK_RESTART", "SK_AGENT", "SKR", "skResult", "skAgentHTML", "skHeadText", "SK_DIFF", "skHeadHTML", "skHeadPaint", "SK_KIND", "skWiden", "skGitText", "skRebuild", "skRepaint") + """
let state = { relay: { staff: { t: { '기획': { staff: 'ag-planner', agent: '바뀜' } } } } }, DF = { tid: 't', role: '기획' }, calls = [], reply = { ok: true, restart: true }, fail = null, widen = null, asked = [], yes = true;
const confirm = q => { asked.push(q); return yes; };
const skInfo = (t, r) => state.relay.staff[t][r], exampleTeam = () => false, SU = { open: false }, renderSetup = () => calls.push('setup'), liveTake = () => {};
const ag = { html: '', contains: () => false }, $ = s => (s === '#dfAgent' ? ag : null), put = (el, h) => { el.html = h; }, document = { activeElement: null };
const post = async (p, b) => { calls.push([p, b]); if (widen && !b.confirm) throw Object.assign(new Error('명찰을 다시 만들면 도구가 늘어요'), { body: widen }); if (fail) throw fail; return reply; };
const getText = async () => JSON.stringify({ ok: true, staff: { t: { '기획': { staff: 'ag-planner', agent: 'ok' } } } });
(async () => {
  const before = skAgentHTML('t', '기획');
  await skRebuild('t', '기획');
  const after = ag.html;
  fail = new Error('직원 스킬을 쓸 수 없어요'); state.relay.staff.t['기획'].agent = '바뀜';
  await skRebuild('t', '기획');
  const bad = ag.html, first = calls.slice();
  fail = null; widen = { ok: false, why: 'widen', add: ['Bash'], wide: ['Bash'], model: ['sonnet', 'opus'], tools: ['Read', 'Bash'] }; calls.length = 0; state.relay.staff.t['기획'].agent = '바뀜';
  yes = false; await skRebuild('t', '기획'); const no = [ag.html, calls.slice()];
  yes = true; calls.length = 0; await skRebuild('t', '기획'); const yesCalls = calls.slice();
  console.log(JSON.stringify({ before, after, bad, calls: first, no, yesCalls, asked }));
})();
"""
        r = self.node(code)
        self.assertIn('명찰 다시 만들기', r["before"])
        self.assertEqual(r["calls"][0], ["api/staff/rebuild", {"team": "t", "role": "기획"}])
        self.assertEqual(r["yesCalls"], [["api/staff/rebuild", {"team": "t", "role": "기획"}],   # 확인하면 confirm과 확인 창에 보인 도구·모델(409의 tools·model)로 다시
                                         ["api/staff/rebuild", {"team": "t", "role": "기획", "confirm": True, "expect": {"tools": ["Read", "Bash"], "model": ["sonnet", "opus"]}}]])
        self.assertEqual(r["no"][1], [["api/staff/rebuild", {"team": "t", "role": "기획"}]])   # 취소하면 다시 보내지 않아요
        self.assertIn("명찰을 다시 만들지 않았어요. 도구나 모델이 바뀌어서 확인 창에서 멈췄어요.", r["no"][0])
        q = r["asked"][0]
        for part in ("‘기획’ 명찰을 다시 만들면", "도구가 늘어요: Bash(셸 명령)\n", "모델이 바뀌어요: sonnet → opus", "직원 스킬(SKILL.md)은 일꾼도 고칠 수 있어요"):
            self.assertIn(part, q)
        self.assertIn('>맞음</span>', r["after"])                              # 서버가 새로 알려 준 대로
        self.assertIn('명찰을 다시 만들었어요. 팀장 창을 한 번 다시 켜야 새 직원이 보여요. 일꾼이 없을 때 해요.', r["after"])
        self.assertIn('직원 스킬을 쓸 수 없어요', r["bad"])
        self.assertIn('class="err"', r["bad"])
        self.assertIn("if (act.dataset.act === 'sk-rebuild')", SRC)            # 서랍의 단추를 누르면 이 길로 와요
        self.assertIn("const ag = $('#dfAgent'); if (ag) { put(ag, skAgentHTML(DF.tid, DF.role)); skHeadPaint(DF.tid, DF.role); }", page_js("drawerPaint"))

    REBUILD = "const API = true;\n" + page_js("esc", "SK_RESTART", "SK_AGENT", "SKR", "skResult", "skAgentHTML", "skHeadText", "SK_DIFF", "skHeadHTML", "skHeadPaint", "SK_KIND", "skWiden", "skGitText", "skRebuild", "skRepaint") + """
let state = { relay: { staff: { t: { '기획': { staff: 'ag-planner', agent: '바뀜' } } } } }, DF = { tid: 't', role: '기획' };
const skInfo = (t, r) => state.relay.staff[t][r], exampleTeam = () => false, SU = { open: false }, renderSetup = () => {}, liveTake = () => {};
const ag = { html: '', contains: () => false }, $ = s => (s === '#dfAgent' ? ag : null), put = (el, h) => { el.html = h; }, document = { activeElement: null };
const getText = async () => JSON.stringify({ ok: true, staff: { t: { '기획': { staff: 'ag-planner', agent: 'ok' } } } });
"""

    def test_rebuild_asks_again_when_skill_widens_meanwhile(self):
        """확인 창에 보인 도구·모델(409의 tools·model)을 expect로 함께 보내요. 그사이 SKILL.md가 또 넓어져 서버가 다시 409(again)면 새 차이로 다시 묻고,
        그 차이를 expect로 보내요. 두 번째 창에서 취소하면 더 보내지 않고, 세 번 넘게 바뀌면 서버의 까닭을 보여요."""
        code = self.REBUILD + """
const calls = [], asked = []; let answers = [], replies = [];
const confirm = q => { asked.push(q); return answers.shift(); };
const post = async (p, b) => { calls.push(b); const r = replies.shift(); if (r && r.why) throw Object.assign(new Error('명찰을 다시 만들면 도구가 늘어요'), { body: r }); return r; };
const w1 = { ok: false, why: 'widen', add: ['Bash'], wide: ['Bash'], model: null, tools: ['Read', 'Bash'], again: false };
const w2 = { ok: false, why: 'widen', add: ['Bash', 'WebFetch'], wide: ['Bash', 'WebFetch'], model: ['sonnet', 'opus'], tools: ['Read', 'Bash', 'WebFetch'], again: true };
(async () => {
  replies = [w1, w2, { ok: true, restart: false }]; answers = [true, true]; await skRebuild('t', '기획'); const twice = [calls.slice(), asked.slice(), ag.html];
  calls.length = 0; asked.length = 0; replies = [w1, w2]; answers = [true, false]; await skRebuild('t', '기획'); const cancel = [calls.length, ag.html];
  calls.length = 0; asked.length = 0; replies = [w1, w2, w2, w2]; answers = [true, true, true]; await skRebuild('t', '기획'); const gaveUp = [calls.length, asked.length, ag.html];
  console.log(JSON.stringify({ twice, cancel, gaveUp }));
})();
"""
        r = self.node(code)
        bodies, asked, html = r["twice"]
        self.assertEqual(bodies, [{"team": "t", "role": "기획"},
                                  {"team": "t", "role": "기획", "confirm": True, "expect": {"tools": ["Read", "Bash"], "model": None}},
                                  {"team": "t", "role": "기획", "confirm": True, "expect": {"tools": ["Read", "Bash", "WebFetch"], "model": ["sonnet", "opus"]}}])
        self.assertNotIn("또 바뀌었어요", asked[0])
        self.assertTrue(asked[1].startswith("확인하는 사이에 직원 스킬(SKILL.md)이 또 바뀌었어요.\n‘기획’ 명찰을 다시 만들면\n"), asked[1])
        for part in ("도구가 늘어요: Bash, WebFetch (셸 명령·인터넷)\n", "모델이 바뀌어요: sonnet → opus"):
            self.assertIn(part, asked[1])                                               # 새로 넓어진 것까지 보고 정해요
        self.assertIn("명찰을 다시 만들었어요.", html)
        self.assertEqual(r["cancel"][0], 2)                                                # 두 번째 창에서 취소하면 그만 보내요
        self.assertIn("명찰을 다시 만들지 않았어요. 도구나 모델이 바뀌어서 확인 창에서 멈췄어요.", r["cancel"][1])
        self.assertEqual(r["gaveUp"][:2], [4, 3])                                          # 세 번까지 묻고
        self.assertIn('class="err"', r["gaveUp"][2])
        self.assertIn("명찰을 다시 만들면 도구가 늘어요", r["gaveUp"][2])

    def test_rebuild_result_goes_when_agent_changes(self):
        """[명찰 다시 만들기] 결과 글은 그 뒤로 명찰 상태가 바뀌면 지워져요(서랍이 열린 채로도, 다시 열어도, 설정 직원 줄에서도 skResult를 봐요).
        만드는 중이거나, 상태가 그대로이거나, 상태를 적지 않은 결과는 남아요."""
        code = self.REBUILD + """
const confirm = () => true, post = async () => ({ ok: true, restart: true });
(async () => {
  await skRebuild('t', '기획');
  const kept = [skAgentHTML('t', '기획'), SKR['t|기획'].agent, ag.html];
  state.relay.staff.t['기획'] = { staff: 'ag-planner', agent: '바뀜' };           // 그 뒤에 누가 명찰을 손으로 고쳤어요
  const gone = [skAgentHTML('t', '기획'), 't|기획' in SKR];
  SKR['t|기획'] = { busy: true, text: '', bad: false }; const busy = skResult('t', '기획').busy;
  SKR['t|기획'] = { busy: false, text: '옛 결과', bad: true }; const noAgent = skResult('t', '기획').text;
  console.log(JSON.stringify({ kept, gone, busy, noAgent }));
})();
"""
        r = self.node(code)
        self.assertIn("명찰을 다시 만들었어요. 팀장 창을 한 번 다시 켜야 새 직원이 보여요", r["kept"][0])
        self.assertEqual(r["kept"][1], "ok")                                               # 결과를 적을 때의 명찰 상태
        self.assertIn(">맞음</span>", r["kept"][2])
        self.assertNotIn("명찰을 다시 만들었어요", r["gone"][0])
        self.assertIn(">바뀜</span>", r["gone"][0])
        self.assertFalse(r["gone"][1])
        self.assertTrue(r["busy"])
        self.assertEqual(r["noAgent"], "옛 결과")
        self.assertIn("r = skResult(f.id, role)", page_js("skRowHTML"))                  # 설정 직원 줄도 같은 결과를 봐요
        self.assertIn("r = skResult(tid, role)", page_js("skAgentHTML"))

    def test_widen_text_follows_the_tools(self):
        """확인 창의 넓힘 글은 실제로 늘어나는 도구로 만들어요(고정 문구 없이): Bash는 셸 명령, WebFetch·WebSearch는 인터넷, Write·Edit는 파일 쓰기,
        Read·Grep·Glob은 파일 읽기, '*'(tools 줄 없음)은 모든 도구예요. 같은 일은 한 번만 적고, 모델이 바뀌면 그 줄도 더해요."""
        code = page_js("SK_KIND", "skWiden") + """
const w = (add, model) => skWiden({ add, model });
console.log(JSON.stringify([w(['WebFetch']), w(['Bash']), w(['Write', 'Edit']), w(['Grep', 'Glob', 'WebSearch', 'WebFetch']), w(['*']), w([], ['sonnet', 'opus']),
  w(['Bash'], ['inherit', 'haiku']), w(['Read', 'Write', 'Bash', 'WebFetch']), w(['constructor']), w(null, null)]));
"""
        self.assertEqual(self.node(code), [
            "도구가 늘어요: WebFetch(인터넷)", "도구가 늘어요: Bash(셸 명령)", "도구가 늘어요: Write, Edit (파일 쓰기)",
            "도구가 늘어요: Grep, Glob, WebSearch, WebFetch (파일 읽기·인터넷)", "도구가 늘어요: *(모든 도구)", "모델이 바뀌어요: sonnet → opus",
            "도구가 늘어요: Bash(셸 명령)\n모델이 바뀌어요: inherit → haiku", "도구가 늘어요: Read, Write, Bash, WebFetch (파일 읽기·파일 쓰기·셸 명령·인터넷)",
            "도구가 늘어요: constructor", ""])                                             # 모르는 이름은 도구 이름만(Object 속성으로 읽지 않아요)
        self.assertNotIn("셸·인터넷을 쓸 수 있게 돼요", SRC)

    def test_git_text_follows_the_server(self):
        """들이기·다시 만들기 결과 글의 info/exclude 부분은 서버 답 git(exclude_agents)대로예요. 명찰 줄과 스킬 링크 줄을 나눠 세고, 넣을 줄 중
        이번에 더하지 않은 줄은 '이미 있어요'예요. 못 쓴 까닭(skipped)이 있으면 그 글이고 더하지 못한 줄은 세지 않아요. 저장소가 아니면 아무것도 적지 않아요."""
        code = page_js("skGitText") + """
const A = '.claude/agents/ag-*.md', S1 = '.claude/skills/x', S2 = 'sub/.claude/skills/y';
const g = (lines, added, more) => skGitText(Object.assign({ repo: true, excluded: added.length > 0, already: !added.length, line: A, lines, added }, more || {}));
console.log(JSON.stringify([
  g([A, S1], [A, S1]), g([A, S1], [S1]), g([A], []), g([A, S1, S2], [S2]), g([A, S1], [], { skipped: 'info/exclude가 링크라 고치지 않았어요' }),
  g([A, S1], [A], { skipped: 'info/exclude를 쓰지 못했어요(EACCES)' }), skGitText({ repo: false, excluded: false, already: false }), skGitText(undefined),
  skGitText({ repo: true, excluded: true, line: A })]));
"""
        w = "팀장 폴더 저장소의 info/exclude에 "
        self.assertEqual(self.node(code), [
            w + "명찰 줄 1개·스킬 링크 줄 1개를 더했어요", w + "스킬 링크 줄 1개를 더했어요(명찰 줄 1개는 이미 있어요)", w + "명찰 줄 1개는 이미 있어요",
            w + "스킬 링크 줄 1개를 더했어요(명찰 줄 1개·스킬 링크 줄 1개는 이미 있어요)", "info/exclude가 링크라 고치지 않았어요",
            w + "명찰 줄 1개를 더했어요 · info/exclude를 쓰지 못했어요(EACCES)", "", "", w + "명찰 줄 1개를 더했어요"])
        self.assertIn("g = skGitText(r.git)", page_js("skHire"))                          # 들이기 결과 글도 같은 글이에요

    def test_rebuild_result_tells_exclude_lines(self):
        """[명찰 다시 만들기] 결과 글에도 서버가 info/exclude에 실제로 더한 줄과 이미 있던 줄을 적어요."""
        code = self.REBUILD + """
const confirm = () => true, post = async () => ({ ok: true, restart: true, git: { repo: true, excluded: true, already: false, line: '.claude/agents/ag-*.md',
  lines: ['.claude/agents/ag-*.md', '.claude/skills/x'], added: ['.claude/skills/x'] } });
(async () => { await skRebuild('t', '기획'); console.log(JSON.stringify(SKR['t|기획'].text)); })();
"""
        self.assertEqual(self.node(code), "명찰을 다시 만들었어요. 팀장 폴더 저장소의 info/exclude에 스킬 링크 줄 1개를 더했어요(명찰 줄 1개는 이미 있어요). "
                                          "팀장 창을 한 번 다시 켜야 새 직원이 보여요. 일꾼이 없을 때 해요.")

    def test_floor_word_in_staff_panel(self):
        """직원 묶음의 이름표('<층 이름> 층 직원 스킬'): 층 이름이 이미 '층'으로 끝나면 '층'을 또 붙이지 않아요. 서버 floor_word와 같아요."""
        code = self.SETUP + """
const out = {};
for (const n of ['일층', '시험층', '알파']) { F.t1.name = n; out[n] = skPanelHTML(F.t1, 3); }
console.log(JSON.stringify({ out, w: ['시험층', '3층', '옛 층', '층', '알파', '층 사무실'].map(floorWord) }));
"""
        r = self.node(code)
        o = server_ns("floor_word")
        self.assertEqual(r["w"], [o["floor_word"](x) for x in ('시험층', '3층', '옛 층', '층', '알파', '층 사무실')])
        self.assertEqual(r["w"], ["시험층", "3층", "옛 층", "층", "알파 층", "층 사무실 층"])
        for name, label in (("일층", "일층"), ("시험층", "시험층"), ("알파", "알파 층")):
            self.assertIn(f'role="group" aria-label="{label} 직원 스킬"', r["out"][name])
            self.assertIn(f'<ul class="su-sklist" aria-label="{label} 직원">', r["out"][name])
            self.assertNotIn("층 층", r["out"][name])

    @unittest.skipUnless(CHROME, "헤드리스 Chrome이 없어요")
    def test_drawer_head_line_follows_the_server(self):
        """서랍이 열린 채 명찰이 생기거나 손으로 고쳐지면 '명찰의 도구' 줄(<dt>·<dd>)을 '명찰' 줄 바로 앞에 만들거나 바꾸고, 명찰을 모르게 되면 빼요.
        그대로면 건드리지 않아요. 서랍을 고치는 drawerPaint와 다시 만들기 뒤의 skRepaint가 이 함수를 불러요."""
        body = '<dl class="facts" id="F"><dt>모델</dt><dd>sonnet</dd><dt>명찰</dt><dd id="dfAgent">명찰 칸</dd><dt>상태</dt><dd id="dfState">대기</dd></dl>'
        script = "const $ = (s, r = document) => r.querySelector(s);\n" + page_js("esc", "skHeadText", "SK_DIFF", "skHeadHTML", "skHeadPaint") + """
let INFO = null; const skInfo = () => INFO, F = document.getElementById('F'), out = {};
const look = () => [...F.children].map(e => e.tagName + ':' + e.textContent);
skHeadPaint('t', '기획'); out.none = look();
INFO = { agent_tools: ['Read', 'Write', 'Edit'], agent_model: 'sonnet', agent_diff: false }; skHeadPaint('t', '기획'); out.made = look();
const dd = document.getElementById('dfHead'); skHeadPaint('t', '기획'); out.same = document.getElementById('dfHead') === dd;
INFO = { agent_tools: ['Read', 'Write', 'Edit', 'Bash'], agent_model: 'sonnet', agent_diff: true }; skHeadPaint('t', '기획'); out.wide = look(); out.chip = !!document.querySelector('#dfHead .chip.wait');
INFO = { agent_tools: null }; skHeadPaint('t', '기획'); out.gone = look();
document.getElementById('out').textContent = JSON.stringify(out);
"""
        r = in_browser(body, script)
        base = ["DT:모델", "DD:sonnet", "DT:명찰", "DD:명찰 칸", "DT:상태", "DD:대기"]
        self.assertEqual(r["none"], base)
        self.assertEqual(r["made"], base[:2] + ["DT:명찰의 도구", "DD:Read, Write, Edit · 모델 sonnet"] + base[2:])
        self.assertTrue(r["same"])
        self.assertEqual(r["wide"], base[:2] + ["DT:명찰의 도구", "DD:Read, Write, Edit, Bash · 모델 sonnet SKILL.md와 달라요"] + base[2:])
        self.assertTrue(r["chip"])
        self.assertEqual(r["gone"], base)
        self.assertIn("skHeadPaint(tid, role);", page_js("skRepaint"))

    def test_read_info_names_staff_records(self):
        """읽는 정보의 [자세히]: 직원 층이 더 읽는 것(일꾼 기록의 종류 이름·끝 표시·고친 시각)과 열지 않는 것(일꾼에게 준 글과 답)을 적어요.
        꼭 보일 줄은 그대로예요(공개 문구 점검이 그 문장을 지켜요)."""
        h = self.node(page_js("readInfoHTML") + "\nconsole.log(JSON.stringify(readInfoHTML()));")
        self.assertIn('<p class="hint" data-must data-say>이 맥의 세션 목록(제목·폴더·마지막 활동)과 실행 상태만 읽어요.</p>', h)
        more = h[h.index("<details"):]
        self.assertIn("직원을 둔 층은 팀장 세션의 일꾼 기록(meta.json)에서 종류 이름·끝 표시·고친 시각만 꺼내요. 일꾼에게 준 글과 답은 열지 않아요.", more)

    def test_meeting_start_lists_staff(self):
        """회의 열기 서랍: 지금 말을 전할 수 있는 직원도 참석자로 골라요(이름 꼴이 틀린 직원은 빼요). 직원 표시와 한 줄 안내가 있어요."""
        code = page_js("esc", "LEAD", "leadFirst", "SID_RE", "STAFF_RE", "skOn", "isSk", "skName", "skRole", "skLead", "meetStartDrawer") + """
let html = '', state = { org: { teams: [{ id: 't' }] }, teams: { t: { team: { team: '가짜층', members: [{ role: '개발자', sessionId: 'local_dev' }, { role: '기획', staff: 'ag-planner', sessionId: null },
  { role: '운영', staff: 'Bad Name' }, { role: 'QA', sessionId: null }, { role: '팀장', sessionId: 'local_aaaaaaaa-0000' }] } } } };
const leadGapHTML = () => '', seatHTML = (t, r) => esc(r), relayBox = () => '', openDrawer = h => { html = h; };
meetStartDrawer('t'); const all = html;
meetStartDrawer('t', { participants: ['팀장', '개발자'] }); const preset = html;
state.teams.t.team.members[4].sessionId = null; meetStartDrawer('t'); const noLead = html;
console.log(JSON.stringify({ all, preset, noLead }));
"""
        r = self.node(code)
        a = r["all"]
        for part in ('value="팀장"', 'value="개발자"', 'value="기획" checked', '기획 <small class="hint">직원</small>', '직원은 팀장 창에서 일해요.'):
            self.assertIn(part, a)
        for gone in ('value="운영"', 'value="QA"'):
            self.assertNotIn(gone, a)
        self.assertLess(a.index('value="팀장"'), a.index('value="개발자"'))   # 팀장 먼저, 그다음 team.json 순서
        self.assertLess(a.index('value="개발자"'), a.index('value="기획"'))
        self.assertIn('value="기획">', r["preset"])                          # 미리 고른 참석자가 있으면 그대로(직원은 고르지 않은 채)
        self.assertNotIn('value="기획"', r["noLead"])                        # 팀장이 없으면 직원에게 전할 수 없어요

    SETUP = page_js("esc", "LEAD", "ROLE_RE", "ROLE_BAN", "roleKey", "roleOk", "glen", "STAFF_RE", "skOn", "isSk", "skName", "skRole", "skRows", "skInfo",
                    "SK_AGENT", "SKR", "skResult", "SK_BASH", "SK_RESTART", "SK_TOOLS", "floorWord", "skState", "skCount", "skDraft", "skPanelHTML", "skHeadText", "SK_DIFF", "skHeadHTML", "skRowHTML",
                    "skFormHTML", "skInput", "skCheck", "skGitText") + "\n" + page_block("roleErr") + """
const SU = { sk: {} }, FORM = { tools: ['Read', 'Grep', 'Glob', 'Write', 'Edit', 'Bash', 'WebFetch', 'WebSearch'], defaultTools: ['Read', 'Grep', 'Glob', 'Write', 'Edit'], models: ['inherit', 'opus', 'sonnet', 'haiku'],
  skills: { floor: ['public-copy-check'], personal: ['public-copy-check', 'my-note'] } };
let state = { teams: { t1: { team: { members: [{ role: '팀장', sessionId: 'local_a' }, { role: '기획', staff: 'ag-planner', sessionId: null }, { role: '마케팅', staff: 'ag-marketer' }, { role: '개발자', sessionId: 'local_b' },
  { role: '운영', staff: 'Bad Name' }] } } },
  relay: { staff: { t1: { '기획': { staff: 'ag-planner', agent: '없음', missing_skills: ['probe'] }, '마케팅': { staff: 'ag-marketer', agent: 'ok', tools: ['Read'], agent_tools: ['Read', 'Bash'], agent_model: 'inherit', agent_diff: true },
    '운영': { staff: null, agent: '없음' } } } } };
const F = { t1: { id: 't1', name: '일층', staffOn: true, staffForm: FORM } }, floorById = id => F[id] || null;
"""

    def test_settings_staff_panel(self):
        """설정 → 층의 [직원 스킬]: 켜기 단추, 켠 층만 [직원 들이기] 폼(기본 도구는 Bash 없이), 직원마다 [퇴근], 바뀌었거나 없는 명찰은 [명찰 다시 만들기], restart면 다시 켜기 안내."""
        code = self.SETUP + """
const on = skPanelHTML(F.t1, 3);
skState('t1').restart = true; skState('t1').text = '‘기획’ 직원(ag-planner)을 들였어요.';
const restart = skPanelHTML(F.t1, 3);
F.t1.staffOn = false; skState('t1').restart = false; skState('t1').text = '';
const off = skPanelHTML(F.t1, 3);
console.log(JSON.stringify({ on, restart, off, count: skCount(F.t1) }));
"""
        r = self.node(code)
        on = r["on"]
        for part in ('role="switch" id="suK3on" data-su-in="sk-on" data-team="t1" checked', '직원 스킬(시험 기능) 켜기', '<legend>직원 들이기</legend>',
                     'id="suK3r" data-su-in="sk" data-k="role"', 'id="suK3n" data-su-in="sk" data-k="staff"', 'placeholder="ag-planner"', 'id="suK3d" data-su-in="sk" data-k="desc"',
                     '<textarea id="suK3w" data-su-in="sk" data-k="work"', '<legend>도구</legend>', 'value="Read" checked', 'value="Edit" checked', 'value="WebSearch">',
                     '<option value="inherit" selected>inherit (팀장과 같게)</option>', '<option value="haiku">haiku</option>',
                     '쓸 스킬 · 이 층 스킬', 'value="public-copy-check"', '쓸 스킬 · 개인 스킬', 'value="my-note"', 'data-su="sk-hire"',
                     'data-su="sk-fire" data-team="t1" data-role="기획"', 'data-su="sk-fire" data-team="t1" data-role="마케팅"', '>퇴근</button>',
                     'data-su="sk-rebuild" data-team="t1" data-role="기획"', '명찰 없음', '명찰 맞음', '못 찾은 쓸 스킬: probe'):
            self.assertIn(part, on)
        self.assertNotIn('value="Bash" checked', on)                                 # 기본 도구는 Bash 없이(결정 11)
        self.assertNotIn('셸 명령은 좁힐 수 없어요', on)
        self.assertEqual(on.count('value="public-copy-check"'), 1)                  # 층 스킬과 개인 스킬에 같은 이름이면 층 스킬(링크)로 한 번만
        self.assertNotIn('data-su="sk-rebuild" data-team="t1" data-role="마케팅"', on)
        self.assertIn('<p class="hint">명찰의 도구: Read, Bash · 모델 inherit <span class="chip wait">SKILL.md와 달라요</span></p>', on)   # 일꾼이 실제로 받는 도구
        self.assertEqual(on.count('명찰의 도구'), 1)                                       # 명찰을 모르는 직원은 그 줄이 없어요
        self.assertNotIn('data-su="sk-rebuild" data-team="t1" data-role="운영"', on)    # 이름 꼴이 틀린 직원은 다시 만들 수 없어요(퇴근은 돼요)
        self.assertIn('data-su="sk-fire" data-team="t1" data-role="운영"', on)
        self.assertIn('명찰 이름 꼴이 틀림', on)
        self.assertIn('팀장 창을 한 번 다시 켜야 새 직원이 보여요. 일꾼이 없을 때 해요.', r["restart"])
        self.assertIn('들였어요', r["restart"])
        off = r["off"]
        self.assertNotIn(' checked aria-describedby', off.split('직원 스킬(시험 기능) 켜기')[0][-200:])
        self.assertNotIn('<legend>직원 들이기</legend>', off)                         # 끄면 들이기만 숨겨요
        self.assertIn('data-su="sk-fire"', off)                                      # 들인 직원과 퇴근은 그대로
        self.assertEqual(r["count"], 3)

    def test_settings_staff_form_input_and_check(self):
        """폼 칸: 영문 이름은 소문자로, Bash를 고르면 경고 한 줄. 보내기 전 검사는 서버와 같은 말이에요(빈 칸, 겹치는 역할, 팀장, 이름 꼴, 도구)."""
        code = self.SETUP + """
const warn = { id: 'suK3b', textContent: '' }, box = { nextElementSibling: warn };
const inp = (k, value) => ({ dataset: { team: 't1', k }, value, selectionStart: 0, selectionEnd: 0, setSelectionRange() {} });
const ck = (kind, value, checked) => ({ dataset: { team: 't1' }, value, checked, closest: () => box });
const n = inp('staff', 'AG-Planner'); skInput(n, 'sk'); skInput(inp('role', '디자이너'), 'sk'); skInput(inp('work', '첫 줄\\n둘째 줄'), 'sk'); skInput(inp('model', 'haiku'), 'sk'); skInput(inp('desc', '화면 시안'), 'sk');
skInput(ck('t', 'Bash', true), 'sk-tool'); const bash = [warn.textContent, skDraft(F.t1).tools.slice()];
skInput(ck('t', 'Bash', false), 'sk-tool'); const nobash = warn.textContent;
skInput(ck('s', 'my-note', true), 'sk-skill');
const d = skDraft(F.t1), base = Object.assign({}, d, { tools: d.tools.slice() }), c = o => skCheck(F.t1, Object.assign({}, base, o));
console.log(JSON.stringify({ shown: n.value, draft: d, bash, nobash,
  checks: [c({ role: '' }), c({ role: '기획' }), c({ role: '팀장' }), c({ role: '개발자' }), c({ role: 'a/b' }), c({ staff: 'planner' }), c({ staff: 'ag-' }), c({ desc: '  ' }), c({ work: ' ' }), c({ tools: [] }), c({})] }));
"""
        r = self.node(code)
        self.assertEqual(r["shown"], "ag-planner")
        self.assertEqual((r["draft"]["staff"], r["draft"]["role"], r["draft"]["work"], r["draft"]["model"], r["draft"]["skills"]), ("ag-planner", "디자이너", "첫 줄\n둘째 줄", "haiku", ["my-note"]))
        self.assertEqual(r["bash"], ["셸 명령은 좁힐 수 없어요. 꼭 필요한 직원에게만 줘요", ["Read", "Grep", "Glob", "Write", "Edit", "Bash"]])
        self.assertEqual(r["nobash"], "")
        keys = [x and x[0] for x in r["checks"]]
        self.assertEqual(keys, ["r", "r", "r", "r", "r", "n", "n", "d", "w", "t0", None])
        self.assertEqual(r["checks"][0][1], "역할 이름을 적어 주세요")
        self.assertIn("같은 이름의 역할이 이미 있어요", r["checks"][1][1])              # 이 층의 직원 역할과도 겹치지 않게
        self.assertIn("팀장은", r["checks"][2][1])
        self.assertIn("ag-로 시작", r["checks"][5][1])

    def test_settings_staff_actions(self):
        """들이기·퇴근·켜기: 서버에 보내는 값과 결과 글. 퇴근은 확인 창을 띄우고 ‘직원 폴더는 남아요’라고 알려요. restart면 다시 켜기 안내를 남겨요."""
        code = self.SETUP + page_js("skHire", "skFire", "skEnable") + """
const calls = [], asked = [], said = [], renders = [];
let replies = {}, yes = true, answers = [];
const post = async (p, b) => { calls.push([p, b]); const r = p === 'api/staff/fire' && !b.anyway && replies[p + '#first'] ? replies[p + '#first'] : replies[p]; if (r instanceof Error) throw r; return r; };
const refreshSetup = async () => { calls.push('refresh'); }, load = async () => { calls.push('load'); }, renderSetup = f => renders.push(f), suSay = t => said.push(t), confirm = q => { asked.push(q); return answers.length ? answers.shift() : yes; };
const CSS = { escape: s => s };
(async () => {
  Object.assign(skDraft(F.t1), { role: '디자이너', staff: 'ag-designer', desc: ' 화면 시안 ', work: '시안 만들기', tools: ['Read', 'Write'], model: 'sonnet', skills: ['my-note'] });
  replies['api/staff/hire'] = { ok: true, team: 't1', role: '디자이너', staff: 'ag-designer', folder: '~/p/.office/staff/ag-designer', agent: '~/lead/.claude/agents/ag-designer.md', restart: true, links: ['~/lead/.claude/skills/x'],
    git: { repo: true, excluded: true, already: false, line: '.claude/agents/ag-*.md', lines: ['.claude/agents/ag-*.md', '.claude/skills/x'], added: ['.claude/agents/ag-*.md', '.claude/skills/x'] } };
  await skHire('t1', 'suK3');
  const hired = Object.assign({}, skState('t1')), hireBody = calls.find(x => Array.isArray(x) && x[0] === 'api/staff/hire')[1];
  Object.assign(skDraft(F.t1), { role: '', staff: 'ag-x', desc: 'a', work: 'b' }); calls.length = 0; await skHire('t1', 'suK3'); const empty = [skState('t1').err, calls.length, renders[renders.length - 1]];
  Object.assign(skDraft(F.t1), { role: '연구' }); replies['api/staff/hire'] = new Error('그 이름의 직원 폴더가 이미 있어요'); await skHire('t1', 'suK3'); const refused = skState('t1').err;
  yes = false; calls.length = 0; await skFire('t1', '기획', 'suK3'); const kept = calls.length;
  yes = true; replies['api/staff/fire'] = { ok: true, retired: '~/p/.office/staff/ag-planner/retired/20261108-101010-agent.md', kept: '~/p/.office/staff/ag-planner', left: null }; await skFire('t1', '기획', 'suK3'); const fired = skState('t1').text;
  const firedBad = skState('t1').bad;
  // 팀장 폴더를 못 찾아요: 서버가 409(why: lead)로 멈추면 한 번 더 묻고, 그래도 빼면 anyway로 다시 보내요
  replies['api/staff/fire'] = { ok: true, retired: null, kept: '~/p/.office/staff/ag-planner', left: '팀장 폴더를 찾지 못해서 명찰(.claude/agents/ag-planner.md)을 옮기지 못했어요. 팀장 폴더에 남아 있으면 팀장이 아직 이 일꾼을 띄울 수 있어요' };
  const leadErr = Object.assign(new Error('팀장 세션의 작업 폴더를 찾지 못해서 명찰을 옮길 수 없어요'), { body: { ok: false, why: 'lead' } });
  calls.length = 0; asked.length = 0; yes = true;
  replies['api/staff/fire#first'] = leadErr;
  await skFire('t1', '기획', 'suK3'); const anyway = [skState('t1').text, skState('t1').bad, calls.filter(x => Array.isArray(x)).map(x => x[1]), asked.slice()];
  calls.length = 0; answers.push(true, false); await skFire('t1', '기획', 'suK3');   // 두 번째 확인에서 취소: anyway로 보내지 않아요
  const firstOnly = [calls.filter(x => Array.isArray(x)).length, skState('t1').text, skState('t1').bad];
  const t = { dataset: { team: 't1' }, checked: true, id: 'suK3on', disabled: false };
  replies['api/staff/enable'] = { ok: true, on: true, changed: true, rules: { ok: true, appended: ['staff'], updated: [], removed: [] }, told: null }; await skEnable(t); const onText = skState('t1').text;
  replies['api/staff/enable'] = { ok: true, on: true, changed: true, rules: { ok: true, appended: ['staff'], updated: [], removed: [] }, told: true }; await skEnable(t); const toldText = skState('t1').text;
  replies['api/staff/enable'] = { ok: true, on: true, changed: true, rules: { ok: true, appended: ['staff'], updated: [], removed: [] }, told: false, tellError: '1분에 보낼 수 있는 양을 넘었어요' }; await skEnable(t); const notTold = [skState('t1').text, skState('t1').bad];
  t.checked = false; replies['api/staff/enable'] = { ok: true, on: false, changed: true, rules: { ok: true, appended: [], updated: [], removed: [] } }; await skEnable(t); const keptText = skState('t1').text;
  t.checked = false; replies['api/staff/enable'] = { ok: true, on: false, changed: true, rules: { ok: true, appended: [], updated: [], removed: ['staff'] } }; await skEnable(t); const offText = skState('t1').text;
  t.checked = false; replies['api/staff/enable'] = { ok: true, on: false, changed: true, rules: { ok: true, appended: ['team-talk', 'handoff', 'staff'], updated: [], removed: [] }, told: true }; await skEnable(t); const offAdded = skState('t1').text;
  t.checked = true; replies['api/staff/enable'] = new Error('예시 층은 직원 스킬을 켤 수 없어요'); await skEnable(t); const failed = [skState('t1').text, skState('t1').bad, t.checked, t.disabled];
  console.log(JSON.stringify({ hired, hireBody, empty, refused, kept, fired, firedBad, anyway, firstOnly, asked, onText, toldText, notTold, keptText, offText, offAdded, failed, said, posts: calls.filter(x => Array.isArray(x)) }));
})();
"""
        r = self.node(code)
        h = r["hired"]
        self.assertTrue(h["restart"])
        self.assertIsNone(h["draft"])                                                     # 들인 뒤 폼은 비워요
        self.assertIn("‘디자이너’ 직원(ag-designer)을 들였어요. 직원 스킬: ~/p/.office/staff/ag-designer/SKILL.md", h["text"])
        self.assertIn("층 스킬 1개를 팀장 폴더에 링크했어요", h["text"])
        self.assertTrue(h["text"].endswith(" · 팀장 폴더 저장소의 info/exclude에 명찰 줄 1개·스킬 링크 줄 1개를 더했어요."), h["text"])
        self.assertIn("팀장 창을 한 번 다시 켜야 새 직원이 보여요. 일꾼이 없을 때 해요.", r["said"][0])
        self.assertEqual(r["empty"], ["역할 이름을 적어 주세요", 0, ["#suK3r", "#suK3e"]])   # 서버에 보내지 않고 그 칸으로
        self.assertEqual(r["refused"], "그 이름의 직원 폴더가 이미 있어요")                    # 서버가 막은 까닭은 폼 안에
        self.assertEqual(r["kept"], 0)                                                    # 확인 창에서 취소하면 보내지 않아요
        self.assertTrue(any("직원 폴더(SKILL.md·기억.md)는 남아요" in q for q in r["asked"]))
        self.assertFalse(r["firedBad"])
        text, bad, bodies, asked = r["anyway"]
        self.assertEqual(bodies, [{"team": "t1", "role": "기획"}, {"team": "t1", "role": "기획", "anyway": True}])   # 한 번 더 물은 뒤 anyway로
        self.assertIn("팀장 세션의 작업 폴더를 찾지 못해서 명찰을 옮길 수 없어요\n\n그래도 팀원 목록에서만 뺄까요?", asked[1])
        self.assertTrue(bad)
        self.assertIn("팀장이 아직 이 일꾼을 띄울 수 있어요", text)
        self.assertEqual(r["firstOnly"], [1, "‘기획’ 직원을 퇴근시키지 않았어요. 팀장 창을 한 번 연 뒤 다시 해 주세요.", True])
        self.assertIn("‘기획’ 직원을 퇴근시켰어요. 직원 폴더는 남아요(~/p/.office/staff/ag-planner).", r["fired"])
        self.assertIn("retired/20261108-101010-agent.md로 옮겼어요", r["fired"])
        self.assertEqual(r["onText"], "직원 스킬을 켰어요. RULES.md에 ‘직원 일꾼’ 부분을 넣었어요.")
        self.assertEqual(r["toldText"], "직원 스킬을 켰어요. RULES.md에 ‘직원 일꾼’ 부분을 넣었어요. 켜져 있는 팀장에게 RULES.md를 다시 읽으라는 사이트 알림을 보냈어요.")
        self.assertEqual(r["notTold"], ["직원 스킬을 켰어요. RULES.md에 ‘직원 일꾼’ 부분을 넣었어요. 팀장에게 RULES.md를 다시 읽으라는 사이트 알림을 보내지 못했어요(1분에 보낼 수 있는 양을 넘었어요). 팀장 창에서 RULES.md를 다시 읽게 해 주세요.", True])
        self.assertEqual(r["keptText"], "직원 스킬을 껐어요. 들인 직원과 명찰은 그대로예요. 들인 직원이 남아 있어서 RULES.md의 ‘직원 일꾼’ 부분은 그대로 둬요(일꾼이 지킬 규칙이에요).")
        self.assertEqual(r["offText"], "직원 스킬을 껐어요. 들인 직원과 명찰은 그대로예요. RULES.md에서 ‘직원 일꾼’ 부분을 뺐어요(예전 글은 RULES.md.bak).")
        self.assertEqual(r["offAdded"], "직원 스킬을 껐어요. 들인 직원과 명찰은 그대로예요. 들인 직원이 남아 있어서 RULES.md에 ‘직원 일꾼’ 부분을 넣었어요(일꾼이 지킬 규칙이에요). "
                                        "켜져 있는 팀장에게 RULES.md를 다시 읽으라는 사이트 알림을 보냈어요.")   # 끌 때 그 부분이 없던 층: ‘켰어요’라고 하지 않아요
        self.assertEqual(r["failed"], ["예시 층은 직원 스킬을 켤 수 없어요", True, False, False])   # 실패하면 단추를 되돌려요
        self.assertEqual(r["hireBody"], {"team": "t1", "role": "디자이너", "staff": "ag-designer", "desc": "화면 시안", "work": "시안 만들기", "tools": ["Read", "Write"], "model": "sonnet", "skills": ["my-note"]})
        self.assertIn(["api/staff/fire", {"team": "t1", "role": "기획"}], r["posts"])
        self.assertIn(["api/staff/enable", {"team": "t1", "on": False}], r["posts"])

    def test_floor_editor_keeps_staff_seats(self):
        """팀원 고치기: 직원 자리는 불러오지 않고, 그 역할 이름으로 세션 자리를 만들지 않아요. 직원 줄도 한 층 자리를 차지해요."""
        self.assertIn("e.staff = ms.map(skRole).filter(Boolean);", SRC)
        chk = page_js("checkRows")
        self.assertIn("sk.has(roleKey(r.role))", chk)
        self.assertIn("e.rows.length > seatMax(e)", chk)
        code = "let MAX_MEMBERS = 12;\n" + page_js("seatMax") + """
console.log(JSON.stringify([seatMax({}), seatMax({ staff: ['기획', '마케팅'] })]));
"""
        self.assertEqual(self.node(code), [12, 10])
        self.assertIn("seatMax(x.e)", page_js("addRow"))
        self.assertIn("직원 자리(", page_js("editHTML"))

    def test_have_row_has_staff_button(self):
        """층 줄에 [직원 스킬] 단추(예시 층이 아닐 때)와 직원 수. 누르면 묶음을 펼쳐요."""
        have = page_js("haveHTML")
        for part in ('data-su="sk-open"', "'직원 스킬'", "skPanelHTML(f, j)", "직원 ${skn}명"):
            self.assertIn(part, have)
        for act in ("a === 'sk-open'", "a === 'sk-hire'", "a === 'sk-fire'", "a === 'sk-rebuild'", "kind === 'sk-on'", "kind === 'sk' || kind === 'sk-tool' || kind === 'sk-skill'"):
            self.assertIn(act, SRC)
        self.assertIn("e.target.tagName === 'TEXTAREA'", SRC)   # 하는 일(여러 줄)도 쓰는 대로 남겨요

    @unittest.skipUnless(CHROME, "헤드리스 Chrome이 없어요")
    def test_staff_panel_fits_a_phone(self):
        """직원 스킬 묶음과 들이기 폼이 폰 폭(375)에서도 가로로 넘치지 않고, 하는 일 칸이 여러 줄이에요."""
        html = self.node(self.SETUP + "\nconsole.log(JSON.stringify(skPanelHTML(F.t1, 3)));")
        body = f'<div class="setup" style="position:static"><section class="su-card"><ul class="su-floors"><li class="su-have">{html}</li></ul></section></div>'
        script = ("const w = document.getElementById('suK3w').getBoundingClientRect(), all = [...document.querySelectorAll('.su-staff *')].map(e => e.getBoundingClientRect().right);"
                  "document.getElementById('out').textContent = JSON.stringify({ over: document.documentElement.scrollWidth - innerWidth, right: Math.max(...all) - innerWidth, h: w.height, w: w.width });")
        for width in (375, 1280):
            r = in_browser(body, script, width)
            self.assertLessEqual(r["over"], 0, width)
            self.assertLessEqual(r["right"], 1, width)
            self.assertGreaterEqual(r["h"], 60, width)
            self.assertGreater(r["w"], 200, width)

    @unittest.skipUnless(CHROME, "헤드리스 Chrome이 없어요")
    def test_staff_rows_drop_the_floor_box(self):
        """설정의 직원 줄은 층 줄(.su-floors li)의 점선 상자 꼴을 물려받지 않아요: 윗줄만 있고 좌우·아래 점선, 배경, 둥근 모서리, 좌우 여백이 없어요."""
        html = self.node(self.SETUP + "\nconsole.log(JSON.stringify(skPanelHTML(F.t1, 3)));")
        body = f'<div class="setup" style="position:static"><section class="su-card"><ul class="su-floors"><li class="su-have">{html}</li></ul></section></div>'
        script = ("const li = document.querySelector('.su-sklist li'), cs = getComputedStyle(li), have = getComputedStyle(document.querySelector('.su-floors > li'));"
                  "document.getElementById('out').textContent = JSON.stringify({ l: cs.borderLeftStyle, r: cs.borderRightStyle, b: cs.borderBottomStyle, t: cs.borderTopStyle,"
                  " pl: cs.paddingLeft, pr: cs.paddingRight, bg: cs.backgroundColor, rad: cs.borderTopLeftRadius, haveL: have.borderLeftStyle });")
        for width in (375, 1280):
            r = in_browser(body, script, width)
            self.assertEqual((r["l"], r["r"], r["b"], r["t"]), ("none", "none", "none", "solid"), width)
            self.assertEqual((r["pl"], r["pr"], r["bg"], r["rad"]), ("0px", "0px", "rgba(0, 0, 0, 0)", "0px"), width)
            self.assertEqual(r["haveL"], "dashed", width)                                 # 층 줄은 그대로예요

    def test_old_floor_page_is_the_same(self):
        """직원 줄이 없는 옛 층: 명단 줄·서랍 머리·참석자·빈자리는 지금과 같은 길이에요(직원 표시가 섞이지 않아요)."""
        code = self.ROW + """
const seatBoxHTML = () => '<i class="seatbox"></i>', nameEditHTML = () => '';
const dev = { role: '개발자', sessionId: 'local_dev' }, vac = { role: 'QA', sessionId: null }, cx = { names: [], edit: new Set([dev, vac]), seat: true, lead: 'local_lead' };
console.log(JSON.stringify([seatRowHTML(dev, { state: '대기', updated: ago(1) }, 't', false, cx, null), seatRowHTML(vac, null, 't', false, cx, null), seatView('t', dev, { state: '대기', updated: ago(1) }, null, NOW)]));
"""
        dev, vac, view = self.node(code)
        self.assertIn('href="claude://x/local_dev" aria-label="개발자 Claude 창 열기" title="Claude 창 열기"', dev)
        for gone in ('직원', '팀장 창', '×'):
            self.assertNotIn(gone, dev)
        self.assertIn('seatbox', vac)
        self.assertEqual((view["kind"], view["runs"]), ("member", 0))
        rows = [{"role": "팀장", "sessionId": LEAD_SID}, {"role": "개발자", "sessionId": DEV_SID}, {"role": "QA", "sessionId": None}, {"role": "UI/UX", "sessionId": None}]
        code = "const isCx = () => false;\n" + self.ROWJS + f"""
const R = {json.dumps(rows, ensure_ascii=False)};
console.log(JSON.stringify({{ shown: shownRows(R).map(x => [x.i, x.role]), hidden: hiddenRows(R), fill: fillEmpty(R).map(m => m.role) }}));
"""
        r = self.node(code)
        o = server_ns("LEAD", "ROLE_RE", "NOT_ROLES", "STAFF_RE", "SHOWN_MAX", "is_role", "is_staff_row", "staff_of", "staff_role", "staff_keys", "shown_rows")
        self.assertEqual(r["shown"], [[i, x] for i, x in o["shown_rows"](rows)])
        self.assertEqual(r, {"shown": [[0, "팀장"], [1, "개발자"], [2, "QA"]], "hidden": ["UI/UX"], "fill": ["QA"]})


if __name__ == "__main__":
    unittest.main()
