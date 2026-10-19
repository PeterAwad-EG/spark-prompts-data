"""Phase 1 inventory: REST pagination + taxonomy terms + sitemap cross-check."""
import json
import re
import xml.etree.ElementTree as ET
from http_client import get

BASE = "https://sparktech.pro"
FIELDS = "id,slug,link,title,modified,domain,topic"


def paged(endpoint, fields):
    items, page, total, pages = [], 1, None, 1
    while page <= pages:
        st, h, body = get(f"{BASE}/wp-json/wp/v2/{endpoint}?per_page=100&page={page}&_fields={fields}")
        if st != 200:
            raise SystemExit(f"{endpoint} page {page}: HTTP {st}")
        h = {k.lower(): v for k, v in h.items()}
        total, pages = int(h["x-wp-total"]), int(h["x-wp-totalpages"])
        items += json.loads(body)
        page += 1
    return items, total


def sitemap_urls():
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    st, _, body = get(f"{BASE}/sitemap_index.xml")
    index = [e.text.strip() for e in ET.fromstring(body).findall(".//s:sitemap/s:loc", ns)]
    maps = [u for u in index if "ai_prompts" in u or "ai-prompts" in u]
    urls = []
    for m in maps:
        _, _, b = get(m)
        urls += [e.text.strip() for e in ET.fromstring(b).findall(".//s:url/s:loc", ns)]
    return index, maps, urls


if __name__ == "__main__":
    prompts, total = paged("ai_prompts", FIELDS)
    topics, _ = paged("topic", "id,slug,name,count")
    domains, _ = paged("domain", "id,slug,name,count")
    index, maps, smap = sitemap_urls()
    rest_links = {p["link"] for p in prompts}
    out = {
        "rest_total_header": total, "rest_items": len(prompts), "prompts": prompts,
        "topics": topics, "domains": domains,
        "sitemap_index": index, "prompt_sitemaps": maps, "sitemap_urls": smap,
        "only_in_rest": sorted(rest_links - set(smap)),
        "only_in_sitemap": sorted(set(smap) - rest_links),
    }
    json.dump(out, open("inventory.json", "w"), ensure_ascii=False, indent=1)
    print("REST header", total, "items", len(prompts), "unique ids", len({p["id"] for p in prompts}))
    print("prompt sitemaps", maps, "sitemap urls", len(smap))
    print("only_in_rest", out["only_in_rest"]); print("only_in_sitemap", out["only_in_sitemap"])
    print("topics", [(t["slug"], t["name"], t["count"]) for t in topics])
    print("domains", [(d["slug"], d["name"], d["count"]) for d in domains])
