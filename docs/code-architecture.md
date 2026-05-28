# Code Architecture

## Module Map

```
src/
  main.py       — 진입점. DB init → scheduler → health server → bot 시작
  config.py     — 환경변수 로딩 (모든 설정 단일 진실점)
  scraper.py    — 멀티소스 스크래핑: timeetf HTML, iShares CSV, yfinance holdings + returns
  database.py   — SQLite CRUD. 스키마 정의 + contextmanager 커넥션 + returns 헬퍼
  analyzer.py   — 변화 감지 로직 + Claude API 호출 (claude-sonnet-4-6)
  scheduler.py  — APScheduler 일일 잡. scrape→analyze→report + 수익률 수집 오케스트레이션
  bot.py        — Discord 이벤트 핸들러. DM 상태머신 + /insight, /report, /returns 명령

scripts/
  backfill.py   — 초기 이력 적재용 일회성 스크립트 (2023-05-16 ~)
```

## Request / Event Flow

### 일일 자동 리포트
```
APScheduler (KST cron)
  → scheduler.run_daily_job()
      for each non-benchmark ETF:
        → _backfill_gaps()                 # yfinance ETFs는 스킵
        → scraper.fetch_holdings()         # URL별 디스패치 (timeetf/iShares/yfinance)
        → db.save_snapshot()
        → analyzer.analyze_changes()       # 의도적/수동 분류
        → analyzer.generate_etf_report()   # Claude API (max_tokens=3000)
        → db.save_daily_report()
      → _collect_daily_returns()           # 전 ETF (벤치마크 포함) yfinance 종가 수집
      → analyzer.generate_market_headline()# Claude API (max_tokens=3000)
      → bot.send_report()                  # Discord webhook 청킹 전송
```

### 수익률 수집 흐름
```
scheduler._collect_daily_returns()
  for each ETF with yf_ticker:
    → scraper.fetch_etf_returns(yf_ticker, period="1mo")
    → db.save_returns()
    → _calc_period_return() (주간/월간)
  → returns_summary → _format_returns_table() → 일일 메시지에 포함
```

### 온디맨드 인사이트
```
Discord DM "/insight"
  → bot.on_message()
      → _handle_insight(): ETF 목록 표시 + 상태 저장
  → 사용자 번호 입력
      → bot.on_message() (state: awaiting_insight_selection)
          → _send_etf_insight(): DB에서 최신 insight 조회 → 청킹 전송
```

### 수익률 비교 (/returns)
```
Discord DM "/returns"
  → bot.on_message()
      → _handle_returns(): 기간 선택 메뉴 표시
  → 사용자 번호 입력 (1=일간, 2=주간, 3=월간, 4=연간)
      → bot.on_message() (state: awaiting_returns_period)
          → _send_returns_comparison(): DB에서 수익률 조회 → 정렬 → 청킹 전송
```

## Key Design Points

**단방향 의존성**: `bot` → `scheduler` → `analyzer`/`database`/`scraper`. 역방향 없음.

**상태머신 (bot.py)**: Discord DM 다단계 대화를 `_user_states` dict로 관리. 현재 1인 사용자 가정이므로 in-memory로 충분. 상태 종류: `awaiting_language_selection`, `awaiting_startup_confirm`, `awaiting_insight_selection`, `awaiting_report_selection`, `awaiting_report_generate_confirm`, `awaiting_returns_period`.

**멀티소스 스크래핑 (scraper.py)**: `fetch_holdings(url, target_date)`가 URL 패턴으로 디스패치:
- `yfinance://TICKER` → `_fetch_yfinance_holdings()` (yf.Ticker.funds_data.top_holdings, top 10)
- `ishares.com` 포함 → `_fetch_ishares()` (CSV 다운로드)
- 그 외 → `_fetch_timeetf()` (HTML 파싱)
- `fetch_etf_returns(yf_ticker, period)` — yfinance로 일별 종가/수익률 수집 (별도 함수)

**Claude API 호출 3종** (모델: claude-sonnet-4-6):
- `generate_etf_report` — 오늘 변화 요약 (max_tokens=3000)
- `generate_etf_insight` — 누적 60회 이력 분석 (max_tokens=8000)
- `generate_market_headline` — 전체 ETF 종합 (max_tokens=3000)

**벤치마크 처리**: `etf.benchmark=1`인 ETF는 `run_daily_job`에서 분석/리포트 루프를 건너뜀. 수익률 수집(`_collect_daily_returns`)에는 포함.

**청킹**: Discord 2000자 제한 대응. `CHUNK_SIZE=1900`으로 여유 확보.

**Health endpoint**: `/health` → `OK`. 봇 기능과 무관.

## Infrastructure
- **배포**: macOS launchd 서비스 (`com.etfanalyzer.bot`), `python -m src.main`
- **DB 위치**: 로컬 `data/etf_analyzer.db`
- **프로세스**: 단일 asyncio 이벤트 루프에서 APScheduler + Discord bot + aiohttp 서버 동시 실행
- **크로스 프로젝트**: investmentConsensus 웹앱이 `ETF_DB_PATH` 환경변수를 통해 이 DB를 직접 읽음
