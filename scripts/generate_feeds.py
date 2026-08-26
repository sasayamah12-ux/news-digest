#!/usr/bin/env python3
"""NetNewsWire向けに3本のRSSフィード(一般ニュース/政治経済/空調機業界)を生成する。
外部依存なし(標準ライブラリのみ)。既存のgenerate_digest.py(HTMLダッシュボード)とは独立して動作する。
"""

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Bangkok")
USER_AGENT = "Mozilla/5.0 (compatible; MorningDigestBot/1.0; personal use)"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
SITE_URL = "https://sasayamah12-ux.github.io/news-digest/"

# 一般ニュース。Yahoo!ニュースは利用規約で「個人利用のみ、プログラムでの再配信・再公開は禁止」と
# 明記されているため、自動生成フィードのソースからは除外する。
GENERAL_FEEDS = [
    ("社会", "https://www3.nhk.or.jp/rss/news/cat1.xml"),
    ("国際", "https://www3.nhk.or.jp/rss/news/cat6.xml"),
    ("科学・医療", "https://www3.nhk.or.jp/rss/news/cat3.xml"),
    ("文化・エンタメ", "https://www3.nhk.or.jp/rss/news/cat2.xml"),
    ("テック", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
]
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
GENERAL_TOTAL = 12
GENERAL_PER_CATEGORY = 2

POLITICS_ECON_FEEDS = [
    ("政治", "https://www3.nhk.or.jp/rss/news/cat4.xml", None),
    ("経済", "https://www3.nhk.or.jp/rss/news/cat5.xml", None),
    ("経済", "https://toyokeizai.net/list/feed/rss", "toyokeizai"),
]
POLITICS_ECON_TOTAL = 8
POLITICS_ECON_PER_SOURCE = 3
TOYOKEIZAI_ALLOWED_CATEGORIES = {"政治・経済・投資"}

# 空調機(業界専門ニュース)。日本語の業界専門メディアはRSS配信が確認できなかったため、
# Cooling Post(coolingpost.com、世界の空調・冷凍・ヒートポンプ業界の専門ニュースサイト)のみを使う。
HVAC_FEED_URL = "https://coolingpost.com/feed"
HVAC_ROOM_KEYWORDS = [
    "residential", "split system", "split-system", "mini-split", "mini split",
    "domestic", "ductless", "room air conditioner", "window unit", "home cooling",
]
HVAC_ROOM_MAX = 2
HVAC_COMMERCIAL_MAX = 6

KEYWORD_STOPWORDS = {"日本", "政府", "発表", "会見", "関係者", "一部", "きょう", "ニュース"}


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
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def rfc822(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


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


def deep_dive_url(title: str, keyword: str) -> str:
    question = f"「{title}」というニュースを見た。{keyword}について、背景や意味をわかりやすく教えて。"
    return "https://claude.ai/new?q=" + urllib.parse.quote(question, safe="")


def deep_dive_links_html(item: dict) -> str:
    """記事タイトルから抽出したキーワードごとに深掘りリンクを生成し、<br>区切りのHTML片で返す。"""
    keywords = extract_keywords(item["title"]) if has_japanese(item["title"]) else []
    if not keywords:
        keywords = [item["title"]]
    links = []
    for kw in keywords:
        dest = deep_dive_url(item["title"], kw)
        label = html.escape(kw) if kw != item["title"] else "この件を深掘り"
        links.append(f'<a href="{html.escape(dest)}">🔍 深掘り：{label}</a>')
    return "<br/>".join(links)


def build_general_list() -> list[dict]:
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
        count = 0
        for item in by_category[tag]:
            if count >= GENERAL_PER_CATEGORY:
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
    """Cooling Postの記事を、キーワードでルームエアコン(大きな話題のみ)と店舗用・業務用(メイン)に振り分ける。"""
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


def rss_item(title: str, link: str, pubdate: datetime, description_html: str | None) -> str:
    parts = [
        "  <item>",
        f"    <title>{html.escape(title)}</title>",
        f"    <link>{html.escape(link)}</link>",
        f'    <guid isPermaLink="true">{html.escape(link)}</guid>',
        f"    <pubDate>{rfc822(pubdate)}</pubDate>",
    ]
    if description_html:
        parts.append(f"    <description><![CDATA[{description_html}]]></description>")
    parts.append("  </item>")
    return "\n".join(parts)


def rss_feed(title: str, description: str, link: str, items_xml: list[str], now: datetime) -> str:
    items_block = "\n".join(items_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{html.escape(title)}</title>
  <link>{html.escape(link)}</link>
  <description>{html.escape(description)}</description>
  <language>ja</language>
  <lastBuildDate>{rfc822(now)}</lastBuildDate>
{items_block}
</channel>
</rss>
"""


def build_general_feed(now: datetime) -> str:
    items = build_general_list()
    items_xml = [
        rss_item(f"【{item['tag']}】{item['title']}", item["link"], item["pubdate"], None)
        for item in items
    ]
    return rss_feed(
        "一般ニュース",
        "見出し中心・量重視の一般ニュース(スポーツ除く)",
        SITE_URL + "general.xml",
        items_xml,
        now,
    )


def build_politics_econ_feed(now: datetime) -> str:
    items = build_politics_econ_list()
    items_xml = []
    for item in items:
        summary = item["description"] or "詳細は記事本文をご覧ください。"
        body = f"{html.escape(summary)}<br/><br/>{deep_dive_links_html(item)}"
        items_xml.append(
            rss_item(f"【{item['tag']}】{item['title']}", item["link"], item["pubdate"], body)
        )
    return rss_feed(
        "政治経済",
        "要約と深掘りリンク付きの政治経済ニュース",
        SITE_URL + "politics-economy.xml",
        items_xml,
        now,
    )


def build_hvac_feed(now: datetime) -> str:
    room_items, commercial_items = build_hvac_lists()
    items_xml = []
    for item in room_items:
        summary = item["description"] or "詳細は記事本文をご覧ください。"
        items_xml.append(
            rss_item(f"【ルーム】{item['title']}", item["link"], item["pubdate"], html.escape(summary))
        )
    for item in commercial_items:
        summary = item["description"] or "詳細は記事本文をご覧ください。"
        body = f"{html.escape(summary)}<br/><br/>{deep_dive_links_html(item)}"
        items_xml.append(
            rss_item(f"【業務用】{item['title']}", item["link"], item["pubdate"], body)
        )
    return rss_feed(
        "空調機（エアコン）業界ニュース",
        "ルームエアコン(大きな話題のみ)と店舗用・業務用(日本・アセオセ市場)の業界ニュース",
        SITE_URL + "hvac.xml",
        items_xml,
        now,
    )


def main() -> None:
    now = datetime.now(TIMEZONE)

    feeds = {
        "public/general.xml": build_general_feed(now),
        "public/politics-economy.xml": build_politics_econ_feed(now),
        "public/hvac.xml": build_hvac_feed(now),
    }
    for path, content in feeds.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
