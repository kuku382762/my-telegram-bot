import asyncio
import os
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
# ===================================

if not BOT_TOKEN:
    raise ValueError("Не задан BOT_TOKEN!")
if not ADMIN_ID:
    raise ValueError("Не задан ADMIN_ID!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

users_data = {}


class OrderFlow(StatesGroup):
    waiting_age = State()
    waiting_gender = State()


def get_products_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="100 рублей за кружок")],
            [KeyboardButton(text="50 рублей за гс")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери услугу..."
    )


@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Выбери услугу:", reply_markup=get_products_kb())


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


@dp.message(F.text == "100 рублей за кружок")
async def choose_circle(message: Message, state: FSMContext):
    await state.update_data(product="100 рублей за кружок")
    await state.set_state(OrderFlow.waiting_age)
    await message.answer("сколько тебе лет?", reply_markup=ReplyKeyboardRemove())


@dp.message(F.text == "50 рублей за гс")
async def choose_gs(message: Message, state: FSMContext):
    await state.update_data(product="50 рублей за гс")
    await state.set_state(OrderFlow.waiting_age)
    await message.answer("сколько тебе лет?", reply_markup=ReplyKeyboardRemove())


@dp.message(OrderFlow.waiting_age)
async def get_age(message: Message, state: FSMContext):
    await state.update_data(age=message.text)
    await state.set_state(OrderFlow.waiting_gender)
    await message.answer("напиши свой пол")


@dp.message(OrderFlow.waiting_gender)
async def get_gender(message: Message, state: FSMContext):
    await state.update_data(gender=message.text)
    data = await state.get_data()

    users_data[message.from_user.id] = {
        "product": data["product"],
        "age": data["age"],
        "gender": data["gender"],
        "username": message.from_user.username or "нет",
        "name": message.from_user.full_name,
    }

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


@dp.callback_query(F.data.startswith("approve_"))
async def approve_user(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Одобрено. Напиши:\n<code>/send {user_id} твой текст</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("reject_"))
async def reject_user(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Заявка {user_id} отклонена.")
    try:
        await bot.send_message(user_id, "❌ Заявка отклонена администратором.")
    except Exception as e:
        await callback.message.answer(f"⚠️ {e}")
    await callback.answer()


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
    await start_web_server()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
