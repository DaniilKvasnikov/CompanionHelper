import uvicorn
from fastapi import FastAPI
import requests

app = FastAPI()

# Базовый URL для управления дизайном кнопок в Companion v3/v4
COMPANION_URL = "http://localhost:8000/api/location"

@app.post("/press")
def handle_button_press(page: str, row: str, col: str):
    # Логируем нажатие в консоль сервера для отладки
    print(f"[BUTTON PRESSED] -> Page: {page}, Row: {row}, Column: {col}")
    
    # Текст, который мы отправим обратно на нажатую кнопку
    display_text = f"Pressed!\nP:{page} R:{row} C:{col}"
    
    # Формируем URL запроса, кодируя текст для безопасной передачи в GET-параметре
    url = f"{COMPANION_URL}/{page}/{row}/{col}/style?text={requests.utils.quote(display_text)}"
    
    try:
        # Отправляем POST-запрос в Companion, чтобы обновить текст на кнопке
        # Скрипт шлет пустой JSON {}, так как текст передается прямо в строке URL
        requests.post(url, json={}, timeout=1)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to contact Companion: {e}")
        
    return {"status": "ok", "received": {"page": page, "row": row, "col": col}}

if __name__ == "__main__":
    # Запускаем сервер на порту 8000
    uvicorn.run(app, host="0.0.0.0", port=7878)
