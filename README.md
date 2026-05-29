# Gemini Image Generator — MCP Server

An MCP server that exposes a `generate_image` tool directly inside **Claude Desktop**.  
Generates images via **Gemini Web** — completely free, no API key required.

---

## How it works

```
Claude Desktop
     │
     │  calls generate_image(prompt, ...)
     ▼
gemini-mcp-server.py   ← MCP server (stdio)
     │
     │  imports & calls
     ▼
generate-web.py        ← Playwright backend
     │
     │  automates browser
     ▼
gemini.google.com      ← generates image (free)
     │
     │  returns PNG bytes
     ▼
gemini-mcp-server.py   ← resize / convert / compress (Pillow)
     │
     ├─ saves to  ./images/<filename>
     │
     └─ (optional) POST to upload.php → returns public URL
```

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python3 --version` |
| Chrome browser | Must be **logged in** to `gemini.google.com` |
| Chromium (Playwright) | Installed separately — see below |
| `pip` packages | `mcp`, `pillow`, `playwright`, `browser-cookie3` |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/gemini-image-gen-mcp.git
cd gemini-image-gen-mcp
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
```

### 3. Install Python dependencies

```bash
pip install mcp pillow playwright browser-cookie3
```

### 4. Install Chromium for Playwright

```bash
playwright install chromium
```

### 5. Log in to Gemini in Chrome

Open Chrome (the real Chrome browser, not Chromium) and go to `https://gemini.google.com`.  
Sign in with your Google account. The server reads cookies from your Chrome profile — no passwords are stored or sent anywhere.

---

## Configuration

### Claude Desktop config

Open (or create) the config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the MCP server entry:

```json
{
  "mcpServers": {
    "gemini-image-gen": {
      "command": "/ABSOLUTE/PATH/TO/gemini-image-gen-mcp/.venv/bin/python3",
      "args": ["/ABSOLUTE/PATH/TO/gemini-image-gen-mcp/gemini-mcp-server.py"]
    }
  }
}
```

> Replace `/ABSOLUTE/PATH/TO/` with the actual path where you cloned the repo.  
> Example: `/Users/john/Projects/gemini-image-gen-mcp`

After saving, **restart Claude Desktop**. You should see `gemini-image-gen` appear in the tools list.

### Environment variables (optional)

Required only if you want to upload generated images to your own server:

```bash
cp .env.example .env
# edit .env and set ASELEX_UPLOAD_TOKEN
```

You can also pass env vars directly in the Claude Desktop config:

```json
{
  "mcpServers": {
    "gemini-image-gen": {
      "command": "/path/to/.venv/bin/python3",
      "args": ["/path/to/gemini-mcp-server.py"],
      "env": {
        "ASELEX_UPLOAD_TOKEN": "your_secret_token_here"
      }
    }
  }
}
```

---

## Tool reference: `generate_image`

Claude calls this tool automatically when you ask it to generate an image.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | **required** | Image description in English. Starting with `Draw …` gives the best results |
| `output_file` | string | auto-derived | Output filename: `3-6_keywords.jpg` — derived from prompt if omitted |
| `title` | string | auto-derived | Image title in Title Case |
| `alt` | string | auto-derived | Alt text describing image content |
| `caption` | string | auto-derived | Short caption |
| `description` | string | auto-derived | Full natural-language description of the image |
| `width` | int | `1200` | Output width in pixels. `0` = keep original |
| `height` | int | `630` | Output height in pixels. `0` = keep original |
| `format` | string | `jpeg` | Output format: `jpeg` / `webp` / `png` |
| `quality` | int | `82` | Starting JPEG/WebP quality (1–95). Auto-reduced to meet `max_size_kb` |
| `max_size_kb` | int | `200` | Hard file size limit in KB. Quality is reduced automatically |
| `output_dir` | string | `./images/` | Absolute path to save directory. Created automatically if missing |
| `upload_to_site` | bool | `false` | Upload to your server via `upload.php` and return a public URL |

### Response

Returns JSON:

```json
{
  "saved": true,
  "url": "https://your-server.com/uploads/images/blue_car.jpg",
  "path": "/Users/john/Projects/gemini-image-gen-mcp/images/blue_car.jpg",
  "output_dir": "/Users/john/Projects/gemini-image-gen-mcp/images",
  "output_file": "blue_car.jpg",
  "prompt": "Draw a blue sports car on a city street at night",
  "title": "Blue Sports Car City Street",
  "alt": "A blue sports car driving on a city street at night with neon lights",
  "caption": "Blue sports car at night",
  "description": "A sleek blue sports car driving on a wet city street at night, surrounded by colorful neon lights reflecting on the pavement.",
  "width": 1200,
  "height": 630,
  "format": "jpeg",
  "quality": 78,
  "size_kb": 187,
  "max_size_kb": 200
}
```

### Example prompts

```
Generate an image of a cozy home office with warm lighting
Draw a product photo of a red coffee mug on a wooden table, white background
Create a featured image for a blog post about digital marketing, flat design style
Draw a portrait of a friendly robot assistant, cartoon style
```

---

## Recommended sizes

| Use case | Width | Height | Format | Quality |
|---|---|---|---|---|
| Blog featured image | 1200 | 630 | jpeg | 82 |
| Blog featured image (tall) | 1200 | 900 | jpeg | 82 |
| Inline image | 800 | 600 | jpeg | 80 |
| Product image (square) | 1000 | 1000 | jpeg | 85 |
| WebP (modern themes) | 1200 | 630 | webp | 82 |

---

## Server-side upload (optional)

`upload.php` lets you host generated images on your own web server and get a permanent public URL back.

### Setup

1. Upload `upload.php` to your web server at `/uploads/upload.php`
2. Create the directory `/uploads/images/` with write permissions:
   ```bash
   mkdir -p /var/www/html/uploads/images
   chmod 755 /var/www/html/uploads/images
   ```
3. Open `upload.php` and replace `REPLACE_WITH_YOUR_SECRET_TOKEN` with a strong random string:
   ```php
   define('UPLOAD_TOKEN', 'your_very_long_random_secret_here');
   ```
4. Optionally change `BASE_URL` to match your domain
5. Add the same token to `.env`:
   ```
   ASELEX_UPLOAD_TOKEN=your_very_long_random_secret_here
   ```

### How it works

- Accepts `POST` requests with `multipart/form-data` field `file`
- Authenticates via `X-Upload-Token` header
- Validates MIME type (only `image/jpeg`, `image/webp`, `image/png`)
- Limits file size to 16 MB
- Auto-deletes files older than 24 hours
- Returns JSON: `{"ok": true, "url": "https://your-server.com/uploads/images/file.jpg"}`

---

## Test the server manually

```bash
# Activate venv first
source .venv/bin/activate

# Start the MCP server (it listens on stdio)
python3 gemini-mcp-server.py
```

If it starts without errors, the server is working. Press `Ctrl+C` to stop.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Generation failed — not logged in` | Chrome has no Gemini session | Open Chrome → go to `gemini.google.com` → sign in |
| `Generation failed — Gemini overloaded` | Gemini rate limit | Wait 30 seconds and retry |
| `Cannot load generate-web.py` | File not found | Make sure `generate-web.py` is in the same directory as `gemini-mcp-server.py` |
| `playwright install chromium` fails | Permissions or disk space | Run with `sudo` or free up disk space |
| `ASELEX_UPLOAD_TOKEN not set` | Missing env var | Add token to `.env` or to the MCP server `env` config |
| Tool not showing in Claude Desktop | Wrong config path or restart needed | Check config file path, restart Claude Desktop |
| Images look pixelated | Resolution too low for the output size | Increase `width`/`height` or reduce them to match the generated resolution |

---

## Project structure

```
gemini-image-gen-mcp/
├── gemini-mcp-server.py   # MCP server — exposes generate_image tool
├── generate-web.py        # Playwright backend — browser automation + image processing
├── upload.php             # PHP endpoint for server-side image hosting
├── .env.example           # Environment variable template
└── .gitignore
```

---

## License

MIT
