"""Wikimedia Commons から各遺産の写真候補を集める。

sites.csv の検索キーワードで Commons を検索し、再利用可能なライセンス
(CC BY / CC BY-SA / CC0 / パブリックドメイン)で横長の JPEG だけを残して、
幅1000pxのサムネイルを candidates/<id>/<n>.jpg に保存する。
作者・ライセンス・元ページは candidates.csv に記録する。

すでにある候補は番号ごと残し、足りない分だけ追加する(selection.csv の番号がずれないように)。
検索キーワードは " | " で区切って複数指定でき、前から順に候補を集める。
使えない候補は candidates.csv の行と画像を消し、rejected.csv(id, title)に書いておくと、
次の実行でその分が別の写真で補充される(同じ写真は二度と取らない)。

使い方: python heritage-quiz/fetch_candidates.py [--per-site 8] [id ...]
"""
import argparse
import csv
import html
import json
import os
import re
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


def search(query, seen):
    params = {
        "action": "query", "format": "json", "formatversion": 2,
        "generator": "search", "gsrnamespace": 6, "gsrlimit": 40,
        "gsrsearch": f"{query} filetype:bitmap",
        "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1000,
    }
    data = json.loads(get(API, params))
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    for p in pages:
        if p["title"] in seen:
            continue
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = plain(meta.get("LicenseShortName", {}).get("value"))
        w, h = info.get("width", 0), info.get("height", 0)
        if info.get("mime") != "image/jpeg" or not reusable(lic):
            continue
        if w < 1200 or not (1.2 <= w / max(h, 1) <= 2.2):
            continue
        yield {
            "title": p["title"],
            "author": plain(meta.get("Artist", {}).get("value")) or "不明",
            "license": lic,
            "license_url": meta.get("LicenseUrl", {}).get("value", ""),
            "url": info.get("descriptionurl", ""),
            "thumb": info.get("thumburl") or info.get("url"),
            "width": w, "height": h,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-site", type=int, default=8)
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()

    sites = list(csv.DictReader(open(os.path.join(HERE, "sites.csv"), encoding="utf-8")))
    order = {s["id"]: i for i, s in enumerate(sites)}
    if a.ids:
        sites = [s for s in sites if s["id"] in a.ids]

    csv_path = os.path.join(HERE, "candidates.csv")
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8"))) if os.path.exists(csv_path) else []
    rej_path = os.path.join(HERE, "rejected.csv")
    rejected = list(csv.DictReader(open(rej_path, encoding="utf-8"))) if os.path.exists(rej_path) else []

    for s in sites:
        have = [r for r in rows if r["id"] == s["id"]]
        if len(have) >= a.per_site:
            continue
        print(f"[{s['id']}] {s['query']} ({len(have)} -> {a.per_site})")
        d = os.path.join(HERE, "candidates", s["id"])
        os.makedirs(d, exist_ok=True)
        seen = {r["title"] for r in have} | {r["title"] for r in rejected if r["id"] == s["id"]}
        n = max([int(r["n"]) for r in have] + [0])
        for q in [q.strip() for q in s["query"].split("|") if q.strip()]:
            for c in search(q, seen):
                if len(have) >= a.per_site:
                    break
                n += 1
                name = f"{n}.jpg"
                with open(os.path.join(d, name), "wb") as f:
                    f.write(get(c["thumb"]))
                row = {"id": s["id"], "n": n, "file": f"candidates/{s['id']}/{name}",
                       **{k: c[k] for k in FIELDS if k in c}}
                rows.append(row)
                have.append(row)
                seen.add(c["title"])
                print(f"  {n}: {c['title']} ({c['license']})")
                time.sleep(0.3)

    rows.sort(key=lambda r: (order.get(r["id"], 999), int(r["n"])))
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
