#!/bin/sh
# 클로드 오피스 설치하고 바로 켜기 (macOS·Linux)
#
#   curl -fsSL https://raw.githubusercontent.com/Min-heee/claude-office/main/install.sh | sh
#
# - 설치 위치: ~/claude-office (바꾸려면 ... | CLAUDE_OFFICE_DIR=~/다른/곳 sh)
# - 받을 버전: 최신 릴리스 (CLAUDE_OFFICE_REF=main 처럼 브랜치·태그를 고를 수 있어요)
# - 같은 폴더에 다시 실행하면 코드만 새로 받고, 내 팀 정보(org.json, teams/, hq/, outbox/, public.json,
#   claude-office.json)와 폴더 권한은 그대로 둬요.
# - git으로 받은 폴더나 클로드 오피스가 아닌 파일이 든 폴더에는 설치하지 않아요(git 폴더는 git pull로 새로 받아요).
# - 설치만 하고 켜지 않으려면 CLAUDE_OFFICE_NO_START=1
set -eu

# 내려받는 도중 끊기면 반쪽 스크립트가 실행되지 않도록 전체를 함수로 감싸고 맨 끝에서 불러요.
main() {

  REPO="Min-heee/claude-office"
  DIR="${CLAUDE_OFFICE_DIR:-$HOME/claude-office}"

  say() { printf '%s\n' "$*"; }
  warn() { printf '%s\n' "$*" >&2; }
  fail() { printf '설치하지 못했어요: %s\n' "$*" >&2; exit 1; }

  command -v python3 >/dev/null 2>&1 || fail "python3가 필요해요. 맥이면 터미널에서 xcode-select --install"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || fail "파이썬 3.9 이상이 필요해요."
  command -v jq >/dev/null 2>&1 || say "참고: jq가 없어요. 사이트 메시지 전달과 팀원 답장에 필요해요. 맥: brew install jq"

  # 이미 있는 폴더는 클로드 오피스 설치본일 때만 덮어써요.
  if [ -e "$DIR" ] && [ ! -d "$DIR" ]; then
    fail "$DIR 가 폴더가 아니에요."
  fi
  if [ -e "$DIR/.git" ] && [ "${CLAUDE_OFFICE_FORCE:-}" != 1 ]; then
    fail "$DIR 는 git으로 받은 폴더예요. git -C \"$DIR\" pull 로 새로 받아요. (그래도 덮어쓰려면 CLAUDE_OFFICE_FORCE=1)"
  fi
  if [ -d "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ] && [ ! -f "$DIR/office_server.py" ]; then
    fail "$DIR 에 다른 파일이 있어요. 빈 폴더나 새 위치를 CLAUDE_OFFICE_DIR 로 골라 주세요."
  fi

  TMP=$(mktemp -d 2>/dev/null || mktemp -d -t claude-office)
  trap 'rm -rf "$TMP"' EXIT INT TERM

  mkdir "$TMP/src"
  if [ -n "${CLAUDE_OFFICE_SRC:-}" ]; then
    # 시험용: 내려받지 않고 로컬 폴더를 임시 폴더로 복사해서 씀(원본은 건드리지 않음)
    cp -R "$CLAUDE_OFFICE_SRC" "$TMP/src/local" || fail "로컬 폴더를 복사하지 못했어요"
    SRC="$TMP/src/local"
  else
    command -v curl >/dev/null 2>&1 || fail "curl이 필요해요."
    REF="${CLAUDE_OFFICE_REF:-}"
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
      warn "참고: 최신 릴리스를 찾지 못해 main을 받아요. (CLAUDE_OFFICE_REF=v0.3.0 처럼 고를 수 있어요)"
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
  for x in org.json teams hq outbox public.json claude-office.json .git; do rm -rf "${SRC:?}/$x"; done
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
  chmod +x "$DIR/start.py" "$DIR/Claude Office.command" "$DIR"/bin/*.sh 2>/dev/null || true

  say "설치했어요: $DIR"
  say "다음에 켤 때: python3 \"$DIR/start.py\"  (맥은 \"$DIR/Claude Office.command\" 더블클릭)"
  say "내 팀 등록: python3 \"$DIR/bin/new_team.py\""
  if [ "${CLAUDE_OFFICE_NO_START:-}" = 1 ]; then exit 0; fi
  trap - EXIT INT TERM
  rm -rf "$TMP"
  exec python3 "$DIR/start.py" </dev/null
}

main "$@"
