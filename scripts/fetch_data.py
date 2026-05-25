"""
Сбор данных по нерке Аляски — финальная версия v4.0
- Автоматический перевод новостей на русский и японский
- Скачивание Blue Sheet всей страницы как PDF
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import feedparser
    import requests
    from bs4 import BeautifulSoup
    from deep_translator import GoogleTranslator
    print("✅ Все библиотеки импортированы успешно")
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("💡 Установите недостающие библиотеки:")
    print("   pip install deep-translator --break-system-packages")
    sys.exit(1)

# ============================================================
# Константы
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

# Blue Sheet URL
BLUE_SHEET_URL = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyfisherysalmon.bluesheet"

# RSS-источники (только английские — будем переводить)
RSS_FEEDS = [
    ("SeafoodSource", "https://www.seafoodsource.com/rss/news"),
    ("Undercurrent News", "https://www.undercurrentnews.com/feed/"),
    ("IntraFish", "https://www.intrafish.com/rss"),
    ("National Fisherman", "https://www.nationalfisherman.com/rss"),
    ("KDLG Bristol Bay", "https://www.kdlg.org/feed"),
    ("Alaska Beacon", "https://alaskabeacon.com/feed/"),
]

# Ключевые слова для фильтрации
KEYWORDS = [
    "sockeye", "bristol bay", "alaska salmon", "red salmon",
    "salmon harvest", "salmon season", "salmon price", "salmon forecast",
    "adf&g", "bbrsda", "ex-vessel", "chinook", "king salmon",
]

USER_AGENT = "Mozilla/5.0 (compatible; AlaskaSockeyeBot/4.0)"
TIMEOUT = 25


# ============================================================
# Функции
# ============================================================

def http_get(url):
    """HTTP GET с обработкой ошибок."""
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except Exception as e:
        print(f"  ⚠️  Ошибка {url}: {type(e).__name__}")
        return None


def is_relevant(text):
    """Проверка релевантности."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)


def translate_text(text, target_lang):
    """
    Перевод текста через Google Translate (бесплатно).
    target_lang: 'ru' или 'ja'
    """
    if not text or len(text) < 5:
        return text
    
    try:
        # Ограничиваем длину (Google Translate имеет лимит)
        text_short = text[:1000] if len(text) > 1000 else text
        
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated = translator.translate(text_short)
        
        # Задержка чтобы не словить rate limit
        time.sleep(0.5)
        
        return translated
    except Exception as e:
        print(f"  ⚠️  Ошибка перевода на {target_lang}: {e}")
        return text  # возвращаем оригинал если перевод не удался


def fetch_news():
    """Собрать новости и перевести на RU и JA."""
    print("\n" + "="*70)
    print("📰 СОБИРАЮ И ПЕРЕВОЖУ НОВОСТИ")
    print("="*70)
    
    all_news = []
    
    for source_name, feed_url in RSS_FEEDS:
        print(f"\n🔍 {source_name}...")
        
        try:
            parsed = feedparser.parse(feed_url)
            
            if not parsed.entries:
                print(f"  ⚠️  Лента пустая")
                continue
            
            count = 0
            for entry in parsed.entries[:30]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
                
                if not is_relevant(title + " " + summary):
                    continue
                
                # Очистка HTML
                try:
                    summary_clean = BeautifulSoup(summary, "html.parser").get_text()[:500]
                except:
                    summary_clean = summary[:500]
                
                print(f"  ✅ {title[:70]}")
                print(f"     🔄 Перевожу на русский...")
                title_ru = translate_text(title, 'ru')
                summary_ru = translate_text(summary_clean, 'ru')
                
                print(f"     🔄 Перевожу на японский...")
                title_ja = translate_text(title, 'ja')
                summary_ja = translate_text(summary_clean, 'ja')
                
                all_news.append({
                    "source": source_name,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                    "title_en": title,
                    "summary_en": summary_clean,
                    "title_ru": title_ru,
                    "summary_ru": summary_ru,
                    "title_ja": title_ja,
                    "summary_ja": summary_ja,
                })
                count += 1
                
                if count >= 10:  # Лимит 10 новостей на источник
                    break
            
            print(f"  ✅ Собрано и переведено: {count}")
            
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
    
    print(f"\n📊 ВСЕГО: {len(all_news)} новостей")
    return all_news


def fetch_bluesheet_as_pdf():
    """
    Скачать Blue Sheet страницу и сохранить как PDF.
    Используем простой метод через wkhtmltopdf или сохранение HTML.
    """
    print("\n" + "="*70)
    print("📋 СКАЧИВАЮ BLUE SHEET")
    print("="*70)
    
    result = {
        "url": BLUE_SHEET_URL,
        "available": False,
        "note": "Межсезонье или ошибка загрузки",
    }
    
    print(f"URL: {BLUE_SHEET_URL}")
    
    response = http_get(BLUE_SHEET_URL)
    if not response:
        return result
    
    try:
        # Сохраняем HTML-версию
        html_path = DATA_DIR / "blue-sheet.html"
        html_path.write_text(response.text, encoding='utf-8')
        print(f"  ✅ HTML сохранён: {html_path}")
        
        # Пытаемся конвертировать в PDF через weasyprint
        try:
            from weasyprint import HTML
            
            pdf_path = DATA_DIR / "blue-sheet.pdf"
            HTML(string=response.text, base_url=BLUE_SHEET_URL).write_pdf(pdf_path)
            
            result["available"] = True
            result["note"] = f"Blue Sheet сохранён как PDF ({pdf_path.stat().st_size // 1024} KB)"
            result["file_size_kb"] = round(pdf_path.stat().st_size / 1024, 1)
            print(f"  ✅ PDF создан: {result['file_size_kb']} KB")
            
        except ImportError:
            # Если weasyprint не установлен — сохраняем только HTML
            print("  ⚠️  weasyprint не установлен, сохраняю только HTML")
            result["available"] = True
            result["note"] = "Blue Sheet сохранён как HTML (установите weasyprint для PDF)"
        
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
    
    return result


def main():
    """Главная функция."""
    print("\n" + "="*70)
    print("🐟 ALASKA SOCKEYE DAILY UPDATE v4.0")
    print(f"⏰ {datetime.now(timezone.utc).isoformat()}")
    print("="*70)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Собираем данные
    news = fetch_news()
    bluesheet = fetch_bluesheet_as_pdf()
    
    # Формируем JSON
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "range_million_fish": [31.12, 59.52],
            "source": "ADF&G 2026 Bristol Bay Sockeye Forecast",
        },
        "bluesheet": bluesheet,
        "news": news,
        "stats": {
            "news_count": len(news),
            "bluesheet_available": bluesheet["available"],
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
    print(f"✅ ГОТОВО! Новостей: {len(news)}")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
