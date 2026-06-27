# Code Architecture

## Module Map

```
src/
  main.py         — 진입점. DB init → scheduler → health server (봇 없이 독립 실행)
  config.py       — 환경변수 로딩 (모든 설정 단일 진실점)
  scraper.py      — 멀티소스 스크래핑: timeetf HTML, iShares CSV, Roundhill CSV, WisdomTree CSV, VistaShares CSV, yfinance holdings + returns
  database.py     — SQLite CRUD. 스키마 정의 + contextmanager 커넥션 + returns 헬퍼
  analyzer.py     — 변화 감지 로직 + Claude API 호출 (claude-sonnet-4-6)
  scheduler.py    — APScheduler 일일/주간/복구 잡. scrape→analyze→report + 수익률 수집 + 헬스 체크
  bot.py          — Discord 이벤트 핸들러. DM 상태머신 + /insight, /report, /returns 명령
  webhook.py      — Discord Webhook 전송 (봇 프로세스 없이 독립적 메시지 전송)
  pdf_report.py   — ReportLab + matplotlib 기반 다크 테마 PDF 보고서 생성

assets/
  fonts/          — Pretendard 폰트 파일 (Regular, Bold, SemiBold, Medium, Light)

scripts/
  backfill.py     — 초기 이력 적재용 일회성 스크립트 (2023-05-16 ~)
```

## Request / Event Flow

### 일일 자동 리포트
```
APScheduler (KST cron, 08:00)
  → scheduler.run_daily_job()
      for each non-benchmark ETF:
        → _backfill_gaps()                    # yfinance ETFs는 스킵
        → scraper.fetch_holdings(yf_ticker=)  # URL별 디스패치 (timeetf/iShares/Roundhill/WisdomTree/VistaShares/yfinance)
                                              # iShares 실패 시 yfinance 자동 폴백
                                              # timeetf pdfDate 실패 시 최신 데이터 폴백
        → db.save_snapshot()
        → analyzer.analyze_changes()          # 의도적/수동 분류
        → analyzer.generate_etf_report()      # Claude API (max_tokens=3000)
        → db.save_daily_report()
      → _collect_daily_returns()              # 전 ETF (벤치마크 포함) yfinance 종가 수집
                                              # 첫 수집 시 period="2y", 이후 "1mo"
      → _check_data_health()                  # 3일+ 연속 실패 ETF → yfinance 자동 복구
      → analyzer.generate_market_headline()   # Claude API (max_tokens=3000)
      → pdf_report.generate_daily_pdf()       # ReportLab PDF 생성
      → webhook.send_report()                 # Discord Webhook 전송 (텍스트 + PDF 첨부)
```

### 수익률 수집 흐름
```
scheduler._collect_daily_returns()
  for each ETF with yf_ticker:
    → db.get_returns(days=1) → 기존 데이터 유무 확인
    → scraper.fetch_etf_returns(yf_ticker, period="2y"|"1mo")  # 첫 수집 시 2년치
    → db.save_returns()
    → _calc_period_return() (주간/월간)
  → returns_summary → _format_returns_table() → 일일 메시지에 포함
```

### 복구 체크 (09:00 KST)
```
scheduler._recovery_check()
  → db.get_latest_market_insight() → 오늘 리포트 존재 확인
  → 없으면 run_daily_job() 재시도
  → 재시도도 실패 시 Discord Webhook으로 경고 전송
```

### 데이터 헬스 체크
```
scheduler._check_data_health()
  for each non-benchmark ETF:
    → db.get_latest_snapshot_date() → 최종 데이터 날짜
    → _count_weekday_gap() → 영업일 기준 갭 계산
    → gap ≥ 3일: yfinance로 자동 복구 시도
    → 결과를 health_alerts로 리포트에 포함
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
  → 사용자 번호 입력 (1=일간, 2=주간, 3=월간, 4=3개월, 5=6개월, 6=YTD, 7=연간)
      → bot.on_message() (state: awaiting_returns_period)
          → _send_returns_comparison(): db.get_returns_range() → dateutil.relativedelta로 기간 계산 → 정렬 → 청킹 전송
```

## Key Design Points

**단방향 의존성**: `main` → `scheduler` → `webhook`/`analyzer`/`database`/`scraper`. `bot` → `scheduler`. 역방향 없음.

**상태머신 (bot.py)**: Discord DM 다단계 대화를 `_user_states` dict로 관리. 현재 1인 사용자 가정이므로 in-memory로 충분. 상태 종류: `awaiting_language_selection`, `awaiting_insight_selection`, `awaiting_report_selection`, `awaiting_report_generate_confirm`, `awaiting_returns_period`. 봇 기동 시 자동으로 시작 작업 실행 (2시간 쿨다운).

**멀티소스 스크래핑 (scraper.py)**: `fetch_holdings(url, target_date, yf_ticker=)`가 URL 패턴으로 디스패치:
- `vistashares://TICKER` → `_fetch_vistashares()` (VistaShares CSV)
- `roundhill://TICKER` → `_fetch_roundhill()` (Roundhill CSV)
- `wisdomtree://TICKER` → `_fetch_wisdomtree()` (WisdomTree CSV)
- `yfinance://TICKER` → `_fetch_yfinance_holdings()` (yf.Ticker.funds_data.top_holdings, top 10)
- `ishares.com` 포함 → `_fetch_ishares()` (CSV 다운로드, 실패 시 yfinance 폴백)
- 그 외 → `_fetch_timeetf()` (HTML 파싱, pdfDate 실패 시 최신 데이터 폴백)
- `fetch_etf_returns(yf_ticker, period)` — yfinance로 일별 종가/수익률 수집 (별도 함수)

**Claude API 호출 3종** (모델: claude-sonnet-4-6):
- `generate_etf_report` — 오늘 변화 요약 (max_tokens=3000)
- `generate_etf_insight` — 누적 60회 이력 분석 (max_tokens=8000)
- `generate_market_headline` — 전체 ETF 종합 (max_tokens=3000)

**벤치마크 처리**: `etf.benchmark=1`인 ETF는 `run_daily_job`에서 분석/리포트 루프를 건너뜀. 수익률 수집(`_collect_daily_returns`)에는 포함.

**Webhook 전송 (webhook.py)**: `send_report(text, pdf_path=None)`. Discord Webhook URL로 메시지 전송. PDF 첨부 지원. `CHUNK_SIZE=1900`으로 청킹. 봇 프로세스와 독립적으로 동작.

**PDF 보고서 (pdf_report.py)**: ReportLab `SimpleDocTemplate` + matplotlib 차트. 다크 테마 (`#111111` 배경). Pretendard 폰트 (`assets/fonts/`). 구성:
- 커버 페이지: 제목, 마켓 헤드라인, 수익률 차트 + 테이블, 기간별 비교 차트
- 상세 페이지: ETF별 분석 (섹션 파싱, 매수/매도 색상 구분)

**데이터 헬스 체크**: `_check_data_health()`가 각 ETF의 최종 스냅샷 날짜와 현재 날짜의 영업일 갭을 계산. 3일 이상 갭이면 yfinance 폴백 복구를 시도하고 결과를 알림.

**자동 시작**: `_startup_greeting()`에서 2시간 쿨다운(`last_startup_run`) 확인 후 자동으로 `run_startup_job()` 실행. 수동 확인 프롬프트 없음.

**대시보드 URL 응답**: 채널에서 "주소"/"url" 키워드 감지 시 `_read_dashboard_urls()`로 Signal Catcher, Investment Consensus의 tunnel URL을 읽어 응답.

**Health endpoint**: `/health` → `OK`. 봇 기능과 무관.

## Infrastructure
- **배포**: macOS launchd 서비스 (`com.etfanalyzer.bot`), `python -m src.main`
- **launchd**: `-m src.main` 방식으로 실행 (이전 `-c "import asyncio..."` 방식에서 변경)
- **DB 위치**: 로컬 `data/etf_analyzer.db`
- **프로세스**: 단일 asyncio 이벤트 루프에서 APScheduler + aiohttp 서버 실행. 일일 리포트는 Webhook으로 전송.
- **스케줄**: 일일 08:00 + 복구 09:00 + 주간 일요일 10:00 (모두 `misfire_grace_time` 설정)
- **크로스 프로젝트**: investmentConsensus 웹앱이 `ETF_DB_PATH` 환경변수를 통해 이 DB를 직접 읽음
