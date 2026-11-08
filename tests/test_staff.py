"""에이전시티 U-31 시험(S1 서버): 직원 줄(스킬이 곧 직원)을 알아보고, 세션을 앉히지 않고, 직원에게 가는 말은 팀장 세션이 받아요.
(S3 서버): 팀장 세션의 일꾼 기록으로 직원 신호와 status를 만들고, 직원 들이기·퇴근·명찰 다시 만들기·켜기와 '직원 일꾼' 규칙 블록을 봐요.

python3 -m unittest discover -s tests -p test_staff.py      (저장소 맨 위에서)

저장소를 /private/tmp/agencity-u31-… 임시 폴더에 복사해 그 폴더를 설치 폴더로 써요. HOME도 임시 폴더라 진짜 층과 세션은 건드리지 않아요.
가짜 pid 폴더(AGENCITY_CLAUDE_RUN_DIR)와 가짜 기록 폴더(AGENCITY_CLAUDE_PROJECTS_DIR)만 써요.
서버를 켜는 시험은 9700번대 포트를 써요. 직원 줄이 없는 옛 층의 결과가 그대로인지도 봐요.
"""
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_city import TMP_BASE, copy_repo, free_port   # noqa: E402

LEAD, DEV, LEAD3, DEV3 = ("local_aaaaaaaa-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3, 4))
STRAY = "local_aaaaaaaa-0000-4000-8000-000000000009"   # 직원 줄에 잘못 적힌 세션 id(옛 서버가 써 넣은 것처럼)
NEW = "local_dddddddd-0000-4000-8000-000000000001"
BOSS = "local_cccccccc-0000-4000-8000-000000000001"
CX = "cccccccc-0000-4000-8000-000000000001"
MEET = "20261107-M-1"
CLI = "11111111-2222-4333-8444-555555555555"   # 팀장 pid 파일의 sessionId(CLI 세션 id)
SECRET_DESC = "비밀작업설명표시"                  # 일꾼 meta.json의 description·기록 글: 답과 파일에 나오면 안 돼요
NO_SEAT = "직원 자리는 세션을 앉히지 않아요"
NO_LEAD = "이 층에 팀장이 없어서 직원에게 전할 수 없어요"


def staff_floor():
    """직원 줄이 섞인 층: 세션 줄, 빈자리, 직원 줄(이름 꼴이 맞는 것·틀린 것·sessionId가 잘못 적힌 것)."""
    return [{"role": "팀장", "sessionId": LEAD},
            {"role": "개발자", "sessionId": DEV},
            {"role": "기획", "staff": "ag-planner", "sessionId": None, "name": "기획 직원"},
            {"role": "QA", "sessionId": None},
            {"role": "마케팅", "staff": "ag-marketer"},
            {"role": "운영", "staff": "Bad Name", "sessionId": None},
            {"role": "데이터", "staff": "ag-data", "sessionId": STRAY}]


FLOORS = {"t1": ("층", staff_floor),
          "t2": ("팀장 없는 층", lambda: [{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner", "sessionId": None}]),
          "t3": ("옛 층", lambda: [{"role": "팀장", "sessionId": LEAD3}, {"role": "개발자", "sessionId": DEV3}, {"role": "QA", "sessionId": None}])}


def make_install(tmp):
    d = copy_repo(os.path.join(tmp, "app"))
    home, conf, run = (os.path.join(tmp, x) for x in ("home", "conf", "run"))
    for x in (home, conf, run, os.path.join(home, ".claude", "projects")):
        os.makedirs(x, exist_ok=True)
    env = {"HOME": home, "AGENCITY_CONFIG_DIR": conf, "AGENCITY_CLAUDE_RUN_DIR": run, "AGENCITY_UPDATE_INTERVAL": "999999999",
           "AGENCITY_CLAUDE_PROJECTS_DIR": os.path.join(home, ".claude", "projects"),
           "AGENCITY_CLAUDE_SESSIONS_DIR": os.path.join(home, "sessions"),
           "AGENCITY_UPDATE_BASE": "http://127.0.0.1:9", "AGENCITY_UPDATE_RAW": "http://127.0.0.1:9",
           "AGENCITY_GITHUB_API": "http://127.0.0.1:9", "AGENCITY_GITHUB_BASE": "http://127.0.0.1:9"}
    return d, env


def reset_floors(d):
    """층 파일을 처음 모양으로(시험마다). 팀 사무실은 진짜 설치처럼 설치 폴더 밖(<임시>/proj/<층>/.office)에 두고 teams/<층>으로 이어요."""
    os.makedirs(os.path.join(d, "teams"), exist_ok=True)
    for tid, (name, rows) in FLOORS.items():
        base = os.path.join(os.path.dirname(d), "proj", tid, ".office")
        shutil.rmtree(os.path.dirname(base), ignore_errors=True)
        for sub in ("status", "chat", "meetings", "approvals"):
            os.makedirs(os.path.join(base, sub))
        link = os.path.join(d, "teams", tid)
        if os.path.islink(link):
            os.remove(link)
        os.symlink(base, link)
        with open(os.path.join(base, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": name, "members": rows()}, f, ensure_ascii=False, indent=2)
        with open(os.path.join(base, "RULES.md"), "w", encoding="utf-8") as f:
            f.write("# 규칙\n")
    with open(os.path.join(d, "org.json"), "w", encoding="utf-8") as f:
        json.dump({"boss": {"name": "총괄", "sessionId": BOSS},
                   "teams": [{"id": tid, "name": name, "office": f"teams/{tid}", "floor": i} for i, (tid, (name, _)) in enumerate(FLOORS.items(), 1)]},
                  f, ensure_ascii=False)
    with open(os.path.join(d, "setup.json"), "w", encoding="utf-8") as f:
        json.dump({"done": True}, f)
    shutil.rmtree(os.path.join(d, "outbox"), ignore_errors=True)


class Base(unittest.TestCase):
    """설치 폴더 하나를 만들고 office_server를 그 폴더에서 읽어요(서버는 켜지 않아요)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix="agencity-u31-", dir=TMP_BASE))
        cls.dir, cls.env = make_install(cls.tmp)
        reset_floors(cls.dir)
        with mock.patch.dict(os.environ, cls.env):
            spec = importlib.util.spec_from_file_location("agencity_u31_server", os.path.join(cls.dir, "office_server.py"))
            cls.o = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.o)
            spec = importlib.util.spec_from_file_location("agencity_u31_new_team", os.path.join(cls.dir, "bin", "new_team.py"))
            cls.nt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.nt)
        cls.o.MAX_PER_MIN = cls.o.MAX_PENDING = 10 ** 6
        cls.o.seat_kick = lambda: None   # 뒤쪽 살피기 일은 켜지 않아요

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        reset_floors(self.dir)

    def office(self, tid):
        return os.path.realpath(os.path.join(self.dir, "teams", tid))

    def team_bytes(self, tid):
        with open(os.path.join(self.office(tid), "team.json"), "rb") as f:
            return f.read()

    def team(self, tid):
        return json.loads(self.team_bytes(tid).decode("utf-8"))

    def items(self):
        box = os.path.join(self.dir, "outbox")
        out = []
        for n in sorted(os.listdir(box)) if os.path.isdir(box) else []:
            if n.endswith(".json"):
                with open(os.path.join(box, n), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out

    def refused(self, code, fn, *a):
        with self.assertRaises(self.o.ApiError) as e:
            fn(*a)
        self.assertEqual(e.exception.code, code, e.exception.msg)
        return e.exception

    def meeting(self, tid="t1", parts=("팀장", "개발자", "기획", "마케팅")):
        with open(os.path.join(self.office(tid), "meetings", MEET + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": MEET, "status": "진행 중", "mode": "참석", "topic": "주제", "participants": list(parts)}, f, ensure_ascii=False)


class Rows(Base):
    def test_staff_of_and_is_staff_row(self):
        o = self.o
        for v, want in (("ag-planner", "ag-planner"), ("ag-x", "ag-x"), ("ag-" + "a" * 24, "ag-" + "a" * 24), ("ag-0a-b", "ag-0a-b"),
                        ("ag-", None), ("ag--x", None), ("ag-Planner", None), ("ag-x\n", None), ("ag-" + "a" * 25, None),
                        ("planner", None), (" ag-x", None), ("ag-가", None), (7, None), (None, None), (["ag-x"], None)):
            self.assertEqual(o.staff_of({"role": "기획", "staff": v}), want, v)
        self.assertIsNone(o.staff_of("ag-x"))
        for v, want in (("ag-x", True), ("Bad Name", True), ("  x ", True), (["x"], True), ({"a": 1}, True), (1, True), (True, True),
                        ("", False), ("   ", False), (None, False), (False, False), ([], False), ({}, False)):
            self.assertIs(o.is_staff_row({"role": "기획", "staff": v}), want, v)
        self.assertFalse(o.is_staff_row({"role": "기획"}))
        self.assertFalse(o.is_staff_row(["staff"]))
        self.assertFalse(o.seat_empty({"role": "기획", "staff": "ag-planner", "sessionId": None}))
        self.assertFalse(o.seat_empty({"role": "기획", "staff": "이름이 틀려도"}))       # 이름이 틀려도 빈자리가 아니에요
        self.assertTrue(o.seat_empty({"role": "기획", "sessionId": None}))
        self.assertIsNone(o.codex_of({"role": "기획", "staff": "ag-planner", "codexId": CX}))   # 직원 줄은 Codex 자리도 아니에요

    def test_shown_rows_leave_staff_rows(self):
        raw = staff_floor() + [{"role": "기획", "sessionId": None}, {"role": "팀장", "staff": "ag-lead"}]   # 직원과 같은 역할의 줄, 팀장 직원 줄
        self.assertEqual([r for _, r in self.o.shown_rows(raw)], ["팀장", "개발자", "QA"])
        self.assertEqual([r for _, r in self.nt.shown_rows(raw)], ["팀장", "개발자", "QA"])   # new_team.py와 같은 기준
        self.assertEqual(self.o.staff_keys(raw), {"기획", "마케팅", "운영", "데이터"})            # 팀장은 직원 자리가 될 수 없어요

    def test_team_info_has_staff_with_via(self):
        _, _, ms = self.o.team_info("t1")
        self.assertEqual(list(ms), ["팀장", "개발자", "기획", "마케팅", "운영", "데이터"])
        p = ms["기획"]
        self.assertEqual((p["_staff"], p["_via"], p["sessionId"]), ("ag-planner", LEAD, None))
        self.assertEqual(self.o.deliver_sid(p), LEAD)
        self.assertEqual(ms["운영"]["_staff"], None)                     # 이름 꼴이 틀린 직원
        self.assertEqual(ms["데이터"]["sessionId"], None)                # 줄에 적힌 세션 id는 쓰지 않아요
        self.assertEqual(self.o.deliver_sid(ms["데이터"]), LEAD)
        self.assertEqual(self.o.deliver_sid(ms["개발자"]), DEV)
        self.assertNotIn("_staff", ms["개발자"])
        self.assertNotIn("_via", ms["팀장"])
        _, _, ms2 = self.o.team_info("t2")
        self.assertEqual(list(ms2), ["기획"])
        self.assertIsNone(ms2["기획"]["_via"])
        self.assertIsNone(self.o.deliver_sid(ms2["기획"]))

    def test_enqueue_refuses_non_session(self):
        for to in (None, "", "ag-planner", "local_", 7):
            self.refused(409, self.o.enqueue, to, "라벨", "글", "thread")
        self.assertEqual(self.items(), [])

    def test_old_floor_team_info_is_unchanged(self):
        _, _, ms = self.o.team_info("t3")
        rows = FLOORS["t3"][1]()
        self.assertEqual(ms, {"팀장": dict(rows[0], _custom=""), "개발자": dict(rows[1], _custom="")})   # 옛 모양 그대로(_staff·_via 없음)

    def test_floor_members_run_seats_skip_staff(self):
        self.assertNotIn(STRAY, self.o.floor_members())
        self.assertEqual(self.o.run_seats({"office": "teams/t1"}), {"팀장": LEAD, "개발자": DEV})
        self.assertNotIn(STRAY, self.nt.seated_sessions({"teams": [{"id": "t1", "name": "층", "office": "teams/t1"}]}))


class Seats(Base):
    def test_seat_link_refused(self):
        before = self.team_bytes("t1")
        for role in ("기획", "마케팅", "운영", "데이터", " 기획 "):
            e = self.refused(409, self.o.seat_url, "t1", role, "AGC-00000000")
            self.assertEqual(e.msg, NO_SEAT)
            e = self.refused(409, self.o.api_seat_link, {"team": "t1", "role": role})
            self.assertEqual(e.msg, NO_SEAT)
        with open(os.path.join(self.dir, "setup.json"), encoding="utf-8") as f:
            self.assertNotIn("pendingSeats", json.load(f))              # 기다리는 자리를 만들지 않아요
        self.assertEqual(self.team_bytes("t1"), before)
        self.assertEqual(self.o.seat_url("t1", "QA", "AGC-00000000")[3], "QA")   # 진짜 빈자리는 그대로 돼요

    def test_seat_write_never_writes_into_staff_row(self):
        # 옛 서버의 함정: 직원 줄을 빈자리로 보고 sessionId를 써 넣었어요
        before = self.team_bytes("t1")
        for role in ("기획", "운영", "데이터"):
            with self.o.TEAM_LOCK:
                e = self.refused(409, self.o.seat_write, "t1", role, NEW)
            self.assertEqual((e.msg, e.extra.get("why")), (NO_SEAT, "seat"))
        self.assertEqual(self.team_bytes("t1"), before)
        with self.o.TEAM_LOCK:
            self.o.seat_write("t1", "QA", NEW)
        rows = self.team("t1")["members"]
        self.assertEqual(rows[3]["sessionId"], NEW)
        self.assertEqual([r for i, r in enumerate(rows) if i != 3], [r for i, r in enumerate(staff_floor()) if i != 3])

    def test_fill_seats_skip_staff(self):
        self.assertEqual(self.o.fill_seats({"t1", "t2", "t3"}), [("t1", "QA"), ("t2", "팀장"), ("t3", "QA")])
        self.assertEqual(self.o.seat_now("t1", "기획"), "staff")
        self.assertEqual(self.o.seat_now("t1", "QA"), "empty")
        r = self.o.api_seat_fill({"teams": ["t2"]})
        self.assertEqual([it["role"] for it in r["fill"]["items"]], ["팀장"])
        self.assertEqual(self.team("t2")["members"][1], {"role": "기획", "staff": "ag-planner", "sessionId": None})

    def test_pending_seat_on_staff_role_fails(self):
        # 기다리던 자리가 그사이 직원 자리가 됐어요: 앉히지 않고 failed로 끝내요
        p = {"team": "t1", "role": "기획", "marker": "AGC-0000000a", "state": "waiting", "folder": "x"}
        self.assertEqual(self.o.seat_check_live([p]), {"AGC-0000000a": ("failed", f"‘기획’ 자리: {NO_SEAT}")})

    def test_fill_queue_skips_staff_role(self):
        t = self.o.now()
        with open(os.path.join(self.dir, "setup.json"), "w", encoding="utf-8") as f:
            json.dump({"done": True, "fillQueue": {"id": "f-0000000a", "state": "run", "started": t, "items": [
                {"team": "t1", "role": "기획", "state": "todo"}, {"team": "t1", "role": "QA", "state": "todo"}]}}, f, ensure_ascii=False)
        r = self.o.fill_step("page", "f-0000000a")
        self.assertEqual(r["role"], "QA")                                  # 직원 자리는 건너뛰고 다음 빈자리를 열어요
        with open(os.path.join(self.dir, "setup.json"), encoding="utf-8") as f:
            q = json.load(f)["fillQueue"]
        self.assertEqual([(it["role"], it["state"]) for it in q["items"]], [("기획", "skipped"), ("QA", "open")])


class Talk(Base):
    def test_chat_to_staff_goes_to_lead(self):
        self.assertEqual(self.o.api_say({"team": "t1", "thread": "chat:기획", "text": "기획서 봐 줘"}), {"ok": True})
        [it] = self.items()
        chat = os.path.join(self.office("t1"), "chat", "기획.jsonl")
        self.assertEqual((it["to"], it["thread"]), (LEAD, chat))
        self.assertTrue(it["text"].startswith("[대표·사이트] 층 기획에게 (직원 ag-planner) 바로 말 걸기\n기획서 봐 줘"), it["text"][:80])
        self.assertIn("Agent(subagent_type: ag-planner)", it["text"])
        self.assertIn("SendMessage로 이어 쓰고", it["text"])
        self.assertIn(".out/기획.txt", it["text"])
        self.assertIn(f" {shlex.quote(chat)} 기획 --file ", it["text"])   # 답은 그 직원 이름으로
        self.assertTrue(it["text"].endswith(self.o.NOTE))
        with open(chat, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.readline())["text"], "기획서 봐 줘")

    def test_staff_without_lead_or_bad_name_is_409(self):
        for tid, role, want in (("t2", "기획", NO_LEAD), ("t1", "운영", "‘운영’ 직원의 명찰 이름")):
            e = self.refused(409, self.o.api_say, {"team": tid, "thread": "chat:" + role, "text": "안녕"})
            self.assertTrue(e.msg.startswith(want), e.msg)
            self.refused(409, self.o.say_target, tid, "chat:" + role)
            self.assertFalse(os.path.exists(os.path.join(self.office(tid), "chat", role + ".jsonl")))   # 파일을 쓰기 전에 막아요
        self.assertEqual(self.items(), [])

    def test_meeting_bundles_staff_to_lead(self):
        self.meeting()
        self.o.api_say({"team": "t1", "thread": "meeting:" + MEET, "text": "모두 의견"})
        items = self.items()
        self.assertEqual(sorted(it["to"] for it in items), sorted([LEAD, DEV]))   # 팀장과 직원은 한 통, 세션 자리는 한 통씩
        lead = next(it for it in items if it["to"] == LEAD)
        self.assertIn("받는 사람: 팀장, 개발자, 기획, 마케팅", lead["text"])
        self.assertIn("팀장은 늘 답하고 진행을 이끌어요.", lead["text"])
        self.assertIn("직원 참석자: 기획(ag-planner), 마케팅(ag-marketer)", lead["text"])
        self.assertIn("3문장 안으로, 회의 파일에 그 역할 이름으로 답해요", lead["text"])
        dev = next(it for it in items if it["to"] == DEV)
        self.assertNotIn("직원", dev["text"])

    def test_meeting_to_staff_only(self):
        self.meeting()
        self.o.api_say({"team": "t1", "thread": "meeting:" + MEET, "text": "기획만", "to": ["기획"]})
        [it] = self.items()
        self.assertEqual((it["to"], it["label"]), (LEAD, "층 회의 · 팀장"))
        self.assertIn("이 말은 직원 참석자에게 온 거예요", it["text"])
        self.assertIn("직원 참석자: 기획(ag-planner)\n", it["text"])
        self.o.api_say({"team": "t1", "thread": "meeting:" + MEET, "text": "개발만", "to": ["개발자"]})
        [it] = [x for x in self.items() if "개발만" in x["text"]]
        self.assertEqual(it["to"], DEV)
        self.assertNotIn("직원 참석자", it["text"])

    def test_meeting_staff_without_lead_is_409(self):
        self.meeting()
        rows = staff_floor()
        rows[0]["sessionId"] = None                                        # 회의 중에 팀장 자리가 비었어요
        with open(os.path.join(self.office("t1"), "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "층", "members": rows}, f, ensure_ascii=False)
        e = self.refused(409, self.o.api_say, {"team": "t1", "thread": "meeting:" + MEET, "text": "기획만", "to": ["기획"]})
        self.assertEqual(e.msg, NO_LEAD)
        self.assertEqual(self.items(), [])

    def test_meeting_start_takes_staff(self):
        r = self.o.api_meeting_start({"team": "t1", "topic": "주제", "mode": "위임", "participants": ["팀장", "기획", "개발자"]})
        with open(os.path.join(self.office("t1"), "meetings", r["id"] + ".json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["participants"], ["팀장", "개발자", "기획"])
        [it] = self.items()
        self.assertEqual(it["to"], LEAD)
        self.assertIn("직원 참석자: 기획(ag-planner)", it["text"])
        self.assertIn(os.path.join(self.office("t1"), "meetings", r["id"]) + os.sep + "<역할>.md", it["text"])   # 위임: 의견 파일로
        e = self.refused(409, self.o.api_meeting_start, {"team": "t1", "topic": "다음", "mode": "참석", "participants": ["팀장", "운영"]})
        self.assertIn("명찰 이름", e.msg)

    def test_meeting_start_default_includes_staff(self):
        r = self.o.api_meeting_start({"team": "t1", "topic": "주제", "mode": "참석"})
        with open(os.path.join(self.office("t1"), "meetings", r["id"] + ".json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["participants"], ["팀장", "개발자", "기획", "마케팅", "데이터"])   # 이름 꼴이 틀린 직원(운영)은 빼요
        [it] = self.items()
        self.assertIn("대표 말 중 직원에게 온 것은 팀장에게 한 통으로 묶어 와요", it["text"])

    def test_meeting_default_recipients_skip_unreachable_staff(self):
        self.meeting(parts=("팀장", "개발자", "기획", "운영"))
        self.o.api_say({"team": "t1", "thread": "meeting:" + MEET, "text": "모두"})   # 받는 사람을 안 정하면 전할 수 없는 직원만 빼요
        lead = next(it for it in self.items() if it["to"] == LEAD)
        self.assertIn("받는 사람: 팀장, 개발자, 기획\n", lead["text"])
        e = self.refused(409, self.o.api_say, {"team": "t1", "thread": "meeting:" + MEET, "text": "운영만", "to": ["운영"]})
        self.assertIn("명찰 이름", e.msg)

    def test_old_floor_meeting_and_chat_texts(self):
        self.meeting("t3", ("팀장", "개발자"))
        self.o.api_say({"team": "t3", "thread": "meeting:" + MEET, "text": "옛 회의"})
        self.o.api_say({"team": "t3", "thread": "chat:개발자", "text": "옛 대화"})
        items = self.items()
        self.assertEqual(sorted(it["to"] for it in items), sorted([LEAD3, DEV3, DEV3]))
        for it in items:
            self.assertNotIn("직원", it["text"])
        chat = next(it for it in items if "옛 대화" in it["text"])
        self.assertTrue(chat["text"].startswith("[대표·사이트] 옛 층 개발자에게 바로 말 걸기\n옛 대화"))

    def test_meeting_result_note_only_with_staff(self):
        """회의 시작·끝·넛지 글의 '참석자에게 [회의 결과]'에, 직원 참석자가 있을 때만 '직원은 세션이 아니라서 보내지 않아요' 한 줄을 더해요.
        직원 참석자가 없는 회의(옛 층, 직원 층이어도 세션만 부른 회의)는 글이 한 글자도 그대로예요."""
        o = self.o
        note = "\n직원 참석자(기획)는 세션이 아니라서 [회의 결과]를 보내지 않아요(직원 status는 서버가 써요)."

        def plain_end(tid):
            base = self.office(tid)
            chat = os.path.join(base, "meetings", MEET + ".chat.jsonl")
            return (f"[대표·사이트] 회의 {MEET}를 대표가 끝냈어요. 팀 규칙의 회의 끝 순서로: 회의록 {os.path.join(base, 'meetings', MEET + '.md')} → "
                    f"회의 정보 status '끝' → 참석자에게 [회의 결과](status 되돌리기) → 대표가 정할 게 있으면 결재.\n"
                    f"회의 파일: {chat}\n마지막으로 회의 파일에 결론 한 줄을 남겨요.{o.reply_hint(chat, '팀장')}\n\n{o.NOTE}")

        def plain_nudge(tid):
            base = self.office(tid)
            chat = os.path.join(base, "meetings", MEET + ".chat.jsonl")
            return (f"[사이트 알림] 위임 회의 {MEET}가 30분 넘게 조용해요. 사이트가 저절로 보내는 알림이에요(대표가 쓴 말은 아니에요).\n"
                    f"남은 안건이 있으면 마무리하고, 팀 규칙의 회의 끝 순서대로 닫아요: 회의록 {os.path.join(base, 'meetings', MEET + '.md')} → "
                    f"회의 정보 status '끝' → 참석자에게 [회의 결과](status 되돌리기) → 대표가 정할 게 있으면 결재.\n"
                    f"회의 파일: {chat}{o.reply_hint(chat, '팀장')}")

        def sent(tid, fn, *a):
            shutil.rmtree(os.path.join(self.dir, "outbox"), ignore_errors=True)       # 한 통씩 봐요(같은 ms의 id 차례에 기대지 않게)
            r = fn(*a)
            [it] = self.items()
            self.assertEqual(it["to"], LEAD3 if tid == "t3" else LEAD)
            return r, it["text"]

        for tid, parts, add in (("t3", ("팀장", "개발자"), ""), ("t1", ("팀장", "개발자"), ""), ("t1", ("팀장", "개발자", "기획"), note)):
            self.meeting(tid, parts)
            _, text = sent(tid, o.api_meeting_end, {"team": tid, "id": MEET})
            self.assertEqual(text, plain_end(tid).replace("결재.\n", "결재." + add + "\n", 1), (tid, parts))
            self.meeting(tid, parts)
            meta = os.path.join(self.office(tid), "meetings", MEET + ".json")
            with open(meta, encoding="utf-8") as f:
                m = json.load(f)
            m["mode"] = "위임"
            with open(meta, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False)
            got, text = sent(tid, o.meeting_nudge_floor, {"id": tid}, time.time() + o.MEET_IDLE + 60)
            self.assertEqual(got, [MEET])
            self.assertEqual(text, plain_nudge(tid).replace("결재.\n", "결재." + add + "\n", 1), (tid, parts))
            os.remove(meta)                                                               # 진행 중인 회의를 치워요(새 회의를 막아요)
        r, text = sent("t3", o.api_meeting_start, {"team": "t3", "topic": "옛 주제", "mode": "참석", "participants": ["팀장", "개발자"]})   # 시작 글도 같아요
        chat = os.path.join(self.office("t3"), "meetings", r["id"] + ".chat.jsonl")
        self.assertIn("→ 대표가 정할 게 있으면 결재." + o.reply_hint(chat, "팀장") + "\n\n" + o.NOTE, text)
        self.assertNotIn("직원", text)
        r, text = sent("t1", o.api_meeting_start, {"team": "t1", "topic": "주제", "mode": "참석", "participants": ["팀장", "개발자", "기획"]})
        chat = os.path.join(self.office("t1"), "meetings", r["id"] + ".chat.jsonl")
        self.assertIn("→ 대표가 정할 게 있으면 결재." + note + o.reply_hint(chat, "팀장"), text)
        self.assertEqual(o.staff_result_note({"기획": {"_staff": "ag-planner"}}, None), "")   # 참석자 목록이 이상하면 더하지 않아요

    def test_decide_and_meeting_close_reach_lead(self):
        with open(os.path.join(self.office("t1"), "approvals", "20261107-U-31-1.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "결재", "status": "결재 대기"}, f, ensure_ascii=False)
        self.assertTrue(self.o.api_decide({"team": "t1", "id": "20261107-U-31-1", "choice": "승인"})["delivered"])
        self.meeting()
        self.o.api_meeting_end({"team": "t1", "id": MEET})
        self.o.api_meeting_close({"team": "t1", "id": MEET})
        self.assertEqual([it["to"] for it in self.items()], [LEAD] * 3)

    def test_sidebar_and_away_skip_staff(self):
        self.o.api_floor_sidebar({"team": "t1"})
        [it] = self.items()
        self.assertEqual(it["to"], BOSS)
        self.assertIn("옮길 세션(2개)", it["text"])
        self.assertNotIn(STRAY, it["text"])
        where = {STRAY: {"sessionId": STRAY, "cwd": "/private/tmp", "title": "다른 곳"}}
        rows = [{"role": "데이터", "staff": "ag-data", "sessionId": STRAY}]
        self.assertEqual(self.o.away_of(rows, self.office("t1"), where)["away"], [])


class Members(Base):
    def members_body(self, *extra):
        return [{"role": "팀장", "sessionId": LEAD}, {"role": "개발자", "sessionId": DEV, "was": "개발자"}, {"role": "QA", "sessionId": None}] + list(extra)

    def test_check_members_accepts_staff_rows(self):
        out = self.o.check_members([{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner", "sessionId": None}])
        self.assertEqual(out[1], {"role": "기획", "sessionId": None, "staff": "ag-planner"})
        e = self.refused(409, self.o.check_members, [{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner", "sessionId": NEW}])
        self.assertIn(NO_SEAT, e.msg)
        self.refused(409, self.o.check_members, [{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner", "codexId": CX}])
        self.refused(400, self.o.check_members, [{"role": "팀장", "staff": "ag-lead"}])
        out = self.nt.parse_members([{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner"}])
        self.assertEqual(out[1], {"role": "기획", "sessionId": "", "staff": "ag-planner"})
        with self.assertRaises(self.nt.TeamError):
            self.nt.parse_members([{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner", "sessionId": NEW}])

    def test_setup_members_keeps_staff_rows(self):
        staff_rows = [r for r in staff_floor() if "staff" in r]
        for extra in ((), ({"role": "기획", "sessionId": None, "was": "기획"},), ({"role": "기획", "staff": "ag-planner"},)):
            self.setUp()
            r = self.o.api_setup_members({"team": "t1", "members": self.members_body(*extra)})
            self.assertEqual([m["role"] for m in r["members"]], ["팀장", "개발자", "QA"])
            rows = self.team("t1")["members"]
            self.assertEqual([m for m in rows if "staff" in m], staff_rows)                  # 지우지도 고치지도 않아요
            self.assertEqual([m["role"] for m in rows], ["팀장", "개발자", "기획", "QA", "마케팅", "운영", "데이터"])   # 자리도 그대로
        self.setUp()
        before = self.team_bytes("t1")
        e = self.refused(409, self.o.api_setup_members, {"team": "t1", "members": self.members_body({"role": "기획", "sessionId": NEW})})
        self.assertIn(NO_SEAT, e.msg)
        self.refused(409, self.o.api_setup_members, {"team": "t1", "members": self.members_body({"role": "마케팅", "codexId": CX})})
        self.refused(400, self.o.api_setup_members, {"team": "t1", "members": self.members_body({"role": "새직원", "staff": "ag-new"})})
        many = [{"role": f"자리{i}", "sessionId": None} for i in range(6)]                 # 3 + 6 + 직원 4 = 13
        self.refused(400, self.o.api_setup_members, {"team": "t1", "members": self.members_body(*many)})
        self.assertEqual(self.team_bytes("t1"), before)

    def test_stray_session_in_staff_row_can_sit_elsewhere(self):
        """직원 줄에 잘못 적힌 sessionId(0.12.0 함정, 데이터 줄의 STRAY)는 쓰지 않는 값이에요. 같은 층의 다른 자리에 그 세션을 앉힐 수 있어요
        (팀원 고치기·세션 만들기 모두. 화면의 heldSessions·existing_team의 keptSessions와 같은 말이에요). 직원 줄은 그대로예요."""
        body = [{"role": "팀장", "sessionId": LEAD}, {"role": "개발자", "sessionId": DEV, "was": "개발자"}, {"role": "QA", "sessionId": STRAY}]
        r = self.o.api_setup_members({"team": "t1", "members": body})
        self.assertEqual([m["sessionId"] for m in r["members"]], [LEAD, DEV, STRAY])
        rows = self.team("t1")["members"]
        self.assertEqual(next(m for m in rows if m["role"] == "데이터"), {"role": "데이터", "staff": "ag-data", "sessionId": STRAY})   # 직원 줄은 그대로
        self.setUp()
        with self.o.TEAM_LOCK:
            self.o.seat_write("t1", "QA", STRAY)
        self.assertEqual(self.team("t1")["members"][3]["sessionId"], STRAY)
        self.setUp()
        rows = staff_floor() + [{"role": "UI/UX", "sessionId": NEW}]                     # 그대로 두는 깨진 줄에 앉은 세션은 여전히 막아요
        with open(os.path.join(self.office("t1"), "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "층", "members": rows}, f, ensure_ascii=False)
        body[2]["sessionId"] = NEW
        e = self.refused(400, self.o.api_setup_members, {"team": "t1", "members": body})
        self.assertIn("UI/UX", e.msg)
        with self.o.TEAM_LOCK:
            self.refused(409, self.o.seat_write, "t1", "QA", NEW)

    def test_member_name_on_staff_changes_only_name(self):
        r = self.o.api_setup_member_name({"team": "t1", "role": "기획", "name": "민지"})
        self.assertEqual(r["name"], "민지")
        self.assertEqual(self.team("t1")["members"][2], {"role": "기획", "staff": "ag-planner", "sessionId": None, "name": "민지"})

    def test_existing_team_lists_staff_not_kept(self):
        proj =os.path.join(self.tmp, "ex-proj")
        os.makedirs(os.path.join(proj, ".office"), exist_ok=True)
        with open(os.path.join(proj, ".office", "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "x", "members": staff_floor() + [{"role": "UI/UX", "sessionId": None}]}, f, ensure_ascii=False)
        ex = self.o.existing_team(proj)
        self.assertEqual([m["role"] for m in ex["members"]], ["팀장", "개발자", "QA"])
        self.assertEqual((ex["kept"], ex["keptCount"]), (["UI/UX"], 1))              # 직원 줄은 깨진 줄이 아니에요
        self.assertEqual([s["role"] for s in ex["staff"]], ["기획", "마케팅", "운영", "데이터"])
        self.assertEqual(ex["staff"][2]["staff"], None)
        self.assertNotIn(STRAY, ex["keptSessions"])
        with open(os.path.join(proj, ".office", "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "x", "members": FLOORS["t3"][1]()}, f, ensure_ascii=False)
        self.assertNotIn("staff", self.o.existing_team(proj))                         # 옛 사무실의 답은 그대로예요

    def test_recommend_rows_avoid_staff_roles(self):
        ex = {"members": [{"role": "팀장", "sessionId": LEAD, "name": ""}], "keptSessions": {},
              "staff": [{"role": "기획", "staff": "ag-planner", "name": ""}]}
        pool = [{"tool": "claude", "id": NEW, "title": "기획 세션", "act": 1, "guess": "기획", "why": "제목의 '기획'", "alt": None, "altWhy": ""}]
        rows, left = self.o.rec_rows(pool, ex, {})
        self.assertEqual([r["role"] for r in rows], ["팀장", "기획2"])
        ex["staff"] = [{"role": f"직원{i}", "staff": f"ag-s{i}", "name": ""} for i in range(11)]
        rows, left = self.o.rec_rows(pool, ex, {})
        self.assertEqual((len(rows), left), (1, 1))                                     # 직원 줄도 12자리에 세요


class NewTeam(Base):
    def project(self, name, members):
        proj = os.path.join(self.tmp, "proj", name)
        shutil.rmtree(proj, ignore_errors=True)
        os.makedirs(os.path.join(proj, ".office"))
        with open(os.path.join(proj, ".office", "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "직원팀", "prefix": "ST-", "members": members}, f, ensure_ascii=False, indent=2)
        link = os.path.join(self.dir, "teams", name)
        if os.path.islink(link):
            os.remove(link)
        return proj

    def run_spec(self, floor):
        r = subprocess.run([sys.executable, "-I", os.path.join(self.dir, "bin", "new_team.py"), "--spec", "-"], cwd=self.dir,
                           input=json.dumps({"boss": None, "dropDemo": True, "floors": [floor]}, ensure_ascii=False),
                           capture_output=True, text=True, env=dict(os.environ, **self.env), timeout=60)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def rows(self, proj):
        with open(os.path.join(proj, ".office", "team.json"), encoding="utf-8") as f:
            return json.load(f)["members"]

    def test_members_spec_keeps_staff(self):
        for echo in ((), ({"role": "기획", "staff": "ag-planner"},), ({"role": "기획", "sessionId": None},)):
            proj = self.project("nt1", staff_floor())
            res = self.run_spec({"id": "nt1", "name": "직원팀", "folder": proj,
                                 "members": [{"role": "팀장", "sessionId": None}, {"role": "QA", "sessionId": None}] + list(echo)})
            self.assertTrue(res["ok"] and res["created"], res)
            rows = self.rows(proj)
            self.assertEqual([m for m in rows if "staff" in m], [m for m in staff_floor() if "staff" in m])
            self.assertEqual([m["role"] for m in rows], ["팀장", "기획", "QA", "마케팅", "운영", "데이터"])   # 보내지 않은 개발자만 빠져요
            self.setUp()

    def test_session_into_staff_role_stops(self):
        for floor in ({"members": [{"role": "팀장", "sessionId": None}, {"role": "기획", "sessionId": NEW}]},
                      {"members": [{"role": "팀장", "sessionId": None}, {"role": "새직원", "staff": "ag-new"}]},
                      {"roles": {"팀장": None, "기획": NEW}}):
            proj = self.project("nt2", staff_floor())
            with open(os.path.join(proj, ".office", "team.json"), "rb") as f:
                before = f.read()
            res = self.run_spec(dict(floor, id="nt2", name="직원팀", folder=proj))
            self.assertEqual(res["created"], [], res)
            self.assertTrue(res["errors"][0]["error"], res)
            with open(os.path.join(proj, ".office", "team.json"), "rb") as f:
                self.assertEqual(f.read(), before)
            self.setUp()

    def test_stray_session_in_staff_row_does_not_block_new_team(self):
        """new_team.py도 직원 줄에 잘못 적힌 sessionId를 세지 않아요(more_seats). 직원 줄은 그대로예요."""
        proj = self.project("nt4", staff_floor())
        res = self.run_spec({"id": "nt4", "name": "직원팀", "folder": proj,
                             "members": [{"role": "팀장", "sessionId": None}, {"role": "QA", "sessionId": STRAY}]})
        self.assertTrue(res["ok"] and res["created"], res)
        rows = self.rows(proj)
        self.assertEqual(next(m for m in rows if m["role"] == "QA")["sessionId"], STRAY)
        self.assertEqual(next(m for m in rows if m["role"] == "데이터"), {"role": "데이터", "staff": "ag-data", "sessionId": STRAY})
        self.assertEqual(self.nt.more_seats(staff_floor(), staff_floor() + [{"role": "QA", "sessionId": STRAY}]), set())
        self.assertEqual(self.nt.more_seats([{"role": "x/y", "sessionId": NEW}], [{"role": "x/y", "sessionId": NEW}, {"role": "QA", "sessionId": NEW}]), {NEW})

    def test_roles_spec_leaves_staff_row(self):
        proj = self.project("nt3", [{"role": "팀장", "sessionId": None}, {"role": "기획", "staff": "ag-planner", "sessionId": None}])
        res = self.run_spec({"id": "nt3", "name": "직원팀", "folder": proj, "roles": {"팀장": NEW, "기획": None}})
        self.assertTrue(res["created"], res)
        rows = self.rows(proj)
        self.assertEqual(rows[1], {"role": "기획", "staff": "ag-planner", "sessionId": None})   # 세션 자리로 바꾸지 않아요
        self.assertEqual(rows[0]["sessionId"], NEW)
        self.assertEqual(sum(1 for m in rows if m["role"] == "기획"), 1)                  # 같은 역할의 세션 줄을 더하지 않아요

    def test_merged_rows_directly(self):
        old = {"members": staff_floor()}
        m = self.nt.merged_rows(old, "직원팀", [{"role": "팀장", "sessionId": NEW}, {"role": "기획", "sessionId": "", "staff": "ag-planner"}], True)
        self.assertEqual([r for r in m if "staff" in r], [r for r in staff_floor() if "staff" in r])
        m = self.nt.merged_rows({"members": [{"role": "팀장", "staff": "ag-lead"}, {"role": "팀장", "sessionId": None}]}, "직원팀",
                                [{"role": "팀장", "sessionId": NEW}], False)
        self.assertEqual(m[0], {"role": "팀장", "staff": "ag-lead"})                      # 팀장 직원 줄(깨진 줄)에도 세션을 넣지 않아요
        self.assertEqual(m[1]["sessionId"], NEW)


class Signal(Base):
    """S3 신호: 팀장 pid 파일 → CLI 세션 id → subagents/agent-*.meta.json(agentType·finished)과 jsonl 고친 시각."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sleeper = subprocess.Popen(["sleep", "300"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.run_dir, cls.projects = cls.env["AGENCITY_CLAUDE_RUN_DIR"], cls.env["AGENCITY_CLAUDE_PROJECTS_DIR"]

    @classmethod
    def tearDownClass(cls):
        cls.sleeper.kill()
        cls.sleeper.wait()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        for d in (self.run_dir, self.projects):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        for c in (self.o.STAFF_SCAN, self.o.STAFF_DIRS, self.o.STAFF_SINCE, self.o.BOARD_SEEN):
            c.clear()
        self.sub = os.path.join(self.projects, "-proj", CLI, "subagents")
        os.makedirs(self.sub)
        open(os.path.join(self.projects, "-proj", CLI + ".jsonl"), "w").close()
        self.lead_pid()

    def lead_pid(self, status="idle"):
        """팀장 pid 파일. 15분째 쉬는 중이어도(U-27 live에서는 빠지는 자리) 프로세스가 살아 있으면 팀장 기록이에요."""
        now = int(time.time() * 1000)
        with open(self.pid_path(), "w", encoding="utf-8") as f:
            json.dump({"pid": self.sleeper.pid, "hostSessionId": LEAD, "status": status, "statusUpdatedAt": now - 900000, "startedAt": now - 990000,
                       "sessionId": CLI, "cwd": "/private/tmp/비밀폴더표시"}, f, ensure_ascii=False)

    def pid_path(self):
        return os.path.join(self.run_dir, f"{self.sleeper.pid}.json")

    def worker(self, aid, typ="ag-planner", finished=None, age=0, meta_age=None, folder=None):
        d = folder or self.sub
        os.makedirs(d, exist_ok=True)
        meta = {"agentType": typ, "description": SECRET_DESC, "prompt": SECRET_DESC, "nested": {"description": SECRET_DESC}}
        if finished is not None:
            meta["finished"] = finished
        p, j = os.path.join(d, f"agent-{aid}.meta.json"), os.path.join(d, f"agent-{aid}.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        with open(j, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": SECRET_DESC}, ensure_ascii=False) + "\n")
        os.utime(j, (time.time() - age,) * 2)
        if meta_age is not None:
            os.utime(p, (time.time() - meta_age,) * 2)
        return p, j

    def live(self):
        return self.o.staff_live()

    def status(self, role, tid="t1"):
        with open(os.path.join(self.office(tid), "status", role + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def test_cycle_run_finish_resume_no_lead_idle(self):
        _, j = self.worker("a1")                                                         # 돌기: 끝 표시가 없고 기록이 막 바뀌었어요
        live = self.live()
        self.assertEqual(set(live), {"t1", "t2"})
        self.assertEqual(set(live["t1"]), {"기획", "마케팅", "데이터"})                     # 이름 꼴이 틀린 직원(운영)과 세션 자리는 없어요
        x = live["t1"]["기획"]
        self.assertEqual((x["s"], x["staff"], x["n"]), ("busy", True, 1))
        self.assertLess(abs(x["since"] - time.time() * 1000), 5000)
        self.assertEqual(live["t1"]["마케팅"]["s"], "idle")
        self.assertEqual(self.status("기획")["state"], "일하는 중")
        self.worker("a1", finished=True, age=60)                                        # 끝: finished true, 기록은 1분 전
        x2 = self.live()["t1"]["기획"]
        self.assertEqual((x2["s"], x2["n"]), ("idle", 0))
        self.assertGreaterEqual(x2["since"], x["since"])
        self.assertEqual(self.status("기획")["state"], "대기")
        os.utime(j, None)                                                              # 이어 쓰기: finished는 true 그대로, 기록만 바뀌어요(20초 안)
        self.assertEqual(self.live()["t1"]["기획"]["s"], "busy")
        self.assertEqual(self.status("기획")["state"], "일하는 중")
        os.utime(j, (time.time() - 21,) * 2)
        self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")                          # 20초가 지나면 대기
        os.utime(j, None)
        os.remove(self.pid_path())                                                     # 팀장 없음: 팀장 프로세스가 없으면 모두 대기
        self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")
        self.assertEqual(self.status("기획")["state"], "대기")
        self.lead_pid("busy")
        self.assertEqual(self.live()["t1"]["기획"]["s"], "busy")
        self.worker("a1", age=31 * 60)                                                  # 끝 표시 없이 30분 넘게 그대로: 거짓 '일하는 중'을 남기지 않아요
        self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")
        self.worker("a1", age=29 * 60)
        self.assertEqual(self.live()["t1"]["기획"]["s"], "busy")
        self.assertEqual(self.live()["t2"]["기획"]["s"], "idle")                         # 팀장이 없는 층은 늘 대기
        self.assertEqual(self.status("기획", "t2")["state"], "대기")

    def test_resume_of_old_worker_is_seen_at_once(self):
        """2시간 넘게 그대로였던(끝난) 일꾼에게 이어 쓰기: 다음에 잴 때 바로 일하는 중이에요(30초를 기다리지 않아요).
        재는 사이에 끝난 짧은 이어 쓰기(기록은 25초 전)도 알아챈 때부터 20초 동안 일하는 중이에요."""
        _, j = self.worker("old", finished=True, age=3 * 3600, meta_age=3 * 3600)
        x = self.live()["t1"]["기획"]
        self.assertEqual((x["s"], x["n"]), ("idle", 0))
        os.utime(j, None)                                                              # 이어 쓰기: 기록만 바뀌어요
        x = self.live()["t1"]["기획"]
        self.assertEqual((x["s"], x["n"]), ("busy", 1))
        self.assertEqual(self.status("기획")["state"], "일하는 중")
        os.utime(j, (time.time() - 3 * 3600,) * 2)                                      # 다시 오래된 일꾼
        self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")
        os.utime(j, (time.time() - 25,) * 2)                                            # 25초 전에 끝난 짧은 이어 쓰기를 이제야 봤어요
        self.assertEqual(self.live()["t1"]["기획"]["s"], "busy")
        self.assertEqual(self.live()["t1"]["기획"]["s"], "busy")                          # 알아챈 때부터 20초는 그대로
        later = time.time() + 21
        with mock.patch.object(self.o.time, "time", return_value=later):
            self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")
        calls = []
        with mock.patch.object(self.o, "staff_meta", side_effect=lambda p: calls.append(p) or ("ag-planner", True)):
            for i in range(50):
                self.worker(f"o{i}", finished=True, age=3 * 3600, meta_age=3 * 3600)
            self.o.STAFF_SCAN.clear()
            self.live()
            self.live()
            self.assertEqual(len(calls), 1)                                             # 오래된 50개는 시각만 재요(meta.json은 2시간 안에 바뀐 'old' 하나만 열어요)

    def test_dead_lead_process_counts_as_missing(self):
        gone = subprocess.Popen(["true"])
        gone.wait()
        os.remove(self.pid_path())
        with open(os.path.join(self.run_dir, f"{gone.pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": gone.pid, "hostSessionId": LEAD, "status": "busy", "statusUpdatedAt": 1, "sessionId": CLI}, f)
        self.worker("a1")
        self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")

    def test_counts_kinds_and_places(self):
        self.worker("a1")
        self.worker("a2")
        self.worker("a3", typ="ag-marketer", finished=True, age=5)
        self.worker("a4", typ="general-purpose")                                        # 직원이 아닌 일꾼
        self.worker("a5", typ="ag-nobody")                                              # 이 층에 없는 명찰
        self.worker("w1", folder=os.path.join(self.sub, "workflows", "x"))              # workflows 아래는 보지 않아요
        self.worker("b1", typ="ag-data", folder=os.path.join(self.projects, "-other", "99999999-2222-4333-8444-555555555555", "subagents"))   # 다른 세션
        live = self.live()["t1"]
        self.assertEqual((live["기획"]["s"], live["기획"]["n"]), ("busy", 2))
        self.assertEqual((live["마케팅"]["s"], live["마케팅"]["n"]), ("busy", 1))
        self.assertEqual(live["데이터"]["s"], "idle")
        with open(os.path.join(self.sub, "agent-l1.meta.json.real"), "w", encoding="utf-8") as f:
            json.dump({"agentType": "ag-data"}, f)
        os.symlink(os.path.join(self.sub, "agent-l1.meta.json.real"), os.path.join(self.sub, "agent-l1.meta.json"))   # 링크는 따라가지 않아요
        self.assertEqual(self.live()["t1"]["데이터"]["s"], "idle")

    def test_descriptions_are_never_kept(self):
        self.worker("a1")
        live = self.live()
        self.assertEqual(live["t1"]["기획"]["s"], "busy")
        for blob in (json.dumps(live, ensure_ascii=False), repr(self.o.STAFF_SCAN), repr(self.o.STAFF_DIRS), repr(self.o.STAFF_SINCE)):
            self.assertNotIn(SECRET_DESC, blob)
            self.assertNotIn("비밀폴더표시", blob)
        for n in os.listdir(os.path.join(self.office("t1"), "status")):
            with open(os.path.join(self.office("t1"), "status", n), encoding="utf-8") as f:
                self.assertNotIn(SECRET_DESC, f.read())
        self.assertEqual(self.o.staff_meta(os.path.join(self.sub, "agent-a1.meta.json")), ("ag-planner", False))

    def test_only_meta_files_are_opened(self):
        """jsonl은 열지 않아요. 2시간 넘게 그대로인 일꾼은 meta.json도 열지 않아요. 그대로인 meta.json은 다시 열지 않아요."""
        self.worker("a1")
        self.worker("old", age=3 * 3600, meta_age=3 * 3600)
        code = f"""
import json, os, sys
seen = []
sys.addaudithook(lambda e, a: seen.append(str(a[0])) if e == "open" and isinstance(a[0], str) else None)
sys.path.insert(0, os.getcwd())
import office_server as o
first = o.staff_live()
a = [x for x in seen if {self.projects!r} in x]
seen.clear()
o.staff_live()
b = [x for x in seen if {self.projects!r} in x]
print(json.dumps({{"a": a, "b": b, "s": first["t1"]["기획"]["s"]}}))
"""
        out = subprocess.run([sys.executable, "-I", "-c", code], cwd=self.dir, env=dict(os.environ, **self.env), capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(got["s"], "busy")
        self.assertEqual(got["a"], [os.path.join(self.sub, "agent-a1.meta.json")])
        self.assertEqual(got["b"], [])

    def test_many_files_stay_light(self):
        for i in range(400):
            self.worker(f"o{i}", age=3 * 3600, meta_age=3 * 3600)
        self.worker("a1")
        calls = []
        with mock.patch.object(self.o, "staff_meta", side_effect=lambda p: calls.append(p) or ("ag-planner", False)):
            self.assertEqual(self.live()["t1"]["기획"]["n"], 1)
            self.assertEqual(len(calls), 1)                                              # 오래된 400개는 열지 않아요
            self.live()
            self.assertEqual(len(calls), 1)                                              # 그대로인 meta.json은 다시 열지 않아요

    def test_status_written_only_on_change(self):
        o = self.o
        dev = os.path.join(self.office("t1"), "status", "개발자.json")
        with open(dev, "w", encoding="utf-8") as f:
            f.write('{"state":"회의 중","updated":"2026-11-01T00:00:00+09:00"}')
        with open(os.path.join(self.office("t1"), "status", "기획.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "기획 직원", "role": "기획", "state": "막힘", "task": "", "say": "옛 말", "prev_state": "x"}, f, ensure_ascii=False)
        self.worker("a1")
        real = o.write_json
        with mock.patch.object(o, "write_json", side_effect=real) as w:
            self.live()
            mine = [c.args[0] for c in w.call_args_list]
            self.assertIn(os.path.join(self.office("t1"), "status", "기획.json"), mine)
            st = self.status("기획")
            self.assertEqual({k: st[k] for k in ("name", "role", "state", "task", "say")},
                             {"name": "기획 직원", "role": "기획", "state": "일하는 중", "task": "", "say": ""})
            self.assertNotIn("prev_state", st)
            w.reset_mock()
            self.live()
            self.live()
            self.assertEqual(w.call_args_list, [])                                      # 그대로면 쓰지 않아요
        with open(dev, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"state":"회의 중","updated":"2026-11-01T00:00:00+09:00"}')   # 세션 줄의 status는 쓰지 않아요
        rows = staff_floor() + [{"role": "기획", "sessionId": NEW}]                        # 깨진 파일: 같은 역할에 세션이 앉은 줄도 있어요
        with open(os.path.join(self.office("t1"), "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "층", "members": rows}, f, ensure_ascii=False)
        os.utime(os.path.join(self.sub, "agent-a1.jsonl"), (time.time() - 3000,) * 2)
        self.assertEqual(self.live()["t1"]["기획"]["s"], "idle")
        self.assertEqual(self.status("기획")["state"], "일하는 중")                         # 그 역할의 status는 쓰지 않았어요

    def test_task_from_board(self):
        board = os.path.join(self.office("t1"), "board.md")
        with open(board, "w", encoding="utf-8") as f:
            f.write("# 업무판\n\n- [ ] U-7 | 팀장 | 큰 일 | 진행\n- [ ] U-7-기획 | 기획 | 기획서 쓰기 | 진행\n- [x] U-6-기획 | 기획 | 끝난 일 | 끝\n"
                    "- [ ] U-8 | 기획 | 번호 꼴이 다른 줄 | 진행\n- [ ] U-9-기획 | 기획 | 두 번째 직원 줄 | 진행\n- [ ] U-9-마케팅 | 마케팅 | " + "가" * 100 + " | 진행\n"
                    "- [ ] U-10 | 데이터 | 데이터 줄 | 진행\n")
        self.live()
        self.assertEqual(self.status("기획")["task"], "U-9-기획 두 번째 직원 줄")             # '-<역할>' 줄 중 마지막
        task = self.status("마케팅")["task"]
        self.assertEqual(len(task), 80)
        self.assertTrue(task.startswith("U-9-마케팅 가가"))
        self.assertEqual(self.status("데이터")["task"], "U-10 데이터 줄")                     # '-<역할>' 줄이 없으면 그 역할의 열린 줄
        with open(board, "w", encoding="utf-8") as f:
            f.write("- [x] U-9-기획 | 기획 | 닫았어요 | 끝\n")
        self.live()
        self.assertEqual(self.status("기획")["task"], "")

    def test_old_install_has_no_staff_parts(self):
        """직원 줄이 없는 설치본: 직원 신호·직원 정보가 비고, status 파일도 쓰지 않아요(옛 층의 답과 파일이 그대로예요)."""
        o = self.o
        with open(os.path.join(self.dir, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"boss": {"name": "총괄", "sessionId": BOSS}, "teams": [{"id": "t3", "name": "옛 층", "office": "teams/t3", "floor": 1}]}, f, ensure_ascii=False)
        self.worker("a1", typ="ag-planner")
        before = sorted(os.listdir(os.path.join(self.office("t3"), "status")))
        o.staff_forget()
        self.assertEqual((o.staff_live(), o.staff_info(), o.staff_floors()), ({}, {}, []))
        self.assertEqual(o.run_live(), {})                                               # 팀장 pid가 15분째 쉬는 중이라 U-27 live에서는 빠져요
        self.assertEqual(sorted(os.listdir(os.path.join(self.office("t3"), "status"))), before)
        now = int(time.time() * 1000)
        with open(self.pid_path(), "w", encoding="utf-8") as f:
            json.dump({"pid": self.sleeper.pid, "hostSessionId": LEAD3, "status": "busy", "statusUpdatedAt": now - 1000, "startedAt": now - 600000}, f)
        self.assertEqual(o.run_live(), {"t3": {"팀장": {"s": "busy", "since": now - 1000}}})   # 옛 꼴 그대로(staff·n 칸 없음)

    def test_live_merges_into_run_live(self):
        """세션 자리(U-27 live)와 같은 자리, 같은 꼴로 합쳐요. 옛 층(t3)의 답은 그대로예요."""
        self.worker("a1")
        live = self.o.run_live()
        self.assertEqual(live["t1"]["기획"]["s"], "busy")
        self.assertNotIn("t3", live)
        self.assertNotIn("팀장", live["t1"])                                              # 팀장 pid는 15분째 쉬는 중이라 U-27 live에서는 빠져요


class StaffHire(Base):
    """S3 들이기·퇴근·명찰 다시 만들기·켜기. 팀장 폴더는 가짜 Claude 앱 세션 기록의 cwd로 찾아요."""

    def setUp(self):
        super().setUp()
        o = self.o
        o.staff_forget()
        self.lead = os.path.join(self.tmp, "lead1")
        shutil.rmtree(self.lead, ignore_errors=True)
        os.makedirs(os.path.join(self.lead, ".git", "info"))                             # 팀장 폴더가 git 저장소예요
        self.session_record(LEAD, self.lead)
        sk = os.path.join(self.office("t1"), "skills", "public-copy-check")
        os.makedirs(sk)
        with open(os.path.join(sk, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: public-copy-check\ndescription: 층 스킬\n---\n")
        mine = os.path.join(self.env["HOME"], ".claude", "skills", "my-skill")
        os.makedirs(mine, exist_ok=True)
        with open(os.path.join(mine, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: my-skill\ndescription: 개인 스킬\n---\n")
        o.api_staff_enable({"team": "t1", "on": True})

    def session_record(self, sid, cwd):
        d = os.path.join(self.o.SESSIONS_DIR, "acct", "org")
        shutil.rmtree(os.path.dirname(d), ignore_errors=True)
        os.makedirs(d)
        with open(os.path.join(d, sid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"sessionId": sid, "cwd": cwd, "title": "팀장 창", "lastActivityAt": int(time.time() * 1000)}, f, ensure_ascii=False)
        self.o.staff_forget()

    def hire(self, **over):
        body = {"team": "t1", "role": "작가", "staff": "ag-writer", "desc": "글을 쓰는 직원", "work": "보고서와 안내문을 써요.\n짧게 써요.",
                "tools": ["Write", "Read", "Edit", "Read"], "model": "sonnet", "skills": ["public-copy-check", "my-skill"]}
        body.update(over)
        return self.o.api_staff_hire(body)

    def agent(self, name="ag-writer"):
        return os.path.join(self.lead, ".claude", "agents", name + ".md")

    def read(self, p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    def info(self, role="작가"):
        self.o.staff_forget()
        return self.o.staff_info()["t1"][role]

    def test_hire_makes_folder_row_agent_and_hash(self):
        base = self.office("t1")
        r = self.hire()
        self.assertEqual((r["role"], r["staff"], r["restart"]), ("작가", "ag-writer", True))
        self.assertEqual((r["git"]["repo"], r["git"]["excluded"], r["git"]["line"]), (True, True, ".claude/agents/ag-*.md"))
        self.assertEqual(r["git"]["added"], [".claude/agents/ag-*.md", ".claude/skills/public-copy-check"])   # 건 스킬 링크도 한 줄(개인 스킬은 링크가 없어요)
        self.assertEqual(self.team("t1")["members"][-1], {"role": "작가", "staff": "ag-writer", "sessionId": None})
        sdir = os.path.join(base, "staff", "ag-writer")
        self.assertEqual(sorted(os.listdir(sdir)), [".agent.sha256", "SKILL.md", "기억.md"])
        text = self.read(self.agent())
        self.assertEqual(text, self.o.staff_agent_text(base, "ag-writer"))
        self.assertTrue(text.startswith("---\nname: ag-writer\ndescription: 글을 쓰는 직원\ntools: Read, Write, Edit\nmodel: sonnet\n"
                                        "skills: [public-copy-check, my-skill]\n---\n너는 층 직원 '작가'의 일꾼이에요. 팀장이 준 [일 맡기기] 범위까지만 해요. "
                                        "RULES.md의 '직원 일꾼' 장을 따라요.\n\n# 작가\n\n## 하는 일\n보고서와 안내문을 써요.\n짧게 써요.\n"), text[:400])
        self.assertTrue(text.endswith(f"\n\n시작하면 `{os.path.join(base, 'staff', 'ag-writer', '기억.md')}`를 읽어요.\n"))
        self.assertEqual(self.read(os.path.join(sdir, ".agent.sha256")).strip(), hashlib.sha256(text.encode("utf-8")).hexdigest())
        link = os.path.join(self.lead, ".claude", "skills", "public-copy-check")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), os.path.join(base, "skills", "public-copy-check"))   # 층 스킬만 링크해요
        self.assertFalse(os.path.lexists(os.path.join(self.lead, ".claude", "skills", "my-skill")))   # 개인 스킬은 그대로
        self.assertEqual(self.status_of("작가")["state"], "대기")
        sk = self.o.staff_skill(base, "ag-writer")
        self.assertEqual((sk["role"], sk["tools"], sk["model"], sk["skills"]), ("작가", ["Read", "Write", "Edit"], "sonnet", ["public-copy-check", "my-skill"]))
        r2 = self.hire(role="편집", staff="ag-editor", skills=[], tools=["Read"], model="inherit")
        self.assertEqual((r2["restart"], r2["git"]["excluded"], r2["git"]["already"]), (False, False, True))
        self.assertNotIn("skills:", self.read(self.agent("ag-editor")).split("---")[1])   # 쓸 스킬이 없으면 skills 줄이 없어요
        ex = self.read(os.path.join(self.lead, ".git", "info", "exclude")).splitlines()
        self.assertEqual((ex.count(".claude/agents/ag-*.md"), ex.count(".claude/skills/public-copy-check")), (1, 1))
        self.assertNotIn(".claude/skills/", ex)                                          # 스킬 폴더 통째로는 넣지 않아요(내 스킬이 있을 수 있어요)
        info = self.info()
        self.assertEqual(info, {"staff": "ag-writer", "skill_path": self.o.show_path(os.path.join(sdir, "SKILL.md")),
                                "memory_path": self.o.show_path(os.path.join(sdir, "기억.md")), "tools": ["Read", "Write", "Edit"], "model": "sonnet",
                                "skills": ["public-copy-check", "my-skill"], "agent": "ok", "missing_skills": [],
                                "agent_tools": ["Read", "Write", "Edit"], "agent_model": "sonnet", "agent_diff": False})
        rec = self.o.STAFF_RECORD                                                        # 지은 명찰 기록은 설정 폴더의 0600 파일이에요(일꾼이 닿는 곳 밖)
        self.assertEqual(os.path.dirname(rec), self.env["AGENCITY_CONFIG_DIR"])
        self.assertEqual(os.stat(rec).st_mode & 0o777, 0o600)
        with open(rec, encoding="utf-8") as f:
            body = f.read()
        self.assertNotIn(base, body)                                                     # 경로는 적지 않아요(열쇠는 해시)
        self.assertEqual(sorted(x["tools"] for x in json.loads(body)["agents"].values()), [["Read"], ["Read", "Write", "Edit"]])

    def status_of(self, role):
        with open(os.path.join(self.office("t1"), "status", role + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def test_hire_refusals_leave_nothing(self):
        base = self.office("t1")
        before = self.team_bytes("t1")
        cases = [(400, dict(staff="Planner")), (400, dict(staff="ag-")), (400, dict(staff="ag-가")), (400, dict(staff="ag-../x")),
                 (400, dict(staff="ag-x/../../y")), (400, dict(role="../x")), (400, dict(role="팀장")), (400, dict(role="총괄")),
                 (409, dict(role="개발자")), (409, dict(role=" 기획 ")), (409, dict(role="qa")), (409, dict(staff="ag-planner", role="새자리")),
                 (400, dict(desc="두\n줄")), (400, dict(desc="가" * 301)), (400, dict(work="")), (400, dict(work="가" * 4001)),
                 (400, dict(tools=[])), (400, dict(tools=["Read", "Task"])), (400, dict(tools="Read")), (400, dict(model="gpt")),
                 (400, dict(skills=["../x"])), (409, dict(skills=["nothing-here"])), (409, dict(team="t3"))]
        for code, over in cases:
            e = self.refused(code, lambda: self.hire(**over))
            self.assertTrue(e.msg, over)
        self.assertEqual(self.team_bytes("t1"), before)
        self.assertFalse(os.path.lexists(os.path.join(base, "staff")))
        self.assertFalse(os.path.lexists(os.path.join(self.lead, ".claude")))
        os.makedirs(os.path.join(base, "staff", "ag-writer"))                              # 직원 폴더가 이미 있어요(퇴근한 직원 등)
        self.assertEqual(self.refused(409, self.hire).extra["why"], "folder")
        shutil.rmtree(os.path.join(base, "staff"))
        self.session_record(NEW, self.lead)                                             # 팀장 세션 기록을 못 찾아요
        self.assertEqual(self.refused(409, self.hire).extra["why"], "lead")
        self.session_record(LEAD, self.lead)
        rows = staff_floor() + [{"role": f"자리{i}", "sessionId": None} for i in range(5)]   # 세션 줄 3 + 빈자리 5 + 직원 4 = 12
        with open(os.path.join(base, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "층", "members": rows}, f, ensure_ascii=False)
        self.assertEqual(self.refused(409, self.hire).extra["why"], "full")
        self.assertFalse(os.path.lexists(os.path.join(base, "staff")))

    def test_hire_refuses_links(self):
        base = self.office("t1")
        before = self.team_bytes("t1")
        other = os.path.join(self.tmp, "남의 폴더")
        shutil.rmtree(other, ignore_errors=True)
        os.makedirs(os.path.join(other, "agents"))
        os.symlink(other, os.path.join(self.lead, ".claude"))                            # .claude가 링크
        self.assertEqual(self.refused(409, self.hire).extra["why"], "link")
        os.remove(os.path.join(self.lead, ".claude"))
        os.makedirs(os.path.join(self.lead, ".claude"))
        os.symlink(os.path.join(other, "agents"), os.path.join(self.lead, ".claude", "agents"))   # agents가 링크
        self.assertEqual(self.refused(409, self.hire).extra["why"], "link")
        os.remove(os.path.join(self.lead, ".claude", "agents"))
        os.makedirs(os.path.join(self.lead, ".claude", "agents"))
        os.symlink(os.path.join(other, "x.md"), self.agent())                            # 명찰 자리가 (깨진) 링크
        self.assertEqual(self.refused(409, self.hire).extra["why"], "link")
        os.remove(self.agent())
        os.symlink(other, os.path.join(self.lead, ".claude", "skills"))                  # 스킬 폴더가 링크
        self.assertEqual(self.refused(409, self.hire).extra["why"], "link")
        os.remove(os.path.join(self.lead, ".claude", "skills"))
        os.symlink(other, os.path.join(base, "staff"))                                   # 직원 폴더 위가 링크
        self.assertEqual(self.refused(409, self.hire).extra["why"], "folder")
        os.remove(os.path.join(base, "staff"))
        self.assertEqual(os.listdir(os.path.join(other, "agents")), [])
        self.assertEqual(sorted(os.listdir(other)), ["agents"])
        self.assertEqual(self.team_bytes("t1"), before)
        self.assertEqual(os.listdir(os.path.join(self.lead, ".claude", "agents")), [])
        self.assertFalse(os.path.lexists(os.path.join(base, "staff")))
        self.assertFalse(os.path.lexists(os.path.join(self.lead, ".claude", "skills")))   # 실패한 들이기는 만든 폴더도 지워요

    def test_hire_rolls_back_when_team_json_fails(self):
        base = self.office("t1")
        before = self.team_bytes("t1")
        real = self.o.write_json

        def boom(path, obj):
            if path.endswith("team.json"):
                raise OSError(28, "공간 없음")
            return real(path, obj)
        with mock.patch.object(self.o, "write_json", side_effect=boom):
            self.refused(500, self.hire)
        self.assertEqual(self.team_bytes("t1"), before)
        self.assertFalse(os.path.lexists(os.path.join(base, "staff")))
        self.assertFalse(os.path.lexists(os.path.join(self.lead, ".claude")))           # 명찰, 스킬 링크, 새로 만든 폴더 모두 지웠어요
        self.assertFalse(os.path.exists(os.path.join(base, "status", "작가.json")))

    def test_rebuild_hash_and_changed(self):
        base = self.office("t1")
        self.hire()
        self.assertEqual(self.info()["agent"], "ok")
        with open(self.agent(), "a", encoding="utf-8") as f:
            f.write("손으로 더한 줄\n")                                                    # 누가 명찰을 고쳤어요
        self.assertEqual(self.info()["agent"], "바뀜")
        r = self.o.api_staff_rebuild({"team": "t1", "role": "작가"})
        self.assertEqual((r["restart"], r["links"]), (False, []))
        self.assertEqual(self.info()["agent"], "ok")
        skill = os.path.join(base, "staff", "ag-writer", "SKILL.md")
        text = self.read(skill).replace("description: 글을 쓰는 직원", 'description: "새 설명: 따옴표"')
        with open(skill, "w", encoding="utf-8") as f:
            f.write(text)                                                               # 대표가 SKILL.md를 고쳤어요: 명찰이 예전 것
        self.assertEqual(self.info()["agent"], "바뀜")
        self.o.api_staff_rebuild({"team": "t1", "role": "작가"})
        self.assertIn('\ndescription: "새 설명: 따옴표"\n', self.read(self.agent()))
        self.assertEqual(self.info()["agent"], "ok")
        os.remove(os.path.join(self.lead, ".claude", "skills", "public-copy-check"))
        self.assertEqual(self.info()["missing_skills"], ["public-copy-check"])
        self.assertEqual(self.o.api_staff_rebuild({"team": "t1", "role": "작가"})["links"], [self.o.show_path(os.path.join(self.lead, ".claude", "skills", "public-copy-check"))])
        os.remove(self.agent())
        self.assertEqual(self.info()["agent"], "없음")
        with open(skill, "w", encoding="utf-8") as f:
            f.write(text.replace("tools: [Read, Write, Edit]", "tools: [Read, Task]"))
        e = self.refused(409, self.o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.assertIn("Task", e.msg)
        self.assertIn("error", self.info())
        self.assertFalse(os.path.exists(self.agent()))
        self.session_record(NEW, self.lead)                                             # 팀장 폴더를 못 찾아요
        self.assertEqual(self.info()["agent"], "없음")
        self.refused(409, self.o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.refused(404, self.o.api_staff_rebuild, {"team": "t1", "role": "개발자"})
        self.refused(409, self.o.api_staff_rebuild, {"team": "t1", "role": "운영"})       # 명찰 이름 꼴이 틀린 직원

    def test_lead_folder_lookup(self):
        """팀장 폴더: 그 세션 파일만 읽어요(모든 기록을 읽지 않아요). 파일 이름이 달라도 모든 기록에서 찾고, 그래도 없으면 pid 기록의 cwd예요."""
        o = self.o
        with mock.patch.object(o, "claude_sessions", side_effect=AssertionError("모든 기록을 읽었어요")):
            self.assertEqual(o.lead_folder(LEAD), os.path.realpath(self.lead))
        d = os.path.join(o.SESSIONS_DIR, "acct", "org")
        os.rename(os.path.join(d, LEAD + ".json"), os.path.join(d, "local_zzzzzzzz.json"))
        o.staff_forget()
        self.assertEqual(o.lead_folder(LEAD), os.path.realpath(self.lead))
        os.remove(os.path.join(d, "local_zzzzzzzz.json"))
        o.staff_forget()
        self.assertIsNone(o.lead_folder(LEAD))
        p = subprocess.Popen(["sleep", "60"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with open(os.path.join(self.env["AGENCITY_CLAUDE_RUN_DIR"], f"{p.pid}.json"), "w", encoding="utf-8") as f:
                json.dump({"pid": p.pid, "hostSessionId": LEAD, "status": "idle", "statusUpdatedAt": 1, "cwd": self.lead}, f)
            self.assertEqual(o.lead_folder(LEAD), os.path.realpath(self.lead))
            for bad in (self.env["HOME"], self.dir, "/", os.path.join(self.tmp, "없는 폴더")):
                self.session_record(LEAD, bad)
                self.assertIsNone(o.lead_folder(LEAD), bad)                             # 홈·설치 폴더·/·없는 폴더에는 명찰을 두지 않아요
        finally:
            p.kill()
            p.wait()
            os.remove(os.path.join(self.env["AGENCITY_CLAUDE_RUN_DIR"], f"{p.pid}.json"))

    def test_restart_flag_when_agents_folder_is_new(self):
        os.makedirs(os.path.join(self.lead, ".claude"))
        self.assertTrue(self.hire()["restart"])
        shutil.rmtree(os.path.join(self.lead, ".claude", "agents"))
        self.assertTrue(self.o.api_staff_rebuild({"team": "t1", "role": "작가"})["restart"])
        self.assertFalse(self.o.api_staff_rebuild({"team": "t1", "role": "작가"})["restart"])

    def test_exclude_line_for_sub_folder_and_no_repo(self):
        shutil.rmtree(os.path.join(self.lead, ".git"))
        self.assertEqual(self.hire()["git"], {"repo": False, "excluded": False, "already": False})
        repo = os.path.join(self.tmp, "repo")
        shutil.rmtree(repo, ignore_errors=True)
        sub = os.path.join(repo, "앱", "web")
        os.makedirs(sub)
        os.makedirs(os.path.join(repo, ".git", "info"))
        self.session_record(LEAD, sub)
        g = self.o.api_staff_rebuild({"team": "t1", "role": "작가"})["git"]
        self.assertEqual((g["excluded"], g["line"]), (True, "앱/web/.claude/agents/ag-*.md"))

    def test_fire_moves_agent_and_keeps_folder(self):
        base = self.office("t1")
        self.hire()
        r = self.o.api_staff_fire({"team": "t1", "role": "작가"})
        self.assertEqual((r["role"], r["staff"]), ("작가", "ag-writer"))
        self.assertNotIn("작가", [m["role"] for m in self.team("t1")["members"]])
        self.assertFalse(os.path.lexists(self.agent()))
        retired = os.listdir(os.path.join(base, "staff", "ag-writer", "retired"))
        self.assertEqual(len(retired), 1)
        self.assertRegex(retired[0], r"^\d{8}-\d{6}-agent\.md\Z")
        self.assertTrue(self.read(os.path.join(base, "staff", "ag-writer", "retired", retired[0])).startswith("---\nname: ag-writer\n"))
        self.assertTrue(os.path.isfile(os.path.join(base, "staff", "ag-writer", "SKILL.md")))   # 직원 폴더는 남아요
        self.assertTrue(os.path.isfile(os.path.join(base, "status", "작가.json")))
        self.refused(404, self.o.api_staff_fire, {"team": "t1", "role": "작가"})
        self.refused(404, self.o.api_staff_fire, {"team": "t1", "role": "개발자"})         # 세션 자리는 퇴근시키지 않아요
        r = self.o.api_staff_fire({"team": "t1", "role": "기획"})                           # 명찰이 없는 직원 줄
        self.assertEqual((r["staff"], r["retired"]), ("ag-planner", None))
        self.assertEqual([m["role"] for m in self.team("t1")["members"]], ["팀장", "개발자", "QA", "마케팅", "운영", "데이터"])
        self.refused(409, self.hire)                                                    # 같은 이름의 폴더가 남아 있어요
        r = self.o.api_staff_fire({"team": "t1", "role": "운영"})                           # 이름 꼴이 틀린 직원 줄도 뺄 수 있어요
        self.assertEqual((r["staff"], r["retired"], r["kept"]), (None, None, None))

    def test_fire_refuses_link_and_restores_on_failure(self):
        base = self.office("t1")
        self.hire()
        before = self.team_bytes("t1")
        real = self.o.write_json

        def boom(path, obj):
            if path.endswith("team.json"):
                raise OSError(28, "공간 없음")
            return real(path, obj)
        with mock.patch.object(self.o, "write_json", side_effect=boom):
            self.refused(500, self.o.api_staff_fire, {"team": "t1", "role": "작가"})
        self.assertTrue(os.path.isfile(self.agent()))                                   # 옮긴 명찰을 되돌렸어요
        self.assertEqual(self.team_bytes("t1"), before)
        shutil.rmtree(os.path.join(base, "staff", "ag-writer", "retired"))
        os.symlink(os.path.join(self.tmp, "남의 곳"), os.path.join(base, "staff", "ag-writer", "retired"))
        self.assertEqual(self.refused(409, self.o.api_staff_fire, {"team": "t1", "role": "작가"}).extra["why"], "link")
        self.assertTrue(os.path.isfile(self.agent()))

    def test_enable_toggles_flag_and_rules_block(self):
        o = self.o
        rules = os.path.join(self.office("t1"), "RULES.md")
        on_text = self.read(rules)
        self.assertEqual(on_text.count("<!-- agencity:staff v1 -->"), 1)
        self.assertIn("## 직원 일꾼", on_text)
        with open(os.path.join(self.dir, "org.json"), encoding="utf-8") as f:
            self.assertIs(next(t for t in json.load(f)["teams"] if t["id"] == "t1")["staff"], True)
        self.hire()
        r = o.api_staff_enable({"team": "t1", "on": False})
        self.assertEqual((r["changed"], r["rules"]["removed"], r["told"]), (True, [], None))   # 직원이 남아 있어요: 팀장이 여전히 띄울 수 있어서 '직원 일꾼' 부분은 그대로
        self.assertEqual(self.read(rules), on_text)
        teams = {t["id"]: t for t in o.real_teams()}
        self.assertIs(o.staff_rules(teams["t1"]), True)
        self.assertIs(o.rules_outdated(o.floor_rules(teams["t1"], o.office_roots()), {k: v for k, (v, _) in o.rule_doc().items()}, o.staff_rules(teams["t1"])), False)
        with open(os.path.join(self.dir, "org.json"), encoding="utf-8") as f:
            self.assertNotIn("staff", next(t for t in json.load(f)["teams"] if t["id"] == "t1"))
        self.assertTrue(os.path.isfile(self.agent()))                                   # 끄면 '직원 들이기'만 숨겨요: 줄과 명찰은 그대로
        self.assertIn("작가", [m["role"] for m in self.team("t1")["members"]])
        self.refused(409, lambda: self.hire(role="편집", staff="ag-editor"))
        self.assertEqual(o.api_staff_enable({"team": "t1", "on": False})["changed"], False)
        for role in ("기획", "마케팅", "운영", "데이터"):                                   # 꺼진 층의 직원을 모두 퇴근시키면 마지막에 그 부분을 빼요
            r = o.api_staff_fire({"team": "t1", "role": role})
            self.assertEqual(r["rules"]["removed"], [])
        r = o.api_staff_fire({"team": "t1", "role": "작가"})
        self.assertEqual((r["rules"]["removed"], r["rules"]["backup"]), (["staff"], "RULES.md.bak"))
        off_text = self.read(rules)
        self.assertNotIn("agencity:staff", off_text)
        self.assertEqual(off_text, on_text[:on_text.index("\n<!-- agencity:staff")])         # 그 부분과 앞의 빈 줄만 빠져요
        self.assertEqual(self.read(rules + ".bak"), on_text)
        r = o.api_staff_enable({"team": "t1", "on": True})
        self.assertEqual((r["changed"], r["rules"]["appended"]), (True, ["staff"]))
        self.assertEqual(self.read(rules), on_text)
        for bad in ({"team": "t1", "on": "yes"}, {"team": "t1"}):
            self.refused(400, o.api_staff_enable, bad)
        self.refused(404, o.api_staff_enable, {"team": "없는층", "on": True})

    def test_rules_block_only_on_enabled_floors(self):
        o = self.o
        r = o.api_floor_rules_sync({"team": "t3"})                                       # 꺼진 층: 팀 간 대화·일 맡기기만 더해요
        self.assertEqual(r["appended"], ["team-talk", "handoff"])
        self.assertEqual(set(r["rules"]), {"team-talk", "handoff"})                       # 옛 층의 답 모양 그대로
        t3 = self.read(os.path.join(self.office("t3"), "RULES.md"))
        self.assertNotIn("agencity:staff", t3)
        self.assertEqual(o.api_floor_rules_sync({"team": "t3"})["changed"], False)
        teams = {t["id"]: t for t in o.real_teams()}
        roots = o.office_roots()
        cur = {k: v for k, (v, _) in o.rule_doc().items()}
        self.assertEqual(o.floor_rules(teams["t3"], roots), {"team-talk": 2, "handoff": 1})
        self.assertIs(o.rules_outdated(o.floor_rules(teams["t3"], roots), cur, False), False)
        self.assertEqual(o.floor_rules(teams["t1"], roots), {"team-talk": 2, "handoff": 1, "staff": 1})
        self.assertIs(o.rules_outdated(o.floor_rules(teams["t1"], roots), cur, True), False)
        self.assertIs(o.rules_outdated({"team-talk": 2, "handoff": 1, "staff": 1}, cur, False), True)   # 꺼진 층에 남은 부분은 빼야 해요
        self.assertIs(o.rules_outdated({"team-talk": 2, "handoff": 1}, cur, True), True)
        self.assertEqual((o.staff_on(teams["t2"]), o.staff_rules(teams["t2"]), o.staff_rules(teams["t3"])), (False, True, False))
        self.assertEqual(o.floor_rules(teams["t2"], roots), {"team-talk": None, "handoff": None, "staff": None})   # 꺼진 층이어도 직원 줄이 있으면 '직원 일꾼' 부분을 둬요
        self.assertEqual(o.api_floor_rules_sync({"team": "t2"})["appended"], ["team-talk", "handoff", "staff"])
        st = o.api_setup_state({})
        f1 = next(f for f in st["floors"] if f["id"] == "t1")
        f3 = next(f for f in st["floors"] if f["id"] == "t3")
        f2 = next(f for f in st["floors"] if f["id"] == "t2")
        self.assertEqual((f1["staffOn"], f1["outdated"]), (True, False))
        self.assertEqual((f2.get("staffOn"), f2["outdated"]), (None, False))
        self.assertEqual(f1["staffForm"]["skills"], {"floor": ["public-copy-check"], "personal": ["my-skill"]})
        self.assertEqual(f1["staffForm"]["defaultTools"], ["Read", "Grep", "Glob", "Write", "Edit"])
        self.assertNotIn("staffOn", f3)
        self.assertNotIn("staffForm", f3)
        crlf = "# 규칙\r\n"                                                              # 줄바꿈은 그 파일을 따라요(더하고 빼도 그대로)
        blocks = o.rule_doc("t1")
        on, appended, _, _ = o.sync_rules_text(crlf, blocks, True)
        self.assertEqual(appended, ["team-talk", "handoff", "staff"])
        off, _, _, removed = o.sync_rules_text(on, blocks, False)
        self.assertEqual((removed, off), (["staff"], o.sync_rules_text(crlf, blocks, False)[0]))
        self.assertTrue(off.endswith("<!-- /agencity:handoff -->\r\n"))

    def test_new_floor_rules_have_no_staff_block(self):
        proj = os.path.join(self.tmp, "proj", "nt9")
        shutil.rmtree(proj, ignore_errors=True)
        os.makedirs(proj)
        r = subprocess.run([sys.executable, "-I", os.path.join(self.dir, "bin", "new_team.py"), "--spec", "-"], cwd=self.dir,
                           input=json.dumps({"boss": None, "dropDemo": True, "floors": [{"id": "nt9", "name": "새층", "folder": proj,
                                                                                          "members": [{"role": "팀장", "sessionId": None}]}]}, ensure_ascii=False),
                           capture_output=True, text=True, env=dict(os.environ, **self.env), timeout=60)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(res["created"], res)
        text = self.read(os.path.join(proj, ".office", "RULES.md"))
        self.assertIn("<!-- /agencity:handoff -->\n", text)
        self.assertTrue(text.endswith("<!-- /agencity:handoff -->\n"))
        self.assertNotIn("agencity:staff", text)
        self.assertNotIn("직원 일꾼", text)

    def test_enable_tells_running_lead_once(self):
        """켜서 '직원 일꾼' 부분을 새로 넣으면 켜져 있는 팀장에게 RULES.md를 다시 읽으라고 한 번 알려요. 대표 말 꼴이 아니라 기존 자동 알림(위임 회의 넛지)과
        같은 '[사이트 알림]' 꼴이고 답 안내가 없어요. 팀장 대화에는 from '사이트'·kind '알림' 줄로 남아요.
        그 부분이 이미 있으면 다시 보내지 않고, 팀장 자리가 비었으면 보내지 않아요. 못 보내면 told: false와 까닭이에요."""
        o = self.o
        [it] = self.items()                                                             # setUp에서 켰어요
        chat = os.path.join(self.office("t1"), "chat", "팀장.jsonl")
        self.assertEqual((it["to"], it["thread"], it["label"]), (LEAD, chat, "층 · 팀장"))
        self.assertEqual(it["text"], "[사이트 알림] 층 RULES.md가 바뀌었어요. 사이트가 저절로 보내는 알림이에요(대표가 쓴 말은 아니에요).\n"
                                     f"{o.STAFF_RULES_TELL}\nRULES.md: {os.path.join(self.office('t1'), 'RULES.md')}")
        for word in ("[대표·사이트]", "바로 말 걸기", "say.sh", ".out/", o.NOTE):        # 대표가 쓴 말 꼴도, 답 안내도 아니에요
            self.assertNotIn(word, it["text"])
        with open(chat, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f.read().splitlines()]
        self.assertEqual([(x["from"], x["kind"], x["text"]) for x in lines], [("사이트", "알림", o.STAFF_RULES_SAID)])   # meeting_nudge_floor가 남기는 줄과 같은 꼴
        self.assertFalse(os.path.exists(os.path.join(self.office("t1"), "chat", ".out")))   # 답 파일 폴더도 만들지 않아요
        self.assertEqual(o.api_staff_enable({"team": "t1", "on": False})["told"], None)
        self.assertEqual(o.api_staff_enable({"team": "t1", "on": True})["told"], None)   # 직원이 남아 있어서 그 부분이 그대로였어요
        r = o.api_staff_enable({"team": "t2", "on": True})                              # 팀장 자리가 비었어요
        self.assertEqual((r["rules"]["appended"], r["told"]), (["team-talk", "handoff", "staff"], None))
        self.assertEqual(len(self.items()), 1)
        with mock.patch.object(o, "check_rate", side_effect=o.ApiError(429, "1분에 보낼 수 있는 양을 넘었어요")):
            r = o.api_staff_enable({"team": "t3", "on": True})
        self.assertEqual((r["ok"], r["changed"], r["told"], r["tellError"]), (True, True, False, "1분에 보낼 수 있는 양을 넘었어요"))
        self.assertIn("staff", r["rules"]["appended"])

    def test_real_git_repo_stays_clean(self):
        """진짜 git 저장소인 팀장 폴더: 들인 뒤 git status가 비어 있어요. 명찰과, 홈 아래 절대 경로를 가리키는 스킬 링크가 untracked로 남지 않아요.
        .claude/skills/ 통째로는 빼지 않아서 내 스킬은 그대로 보여요."""
        if not shutil.which("git"):
            self.skipTest("git이 없어요")
        shutil.rmtree(self.lead)
        os.makedirs(self.lead)
        env = dict(os.environ, HOME=self.env["HOME"], GIT_CONFIG_NOSYSTEM="1")
        git = lambda *a: subprocess.run(["git", "-C", self.lead, *a], check=True, env=env, capture_output=True, text=True).stdout
        git("init", "-q")
        r = self.hire()
        self.assertEqual(r["git"]["added"], [".claude/agents/ag-*.md", ".claude/skills/public-copy-check"])
        self.assertTrue(os.path.islink(os.path.join(self.lead, ".claude", "skills", "public-copy-check")))
        self.assertEqual(git("status", "--porcelain", "--untracked-files=all"), "")
        mine = os.path.join(self.lead, ".claude", "skills", "mine")
        os.makedirs(mine)
        with open(os.path.join(mine, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("내 스킬\n")
        self.assertEqual(git("status", "--porcelain", "--untracked-files=all").strip(), "?? .claude/skills/mine/SKILL.md")
        self.assertEqual(self.o.api_staff_rebuild({"team": "t1", "role": "작가"})["git"]["added"], [])   # 이미 있는 줄은 더하지 않아요

    def test_fire_without_lead_folder_stops_then_warns(self):
        """팀장 폴더를 못 찾으면 명찰을 옮길 수 없어서 409(why: lead)로 멈춰요. anyway면 줄만 빼고 left로 알려요.
        팀장 자리를 다른 폴더의 세션으로 바꿨으면 지금 팀장 폴더에 명찰이 없다고 알려요."""
        o = self.o
        self.hire()
        before = self.team_bytes("t1")
        self.session_record(NEW, self.lead)                                             # Claude 앱 세션 기록에 팀장이 없어요
        e = self.refused(409, o.api_staff_fire, {"team": "t1", "role": "작가"})
        self.assertEqual(e.extra["why"], "lead")
        self.assertIn("팀장이 아직 이 일꾼을 띄울 수 있어요", e.msg)
        self.assertEqual(self.team_bytes("t1"), before)
        r = o.api_staff_fire({"team": "t1", "role": "작가", "anyway": True})
        self.assertIsNone(r["retired"])
        self.assertIn("명찰(.claude/agents/ag-writer.md)을 옮기지 못했어요", r["left"])
        self.assertTrue(os.path.isfile(self.agent()))                                   # 명찰은 남아 있어요(그래서 알려요)
        self.assertNotIn("작가", [m["role"] for m in self.team("t1")["members"]])
        self.session_record(LEAD, self.lead)
        self.hire(role="편집", staff="ag-editor", skills=[])
        other = os.path.join(self.tmp, "lead2")
        shutil.rmtree(other, ignore_errors=True)
        os.makedirs(other)
        self.session_record(LEAD, other)                                                # 팀장 자리를 다른 폴더의 세션으로 바꿨어요
        r = o.api_staff_fire({"team": "t1", "role": "편집"})
        self.assertIsNone(r["retired"])
        self.assertIn("예전 폴더의 .claude/agents/ag-editor.md가 남아 있을 수 있어요", r["left"])
        self.assertTrue(os.path.isfile(self.agent("ag-editor")))
        rows = self.team("t1")["members"]
        rows[0]["sessionId"] = None                                                     # 팀장 자리가 비었어요
        with open(os.path.join(self.office("t1"), "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "층", "members": rows}, f, ensure_ascii=False)
        r = o.api_staff_fire({"team": "t1", "role": "기획"})                            # 막지 않고 줄만 빼요(명찰을 둘 팀장 폴더가 없어요)
        self.assertEqual((r["retired"], r["left"]), (None, "팀장 자리가 비어 있어서 명찰은 옮기지 않았어요(예전 팀장 폴더에 남아 있을 수 있어요)"))
        self.assertNotIn("기획", [m["role"] for m in self.team("t1")["members"]])
        self.assertIsNone(o.api_staff_fire({"team": "t1", "role": "운영"})["left"])      # 이름 꼴이 틀린 직원은 명찰이 없어서 그대로 빼요

    def test_fire_on_floor_without_lead(self):
        """팀장 자리가 빈 층(t2): 들이기도 팀장이 없으면 막아서 이 층에서 지은 명찰이 없어요. 409로 막지 않고 줄만 빼고, 명찰은 옮기지 않았다고 left로 알려요.
        팀장 세션은 있는데 그 폴더를 못 찾을 때의 409·anyway는 그대로예요(test_fire_without_lead_folder_stops_then_warns)."""
        o = self.o
        lead_chat = os.path.join(self.office("t2"), "chat", "팀장.jsonl")
        r = o.api_staff_fire({"team": "t2", "role": "기획"})
        self.assertEqual((r["ok"], r["role"], r["staff"], r["retired"]), (True, "기획", "ag-planner", None))
        self.assertEqual(r["left"], "팀장 자리가 비어 있어서 명찰은 옮기지 않았어요(예전 팀장 폴더에 남아 있을 수 있어요)")
        self.assertEqual(self.team("t2")["members"], [{"role": "팀장", "sessionId": None}])
        self.assertTrue(r["kept"].endswith(os.path.join("staff", "ag-planner")))
        self.assertFalse(os.path.exists(lead_chat))
        self.refused(404, o.api_staff_fire, {"team": "t2", "role": "기획"})              # 한 번만 빠져요
        with open(os.path.join(self.office("t2"), "log.jsonl"), encoding="utf-8") as f:
            self.assertIn("팀장 자리가 비어 명찰은 옮기지 않았어요", f.read().splitlines()[-1])   # 결과 글(left)과 같은 뜻으로 남겨요

    def test_exclude_is_written_inside_team_lock(self):
        """들이기·다시 만들기는 info/exclude를 TEAM_LOCK 안에서(들이기는 team.json을 쓴 뒤) 써요. 규칙 줄 넣기(api_floor_link_rules)가 같은 파일을
        같은 잠금 안에서 읽고 바꿔치기해서, 겹치면 한쪽 줄이 사라져요. exclude_agents는 다른 잠금을 잡지 않아서 잠금 안에서 불러도 멈추지 않아요.
        worktree의 commondir가 FIFO여도 열지 않아서 잠금을 쥔 채 기다리지 않아요."""
        o = self.o
        seen, real = [], o.exclude_agents

        def spy(*a, **k):
            seen.append((o.TEAM_LOCK.locked(), "작가" in [m.get("role") for m in self.team("t1")["members"]]))
            return real(*a, **k)

        with mock.patch.object(o, "exclude_agents", spy):
            r = self.hire()
            b = o.api_staff_rebuild({"team": "t1", "role": "작가"})
        self.assertEqual(seen, [(True, True), (True, True)])                              # 잠금 안이고, 들이기는 team.json을 쓴 뒤예요
        self.assertFalse(o.TEAM_LOCK.locked())                                            # 끝나면 풀려요
        self.assertEqual((r["git"]["added"], b["git"]["added"]), ([".claude/agents/ag-*.md", ".claude/skills/public-copy-check"], []))
        wt, gd = os.path.join(self.tmp, "wt-lead"), os.path.join(self.tmp, "wt-gitdir")
        for d in (wt, gd):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        with open(os.path.join(wt, ".git"), "w", encoding="utf-8") as f:
            f.write(f"gitdir: {gd}\n")
        os.mkfifo(os.path.join(gd, "commondir"))
        got = []
        th = threading.Thread(target=lambda: got.append(o.git_dirs(wt)), daemon=True)
        th.start()
        th.join(2)
        self.assertEqual(got, [(wt, gd)])                                                 # FIFO commondir는 건너뛰고 gitdir 그대로예요

    def test_floor_word_does_not_double(self):
        """'<층 이름> 층'을 만드는 새 글: 층 이름이 이미 '층'으로 끝나면 '층'을 또 붙이지 않아요(명찰 첫 줄 '너는 시험층 직원 …')."""
        o = self.o
        self.assertEqual([o.floor_word(x) for x in ("시험층", "3층", "옛 층", "층", "알파", "층 사무실")],
                         ["시험층", "3층", "옛 층", "층", "알파 층", "층 사무실 층"])
        self.hire()
        base, path = self.office("t1"), os.path.join(self.dir, "org.json")
        cur = json.loads(self.read(path))
        for name, head in (("시험층", "너는 시험층 직원 '작가'의 일꾼이에요."), ("3층", "너는 3층 직원 '작가'의 일꾼이에요."), ("알파", "너는 알파 층 직원 '작가'의 일꾼이에요.")):
            cur["teams"][0]["name"] = name
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False)
            body = o.staff_agent_text(base, "ag-writer").split("\n---\n", 1)[1]
            self.assertTrue(body.startswith(head + " "), body[:60])
            self.assertNotIn("층 층", body)

    def test_staff_rules_block_permission_line(self):
        """'직원 일꾼' 장의 권한 질문 줄은 세션이 지킬 수 있는 말이에요(일꾼의 권한 질문은 팀장 창에 떠서 대표가 정해요). 서버가 층 RULES.md에 넣는 장(rule_doc)은
        docs/TEAM_RULES.md의 그 장과 글자째 같아요(서버 RULE_BLOCKS에는 이름과 이름표만 있고 글은 없어요). 표지는 아직 v1이에요.
        대표에게 하는 말(거절, 세션 동안 허락은 고르지 않기)은 GUIDE의 직원 스킬 절에 있어요."""
        o = self.o
        doc = self.read(os.path.join(self.dir, "docs", "TEAM_RULES.md"))
        new = "- 일꾼이 띄운 권한 질문은 팀장 창에 떠서 대표가 정해요. 팀장도 일꾼도 그 허락을 1장 승인으로 쓰지 않아요.\n"
        a, b = doc.index("<!-- agencity:staff v1 -->"), doc.index("<!-- /agencity:staff -->") + len("<!-- /agencity:staff -->")
        block = doc[a:b]
        self.assertIn(new, block)
        for gone in ("거절해요", "세션 동안 허락", "일꾼 질문에는"):
            self.assertNotIn(gone, block)
        self.assertEqual(o.rule_doc()["staff"], (1, block))
        self.assertEqual(dict(o.RULE_BLOCKS)["staff"], "직원 일꾼")
        self.assertNotIn("일꾼 질문에는", self.read(os.path.join(self.dir, "office_server.py")))
        self.assertIn(new, self.read(os.path.join(self.office("t1"), "RULES.md")))       # setUp에서 켜며 넣은 장도 같은 줄이에요
        self.assertIn("팀장 창에 뜬 일꾼의 권한 질문이 1장 일이면 거절하고, 세션 동안 허락은 고르지 않아요",
                      self.read(os.path.join(self.dir, "docs", "GUIDE.md")))

    def test_rebuild_asks_before_widening(self):
        """SKILL.md는 일꾼도 고칠 수 있어요. 다시 만들 명찰이 서버가 마지막으로 지은 명찰보다 도구를 늘리거나 모델을 바꾸면 confirm 없이는 409(why: widen)예요.
        줄이기만 하면 묻지 않아요."""
        base = self.office("t1")
        self.hire()
        skill = os.path.join(base, "staff", "ag-writer", "SKILL.md")
        orig, agent = self.read(skill), self.read(self.agent())
        with open(skill, "w", encoding="utf-8") as f:
            f.write(orig.replace("tools: [Read, Write, Edit]", "tools: [Read, Write, Edit, Bash, WebFetch]"))
        self.assertEqual(self.info()["agent"], "바뀜")
        e = self.refused(409, self.o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.assertEqual((e.extra["why"], e.extra["add"], e.extra["wide"], e.extra["model"]), ("widen", ["Bash", "WebFetch"], ["Bash", "WebFetch"], None))
        self.assertIn("도구가 늘어요(Bash, WebFetch)", e.msg)
        self.assertEqual(self.read(self.agent()), agent)                                # 확인 전에는 명찰을 고치지 않아요
        self.assertIs(e.extra["again"], False)
        self.o.api_staff_rebuild({"team": "t1", "role": "작가", "confirm": True, "expect": {"tools": e.extra["tools"], "model": e.extra["model"]}})
        self.assertIn("\ntools: Read, Write, Edit, Bash, WebFetch\n", self.read(self.agent()))
        self.assertEqual(self.info()["agent"], "ok")
        with open(skill, "w", encoding="utf-8") as f:
            f.write(orig.replace("model: sonnet", "model: haiku"))                        # 도구는 줄고 모델이 바뀌어요
        e = self.refused(409, self.o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.assertEqual((e.extra["add"], e.extra["model"]), ([], ["sonnet", "haiku"]))
        self.assertIn("모델이 바뀌어요(sonnet → haiku)", e.msg)
        with open(skill, "w", encoding="utf-8") as f:
            f.write(orig)                                                               # 줄이기만: 묻지 않아요
        self.o.api_staff_rebuild({"team": "t1", "role": "작가"})
        self.assertEqual(self.read(self.agent()), agent)
        os.remove(self.o.STAFF_RECORD)                                                  # 기록이 없으면 기본 도구(Bash 없이)·inherit과 견줘요
        e = self.refused(409, self.o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.assertEqual((e.extra["add"], e.extra["model"]), ([], ["inherit", "sonnet"]))

    def test_forged_hash_and_hand_widened_agent(self):
        """일꾼이 SKILL.md·명찰·.agent.sha256을 함께 고쳐도 설정 폴더의 기록과 달라서 '바뀜'이고, 다시 만들기는 늘어난 도구를 물어요.
        명찰만 고쳐 도구를 더하면 정보의 agent_tools에 실제로 일꾼이 받는 도구가 보이고(agent_diff), 다시 만들기는 묻지 않고 줄여요."""
        o = self.o
        base = self.office("t1")
        self.hire()
        sdir = os.path.join(base, "staff", "ag-writer")
        skill = os.path.join(sdir, "SKILL.md")
        orig, agent = self.read(skill), self.read(self.agent())
        with open(skill, "w", encoding="utf-8") as f:
            f.write(orig.replace("tools: [Read, Write, Edit]", "tools: [Read, Write, Edit, Bash]"))
        text = o.staff_agent_text(base, "ag-writer")
        with open(self.agent(), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(sdir, ".agent.sha256"), "w", encoding="utf-8") as f:
            f.write(hashlib.sha256(text.encode("utf-8")).hexdigest() + "\n")
        info = self.info()
        self.assertEqual((info["agent"], info["tools"], info["agent_tools"], info["agent_diff"]), ("바뀜", ["Read", "Write", "Edit", "Bash"], ["Read", "Write", "Edit", "Bash"], False))
        self.assertEqual(self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가"}).extra["add"], ["Bash"])
        with open(skill, "w", encoding="utf-8") as f:
            f.write(orig)
        with open(self.agent(), "w", encoding="utf-8") as f:
            f.write(agent.replace("tools: Read, Write, Edit\n", "tools: Read, Write, Edit, Bash\nmodel: opus\n").replace("model: sonnet\n", ""))   # 명찰만 고쳤어요
        info = self.info()
        self.assertEqual((info["agent"], info["tools"], info["agent_tools"], info["agent_model"], info["agent_diff"]),
                         ("바뀜", ["Read", "Write", "Edit"], ["Read", "Write", "Edit", "Bash"], "opus", True))
        with open(self.agent(), "w", encoding="utf-8") as f:
            f.write(agent.replace("tools: Read, Write, Edit\n", ""))                     # tools 줄이 없으면 일꾼이 모든 도구를 받아요
        self.assertEqual((self.info()["agent_tools"], self.info()["agent_diff"]), (["*"], True))
        o.api_staff_rebuild({"team": "t1", "role": "작가"})                               # SKILL.md는 그대로라 묻지 않고 되돌려요
        self.assertEqual(self.read(self.agent()), agent)
        self.assertEqual((self.info()["agent"], self.info()["agent_diff"]), ("ok", False))

    def sessions(self, cwd_of):
        """Claude 앱 세션 기록을 여러 개 써요({세션 id: cwd}). session_record는 하나만 남겨요."""
        d = os.path.join(self.o.SESSIONS_DIR, "acct", "org")
        shutil.rmtree(os.path.dirname(d), ignore_errors=True)
        os.makedirs(d)
        for sid, cwd in cwd_of.items():
            with open(os.path.join(d, sid + ".json"), "w", encoding="utf-8") as f:
                json.dump({"sessionId": sid, "cwd": cwd, "title": "팀장 창", "lastActivityAt": int(time.time() * 1000)}, f, ensure_ascii=False)
        self.o.staff_forget()

    def quick(self, fn, fifos, limit=1.0):
        """fn()이 limit초 안에 끝나야 해요. 끝나지 않으면(FIFO를 읽다 멈췄어요) 그 FIFO를 쓰기로 열고 닫아 풀어 준 뒤 실패로 알려요."""
        box = {}

        def run():
            try:
                box["v"] = fn()
            except BaseException as e:  # noqa: BLE001  시험 스레드의 예외는 부른 쪽에서 다시 던져요
                box["e"] = e
        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(limit)
        if th.is_alive():
            for p in fifos:
                try:
                    os.close(os.open(p, os.O_WRONLY | os.O_NONBLOCK))
                except OSError:
                    pass
            th.join(5)
            self.fail(f"{limit}초 안에 끝나지 않았어요(FIFO에서 멈췄어요): {fifos}")
        if "e" in box:
            raise box["e"]
        return box["v"]

    def fifo(self, p):
        os.remove(p)
        os.mkfifo(p)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "mkfifo가 없어요")
    def test_fifo_does_not_hang_staff_info(self):
        """명찰·.agent.sha256·SKILL.md·팀장 세션 기록이 FIFO여도(Bash가 있는 팀장이나 일꾼이 만들 수 있어요) staff_info가 STAFF_INFO_LOCK을 쥔 채 멈추지 않아요.
        읽지 못한 명찰은 '바뀜'이고, 다음 staff_info도 잠금에서 막히지 않아요. 다시 만들기·퇴근도 TEAM_LOCK을 쥔 채 멈추지 않고, FIFO 명찰은 덮거나 옮기지 않아요."""
        o = self.o
        base = self.office("t1")
        self.hire()
        sdir = os.path.join(base, "staff", "ag-writer")
        agent, sha = self.read(self.agent()), os.path.join(sdir, ".agent.sha256")
        self.fifo(self.agent())                                                          # 명찰이 FIFO
        info = self.quick(self.info, [self.agent()])
        self.assertEqual((info["agent"], info["agent_tools"]), ("바뀜", None))
        self.assertEqual(self.quick(self.info, [self.agent()])["agent"], "바뀜")         # 잠금이 풀려 있어요
        e = self.quick(lambda: self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가"}), [self.agent()])
        self.assertEqual(e.extra["why"], "other")                                        # 무엇인지 모르는 것은 덮지 않아요
        os.remove(self.agent())
        with open(self.agent(), "w", encoding="utf-8") as f:
            f.write(agent)
        self.assertEqual(self.info()["agent"], "ok")
        good = self.read(sha)
        self.fifo(sha)                                                                   # .agent.sha256이 FIFO
        self.assertEqual(self.quick(self.info, [sha])["agent"], "바뀜")
        os.remove(sha)
        with open(sha, "w", encoding="utf-8") as f:
            f.write(good)
        skill = os.path.join(sdir, "SKILL.md")
        text = self.read(skill)
        self.fifo(skill)                                                                 # SKILL.md가 FIFO
        info = self.quick(self.info, [skill])
        self.assertIn("SKILL.md", info["error"])
        self.assertEqual(self.quick(lambda: self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가"}), [skill]).extra["why"], "skill")
        with mock.patch.object(o.os.path, "isfile", return_value=True), mock.patch.object(o.os.path, "getsize", return_value=10):
            with self.assertRaises(ValueError):                                          # 본 뒤에 FIFO로 바뀌어도(본 때와 읽는 때 사이) 멈추지 않아요
                self.quick(lambda: o.staff_skill(base, "ag-writer"), [skill])
        os.remove(skill)
        with open(skill, "w", encoding="utf-8") as f:
            f.write(text)
        rec = os.path.join(o.SESSIONS_DIR, "acct", "org", LEAD + ".json")
        self.fifo(rec)                                                                   # 팀장 세션 기록이 FIFO: 다른 기록도 FIFO는 건너뛰어요
        self.assertEqual(self.quick(self.info, [rec])["agent"], "없음")
        self.assertIsNone(self.quick(lambda: o.lead_folder(LEAD), [rec]))
        self.assertNotIn(LEAD, [s["sessionId"] for s in self.quick(lambda: o.claude_sessions(True), [rec])])
        self.session_record(LEAD, self.lead)
        self.fifo(self.agent())
        r = self.quick(lambda: o.api_staff_fire({"team": "t1", "role": "작가"}), [self.agent()])
        self.assertIsNone(r["retired"])
        self.assertIn("이 층이 지은 명찰이 아니에요", r["left"])
        self.assertFalse(os.path.lexists(os.path.join(sdir, "retired")))
        self.assertTrue(stat.S_ISFIFO(os.lstat(self.agent()).st_mode))

    def test_read_small(self):
        """작은 파일 읽기: 없으면 None, 일반 파일만(링크·FIFO·폴더는 ValueError), limit보다 크면 ValueError, limit까지는 그대로예요."""
        o = self.o
        d = os.path.join(self.tmp, "small")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        p = os.path.join(d, "a")
        with open(p, "wb") as f:
            f.write(b"x" * 10)
        self.assertEqual(o.read_small(p, 10), b"x" * 10)
        with self.assertRaises(ValueError):
            o.read_small(p, 9)
        self.assertIsNone(o.read_small(os.path.join(d, "없음"), 10))
        self.assertIsNone(o.read_small(os.path.join(p, "아래"), 10))                    # 위가 파일이에요
        os.symlink(p, os.path.join(d, "링크"))
        for bad in (os.path.join(d, "링크"), d):
            with self.assertRaises(ValueError):
                o.read_small(bad, 10)
        if hasattr(os, "mkfifo"):
            os.mkfifo(os.path.join(d, "f"))
            with self.assertRaises(ValueError):
                self.quick(lambda: o.read_small(os.path.join(d, "f"), 10), [os.path.join(d, "f")])
        self.assertIsNone(o.session_json(os.path.join(d, "링크")))
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"sessionId": "깨진')
        self.assertIsNone(o.session_json(p))                                             # 깨진 기록은 넘어가요
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"sessionId": "x"}')
        self.assertEqual(o.session_json(p), {"sessionId": "x"})

    def test_rebuild_confirm_is_tied_to_what_was_shown(self):
        """확인(confirm: true)은 확인 창에 보인 409의 tools·model(expect)과 묶여요. 확인하는 사이에 SKILL.md가 더 넓어지면(도구가 더 늘고 모델이 바뀌면)
        다시 409(again)로 새 차이를 보이고 명찰은 그대로예요. expect 없는 confirm, 모양이 틀린 confirm·expect도 확인이 아니에요."""
        o = self.o
        base = self.office("t1")
        self.hire()
        skill = os.path.join(base, "staff", "ag-writer", "SKILL.md")
        orig, agent = self.read(skill), self.read(self.agent())
        with open(skill, "w", encoding="utf-8") as f:
            f.write(orig.replace("tools: [Read, Write, Edit]", "tools: [Read, Write, Edit, Bash]"))
        first = self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가"}).extra
        self.assertEqual((first["add"], first["model"], first["tools"], first["again"]), (["Bash"], None, ["Read", "Write", "Edit", "Bash"], False))
        shown = {"tools": first["tools"], "model": first["model"]}                      # 대표는 'Bash가 늘어요'만 봤어요
        with open(skill, "w", encoding="utf-8") as f:                                     # 확인 창이 뜬 사이에 일꾼이 더 넓혔어요
            f.write(orig.replace("tools: [Read, Write, Edit]", "tools: [Read, Write, Edit, Bash, WebFetch, WebSearch]").replace("model: sonnet", "model: opus"))
        e = self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가", "confirm": True, "expect": shown})
        self.assertEqual((e.extra["why"], e.extra["again"], e.extra["add"], e.extra["model"]), ("widen", True, ["Bash", "WebFetch", "WebSearch"], ["sonnet", "opus"]))
        self.assertIn("확인하는 사이에 직원 스킬(SKILL.md)이 또 바뀌었어요", e.msg)
        self.assertEqual(self.read(self.agent()), agent)                                 # 대표가 본 것보다 넓은 명찰은 쓰지 않아요
        now = {"tools": e.extra["tools"], "model": e.extra["model"]}
        for bad in ({"confirm": True}, {"confirm": True, "expect": None}, {"confirm": True, "expect": [now]}, {"confirm": "true", "expect": now},
                    {"confirm": 1, "expect": now}, {"confirm": True, "expect": {"tools": now["tools"]}}, {"confirm": True, "expect": {"tools": now["tools"][:-1], "model": now["model"]}},
                    {"confirm": True, "expect": {"tools": now["tools"], "model": ["sonnet", "haiku"]}}, {"expect": now}):
            self.assertEqual(self.refused(409, o.api_staff_rebuild, dict(bad, team="t1", role="작가")).extra["why"], "widen", bad)
        self.assertEqual(self.read(self.agent()), agent)
        o.api_staff_rebuild({"team": "t1", "role": "작가", "confirm": True, "expect": now})   # 새 차이를 보고 확인했어요
        self.assertIn("\ntools: Read, Write, Edit, Bash, WebFetch, WebSearch\nmodel: opus\n", self.read(self.agent()))
        self.assertEqual(self.info()["agent"], "ok")

    def test_two_floors_in_one_lead_folder(self):
        """두 층의 팀장이 같은 폴더에서 일해요(편집기가 허락하는 구성). 1층 팀장 자리를 3층 팀장 폴더에서 일하는 세션으로 바꿔도, 1층의 다시 만들기는
        3층 명찰을 덮지 않고(409 why: other, confirm이 있어도) 퇴근은 옮기지 않아요(left). 손으로 만든 명찰도 덮지 않고, 손으로 고친 이 층 명찰은 다시 만들어요."""
        o = self.o
        b = os.path.join(self.tmp, "leadB")
        shutil.rmtree(b, ignore_errors=True)
        os.makedirs(b)
        self.sessions({LEAD: self.lead, LEAD3: b, NEW: b})
        self.hire()                                                                      # 1층: 폴더 A에 ag-writer(Read·Write·Edit, sonnet)
        o.api_staff_enable({"team": "t3", "on": True})
        o.api_staff_hire({"team": "t3", "role": "작가", "staff": "ag-writer", "desc": "3층 작가", "work": "3층 글을 써요.", "tools": ["Read"], "model": "haiku", "skills": []})
        theirs_p = os.path.join(b, ".claude", "agents", "ag-writer.md")
        theirs = self.read(theirs_p)
        o.staff_forget()
        self.assertEqual((o.staff_info()["t1"]["작가"]["agent"], o.staff_info()["t3"]["작가"]["agent"]), ("ok", "ok"))
        rows = self.team("t1")["members"]
        rows[0]["sessionId"] = NEW                                                       # 대표가 1층 팀장 자리를 폴더 B의 다른 세션으로 바꿨어요
        with open(os.path.join(self.office("t1"), "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "층", "members": rows}, f, ensure_ascii=False)
        o.staff_forget()
        self.assertEqual(o.staff_info()["t1"]["작가"]["agent"], "바뀜")
        e = self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.assertEqual(e.extra["why"], "other")
        self.assertIn("다른 층(또는 손으로 만든) 명찰이 이미 있어요", e.msg)
        self.assertIn("덮지 않았어요", e.msg)
        self.assertEqual(self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가", "confirm": True,
                                                                  "expect": {"tools": ["Read", "Write", "Edit"], "model": None}}).extra["why"], "other")
        self.assertEqual(self.read(theirs_p), theirs)                                    # 3층 일꾼이 1층 도구·모델·기억을 받지 않아요
        self.assertFalse(os.path.lexists(os.path.join(b, ".claude", "skills")))          # 1층 스킬 링크도 걸지 않았어요
        o.staff_forget()
        t3 = o.staff_info()["t3"]["작가"]
        self.assertEqual((t3["agent"], t3["agent_tools"], t3["agent_model"]), ("ok", ["Read"], "haiku"))
        r = o.api_staff_fire({"team": "t1", "role": "작가"})
        self.assertIsNone(r["retired"])
        self.assertIn("이 층이 지은 명찰이 아니에요", r["left"])
        self.assertIn("예전 폴더의 .claude/agents/ag-writer.md가 남아 있을 수 있어요", r["left"])
        self.assertEqual(self.read(theirs_p), theirs)                                    # 3층 명찰을 1층 retired/로 옮기지 않아요
        self.assertFalse(os.path.lexists(os.path.join(self.office("t1"), "staff", "ag-writer", "retired")))
        self.assertNotIn("작가", [m["role"] for m in self.team("t1")["members"]])
        self.assertTrue(os.path.isfile(self.agent()))                                    # 폴더 A의 1층 명찰은 그대로예요(그래서 left로 알려요)
        o.staff_forget()
        self.assertEqual(o.staff_info()["t3"]["작가"]["agent"], "ok")
        with open(theirs_p, "w", encoding="utf-8") as f:                                  # 손으로 만든 명찰(기록과 다르고 3층 기억.md 경로도 없어요)
            f.write("---\nname: ag-writer\ndescription: 손\ntools: Read, Bash\n---\n손으로 만든 명찰\n")
        hand = self.read(theirs_p)
        self.assertEqual(self.refused(409, o.api_staff_rebuild, {"team": "t3", "role": "작가"}).extra["why"], "other")
        self.assertEqual(self.read(theirs_p), hand)
        with open(theirs_p, "w", encoding="utf-8") as f:
            f.write(theirs + "손으로 더한 줄\n")                                            # 3층 명찰을 손으로 고쳤어요(3층 기억.md 경로가 있어요)
        o.api_staff_rebuild({"team": "t3", "role": "작가"})
        self.assertEqual(self.read(theirs_p), theirs)
        os.remove(o.STAFF_RECORD)                                                        # 기록이 없어도 본문의 기억.md 경로로 이 층 것을 알아요
        o.api_staff_rebuild({"team": "t3", "role": "작가", "confirm": True, "expect": {"tools": ["Read"], "model": ["inherit", "haiku"]}})
        self.assertEqual(self.read(theirs_p), theirs)

    def test_enable_off_tells_remaining_staff_not_on(self):
        """끌 때 RULES.md에 '직원 일꾼' 장이 없었으면(손으로 지웠거나 켤 때 맞추지 못했어요) 남은 직원 때문에 그 장을 넣고, 팀장에게는 '켰어요'가 아니라
        남은 직원이 있어서 넣었다고 알려요. 그 장이 그대로면 다시 보내지 않아요."""
        o = self.o
        chat = os.path.join(self.office("t1"), "chat", "팀장.jsonl")
        with open(os.path.join(self.office("t1"), "RULES.md"), "w", encoding="utf-8") as f:
            f.write("# 규칙\n")                                                            # 그 장을 손으로 지웠어요
        r = o.api_staff_enable({"team": "t1", "on": False})
        self.assertEqual((r["changed"], r["told"]), (True, True))
        self.assertIn("staff", r["rules"]["appended"])
        texts = [it["text"] for it in self.items()]
        self.assertEqual(sum(o.STAFF_RULES_TELL in x for x in texts), 1)                 # 켤 때(setUp) 한 번뿐이에요
        self.assertEqual(sum(o.STAFF_RULES_TELL_OFF in x for x in texts), 1)
        self.assertNotIn("켰어요", o.STAFF_RULES_TELL_OFF)
        self.assertIn("껐지만 남은 직원이 있어서", o.STAFF_RULES_TELL_OFF)
        off = next(x for x in texts if o.STAFF_RULES_TELL_OFF in x)
        self.assertTrue(off.startswith("[사이트 알림] 층 RULES.md가 바뀌었어요. 사이트가 저절로 보내는 알림이에요(대표가 쓴 말은 아니에요).\n"), off)
        self.assertNotIn("[대표·사이트]", off)
        with open(chat, encoding="utf-8") as f:
            last = json.loads(f.read().splitlines()[-1])
        self.assertEqual((last["from"], last["kind"], last["text"]), ("사이트", "알림", o.STAFF_RULES_SAID_OFF))   # 팀장 대화에 남는 줄도 끌 때의 말이에요
        self.assertNotIn("켰어요", o.STAFF_RULES_SAID_OFF)
        self.assertIsNone(o.api_staff_enable({"team": "t1", "on": False})["told"])

    def test_deep_lists_do_not_break_staff_info(self):
        """SKILL.md에 깊이 겹친 목록이 있어도 RecursionError가 나지 않아요: 그 직원만 error이고 다른 직원과 다른 층은 그대로, 다시 만들기는 409예요."""
        o = self.o
        base = self.office("t1")
        self.hire()
        self.hire(role="편집", staff="ag-editor", skills=[])
        skill = os.path.join(base, "staff", "ag-writer", "SKILL.md")
        deep = self.read(skill).replace("tools: [Read, Write, Edit]", "tools: " + "[" * 3000 + "Read" + "]" * 3000)
        with open(skill, "w", encoding="utf-8") as f:
            f.write(deep)
        o.staff_forget()
        info = o.staff_info()
        self.assertIn("목록 안에 목록이 있어요", info["t1"]["작가"]["error"])
        self.assertEqual(info["t1"]["편집"]["agent"], "ok")
        self.assertIn("t2", info)
        e = self.refused(409, o.api_staff_rebuild, {"team": "t1", "role": "작가"})
        self.assertEqual(e.extra["why"], "skill")
        with self.assertRaises(ValueError):
            o.yaml_scalar("[[a], b]")
        with self.assertRaises(ValueError):
            o.front_matter("---\ntools:\n  - [Read]\n---\n")
        self.assertEqual(o.yaml_scalar("[a, b]"), ["a", "b"])
        with mock.patch.object(o, "staff_one", side_effect=RuntimeError("깨짐")):         # 무엇이 깨져도 직원마다 따로 알려요
            o.staff_forget()
            bad = o.staff_info()
        self.assertEqual(bad["t1"]["작가"]["error"], "직원 정보를 읽지 못했어요(RuntimeError)")
        self.assertEqual(bad["t1"]["작가"]["staff"], "ag-writer")

    def test_front_matter_shapes(self):
        o = self.o
        doc = ("---\nname: ag-x\ndescription: >\n  여러 줄\n  설명이에요\noffice:\n  role: '기획'\n  tools:\n    - Read\n    - Grep   # 주석\n"
               "  model: haiku\n  skills:\n  - a-b\nextra:\n- 1\n---\n본문\n---\n둘째\n")
        front, body = o.front_matter(doc)
        self.assertEqual(front, {"name": "ag-x", "description": "여러 줄 설명이에요", "office": {"role": "기획", "tools": ["Read", "Grep"], "model": "haiku", "skills": ["a-b"]},
                                 "extra": ["1"]})
        self.assertEqual(body, "본문\n---\n둘째\n")
        self.assertEqual(o.front_matter('---\ndescription: "a: \\"b\\""\nk: |\n  줄1\n  줄2\n---\n')[0], {"description": 'a: "b"', "k": "줄1\n줄2"})
        for bad in ("없음", "---\nname: x\n", "---\n\tname: x\n---\n", "---\n- x\n---\n", "---\nname\n---\n", "---\na:\n    b: 1\n  c: 2\n---\n"):
            with self.assertRaises(ValueError, msg=bad):
                o.front_matter(bad)
        for s, want in (("글", "글"), ("a: b", '"a: b"'), ("- x", '"- x"'), ("true", '"true"'), ("12", '"12"'), ("x #y", '"x #y"'), ("[a]", '"[a]"')):
            self.assertEqual(o.yaml_text(s), want)
            self.assertEqual(o.yaml_scalar(o.yaml_text(s)), s)


class Server(unittest.TestCase):
    """서버를 켜고 사진 올리기와 /api/state를 봐요(9700번대 포트)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix="agencity-u31-srv-", dir=TMP_BASE))
        cls.dir, env = make_install(cls.tmp)
        reset_floors(cls.dir)
        subprocess.run([sys.executable, "-I", "build.py"], cwd=cls.dir, check=True, capture_output=True)
        cls.run_dir = env["AGENCITY_CLAUDE_RUN_DIR"]
        cls.projects = env["AGENCITY_CLAUDE_PROJECTS_DIR"]
        cls.port = free_port(9700, 9799)
        full = {k: v for k, v in os.environ.items() if not k.upper().startswith(("AGENCITY_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"))}
        full.update(env, OFFICE_PORT=str(cls.port))
        code = "import sys; sys.path.insert(0, '.'); import office_server as o; o.MAX_PER_MIN = 10 ** 6; o.MAX_PENDING = 10 ** 6; o.main()"
        cls.proc = subprocess.Popen([sys.executable, "-I", "-c", code], cwd=cls.dir, env=full, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.token = None
        for _ in range(100):
            try:
                cls.token = re.search(r"const TOKEN = '([A-Za-z0-9_-]{20,})'", cls.fetch("/")[1].decode("utf-8")).group(1)
                break
            except (OSError, http.client.HTTPException, AttributeError):
                time.sleep(.1)
        if not cls.token:
            raise RuntimeError("서버가 켜지지 않았어요")
        cls.sleepers = [subprocess.Popen(["sleep", "300"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(2)]

    @classmethod
    def tearDownClass(cls):
        for s in cls.sleepers:
            s.kill()
            s.wait()
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def fetch(cls, path, method="GET", body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=20)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def png(self):
        import struct
        import zlib

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        raw = (b"\0" + b"\x10\x20\x30" * 2) * 2
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

    def up(self, team, thread):
        q = urllib.parse.urlencode({"team": team, "thread": thread})
        status, raw = self.fetch("/api/image?" + q, "POST", self.png(),
                                 {"Origin": self.base, "X-Office-Token": self.token, "Content-Type": "application/octet-stream"})
        return status, json.loads(raw.decode("utf-8"))

    def post(self, path, body):
        status, raw = self.fetch(path, "POST", json.dumps(body).encode("utf-8"),
                                 {"Origin": self.base, "X-Office-Token": self.token, "Content-Type": "application/json"})
        return status, json.loads(raw.decode("utf-8"))

    def items(self):
        box = os.path.join(self.dir, "outbox")
        out = []
        for n in sorted(os.listdir(box)) if os.path.isdir(box) else []:
            if n.endswith(".json"):
                with open(os.path.join(box, n), encoding="utf-8") as f:
                    out.append(json.load(f))
                os.remove(os.path.join(box, n))
        return out

    def pics(self, tid):
        d = os.path.join(self.dir, "teams", tid, "chat-images")
        return sorted(n for n in os.listdir(d) if n != ".gitignore") if os.path.isdir(d) else []

    def test_image_to_staff(self):
        status, j = self.up("t1", "chat:기획")
        self.assertEqual(status, 200, j)
        self.assertEqual(self.pics("t1"), [j["id"]])
        status, r = self.post("/api/say", {"team": "t1", "thread": "chat:기획", "text": "이 사진", "images": [j["id"]]})
        self.assertEqual(status, 200, r)
        [it] = self.items()
        self.assertEqual(it["to"], LEAD)
        self.assertIn("(직원 ag-planner) 바로 말 걸기 · 사진 1장", it["text"])
        self.assertIn(os.path.join(os.path.realpath(os.path.join(self.dir, "teams", "t1")), "chat-images", j["id"]), it["text"])

    def test_image_to_staff_without_lead(self):
        status, j = self.up("t2", "chat:기획")
        self.assertEqual((status, j.get("error")), (409, NO_LEAD))
        self.assertEqual(self.pics("t2"), [])                                            # 자리가 없으면 파일을 만들지 않아요
        status, j = self.post("/api/say", {"team": "t2", "thread": "chat:기획", "text": "안녕"})
        self.assertEqual((status, j.get("error")), (409, NO_LEAD))
        status, j = self.post("/api/seat/link", {"team": "t1", "role": "기획"})
        self.assertEqual((status, j.get("error")), (409, NO_SEAT))

    def test_state_live_skips_staff_and_old_floor_is_same(self):
        now = int(time.time() * 1000)
        for p, host in zip(self.sleepers, (LEAD3, STRAY)):
            with open(os.path.join(self.run_dir, f"{p.pid}.json"), "w", encoding="utf-8") as f:
                json.dump({"pid": p.pid, "hostSessionId": host, "status": "busy", "statusUpdatedAt": now - 1000, "startedAt": now - 600000}, f)
        try:
            status, raw = self.fetch("/api/state")
            self.assertEqual(status, 200)
            state = json.loads(raw.decode("utf-8"))
            live = state["live"]
            self.assertEqual(set(live), {"t1", "t2", "t3"})
            self.assertEqual(set(live["t3"]), {"팀장"})
            self.assertEqual(set(live["t3"]["팀장"]), {"s", "since"})                    # 옛 층의 모양 그대로
            self.assertEqual(live["t3"]["팀장"]["s"], "busy")
            self.assertEqual(set(live["t1"]), {"기획", "마케팅", "데이터"})              # 세션 자리는 pid 파일이 없고, 이름 꼴이 틀린 직원(운영)은 신호가 없어요
            for tid in ("t1", "t2"):
                for x in live[tid].values():
                    self.assertEqual((x["staff"], x["s"], x["n"]), (True, "idle", 0))   # 직원 줄에 잘못 적힌 세션(STRAY)이 일해도 그 직원은 대기예요
            self.assertEqual(set(state["staff"]), {"t1", "t2"})                          # 직원 정보는 직원 줄이 있는 층만
        finally:
            for n in os.listdir(self.run_dir):
                os.remove(os.path.join(self.run_dir, n))

    def test_staff_posts_need_origin_and_token(self):
        body = json.dumps({"team": "t3", "on": True}).encode("utf-8")
        for headers in ({"Content-Type": "application/json", "X-Office-Token": self.token},
                        {"Content-Type": "application/json", "Origin": self.base, "X-Office-Token": "틀린 열쇠".encode("utf-8").hex()},
                        {"Content-Type": "application/json", "Origin": "http://127.0.0.1:9", "X-Office-Token": self.token}):
            for path in ("/api/staff/enable", "/api/staff/hire", "/api/staff/fire", "/api/staff/rebuild"):
                status, _ = self.fetch(path, "POST", body, headers)
                self.assertEqual(status, 403, (path, headers))
        with open(os.path.join(self.dir, "org.json"), encoding="utf-8") as f:
            self.assertNotIn("staff", next(t for t in json.load(f)["teams"] if t["id"] == "t3"))
        self.items()
        status, j = self.post("/api/staff/enable", {"team": "t3", "on": True})
        self.assertEqual((status, j["on"], j["changed"], j["told"]), (200, True, True, True), j)
        [it] = self.items()                                                             # 켜져 있는 팀장에게 RULES.md를 다시 읽으라고 한 번
        self.assertEqual(it["to"], LEAD3)
        self.assertIn("[규칙] RULES.md를 다시 읽어 주세요", it["text"])
        status, j = self.post("/api/staff/enable", {"team": "t3", "on": False})
        self.assertEqual((status, j["changed"]), (200, True), j)
        status, j = self.post("/api/staff/hire", {"team": "t3", "role": "작가", "staff": "ag-writer", "desc": "글", "work": "글", "tools": ["Read"]})
        self.assertEqual((status, j.get("why")), (409, "off"), j)

    def test_state_signal_keeps_descriptions_out(self):
        """서버를 거쳐도 일꾼 기록의 작업 설명·글은 답과 status 파일에 나오지 않아요. 일하는 직원은 live에 busy로 나와요."""
        now = int(time.time() * 1000)
        p = self.sleepers[0]
        with open(os.path.join(self.run_dir, f"{p.pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": p.pid, "hostSessionId": LEAD, "status": "idle", "statusUpdatedAt": now - 900000, "startedAt": now - 990000,
                       "sessionId": CLI, "cwd": "/private/tmp/비밀폴더표시"}, f, ensure_ascii=False)
        sub = os.path.join(self.projects, "-proj", CLI, "subagents")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "agent-s1.meta.json"), "w", encoding="utf-8") as f:
            json.dump({"agentType": "ag-planner", "description": SECRET_DESC}, f, ensure_ascii=False)
        with open(os.path.join(sub, "agent-s1.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"message": SECRET_DESC}, ensure_ascii=False) + "\n")
        try:
            status, raw = self.fetch("/api/state")
            body = raw.decode("utf-8")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["live"]["t1"]["기획"], {"s": "busy", "since": mock.ANY, "staff": True, "n": 1})
            for word in (SECRET_DESC, "비밀폴더표시", CLI):
                self.assertNotIn(word, body)
            with open(os.path.join(self.dir, "teams", "t1", "status", "기획.json"), encoding="utf-8") as f:
                st = f.read()
            self.assertEqual(json.loads(st)["state"], "일하는 중")
            self.assertNotIn(SECRET_DESC, st)
        finally:
            for n in os.listdir(self.run_dir):
                os.remove(os.path.join(self.run_dir, n))
            shutil.rmtree(os.path.dirname(os.path.dirname(sub)), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
