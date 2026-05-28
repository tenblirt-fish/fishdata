"""
Сбор данных по нерке Аляски — версия v5.0
- Парсинг таблицы Blue Sheet (вылов по районам)
- Сбор и перевод свежих новостей по вылову
- Мониторинг ex-vessel цен, прогнозов, новостей сезона
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

# ============================================================
# Константы
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

BLUE_SHEET_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyfisherysalmon.bluesheet"
ADFG_NEWS = "https://www.adfg.alaska.gov/index.cfm?adfg=pressreleases.main"

# RSS источники (только английские)
RSS_FEEDS = [
    ("SeafoodSource", "https://www.seafoodsource.com/rss/news"),
    ("BBRSDA", "https://www.bbrsda.com/rss"),
    ("Undercurrent News", "https://www.undercurrentnews.com/feed/"),
    ("KDLG Bristol Bay", "https://www.kdlg.org/feed"),
    ("IntraFish", "https://www.intrafish.com/rss"),
    ("Alaska Beacon", "https://alaskabeacon.com/feed/"),
]

# Ключевые слова мониторинга (как в Notion скиле)
KEYWORDS_HARVEST = ["sockeye", "bristol bay", "harvest", "catch", "вылов"]
KEYWORDS_PRICE = ["ex-vessel", "price", "per pound", "цена", "$/lb"]
KEYWORDS_FORECAST = ["forecast", "projection", "prediction", "прогноз"]
KEYWORDS_SEASON = ["season", "opening", "closing", "summary", "сезон"]

USER_AGENT = "Mozilla/5.0 (compatible; AlaskaSockeyeMonitor/5.0)"
TIMEOUT = 25

# Районы Bristol Bay для парсинга
DISTRICTS = {
    "Naknek-Kvichak": None,
    "Egegik": None,
    "Ugashik": None,
    "Nushagak": None,
    "Togiak": None,
}


# ============================================================
# Функции парсинга Blue Sheet
# ============================================================

def fetch_bluesheet_html():
    """Скачать HTML Blue Sheet страницы."""
    print("\n" + "="*70)
    print("📋 ПАРСЮ BLUE SHEET (таблица вылова)")
    print("="*70)
    
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(BLUE_SHEET_URL, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"  ⚠️  Ошибка загрузки: {e}")
        return None


def parse_bluesheet_table(html):
    """
    Парсить таблицу вылова из HTML Blue Sheet.
    Ищет таблицы с цифрами вылова по районам.
    """
    if not html:
        return DISTRICTS.copy()
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Ищем все таблицы на странице
        tables = soup.find_all("table")
        print(f"  📊 Найдено таблиц: {len(tables)}")
        
        districts_found = {}
        
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                row_text = " ".join([cell.get_text(strip=True) for cell in cells])
                
                # Ищем названия районов в строках
                for district_name in DISTRICTS.keys():
                    if district_name.lower() in row_text.lower():
                        # Ищем цифры в этой строке или соседних
                        numbers = re.findall(r"[\d,]+", row_text)
                        if numbers:
                            # Берём первую найденную цифру
                            value_str = numbers[0].replace(",", "")
                            try:
                                value = int(value_str)
                                districts_found[district_name] = value
                                print(f"  ✅ {district_name}: {value:,} рыб")
                            except:
                                pass
        
        if not districts_found:
            print("  ⚠️  Таблица вылова не найдена (может быть вне сезона)")
            return DISTRICTS.copy()
        
        # Заполняем результат
        result = DISTRICTS.copy()
        result.update(districts_found)
        return result
        
    except Exception as e:
        print(f"  ❌ Ошибка парсинга: {e}")
        return DISTRICTS.copy()


# ============================================================
# Функции сбора новостей
# ============================================================

def translate_text(text, target_lang):
    """Перевод через Google Translate."""
    if not text or len(text) < 5:
        return text
    
    try:
        text_short = text[:1000] if len(text) > 1000 else text
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated = translator.translate(text_short)
        time.sleep(0.5)
        return translated
    except Exception as e:
        print(f"  ⚠️  Ошибка перевода: {e}")
        return text


def is_relevant_news(text, category):
    """
    Классифицировать новость по категориям.
    category: 'harvest', 'price', 'forecast', 'season'
    """
    text_lower = text.lower()
    
    keywords_map = {
        "harvest": KEYWORDS_HARVEST,
        "price": KEYWORDS_PRICE,
        "forecast": KEYWORDS_FORECAST,
        "season": KEYWORDS_SEASON,
    }
    
    keywords = keywords_map.get(category, KEYWORDS_HARVEST)
    return any(kw.lower() in text_lower for kw in keywords)


def fetch_news_by_category():
    """Собрать новости по категориям (как в Notion скиле)."""
    print("\n" + "="*70)
    print("📰 СОБИРАЮ И ПЕРЕНОШУ НОВОСТИ (по категориям)")
    print("="*70)
    
    categories = {
        "harvest": [],      # Вылов, улов
        "price": [],        # Ex-vessel цены
        "forecast": [],     # Прогнозы
        "season": [],       # Новости сезона
    }
    
    for source_name, feed_url in RSS_FEEDS:
        print(f"\n🔍 {source_name}...")
        
        try:
            parsed = feedparser.parse(feed_url)
            
            if not parsed.entries:
                print(f"  ⚠️  Лента пустая")
                continue
            
            for entry in parsed.entries[:30]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
                link = entry.get("link", "")
                published = entry.get("published", "") or entry.get("updated", "")
                
                if not title:
                    continue
                
                # Очистка HTML
                try:
                    summary_clean = BeautifulSoup(summary, "html.parser").get_text()[:600]
                except:
                    summary_clean = summary[:600]
                
                full_text = title + " " + summary_clean
                
                # Классифицируем по категориям
                for category in categories.keys():
                    if is_relevant_news(full_text, category):
                        print(f"  ✅ [{category.upper()}] {title[:70]}")
                        
                        # Переводим
                        title_ru = translate_text(title, 'ru')
                        title_ja = translate_text(title, 'ja')
                        summary_ru = translate_text(summary_clean, 'ru')
                        summary_ja = translate_text(summary_clean, 'ja')
                        
                        news_item = {
                            "source": source_name,
                            "category": category,
                            "link": link,
                            "published": published,
                            "title_en": title,
                            "summary_en": summary_clean,
                            "title_ru": title_ru,
                            "summary_ru": summary_ru,
                            "title_ja": title_ja,
                            "summary_ja": summary_ja,
                        }
                        
                        categories[category].append(news_item)
                        break  # Одна новость — одна категория
                        
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
    
    # Статистика
    total = sum(len(v) for v in categories.values())
    print(f"\n📊 ИТОГО новостей: {total}")
    for cat, news in categories.items():
        print(f"   {cat}: {len(news)}")
    
    return categories


def fetch_press_releases():
    """Пресс-релизы ADF&G."""
    print("\n" + "="*70)
    print("🏛  ПРЕСС-РЕЛИЗЫ ADF&G")
    print("="*70)
    
    releases = []
    
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(ADFG_NEWS, headers=headers, timeout=TIMEOUT)
        soup = BeautifulSoup(response.text, "html.parser")
        
        for link in soup.find_all("a", href=True)[:50]:
            text = link.get_text(strip=True)
            if len(text) < 15 or not any(kw in text.lower() for kw in ["sockeye", "salmon", "bristol", "нерка"]):
                continue
            
            href = link["href"]
            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            
            releases.append({
                "title": text,
                "link": full_url,
                "title_ru": translate_text(text, 'ru'),
                "title_ja": translate_text(text, 'ja'),
            })
            
            if len(releases) >= 10:
                break
        
        print(f"  ✅ Найдено: {len(releases)}")
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
    
    return releases


# ============================================================
# Главная функция
# ============================================================

def main():
    """Главная функция."""
    print("\n" + "="*70)
    print("🐟 ALASKA SOCKEYE DAILY MONITOR v5.0")
    print(f"⏰ {datetime.now(timezone.utc).isoformat()}")
    print("="*70)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Парсим Blue Sheet
    html = fetch_bluesheet_html()
    districts = parse_bluesheet_table(html)
    
    # Собираем новости
    news_by_category = fetch_news_by_category()
    press_releases = fetch_press_releases()
    
    # Формируем итоговый JSON
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "range_million_fish": [31.12, 59.52],
            "source": "ADF&G 2026 Bristol Bay Sockeye Forecast",
        },
        # Таблица вылова по районам
        "harvest_by_district": districts,
        # Новости по категориям (как в Notion)
        "news": {
            "harvest": news_by_category.get("harvest", []),      # Вылов
            "price": news_by_category.get("price", []),          # Ex-vessel цены
            "forecast": news_by_category.get("forecast", []),    # Прогнозы
            "season": news_by_category.get("season", []),        # Новости сезона
        },
        "press_releases": press_releases,
        # Статистика
        "stats": {
            "districts_available": sum(1 for v in districts.values() if v is not None),
            "total_harvest": sum(v for v in districts.values() if v is not None),
            "news_harvest": len(news_by_category.get("harvest", [])),
            "news_price": len(news_by_category.get("price", [])),
            "news_forecast": len(news_by_category.get("forecast", [])),
            "news_season": len(news_by_category.get("season", [])),
            "press_releases": len(press_releases),
        },
    }
    
    # Сохраняем
    print("\n" + "="*70)
    print("💾 СОХРАНЯЮ")
    print("="*70)
    
    latest_path = DATA_DIR / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ {latest_path}")
    
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_path = HISTORY_DIR / f"{date_str}.json"
    archive_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ {archive_path}")
    
    print("\n" + "="*70)
    stats = payload["stats"]
    print(f"✅ ГОТОВО!")
    print(f"   Районов: {stats['districts_available']}")
    print(f"   Вылов: {stats['total_harvest']:,} рыб")
    print(f"   Новостей (вылов/цена/прогноз/сезон): {stats['news_harvest']}/{stats['news_price']}/{stats['news_forecast']}/{stats['news_season']}")
    print(f"   Пресс-релизов: {stats['press_releases']}")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
