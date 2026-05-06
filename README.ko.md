# ETF Analyzer

ETF 일별 보유종목 변화를 자동 분석하여 매일 아침 Discord DM으로 리포트를 전송하는 개인용 봇입니다.  
운용역의 의도적 매매와 설정/해지로 인한 수동적 변화를 구분하고, Claude AI로 인사이트를 생성합니다.

## 주요 기능

- **일일 자동 리포트** — 매일 08:00 KST, ETF 보유종목 변화 분석 결과를 Discord DM으로 전송
- **의도적 변화 감지** — 설정/해지(creation/redemption) 영향을 제거하고 운용역의 순수한 매수/매도 식별
- **주간 인사이트** — 매주 일요일 10:00 KST, 누적 이력 기반 운용 원칙 분석 및 저장
- **온디맨드 인사이트 조회** — Discord에서 `/insight` 명령어로 최신 인사이트 즉시 확인
- **이력 자동 백필** — 새 ETF 추가 시 등록일부터 누락 데이터 자동 수집

## 지원 ETF

| ETF | 티커 | 데이터 소스 |
|-----|------|-------------|
| TIME 글로벌AI인공지능액티브 | 456600 | timeetf.co.kr |
| TIME 미국나스닥100액티브 | 426030 | timeetf.co.kr |
| TIME 코스피액티브 | 385720 | timeetf.co.kr |
| iShares A.I. Innovation and Tech Active ETF | BAI | iShares CSV API |

## 빠른 시작

### 1. 사전 준비

다음 세 가지가 필요합니다:

- **Python 3.10+**
- **Discord 봇 토큰** — [Discord Developer Portal](https://discord.com/developers/applications)에서 봇 생성
- **Anthropic API 키** — [console.anthropic.com](https://console.anthropic.com)에서 발급

#### Discord 봇 설정 방법

**Step 1 — 봇 생성 및 토큰 발급**
1. [Discord Developer Portal](https://discord.com/developers/applications) 접속
2. **New Application** → 이름 입력 → Create
3. 왼쪽 사이드바 **Bot** 클릭
4. **Token** 섹션에서 **Reset Token** → 토큰 복사 (`.env`의 `DISCORD_BOT_TOKEN`에 입력)
5. 같은 페이지 아래 **Privileged Gateway Intents** 섹션에서  
   **Message Content Intent** 스위치 켜기 → Save Changes

**Step 2 — 서버 초대 URL 생성**
1. 왼쪽 사이드바 **OAuth2** 클릭
2. **OAuth2 URL Generator** 탭 선택
3. **SCOPES** 에서 `bot` 체크
4. 아래 나타나는 **BOT PERMISSIONS** 에서 다음 체크:
   - `Send Messages`
   - `Read Message History`
   - `Read Messages/View Channels`
5. 페이지 하단 **GENERATED URL** 복사 → 브라우저에서 열기 → 서버 선택 후 초대

> 개인 테스트 서버가 없다면 Discord에서 새 서버를 하나 만들어 초대하면 됩니다.  
> 봇이 서버에 있어야 DM을 보낼 수 있습니다.

**Step 3 — 내 사용자 ID 확인**
1. Discord → 설정 → 고급 → **개발자 모드** 켜기
2. 내 프로필 우클릭 → **사용자 ID 복사** (`.env`의 `DISCORD_USER_ID`에 입력)

### 2. 설치

```bash
git clone https://github.com/zenibakoLee/etfAnalyzer.git
cd etfAnalyzer
pip install -r requirements.txt
```

### 3. 환경 변수 설정

`.env.example`을 복사하여 `.env` 파일을 만들고 값을 채웁니다:

```bash
cp .env.example .env
```

```env
DISCORD_BOT_TOKEN=your_bot_token_here        # Discord 봇 토큰
DISCORD_USER_ID=your_discord_user_id_here    # 리포트를 받을 사용자 ID
ANTHROPIC_API_KEY=your_anthropic_api_key     # Anthropic API 키
DB_PATH=./data/etf_analyzer.db              # DB 경로 (기본값 그대로 사용 권장)
SCHEDULE_HOUR=8                              # 일일 리포트 전송 시각 (KST, 24h)
SCHEDULE_MINUTE=0
```

### 4. 실행

**로컬 개발 (권장)** — 소스 변경 시 자동 재시작:
```bash
python dev.py
```

**프로덕션 (Railway 등)** — 단순 실행:
```bash
python -m src.main
```

정상 실행 시 출력:
```
Database initialized
Scheduler started: daily=08:00 KST, weekly insight=Sun 10:00 KST
Health server listening on port 8080
Starting Discord bot...
Discord bot ready: YourBot#1234
```

> **포트 충돌 시**: `lsof -ti:8080 | xargs kill -9` 또는 `PORT=8081 python dev.py`

## Discord 명령어

봇과 **DM**으로 다음 명령어를 사용합니다:

| 명령어 | 설명 |
|--------|------|
| `/insight` | 등록된 ETF 목록 표시 후 번호 선택 → 최신 인사이트 조회 |

## 데이터 흐름

```
매일 08:00 KST
  → 누락 이력 자동 백필 (ETF별 등록일부터)
  → 오늘 보유종목 스크래핑
  → 설정/해지 기준선(베이스라인 비율) 계산
  → 의도적 변화 / 가격 드리프트 분류
  → Claude AI로 ETF별 리포트 생성
  → 시장 종합 헤드라인 생성
  → Discord DM 전송

매주 일요일 10:00 KST
  → 전체 누적 이력 분석
  → ETF별 운용 원칙 인사이트 생성 및 저장
```

## 프로젝트 구조

```
src/
  main.py       진입점 (DB 초기화, 스케줄러, 헬스 서버, 봇 시작)
  config.py     환경 변수 로딩
  scraper.py    ETF 보유종목 스크래핑 (timeetf.co.kr, iShares)
  database.py   SQLite CRUD
  analyzer.py   변화 감지 로직 + Claude API 호출
  scheduler.py  일일/주간 스케줄 잡
  bot.py        Discord 이벤트 핸들러

docs/
  prd.md              제품 요구사항
  data-schema.md      DB 스키마 설명
  code-architecture.md 코드 구조
  adr.md              기술 결정 기록
```

## ETF 추가 방법

`src/database.py`의 `DEFAULT_ETFS`에 항목을 추가합니다:

```python
DEFAULT_ETFS = [
    # (id, name, ticker, url, backfill_from)
    ...,
    (5, "새 ETF 이름", "티커", "https://...", "YYYY-MM-DD"),
]
```

- **timeetf.co.kr ETF**: URL 형식 `https://timeetf.co.kr/m11_view.php?idx=N`
- **iShares ETF**: URL 형식 `https://www.ishares.com/.../1467271812596.ajax?tab=holdings&fileType=csv`

## 기술 스택

- Python 3.10+, asyncio
- discord.py, APScheduler, aiohttp
- anthropic SDK (Claude claude-sonnet-4-6, 프롬프트 캐싱 적용)
- SQLite, BeautifulSoup4

## 라이선스

개인 사용 목적으로 제작된 프로젝트입니다.
