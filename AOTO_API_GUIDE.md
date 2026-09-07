# Aoto LED-контроллер — гайд по HTTP API

> Документация собрана из **веб-UI контроллера** (Vue SPA `/aoto/`, бандлы
> `static/js/app.*.js` и карта модулей `/docs/config.js` → `/docs/record/*.js`)
> и **живых проверок** на тестовом контроллере.
>
> Тестовое устройство: `192.168.200.212:8080`, ПО «AOTO_V1.0.5» (из
> `/docs/config.js`). Применимо к семейству Aoto LED-процессоров/контроллеров
> с этим веб-UI; наборы модулей различаются по железу.
>
> Метки по ходу текста: `[verified]` — проверено запросом к устройству ·
> `[ui]` — найдено в исходниках веб-UI (не перепроверено) · `[probe]` —
> существование подтверждено OPTIONS-пробой.

---

## 1. Обзор

| Что | Значение |
|---|---|
| База HTTP | `http://<ip>:8080` |
| Префикс API | `/ng_ctrl_sys` (все пути ниже — после него) |
| Метод | `POST`, тело — JSON |
| Заголовки | `Content-Type: application/json;charset=UTF-8`, **`token: ""`** (пустой — авторизации нет) |
| Ответ | `{ "status": 200, "msg": "SUCCESS", "obj": <object|array|null>, "total": N, "cabinetNum": N }` |
| Web-UI | `http://<ip>:8080/aoto/#/controlSystem` |

В отличие от PixelHue: **никакого JWT/пароля** — пустой заголовок `token`.

Минимальный клиент (Python, stdlib):

```python
import json, urllib.request

def api(path, body):
    req = urllib.request.Request(
        f"http://192.168.200.212:8080/ng_ctrl_sys{path}",
        data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json;charset=UTF-8")
    req.add_header("token", "")
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))

obj = api("/globalSettings/getGlobalSettings", {})["obj"]   # читать состояние
api("/globalSettings/setBrightness", {"brightness": 1000})   # писать
```

---

## 2. Чтение состояния

### 2.1 `POST /globalSettings/getGlobalSettings` `[verified]`

Тело `{}`. Возвращает большой объект настроек системы (поля, используемые в
пресетах, ниже с краткими типами):

| Поле | Тип | Сеттер |
|---|---|---|
| `brightness` | int | `setBrightness` |
| `colorTemperature` | int (K) | `setColorTemple` *(так в прошивке!)* |
| `gammaCoefficient` | float | `setGammaCoefficient` |
| `scal` | int | `setScal` |
| `darkMagic` | int 0/1 | `setDarkMagic` |
| `colorSpaceEn` | int 0/1 | `setColorSpaceEn` |
| `hdrSetting` | int (read-шкала SDR=1/HLG=2/PQ=3) | `setHDR` (write-шкала SDR=2/HLG=3/PQ=4) |
| `maximumBrightness`, `coefficient` | int/float | фикс-поля тела `setHDR` |
| `redGain`/`greenGain`/`blueGain`/`whiteGain` | int | (настраиваются секторно — см. §5) |
| `deepcolor`, `lowGrayBias`, `lowAshCorrection`, `beyondGamut`, `calibrationSwitch`, `grayCompensationEn`, `thermalCompensationEn`, … | 0/1 | соответствующие `set*` |

Внимание: имя поля в объекте — **`deepcolor`** (строчное `c`), тогда как сеттер
называется `setDeepColor` (ключ тела, судя по UI, `deepColor`) — не включайте
`deepcolor` в захват пресетов вслепую, проверяйте ключ.

### 2.2 `POST /input/getDataBaseInputInfo` `[verified]`

Тело **`{"id": 1}`** (обязательно; с `{}` или `{"areaId":…}` возвращает `obj: null`).
Возвращает состояние выбранного входа + **текущий тест-паттерн**:

```
testPicEn, testPicMode, testPicDeep, testPicPlayStatus,
testPicRedValue, testPicGreenValue, testPicBlueValue, ...
```

---

## 3. Тест-паттерн (ScreenTest)

`POST /input/setTestImage` `[verified]` — полный пример (из UI):

```json
{ "areaId": 1, "testPicEn": 1, "testPicMode": 1,
  "testPicRedValue": 1022, "testPicGreenValue": 1023, "testPicBlueValue": 1023,
  "testPicDeep": 1, "testPicPlayStatus": 0 }
```

- **Включение теста независимо от цветов**: `testPicEn` 0/1 шлётся отдельно от
  значений RGB (UI при выключении повторяет те же цвета с `testPicEn: 0`).
- **Запись мержит по ключам** `[verified]`: тело с одним `testPicRedValue`
  меняет только красный, зелёный/синий не трогаются. Поэтому цвета можно
  писать тремя отдельными параметрами.
- `areaId` на тестовом контроллере = 1 (проверяйте под своё железо).

---

## 4. Справочник эндпоинтов (из веб-UI, 156 шт.)

Префикс везде `/ng_ctrl_sys`. `[✓]` = подтверждён на устройстве (запись или
OPTIONS), остальное `[ui]`.

### 4.1 `/globalSettings/*`

| Метод/путь | Назначение | Статус |
|---|---|---|
| `getGlobalSettings` | всё состояние системы | ✓ `[verified]` |
| `getShutterSync` / `setShutterSync` | shutter-sync | ✓(set)/`[ui]` |
| `setBrightness` | яркость | ✓ `[verified]` |
| `setColorTemple` | цветовая температура (K) — **опечатка в прошивке** | ✓ `[verified]` |
| `setGammaCoefficient` | гамма | ✓ `[verified]` |
| `setScal` | scal | ✓ `[verified]` |
| `setDarkMagic` | dark magic | ✓ `[verified]` |
| `setColorSpaceEn` | вкл цветового пространства | ✓ `[verified]` |
| `setColorSpace`, `getColorSpaceList` | выбор ЦП | `[ui]` |
| `setDeepColor`, `setLowGrayBias`, `setLowAshCorrection`, `setBeyondGamut`, `setCalibrationSwitch`, `setGrayGain`, `setGrayCompensationEn`/`Level`, `setThermalCompensationEn`/`Coefficient`, `setSpectralCoefficient`, `setColorCompenCoefficient`, `setBeyondBrightness`, `setScreenExtensionLevel` | картинка/компенсации | `[ui]` |
| `setScreenStatus` | вход-тип (Вход/Блэкаут/Фриз…) | ✓(set существует) |
| **`getScreenStatus` — отсутствует (404 на этой FW)** | читать текущий нет чем | — |
| `setHDR` | HDR (write-шкала) | ✓ (через пресеты) |
| `setVideoDelayFrame`, `setOSD`/`getOSD`, `setBrightnessOverdriveEn`, `setAutoBrightnessEn` | разное | `[ui]` |

### 4.2 `/input/*`

| Путь | Назначение |
|---|---|
| `setTestImage` / `getDataBaseInputInfo` | тест-паттерн + состояние входа ✓ `[verified]` |
| `setContrast`, `setBlackLevel`, `setColorBalance`, `setCutZoom` | картинка входа `[ui]` |
| `setVirtualDisplay`, `set3DEnable`/`set3Dmode`, `setLeveldomain`, `setInputPortUse`/`getInputPort` | режимы входа `[ui]` |

> Чтения для `setContrast`/`setBlackLevel`/`setColorBalance` в `getDataBaseInputInfo`
> нет — отдельного getter'а в списке не видно; в захват пресетов не включены.

### 4.3 Секторы/кабинеты (если адресуется посекторно)

- `/module/*`: `setModuleColorTemp`, `setModuleBright`, `setModuleLine(…ByUpOrDown)`, `resetModBorderBright`, `getModColorSpace`
- `/boxGroup/*`: `setGain`, `changeGama`, `changeColorTemp`, `changeEnable(s)`, `setGroup{GrayCompensationLevel,ExtensionLevel,ThermalCoefficient,SpectralCoefficient}`
- `/box/*`: `setSetCabinetBrightGain`, `setBoxOsd`, `getBoxTable`/`getBox`, `selectBoxList`, `exchangeBox`, `updateBox`
- `/area/*`: `findAreaIdAndName`, `updateGridProperty`

### 4.4 Сцены/пресеты устройства (нативные)

- `/presupposition/*`: `getList`, `add`, `getInfo`, `update`, `del`, `applyPresupposition`, `updateName`, `importPresupposition`, `exportPresupposition` `[ui]`
- `/industryModel/*`: `getList`, `add`, `getInfo`, `update`, `del`, `applyIndustryModel`, `updateName` `[ui]`
- `/backup/*`: `findBackUp`, `addBackUp`, `deleteBackUp`, `uploadBackUp`, `recoveryBackUp`, `updateName`, `exportBackUp` — экспорт/восстановление всего конфига

### 4.5 Сеть/система/прочее

- `/netParam/*` (IP/wifi), `/system/*` (`getMenu`, `getSystemStatus`, `getPoint`, `testCMD`, `exportConfigFile`, …), `/atiec/*`, `/inputEdid/*`, `/3dLutSetting/*`, `/canvas/*`, `/dmx/*`, `/onlineBox/sendOSD`, `/hardWareVersion/*`, `/version/upgrade`, `/boxFile/*`

---

## 5. Пресеты CompanionHelper (каталог параметров)

Фича пресетов в этом репозитории описана в [core/aotopresets.py](core/aotopresets.py)
и README. Файл-каталог `aoto/presets/parameters.json` (шаблон
`parameters.example.json`) — единственное место, где растёт список параметров
захвата, **без правки кода**. Формат одного параметра:

```json
{
  "name": "Яркость",
  "set":  { "path": "/ng_ctrl_sys/globalSettings/setBrightness", "key": "brightness" },
  "get":  { "path": "/ng_ctrl_sys/globalSettings/getGlobalSettings", "field": "obj.brightness" }
}
```

- `set` — как писать: `{path, key, value(кладётся при захвате), method?, extra?}`;
- `get` — как читать: `{path, field, body?}` (поле через точку; `body` — если
  чтению нужно тело, напр. `{"id": 1}`);
- `map` (опц.) — `{"прочитанное": "записываемое"}` для разных шкал чтения/записи
  (HDR: чтение SDR=1/HLG=2/PQ=3, запись SDR=2/HLG=3/PQ=4);
- значения пишутся телом `{key: value, **extra}`.

Сейчас в каталоге 11 параметров (все `[verified]` по чтению, запись проверена):
Яркость, Гамма, ColorTemperature, Scal, DarkMagic, ColorSpaceEn, ScreenTest
(вкл/выкл), ScreenTest R/G/B, HDR.

---

## 6. Грабли и заметки

1. **`token` пустой** — но заголовок обязателен (UI шлёт `token: ""`).
2. **`setColorTemple`** — опечатка в прошивке; `setColorTemperature` — 404.
3. **`deepcolor` vs `DeepColor`** — поле объекта в нижнем регистре, сеттер в
   camelCase; не захватывать без проверки ключа.
4. **`getScreenStatus` отсутствует** (404) — «Вход/Блэкаут/Фриз» можно только
   писать (`setScreenStatus`), захватывать текущее нечем.
5. **Чтение с телом**: `getGlobalSettings` отвечает на `{}`, а
   `getDataBaseInputInfo` требует `{"id":1}` (иначе `obj: null`).
6. **`setTestImage` мержит** — безопасно писать цвета по одному; `testPicEn`
   отдельный параметр.
7. OPTIONS на этом устройстве — рабочий способ проверки существования
   эндпоинта (200 есть / 404 нет), без побочных эффектов.
8. Rate limiting: UI держит таймаут 60 c и не гонит пачками; для пресетов
   пишем последовательно параметр за параметром.

---

## 7. Источники

- Веб-UI контроллера: `http://<ip>:8080/aoto/` → `static/js/app.*.js`,
  `/docs/config.js` → `/docs/record/*.js` (карты модулей по железу).
- Живые проверки: `192.168.200.212:8080` (ПО «AOTO_V1.0.5»): чтения, дельта-
  тесты сеттеров с восстановлением, семантика `setTestImage`, сквозной
  захват/применение пресета (7/7 параметров).
