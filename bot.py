import asyncio
import base64
import ssl
import certifi
import aiohttp
import time
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# Ключи из настроек Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
AIAI_KEY = os.getenv("AIAI_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ssl_context = ssl.create_default_context(cafile=certifi.where())
AIAI_URL = "https://api.aiai.by/v1/chat/completions"

MODEL_NAME = "gpt-4o-mini" 

processed_messages = set()
user_cooldowns = {}
user_histories = {}
MAX_HISTORY = 6

async def ask_aiai(parts: list) -> str:
    headers = {
        "Authorization": f"Bearer {AIAI_KEY}",
        "Content-Type": "application/json"
    }
    
    # ЖЕСТКИЙ ПРОМПТ: только инструмент для списывания
    system_prompt = {
        "role": "system", 
        "content": "Ты — инструмент для решения задач. Твоя цель — выдать готовый ответ для списывания. Никаких приветствий, объяснений и лишних слов. Только сухие шаги решения (если они нужны) и итоговый ответ. Формулы пиши обычным текстом без сложных символов."
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [system_prompt] + parts,
        "max_tokens": 2000,
        "temperature": 0.1 # Минимум креатива, максимум точности
    }
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            async with session.post(AIAI_URL, json=payload, headers=headers, timeout=60) as resp:
                data = await resp.json()
                
                if "error" in data:
                    print("ОШИБКА ОТ API:", data["error"])
                    return "Ошибка сервера ИИ."
                
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"].get("content")
                    if content and content.strip():
                        return content.strip()
                
                return "Не удалось распознать."
        except asyncio.TimeoutError:
            return "Превышено время ожидания."
        except Exception as e:
            print("ОШИБКА:", e)
            return "Ошибка при обращении к ИИ."

async def solve_photo(image_bytes: bytes, history: list) -> str:
    b64 = base64.b64encode(image_bytes).decode('utf-8')
    
    prompt = """Реши задания с фото. 
    Выдай ответы так, чтобы их можно было сразу переписать в тетрадь. 
    Если нужно решение — напиши его кратко. Если просят просто ответ — дай ответ. 
    Указывай номера заданий, если их несколько."""
    
    current_message = {
        "role": "user", 
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]
    }
    
    return await ask_aiai(history + [current_message])

async def chat_text(user_text: str, history: list) -> str:
    current_message = {"role": "user", "content": user_text}
    return await ask_aiai(history + [current_message])

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📸 Списáть по фото")],
        [KeyboardButton(text="✏️ Написать вопрос")]
    ],
    resize_keyboard=True
)

def update_history(user_id: int, role: str, content: str):
    if user_id not in user_histories:
        user_histories[user_id] = []
    user_histories[user_id].append({"role": role, "content": content})
    if len(user_histories[user_id]) > MAX_HISTORY:
        user_histories[user_id] = user_histories[user_id][-MAX_HISTORY:]

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    now = time.time()
    
    if user_id in user_cooldowns and now - user_cooldowns[user_id] < 5:
        wait_time = int(5 - (now - user_cooldowns[user_id]))
        await message.answer(f"⏳ Подожди {wait_time} сек.")
        return
    
    user_cooldowns[user_id] = now
    
    if message.message_id in processed_messages: return
    processed_messages.add(message.message_id)
    
    try:
        history = user_histories.get(user_id, [])
        file = await bot.get_file(message.photo[-1].file_id)
        file_bytes = await bot.download_file(file.file_path)
        solution = await solve_photo(file_bytes.read(), history)
        
        update_history(user_id, "user", "[Фото задачи]")
        update_history(user_id, "assistant", solution)
        
        if len(solution) > 4000:
            for i in range(0, len(solution), 4000):
                await message.answer(solution[i:i+4000], reply_markup=main_menu)
                await asyncio.sleep(0.5)
        else:
            await message.answer(solution, reply_markup=main_menu)
            
    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("Ошибка. Попробуй еще раз.")

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    now = time.time()
    
    text = message.text
    if text == "/start":
        user_histories[user_id] = []
        await message.answer("Отправь фото задания или напиши вопрос.", reply_markup=main_menu)
        return
        
    if text in ["📸 Списáть по фото", "✏️ Написать вопрос"]:
        await message.answer("Жду фото или текст.", reply_markup=main_menu)
        return

    if user_id in user_cooldowns and now - user_cooldowns[user_id] < 5:
        wait_time = int(5 - (now - user_cooldowns[user_id]))
        await message.answer(f"⏳ Подожди {wait_time} сек.")
        return
    user_cooldowns[user_id] = now

    if message.message_id in processed_messages: return
    processed_messages.add(message.message_id)

    history = user_histories.get(user_id, [])
    answer = await chat_text(text, history)
    
    update_history(user_id, "user", text)
    update_history(user_id, "assistant", answer)

    await message.answer(answer[:4000], reply_markup=main_menu)

async def main():
    print("====================================")
    print("БОТ ЗАПУЩЕН! РЕЖИМ: ИНСТРУМЕНТ ДЛЯ СПИСЫВАНИЯ.")
    print("====================================")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
