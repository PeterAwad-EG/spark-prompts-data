"""Extract all downloaded pages and build the Gate A data (extracted.json + gate_a.json)."""
import collections
import hashlib
import html
import json
from extract import extract, norm

inv = json.load(open("inventory.json"))
tslug = {t["id"]: t["slug"] for t in inv["topics"]}
dslug = {d["id"]: d["slug"] for d in inv["domains"]}
rows, review = [], []
for p in inv["prompts"]:
    try:
        doc = open(f"pages/{p['id']}.html", encoding="utf-8").read()
    except FileNotFoundError:
        review.append({"id": p["id"], "url": p["link"], "problems": ["page not downloaded"]})
        continue
    r = extract(doc)
    row = {
        "wp_id": p["id"], "slug": p["slug"], "url": p["link"], "modified": p["modified"],
        "title": html.unescape(p["title"]["rendered"]), "h1": r.get("h1"),
        "topics": [tslug.get(t, f"#{t}") for t in p["topic"]],
        "domains": [dslug.get(d, f"#{d}") for d in p["domain"]],
        "platforms": r.get("platforms"), "text": r["text"], "checks": r.get("checks"),
        "problems": r["problems"], "sha256": hashlib.sha256(r["text"].encode()).hexdigest(),
    }
    rows.append(row)
    if r["problems"]:
        review.append({"id": p["id"], "url": p["link"], "problems": r["problems"]})

by_title = collections.defaultdict(list)
by_text = collections.defaultdict(list)
for r in rows:
    by_title[norm(r["title"])].append(r["url"])
    by_text[norm(r["text"])].append(r["url"])
gate = {
    "rest_total": inv["rest_total_header"], "rest_items": inv["rest_items"],
    "sitemap_urls": len(inv["sitemap_urls"]), "only_in_rest": inv["only_in_rest"],
    "only_in_sitemap": inv["only_in_sitemap"],
    "extracted_ok": sum(1 for r in rows if not r["problems"]), "needs_review": review,
    "dup_titles": {k: v for k, v in by_title.items() if len(v) > 1},
    "dup_texts": [v for v in by_text.values() if len(v) > 1],
    "title_vs_h1_mismatch": [(r["url"], r["title"], r["h1"]) for r in rows if r["h1"] and norm(r["h1"]) != norm(r["title"])],
    "platform_sets": collections.Counter(",".join(r["platforms"] or ["(none)"]) for r in rows).most_common(),
    "no_topic": [r["url"] for r in rows if not r["topics"]],
    "len_stats": [min(len(r["text"]) for r in rows), max(len(r["text"]) for r in rows), sum(len(r["text"]) for r in rows)],
}
json.dump(rows, open("extracted.json", "w"), ensure_ascii=False, indent=1)
json.dump(gate, open("gate_a.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in gate.items()}, ensure_ascii=False, indent=1))
