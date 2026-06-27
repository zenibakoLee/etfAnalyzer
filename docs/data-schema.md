# Data Schema

## SQLite — `etf_analyzer.db`

### `etfs`
ETF 마스터 정보. `DEFAULT_ETFS` 튜플로 하드코딩, `init_db`에서 ON CONFLICT DO UPDATE로 upsert.

| column | type | note |
|---|---|---|
| id | INTEGER PK | 수동 할당 (DEFAULT_ETFS 하드코딩) |
| name | TEXT | 표시명 |
| ticker | TEXT | 종목코드 |
| url | TEXT | 스크래핑 대상 URL (`yfinance://TICKER` 형식 포함) |
| active | INTEGER | 0 = 비활성화 |
| added_at | DATE | |
| backfill_from | DATE | 백필 시작일 (DEFAULT '2023-05-16') |
| yf_ticker | TEXT | yfinance 티커 (e.g. "456600.KS", "BAI", "VOO"). 수익률 수집에 사용 |
| benchmark | INTEGER | 1 = 벤치마크 ETF (리포트/분석 대상에서 제외), DEFAULT 0 |

DEFAULT_ETFS 튜플 형식: `(id, name, ticker, url, backfill_from, yf_ticker, benchmark)`

현재 등록 ETF:
| id | ticker | name | source | benchmark |
|---|---|---|---|---|
| 1 | 456600 | TIME 글로벌AI인공지능액티브 | timeetf | 0 |
| 2 | 426030 | TIME 미국나스닥100액티브 | timeetf | 0 |
| 3 | 385720 | TIME 코스피액티브 | timeetf | 0 |
| 4 | BAI | iShares A.I. Innovation and Tech Active ETF | iShares CSV (yfinance 폴백) | 0 |
| 5 | CHAT | Roundhill Generative AI & Technology ETF | roundhill:// | 0 |
| 6 | WTAI | WisdomTree AI & Innovation Fund | wisdomtree:// | 0 |
| 7 | VOO | Vanguard S&P 500 ETF | yfinance | 1 |
| 8 | QQQ | Invesco QQQ Trust | yfinance | 1 |
| 9 | SOXX | iShares Semiconductor ETF | yfinance:// | 1 |
| 10 | AIS | VistaShares AI Supercycle ETF | vistashares:// | 0 (비활성) |

### `snapshots`
특정 날짜의 ETF 전체 스냅샷. 1 ETF × 1 일 = 1 row.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| etf_id | INTEGER FK→etfs | |
| date | DATE | UNIQUE(etf_id, date) |
| aum_100m | REAL | 순자산총액(억원). 과거 날짜에도 당일 값이 표시되는 버그가 있어 분석에 미사용 |

### `holdings`
snapshot의 개별 종목 내역.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| snapshot_id | INTEGER FK→snapshots | |
| ticker_code | TEXT | |
| stock_name | TEXT | |
| quantity | INTEGER | 보유 수량 (baseline 계산의 핵심 필드) |
| valuation_krw | BIGINT | 평가금액(원) |
| weight_pct | REAL | 비중(%) |

### `insights`
ETF별 누적 인사이트 텍스트. 매일 갱신.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| etf_id | INTEGER FK→etfs | |
| date | DATE | UNIQUE(etf_id, date) — 최신 1건만 활용 |
| insight_text | TEXT | Claude 생성 마크다운 |

### `market_insights`
전체 ETF 종합 헤드라인. 매일 갱신.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| date | DATE UNIQUE | |
| headline_text | TEXT | |
| created_at | TIMESTAMP | |

### `no_data_dates`
스크래핑 결과 데이터가 없는 날짜 기록 (주말/공휴일). 백필 시 이미 확인한 날짜를 다시 조회하지 않기 위함.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| etf_id | INTEGER FK→etfs | |
| date | DATE | UNIQUE(etf_id, date) |

### `daily_reports`
ETF별 일일 리포트 텍스트. Claude가 생성한 분석 결과를 저장. `/report` 명령에서 조회.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| etf_id | INTEGER FK→etfs | |
| date | DATE | UNIQUE(etf_id, date) |
| report_text | TEXT | Claude 생성 리포트 |

### `user_preferences`
사용자 설정 (언어 등).

| column | type | note |
|---|---|---|
| key | TEXT PK | |
| value | TEXT | |

주요 키: `language` (ko/en), `last_startup_run` (ISO 형식 타임스탬프, 자동 시작 작업 2시간 쿨다운에 사용)

### `etf_returns`
ETF별 일별 종가 및 수익률. yfinance로 수집.

| column | type | note |
|---|---|---|
| id | INTEGER PK | |
| etf_id | INTEGER FK→etfs | |
| date | DATE | UNIQUE(etf_id, date) |
| close_price | REAL | 일별 종가 |
| daily_return_pct | REAL | 전일 대비 수익률 (%). 첫 날은 NULL |

Helper 함수: `save_returns`, `get_returns`, `get_latest_return`, `get_returns_range`, `get_latest_snapshot_date`, `delete_no_data_date`

## Indexes
- `idx_snapshots_etf_date` ON `snapshots(etf_id, date)` — 전일 스냅샷 조회에 사용
- `idx_holdings_snapshot` ON `holdings(snapshot_id)` — 종목 목록 조회에 사용
- `idx_no_data_etf_date` ON `no_data_dates(etf_id, date)` — 백필 시 확인 완료 날짜 조회
- `idx_daily_reports_etf_date` ON `daily_reports(etf_id, date)` — 리포트 조회
- `idx_etf_returns_etf_date` ON `etf_returns(etf_id, date DESC)` — 최신 수익률 조회에 사용

## Key Design Notes
- `aum_100m`은 저장하지만 분석에 사용하지 않는다. 스크래핑 소스가 과거 날짜 조회 시에도 오늘 AUM을 반환하기 때문.
- 설정/해지 기준선(baseline)은 `holdings.quantity`의 중앙값 비율로 계산한다.
- `insights`는 UPSERT 방식으로 하루에 1번 전체 이력 재분석해 갱신한다.
- `init_db`는 `ON CONFLICT(id) DO UPDATE`를 사용하여 ETF 마스터 정보를 항상 최신으로 유지한다 (기존 INSERT OR IGNORE 대신).
- yfinance ETF (`yfinance://` URL)는 백필 대상에서 제외된다 — 과거 보유종목 이력이 제공되지 않음.
- 벤치마크 ETF (`benchmark=1`)는 수익률만 수집하고 분석/리포트 생성을 건너뛴다.
