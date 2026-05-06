# Code Architecture

## Module Map

```
src/
  main.py       — 진입점. DB init → scheduler → health server → bot 시작
  config.py     — 환경변수 로딩 (모든 설정 단일 진실점)
  scraper.py    — HTTP 스크래핑. timeetf.co.kr HTML 파싱
  database.py   — SQLite CRUD. 스키마 정의 + contextmanager 커넥션
  analyzer.py   — 변화 감지 로직 + Claude API 호출
  scheduler.py  — APScheduler 일일 잡. scrape→analyze→report 오케스트레이션
  bot.py        — Discord 이벤트 핸들러. DM 상태머신 + send_report

scripts/
  backfill.py   — 초기 이력 적재용 일회성 스크립트 (2023-05-16 ~)
```

## Request / Event Flow

### 일일 자동 리포트
```
APScheduler (KST cron)
  → scheduler.run_daily_job()
      → scraper.fetch_holdings()       # per ETF
      → db.save_snapshot()
      → analyzer.analyze_changes()     # 의도적/수동 분류
      → analyzer.generate_etf_report() # Claude API
      → analyzer.generate_etf_insight() # Claude API (누적 60회)
      → db.save_insight()
      → analyzer.generate_market_headline() # Claude API
      → bot.send_report()              # Discord DM 청킹 전송
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

## Key Design Points

**단방향 의존성**: `bot` → `scheduler` → `analyzer`/`database`/`scraper`. 역방향 없음.

**상태머신 (bot.py)**: Discord DM 다단계 대화를 `_user_states` dict로 관리. 현재 1인 사용자 가정이므로 in-memory로 충분.

**Claude API 호출 3종**:
- `generate_etf_report` — 오늘 변화 요약 (800 tokens)
- `generate_etf_insight` — 누적 60회 이력 분석 (1200 tokens)
- `generate_market_headline` — 전체 ETF 종합 (300 tokens)

**청킹**: Discord 2000자 제한 대응. `CHUNK_SIZE=1900`으로 여유 확보.

**Health endpoint**: Railway 헬스체크용 `/health` → `OK`. 봇 기능과 무관.

## Infrastructure
- **배포**: Railway (Nixpacks 빌드, `python -m src.main`)
- **DB 위치**: Railway persistent volume `/data/etf_analyzer.db`
- **프로세스**: 단일 asyncio 이벤트 루프에서 APScheduler + Discord bot + aiohttp 서버 동시 실행
