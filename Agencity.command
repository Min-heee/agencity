#!/bin/sh
# 맥에서 더블클릭하면 에이전시티를 켜요(처음에 막히면 README의 안내대로 한 번 허용).
# 명령어 도구(swiftc)가 있으면 이 폴더용 맥 앱(~/Applications/Agencity.app)을 만들어(같은 판이 있으면 그대로) 앱으로 열고,
# 없거나 만들지 못하면 예전처럼 브라우저로 켜요. 명령어 도구 없이 맥 기본 python3(/usr/bin/python3)뿐이면 켜지 못해서 알려만 줘요.
cd "$(dirname "$0")" || exit 1
if xcode-select -p >/dev/null 2>&1 && xcrun --find swiftc >/dev/null 2>&1; then
  if sh bin/make_mac_app.sh --if-needed --open; then exit 0; fi
  echo "앱으로 열지 못해서 브라우저로 켜요."
elif ! xcode-select -p >/dev/null 2>&1 && [ "$(command -v python3 2>/dev/null)" = /usr/bin/python3 ]; then
  echo "명령어 도구가 필요해요: xcode-select --install 을 실행한 뒤 다시 더블클릭해 주세요 (또는 python.org 파이썬)"
  exit 1
else
  echo "참고: 프로그램(맥 앱)으로 쓰려면 xcode-select --install 로 명령어 도구를 설치한 뒤 다시 더블클릭해요. 지금은 브라우저로 켜요."
fi
exec python3 start.py
