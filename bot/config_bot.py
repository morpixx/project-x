import os
import time
import requests
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, Message, ContentType
)
from tinydb import TinyDB, Query
from dotenv import load_dotenv

# Завантаження .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Забезпечення існування директорії та файлу з конфігами
config_dir = os.path.join(os.path.dirname(__file__), "../config")
os.makedirs(config_dir, exist_ok=True)
users_path = os.path.join(config_dir, "users.json")
if not os.path.exists(users_path):
    with open(users_path, "w", encoding="utf-8") as f:
        f.write("{}")

db = TinyDB(users_path)

# Клавіатура головного меню
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔐 Логін до акаунту")],
        [KeyboardButton(text="🧷 Канал-джерело"), KeyboardButton(text="📤 Канал-приймач")],
        [KeyboardButton(text="🧩 Шаблон парсингу"), KeyboardButton(text="🖋 Шаблон нового опису")],
        [KeyboardButton(text="🔢 Кількість постів"), KeyboardButton(text="🔁 Режим")],
        [KeyboardButton(text="✅ Підтвердити запуск")]
    ],
    resize_keyboard=True
)

# Клавіатура для відправлення контакту
contact_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Надіслати контакт", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Перевірка підписки
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.is_chat_member()
    except Exception:
        return False

def get_user(user_id: int) -> dict:
    User = Query()
    user = db.get(User.user_id == user_id)
    if not user:
        now = int(time.time())
        db.insert({"user_id": user_id, "first_seen": now, "is_subscribed": False, "config": {}})
        user = db.get(User.user_id == user_id)
    return user

def update_user_config(user_id: int, key: str, value) -> None:
    User = Query()
    user = get_user(user_id)
    config = user.get("config", {})
    config[key] = value
    db.update({"config": config}, User.user_id == user_id)

# Старт
@dp.message(F.text, F.text.regexp(r"^/start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    now = int(time.time())

    if user_id == OWNER_ID:
        await message.answer("Вітаю, власнику! Повний доступ.", reply_markup=main_kb)
        return

    first_seen = user["first_seen"]
    if now - first_seen < 86400:
        await message.answer("Ви у пробному періоді (1 день).", reply_markup=main_kb)
    else:
        if "phone" not in user.get("config", {}):
            await message.answer("Будь ласка, надішліть свій контакт (номер телефону) через кнопку нижче:", reply_markup=contact_kb)
        else:
            if await check_subscription(user_id):
                db.update({"is_subscribed": True}, Query().user_id == user_id)
                await message.answer("Дякую за підписку! Можна користуватись ботом.", reply_markup=main_kb)
            else:
                sub_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Підписатись", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
                    [InlineKeyboardButton(text="Я підписався", callback_data="check_sub")]
                ])
                await message.answer("Підпишіться на канал власника для продовження:", reply_markup=sub_kb)

# Перевірка підписки після натискання "Я підписався"
@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback_query):
    user_id = callback_query.from_user.id
    if await check_subscription(user_id):
        db.update({"is_subscribed": True}, Query().user_id == user_id)
        await bot.send_message(user_id, "Дякую за підписку! Можна користуватись ботом.", reply_markup=main_kb)
    else:
        await bot.send_message(user_id, "Ви ще не підписані. Перевірте ще раз.",
                               reply_markup=callback_query.message.reply_markup)
    await callback_query.answer()

# Логін до акаунту
@dp.message(F.text == "🔐 Логін до акаунту")
async def login_handler(message: Message):
    user = get_user(message.from_user.id)
    if "phone" not in user.get("config", {}):
        await message.answer("Щоб увійти, надішліть, будь ласка, свій контакт (номер телефону):", reply_markup=contact_kb)
    else:
        await message.answer(f"Ваш номер {user['config']['phone']} вже збережено. Тепер введіть отриманий код (наприклад, 3 4 5 6 7):", reply_markup=None)

# Обробник для отримання контакту від користувача
@dp.message(F.content_type == ContentType.CONTACT)
async def contact_handler(message: Message):
    contact = message.contact
    if contact and contact.phone_number:
        update_user_config(message.from_user.id, "phone", contact.phone_number)
        await message.answer(f"Ваш номер {contact.phone_number} збережено.", reply_markup=main_kb)
        await message.answer("Введіть код, який ви отримали (наприклад, 3 4 5 6 7):")
    else:
        await message.answer("Не вдалося отримати контакт. Спробуйте ще раз.", reply_markup=contact_kb)

# Обробник для введення коду (цифри через пробіл) з перевіркою через воркер
@dp.message(F.text.regexp(r"^(\d\s*){5,}$"))
async def code_handler(message: Message):
    raw_code = message.text.strip()
    code = "".join(raw_code.split())
    update_user_config(message.from_user.id, "auth_code", code)

    # Надсилаємо код воркеру для перевірки
    user_id = message.from_user.id
    user = get_user(user_id)
    phone = user.get("config", {}).get("phone")
    try:
        resp = requests.post(
            "http://localhost:8000/check_code",  # змініть на адресу вашого воркера
            json={"user_id": user_id, "phone": phone, "code": code},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                await message.answer("Код підтверджено! Реєстрація успішна.", reply_markup=main_kb)
            else:
                await message.answer(f"Код невірний. {data.get('message', 'Спробуйте ще раз.')}")
        else:
            await message.answer(f"Помилка від воркера: {resp.text}")
    except Exception as e:
        await message.answer(f"Не вдалося перевірити код: {e}")

# Канал-джерело
@dp.message(F.text == "🧷 Канал-джерело")
async def source_handler(message: Message):
    await message.answer("Введіть @username або ID каналу-джерела:")
    
@dp.message(F.text.regexp(r"^@?\w+$"))
async def source_input(message: Message):
    if "source_channel" not in get_user(message.from_user.id).get("config", {}):
        source = message.text.strip()
        update_user_config(message.from_user.id, "source_channel", source)
        await message.answer("Канал-джерело збережено.", reply_markup=main_kb)

# Канал-приймач
@dp.message(F.text == "📤 Канал-приймач")
async def target_handler(message: Message):
    await message.answer("Введіть @username або ID каналу-приймача:")

@dp.message(F.text.regexp(r"^@?\w+$"))
async def target_input(message: Message):
    if "target_channel" not in get_user(message.from_user.id).get("config", {}):
        target = message.text.strip()
        update_user_config(message.from_user.id, "target_channel", target)
        await message.answer("Канал-приймач збережено.", reply_markup=main_kb)

# Шаблон парсингу
@dp.message(F.text == "🧩 Шаблон парсингу")
async def parse_template_handler(message: Message):
    await message.answer("Введіть шаблон для пошуку у caption (наприклад: Ціна - [сума])")

@dp.message(F.text.regexp(r".*\[.*\].*"))
async def parse_template_input(message: Message):
    update_user_config(message.from_user.id, "parse_template", message.text.strip())
    await message.answer("Шаблон парсингу збережено.", reply_markup=main_kb)

# Шаблон нового опису
@dp.message(F.text == "🖋 Шаблон нового опису")
async def new_caption_handler(message: Message):
    await message.answer("Введіть шаблон нового опису (наприклад: Ценник: [1]+₴)")

@dp.message(F.text.regexp(r".*\[.*\].*"))
async def new_caption_input(message: Message):
    update_user_config(message.from_user.id, "new_caption_template", message.text.strip())
    await message.answer("Шаблон нового опису збережено.", reply_markup=main_kb)

# Кількість постів
@dp.message(F.text == "🔢 Кількість постів")
async def count_handler(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Всі", callback_data="count_all")],
        [InlineKeyboardButton(text="Ввести кількість", callback_data="count_custom")]
    ])
    await message.answer("Оберіть кількість постів для обробки:", reply_markup=kb)

@dp.callback_query(F.data.in_(["count_all", "count_custom"]))
async def count_callback_handler(callback_query):
    user_id = callback_query.from_user.id
    if callback_query.data == "count_all":
        update_user_config(user_id, "posts_count", "all")
        await bot.send_message(user_id, "Вибрано: всі пости.", reply_markup=main_kb)
    else:
        await bot.send_message(user_id, "Введіть кількість постів:")

@dp.message(F.text.regexp(r"^\d+$"))
async def count_input(message: Message):
    count = int(message.text.strip())
    update_user_config(message.from_user.id, "posts_count", count)
    await message.answer(f"Кількість постів: {count} збережено.", reply_markup=main_kb)

# Режим
@dp.message(F.text == "🔁 Режим")
async def mode_handler(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пересилка", callback_data="mode_forward")],
        [InlineKeyboardButton(text="Редагування", callback_data="mode_edit")]
    ])
    await message.answer("Оберіть режим роботи:", reply_markup=kb)

@dp.callback_query(F.data.in_(["mode_forward", "mode_edit"]))
async def mode_callback_handler(callback_query):
    user_id = callback_query.from_user.id
    mode = "forward" if callback_query.data == "mode_forward" else "edit"
    update_user_config(user_id, "mode", mode)
    await bot.send_message(user_id,
                           f"Режим '{'Пересилка' if mode == 'forward' else 'Редагування'}' збережено.",
                           reply_markup=main_kb)
    await callback_query.answer()

# Підтвердити запуск і відправка конфігурації через API
@dp.message(F.text == "✅ Підтвердити запуск")
async def confirm_handler(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    config = user.get("config", {})
    try:
        resp = requests.post(
            "http://localhost:8000/start_task",
            json={"user_id": user_id, "config": config},
            timeout=5
        )
        if resp.status_code == 200:
            await message.answer(
                f"Ваша конфігурація:\n{config}\n\nКонфігурацію відправлено воркеру. Запускаємо обробку!",
                reply_markup=main_kb)
        else:
            await message.answer("Не вдалося виконати операцію. Спробуйте пізніше.", reply_markup=main_kb)
    except Exception:
        await message.answer("Не вдалося виконати операцію. Спробуйте пізніше.", reply_markup=main_kb)

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))