#!/usr/bin/env python3
import argparse, csv, glob, os, re, shlex, subprocess, sys, tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
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

def gallery_media_index(url: str):
    img_idx = extract_img_index(url)
    if img_idx is not None:
        return img_idx
    x_idx = extract_x_media_index(url)
    if x_idx is not None:
        return x_idx
    return 1 if is_x_status_url(url) else None

def is_instagram_story_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in {"instagram.com", "www.instagram.com"} and \
        re.fullmatch(r"/stories/[^/]+/\d+/?", parsed.path) is not None

def download_with_gallery_dl(url: str, filepath: str, cookies_spec: str,
                             work_dir: str, rate_limit: str,
                             video_mode: str = "") -> bool:
    gallery_dir = os.path.join(work_dir, f"gallery_{video_mode or 'default'}")
    os.makedirs(gallery_dir)
    cmd = [
        sys.executable, "-m", "gallery_dl", "--config-ignore",
        "--cookies-from-browser", cookies_spec,
        "--directory", gallery_dir,
    ]
    if video_mode:
        cmd.extend(["-o", f"extractor.instagram.videos={video_mode}"])
    media_idx = gallery_media_index(url)
    if media_idx is not None:
        cmd.extend(["--filter", f"num == {media_idx}"])
    if rate_limit:
        cmd.extend(["--limit-rate", rate_limit])
    cmd.append(url)

    print(f"[fallback] Trying gallery-dl ({video_mode or 'default'}): {url}")
    try:
        proc = subprocess.run(cmd, check=False)
    except OSError as error:
        print(f"[warn] Cannot start gallery-dl: {error}")
        return False

    videos = [path for path in Path(gallery_dir).rglob("*")
              if path.is_file() and path.suffix.lower() == ".mp4" and file_ok(str(path))]
    if proc.returncode != 0 or len(videos) != 1:
        print(f"[warn] gallery-dl did not produce exactly one MP4 "
              f"(rc={proc.returncode}, videos={len(videos)})")
        return False

    os.replace(videos[0], filepath)
    print(f"[fallback] Saved: {filepath}")
    return True

def download_with_instaloader(url: str, filepath: str, work_dir: str,
                              chrome_profile: str) -> bool:
    parsed = urlparse(url)
    match = re.fullmatch(r"/stories/([A-Za-z0-9._]+)/([0-9]+)/?", parsed.path)
    if not match:
        return False

    username, story_id = match.groups()
    output_dir = os.path.join(work_dir, "instaloader")
    os.makedirs(output_dir)
    cmd = [
        sys.executable, "-m", "instaloader",
        "--load-cookies", "chrome",
        "--sessionfile", os.path.join(work_dir, "instaloader_session"),
        "--stories", "--no-posts", "--no-profile-pic", "--no-iphone",
        "--no-pictures", "--no-video-thumbnails", "--no-metadata-json",
        "--no-captions", "--storyitem-filter", f"mediaid == {story_id} and is_video",
        "--dirname-pattern", output_dir, "--filename-pattern", "{shortcode}",
    ]
    if chrome_profile:
        profile_dir = os.path.join(
            expand("~/Library/Application Support/Google/Chrome"), chrome_profile)
        cookie_file = next((path for path in (
            os.path.join(profile_dir, "Network", "Cookies"),
            os.path.join(profile_dir, "Cookies"),
        ) if os.path.isfile(path)), None)
        if cookie_file is None:
            print(f"[warn] Chrome profile cookie database not found: {profile_dir}")
            return False
        cmd.extend(["--cookiefile", cookie_file])
    cmd.append(username)

    print(f"[fallback] Trying Instaloader (Chrome, no-iphone): {url}")
    try:
        proc = subprocess.run(cmd, check=False)
    except OSError as error:
        print(f"[warn] Cannot start Instaloader: {error}")
        return False

    videos = [path for path in Path(output_dir).glob("*.mp4")
              if path.is_file() and file_ok(str(path))]
    if proc.returncode != 0 or len(videos) != 1:
        print(f"[warn] Instaloader did not produce exactly one MP4 "
              f"(rc={proc.returncode}, videos={len(videos)})")
        return False

    os.replace(videos[0], filepath)
    print(f"[fallback] Saved (Instaloader, potentially lower quality): {filepath}")
    return True

def download_video(url: str, filepath: str, cookies_spec: str, args) -> bool:
    with tempfile.TemporaryDirectory(prefix="igfb_", dir=os.path.dirname(filepath)) as work_dir:
        yt_output = os.path.join(work_dir, "video.mp4")
        cmd = [
            "yt-dlp",
            "--cookies-from-browser", cookies_spec,
            "--merge-output-format", "mp4",
            "--no-part",
            "--no-abort-on-error",
            "-o", yt_output,
        ]

        img_idx = extract_img_index(url)
        x_media_idx = extract_x_media_index(url)
        if img_idx is not None:
            cmd.extend(["--playlist-items", str(img_idx)])
        elif x_media_idx is not None:
            cmd.append("--no-playlist")
        elif is_x_status_url(url):
            cmd.extend(["--playlist-items", "1"])
        else:
            cmd.append("--no-playlist")

        if args.rate_limit:
            cmd.extend(["--limit-rate", args.rate_limit])
        if args.extra:
            cmd.extend(shlex.split(args.extra))
        cmd.append(url)

        try:
            proc = subprocess.run(cmd, check=False)
            rc = proc.returncode
        except OSError as error:
            print(f"[warn] Cannot start yt-dlp: {error}")
            rc = -1

        if rc == 0 and file_ok(yt_output):
            os.replace(yt_output, filepath)
            return True

        print(f"[warn] yt-dlp failed or output is invalid: {filepath} (rc={rc})")
        if download_with_gallery_dl(url, filepath, cookies_spec, work_dir, args.rate_limit):
            return True
        if is_instagram_story_url(url):
            if download_with_gallery_dl(
                    url, filepath, cookies_spec, work_dir, args.rate_limit, "merged"):
                return True
            return download_with_instaloader(url, filepath, work_dir, args.profile)
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

def rewrite_csv_rows(csv_path: str, rows: List[List[str]]) -> None:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", newline="", encoding="utf-8", prefix=".igfb_",
                suffix=".csv", dir=os.path.dirname(csv_path), delete=False) as temp_file:
            temp_path = temp_file.name
            csv.writer(temp_file, lineterminator="\n").writerows(rows)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, csv_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

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
    rows: List[Tuple[int, str, str, str]] = []
    csv_rows: List[List[str]] = []
    remaining_indices: Set[int] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        original_stat = os.fstat(f.fileno())
        r = csv.reader(f)
        for row_idx, row in enumerate(r):
            csv_rows.append(row)
            if len(row) >= 3 and row[2].strip():
                rows.append((row_idx, row[0].strip(), row[1].strip(), row[2].strip()))
            else:
                remaining_indices.add(row_idx)

    # group by (note,date)
    groups: Dict[Tuple[str, str], List[Tuple[int, str, str, str]]] = defaultdict(list)
    for row_idx, ts, comment, url in rows:
        date_str = parse_date_yyyymmdd(ts)
        note = sanitize_note(comment)
        groups[(note, date_str)].append((row_idx, ts, comment, url))

    cookies_spec = build_browser_cookies_arg(args.browser, args.profile)

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

        for (row_idx, ts, comment, url), idx in zip(items, indices):
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
                group_results.append(True)
                continue

            print(f"[download] {url}  ->  {filepath}")
            if args.dry_run:
                # 乾跑模式，不實際下載，但視為未完成（避免誤丟 CSV）
                group_results.append(False)
            else:
                ok = download_video(url, filepath, cookies_spec, args)
                group_results.append(ok)
                if not ok:
                    remaining_indices.add(row_idx)

        if pending_rename and group_results and all(group_results):
            rename_batches.append(pending_rename)

    # Each (note, date) group is renamed independently. A failure in another
    # group must not block renaming for groups whose downloads all succeeded.
    if not args.dry_run:
        for moves in rename_batches:
            move_many_without_overwrite(moves)

    if args.dry_run:
        print("[note] Dry-run mode: CSV will NOT be modified.")
        return
    if not rows:
        print("[note] No downloadable rows; CSV unchanged.")
        return

    try:
        current_stat = os.stat(csv_path)
    except OSError as error:
        print(f"[error] Cannot check CSV before updating it: {error}")
        return
    if (current_stat.st_dev, current_stat.st_ino, current_stat.st_size,
            current_stat.st_mtime_ns) != (
            original_stat.st_dev, original_stat.st_ino, original_stat.st_size,
            original_stat.st_mtime_ns):
        print("[warn] CSV changed during download; leaving it untouched.")
        return

    if not remaining_indices:
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
        remaining_rows = [row for row_idx, row in enumerate(csv_rows)
                          if row_idx in remaining_indices]
        try:
            rewrite_csv_rows(csv_path, remaining_rows)
            print(f"[done] CSV updated with {len(remaining_rows)} failed or unprocessed "
                  f"row(s): {csv_path}")
        except OSError as error:
            print(f"[error] Cannot update CSV; original file retained: {error}")

if __name__ == "__main__":
    main()
