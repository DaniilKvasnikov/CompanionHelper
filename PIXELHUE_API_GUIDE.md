# Pixelhue Q8 — гайд по подключению и управлению по API

> Реконструкция утерянной документации `api.pixelhue.com`.
> Составлено из: официальных фрагментов доков (Apifox), исходников модуля
> Bitfocus Companion `companion-module-pixelhue-switcher`, и **живого
> тестирования** на реальном устройстве в этом проекте.
>
> Тестовое устройство: SN `25704A000000017`, прошивка **V2.0.0**, protocolType
> `G4A` / protocolVersion `2.0` / apiVersion `1.0`. Применимо к Q8, а также
> P10 / P20 / P80 (у них те же протоколы, отличаются наборы модулей).
>
> Метки достоверности по ходу текста:
> `[verified]` — проверено запросом к устройству ·
> `[docs]` — из официальной документации ·
> `[companion]` — из реверс-инжиниринга модуля Companion (не перепроверено).

---

## 1. Обзор

Q8 — модульный бесшовный коммутатор/процессор. Управляется по:

| Канал | Порт | Назначение |
|---|---|---|
| HTTP REST | `8088` | команды и чтение состояния |
| WebSocket | `8088` (или `19998` через `ucenter`) | пуш событий/состояния в реальном времени |
| UDP | `5600` | обнаружение / низкоуровневый протокол |
| Discovery (HTTPS) | `19998` | список устройств, самоподписанный TLS |

Штатный софт: **PixelFlow** (event-софт), контроллеры **U5 / U5 Pro**.
Сторонние: Bitfocus Companion (модуль `pixelhue-switcher`).

---

## 2. Обнаружение устройства

```
GET https://<ip>:19998/unico/v1/ucenter/device-list
```
- Самоподписанный сертификат → проверку TLS отключить (`verify=False`).
- Опциональный query `?clientType=8`.

Ответ `[verified]`:
```json
{
  "code": 0, "message": "ok",
  "data": { "list": [ {
    "modelId": 29974,
    "SN": "25704A000000017",
    "deviceName": "System1",
    "ip": "192.168.200.161",
    "mac": "54:B5:6C:1D:C6:3E",
    "online": 1,
    "protocols": [
      { "port": 8088, "linkType": "http",      "protocolType": "G4A", "protocolVersion": "2.0", "apiVersion": "1.0" },
      { "port": 8088, "linkType": "websocket",  "protocolType": "G4A", "protocolVersion": "2.0", "apiVersion": "1.0" },
      { "port": 5600, "linkType": "udp",        "protocolType": "G4A", "protocolVersion": "2.0", "apiVersion": "1.0" }
    ],
    "projectInfo": { "identify": "defaultProject-q", "name": "defaultProject-q" },
    "connectionLimit": { "maxClientsNum": 0, "connectedNum": 2 }
  } ] }
}
```
`protocols[linkType=="http"].port` — это база для командного REST API (обычно `8088`).

---

## 3. Аутентификация

### 3.1 Способ A — JWT без пароля (основной)  `[verified]`

**Шаг 1.** Получить публичные данные ноды (без токена):
```
GET http://<ip>:8088/pixelhue/v1/node/open-detail?nodeId=1
```
```json
{ "code": 0, "message": "ok",
  "data": { "sn": "25704A000000017", "startTime": "1788509316542" } }
```

**Шаг 2.** Собрать JWT:
- алгоритм **HS256**
- header: `{"alg":"HS256","typ":"JWT"}`
- payload: `{"SN": <sn>}`  — только это поле, **без** `exp`/`iat`  `[companion]` `[verified]`
- секрет для подписи = строка **`startTime`** (как есть, миллисекунды)

> Официальный Go-пример `[docs]` показывает вариант с `StandardClaims`
> (`exp` = +2 мин, `iat`, `iss:"gin-jwt-demo"`). На V2.0.0 работает и он, и
> минимальный `{"SN": sn}` без времени. Минимальный проще — токен не истекает.

**Шаг 3.** Во всех последующих запросах:
```
Authorization: <jwt>          (строка как есть, БЕЗ префикса "Bearer ")
Content-Type: application/json (для PUT/POST с телом)
```

**Токен не истекает.** Пересобрать нужно только после перезагрузки устройства
(меняется `startTime` → старый токен становится невалидным → HTTP 401).

Готовый Python (stdlib, без `PyJWT`):
```python
import hmac, hashlib, base64, json, urllib.request

def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=")

def get_token(host, port=8088, node_id="1"):
    od = json.load(urllib.request.urlopen(
        f"http://{host}:{port}/pixelhue/v1/node/open-detail?nodeId={node_id}"))
    sn, start = od["data"]["sn"], od["data"]["startTime"]
    seg = b64(b'{"alg":"HS256","typ":"JWT"}') + b"." + \
          b64(json.dumps({"SN": sn}, separators=(",", ":")).encode())
    sig = hmac.new(start.encode(), seg, hashlib.sha256).digest()
    return (seg + b"." + b64(sig)).decode()
```

### 3.2 Способ B — логин/пароль  `[docs]`

```
POST http://<ip>:8088/pixelhue/v1/system/auth/login
{ "username": "...", "password": "..." }
->  { "code": 0, "data": { "token": "..." } }
```
Полученный `token` используется так же в заголовке `Authorization`.

---

## 4. Соглашения запросов/ответов

- Все ответы: `{ "code": <int>, "message": <str>, "data": <object|array> }`
- **Успех = `code` равен `0` ИЛИ `200`** (устройство использует оба).
- HTTP-статус почти всегда `200`, даже когда `code` в теле — ошибка.
- Тело для команд над экранами/слоями — обычно **массив** объектов
  (можно адресовать несколько экранов/слоёв за один запрос).

---

## 5. Два пространства имён

На одном порту `8088` живут два префикса:

| Префикс | Что это | Покрытие |
|---|---|---|
| `/pixelhue/v1/...` | официальное/документированное | node, auth, screens, layers (source/select/template), interfaces, scenes, gallery |
| `/unico/v1/...` | легаси-алиас, тот же токен | **надмножество** — всё вышеперечисленное **+** `layers/window`, `layers/zorder`, `layers/umd`, `layers/layer-preset/*`, `interface/crop-source`, `system/ctrl/source-backup` |

**Важно `[verified]`:** `PUT /pixelhue/v1/layers/window` и `.../layers/zorder`
на прошивке V2.0.0 возвращают **HTTP 404** («Cannot PUT …»). Эти эндпоинты
существуют **только под `/unico/v1`**. Всё остальное работает под обоими
префиксами одинаково (тот же токен, те же ответы).

Практика: используй `/pixelhue/v1` для задокументированного, а для
`layers/window` и `layers/zorder` — `/unico/v1`.

---

## 6. Справочник эндпоинтов

Базовый URL везде: `http://<ip>:8088<prefix>` где `<prefix>` = `/pixelhue/v1`
или `/unico/v1` (см. §5).

### 6.1 Node / система

| Метод | Путь | Auth | Назначение |
|---|---|---|---|
| GET | `/node/open-detail?nodeId=1` | нет | `{sn, startTime}` — для токена `[verified]` |
| GET | `/node/detail?nodeId=1` | да | модель, версия, `online`, `status` `[verified]` |
| GET | `/node/status` (2.5) | да | статус ноды `[docs]` |
| PUT | `/node/factory-reset` (2.2) | да | сброс к заводским `[docs]` |
| GET/PUT | `/system/ctrl/source-backup` | да | резервный источник входа `[companion]` |
| PUT | `/system/ctrl/switch-effect` (2.3) | да | глобальные эффекты перехода `[docs]` |
| PUT | `/system/ctrl/swap` (2.4) | да | глобальный swap `[docs]` |

`GET /pixelhue/v1/node/detail?nodeId=1` ответ `[verified]`:
```json
{ "code": 0, "message": "ok", "data": {
  "nodeId": 1, "modelId": 29974, "seriesType": 9,
  "status": 1, "online": 1, "sn": "25704A000000017",
  "version": "V2.0.0",
  "versionMatching": { "serverVersion": "V2.0.0", "minMatchingVersion": "..." }
}}
```

### 6.2 Экраны (Screens)

| Метод | Путь | Тело | Назначение |
|---|---|---|---|
| GET | `/screen/list-detail` | — | список экранов `[verified]` |
| PUT | `/screen/take` | массив, см. ниже | Take выбранного/указанного `[verified]` |
| PUT | `/screen/cut` | массив | Cut `[verified]` |
| PUT | `/screen/freeze` | массив | заморозка по экрану `[verified]` |
| PUT | `/screen/ftb` | массив | fade-to-black по экрану `[verified]` |
| PUT | `/screen/selected/freeze` | `{"freeze":0\|1}` | глобальная заморозка выбранных `[docs]` |
| PUT | `/screen/selected/ftb` | `{"ftb":{"enable":0\|1,"time":ms}}` | глобальный FTB `[docs]` |
| PUT | `/screen/select` | `[{screenId, select, screenName}]` | выбрать экраны `[companion]` |
| PUT | `/screen/test-pattern` | `[{screenId, testPattern:{...}}]` | тестовая таблица `[companion]` |

`GET /screen/list-detail` ответ `[verified]` (сокращённо):
```json
{ "code": 0, "message": "ok", "data": { "count": 7, "totalCount": 7, "list": [
  { "screenId": 1, "guid": "7d70c96c-9725-4ebc-aab5-6c0e2163dc1a",
    "combinationType": 1,
    "general": { "name": "MVR 1" },
    "freeze": 0,
    "ftb": { "enable": 0, "time": 700 } },
  { "screenId": 6, "guid": "0c62b6f2-...", "general": { "name": "Screen 1" }, "freeze": 0, "ftb": {"enable":0,"time":700} }
]}}
```
На тестовом устройстве: экраны 1-2 — MVR (мультивьюверы), 6-7 — реальные
выходные экраны «Screen 1» / «Screen 2».

**Take** `PUT /screen/take` `[verified]`:
```json
[ {
  "screenId": 6,
  "screenGuid": "0c62b6f2-...",
  "screenName": "Screen 1",
  "effectSelect": 1,          // 0 = системный эффект по умолчанию, 1 = заданный в switchEffect
  "direction": 0,             // 0 = PVW->PGM, 1 = PGM->PVW
  "switchEffect": { "type": 1, "time": 500 },   // type: 0 = CUT, 1 = FADE ; time в мс
  "swapEnable": 1             // 0/1 — менять местами PVW/PGM
} ]
```
Ответ успеха: `{ "code": 200, "message": "success", "data": {} }`

**Cut** `PUT /screen/cut`:
```json
[ { "screenId": 6, "screenGuid": "...", "screenName": "Screen 1",
    "direction": 0, "swapEnable": 1 } ]
```

**Freeze** `PUT /screen/freeze`:
```json
[ { "screenId": 6, "screenGuid": "...", "screenName": "Screen 1", "freeze": 1 } ]
```

**FTB** `PUT /screen/ftb`:
```json
[ { "screenId": 6, "screenGuid": "...", "screenName": "Screen 1",
    "ftb": { "enable": 1, "time": 500 } } ]
```

> `screenGuid` формально «required», но на V2.0.0 запрос проходит и с одним
> `screenId` `[verified]`. `screenId` имеет приоритет над `screenName`.

### 6.3 Слои (Layers)

| Метод | Путь (префикс!) | Тело | Назначение |
|---|---|---|---|
| GET | `/pixelhue/v1/layers/list-detail` | — | полная инфа по слоям `[verified]` |
| PUT | **`/unico/v1/layers/window`** | `[{layerId, window}]` | позиция/размер `[verified]` |
| PUT | **`/unico/v1/layers/zorder`** | `[{layerId, zorder:{type, para}}]` | порядок наложения `[companion]` (эндпоинт есть `[verified]`) |
| PUT | `/pixelhue/v1/layers/select` | `[{layerId, selected:0\|1}]` | выбор слоёв `[docs]` |
| PUT | `/pixelhue/v1/layers/source` | `[{layerId, source:{general:{...}}}]` | назначить вход слою `[docs]` |
| PUT | `/pixelhue/v1/layers/template/select` | `{templateId, screenId, sceneType, locked}` | применить шаблон раскладки `[docs]` |
| GET | `/unico/v1/layers/layer-preset/list-detail` | — | пресеты слоя `[companion]` |
| PUT | `/unico/v1/layers/layer-preset/apply` | `[{layerIds:[{layerId}], layerPreset}]` | применить пресет слоя `[companion]` |
| PUT | `/unico/v1/layers/umd` | `[{layerId, UMD:[...]}]` | UMD-тэги слоя `[companion]` |

`GET /layers/list-detail` — элемент списка `[verified]` (важные поля):
```json
{
  "layerId": 104923136,
  "layerIdObj": {
    "attachScreenId": 6, "attachScreenType": 0,
    "screenGuid": "0c62b6f2-...",
    "sceneType": 2, "type": 2, "id": 0
  },
  "general": { "name": "Layer 16", "isBackground": 0, "isFreeze": 0 },
  "enable": 1, "selected": 1, "isLock": 0, "opacity": 100, "zorder": 16,
  "window":        { "width": 1920, "height": 1080, "x": 0, "y": -864 },
  "virtualWindow": { "width": 1920, "height": 1080, "x": 0, "y": 0 },
  "source": { "general": { "sourceId": 1, "sourceType": 2, "connectorType": 4,
                           "sourceName": "HDMI Input" } }
}
```
`layerIdObj.type`: **`2`** — обычный программный слой, **`8`** — слой MVR
(мультивьювер), **`16`** — фоновый/спец. `attachScreenId` — на каком экране слой.

**Позиция / размер слоя** `PUT /unico/v1/layers/window` `[verified]`:
```json
[ { "layerId": 104923136,
    "window": { "x": 120, "y": -804, "width": 1820, "height": 1024 } } ]
```
- **Обязательны все 4 ключа** `x, y, width, height`. Частичный объект
  (только `x`,`y`) → `code 8210 "manage param invalid"` `[verified]`.
- Массив может содержать несколько слоёв — все едут одним запросом.
- Успех: `{ "code": 0, "message": "ok", "data": [] }`

**Z-order** `PUT /unico/v1/layers/zorder` `[companion]`:
```json
[ { "layerId": 104923136, "zorder": { "type": 1, "para": <индекс> } } ]
```
(`type 1` — переместить на позицию `para`; форма из Companion, на устройстве не
перепроверена, но эндпоинт отвечает `405` на GET → существует и принимает PUT.)

**Источник слоя** `PUT /pixelhue/v1/layers/source` `[companion]`:
```json
[ { "layerId": 104923136,
    "source": { "general": {
      "sourceId": 1,            // interfaceId входа (или cropId для кропа)
      "sourceType": 2,          // 8 = кроп-источник
      "connectorType": 4
    } } } ]
```

### 6.4 Пресеты и сцены

| Метод | Путь | Тело | Назначение |
|---|---|---|---|
| GET | `/pixelhue/v1/preset` | — | список пресетов `[companion]` |
| POST | `/pixelhue/v1/preset/apply` | см. ниже | загрузить пресет `[companion]` |
| GET | `/pixelhue/v1/scene` (6.2.1) | — | детали сцен `[docs]` |
| POST | `/pixelhue/v1/scene` (6.2.2) | — | создать сцену `[docs]` |
| PUT | `/pixelhue/v1/scene/apply` (6.2.3) | — | применить сцену `[docs]` |
| PUT | `/pixelhue/v1/scene/name` (6.2.4) | — | переименовать `[docs]` |
| DELETE | `/pixelhue/v1/scene/{id}` (6.2.5) | — | удалить `[docs]` |
| PUT | `/pixelhue/v1/scene/save` (6.1.2) | — | сохранить текущее в сцену `[docs]` |
| PUT | `/pixelhue/v1/scene/load` (6.1.3) | — | загрузить сцену `[docs]` |

**Apply preset** `POST /pixelhue/v1/preset/apply` `[companion]`:
```json
{
  "serial": 0,
  "presetId": "<guid>",
  "targetRegion": 0,
  "auxiliary": {
    "keyFrame": { "enable": 1 },
    "switchEffect": { "type": 1, "time": 500 },
    "swapEnable": 1,
    "effect": { "enable": 1 }
  }
}
```

### 6.5 Интерфейсы / входы

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/pixelhue/v1/interface/list-detail` | список входов/выходов `[docs]` `[companion]` |
| GET | `/unico/v1/interface/crop-source` | список кроп-источников `[companion]` |
| PUT | `/pixelhue/v1/interface/output-position` (3.2) | позиция выхода `[docs]` |
| PUT | `/pixelhue/v1/interface/image-quality` (3.3) | цветокоррекция входа `[docs]` |

### 6.6 Галерея / картинки

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/pixelhue/v1/gallery` (7.1) | список изображений `[docs]` |

---

## 7. WebSocket — состояние в реальном времени  `[companion]`

```
wss://<ip>:19998/unico/v1/ucenter/ws?client-type=8
Заголовок:  Authorization: <jwt>       (тот же токен)
TLS:        самоподписанный, проверку отключить
```

Сообщения — **бинарный TLV** (Tag-Length-Value), не JSON:
- TLV1 (со смещения 32): JSON-заголовок; длина в uint16 LE по смещению `32+6`,
  данные с `32+8`.
- TLV2 (сразу за TLV1): `tag` uint32 LE, `errCode` uint16 LE, длина uint16 LE,
  затем JSON-payload.
- Полная логика парсинга — в `WebSocketClient.ts` модуля Companion.

Используется, чтобы не поллить `list-detail`: устройство пушит изменения
экранов/слоёв/источников по мере их наступления.

---

## 8. Коды ошибок  `[verified]`

| `code` | Значение | Причина / что делать |
|---|---|---|
| `0` / `200` | успех | — |
| `8210` | `manage param invalid` | некорректное тело запроса (напр. неполный объект `window` — нужны все 4 ключа) |
| `8212` | `manage mio error: sdk layer move faild` | устройство отказало в операции над слоем: слой **заблокирован / привязан к keyframe / в группе** на пульте, ИЛИ окно уходит за пределы канваса экрана |
| `8212` | `getNotEmptyNormalAuxScreens ... no found screens` | Take/Cut применён к MVR-экрану (`layerIdObj.type == 8`) — не поддерживается |
| HTTP `404` `Cannot PUT /pixelhue/v1/layers/window` | эндпоинта нет в этом префиксе | использовать `/unico/v1/...` |
| HTTP `401` | токен невалиден/протух | устройство перезагрузилось → пересобрать токен через `open-detail` |

---

## 9. Практические замечания (по итогам тестирования)

1. **Rate limiting.** Это HTTP+JSON control-плоскость, не realtime-транспорт.
   Не слать `layers/window` на каждом кадре из CHOP-потока 60 Гц — троттлить
   до ~15-20 Гц, и не запускать новый запрос, пока не пришёл ответ на
   предыдущий (single-flight по каналу).
2. **Батчинг.** `screen/*` и `layers/window` принимают массив — несколько
   экранов/слоёв в одном запросе. Пользуйся этим вместо N отдельных запросов.
3. **Границы канваса.** `layers/window` отклоняется (`8212`), если слой
   уходит целиком за пределы экрана. Держи окно в пределах.
4. **Заблокированные слои.** Отдельные слои могут быть залочены/привязаны на
   самом пульте (keyframe-путь, группа, замок) — API вернёт `8212 "sdk layer
   move faild"` при любой попытке. Разблокировать можно только на устройстве.
   (В этом проекте так себя ведёт слой `104923137` «Layer 15» на экране 6 —
   единственный такой из ~40 слоёв.)
5. **MVR-экраны.** Экраны-мультивьюверы (у нас `screenId` 1-2) и их слои
   (`type 8`) не принимают Take/Cut. Реальные выходные экраны — 6-7.
6. **`/unico/v1` — надмножество.** Если сомневаешься — почти всё работает и
   под `/unico/v1`. Только `layers/window` и `layers/zorder` работают
   *исключительно* под ним.
7. **Нет корреляции ответов.** В HTTP-клиенте TouchDesigner (`webclientDAT`)
   `onResponse` не несёт id запроса → сопоставлять ответы с запросами
   FIFO-очередью на клиент, и не гнать параллельные запросы по одному клиенту.
8. **Токен в память, не в стор.** Не сохранять токен между запусками — он
   привязан к `startTime`, который меняется при ребуте. Пересобирать при
   старте и по HTTP 401.

---

## 10. Минимальный рабочий пример (Python, stdlib)

```python
import hmac, hashlib, base64, json, urllib.request

HOST, PORT = "192.168.200.161", 8088

def _b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=")

def token():
    od = json.load(urllib.request.urlopen(
        f"http://{HOST}:{PORT}/pixelhue/v1/node/open-detail?nodeId=1"))
    sn, start = od["data"]["sn"], od["data"]["startTime"]
    seg = _b64(b'{"alg":"HS256","typ":"JWT"}') + b"." + \
          _b64(json.dumps({"SN": sn}, separators=(",", ":")).encode())
    sig = hmac.new(start.encode(), seg, hashlib.sha256).digest()
    return (seg + b"." + _b64(sig)).decode()

def api(method, path, body=None, prefix="/pixelhue/v1"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}{prefix}{path}", data=data, method=method,
        headers={"Authorization": TOK, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=8).read())

TOK = token()

# список экранов
screens = api("GET", "/screen/list-detail")["data"]["list"]

# Take экрана 6 с фейдом 500 мс
api("PUT", "/screen/take", [{
    "screenId": 6, "effectSelect": 1, "direction": 0,
    "switchEffect": {"type": 1, "time": 500}, "swapEnable": 1}])

# подвинуть слой (ТОЛЬКО через /unico/v1, все 4 ключа window)
api("PUT", "/layers/window",
    [{"layerId": 104923136,
      "window": {"x": 100, "y": 0, "width": 1920, "height": 1080}}],
    prefix="/unico/v1")
```

---

## 11. Компоненты в этом проекте (TouchDesigner)

| Компонент | Файл | Что делает |
|---|---|---|
| `/project1/pixelhue_q8` | `tox/pixelhue_q8.tox` | клиент Q8: Connect (JWT), Take/Cut/Freeze/FTB, чтение экранов/слоёв, ручное управление окном одного слоя, CHOP in/out, **`layermap`** (таблица `layerId → путь к CHOP` + `Maptick`) для управления многими слоями из CHOP'ов, throttled батч-PUT |
| `/project1/midi_relative` | `tox/midi_relative.tox` | встроенный `midiin` DAT; декодирует relative-энкодеры (twos-complement, `Threshold` 64) в накопленные абсолютные значения; параметры `Relativecc`/`Midichannels`, таблица `config` (per-CC sensitivity/min/max/wrap/start), `in2` для прямой записи по имени, `out1` — CHOP с каналами `ch<ch>ctrl<idx>` |
| `/project1/example_2layer` | (встроен в .toe) | пример: 6 энкодеров X-Touch → позиция+масштаб 2 слоёв; `Select CHOP` для переименования, `constant CHOP` для соотношения сторон, математика `h = w / aspect`, вывод в `pixelhue_q8/layermap` |

Ключевые детали реализации:
- JWT собирается на stdlib (`hmac`/`hashlib`/`base64`/`json`), без `PyJWT`.
- `layers/window` идёт через `_baseUnico()` (`/unico/v1`), остальное — `/pixelhue/v1`.
- Отдельный `webclientDAT` на каждый тип запроса (meta / action / window),
  FIFO-очередь тегов на клиент вместо корреляции по id.
- Троттлинг пушей окна: не чаще раза в `Syncevery` кадров, single-flight
  через флаг `_winBusy`.

---

## 12. Источники

- Официальные фрагменты: `api.pixelhue.com` (Apifox) — **сейчас недоступен**,
  в веб-архиве не сохранён.
- Реверс-инжиниринг: [github.com/bitfocus/companion-module-pixelhue-switcher](https://github.com/bitfocus/companion-module-pixelhue-switcher)
  — файлы `src/services/ApiClient.ts`, `HttpClient.ts`, `WebSocketClient.ts`,
  `Discovery.ts`, `src/config/devices/Q8.ts`, `src/utils/utils.ts`.
- Живое тестирование на устройстве SN `25704A000000017` (V2.0.0) в рамках
  этого проекта.
- Поддержка производителя: `service@pixelhue.com`, `info@pixelhue.com`.
