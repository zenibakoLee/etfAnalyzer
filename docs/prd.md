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

## Non-Goals
- 멀티 유저 지원 없음
- 매수/매도 자동 실행 없음
- 실시간 스트리밍 없음

## Constraints
- 데이터 소스: timeetf.co.kr (HTML 스크래핑, rate-limit 고려해 0.5s delay)
- 배포: Railway (persistent volume at `/data`, health check at `/health`)
- Discord 메시지 최대 2000자 → 청킹 필요
