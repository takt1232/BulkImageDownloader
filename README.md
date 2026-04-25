# 📥 Bulk Image Downloader

A zero-dependency Python script that downloads a list of raw image URLs in parallel — with grouped subfolder organization, a live progress bar, and a full download log.

---

## ✨ Features

- **Three input modes** — interactive paste, text file, or piped stdin
- **Group into subfolders** — use `# Comment Headers` in your URL list to organize downloads into named folders automatically
- **Parallel downloads** — configurable worker threads for fast batch downloading
- **Live progress bar** — real-time feedback with success/fail counters
- **Smart filenames** — derived from URL paths, with collision-safe numbering
- **Duplicate detection** — skips duplicate URLs before downloading
- **Full download log** — `download_log.txt` saved inside every output folder
- **Zero dependencies** — uses Python's standard library only

---

## 📋 Requirements

- Python 3.10 or higher
- No third-party packages needed

---

## 🚀 Usage

### Interactive mode
Run the script and paste URLs one by one directly in the terminal. Press **Enter on a blank line** when done.

```bash
python bulk_image_downloader.py
```

### File mode (recommended)
Prepare a `.txt` file with one URL per line, then pass it as an argument.

```bash
python bulk_image_downloader.py urls.txt
```

### File mode with custom workers
Control how many images download simultaneously (default: 5, max: 20).

```bash
python bulk_image_downloader.py urls.txt -w 10
```

### Help
```bash
python bulk_image_downloader.py --help
```

---

## 📁 URL File Format

Create a plain `.txt` file with your URLs. Use `# Comment Headers` to group images into subfolders.

```
# Product Photos
https://example.com/chair.jpg
https://example.com/table.jpg
https://example.com/lamp.jpg

# Banner Images
https://example.com/summer-banner.jpg
https://example.com/sale-banner.jpg

# Misc
https://example.com/logo.png
```

**Rules:**
- One URL per line
- Lines starting with `#` become subfolder names
- Blank lines are ignored
- URLs before the first `#` header go into the root output folder
- Duplicate URLs are automatically skipped

---

## 📂 Output Structure

Every run creates a timestamped folder next to the script containing your grouped images and a log file.

```
20260425_143022/
├── logo.png                  ← URLs before any # header
├── Product Photos/
│   ├── chair.jpg
│   ├── table.jpg
│   └── lamp.jpg
├── Banner Images/
│   ├── summer-banner.jpg
│   └── sale-banner.jpg
├── Misc/
│   └── logo.png
└── download_log.txt
```

---

## 🖥️ Terminal Output

```
Bulk Image Downloader
════════════════════════════════════════════════════════════
[10:42:01] ℹ INFO: Source file : urls.txt
[10:42:01] ℹ INFO: URLs found  : 9
[10:42:01] ℹ INFO: Workers     : 5  (parallel downloads)
[10:42:01] ℹ INFO: Output      : /downloads/20260425_104201

  Groups:
    • (root)            (1 URL)   → (root folder)
    • Product Photos    (3 URLs)  → Product Photos/
    • Banner Images     (2 URLs)  → Banner Images/
    • Misc              (1 URL)   → Misc/

════════════════════════════════════════════════════════════

Progress  [===========>        ]  56%  5/9  ✔ 4  ✘ 1

[10:42:02] ✔ SUCCESS: [1] [Product Photos] 284.3 KB → chair.jpg
[10:42:02] ✔ SUCCESS: [2] [Product Photos] 191.7 KB → table.jpg

════════════════════════════════════════════════════════════
  Download Summary
────────────────────────────────────────────────────────────
  ✔ Succeeded : 8
  ✘ Failed    : 1
  ⏱ Time      : 1.24s  (5 parallel workers)
  📁 Folder   : /downloads/20260425_104201

  Per group:
    • (root)            ✔ 1
    • Product Photos    ✔ 3
    • Banner Images     ✔ 2  ✘ 1
    • Misc              ✔ 1
════════════════════════════════════════════════════════════
```

---

## ⚙️ Options

| Flag | Description | Default |
|---|---|---|
| `urls.txt` | Path to a text file containing URLs | — |
| `-w`, `--workers` | Number of parallel download threads | `5` |
| `-h`, `--help` | Show usage information | — |

---

## 📝 Download Log

A `download_log.txt` is saved inside every output folder with a full per-URL report grouped by category.

```
Bulk Image Download Log
Generated : 2026-04-25T10:42:03.412
Source    : urls.txt
Folder    : /downloads/20260425_104201
Workers   : 5
============================================================

── Product Photos (3 URLs) ──
  [SUCCESS] (1) https://example.com/chair.jpg
    Detail  : 284.3 KB → chair.jpg
    Saved as: Product Photos/chair.jpg

  [FAILED] (2) https://example.com/broken.jpg
    Detail  : HTTP 404 Not Found

============================================================
Total: 9  |  Success: 8  |  Failed: 1  |  Skipped: 0
Elapsed: 1.24s
```

---

## 🪟 Windows Note

On Windows, use `python` instead of `python3`:

```bash
python bulk_image_downloader.py urls.txt
```

---

## 📄 License

MIT — free to use, modify, and distribute.
