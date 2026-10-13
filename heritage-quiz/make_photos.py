"""選んだ候補から photos/<id>.jpg と photos/credits.csv を作る。

selection.csv(id, n)で各遺産に使う候補番号を指定する。
写真は幅800px・JPEG品質75に縮小する。

使い方: python heritage-quiz/make_photos.py
"""
import csv
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH, QUALITY = 800, 75


def main():
    cands = {(r["id"], r["n"]): r for r in csv.DictReader(open(os.path.join(HERE, "candidates.csv"), encoding="utf-8"))}
    picks = list(csv.DictReader(open(os.path.join(HERE, "selection.csv"), encoding="utf-8")))
    out_dir = os.path.join(HERE, "photos")
    os.makedirs(out_dir, exist_ok=True)

    credits = []
    for p in picks:
        if not p.get("n"):
            continue
        c = cands[(p["id"], p["n"])]
        im = Image.open(os.path.join(HERE, c["file"])).convert("RGB")
        if im.width > WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
        name = f"{p['id']}.jpg"
        im.save(os.path.join(out_dir, name), "JPEG", quality=QUALITY, optimize=True, progressive=True)
        credits.append({"file": name, "author": c["author"], "license": c["license"], "url": c["url"]})
        print(f"{name}: {os.path.getsize(os.path.join(out_dir, name)) // 1024}KB  {c['title']}")

    with open(os.path.join(out_dir, "credits.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "author", "license", "url"])
        w.writeheader()
        w.writerows(credits)


if __name__ == "__main__":
    main()
