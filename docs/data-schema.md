# Data Schema

## SQLite — `etf_analyzer.db`

### `etfs`
ETF 마스터 정보. 수동으로 사전 등록.

| column | type | note |
|---|---|---|
| id | INTEGER PK | 수동 할당 (DEFAULT_ETFS 하드코딩) |
| name | TEXT | 표시명 |
| ticker | TEXT | 종목코드 |
| url | TEXT | 스크래핑 대상 URL |
| active | INTEGER | 0 = 비활성화 |
| added_at | DATE | |

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

## Indexes
- `idx_snapshots_etf_date` ON `snapshots(etf_id, date)` — 전일 스냅샷 조회에 사용
- `idx_holdings_snapshot` ON `holdings(snapshot_id)` — 종목 목록 조회에 사용

## Key Design Notes
- `aum_100m`은 저장하지만 분석에 사용하지 않는다. 스크래핑 소스가 과거 날짜 조회 시에도 오늘 AUM을 반환하기 때문.
- 설정/해지 기준선(baseline)은 `holdings.quantity`의 중앙값 비율로 계산한다.
- `insights`는 UPSERT 방식으로 하루에 1번 전체 이력 재분석해 갱신한다.
