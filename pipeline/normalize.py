"""Phase 2: normalize extracted prompts to the extension data model.

Rules only; prompt text is never changed. Every inference is recorded in the run
report under "inferred"; overrides.json keys under "set" always win.

Override governance: every entry under "set" pins the exact site text it
targets ("source"). If that text is no longer on the site, the entry is
skipped and reported as a stale override (never applied blindly).
"""
import re
import sys

TARGETS = ["chat", "image", "slides", "video", "notebooklm", "ai-settings", "other"]
CHAT_SITES = ["gemini", "chatgpt", "claude"]

CATEGORIES = [
    ("teaching", "التعليم والتلمذة", "Teaching & Discipleship", ["biblical-teaching", "discipleship", "ministry-groups", "kids-ministry"]),
    ("admin", "الإدارة والإنتاجية", "Administration & Productivity", ["management", "productivity", "support-follow-up"]),
    ("media", "الإعلام والمحتوى", "Media & Content", ["social-media", "images", "audio", "video"]),
    ("personal", "الحياة الشخصية والروحية", "Personal & Spiritual Life", ["career-finance", "relationships", "spiritual-life", "self-discovery"]),
    ("outreach", "الكرازة والمجتمع", "Outreach & Community", ["community", "outreach", "worship"]),
]
OTHER_CAT = ("other", "أخرى", "Other")
NAME_FIX = {"management": "إداريات", "video": "فيديو"}
TOKEN_LISTS = ("exclude_tokens", "optional_tokens")
SCALARS = {"title_ar": "title", "target": "text", "preferredSite": "text"}  # override -> field its source pins

TOKEN_RE = re.compile(r"\[([^\[\]\n]{1,300})\](\()?")
SCRIPTURE_RE = re.compile(r"^\S{1,8} \d+:\d+(?:-\d+)?$")
IMAGE_WORDS = re.compile(r"Nano Banana|نانو بنانا|\bimage\b|صورة|صوره|بوستر|انفوجرافيك|إنفوجرافيك|انفوجراف|سكتش|رسم|illustration|poster|infographic", re.I)
IMAGE_TASK = re.compile(r"Nano Banana|نانو بنانا|Create (?:a|an)? ?\[?[^\]\n]{0,40}\]? ?(?:infographic )?image|صمم|صمّم|ارسم|أنشئ صورة|انشئ صورة|اعد تصميم|أعد تصميم|حوّل .{0,30}(?:صورة|إنفوجرافيك|انفوجرافيك)|generate an image|الصورة المطلوبة|(?:ب)?[اإ]نشاء صورة|أنشئ إنفوجرافيك|انشئ انفوجرافيك|Create a\b.{0,80}\b(?:image|illustration|infographic)", re.I)


def split_platforms(raw):
    """Site stores platforms as comma-joined strings; return a sorted, de-duplicated key list."""
    return sorted({p.strip() for s in raw or [] for p in s.split(",") if p.strip()})


def token_source(text, token):
    """Exact site text an override pins: the line holding the token (clipped around it if long)."""
    i = text.find(token)
    if i < 0:
        return None
    a, b = text.rfind("\n", 0, i) + 1, text.find("\n", i)
    b = len(text) if b < 0 else b
    if b - a > 240:
        a, b = max(a, i - 100), min(b, i + len(token) + 100)
    return text[a:b]


def resolve_overrides(r, ov_set, stale):
    """Return the override values that still match the site; record the rest as stale."""
    out = {}
    for key in TOKEN_LISTS:
        keep = []
        for e in ov_set.get(key, []):
            if e["token"] in r["text"] and e["source"] in r["text"]:
                keep.append(e["token"][1:-1])
            else:
                stale.append({"slug": r["slug"], "override": key, "token": e["token"], "source": e["source"]})
        out[key] = keep
    for key, field in SCALARS.items():
        if key in ov_set:
            e = ov_set[key]
            if e["source"] in r[field]:
                out[key] = e["value"]
            else:
                stale.append({"slug": r["slug"], "override": key, "value": e["value"], "source": e["source"]})
    return out


def detect_inputs(text, exclude):
    seen, out, skipped = set(), [], []
    for m in TOKEN_RE.finditer(text):
        name, is_link = m.group(1).strip(), bool(m.group(2))
        why = None
        if is_link:
            why = "markdown-link"
        elif SCRIPTURE_RE.match(name):
            why = "scripture-ref"
        elif " | " in name or "|" in name and len(name.split("|")) > 2:
            why = "output-template"
        elif name in exclude:
            why = "override"
        elif re.fullmatch(r"verify(:.*)?", name, re.I):
            why = "verify-note"
        if why:
            skipped.append({"token": m.group(0), "why": why})
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "label": name, "token": m.group(0), "hint": "",
                    "required": not re.search(r"اختياري|optional", name, re.I)})
    return out, skipped


def fill(text, inputs, values):
    """Reference fill rule for the extension: an empty optional field inserts its default
    WITHOUT brackets; an empty required field leaves the token in place."""
    for inp in inputs:
        v = (values.get(inp["name"]) or "").strip()
        if not v and not inp["required"]:
            v = inp.get("default", "")
        if v:
            text = text.replace(inp["token"], v)
    return text


def infer_target(r):
    t, x, plats = r["title"], r["text"], set(r["platforms"])
    tx = t + "\n" + x
    if plats & {"gemini_instructions", "chatgpt_personal"} or re.search(r"تخصيص AI|custom instructions|personali[sz]ation", t, re.I):
        return "ai-settings", "site platforms / title: AI personalization"
    if "heygen" in plats or re.search(r"HeyGen", tx, re.I):
        return "video", "HeyGen"
    if "gamma" in plats or re.search(r"\bGamma\b", tx, re.I):
        return "slides", "Gamma"
    if re.search(r"NotebookLM|Gemini Notebook", tx, re.I):
        return "notebooklm", "NotebookLM / Gemini Notebook named"
    if re.search(r"Nano Banana|نانو بنانا", tx, re.I) or "nano-banana" in r["slug"]:
        return "image", "Nano Banana"
    if "images" in r["topics"] and (IMAGE_WORDS.search(t) or "صورة" in x) and IMAGE_TASK.search(tx) and not re.search(r"أفكار|افكار", t):
        return "image", "images topic + image-making task"
    return "chat", "default"


def infer_site(r):
    t, x = r["title"], r["text"]
    for s, pat in (("gemini", r"Gemini"), ("chatgpt", r"ChatGPT"), ("claude", r"Claude")):
        if re.search(pat, t, re.I):
            return s, f"title names {pat}"
    chats = [p for p in r["platforms"] if p in CHAT_SITES]
    if len(chats) == 1:
        return chats[0], "site offers only this chat tool"
    m = re.search(r"(?:على|في|استخدمه على|use (?:it )?(?:on|in)) (Gemini|ChatGPT|Claude)", x, re.I)
    if m:
        return m.group(1).lower(), f"text: {m.group(0)}"
    return None, None


def build(extracted, inventory, overrides, ui_lists, targets_cfg):
    topic_names = {t["slug"]: NAME_FIX.get(t["slug"], t["name"]) for t in inventory["topics"]}
    known = {s for c in CATEGORIES for s in c[3]}
    pmap = targets_cfg["platforms"]
    prompts, inferred, stale = [], {}, []
    report = {"skipped_tokens": {}, "repeated_tokens": {}, "unknown_topics": set(), "unmapped_platforms": {},
              "platform_keys": {}, "flags": []}
    for r in extracted:
        r = dict(r, platforms=split_platforms(r["platforms"]))
        ov = resolve_overrides(r, overrides.get(r["slug"], {}).get("set", {}), stale)
        target, why_t = infer_target(r)
        site, why_s = infer_site(r)
        inputs, skipped = detect_inputs(r["text"], set(ov["exclude_tokens"]))
        inferred[r["slug"]] = {"target": target, "target_rule": why_t, "preferredSite": site, "site_rule": why_s}
        target = ov.get("target", target)
        site = ov.get("preferredSite", site)
        for inp in inputs:
            if inp["name"] in ov["optional_tokens"]:
                inp["required"] = False
                inp["default"] = inp["name"]
        if target not in TARGETS:
            sys.exit(f"{r['slug']}: unknown target {target}")
        if skipped:
            report["skipped_tokens"][r["slug"]] = skipped
        reps = [i["name"] for i in inputs if r["text"].count(i["token"]) > 1]
        if reps:
            report["repeated_tokens"][r["slug"]] = reps
        for p in r["platforms"]:
            report["platform_keys"].setdefault(p, []).append(r["slug"])
            if p not in pmap:
                report["unmapped_platforms"].setdefault(p, []).append(r["slug"])
        report["unknown_topics"] |= {t for t in r["topics"] if t not in known}
        choices = ["lang", "tone", "style"] if target == "chat" else ["lang"] if target == "image" else []
        item = {
            "id": f"SP-{r['wp_id']}", "slug": r["slug"], "url": r["url"], "modified": r["modified"],
            "title_ar": ov.get("title_ar", r["title"]), "text": r["text"], "topics": r["topics"], "domains": r["domains"],
            "platforms": r["platforms"], "inputs": inputs, "target": target, "ui": {"choices": choices},
        }
        extra = [p for p in r["platforms"] if pmap.get(p, {}).get("extra_link")]
        if extra:
            item["extra_links"] = extra
        if site:
            item["preferredSite"] = site
        prompts.append(item)

    cats = []
    for cid, ar, en, slugs in CATEGORIES:
        subs = [{"slug": s, "name_ar": topic_names.get(s, s), "count": sum(1 for p in prompts if s in p["topics"])} for s in slugs]
        cats.append({"id": cid, "name_ar": ar, "name_en": en, "subs": subs})
    other = [p for p in prompts if not p["topics"] or any(t not in known for t in p["topics"])]
    other_subs = sorted({t for p in other for t in p["topics"] if t not in known})
    cats.append({"id": OTHER_CAT[0], "name_ar": OTHER_CAT[1], "name_en": OTHER_CAT[2],
                 "subs": [{"slug": s, "name_ar": topic_names.get(s, s), "count": sum(1 for p in prompts if s in p["topics"])} for s in other_subs]
                 + ([{"slug": "_none", "name_ar": "بدون تصنيف", "count": sum(1 for p in prompts if not p["topics"])}] if any(not p["topics"] for p in prompts) else [])})
    slugs = {p["slug"] for p in prompts}
    report["unknown_topics"] = sorted(report["unknown_topics"])
    report["platform_keys"] = {k: len(v) for k, v in sorted(report["platform_keys"].items())}
    report["summary"] = {
        "prompts": len(prompts),
        "stale_overrides": stale,
        "orphan_overrides": sorted(s for s, v in overrides.items() if v.get("set") and s not in slugs),
        "unmapped_platforms": report["unmapped_platforms"],
    }
    data = {"schema": 1, "source": "https://sparktech.pro/ai_prompts/", "categories": cats, "lists": ui_lists,
            "targets": targets_cfg["targets"], "platforms": pmap, "allowlist": targets_cfg["allowlist"], "prompts": prompts}
    report["inferred"] = inferred
    return data, report
