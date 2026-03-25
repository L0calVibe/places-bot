import logging
import os
import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Настройки (берутся из переменных окружения) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
RENDER_URL = os.environ.get("RENDER_URL", "")  # https://your-app.onrender.com
PORT = int(os.environ.get("PORT", 8000))
RADIUS = 5000  # 5 км

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Категории мест
PLACE_TYPES = [
    ("museum", "🏛 Музеи"),
    ("movie_theater", "🎬 Кинотеатры"),
    ("park", "🌳 Парки и красивые места"),
    ("restaurant", "🍽 Местная кухня"),
    ("tourist_attraction", "📸 Достопримечательности"),
    ("night_club", "🎵 Концерты и клубы"),
    ("art_gallery", "🎨 Галереи"),
    ("shopping_mall", "🛍 Ярмарки и рынки"),
    ("amusement_park", "🎡 Развлечения"),
    ("stadium", "🏟 Ивенты и мероприятия"),
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я помогу найти интересные места рядом с тобой.\n\n"
        "📍 Просто отправь мне свою геолокацию — и я покажу музеи, рестораны, "
        "парки, концерты и многое другое в радиусе 5 км!\n\n"
        "Нажми на скрепку 📎 → Геопозиция"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Как пользоваться ботом:\n\n"
        "1. Нажми на 📎 (скрепка) в поле ввода\n"
        "2. Выбери «Геопозиция»\n"
        "3. Отправь своё местоположение\n\n"
        "Я найду интересные места в радиусе 5 км!"
    )


async def fetch_places(lat: float, lon: float, place_type: str) -> list:
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius": RADIUS,
        "type": place_type,
        "language": "ru",
        "key": GOOGLE_API_KEY,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, params=params)
        data = response.json()
    return data.get("results", [])


def format_place(place: dict) -> str:
    name = place.get("name", "Без названия")
    address = place.get("vicinity", "Адрес не указан")
    rating = place.get("rating")
    user_ratings = place.get("user_ratings_total", 0)
    open_now = place.get("opening_hours", {}).get("open_now")

    text = f"📌 *{name}*\n"
    text += f"📍 {address}\n"

    if rating:
        stars = "⭐" * round(rating)
        text += f"{stars} {rating} ({user_ratings} отзывов)\n"

    if open_now is True:
        text += "🟢 Сейчас открыто\n"
    elif open_now is False:
        text += "🔴 Сейчас закрыто\n"

    maps_url = f"https://www.google.com/maps/search/?api=1&query={name}&query_place_id={place.get('place_id', '')}"
    text += f"[Открыть на карте]({maps_url})"
    return text


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.location
    lat = location.latitude
    lon = location.longitude

    await update.message.reply_text(
        "🔍 Ищу интересные места рядом с тобой... Это займёт несколько секунд!"
    )

    all_places = []
    for place_type, category_name in PLACE_TYPES:
        try:
            places = await fetch_places(lat, lon, place_type)
            top_places = sorted(places, key=lambda x: x.get("rating", 0), reverse=True)[:2]
            if top_places:
                all_places.append((category_name, top_places))
        except Exception as e:
            logger.error(f"Ошибка при запросе {place_type}: {e}")

    if not all_places:
        await update.message.reply_text(
            "😔 К сожалению, рядом с тобой ничего не найдено. Попробуй ещё раз."
        )
        return

    await update.message.reply_text(
        f"🗺 Нашёл интересные места в радиусе 5 км!\nКатегорий: {len(all_places)}"
    )

    for category_name, places in all_places:
        message = f"*{category_name}*\n\n"
        message += "\n\n".join([format_place(p) for p in places])
        try:
            await update.message.reply_text(
                message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")

    await update.message.reply_text(
        "✅ Готово! Хочешь найти места в другом месте? Просто отправь новую геолокацию."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📍 Отправь мне свою геолокацию!\nНажми на 📎 → Геопозиция"
    )


# --- Webhook setup ---
async def telegram_webhook(request: Request) -> Response:
    app = request.app.state.bot_app
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return Response()


async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


async def startup():
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await bot_app.initialize()
    await bot_app.start()

    webhook_url = f"{RENDER_URL}/webhook"
    await bot_app.bot.set_webhook(webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

    starlette_app.state.bot_app = bot_app


async def shutdown():
    app = starlette_app.state.bot_app
    await app.stop()
    await app.shutdown()


starlette_app = Starlette(
    routes=[
        Route("/webhook", telegram_webhook, methods=["POST"]),
        Route("/", health_check, methods=["GET"]),
    ],
    on_startup=[startup],
    on_shutdown=[shutdown],
)


if __name__ == "__main__":
    uvicorn.run(starlette_app, host="0.0.0.0", port=PORT)
