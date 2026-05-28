"""
Сбор данных по нерке Аляски — версия v6.0
Структурированный мониторинг как в Notion:
1. ПРИОРИТЕТ: Bluesheet ADF&G (ежедневный отчёт о вылове)
2. Остальные данные: цены, переработка, рынок Японии
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

# ШАГ 1: ПРИОРИТЕТ — Bluesheet ADF&G
BLUESHEET_URLS = [
    "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.salmon",
    "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.bbnews",
    "https://www.adfg.alaska.gov/index.cfm?adfg=newsroom.pressreleases",
]

# ШАГ 2: Остальные источники
RSS_FEEDS = [
    ("SeafoodSource", "https://www.seafoodsource.com/rss/news"),
    ("BBRSDA", "https://www.bbrsda.com/rss"),
    ("Undercurrent News", "https://www.undercurrentnews.com/feed/"),
    ("KDLG Bristol Bay", "https://www.kdlg.org/feed"),
    ("IntraFish", "https://www.intrafish.com/rss"),
]

USER_AGENT = "Mozilla/5.0 (compatible; AlaskaSockeyeMonitor/6.0)"
TIMEOUT = 25

# Районы Bristol Bay
DISTRICTS = ["Naknek-Kvichak", "Egegik", "Ugashik", "Nushagak", "Togiak"]


# ============================================================
# ШАГ 1: BLUESHEET (ПРИОРИТЕТ)
# ============================================================

def fetch_bluesheet():
    """
    Шаг 1: Мониторинг Bluesheet ADF&G — ПРИОРИТЕТ.
    Ищет свежий ежедневный отчёт о вылове в Bristol Bay.
    """
    print("\n" + "="*70)
    print("🔴 ШАГ 1: BLUESHEET ADF&G (ПРИОРИТЕТ)")
    print("="*70)
    
    bluesheet_data = {
        "available": False,
        "date": None,
        "source_url": None,
        "daily_catch_by_district": {},  # Nushagak: 12345, Egegik: 54321 и т.д.
        "cumulative_catch": None,
        "escapement": {},  # Wood: 123456, Nushagak: 234567 и т.д.
        "effort": {
            "permitted_deliveries": None,
            "boats_active": None,
        },
        "comparison": {
            "vs_forecast_2026": None,  # "78% от прогноза (45.32M)"
            "vs_2025": None,           # "41.2M в 2025"
        },
        "management_actions": [],  # extensions, closures, restrictions
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "note": "Bluesheet ещё не опубликован или вне сезона",
    }
    
    print("Ищу свежий Bluesheet в приоритетных источниках...")
    
    for url in BLUESHEET_URLS:
        print(f"\n📍 Проверяю: {url}")
        
        try:
            headers = {"User-Agent": USER_AGENT}
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Ищем "Daily Catch", "Bluesheet", "Inseason" в заголовках
            page_text = soup.get_text()
            
            if "daily" in page_text.lower() or "catch" in page_text.lower():
                print(f"  ✅ Найден отчёт о вылове")
                
                # Пытаемся извлечь дату
                date_match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", page_text)
                if date_match:
                    bluesheet_data["date"] = date_match.group(0)
                    print(f"     Дата: {bluesheet_data['date']}")
                
                # Ищем цифры вылова по районам
                for district in DISTRICTS:
                    pattern = rf"{district}[:\s]+([0-9,]+)"
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        value_str = match.group(1).replace(",", "")
                        try:
                            value = int(value_str)
                            bluesheet_data["daily_catch_by_district"][district] = value
                            print(f"     {district}: {value:,}")
                        except:
                            pass
                
                # Ищем cumulative catch (нарастающий итог)
                cumulative_match = re.search(r"cumulative[:\s]+([0-9,]+)", page_text, re.IGNORECASE)
                if cumulative_match:
                    bluesheet_data["cumulative_catch"] = int(cumulative_match.group(1).replace(",", ""))
                    print(f"     Cumulative: {bluesheet_data['cumulative_catch']:,}")
                
                bluesheet_data["available"] = True
                bluesheet_data["source_url"] = url
                bluesheet_data["note"] = "Bluesheet актуален"
                break
                
        except Exception as e:
            print(f"  ⚠️  Ошибка: {e}")
    
    if not bluesheet_data["available"]:
        print("\n⚠️  Свежий Bluesheet не найден (вне сезона или ещё не опубликован)")
    
    return bluesheet_data


# ============================================================
# ШАГ 2: ОСТАЛЬНЫЕ ДАННЫЕ
# ============================================================

def translate_text(text, target_lang):
    """Перевод через Google Translate."""
    if not text or len(text) < 5:
        return text
    try:
        text_short = text[:800] if len(text) > 800 else text
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated = translator.translate(text_short)
        time.sleep(0.3)
        return translated
    except Exception as e:
        return text


def fetch_market_data():
    """
    Шаг 2: Сбор остальных данных.
    - Производство и цены (ex-vessel, оптовые)
    - Японский рынок (импорт, цены)
    - Аналитика
    """
    print("\n" + "="*70)
    print("🟠 ШАГ 2: ОСТАЛЬНЫЕ ДАННЫЕ")
    print("="*70)
    
    market_data = {
        "alaska": {
            "production": {
                "note": "Объёмы переработки (H&G, филе, икра)",
                "items": [],
            },
            "prices": {
                "ex_vessel": None,          # ex-vessel $/lb
                "wholesale": None,          # оптовые цены
                "note": "Цены от Trident, Silver Bay, OBI и др.",
            },
            "exports": {
                "note": "Объёмы экспорта в Японию и другие страны",
                "items": [],
            },
        },
        "japan": {
            "import": {
                "volume_tons": None,        # тонны импорта нерки
                "value_jpy_million": None,  # стоимость в млн иен
                "vs_previous_year": None,   # изменение %
                "note": "Japan Customs данные",
            },
            "wholesale_market": {
                "toyosu_yen_per_kg": None,  # ¥/кг на Toyosu
                "hokkaido_salted": None,    # солёная нерка в Хоккайдо
                "note": "Оптовые цены на Toyosu и Hokkaido",
            },
            "retail_consumption": {
                "note": "Ценовые тренды, сезонные факторы (お盆, お歳暮)",
                "trends": [],
            },
        },
        "analytics": {
            "usd_jpy_rate": None,
            "logistics_notes": "Таможенные сборы, логистика",
            "forecast_notes": "Прогнозы на следующий период",
        }
    }
    
    # Собираем новости которые могут содержать эту информацию
    print("Собираю новости о ценах, производстве и японском рынке...")
    
    all_news = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:20]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or ""
                
                # Фильтруем по ключевым словам
                keywords = ["price", "ex-vessel", "production", "japan", "export", "toyosu", 
                           "цена", "производ", "японский", "экспорт", "¥"]
                
                if any(kw.lower() in (title + summary).lower() for kw in keywords):
                    all_news.append({
                        "source": source_name,
                        "title": title,
                        "summary": summary[:400],
                        "link": entry.get("link", ""),
                    })
        except:
            pass
    
    if all_news:
        print(f"  ✅ Собрано новостей: {len(all_news)}")
        
        # Извлекаем цены из текста (простой парсинг)
        for news in all_news:
            full_text = news["title"] + " " + news["summary"]
            
            # ex-vessel цена
            price_match = re.search(r"\$(\d+\.\d{2})\s*(?:/lb|per pound)", full_text, re.I)
            if price_match and not market_data["alaska"]["prices"]["ex_vessel"]:
                market_data["alaska"]["prices"]["ex_vessel"] = f"${price_match.group(1)}/lb"
            
            # Японская цена
            yen_match = re.search(r"¥([\d,]+)\s*(?:/kg|per kg)", full_text, re.I)
            if yen_match and not market_data["japan"]["wholesale_market"]["toyosu_yen_per_kg"]:
                market_data["japan"]["wholesale_market"]["toyosu_yen_per_kg"] = f"¥{yen_match.group(1)}/kg"
        
        market_data["alaska"]["production"]["items"] = all_news[:5]
    else:
        print("  ⚠️  Новостей о ценах и производстве не найдено")
    
    return market_data


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    """Главная функция."""
    print("\n" + "="*70)
    print("🐟 ALASKA SOCKEYE DAILY MONITOR v6.0")
    print("Структурированный мониторинг как в Notion")
    print(f"⏰ {datetime.now(timezone.utc).isoformat()}")
    print("="*70)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # ШАГ 1: BLUESHEET (ПРИОРИТЕТ)
    bluesheet = fetch_bluesheet()
    
    # ШАГ 2: ОСТАЛЬНЫЕ ДАННЫЕ
    market = fetch_market_data()
    
    # Формируем итоговый JSON с приоритетной структурой
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "harvestable_million_fish": 32.3,
            "range_million_fish": [31.12, 59.52],
        },
        
        # ШАГИ МОНИТОРИНГА В ПОРЯДКЕ ПРИОРИТЕТА
        "monitoring": {
            "step_1_bluesheet": bluesheet,           # ПРИОРИТЕТ
            "step_2_market_data": market,            # Остальное
        },
        
        # Статистика
        "stats": {
            "bluesheet_available": bluesheet["available"],
            "districts_with_data": len(bluesheet["daily_catch_by_district"]),
            "total_daily_catch": sum(bluesheet["daily_catch_by_district"].values()) or 0,
            "cumulative_catch": bluesheet["cumulative_catch"],
            "market_news_count": len(market["alaska"]["production"]["items"]),
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
    
    # Финальный отчёт
    print("\n" + "="*70)
    print("📊 ИТОГОВЫЙ ОТЧЁТ")
    print("="*70)
    stats = payload["stats"]
    print(f"✅ Bluesheet доступен: {stats['bluesheet_available']}")
    print(f"   Районов с данными: {stats['districts_with_data']}")
    print(f"   Вылов за день: {stats['total_daily_catch']:,} рыб")
    print(f"   Cumulative: {stats['cumulative_catch']:,} рыб" if stats['cumulative_catch'] else "   Cumulative: —")
    print(f"   Новостей о ценах/производстве: {stats['market_news_count']}")
    print("="*70)
    print("✅ ГОТОВО!")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
