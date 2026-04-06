"""
core/image_tools.py
-------------------
Image utility suite for the orchestrator agent.

Provides four tools for vision-capable LLMs:
  1. read_image      — Read & analyse an image (local path or URL)
  2. save_image      — Download/copy an image to a local path
  3. screenshot      — Capture a screenshot of the desktop
  4. extract_text    — OCR: extract text from an image

Supports both local file paths AND HTTP/HTTPS URLs.
Supported formats: PNG, JPEG, GIF, WEBP, BMP, TIFF, SVG
Max file size default: 20 MB.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_MIME_TYPES: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
    ".svg":  "image/svg+xml",
}

DEFAULT_MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
DEFAULT_TIMEOUT_SECONDS = 30


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_url(path: str) -> bool:
    """Check if the given path is an HTTP/HTTPS URL."""
    try:
        parsed = urlparse(path)
        return parsed.scheme in ("http", "https")
    except Exception:
        return False


def _resolve_mime_type(*, ext: str = "", content_type: str = "", url: str = "") -> str | None:
    """Determine MIME type from extension, Content-Type header, or URL."""
    if ext:
        mime = SUPPORTED_MIME_TYPES.get(ext.lower())
        if mime:
            return mime
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct.startswith("image/"):
            return ct
    source = url or (f"file{ext}" if ext else "")
    if source:
        guessed, _ = mimetypes.guess_type(source)
        if guessed and guessed.startswith("image/"):
            return guessed
    return None


def _download_bytes(url: str, max_size: int = DEFAULT_MAX_SIZE_BYTES,
                    timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[bytes, str, str]:
    """
    Download raw bytes from a URL.
    Returns (raw_bytes, content_type, file_name).
    """
    import urllib.request
    import urllib.error

    parsed = urlparse(url)
    url_path = parsed.path.rstrip("/")
    file_name = url_path.split("/")[-1] if url_path else "image"

    req = urllib.request.Request(url, headers={"User-Agent": "Agent_head/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > max_size:
                raise ValueError(
                    f"Remote file too large: {int(cl)/(1024*1024):.1f} MB "
                    f"(max {max_size/(1024*1024):.1f} MB). URL: {url}"
                )
            raw = resp.read(max_size + 1)
            if len(raw) > max_size:
                raise ValueError(
                    f"Remote file exceeded {max_size/(1024*1024):.1f} MB limit. URL: {url}"
                )
            ct = resp.headers.get("Content-Type", "")
            return raw, ct, file_name
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"Cannot reach {url}: {e.reason}") from e


# ─────────────────────────────────────────────────────────────────────────────
# 1. read_image_file  (core read + base64 encode)
# ─────────────────────────────────────────────────────────────────────────────

def read_image_file(
    file_path: str,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
) -> dict:
    """
    Read an image from a local path or URL and return base64-encoded data.

    Returns dict: base64_data, mime_type, file_name, file_size_bytes, source.
    """
    if _is_url(file_path):
        raw, ct, fname = _download_bytes(file_path, max_size=max_size_bytes)
        ext = Path(fname).suffix if fname else ""
        mime = _resolve_mime_type(ext=ext, content_type=ct, url=file_path)
        if mime is None:
            raise ValueError(f"Cannot determine image format from URL. Content-Type: '{ct}'")
        if not Path(fname).suffix:
            guess = mimetypes.guess_extension(mime)
            if guess:
                fname += guess
        return {
            "base64_data": base64.standard_b64encode(raw).decode("ascii"),
            "mime_type": mime, "file_name": fname,
            "file_size_bytes": len(raw), "source": "url",
        }
    else:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")
        ext = path.suffix.lower()
        mime = _resolve_mime_type(ext=ext)
        if mime is None:
            raise ValueError(f"Unsupported format '{ext}'. Supported: {sorted(SUPPORTED_MIME_TYPES)}")
        sz = path.stat().st_size
        if sz > max_size_bytes:
            raise ValueError(f"File too large: {sz/(1024*1024):.1f} MB (max {max_size_bytes/(1024*1024):.1f} MB)")
        raw = path.read_bytes()
        return {
            "base64_data": base64.standard_b64encode(raw).decode("ascii"),
            "mime_type": mime, "file_name": path.name,
            "file_size_bytes": sz, "source": "local",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. save_image_to_disk
# ─────────────────────────────────────────────────────────────────────────────

def save_image_to_disk(source: str, destination: str) -> dict:
    """
    Save an image from URL or local path to a destination on disk.

    Args:
        source: HTTP/HTTPS URL or local file path.
        destination: Target file path (directories created automatically).

    Returns dict: saved_to, file_name, file_size_bytes.
    """
    dest = Path(destination).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    if _is_url(source):
        raw, ct, fname = _download_bytes(source)
        dest.write_bytes(raw)
        logger.info("Saved image from URL to %s (%d bytes)", dest, len(raw))
    else:
        src = Path(source).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if not src.is_file():
            raise ValueError(f"Source is not a file: {src}")
        shutil.copy2(src, dest)
        logger.info("Copied image %s → %s", src, dest)

    return {
        "saved_to": str(dest),
        "file_name": dest.name,
        "file_size_bytes": dest.stat().st_size,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. take_screenshot
# ─────────────────────────────────────────────────────────────────────────────

def take_screenshot(output_path: str | None = None, monitor: int = 0) -> dict:
    """
    Capture a screenshot and return it as base64-encoded PNG.

    Requires the `mss` package (pip install mss).

    Args:
        output_path: If provided, also save the screenshot to this path.
        monitor: Monitor index (0 = all monitors, 1 = primary, 2+ = others).

    Returns dict: base64_data, mime_type, file_name, file_size_bytes, saved_to.
    """
    try:
        import mss
        import mss.tools
    except ImportError:
        raise ImportError(
            "The 'mss' package is required for screenshots. "
            "Install with: pip install mss"
        )

    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor >= len(monitors):
            monitor = 0  # fallback to all monitors

        grab = sct.grab(monitors[monitor])
        raw_png = mss.tools.to_png(grab.rgb, grab.size)

    b64 = base64.standard_b64encode(raw_png).decode("ascii")
    file_name = "screenshot.png"
    saved_to = None

    if output_path:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw_png)
        file_name = out.name
        saved_to = str(out)
        logger.info("Screenshot saved to %s (%d bytes)", out, len(raw_png))

    return {
        "base64_data": b64,
        "mime_type": "image/png",
        "file_name": file_name,
        "file_size_bytes": len(raw_png),
        "source": "screenshot",
        "saved_to": saved_to,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. extract_text_from_image (OCR)
# ─────────────────────────────────────────────────────────────────────────────

def extract_text_from_image(file_path: str) -> str:
    """
    Extract text from an image using Tesseract OCR.

    Requires: pip install pytesseract Pillow
    Also requires Tesseract-OCR binary installed on the system.

    Supports local paths and HTTP/HTTPS URLs.

    Returns the extracted text string.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ImportError(
            "OCR requires 'pytesseract' and 'Pillow'. Install with:\n"
            "  pip install pytesseract Pillow\n"
            "Also install Tesseract-OCR binary:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Linux:   sudo apt install tesseract-ocr\n"
            "  macOS:   brew install tesseract\n\n"
            "Alternatively, use the 'read_image' tool with question='Extract all text from this image' "
            "to leverage the vision LLM instead of OCR."
        )

    import io

    if _is_url(file_path):
        raw, _, _ = _download_bytes(file_path)
        img = Image.open(io.BytesIO(raw))
    else:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        img = Image.open(path)

    text = pytesseract.image_to_string(img)
    logger.info("OCR extracted %d characters from %s", len(text), file_path)
    return text.strip() if text else "(No text detected in image)"


# ─────────────────────────────────────────────────────────────────────────────
# Tool factory — creates all LangChain tools in one place
# ─────────────────────────────────────────────────────────────────────────────

def _make_multimodal_response(result: dict, text_prefix: str) -> list:
    """Build a multimodal tool response (text + base64 image)."""
    return [
        {
            "type": "text",
            "text": f"[{text_prefix}: {result['file_name']} "
                    f"({result['file_size_bytes']} bytes, {result['mime_type']})]",
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{result['mime_type']};base64,{result['base64_data']}"
            },
        },
    ]


def get_image_tools(
    enabled: bool = True,
    enable_save: bool = True,
    enable_screenshot: bool = True,
    enable_ocr: bool = True,
    screenshot_dir: str = "./screenshots",
) -> list:
    """
    Create and return image-related LangChain tools based on config flags.

    Args:
        enabled: Master switch. If False, returns empty list.
        enable_save: Include the save_image tool.
        enable_screenshot: Include the screenshot tool.
        enable_ocr: Include the extract_text (OCR) tool.
        screenshot_dir: Directory to auto-save screenshots to.

    read_image is always included when enabled=True.
    """
    if not enabled:
        return []

    from langchain_core.tools import tool as lc_tool

    tools = []

    # ── 1. read_image (always on when enabled) ────────────────────────────

    @lc_tool
    def read_image(
        file_path: str,
        question: str = "Describe this image in detail.",
    ) -> list:
        """
        Read an image from a local file path or HTTP/HTTPS URL and return it for visual analysis.
        Use this when you need to view, describe, or extract information from an image.

        Supported formats: PNG, JPEG, GIF, WEBP, BMP, TIFF, SVG. Max 20 MB.

        args:
            file_path (str): Local path or URL to the image.
            question (str): What to analyse. Defaults to describing the image.
        """
        result = read_image_file(file_path)
        response = _make_multimodal_response(result, "Image")
        response[0]["text"] += f"\n{question}"
        return response

    tools.append(read_image)

    # ── 2. save_image ─────────────────────────────────────────────────────

    if enable_save:
        @lc_tool
        def save_image(source: str, destination: str) -> str:
            """
            Save/download an image to a local file path.
            Use this to download an image from a URL or copy a local image to a new location.

            args:
                source (str): HTTP/HTTPS URL or local file path of the source image.
                destination (str): Local file path to save the image to (directories are created automatically).
            """
            result = save_image_to_disk(source, destination)
            return (
                f"Image saved successfully.\n"
                f"  Path: {result['saved_to']}\n"
                f"  Size: {result['file_size_bytes']} bytes"
            )

        tools.append(save_image)

    # ── 3. screenshot ─────────────────────────────────────────────────────

    if enable_screenshot:
        _screenshot_dir = screenshot_dir

        @lc_tool
        def screenshot(
            output_path: str = "",
            monitor: int = 0,
        ) -> list:
            """
            Capture a screenshot of the desktop and return it for visual analysis.
            Use this to see what is currently on screen.
            Screenshots are automatically saved to the configured directory.

            args:
                output_path (str): Custom file path to save. Leave empty to auto-save to the configured screenshot directory.
                monitor (int): Monitor to capture (0 = all monitors, 1 = primary, 2 = secondary).
            """
            import time as _time
            # Auto-generate path if not provided
            save_path = output_path if output_path else None
            if not save_path:
                _dir = Path(_screenshot_dir)
                _dir.mkdir(parents=True, exist_ok=True)
                ts = _time.strftime("%Y%m%d_%H%M%S")
                save_path = str(_dir / f"screenshot_{ts}.png")

            result = take_screenshot(output_path=save_path, monitor=monitor)
            response = _make_multimodal_response(result, "Screenshot")
            if result.get("saved_to"):
                response[0]["text"] += f"\nSaved to: {result['saved_to']}"
            return response

        tools.append(screenshot)

    # ── 4. extract_text (OCR) ─────────────────────────────────────────────

    if enable_ocr:
        @lc_tool
        def extract_text(file_path: str) -> str:
            """
            Extract text from an image using OCR (Optical Character Recognition).
            Use this to read text from photos of documents, receipts, signs, code screenshots, etc.

            Supports local paths and HTTP/HTTPS URLs.
            Requires pytesseract + Tesseract-OCR to be installed.

            args:
                file_path (str): Local path or URL to the image containing text.
            """
            return extract_text_from_image(file_path)

        tools.append(extract_text)

    return tools

