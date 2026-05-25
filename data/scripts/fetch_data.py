"""
Сбор ежедневных данных по вылову нерки на Аляске (сезон 2026).
Версия 2.0 — улучшенный сбор новостей, японские источники.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

# ============================================================
# Константы
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

# URL источников
ADFG_BRISTOL_BAY = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.salmon"
ADFG_HARVEST_SUMMARY = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.salmon_harvest"
ADFG_NEWS = "https://www.adfg.alaska.gov/index.cfm?adfg=pressreleases.main"
BBRSDA_UPDATES = "https://www.bbrsda.com/updates/"

# RSS новостных источников (английские)
NEWS_FEEDS_EN = [
    ("SeafoodSource", "https://www.seafoodsource.com/rss/news"),
    ("Undercurrent News", "https://www.undercurrentnews.com/feed/"),
    ("KDLG Bristol Bay", "https://www.kdlg.org/feed"),
    ("Alaska Public Media", "https://alaskapublic.org/feed/"),
    ("IntraFish", "https://www.intrafish.com/rss"),
    ("National Fisherman", "https://www.nationalfisherman.com/rss"),
    ("Alaska Beacon", "https://alaskabeacon.com/feed/"),
]

# Японские источники (если есть RSS)
NEWS_FEEDS_JA = [
    ("みなと新聞 (Minato Shimbun)", "https://www.minato-yamaguchi.co.jp/rss/rss.xml"),
]

# Ключевые слова для фильтрации (расширенный список)
KEYWORDS_EN = [
    "sockeye", "bristol bay", "alaska salmon", "red salmon",
    "salmon harvest", "salmon season", "salmon price", "salmon export",
    "adf&g", "bbrsda", "ex-vessel", "salmon forecast", "salmon run",
    "nushagak", "kvichak", "egegik", "ugashik", "togiak",
    "chinook", "king salmon", "chum salmon",
]

KEYWORDS_RU = ["нерка", "брист", "аляск", "лосось", "путина"]

KEYWORDS_JA = ["ベニサケ", "紅鮭", "サケ", "鮭", "アラスカ", "ブリストル", "漁獲"]

ALL_KEYWORDS = KEYWORDS_EN + KEYWORDS_RU + KEYWORDS_JA

USER_AGENT = "Mozilla/5.0 (compatible; AlaskaSockeyeMonitor/2.0)"
TIMEOUT = 30


# ============================================================
# Утилиты
# ============================================================

def http_get(url, **kwargs):
    """GET с обработкой ошибок."""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"  ⚠️  Ошибка {url}: {e}", file=sys.stderr)
        return None


def is_relevant(text):
    """Проверка релевантности по ключевым словам."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in ALL_KEYWORDS)


def extract_numbers(text):
    """Извлечение цифр из текста."""
    if not text:
        return []
    
    numbers = []
    
    # Вылов в миллионах
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*million\s+(?:sockeye|salmon|fish)", text, re.I):
        numbers.append(f"{match.group(1)}M fish")
    
    # Цены за фунт
    for match in re.finditer(r"\$(\d+\.\d{2})\s*(?:per\s+pound|/lb)", text, re.I):
        numbers.append(f"${match.group(1)}/lb")
    
    # Общая стоимость
    for match in re.finditer(r"\$(\d+(?:\.\d+)?)\s*million", text, re.I):
        numbers.append(f"${match.group(1)}M")
    
    return numbers[:5]  # макс 5


# ============================================================
# Сбор новостей
# ============================================================

def fetch_news():
    """Собрать новости из RSS."""
    print("📰 Собираю новости...")
    all_news = []
    
    all_feeds = NEWS_FEEDS_EN + NEWS_FEEDS_JA
    
    for source_name, feed_url in all_feeds:
        try:
            parsed = feedparser.parse(feed_url)
            count = 0
            
            for entry in parsed.entries[:30]:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                
                if not is_relevant(title + " " + summary):
                    continue
                
                # Очистка HTML
                summary_clean = BeautifulSoup(summary, "html.parser").get_text()[:500]
                
                # Извлечение цифр
                numbers = extract_numbers(title + " " + summary_clean)
                
                all_news.append({
                    "source": source_name,
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                    "summary": summary_clean,
                    "numbers_found": numbers,
                })
                count += 1
            
            if count > 0:
                print(f"  ✅ {source_name}: {count} новостей")
        except Exception as e:
            print(f"  ⚠️  {source_name}: {e}")
    
    # Сортировка по дате
    all_news.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_news[:40]


def fetch_adfg_press():
    """Скрапинг пресс-релизов ADF&G."""
    print("🏛  Проверяю пресс-релизы ADF&G...")
    releases = []
    
    response = http_get(ADFG_NEWS)
    if not response:
        return releases
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    for link in soup.find_all("a", href=True)[:100]:
        text = link.get_text(strip=True)
        if len(text) < 10:
            continue
        if is_relevant(text):
            href = link["href"]
            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            releases.append({"title": text, "link": full_url})
            if len(releases) >= 15:
                break
    
    print(f"  ✅ Найдено: {len(releases)}")
    return releases


# ============================================================
# Blue Sheet
# ============================================================

def fetch_bluesheet():
    """Попытка скачать Blue Sheet."""
    print("📋 Ищу Blue Sheet...")
    
    result = {
        "season_active": False,
        "pdf_url": None,
        "note": "Межсезонье. Blue Sheet публикуется с ~22 июня по август.",
    }
    
    # Проверяем основную страницу Bristol Bay
    response = http_get(ADFG_BRISTOL_BAY)
    if not response:
        return result
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Ищем PDF-ссылки
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True).lower()
        
        if href.lower().endswith(".pdf") and ("outlook" in text or "bluesheet" in href.lower() or "2026" in text):
            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            
            # Скачиваем
            pdf_response = http_get(full_url)
            if pdf_response:
                pdf_path = DATA_DIR / "blue-sheet.pdf"
                pdf_path.write_bytes(pdf_response.content)
                
                result["season_active"] = True
                result["pdf_url"] = full_url
                result["file_size_kb"] = round(len(pdf_response.content) / 1024, 1)
                result["note"] = "Blue Sheet загружен"
                print(f"  ✅ Скачан: {result['file_size_kb']} KB")
                return result
    
    print("  ℹ️  Blue Sheet не найден (вне сезона)")
    return result


# ============================================================
# Главный pipeline
# ============================================================

def main():
    print("=" * 70)
    print(f"🐟 Alaska Sockeye Daily Update v2.0 — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    news = fetch_news()
    press_releases = fetch_adfg_press()
    bluesheet = fetch_bluesheet()
    
    # Итоговая структура
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_msk": datetime.now(timezone.utc).astimezone().isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "range_million_fish": [31.12, 59.52],
            "source": "ADF&G 2026 Bristol Bay Sockeye Forecast (Nov 2025)",
            "source_url": "https://www.adfg.alaska.gov/static/applications/dcfnewsrelease/1745780946.pdf",
            "notes": "Прогноз на 26% ниже среднего за последние 10 лет (61M), но на 21% выше долгосрочного среднего (37.4M)"
        },
        "bluesheet": bluesheet,
        "news": news,
        "press_releases": press_releases,
        "stats": {
            "news_count": len(news),
            "press_releases_count": len(press_releases),
            "bluesheet_available": bluesheet["season_active"],
        },
    }
    
    # Сохраняем latest.json
    latest_path = DATA_DIR / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n💾 Сохранён: {latest_path}")
    
    # Архив
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_path = HISTORY_DIR / f"{date_str}.json"
    archive_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"💾 Архив: {archive_path}")
    
    print("\n" + "=" * 70)
    print(f"✅ Готово. Новостей: {len(news)} | Релизов: {len(press_releases)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
   
