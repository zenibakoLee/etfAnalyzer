# PRD — ETF Analyzer

## Problem
ETF 운용사 사이트의 일별 보유종목(PDF) 데이터는 공개되어 있지만, 변화를 해석해주는 도구가 없다. 설정/해지(creation/redemption)로 인한 수동적 수량 변화와 운용역의 의도적 비중 조절을 구분하는 것이 핵심 과제다.

## Goal
매일 아침 KST 지정 시각에 사용자의 Discord DM으로 ETF 보유종목 변화 분석 리포트를 자동 전송한다. 누적 운용 이력을 바탕으로 한 중장기 인사이트도 온디맨드로 제공한다.

## Users
- 1인(서비스 오너). ETF 운용 스타일을 파악해 투자 판단에 활용한다.

## Core Features

### F1: 일일 자동 보고
- 매일 KST `SCHEDULE_HOUR:SCHEDULE_MINUTE`에 스크래핑 → 분석 → Claude 리포트 생성 → Discord DM 전송
- 주말·공휴일처럼 데이터가 없으면 전송 생략

### F2: 변화 분류
| 구분 | 기준 |
|---|---|
| 신규 편입 | 당일 등장, 전일 없음 |
| 청산 | 전일 있음, 당일 없음 |
| 의도적 변화 | 수량이 baseline 대비 ±5% 초과 |
| 가격 드리프트 | 수량 변화 없으나 weight ±0.1% 초과 |

**Baseline** = 양일 모두 보유한 종목들의 (오늘수량/전일수량) 중앙값 → 설정/해지 배율 추정

### F3: Claude 리포트
- 종목별: 오늘 변화 요약 + 운용 의도 분석 + 주목할 점
- 전체: 복수 ETF 변화를 종합한 시장 헤드라인
- 누적 인사이트: 최대 60회 이력 기반 운용 원칙 분석 (DB에 저장, 다음 날 prior context로 활용)

### F4: 온디맨드 인사이트 조회
- Discord DM에서 `/insight` → 번호 선택 → 누적 인사이트 반환

### F5: 수익률 추적 (Returns Tracking)
- 모든 ETF의 일별 종가 및 수익률을 yfinance로 수집·저장
- 일일 보고서에 수익률 현황 테이블 자동 포함 (일간/주간/월간)
- Discord `/returns` 명령으로 기간별(일간/주간/월간/3개월/6개월/YTD/연간) 수익률 비교 조회
- 첫 수익률 수집 시 2년치 이력을 확보하여 장기 비교 가능

### F6: 벤치마크 비교
- VOO (S&P 500), QQQ (Nasdaq 100), SOXX (반도체)를 벤치마크 ETF로 등록
- 벤치마크는 수익률 추적만 수행하고, 보유종목 분석/리포트 생성 대상에서 제외
- 수익률 비교 시 벤치마크 대비 상대 성과 확인 가능

### F7: PDF 보고서
- ReportLab + matplotlib 기반 다크 테마 PDF 생성
- 수익률 차트 (일간 수익률 막대 그래프 + 주간/월간 비교 차트)
- ETF별 상세 분석 섹션 (매수/매도 색상 구분)
- Pretendard 폰트 사용 (한글 렌더링)
- Discord Webhook으로 PDF 첨부 전송

### F8: Webhook 전송
- Discord Webhook URL을 통한 리포트 전송 (봇 프로세스와 독립)
- 텍스트 메시지 청킹 (1900자 단위) + PDF 파일 첨부

### F9: 데이터 헬스 체크 & 자동 복구
- 3일 이상 연속 수집 실패 감지
- yfinance 폴백 자동 복구 시도
- 수집 실패 및 복구 결과를 일일 리포트에 포함
- iShares 봇 방어(HTML 반환) 자동 감지 및 yfinance 폴백

### F10: 09:00 복구 체크
- 08:00 리포트 미생성 시 09:00에 자동 재시도
- 재시도 실패 시 Discord Webhook으로 경고 전송

## Non-Goals
- 멀티 유저 지원 없음
- 매수/매도 자동 실행 없음
- 실시간 스트리밍 없음

## Constraints
- 데이터 소스:
  - timeetf.co.kr — 한국 ETF 보유종목 (HTML 스크래핑, rate-limit 고려해 0.5s delay, pdfDate 실패 시 최신 데이터 폴백)
  - iShares CSV — 미국 iShares ETF 보유종목 (CSV 다운로드, 봇 방어 시 yfinance 폴백)
  - Roundhill CSV — Roundhill 운용사 ETF (CSV 다운로드)
  - WisdomTree CSV — WisdomTree 운용사 ETF (CSV 다운로드)
  - VistaShares CSV — VistaShares 운용사 ETF (CSV 다운로드)
  - yfinance — 미국 ETF 보유종목 (top 10 holdings) 및 전 ETF 일별 종가/수익률
- 배포: macOS launchd 서비스 (`com.etfanalyzer.bot`), DB는 로컬 `data/etf_analyzer.db`
- Discord Webhook으로 메시지 전송 (텍스트 1900자 청킹 + PDF 첨부)
- investmentConsensus 웹앱이 `ETF_DB_PATH`를 통해 이 DB를 직접 읽음
