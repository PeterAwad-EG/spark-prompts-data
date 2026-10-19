# spark-prompts-data

The public prompt catalogue for the SparkTech Prompts browser extension, built daily from the public prompt pages at <https://sparktech.pro/ai_prompts/>.

- **`prompts.json`**: the data the extension downloads, no token needed:
  `https://raw.githubusercontent.com/PeterAwad-EG/spark-prompts-data/main/prompts.json`
- **`pipeline/`**: the code that builds it (Python 3 standard library only). This is the only copy of the pipeline.
- **`.github/workflows/sync.yml`**: runs every day and on demand. It uses only the built-in `GITHUB_TOKEN`.

Prompt text is copied from the site exactly as published and is never edited here. Fix content on the site.

## How the daily sync works

1. Reads the public WordPress REST listing, the taxonomies and the sitemap, then downloads every public prompt page. It sends GET requests only, at most one per second, with a descriptive User-Agent.
2. Extracts each prompt's text exactly and checks it against the page.
3. Normalizes the prompts using `pipeline/targets.json` (targets, links, platform keys, URL allowlist), `pipeline/overrides.json` and `pipeline/ui_lists.json`.
4. Validates the result. If any request fails or any check fails, nothing is committed: the last good `prompts.json` stays, and the run opens (or comments on) a **"Daily sync failed"** issue.
5. Commits `prompts.json` only when its content changed. The commit message lists the changed, added and removed IDs, stale overrides, unknown platform keys and warnings.

### Overrides

Each entry under `set` in `overrides.json` pins the exact site text it targets (`source`). If the site text changes, the override is skipped and reported as a **stale override** instead of being applied blindly. Site platform keys missing from `targets.json` are reported as **unknown platform keys**, never dropped silently.

## Run locally

```bash
python3 pipeline/sync.py                 # full run against the live site
python3 pipeline/sync.py --offline DIR   # reuse inventory.json / extracted.json / gate_a.json from DIR
python3 pipeline/diff_prompts.py OLD.json NEW.json
```

Output goes to `pipeline/_run/`, which is git-ignored.
