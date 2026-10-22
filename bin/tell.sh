#!/bin/sh
# 다른 층 팀장에게 보내는 팀 간 대화를 남기고, 보낼 곳을 알려 줘요(팀장만 써요).
# 사용: tell.sh <상대 층 id> --from <내 층 id> --role <내 역할> --file <보낼 글을 쓴 파일>
#       tell.sh --list        층 id와 층 이름 목록(예시 팀은 빼요)
#   보낼 글은 Write 도구로 <에이전시티>/hq/.out/tell-<내 층 id>.txt에 먼저 써요. 본문을 명령 줄에 넣지 않아야
#   팀 안전장치(훅)가 본문 낱말에 걸리지 않아요. 그 파일은 읽은 뒤 지워요.
#   대화는 <에이전시티>/hq/teams.jsonl에 한 줄로 남겨요(사이트의 '팀 간 대화'가 이 파일을 보여 줘요).
#   잘 되면 딱 두 줄을 찍어요:
#     SEND_TO=<상대 층 팀장 세션 id>
#     HEADER=[협업·<내 층 이름>→<상대 층 이름>]
#   그다음 내가 SendMessage(to = SEND_TO)로 HEADER 줄과 보낼 글을 보내요. 이 스크립트는 메시지를 보내지 않아요.
#   지금은 팀장만 보낼 수 있어요(대표가 나중에 '누구나'를 켤 수 있게 남겨 둔 자리예요).
set -eu
command -v jq >/dev/null 2>&1 || { echo "jq가 필요해요. 맥: brew install jq, 리눅스: sudo apt install jq" >&2; exit 1; }
OFFICE=$(cd "$(dirname "$0")/.." && pwd -P)
ORG="$OFFICE/org.json"
MAX=4000
die() { echo "$*" >&2; exit 1; }
usage() { echo "사용: tell.sh <상대 층 id> --from <내 층 id> --role <내 역할> --file <보낼 글 파일>   (층 목록: tell.sh --list)" >&2; exit 2; }
[ -f "$ORG" ] || die "org.json이 없어요: $ORG"
# 화면에 보일 이름: 줄바꿈·제어 문자는 빼요(HEADER가 꼭 한 줄이게)
CLEAN='gsub("[\u0000-\u001f\u007f  ‪-‮⁦-⁩]"; "")'

if [ "${1:-}" = "--list" ]; then
  jq -r '.teams[]? | select(type == "object" and (.office | type) == "string" and .office != "" and (.office | startswith("examples/") | not))
         | "\(.id)\t\((.name // .id) | tostring | '"$CLEAN"')"' "$ORG"
  exit 0
fi

[ $# -ge 1 ] || usage
to=$1; shift
from=""; role=""; src=""
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || usage
  case "$1" in
    --from) from=$2 ;;
    --role) role=$2 ;;
    --file) src=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[ -n "$from" ] && [ -n "$role" ] && [ -n "$src" ] || usage

# 층 id 모양(office_server.py의 SAFE_ID와 같아요, ..는 안 돼요)
for id in "$to" "$from"; do
  case "$id" in *..*) die "층 id가 이상해요: $id" ;; esac
  jq -en --arg v "$id" '$v | test("\\A[0-9A-Za-z가-힣._-]{1,80}\\z")' >/dev/null 2>&1 || die "층 id가 이상해요: $id"
done
[ "$to" != "$from" ] || die "내 층에는 tell.sh로 보내지 않아요. 같은 층 팀원과는 바로 [협업]으로 주고받아요"

# 보내는 사람: 역할 이름 모양(say.sh와 같아요), 대표·총괄은 안 되고, 지금은 팀장만
case "$role" in 대표|총괄|"") die "보내는 사람이 이상해요: $role (대표·총괄은 tell.sh를 쓰지 않아요)" ;; esac
jq -en --arg w "$role" '$w | test("\\A[0-9A-Za-z가-힣][0-9A-Za-z가-힣_·-]{0,11}\\z")' >/dev/null 2>&1 ||
  die "보내는 사람이 이상해요(역할 이름이어야 해요): $role"
[ "$role" = "팀장" ] || die "팀 간 대화는 팀장만 보내요(지금은 ‘${role}’). 다른 층에 할 말이 있으면 내 층 팀장에게 [협업]으로 부탁해요"

# 층 찾기: org.json에서 사무실이 있는 층, 예시 팀은 빼요
floor_of() {
  jq -c --arg id "$1" '[.teams[]? | select(type == "object" and .id == $id and (.office | type) == "string" and .office != "")][0] // empty' "$ORG"
}
office_dir() {   # 층 줄(JSON) → 팀 사무실 실제 경로. 설치 폴더를 품는 곳(링크로 잘못 이어진 사무실)은 안 돼요
  o=$(printf '%s' "$1" | jq -r '.office')
  case "$o" in *..*) return 1 ;; examples/*) return 1 ;; /*) p=$o ;; *) p=$OFFICE/$o ;; esac
  r=$(cd "$p" 2>/dev/null && pwd -P) || return 1
  case "$OFFICE/" in "$r/"*) return 1 ;; esac
  [ -f "$r/team.json" ] || return 1
  printf '%s' "$r"
}
fj=$(floor_of "$from"); [ -n "$fj" ] || die "내 층을 org.json에서 찾지 못했어요: $from (층 목록: tell.sh --list)"
tj=$(floor_of "$to"); [ -n "$tj" ] || die "상대 층을 org.json에서 찾지 못했어요: $to (층 목록: tell.sh --list)"
case "$(printf '%s' "$fj" | jq -r '.office')" in examples/*) die "예시 팀은 팀 간 대화를 하지 않아요" ;; esac
case "$(printf '%s' "$tj" | jq -r '.office')" in examples/*) die "예시 팀에는 보낼 수 없어요" ;; esac
froot=$(office_dir "$fj") || die "내 층의 팀 사무실(team.json)을 읽지 못했어요: $from"
troot=$(office_dir "$tj") || die "상대 층의 팀 사무실(team.json)을 읽지 못했어요: $to"
fname=$(printf '%s' "$fj" | jq -r '(.name // .id) | tostring | '"$CLEAN")
tname=$(printf '%s' "$tj" | jq -r '(.name // .id) | tostring | '"$CLEAN")

SID='test("\\Alocal_[0-9a-f-]{8,64}\\z") and (startswith("local_00000000") | not)'
mine=$(jq -c --arg r "$role" '[.members[]? | select(type == "object" and .role == $r)][0] // empty' "$froot/team.json") ||
  die "내 층의 team.json을 읽지 못했어요"
[ -n "$mine" ] || die "내 층에 ‘${role}’ 자리가 없어요"
printf '%s' "$mine" | jq -e '(.sessionId // "") | '"$SID" >/dev/null 2>&1 || die "내 층 ‘${role}’ 자리에 세션이 앉아 있지 않아요"
msid=$(printf '%s' "$mine" | jq -r '.sessionId')
sname=$(printf '%s' "$mine" | jq -r --arg d "$fname $role" '(if (.name | type) == "string" and .name != "" then .name else $d end) | '"$CLEAN"' | .[0:40]')
tsid=$(jq -r '[.members[]? | select(type == "object" and .role == "팀장")][0].sessionId // ""' "$troot/team.json") ||
  die "상대 층의 team.json을 읽지 못했어요"
jq -en --arg v "$tsid" '$v | '"$SID" >/dev/null 2>&1 || die "‘${tname}’ 층 팀장 자리에 세션이 앉아 있지 않아요"
[ "$tsid" != "$msid" ] || die "상대 층 팀장이 나와 같은 세션이에요. team.json을 확인해 주세요"

# 보낼 글 파일: hq/.out/ 안의 보통 파일만(say.sh처럼 대화 파일 옆 .out/)
case "$src" in *..*) die "보낼 글 파일 경로에 ..를 쓸 수 없어요" ;; esac
outd=$(cd "$OFFICE/hq/.out" 2>/dev/null && pwd -P) || die "보낼 글 파일은 Write 도구로 $OFFICE/hq/.out/ 폴더에 먼저 써요"
sdir=$(cd "$(dirname "$src")" 2>/dev/null && pwd -P) || die "보낼 글 파일이 없어요: $src"
[ "$sdir" = "$outd" ] || die "보낼 글 파일은 $OFFICE/hq/.out/ 폴더에 둬요"
[ -f "$src" ] && [ ! -L "$src" ] || die "보낼 글 파일이 없어요: $src"
text=$(cat "$src")
[ -n "$text" ] || die "보낼 글이 비었어요"
jq -en --arg t "$text" --argjson n "$MAX" '$t | length <= $n' >/dev/null 2>&1 || die "보낼 글이 너무 길어요(${MAX}자까지). 줄여서 다시 써 주세요"

mkdir -p "$OFFICE/hq"
jq -nc --arg t "$(date -Iseconds)" --arg ff "$from" --arg fr "$role" --arg nm "$sname" --arg fn "$fname" \
  --arg tf "$to" --arg tn "$tname" --arg text "$text" \
  '{t: $t, from: {floor: $ff, role: $fr, name: $nm, floorName: $fn}, to: {floor: $tf, role: "팀장", floorName: $tn}, text: $text}' \
  >> "$OFFICE/hq/teams.jsonl"
rm -f "$src"
printf 'SEND_TO=%s\nHEADER=[협업·%s→%s]\n' "$tsid" "$fname" "$tname"
