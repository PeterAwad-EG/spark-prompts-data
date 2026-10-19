"""Diff two prompts.json builds by prompt id (daily-sync change summary).

usage: diff_prompts.py OLD NEW [--ignore field,field] [--allow id,id]
Exits 1 if any changed id is outside --allow (when given).
"""
import argparse
import json


def by_id(path):
    return {p["id"]: p for p in json.load(open(path))["prompts"]}


def diff(old, new, ignore=()):
    out = {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)), "changed": {}}
    for i in sorted(set(old) & set(new)):
        a, b = old[i], new[i]
        fields = sorted(k for k in set(a) | set(b) if k not in ignore and a.get(k) != b.get(k))
        if fields:
            out["changed"][i] = {"slug": b["slug"], "fields": fields}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--ignore", default="")
    ap.add_argument("--allow", default="")
    a = ap.parse_args()
    d = diff(by_id(a.old), by_id(a.new), set(filter(None, a.ignore.split(","))))
    print(json.dumps(d, ensure_ascii=False, indent=1))
    allow = set(filter(None, a.allow.split(",")))
    unexpected = [i for i in d["added"] + d["removed"] + list(d["changed"]) if allow and i not in allow]
    if unexpected:
        print("UNEXPECTED:", unexpected)
        raise SystemExit(1)
