#!/usr/bin/env python3
"""에이전시티 업데이트 도우미. 서버(/api/update/run)가 세션을 떼어 따로 켜요. 손으로 켤 일은 없어요.

python3 -I bin/self_update.py --to vX.Y.Z --dir <설치 폴더> [--app-bundle <Agencity.app>] [--stop-pid <pid>] [--server-pid <pid>]
python3 -I bin/self_update.py --restart-only --dir <설치 폴더> --old-boot <code.boot> [--app-bundle …] [--stop-pid …] [--server-pid …]

1. 진행 상태를 <설치 폴더>/.update/status.json에 적어요: {state: running|done|failed, kind: update|restart, to, from, mode, pid, started,
   updated, finished, message, installed(새 코드를 받아 VERSION까지 확인했으면 true)}.
   이 도우미의 출력(설치 기록)은 서버가 .update/last.log로 받아요.
2. <RAW>/<REPO>/<태그>/install.sh(그 태그에 고정, 기본은 https://raw.githubusercontent.com)를 임시 파일로 받아 sh로 실행해요.
   환경: AGENCITY_DIR=<설치 폴더> AGENCITY_REF=<태그> AGENCITY_NO_START=1 AGENCITY_NO_APP=1. install.sh는 코드만 새로 받고
   내 팀 정보(org.json, teams/, hq/, outbox/, setup.json 등)와 .update/는 그대로 둬요.
3. 실패하면 status를 failed로(기록 끝부분과 함께) 남기고 아무것도 다시 켜지 않아요. 켜져 있던 사무실은 그대로예요.
4. 성공하면 다시 켜요.
   - 앱(--app-bundle, 또는 서버 환경에 AGENCITY_APP=1이 있고 ~/Applications/Agencity.app이 우리 앱일 때):
     AGENCITY_APP_DEST=<앱이 있는 폴더> sh <설치 폴더>/bin/make_mac_app.sh --open
     (앱을 새로 만들고, 켜져 있던 앱을 끈 뒤 다시 열어요. 앱이 꺼지면 앱이 켠 서버도 같이 꺼져요.)
   - 브라우저: --stop-pid(서버를 켠 start.py, 없으면 서버)에 SIGTERM을 보내고 10초까지 기다린 뒤,
     python3 <설치 폴더>/start.py --no-open을 따로 켜요(기록 .update/server.log, 프로세스 번호 .update/server.pid.
     그 start.py는 꺼질 때 이 번호 파일이 자기 것이면 지워요).
   새 버전 사무실이 대답하면(같은 설치 폴더, 버전이 태그와 같음) status를 done으로 적어요.
--restart-only(화면의 ‘다시 켜기’, /api/update/restart): 아무것도 받지 않고 2·3을 건너뛰어, 지금 디스크의 코드로 4만 해요.
   끄기 전에 그 코드가 켜질 수 있는지 봐요(문법, 임시 폴더에서 페이지 만들기, 서버 코드 읽기). 안 되면 failed로 적고 끄지 않아요.
   status에는 kind: restart와 oldBoot(끈 서버의 표시)를 적어요. 앱은 make_mac_app.sh --if-needed --reopen(앱 소스가 그대로면
   다시 만들지 않고 끈 뒤 다시 열어요). 새 사무실은 표시(code.boot)가 끈 서버와 다를 때 켜진 걸로 봐요(버전이 같아도 돼요).
   git 폴더·개발용 판(VERSION이 vX.Y.Z가 아님)도 돼요.
시험용 환경 변수: AGENCITY_UPDATE_RAW(https, 또는 127.0.0.1·localhost의 http), AGENCITY_UPDATE_REPO.
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

KST = timezone(timedelta(hours=9))
TAG_RE = re.compile(r"^v(\d{1,6})\.(\d{1,6})\.(\d{1,6})\Z")
BOOT_RE = re.compile(r"^[0-9a-f]{6,32}\Z")   # 서버 표시(/api/state의 code.boot)
APP_ID = "io.github.min-heee.agencity"   # bin/make_mac_app.sh가 만드는 앱의 번들 ID
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}\Z")
MAX_SCRIPT = 512 * 1024      # install.sh가 이보다 크면 이상한 거예요
INSTALL_TIMEOUT = 15 * 60
APP_TIMEOUT = 15 * 60        # 앱 컴파일은 처음엔 1분쯤
STOP_WAIT = 10               # 예전 사무실이 꺼지길 기다리는 시간
START_WAIT = 60              # 새 버전 사무실이 대답하길 기다리는 시간
PREFLIGHT_WAIT = 60          # 다시 켜기 전에 새 코드를 살펴보는 데 쓰는 시간(하나마다)
TAIL = 15                    # 실패 메시지에 붙이는 기록 줄 수
# 설치 스크립트·앱 만들기·새 start.py에 물려주지 않는 값(설치 위치·버전은 여기서 정해요)
DROP_ENV = ("AGENCITY_SRC", "AGENCITY_FORCE", "AGENCITY_DIR", "AGENCITY_REF", "AGENCITY_NO_START", "AGENCITY_NO_APP",
            "AGENCITY_APP_DEST", "AGENCITY_START_PID", "CLAUDE_OFFICE_DIR", "CLAUDE_OFFICE_REF")
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1은 프록시를 거치지 않게


class Fail(Exception):
    pass


def now():
    return datetime.now(KST).isoformat(timespec="seconds")


def say(msg):
    print(f"[{now()}] {msg}", flush=True)


def update_url(name, default):
    """office_server.py와 같은 규칙: https, 또는 이 컴퓨터의 http만."""
    v = (os.environ.get(name) or "").strip().rstrip("/")
    try:
        p = urlsplit(v)
        ok = bool(p.hostname) and not p.query and not p.fragment and not re.search(r"\s", v) and (
            p.scheme == "https" or (p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")))
    except ValueError:
        ok = False
    return v if ok else default


def read_version(d):
    try:
        with open(os.path.join(d, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in DROP_ENV}


class Status:
    def __init__(self, d, to, mode, kind="update"):
        self.path = os.path.join(d, ".update", "status.json")
        t = now()
        self.doc = {"state": "running", "kind": kind, "to": to, "from": read_version(d), "mode": mode, "pid": os.getpid(),
                    "started": t, "updated": t, "message": ""}

    def set(self, state, message):
        self.doc.update(state=state, message=message, updated=now())
        if state in ("done", "failed"):
            self.doc["finished"] = self.doc["updated"]
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        tmp = f"{self.path}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


def with_tail(msg, tail):
    return msg + ("\n\n기록 끝부분:\n" + "\n".join(tail) if tail else "")


def download(url, path, ver):
    say(f"받는 중: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"agencity/{ver or 'dev'}"})
    try:
        opener = LOCAL if urlsplit(url).hostname in ("127.0.0.1", "localhost") else urllib.request.build_opener()
        with opener.open(req, timeout=30) as r:
            data = r.read(MAX_SCRIPT + 1)
    except urllib.error.HTTPError as e:
        raise Fail(f"설치 스크립트를 받지 못했어요(HTTP {e.code}). 켜져 있던 사무실은 그대로예요.")
    except (urllib.error.URLError, OSError, ValueError) as e:
        if not (isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError) and url.startswith("https://") and shutil.which("curl")):
            raise Fail("설치 스크립트를 받지 못했어요. 인터넷 연결을 확인해 주세요. 켜져 있던 사무실은 그대로예요.")
        # python.org에서 받은 파이썬은 인증서를 따로 깔아야 해요. 그럴 땐 맥에 있는 curl로 받아요.
        say("파이썬이 인증서를 확인하지 못해서 curl로 받아요")
        r = subprocess.run(["curl", "-fsSL", "--proto", "=https", "--max-time", "60", "-A", f"agencity/{ver or 'dev'}", url],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=90)
        if r.returncode != 0:
            raise Fail("설치 스크립트를 받지 못했어요(curl). 인터넷 연결을 확인해 주세요. 켜져 있던 사무실은 그대로예요.")
        data = r.stdout
    if len(data) > MAX_SCRIPT or not data.startswith(b"#!") or b"AGENCITY_DIR" not in data:
        raise Fail("받은 설치 스크립트가 이상해서 실행하지 않았어요. 켜져 있던 사무실은 그대로예요.")
    with open(path, "wb") as f:
        f.write(data)


def run_logged(cmd, env, cwd, timeout):
    """명령을 켜고 출력을 그대로 기록에 남겨요. (종료 코드, 마지막 몇 줄)"""
    say("실행: " + " ".join(cmd))
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)

    def kill():
        say(f"{timeout}초가 지나도 끝나지 않아서 멈춰요")
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
    timer = threading.Timer(timeout, kill)
    timer.daemon = True
    timer.start()
    tail = deque(maxlen=TAIL)
    try:
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            print("  " + line, flush=True)
            if line.strip():
                tail.append(line[:300])
        rc = p.wait()
    finally:
        timer.cancel()
    say(f"끝: 코드 {rc}")
    return rc, list(tail)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return True


def wait_gone(pids, seconds):
    until = time.time() + seconds
    while time.time() < until:
        alive = [p for p in pids if pid_alive(p)]
        if not alive:
            return []
        time.sleep(0.1)
    return [p for p in pids if pid_alive(p)]


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def office_state(port):
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}/api/state", timeout=1) as r:
            res = json.load(r)
    except Exception:  # noqa: BLE001 — 다른 프로그램이거나 아직 안 켜졌어요
        return None
    return res if isinstance(res, dict) and res.get("ok") is True else None


def first_port():
    try:
        p = int(os.environ.get("OFFICE_PORT") or 8765)
    except ValueError:
        return 8765
    return p if 1 <= p <= 65515 else 8765


def wait_new_office(home, want, seconds, proc=None, old_boot=None):
    """같은 설치 폴더의 새 버전(want, None이면 버전은 보지 않아요) 사무실이 대답한 포트. proc(start.py)가 먼저 끝나면 None.
    old_boot: 다시 켜기로 끈 서버의 표시(code.boot). 그 표시로 대답하는 사무실은 아직 예전 서버라 넘어가요."""
    base = first_port()
    until = time.time() + seconds
    while time.time() < until:
        for port in range(base, base + 20):
            if port_open(port):
                st = office_state(port)
                code = st.get("code") if st else None
                boot = code.get("boot") if isinstance(code, dict) else None
                if st and st.get("home") == home and (want is None or st.get("version") == want) and (old_boot is None or boot != old_boot):
                    return port
        if proc is not None and proc.poll() is not None:
            return None
        time.sleep(0.5)
    return None


def file_tail(path, n=TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 16384))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    return [x[:300] for x in lines if x.strip()][-n:]


def default_app_bundle():
    """~/Applications/Agencity.app이 make_mac_app.sh가 만든 앱(번들 ID)이면 그 경로."""
    b = os.path.join(os.path.expanduser("~"), "Applications", "Agencity.app")
    try:
        with open(os.path.join(b, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
    except Exception:  # noqa: BLE001 — 없거나 못 읽으면 우리 앱이 아니에요
        return None
    return b if sys.platform == "darwin" and isinstance(info, dict) and info.get("CFBundleIdentifier") == APP_ID else None


def restart_app(d, tag, bundle, st, old_boot=None):
    """앱을 다시 열어요. tag가 None이면 다시 켜기(받지 않음): 앱 소스가 그대로면 다시 만들지 않고 끈 뒤 다시 열어요."""
    st.set("running", "새 앱을 만들고 다시 여는 중이에요(1분쯤 걸릴 수 있어요)" if tag else "앱을 다시 여는 중이에요")
    env = clean_env()
    env["AGENCITY_APP_DEST"] = os.path.dirname(bundle)
    rc, tail = run_logged(["sh", os.path.join(d, "bin", "make_mac_app.sh")] + (["--open"] if tag else ["--if-needed", "--reopen"]),
                          env, d, APP_TIMEOUT)
    if rc != 0:
        raise Fail(with_tail(f"{tag} 파일은 받았지만 앱을 다시 만들거나 열지 못했어요. 앱을 ⌘Q로 끄고 다시 열면 새 버전으로 켜져요." if tag
                             else "앱을 다시 열지 못했어요. 앱을 ⌘Q로 끄고 다시 열면 새 코드로 켜져요.", tail))
    home = hashlib.sha256(d.encode("utf-8")).hexdigest()[:12]
    port = wait_new_office(home, tag[1:] if tag else None, START_WAIT, old_boot=old_boot)
    if port is None:
        raise Fail(f"{tag} 파일은 받고 앱도 다시 열었지만 새 버전 사무실이 대답하지 않아요. 앱을 ⌘Q로 끄고 다시 열어 주세요." if tag
                   else "앱은 다시 열었지만 사무실이 대답하지 않아요. 앱을 ⌘Q로 끄고 다시 열어 주세요.")
    say(f"{'새 버전 ' if tag else ''}사무실이 켜졌어요: http://127.0.0.1:{port}/")


def restart_browser(d, tag, stop_pid, server_pid, st, old_boot=None):
    """켠 start.py(없으면 서버)를 끄고 start.py --no-open을 따로 켜요. tag가 None이면 다시 켜기(받지 않음)예요."""
    st.set("running", "사무실을 끄고 새 버전으로 다시 켜는 중이에요" if tag else "사무실을 끄고 다시 켜는 중이에요")
    me = os.getpid()
    pids = [p for p in (stop_pid, server_pid) if p and p > 1 and p != me]
    target = stop_pid if stop_pid and stop_pid > 1 and stop_pid != me else server_pid
    if target and target > 1 and target != me:
        say(f"예전 사무실을 꺼요(pid {target})")
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            pass
    left = wait_gone(pids, STOP_WAIT)
    if left:
        say(f"{STOP_WAIT}초 안에 꺼지지 않아서 강제로 꺼요: {left}")
        for p in left:
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
        left = wait_gone(left, 3)
        if left:
            raise Fail((f"{tag} 파일은 받았지만 " if tag else "") + "예전 사무실이 꺼지지 않았어요. 사무실을 끄고(Ctrl-C) python3 start.py로 다시 켜 주세요.")
    port = first_port()
    until = time.time() + 5
    while port_open(port) and time.time() < until:   # 예전 서버가 포트를 놓을 때까지 조금 기다려요
        time.sleep(0.1)
    log_path = os.path.join(d, ".update", "server.log")
    with open(log_path, "ab") as log:
        log.write(f"\n[{now()}] {tag or '다시 켜기'}: python3 start.py --no-open\n".encode("utf-8"))
        log.flush()
        proc = subprocess.Popen([sys.executable, "-I", os.path.join(d, "start.py"), "--no-open"], cwd=d, env=clean_env(),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                close_fds=True)
    # start.py는 끌 때 이 파일이 자기 번호면 지워요(남은 번호로 엉뚱한 프로그램을 끄지 않게)
    pid_path = os.path.join(d, ".update", "server.pid")
    with open(pid_path, "w", encoding="utf-8") as f:
        f.write(f"{proc.pid}\n")
    say(f"{'새 버전 ' if tag else ''}사무실을 켰어요(start.py pid {proc.pid}, 기록 .update/server.log)")
    home = hashlib.sha256(d.encode("utf-8")).hexdigest()[:12]
    found = wait_new_office(home, tag[1:] if tag else None, START_WAIT, proc, old_boot)
    if found is None and proc.poll() is not None:   # 바로 꺼졌으면 번호를 남기지 않아요
        try:
            os.remove(pid_path)
        except OSError:
            pass
    if found is None:
        raise Fail(with_tail((f"{tag} 파일은 받았지만 " if tag else "") + f"사무실을 다시 켜지 못했어요. 터미널에서 python3 \"{d}/start.py\" 로 켜 주세요.",
                             file_tail(log_path)))
    say(f"{'새 버전 ' if tag else ''}사무실이 켜졌어요: http://127.0.0.1:{found}/")


def pick_bundle(a, st):
    """다시 열 맥 앱 경로(브라우저면 None). 업데이트와 다시 켜기가 같이 써요."""
    if a.app_bundle:
        bundle = os.path.normpath(a.app_bundle)
        if not os.path.isabs(bundle) or os.path.basename(bundle) != "Agencity.app":
            raise Fail("앱 경로가 이상해요(…/Agencity.app이어야 해요). 한 줄 설치를 다시 실행해 주세요.")
        return bundle
    if os.environ.get("AGENCITY_APP") == "1":
        # 앱 안에서 켠 서버인데 앱 경로를 받지 못했으면(예전 앱) 기본 자리의 앱을 써요. 없으면 브라우저처럼 끄지 않아요.
        st.doc["mode"] = "app"
        bundle = default_app_bundle()
        if not bundle:
            raise Fail("이 사무실을 켠 맥 앱을 찾지 못했어요. 한 줄 설치를 다시 실행해 주세요.")
        return bundle
    return None


# 서버 코드를 읽어만 봐요(main()은 부르지 않아서 포트를 열거나 파일을 쓰지 않아요)
CHECK_SERVER = "import runpy, sys; runpy.run_path(sys.argv[1], run_name='agencity_check')"


def preflight(d, st):
    """다시 켜기 전에(끄기 전에) 디스크의 코드가 켜질 수 있는지 봐요. 안 되면 Fail이고 쓰던 사무실은 그대로 둬요(손으로 고친 코드의 오타 등).
    세 파일의 문법을 보고, 페이지는 임시 폴더에서 만들어 보고(켜진 서버의 index.html은 건드리지 않아요), office_server.py는 읽어만 봐요."""
    st.set("running", "새 코드를 살펴보는 중이에요")
    keep = "켜져 있던 사무실은 그대로예요. 고친 뒤 다시 눌러 주세요."
    for n in ("start.py", "build.py", "office_server.py"):
        p = os.path.join(d, n)
        try:
            with open(p, "rb") as f:
                compile(f.read(), p, "exec", dont_inherit=True)
        except SyntaxError as e:
            raise Fail(with_tail(f"{n}에 문법 오류가 있어서 다시 켜지 않았어요. {keep}", [f"{n} {e.lineno}번째 줄: {e.msg}"]))
        except (OSError, ValueError) as e:
            raise Fail(f"{n} 파일을 읽지 못해서 다시 켜지 않았어요({type(e).__name__}). {keep}")
    with tempfile.TemporaryDirectory(prefix="agencity-check-") as t:
        try:
            for n in ("build.py", "office.src.html"):
                shutil.copyfile(os.path.join(d, n), os.path.join(t, n))
        except OSError as e:
            raise Fail(f"페이지 파일을 읽지 못해서 다시 켜지 않았어요({type(e).__name__}). {keep}")
        rc, tail = run_logged([sys.executable, "-I", os.path.join(t, "build.py")], clean_env(), t, PREFLIGHT_WAIT)
        if rc != 0 or not os.path.isfile(os.path.join(t, "index.html")):
            raise Fail(with_tail(f"페이지(office.src.html)를 만들지 못해서 다시 켜지 않았어요. {keep}", tail))
    # 문법은 맞아도 읽다가(켤 때 맨 먼저) 멈추는 오류(없는 이름 등)
    rc, tail = run_logged([sys.executable, "-I", "-c", CHECK_SERVER, os.path.join(d, "office_server.py")], clean_env(), d, PREFLIGHT_WAIT)
    if rc != 0:
        raise Fail(with_tail(f"office_server.py에 오류가 있어서 다시 켜지 않았어요. {keep}", tail))


def restart_only(d, a):
    """화면의 ‘다시 켜기’: 아무것도 받지 않고 지금 디스크의 코드로 다시 켜요. 끄고 켜는 순서는 업데이트와 같아요.
    끄기 전에 그 코드가 켜질 수 있는지 먼저 봐요(preflight)."""
    cur = read_version(d)
    old_boot = a.old_boot if a.old_boot and BOOT_RE.match(a.old_boot) else None
    st = Status(d, f"v{cur}" if TAG_RE.match(f"v{cur}") else None, "app" if a.app_bundle else "browser", kind="restart")
    if old_boot:
        st.doc["oldBoot"] = old_boot
    try:
        bundle = pick_bundle(a, st)
        say(f"다시 켜기 시작: {cur or '?'} ({d}, {st.doc['mode']})")
        preflight(d, st)
        if bundle:
            restart_app(d, None, bundle, st, old_boot)
        else:
            restart_browser(d, None, a.stop_pid, a.server_pid, st, old_boot)
        st.set("done", "새 코드로 다시 켰어요")
        say("끝났어요")
        return 0
    except Fail as e:
        say(f"실패: {e}")
        st.set("failed", str(e))
        return 1
    except Exception as e:  # noqa: BLE001 — 상태 파일에 남기고 끝내요
        say(f"오류: {type(e).__name__}: {e}")
        st.set("failed", f"다시 켜기 도우미 오류({type(e).__name__}). .update/last.log를 확인해 주세요.")
        return 1


def main():
    ap = argparse.ArgumentParser(description="에이전시티 업데이트 도우미(서버가 켜요)")
    ap.add_argument("--to", help="받을 태그 vX.Y.Z(업데이트)")
    ap.add_argument("--restart-only", action="store_true", help="받지 않고 지금 디스크의 코드로 다시 켜기만 해요(화면의 ‘다시 켜기’)")
    ap.add_argument("--old-boot", help="--restart-only: 끌 서버의 표시(/api/state의 code.boot)")
    ap.add_argument("--dir", required=True, help="설치 폴더")
    ap.add_argument("--app-bundle", help="다시 만들고 열 맥 앱(Agencity.app) 경로")
    ap.add_argument("--stop-pid", type=int, help="브라우저 모드: 끌 프로세스(서버를 켠 start.py)")
    ap.add_argument("--server-pid", type=int, help="브라우저 모드: 꺼질 때까지 기다릴 서버")
    a = ap.parse_args()
    if not a.restart_only and not a.to:
        ap.error("--to(받을 태그)나 --restart-only가 필요해요")
    d = os.path.realpath(a.dir)
    if not os.path.isfile(os.path.join(d, "office_server.py")):
        sys.exit(f"설치 폴더가 아니에요: {d}")
    if a.restart_only:
        return restart_only(d, a)
    tag = a.to
    mode = "app" if a.app_bundle else "browser"
    st = Status(d, tag if TAG_RE.match(tag) else None, mode)
    try:
        if not TAG_RE.match(tag):
            raise Fail("버전 이름이 이상해요(vX.Y.Z 모양이어야 해요)")
        if os.path.exists(os.path.join(d, ".git")):
            raise Fail("git으로 받은 폴더예요. git pull로 새로 받아요.")
        bundle = pick_bundle(a, st)
        mode = st.doc["mode"]
        cur = read_version(d)
        say(f"업데이트 시작: {cur or '?'} → {tag} ({d}, {mode})")
        st.set("running", f"{tag} 설치 스크립트를 받는 중이에요")
        raw = update_url("AGENCITY_UPDATE_RAW", "https://raw.githubusercontent.com")
        repo = os.environ.get("AGENCITY_UPDATE_REPO") or "Min-heee/agencity"
        if not REPO_RE.match(repo):
            repo = "Min-heee/agencity"
        tmp = tempfile.mkdtemp(prefix="agencity-update-")
        try:
            script = os.path.join(tmp, "install.sh")
            download(f"{raw}/{repo}/{tag}/install.sh", script, cur)
            st.set("running", f"{tag}를 설치하는 중이에요")
            env = clean_env()
            env.update(AGENCITY_DIR=d, AGENCITY_REF=tag, AGENCITY_NO_START="1", AGENCITY_NO_APP="1")
            rc, tail = run_logged(["sh", script], env, tmp, INSTALL_TIMEOUT)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if rc != 0:
            raise Fail(with_tail(f"설치 스크립트가 실패했어요(코드 {rc}). 켜져 있던 사무실은 그대로예요.", tail))
        got = read_version(d)
        if got != tag[1:]:
            raise Fail(f"설치한 뒤 버전이 {got or '?'}예요({tag[1:]}이어야 해요). 켜져 있던 사무실은 그대로예요.")
        say(f"설치했어요: {got}")
        st.doc["installed"] = True   # 여기부터 실패하면 새 코드는 받았고 다시 켜기만 못 한 거예요(화면이 ‘다시 시도’ 대신 ‘닫기’를 앞에 둬요)
        if bundle:
            restart_app(d, tag, bundle, st)
        else:
            restart_browser(d, tag, a.stop_pid, a.server_pid, st)
        st.set("done", f"{tag}로 업데이트했어요")
        say("끝났어요")
        return 0
    except Fail as e:
        say(f"실패: {e}")
        st.set("failed", str(e))
        return 1
    except Exception as e:  # noqa: BLE001 — 상태 파일에 남기고 끝내요
        say(f"오류: {type(e).__name__}: {e}")
        st.set("failed", f"업데이트 도우미 오류({type(e).__name__}). .update/last.log를 확인해 주세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
