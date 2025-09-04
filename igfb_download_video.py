#!/usr/bin/env python3
import argparse, csv, glob, os, re, shlex, subprocess
from collections import defaultdict
from datetime import datetime
from typing import Dict, Tuple, List, Set
from urllib.parse import urlparse, parse_qs

SAFE_CHAR_RE = re.compile(r"[^-\w\s\.\(\)\[\]{}、，・·’'`‧＿]+")

def expand(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))

def sanitize_note(note: str) -> str:
    if not note: return "NoNote"
    note = " ".join(note.strip().split())
    note = SAFE_CHAR_RE.sub("_", note)
    return note[:80] or "NoNote"

def parse_date_yyyymmdd(ts: str) -> str:
    ts = (ts or "").strip()
    try:
        if ts.endswith("Z"):
            from datetime import timezone
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y%m%d")
    except Exception:
        m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", ts)
        return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else "unknown"

def scan_existing_indices(out_dir: str, note: str, date_str: str) -> Set[int]:
    used: Set[int] = set()
    base_n = os.path.join(out_dir, f"{note}_{date_str}.mp4")
    if os.path.exists(base_n): used.add(1)
    pattern = os.path.join(out_dir, f"{note}_{date_str}_*.mp4")
    tail_re = re.compile(r"_(\d+)\.mp4$", re.IGNORECASE)
    for path in glob.glob(pattern):
        m = tail_re.search(os.path.basename(path))
        if m:
            try: used.add(int(m.group(1)))
            except: pass
    return used

def choose_width(total_count: int) -> int:
    if total_count <= 1: return 0
    if total_count <= 9: return 1
    if total_count <= 99: return 2
    return len(str(total_count))

def next_indices(used: Set[int], how_many: int) -> List[int]:
    out, n = [], 1
    while len(out) < how_many:
        if n not in used:
            out.append(n); used.add(n)
        n += 1
    return out

def build_browser_cookies_arg(browser: str, profile: str) -> str:
    browser = (browser or "chrome").strip().lower()
    return f"{browser}:{profile}" if profile else browser

def extract_img_index(url: str):
    try:
        q = parse_qs(urlparse(url).query)
        if "img_index" in q and q["img_index"]:
            return int(q["img_index"][0])
    except Exception:
        pass
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="~/Downloads/ig_fb_saved_urls.csv", help="CSV (time,comment,url)")
    ap.add_argument("--out", default="~/Downloads", help="Output directory")
    ap.add_argument("--browser", default="chrome", help="cookies-from-browser (chrome|chromium|edge|brave)")
    ap.add_argument("--profile", default="", help='Browser profile, e.g. "Default", "Profile 2"')
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rate-limit", default="")
    ap.add_argument("--extra", default="")
    args = ap.parse_args()

    csv_path, out_dir = expand(args.csv), expand(args.out)
    os.makedirs(out_dir, exist_ok=True)

    # read CSV rows
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        for row in r:
            if len(row) >= 3 and row[2].strip():
                rows.append((row[0].strip(), row[1].strip(), row[2].strip()))

    # group by (note,date)
    from collections import defaultdict
    groups: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = defaultdict(list)
    for ts, comment, url in rows:
        date_str = parse_date_yyyymmdd(ts)
        note = sanitize_note(comment)
        groups[(note, date_str)].append((ts, comment, url))

    cookies_spec = build_browser_cookies_arg(args.browser, args.profile)

    for (note, date_str), items in groups.items():
        used = scan_existing_indices(out_dir, note, date_str)
        existing_count = len(used)
        total_after = existing_count + len(items)
        width = choose_width(total_after)
        indices = next_indices(used, len(items))

        for (ts, comment, url), idx in zip(items, indices):
            # decide filename by your rules
            if width == 0 and existing_count == 0 and idx == 1:
                filename = f"{note}_{date_str}.mp4"
            else:
                suffix = str(idx) if width <= 1 else f"{idx:0{width}d}"
                filename = f"{note}_{date_str}_{suffix}.mp4"
            filepath = os.path.join(out_dir, filename)

            if os.path.exists(filepath):
                print(f"[skip exists] {filepath}")
                continue

            # --- KEY FIX: map ?img_index=N -> --playlist-items N ---
            img_idx = extract_img_index(url)

            cmd = [
                "yt-dlp",
                "--cookies-from-browser", cookies_spec,
                "--merge-output-format", "mp4",
                "--no-part",
                "--no-abort-on-error",
                "-o", filepath,
            ]

            if img_idx is not None:
                # 只抓清單中的第 N 個條目（與你 CSV 的 img_index 對齊）
                cmd.extend(["--playlist-items", str(img_idx)])
            else:
                # 沒有 img_index 的情況，避免整包抓
                cmd.append("--no-playlist")

            if args.rate_limit:
                cmd.extend(["--limit-rate", args.rate_limit])
            if args.extra:
                cmd.extend(shlex.split(args.extra))

            cmd.append(url)

            print(f"[download] {url}  ->  {filepath}")
            if not args.dry_run:
                subprocess.run(cmd, check=False)

if __name__ == "__main__":
    main()

