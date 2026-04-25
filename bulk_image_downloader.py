#!/usr/bin/env python3
"""
Bulk Image Downloader
---------------------
Downloads a list of raw image URLs into a timestamped folder located
next to this script. URLs can be organized into subfolders using
comment headers in the input file.

Usage:
  python bulk_image_downloader.py               # interactive paste mode
  python bulk_image_downloader.py urls.txt      # load URLs from a text file
  python bulk_image_downloader.py urls.txt -w 8 # use 8 parallel workers

File format (urls.txt):
  - One URL per line
  - Blank lines are ignored
  - Lines starting with # define a group — URLs below go into that subfolder
  - URLs before any # header go into the root output folder

Example:
  # Product Photos
  https://example.com/photo1.jpg
  https://example.com/photo2.jpg

  # Banner Images
  https://example.com/banner.jpg

Output structure:
  20260425_143022/
  ├── photo1.jpg          ← URLs before any header
  ├── Product Photos/
  │   ├── photo1.jpg
  │   └── photo2.jpg
  ├── Banner Images/
  │   └── banner.jpg
  └── download_log.txt
"""

import re
import sys
import time
import threading
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_WORKERS = 5
MAX_WORKERS     = 20
TIMEOUT_SECONDS = 30
USER_AGENT      = "BulkImageDownloader/1.0"

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[2m"


# ── Thread-safe logger ───────────────────────────────────────────────────────

_print_lock = threading.Lock()


def tprint(*args, **kwargs) -> None:
    """Thread-safe print — prevents interleaved output from concurrent workers."""
    with _print_lock:
        print(*args, **kwargs)


def log(symbol: str, color: str, label: str, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    tprint(f"{DIM}[{timestamp}]{RESET} {color}{symbol} {BOLD}{label}{RESET}{color}:{RESET} {message}")


def log_info(message: str)    -> None: log("ℹ", CYAN,   "INFO",    message)
def log_success(message: str) -> None: log("✔", GREEN,  "SUCCESS", message)
def log_error(message: str)   -> None: log("✘", RED,    "ERROR",   message)
def log_warn(message: str)    -> None: log("⚠", YELLOW, "WARNING", message)
def log_skip(message: str)    -> None: log("↷", YELLOW, "SKIPPED", message)


def separator(char: str = "─", width: int = 60) -> None:
    tprint(f"{DIM}{char * width}{RESET}")


# ── Progress bar ─────────────────────────────────────────────────────────────

class ProgressBar:
    """
    Thread-safe live progress bar on a single terminal line.
    Example: Progress  [===========>        ]  56%  28/50  ✔ 25  ✘ 3
    """

    BAR_WIDTH = 20

    def __init__(self, total: int) -> None:
        self._total     = total
        self._done      = 0
        self._succeeded = 0
        self._failed    = 0
        self._lock      = threading.Lock()

    def update(self, succeeded: bool) -> None:
        with self._lock:
            self._done += 1
            if succeeded:
                self._succeeded += 1
            else:
                self._failed += 1
            self._render()

    def _render(self) -> None:
        pct    = self._done / self._total if self._total else 0
        filled = int(self.BAR_WIDTH * pct)
        arrow  = ">" if filled < self.BAR_WIDTH else ""
        empty  = self.BAR_WIDTH - filled - len(arrow)
        bar    = "=" * filled + arrow + " " * empty
        line   = (
            f"\r{CYAN}Progress{RESET}  "
            f"[{GREEN}{bar}{RESET}] "
            f"{BOLD}{pct:>4.0%}{RESET}  "
            f"{DIM}{self._done}/{self._total}{RESET}  "
            f"{GREEN}✔ {self._succeeded}{RESET}  "
            f"{RED}✘ {self._failed}{RESET}  "
        )
        print(line, end="", flush=True)

    def finish(self) -> None:
        print()


# ── Group / URL parsing ───────────────────────────────────────────────────────

# A "group" is a named collection of URLs that maps to a subfolder.
# group=None means the root output folder (no header seen yet).
type UrlEntry = tuple[str | None, str]   # (group_name_or_None, url)


def sanitize_folder_name(raw: str) -> str:
    """
    Turn a comment header into a safe folder name.
      1. Strip leading # characters and whitespace
      2. Replace characters illegal on Windows/macOS/Linux with a space
      3. Collapse multiple spaces, strip edges
      4. Truncate to 60 chars to stay filesystem-friendly
    """
    name = raw.lstrip("#").strip()
    # Characters forbidden on Windows: \ / : * ? " < > |
    # Also strip control characters
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", name)
    name = re.sub(r" {2,}", " ", name).strip()
    return name[:60] if name else "Unnamed Group"


def parse_entries_from_lines(lines: list[str]) -> list[UrlEntry]:
    """
    Walk through raw lines and produce (group, url) pairs.
    - Comment lines (#...) set the current group name.
    - URL lines are tagged with the current group (None = root).
    - Blank lines are ignored.
    """
    entries: list[UrlEntry] = []
    current_group: str | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_group = sanitize_folder_name(line)
        else:
            entries.append((current_group, line))

    return entries


def load_entries_from_file(filepath: str) -> list[UrlEntry]:
    path = Path(filepath)
    if not path.exists():
        tprint(f"{RED}Error: file not found — {filepath!r}{RESET}")
        sys.exit(1)
    if not path.is_file():
        tprint(f"{RED}Error: path is not a file — {filepath!r}{RESET}")
        sys.exit(1)

    with path.open("r", encoding="utf-8") as f:
        return parse_entries_from_lines(f.readlines())


def collect_entries_interactive() -> list[UrlEntry]:
    """
    Interactive mode: paste URLs (and optional # group headers) one per line.
    Empty line ends input.
    """
    tprint()
    tprint(f"{BOLD}Bulk Image Downloader{RESET}")
    separator("═")
    tprint(f"Paste URLs — {BOLD}one per line{RESET}. Use {BOLD}# Group Name{RESET} headers to create subfolders.")
    tprint(f"Press {BOLD}Enter{RESET} on an empty line when done (or {BOLD}Ctrl+Z{RESET} on Windows).")
    separator()
    tprint()

    raw_lines: list[str] = []
    entry_count = 0
    try:
        while True:
            line = input(f"  {DIM}{'#Group or URL':>14} {entry_count + 1:>3}:{RESET} ").strip()
            if not line:
                if raw_lines:
                    break
                tprint(f"  {YELLOW}(enter a URL or # Group Name, or press Enter again to finish){RESET}")
                line2 = input(f"  {DIM}{'#Group or URL':>14} {entry_count + 1:>3}:{RESET} ").strip()
                if not line2:
                    break
                raw_lines.append(line2)
                if not line2.startswith("#"):
                    entry_count += 1
            else:
                raw_lines.append(line)
                if not line.startswith("#"):
                    entry_count += 1
    except EOFError:
        pass

    return parse_entries_from_lines(raw_lines)


# ── Filesystem helpers ────────────────────────────────────────────────────────

def derive_filename(url: str, index: int) -> str:
    """Derive a safe filename from the URL. Falls back to a numbered name."""
    parsed = urllib.parse.urlparse(url)
    name   = Path(parsed.path).name.split("?")[0].split("#")[0]
    if not name or "." not in name:
        name = f"image_{index + 1:04d}.jpg"
    return name


_filename_lock = threading.Lock()


def make_unique_path(folder: Path, filename: str) -> Path:
    """
    Thread-safe unique path reservation inside `folder`.
    Touches the file immediately to hold the slot.
    """
    with _filename_lock:
        target = folder / filename
        if not target.exists():
            target.touch()
            return target

        stem    = Path(filename).stem
        suffix  = Path(filename).suffix
        counter = 1
        while True:
            candidate = folder / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                candidate.touch()
                return candidate
            counter += 1


# ── Download worker ───────────────────────────────────────────────────────────

def download_image(url: str, dest_path: Path) -> tuple[bool, str]:
    """Download a single image. Returns (success, detail_message)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type and not content_type.startswith("image/"):
                dest_path.unlink(missing_ok=True)
                return False, f"unexpected Content-Type: {content_type!r}"

            data = response.read()
            dest_path.write_bytes(data)
            size_kb = len(data) / 1024
            return True, f"{size_kb:.1f} KB → {dest_path.name}"

    except urllib.error.HTTPError as e:
        dest_path.unlink(missing_ok=True)
        return False, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        dest_path.unlink(missing_ok=True)
        return False, f"URL error: {e.reason}"
    except TimeoutError:
        dest_path.unlink(missing_ok=True)
        return False, f"timed out after {TIMEOUT_SECONDS}s"
    except Exception as e:
        dest_path.unlink(missing_ok=True)
        return False, str(e)


def process_entry(
    index:         int,
    url:           str,
    group:         str | None,
    output_folder: Path,
    bar:           ProgressBar,
) -> dict:
    """
    Validate and download one URL into the correct subfolder (or root).
    Called from ThreadPoolExecutor workers.
    """
    display_url   = url if len(url) <= 68 else url[:65] + "..."
    group_label   = f"{CYAN}[{group}]{RESET} " if group else ""

    if not url.lower().startswith(("http://", "https://")):
        log_skip(f"[{index}] {group_label}{display_url} — invalid scheme")
        bar.update(succeeded=False)
        return {"url": url, "group": group, "status": "skipped", "detail": "invalid scheme"}

    # Resolve destination folder — create subfolder on demand
    dest_folder = output_folder / group if group else output_folder
    dest_folder.mkdir(parents=True, exist_ok=True)

    filename  = derive_filename(url, index - 1)
    dest_path = make_unique_path(dest_folder, filename)

    success, detail = download_image(url, dest_path)
    bar.update(succeeded=success)

    relative = f"{group}/{dest_path.name}" if group else dest_path.name

    if success:
        log_success(f"[{index}] {group_label}{detail}")
        return {"url": url, "group": group, "status": "success", "detail": detail, "file": relative}
    else:
        log_error(f"[{index}] {group_label}{display_url} — {detail}")
        return {"url": url, "group": group, "status": "failed", "detail": detail}


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> tuple[str | None, int]:
    """Returns (file_path_or_None, worker_count)."""
    args    = sys.argv[1:]
    file_in = None
    workers = DEFAULT_WORKERS

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-w", "--workers"):
            i += 1
            if i >= len(args):
                tprint(f"{RED}Error: -w requires a number{RESET}")
                sys.exit(1)
            try:
                workers = max(1, min(MAX_WORKERS, int(args[i])))
            except ValueError:
                tprint(f"{RED}Error: -w value must be an integer{RESET}")
                sys.exit(1)
        elif arg in ("-h", "--help"):
            tprint(__doc__)
            sys.exit(0)
        elif not arg.startswith("-"):
            file_in = arg
        i += 1

    return file_in, workers


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    file_in, workers = parse_args()

    # ── Collect entries ───────────────────────────────────────────────────
    if file_in:
        entries = load_entries_from_file(file_in)
        tprint()
        tprint(f"{BOLD}Bulk Image Downloader{RESET}")
        separator("═")
        log_info(f"Source file : {BOLD}{file_in}{RESET}")
    elif not sys.stdin.isatty():
        lines   = sys.stdin.readlines()
        entries = parse_entries_from_lines(lines)
        tprint()
        tprint(f"{BOLD}Bulk Image Downloader{RESET}")
        separator("═")
        log_info("Source : stdin (piped)")
    else:
        entries = collect_entries_interactive()

    if not entries:
        log_warn("No URLs provided. Exiting.")
        sys.exit(0)

    # ── Deduplicate by URL (preserve order) ───────────────────────────────
    seen: set[str]              = set()
    unique_entries: list[UrlEntry] = []
    for group, url in entries:
        if url not in seen:
            seen.add(url)
            unique_entries.append((group, url))

    duplicates_removed = len(entries) - len(unique_entries)

    # ── Summarize groups ──────────────────────────────────────────────────
    group_counts: dict[str, int] = {}
    for group, _ in unique_entries:
        label = group if group else "(root)"
        group_counts[label] = group_counts.get(label, 0) + 1

    # ── Create root output folder ─────────────────────────────────────────
    script_dir    = Path(__file__).parent.resolve()
    timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_folder = script_dir / timestamp
    output_folder.mkdir(parents=True, exist_ok=True)

    dup_note = f"  {DIM}({duplicates_removed} duplicate(s) removed){RESET}" if duplicates_removed else ""
    log_info(f"URLs found  : {BOLD}{len(unique_entries)}{RESET}{dup_note}")
    log_info(f"Workers     : {BOLD}{workers}{RESET}  {DIM}(parallel downloads){RESET}")
    log_info(f"Output      : {BOLD}{output_folder}{RESET}")

    # Print group breakdown
    tprint()
    tprint(f"  {BOLD}Groups:{RESET}")
    for label, count in group_counts.items():
        folder_note = f"{DIM}→ {label}/{RESET}" if label != "(root)" else f"{DIM}→ (root folder){RESET}"
        tprint(f"    {CYAN}•{RESET} {label}  {DIM}({count} URL{'s' if count != 1 else ''}){RESET}  {folder_note}")

    tprint()
    separator("═")
    tprint()

    # ── Concurrent download ───────────────────────────────────────────────
    results: list[dict] = [{}] * len(unique_entries)
    bar        = ProgressBar(total=len(unique_entries))
    start_time = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(process_entry, idx + 1, url, group, output_folder, bar): idx
            for idx, (group, url) in enumerate(unique_entries)
        }
        for future in as_completed(future_to_index):
            idx          = future_to_index[future]
            results[idx] = future.result()

    bar.finish()
    elapsed = time.perf_counter() - start_time

    # ── Summary ───────────────────────────────────────────────────────────
    success_count = sum(1 for r in results if r.get("status") == "success")
    failed_count  = sum(1 for r in results if r.get("status") == "failed")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")

    tprint()
    separator("═")
    tprint(f"{BOLD}  Download Summary{RESET}")
    separator()
    tprint(f"  {GREEN}✔ Succeeded : {success_count}{RESET}")
    if failed_count:
        tprint(f"  {RED}✘ Failed    : {failed_count}{RESET}")
    if skipped_count:
        tprint(f"  {YELLOW}↷ Skipped   : {skipped_count}{RESET}")
    tprint(f"  {DIM}⏱ Time      : {elapsed:.2f}s  ({workers} parallel workers){RESET}")
    tprint(f"  {CYAN}📁 Folder   : {output_folder}{RESET}")

    # Per-group breakdown in summary
    if len(group_counts) > 1:
        tprint()
        tprint(f"  {BOLD}Per group:{RESET}")
        for label in group_counts:
            group_key    = None if label == "(root)" else label
            g_success    = sum(1 for r in results if r.get("group") == group_key and r.get("status") == "success")
            g_failed     = sum(1 for r in results if r.get("group") == group_key and r.get("status") == "failed")
            status_str   = f"{GREEN}✔ {g_success}{RESET}"
            if g_failed:
                status_str += f"  {RED}✘ {g_failed}{RESET}"
            tprint(f"    {CYAN}•{RESET} {label}  {status_str}")

    separator("═")

    if failed_count:
        tprint()
        tprint(f"{RED}{BOLD}Failed URLs:{RESET}")
        for r in results:
            if r.get("status") == "failed":
                group_label = f"[{r['group']}] " if r.get("group") else ""
                tprint(f"  {RED}✘{RESET} {group_label}{r['url']}")
                tprint(f"    {DIM}→ {r['detail']}{RESET}")

    tprint()

    # ── Write download_log.txt ────────────────────────────────────────────
    log_path     = output_folder / "download_log.txt"
    source_label = file_in if file_in else "interactive / stdin"

    with log_path.open("w", encoding="utf-8") as f:
        f.write("Bulk Image Download Log\n")
        f.write(f"Generated : {datetime.now().isoformat()}\n")
        f.write(f"Source    : {source_label}\n")
        f.write(f"Folder    : {output_folder}\n")
        f.write(f"Workers   : {workers}\n")
        f.write("=" * 60 + "\n\n")

        # Group-by-group breakdown
        for label, count in group_counts.items():
            f.write(f"── {label} ({count} URL{'s' if count != 1 else ''}) ──\n")
            group_key = None if label == "(root)" else label
            for idx, r in enumerate(results, start=1):
                if r.get("group") != group_key:
                    continue
                status = r.get("status", "unknown").upper()
                f.write(f"  [{status}] ({idx}) {r.get('url', '')}\n")
                f.write(f"    Detail  : {r.get('detail', '')}\n")
                if "file" in r:
                    f.write(f"    Saved as: {r['file']}\n")
            f.write("\n")

        f.write("=" * 60 + "\n")
        f.write(f"Total: {len(results)}  |  Success: {success_count}  |  Failed: {failed_count}  |  Skipped: {skipped_count}\n")
        f.write(f"Elapsed: {elapsed:.2f}s\n")

    log_info(f"Log saved → {log_path.name}")
    tprint()


if __name__ == "__main__":
    main()