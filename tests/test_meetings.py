"""회의 정리 시험: 오래 조용한 위임 회의를 팀장에게 한 번 알리기(office_server.meeting_nudge).

python3 -m unittest tests/test_meetings.py -v      (저장소 맨 위에서)

office_server.py를 임시 폴더(/private/tmp 아래)에 복사해 그 폴더를 설치 폴더로 써요. 진짜 사무실(~/agencity)은 건드리지 않아요.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TMP_BASE = "/private/tmp" if os.path.isdir("/private/tmp") else None
LEAD = "local_aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class MeetingNudge(unittest.TestCase):
    def setUp(self):
        self.here = os.path.realpath(tempfile.mkdtemp(prefix="meetnudge-", dir=TMP_BASE))
        shutil.copy(os.path.join(ROOT, "office_server.py"), self.here)
        self.office = os.path.join(self.here, "teams", "t1")
        os.makedirs(os.path.join(self.office, "meetings"))
        with open(os.path.join(self.here, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"boss": {"sessionId": "local_00000000-0000-0000-0000-000000000000"},
                       "teams": [{"id": "t1", "name": "시험팀", "office": "teams/t1"}]}, f, ensure_ascii=False)
        with open(os.path.join(self.office, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "시험팀", "members": [{"role": "팀장", "sessionId": LEAD}]}, f, ensure_ascii=False)
        sys.path.insert(0, self.here)
        try:
            import office_server
        finally:
            sys.path.remove(self.here)
        self.srv = office_server
        sys.modules.pop("office_server", None)

    def tearDown(self):
        shutil.rmtree(self.here, ignore_errors=True)

    def meeting(self, mid, status="진행 중", mode="위임", quiet=3600):
        meta = os.path.join(self.office, "meetings", mid + ".json")
        chat = os.path.join(self.office, "meetings", mid + ".chat.jsonl")
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"id": mid, "topic": "정리", "status": status, "mode": mode, "participants": ["팀장"]}, f, ensure_ascii=False)
        with open(chat, "w", encoding="utf-8") as f:
            f.write(json.dumps({"t": "2026-10-27T17:01:31+09:00", "from": "대표", "kind": "퇴장", "text": "대표가 회의에서 빠졌어요."}, ensure_ascii=False) + "\n")
        old = time.time() - quiet
        os.utime(chat, (old, old))
        os.utime(meta, (old, old))
        return meta, chat

    def outbox(self):
        d = os.path.join(self.here, "outbox")
        items = []
        for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if n.endswith(".json"):
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    items.append(json.load(f))
        return items

    def test_quiet_delegated_meeting_nudges_lead_once(self):
        meta, chat = self.meeting("20261027-M-1")
        self.assertEqual(self.srv.meeting_nudge(), ["20261027-M-1"])
        items = self.outbox()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["to"], LEAD)
        self.assertTrue(items[0]["text"].startswith("[사이트 알림] 위임 회의 20261027-M-1"))
        self.assertIn("회의 끝 순서", items[0]["text"])
        with open(meta, encoding="utf-8") as f:
            self.assertTrue(json.load(f).get("nudged"))
        with open(chat, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read().splitlines()[-1])["kind"], "알림")
        self.assertEqual(self.srv.meeting_nudge(time.time() + 7200), [])   # 회의마다 한 번이에요
        self.assertEqual(len(self.outbox()), 1)

    def test_skips_active_attended_closing_and_fresh(self):
        self.meeting("20261027-M-2", mode="참석")           # 대표가 있는 회의
        self.meeting("20261027-M-3", status="정리 중")       # 대표가 끝낸 회의(정리는 [내가 닫기]로)
        self.meeting("20261027-M-4", quiet=60)              # 막 이야기한 위임 회의
        self.assertEqual(self.srv.meeting_nudge(), [])
        self.assertEqual(self.outbox(), [])

    def test_opinion_files_and_status_count_as_activity(self):
        # 위임 회의 의견은 meetings/<번호>/<역할>.md로 받아요. 거기나 참석자 status가 막 바뀌었으면 조용한 게 아니에요
        self.meeting("20261027-M-6")
        d = os.path.join(self.office, "meetings", "20261027-M-6")
        os.makedirs(d)
        with open(os.path.join(d, "개발자.md"), "w", encoding="utf-8") as f:
            f.write("의견")
        self.assertEqual(self.srv.meeting_nudge(), [])
        old = time.time() - 3600
        os.utime(os.path.join(d, "개발자.md"), (old, old))
        os.makedirs(os.path.join(self.office, "status"))
        with open(os.path.join(self.office, "status", "팀장.json"), "w", encoding="utf-8") as f:
            json.dump({"state": "회의 중"}, f, ensure_ascii=False)
        self.assertEqual(self.srv.meeting_nudge(), [])

    def test_broken_floor_does_not_stop_others(self):
        os.makedirs(os.path.join(self.here, "teams", "t0"))
        with open(os.path.join(self.here, "teams", "t0", "team.json"), "w") as f:
            json.dump([], f)   # 모양이 깨진 층
        with open(os.path.join(self.here, "org.json"), "w", encoding="utf-8") as f:
            json.dump({"teams": [{"id": "t0", "name": "깨짐", "office": "teams/t0"}, {"id": "t1", "name": "시험팀", "office": "teams/t1"}]}, f, ensure_ascii=False)
        self.meeting("20261027-M-7")
        self.assertEqual(self.srv.meeting_nudge(), ["20261027-M-7"])

    def test_sleep_time_is_not_quiet_time(self):
        self.meeting("20261027-M-8")
        self.srv.MEET_AWAKE[0] = time.time() - 60   # 1분 전에 깼어요
        self.assertEqual(self.srv.meeting_nudge(), [])
        self.assertEqual(self.srv.meeting_nudge(time.time() + 1800), ["20261027-M-8"])

    def test_no_lead_no_nudge(self):
        with open(os.path.join(self.office, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"team": "시험팀", "members": []}, f)
        self.meeting("20261027-M-5")
        self.assertEqual(self.srv.meeting_nudge(), [])


if __name__ == "__main__":
    unittest.main()
