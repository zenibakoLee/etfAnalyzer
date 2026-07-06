"""Discord webhook delivery — no bot dependency."""
from __future__ import annotations

import asyncio
import logging

import httpx

from src.config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1900


async def send_report(text: str, pdf_path: str | None = None, extra_files: list[str] | None = None):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        all_files = []
        if pdf_path:
            all_files.append(pdf_path)
        if extra_files:
            all_files.extend(extra_files)

        if all_files:
            await _send_webhook_with_files(text, all_files)
        else:
            await _send_webhook(text)
        logger.info("Daily report sent via webhook")
    except Exception:
        logger.exception("Failed to send webhook report")


async def _send_webhook_with_files(text: str, file_paths: list[str]):
    import mimetypes
    import os
    async with httpx.AsyncClient() as client:
        files = []
        open_handles = []
        try:
            for i, path in enumerate(file_paths):
                name = os.path.basename(path)
                mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
                fh = open(path, "rb")
                open_handles.append(fh)
                files.append((f"file{i}", (name, fh, mime)))
            resp = await client.post(
                DISCORD_WEBHOOK_URL,
                data={"content": text[:1900]},
                files=files,
            )
            resp.raise_for_status()
        finally:
            for fh in open_handles:
                fh.close()


async def _send_webhook(text: str):
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = (current + "\n" + line) if current else line
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(line) > CHUNK_SIZE:
                cut = _find_split(line, CHUNK_SIZE)
                chunks.append(line[:cut].rstrip())
                line = line[cut:].lstrip()
            current = line
    if current:
        chunks.append(current)

    async with httpx.AsyncClient() as client:
        for i, chunk in enumerate(chunks):
            resp = await client.post(DISCORD_WEBHOOK_URL, json={"content": chunk})
            resp.raise_for_status()
            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)


def _find_split(text: str, limit: int) -> int:
    for sep in (". ", "。", "! ", "? ", " "):
        pos = text.rfind(sep, 0, limit)
        if pos != -1:
            return pos + len(sep)
    return limit
