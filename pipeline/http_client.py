"""Polite read-only HTTP client: GET only, >=1 s between requests, exponential backoff."""
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

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
            probe = "" if isinstance(err, urllib.error.HTTPError) else "\n" + probe_tcp(url)
            raise RuntimeError(f"GET failed after {retries + 1} tries: {url}: {err}{probe}")
        time.sleep(delay)
        delay *= 2


def probe_tcp(url, timeout=10):
    """Diagnose a network-level failure: try a TCP connect to every address the host resolves to."""
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        addrs = sorted({(ai[0], ai[4][0]) for ai in socket.getaddrinfo(u.hostname, port, type=socket.SOCK_STREAM)})
    except OSError as e:
        return f"TCP probe: DNS failed for {u.hostname}: {e}"
    lines = []
    for fam, ip in addrs:
        try:
            socket.create_connection((ip, port), timeout=timeout).close()
            res = "connected"
        except OSError as e:
            res = f"{type(e).__name__}: {e}"
        lines.append(f"TCP probe {'IPv6' if fam == socket.AF_INET6 else 'IPv4'} {ip}:{port} -> {res}")
    return "\n".join(lines)
