# buy_emeralds_top_up.py
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

def save_raw_api_balances(obj):
    try:
        Path("balances_api_raw.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("[balances] Сырой ответ сохранён в balances_api_raw.json")
    except Exception as e:
        print(f"[balances] Не удалось сохранить balances_api_raw.json: {e}")

def log(msg):
    print(f"[flow] {msg}", flush=True)

# ----------------- Playwright запуск и отладка -----------------

def launch_ctx(p):
    # Требуется: playwright install chrome
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

# ----------------- базовые шаги UI: Play → модалка → iframe -----------------

def click_play(page) -> bool:
    try:
        btns = page.locator('button.Button.tiny.primary:has(span.inline-button-text:has-text("Play"))')
        if btns.count():
            btns.last.scroll_into_view_if_needed()
            btns.last.click(timeout=6000)
            page.wait_for_timeout(7000)
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

# ----------------- сценарий: пополнение изумрудов -----------------

def click_emeralds_deposit_and_flow(app_frame) -> bool:
    try:
        # 1) В блоке изумрудов нажать кнопку пополнения
        card = app_frame.locator(
            'div.balances__item',
            has=app_frame.locator('img[src*="emeraldsBalance"]')
        )
        deposit_btn = card.locator('div.balances__deposit .button__image, div.balances__deposit')
        deposit_btn.first.scroll_into_view_if_needed()
        deposit_btn.first.click(timeout=8000)
        app_frame.wait_for_timeout(3000)  # подождать 3 секунды
        log("В WebApp: нажал пополнение у изумрудов.")

        # 2) Дождаться появления карточки с кнопкой «Купить за …»
        #    Иногда рендерится не сразу — ждём до 12 сек
        app_frame.wait_for_selector(
            'button.card__submit-button, .card__submit-button',
            state="visible", timeout=12000
        )

        # Ищем именно кнопку с суммой 10
        buy_btn = app_frame.locator(
            "button.card__submit-button",
            has=app_frame.locator("span.card__button-amount:has-text('10')")
        )

        # Если не нашли по сумме — берём любую «Купить за»/«Buy»
        if not buy_btn.count():
            buy_btn = app_frame.locator(
                "button.card__submit-button"
            ).filter(has_text=re.compile(r"(Купить за|Buy)", re.I))

        # Фолбэки на случай отличной разметки
        if not buy_btn.count():
            buy_btn = app_frame.locator(
                'button:has-text("Купить за"), button:has-text("Buy")'
            )

        # Иногда элемент вне вьюпорта — скроллим несколько раз
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
                    # попробуем форс-клик
                    try:
                        buy_btn.first.click(timeout=3000, force=True)
                        clicked = True
                        break
                    except Exception:
                        # прокрутим страницу и попробуем ещё
                        try:
                            app_frame.mouse.wheel(0, 400)
                        except Exception:
                            pass
                        app_frame.wait_for_timeout(400)
            else:
                # подождём и пересчитаем
                app_frame.wait_for_timeout(500)

        if not clicked:
            raise TimeoutError("Не удалось нажать кнопку «Купить за».")

        app_frame.wait_for_timeout(2000)  # 2 секунды
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

        # 4) Ввести код: 1 1 1 1
        code_inputs = app_frame.locator('div.code input.code__input')
        app_frame.wait_for_selector('div.code input.code__input', timeout=8000)
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
        log(f"В WebApp: сценарий пополнения изумрудов не завершён: {e}")
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

# ----------------- запрос балансов и сравнение ИЗУМРУДОВ -----------------

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

def extract_asset_balance(obj, names=("emerald", "emeralds")) -> float | None:
    names = {n.lower() for n in names}
    numeric_keys = (
        "amount", "balance", "available", "available_balance",
        "value", "qty", "quantity", "total", "current", "count"
    )
    name_keys = ("asset", "asset_type", "type", "currency", "code", "name")

    def is_name(v): return isinstance(v, str) and v.strip().lower() in names

    def scan(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.strip().lower() in names:
                    num = _coerce_num(v)
                    if num is not None:
                        return num
            for subkey in ("balances", "data", "items", "result", "payload", "results"):
                if subkey in node:
                    r = scan(node[subkey])
                    if r is not None: return r
            for nk in name_keys:
                if nk in node and is_name(node[nk]):
                    for vk in numeric_keys:
                        if vk in node:
                            num = _coerce_num(node[vk])
                            if num is not None: return num
                    for v in node.values():
                        r = scan(v)
                        if r is not None: return r
            for v in node.values():
                r = scan(v)
                if r is not None: return r
            return None
        if isinstance(node, list):
            for it in node:
                r = scan(it)
                if r is not None: return r
            return None
        return None

    return scan(obj)

def compare_and_report_emeralds(old_balances: dict | None, new_balances: dict | None):
    old_val = extract_asset_balance(old_balances, names=("emerald", "emeralds")) if old_balances else None
    new_val = extract_asset_balance(new_balances, names=("emerald", "emeralds")) if new_balances else None
    print("\n=== Emeralds balance check ===")
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
            # 0) открыть веб-телеграм
            open_tg(page, tg_web_url)

            # 1) жмём Play (в чате бота)
            clicked = click_play(page)
            if not clicked:
                log("Не удалось найти/нажать Play в чате. Проверь, что ты в чате с ботом и есть кнопка.")

            # 2) подтверждаем модалку Telegram (если появится)
            maybe_confirm_modal(page)

            # 3) ждём iFrame WebApp
            frame = wait_webapp_iframe(page, timeout_ms=30000)
            if frame:
                log(f"✅ WebApp iframe найден. URL: {frame.url}")
                # 4) внутри WebApp — пополнение изумрудов по шагам
                click_emeralds_deposit_and_flow(frame)
            else:
                log("⚠ WebApp iframe не нашёлся/не загрузился.")

            # --- Токен: берём из auth.json или вытаскиваем из iframe ---
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
                        token_from_iframe = get_auth_token_from_webapp_frame(fr)
                        if token_from_iframe:
                            save_auth_token(token_from_iframe)
                            token = token_from_iframe
                            break

            # 5) Балансы: запрос и сравнение изумрудов (всегда, даже если покупка не прошла)
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

            if new_balances:
                save_raw_api_balances(new_balances)

            compare_and_report_emeralds(old_balances, new_balances)
            if new_balances:
                save_balances_to_file(new_balances)

        finally:
            input("Нажми Enter, чтобы закрыть браузер…")
            ctx.close()

if __name__ == "__main__":
    run()
