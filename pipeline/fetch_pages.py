import json, os, sys
from http_client import get
inv = json.load(open("inventory.json"))
bad = []
for p in inv["prompts"]:
    path = f"pages/{p['id']}.html"
    if os.path.exists(path): continue
    st, h, body = get(p["link"])
    if st != 200: bad.append((p["link"], st)); continue
    open(path, "wb").write(body)
print("done; failures:", bad)
if bad:
    sys.exit(1)
