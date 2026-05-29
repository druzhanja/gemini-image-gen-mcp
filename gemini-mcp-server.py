#!/usr/bin/env python3
"""
Gemini Image Generator — MCP Server
====================================
Виставляє generate_image як інструмент Claude.
Claude викликає його напряму — ніякого Terminal, ніякого copy-paste.

ВСТАНОВЛЕННЯ:
    pip install mcp pillow playwright browser-cookie3
    playwright install chromium

КОНФІГУРАЦІЯ (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "gemini-image-gen": {
          "command": "/Users/mac/Documents/Claude/Projects/amazon-kdp/hello-summer/.venv/bin/python3",
          "args": ["/Users/mac/Documents/Claude/Projects/amazon-kdp/hello-summer/gemini-mcp-server.py"]
        }
      }
    }

ЗАПУСК ДЛЯ ТЕСТУ:
    .venv/bin/python3 gemini-mcp-server.py
"""

import asyncio
import importlib.util
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

# ── Завантажуємо .env з директорії скрипту ───────────────────────────────────
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

_load_dotenv(Path(__file__).parent / ".env")

# ── Токен для завантаження на aselex.app ──────────────────────────────────────
_ASELEX_TOKEN = os.environ.get("ASELEX_UPLOAD_TOKEN", "").strip()

# ── Завантажуємо generate-web.py ──────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
# generate-web.py може лежати в іншій папці — шукаємо в кількох місцях
_GEN_WEB_CANDIDATES = [
    _SCRIPT_DIR / "generate-web.py",
    Path("/Users/mac/Documents/Claude/Projects/amazon-kdp/hello-summer/generate-web.py"),
]
_GEN_WEB = next((p for p in _GEN_WEB_CANDIDATES if p.exists()), _SCRIPT_DIR / "generate-web.py")

def _load_gen_web():
    import builtins, io
    _real_open = builtins.open

    def _patched_open(file, *args, **kwargs):
        # generate-web.py завантажує simple-book.csv при старті — підставляємо порожній файл
        if str(file).endswith(".csv"):
            return io.StringIO("page_number,image_name,image_prompt,has_luna,luna_placement\n")
        return _real_open(file, *args, **kwargs)

    builtins.open = _patched_open
    try:
        spec = importlib.util.spec_from_file_location("generate_web", _GEN_WEB)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        builtins.open = _real_open
    return mod

try:
    _gw = _load_gen_web()
    _playwright_generate = _gw._playwright_generate
    _make_short_prompt   = _gw._make_short_prompt
except Exception as e:
    # Якщо generate-web.py недоступний — сервер стартує, але інструмент поверне помилку
    _playwright_generate = None
    _make_short_prompt   = None
    _LOAD_ERROR          = str(e)
else:
    _LOAD_ERROR = None

# ── MCP сервер ────────────────────────────────────────────────────────────────
server = Server("gemini-image-gen")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_image",
            description=(
                "Generate an image using Gemini Web (free, no API key). "
                "Before calling, Claude must prepare all metadata fields from the prompt: "
                "output_file (3-6 keyword slug), title, alt, caption, description. "
                "Returns JSON with path, title, alt, caption, description."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Image description in English. Start with 'Draw …' for best results.",
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Filename: 3-6 keywords from prompt joined by '_', ending in .png. Example: 'blue_sports_car_city_street.png'",
                    },
                    "title": {
                        "type": "string",
                        "description": "Image title, Title Case. Example: 'Blue Sports Car City Street'",
                    },
                    "alt": {
                        "type": "string",
                        "description": "Alt text describing the image content.",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Short caption for the image.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Full natural language description of what is depicted in the image.",
                    },
                    "width": {
                        "type": "integer",
                        "description": "Output width in px. Featured image: 1200 or 1600. Inline: 800 or 1000. 0 = original.",
                    },
                    "height": {
                        "type": "integer",
                        "description": "Output height in px. Featured image: 630 or 900. Inline: 600 or 667. 0 = original.",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["jpeg", "webp", "png"],
                        "description": "Output format. Use jpeg for photos (5-8x smaller than png), webp if theme supports it.",
                    },
                    "quality": {
                        "type": "integer",
                        "description": "Starting JPEG/WebP quality 1-95. Auto-reduced until max_size_kb is met. Featured: 82, Inline: 80.",
                    },
                    "max_size_kb": {
                        "type": "integer",
                        "description": "Hard file size limit in KB. Quality is auto-reduced until met. Default: 200. Hard limit: 200.",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Absolute path to output directory. Optional. Default: <script_dir>/images. Example: '/Users/mac/Documents/Claude/Projects/amazon-affiliate-kitchaneers.com/images'. Directory is created automatically if it does not exist.",
                    },
                    "upload_to_site": {
                        "type": "boolean",
                        "description": "If true — upload generated image to aselex.app and return 'url' field in response. Token is read from ASELEX_UPLOAD_TOKEN env var. Default: false.",
                    },
                    "cleanup_days": {
                        "type": "integer",
                        "description": "Delete files in the output directory older than N days. 0 = never delete. Default: 1.",
                    },
                },
                "required": ["prompt"],
            },
        )
    ]


def _upload_to_aselex(image_bytes: bytes, filename: str, token: str) -> str | None:
    """Завантажує image_bytes на aselex.app, повертає публічний URL або None."""
    import ssl
    endpoint = "https://aselex.app/uploads/upload.php"
    boundary = "----MCPBoundary" + str(int(time.time()))
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-Upload-Token", token)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    try:
        ctx = ssl.create_default_context()
    except Exception:
        ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read())
            return data.get("url")
    except Exception:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read())
            return data.get("url")


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "generate_image":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    # Перевіряємо що generate-web.py завантажився
    if _LOAD_ERROR:
        return [TextContent(
            type="text",
            text=f"❌ Cannot load generate-web.py: {_LOAD_ERROR}\n"
                 f"Make sure generate-web.py is in: {_SCRIPT_DIR}"
        )]

    prompt      = (arguments.get("prompt") or "").strip()
    if not prompt:
        return [TextContent(type="text", text="❌ 'prompt' is required")]

    fmt          = (arguments.get("format") or "jpeg").lower()
    width        = int(arguments.get("width") or 1200)
    height       = int(arguments.get("height") or 630)
    quality      = int(arguments.get("quality") or 82)
    max_size_kb  = int(arguments.get("max_size_kb") or 200)
    output_dir   = (arguments.get("output_dir") or "").strip()
    cleanup_days = int(arguments.get("cleanup_days") if arguments.get("cleanup_days") is not None else 1)

    # Деривація відсутніх метаданих із prompt
    clean_prompt = re.sub(r"^\s*draw\s+", "", prompt, flags=re.IGNORECASE).strip()
    words        = re.findall(r"[A-Za-z0-9]+", clean_prompt)
    slug_words   = [w.lower() for w in words[:6]] or ["image"]
    ext          = {"jpeg": ".jpg", "webp": ".webp", "png": ".png"}.get(fmt, ".jpg")

    output_file = (arguments.get("output_file") or "").strip() or ("_".join(slug_words) + ext)
    title       = (arguments.get("title") or "").strip()       or " ".join(w.capitalize() for w in slug_words)
    alt         = (arguments.get("alt") or "").strip()         or clean_prompt
    caption     = (arguments.get("caption") or "").strip()     or clean_prompt
    description = (arguments.get("description") or "").strip() or clean_prompt

    short_prompt = _make_short_prompt(prompt)

    # Генеруємо
    try:
        image_bytes = await _playwright_generate(short_prompt)
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Generation error: {e}")]

    if image_bytes is None:
        return [TextContent(
            type="text",
            text=(
                "❌ Generation failed.\n"
                "• Not logged in to gemini.google.com in Chrome → open it and sign in\n"
                "• Playwright not installed → run: playwright install chromium\n"
                "• Gemini overloaded → wait 30s and retry"
            )
        )]

    # Конвертуємо / ресайзимо / стискаємо
    try:
        image_bytes, img_info = _gw.process_image(
            image_bytes,
            width=width,
            height=height,
            fmt=fmt,
            quality=quality,
            max_size_kb=max_size_kb,
        )
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Image processing error: {e}")]

    # Зберігаємо файл — структура images/YYYY/MM/
    date_subdir = datetime.now().strftime("%Y/%m")
    base_dir    = Path(output_dir) if output_dir else _SCRIPT_DIR / "images"
    month_dir   = base_dir / date_subdir
    month_dir.mkdir(parents=True, exist_ok=True)

    # Вирішуємо конфлікти імен: file.jpg → file-2.jpg → file-3.jpg
    stem     = Path(output_file).stem
    suffix   = Path(output_file).suffix
    out_path = month_dir / output_file
    counter  = 2
    while out_path.exists():
        out_path = month_dir / f"{stem}-{counter}{suffix}"
        counter += 1

    # Видаляємо файли в поточному місяці старші cleanup_days (0 = не видаляти)
    if cleanup_days > 0:
        cutoff = time.time() - cleanup_days * 86400
        for old_file in month_dir.iterdir():
            if old_file.is_file() and old_file != out_path and old_file.stat().st_mtime < cutoff:
                old_file.unlink(missing_ok=True)

    out_path.write_bytes(image_bytes)

    exists = out_path.exists() and out_path.stat().st_size > 0

    upload_to_site = bool(arguments.get("upload_to_site"))
    site_url       = None

    if upload_to_site:
        if not _ASELEX_TOKEN:
            return [TextContent(type="text", text="❌ ASELEX_UPLOAD_TOKEN env var is not set — add it to MCP server config")]
        site_url = _upload_to_aselex(image_bytes, out_path.name, _ASELEX_TOKEN)
        if not site_url:
            return [TextContent(type="text", text="❌ Upload to aselex.app failed — check token and server connectivity")]

    return [
        TextContent(
            type="text",
            text=json.dumps({
                "saved":       exists,
                "url":         site_url,
                "path":        str(out_path),
                "output_dir":  str(out_path.parent),
                "output_file": out_path.name,
                "prompt":      prompt,
                "title":       title,
                "alt":         alt,
                "caption":     caption,
                "description": description,
                "width":       img_info["width"],
                "height":      img_info["height"],
                "format":      img_info["format"],
                "quality":     img_info["quality"],
                "size_kb":     img_info["size_kb"],
                "max_size_kb": max_size_kb,
            }, ensure_ascii=False, indent=2),
        ),
    ]


# ── Точка входу ───────────────────────────────────────────────────────────────
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
