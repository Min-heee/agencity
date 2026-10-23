#!/bin/sh
# 맥 앱(Agencity.app) 만들기: 이 설치 폴더의 사무실을 브라우저 대신 창 하나로 여는 작은 앱을 이 맥에서 직접 컴파일해요.
#
#   sh bin/make_mac_app.sh              # ~/Applications/Agencity.app 을 만들어요(있으면 새로 만들어 바꿔요)
#   sh bin/make_mac_app.sh --open       # 만든 뒤 열어요(켜져 있던 앱은 먼저 끄고 새로 열어요)
#   sh bin/make_mac_app.sh --if-needed  # 이 폴더용 같은 판이 이미 있으면 다시 만들지 않아요(--open과 같이 쓰면 그냥 열어요)
#   sh bin/make_mac_app.sh --if-needed --reopen  # --open과 같지만, 다시 만들지 않을 때도 켜져 있던 앱을 끄고 새로 열어요(화면의 ‘다시 켜기’)
#   AGENCITY_APP_DEST=<폴더> sh bin/make_mac_app.sh   # 다른 곳에 만들기
#
# - 필요한 것: Xcode 명령어 도구(swiftc). 없으면 xcode-select --install 로 설치한 뒤 다시 실행해요.
# - 서명 계정이 없어도 돼요. 이 맥에서 만든 앱이라 그대로 열리고, 임시(ad-hoc) 서명만 해요.
# - 앱에는 설치 폴더 경로만 들어가요(Contents/Resources/install_dir.txt). 앱은 그 폴더의 start.py --app을 켜요.
#   폴더를 옮기면 새 위치에서 이 스크립트를 다시 실행해요. 코드만 새로 받은 경우(git pull 등)는 다시 만들 필요 없어요.
# - 예전 이름: 클로드 오피스(Claude Office). 같은 폴더에 예전 이름으로 만든 앱(Claude Office.app)이 있으면
#   우리가 만든 것(번들 ID로 확인)일 때만 끄고 지워요.
set -eu

ID=io.github.min-heee.agencity
OLD_ID=io.github.min-heee.claude-office   # 예전 이름(Claude Office.app)으로 만든 앱
say() { printf '%s\n' "$*"; }
fail() { printf '앱을 만들지 못했어요: %s\n' "$*" >&2; exit 1; }

OPEN=no
IF_NEEDED=no
REOPEN=no
for a in "$@"; do
  case "$a" in
    --open) OPEN=yes ;;
    --reopen) OPEN=yes; REOPEN=yes ;;
    --if-needed) IF_NEEDED=yes ;;
    *) fail "모르는 옵션이에요: $a (쓸 수 있는 것: --open, --reopen, --if-needed)" ;;
  esac
done

[ "$(uname -s)" = Darwin ] || fail "맥에서만 만들 수 있어요. 리눅스는 python3 start.py 로 켜요."
HERE=$(cd "$(dirname "$0")/.." && pwd -P)
SRC="$HERE/mac/Agencity.swift"
[ -f "$SRC" ] && [ -f "$HERE/start.py" ] || fail "$HERE 에 mac/Agencity.swift 나 start.py가 없어요."
case "$HERE" in *'
'*) fail "설치 폴더 경로에 줄바꿈이 있어요." ;; esac
# /usr/bin/swiftc는 명령어 도구가 없으면 설치 창부터 띄우므로, 있는지 먼저 확인해요.
if ! xcode-select -p >/dev/null 2>&1 || ! xcrun --find swiftc >/dev/null 2>&1; then
  fail "swiftc가 없어요. 터미널에서 xcode-select --install 로 명령어 도구를 설치한 뒤 sh \"$HERE/bin/make_mac_app.sh\" 를 다시 실행해 주세요."
fi

DEST="${AGENCITY_APP_DEST:-$HOME/Applications}"
APP="$DEST/Agencity.app"
EXE="$APP/Contents/MacOS/Agencity"
OLD_APP="$DEST/Claude Office.app"
if [ -e "$APP" ]; then
  old_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Contents/Info.plist" 2>/dev/null || true)
  [ "$old_id" = "$ID" ] || fail "$APP 에 다른 앱이 있어요. 치우거나 AGENCITY_APP_DEST 로 다른 폴더를 골라 주세요."
fi
OLD_DIR=$(cat "$APP/Contents/Resources/install_dir.txt" 2>/dev/null || true)

VER=$(sed -n '1{s/[^0-9.]//g;p;}' "$HERE/VERSION" 2>/dev/null || true)
[ -n "$VER" ] || VER=0
# 같은 소스·같은 폴더로 만든 앱인지 알아보는 표시
STAMP="$(cat "$SRC" "$HERE/bin/make_mac_app.sh" "$HERE/VERSION" 2>/dev/null | cksum | tr ' ' '-') $HERE"

# 그 실행 파일로 켜져 있는 앱의 프로세스 번호들(경로 속 정규식 글자는 이스케이프)
# -a: 앱 안 업데이트·다시 켜기는 앱 → start.py → 서버 → 도우미 → 이 스크립트로 이어져서 앱이 조상이에요. 맥 pgrep은 조상을 빼서 넣어 줘요.
running_pids() {
  re=$(printf '%s' "$1" | sed 's/[][\.*^$+?(){}|]/\\&/g')
  pgrep -a -f "^$re" 2>/dev/null || true
}

# 켜져 있으면 끄고 6초까지 기다려요. 다 꺼졌으면 성공.
# 앱은 종료 신호를 ⌘Q처럼 받아서 자기가 켠 서버까지 정리하고 꺼져요.
quit_running() {
  [ -n "$(running_pids "$1")" ] || return 0
  kill -TERM $(running_pids "$1") 2>/dev/null || true
  i=0
  while [ -n "$(running_pids "$1")" ] && [ "$i" -lt 60 ]; do sleep 0.1; i=$((i + 1)); done
  [ -z "$(running_pids "$1")" ]
}

# 예전 이름으로 만든 앱: 번들 ID가 우리 것일 때만 끄고 지워요. 다른 앱이면 그대로 둬요.
remove_old_name_app() {
  [ -e "$OLD_APP" ] || return 0
  that_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$OLD_APP/Contents/Info.plist" 2>/dev/null || true)
  if [ "$that_id" != "$OLD_ID" ]; then
    say "참고: $OLD_APP 는 우리가 만든 앱이 아니라서 그대로 뒀어요."
    return 0
  fi
  if ! quit_running "$OLD_APP/Contents/MacOS/ClaudeOffice"; then
    say "참고: 예전 이름의 앱($OLD_APP)이 꺼지지 않아서 그대로 뒀어요. ⌘Q로 끈 뒤 지워 주세요."
    return 0
  fi
  if rm -rf "$OLD_APP"; then
    say "· 예전 이름의 앱을 지웠어요: $OLD_APP (이제 $APP 를 써요)"
  else
    say "참고: 예전 이름의 앱($OLD_APP)을 지우지 못했어요. 직접 지워 주세요."
  fi
}

open_app() {
  if [ "$1" = restart ] && [ -n "$(running_pids "$EXE")" ]; then
    say "켜져 있던 앱을 끄고 새로 열어요."
    quit_running "$EXE" || say "참고: 켜져 있던 앱이 아직 꺼지지 않았어요. ⌘Q로 끈 뒤 다시 열어 주세요."
    sleep 0.3
  fi
  # OFFICE_PORT를 정했으면 이번에 여는 앱에도 넘겨요(start.py와 같은 뜻).
  if [ -n "${OFFICE_PORT:-}" ]; then
    open --env "OFFICE_PORT=$OFFICE_PORT" "$APP" || fail "앱을 열지 못했어요: $APP"
  else
    open "$APP" || fail "앱을 열지 못했어요: $APP"
  fi
  say "앱을 열었어요: $APP"
}

if [ "$IF_NEEDED" = yes ] && [ -x "$EXE" ] \
  && [ "$(cat "$APP/Contents/Resources/build_stamp.txt" 2>/dev/null || true)" = "$STAMP" ] \
  && codesign --verify "$APP" >/dev/null 2>&1; then
  say "앱이 이미 있어요: $APP"
  remove_old_name_app
  if [ "$REOPEN" = yes ]; then open_app restart; elif [ "$OPEN" = yes ]; then open_app keep; fi
  exit 0
fi

mkdir -p "$DEST" || fail "$DEST 폴더를 만들지 못했어요."
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t agencity-app) || fail "임시 폴더를 만들지 못했어요."
trap 'rm -rf "$TMP"' EXIT
trap 'exit 130' INT TERM
B="$TMP/Agencity.app"
mkdir -p "$B/Contents/MacOS" "$B/Contents/Resources"

say "맥 앱을 만드는 중이에요(처음엔 1분쯤 걸릴 수 있어요)…"
# 이 맥의 CPU용으로만, macOS 12 이상에서 돌게 컴파일해요.
if ! xcrun swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos12.0" \
  -o "$B/Contents/MacOS/Agencity" "$SRC" >"$TMP/swiftc.log" 2>&1; then
  tail -n 20 "$TMP/swiftc.log" >&2
  fail "컴파일하지 못했어요(위 기록). Xcode를 처음 깔았다면 sudo xcodebuild -license 로 사용권에 먼저 동의해야 할 수 있어요."
fi

cat >"$B/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>ko</string>
  <key>CFBundleDisplayName</key><string>Agencity</string>
  <key>CFBundleExecutable</key><string>Agencity</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleIdentifier</key><string>$ID</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Agencity</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHumanReadableCopyright</key><string>MIT License · github.com/Min-heee/agencity</string>
  <key>NSSupportsAutomaticTermination</key><false/>
  <key>NSSupportsSuddenTermination</key><false/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
EOF
printf 'APPL????' >"$B/Contents/PkgInfo"
printf '%s\n' "$HERE" >"$B/Contents/Resources/install_dir.txt"
printf '%s\n' "$STAMP" >"$B/Contents/Resources/build_stamp.txt"

# 아이콘: 앱이 직접 그린 PNG들을 icns로 묶어요. 안 되면 기본 아이콘으로 둬요.
if "$B/Contents/MacOS/Agencity" --make-iconset "$TMP/AppIcon.iconset" >/dev/null 2>&1 \
  && iconutil -c icns -o "$B/Contents/Resources/AppIcon.icns" "$TMP/AppIcon.iconset" >/dev/null 2>&1; then
  :
else
  say "참고: 아이콘은 건너뛰었어요(기본 아이콘으로 보여요)."
fi

codesign --force --deep -s - "$B" >"$TMP/codesign.log" 2>&1 || { cat "$TMP/codesign.log" >&2; fail "임시 서명을 하지 못했어요."; }

# 바꿔 넣기: 예전 앱은 옆으로 치웠다가 지워요(켜져 있는 앱은 다음에 열 때부터 새 앱이에요).
if [ -e "$APP" ]; then
  mv "$APP" "$TMP/old.app" || fail "예전 앱을 치우지 못했어요: $APP"
fi
if ! mv "$B" "$APP"; then
  [ -e "$TMP/old.app" ] && mv "$TMP/old.app" "$APP"
  fail "$APP 에 넣지 못했어요."
fi
touch "$APP"   # Finder가 새 아이콘을 보게
say "맥 앱을 만들었어요: $APP"
if [ -n "$OLD_DIR" ] && [ "$OLD_DIR" != "$HERE" ]; then
  say "· 앱이 여는 설치 폴더를 바꿨어요: $OLD_DIR → $HERE"
fi
remove_old_name_app
if [ "$OPEN" = yes ]; then
  open_app restart
else
  say "열기: open \"$APP\"  (Finder의 응용 프로그램 폴더나 Spotlight에서 Agencity)"
fi
