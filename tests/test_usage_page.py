"""에이전시티 U-39 시험(페이지): 층 머리글의 ‘남은 양 5시간 72% · 이번 주 65%’.

python3 -m unittest discover -s tests -p test_usage_page.py      (저장소 맨 위에서)

사용량 알림에서 한도를 정한 기간만, 이 맥 전체 숫자로 보여요. 문턱(80%·100%)은 머리말 칩(usgPick)과 같아요.
test_scene.py처럼 화면 코드(office.src.html)의 함수를 그대로 꺼내 node에서 가짜 state로 돌려요. node가 없으면 건너뛰어요.
줄바꿈·색(CSS)은 헤드리스 브라우저가 있을 때만 재요. 포트를 열지 않아요.
문서(GUIDE·README)가 코드와 맞는지도 글로 봐요(node 없이).
파이썬 표준 라이브러리만 써요. 진짜 세션·파일은 건드리지 않아요.
"""
import json
import os
import re
import shutil
import subprocess
import unittest

from test_scene import CHROME, ROOT, SRC, in_browser, page_js

MAN = 10_000   # 만
TITLE = "이 맥 전체예요(층 밖 폴더까지, Claude·Codex·Gemini 합계). 사용량 알림에서 정한 한도 기준이에요"
USG = page_js("esc", "USG_WIN", "korNum", "usgRelay", "usgLevel", "usgPick", "usgLeftHTML", "usgFloorHTML")
ALL = {"h5": 1000 * MAN, "day": 1000 * MAN, "week": 1000 * MAN}
NONE = {"h5": None, "day": None, "week": None}


def parts(html):
    """그린 ‘남은 양’을 기간마다 {cls, tip, name, pct}로 나눠요."""
    return [{"cls": c.strip(), "tip": t, "name": n, "pct": p}
            for c, t, n, p in re.findall(r'<span class="usg-w([^"]*)" title="([^"]*)">([^<]*) <b>([^<]*)</b>', html)]


@unittest.skipUnless(shutil.which("node"), "node가 없어요(화면 코드 시험은 node로 돌려요)")
class UsageLeft(unittest.TestCase):
    def node(self, code):
        r = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def draw(self, cases, tid="a"):
        """cases: {이름: usage(None이면 사용량 알림 꺼짐)} → {이름: {left, floor}}. '_snap'으로 시작하면 API 없이(스냅샷)."""
        code = "let API = true, state = null;\n" + USG + f"""
const cases = {json.dumps(cases, ensure_ascii=False)}, out = {{}};
for (const [k, u] of Object.entries(cases)) {{
  API = !k.startsWith('_snap');
  state = u === null ? {{ relay: {{}} }} : {{ relay: {{ usage: u }} }};
  out[k] = {{ left: usgLeftHTML(), floor: usgFloorHTML({json.dumps(tid)}) }};
}}
console.log(JSON.stringify(out));
"""
        return self.node(code)

    def test_off_or_no_limit_is_empty(self):
        """사용량 알림이 꺼졌거나, 한도를 하나도 정하지 않았거나, 스냅샷(API 없음)이면 아무것도 그리지 않아요."""
        win = {"h5": 100 * MAN, "day": 200 * MAN, "week": 300 * MAN}
        r = self.draw({"off": None, "blank": {}, "nolim": {"limits": NONE, "win": win}, "zero": {"limits": {"h5": 0, "day": 0, "week": 0}, "win": win},
                       "_snap": {"limits": ALL, "win": win}})
        for k, v in r.items():
            self.assertEqual(v, {"left": "", "floor": ""}, k)

    def test_only_periods_with_a_limit_in_order(self):
        """5시간·이번 주만 한도를 정하면 그 둘만, 5시간 → 이번 주 차례로 남은 비율을 보여요. 하루는 빠져요."""
        lim = {"h5": 1500 * MAN, "day": None, "week": 10000 * MAN}
        r = self.draw({"two": {"limits": lim, "win": {"h5": 420 * MAN, "day": 5000 * MAN, "week": 3500 * MAN}},
                       "all": {"limits": ALL, "win": {"week": 100 * MAN, "day": 300 * MAN, "h5": 0}}})
        left = r["two"]["left"]
        self.assertTrue(left.startswith(f'<span class="usg-left" title="{TITLE}">남은 양'), left)
        self.assertIn('<span class="su-sr">(이 맥 전체, 사용량 알림에서 정한 한도 기준)</span>', left)   # title은 화면 읽기가 안 읽을 수 있어요
        self.assertEqual(parts(left), [
            {"cls": "", "tip": "최근 5시간: 쓴 양 420만 / 한도 1,500만 · 남은 양 1,080만", "name": "5시간", "pct": "72%"},
            {"cls": "", "tip": "이번 주: 쓴 양 3,500만 / 한도 1억 · 남은 양 6,500만", "name": "이번 주", "pct": "65%"}])
        self.assertIn("</span> · <span", left)
        self.assertNotIn("오늘", left)
        self.assertEqual([p["name"] for p in parts(r["all"]["left"])], ["5시간", "오늘", "이번 주"])   # 서버가 주는 차례와 상관없이
        self.assertEqual([p["pct"] for p in parts(r["all"]["left"])], ["100%", "70%", "90%"])

    def test_missing_null_or_text_windows_are_left_out(self):
        """서버가 뺀(자정이 지난 등) 기간, null, 글, 음수, 객체는 빼요. Number(null)이 0이 되어 100%로 보이면 안 돼요. 모두 빠지면 ''."""
        r = self.draw({
            "none": {"limits": ALL, "win": {"h5": None, "day": "300", "week": {"work": 5}}},
            "gone": {"limits": ALL, "win": {}},
            "nowin": {"limits": ALL},
            "oddwin": {"limits": ALL, "win": "12"},
            "oddlim": {"limits": "1000", "win": {"h5": 1}},
            "some": {"limits": ALL, "win": {"h5": None, "day": 200 * MAN, "week": "x"}},
            "neg": {"limits": ALL, "win": {"h5": -5, "day": True, "week": [3]}},
        })
        for k in ("none", "gone", "nowin", "oddwin", "oddlim", "neg"):
            self.assertEqual(r[k]["left"], "", k)
        self.assertEqual([(p["name"], p["pct"]) for p in parts(r["some"]["left"])], [("오늘", "80%")])

    def test_over_warn_and_under_one_percent(self):
        """넘으면 ‘넘음’(글로도)과 over, 딱 한도면 0%와 over, 80% 이상 쓰면 warn, 남은 게 1% 아래면 ‘<1%’(esc를 거쳐요)."""
        lim = {"h5": 1000 * MAN, "day": None, "week": None}
        cases = {"over": 1200 * MAN, "full": 1000 * MAN, "warn": 900 * MAN, "edge": 800 * MAN, "calm": 799 * MAN, "tiny": 995 * MAN, "last": 1000 * MAN - 1, "zero": 0}
        r = self.draw({k: {"limits": lim, "win": {"h5": v}} for k, v in cases.items()})
        p = {k: parts(v["left"])[0] for k, v in r.items()}
        self.assertEqual((p["over"]["pct"], p["over"]["cls"]), ("넘음", "over"))
        self.assertIn("넘은 양 200만", p["over"]["tip"])
        self.assertIn("<b>넘음</b>", r["over"]["left"])
        self.assertNotIn("0%", re.sub(r'title="[^"]*"', "", r["over"]["left"]))
        self.assertEqual((p["full"]["pct"], p["full"]["cls"]), ("0%", "over"))
        self.assertIn("· 남은 양 0", p["full"]["tip"])
        self.assertEqual((p["warn"]["pct"], p["warn"]["cls"]), ("10%", "warn"))
        self.assertEqual((p["edge"]["pct"], p["edge"]["cls"]), ("20%", "warn"))
        self.assertEqual((p["calm"]["pct"], p["calm"]["cls"]), ("20%", ""))   # 20.1% 남음: 80%가 안 됐어요
        self.assertEqual((p["zero"]["pct"], p["zero"]["cls"]), ("100%", ""))
        for k in ("tiny", "last"):
            self.assertEqual((p[k]["pct"], p[k]["cls"]), ("&lt;1%", "warn"), k)
            self.assertIn("<b>&lt;1%</b>", r[k]["left"])
            self.assertNotIn("<b><1%", r[k]["left"])
        for k in ("warn", "tiny", "calm"):
            self.assertNotIn("한도 넘음", r[k]["left"], k)

    def test_odd_limits_never_show_nan_or_infinity(self):
        """한도가 Infinity·‘1e999’·아주 큰 수(망가진 중계)면 그 기간을 빼요(NaN%·Infinity%가 아니에요).
        안전한 정수 한도는 그대로 보여요. 나누는 차례 때문에 29%가 28%로 보이지 않아요."""
        big = 9_007_199_254_740_991   # Number.MAX_SAFE_INTEGER
        code = "let API = true, state = null;\n" + USG + f"""
const cases = {{ inf: Infinity, text: '1e999', huge: 1e307, above: {big} + 2, top: {big}, max: 1e15 }}, out = {{}};
for (const [k, lim] of Object.entries(cases)) {{
  state = {{ relay: {{ usage: {{ limits: {{ h5: lim, day: 100, week: 1000 }}, win: {{ h5: 5, day: 71, week: 710 }} }} }} }};
  out[k] = usgLeftHTML();
}}
console.log(JSON.stringify(out));
"""
        r = self.node(code)
        for k, html in r.items():
            self.assertNotIn("NaN", html, k)
            self.assertNotIn("Infinity", html, k)
            names = [(p["name"], p["pct"]) for p in parts(html)]
            self.assertEqual(names[-2:], [("오늘", "29%"), ("이번 주", "29%")], k)   # 71/100 쓰면 29% 남아요(28%가 아니에요)
            self.assertEqual(names[0][0] == "5시간", k in ("top", "max"), k)
        self.assertEqual(parts(r["max"])[0]["pct"], "99%")

    def test_threshold_matches_the_header_chip(self):
        """같은 숫자에서 층 머리글의 warn·over가 머리말 칩(usgPick)의 단계와 같아요."""
        pairs = [(lim, used) for lim in (1000 * MAN, 3, 7, 1500 * MAN) for used in (0, lim * 0.5, lim * 0.79999, lim * 0.8, lim * 0.95, lim * 0.99999, lim, lim * 1.2)]
        code = "const API = true; let state = null;\n" + USG + f"""
const pairs = {json.dumps(pairs)}, out = [];
for (const w of ['h5', 'day', 'week'])
  for (const [lim, used] of pairs) {{
    const u = {{ limits: {{ h5: null, day: null, week: null, [w]: lim }}, win: {{ h5: 1, day: 1, week: 1, [w]: used }} }};
    state = {{ relay: {{ usage: u }} }};
    const c = usgPick(u, '2026-11-12', {{}}), m = usgLeftHTML().match(/class="usg-w ?([a-z]*)"/);
    out.push([w, lim, used, c ? c.level : '', m ? m[1] : null]);
  }}
console.log(JSON.stringify(out));
"""
        rows = self.node(code)
        self.assertEqual(len(rows), 3 * len(pairs))
        for w, lim, used, chip, left in rows:
            self.assertEqual(left, chip, (w, lim, used))
        self.assertEqual({r[3] for r in rows}, {"", "warn", "over"})

    def test_floor_header_appends_left_after_today(self):
        """usgFloorHTML은 층 ‘오늘 n’ 다음에 남은 양을 붙여요. 오늘 쓴 게 없는 층에도 남은 양은 같아요(이 맥 전체)."""
        u = {"limits": {"h5": 1500 * MAN, "day": None, "week": None}, "win": {"h5": 420 * MAN}, "floors": {"a": 1234 * MAN}}
        r = self.draw({"on": u, "nolim": dict(u, limits=NONE)})
        # 화면 읽기가 ‘오늘 1,234만 남은 양’으로 이어 읽지 않게 층 숫자에 ‘이 층에서 쓴 양’을 숨겨 붙여요
        today = '<span title="오늘 이 층 폴더에서 쓴 작업량(캐시 읽기 ×0.1)">오늘<span class="su-sr"> 이 층에서 쓴 양</span> <b>1,234만</b></span>'
        self.assertEqual(r["on"]["floor"], today + r["on"]["left"])
        self.assertTrue(r["on"]["left"].startswith('<span class="usg-left"'))
        self.assertEqual(r["nolim"]["floor"], today)
        other = self.draw({"on": u}, tid="b")["on"]
        self.assertEqual(other["floor"], r["on"]["left"])
        # 두 그리는 자리(roomHTML·countsPaint)가 모두 usgFloorHTML을 불러서 남은 양도 그대로 따라와요
        self.assertEqual(SRC.count("usgFloorHTML(t.id)"), 2)
        self.assertIn("put(box, countsHTML(views) + usgFloorHTML(t.id));", SRC)
        self.assertIn('<div class="counts">${counts}${usgFloorHTML(t.id)}</div>', SRC)

    def test_tag_like_text_never_lands_raw(self):
        """서버 칸에 태그 모양 글이 와도 날것으로 그려지지 않아요(숫자는 Number()로만 써서 글은 빠져요). 층 id가 bad든 'a'든 같아요."""
        bad = "<img src=x onerror=alert(1)>"
        u = {"limits": {"h5": bad, "day": 1000 * MAN, "week": "<b>"}, "win": {"h5": "<script>", "day": 100 * MAN, "week": bad},
             "floors": {"a": bad, bad: 5}, "error": "<svg onload=1>", "at": "<i>"}
        for tid in (bad, "a"):
            r = self.draw({"x": u}, tid=tid)
            for v in r.values():
                for html in v.values():
                    self.assertEqual(set(re.findall(r"</?([a-zA-Z]+)", html)) - {"span", "b"}, set(), html)
                    self.assertNotIn("onerror", html)
            self.assertEqual([(p["name"], p["pct"]) for p in parts(r["x"]["left"])], [("오늘", "90%")])
        self.assertEqual(r["x"]["floor"], r["x"]["left"])   # 층 ‘a’는 floors 값이 글이라 ‘오늘 n’이 빠져요

    def test_labels_and_tips_go_through_esc(self):
        """이름·마우스 글(title)도 esc()를 거쳐요. 기간 이름을 태그 모양으로 바꿔 넣어도 &lt;로만 나와요."""
        code = "let API = true, state = null;\n" + USG + f"""
for (const row of USG_WIN) {{ row[1] = '<i>' + row[1] + '"'; row[3] = '<u>' + row[3]; }}
state = {{ relay: {{ usage: {{ limits: {{ h5: 100, day: 100, week: 100 }}, win: {{ h5: 10, day: 90, week: 120 }} }} }} }};
console.log(JSON.stringify({{ html: usgLeftHTML() }}));
"""
        html = self.node(code)["html"]
        self.assertEqual(set(re.findall(r"</?([a-zA-Z]+)", html)) - {"span", "b"}, set(), html)
        self.assertEqual(html.count('title="&lt;i&gt;'), 3, html)    # 기간마다 title
        self.assertEqual(html.count('&quot;: 쓴 양'), 3, html)        # title의 따옴표도 닫히지 않아요
        self.assertEqual(html.count('">&lt;u&gt;'), 3, html)         # 기간 이름

    def test_settings_hint_mentions_the_header(self):
        """설정 ‘사용량 알림’의 한도 설명에 층 머리글 남은 양 이야기가 있어요."""
        code = "const API = true, ago = () => '';\n" + page_js("esc", "USG_WIN", "korNum", "usgLimText", "usgLine", "usgSetHTML") + """
const USG = { st: { enabled: true, counting: false, at: '', error: '', limits: { h5: 15000000, day: null, week: null }, win: { h5: 1, day: 2, week: 3 } }, gone: false, draft: null, err: '' };
console.log(JSON.stringify({ html: usgSetHTML() }));
"""
        html = self.node(code)["html"]
        hint = re.search(r'<p class="hint" id="suUsgL">(.*?)</p>', html).group(1)
        self.assertIn("80%·100%가 되면 위에 알려요.", hint)
        self.assertIn("한도를 정한 기간은 층 머리글에 남은 양이 늘 보여요.", hint)

    @unittest.skipUnless(CHROME, "헤드리스 브라우저가 없어요")
    def test_header_wraps_as_one_piece_and_reads_in_both_themes(self):
        """넓으면 한 줄, 폰 폭(320px)에서도 가로로 넘치지 않고 기간 한 덩이는 끊기지 않아요. warn·over 글자는 밝은·어두운 테마 모두 4.5:1 이상이에요."""
        left = self.draw({"x": {"limits": ALL, "win": {"h5": 1200 * MAN, "day": 900 * MAN, "week": 100 * MAN}, "floors": {"a": 1234 * MAN}}})["x"]["floor"]
        body = ('<div class="scene-card"><header class="sc-head"><span class="fl">3층</span><h2>예시 층</h2>'
                f'<div class="counts"><span><i class="dot d-work"></i>일하는 중 <b>2</b></span><span><i class="dot d-idle"></i>대기 <b>3</b></span>{left}</div>'
                '<span class="sp"></span><button type="button" class="btn">움직임 멈추기</button></header></div>')
        script = """
const rgb = s => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const x = lum(rgb(a)), y = lum(rgb(b)); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const probe = v => { const p = document.createElement('i'); p.style.color = 'var(' + v + ')'; document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; };
const col = q => getComputedStyle(document.querySelector(q)).color;
const Q = { warn: '.usg-w.warn b', over: '.usg-w.over b', plain: '.usg-w:not(.warn):not(.over) b' };
const look = () => { const bg = getComputedStyle(document.querySelector('.sc-head')).backgroundColor;
  return { warn: col(Q.warn) === probe('--hot'), over: col(Q.over) === probe('--err-ink'), plain: col(Q.plain) === probe('--ink'), min: Math.min(...Object.values(Q).map(q => ratio(col(q), bg))) }; };
const ws = [...document.querySelectorAll('.usg-w')].map(e => e.getBoundingClientRect()), L = document.querySelector('.usg-left');
const line = parseFloat(getComputedStyle(L).fontSize) * 2, sr = [...L.querySelectorAll('.su-sr')].map(e => e.getBoundingClientRect().width);
const size = { over: document.documentElement.scrollWidth - innerWidth, right: L.getBoundingClientRect().right <= innerWidth + 0.5, whole: ws.every(r => r.height < line), oneLine: ws.every(r => Math.abs(r.top - ws[0].top) < 2), sr: Math.max(...sr) };
const ls = getComputedStyle(L), today = [...document.querySelectorAll('.counts > span:not(.usg-left)')].pop().getBoundingClientRect();
const lr = L.getBoundingClientRect(), edge = { w: ls.borderLeftWidth, line: ls.borderLeftColor === probe('--line-2'), pad: parseFloat(ls.paddingLeft) >= 8, apart: today.right < lr.left || lr.top >= today.bottom - 1 };   // 같은 줄이면 옆에 떨어져, 좁으면 다음 줄에
// 기간 한 덩이보다 좁은 칸(40px)에 넣어도 기간 안에서는 끊지 않고 기간 사이에서만 끊어요(nowrap이 하는 일)
document.querySelector('.counts').style.width = '40px';
const sq = [...document.querySelectorAll('.usg-w')].map(e => e.getBoundingClientRect());
const squeeze = { whole: sq.every(r => r.height < line), rows: new Set(sq.map(r => Math.round(r.top))).size };
document.querySelector('.counts').style.width = '';
const light = look(); document.documentElement.dataset.theme = 'dark'; const dark = look();
document.getElementById('out').textContent = JSON.stringify({ size, edge, squeeze, light, dark });
"""
        wide, phone = in_browser(body, script), in_browser(body, script, 320)
        self.assertEqual(wide["size"], {"over": 0, "right": True, "whole": True, "oneLine": True, "sr": 1})
        self.assertEqual(phone["size"]["over"], 0)
        self.assertTrue(phone["size"]["right"])
        self.assertTrue(phone["size"]["whole"])   # ‘이번 주 90%’가 두 줄로 쪼개지지 않아요
        for m in (wide, phone):
            # 층 ‘오늘 1,234만’과 ‘남은 양’ 사이에 가는 선이 있어 ‘오늘 1,234만 남은 양’으로 이어 읽히지 않아요
            self.assertEqual(m["edge"], {"w": "1px", "line": True, "pad": True, "apart": True}, m is phone)
            self.assertEqual(m["squeeze"], {"whole": True, "rows": 3})
        for theme in ("light", "dark"):
            for m in (wide, phone):
                self.assertEqual({k: m[theme][k] for k in ("warn", "over", "plain")}, {"warn": True, "over": True, "plain": True}, theme)
                self.assertGreaterEqual(m[theme]["min"], 4.5, theme)


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class UsageDocs(unittest.TestCase):
    """GUIDE·README·CSS 주석의 ‘남은 양’ 설명이 코드와 맞아요(node 없이 글로 봐요)."""

    def guide(self):
        g = read("docs", "GUIDE.md")
        return g[g.index("#### 사용량 알림"):g.index("\n---", g.index("#### 사용량 알림"))]

    def test_css_comment_says_80_or_more(self):
        """usgLevel은 r >= 0.8이라 딱 80%도 warn이에요. 주석도 ‘80% 이상’이에요."""
        self.assertIn("const usgLevel = r => (r >= 1 ? 'over' : r >= 0.8 ? 'warn' : '');", SRC)
        css = SRC[SRC.index("/* 층 머리글의 ‘남은 양’"):SRC.index(".counts .usg-left .over b")]
        self.assertIn("80% 이상 쓰면 --hot", css)
        self.assertNotIn("80% 넘게", css)

    def test_whole_mac_wording(self):
        """남은 양은 층과 상관없이 이 맥의 모든 기록(층 밖 폴더 포함)이라 ‘모든 층 합계’라고 쓰지 않아요."""
        g = self.guide()
        for text in (g, SRC):
            self.assertNotIn("모든 층·", text)
        self.assertIn("층 밖 폴더에서 쓴 양도 들어가요", g)
        self.assertIn(f'title="{TITLE}"', SRC)
        self.assertIn("이 맥 전체(층 밖 폴더까지, 세 도구 합계)라 어느 층에서나 같아요", SRC)

    def test_guide_differences_from_the_app_plan(self):
        """Claude 앱 플랜 사용량과 다른 점: 대화창·다른 기기는 빠지고, 모델 무게가 없고, 초기화 때가 달라요. 같은 말은 한 번만."""
        g = self.guide()
        self.assertIn("Claude 앱 대화창이나 다른 기기에서 쓴 양은 빠지고", g)
        self.assertIn("모델과 상관없이 같은 무게로 세요", g)
        self.assertNotIn("앱은 플랜마다", g)
        self.assertIn("앱은 앱의 사용량 화면에 나온 시각에 초기화돼요", g)
        self.assertIn("지금부터 거꾸로 센 5시간이라 오래된 것부터 조금씩 빠지고", g)
        self.assertIn("하루 한도는 ‘오늘’로 보여요", g)
        self.assertIn("['day', '오늘', '하루', '오늘']", SRC)   # 설정 칸은 ‘하루’, 머리글은 ‘오늘’
        for once in ("세 도구", "캐시 읽기", "10분의 1"):
            self.assertEqual(g.count(once), 1, once)

    def test_guide_says_when_it_is_missing(self):
        """처음 세기 전에는 없고, 5시간은 USAGE_OLD(2 × 10분 + 5분 = 25분)보다 오래되면 빠져요."""
        server = read("office_server.py")
        self.assertIn('USAGE_EVERY = int_in(os.environ.get("AGENCITY_USAGE_EVERY"), 600,', server)
        self.assertIn("USAGE_OLD = 2 * USAGE_EVERY + 300", server)
        g = self.guide()
        self.assertIn("처음 세기가 끝나기 전에는 남은 양이 보이지 않아요", g)
        self.assertIn(f"{(2 * 600 + 300) // 60}분 넘게 못 셌으면(잠자기 뒤 등) 5시간은 다시 셀 때까지 빠져요", g)

    def test_readme_keeps_the_safety_sentence_together(self):
        """README ‘안전하게’에서 ‘아무것도 보내지 않고, 끄면 읽지 않아요’가 먼저, 남은 양은 끝에 기준(정한 한도)과 함께예요."""
        line = next(x for x in read("README.md").splitlines() if x.startswith("- 사용량 알림(기본 꺼짐)"))
        self.assertTrue(line.endswith("이 맥 안에서 세요. 아무것도 보내지 않고, 끄면 읽지 않아요. 한도를 정하면 그 한도에서 남은 양(%)이 층 머리글에 보여요."), line)


if __name__ == "__main__":
    unittest.main()
