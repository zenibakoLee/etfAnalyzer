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

def generate_etf_report(changes: dict, prev_insight: str = "") -> str:
    changes_summary = _format_changes(changes)
    prior_context = f"\n---\n과거 누적 인사이트:\n{prev_insight}" if prev_insight else ""

    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[
            {
                "role": "user",
                "content": f"""당신은 ETF 포트폴리오 분석 전문가입니다. 아래 데이터를 기반으로 오늘의 변화를 분석해주세요.

ETF: {changes['etf_name']}
날짜: {changes['date']}
베이스라인 비율(설정/해지): {changes.get('baseline_ratio', 1.0):.4f}

변화 내역:
{changes_summary}{prior_context}

다음 형식으로 간결하게 한국어로 답변해주세요:

**오늘의 주요 변화**
- 신규 편입/청산/의도적 비중조절 핵심 내용 2-3줄

**운용 의도 분석**
- 이 변화의 배경이나 의도 1-2줄

**주목할 점**
- 투자자 관점에서 주목할 1가지""",
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
        messages=[
            {
                "role": "user",
                "content": f"""다음 ETF들의 오늘 변화를 종합하여, 오늘 시장의 큰 그림을 2-3문장으로 한국어로 요약해주세요.
어떤 섹터/테마가 부각되고 있는지, 전반적인 포지셔닝 변화가 무엇을 시사하는지 포함해주세요.

{summaries}""",
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
        messages=[
            {
                "role": "user",
                "content": f"""당신은 ETF 운용 전문가입니다. {etf_name}의 누적 운용 이력을 분석하여 인사이트를 도출해주세요.

운용 이력 (최근 {len(recent)}회):
{history}

다음 형식으로 한국어로 답변해주세요:

**운용 원칙 분석**
이 ETF가 어떤 기준으로 종목을 선택하고 비중을 조절하는지

**비중 원칙 변화 이력**
시간에 따른 운용 스타일/원칙의 변화가 있다면

**핵심 인사이트**
이 ETF에 투자할 때 알아야 할 가장 중요한 3가지""",
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
