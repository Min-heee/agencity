"""최근 사용량 세기 — 설정의 ‘사용량 알림’이 써요. 서버(office_server.py)가 따로 띄우고 결과(JSON 한 줄)만 받아요.

python3 -I -B bin/usage_meter.py            # 내 최근 사용량 요약(기억 파일 없이 처음부터 세요. 아무것도 쓰지 않아요)
python3 -I -B bin/usage_meter.py --count    # 서버용: 표준 입력 {"roots", "floors": [{"id", "folder"}], "cache"} → 표준 출력 JSON

세는 규칙은 bin/token_meter.py(token-meter collect.mjs를 옮긴 것) 그대로예요. Claude는 한 응답을 message.id로 접고(스냅샷은 칸마다
최대값, resume·fork 복사본도 한 번), Codex는 세션 누적값의 양수 델타, Gemini는 같은 id는 교체·$set·$rewindTo예요.
다른 건 기간뿐이에요: 최근 5시간, 오늘(이 맥 시간대의 자정부터), 이번 주(ISO 주, 월요일 자정부터). 서머타임이 바뀌는 날에도
자정은 그날 처음 오는 시각이에요. 작업량은 도시 건물과 같아요: 총 토큰 − 캐시 읽기 + 캐시 읽기 × 0.1.
token_meter와 일부러 다른 것: 시각을 못 읽은 기록은 기간에 넣지 않아요. Codex에서 NaN이 되는 줄은 그 줄만 빼요(collect.mjs는 Codex를
통째로 빼요). Codex 세션의 앞 파일(이름에 같은 세션 id)을 기간 전에 고쳐서 열지 않았으면, 직전 누적값을 몰라 그 세션의 첫 줄은
last_token_usage만큼만 세요(그 전 누적을 통째로 오늘 것으로 세지 않게).

층별: 기록의 작업 폴더(Claude 줄의 cwd, 없으면 프로젝트 폴더 이름, Codex session_meta의 cwd, Gemini는 tmp/<폴더 해시>)가
층 폴더 안이면 그 층이에요. 층 폴더가 겹치면(한 층 폴더 안에 다른 층 폴더) 가장 깊은 층이에요.

읽는 것: 세 도구 로그의 토큰 수·시각·응답/세션 id·작업 폴더뿐이에요. 대화 글은 꺼내지 않고 남기지 않아요. 아무것도 올리지 않아요.
가장 이른 기간 시작(이번 주 월요일이나 5시간 전) 전에 고친 파일은 열지 않아요. 크기·고친 시각이 그대로인 파일은 다시 읽지 않고,
뒤에 덧붙기만 한 Claude·Codex .jsonl은 덧붙은 곳부터 읽어요(줄 끝까지 쓴 줄만 세요. 쓰는 중인 줄은 다음에).
그 기억(파일마다 크기·시각, 기간 안 기록의 숫자·id·작업 폴더)은 서버가 정한 기억 파일(설치 폴더의 .usage/cache.json, 0600) 하나에만 둬요.
"""
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_V = 1
CACHE_MAX = 64 * 1024 * 1024   # 기억 파일이 이보다 크면 버리고 새로 세요
WINDOWS = ("h5", "day", "week")
TOOLS = ("claude", "codex", "gemini")
H5 = 5 * 3600
AHEAD = 600   # 이보다 미래 시각의 기록은 세지 않아요(시계가 틀린 기록)
FP = 64       # 덧붙기만 했는지 볼 때 견주는 바이트(지난번에 읽은 곳 바로 앞)
CACHE_RATE = 0.1   # 작업량: 캐시 읽기는 10분의 1로(city.html의 workOf와 같아요)


def _load_tm():
    """bin/token_meter.py를 읽어요(-I로 켜서 이 폴더가 import 경로에 없어요)."""
    spec = importlib.util.spec_from_file_location("agencity_token_meter", os.path.join(HERE, "token_meter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tm = _load_tm()
_loads, _OBJ, _NOGET, _UNDEF = tm._loads, tm._OBJ, tm._NOGET, tm._UNDEF
_num, _tonum, _get, _truthy = tm._num, tm._tonum, tm._get, tm._truthy


# ── 기간 ────────────────────────────────────────────────────────────────
def _ymd(t):
    lt = time.localtime(t)
    return lt.tm_year, lt.tm_mon, lt.tm_mday


def day_start(d):
    """이 맥 시간대에서 날짜 d(date)가 시작하는 시각(초). 서머타임으로 자정이 없거나 두 번 와도 그날 처음 오는 시각이에요."""
    want = (d.year, d.month, d.day)
    hi = int(time.mktime((d.year, d.month, d.day, 12, 0, 0, 0, 0, -1)))   # 낮 12시는 거의 늘 있어요
    while _ymd(hi) < want:
        hi += 3600
    lo = hi - 48 * 3600   # 이틀 전 낮은 늘 그 전날이에요
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _ymd(mid) >= want:
            hi = mid
        else:
            lo = mid
    return hi


def windows(now):
    """{h5: 5시간 전, day: 오늘 자정, week: 이번 주 월요일 자정} (초)."""
    today = date(*_ymd(now))
    return {"h5": now - H5, "day": float(day_start(today)), "week": float(day_start(today - timedelta(days=today.weekday())))}


def _ts(v):
    """기록 시각(초, 정수). token_meter와 같은 날짜 읽기(ISO 글, ms 숫자). 못 읽으면 None."""
    t = type(v)
    if t is str:
        ms = tm._parse_date(v)
    elif t is float:
        ms = v
    else:
        return None
    if ms is None or ms != ms or abs(ms) > 8.64e15:
        return None
    return int(ms // 1000)


# ── 작은 도우미 ────────────────────────────────────────────────────────
def _k(v, where):
    """token_meter._key(Map·Set 열쇠)를 JSON에 둘 수 있는 글로. 글은 그대로, 객체·배열은 그 줄마다 다른 열쇠예요."""
    t = type(v)
    if t is str:
        return v
    if t is float:
        return "\0n" + repr(v + 0.0)   # -0과 0은 같은 열쇠
    if t is bool:
        return "\0b1" if v else "\0b0"
    if v is None:
        return "\0z"
    return "\0o" + where


def _c(v):
    """숫자를 짧게(정수인 실수는 정수로). 유한하지 않으면 None."""
    if type(v) is not float or v - v != 0:
        return None
    return int(v) if v.is_integer() and abs(v) < 2 ** 53 else v


def _idx(cws, c):
    try:
        return cws.index(c)
    except ValueError:
        cws.append(c)
        return len(cws) - 1


def _fp(path, end):
    """end 바로 앞 FP바이트의 지문. 못 읽으면 None."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, end - FP))
            return hashlib.sha1(f.read(min(FP, end))).hexdigest()[:16]
    except OSError:
        return None


def _lines(f, pos, st):
    """열린 파일의 지금 자리부터 줄 끝(\\n)까지 쓴 줄만 (그 줄이 시작한 바이트, 줄). 쓰는 중인 마지막 줄은 다음에 읽어요."""
    for raw in f:
        if not raw.endswith(b"\n"):
            return
        st["bytes"] += len(raw)
        yield pos, raw
        pos += len(raw)


# ── Claude Code ─────────────────────────────────────────────────────────
def _claude_feed(e, f, path, pos, floor, st):
    """token_meter._claude의 줄 거르기 그대로. e["r"]: 응답 열쇠 → [시각, input, output, write5m, write1h, read, 작업 폴더 번호]."""
    recs, cws, fb = e["r"], e["cw"], e["fb"]
    end = pos
    for at, raw in _lines(f, pos, st):
        end = at + len(raw)
        if b'"usage"' not in raw:
            continue
        try:
            d = _loads(raw.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            continue
        m = d.get("message") if type(d) is dict else None
        u = m.get("usage") if type(m) is dict else None
        if type(u) not in _OBJ:
            continue
        model, err = m.get("model"), d.get("isApiErrorMessage")
        if not (model or type(model) in _OBJ) or model == "<synthetic>" or err or type(err) in _OBJ:
            continue
        rid = m.get("id")
        if not (rid or type(rid) in _OBJ):
            rid = d.get("requestId")
        if not (rid or type(rid) in _OBJ):
            rid = d.get("uuid")
        if not (rid or type(rid) in _OBJ):
            continue
        ug = u.get if type(u) is dict else _NOGET
        cc = ug("cache_creation")
        cg = cc.get if type(cc) is dict else _NOGET
        w1h, w5m = _num(cg("ephemeral_1h_input_tokens")), _num(cg("ephemeral_5m_input_tokens"))
        vals = (_num(ug("input_tokens")), _num(ug("output_tokens")),
                w5m if w1h + w5m > 0 else _num(ug("cache_creation_input_tokens")), w1h, _num(ug("cache_read_input_tokens")))
        k = _k(rid, f"{path}:{at}")
        prev = recs.get(k)
        if prev is None:
            ts = _ts(d.get("timestamp", _UNDEF))
            if ts is None or ts < floor:
                continue   # 기간 전 기록(resume 복사본 포함)은 남기지 않아요
            cwd = d.get("cwd")
            recs[k] = [ts] + [_c(v) for v in vals] + [_idx(cws, cwd if type(cwd) is str and cwd else fb)]
            continue
        for i, v in enumerate(vals, 1):   # 스트리밍 스냅샷: 합이 아니라 칸마다 최대값
            if v > prev[i]:
                prev[i] = _c(v)
    return end


# ── Codex ───────────────────────────────────────────────────────────────
_TT = ("input_tokens", "cached_input_tokens", "output_tokens")


def _codex_feed(e, f, path, pos, st):
    """token_meter._codex의 줄 거르기 그대로. e["e"]: ["m", 세션 열쇠, 작업 폴더 번호] 또는 ["t", 시각, 누적 in·cached·out, last 셋 또는 None].
    델타는 모을 때(_sum) 파일 순서대로 다시 셈해요(세션이 여러 파일에 걸치면 직전값을 이어받아요)."""
    ev, cws = e["e"], e["cw"]
    sid, ci = e["sid"], e["ci"]
    end = pos
    for at, raw in _lines(f, pos, st):
        end = at + len(raw)
        if not tm._CODEX_WANT.search(raw):
            continue
        try:
            d = _loads(raw.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            continue
        p = d.get("payload") if type(d) is dict else None
        if type(p) not in _OBJ:
            continue
        pg = p.get if type(p) is dict else _NOGET
        dt = d.get("type")
        if dt == "session_meta":
            pid = pg("id")
            if pid or type(pid) in _OBJ:
                sid = _k(pid, f"{path}:{at}")
            cwd = pg("cwd")
            ci = _idx(cws, cwd) if type(cwd) is str and cwd else -1
            ev.append(["m", sid, ci])
            continue
        pm = pg("model")
        if dt == "turn_context" and (pm or type(pm) in _OBJ):
            continue
        pt = pg("type")
        if pt == "agent_message":
            continue
        info = pg("info")
        if pt != "token_count" or not (info or type(info) in _OBJ):
            continue
        ig = info.get if type(info) is dict else _NOGET
        tt, lt = ig("total_token_usage"), ig("last_token_usage")
        if not (tt or type(tt) in _OBJ):
            continue
        tg = tt.get if type(tt) is dict else _NOGET
        last = [_c(_tonum(lt.get(k, _UNDEF))) for k in _TT] if type(lt) is dict else None
        ev.append(["t", _ts(d.get("timestamp", _UNDEF))] + [_c(_tonum(tg(k, _UNDEF))) for k in _TT] + [last])
    e["sid"], e["ci"] = sid, ci
    return end


# ── Gemini CLI ──────────────────────────────────────────────────────────
def _gem_rec(m):
    """token_meter._gem_one과 같은 거르기: (시각, input − cached, cached, output + thoughts) 또는 None(셈에 안 들어가는 메시지)."""
    tk = m.get("tokens", _UNDEF)
    if m.get("type") != "gemini" or type(tk) not in _OBJ:
        return None
    raw_in = _num(_get(tk, "input"))
    cached = min(_num(_get(tk, "cached")), raw_in)
    out = _num(_get(tk, "output")) + _num(_get(tk, "thoughts"))
    if raw_in + out == 0:
        return None
    return _ts(m.get("timestamp", _UNDEF)), raw_in - cached, cached, out


def _gemini_file(path, floor, hdir):
    """token_meter._gemini의 파일 하나 → [세션 열쇠, kind, fmt, 메시지가 있었는지, [[시각, input, cached, output], …], 층 표시]."""
    sid, kind, msgs, phash = None, "main", {}, None
    is_jsonl = path.endswith(".jsonl")
    if is_jsonl:
        for rec in tm._jsonl(path, loads=tm._loads_gem):
            if type(rec) is not dict:
                continue
            rid = rec.get("id", _UNDEF)
            if _truthy(rec.get("sessionId")) and _truthy(rec.get("projectHash")) and not _truthy(rid):
                sid, kind = rec["sessionId"], rec["kind"] if _truthy(rec.get("kind")) else "main"
                phash = rec["projectHash"] if type(rec["projectHash"]) is str else phash
                continue
            stv = rec.get("$set", _UNDEF)
            if _truthy(stv):
                ms = _get(stv, "messages")
                if type(ms) is list:
                    msgs.clear()
                    for m in ms:
                        if _truthy(_get(m, "id")):
                            msgs[tm._key(m["id"])] = _gem_rec(m)
                continue
            rw = rec.get("$rewindTo", _UNDEF)
            if _truthy(rw):
                k = tm._key(rw)
                if k in msgs:
                    ks = list(msgs)
                    for kk in ks[ks.index(k):]:
                        del msgs[kk]
                continue
            if _truthy(rid):
                msgs[tm._key(rid)] = _gem_rec(rec)
    else:
        doc = tm._read_doc(path, tm._loads_gem)
        if type(doc) is not dict or type(doc.get("messages")) is not list:
            return None
        sid = doc["sessionId"] if _truthy(doc.get("sessionId")) else path
        kind = doc["kind"] if _truthy(doc.get("kind")) else "main"
        if type(doc.get("projectHash")) is str:
            phash = doc["projectHash"]
        for m in doc["messages"]:
            if _truthy(_get(m, "id")):
                msgs[tm._key(m["id"])] = _gem_rec(m)
    recs = [[r[0]] + [_c(x) for x in r[1:]] for r in msgs.values() if r is not None and r[0] is not None and r[0] >= floor]
    return [_k(sid if _truthy(sid) else path, path), kind if isinstance(kind, str) else "main", "jsonl" if is_jsonl else "json",
            bool(msgs), recs, "\0gem:" + (phash or hdir)]


# ── 층 ──────────────────────────────────────────────────────────────────
def _under(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


class _Floors:
    """작업 폴더(또는 Claude 프로젝트 폴더 이름·Gemini 폴더 해시) → 층 id. 겹치면 가장 깊은 층(실제 경로가 가장 긴 층)."""

    def __init__(self, floors):
        self.fl, self.enc, self.gem, self.memo = [], {}, {}, {}
        for f in floors if isinstance(floors, list) else []:
            fid, folder = (f.get("id"), f.get("folder")) if isinstance(f, dict) else (None, None)
            if not isinstance(fid, str) or not fid or not isinstance(folder, str) or not folder.strip():
                continue
            p = os.path.expanduser(folder)
            try:
                real = os.path.realpath(p)
            except (OSError, ValueError):
                continue
            if not os.path.isabs(p):
                continue
            vs, depth = sorted({os.path.normpath(p), real}), len(real)
            self.fl.append((fid, vs, depth))
            for v in vs:   # Claude는 폴더의 글자·숫자 말고는 모두 '-'로 바꾼 이름, Gemini는 폴더 경로의 sha256
                for table, key in ((self.enc, re.sub(r"[^A-Za-z0-9]", "-", v)), (self.gem, hashlib.sha256(v.encode("utf-8", "surrogatepass")).hexdigest())):
                    if key not in table or depth > table[key][0]:
                        table[key] = (depth, fid)

    def __call__(self, mark):
        if mark in self.memo:
            return self.memo[mark]
        r = None
        if mark.startswith("\0enc:") or mark.startswith("\0gem:"):
            x = (self.enc if mark[1] == "e" else self.gem).get(mark[5:])
            r = x[1] if x else None
        elif mark and os.path.isabs(mark):
            cands, best = {os.path.normpath(mark)}, -1
            try:
                cands.add(os.path.realpath(mark))
            except (OSError, ValueError):
                pass
            for fid, vs, depth in self.fl:
                if depth > best and any(_under(c, v) for c in cands for v in vs):
                    best, r = depth, fid
        if len(self.memo) < 100000:
            self.memo[mark] = r
        return r


# ── 파일 목록 ───────────────────────────────────────────────────────────
def _files(roots):
    """(도구, 루트, [파일…]) — token_meter와 같은 곳·같은 순서."""
    base = tm.default_roots()
    r = {t: tm._norm((roots or {}).get(t) or base[t]) for t in TOOLS}
    cx = [f for d in ("sessions", "archived_sessions") for f in tm._walk(os.path.join(r["codex"], d), (".jsonl",))
          if os.path.basename(f).startswith("rollout-")]
    cx.sort(key=lambda s: s.encode("utf-16-be", "surrogatepass"))   # JS sort(): UTF-16 순
    gm = [f for f in tm._walk(os.path.join(r["gemini"], "tmp"), (".jsonl", ".json")) if "chats" in f.split(os.sep)]
    return [("claude", r["claude"], tm._walk(r["claude"], (".jsonl",))), ("codex", r["codex"], cx),
            ("gemini", os.path.join(r["gemini"], "tmp"), gm)]


def _first_dir(path, root):
    rel = os.path.relpath(path, root)
    return rel.split(os.sep, 1)[0] if rel and not rel.startswith("..") else ""


def _update(tool, root, path, s, e, floor, st):
    """파일 하나의 기억을 새로 해요. 그대로면 읽지 않고, 덧붙기만 했으면 덧붙은 곳부터, 아니면 처음부터 읽어요."""
    same = type(e) is dict and e.get("t") == tool and e.get("i") == s.st_ino and e.get("d") == s.st_dev
    if same and e.get("s") == s.st_size and e.get("m") == s.st_mtime_ns:
        st["same"] += 1
        return e
    if tool == "gemini":
        st["full"] += 1
        st["bytes"] += s.st_size
        g = _gemini_file(path, floor, _first_dir(path, root))
        return None if g is None else {"t": tool, "i": s.st_ino, "d": s.st_dev, "s": s.st_size, "m": s.st_mtime_ns, "g": g}
    o = e.get("o") if same else None
    tail = isinstance(o, int) and 0 < o <= s.st_size and e.get("fp") is not None and _fp(path, o) == e["fp"]
    if not tail:
        o = 0
        e = {"t": tool, "i": s.st_ino, "d": s.st_dev, "cw": []}
        if tool == "claude":
            e.update(r={}, fb="\0enc:" + _first_dir(path, root))
        else:
            e.update(e=[], sid=os.path.basename(path), ci=-1)
    st["tail" if tail else "full"] += 1
    try:
        with open(path, "rb") as f:
            f.seek(o)
            end = _claude_feed(e, f, path, o, floor, st) if tool == "claude" else _codex_feed(e, f, path, o, st)
    except OSError:
        return None
    e.update(s=s.st_size, m=s.st_mtime_ns, o=end, fp=_fp(path, end) if end else None)
    return e


def _prune(e, floor):
    """기간 전 기록은 기억에서 빼요(Codex는 누적값을 이어받아야 해서 그대로 둬요)."""
    if e["t"] == "claude":
        e["r"] = {k: r for k, r in e["r"].items() if r[0] >= floor}
    elif e["t"] == "gemini":
        e["g"][4] = [r for r in e["g"][4] if r[0] >= floor]


# ── 모으기 ──────────────────────────────────────────────────────────────
def _sum(files, wins, now, floors, gone=frozenset()):
    """기억(파일 순서대로)을 기간·도구·층별 작업량으로 모아요. gone: 열지 않은(기간 전에 고친) Codex 파일 이름의 세션 id들."""
    tot = {w: {"work": 0.0, "tools": {t: 0.0 for t in TOOLS}} for w in WINDOWS}
    per = {}

    def add(ts, tool, work, mark):
        if ts is None or ts > now + AHEAD or not work > 0:
            return
        fid = False
        for w in WINDOWS:
            if ts >= wins[w]:
                tot[w]["work"] += work
                tot[w]["tools"][tool] += work
                if fid is False:
                    fid = floors(mark) if mark else None
                if fid:
                    per.setdefault(fid, {x: 0.0 for x in WINDOWS})[w] += work

    # Claude: 응답 열쇠는 모든 파일에 걸쳐 한 번(먼저 나온 파일의 시각·폴더, 칸마다 최대값)
    seen = {}
    for e in files["claude"]:
        cws = e["cw"]
        for k, r in e["r"].items():
            p = seen.get(k)
            if p is None:
                seen[k] = r[:6] + [cws[r[6]] if 0 <= r[6] < len(cws) else ""]
            else:
                for i in range(1, 6):
                    if r[i] > p[i]:
                        p[i] = r[i]
    for ts, inp, out, w5, w1, rd, mark in seen.values():
        add(ts, "claude", inp + out + w5 + w1 + rd * CACHE_RATE, mark)

    # Codex: 파일 순서대로 세션 누적값의 델타(token_meter와 같아요). 그 세션의 앞 파일을 열지 않아 직전값을 모를 때만 last_token_usage만큼
    prev_by = {}
    for e in files["codex"]:
        cws, sid, mark, prev = e["cw"], os.path.basename(e["path"]), "", None
        for ev in e["e"]:
            if ev[0] == "m":
                sid, mark, prev = ev[1], cws[ev[2]] if 0 <= ev[2] < len(cws) else "", prev_by.get(ev[1])
                continue
            ts, cur, last = ev[1], ev[2:5], ev[5]
            base = prev
            if base is None:
                base = (0, 0, 0)
                if sid in gone and last and all(isinstance(x, (int, float)) for x in last) and all(isinstance(x, (int, float)) for x in cur) \
                        and all(0 <= b <= a for a, b in zip(cur, last)):
                    base = tuple(a - b for a, b in zip(cur, last))
            prev = prev_by[sid] = cur
            if any(x is None for x in cur) or any(x is None for x in base):
                continue   # NaN이 되는 줄은 그 줄만 빼요
            d_in, d_ca, d_out = cur[0] - base[0], cur[1] - base[1], cur[2] - base[2]
            if d_in < 0 or d_out < 0 or (d_in == 0 and d_out == 0):
                continue
            cached = max(0, min(d_ca, d_in))
            add(ts, "codex", d_in - cached + d_out + cached * CACHE_RATE, mark)

    # Gemini: 같은 세션은 나중 파일이 이기고, 같은 세션의 .jsonl이 있으면 .json은 빼요
    sess = {}
    for e in files["gemini"]:
        key, kind, fmt, has, recs, mark = e["g"]
        if not has:
            continue
        p = sess.get(key)
        if p is not None and p[0] == "jsonl" and fmt != "jsonl":
            continue
        sess[key] = (fmt, recs, mark)
    for _, recs, mark in sess.values():
        for ts, inp, cached, out in recs:
            add(ts, "gemini", inp + out + cached * CACHE_RATE, mark)

    r = lambda v: int(round(v))  # noqa: E731
    return ({w: {"from": int(wins[w]), "work": r(tot[w]["work"]), "tools": {t: r(v) for t, v in tot[w]["tools"].items()}} for w in WINDOWS},
            {fid: {w: r(v) for w, v in x.items()} for fid, x in per.items()})


# ── 기억 파일 ───────────────────────────────────────────────────────────
def _load_cache(path, floor):
    try:
        if os.path.islink(path) or os.path.getsize(path) > CACHE_MAX:
            return {}
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(c, dict) or c.get("v") != CACHE_V or not isinstance(c.get("files"), dict):
        return {}
    fl = c.get("floor")
    if not isinstance(fl, (int, float)) or floor < fl - 1:
        return {}   # 기간 시작이 앞으로 갔어요(시계·시간대가 바뀜): 기억에 없는 기록이 있을 수 있어 처음부터 세요
    return c["files"]


def _save_cache(path, files, floor):
    d = os.path.dirname(path)
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            return
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"v": CACHE_V, "floor": floor, "files": files}, f, separators=(",", ":"))
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── 세기 ────────────────────────────────────────────────────────────────
def count(roots=None, floors=None, cache=None, now=None, alive=None):
    """{at, windows: {h5·day·week: {from, work, tools}}, floors: {층 id: {h5, day, week}}, stats}.
    cache: 기억 파일 경로(없으면 처음부터 세고 쓰지 않아요). alive: 파일마다 묻는 함수, False면 쓰지 않고 그만둬요."""
    t0 = time.monotonic()
    now = time.time() if now is None else float(now)
    wins = windows(now)
    floor = int(min(wins.values()))
    old = _load_cache(cache, floor) if cache else {}
    try:
        res = _run(roots, floors, old, wins, now, floor, alive)
    except (KeyError, TypeError, IndexError, AttributeError, ValueError):
        if not old:
            raise
        res = _run(roots, floors, {}, wins, now, floor, alive)   # 기억 파일이 깨졌으면 처음부터 세요
    if res is None:
        return None
    w, per, new, st = res
    if cache:
        _save_cache(cache, new, floor)
    st["ms"] = int((time.monotonic() - t0) * 1000)
    return {"ok": True, "at": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"), "windows": w, "floors": per, "stats": st}


def _run(roots, floors, old, wins, now, floor, alive):
    new, by, gone = {}, {t: [] for t in TOOLS}, set()
    st = {"files": 0, "old": 0, "same": 0, "tail": 0, "full": 0, "bytes": 0}
    for tool, root, paths in _files(roots):
        for path in paths:
            if alive is not None and not alive():
                return None
            try:
                s = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            st["files"] += 1
            if s.st_mtime < floor:
                st["old"] += 1   # 기간 전에 고친 파일은 열지 않아요
                if tool == "codex":   # rollout-<시각>-<세션 id>.jsonl: 그 세션의 앞부분이 여기 있을 수 있어요
                    gone.add(os.path.basename(path)[:-6].split("-", 6)[-1])
                continue
            e = _update(tool, root, path, s, old.get(path), floor, st)
            if e is None:
                continue
            _prune(e, floor)
            new[path] = e
            by[tool].append(dict(e, path=path) if tool == "codex" else e)
    w, per = _sum(by, wins, now, _Floors(floors), gone)
    return w, per, new, st


def _child():
    """서버용: 표준 입력의 {roots, floors, cache}로 세어 표준 출력에 JSON 한 줄. 서버가 꺼지면(부모가 바뀌면) 쓰지 않고 그만둬요."""
    parent = os.getppid()
    try:
        os.nice(10)   # 화면을 밀어내지 않게 천천히
    except (OSError, AttributeError):
        pass
    a = json.loads(sys.stdin.buffer.read() or b"{}")
    cache = a.get("cache")
    if not (isinstance(cache, str) and os.path.isabs(cache) and os.path.basename(cache) == "cache.json"):
        cache = None
    res = count(a.get("roots") if isinstance(a.get("roots"), dict) else None, a.get("floors"), cache,
                a.get("now") if isinstance(a.get("now"), (int, float)) else None, alive=lambda: os.getppid() == parent)
    if res is None:
        sys.exit(3)
    sys.stdout.write(json.dumps(res))


def main():
    if sys.argv[1:] == ["--count"]:
        _child()
        return
    if sys.argv[1:]:
        sys.exit(__doc__.split("\n\n")[0])
    res = count()
    names = {"h5": "최근 5시간", "day": "오늘", "week": "이번 주"}
    for w in WINDOWS:
        x = res["windows"][w]
        tools = " · ".join(f"{t} {x['tools'][t]:,}" for t in TOOLS if x["tools"][t])
        print(f"{names[w]}: 작업량 {x['work']:,}" + (f"  ({tools})" if tools else ""))


if __name__ == "__main__":
    main()
