#!/bin/sh
# 총괄이 outbox 항목을 전한 뒤 outbox/sent/로 옮겨요.
# 사용: relay_done.sh <outbox 파일> <결과>
#   결과가 delivered(전달됨)가 아니면(실패·보류·대기열 등) 그 대화 파일에 시스템 줄을 남겨 대표가 사이트에서 알 수 있게 해요.
set -eu
f=$1; r=${2:-delivered}
d=$(dirname "$f")/sent
mkdir -p "$d"
case "$r" in
  *delivered*|전달됨) ;;
  *)
    th=$(jq -r '.thread // empty' "$f")
    lb=$(jq -r '.label // ""' "$f")
    if [ -n "$th" ] && [ -f "$th" ]; then
      jq -nc --arg t "$(date -Iseconds)" --arg text "$lb · 전달 상태: $r" '{t:$t,from:"총괄",kind:"전달",text:$text}' >> "$th"
    fi
    ;;
esac
jq --arg r "$r" --arg t "$(date -Iseconds)" '. + {result:$r, done:$t}' "$f" > "$d/$(basename "$f").tmp" && mv "$d/$(basename "$f").tmp" "$d/$(basename "$f")" && rm -f "$f"
echo "정리: $(basename "$f") → sent ($r)"
