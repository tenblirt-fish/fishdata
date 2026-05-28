"""
Сбор данных по нерке Аляски — версия v8.0
Прямой парсинг сайтов без RSS (обходим пейволл)
"""

import json
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
    from deep_translator import GoogleTranslator
    print("✅ Библиотеки импортированы")
except ImportError as e:
    print(f"❌ {e}")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

HARVEST_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.harvestsummary"
ADFG_BB_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.salmon"
ADFG_NEWS_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.bbnews"

# Источники для прямого парсинга (без RSS, бесплатные)
NEWS_SOURCES = [
    {
        "name": "KDLG Bristol Bay",
        "url": "https://www.kdlg.org/search?query=sockeye+salmon&t=article",
        "article_selector": "article, .node--type-article, .views-row",
        "title_selector": "h2, h3, .node__title",
        "link_selector": "a",
        "summary_selector": "p, .field--name-body",
    },
    {
        "name": "Alaska Beacon",
        "url": "https://alaskabeacon.com/?s=sockeye+salmon",
        "article_selector": "article, .post",
        "title_selector": "h2, h3, .entry-title",
        "link_selector": "a",
        "summary_selector": ".entry-summary, p",
    },
    {
        "name": "National Fisherman",
        "url": "https://www.nationalfisherman.com/?s=bristol+bay+sockeye",
        "article_selector": "article, .article-item, .post",
        "title_selector": "h2, h3, .article-title",
        "link_selector": "a",
        "summary_selector": "p, .excerpt",
    },
    {
        "name": "BBRSDA",
        "url": "https://www.bbrsda.com/updates/",
        "article_selector": "article, .update-item, .entry, .post",
        "title_selector": "h2, h3, h4",
        "link_selector": "a",
        "summary_selector": "p",
    },
    {
        "name": "Anchorage Daily News",
        "url": "https://www.adn.com/search/?q=bristol+bay+sockeye&sort=date",
        "article_selector": "article, .ArticleCard",
        "title_selector": "h2, h3, .ArticleCard-headline",
        "link_selector": "a",
        "summary_selector": "p, .ArticleCard-description",
    },
    {
        "name": "SeafoodSource",
        "url": "https://www.seafoodsource.com/news/supply-trade?q=bristol+bay+sockeye",
        "article_selector": "article, .news-item, .article-card",
        "title_selector": "h2, h3, .article-title",
        "link_selector": "a",
        "summary_selector": "p, .summary",
    },
]

KEYWORDS = [
    "sockeye", "bristol bay", "salmon harvest", "red salmon",
    "ex-vessel", "salmon season", "salmon price", "adf&g",
    "нерка", "лосось", "аляск",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 20


def http_get(url):
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  ⚠️  {url[:60]}: {type(e).__name__}")
        return None


def translate_text(text, lang):
    if not text or len(text.strip()) < 5:
        return text
    try:
        t = GoogleTranslator(source='auto', target=lang)
        result = t.translate(text[:600])
        time.sleep(0.25)
        return result or text
    except:
        return text


def is_relevant(text):
    return any(kw.lower() in text.lower() for kw in KEYWORDS)


def parse_news_source(source):
    """Парсит один источник напрямую без RSS."""
    print(f"\n🔍 {source['name']}...")
    print(f"   {source['url']}")

    items = []
    resp = http_get(source["url"])
    if not resp:
        return items

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Пробуем найти статьи по селектору
        articles = []
        for sel in source["article_selector"].split(", "):
            found = soup.select(sel)
            if found:
                articles = found
                break

        if not articles:
            # Fallback — ищем все ссылки с текстом
            articles = soup.find_all("a", href=True)

        print(f"   Найдено блоков: {len(articles)}")

        for art in articles[:20]:
            # Заголовок
            title = ""
            for sel in source["title_selector"].split(", "):
                el = art.select_one(sel) if hasattr(art, 'select_one') else None
                if el:
                    title = el.get_text(strip=True)
                    break
            if not title:
                title = art.get_text(strip=True)[:120]

            if len(title) < 15:
                continue

            # Ссылка
            link = ""
            a_tag = art.find("a") if hasattr(art, 'find') else art
            if a_tag and a_tag.get("href"):
                href = a_tag["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    domain = "/".join(source["url"].split("/")[:3])
                    link = domain + href

            # Summary
            summary = ""
            for sel in source["summary_selector"].split(", "):
                el = art.select_one(sel) if hasattr(art, 'select_one') else None
                if el:
                    summary = el.get_text(strip=True)[:400]
                    break

            # Проверяем релевантность
            if not is_relevant(title + " " + summary):
                continue

            print(f"   ✅ {title[:70]}")
            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "published": "",
            })

            if len(items) >= 5:
                break

    except Exception as e:
        print(f"   ❌ Ошибка: {e}")

    return items


def fetch_adfg_news_direct():
    """Прямой парсинг пресс-релизов ADF&G Bristol Bay."""
    print(f"\n🏛  ADF&G Bristol Bay News...")
    items = []

    resp = http_get(ADFG_NEWS_URL)
    if not resp:
        return items

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            href = link["href"]

            if len(text) < 15:
                continue
            if not any(kw in text.lower() for kw in ["salmon", "sockeye", "2026", "harvest", "season"]):
                continue

            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            items.append({
                "title": text,
                "link": full_url,
                "summary": "",
                "published": "",
            })
            print(f"   ✅ {text[:70]}")

            if len(items) >= 8:
                break

    except Exception as e:
        print(f"   ❌ {e}")

    return items


def fetch_harvest_tables():
    """Парсит таблицы вылова с harvestsummary."""
    print("\n" + "="*70)
    print("📋 ТАБЛИЦЫ ВЫЛОВА (harvestsummary)")
    print("="*70)

    result = {
        "url": HARVEST_URL,
        "run_date": None,
        "season_active": False,
        "total_run_summary": {},
        "river_estimates": {},
        "sockeye_per_delivery": {},
        "cumulative_catch": 0,
        "cumulative_escapement": 0,
        "note": "Межсезонье. Данные появятся с ~22 июня 2026.",
    }

    resp = http_get(HARVEST_URL)
    if not resp:
        return result

    soup = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text()

    # Дата
    dm = re.search(r"(\d{2}-\d{2}-\d{4})", page_text)
    if dm:
        result["run_date"] = dm.group(1)
        print(f"  📅 Дата: {result['run_date']}")

    tables = soup.find_all("table")
    print(f"  📊 Таблиц: {len(tables)}")

    for table in tables:
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if not headers:
            continue

        rows = table.find_all("tr")[1:]  # без заголовка

        def parse_val(s):
            s = s.replace(",", "").strip()
            try:
                return int(s)
            except:
                return s

        # Таблица Total Run Summary
        if "Catch Daily" in headers and "Catch Cumulative" in headers:
            print("  ✅ Total Run Summary")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cells:
                    continue
                district = cells[0]
                data = {}
                for i, h in enumerate(headers):
                    if i < len(cells):
                        data[h] = parse_val(cells[i])
                key = "TOTALS" if "Totals" in district else district
                result["total_run_summary"][key] = data
                # Проверяем есть ли данные
                cum = data.get("Catch Cumulative", 0)
                if isinstance(cum, int) and cum > 0:
                    result["season_active"] = True

            totals = result["total_run_summary"].get("TOTALS", {})
            result["cumulative_catch"] = totals.get("Catch Cumulative", 0) or 0
            result["cumulative_escapement"] = totals.get("Escapement Cumulative", 0) or 0

        # River Estimates
        elif "Escapement Daily" in headers and "In-River Estimate" in headers:
            print("  ✅ River Estimates")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    river = cells[0]
                    data = {h: parse_val(cells[i]) for i, h in enumerate(headers) if i < len(cells)}
                    if river:
                        result["river_estimates"][river] = data

        # Sockeye per Delivery
        elif "Sockeye per Delivery" in headers:
            print("  ✅ Sockeye per Delivery")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    result["sockeye_per_delivery"][cells[0]] = parse_val(cells[1])

    if result["season_active"]:
        result["note"] = f"Bluesheet активен (дата: {result['run_date']})"

    print(f"  Cumulative catch: {result['cumulative_catch']:,}")
    print(f"  Сезон активен: {result['season_active']}")
    return result


def main():
    print("\n" + "="*70)
    print("🐟 ALASKA SOCKEYE MONITOR v8.0 — прямой парсинг")
    print(f"⏰ {datetime.now(timezone.utc).isoformat()}")
    print("="*70)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # Таблицы вылова
    harvest = fetch_harvest_tables()

    # Новости — прямой парсинг
    print("\n" + "="*70)
    print("📰 СОБИРАЮ НОВОСТИ (прямой парсинг)")
    print("="*70)

    raw_news = []

    # 1. Прямой парсинг сайтов
    for source in NEWS_SOURCES:
        items = parse_news_source(source)
        for item in items:
            item["source"] = source["name"]
            raw_news.append(item)

    # 2. ADF&G новости
    adfg_items = fetch_adfg_news_direct()
    for item in adfg_items:
        item["source"] = "ADF&G Bristol Bay"
        raw_news.append(item)

    print(f"\n📊 Всего новостей до перевода: {len(raw_news)}")

    # Переводим
    news = []
    for item in raw_news[:25]:
        print(f"  🔄 {item['title'][:60]}...")
        news.append({
            "source": item["source"],
            "link": item["link"],
            "published": item.get("published", ""),
            "title_en": item["title"],
            "title_ru": translate_text(item["title"], "ru"),
            "title_ja": translate_text(item["title"], "ja"),
            "summary_en": item["summary"],
            "summary_ru": translate_text(item["summary"], "ru") if item["summary"] else "",
            "summary_ja": translate_text(item["summary"], "ja") if item["summary"] else "",
        })

    print(f"✅ Переведено новостей: {len(news)}")

    # Итоговый JSON
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "harvestable_million_fish": 32.3,
            "range_million_fish": [31.12, 59.52],
            "uw_asp_forecast_million_fish": 41.5,
            "source_url": "https://www.adfg.alaska.gov/static/applications/dcfnewsrelease/1745780946.pdf",
        },
        "harvest": harvest,
        "news": news,
        "stats": {
            "season_active": harvest["season_active"],
            "cumulative_catch": harvest["cumulative_catch"],
            "news_count": len(news),
        },
    }

    # Сохраняем
    latest_path = DATA_DIR / "latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 {latest_path}")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (HISTORY_DIR / f"{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "="*70)
    print(f"✅ ГОТОВО! Новостей: {len(news)} | Сезон: {harvest['season_active']}")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
