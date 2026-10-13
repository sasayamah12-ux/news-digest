"""Wikimedia Commons から各遺産の写真候補を集める。

sites.csv の検索キーワードで Commons を検索し、再利用可能なライセンス
(CC BY / CC BY-SA / CC0 / パブリックドメイン)で横長の JPEG だけを残して、
幅1000pxのサムネイルを candidates/<id>/<n>.jpg に保存する。
作者・ライセンス・元ページは candidates.csv に記録する。

使い方: python heritage-quiz/fetch_candidates.py [--per-site 4] [--changed-since REV] [id ...]
  --changed-since: 指定したコミットから sites.csv の検索キーワードが変わった id だけを取り直す
"""
import argparse
import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://commons.wikimedia.org/w/api.php"
UA = "heritage-quiz-photo-fetcher/1.0 (https://github.com/sasayamah12-ux/news-digest)"
FIELDS = ["id", "n", "file", "title", "author", "license", "license_url", "url", "width", "height"]


def get(url, params=None, retries=4):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry any network error
            if i == retries - 1:
                raise
            print(f"  retry {url[:80]}: {e}", file=sys.stderr)
            time.sleep(2 ** (i + 1))


def plain(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def reusable(lic):
    l = lic.lower()
    if "nc" in re.split(r"[\s\-]+", l) or "nd" in re.split(r"[\s\-]+", l):
        return False
    return l.startswith(("cc by", "cc-by", "cc0", "public domain", "pd")) or l == "pd"


def search(query, limit):
    params = {
        "action": "query", "format": "json", "formatversion": 2,
        "generator": "search", "gsrnamespace": 6, "gsrlimit": 40,
        "gsrsearch": f"{query} filetype:bitmap",
        "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1000,
    }
    data = json.loads(get(API, params))
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = plain(meta.get("LicenseShortName", {}).get("value"))
        w, h = info.get("width", 0), info.get("height", 0)
        if info.get("mime") != "image/jpeg" or not reusable(lic):
            continue
        if w < 1200 or not (1.2 <= w / max(h, 1) <= 2.2):
            continue
        out.append({
            "title": p["title"],
            "author": plain(meta.get("Artist", {}).get("value")) or "不明",
            "license": lic,
            "license_url": meta.get("LicenseUrl", {}).get("value", ""),
            "url": info.get("descriptionurl", ""),
            "thumb": info.get("thumburl") or info.get("url"),
            "width": w, "height": h,
        })
        if len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-site", type=int, default=4)
    ap.add_argument("--changed-since")
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()

    sites = list(csv.DictReader(open(os.path.join(HERE, "sites.csv"), encoding="utf-8")))
    if a.changed_since and not a.ids:
        try:
            old = subprocess.run(["git", "show", f"{a.changed_since}:heritage-quiz/sites.csv"],
                                 capture_output=True, text=True, check=True, cwd=HERE).stdout
            before = {r["id"]: r["query"] for r in csv.DictReader(old.splitlines())}
            a.ids = [s["id"] for s in sites if before.get(s["id"]) != s["query"]]
            if not a.ids:
                print("no query changes")
                return
        except subprocess.CalledProcessError:
            pass  # 比較できないときは全件
    if a.ids:
        sites = [s for s in sites if s["id"] in a.ids]

    csv_path = os.path.join(HERE, "candidates.csv")
    rows = []
    if os.path.exists(csv_path):
        keep = {s["id"] for s in sites}
        rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8")) if r["id"] not in keep]

    for s in sites:
        print(f"[{s['id']}] {s['query']}")
        d = os.path.join(HERE, "candidates", s["id"])
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        for n, c in enumerate(search(s["query"], a.per_site), 1):
            name = f"{n}.jpg"
            with open(os.path.join(d, name), "wb") as f:
                f.write(get(c["thumb"]))
            rows.append({"id": s["id"], "n": n, "file": f"candidates/{s['id']}/{name}",
                         **{k: c[k] for k in FIELDS if k in c}})
            print(f"  {n}: {c['title']} ({c['license']})")
            time.sleep(0.3)

    order = {s["id"]: i for i, s in enumerate(csv.DictReader(open(os.path.join(HERE, "sites.csv"), encoding="utf-8")))}
    rows.sort(key=lambda r: (order.get(r["id"], 999), int(r["n"])))
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
