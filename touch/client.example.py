"""ПРИМЕР клиента TouchDesigner для вкладки Touch в CompanionHelper.

Этот файл - образец, а не часть сервера: его содержимое вставляется в
TouchDesigner (Text DAT + Execute DAT / Timer CHOP) и правится под свой проект.
Сервер сюда ничего не импортирует.

Как это работает
----------------
1. Клиент шлёт серверу СВОИ кнопки: POST /touch/buttons
   {"client": "...", "label": "...", "host": ..., "port": ..., "address": "...",
    "buttons": [{"id": "...", "label": "...", "color": "#rrggbb", "active": true}]}
   Список заменяется целиком, поэтому его просто отправляют заново, когда
   кнопки изменились (например, поменялся оператор или активный пресет).
2. Пока клиент жив, он раз в пару секунд шлёт POST /touch/ping - иначе сервер
   через TOUCH_CLIENT_TIMEOUT секунд выкинет его с деки (мёртвый .toe не
   оставит после себя кнопок).
3. Нажатие кнопки на деке сервер отправляет ОБРАТНО в TouchDesigner одним
   OSC-сообщением на host:port/address со строкой - id кнопки. Ловить его
   удобнее всего OSC In DAT (см. on_press ниже), подписка не нужна.

Поля кнопки: id (обязательно), label (по умолчанию = id), color (фон, "#rrggbb"),
active (true - кнопка горит зелёным, как «активное» состояние на других вкладках).
"""

import json
import time
import urllib.error
import urllib.request

# --- настройки проекта ------------------------------------------------------
SERVER = "http://127.0.0.1:7878"     # адрес CompanionHelper
CLIENT = "wall"                       # id клиента (латиницей, без пробелов)
LABEL = "Стена"                       # подпись вкладки на деке
OSC_HOST = "127.0.0.1"                # куда сервер шлёт нажатия (этот компьютер)
OSC_PORT = 7777                       # порт OSC In в TouchDesigner
OSC_ADDRESS = "/touch"                # адрес, на который приходят нажатия
PING_EVERY = 5.0                      # секунд между пингами (меньше TOUCH_CLIENT_TIMEOUT)


def buttons_from_project() -> list[dict]:
    """Замените это на чтение реального состояния проекта.

    Вызывается перед каждой отправкой: вернули новый список - дека обновилась.
    `active=True` подсветит кнопку (например, текущий активный клип).
    """
    return [
        {"id": "intro", "label": "Intro"},
        {"id": "clipA", "label": "Клип A", "active": True},
        {"id": "clipB", "label": "Клип B"},
        {"id": "black", "label": "Блэкаут", "color": "#4a1414"},
    ]


def post(path: str, payload: dict) -> dict:
    """POST JSON на сервер; любой сбой возвращает {'status': 'error', ...}."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:                 # 400 - битый payload
        return {"status": "error", "http": e.code,
                "detail": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:                              # сервер выключен/сеть
        return {"status": "error", "detail": str(e)}


def set_buttons(buttons: list[dict]) -> dict:
    """Отправить кнопки (полная замена списка на сервере)."""
    return post("/touch/buttons", {
        "client": CLIENT, "label": LABEL,
        "host": OSC_HOST, "port": OSC_PORT, "address": OSC_ADDRESS,
        "buttons": buttons,
    })


def ping() -> dict:
    """Продлить жизнь клиента; ответ {'status': 'unknown'} значит, что сервер
    перезапускался - надо заново отправить кнопки."""
    return post("/touch/ping", {"client": CLIENT})


def pump() -> None:
    """Один шаг: отправить кнопки и, если сервер их не знает, зарегистрироваться.

    Вызывайте раз в PING_EVERY секунд из Execute DAT (onFrameStart с таймером).
    """
    result = ping()
    if result.get("status") != "ok":
        result = set_buttons(buttons_from_project())
    print("touch client:", result)


def on_press(button_id: str) -> None:
    """Что делать с нажатием - это и есть OSC In DAT в TouchDesigner.

    В TD на сообщение OSC_ADDRESS приходит один строковый аргумент: id кнопки.
    Пример реакции (замените на своё):
    """
    print("нажата кнопка:", button_id)


if __name__ == "__main__":
    # Автономная проверка без TouchDesigner: регистрируемся и пингуем.
    print("register:", set_buttons(buttons_from_project()))
    while True:
        time.sleep(PING_EVERY)
        pump()
