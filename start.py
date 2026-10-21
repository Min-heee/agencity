#!/usr/bin/env python3
"""클로드 오피스 시작하기.

python3 start.py              # 페이지를 만들고 서버를 켠 뒤 브라우저를 열어요(끄려면 Ctrl-C)
python3 start.py --no-open    # 브라우저는 열지 않아요
OFFICE_PORT=8766 python3 start.py   # 다른 포트로

처음 켜면 org.json이 없어서 예시 팀(examples/)으로 시작해요. 내 팀은 python3 bin/new_team.py로 등록해요.
"""
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
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
    """그 포트가 클로드 오피스면 /api/state 답(dict), 아니면 None."""
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}/api/state", timeout=1) as r:
            res = json.load(r)
    except Exception:  # noqa: BLE001 — 다른 프로그램이면 아니라고 봐요
        return None
    return res if isinstance(res, dict) and res.get("ok") is True else None


def main():
    if sys.version_info < (3, 9):
        sys.exit("파이썬 3.9 이상이 필요해요. https://www.python.org/downloads/ 에서 받거나, 맥이면 xcode-select --install")
    os.chdir(HERE)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # 터미널이 아니어도 안내가 바로 보이게
    except (AttributeError, ValueError):
        pass
    no_open = "--no-open" in sys.argv
    ver = version()
    print(f"클로드 오피스 {ver}")

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
            print(f"· 참고: {p} 포트에는 {what} 클로드 오피스가 켜져 있어요.")
            continue
        if st.get("version") != ver:
            print(f"· 이 폴더의 예전 버전({st.get('version') or '?'})이 {url} 에 켜져 있어요."
                  f" 새 버전({ver})은 그 창에서 Ctrl-C로 끄고 python3 start.py로 다시 켜야 적용돼요.")
        else:
            print(f"· 이미 켜져 있어요: {url}")
        if not no_open:
            webbrowser.open(url)
        return
    if port is None:
        sys.exit(f"{want}~{want + 19} 포트가 모두 쓰이고 있어요. OFFICE_PORT=<빈 포트> python3 start.py 로 켜 주세요.")

    if not os.path.exists("org.json"):
        shutil.copy(os.path.join("examples", "org.example.json"), "org.json")
        print("· 처음이라 예시 팀으로 시작해요. 내 팀은 python3 bin/new_team.py 로 등록해요.")
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

    env = dict(os.environ, OFFICE_PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-I", "office_server.py"], env=env)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(50):
            if proc.poll() is not None:
                sys.exit("서버가 바로 꺼졌어요. 위의 메시지를 확인해 주세요.")
            if port_open(port):
                break
            time.sleep(0.1)
        print(f"· 켜졌어요: {url}   (토큰 시티: {url}city.html)")
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
        print("\n끝냈어요.")


if __name__ == "__main__":
    main()
