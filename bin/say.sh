#!/bin/sh
# 사이트 대화 파일에 한 줄 남기기 (팀원·팀장·총괄의 답).
# 사용: say.sh <대화 파일> <보내는 사람> --file <답을 쓴 파일>
#   답 본문은 Write 도구로 대화 파일 옆 .out/<역할>.txt에 먼저 써요. 본문을 명령 줄에 넣지 않아야
#   팀 안전장치(훅)가 본문 낱말에 걸리지 않아요. (예전 방식: [내용] 또는 표준입력도 아직 돼요.)
set -eu
OFFICE=$(cd "$(dirname "$0")/.." && pwd -P)
[ $# -ge 2 ] || { echo "사용: say.sh <대화 파일> <보내는 사람> --file <답 파일>" >&2; exit 2; }
f=$1; who=$2; shift 2
case "$who" in 대표|"") echo "보내는 사람이 이상해요: $who" >&2; exit 1 ;; esac
case "$f" in *..*) echo "경로에 ..를 쓸 수 없어요" >&2; exit 1 ;; esac
dir=$(cd "$(dirname "$f")" 2>/dev/null && pwd -P) || { echo "대화 파일 폴더가 없어요: $f" >&2; exit 1; }
name=$(basename "$f")
# 허용: 총괄 대화(hq/chat.jsonl), 팀 사무실의 chat/<역할>.jsonl, meetings/<번호>.chat.jsonl
ok=no
hq=$(cd "$OFFICE/hq" 2>/dev/null && pwd -P || true)
if [ -n "$hq" ] && [ "$dir" = "$hq" ] && [ "$name" = chat.jsonl ]; then ok=yes; fi
for o in $(jq -r '.teams[] | select(.office) | .office' "$OFFICE/org.json"); do
  root=$(cd "$OFFICE/$o" 2>/dev/null && pwd -P) || continue
  case "$dir/$name" in
    "$root/chat/"*.jsonl) ok=yes ;;
    "$root/meetings/"*.chat.jsonl) ok=yes ;;
  esac
done
[ "$ok" = yes ] || { echo "사이트 대화 파일이 아니에요: $f" >&2; exit 1; }
if [ "${1:-}" = "--file" ]; then
  src=${2:-}
  case "$src" in *..*|"") echo "답 파일 경로가 이상해요" >&2; exit 1 ;; esac
  sdir=$(cd "$(dirname "$src")" 2>/dev/null && pwd -P) || { echo "답 파일이 없어요: $src" >&2; exit 1; }
  [ "$sdir" = "$dir/.out" ] || { echo "답 파일은 대화 파일 옆 .out/ 폴더에 둬요: $dir/.out/" >&2; exit 1; }
  text=$(cat "$src")
  rm -f "$src"
elif [ $# -gt 0 ]; then
  text=$*
else
  text=$(cat)
fi
[ -n "$text" ] || { echo "내용이 비었어요" >&2; exit 1; }
jq -nc --arg t "$(date -Iseconds)" --arg from "$who" --arg text "$text" '{t:$t,from:$from,text:$text}' >> "$dir/$name"
echo "사이트에 남겼어요: $dir/$name"
