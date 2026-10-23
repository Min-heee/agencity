#!/usr/bin/env python3
"""에이전시티 시작하기.

python3 start.py              # 페이지를 만들고 서버를 켠 뒤 브라우저를 열어요(끄려면 Ctrl-C)
python3 start.py --no-open    # 브라우저는 열지 않아요
python3 start.py --app        # 맥 앱(Agencity.app)이 쓰는 방식: 브라우저 대신 주소 한 줄을 알려 줘요
OFFICE_PORT=8766 python3 start.py   # 다른 포트로

처음 켜면 org.json이 없어서 예시 팀(examples/)으로 시작해요. 내 팀은 화면에 뜨는 설정에서 만들어요(터미널은 bin/new_team.py).

--app: 서버가 켜지면(이 폴더의 사무실이 이미 켜져 있으면 바로) AGENCITY_URL=http://127.0.0.1:<포트>/ 한 줄을 알려 줘요.
  이미 켜져 있었으면 그 줄만 알리고 끝나요. 아니면 종료 신호(SIGTERM·SIGHUP)를 받거나, 앱과 이어진 표준입력(파이프)이
  닫힐 때까지(앱이 강제로 꺼진 경우) 켜 둬요. 앱에 따로 보여 줄 말은 AGENCITY_NOTE=<말> 줄로 먼저 알려요.

이 폴더의 사무실이 예전 코드로 켜져 있으면(새로 설치·git pull 뒤) 새로 켜지 않고 화면 위 ‘다시 켜기’로 안내해요
(그 단추가 없는 예전 서버면 끄고 다시 켜라고 알려요).
"""
import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.realpath(__file__))
FIRST_PORT = 8765
HOME_ID = hashlib.sha256(HERE.encode("utf-8")).hexdigest()[:12]   # office_server.py와 같은 방식
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1은 프록시를 거치지 않게


def version():
    try:
        with open(os.path.join(HERE, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def office_state(port):
    """그 포트가 에이전시티면 /api/state 답(dict), 아니면 None. code=now: 서버가 코드 파일을 바로 다시 봐요(모르는 서버는 그냥 넘겨요)."""
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}/api/state?code=now", timeout=1) as r:
            res = json.load(r)
    except Exception:  # noqa: BLE001 — 다른 프로그램이면 아니라고 봐요
        return None
    return res if isinstance(res, dict) and res.get("ok") is True else None


def tell_app(url):
    """--app: 앱이 읽는 주소 줄. 한 번만, 바로 보내요."""
    print(f"AGENCITY_URL={url}", flush=True)


def stdin_is_pipe():
    try:
        return stat.S_ISFIFO(os.fstat(0).st_mode)
    except OSError:
        return False


def watch_stdin():
    """--app: 앱과 이어진 표준입력이 닫히면(앱이 강제로 꺼져도) 종료 신호처럼 서버까지 같이 꺼요."""
    try:
        while os.read(0, 1024):
            pass
    except OSError:
        pass
    os.kill(os.getpid(), signal.SIGTERM)


def forget_pid_file():
    """앱 안 업데이트(bin/self_update.py)가 뒤에서 켠 start.py는 .update/server.pid에 번호가 적혀 있어요.
    끌 때 그 번호가 이 start.py 것이면 지워요(남은 번호로 나중에 엉뚱한 프로그램을 끄지 않게)."""
    p = os.path.join(HERE, ".update", "server.pid")
    try:
        with open(p, encoding="utf-8") as f:
            mine = f.read().strip() == str(os.getpid())
        if mine:
            os.remove(p)
    except OSError:
        pass


def main():
    if sys.version_info < (3, 9):
        sys.exit("파이썬 3.9 이상이 필요해요. https://www.python.org/downloads/ 에서 받거나, 맥이면 xcode-select --install")
    os.chdir(HERE)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # 터미널이 아니어도 안내가 바로 보이게
    except (AttributeError, ValueError):
        pass
    app = "--app" in sys.argv
    no_open = app or "--no-open" in sys.argv
    ver = version()
    print(f"에이전시티 {ver}")

    # 이 폴더의 사무실이 이미 켜져 있으면 그걸 열어요. 페이지는 다시 만들지 않아요(켜진 서버와 짝이 맞게).
    want = int(os.environ.get("OFFICE_PORT", FIRST_PORT))
    port = None
    for p in range(want, want + 20):
        if not port_open(p):
            port = port or p
            continue
        st = office_state(p)
        if st is None:
            continue
        url = f"http://127.0.0.1:{p}/"
        if st.get("home") != HOME_ID:
            # home이 없으면 0.3.0 이전 서버라 어느 폴더 것인지 몰라요. 다른 사무실로 보고 넘어가요.
            what = "다른 폴더의" if st.get("home") else "다른(예전 버전)"
            print(f"· 참고: {p} 포트에는 {what} 에이전시티가 켜져 있어요.")
            continue
        old = st.get("version") or "?"
        # 화면 위 ‘다시 켜기’가 있는 서버(code.canRestart)면 그 단추로 안내해요. 그 전 서버는 예전처럼 끄고 다시 켜라고 해요.
        code = st.get("code") if isinstance(st.get("code"), dict) else {}
        button = code.get("canRestart") is True
        if st.get("version") != ver and button:
            print(f"· 이 폴더의 예전 버전({old})이 {url} 에 켜져 있어요. 화면 위 ‘다시 켜기’를 누르면 새 버전({ver})이 적용돼요.")
            if app:
                print(f"AGENCITY_NOTE=화면 위 ‘다시 켜기’를 누르면 새 버전({ver})이 적용돼요(지금 {old}).")   # 앱 알림 제목: ‘예전 버전이 켜져 있어요’
        elif st.get("version") != ver:
            print(f"· 이 폴더의 예전 버전({old})이 {url} 에 켜져 있어요."
                  f" 새 버전({ver})은 그 창에서 Ctrl-C로 끄고 python3 start.py로 다시 켜야 적용돼요.")
            if app:
                print(f"AGENCITY_NOTE=이 폴더의 예전 버전({old}) 사무실이 이미 켜져 있어서 그 화면을 보여 줘요."
                      f" 새 버전({ver})을 쓰려면 예전 사무실을 켠 창에서 끈 뒤(터미널은 Ctrl-C, 앱은 ⌘Q) 앱을 다시 열어 주세요.")
        elif button and code.get("changed") is True:   # 버전은 같고 코드만 바뀜(git pull, 손으로 고침)
            # 앱 알림은 띄우지 않아요(알림 제목이 ‘예전 버전’이라서요). 앱 화면 위에 바로 ‘다시 켜기’가 떠요.
            print(f"· 이 폴더의 사무실이 예전 코드로 {url} 에 켜져 있어요. 화면 위 ‘다시 켜기’를 누르면 새 코드가 적용돼요.")
        else:
            print(f"· 이미 켜져 있어요: {url}")
        if app:
            tell_app(url)
        if not no_open:
            webbrowser.open(url)
        return
    if port is None:
        sys.exit(f"{want}~{want + 19} 포트가 모두 쓰이고 있어요. OFFICE_PORT=<빈 포트> python3 start.py 로 켜 주세요.")

    if not os.path.exists("org.json"):
        shutil.copy(os.path.join("examples", "org.example.json"), "org.json")
        print("· 처음이라 예시 팀으로 시작해요. 내 팀은 화면에 뜨는 설정에서 만들어요.")
    if not shutil.which("jq"):
        print("· 참고: jq가 없어요. 사이트 메시지 전달(relay_done.sh)과 팀원 답장(say.sh)에 필요해요. 맥: brew install jq")

    r = subprocess.run([sys.executable, "-I", "build.py"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("페이지를 만들지 못했어요:\n" + r.stderr[-800:])

    # 창을 닫거나(SIGHUP) 종료 신호(SIGTERM)를 받아도 Ctrl-C처럼 서버까지 같이 꺼요. nohup처럼 무시하게 한 신호는 그대로 둬요.
    def stop(*_):
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None and signal.getsignal(sig) is not signal.SIG_IGN:
            signal.signal(sig, stop)

    # AGENCITY_START_PID: 서버가 자기를 켠 start.py를 알아보는 표시(앱 안 업데이트가 브라우저로 켠 사무실을 끄고 다시 켤 때 써요)
    env = dict(os.environ, OFFICE_PORT=str(port), AGENCITY_START_PID=str(os.getpid()))
    # --app: 서버는 앱과 이어진 표준입력을 물려받지 않게 해요(그 파이프는 start.py만 지켜봐요).
    proc = subprocess.Popen([sys.executable, "-I", "office_server.py"], env=env,
                            stdin=subprocess.DEVNULL if app else None)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(50):
            if proc.poll() is not None:
                sys.exit("서버가 바로 꺼졌어요. 위의 메시지를 확인해 주세요.")
            if port_open(port):
                break
            time.sleep(0.1)
        print(f"· 켜졌어요: {url}   (도시: {url}city.html)")
        if app:
            tell_app(url)
            if stdin_is_pipe():   # 터미널이나 /dev/null이면 지켜보지 않아요
                threading.Thread(target=watch_stdin, daemon=True).start()
        else:
            print("· 끄려면 이 창에서 Ctrl-C")
        print("· 사이트에서 보낸 말을 팀 세션에 전하려면, 총괄로 쓸 Claude Code 세션에서 docs/COORDINATOR.md 대로 전달을 켜요")
        if not no_open:
            webbrowser.open(url)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            print("\n끝냈어요.")
        except OSError:   # --app: 앱이 먼저 꺼져 출력 파이프가 닫힌 경우
            pass
    finally:
        forget_pid_file()


if __name__ == "__main__":
    main()
