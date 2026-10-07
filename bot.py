import asyncio
import os
import asyncpg
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ReplyKeyboardRemove
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
# ===================================

if not BOT_TOKEN:
    raise ValueError("Не задан BOT_TOKEN!")
if not ADMIN_ID:
    raise ValueError("Не задан ADMIN_ID!")
if not DATABASE_URL:
    raise ValueError("Не задан DATABASE_URL!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool = None  # Пул соединений


# ===== СОСТОЯНИЯ =====
class OrderFlow(StatesGroup):
    waiting_age = State()
    waiting_gender = State()


# ===== КЛАВИАТУРА =====
def get_products_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="350 рублей за кружок")],
            [KeyboardButton(text="200 рублей за гс")],
            [KeyboardButton(text="600 рублей за кружок + @username")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери услугу..."
    )


# ===== ИНИЦИАЛИЗАЦИЯ БД =====
async def init_db():
    global db_pool
    # Пул соединений (рекомендуется для asyncpg)
    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5
    )

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                user_id BIGINT PRIMARY KEY,
                product TEXT NOT NULL,
                age TEXT NOT NULL,
                gender TEXT NOT NULL,
                username TEXT,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                status TEXT DEFAULT 'pending'
            )
        """)
    print("✅ База данных готова")


# ===== /start =====
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Выбери услугу:", reply_markup=get_products_kb())


# ===== КОМАНДА /send =====
@dp.message(Command("send"))
async def admin_send(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "⚠️ Формат: <code>/send ID текст</code>\n"
            "Пример: <code>/send 123456789 Привет!</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ ID должен быть числом.")
        return

    try:
        await bot.send_message(target_id, parts[2])
        await message.answer(f"✅ Отправлено пользователю <code>{target_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")


# ===== КНОПКА «100 рублей за кружок» =====
@dp.message(F.text == "350 рублей за кружок")
async def choose_circle(message: Message, state: FSMContext):
    await state.update_data(product="350 рублей за кружок")
    await state.set_state(OrderFlow.waiting_age)
    await message.answer("сколько тебе лет?", reply_markup=ReplyKeyboardRemove())


# ===== КНОПКА «50 рублей за гс» =====
@dp.message(F.text == "200 рублей за гс")
async def choose_gs(message: Message, state: FSMContext):
    await state.update_data(product="200 рублей за гс")
    await state.set_state(OrderFlow.waiting_age)
    await message.answer("сколько тебе лет?", reply_markup=ReplyKeyboardRemove())


@dp.message(F.text == "600 рублей за кружок + @username")
async def choose_circle_username(message: Message, state: FSMContext):
    await state.update_data(product="600 рублей за кружок + @username")
    await state.set_state(OrderFlow.waiting_age)
    await message.answer("сколько тебе лет?", reply_markup=ReplyKeyboardRemove())


# ===== ПОЛУЧАЕМ ВОЗРАСТ =====
@dp.message(OrderFlow.waiting_age)
async def get_age(message: Message, state: FSMContext):
    await state.update_data(age=message.text)
    await state.set_state(OrderFlow.waiting_gender)
    await message.answer("напиши свой пол")


# ===== ПОЛУЧАЕМ ПОЛ → СОХРАНЯЕМ В БД → ШЛЁМ АДМИНУ =====
@dp.message(OrderFlow.waiting_gender)
async def get_gender(message: Message, state: FSMContext):
    await state.update_data(gender=message.text)
    data = await state.get_data()

    # СОХРАНЯЕМ В БАЗУ ДАННЫХ
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO orders (user_id, product, age, gender, username, full_name)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id) DO UPDATE SET
                product = EXCLUDED.product,
                age = EXCLUDED.age,
                gender = EXCLUDED.gender,
                username = EXCLUDED.username,
                full_name = EXCLUDED.full_name,
                created_at = NOW(),
                status = 'pending'
        """,
            message.from_user.id,
            data["product"],
            data["age"],
            data["gender"],
            message.from_user.username or "",
            message.from_user.full_name
        )

    await message.answer("дождись проверки администратора")
    await state.clear()

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{message.from_user.id}")
        ]]
    )

    text = (
        f"🔔 <b>Новая заявка</b>\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"🔗 @{message.from_user.username or 'нет'}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"📦 {data['product']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"⚧ Пол: {data['gender']}\n\n"
        f"👉 Ответить: <code>/send {message.from_user.id} текст</code>"
    )
    await bot.send_message(ADMIN_ID, text, reply_markup=admin_kb, parse_mode="HTML")


# ===== ✅ ОДОБРИТЬ =====
@dp.callback_query(F.data.startswith("approve_"))
async def approve_user(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'approved' WHERE user_id = $1", user_id)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Одобрено. Напиши:\n<code>/send {user_id} твой текст</code>",
        parse_mode="HTML"
    )
    await callback.answer()


# ===== ❌ ОТКЛОНИТЬ =====
@dp.callback_query(F.data.startswith("reject_"))
async def reject_user(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'rejected' WHERE user_id = $1", user_id)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Заявка {user_id} отклонена.")
    try:
        await bot.send_message(user_id, "❌ Заявка отклонена администратором.")
    except Exception as e:
        await callback.message.answer(f"⚠️ {e}")
    await callback.answer()


# ===== ЗАГЛУШКА-СЕРВЕР ДЛЯ RENDER =====
async def handle_ping(request):
    return web.Response(text="Bot is alive")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    await init_db()          # Подключаемся к БД
    await start_web_server() # Запускаем заглушку для Render
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
