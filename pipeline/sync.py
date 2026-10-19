"""Daily sync: site -> validated prompts.json. Single entry point for CI and local runs.

usage: python3 pipeline/sync.py [--offline DIR]

  --offline DIR  skip the network; reuse inventory.json / extracted.json / gate_a.json from DIR

Writes to pipeline/_run/: prompts.json, report.json, summary.md, commit_message.txt, status.json,
status_public.json (the repo-root heartbeat file) and heartbeat_message.txt.
Exit 0: valid build (status.json "changed" says whether prompts.json differs from the repo copy).
Exit 1: a request or a validation failed; summary.md explains, and the repo copy must stay as is.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUN = os.path.join(HERE, "_run")
PUBLISHED = os.path.join(ROOT, "prompts.json")
ARCHIVE_URL = "https://sparktech.pro/ai_prompts/"
PHASE_ATTEMPTS = 2  # a network phase that fails (after per-request retries) is re-run once
PHASE_RETRY_WAIT = 300  # seconds; outlasts short network outages
MAX_DROP = 0.10  # fail if the prompt count falls by more than this share in one run

sys.path.insert(0, HERE)
from diff_prompts import diff  # noqa: E402
from normalize import build, TARGETS  # noqa: E402


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fail(title, details):
    write(os.path.join(RUN, "summary.md"), f"## Sync failed: {title}\n\n{details}\n\nprompts.json was NOT changed.\n")
    dump({"ok": False, "changed": False, "error": title}, os.path.join(RUN, "status.json"))
    print(f"FAIL: {title}\n{details}")
    sys.exit(1)


def fetch():
    for script in ("inventory.py", "fetch_pages.py", "run_extract.py"):
        attempts = PHASE_ATTEMPTS if script != "run_extract.py" else 1  # only network phases are retried
        for attempt in range(1, attempts + 1):
            p = subprocess.run([sys.executable, os.path.join(HERE, script)], cwd=RUN, capture_output=True, text=True)
            with open(os.path.join(RUN, "fetch.log"), "a", encoding="utf-8") as log:
                log.write(f"$ {script} (attempt {attempt})\n{p.stdout}{p.stderr}\n")
            if p.returncode == 0:
                break
            if attempt < attempts:
                print(f"{script} failed (attempt {attempt}); retrying in {PHASE_RETRY_WAIT} s")
                time.sleep(PHASE_RETRY_WAIT)
        if p.returncode != 0:
            tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-15:])
            fail(f"{script} exited with {p.returncode} after {attempts} attempt(s)", f"```\n{tail}\n```")


def check_gate(gate):
    errors, warnings = [], []
    if not gate["rest_total"] == gate["rest_items"] == gate["extracted_ok"]:
        errors.append(f"REST header {gate['rest_total']}, REST items {gate['rest_items']}, extracted OK {gate['extracted_ok']}")
    for r in gate["needs_review"]:
        errors.append(f"needs review: {r['url']}: {', '.join(r['problems'])}")
    if gate["only_in_rest"]:
        warnings.append(f"in REST but not in sitemap: {gate['only_in_rest']}")
    extra = [u for u in gate["only_in_sitemap"] if u != ARCHIVE_URL]
    if extra:
        warnings.append(f"in sitemap but not in REST: {extra}")
    return errors, warnings


def check_data(data, previous):
    errors = []
    prompts = data["prompts"]
    allow = set(data["allowlist"])
    for key in ("id", "slug"):
        seen = [p[key] for p in prompts]
        dups = sorted({x for x in seen if seen.count(x) > 1})
        if dups:
            errors.append(f"duplicate {key}: {dups}")
    for p in prompts:
        if not p["text"].strip() or not p["title_ar"].strip():
            errors.append(f"{p['id']}: empty text or title")
        if p["target"] not in TARGETS or p["target"] not in data["targets"]:
            errors.append(f"{p['id']}: unknown target {p['target']}")
        for i in p["inputs"]:
            if i["token"] not in p["text"]:
                errors.append(f"{p['id']}: input token {i['token']} not in text")
    urls = [lk[k] for t in data["targets"].values() for lk in t["links"] for k in ("url", "fallback_url") if k in lk]
    urls += [v["url"] for v in data["platforms"].values()]
    for u in urls:
        if urlparse(u).scheme != "https" or urlparse(u).hostname not in allow:
            errors.append(f"link not https or not in allowlist: {u}")
    if previous and len(prompts) < len(previous["prompts"]) * (1 - MAX_DROP):
        errors.append(f"prompt count fell from {len(previous['prompts'])} to {len(prompts)} (> {MAX_DROP:.0%})")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline")
    args = ap.parse_args()
    shutil.rmtree(RUN, ignore_errors=True)
    os.makedirs(RUN)
    if args.offline:
        for name in ("inventory.json", "extracted.json", "gate_a.json"):
            shutil.copy(os.path.join(args.offline, name), RUN)
    else:
        fetch()

    gate = load(os.path.join(RUN, "gate_a.json"))
    errors, warnings = check_gate(gate)
    if errors:
        fail("site extraction did not validate", "\n".join(f"- {e}" for e in errors))

    previous = load(PUBLISHED) if os.path.exists(PUBLISHED) else None
    try:
        data, report = build(load(os.path.join(RUN, "extracted.json")), load(os.path.join(RUN, "inventory.json")),
                             load(os.path.join(HERE, "overrides.json")), load(os.path.join(HERE, "ui_lists.json"))["lists"],
                             load(os.path.join(HERE, "targets.json")))
    except SystemExit as e:
        fail("normalization stopped", str(e))
    errors = check_data(data, previous)
    if errors:
        fail("prompts.json did not validate", "\n".join(f"- {e}" for e in errors))

    out = os.path.join(RUN, "prompts.json")
    dump(data, out)
    dump(report, os.path.join(RUN, "report.json"))
    with open(out, "rb") as f:
        new_bytes = f.read()
    changed = previous is None or open(PUBLISHED, "rb").read() != new_bytes

    s = report["summary"]
    if previous:
        d = diff({p["id"]: p for p in previous["prompts"]}, {p["id"]: p for p in data["prompts"]})
        config = sorted(k for k in set(previous) | set(data) if k != "prompts" and previous.get(k) != data.get(k))
    else:
        d, config = {"added": [p["id"] for p in data["prompts"]], "removed": [], "changed": {}}, []
    lines = [f"Prompts: {s['prompts']}"]
    if previous is None:
        lines.append(f"Initial build: {len(d['added'])} prompts")
    else:
        lines.append("Changed IDs: " + (", ".join(f"{i} ({c['slug']}: {', '.join(c['fields'])})" for i, c in d["changed"].items()) or "none"))
        lines.append("Added IDs: " + (", ".join(d["added"]) or "none"))
        lines.append("Removed IDs: " + (", ".join(d["removed"]) or "none"))
        lines.append("Config changed: " + (", ".join(config) or "none"))
    lines.append("Stale overrides: " + (", ".join(f"{x['slug']} {x['override']} {x.get('token', x.get('value'))}" for x in s["stale_overrides"]) or "none"))
    lines.append("Orphan overrides: " + (", ".join(s["orphan_overrides"]) or "none"))
    lines.append("Unknown platform keys: " + (", ".join(f"{k} ({', '.join(v)})" for k, v in s["unmapped_platforms"].items()) or "none"))
    lines.append("Warnings: " + ("; ".join(warnings) or "none"))
    body = "\n".join(lines)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    head = f"sync {day}: initial prompts.json ({s['prompts']} prompts)" if previous is None else \
        f"sync {day}: {len(d['changed'])} changed, {len(d['added'])} added, {len(d['removed'])} removed"
    write(os.path.join(RUN, "commit_message.txt"), f"{head}\n\n{body}\n")
    write(os.path.join(RUN, "summary.md"), f"## Sync OK ({'content changed' if changed else 'no content change'})\n\n" +
          "\n".join(f"- {x}" for x in lines) + "\n")
    dump({"ok": True, "changed": changed}, os.path.join(RUN, "status.json"))
    # Public heartbeat (repo-root status.json): committed with every content change, and on its own when
    # main has had no commit for 30 days, so GitHub never disables the schedule for inactivity.
    run_url = os.environ.get("GITHUB_RUN_ID") and \
        f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    dump({"last_successful_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prompts": s["prompts"],
          "prompts_json_changed": changed, "summary": lines, "run": run_url},
         os.path.join(RUN, "status_public.json"))
    write(os.path.join(RUN, "heartbeat_message.txt"), f"heartbeat {day}: no content change\n\n{body}\n")
    print(head + "\n" + body + f"\nchanged={changed}")


if __name__ == "__main__":
    main()
