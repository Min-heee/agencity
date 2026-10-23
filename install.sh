#!/bin/sh
# 에이전시티(Agencity) 설치하고 바로 켜기 (macOS·Linux)
#
#   curl -fsSL https://raw.githubusercontent.com/Min-heee/agencity/main/install.sh | sh
#
# - 설치 위치: ~/agencity (바꾸려면 ... | AGENCITY_DIR=~/다른/곳 sh)
# - 받을 버전: 최신 릴리스 (AGENCITY_REF=main 처럼 브랜치·태그를 고를 수 있어요)
# - 같은 폴더에 다시 실행하면 코드만 새로 받고, 내 팀 정보(org.json, teams/, hq/, outbox/, public.json,
#   agencity.json, setup.json)와 앱 안 업데이트 기록(.update/), 폴더 권한은 그대로 둬요.
# - git으로 받은 폴더나 에이전시티가 아닌 파일이 든 폴더에는 설치하지 않아요(git 폴더는 git pull로 새로 받아요).
# - 맥: 명령어 도구(swiftc)가 있으면 이 맥에서 앱(~/Applications/Agencity.app)을 만들어 브라우저 대신 앱으로 열어요.
#   앱 위치는 AGENCITY_APP_DEST, 예전처럼 브라우저로 켜려면 AGENCITY_NO_APP=1. 리눅스는 브라우저로 켜요.
# - 설치만 하고 켜지 않으려면 AGENCITY_NO_START=1 (맥 앱도 만들지 않고 만드는 법만 알려 줘요)
# - 예전 이름: 클로드 오피스(Claude Office). AGENCITY_DIR를 정하지 않았고 ~/agencity가 없는데 예전 기본 위치
#   ~/claude-office에 내려받은 설치본(git 폴더 아님)이 있으면, 그 폴더를 그 자리에서 새로 받아요.
set -eu

# 내려받는 도중 끊기면 반쪽 스크립트가 실행되지 않도록 전체를 함수로 감싸고 맨 끝에서 불러요.
main() {

  say() { printf '%s\n' "$*"; }
  warn() { printf '%s\n' "$*" >&2; }
  fail() { printf '설치하지 못했어요: %s\n' "$*" >&2; exit 1; }

  # 예전 README의 설치 줄(예전 이름의 환경 변수)도 받아요.
  if [ -z "${AGENCITY_DIR:-}" ] && [ -n "${CLAUDE_OFFICE_DIR:-}" ]; then AGENCITY_DIR=$CLAUDE_OFFICE_DIR; fi
  if [ -z "${AGENCITY_REF:-}" ] && [ -n "${CLAUDE_OFFICE_REF:-}" ]; then AGENCITY_REF=$CLAUDE_OFFICE_REF; fi

  REPO="Min-heee/agencity"
  DIR="${AGENCITY_DIR:-$HOME/agencity}"
  # 예전 기본 위치에 내려받은 설치본이 있고 새 위치가 아직 없으면, 옮기지 않고 그 자리에서 새로 받아요.
  if [ -z "${AGENCITY_DIR:-}" ] && [ ! -e "$HOME/agencity" ] && [ -d "$HOME/claude-office" ] \
    && [ -f "$HOME/claude-office/office_server.py" ] && [ ! -e "$HOME/claude-office/.git" ]; then
    DIR="$HOME/claude-office"
    say "예전 이름(클로드 오피스)의 설치본이 있어서 그 자리($DIR)에서 새로 받아요."
  fi

  # 맥: 명령어 도구가 없으면 /usr/bin/python3는 설치 창만 띄우는 자리라 파이썬이 없는 것과 같아요
  if [ "$(uname -s)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1 && [ "$(command -v python3 2>/dev/null)" = /usr/bin/python3 ]; then
    fail "명령어 도구가 필요해요: xcode-select --install 을 실행한 뒤 다시 설치해 주세요 (또는 python.org 파이썬)"
  fi
  command -v python3 >/dev/null 2>&1 || fail "python3가 필요해요. 맥이면 터미널에서 xcode-select --install"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || fail "파이썬 3.9 이상이 필요해요."
  command -v jq >/dev/null 2>&1 || say "참고: jq가 없어요. 사이트 메시지 전달과 팀원 답장에 필요해요. 맥: brew install jq"

  # 이미 있는 폴더는 에이전시티 설치본일 때만 덮어써요.
  if [ -e "$DIR" ] && [ ! -d "$DIR" ]; then
    fail "$DIR 가 폴더가 아니에요."
  fi
  if [ -e "$DIR/.git" ] && [ "${AGENCITY_FORCE:-}" != 1 ]; then
    fail "$DIR 는 git으로 받은 폴더예요. git -C \"$DIR\" pull 로 새로 받아요. (그래도 덮어쓰려면 AGENCITY_FORCE=1)"
  fi
  if [ -d "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ] && [ ! -f "$DIR/office_server.py" ]; then
    fail "$DIR 에 다른 파일이 있어요. 빈 폴더나 새 위치를 AGENCITY_DIR 로 골라 주세요."
  fi

  TMP=$(mktemp -d 2>/dev/null || mktemp -d -t agencity)
  trap 'rm -rf "$TMP"' EXIT INT TERM

  mkdir "$TMP/src"
  if [ -n "${AGENCITY_SRC:-}" ]; then
    # 시험용: 내려받지 않고 로컬 폴더를 임시 폴더로 복사해서 씀(원본은 건드리지 않음)
    cp -R "$AGENCITY_SRC" "$TMP/src/local" || fail "로컬 폴더를 복사하지 못했어요"
    SRC="$TMP/src/local"
  else
    command -v curl >/dev/null 2>&1 || fail "curl이 필요해요."
    REF="${AGENCITY_REF:-}"
    if [ -z "$REF" ]; then
      # 최신 릴리스: releases/latest가 넘겨 주는 태그 주소에서 읽어요(API 호출 한도에 걸리지 않아요)
      u=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest" 2>/dev/null || true)
      case "$u" in */releases/tag/*) REF=${u##*/} ;; esac
    fi
    if [ -z "$REF" ]; then
      REF=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tag_name", "") if isinstance(d, dict) else "")' 2>/dev/null || true)
    fi
    if [ -z "$REF" ]; then
      REF=main
      warn "참고: 최신 릴리스를 찾지 못해 main을 받아요. (AGENCITY_REF=v0.4.0 처럼 고를 수 있어요)"
    fi
    case "$REF" in *[!A-Za-z0-9._/-]*) fail "버전 이름이 이상해요: $REF" ;; esac
    say "받는 중: $REPO ($REF)"
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$TMP/src.tgz" || fail "내려받기 실패"
    tar -xzf "$TMP/src.tgz" -C "$TMP/src" || fail "압축 풀기 실패"
    SRC=$(find "$TMP/src" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    [ -n "$SRC" ] && [ -f "$SRC/office_server.py" ] || fail "받은 파일이 이상해요"
  fi

  # 코드만 덮어써요. 받은 임시 사본의 맨 위에서 내 정보 자리(있을 리 없지만)를 먼저 지운 뒤 통째로 복사해요.
  # (tar --exclude는 하위 폴더 이름까지 걸러서 examples/teams 같은 것도 빠지므로 쓰지 않아요.)
  # .update/는 앱 안 업데이트의 진행 상태·기록, .usage/는 사용량 알림의 기억이에요(받은 사본에 있으면 덮어쓰지 않게 빼요). 설치 폴더의 것은 지우지 않아요.
  for x in org.json teams hq outbox public.json agencity.json claude-office.json setup.json .update .usage .git; do rm -rf "${SRC:?}/$x"; done
  # GNU tar는 './'의 권한을 설치 폴더에 덮어쓰므로, 원래 권한(예: chmod 700)을 기억했다가 되돌려요.
  OLD_MODE=
  if [ -d "$DIR" ]; then
    OLD_MODE=$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o7777))' "$DIR" 2>/dev/null || true)
  fi
  mkdir -p "$DIR"
  (cd "$SRC" && tar -cf - .) | (cd "$DIR" && tar -xf -) || fail "복사하지 못했어요"
  if [ -n "$OLD_MODE" ]; then
    python3 -c 'import os,sys; os.chmod(sys.argv[1], int(sys.argv[2], 8))' "$DIR" "$OLD_MODE" || true
  fi
  chmod +x "$DIR/start.py" "$DIR/Agencity.command" "$DIR"/bin/*.sh 2>/dev/null || true
  # 예전 이름의 더블클릭 파일은 Agencity.command로 바뀌었어요. 예전 판에서 받은 게 남아 있으면 지워요.
  if [ -f "$DIR/Claude Office.command" ] && [ ! -L "$DIR/Claude Office.command" ]; then
    rm -f "$DIR/Claude Office.command" && say "· 예전 이름의 더블클릭 파일을 지웠어요. 이제 Agencity.command를 써요."
  fi

  say "설치했어요: $DIR"

  # 맥: 이 맥에서 앱을 만들어(서명 계정 필요 없음) 앱으로 열어요. 못 만들면 아래처럼 브라우저로 켜요.
  if [ "$(uname -s)" = Darwin ] && [ "${AGENCITY_NO_APP:-}" != 1 ]; then
    if xcode-select -p >/dev/null 2>&1 && xcrun --find swiftc >/dev/null 2>&1; then
      if [ "${AGENCITY_NO_START:-}" = 1 ]; then
        say "맥 앱 만들기: sh \"$DIR/bin/make_mac_app.sh\" --open"
      elif sh "$DIR/bin/make_mac_app.sh" --open </dev/null; then
        say "다음에 켤 때: 응용 프로그램 폴더(${AGENCITY_APP_DEST:-~/Applications})의 Agencity 앱을 열어요. 끄려면 앱에서 ⌘Q."
        exit 0
      else
        warn "앱을 만들지 못해서 브라우저로 켜요."
      fi
    else
      say "참고: 프로그램(맥 앱)으로 쓰려면 xcode-select --install 로 명령어 도구를 설치한 뒤 sh \"$DIR/bin/make_mac_app.sh\" --open"
    fi
  fi
  say "다음에 켤 때: python3 \"$DIR/start.py\"  (맥은 \"$DIR/Agencity.command\" 더블클릭)"
  say "내 팀 등록: 켜면 뜨는 설정 화면에서 해요(나중에는 사무실 위쪽 ‘설정’)"
  if [ "${AGENCITY_NO_START:-}" = 1 ]; then exit 0; fi
  trap - EXIT INT TERM
  rm -rf "$TMP"
  exec python3 "$DIR/start.py" </dev/null
}

main "$@"
