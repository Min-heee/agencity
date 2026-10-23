# 앞으로의 계획: 에이전시티 도시

> **English summary.** Today Agencity is a private, local dashboard (it seats Claude Code sessions, and
> Codex sessions as read-only seats; Gemini CLI is planned). The plan is a shared, opt-in city, the Agencity city: everyone who
> registers their office gets one building whose height grows with their
> token usage, and whose floors are their teams. Clicking a building flies the camera to it and
> opens a card; if the owner has made floors public, visitors can walk through a read-only view of what
> that person's teams are working on. Nothing is public by default, and raw chats, approvals, reports,
> paths and session ids are never published. Token numbers are counted locally and published by the owner,
> who joins the [city member list](https://github.com/Min-heee/token-meter).
> Inspired by [Git City](https://github.com/srizzon/git-city) — ideas only; it is AGPL-3.0, so we write our own code under MIT.

## 한 줄로

사람마다 자기 에이전시티 사무실을 등록하면 **토큰 사용량만큼 높은 빌딩**이 하나씩 서는 도시를 만들어요.
빌딩을 누르면, 그 사람이 **공개해 둔 것만** 들여다보고 사무실을 둘러볼 수 있어요.
GitHub 활동을 3D 도시로 보여 주는 [Git City](https://github.com/srizzon/git-city)(thegitcity.com)에서 영감을 받았어요.

## 왜 만들고 싶나요

- 에이전시티는 지금 한 사람이 자기 팀을 보는 화면이에요. 팀은 지금 Claude Code 세션으로 꾸리고, Codex 세션은 읽기 전용 자리로 앉혀요. Gemini CLI는 앞으로 함께 앉힐 수 있게 할 거예요.
- 다른 사람들은 AI 에이전트로 어떤 팀을 꾸려 무슨 일을 하는지 **구경하고 배우는 공간**을 만들고 싶어요.
- "이 사람은 앱 세 개를 팀 셋으로 굴리네", "이 건물은 밤에도 불이 켜져 있네"처럼 둘러보는 재미가 있게요.

## 어떻게 보이나요

| 도시에서 | 무엇을 나타내나요 |
|---|---|
| 건물 하나 | 한 사람의 에이전시티 사무실 |
| 건물 높이 | 토큰 사용량(입력+출력+캐시 쓰기 중심, 캐시 읽기는 가볍게). 로그·거듭제곱 곡선으로 줄여서, 많이 쓰는 몇 명이 도시를 덮지 않게 최소·최대 높이와 상한을 둬요 |
| 층 | 그 사람의 팀. 사무실의 1층·2층·3층이 그대로 건물의 층이 돼요 |
| 창문 불빛 | 최근 7~30일에 활동한 날, 지금 일하는 세션이 있으면 그 층에 불이 켜져요 |
| 구역(동네) | 주로 하는 일(앱, 웹, 데이터, 콘텐츠 자동화 등). 본인이 고르거나 공개 프로젝트에서 정해요 |
| 도심과의 거리 | 쌓인 활동(가입 기간, 누적 사용량)으로만 정해서, 잠깐 쉬어도 바깥으로 밀려나지 않게 해요 |

## 건물을 누르면

1. 카메라가 그 건물로 날아가고, 나머지 건물은 흐려져요.
2. 옆에 카드가 열려요: 공개 프로필, 토큰 규모(정확한 숫자 대신 등급), 층(팀) 이름, 공개한 프로젝트 소개, 응원(+1), 비교하기.
3. **사무실 들어가기**를 누르면, 주인이 공개해 둔 층만 **읽기 전용**으로 둘러봐요.
   - 볼 수 있는 것: 책상별 상태(일하는 중·대기)와 "지금 하는 일" 한 줄, 업무판 제목, 공개용으로 따로 쓴 소개.
   - 절대 안 보이는 것: 대화, 결재, 보고서 원문, 파일 경로, 세션 id, 프롬프트.

## 공개 범위 (기본은 비공개, 본인이 직접 켬)

| 단계 | 도시에 보이는 것 |
|---|---|
| 0. 등록 안 함 | 아무것도 없어요 |
| 1. 건물만 | 건물 크기·등급·창문 불빛 |
| 2. 층 이름 | + 팀 이름, 공개 소개 |
| 3. 둘러보기 | + 고른 층의 책상(역할 이름·상태)과 업무판 제목 (층마다 따로 켜요) |

- 올리기 전에 **미리보기**로 무엇이 나가는지 보여 주고, 직접 눌러야 공개돼요.
- 철회하면 바로 건물을 내려요. 다만 GitHub gist처럼 기록이 남는 곳에 올렸다면 예전 판은 남을 수 있다고 미리 알려요.
- 모델 이름은 계열(opus·sonnet·haiku 등)로만 묶어서, 회사 내부 배포 이름 같은 것이 새지 않게 해요.

## 숫자는 어디서 오나요

- **내 사용량**: Claude Code·Codex·Gemini CLI의 사용량을 내 컴퓨터의 세션 기록에서 **숫자만** 세요. 본인이 원할 때만 자기 GitHub gist에 올리고, [참가 이슈](https://github.com/Min-heee/token-meter)로 등록해요. 대화 내용, 경로, 프로젝트 이름, 세션 id는 올리지 않아요.
- 에이전시티 사무실 등록도 같은 방식으로 해요: GitHub 로그인 + 본인 gist 확인(gist 주인 = 등록한 사람).
- 숫자는 각자 신고한 값이라 검증할 수 없어요. 그래서 도시에는 정확한 수치 대신 **등급**만 보여 주고, 지나친 값은 상한으로 자르고, "자기 신고"라고 표시해요.
- 나중에는 Claude Code의 OpenTelemetry 지표(`claude_code.token.usage`)도 고를 수 있게 할 수 있어요.

## 구조 (서버 없이 시작)

```
내 에이전시티     ──(미리보기 → 내가 공개)──► 내 gist: agencity.json (공개 층 요약만)
내 사용량         ──(내가 공개)───────────► 내 gist: 사용량 파일 (숫자만)
                                                   │
등록 명단(members.json, 참가 이슈로 추가) ─────────┤
                                                   ▼
                         정적 도시 페이지(GitHub Pages)가 명단과 gist를 읽어 건물을 그림
                         처음엔 2D/아이소메트릭 → 사람이 늘면 Three.js 3D (instanced mesh, LOD)
                         하루 한 번 스냅샷으로 크기를 갱신
```

공개용 요약 형식(초안):

```json
{
  "schema": 1, "app": "agencity", "login": "<github 아이디>", "updatedAt": "<시각>",
  "profile": { "intro": "직접 쓴 소개 한 줄", "district": "app" },
  "floors": [
    { "floor": 1, "name": "직접 정한 공개용 이름", "public": "tour",
      "summary": "직접 쓴 소개",
      "desks": [ { "role": "개발자", "state": "일하는 중", "task": "직접 공개를 허락한 한 줄" } ],
      "board": [ "업무판 제목만" ] }
  ]
}
```

## 단계

1. **지금**: 로컬 에이전시티(층별 사무실, 말 걸기, 회의, 결재) — 완료
2. **공개 요약 내보내기**: 내 사무실에서 공개용 요약을 만들고 미리보기 → 직접 공개 — 첫 버전(`bin/office_public.py`)
3. **도시 명단 연결**: 등록과 본인 확인(gist 주인 확인) — 도시 명단과 각자의 gist를 그대로 읽어요
4. **2D 도시**: 정적 페이지에 건물을 세우고, 누르면 카드 — 첫 버전(`city.html`, 아이소메트릭 SVG)
5. **둘러보기와 3D**: 읽기 전용 사무실, 비행 카메라, 방문 수·응원·비교

## 참고한 것과 주의

- [Git City](https://github.com/srizzon/git-city): GitHub 사용자 한 명이 3D 픽셀아트 건물 하나가 돼요. 높이는 기여 수, 폭은 공개 저장소 수, 창문 밝기는 스타 수예요. 지표마다 도시 전체 최대값으로 나눈 뒤 곡선으로 줄이고, 건물을 누르면 카메라가 다가가며 프로필 카드가 열려요. **AGPL-3.0**이라 코드는 가져오지 않고 아이디어만 참고해요(에이전시티는 MIT).
- [gh-skyline](https://github.com/github/gh-skyline): GitHub 기여 그래프를 3D 모형으로 만들어요.
- CodeCity(Wettel·Lanza): 소프트웨어를 도시로 보여 주는 연구 도구예요.
- Git City는 원래 공개된 GitHub 데이터만 쓰지만, 에이전시티의 작업 내용은 **원래 비공개 데이터**예요. 그래서 이 계획의 가장 중요한 원칙은 "기본은 비공개, 본인이 고른 것만 공개"예요.
