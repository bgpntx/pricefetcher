#!/usr/bin/env python3
# check_bot.py — простий тест Telegram-бота: перевірка getMe, getUpdates і пробне повідомлення.
import os
import sys
import requests

def get_token():
    # 1) спроба з аргументу: python3 check_bot.py <TOKEN> [CHAT_ID]
    if len(sys.argv) >= 2:
        return sys.argv[1]
    # 2) або зі змінної оточення TELEGRAM_BOT_TOKEN
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    print("Помилка: передай токен як аргумент або встанови змінну оточення TELEGRAM_BOT_TOKEN.")
    print("Приклад: TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН python3 check_bot.py")
    sys.exit(1)

def api(token, method, params=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.status_code, r.text
    except Exception as e:
        return None, f"Exception: {e}"

def post_api(token, method, data):
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code, r.text
    except Exception as e:
        return None, f"Exception: {e}"

def main():
    token = get_token()
    # 1) перевірка getMe
    code, text = api(token, "getMe")
    print("getMe:", code)
    print(text)
    # 2) перевірка getUpdates (показує останні оновлення; тут може бути порожній список)
    code, text = api(token, "getUpdates")
    print("\ngetUpdates:", code)
    print(text)
    # 3) якщо передали chat_id як другий аргумент — відправимо тестове повідомлення
    chat_id = 203410893
    if len(sys.argv) >= 3:
        chat_id = sys.argv[2]
    else:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if chat_id:
        msg = "Тестове повідомлення від check_bot.py"
        code, resp = post_api(token, "sendMessage", {"chat_id": chat_id, "text": msg})
        print("\nsendMessage:", code)
        print(resp)
    else:
        print("\nCHAT_ID не вказаний. Щоб надіслати тест, запусти: python3 check_bot.py <TOKEN> <CHAT_ID>")
        print("Або встанови змінну оточення TELEGRAM_CHAT_ID і запусти без другого аргументу.")

if __name__ == "__main__":
    main()

