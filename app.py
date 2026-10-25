import asyncio
import os
from aiohttp import web
from bot import dp, bot  # Берем бота из твоего bot.py

async def handle(request):
    # Этот ответ будет видеть UptimeRobot
    return web.Response(text="Bot is running!")

async def main():
    # Настраиваем мини-сайт для Render
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print("Сайт для будильника запущен. Запускаю бота...")
    
    # Запускаем самого бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())