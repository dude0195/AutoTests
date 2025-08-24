# buy_diamonds_with_sapphires.py
import json, re, time, requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

CONFIG_FILE   = Path(__file__).with_name("config.json")
AUTH_FILE     = Path(__file__).with_name("auth.json")
BALANCES_FILE = Path(__file__).with_name("balances.json")

# ----------------- утилиты чтения/записи -----------------

def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_auth_token() -> str | None:
    if not AUTH_FILE.exists():
        return None
    try:
        with AUTH_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f) or {}
        token = data.get("auth_token")
        return token.strip() if isinstance(token, str) else None
    except Exception:
        return None

def save_auth_token(token: str):
    try:
        with AUTH_FILE.open("w", encoding="utf-8") as f:
            json.dump({"auth_token": token}, f, ensure_ascii=False, indent=2)
        print("[auth] Токен сохранён в auth.json")
    except Exception as e:
        print(f"[auth] Не удалось сохранить токен: {e}")

def save_balances_to_file(balances: dict):
    try:
        with BALANCES_FILE.open("w", encoding="utf-8") as f:
            json.dump(balances, f, ensure_ascii=False, indent=2)
        print("[balances] balances.json обновлён.")
    except Exception as e:
        print(f"[balances] Не удалось сохранить balances.json: {e}")

def load_old_balances() -> dict | None:
    if not BALANCES_FILE.exists():
        return None
    try:
        with BALANCES_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def log(msg):
    print(f"[flow] {msg}", flush=True)

# ----------------- Playwright запуск и отладка -----------------

def launch_ctx(p):
    # Нужен установленный канал Chrome:  playwright install chrome
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=".pw_telegram",
        headless=False,
        channel="chrome",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-site-isolation-trials",
            "--disable-features=BlockThirdPartyCookies,ThirdPartyStoragePartitioning,PrivacySandboxAdsAPIs",
        ],
        viewport={"width": 1280, "height": 900},
    )
    log("✔ Запущен Chrome-канал.")
    return ctx

def attach_debug(page):
    # m.text — это свойство, не вызываем как функцию
    page.on("console",       lambda m: print("[console]", m.type, m.text))
    page.on("pageerror",     lambda e: print("[pageerror]", e))
    page.on("requestfailed", lambda r: print("[reqfail]", r.url, r.failure))

def open_tg(page, url):
    page.goto(url, wait_until="domcontentloaded")
    log(f"Открыл Telegram Web: {page.url}")
    page.wait_for_timeout(3000)

# ----------------- шаги UI: Play → модалка → iframe -----------------

def click_play(page) -> bool:
    try:
        btns = page.locator('button.Button.tiny.primary:has(span.inline-button-text:has-text("Play"))')
        if btns.count():
            btns.last.scroll_into_view_if_needed()
            btns.last.click(timeout=6000)
            page.wait_for_timeout(7000)  # ждём прогрузку WebApp
            log("Нажал Play (точный селектор).")
            return True
    except Exception:
        pass
    for sel in ['button:has-text("Play")', 'a:has-text("Play")']:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.scroll_into_view_if_needed()
                loc.first.click(timeout=6000)
                page.wait_for_timeout(7000)
                log("Нажал Play (универсальный селектор).")
                return True
            except Exception:
                pass
    try:
        page.get_by_role("button", name=re.compile(r"\bPlay\b", re.I)).first.click(timeout=6000)
        page.wait_for_timeout(7000)
        log("Нажал Play (role=button).")
        return True
    except Exception:
        pass
    return False

def maybe_confirm_modal(page):
    variants = [
        'div[role="dialog"] button:has-text("Confirm")',
        'div[role="dialog"] button:has-text("Open")',
        'div[role="dialog"] button:has-text("Continue")',
        'div[role="dialog"] button:has-text("Открыть")',
        'div[role="dialog"] button:has-text("Продолжить")',
        'button:has-text("Confirm")',
        'button:has-text("Open")',
        'button:has-text("Continue")',
        'button:has-text("Открыть")',
        'button:has-text("Продолжить")',
    ]
    for sel in variants:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=4000)
                page.wait_for_timeout(500)
                log(f"Нажал подтверждение: {sel}")
                return True
            except Exception:
                pass
    return False

def wait_webapp_iframe(page, timeout_ms=30000):
    try:
        page.wait_for_selector('div[role="dialog"] iframe, iframe[src*="http"]', timeout=timeout_ms)
    except PWTimeout:
        return None
    for f in page.frames:
        try:
            u = f.url or ""
            if "http" in u and any(k in u for k in ["tgwebapp", "twa", "zargates", "demo-twa", "zargates.com"]):
                return f
        except Exception:
            pass
    el = page.query_selector('div[role="dialog"] iframe') or page.query_selector('iframe[src*="http"]')
    return el.content_frame() if el else None

# ----------------- покупка DIAMONDS внутри WebApp -----------------

def click_diamonds_deposit_and_flow(app_frame) -> bool:
    try:
        # 1) В блоке алмазов нажать кнопку пополнения
        card = app_frame.locator(
            'div.balances__item',
            has=app_frame.locator('img[alt="Diamonds"], img[src*="diamondsBalance"]')
        )
        deposit_btn = card.locator('div.balances__deposit .button__image, div.balances__deposit')
        deposit_btn.first.scroll_into_view_if_needed()
        deposit_btn.first.click(timeout=8000)
        app_frame.wait_for_timeout(3000)  # подождать 3 секунды
        log("В WebApp: нажал пополнение у алмазов.")

        # 2) Дождаться и нажать «Купить за ...» (ищем вариант с суммой 10)
        app_frame.wait_for_selector('button.card__submit-button, .card__submit-button', state="visible", timeout=12000)

        buy_btn = app_frame.locator(
            "button.card__submit-button",
            has=app_frame.locator("span.card__button-amount:has-text('10')")
        )
        if not buy_btn.count():
            buy_btn = app_frame.locator("button.card__submit-button").filter(has_text=re.compile(r"(Купить за|Buy)", re.I))
        if not buy_btn.count():
            buy_btn = app_frame.locator('button:has-text("Купить за"), button:has-text("Buy")')

        clicked = False
        for _ in range(4):
            if buy_btn.count():
                try:
                    buy_btn.first.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    buy_btn.first.click(timeout=5000)
                    clicked = True
                    break
                except Exception:
                    try:
                        buy_btn.first.click(timeout=3000, force=True)
                        clicked = True
                        break
                    except Exception:
                        try:
                            app_frame.mouse.wheel(0, 400)
                        except Exception:
                            pass
                        app_frame.wait_for_timeout(400)
            else:
                app_frame.wait_for_timeout(500)
        if not clicked:
            raise TimeoutError("Не удалось нажать кнопку «Купить за».")

        app_frame.wait_for_timeout(2000)
        log('В WebApp: нажал кнопку "Купить за".')

        # 3) Нажать «Продолжить» (синяя)
        cont_blue = app_frame.locator(
            'button.button_blue_gradient:has-text("Продолжить"), '
            'button.box__button_continue:has-text("Продолжить"), '
            'button:has-text("Continue")'
        )
        cont_blue.first.scroll_into_view_if_needed()
        try:
            cont_blue.first.click(timeout=6000)
        except Exception:
            cont_blue.first.click(timeout=6000, force=True)
        app_frame.wait_for_timeout(2000)
        log('В WebApp: нажал "Продолжить" (синяя).')

        # 4) Ввести код 1111
        app_frame.wait_for_selector('div.code input.code__input', timeout=8000)
        code_inputs = app_frame.locator('div.code input.code__input')
        for i in range(code_inputs.count()):
            code_inputs.nth(i).fill("1")
            app_frame.wait_for_timeout(100)
        log("В WebApp: ввёл код 1111.")

        # 5) Нажать «Подтвердить»
        confirm_btn = app_frame.locator('button:has-text("Подтвердить"), button:has-text("Confirm")')
        confirm_btn.first.scroll_into_view_if_needed()
        try:
            confirm_btn.first.click(timeout=6000)
        except Exception:
            confirm_btn.first.click(timeout=6000, force=True)
        app_frame.wait_for_timeout(2000)
        log('В WebApp: нажал "Подтвердить".')

        # 6) Нажать «Продолжить» (жёлтая)
        cont_yellow = app_frame.locator(
            'button.button_yellow_gradient:has-text("Продолжить"), '
            'button:has-text("Continue")'
        )
        cont_yellow.first.scroll_into_view_if_needed()
        try:
            cont_yellow.first.click(timeout=6000)
        except Exception:
            cont_yellow.first.click(timeout=6000, force=True)
        app_frame.wait_for_timeout(800)
        log('В WebApp: нажал "Продолжить" (жёлтая).')

        return True

    except Exception as e:
        log(f"В WebApp: сценарий пополнения алмазов не завершён: {e}")
        return False

# ----------------- токен из WebApp (iframe) -----------------

def _safe_json_loads(s):
    try:
        return json.loads(s)
    except Exception:
        return None

def _extract_token_from_obj(obj) -> str | None:
    if not isinstance(obj, (dict, list, str)):
        return None
    if isinstance(obj, str):
        if obj.strip().startswith("{") or obj.strip().startswith("["):
            parsed = _safe_json_loads(obj)
            if parsed is not None:
                return _extract_token_from_obj(parsed)
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("accesstoken", "access_token", "token", "bearer", "authorization"):
                if isinstance(v, str) and v:
                    return v.replace("Bearer ", "").strip()
        for v in obj.values():
            t = _extract_token_from_obj(v)
            if t: return t
    if isinstance(obj, list):
        for v in obj:
            t = _extract_token_from_obj(v)
            if t: return t
    return None

def get_auth_token_from_webapp_frame(app_frame) -> str | None:
    try:
        ls = app_frame.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
        token = _extract_token_from_obj(ls)
        if token:
            print("[auth] Токен найден в localStorage iframe.")
            return token
    except Exception:
        pass
    try:
        ss = app_frame.evaluate("() => Object.fromEntries(Object.entries(sessionStorage))")
        token = _extract_token_from_obj(ss)
        if token:
            print("[auth] Токен найден в sessionStorage iframe.")
            return token
    except Exception:
        pass
    return None

# ----------------- запрос балансов и сравнение АЛМАЗОВ -----------------

def fetch_balances_from_api(auth_token: str) -> tuple[dict | None, int | None]:
    url = "https://demo-api-rd.zargates.com/api/v1/balances"
    if not auth_token:
        return None, None
    headers = {"accept": "application/json", "authorization": f"Bearer {auth_token}"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 401:
            return None, 401
        r.raise_for_status()
        return r.json(), r.status_code
    except Exception as e:
        print(f"[balances] Ошибка запроса балансов: {e}")
        return None, None

def _coerce_num(v):
    try: return float(v)
    except Exception: return None

def extract_diamond_balance(obj) -> float | None:
    # Универсальный проход по словарям/спискам
    if isinstance(obj, dict):
        for key in obj.keys():
            if str(key).lower() in ("diamond", "diamonds"):
                val = _coerce_num(obj[key])
                if val is not None: return val
        if isinstance(obj.get("balances"), dict):
            for k, v in obj["balances"].items():
                if str(k).lower() in ("diamond", "diamonds"):
                    return _coerce_num(v)
        if isinstance(obj.get("data"), list):
            for it in obj["data"]:
                b = extract_diamond_balance(it)
                if b is not None: return b
    if isinstance(obj, list):
        for it in obj:
            if isinstance(it, dict):
                name = None
                for name_key in ("asset", "asset_type", "code", "currency", "name"):
                    if name_key in it:
                        name = str(it[name_key]).lower(); break
                if name in ("diamond", "diamonds"):
                    for val_key in ("amount", "balance", "value", "qty"):
                        if val_key in it:
                            v = _coerce_num(it[val_key])
                            if v is not None: return v
                b = extract_diamond_balance(it)
                if b is not None: return b
    return None

def compare_and_report_diamonds(old_balances: dict | None, new_balances: dict | None):
    old_val = extract_diamond_balance(old_balances) if old_balances else None
    new_val = extract_diamond_balance(new_balances) if new_balances else None

    print("\n=== Diamond balance check ===")
    print(f"old (balances.json): {old_val if old_val is not None else '—'}")
    print(f"new (API):           {new_val if new_val is not None else '—'}")
    if old_val is not None and new_val is not None:
        delta = new_val - old_val
        print(f"Δ change:            {delta:+.6f}")
    else:
        print("Δ change:            невозможно вычислить (нет старого или нового значения)")
    print("==============================\n")

# ----------------- основной сценарий -----------------

def run():
    cfg = load_config()
    tg_web_url = cfg.get("tg_web_url") or "https://web.telegram.org/a/"

    with sync_playwright() as p:
        ctx = launch_ctx(p)
        page = ctx.new_page()
        attach_debug(page)

        try:
            open_tg(page, tg_web_url)

            # 1) жмём Play (если уже в чате с кнопкой)
            clicked = click_play(page)
            if not clicked:
                log("Не удалось найти/нажать Play в чате. Проверь, что ты в чате с ботом и есть кнопка.")

            # 2) подтверждаем модалку Telegram (если появится)
            maybe_confirm_modal(page)

            # 3) ждём iFrame WebApp
            frame = wait_webapp_iframe(page, timeout_ms=30000)
            if frame:
                log(f"✅ WebApp iframe найден. URL: {frame.url}")
                # 4) внутри WebApp — клики на покупку алмазов
                click_diamonds_deposit_and_flow(frame)
            else:
                log("⚠ WebApp iframe не нашёлся/не загрузился.")

            # --- ПЕРЕД запросом балансов берём токен из iframe, если его ещё нет ---
            token = load_auth_token()
            if not token and frame:
                token_from_iframe = get_auth_token_from_webapp_frame(frame)
                if token_from_iframe:
                    save_auth_token(token_from_iframe)
                    token = token_from_iframe

            if not token:
                for fr in page.frames:
                    url = (fr.url or "")
                    if "zargates" in url or "demo-twa" in url or "tgwebapp" in url:
                        t2 = get_auth_token_from_webapp_frame(fr)
                        if t2:
                            save_auth_token(t2)
                            token = t2
                            break

            # -------- баланс алмазов: запрос и сравнение (всегда) --------
            new_balances, code = fetch_balances_from_api(token)
            if code == 401:
                print("[balances] 401 Unauthorized — обновляю токен из iframe и повторяю запрос.")
                if frame:
                    t2 = get_auth_token_from_webapp_frame(frame)
                    if t2 and t2 != token:
                        save_auth_token(t2)
                        token = t2
                        new_balances, code = fetch_balances_from_api(token)

            old_balances = load_old_balances()
            compare_and_report_diamonds(old_balances, new_balances)
            if new_balances:
                save_balances_to_file(new_balances)

        finally:
            input("Нажми Enter, чтобы закрыть браузер…")
            ctx.close()

if __name__ == "__main__":
    run()
