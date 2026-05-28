"""
Сбор данных по нерке Аляски — версия v7.0 ФИНАЛЬНАЯ
- Парсит реальные таблицы с harvestsummary (Total Run + Rivers + Delivery)
- Новости через RSS без жёсткой фильтрации
- Перевод на RU и JA
"""

import json
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    import feedparser
    import requests
    from bs4 import BeautifulSoup
    from deep_translator import GoogleTranslator
    print("✅ Все библиотеки импортированы")
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

# ТОЧНЫЙ URL с таблицами
HARVEST_SUMMARY_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.harvestsummary"
ADFG_BB_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.salmon"

RSS_FEEDS = [
    ("SeafoodSource", "https://www.seafoodsource.com/rss/news"),
    ("Undercurrent News", "https://www.undercurrentnews.com/feed/"),
    ("KDLG Bristol Bay", "https://www.kdlg.org/feed"),
    ("IntraFish", "https://www.intrafish.com/rss"),
    ("Alaska Beacon", "https://alaskabeacon.com/feed/"),
]

KEYWORDS = [
    "sockeye", "bristol bay", "alaska salmon", "red salmon",
    "salmon harvest", "salmon season", "salmon price", "salmon forecast",
    "adf&g", "bbrsda", "ex-vessel", "chinook", "king salmon",
    "нерка", "лосось", "аляск",
]

USER_AGENT = "Mozilla/5.0 (compatible; AlaskaSockeyeBot/7.0)"
TIMEOUT = 25


def http_get(url):
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  ⚠️  {url}: {e}")
        return None


def translate_text(text, lang):
    if not text or len(text) < 5:
        return text
    try:
        t = GoogleTranslator(source='auto', target=lang)
        result = t.translate(text[:800])
        time.sleep(0.3)
        return result
    except:
        return text


def fetch_harvest_tables():
    """Парсим РЕАЛЬНЫЕ таблицы с harvestsummary."""
    print("\n" + "="*70)
    print("📋 ПАРСЮ ТАБЛИЦЫ ВЫЛОВА (harvestsummary)")
    print("="*70)

    result = {
        "url": HARVEST_SUMMARY_URL,
        "run_date": None,
        "season_active": False,
        "total_run_summary": {},
        "river_estimates": {},
        "sockeye_per_delivery": {},
        "note": "Данные недоступны или вне сезона",
    }

    resp = http_get(HARVEST_SUMMARY_URL)
    if not resp:
        return result

    soup = BeautifulSoup(resp.text, "html.parser")

    # Дата отчёта
    page_text = soup.get_text()
    date_match = re.search(r"Run Date[:\s]+(\d{2}-\d{2}-\d{4})", page_text)
    if date_match:
        result["run_date"] = date_match.group(1)
        print(f"  📅 Дата отчёта: {result['run_date']}")

    tables = soup.find_all("table")
    print(f"  📊 Таблиц найдено: {len(tables)}")

    for table in tables:
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        rows = table.find_all("tr")

        if not headers or not rows:
            continue

        # === Таблица 1: Total Run Summary ===
        if "Catch Daily" in headers and "Catch Cumulative" in headers:
            print("  ✅ Найдена: Total Run Summary")
            for row in rows[1:]:  # пропускаем заголовок
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    district = cells[0]
                    data = {}
                    for i, h in enumerate(headers):
                        if i < len(cells):
                            try:
                                data[h] = int(cells[i].replace(",", "")) if cells[i].replace(",", "").isdigit() else cells[i]
                            except:
                                data[h] = cells[i]
                    if district and district != "Totals:":
                        result["total_run_summary"][district] = data
                    elif district == "Totals:":
                        result["total_run_summary"]["TOTALS"] = data

            # Проверяем есть ли ненулевые данные
            for d, v in result["total_run_summary"].items():
                catch = v.get("Catch Cumulative", 0)
                if isinstance(catch, int) and catch > 0:
                    result["season_active"] = True
                    result["note"] = f"Bluesheet активен (дата: {result['run_date']})"
                    break

        # === Таблица 2: Individual River Estimates ===
        elif "Escapement Daily" in headers and "Escapement Cumulative" in headers and "In-River Estimate" in headers:
            print("  ✅ Найдена: Individual River Estimates")
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    river = cells[0]
                    if river:
                        data = {}
                        for i, h in enumerate(headers):
                            if i < len(cells):
                                try:
                                    data[h] = int(cells[i].replace(",", "")) if cells[i].replace(",", "").replace("-", "").isdigit() else cells[i]
                                except:
                                    data[h] = cells[i]
                        result["river_estimates"][river] = data

        # === Таблица 3: Sockeye per Drift Delivery ===
        elif "Sockeye per Delivery" in headers:
            print("  ✅ Найдена: Sockeye per Delivery")
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    district = cells[0]
                    delivery = cells[1] if len(cells) > 1 else "0"
                    if district:
                        try:
                            result["sockeye_per_delivery"][district] = int(delivery.replace(",", ""))
                        except:
                            result["sockeye_per_delivery"][district] = delivery

    # Cumulative totals для удобного отображения
    totals = result["total_run_summary"].get("TOTALS", {})
    result["cumulative_catch"] = totals.get("Catch Cumulative", 0)
    result["cumulative_escapement"] = totals.get("Escapement Cumulative", 0)

    print(f"  📈 Cumulative catch: {result['cumulative_catch']:,}")
    print(f"  📈 Cumulative escapement: {result['cumulative_escapement']:,}")
    print(f"  🟢 Сезон активен: {result['season_active']}")

    return result


def fetch_news():
    """Собрать новости по нерке с переводом."""
    print("\n" + "="*70)
    print("📰 СОБИРАЮ НОВОСТИ")
    print("="*70)

    all_news = []

    for source_name, feed_url in RSS_FEEDS:
        print(f"\n🔍 {source_name}...")
        try:
            parsed = feedparser.parse(feed_url)
            count = 0
            for entry in parsed.entries[:25]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or ""
                if not any(kw.lower() in (title + summary).lower() for kw in KEYWORDS):
                    continue

                try:
                    summary_clean = BeautifulSoup(summary, "html.parser").get_text()[:500]
                except:
                    summary_clean = summary[:500]

                print(f"  ✅ {title[:70]}")
                title_ru = translate_text(title, 'ru')
                title_ja = translate_text(title, 'ja')
                summary_ru = translate_text(summary_clean, 'ru')
                summary_ja = translate_text(summary_clean, 'ja')

                all_news.append({
                    "source": source_name,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                    "title_en": title,
                    "title_ru": title_ru,
                    "title_ja": title_ja,
                    "summary_en": summary_clean,
                    "summary_ru": summary_ru,
                    "summary_ja": summary_ja,
                })
                count += 1
                if count >= 8:
                    break

            print(f"  → {count} новостей")
        except Exception as e:
            print(f"  ❌ {e}")

    print(f"\n📊 Всего: {len(all_news)}")
    return all_news


def fetch_adfg_outlook():
    """Свежий 2026 Outlook с ADF&G."""
    print("\n" + "="*70)
    print("📄 OUTLOOK 2026 ADF&G")
    print("="*70)

    resp = http_get(ADFG_BB_URL)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        href = link["href"]
        if len(text) < 10:
            continue
        if any(kw in text.lower() for kw in ["2026", "sockeye", "salmon", "outlook", "summary", "forecast"]):
            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            items.append({"title": text, "link": full_url})
            print(f"  ✅ {text[:80]}")
            if len(items) >= 8:
                break

    return items


def main():
    print("\n" + "="*70)
    print("🐟 ALASKA SOCKEYE DAILY MONITOR v7.0")
    print(f"⏰ {datetime.now(timezone.utc).isoformat()}")
    print("="*70)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    harvest = fetch_harvest_tables()
    news = fetch_news()
    outlook_links = fetch_adfg_outlook()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "harvestable_million_fish": 32.3,
            "range_million_fish": [31.12, 59.52],
            "source_url": "https://www.adfg.alaska.gov/static/applications/dcfnewsrelease/1745780946.pdf",
        },
        "harvest": harvest,
        "news": news,
        "adfg_links": outlook_links,
        "stats": {
            "season_active": harvest["season_active"],
            "cumulative_catch": harvest["cumulative_catch"],
            "cumulative_escapement": harvest["cumulative_escapement"],
            "districts": len(harvest["total_run_summary"]),
            "rivers": len(harvest["river_estimates"]),
            "news_count": len(news),
        },
    }

    latest_path = DATA_DIR / "latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 Сохранён: {latest_path}")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_path = HISTORY_DIR / f"{date_str}.json"
    archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 Архив: {archive_path}")

    print("\n" + "="*70)
    s = payload["stats"]
    print(f"✅ ГОТОВО!")
    print(f"   Сезон активен: {s['season_active']}")
    print(f"   Cumulative catch: {s['cumulative_catch']:,}")
    print(f"   Новостей: {s['news_count']}")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
