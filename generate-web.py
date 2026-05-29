"""
Gemini Image Generator — Playwright backend
Генерує зображення через gemini.google.com (безкоштовно, без API ключа).
Використовується як бібліотека з gemini-mcp-server.py.
"""

import asyncio


def process_image(
    image_bytes: bytes,
    width: int = 0,
    height: int = 0,
    fmt: str = "jpeg",
    quality: int = 82,
    max_size_kb: int = 200,
) -> tuple[bytes, dict]:
    """Ресайз + конвертація + гарантований розмір файлу.

    Повертає (bytes, info) де info = {width, height, size_kb, quality, format}.

    width/height = 0 → зберігаємо оригінальні розміри.
    fmt: "jpeg" | "webp" | "png"
    quality: початкова якість (1–95). Автоматично знижується до досягнення max_size_kb.
    max_size_kb: жорстка межа розміру файлу. 0 = без обмежень.
    """
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Ресайз
    if width and height:
        img = img.resize((width, height), Image.LANCZOS)
    elif width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    elif height:
        img = img.resize((round(img.width * height / img.height), height), Image.LANCZOS)

    out_w, out_h = img.size
    pil_fmt = {"jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP", "png": "PNG"}.get(fmt.lower(), "JPEG")

    def _encode(q: int) -> bytes:
        buf = io.BytesIO()
        if pil_fmt == "JPEG":
            img.save(buf, format="JPEG", quality=q, optimize=True,
                     progressive=True, subsampling=2)
        elif pil_fmt == "WEBP":
            img.save(buf, format="WEBP", quality=q, method=6)
        else:
            img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    # PNG — без стиснення якістю, повертаємо одразу
    if pil_fmt == "PNG":
        data = _encode(0)
        return data, {"width": out_w, "height": out_h,
                      "size_kb": round(len(data) / 1024), "quality": None, "format": "png"}

    # JPEG / WebP — знижуємо якість поки не вкладемось у max_size_kb
    q = quality
    data = _encode(q)

    if max_size_kb > 0:
        while len(data) > max_size_kb * 1024 and q > 20:
            q -= 5
            data = _encode(q)

    return data, {
        "width": out_w,
        "height": out_h,
        "size_kb": round(len(data) / 1024),
        "quality": q,
        "format": fmt.lower().replace("jpg", "jpeg"),
    }


def _make_short_prompt(prompt: str) -> str:
    """Нормалізує промпт до 500 символів для Gemini Web."""
    return " ".join(prompt.split())[:500]



async def _playwright_generate(short_prompt: str) -> bytes | None:
    """Генерує зображення через Playwright (реальний Chromium + Chrome cookies)."""
    from playwright.async_api import async_playwright

    pw_cookies = []
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".google.com")
        for c in cj:
            cookie = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain if c.domain else ".google.com",
                "path": c.path if c.path else "/",
                "secure": bool(c.secure),
                "httpOnly": False,
            }
            if hasattr(c, "expires") and c.expires and c.expires > 0:
                cookie["expires"] = float(c.expires)
            pw_cookies.append(cookie)
    except Exception as e:
        print(f"    ⚠️  Cookie: {e}")

    image_bytes_result = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.7778.168 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        if pw_cookies:
            try:
                await context.add_cookies(pw_cookies)
            except Exception as e:
                print(f"    ⚠️  add_cookies: {e}")

        page = await context.new_page()

        async def on_response(response):
            nonlocal image_bytes_result
            if image_bytes_result:
                return
            url = response.url
            ct = response.headers.get("content-type", "")
            if "rd-gg-dl/" in url and "googleusercontent.com" in url and "image/" in ct:
                try:
                    data = await response.body()
                    if len(data) > 10_000:
                        image_bytes_result = data
                        print(f"    🖼️  Зображення отримано ({len(data) // 1024} KB)")
                except Exception:
                    pass

        page.on("response", on_response)

        print("    🌐 Відкриваємо Gemini...")
        await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(3)

        if "accounts.google.com" in page.url:
            print("    ❌ Не залогінено — Chrome cookies не підходять")
            await browser.close()
            return None

        selectors = [
            "rich-textarea",
            'div[contenteditable="true"]',
            '[aria-label="Enter a prompt here"]',
            "p[data-placeholder]",
            ".ql-editor",
            "textarea",
        ]
        input_found = False
        for sel in selectors:
            try:
                elem = await page.wait_for_selector(sel, timeout=5_000, state="visible")
                if elem:
                    await elem.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.type(short_prompt, delay=15)
                    input_found = True
                    print(f"    ✍️  Промпт введено ({sel})")
                    break
            except Exception:
                continue

        if not input_found:
            print("    ❌ Поле вводу не знайдено")
            await page.screenshot(path="/tmp/gemini_debug.png")
            await browser.close()
            return None

        await page.keyboard.press("Enter")
        print("    ⏳ Очікуємо зображення (до 90 сек)...")

        for _ in range(90):
            if image_bytes_result:
                break
            await asyncio.sleep(1)

        await browser.close()

    return image_bytes_result


def generate_image(prompt: str) -> bytes | None:
    """Публічний інтерфейс: промпт → bytes PNG або None."""
    short = _make_short_prompt(prompt)
    try:
        return asyncio.run(_playwright_generate(short))
    except Exception as e:
        print(f"    ❌ Playwright error: {e}")
        return None
