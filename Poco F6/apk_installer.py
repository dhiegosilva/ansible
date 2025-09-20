import os
import sys
import time
import subprocess
import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APK_CACHE = os.path.join(BASE_DIR, "apk_cache")
APK_LIST_FILE = os.path.join(BASE_DIR, "apks.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 30
COUNTDOWN_SECONDS = 10
RETRY_DOWNLOADS = 3

def ensure_dirs():
    os.makedirs(APK_CACHE, exist_ok=True)

def is_url(s: str) -> bool:
    try:
        u = urlparse(s)
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False

def slug_to_app_page(slug: str) -> str:
    return f"https://{slug}.en.uptodown.com/android"

def get_app_page_url(entry: str) -> str:
    entry = entry.strip()
    if is_url(entry):
        return entry.rstrip("/") if entry.rstrip("/").endswith("/android") else entry.rstrip("/") + "/android"
    return slug_to_app_page(entry)

def verify_apk(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"PK\x03\x04"  # ZIP magic
    except Exception:
        return False

def stream_download(session: requests.Session, url: str, dest_path: str) -> str:
    tmp_path = dest_path + ".part"
    with session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, stream=True) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    if not verify_apk(tmp_path):
        raise RuntimeError("Downloaded file is not an APK (ZIP signature missing).")
    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.rename(tmp_path, dest_path)
    return dest_path

def find_download_page(session: requests.Session, app_page_url: str) -> str:
    r = session.get(app_page_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Primary: the big button leading to /android/download
    link = soup.select_one('#button-download-page-link, a[href$="/android/download"], a.button.download')
    if link and link.get("href"):
        href = link["href"].strip()
        if href.startswith("//"): return "https:" + href
        if href.startswith("/"):  return urljoin(app_page_url, href)
        if href.startswith("http"): return href

    # Fallback construction
    return app_page_url.rstrip("/") + "/download"

def pick_final_apk_link(soup: BeautifulSoup, base_url: str) -> str | None:
    # 1) Explicit final download anchor seen on many pages
    a = soup.select_one("#download-url, a.direct-download, a.button[href*='dw.uptodown.net']")
    if a and a.get("href"):
        href = a["href"].strip()
        if href.startswith("//"): return "https:" + href
        if href.startswith("/"):  return urljoin(base_url, href)
        if href.startswith("http"): return href

    # 2) Any anchor to dw.uptodown.net with .apk
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if "dw.uptodown.net" in href and href.endswith(".apk"):
            if href.startswith("//"): return "https:" + href
            if href.startswith("/"):  return urljoin(base_url, href)
            return href

    # 3) meta refresh
    meta = soup.select_one("meta[http-equiv='refresh']")
    if meta:
        content = meta.get("content", "")
        if "url=" in content.lower():
            url = content.split("url=")[-1].strip()
            if url.startswith("//"): return "https:" + url
            if url.startswith("/"):  return urljoin(base_url, url)
            if url.startswith("http"): return url
    return None

def extract_final_link_or_wait(session: requests.Session, download_page_url: str) -> str:
    r = session.get(download_page_url, headers={**HEADERS, "Referer": download_page_url},
                    timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Try to pick the CDN APK link directly
    url = pick_final_apk_link(soup, download_page_url)
    if url:
        return url

    # Countdown fallback
    print(f"⏳ Waiting {COUNTDOWN_SECONDS}s for Uptodown countdown...")
    time.sleep(COUNTDOWN_SECONDS)

    # Re-request page after wait and try again
    r2 = session.get(download_page_url, headers={**HEADERS, "Referer": download_page_url},
                     timeout=TIMEOUT, allow_redirects=True)
    r2.raise_for_status()
    soup2 = BeautifulSoup(r2.text, "html.parser")
    url = pick_final_apk_link(soup2, download_page_url)
    return url if url else download_page_url  # last chance: let stream_download follow redirects

def download_from_uptodown(entry: str, dest_path: str) -> str:
    session = requests.Session(); session.headers.update(HEADERS)
    app_page = get_app_page_url(entry)
    download_page = find_download_page(session, app_page)

    last_err = None
    for attempt in range(1, RETRY_DOWNLOADS + 1):
        try:
            final_url = extract_final_link_or_wait(session, download_page)
            return stream_download(session, final_url, dest_path)
        except Exception as e:
            last_err = e
            print(f"⚠️ Attempt {attempt}/{RETRY_DOWNLOADS} failed for {entry}: {e}")
            time.sleep(2)
    raise RuntimeError(f"Uptodown download failed for {entry}: {last_err}")

def install_apk(apk_path: str, display_name: str):
    print(f"📦 Installing {display_name} via adb...")
    res = subprocess.run(["adb", "install", "-r", apk_path], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"✅ Installed {display_name}")
        try: os.remove(apk_path)
        except Exception: pass
    else:
        print(f"❌ Failed to install {display_name}: {res.stderr.strip()}")
        print(f"   APK kept at: {apk_path}")

def main():
    list_path = APK_LIST_FILE
    if not os.path.exists(list_path):
        print(f"{list_path} not found in {BASE_DIR}")
        sys.exit(1)

    ensure_dirs()
    with open(list_path, "r", encoding="utf-8") as f:
        entries = [line.strip() for line in f if line.strip()]

    for entry in entries:
        safe = entry.replace("://","_").replace("/","_").replace(",","_").replace(" ","_")
        apk_path = os.path.join(APK_CACHE, f"{safe}.apk")
        try:
            print(f"🔎 Processing {entry} ...")
            path = download_from_uptodown(entry, apk_path)
            install_apk(path, entry)
        except KeyboardInterrupt:
            print("\nInterrupted."); break
        except Exception as e:
            print(f"❌ Skipping {entry}: {e}")

if __name__ == "__main__":
    main()
