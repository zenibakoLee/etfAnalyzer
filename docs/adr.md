# ADR — Architecture Decision Records

---

## ADR-001: baseline을 AUM이 아닌 수량 중앙값 비율로 계산

**결정**: 설정/해지 기준선(baseline)을 `aum_100m` 헤더 비율이 아닌, 양일 공통 보유 종목들의 `quantity` 비율 중앙값으로 계산한다.

**배경**: timeetf.co.kr은 과거 날짜를 조회해도 `순자산총액` 필드에 항상 오늘 날짜의 AUM을 반환한다. AUM 비율을 baseline으로 쓰면 설정/해지 추정이 왜곡된다.

**Trade-off**: 수량 중앙값은 outlier(특정 종목 의도적 매매)에 robust하지만, 전 종목 대규모 리밸런싱 시 baseline 자체가 왜곡될 수 있다. 현실적으로 이 케이스는 매우 드물다.

---

## ADR-002: 의도적 변화 임계값 5%, 드리프트 임계값 0.1%

**결정**: 수량이 baseline 대비 ±5% 초과 시 의도적 변화, weight가 ±0.1% 초과 시 가격 드리프트로 분류한다.

**배경**: 5% 미만의 수량 차이는 ETF 설정/해지 과정의 잔량 오차(round lot 조정 등)로 발생할 수 있다. 0.1% weight 변화는 수량 변화 없이 가격 움직임으로도 충분히 발생한다.

**Trade-off**: 5%는 보수적 기준이다. 실제 운용에서 소규모 의도적 조정이 이 기준 아래에 가려질 수 있다. 노이즈 최소화를 우선으로 판단했다.

---

## ADR-003: SQLite 단일 파일 DB

**결정**: PostgreSQL 등 외부 DB 없이 SQLite를 사용한다.

**배경**: 단일 사용자, 단일 프로세스, 일 1회 배치. 동시성 요구가 없다. Railway persistent volume에 파일 하나로 전체 데이터를 관리하면 운영 복잡도가 최소화된다.

**Trade-off**: 수평 확장 불가. 멀티 유저/멀티 프로세스로 확장 시 재설계 필요.

---

## ADR-004: 누적 인사이트를 매일 전체 재생성

**결정**: 하루에 1번 전체 이력(최대 60회)을 Claude에 넘겨 인사이트를 재생성한다. 증분 업데이트를 하지 않는다.

**배경**: ETF 운용 원칙은 과거 이력 전체를 봐야 일관되게 추론된다. 증분 업데이트는 초기 오류가 누적될 위험이 있다.

**Trade-off**: 매일 1200 token 분량의 Claude API 호출이 발생한다. 비용 대비 인사이트 품질이 충분하다고 판단. ETF 수가 늘면 비용 재검토 필요.

---

## ADR-005: Discord DM 전용 단일 사용자

**결정**: 봇은 DM 채널만 응답하며, `DISCORD_USER_ID`로 지정된 1인에게만 능동적 메시지를 보낸다.

**배경**: 퍼스널 도구이므로 멀티 유저 권한 관리 오버헤드가 불필요하다.

**Trade-off**: 공유가 필요한 경우 추가 개발 필요.

---

## ADR-006: 단일 asyncio 프로세스

**결정**: APScheduler, Discord bot, aiohttp 헬스 서버를 단일 asyncio 이벤트 루프에서 실행한다.

**배경**: 단일 사용자, 단일 서비스 단위. 별도 worker 프로세스를 두면 배포 복잡도가 올라간다. 일 1회 배치 + 저빈도 DM이므로 단일 루프로 충분하다.

**Trade-off**: 스크래핑/분석 중 블로킹 I/O가 Discord 응답성에 영향을 줄 수 있다. `requests`(동기)를 asyncio 루프 내에서 직접 호출 중이므로, ETF 수가 많아지면 `asyncio.to_thread` 또는 `aiohttp` 전환을 고려해야 한다.

---

## ADR-007: yfinance를 미국 ETF 데이터 소스로 사용

**결정**: CHAT, WTAI 등 미국 ETF의 보유종목 데이터는 `yfinance` 라이브러리의 `Ticker.funds_data.top_holdings`를 통해 수집한다. URL은 `yfinance://TICKER` 형식으로 지정하며, `fetch_holdings()`가 이를 감지해 yfinance 핸들러로 디스패치한다. 모든 ETF의 일별 종가/수익률도 yfinance로 수집한다.

**배경**: 미국 ETF 운용사 사이트는 스크래핑이 어렵거나 API가 없는 경우가 많다. yfinance는 무료이고 top 10 보유종목 및 가격 데이터를 안정적으로 제공한다. iShares CSV처럼 운용사 개별 포맷을 파싱할 필요가 없어 새 ETF 추가가 용이하다.

**Trade-off**: yfinance는 top 10 보유종목만 제공하므로, 전체 포트폴리오 대비 커버리지가 제한적이다. 과거 보유종목 이력을 제공하지 않아 백필이 불가능하다. 비공식 라이브러리이므로 Yahoo Finance 정책 변경 시 차단될 수 있다.

---

## ADR-008: 벤치마크 ETF는 분석 대상에서 제외

**결정**: `etfs` 테이블에 `benchmark` 컬럼(INTEGER DEFAULT 0)을 추가한다. `benchmark=1`인 ETF(VOO, QQQ)는 `run_daily_job`의 보유종목 분석/리포트 생성 루프에서 제외하되, 수익률 수집(`_collect_daily_returns`)에는 포함한다.

**배경**: VOO, QQQ는 시장 벤치마크로서 수익률 비교 기준이 필요하지만, 패시브 인덱스 ETF의 보유종목 변화를 분석하는 것은 의미가 없다. Claude API 호출 비용도 절감된다.

**Trade-off**: 벤치마크에 대한 인사이트/리포트가 생성되지 않는다. 향후 벤치마크 대비 상대 수익률 분석을 추가할 때는 별도 로직이 필요하다.

---

## ADR-009: Railway에서 macOS launchd 서비스로 배포 전환

**결정**: Railway 클라우드 배포를 중단하고 macOS launchd 서비스(`com.etfanalyzer.bot`)로 로컬 실행한다. DB는 `data/etf_analyzer.db`에 로컬 저장한다.

**배경**: Railway 무료 플랜 제한(크레딧 소진, persistent volume 불안정)으로 운영 안정성이 떨어졌다. 로컬 실행 시 DB 접근이 빠르고, investmentConsensus 웹앱이 `ETF_DB_PATH`로 동일 DB를 직접 읽을 수 있어 크로스 프로젝트 연동이 간단해진다. 외부 접근이 필요한 경우 Cloudflare Quick Tunnel을 사용한다.

**Trade-off**: 맥이 꺼져 있거나 네트워크가 끊기면 서비스가 중단된다. 클라우드 대비 가용성이 낮지만, 1인 사용 기준으로 충분하다.

---

## ADR-010: Discord Webhook 전송으로 전환

**결정**: 일일 리포트 전송을 Discord 봇의 `send_report()`에서 Discord Webhook(`webhook.py`)으로 전환한다. `main.py`에서 봇을 기동하지 않고, 스케줄러 + 헬스 서버만 실행한다.

**배경**: 일일 리포트 전송에 봇 프로세스가 필수적이지 않다. Webhook은 봇 토큰 없이도 메시지를 보낼 수 있어 프로세스 구성이 단순해진다. 봇은 DM 상호작용(`/insight`, `/returns` 등)을 위해 별도로 실행할 수 있다.

**Trade-off**: Webhook은 DM 전송이 불가하여 채널에만 메시지를 보낼 수 있다. 사용자 개인에게만 전달하려면 여전히 봇이 필요하다. PDF 첨부는 httpx 멀티파트로 처리.

---

## ADR-011: PDF 보고서를 ReportLab으로 전환

**결정**: PDF 보고서 생성을 matplotlib-only(`PdfPages`)에서 ReportLab `SimpleDocTemplate` + matplotlib 차트(PNG 임베딩)으로 전환한다. Pretendard 폰트를 `assets/fonts/`에 번들한다.

**배경**: matplotlib `PdfPages`는 텍스트 레이아웃 제어가 제한적이다. 한글 렌더링 시 시스템 폰트 의존성이 있어 환경마다 결과가 달랐다. ReportLab은 정밀한 레이아웃(테이블, 컬러링, 페이지 분리)을 제공하고, 번들 폰트로 환경 독립적 한글 렌더링이 가능하다.

**Trade-off**: 폰트 파일(~13MB)이 리포지토리에 포함된다. ReportLab 의존성이 추가된다. 다크 테마 PDF는 인쇄 시 잉크 소모가 크지만, 디지털 열람만을 가정한다.

---

## ADR-012: 시작 작업 자동 실행 (수동 확인 제거)

**결정**: 봇 기동 시 사용자 확인 없이 자동으로 시작 작업(`run_startup_job`)을 실행한다. 2시간 쿨다운(`last_startup_run`)으로 중복 실행을 방지한다.

**배경**: 기존에는 봇 기동 후 "시작할까요?"라고 묻고 사용자가 확인해야 작업이 실행되었다. launchd 서비스가 재시작될 때마다 수동 확인이 필요해 운영 부담이 있었다. 자동 실행 + 쿨다운으로 이를 해소한다.

**Trade-off**: 원하지 않는 타이밍에 자동 실행될 수 있다. 2시간 쿨다운으로 빈번한 재시작 시의 중복은 방지하지만, 완전한 제어는 불가.

---

## ADR-013: 09:00 복구 체크 스케줄 추가

**결정**: 08:00 일일 리포트 생성에 실패했을 경우, 09:00에 자동 재시도하는 `_recovery_check` 스케줄을 추가한다.

**배경**: 네트워크 장애, 소스 사이트 일시 장애 등으로 08:00 잡이 실패하면 하루 리포트가 누락된다. 1시간 후 재시도로 일시적 장애를 커버한다.

**Trade-off**: 근본적인 장애(API 키 만료, 사이트 영구 차단 등)는 재시도해도 해결되지 않는다. 재시도 실패 시 Discord Webhook으로 수동 확인 알림을 전송한다.

---

## ADR-014: 데이터 헬스 체크 및 yfinance 자동 복구

**결정**: 일일 잡 실행 시 각 ETF의 최종 스냅샷 날짜를 확인하고, 영업일 기준 3일 이상 갭이 있으면 yfinance로 자동 복구를 시도한다.

**배경**: 특정 소스(timeetf, iShares 등)가 수일간 장애를 겪어도 감지되지 않아 데이터 갭이 쌓이는 문제가 있었다. yfinance는 보유종목 상위 10개만 제공하지만, 완전 누락보다 부분 데이터가 낫다.

**Trade-off**: yfinance 폴백 데이터는 원본 소스 대비 종목 수가 적어(top 10) 분석 정밀도가 떨어진다. 복구 성공/실패를 일일 리포트에 명시하여 사용자가 인지할 수 있도록 한다.
