#!/usr/bin/env python3
"""
NetMirror Cloud Cookie Sync (High Reliability Edition)
Runs automatically via GitHub Actions / local daemon to keep Firebase Realtime Database
loaded with active, verified bypass cookies for NetMirror Android and Android TV APKs.
Uses dynamic parameter extraction and browser automation to bypass Cloudflare protection.
"""

import urllib.request
import urllib.parse
import time
import json
import re
import ssl
import sys
import os
import subprocess

# Unbuffered output for real-time CI/CD logging
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

FIREBASE_URL = "https://shinzoverseapk-default-rtdb.firebaseio.com/netmirror_cookie.json"
TV_FIREBASE_URL = "https://shinzoverseapk-default-rtdb.firebaseio.com/netmirror_tv_token.json"
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

def register_click_via_browser(userver_url):
    """
    Register the ad click using a real browser to pass Cloudflare Turnstile.
    Supports native macOS Chrome and Linux/CI xvfb Playwright GUI automation.
    """
    print("[*] Attempting browser-based ad click registration to pass Cloudflare...")

    # Strategy 1: System browser (on macOS desktop)
    if sys.platform == "darwin":
        try:
            print("[*] Opening URL via macOS Chrome...")
            subprocess.run(["open", "-a", "Google Chrome", userver_url], check=True)
            time.sleep(6)
            return True
        except Exception as e:
            print(f"[-] macOS Chrome open warning: {e}")

    # Strategy 2: Playwright with Chromium (supports xvfb-run on Linux CI)
    try:
        from playwright.sync_api import sync_playwright
        
        is_linux = sys.platform.startswith("linux")
        has_display = bool(os.environ.get("DISPLAY"))
        # In xvfb-run on Linux, headless=False runs inside the virtual display as a real GUI browser
        use_headless = not (is_linux and has_display)

        print(f"[*] Launching Playwright browser (headless={use_headless}, linux_display={has_display})...")
        with sync_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage"
            ]
            
            browser = None
            try:
                browser = p.chromium.launch(headless=use_headless, channel="chrome" if is_linux else None, args=launch_args)
            except Exception:
                browser = p.chromium.launch(headless=use_headless, args=launch_args)

            context = browser.new_context()
            page = context.new_page()
            
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(page)
            except Exception:
                pass

            print(f"[*] Navigating to {userver_url}...")
            try:
                page.goto(userver_url, wait_until="commit", timeout=15000)
            except Exception:
                pass

            for sec in range(15):
                time.sleep(1)
                try:
                    title = page.title()
                    if "Just a moment" not in title and len(title) > 0:
                        print(f"[✓] Cloudflare challenge passed in {sec+1}s! Title: {title}")
                        time.sleep(2)
                        break
                except Exception:
                    pass

            browser.close()
            print("[+] Playwright click registration step completed.")
            return True
    except Exception as e:
        print(f"[-] Playwright browser error: {e}")

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

    # Dynamically extract Vsite2 and Qury from page script
    vsite_m = re.search(r'var\s+Vsite2\s*=\s*[\"\']([^\"\']+)[\"\']', html)
    vsite = vsite_m.group(1).strip() if vsite_m else "userver"

    qury_m = re.search(r'var\s+Qury\s*=\s*[\"\']([^\"\']+)[\"\']', html)
    if qury_m:
        qury = qury_m.group(1).strip()
    else:
        open_match = re.search(r'[\'"][?]([a-zA-Z0-9_-]+)=', html)
        qury = open_match.group(1).strip() if open_match else "ffr455"

    print(f"[+] Extracted endpoint config: Vsite='{vsite}', Qury='{qury}'")

    # Step 2: Register click with userver
    print("[2/4] Registering ad click with userver...")
    userver_url = f"https://{vsite}.net52.cc/?{qury}={urllib.parse.quote(addhash)}&a=y&t={time.time()}"

    # Try fast HTTP GET first
    fast_ping_ok = False
    req2 = urllib.request.Request(userver_url, headers={
        "User-Agent": UA,
        "Referer": "https://net52.cc/"
    })
    try:
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp2:
            print(f"[+] Fast Userver response status: {resp2.status}")
            fast_ping_ok = True
    except Exception as e:
        print(f"[-] Direct Userver ping returned ({e}). Switching to browser-based bypass...")
        register_click_via_browser(userver_url)

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

    # Step 4: Push to Firebase (both Mobile and TV endpoints)
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
            print(f"[+] Firebase Mobile Cookie updated successfully (HTTP {fb_resp.status})!")
    except Exception as e:
        print(f"[-] Firebase Mobile update error: {e}")
        return None

    # Step 5: Push TV Usertoken to Firebase for TV APK
    try:
        raw_val = verified_cookie.split("t_hash_t=")[1].split(";")[0].strip() if "t_hash_t=" in verified_cookie else verified_cookie
        unquoted = urllib.parse.unquote(raw_val)
        parts = unquoted.split("::")
        tv_token = "::".join(parts[:4])
        
        tv_payload = {
            "usertoken": tv_token,
            "updated_at": int(time.time()),
            "updated_at_readable": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }
        tv_req = urllib.request.Request(TV_FIREBASE_URL, data=json.dumps(tv_payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        tv_req.get_method = lambda: "PUT"
        with urllib.request.urlopen(tv_req, timeout=15, context=ctx) as tv_resp:
            print(f"[+] Firebase TV Usertoken ({tv_token}) updated successfully (HTTP {tv_resp.status})!")
    except Exception as e:
        print(f"[-] Firebase TV update warning: {e}")

    return verified_cookie

def check_existing_firebase_cookie(max_age_hours=3.5):
    """Check if Firebase already has a verified active cookie before performing new sync"""
    ctx = get_ssl_context()
    try:
        req = urllib.request.Request(FIREBASE_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cookie = data.get("cookie")
        updated_at = data.get("updated_at", 0)
        age_hours = (time.time() - updated_at) / 3600.0
        
        if cookie and test_cookie_validity(cookie):
            print(f"[✓] Existing Firebase cookie is verified active and valid (age: {age_hours:.1f}h).")
            if age_hours < max_age_hours:
                print(f"[✓] Firebase cookie was refreshed recently (< {max_age_hours}h) and remains healthy. No re-verification required.")
                return True
    except Exception as e:
        print(f"[-] Could not pre-check Firebase cookie: {e}")
    return False

def main():
    print(f"=== NetMirror Cloud Cookie & Token Sync Starting @ {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} ===")
    
    # Pre-check: If Firebase already has a valid token refreshed within last 3.5 hours, avoid redundant hits
    if check_existing_firebase_cookie(max_age_hours=3.5):
        print("\n[SUCCESS] Firebase is already loaded with an active bypass cookie.")
        sys.exit(0)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"\n--- Sync Attempt {attempt}/{max_retries} ---")
        cookie = sync_cookie_attempt()
        if cookie:
            print(f"\n[SUCCESS] Active bypass cookie & TV token stored in Firebase: {cookie}")
            sys.exit(0)
        print(f"[!] Attempt {attempt} failed, waiting 5 seconds before retry...")
        time.sleep(5)

    # Post-check fallback: Even if generating a brand new cookie timed out,
    # verify if the existing cookie in Firebase is still functional and operational.
    print("\n[*] Checking if existing Firebase cookie can serve as an active fallback...")
    ctx = get_ssl_context()
    try:
        req = urllib.request.Request(FIREBASE_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        fallback_cookie = data.get("cookie")
        if fallback_cookie and test_cookie_validity(fallback_cookie):
            print(f"\n[✓] RECOVERED: The existing cookie in Firebase is STILL VALID and passing checks!")
            print("[✓] Service continues uninterrupted without downtime.")
            sys.exit(0)
    except Exception as e:
        print(f"[-] Fallback check error: {e}")

    print("\n[ERROR] All sync attempts failed and no valid fallback cookie exists.")
    sys.exit(1)

if __name__ == "__main__":
    main()
