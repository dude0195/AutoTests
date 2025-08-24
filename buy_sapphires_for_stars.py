# buy_sapphires_for_stars.py
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

# --- сырой дамп ответа балансов для отладки структуры ---
def save_raw_api_balances(obj):
    try:
        Path("balances_api_raw.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("[balances] Сырой ответ сохранён в balances_api_raw.json")
    except Exception as e:
        print(f"[balances] Не удалось сохранить balances_api_raw.json: {e}")

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
    page.on("console",       lambda m: print("[console]", m.type, m.text))
    page.on("pageerror",     lambda e: print("[pageerror]", e))
    page.on("requestfailed", lambda r: print("[reqfail]", r.url, r.failure))

def open_tg(page, url):
    page.goto(url, wait_until="domcontentloaded")
    log(f"Открыл Telegram Web: {page.url}")
    page.wait_for_timeout(3000)

# ----------------- шаги UI: Play → модалка → iframe → покупка -----------------

def click_play(page) -> bool:
    try:
        btns = page.locator('button.Button.tiny.primary:has(span.inline-button-text:has-text("Play"))')
        if btns.count():
            btns.last.scroll_into_view_if_needed()
            btns.last.click(timeout=6000)
            page.wait_for_timeout(7000)  # ← увеличенная задержка после Play
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

def click_sapphire_deposit_and_buy(app_frame) -> bool:
    try:
        card = app_frame.locator('div.balances__item', has=app_frame.locator('img[alt="Sapphires"]'))
        deposit_btn = card.locator('div.balances__deposit .button__image, div.balances__deposit')
        deposit_btn.first.click(timeout=6000)
        app_frame.wait_for_timeout(400)
        log("В WebApp: открыл окно покупки сапфиров.")

        radio_10 = app_frame.locator('div.buy__buy-item .radio:has(.radio__cash:has-text("10"))')
        if radio_10.count():
            radio_10.first.click(timeout=4000)
            app_frame.wait_for_timeout(300)
            log("В WebApp: выбрал пакет на 10 сапфиров.")
        else:
            log("В WebApp: не нашёл радио на 10 — возможно уже выбран.")

        confirm = app_frame.locator('button.button_blue_gradient, .box__actions button:has-text("Confirm")')
        confirm.first.click(timeout=5000)
        app_frame.wait_for_timeout(600)
        log("В WebApp: нажал Confirm.")
        return True
    except Exception as e:
        log(f"В WebApp: не удалось оформить покупку: {e}")
        return False

def click_confirm_and_pay(page, timeout_ms=30000) -> bool:
    log("Жду модалку оплаты и кнопку 'Confirm and Pay'…")
    deadline = time.time() + timeout_ms / 1000.0
    pay_re = re.compile(r"(Confirm.*Pay|Оплатить|Подтвердить.*оплат|Оплата|Pay)", re.I)

    try:
        page.wait_for_selector('div[role="dialog"], [class*="modal"], [class*="popup"]', timeout=10000)
    except PWTimeout:
        pass

    def _try_click_button_on(target) -> bool:
        try:
            btn = target.get_by_role("button", name=pay_re).first
            if btn.count() and btn.is_visible():
                btn.scroll_into_view_if_needed()
                try: btn.click(timeout=2500)
                except Exception: btn.click(timeout=2500, force=True)
                page.wait_for_timeout(600); return True
        except Exception: pass
        try:
            loc = target.locator("button, .Button, [role=button]").filter(has_text=pay_re)
            if loc.count():
                b = loc.first
                try: b.scroll_into_view_if_needed()
                except Exception: pass
                try: b.click(timeout=2500)
                except Exception: b.click(timeout=2500, force=True)
                page.wait_for_timeout(600); return True
        except Exception: pass
        return False

    while time.time() < deadline:
        if _try_click_button_on(page):
            log("✅ Нажал 'Confirm and Pay' (на основной странице).")
            return True
        for fr in page.frames:
            try:
                if _try_click_button_on(fr):
                    log("✅ Нажал 'Confirm and Pay' внутри iframe.")
                    return True
            except Exception:
                continue
        try: page.mouse.wheel(0, 200)
        except Exception: pass
        page.wait_for_timeout(400)

    log("⚠ Не нашёл/не нажал кнопку 'Confirm and Pay' в отведённое время.")
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

# ----------------- запрос балансов и сравнение сапфиров -----------------

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

# --- числа: поддержка 1.2k / 3.4M / 2B и обычных строк ---
def _coerce_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(" ", "").replace("_", "")
        m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kKmMbB])?", s)
        if m:
            num = float(m.group(1))
            suf = m.group(2)
            if not suf:
                return num
            if suf in ("k", "K"):
                return num * 1_000
            if suf in ("m", "M"):
                return num * 1_000_000
            if suf in ("b", "B"):
                return num * 1_000_000_000
        try:
            return float(s)
        except Exception:
            return None
    return None

# --- универсальный парсер сапфиров из любой структуры ---
def extract_sapphire_balance(obj) -> float | None:
    sapph_names = {"sapphire", "sapphires"}
    numeric_keys = (
        "amount", "balance", "available", "available_balance",
        "value", "qty", "quantity", "total", "current", "count"
    )
    name_keys = ("asset", "asset_type", "type", "currency", "code", "name")

    def is_sapphire_name(val) -> bool:
        return isinstance(val, str) and val.strip().lower() in sapph_names

    def scan(node):
        if isinstance(node, dict):
            # 1) balances: { "sapphire": 123, ... }
            for k, v in node.items():
                if isinstance(k, str) and k.strip().lower() in sapph_names:
                    num = _coerce_num(v)
                    if num is not None:
                        return num
            # 2) вложенные контейнеры
            for subkey in ("balances", "data", "items", "result", "payload", "results"):
                if subkey in node:
                    res = scan(node[subkey])
                    if res is not None:
                        return res
            # 3) элемент со свойством имени
            for nk in name_keys:
                if nk in node and is_sapphire_name(node[nk]):
                    # сначала по «типичным» числовым полям
                    for vk in numeric_keys:
                        if vk in node:
                            num = _coerce_num(node[vk])
                            if num is not None:
                                return num
                    # иначе ищем глубже в значениях
                    for v in node.values():
                        res = scan(v)
                        if res is not None:
                            return res
            # 4) общий обход значений
            for v in node.values():
                res = scan(v)
                if res is not None:
                    return res
            return None

        if isinstance(node, list):
            for it in node:
                res = scan(it)
                if res is not None:
                    return res
            return None

        return None

    return scan(obj)

def compare_and_report_sapphires(old_balances: dict | None, new_balances: dict | None):
    old_val = extract_sapphire_balance(old_balances) if old_balances else None
    new_val = extract_sapphire_balance(new_balances) if new_balances else None

    print("\n=== Sapphire balance check ===")
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

            # 1) жмём Play
            clicked = click_play(page)
            if not clicked:
                log("Не удалось найти/нажать Play в чате. Проверь, что ты в чате с ботом и есть кнопка.")

            # 2) подтверждаем модалку Telegram (если появится)
            maybe_confirm_modal(page)

            # 3) ждём iFrame WebApp
            frame = wait_webapp_iframe(page, timeout_ms=30000)
            if frame:
                log(f"✅ WebApp iframe найден. URL: {frame.url}")
                # 4) внутри WebApp — клики на покупку 10 сапфиров
                click_sapphire_deposit_and_buy(frame)
                # 5) модалка оплаты Telegram "Confirm and Pay"
                click_confirm_and_pay(page, timeout_ms=30000)
            else:
                log("⚠ WebApp iframe не нашёлся/не загрузился.")

            # --- ПЕРЕД запросом балансов пробуем получить и сохранить токен из iframe ---
            token = load_auth_token()
            if not token and frame:
                token_from_iframe = get_auth_token_from_webapp_frame(frame)
                if token_from_iframe:
                    save_auth_token(token_from_iframe)
                    token = token_from_iframe

            # Если фрейм потеряли — попробуем любой zargates-iframe
            if not token:
                for fr in page.frames:
                    url = (fr.url or "")
                    if "zargates" in url or "demo-twa" in url or "tgwebapp" in url:
                        token_from_iframe = get_auth_token_from_webapp_frame(fr)
                        if token_from_iframe:
                            save_auth_token(token_from_iframe)
                            token = token_from_iframe
                            break

            # -------- баланс сапфиров: запрос и сравнение (всегда) --------
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

            # Сохраняем сырой ответ для отладки
            if new_balances:
                save_raw_api_balances(new_balances)

            compare_and_report_sapphires(old_balances, new_balances)
            if new_balances:
                save_balances_to_file(new_balances)

        finally:
            input("Нажми Enter, чтобы закрыть браузер…")
            ctx.close()

if __name__ == "__main__":
    run()
