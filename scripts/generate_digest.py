#!/usr/bin/env python3
"""毎朝のニュースダイジェストHTMLをRSSフィードから生成する。外部依存なし(標準ライブラリのみ)。"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Bangkok")
USER_AGENT = "Mozilla/5.0 (compatible; MorningDigestBot/1.0; personal use)"
DC_NS = "{http://purl.org/dc/elements/1.1/}"

# クリック追跡バックエンド(Google Apps Script)。未設定なら追跡なし・均等配分にフォールバックする。
APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL", "").strip()
APPS_SCRIPT_SECRET = os.environ.get("APPS_SCRIPT_SECRET", "").strip()
CLICK_WEIGHT_DAYS = 30
MIN_CATEGORY_SLOTS = 1
MAX_CATEGORY_SLOTS = 4

# 固定タグの一般ニュースフィード。同じタグを複数指定すると1つのプールに合流する。
GENERAL_FEEDS = [
    ("社会", "https://www3.nhk.or.jp/rss/news/cat1.xml"),
    ("国際", "https://www3.nhk.or.jp/rss/news/cat6.xml"),
    ("科学・医療", "https://www3.nhk.or.jp/rss/news/cat3.xml"),
    ("文化・エンタメ", "https://www3.nhk.or.jp/rss/news/cat2.xml"),
    ("テック", "https://news.yahoo.co.jp/rss/topics/it.xml"),
    ("テック", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("生活", "https://news.yahoo.co.jp/rss/topics/local.xml"),
]
# 朝日新聞は記事ごとにdc:subjectでジャンルが付くので、そのまま対応カテゴリへ振り分ける
ASAHI_FEED_URL = "https://www.asahi.com/rss/asahi/newsheadlines.rdf"
ASAHI_SUBJECT_MAP = {
    "社会": "社会",
    "国際": "国際",
    "文化": "文化・エンタメ",
    "エンタメ": "文化・エンタメ",
    "科学": "科学・医療",
    "医療・健康": "科学・医療",
    "IT・科学": "テック",
    "生活": "生活",
}
CATEGORY_ORDER = ["社会", "国際", "科学・医療", "文化・エンタメ", "テック", "生活"]
TOYOKEIZAI_ALLOWED_CATEGORIES = {"政治・経済・投資"}
GENERAL_TOTAL = 12
GENERAL_PER_CATEGORY = 2

POLITICS_ECON_FEEDS = [
    ("政治", "https://www3.nhk.or.jp/rss/news/cat4.xml", None),
    ("経済", "https://www3.nhk.or.jp/rss/news/cat5.xml", None),
    ("経済", "https://toyokeizai.net/list/feed/rss", "toyokeizai"),
]
POLITICS_ECON_TOTAL = 8
POLITICS_ECON_PER_SOURCE = 3

# 空調機（業界専門ニュース）。Cooling Post(coolingpost.com)は世界の空調・冷凍・ヒートポンプ業界の
# 専門ニュースサイト。日本語の業界専門メディアはRSS配信が確認できなかったため、現状はこの1本のみ。
HVAC_FEED_URL = "https://coolingpost.com/feed"
HVAC_ROOM_KEYWORDS = [
    "residential", "split system", "split-system", "mini-split", "mini split",
    "domestic", "ductless", "room air conditioner", "window unit", "home cooling",
]
HVAC_ROOM_MAX = 2
HVAC_COMMERCIAL_MAX = 6

KEYWORD_STOPWORDS = {"日本", "政府", "発表", "会見", "関係者", "一部", "きょう", "ニュース"}
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def clean_title(title: str, source: str | None) -> str:
    if source == "toyokeizai" and " | " in title:
        return title.split(" | ")[0].strip()
    return title


def clean_description(description: str, source: str | None) -> str:
    if source == "coolingpost":
        description = re.sub(r"Read More\.\.\.\s*", "", description)
        description = re.sub(r"The post .* appeared first on Cooling Post\.\s*", "", description)
    return description.strip()


def has_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶ一-龠]", text))


def translate_to_japanese(text: str) -> str:
    """MyMemory(無料・APIキー不要)で英語テキストを日本語に翻訳する。失敗時は原文のまま返す。"""
    if not text or has_japanese(text):
        return text
    try:
        params = {"q": text[:490], "langpair": "en|ja"}
        url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote
        )
        raw = fetch(url)
        data = json.loads(raw)
        translated = data.get("responseData", {}).get("translatedText", "")
        translated = html.unescape(translated).strip()
        return translated or text
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        print(f"[warn] translation failed for {text[:30]!r}: {exc}", file=sys.stderr)
        return text


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def parse_pubdate(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC"))


def parse_feed(tag: str | None, url: str, source: str | None = None) -> list[dict]:
    """tagがNoneの場合、各アイテムのdc:subjectをASAHI_SUBJECT_MAPで解決してタグにする(朝日新聞用)。"""
    try:
        raw = fetch(url)
        root = ET.fromstring(raw)
    except (urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
        print(f"[warn] failed to fetch {tag or source} ({url}): {exc}", file=sys.stderr)
        return []

    items = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
        if pubdate_el is None:
            pubdate_el = item.find(DC_NS + "date")
        desc_el = item.find("description")
        if title_el is None or link_el is None or not title_el.text:
            continue

        item_tag = tag
        if item_tag is None:
            subject_el = item.find(DC_NS + "subject")
            subject = subject_el.text.strip() if subject_el is not None and subject_el.text else ""
            item_tag = ASAHI_SUBJECT_MAP.get(subject)
            if item_tag is None:
                continue  # 政治・経済・スポーツなど対象外ジャンルは除外

        if source == "toyokeizai":
            category_el = item.find("category")
            category = category_el.text.strip() if category_el is not None and category_el.text else ""
            if category not in TOYOKEIZAI_ALLOWED_CATEGORIES:
                continue

        title = clean_title(html.unescape(title_el.text.strip()), source)
        link = (link_el.text or "").strip()
        pubdate_text = (pubdate_el.text or "").strip() if pubdate_el is not None else ""
        description = ""
        if desc_el is not None and desc_el.text:
            description = html.unescape(re.sub(r"<[^>]+>", "", desc_el.text)).strip()
            description = clean_description(description, source)
        items.append(
            {
                "tag": item_tag,
                "title": title,
                "link": link,
                "pubdate": parse_pubdate(pubdate_text),
                "description": description,
            }
        )
    return items


def source_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def beacon_url(**fields: str) -> str:
    params = {k: v for k, v in fields.items() if v}
    return APPS_SCRIPT_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def click_track_attr(item: dict, kind: str, position: int) -> str:
    """記事クリック記録用のビーコンURLをdata-track属性として返す。記事へは直接リンクしたまま、
    裏でこのURLにfetchするだけにする(Apps ScriptのHtmlOutputは常にサンドボックスiframe経由になり、
    外部サイトへのJSリダイレクトがフレーム埋め込みを拒否するサイトで失敗するため、リダイレクト方式は
    採用しない)。"""
    if not APPS_SCRIPT_URL:
        return ""
    url = beacon_url(
        event="click",
        dest=item["link"],
        cat=item["tag"],
        kind=kind,
        pos=str(position),
        src=source_of(item["link"]),
        t=item["title"][:60],
    )
    return f' data-track="{html.escape(url)}"'


def chip_track_attr(item: dict, kind: str, keyword: str, dest: str) -> str:
    if not APPS_SCRIPT_URL:
        return ""
    url = beacon_url(
        event="chip_click",
        dest=dest,
        cat=item["tag"],
        kind=kind,
        t=item["title"][:60],
        keyword=keyword[:30],
    )
    return f' data-track="{html.escape(url)}"'


def impression_record(item: dict, kind: str, position: int) -> dict:
    return {
        "kind": kind,
        "cat": item["tag"],
        "pos": position,
        "src": source_of(item["link"]),
        "t": item["title"][:60],
        "dest": item["link"],
    }


def fetch_click_weights(kind: str) -> dict[str, dict[str, int]]:
    if not APPS_SCRIPT_URL or not APPS_SCRIPT_SECRET:
        return {}
    params = {"mode": "summary", "key": APPS_SCRIPT_SECRET, "kind": kind, "days": CLICK_WEIGHT_DAYS}
    url = APPS_SCRIPT_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    try:
        raw = fetch(url)
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[warn] failed to fetch click weights: {exc}", file=sys.stderr)
        return {}
    if not isinstance(data, dict) or "error" in data:
        return {}
    result = {}
    for cat, v in data.items():
        if isinstance(v, dict):
            result[cat] = {"clicks": int(v.get("clicks", 0)), "impressions": int(v.get("impressions", 0))}
    return result


def compute_category_slots(
    categories: list[str], stats: dict[str, dict[str, int]], total_slots: int
) -> dict[str, int]:
    """クリック率(CTR、Laplaceスムージング付き)に比例して枠を配分する。データが無ければ均等割り。
    生クリック数ではなくCTRを使うのは、単に多く表示しているカテゴリがさらに多く表示される
    という偏りループを避けるため(表示された数=インプレッションで正規化する)。"""

    def ctr(cat: str) -> float:
        s = stats.get(cat, {})
        return (s.get("clicks", 0) + 1) / (s.get("impressions", 0) + 2)

    weights = {cat: ctr(cat) for cat in categories}
    weight_sum = sum(weights.values())

    raw = {cat: total_slots * w / weight_sum for cat, w in weights.items()}
    slots = {cat: max(MIN_CATEGORY_SLOTS, min(MAX_CATEGORY_SLOTS, round(v))) for cat, v in raw.items()}

    # 丸め・クランプで合計がズレるので、端数の大きい順/小さい順に1個ずつ調整して合わせる
    diff = total_slots - sum(slots.values())
    order = sorted(categories, key=lambda c: raw[c] - slots[c], reverse=(diff > 0))
    i = 0
    while diff != 0 and order:
        cat = order[i % len(order)]
        if diff > 0 and slots[cat] < MAX_CATEGORY_SLOTS:
            slots[cat] += 1
            diff -= 1
        elif diff < 0 and slots[cat] > MIN_CATEGORY_SLOTS:
            slots[cat] -= 1
            diff += 1
        i += 1
        if i > len(order) * (MAX_CATEGORY_SLOTS + 1):
            break  # 安全弁: 極端な設定でも無限ループしない

    return slots


def dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        key = item["title"]
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_general_list(category_slots: dict[str, int]) -> list[dict]:
    by_category: dict[str, list[dict]] = {tag: [] for tag in CATEGORY_ORDER}
    for tag, url in GENERAL_FEEDS:
        by_category[tag].extend(parse_feed(tag, url))
    for item in parse_feed(None, ASAHI_FEED_URL):
        by_category.setdefault(item["tag"], []).append(item)

    for tag in by_category:
        by_category[tag] = dedupe(by_category[tag])
        by_category[tag].sort(key=lambda i: i["pubdate"], reverse=True)

    picked = []
    seen_titles: set[str] = set()
    taken_per_tag: dict[str, int] = {tag: 0 for tag in CATEGORY_ORDER}
    for tag in CATEGORY_ORDER:
        slots = category_slots.get(tag, GENERAL_PER_CATEGORY)
        count = 0
        for item in by_category[tag]:
            if count >= slots:
                break
            if item["title"] in seen_titles:
                continue
            picked.append(item)
            seen_titles.add(item["title"])
            count += 1
        taken_per_tag[tag] = count

    if len(picked) < GENERAL_TOTAL:
        pool = [i for tag in CATEGORY_ORDER for i in by_category[tag][taken_per_tag[tag]:]]
        pool.sort(key=lambda i: i["pubdate"], reverse=True)
        for item in pool:
            if len(picked) >= GENERAL_TOTAL:
                break
            if item["title"] in seen_titles:
                continue
            picked.append(item)
            seen_titles.add(item["title"])

    picked.sort(key=lambda i: i["pubdate"], reverse=True)
    return picked[:GENERAL_TOTAL]


def extract_keywords(title: str) -> list[str]:
    candidates = []
    candidates.extend(re.findall(r"「([^」]{2,14})」", title))
    candidates.extend(re.findall(r"[ァ-ヴー]{2,}[A-Za-z0-9]{0,6}", title))
    candidates.extend(re.findall(r"(?<![A-Za-zÀ-ÖØ-öø-ÿ])[A-Za-z]{2,6}(?![A-Za-zÀ-ÖØ-öø-ÿ])", title))
    candidates.extend(re.findall(r"[一-龠]{2,6}", title))

    seen = set()
    keywords = []
    for word in candidates:
        if word in KEYWORD_STOPWORDS or word in seen:
            continue
        seen.add(word)
        keywords.append(word)
        if len(keywords) >= 3:
            break
    return keywords


def build_politics_econ_list() -> list[dict]:
    buckets = []
    for tag, url, source in POLITICS_ECON_FEEDS:
        items = dedupe(parse_feed(tag, url, source))
        items.sort(key=lambda i: i["pubdate"], reverse=True)
        buckets.append(items)

    picked = []
    seen_titles: set[str] = set()
    for items in buckets:
        count = 0
        for item in items:
            if count >= POLITICS_ECON_PER_SOURCE:
                break
            if item["title"] in seen_titles:
                continue
            picked.append(item)
            seen_titles.add(item["title"])
            count += 1

    if len(picked) < POLITICS_ECON_TOTAL:
        pool = [i for items in buckets for i in items[POLITICS_ECON_PER_SOURCE:]]
        pool.sort(key=lambda i: i["pubdate"], reverse=True)
        for item in pool:
            if len(picked) >= POLITICS_ECON_TOTAL:
                break
            if item["title"] in seen_titles:
                continue
            picked.append(item)
            seen_titles.add(item["title"])

    picked.sort(key=lambda i: i["pubdate"], reverse=True)
    return picked[:POLITICS_ECON_TOTAL]


def build_hvac_lists() -> tuple[list[dict], list[dict]]:
    """Cooling Post(空調・冷凍・ヒートポンプ業界の専門ニュース)を、キーワードでルームエアコン
    (大きな話題のみ)と店舗用・業務用(メイン)に振り分ける。"""
    items = dedupe(parse_feed("空調", HVAC_FEED_URL, "coolingpost"))
    items.sort(key=lambda i: i["pubdate"], reverse=True)

    room, commercial = [], []
    for item in items:
        haystack = (item["title"] + " " + item["description"]).lower()
        if any(kw in haystack for kw in HVAC_ROOM_KEYWORDS):
            room.append(item)
        else:
            commercial.append(item)

    room = room[:HVAC_ROOM_MAX]
    commercial = commercial[:HVAC_COMMERCIAL_MAX]

    for item in room + commercial:
        item["title"] = translate_to_japanese(item["title"])
        item["description"] = translate_to_japanese(item["description"])

    return room, commercial


def deep_dive_url(title: str, keyword: str) -> str:
    question = f"「{title}」というニュースを見た。{keyword}について、背景や意味をわかりやすく教えて。"
    return "https://claude.ai/new?q=" + urllib.parse.quote(question, safe="")


def render_html(
    general_items: list[dict],
    deep_items: list[dict],
    hvac_room_items: list[dict],
    hvac_commercial_items: list[dict],
    now: datetime,
) -> str:
    date_line = f"{now.year}年{now.month}月{now.day}日（{WEEKDAY_JA[now.weekday()]}）"
    updated_line = now.strftime("%H:%M")

    impressions: list[dict] = []

    general_html_parts = []
    for pos, i in enumerate(general_items, start=1):
        impressions.append(impression_record(i, "general", pos))
        attr = click_track_attr(i, "general", pos)
        general_html_parts.append(
            f'          <li><span class="tag">{html.escape(i["tag"])}</span>'
            f'<a href="{html.escape(i["link"])}" target="_blank" rel="noopener"{attr}>{html.escape(i["title"])}</a></li>'
        )
    general_html = "\n".join(general_html_parts)

    deep_blocks = []
    for pos, item in enumerate(deep_items, start=1):
        impressions.append(impression_record(item, "politics_econ", pos))
        keywords = extract_keywords(item["title"])
        chip_parts = []
        for kw in keywords:
            dest = deep_dive_url(item["title"], kw)
            chip_attr = chip_track_attr(item, "politics_econ", kw, dest)
            chip_parts.append(
                f'            <a class="chip" href="{dest}" target="_blank" rel="noopener"{chip_attr}>{html.escape(kw)}</a>'
            )
        if not chip_parts:
            dest = deep_dive_url(item["title"], item["title"])
            chip_attr = chip_track_attr(item, "politics_econ", item["title"], dest)
            chip_parts.append(
                f'            <a class="chip" href="{dest}" target="_blank" rel="noopener"{chip_attr}>この件を深掘り</a>'
            )
        chips = "\n".join(chip_parts)
        description = item["description"] or "詳細は記事本文をご覧ください。"
        article_attr = click_track_attr(item, "politics_econ", pos)
        deep_blocks.append(
            f"""        <div class="deep-item">
          <p class="deep-title"><span class="tag">{html.escape(item["tag"])}</span> <a href="{html.escape(item["link"])}" target="_blank" rel="noopener"{article_attr}>{html.escape(item["title"])}</a></p>
          <p class="deep-body">{html.escape(description)}</p>
          <div class="keywords">
            <span class="keywords-label">気になったら深掘り：</span>
{chips}
          </div>
        </div>"""
        )
    deep_html = "\n\n".join(deep_blocks)

    hvac_room_html_parts = []
    for pos, i in enumerate(hvac_room_items, start=1):
        impressions.append(impression_record(i, "hvac_room", pos))
        attr = click_track_attr(i, "hvac_room", pos)
        hvac_room_html_parts.append(
            f'          <li><span class="tag">ルーム</span>'
            f'<a href="{html.escape(i["link"])}" target="_blank" rel="noopener"{attr}>{html.escape(i["title"])}</a></li>'
        )
    hvac_room_html = (
        "\n".join(hvac_room_html_parts)
        if hvac_room_html_parts
        else '          <li class="empty-note">特筆すべき大きな話題はありません。</li>'
    )

    hvac_commercial_blocks = []
    for pos, item in enumerate(hvac_commercial_items, start=1):
        impressions.append(impression_record(item, "hvac_commercial", pos))
        # 英語タイトルはextract_keywordsが単語断片を拾ってしまうため、日本語タイトルの場合のみ適用する
        keywords = extract_keywords(item["title"]) if has_japanese(item["title"]) else []
        chip_parts = []
        for kw in keywords:
            dest = deep_dive_url(item["title"], kw)
            chip_attr = chip_track_attr(item, "hvac_commercial", kw, dest)
            chip_parts.append(
                f'            <a class="chip" href="{dest}" target="_blank" rel="noopener"{chip_attr}>{html.escape(kw)}</a>'
            )
        if not chip_parts:
            dest = deep_dive_url(item["title"], item["title"])
            chip_attr = chip_track_attr(item, "hvac_commercial", item["title"], dest)
            chip_parts.append(
                f'            <a class="chip" href="{dest}" target="_blank" rel="noopener"{chip_attr}>この件を深掘り</a>'
            )
        chips = "\n".join(chip_parts)
        description = item["description"] or "詳細は記事本文をご覧ください。"
        article_attr = click_track_attr(item, "hvac_commercial", pos)
        hvac_commercial_blocks.append(
            f"""        <div class="deep-item">
          <p class="deep-title"><span class="tag">業務用</span> <a href="{html.escape(item["link"])}" target="_blank" rel="noopener"{article_attr}>{html.escape(item["title"])}</a></p>
          <p class="deep-body">{html.escape(description)}</p>
          <div class="keywords">
            <span class="keywords-label">気になったら深掘り：</span>
{chips}
          </div>
        </div>"""
        )
    hvac_commercial_html = (
        "\n\n".join(hvac_commercial_blocks)
        if hvac_commercial_blocks
        else '        <p class="empty-note">本日は該当ニュースがありません。</p>'
    )

    impressions_script = ""
    if APPS_SCRIPT_URL and impressions:
        payload = json.dumps(impressions, ensure_ascii=False).replace("</", "<\\/")
        impressions_script = f"""
  (function () {{
    var records = {payload};
    try {{
      fetch({json.dumps(APPS_SCRIPT_URL)}, {{ method: 'POST', body: JSON.stringify(records), keepalive: true, mode: 'no-cors' }});
    }} catch (err) {{}}
  }})();"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>今日のニュースダイジェスト</title>
<style>
  :root {{
    --bg: #FCFCFB;
    --wash: #F9F9F7;
    --ink: #2E2C27;
    --ink-soft: #6B6A63;
    --ink-grey: #B4B3A8;
    --hairline: #E4E3DC;
    --clay: #C6613F;
    --clay-soft: #F4E4DD;
    --clay-hover: #AE5133;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
    line-height: 1.6;
  }}
  .band {{ padding: 40px 24px; }}
  .band-top {{ background: var(--wash); border-bottom: 1px solid var(--hairline); }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  .date-line {{ font-size: 13px; color: var(--ink-soft); letter-spacing: 0.02em; margin-bottom: 8px; }}
  .headline {{ font-family: Georgia, "Hiragino Mincho ProN", serif; font-size: 26px; font-weight: 600; margin: 0 0 6px 0; }}
  .subline {{ font-size: 14px; color: var(--ink-soft); margin: 0; }}
  .section-title {{ font-size: 13px; font-weight: 600; letter-spacing: 0.04em; color: var(--ink-soft); text-transform: uppercase; margin: 0 0 18px 0; }}
  .section {{ margin-bottom: 44px; }}
  .section:last-child {{ margin-bottom: 0; }}
  .headline-list {{ list-style: none; margin: 0; padding: 0; }}
  .headline-list li {{ display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--hairline); align-items: baseline; }}
  .headline-list li:last-child {{ border-bottom: none; }}
  .tag {{ flex-shrink: 0; font-size: 11px; color: var(--ink-grey); width: 64px; }}
  .headline-list a {{ color: var(--ink); text-decoration: none; font-size: 15px; }}
  .headline-list a:hover {{ color: var(--clay); }}
  .deep-item {{ padding: 20px 0; border-bottom: 1px solid var(--hairline); }}
  .deep-item:last-child {{ border-bottom: none; }}
  .deep-title {{ font-size: 17px; font-weight: 600; margin: 0 0 8px 0; }}
  .deep-title .tag {{ width: auto; margin-right: 4px; }}
  .deep-title a {{ color: var(--ink); text-decoration: underline; text-decoration-color: var(--hairline); text-underline-offset: 3px; }}
  .deep-body {{ font-size: 14.5px; color: var(--ink-soft); margin: 0 0 12px 0; }}
  .keywords {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  .keywords-label {{ font-size: 12px; color: var(--ink-grey); margin-right: 2px; width: 100%; margin-bottom: 2px; }}
  .chip {{
    font-size: 12.5px; color: var(--clay); background: var(--clay-soft);
    padding: 5px 12px; border-radius: 20px; white-space: nowrap; text-decoration: none;
    display: inline-flex; align-items: center; gap: 4px; transition: background 0.15s, color 0.15s;
  }}
  .chip:hover {{ background: var(--clay); color: #FCFCFB; }}
  .chip::after {{ content: "→"; font-size: 11px; opacity: 0.7; }}
  .subsection-title {{ font-size: 12px; font-weight: 600; letter-spacing: 0.03em; color: var(--ink-grey); margin: 0 0 10px 0; }}
  .hvac-commercial-title {{ margin-top: 26px; }}
  .empty-note {{ font-size: 13.5px; color: var(--ink-grey); padding: 8px 0 4px 0; }}
  .footnote {{ font-size: 12.5px; color: var(--ink-grey); margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--hairline); }}
  @media (max-width: 640px) {{
    .band {{ padding: 28px 18px; }}
    .headline {{ font-size: 22px; }}
    .tag {{ width: 52px; }}
  }}
</style>
</head>
<body>

  <div class="band band-top">
    <div class="wrap">
      <div class="date-line">{date_line}</div>
      <h1 class="headline">今日のニュースダイジェスト</h1>
      <p class="subline">一般ニュースはサッと見出しを、政治経済は気になったらそのまま深掘りへ。</p>
    </div>
  </div>

  <div class="band">
    <div class="wrap">

      <div class="section">
        <p class="section-title">一般ニュース・興味のある分野</p>
        <ul class="headline-list">
{general_html}
        </ul>
      </div>

      <div class="section">
        <p class="section-title">政治経済</p>

{deep_html}

      </div>

      <div class="section">
        <p class="section-title">空調機（エアコン）業界ニュース</p>

        <p class="subsection-title">ルームエアコン（大きな話題のみ）</p>
        <ul class="headline-list">
{hvac_room_html}
        </ul>

        <p class="subsection-title hvac-commercial-title">店舗用・業務用（日本・アセオセ市場）</p>
{hvac_commercial_html}

      </div>

      <p class="footnote">
        最終更新: {date_line} {updated_line}（Asia/Bangkok）※NHK・Yahoo!ニュース・朝日新聞・東洋経済オンライン・ITmedia・Cooling PostのRSSより自動生成。要約は各社提供のものをそのまま使用しています（Cooling Postの英語記事は機械翻訳）。<br>
        「気になったら深掘り」のチップをタップすると、その質問内容が入った新しいClaudeとの会話が開きます。
      </p>

    </div>
  </div>

<script>
  document.addEventListener('click', function (e) {{
    var a = e.target.closest('a[data-track]');
    if (!a) return;
    try {{ fetch(a.dataset.track, {{ mode: 'no-cors', keepalive: true }}); }} catch (err) {{}}
  }}, true);
{impressions_script}
</script>

</body>
</html>
"""


def main() -> None:
    now = datetime.now(TIMEZONE)
    click_weights = fetch_click_weights("general")
    category_slots = compute_category_slots(CATEGORY_ORDER, click_weights, GENERAL_TOTAL)
    if click_weights:
        print(f"[info] click-weighted category slots: {category_slots}", file=sys.stderr)
    general_items = build_general_list(category_slots)
    deep_items = build_politics_econ_list()
    hvac_room_items, hvac_commercial_items = build_hvac_lists()
    output = render_html(general_items, deep_items, hvac_room_items, hvac_commercial_items, now)

    out_path = "public/index.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(
        f"wrote {out_path}: {len(general_items)} general items, {len(deep_items)} politics/econ items, "
        f"{len(hvac_room_items)} hvac-room items, {len(hvac_commercial_items)} hvac-commercial items"
    )


if __name__ == "__main__":
    main()
