"""Polite read-only HTTP client: GET only, >=1 s between requests, exponential backoff."""
import os
import ssl
import time
import urllib.request
import urllib.error

UA = ("SparkTechPromptsSync/1.0 (read-only daily prompt sync for the SparkTech Prompts browser extension; "
      "+https://github.com/PeterAwad-EG/spark-prompts-data; +https://sparktech.pro/contact/)")
MIN_INTERVAL = 1.05
_last = [0.0]
_CA = "/etc/ssl/cert.pem" if os.path.exists("/etc/ssl/cert.pem") else None
_CTX = ssl.create_default_context(cafile=_CA)


def get(url, retries=4, timeout=30):
    """Return (status, headers, body_bytes). Raises after the last retry."""
    delay = 2.0
    for attempt in range(retries + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                return e.code, dict(e.headers), e.read()
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        if attempt == retries:
            raise RuntimeError(f"GET failed after {retries + 1} tries: {url}: {err}")
        time.sleep(delay)
        delay *= 2
