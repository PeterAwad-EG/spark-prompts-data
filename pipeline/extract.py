"""Extract the verbatim prompt body from a public SparkTech prompt page (stdlib only).

The page renders the prompt twice as `.copy-target` Elementor text-editor widgets:
one hidden on desktop/tablet/mobile, one shown to visitors. We take the shown copy,
render it like innerText (plus list markers), and verify it against the page.
"""
import html
import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template", "svg", "head"}
BLOCK1 = {"div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section", "article",
          "header", "footer", "nav", "table", "tr", "pre", "figure", "hr", "dl", "dt", "dd"}
BLOCK2 = {"p"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()


class Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(doc):
    b = Builder()
    b.feed(doc)
    b.close()
    return b.root


ALL_HIDDEN = {"elementor-hidden-desktop", "elementor-hidden-tablet", "elementor-hidden-mobile"}


def hidden(n):
    if ALL_HIDDEN <= set(n.classes):
        return True
    st = (n.attrs.get("style") or "").replace(" ", "").lower()
    return "display:none" in st or "hidden" in n.attrs or n.attrs.get("aria-hidden") == "true" and n.tag != "i"


def render(node, markers=True, force=False):
    """innerText-like rendering. Returns plain text with \\n line breaks."""
    out = []  # items: str or int (required line-break count)

    def walk(n, depth, list_ctx):
        if isinstance(n, str):
            t = re.sub(r"[ \t\r\n\f]+", " ", n)
            if t:
                out.append(t)
            return
        if n.tag in SKIP or (hidden(n) and not (force and n is node)):
            return
        if n.tag == "br":
            out.append("\n")
            return
        req = 2 if n.tag in BLOCK2 else 1 if n.tag in BLOCK1 else 0
        if req:
            out.append(req)
        ctx = list_ctx
        if n.tag in ("ol", "ul"):
            start = int(n.attrs.get("start") or 1) if n.tag == "ol" else None
            ctx = {"tag": n.tag, "i": start, "depth": (list_ctx["depth"] + 1) if list_ctx else 0}
        if n.tag == "li" and markers and list_ctx:
            indent = "   " * list_ctx["depth"]
            if list_ctx["tag"] == "ol":
                out.append(f"\x00{indent}{list_ctx['i']}. \x00")
                list_ctx["i"] += 1
            else:
                out.append(f"\x00{indent}- \x00")
        for c in n.children:
            walk(c, depth + 1, ctx)
        if req:
            out.append(req)

    walk(node, 0, None)
    # Resolve required line breaks (max of adjacent counts), trim spaces around breaks.
    text, pending = [], 0
    for item in out:
        if isinstance(item, int):
            pending = max(pending, item)
            continue
        if pending and text:
            text.append("\n" * pending)
        pending = 0
        text.append(item)
    s = "".join(text)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\x00 +", "\x00", s)  # spaces after a marker sentinel boundary
    s = s.replace("\x00", "")
    return s.strip(" \n")


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def extract(doc):
    """Return dict(text, hidden_copy, platforms, checks, problems)."""
    root = parse(doc)
    problems = []
    targets = [n for n in root.iter() if "copy-target" in n.classes]
    shown = [n for n in targets if not ALL_HIDDEN <= set(n.classes)]
    spare = [n for n in targets if ALL_HIDDEN <= set(n.classes)]
    if len(shown) != 1:
        problems.append(f"visible copy-target count = {len(shown)} (total {len(targets)})")
    if not shown:
        return {"text": "", "problems": problems, "checks": {}}
    tgt = shown[0]
    text = render(tgt)
    other = render(spare[0], markers=True, force=True) if spare else None
    plats = [n.attrs.get("data-platforms") for n in root.iter() if "st-platforms-data" in n.classes]
    body = next((n for n in root.iter() if n.tag == "body"), root)
    page_text = norm(render(body, markers=False))
    checks = {
        "non_empty": bool(text.strip()),
        "in_page_text": norm(render(tgt, markers=False)) in page_text,
        "copies_match": None if other is None else other == text,
    }
    if not checks["non_empty"]:
        problems.append("empty text")
    if not checks["in_page_text"]:
        problems.append("text not found in page visible text")
    if checks["copies_match"] is False:
        problems.append("hidden duplicate differs from visible copy")
    title = next((html.unescape("".join(c for c in n.children if isinstance(c, str))) for n in root.iter() if n.tag == "h1"), None)
    return {"text": text, "hidden_copy": other, "platforms": plats, "h1": title,
            "checks": checks, "problems": problems,
            "has_list": any(n.tag in ("ol", "ul") for n in tgt.iter()),
            "has_bold": any(n.tag in ("b", "strong") for n in tgt.iter())}
