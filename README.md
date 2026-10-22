<div align="center">

# 에이전시티 (Agencity)

**내 AI 에이전시를 꾸리고, 도시 위로 한 층씩 올려요.**

Claude Code 세션들을 팀으로 묶어, 팀마다 사무실 한 층으로 보여 줘요.<br>
누가 무슨 일을 하는지 한눈에 보고, 한 화면에서 말 걸고 회의하고 결재해요.

[설치](#설치) · [처음 켜면](#처음-켜면) · [사용 안내서](docs/GUIDE.md) · [English](#english)

</div>

![에이전시티 사무실 화면](docs/screenshot.jpg)

## 이런 걸 해요

- **한눈에 보기**: 층마다 책상·회의실·업무판·보고서가 있어요. 책상에는 세션 상태와 하는 일이 떠요.
- **팀은 내 마음대로**: 세션을 팀장·팀원 자리에 앉히고, 역할 이름은 직접 지어요. 빈자리는 **세션 만들기**로 바로 채워요.
- **바로 대화**: 책상을 누르면 그 세션과 대화해요. 답도 같은 화면에 올라와요.
- **회의**: 내가 같이 하거나(참석), 팀에 맡기고 회의록으로 받아요(위임).
- **결재**: 팀장이 올린 결재를 결재함에서 고르면 그 팀장에게 바로 전해져요.
- **팀끼리**: 팀장끼리 다른 층과 이야기해요. 주고받은 말은 화면의 **팀 간 대화**에 남아요.

지금은 Claude Code와 함께 써요. Codex·Gemini CLI는 앞으로 지원해요.

## 설치

macOS·Linux 터미널에 붙여 넣어요. `~/agencity`에 설치하고 바로 켜요.

```bash
curl -fsSL https://raw.githubusercontent.com/Min-heee/agencity/main/install.sh | sh
```

- **필요한 것**: 파이썬 3.9 이상, `jq`, Claude Code 데스크톱 앱
- **맥 앱**: Xcode 명령어 도구가 있으면 Agencity 앱 창으로, 없으면 브라우저로 열려요.
- **업데이트**: 새 버전이 나오면 화면 위에 알림이 떠요. **업데이트**를 누르면 팀 정보는 그대로 두고 코드만 새로 받아요.

zip·git으로 받기와 설치 옵션은 [사용 안내서](docs/GUIDE.md#설치)에 있어요.

## 처음 켜면

1. **설정 화면이 떠요.** 먼저 둘러보려면 **나중에 하기**를 눌러요. 예시 팀으로 열려요.
2. **층을 만들어요.** 이 맥의 Claude Code 세션이 Claude 앱 사이드바 모양 그대로 보여요. 그룹이나 세션을 골라 **층으로**를 누르고, 역할과 총괄 세션을 정해요.
3. **팀 규칙을 이어요.** 완료 화면에 나온 한 줄을 안내대로 `CLAUDE.local.md`에 넣어요. 팀 세션들이 팀 규칙을 읽게 돼요.
4. **총괄을 켜요.** 총괄 세션에 [이 지시](docs/COORDINATOR.md)를 설치 폴더 경로만 바꿔 한 번 붙여 넣어요. 화면에서 보낸 말을 이 세션이 팀에 전해 줘요.

Claude는 따로 로그인하지 않아요. GitHub 로그인과 도시 공개는 원할 때만 해요.
설정은 사무실 위쪽 **설정**에서 언제든 다시 열어요. [단계별 설명 →](docs/GUIDE.md#처음-설정)

## 에이전시티 도시

![에이전시티 도시](docs/city.jpg)

등록한 사람마다 **토큰 작업량만큼 높은 건물**이 서요. 건물을 누르면 주인이 공개한 층만 읽기 전용으로 둘러봐요.

- 사무실 위쪽 **도시 보기 →**로 열어요.
- 기본은 비공개예요. 올리려면 [token-meter](https://github.com/Min-heee/token-meter)로 내 숫자를 먼저 올리고, GitHub에 연결한 뒤 **설정 → 공개 범위**에서 골라요.

[도시 안내](docs/GUIDE.md#에이전시티-도시) · [앞으로의 계획](docs/VISION.md)

## 안전하게

- 내 컴퓨터(`127.0.0.1`)에서만 열려요. Claude 앱에서는 세션 목록과 그룹만 읽고, 대화 내용은 읽지 않아요. 세션 만들기로 연 새 세션만 첫 메시지에서 자리 표시를 찾아요.
- 화면에서 보낸 말은 승인으로 쓰이지 않아요. 커밋·배포·결제는 그 세션 창에서 내가 직접 확인해요.
- 도시에는 내가 확인한 것만 올라가요. 대화·결재·보고서 원문은 올리지 않아요.

[보안 자세히 보기 →](docs/GUIDE.md#보안)

## 더 알아보기

| 문서 | 내용 |
|---|---|
| [사용 안내서](docs/GUIDE.md) | 설치·업데이트, 처음 설정, 회의와 결재, 세션 만들기와 팀 간 대화, 도시, 보안 |
| [총괄 세션 설정](docs/COORDINATOR.md) | 화면에서 보낸 말을 팀에 전하는 세션 켜기 |
| [팀 규칙](docs/TEAM_RULES.md) | 팀 세션이 따르는 규칙 |
| [도시 계획](docs/VISION.md) | 에이전시티 도시가 나아갈 방향 |

v0.3.1까지는 클로드 오피스(Claude Office)라는 이름이었어요. 라이선스는 [MIT](LICENSE)예요.

## English

**Agencity**: run your AI agency, and raise it into the skyline.
A local dashboard that seats your Claude Code desktop sessions as teams, one office floor per team.
From one page you can message any session, run meetings, and approve what team leads file.
An empty seat can open a new session through a `claude://` link and gets it seated once you press Enter; team leads talk across floors, and every exchange is logged on the page.
A coordinator session relays messages with Claude Code's own `SendMessage` tool; the page never types into sessions.
Needs macOS or Linux, Python 3.9+, `jq` and the Claude Code desktop app. Codex and Gemini CLI support is planned. The UI is in Korean. Formerly Claude Office (until v0.3.1).

```bash
curl -fsSL https://raw.githubusercontent.com/Min-heee/agencity/main/install.sh | sh
```
