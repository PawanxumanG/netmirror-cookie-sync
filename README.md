# NetMirror Cloud Cookie Sync

Automated cloud cron job powered by GitHub Actions.

### What it does:
1. Runs automatically every 6 hours in GitHub Actions (`.github/workflows/cookie_sync.yml`).
2. Performs the daily 35s ad verification cycle with `net52.cc`.
3. Extracts the active `t_hash_t` session cookie.
4. Uploads it directly to your Firebase Realtime Database at `https://shinzoverseapk-default-rtdb.firebaseio.com/netmirror_cookie.json`.
5. Mobile apps fetch this cookie in ~50ms on cold start to open instantly with 0s wait.
