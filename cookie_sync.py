#!/usr/bin/env python3
"""
NetMirror Cloud Cookie Sync (High Reliability Edition)
Runs automatically via GitHub Actions / local daemon to keep Firebase Realtime Database
loaded with active, verified bypass cookies for NetMirror Android and Android TV APKs.
"""

import urllib.request
import urllib.parse
import time
import json
import re
import ssl
import sys

# Unbuffered output for real-time CI/CD logging
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

FIREBASE_URL = "https://shinzoverseapk-default-rtdb.firebaseio.com/netmirror_cookie.json"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 /OS.Gatu v3.0"
APP_PKG = "app.netmirror.netmirrornew"

def get_ssl_context():
    return ssl._create_unverified_context()

def test_cookie_validity(cookie_str):
    """Verify that the cookie actually bypasses the ad/abuse wall on net52.cc"""
    ctx = get_ssl_context()
    req = urllib.request.Request("https://net52.cc/mobile/home?app=1", headers={
        "User-Agent": UA,
        "X-Requested-With": APP_PKG,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cookie": cookie_str
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            if "data-addhash" not in html and len(html) > 5000:
                print(f"[✓] Cookie validation passed! Verified clean response ({len(html)} bytes).")
                return True
            else:
                print(f"[✗] Cookie validation failed: response still contains ad hash or is too short ({len(html)} bytes).")
                return False
    except Exception as e:
        print(f"[!] Cookie validation error: {e}")
        return False

def sync_cookie_attempt():
    ctx = get_ssl_context()
    print("[1/4] Fetching NetMirror mobile home page to initiate verification session...")
    
    req = urllib.request.Request("https://net52.cc/mobile/home?app=1", headers={
        "User-Agent": UA,
        "X-Requested-With": APP_PKG,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })
    
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[-] Failed to load home page: {e}")
        return None

    m = re.search(r'data-addhash=[\"\']([^\"\']+)[\"\']', html)
    if not m:
        print("[!] No data-addhash found in page. Checking if current session is already clean...")
        return None

    addhash = m.group(1)
    print(f"[+] Got ad verification hash: {addhash}")

    # Step 2: Register click with userver
    print("[2/4] Registering ad click with userver...")
    userver_url = f"https://userver.net52.cc/?hee5={urllib.parse.quote(addhash)}&a=y&t={time.time()}"
    req2 = urllib.request.Request(userver_url, headers={
        "User-Agent": UA,
        "Referer": "https://net52.cc/"
    })
    
    try:
        with urllib.request.urlopen(req2, timeout=15, context=ctx) as resp2:
            print(f"[+] Userver response status: {resp2.status}")
    except Exception as e:
        print(f"[-] Userver ping error: {e}")

    # Step 3: Poll verify2.php until "All Done" (server timer ~35s)
    print("[3/4] Polling verify2.php until verified...")
    start_time = time.time()
    verified_cookie = None

    for i in range(25):
        time.sleep(2)
        post_data = urllib.parse.urlencode({"verify": addhash}).encode("utf-8")
        req3 = urllib.request.Request("https://net52.cc/mobile/verify2.php", data=post_data, headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://net52.cc/mobile/home?app=1"
        })
        try:
            with urllib.request.urlopen(req3, timeout=15, context=ctx) as resp3:
                body = resp3.read().decode("utf-8", errors="ignore")
                elapsed = time.time() - start_time
                print(f"    Poll #{i+1} ({elapsed:.1f}s): {body}")
                if "All Done" in body:
                    cookies = resp3.headers.get_all("Set-Cookie") if hasattr(resp3.headers, "get_all") else [resp3.headers.get("Set-Cookie")]
                    for c in cookies:
                        if c and "t_hash_t" in c:
                            verified_cookie = c.split(";")[0].strip()
                            break
                    if not verified_cookie and resp3.headers.get("Set-Cookie"):
                        verified_cookie = resp3.headers.get("Set-Cookie").split(";")[0].strip()
                    break
        except Exception as e:
            print(f"    Poll #{i+1} error: {e}")

    if not verified_cookie:
        print("[-] Failed to obtain verified cookie from verify2.php")
        return None

    print(f"[+] Obtained verified cookie candidate: {verified_cookie}")
    
    # Test cookie against net52
    if not test_cookie_validity(verified_cookie):
        print("[-] Candidate cookie failed validity check.")
        return None

    # Step 4: Push to Firebase
    print(f"[4/4] Pushing active cookie to Firebase: {FIREBASE_URL}...")
    payload = {
        "cookie": verified_cookie,
        "domain": "net52.cc",
        "updated_at": int(time.time()),
        "updated_at_readable": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    }
    
    data_bytes = json.dumps(payload).encode("utf-8")
    fb_req = urllib.request.Request(FIREBASE_URL, data=data_bytes, headers={"Content-Type": "application/json"})
    fb_req.get_method = lambda: "PUT"

    try:
        with urllib.request.urlopen(fb_req, timeout=15, context=ctx) as fb_resp:
            print(f"[+] Firebase updated successfully (HTTP {fb_resp.status})!")
            return verified_cookie
    except Exception as e:
        print(f"[-] Firebase update error: {e}")
        return None

def main():
    print(f"=== NetMirror Cloud Cookie Sync Starting @ {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} ===")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"\n--- Sync Attempt {attempt}/{max_retries} ---")
        cookie = sync_cookie_attempt()
        if cookie:
            print(f"\n[SUCCESS] Active bypass cookie synced to Cloud Firebase: {cookie}")
            sys.exit(0)
        print(f"[!] Attempt {attempt} failed, waiting 5 seconds before retry...")
        time.sleep(5)
    
    print("\n[ERROR] All sync attempts failed.")
    sys.exit(1)

if __name__ == "__main__":
    main()
