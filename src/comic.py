"""4-panel manga summary image via Gemini image generation."""
import base64
import logging
import tempfile

from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def generate_comic(report_data: str, date_str: str) -> str | None:
    if not GEMINI_API_KEY or not report_data:
        return None

    # Quadrant-position spec — a free-form "4컷만화 그려줘" prompt (or even
    # "정확히 4컷" counting rules) lets the model improvise a 6-panel grid
    # and duplicate content to fill it
    prompt = f"""하나의 이미지를 생성해줘: 2x2 그리드로 나뉜 정사각형 4컷만화. 칸은 정확히 4개이며, 각 칸의 내용은 아래에 위치별로 지정되어 있다.

스타일: 미소녀(분홍 머리)가 남학생에게 오늘의 ETF 리포트를 쉽게 설명해주는 학원물 만화. 비전공자 눈높이.

[오늘의 ETF 리포트 내용]
{report_data}

[왼쪽 위 칸 — 도입] 오늘 시장/ETF의 가장 큰 뉴스를 한 문장으로 소개
[오른쪽 위 칸 — 핵심 변화] 가장 중요한 보유종목 변화 또는 수익률 포인트
[왼쪽 아래 칸 — 해석] 그 변화가 왜 중요한지 쉬운 비유로 설명
[오른쪽 아래 칸 — 결론] 오늘의 핵심 교훈 정리

제약:
- 이미지 전체는 반드시 2x2 = 4칸. 다섯 번째 칸을 만들지 마라.
- 네 칸의 대사와 장면은 각각 지정 내용만 다루고, 칸끼리 중복 금지.
- 말풍선은 자연스러운 한국어, 오탈자 금지.
- 이미지 하단에 "{date_str} ETF 일일 보고서" 표기."""
    try:
        resp = _get_client().models.generate_content(
            model="gemini-3-pro-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
        for part in resp.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                ext = part.inline_data.mime_type.split("/")[-1]
                path = tempfile.mktemp(suffix=f"_comic_{date_str}.{ext}")
                with open(path, "wb") as f:
                    f.write(part.inline_data.data)
                logger.info("Comic generated: %s", path)
                return path

        logger.warning("Gemini response contained no image parts")
        return None
    except Exception:
        logger.exception("Comic generation failed")
        return None
