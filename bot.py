import asyncio
import base64
import ssl
import certifi
import aiohttp
import time
import os
import io
from datetime import datetime
from PIL import Image
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
user_daily_requests = {}
DAILY_LIMIT = 15 
MAX_HISTORY = 6

async def ask_aiai(parts: list) -> str:
    headers = {
        "Authorization": f"Bearer {AIAI_KEY}",
        "Content-Type": "application/json"
    }
    
    # Убираем жесткие запреты, просим "подумать" перед ответом
    system_prompt = {
        "role": "system", 
        "content": "Ты — эксперт по решению школьных заданий. Твоя задача — помочь ученику с домашней работой. Внимательно прочитай задание на фото. Если это тест, определи правильный вариант, выбрав его логически (не угадывай). Сначала напиши краткий ход мысли (почему ты выбрал этот вариант), а затем сам ответ. Если задача по математике/физике — напиши краткое решение. Не пиши длинных вступлений."
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [system_prompt] + parts,
        "max_tokens": 2500, 
        "temperature": 0.1 
    }
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            async with session.post(AIAI_URL, json=payload, headers=headers, timeout=90) as resp:
                data = await resp.json()
                
                if "error" in data:
                    return "Ошибка сервера."
                
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"].get("content")
                    if content and content.strip():
                        return content.strip()
                
                return "Не могу разобрать."
        except Exception:
            return "Ошибка."

async def solve_photo(image_bytes: bytes, history: list) -> str:
    b64 = base64.b64encode(image_bytes).decode('utf-8')
    prompt = """Реши задания с фото. 
    Прочитай каждое задание. Если это тест, выбери правильный вариант и кратко объясни почему. 
    Если это задача, напиши решение. Нумеруй ответы так же, как в задании."""
    
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
        [KeyboardButton(text="📸 Решить по фото")],
        [KeyboardButton(text="✏️ Задать вопрос")]
    ],
    resize_keyboard=True
)

def update_history(user_id: int, role: str, content: str):
    if user_id not in user_histories:
        user_histories[user_id] = []
    user_histories[user_id].append({"role": role, "content": content})
    if len(user_histories[user_id]) > MAX_HISTORY:
        user_histories[user_id] = user_histories[user_id][-MAX_HISTORY:]

def check_daily_limit(user_id: int) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    if user_id not in user_daily_requests or user_daily_requests[user_id]["date"] != today:
        user_daily_requests[user_id] = {"date": today, "count": 0}
    if user_daily_requests[user_id]["count"] >= DAILY_LIMIT:
        return False
    user_daily_requests[user_id]["count"] += 1
    return True

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    now = time.time()
    
    if user_id in user_cooldowns and now - user_cooldowns[user_id] < 5:
        return
    
    if not check_daily_limit(user_id):
        await message.answer(f"Лимит {DAILY_LIMIT} фото в день исчерпан.")
        return

    user_cooldowns[user_id] = now
    
    if message.message_id in processed_messages: return
    processed_messages.add(message.message_id)
    
    try:
        history = user_histories.get(user_id, [])
        file = await bot.get_file(message.photo[-1].file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        # Сжатие (оставляем четким)
        img = Image.open(io.BytesIO(file_bytes.read()))
        img.thumbnail((1600, 1600)) 
        output = io.BytesIO()
        img.convert('RGB').save(output, format='JPEG', quality=90) 
        image_data = output.getvalue()

        solution = await solve_photo(image_data, history)
        
        update_history(user_id, "user", "[Пользователь прислал фото]")
        update_history(user_id, "assistant", solution)
        
        await message.answer(solution, reply_markup=main_menu)
            
    except Exception:
        await message.answer("Ошибка. Попробуй еще раз.")

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    now = time.time()
    
    text = message.text
    if text == "/start":
        user_histories[user_id] = []
        await message.answer("Привет! Отправь фото задания, и я выдам решение с пояснением. (Лимит: 15 фото в день).", reply_markup=main_menu)
        return
        
    if text in ["📸 Решить по фото", "✏️ Задать вопрос"]:
        await message.answer("Жду фото или вопрос.", reply_markup=main_menu)
        return

    if user_id in user_cooldowns and now - user_cooldowns[user_id] < 5:
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
    print("БОТ ЗАПУЩЕН! РЕЖИМ ПОНИМАНИЯ.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
