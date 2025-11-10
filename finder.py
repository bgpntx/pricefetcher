#!/usr/bin/env python3
"""
price_watcher.py
Перевіряє список URL з items.json, витягує ціну і шле Telegram, якщо price <= target_price.
Стан зберігається у state.json, щоб уникнути спаму.
Вимоги: requests, beautifulsoup4
"""

import os, sys, json, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# ---------- Налаштування ----------
ITEMS_FILE = "items.json"
STATE_FILE = "state.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  # краще ставити змінну оточення
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")          # або встановити тут
WORKERS = 6
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
REQUEST_TIMEOUT = 20
# Мінімальний інтервал (с) між запитами до одного хоста (проста пауза в коді або використовуй throttling)
REQUEST_DELAY = 1.0

# ---------- HTTP session ----------
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "uk,ru;q=0.8,en;q=0.7"})

# ---------- Утиліти ----------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        print("Error loading", path, e)
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- Telegram ----------
def send_telegram(msg, token=None, chat_id=None):
    token = token or TELEGRAM_TOKEN
    chat_id = chat_id or CHAT_ID
    if not token or not chat_id:
        print("[Telegram] Missing token or chat_id; skipping send.")
        return False, "no-token-or-chat"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = session.post(url, data={"chat_id": str(chat_id), "text": msg}, timeout=10)
        return (r.status_code == 200), r.text
    except Exception as e:
        return False, str(e)

# ---------- Парсинг ціни ----------
def extract_price_from_jsonld(html):
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except Exception:
            continue
        # може бути об'єкт або список
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            offers = node.get("offers")
            if offers:
                off_list = offers if isinstance(offers, list) else [offers]
                for off in off_list:
                    price = off.get("price")
                    if price:
                        ps = str(price).replace("\u202f","").replace("\xa0","").replace(" ", "")
                        if ps.replace(".", "", 1).isdigit():
                            return float(ps)
            # fallback: node["price"]
            price = node.get("price")
            if price:
                ps = str(price).replace("\u202f","").replace("\xa0","").replace(" ", "")
                if ps.replace(".", "", 1).isdigit():
                    return float(ps)
    return None

def extract_price_fallback(html):
    # Створюємо 'soup' один раз
    soup = BeautifulSoup(html, "html.parser")

    # --- Нова логіка (пріоритетна) ---
    # Шукаємо будь-який тег з атрибутом data-price (як на appleroom.ua)
    price_tag = soup.find(attrs={"data-price": True})
    if price_tag:
        price_str = price_tag.get("data-price")
        # Перевіряємо, чи це справді число
        if price_str and price_str.replace(".", "", 1).isdigit():
            try:
                return float(price_str)
            except ValueError:
                pass # ігноруємо і переходимо до старої логіки

    # --- Стара логіка (fallback 1) ---
    # шукаємо число перед символом ₴ у видимому тексті
    txt = soup.get_text() # Беремо чистий текст зі сторінки
    txt = txt.replace("\u202f","").replace("\xa0"," ")
    
    m = re.search(r'(\d{1,3}(?:[ \d]{0,6}))\s*₴', txt)
    if m:
        val = m.group(1).replace(" ", "")
        if val.isdigit():
            return float(val)
            
    # --- Стара логіка (fallback 2) ---
    # інші можливі місця (шукаємо в усьому HTML, бо це може бути JS/JSON)
    m = re.search(r'"(?:price|currentPrice)"\s*:\s*"?(\d{1,6})"?', html)
    if m:
        return float(m.group(1))
    return None

def find_first_product_url_from_search(search_html):
    soup = BeautifulSoup(search_html, "html.parser")
    # шукаємо пріоритетні лінки /product/
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/product/") or "/product/" in href:
            return urljoin("https://silpo.ua", href)
    return None

def get_price_for_url(url):
    """
    Підтримує як сторінки товару (product), так і сторінки пошуку (search).
    Для search - знаходимо перший товар та парсимо його сторінку.
    Повертає (price_float_or_None, used_url_or_None, error_or_None)
    """
    try:
        time.sleep(REQUEST_DELAY)
        r = session.get(url, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        return None, None, f"HTTP error: {e}"
    if r.status_code != 200:
        return None, None, f"HTTP status {r.status_code}"

    html = r.text
    # Якщо це пошук (має /search? або параметри find=), пробуємо витягти перший продукт
    if "/search" in url or "find=" in url:
        prod = find_first_product_url_from_search(html)
        if not prod:
            return None, None, "no-product-found-in-search"
        # забираємо сторінку продукту
        try:
            time.sleep(REQUEST_DELAY)
            r2 = session.get(prod, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            return None, prod, f"prod HTTP error: {e}"
        if r2.status_code != 200:
            return None, prod, f"prod HTTP status {r2.status_code}"
        price = extract_price_from_jsonld(r2.text) or extract_price_fallback(r2.text)
        return price, prod, None

    # Інакше — безпосередня сторінка товару
    price = extract_price_from_jsonld(html) or extract_price_fallback(html)
    return price, url, None

# ---------- Основна логіка ----------
def process_item(item, state, token=None, chat_id=None):
    name = item.get("name") or item.get("url")
    url = item["url"]
    target = float(item.get("target_price", 0))
    price, used_url, err = get_price_for_url(url)
    now = int(time.time())

    result = {
        "name": name,
        "url": url,
        "checked_at": now,
        "price": price,
        "used_url": used_url,
        "error": err,
        "notified": False,
    }

    key = url  # ключ у state
    prev = state.get(key, {})

    # логіка повідомлення:
    # - надсилаємо, якщо price is not None і price <= target
    # - і якщо раніше не надсилали (prev.get("notified") is False)
    # - або ціна впала нижче за останню зафіксовану notified_price (щоб оновити)
    should_notify = False
    if price is not None:
        prev_price = prev.get("price")
        prev_notified = prev.get("notified", False)
        prev_notified_price = prev.get("notified_price")

        if price <= target:
            # якщо ще не надсилали повідомлення або ціна стала ще менша
            if (not prev_notified) or (prev_notified_price is not None and price < prev_notified_price):
                should_notify = True

    # Формуємо результат і можливо надсилаємо
    if should_notify:
        link = used_url or url
        msg = f"🎯 {name}\nЦіна: {price} грн (ціль: {target} грн)\n{link}"
        ok, resp = send_telegram(msg, token=token, chat_id=chat_id)
        result["notified"] = ok
        result["notify_resp"] = resp
        if ok:
            result["notified_at"] = now
            result["notified_price"] = price
        else:
            result["notify_error"] = resp
    else:
        # нічого надсилати не потрібно
        pass

    # Оновлюємо state: зберігаємо last checked price та чи надсилали
    state[key] = {
        "name": name,
        "url": url,
        "checked_at": now,
        "price": price,
        "notified": result.get("notified", False),
        "notified_at": result.get("notified_at"),
        "notified_price": result.get("notified_price"),
        "error": err
    }
    return result

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Warning: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Telegram notifications will be skipped.")

    items = load_json(ITEMS_FILE, [])
    if not items:
        print("No items found in", ITEMS_FILE)
        return

    state = load_json(STATE_FILE, {})

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_item, item, state, token, chat_id): item for item in items}
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as e:
                res = {"error": f"exception: {e}", "item": futures[fut]}
            results.append(res)
            # просте логування
            if res.get("error"):
                print(f"[{res.get('name')}] ERROR: {res.get('error')}")
            else:
                p = res.get("price")
                if p is None:
                    print(f"[{res.get('name')}] price not found (used_url={res.get('used_url')})")
                else:
                    print(f"[{res.get('name')}] price={p} грн; notified={res.get('notified')}")

    # зберігаємо state
    save_json(STATE_FILE, state)
    # опціонально — зберегти лог результатів
    save_json("last_run_results.json", results)

if __name__ == "__main__":
    main()
