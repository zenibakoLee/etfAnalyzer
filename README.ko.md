# ETF Analyzer

ETF 일별 보유종목 변화를 자동 분석하여 매일 아침 Discord DM으로 리포트를 전송하는 개인용 봇입니다.  
운용역의 의도적 매매와 설정/해지로 인한 수동적 변화를 구분하고, Claude AI로 인사이트를 생성합니다.

## 주요 기능

- **일일 자동 리포트** — 매일 08:00 KST, ETF 보유종목 변화 분석 결과를 Discord로 전송 (investmentConsensus 대시보드 링크 포함)
- **의도적 변화 감지** — 설정/해지(creation/redemption) 영향을 제거하고 운용역의 순수한 매수/매도 식별
- **주간 인사이트** — 매주 일요일 10:00 KST, 누적 이력 기반 운용 원칙 분석 및 저장
- **수익률 비교** — `/returns` 명령어로 전 ETF 일간/주간/월간/3개월/6개월/YTD/연간 수익률 비교
- **벤치마크 지원** — VOO(S&P 500), QQQ(Nasdaq 100)를 벤치마크로 수익률 비교에 포함
- **온디맨드 인사이트 조회** — Discord에서 `/insight` 명령어로 최신 인사이트 즉시 확인
- **이력 자동 백필** — 새 ETF 추가 시 등록일부터 누락 데이터 자동 수집
- **멀티소스 스크래핑** — timeetf, iShares CSV, Roundhill CSV, WisdomTree CSV, VistaShares CSV, Qraft CMS API, yfinance 등 소스별 자동 디스패치
- **휴장 감지** — 토스증권 공식 market-calendar 1순위 (exchange_calendars+yfinance+웹검색 폴백). 주말/휴장일엔 무의미한 "변화 없음" 리포트 대신 휴장 안내만 전송
- **4컷만화** — Gemini 이미지 모델로 일일 리포트를 4컷만화로 변환하여 첨부
- **PDF 리포트** — ReportLab + matplotlib 기반 다크 테마 PDF 보고서 (Pretendard 폰트, 차트 시각화 포함)
- **Webhook 전송** — Discord Webhook을 통한 리포트 전송 (봇 프로세스와 독립적으로 동작)
- **자동 시작 작업** — 봇 기동 시 2시간 쿨다운 기반 자동 데이터 수집 및 리포트 생성
- **데이터 헬스 체크** — 3일 이상 연속 수집 실패 시 yfinance 폴백 자동 복구 + Discord 알림
- **09:00 복구 체크** — 08:00 리포트 미생성 시 09:00에 자동 재시도

## 지원 ETF

| ETF | 티커 | 데이터 소스 | 유형 |
|-----|------|-------------|------|
| TIME 글로벌AI인공지능액티브 | 456600 | timeetf.co.kr | 분석 대상 |
| TIME 미국나스닥100액티브 | 426030 | timeetf.co.kr | 분석 대상 |
| TIME 코스피액티브 | 385720 | timeetf.co.kr | 분석 대상 |
| iShares A.I. Innovation and Tech Active ETF | BAI | iShares CSV (yfinance 폴백) | 분석 대상 |
| Roundhill Generative AI & Technology ETF | CHAT | Roundhill CSV | 분석 대상 |
| WisdomTree AI & Innovation Fund | WTAI | WisdomTree CSV | 분석 대상 |
| Vanguard S&P 500 ETF | VOO | yfinance | 벤치마크 |
| Invesco QQQ Trust | QQQ | yfinance | 벤치마크 |
| iShares Semiconductor ETF | SOXX | yfinance | 벤치마크 |
| VistaShares AI Supercycle ETF | AIS | VistaShares CSV | 분석 대상 (비활성) |
| LG QRAFT AI-Powered U.S. Large Cap Core ETF | LQAI | Qraft CMS API (101종목 전체) | 분석 대상 |

벤치마크 ETF는 수익률 비교에만 사용되며, 일일 리포트/종합 인사이트에서는 제외됩니다.

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
DISCORD_WEBHOOK_URL=your_webhook_url_here    # Discord Webhook URL (리포트 전송용)
ANTHROPIC_API_KEY=your_anthropic_api_key     # Anthropic API 키
DB_PATH=./data/etf_analyzer.db              # DB 경로 (기본값 그대로 사용 권장)
SCHEDULE_HOUR=8                              # 일일 리포트 전송 시각 (KST, 24h)
SCHEDULE_MINUTE=0
```

### 4. 실행

```bash
python -m src.main
```

정상 실행 시 출력:
```
Database initialized
Scheduler started: daily=08:00 KST, weekly insight=Sun 10:00 KST, recovery=09:00 KST
Health server listening on port 8080
```

> **포트 충돌 시**: `lsof -ti:8080 | xargs kill -9` 또는 `PORT=8081 python -m src.main`

## Discord 명령어

봇과 **DM**으로 다음 명령어를 사용합니다:

| 명령어 | 설명 |
|--------|------|
| `/insight` | 등록된 ETF 목록 표시 후 번호 선택 → 최신 인사이트 조회 |
| `/returns` | 전 ETF 수익률 비교 (기간 선택: 1주/1개월/분기/반기/연간) |

## 데이터 흐름

```
매일 08:00 KST
  → 누락 이력 자동 백필 (ETF별 등록일부터)
  → 오늘 보유종목 스크래핑 (실패 시 yfinance 폴백)
  → 설정/해지 기준선(베이스라인 비율) 계산
  → 의도적 변화 / 가격 드리프트 분류
  → Claude AI로 ETF별 리포트 생성
  → 시장 종합 헤드라인 생성
  → 데이터 헬스 체크 (3일+ 연속 실패 ETF → yfinance 자동 복구 시도)
  → PDF 보고서 생성 (ReportLab + matplotlib 차트)
  → Discord Webhook으로 전송

매일 09:00 KST (복구 체크)
  → 08:00 리포트가 생성되지 않았으면 자동 재시도
  → 재시도 실패 시 Discord Webhook으로 경고 전송

매주 일요일 10:00 KST
  → 전체 누적 이력 분석
  → ETF별 운용 원칙 인사이트 생성 및 저장
```

## 프로젝트 구조

```
src/
  main.py         진입점 (DB 초기화, 스케줄러, 헬스 서버)
  config.py       환경 변수 로딩
  scraper.py      ETF 보유종목 스크래핑 (timeetf, iShares, Roundhill, WisdomTree, VistaShares, yfinance)
  database.py     SQLite CRUD
  analyzer.py     변화 감지 로직 + Claude API 호출
  scheduler.py    일일/주간/복구 스케줄 잡
  bot.py          Discord 이벤트 핸들러
  webhook.py      Discord Webhook 전송 (봇 독립)
  pdf_report.py   ReportLab 기반 PDF 보고서 생성

assets/
  fonts/          Pretendard 폰트 (PDF 한글 렌더링용)

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
    # (id, name, ticker, url, backfill_from, yf_ticker, benchmark)
    ...,
    (11, "새 ETF 이름", "티커", "https://...", "YYYY-MM-DD", "YF_TICKER", 0),
]
```

- **timeetf.co.kr ETF**: URL 형식 `https://timeetf.co.kr/m11_view.php?idx=N`
- **iShares ETF**: URL 형식 `https://www.ishares.com/.../1467271812596.ajax?tab=holdings&fileType=csv` (실패 시 yfinance 자동 폴백)
- **yfinance ETF**: URL 형식 `yfinance://TICKER` (미국 상장 ETF)
- **Roundhill ETF**: URL 형식 `roundhill://TICKER`
- **WisdomTree ETF**: URL 형식 `wisdomtree://TICKER`
- **VistaShares ETF**: URL 형식 `vistashares://TICKER`
- **벤치마크**: `benchmark=1`로 설정하면 수익률 비교에만 포함

## 기술 스택

- Python 3.10+, asyncio
- discord.py, APScheduler, aiohttp, httpx
- anthropic SDK (Claude claude-sonnet-4-6, 프롬프트 캐싱 적용)
- yfinance (미국 ETF 데이터)
- ReportLab + matplotlib (PDF 보고서)
- SQLite, BeautifulSoup4

## 라이선스

개인 사용 목적으로 제작된 프로젝트입니다.
