"""選んだ候補から photos/<id>-<k>.jpg と photos/credits.csv を作る。

selection.csv(id, n)で各遺産に使う候補番号を、表示順に空白区切りで指定する(例: "4 1 7")。
写真は photos/<id>-<k>.jpg として、幅720px・JPEG品質68に縮小する(150枚を1ページに埋め込むため)。

使い方: python heritage-quiz/make_photos.py
"""
import csv
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH, QUALITY = 720, 68


def main():
    cands = {(r["id"], r["n"]): r for r in csv.DictReader(open(os.path.join(HERE, "candidates.csv"), encoding="utf-8"))}
    picks = list(csv.DictReader(open(os.path.join(HERE, "selection.csv"), encoding="utf-8")))
    out_dir = os.path.join(HERE, "photos")
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".jpg"):
            os.remove(os.path.join(out_dir, f))

    credits = []
    for p in picks:
        for k, n in enumerate((p.get("n") or "").split(), 1):
            c = cands[(p["id"], n)]
            im = Image.open(os.path.join(HERE, c["file"])).convert("RGB")
            if im.width > WIDTH:
                im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
            name = f"{p['id']}-{k}.jpg"
            im.save(os.path.join(out_dir, name), "JPEG", quality=QUALITY, optimize=True, progressive=True)
            credits.append({"file": name, "id": p["id"], "author": c["author"], "license": c["license"], "url": c["url"]})
            print(f"{name}: {os.path.getsize(os.path.join(out_dir, name)) // 1024}KB  {c['title']}")

    with open(os.path.join(out_dir, "credits.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "id", "author", "license", "url"])
        w.writeheader()
        w.writerows(credits)


if __name__ == "__main__":
    main()
