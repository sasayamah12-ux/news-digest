"""src/quiz.html に写真を差し込んで、2つの完成品を作る。

- dist/world-heritage-quiz.html : 写真を data URI で埋め込んだ1ファイル版(claude.ai の Artifact 用)
- ../public/heritage-quiz/      : 写真を別ファイルで参照する GitHub Pages 版

photos/credits.csv がなければ、全問イラストのまま出力する。

使い方: python heritage-quiz/build.py
"""
import base64
import csv
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = os.path.join(HERE, "..", "public", "heritage-quiz")


def credits():
    path = os.path.join(HERE, "photos", "credits.csv")
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8")))


def render(src, photos):
    js = json.dumps(photos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out, n = re.subn(r"/\*PHOTOS\*/.*?/\*END PHOTOS\*/", lambda _: js, src, flags=re.S)
    assert n == 1, "PHOTOS placeholder not found"
    return out


def main():
    src = open(os.path.join(HERE, "src", "quiz.html"), encoding="utf-8").read()
    rows = credits()

    def entry(r, url):
        return {"src": url, "author": r["author"], "license": r["license"], "url": r["url"]}

    # 遺産ごとに、credits.csv の並び順(=表示順)で写真をまとめる
    embedded, linked = {}, {}
    for r in rows:
        data = open(os.path.join(HERE, "photos", r["file"]), "rb").read()
        embedded.setdefault(r["id"], []).append(entry(r, "data:image/jpeg;base64," + base64.b64encode(data).decode()))
        linked.setdefault(r["id"], []).append(entry(r, "photos/" + r["file"]))
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    one = os.path.join(HERE, "dist", "world-heritage-quiz.html")
    open(one, "w", encoding="utf-8").write(render(src, embedded))

    shutil.rmtree(PAGES_DIR, ignore_errors=True)
    os.makedirs(os.path.join(PAGES_DIR, "photos"))
    for r in rows:
        shutil.copy(os.path.join(HERE, "photos", r["file"]), os.path.join(PAGES_DIR, "photos", r["file"]))
    open(os.path.join(PAGES_DIR, "index.html"), "w", encoding="utf-8").write(render(src, linked))

    print(f"photos: {len(rows)} ({len(embedded)} sites)")
    print(f"{os.path.relpath(one)}: {os.path.getsize(one) / 1e6:.2f} MB")
    print(f"{os.path.relpath(PAGES_DIR)}/index.html")


if __name__ == "__main__":
    main()
