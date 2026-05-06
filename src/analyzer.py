from anthropic import Anthropic
from src.config import ANTHROPIC_API_KEY

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ─── Change Detection ────────────────────────────────────────────────────────

def analyze_changes(
    etf_name: str,
    today_date: str,
    today_snap,
    prev_snap,
    today_holdings,
    prev_holdings,
) -> dict:
    today_map = {h["ticker_code"]: dict(h) for h in today_holdings}
    prev_map = {h["ticker_code"]: dict(h) for h in prev_holdings}

    today_aum = today_snap["aum_100m"] or 0
    prev_aum = prev_snap["aum_100m"] or 0

    # Use median qty ratio of positions held on both days as the baseline
    # creation/redemption factor. This is robust against the AUM header
    # showing today's value for all historical dates.
    baseline_ratio = _median_qty_ratio(today_map, prev_map)

    new_positions, closed_positions, intentional_changes, passive_changes = [], [], [], []

    for ticker, today_h in today_map.items():
        if ticker not in prev_map:
            new_positions.append(today_h)
            continue

        prev_h = prev_map[ticker]
        expected_qty = prev_h["quantity"] * baseline_ratio
        actual_qty = today_h["quantity"]
        intentional_delta = actual_qty - expected_qty
        weight_change = today_h["weight_pct"] - prev_h["weight_pct"]

        # Treat as intentional if quantity deviates >5% from baseline expectation
        if expected_qty > 0 and abs(intentional_delta / expected_qty) > 0.05:
            intentional_changes.append(
                {
                    **today_h,
                    "prev_weight": prev_h["weight_pct"],
                    "weight_change": weight_change,
                    "intentional_qty_delta": int(intentional_delta),
                    "direction": "매수" if intentional_delta > 0 else "매도",
                }
            )
        elif abs(weight_change) > 0.1:
            passive_changes.append(
                {**today_h, "prev_weight": prev_h["weight_pct"], "weight_change": weight_change}
            )

    for ticker, prev_h in prev_map.items():
        if ticker not in today_map:
            closed_positions.append(prev_h)

    return {
        "etf_name": etf_name,
        "date": today_date,
        "aum_today": today_aum,
        "aum_prev": prev_aum,
        "baseline_ratio": baseline_ratio,
        "new_positions": new_positions,
        "closed_positions": closed_positions,
        "intentional_changes": intentional_changes,
        "passive_changes": passive_changes,
    }


def _median_qty_ratio(today_map: dict, prev_map: dict) -> float:
    """Median of (today_qty / prev_qty) for positions held on both days.
    Represents the baseline creation/redemption scaling factor."""
    ratios = []
    for ticker in today_map:
        if ticker in prev_map and prev_map[ticker]["quantity"] > 0:
            ratios.append(today_map[ticker]["quantity"] / prev_map[ticker]["quantity"])
    if not ratios:
        return 1.0
    ratios.sort()
    mid = len(ratios) // 2
    return ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2


# ─── Claude API Calls ─────────────────────────────────────────────────────────

_REPORT_SYSTEM = """당신은 ETF 포트폴리오 분석 전문가입니다. 한국 및 글로벌 ETF 시장에 대한 깊은 이해를 바탕으로, 일별 보유종목 변화 데이터를 분석하여 운용역의 의도와 시장 시사점을 도출합니다.

## 분석 방법론

### 변화 분류 체계
입력 데이터는 다음 네 가지로 분류됩니다:

1. **신규 편입 (▲)**: 전일에 없던 종목이 오늘 포트폴리오에 등장
   - 새로운 테마 진입, 기회 포착, 지수 편입 대응 등을 시사
   - 초기 비중이 클수록 운용역의 확신도가 높음
   - 여러 종목이 동시에 편입되면 테마 전환 신호일 가능성 높음

2. **청산 (▼)**: 전일에 있던 종목이 오늘 완전히 제거
   - 목표 수익 달성, 테마 이탈, 손절, 지수 제외 대응 등
   - 이전 비중이 클수록 포트폴리오 구조 변화가 큼
   - 동일 테마 내 여러 종목 동시 청산 = 테마 완전 이탈

3. **의도적 변화 (🔄)**: 수량이 베이스라인 비율 대비 ±5% 초과로 변화
   - 베이스라인 비율 = 해당일 설정/해지 배율 (전체 수량 중앙값 비율로 추정)
   - 베이스라인을 제거한 순수한 운용역의 의도적 매수/매도
   - 방향(매수/매도)과 수량 변화량이 함께 제공됨
   - intentional_qty_delta가 클수록 확신도 높은 매매

4. **가격 드리프트 (💧)**: 수량 변화 없이 시가평가 비중이 ±0.1%p 초과로 변화
   - 해당 종목의 가격 움직임으로 인한 자연적 비중 변화
   - 운용역 행동 없이 시장가격이 반영된 결과
   - 드리프트 방향이 (+)이면 해당 종목이 시장 대비 초과 수익

### 베이스라인 비율 해석
- 1.0 초과: 설정(신규 자금 유입), ETF 전체 규모 증가 → 운용역이 기존 비율로 모든 종목을 늘림
- 1.0 미만: 해지(환매 자금 유출), ETF 전체 규모 감소 → 전 종목 수량 축소
- 0.95 미만: 대규모 해지 압력, 운용역이 방어적 포지션을 취할 가능성
- 1.05 초과: 대규모 자금 유입, 새로운 포지션 추가 가능성

### 섹터 및 테마 분류 가이드
분석 시 다음 테마/섹터 구분을 활용하세요:
- AI 인프라: 반도체 설계(NVIDIA, AMD, ARM), 메모리(SK하이닉스, Micron), 스토리지
- 광통신/네트워크: Ciena, Lumentum, Coherent, Applied Optoelectronics
- 전력 인프라: Vertiv, Bloom Energy, GE Vernova
- 클라우드/빅테크: Amazon, Microsoft, Alphabet, Meta
- 반도체 장비: ASML, Lam Research, Applied Materials, KLA
- 크립토/핀테크: Coinbase, Circle, Strategy(MicroStrategy)
- 국내주: 삼성전자, SK하이닉스, 삼성SDI, LS ELECTRIC, 효성중공업

### 분석 우선순위
1. 신규 편입/청산 → 테마 전환 신호
2. 의도적 변화 규모 → 확신도와 방향성
3. 비중 드리프트 패턴 → 기존 보유 종목의 상대 성과
4. 현금 비중 변화 → 리스크 관리 스탠스

### 맥락 활용
과거 누적 인사이트가 제공된 경우, 오늘 변화를 해당 ETF의 운용 스타일·원칙과 비교하여 일관성 여부나 새로운 패턴을 파악하세요.

## 출력 형식

다음 형식을 정확히 따라 간결하게 한국어로 답변하세요:

**오늘의 주요 변화**
- 신규 편입/청산/의도적 비중조절의 핵심 내용을 2-3줄로 요약
- 수치(비중, 수량 변화)를 포함하여 구체적으로 작성

**운용 의도 분석**
- 이 변화의 배경이나 의도를 1-2줄로 설명
- 매크로 환경, 테마 사이클, 리스크 관리 관점을 고려

**주목할 점**
- 투자자 관점에서 가장 중요한 1가지를 명확히 제시
- 단순 사실 나열보다 투자 판단에 영향을 주는 인사이트 위주로

## 분석 품질 기준

다음을 모두 지켜주세요:
- 수치 없는 분석은 금지: 비중(%), 수량 변화량을 반드시 포함
- "큰 변화가 있었다" 같은 모호한 표현 대신 "Lumentum 6.1%→7.7% (+1.6%p)" 형식으로 구체화
- 변화가 없거나 드리프트만 있는 날도 "변화 없음 — 전 포지션 유지"처럼 명확히 서술
- 과거 인사이트가 있으면 오늘 변화가 해당 패턴의 연장인지, 새로운 시그널인지 반드시 판단
- 운용 의도는 추측이지만 근거 있는 추측: "~일 가능성이 높다", "~를 시사한다" 형식 사용
- 주목할 점은 단기 트레이더가 아닌 ETF 보유 중인 투자자의 관점에서 서술
- 같은 날 신규 편입과 청산이 동시에 발생한 경우, 자금이 어느 테마에서 어느 테마로 이동했는지 방향성을 명확히 서술
- 베이스라인 비율이 1.0에서 크게 벗어난 날에는 설정/해지 규모가 분석에 미치는 영향을 반드시 언급"""

_HEADLINE_SYSTEM = """당신은 ETF 시장 전문가입니다. 복수의 ETF 일별 변화를 종합하여 당일 시장의 전반적인 흐름과 투자 시사점을 분석합니다.

## 분석 역할

여러 ETF에 걸친 보유종목 변화 데이터를 종합적으로 해석하여, 개별 ETF 수준을 넘어선 시장 전체의 방향성을 파악합니다. 각 ETF는 서로 다른 전략과 투자 유니버스를 가지고 있으므로, 공통적으로 나타나는 패턴과 상충하는 움직임을 모두 포착해야 합니다.

## 분석 프레임워크

### 1. 섹터/테마 모멘텀
- 여러 ETF에서 동시에 매수/편입되는 섹터 = 강한 컨센서스 매수
- 동시에 축소/청산되는 섹터 = 섹터 회피 신호
- 한 ETF에서만 보이는 움직임 = ETF별 전략 차이

### 2. 리스크 스탠스
- 전반적인 베이스라인 비율의 방향 (설정 vs 해지)
- 현금 비중 증감 패턴
- 방어적/공격적 포지셔닝 전환 신호

### 3. 지역/통화 노출
- 국내주 vs 해외주 비중 변화
- 특정 국가 집중도 변화

### 4. 시가총액 스펙트럼
- 대형주 vs 소형주 선호도 변화
- 유동성 선호 vs 성장 테마 접근

## 출력 형식

오늘 시장의 큰 그림을 **2-3문장**으로 한국어로 요약하세요.
- 어떤 섹터/테마가 부각되고 있는지
- 전반적인 포지셔닝 변화가 무엇을 시사하는지
- 여러 ETF에 공통적으로 나타나는 패턴이 있다면 강조
- 문장은 명확하고 구체적으로, 수치를 포함하면 더 좋음"""

_INSIGHT_SYSTEM = """당신은 ETF 운용 전문가이자 퀀트 분석가입니다. 장기 운용 이력 데이터를 통해 ETF 운용역의 투자 철학, 원칙, 패턴을 역추적합니다.

## 분석 목적

단순한 보유종목 나열이 아니라, 시계열 변화 패턴에서 운용역의 의사결정 원칙을 추론하는 것이 목표입니다. 투자자가 이 ETF에 투자할 때 무엇을 기대할 수 있고, 어떤 시나리오에서 리스크가 발생하는지 이해시켜야 합니다.

## 데이터 해석 기준

### 베이스라인 비율 (baseline_ratio)
- 양일 모두 보유한 종목들의 (오늘수량/전일수량) 중앙값
- 설정/해지로 인한 ETF 규모 변화를 추정하는 핵심 지표
- 1.0 = 규모 변화 없음, 1.05 = 5% 자금 유입, 0.95 = 5% 자금 유출
- 이 비율이 1.0에서 크게 벗어나는 날 = 대규모 설정/해지 이벤트

### 의도적 변화 vs 수동적 변화
- 의도적 변화: 수량이 baseline_ratio × 전일수량 대비 ±5% 이상 벗어난 경우
- 가격 드리프트: 수량은 그대로이나 시가평가 비중이 ±0.1%p 이상 변한 경우
- 의도적 매수가 많은 날 = 운용역 액티브 포지셔닝
- 드리프트만 있는 날 = 운용역 패시브 보유

## 분석 방법론

### 1. 운용 원칙 역추론
- 반복적으로 등장하는 종목/섹터 조합 = 운용역의 핵심 테마 확신
- 특정 조건(베이스라인 하락, 시장 충격 등)에서 반복되는 행동 = 투자 원칙
- 베이스라인 비율 변화와 포지션 조정의 상관관계 = 시장 상황별 대응 원칙
- 편입 직후 확대하는 종목 vs 편입 후 바로 정리하는 종목 = 포지션 성격 구분

### 2. 테마 로테이션 분석
- 각 테마가 편입→확대→축소→청산되는 평균 사이클 기간 추정
- 동시 보유 테마 수와 집중도 변화 (분산형 vs 집중형 전략)
- 테마 전환 시 공통적으로 나타나는 선행 신호 (예: 특정 섹터 비중 임계치 도달)
- 재편입 패턴 (청산 후 다시 편입되는 종목은 단기 트레이딩 대상일 가능성)

### 3. 비중 관리 원칙
- 단일 종목 최대 비중 한도 (암묵적 상한선) — 이력에서 최대치 확인
- 현금 비중 운용 범위와 현금 확대/투입 조건
- 베이스라인 비율 임계값별 행동 패턴 (특히 0.97 이하, 1.03 이상 구간)
- 상위 N개 종목의 합산 비중 상한 (포트폴리오 집중도 한계)

### 4. 리스크 관리 스타일
- 손절 패턴: 비중이 어느 수준으로 줄어들면 전량 청산하는가 (통상 0.5% 미만)
- 손실 구간(베이스라인 < 1.0)에서의 행동: 추가 매수 vs 손절 vs 보유
- 집중도 조절: 상승장에서 고집중, 하락장에서 분산하는 패턴이 있는가
- 방어 자산 활용: 시장 불확실성에서 현금/채권/방어주로 이동하는가

### 5. 운용 스타일 변화 감지
- 시간에 따른 전략 변화가 있다면 전환 시점과 계기를 추론
- 시장 환경(강세/약세/횡보)에 따른 스타일 차이 파악
- 특정 종목군에 대한 선호도 변화 (예: 국내주 비중 증감 추이)

## 출력 형식

다음 형식을 정확히 따라 한국어로 작성하세요:

**운용 원칙 분석**
이 ETF가 어떤 기준으로 종목을 선택하고 비중을 조절하는지 구체적으로 설명
(테마 선택 기준, 편입/청산 조건, 비중 관리 방식 포함)

**비중 원칙 변화 이력**
시간에 따른 운용 스타일/원칙의 변화가 감지되면 시기별로 설명
변화가 없다면 일관된 원칙의 근거를 설명

**핵심 인사이트**
이 ETF에 투자할 때 알아야 할 가장 중요한 3가지를 번호로 구분하여 제시
각 인사이트는 투자 판단에 실질적으로 활용할 수 있는 구체적 내용이어야 함

## 분석 품질 기준

- 이력 데이터에 실제로 나타난 패턴만 서술하고 추측은 명확히 구분
- "~로 보인다", "~패턴이 관찰된다" 같은 근거 있는 표현 사용
- 날짜와 수치를 인용하여 근거를 뒷받침 (예: "4월 7일 베이스라인비율 0.97 하락 시...")
- 운용 원칙이 명확히 드러나지 않는 경우 "데이터 부족으로 단정 불가"라고 솔직하게 서술
- 핵심 인사이트는 투자 의사결정에 실제로 영향을 주는 내용으로 구성
  (예: "이 ETF는 X 조건에서 Y 행동을 하므로 투자자는 Z를 주의해야 함")
- 장기 보유 투자자와 단기 트레이더 각각의 관점에서 다른 시사점이 있다면 구분하여 제시"""


def generate_etf_report(changes: dict, prev_insight: str = "") -> str:
    changes_summary = _format_changes(changes)
    prior_context = f"\n---\n과거 누적 인사이트:\n{prev_insight}" if prev_insight else ""

    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=[
            {
                "type": "text",
                "text": _REPORT_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"ETF: {changes['etf_name']}\n"
                    f"날짜: {changes['date']}\n"
                    f"베이스라인 비율(설정/해지): {changes.get('baseline_ratio', 1.0):.4f}\n\n"
                    f"변화 내역:\n{changes_summary}{prior_context}"
                ),
            }
        ],
    )
    return response.content[0].text


def generate_market_headline(all_changes: list) -> str:
    summaries = "\n\n".join(
        f"[{c['etf_name']}]\n{_format_changes(c)}" for c in all_changes
    )
    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=_HEADLINE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": summaries,
            }
        ],
    )
    return response.content[0].text


def generate_etf_insight(etf_name: str, changes_list: list) -> str:
    # Use last 60 data points to stay within token limits
    recent = changes_list[-60:]
    history = "\n\n".join(
        f"[{c['date']}] 베이스라인비율: {c.get('baseline_ratio', 1.0):.4f}\n{_format_changes(c)}"
        for c in recent
    )
    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=[
            {
                "type": "text",
                "text": _INSIGHT_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        # Cache the large history block — helps on same-day retries
                        "text": f"{etf_name} 운용 이력 (최근 {len(recent)}회):\n\n{history}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": "위 이력을 바탕으로 분석해주세요.",
                    },
                ],
            }
        ],
    )
    return response.content[0].text


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_changes(c: dict) -> str:
    lines = []
    for h in c.get("new_positions", []):
        lines.append(f"▲ 신규 편입: {h['stock_name']} ({h['weight_pct']:.1f}%)")
    for h in c.get("closed_positions", []):
        lines.append(f"▼ 청산: {h['stock_name']}")
    for h in c.get("intentional_changes", []):
        lines.append(
            f"🔄 의도적 {h['direction']}: {h['stock_name']} "
            f"{h['prev_weight']:.1f}%→{h['weight_pct']:.1f}% (수량 {h['intentional_qty_delta']:+d})"
        )
    for h in c.get("passive_changes", []):
        lines.append(
            f"💧 가격 드리프트: {h['stock_name']} "
            f"{h['prev_weight']:.1f}%→{h['weight_pct']:.1f}%"
        )
    return "\n".join(lines) if lines else "변화 없음"
