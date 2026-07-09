# CNU 공지 알리미

충남대학교 9개 게시판을 매일 한 번씩 확인해서 최근 7일 이내에 올라온 공지를 텔레그램으로 보내준다.

GitHub Actions의 무료 cron으로 동작함. -> 따라서 다소 딜레이가 생길 수 있음.

## 수집하는 게시판

| 게시판 | 출처 |
|--------|------|
| 학사공지 | 컴퓨터인공지능학부 |
| 교내일반소식 | 컴퓨터인공지능학부 |
| 교외활동·인턴·취업 | 컴퓨터인공지능학부 |
| 사업단소식 | 컴퓨터인공지능학부 |
| 국제교류·모집공지 | 국제교류본부 (cnuint) |
| 국제교류·행사공지 | 국제교류본부 (cnuint) |
| 정보보호특성화대학 | 사이버보안연구센터 (csrc) |
| 교육정보(본부) | 본부 포털 (plus) |
| 비교과 프로그램 | CNU With U+ (with) |

## 동작 방식

- 매일 UTC 00:00 = 한국시간 오전 9시에 자동 실행
- 각 게시판 첫 페이지(최신 10~21건)를 스크래핑
- 게시물의 등록일이 오늘 기준 7일 이내인 것만 발송
- 같은 공지가 7일 동안 매일 반복해서 알림에 포함되므로, 하루 놓쳐도 다음날 다시 보임
- 비교과 프로그램은 등록일 대신 **접수 시작일** 기준. 상세 페이지가 로그인 필수라 링크는 with.cnu.ac.kr 메인으로 연결됨

## 처음 설정하는 법

### 1단계: 텔레그램 봇 만들기

1. 텔레그램에서 `@BotFather` 검색해서 대화 시작
2. `/newbot` 입력 → 이름 → username (반드시 `bot`으로 끝나야 함) 순서로 입력
3. BotFather가 보내준 토큰 복사 (예: `7123456789:AAFxxx...`)

### 2단계: chat_id 알아내기

가장 쉬운 방법은 `@userinfobot`에게 `/start` 보내기. 답장에 나오는 `Id:` 뒤의 숫자가 본인의 chat_id.

또는 본인 봇 대화방에서 `/start`를 보낸 뒤 다음 URL을 브라우저에서 열기 (TOKEN 자리에 1단계 토큰 넣기):

```
https://api.telegram.org/botTOKEN/getUpdates
```

응답 JSON의 `"chat":{"id": ...}` 안의 숫자가 chat_id.

### 3단계: GitHub 저장소 만들기와 push

이미 만들어져 있다면 이 단계 건너뛰기.

1. https://github.com/new 에서 repo 생성 (Private 권장, README 체크 해제)
2. PowerShell에서:
   ```powershell
   cd C:\Users\dmsak\cnu-notice-bot
   git init
   git add .
   git commit -m "init: cnu notice bot"
   git branch -M main
   git remote add origin https://github.com/USERNAME/cnu-notice-bot.git
   git push -u origin main
   ```
   (`USERNAME` 자리에 본인 GitHub 사용자명)

push 시 비밀번호 자리에 Personal Access Token 입력 (https://github.com/settings/tokens/new 에서 `repo` 권한으로 발급).

### 4단계: GitHub Secrets에 등록

repo 페이지 → Settings → Secrets and variables → Actions → New repository secret으로 2개 등록:

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | 1단계 토큰 |
| `TELEGRAM_CHAT_ID` | 2단계 숫자 |

### 5단계: 첫 실행 테스트

repo 페이지 → Actions 탭 → 좌측 `CNU Notice Notifier` 클릭 → 우측 `Run workflow` → `Run workflow` 초록 버튼

1~2분 후 새로고침해서 결과 확인:
- 초록 체크 = 성공. 최근 7일 공지가 있으면 텔레그램으로 도착
- 빨간 X = 실패. 워크플로우 클릭 → 실패한 단계 펼치면 로그 확인

이후 매일 한국시간 오전 9시에 자동 실행.

## 로컬에서 테스트

전송 없이 스크래핑 동작만 확인:

```powershell
cd C:\Users\dmsak\cnu-notice-bot
py -m pip install -r requirements.txt
$env:DRY_RUN="1"
py notify.py
```

실제 전송까지 테스트하려면 환경변수 설정:

```powershell
$env:TELEGRAM_BOT_TOKEN="..."
$env:TELEGRAM_CHAT_ID="..."
py notify.py
```

## 게시판 추가하는 법

사이트 종류에 따라 세 가지 경우로 나뉜다. `notify.py` 상단의 딕셔너리에 추가하면 된다.

1. **충남대 학과형 CMS** (URL이 `...공지.do`, 글 링크에 `articleNo=`): `BOARDS`에 전체 URL 추가. 끝.
2. **NTT형 CMS** (`selectNttList.do?mi=...&bbsId=...`): `NTT_BOARDS`에 목록 URL 추가.
3. **본부 포털형** (`_prog/_board/?code=...`): `PLUS_BOARDS`에 목록 URL 추가.
4. **그 외 구조**: 새 파서 함수를 만들고 `main()`의 `sources` 목록에 연결.

## 스케줄/기간 바꾸기

매일 실행 시각: `.github/workflows/notify.yml`의 `cron` 값 수정. UTC 기준.
- 한국 오전 8시: `0 23 * * *`
- 한국 정오: `0 3 * * *`
- 하루 두 번 (오전 9시, 오후 6시): `0 0,9 * * *`

7일 윈도우 변경: `notify.py` 상단의 `WINDOW_DAYS = 7` 값 수정. 14일로 늘리면 2주, 3일로 줄이면 3일.

수정 후 commit + push 하면 다음 실행부터 적용.

## 잘 안 될 때

- **Actions 실행이 빨간 X**: 워크플로우 클릭 → 실패 단계 펼치면 에러 로그. 99% Secrets 오타.
- **텔레그램 안 옴**: 봇한테 직접 `/start` 보냈는지 확인. chat_id가 본인 개인 chat_id 맞는지 확인.
- **특정 게시판만 0건**: 해당 사이트 HTML이 바뀐 것. `notify.py`의 해당 파서 셀렉터 조정 필요. 한 게시판이 실패해도 나머지는 정상 발송됨.

## 파일 구조

```
cnu-notice-bot/
├── notify.py              스크래핑 + 텔레그램 전송 로직
├── requirements.txt       파이썬 의존성 (requests, beautifulsoup4)
├── .env.example           로컬 테스트용 환경변수 템플릿
├── .gitignore
├── README.md              이 파일
└── .github/
    └── workflows/
        └── notify.yml     매일 실행하는 GitHub Actions cron
```
