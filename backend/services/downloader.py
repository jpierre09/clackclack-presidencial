"""HTTP downloader utilities for E14 PDFs."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/pdf,application/json,text/plain,*/*",
    "Referer": "https://divulgacione14congreso.registraduria.gov.co/",
}


async def download_pdf(url: str, target_path: Path, timeout_s: int = 30, retries: int = 3) -> bool:
    """Download a PDF with retries. Returns True if file exists and has data."""
    target_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
                    raise ValueError(f"Unexpected content type: {content_type}")

                target_path.write_bytes(response.content)
                return target_path.exists() and target_path.stat().st_size > 0
        except Exception:
            if attempt == retries:
                return False
            await asyncio.sleep(min(2 * attempt, 6))

    return False
