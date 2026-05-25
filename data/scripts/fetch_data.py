"""
Сбор ежедневных данных по вылову нерки на Аляске (сезон 2026).

Источники:
- ADF&G Bristol Bay Bluesheet — оперативные данные по вылову
- ADF&G press releases — пресс-релизы по сезону
- BBRSDA — рыночные данные
- SeafoodSource RSS — отраслевые новости
- KDLG — местные новости Bristol Bay
- Japan Customs / Tridge — японский рынок (если найдены свежие)

Запускается через GitHub Actions ежедневно в 06:00 UTC (= 09:00 МСК).
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
ADFG_BLUESHEET_PAGE = "https://www.adfg.alaska.gov/index.cfm?adfg=commercialbyareabristolbay.salmon"
ADFG_NEWS_PAGE = "https://www.adfg.alaska.gov/index.cfm?adfg=pressreleases.main"
BBRSDA_UPDATES = "https://www.bbrsda.com/updates/"

# RSS новостных источников
NEWS_FEEDS = [
    ("SeafoodSource", "https://www.seafoodsource.com/rss/news"),
    ("Undercurrent News", "https://www.undercurrentnews.com/feed/"),
    ("KDLG", "https://www.kdlg.org/feed"),
    ("Alaska Public Media", "https://alaskapublic.org/feed/"),
    ("IntraFish", "https://www.intrafish.com/rss"),
]

# Ключевые слова для фильтрации новостей (RU + EN + JA)
KEYWORDS = [
    # English
    "sockeye", "bristol bay", "alaska salmon", "red salmon",
    "salmon harvest", "salmon season", "salmon price", "salmon export",
    "adf&g", "bbrsda", "ex-vessel",
    # Russian
    "нерка", "брист", "аляск",
    # Japanese
    "ベニサケ", "紅鮭", "サケ", "鮭", "アラスカ", "ブリストル",
]

# Регексы для извлечения цифр вылова из текста
HARVEST_PATTERNS = [
    # "harvest of 41.2 million sockeye"
    re.compile(r"harvest(?:ed)?\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*million\s+sockeye", re.IGNORECASE),
    # "41.2 million fish"
    re.compile(r"(\d+(?:\.\d+)?)\s*million\s+(?:sockeye|salmon|fish)", re.IGNORECASE),
    # "cumulative catch of 12,345,678"
    re.compile(r"cumulative\s+(?:catch|harvest)\s+of\s+([\d,]+)", re.IGNORECASE),
    # "$1.30 per pound" / "$1.30/lb"
    re.compile(r"\$(\d+\.\d{2})\s*(?:per\s+pound|/lb|/pound)", re.IGNORECASE),
]

USER_AGENT = "Mozilla/5.0 (compatible; AlaskaSockeyeMonitor/1.0; +https://github.com)"
TIMEOUT = 30


# ============================================================
# Утилиты
# ============================================================

def http_get(url, **kwargs):
    """GET с таймаутом, юзер-агентом и обработкой ошибок."""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"  ⚠️  Ошибка загрузки {url}: {e}", file=sys.stderr)
        return None


def is_relevant(text):
    """Содержит ли текст ключевые слова по нерке."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def extract_numbers(text):
    """Извлечь все числовые показатели из текста."""
    if not text:
        return {}

    numbers = {}
    for pattern in HARVEST_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            key = pattern.pattern.split("\\")[0][:30]
            numbers[key] = matches[:5]  # макс 5 совпадений
    return numbers


# ============================================================
# Сборщики данных
# ============================================================

def fetch_bluesheet_links():
    """
    Найти ссылки на актуальные blue sheets на сайте ADF&G.
    Bluesheet публикуется ежедневно в сезон путины (июнь–август).
    """
    print("📋 Ищу актуальный Blue Sheet на ADF&G...")
    result = {
        "page_url": ADFG_BLUESHEET_PAGE,
        "pdf_url": None,
        "downloaded_at": None,
        "file_size_kb": None,
        "season_active": False,
    }

    response = http_get(ADFG_BLUESHEET_PAGE)
    if not response:
        return result

    soup = BeautifulSoup(response.text, "html.parser")

    # Ищем все ссылки на PDF которые содержат "blue" / "bluesheet" / "daily"
    pdf_links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True).lower()
        if href.lower().endswith(".pdf") and (
            "blue" in href.lower() or "blue" in text or "daily" in text or "bluesheet" in href.lower()
        ):
            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            pdf_links.append({"url": full_url, "text": link.get_text(strip=True)})

    if not pdf_links:
        print("  ℹ️  Blue Sheet PDF не найден (вне сезона или формат изменился)")
        return result

    # Скачиваем первый найденный (обычно самый свежий)
    pdf_url = pdf_links[0]["url"]
    print(f"  📥 Скачиваю: {pdf_url}")
    pdf_response = http_get(pdf_url)

    if pdf_response:
        pdf_path = DATA_DIR / "blue-sheet.pdf"
        pdf_path.write_bytes(pdf_response.content)
        result["pdf_url"] = pdf_url
        result["downloaded_at"] = datetime.now(timezone.utc).isoformat()
        result["file_size_kb"] = round(len(pdf_response.content) / 1024, 1)
        result["season_active"] = True
        result["all_links_found"] = pdf_links[:5]
        print(f"  ✅ Сохранён: {result['file_size_kb']} KB")

    return result


def parse_bluesheet_pdf():
    """
    Извлечь цифры из скачанного blue sheet PDF.
    Использует pdfplumber для парсинга таблиц.
    """
    pdf_path = DATA_DIR / "blue-sheet.pdf"
    if not pdf_path.exists():
        return {"parsed": False, "reason": "PDF не скачан"}

    try:
        import pdfplumber
    except ImportError:
        return {"parsed": False, "reason": "pdfplumber не установлен"}

    print("🔍 Парсю Blue Sheet PDF...")
    extracted = {
        "parsed": True,
        "districts": {},
        "totals": {},
        "raw_text_preview": "",
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                full_text += page_text + "\n"

            extracted["raw_text_preview"] = full_text[:2000]

            # Извлечь цифры по районам Bristol Bay
            districts = ["Naknek-Kvichak", "Egegik", "Ugashik", "Nushagak", "Togiak"]
            for district in districts:
                # Ищем строки вида "Naknek-Kvichak 1,234,567"
                pattern = rf"{district}[^\d]*([\d,]+)"
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    try:
                        value = int(match.group(1).replace(",", ""))
                        extracted["districts"][district] = value
                    except ValueError:
                        pass

            # Общий итог
            total_match = re.search(r"total[^\d]*([\d,]+)", full_text, re.IGNORECASE)
            if total_match:
                try:
                    extracted["totals"]["bristol_bay_cumulative"] = int(
                        total_match.group(1).replace(",", "")
                    )
                except ValueError:
                    pass

            # Извлечь все «million sockeye» упоминания
            extracted["mentions"] = extract_numbers(full_text)

            print(f"  ✅ Извлечено районов: {len(extracted['districts'])}")
    except Exception as e:
        extracted["parsed"] = False
        extracted["error"] = str(e)
        print(f"  ⚠️  Ошибка парсинга: {e}")

    return extracted


def fetch_news():
    """Собрать релевантные новости из RSS-лент."""
    print("📰 Собираю новости...")
    all_news = []

    for source_name, feed_url in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
            count_for_source = 0
            for entry in parsed.entries[:25]:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                if not is_relevant(title + " " + summary):
                    continue

                # Очистка HTML из summary
                summary_clean = BeautifulSoup(summary, "html.parser").get_text()[:400]

                # Извлечение цифр
                numbers = extract_numbers(title + " " + summary)

                all_news.append({
                    "source": source_name,
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                    "summary": summary_clean,
                    "numbers_found": numbers,
                })
                count_for_source += 1

            print(f"  {source_name}: {count_for_source} релевантных")
        except Exception as e:
            print(f"  ⚠️  {source_name}: {e}")

    # Сортировка по дате (свежие первыми)
    all_news.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_news[:30]  # топ-30


def fetch_adfg_press_releases():
    """Скрапинг пресс-релизов ADF&G."""
    print("🏛  Проверяю пресс-релизы ADF&G...")
    releases = []

    response = http_get(ADFG_NEWS_PAGE)
    if not response:
        return releases

    soup = BeautifulSoup(response.text, "html.parser")

    # ADF&G обычно использует таблицу или список ссылок
    for link in soup.find_all("a", href=True)[:100]:
        text = link.get_text(strip=True)
        href = link["href"]
        if not text or len(text) < 15:
            continue
        if is_relevant(text):
            full_url = href if href.startswith("http") else f"https://www.adfg.alaska.gov{href}"
            releases.append({"title": text, "link": full_url})
            if len(releases) >= 10:
                break

    print(f"  ✅ Найдено релизов: {len(releases)}")
    return releases


# ============================================================
# Главный pipeline
# ============================================================

def main():
    print("=" * 60)
    print(f"🐟 Alaska Sockeye Daily Update — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    bluesheet_info = fetch_bluesheet_links()
    bluesheet_data = parse_bluesheet_pdf() if bluesheet_info["pdf_url"] else {"parsed": False}
    news = fetch_news()
    press_releases = fetch_adfg_press_releases()

    # Итоговая структура данных
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_msk": datetime.now(timezone.utc).astimezone().isoformat(),
        "season": 2026,
        "forecast_2026": {
            "total_run_million_fish": 45.32,
            "range_million_fish": [31.12, 59.52],
            "source": "ADF&G 2026 Bristol Bay Sockeye Forecast",
            "source_url": "https://www.adfg.alaska.gov/static/applications/dcfnewsrelease/1745780946.pdf",
        },
        "bluesheet": bluesheet_info,
        "bluesheet_data": bluesheet_data,
        "news": news,
        "press_releases": press_releases,
        "stats": {
            "news_count": len(news),
            "press_releases_count": len(press_releases),
            "bluesheet_available": bool(bluesheet_info["pdf_url"]),
        },
    }

    # Сохраняем latest.json
    latest_path = DATA_DIR / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n💾 Сохранён: {latest_path}")

    # Архив по дате
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_path = HISTORY_DIR / f"{date_str}.json"
    archive_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"💾 Архив: {archive_path}")

    print("\n" + "=" * 60)
    print(f"✅ Готово. Новостей: {len(news)} | Релизов: {len(press_releases)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
