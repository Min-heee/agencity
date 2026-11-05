#!/bin/sh
# 사이트 대화 파일에 한 줄 남기기 (팀원·팀장·총괄의 답).
# 사용: say.sh <대화 파일> <보내는 사람> --file <답을 쓴 파일> [--image <.out의 사진>]…
#   보내는 사람은 내 역할 이름(층마다 달라요: 팀장·개발자·마케팅…) 또는 총괄이에요. 대표는 안 돼요.
#   답 본문은 Write 도구로 대화 파일 옆 .out/<역할>.txt에 먼저 써요. 본문을 명령 줄에 넣지 않아야
#   팀 안전장치(훅)가 본문 낱말에 걸리지 않아요. (예전 방식: [내용] 또는 표준입력도 아직 돼요.)
#   사진은 --image로 붙여요(4장까지, 글 없이도 돼요). 글만 있는 길은 파이썬을 부르지 않아요. 답 남기기가 가장 튼튼해야 해서요.
set -eu
command -v jq >/dev/null 2>&1 || { echo "jq가 필요해요. 맥: brew install jq, 리눅스: sudo apt install jq" >&2; exit 1; }
OFFICE=$(cd "$(dirname "$0")/.." && pwd -P)
[ $# -ge 2 ] || { echo "사용: say.sh <대화 파일> <보내는 사람> --file <답 파일>" >&2; exit 2; }
f=$1; who=$2; shift 2
case "$who" in 대표|"") echo "보내는 사람이 이상해요: $who" >&2; exit 1 ;; esac
# 역할 이름 규칙(office_server.py의 ROLE_RE와 같아요): 한글·영문·숫자로 12자까지, 빈칸·/·. 없이(_ · - 는 돼요)
jq -en --arg w "$who" '$w | test("\\A[0-9A-Za-z가-힣][0-9A-Za-z가-힣_·-]{0,11}\\z")' >/dev/null 2>&1 ||
  { echo "보내는 사람이 이상해요(역할 이름이나 총괄이어야 해요): $who" >&2; exit 1; }
case "$f" in *..*) echo "경로에 ..를 쓸 수 없어요" >&2; exit 1 ;; esac
dir=$(cd "$(dirname "$f")" 2>/dev/null && pwd -P) || { echo "대화 파일 폴더가 없어요: $f" >&2; exit 1; }
name=$(basename "$f")
# 허용: 총괄 대화(hq/chat.jsonl), 팀 사무실의 chat/<역할>.jsonl, meetings/<번호>.chat.jsonl
ok=no
store=
hq=$(cd "$OFFICE/hq" 2>/dev/null && pwd -P || true)
if [ -n "$hq" ] && [ "$dir" = "$hq" ] && [ "$name" = chat.jsonl ]; then ok=yes; store=$hq; fi
for o in $(jq -r '.teams[] | select(.office) | .office' "$OFFICE/org.json"); do
  root=$(cd "$OFFICE/$o" 2>/dev/null && pwd -P) || continue
  case "$dir/$name" in
    "$root/chat/"*.jsonl) ok=yes; store=$root ;;
    "$root/meetings/"*.chat.jsonl) ok=yes; store=$root ;;
  esac
done
[ "$ok" = yes ] || { echo "사이트 대화 파일이 아니에요: $f" >&2; exit 1; }
# 답 파일은 대화 파일 옆 .out/의 보통 파일만 받아요. 링크를 따라가면 다른 파일 내용이 대화에 남아요
check_src() {
  case "$1" in *..*|"") echo "답 파일 경로가 이상해요" >&2; exit 1 ;; esac
  sdir=$(cd "$(dirname "$1")" 2>/dev/null && pwd -P) || { echo "답 파일이 없어요: $1" >&2; exit 1; }
  [ "$sdir" = "$dir/.out" ] || { echo "답 파일은 대화 파일 옆 .out/ 폴더에 둬요: $dir/.out/" >&2; exit 1; }
  [ -n "$(find "$1" -prune -type f -links 1 2>/dev/null)" ] || { echo "답 파일은 링크가 아닌 보통 파일이어야 해요: $1" >&2; exit 1; }
}
# 사진이 있을 때만 이 길을 타요. 글 파일 검사 → 사진 전부 검사 → 저장 → 줄 추가 → 원본 지우기 순서라, 거절되면 글과 사진이 남아요
image=no
case "${1:-}" in
  --file|--image) for a in "$@"; do if [ "$a" = --image ]; then image=yes; fi; done ;;
esac
if [ "$image" = yes ]; then
  command -v python3 >/dev/null 2>&1 || { echo "사진을 남기려면 python3이 필요해요" >&2; exit 1; }
  src=
  n=$#
  while [ "$n" -gt 0 ]; do
    [ "$n" -ge 2 ] || { echo "$1 뒤에 파일을 적어요" >&2; exit 2; }
    case "$1" in
      --file) src=$2 ;;
      --image) set -- "$@" "$2" ;;
      *) echo "모르는 인자예요: $1" >&2; exit 2 ;;
    esac
    shift 2; n=$((n-2))
  done   # 끝나면 "$@"에는 사진 경로만 남아요
  text=
  if [ -n "$src" ]; then check_src "$src"; text=$(cat "$src"); fi
  names=$(python3 -I "$OFFICE/bin/chat_image.py" "$store" "$dir/.out" "$@") || exit 1
  [ -n "$text" ] || text="사진 $#장"
  jq -nc --arg t "$(date -Iseconds)" --arg from "$who" --arg text "$text" --argjson img "$names" '{t:$t,from:$from,text:$text,img:$img}' >> "$dir/$name"
  if [ -n "$src" ]; then rm -f "$src"; fi
  rm -f -- "$@"
  echo "사이트에 남겼어요: $dir/$name"
  exit 0
fi
src=
if [ "${1:-}" = "--file" ]; then
  src=${2:-}
  check_src "$src"
  text=$(cat "$src")
elif [ $# -gt 0 ]; then
  text=$*
else
  text=$(cat)
fi
[ -n "$text" ] || { echo "내용이 비었어요" >&2; exit 1; }
jq -nc --arg t "$(date -Iseconds)" --arg from "$who" --arg text "$text" '{t:$t,from:$from,text:$text}' >> "$dir/$name"
# 줄을 남긴 뒤에 답 파일을 지워요. 남기기가 실패하면(set -e로 여기 오지 않아요) 답 파일이 그대로 남아 다시 보낼 수 있어요
if [ -n "$src" ]; then rm -f "$src"; fi
echo "사이트에 남겼어요: $dir/$name"
