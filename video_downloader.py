#!/usr/bin/env python3
import argparse, csv, glob, os, re, shlex, subprocess
from collections import defaultdict
from datetime import datetime
from typing import Dict, Tuple, List, Set
from urllib.parse import urlparse, parse_qs

# 可選依賴：send2trash
try:
    from send2trash import send2trash
except Exception:
    send2trash = None  # 未安裝時會提示

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

def extract_x_media_index(url: str):
    try:
        parsed = urlparse(url)
        if parsed.hostname not in {
            "x.com", "www.x.com", "m.x.com", "mobile.x.com",
            "twitter.com", "www.twitter.com", "m.twitter.com", "mobile.twitter.com",
        }:
            return None
        m = re.match(r"^/(?:i/web|[^/]+)/status/\d+/(?:video|photo)/(\d+)", parsed.path)
        return int(m.group(1)) if m else None
    except Exception:
        return None

def is_x_status_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.hostname in {
            "x.com", "www.x.com", "m.x.com", "mobile.x.com",
            "twitter.com", "www.twitter.com", "m.twitter.com", "mobile.twitter.com",
        } and re.match(r"^/(?:i/web|[^/]+)/status/\d+", parsed.path) is not None
    except Exception:
        return False

def file_ok(path: str) -> bool:
    try:
        return os.path.exists(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def move_many_without_overwrite(moves: List[Tuple[str, str]]) -> bool:
    """Move regular files as one checked batch without overwriting destinations."""
    if not moves:
        return True

    for source, destination in moves:
        if not file_ok(source) or not os.path.isfile(source) or os.path.islink(source):
            print(f"[warn] Cannot renumber missing or invalid file: {source}")
            return False
        if os.path.lexists(destination):
            print(f"[warn] Cannot renumber because destination exists: {destination}")
            return False

    # Create every destination as a hard link first. If any one fails, removing
    # the links created so far leaves all original names untouched.
    created: List[str] = []
    try:
        for source, destination in moves:
            os.link(source, destination)
            created.append(destination)
    except OSError as e:
        for destination in reversed(created):
            try:
                os.unlink(destination)
            except OSError:
                pass
        print(f"[warn] Failed to prepare renumber batch: {e}")
        return False

    try:
        for source, _ in moves:
            os.unlink(source)
    except OSError as e:
        # Restore original names when possible. A destination is removed only
        # after confirming that its original name points to the same file.
        for source, destination in moves:
            try:
                if not os.path.lexists(source):
                    os.link(destination, source)
                if os.path.samefile(source, destination):
                    os.unlink(destination)
            except OSError:
                pass
        print(f"[warn] Failed to finish renumber batch: {e}")
        return False

    for source, destination in moves:
        print(f"[rename] {source} -> {destination}")
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="~/Downloads/ig_fb_x_saved_urls.csv", help="CSV (time,comment,url)")
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
    groups: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = defaultdict(list)
    for ts, comment, url in rows:
        date_str = parse_date_yyyymmdd(ts)
        note = sanitize_note(comment)
        groups[(note, date_str)].append((ts, comment, url))

    cookies_spec = build_browser_cookies_arg(args.browser, args.profile)

    # 成功/失敗追蹤
    all_results: List[bool] = []
    rename_batches: List[List[Tuple[str, str]]] = []

    for (note, date_str), items in groups.items():
        group_results: List[bool] = []
        pending_rename: List[Tuple[str, str]] = []
        used = scan_existing_indices(out_dir, note, date_str)
        existing_count = len(used)
        total_after = existing_count + len(items)
        width = choose_width(total_after)
        indices = next_indices(used, len(items))

        # If this batch starts at 2, a legacy unnumbered file may represent #1.
        # Defer the rename until every download in this group has succeeded.
        if indices and indices[0] == 2:
            first_suffix = "1" if width <= 1 else f"{1:0{width}d}"
            pending_rename = [(
                os.path.join(out_dir, f"{note}_{date_str}.mp4"),
                os.path.join(out_dir, f"{note}_{date_str}_{first_suffix}.mp4"),
            )]
        elif indices and indices[0] == 10:
            # The first newly assigned index is 10, so require all existing
            # single-digit files and pad them to match the new filename width.
            pending_rename = [
                (
                    os.path.join(out_dir, f"{note}_{date_str}_{old_idx}.mp4"),
                    os.path.join(out_dir, f"{note}_{date_str}_{old_idx:0{width}d}.mp4"),
                )
                for old_idx in range(1, 10)
            ]

        for (ts, comment, url), idx in zip(items, indices):
            # decide filename by your rules
            if width == 0 and existing_count == 0 and idx == 1:
                filename = f"{note}_{date_str}.mp4"
            else:
                suffix = str(idx) if width <= 1 else f"{idx:0{width}d}"
                filename = f"{note}_{date_str}_{suffix}.mp4"
            filepath = os.path.join(out_dir, filename)

            # 若已存在且非 0 byte，視為已完成
            if file_ok(filepath):
                print(f"[skip exists] {filepath}")
                all_results.append(True)
                group_results.append(True)
                continue

            # --- KEY FIX: map ?img_index=N -> --playlist-items N ---
            img_idx = extract_img_index(url)
            x_media_idx = extract_x_media_index(url)

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
            elif x_media_idx is not None:
                # yt-dlp 會直接依 X URL 的 /video/N 或 /photo/N 選擇媒體。
                cmd.append("--no-playlist")
            elif is_x_status_url(url):
                # X 貼文可能包含多支影片；沒有媒體索引時只抓第一支，避免覆寫同一輸出檔。
                cmd.extend(["--playlist-items", "1"])
            else:
                # 沒有 img_index 的情況，避免整包抓
                cmd.append("--no-playlist")

            if args.rate_limit:
                cmd.extend(["--limit-rate", args.rate_limit])
            if args.extra:
                cmd.extend(shlex.split(args.extra))

            cmd.append(url)

            print(f"[download] {url}  ->  {filepath}")
            if args.dry_run:
                # 乾跑模式，不實際下載，但視為未完成（避免誤丟 CSV）
                all_results.append(False)
                group_results.append(False)
            else:
                proc = subprocess.run(cmd, check=False)
                # 必須同時確認 yt-dlp 成功結束，且實際產出非空檔案。
                ok = proc.returncode == 0 and file_ok(filepath)
                if not ok:
                    print(f"[warn] Download failed or output is invalid: {filepath} (rc={proc.returncode})")
                all_results.append(ok)
                group_results.append(ok)

        if pending_rename and group_results and all(group_results):
            rename_batches.append(pending_rename)

    # Each (note, date) group is renamed independently. A failure in another
    # group must not block renaming for groups whose downloads all succeeded.
    if not args.dry_run:
        for moves in rename_batches:
            move_many_without_overwrite(moves)

    # ---- 新增功能：全部成功才把 CSV 丟到資源回收桶 ----
    if all_results and all(all_results) and not args.dry_run:
        if send2trash is not None:
            try:
                send2trash(csv_path)
                print(f"[done] All items succeeded. CSV moved to Trash: {csv_path}")
            except Exception as e:
                print(f"[error] Failed to send CSV to Trash: {e}")
        else:
            print("[info] All items succeeded, but 'send2trash' is not installed.")
            print("       Install it to enable safe Trash move:  pip install send2trash")
            # 出於安全，不做永久刪除
    else:
        if args.dry_run:
            print("[note] Dry-run mode: CSV will NOT be moved to Trash.")
        else:
            print("[note] Not all items succeeded; CSV retained for retry.")

if __name__ == "__main__":
    main()
