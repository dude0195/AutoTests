import json
import requests
from playwright.sync_api import sync_playwright

# === Константы ===
TMA_URL = "https://twa-rd.zargates.com/#tgWebAppData=user%3D%257B%2522id%2522%253A402312903%252C%2522first_name%2522%253A%2522Roman%2522%252C%2522last_name%2522%253A%2522Kos%2522%252C%2522username%2522%253A%2522RomanKos%2522%252C%2522language_code%2522%253A%2522en%2522%252C%2522allows_write_to_pm%2522%253Atrue%252C%2522photo_url%2522%253A%2522https%253A%255C%252F%255C%252Ft.me%255C%252Fi%255C%252Fuserpic%255C%252F320%255C%252F9lMrMkO8Q6MmXxm8EuGUIzego5uUPNreBgqH3zsnJtY.svg%2522%257D%26chat_instance%3D7225054925153986100%26chat_type%3Dsender%26auth_date%3D1755763054%26signature%3DNwJdRDjYAgfAjLD7W3Ybex5nMsChiKs0Ui8A6i1SEVnC0P1iCHjmAaizGsVXDRwsWlaXVKywxnL6X9ivBnaQAA%26hash%3D1a193a7aca7bf647ad2c875db700f8abb863d5da1533b410a0b7c79698f61fb8&tgWebAppVersion=9.1&tgWebAppPlatform=weba&tgWebAppThemeParams=%7B%22bg_color%22%3A%22%23212121%22%2C%22text_color%22%3A%22%23ffffff%22%2C%22hint_color%22%3A%22%23aaaaaa%22%2C%22link_color%22%3A%22%238774e1%22%2C%22button_color%22%3A%22%238774e1%22%2C%22button_text_color%22%3A%22%23ffffff%22%2C%22secondary_bg_color%22%3A%22%230f0f0f%22%2C%22header_bg_color%22%3A%22%23212121%22%2C%22accent_text_color%22%3A%22%238774e1%22%2C%22section_bg_color%22%3A%22%23212121%22%2C%22section_header_text_color%22%3A%22%23aaaaaa%22%2C%22subtitle_text_color%22%3A%22%23aaaaaa%22%2C%22destructive_text_color%22%3A%22%23e53935%22%7D"

# === Утилиты ===
def get_auth_token_from_page(page):
    local_storage = page.evaluate("() => window.localStorage")
    print("\n=== LocalStorage Dump ===")
    print(json.dumps(local_storage, indent=2, ensure_ascii=False))

    if "auth-store" in local_storage:
        try:
            auth_data = json.loads(local_storage["auth-store"])
            return auth_data.get("accessToken")
        except:
            pass
    return None


def get_user_balances(auth_token):
    url = "https://demo-api-rd.zargates.com/api/v1/balances"
    headers = {"accept": "application/json", "authorization": f"Bearer {auth_token}"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def get_user_inventory(auth_token):
    url = (
        "https://demo-api-rd.zargates.com/api/v1/offer-manager/user/inventory"
        "?page=1&limit=999&filter=ALL&rarity_filter=ALL&tradeable=false&for_trade=false"
    )
    headers = {"accept": "application/json", "authorization": f"Bearer {auth_token}"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()

    # Вытаскиваем именно массив предметов
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return data["data"]
        if "items" in data and isinstance(data["items"], list):
            return data["items"]
        if "inventory" in data and isinstance(data["inventory"], list):
            return data["inventory"]
    elif isinstance(data, list):
        return data
    return []


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 {filename} сохранён")


# === Тест ===
def test_tma_and_api():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(TMA_URL)

        page.wait_for_timeout(10000)  # ждём загрузку страницы

        auth_token = get_auth_token_from_page(page)
        assert auth_token, "❌ Не удалось получить токен авторизации из браузера"

        # сохраняем токен
        save_json("auth.json", {"auth_token": auth_token})

        # получаем и сохраняем балансы
        balances = get_user_balances(auth_token)
        save_json("balances.json", balances)

        # получаем и сохраняем только массив предметов
        inventory = get_user_inventory(auth_token)
        save_json("inventory.json", inventory)
        print(f"📦 Найдено {len(inventory)} предметов")

        input("Нажми Enter, чтобы закрыть браузер...")
        browser.close()
