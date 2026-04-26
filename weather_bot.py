import asyncio
import aiohttp
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# =============================================
#  TOKENLARNI SHU YERGA KIRITING
# =============================================
TELEGRAM_TOKEN = "8409164621:AAEvHfshy9qEnI2iZY8R7Sxi1fayBeC-XhY"
WEATHER_API_KEY = "af7ce77d7cc685f684d3d3981cd6ac78"
# =============================================

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DATA_FILE = "users_data.json"

# Cache — API ni qayta-qayta chaqirmaslik uchun (10 daqiqa)
weather_cache = {}
CACHE_SECONDS = 0

WEATHER_EMOJI = {
    "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️",
    "Drizzle": "🌦️", "Thunderstorm": "⛈️", "Snow": "❄️",
    "Mist": "🌫️", "Fog": "🌫️", "Haze": "🌫️",
}

class CityState(StatesGroup):
    waiting_city = State()
    changing_city = State()

# ─── Ma'lumotlar bazasi ───────────────────────────────────────────────────────

users_db = {}

def load_data():
    global users_db
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            users_db = json.load(f)

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users_db, f, ensure_ascii=False, indent=2)

def get_user(chat_id):
    uid = str(chat_id)
    if uid not in users_db:
        users_db[uid] = {"city": None, "auto_morning": False}
    return users_db[uid]

def set_city(chat_id, city):
    get_user(chat_id)["city"] = city
    save_data()

def set_auto(chat_id, val):
    get_user(chat_id)["auto_morning"] = val
    save_data()

# ─── API (async + cache) ──────────────────────────────────────────────────────

async def get_current(city):
    key = f"current_{city.lower()}"
    now = datetime.now().timestamp()
    if key in weather_cache and now - weather_cache[key]["time"] < CACHE_SECONDS:
        return weather_cache[key]["data"]
    async with aiohttp.ClientSession() as s:
        async with s.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "uz"},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
    weather_cache[key] = {"data": data, "time": now}
    return data

async def get_forecast(city, days=5):
    key = f"forecast_{city.lower()}_{days}"
    now = datetime.now().timestamp()
    if key in weather_cache and now - weather_cache[key]["time"] < CACHE_SECONDS:
        return weather_cache[key]["data"]
    async with aiohttp.ClientSession() as s:
        async with s.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "uz", "cnt": days * 8},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
    weather_cache[key] = {"data": data, "time": now}
    return data

# ─── Formatlash ───────────────────────────────────────────────────────────────

def fmt_current(data):
    if not data or data.get("cod") != 200:
        return None
    emoji = WEATHER_EMOJI.get(data["weather"][0]["main"], "🌤️")
    return (
        f"{emoji} *{data['name']}, {data['sys']['country']}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌡 Harorat: *{round(data['main']['temp'])}°C* "
        f"(his: {round(data['main']['feels_like'])}°C)\n"
        f"💧 Namlik: {data['main']['humidity']}%\n"
        f"💨 Shamol: {data['wind']['speed']} m/s\n"
        f"☁️ {data['weather'][0]['description'].capitalize()}\n"
        f"🕐 {datetime.now().strftime('%H:%M')}"
    )

def fmt_forecast(data, days):
    if not data or data.get("cod") != "200":
        return None
    city = data["city"]["name"]
    country = data["city"]["country"]
    lines = [f"📅 *{city}, {country}* — {days} kunlik\n━━━━━━━━━━━━━━━━━━"]
    day_names = ["Dush", "Sesh", "Chor", "Pay", "Jum", "Shan", "Yak"]
    seen = {}
    for item in data["list"]:
        date, hour = item["dt_txt"].split(" ")
        if date not in seen and hour == "12:00:00":
            seen[date] = item
    for item in data["list"]:
        date = item["dt_txt"].split(" ")[0]
        if date not in seen:
            seen[date] = item
    for i, (date, item) in enumerate(sorted(seen.items())[:days]):
        dt = datetime.strptime(date, "%Y-%m-%d")
        emoji = WEATHER_EMOJI.get(item["weather"][0]["main"], "🌤️")
        if i == 0:
            label = "Bugun"
        elif i == 1:
            label = "Ertaga"
        else:
            label = f"{day_names[dt.weekday()]} {dt.strftime('%d.%m')}"
        lines.append(
            f"{emoji} *{label}*: {round(item['main']['temp_min'])}°C ~ "
            f"{round(item['main']['temp_max'])}°C — "
            f"{item['weather'][0]['description'].capitalize()}"
        )
    return "\n".join(lines)

# ─── Klaviaturalar ────────────────────────────────────────────────────────────

def main_kb():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="🌤 Hozirgi"), KeyboardButton(text="📅 5 kunlik")],
        [KeyboardButton(text="📆 7 kunlik"), KeyboardButton(text="🏙 Shahar")],
        [KeyboardButton(text="⏰ Avtomatik"), KeyboardButton(text="ℹ️ Info")],
    ])

def auto_kb(enabled):
    label = "🔴 O'chirish" if enabled else "🟢 Yoqish (07:00)"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data="auto_off" if enabled else "auto_on")
    ]])

# ─── Handlerlar ───────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def start(msg: Message):
    user = get_user(msg.chat.id)
    name = msg.from_user.first_name or "Do'stim"
    city_info = f"📍 Saqlangan shahar: *{user['city']}*" if user["city"] else "📍 Boshlash uchun shahar nomini yuboring:"
    await msg.answer(
        f"👋 Salom, *{name}*! Men ob-havo botiman 🌤\n\n{city_info}",
        parse_mode="Markdown", reply_markup=main_kb()
    )

@dp.message(F.text == "🌤 Hozirgi")
async def btn_current(msg: Message):
    user = get_user(msg.chat.id)
    city = user.get("city")
    if not city:
        await msg.answer("📍 Shahar nomini kiriting:")
        return
    try:
        data = await get_current(city)
        text = fmt_current(data)
        await msg.answer(text or "❌ Xatolik.", parse_mode="Markdown", reply_markup=main_kb())
    except Exception:
        await msg.answer("❌ Internet xatoligi.", reply_markup=main_kb())

@dp.message(F.text == "📅 5 kunlik")
async def btn_5day(msg: Message):
    await send_forecast_msg(msg, 5)

@dp.message(F.text == "📆 7 kunlik")
async def btn_7day(msg: Message):
    await send_forecast_msg(msg, 7)

@dp.message(F.text == "🏙 Shahar")
async def btn_city(msg: Message, state: FSMContext):
    await state.set_state(CityState.changing_city)
    await msg.answer("🏙 Yangi shahar nomini kiriting:")

@dp.message(F.text == "⏰ Avtomatik")
async def btn_auto(msg: Message):
    user = get_user(msg.chat.id)
    enabled = user.get("auto_morning", False)
    holat = "✅ Yoqilgan" if enabled else "❌ O'chirilgan"
    city = user.get("city") or "Tanlanmagan"
    await msg.answer(
        f"⏰ *Avtomatik xabar*\nHar kuni 07:00 da yuboriladi.\n\n"
        f"🏙 Shahar: *{city}*\nHolat: {holat}",
        parse_mode="Markdown", reply_markup=auto_kb(enabled)
    )

@dp.message(F.text == "ℹ️ Info")
async def btn_info(msg: Message):
    user = get_user(msg.chat.id)
    city = user.get("city") or "Tanlanmagan"
    holat = "✅ Yoqilgan" if user.get("auto_morning") else "❌ O'chirilgan"
    await msg.answer(
        f"ℹ️ *Sozlamalar:*\n\n🏙 Shahar: *{city}*\n⏰ Avtomatik: {holat}",
        parse_mode="Markdown", reply_markup=main_kb()
    )

@dp.message(CityState.changing_city)
async def process_change(msg: Message, state: FSMContext):
    city = msg.text.strip()
    try:
        data = await get_current(city)
        if data.get("cod") == 200:
            set_city(msg.chat.id, city)
            await state.clear()
            await msg.answer(f"✅ Shahar *{data['name']}* ga o'zgartirildi!", parse_mode="Markdown", reply_markup=main_kb())
        else:
            await msg.answer("❌ Shahar topilmadi. Qaytadan kiriting:")
    except Exception:
        await msg.answer("❌ Xatolik. Qaytadan kiriting:")

@dp.message(CityState.waiting_city)
async def process_new_city(msg: Message, state: FSMContext):
    city = msg.text.strip()
    try:
        data = await get_current(city)
        if data.get("cod") == 200:
            set_city(msg.chat.id, city)
            await state.clear()
            text = fmt_current(data)
            await msg.answer(f"✅ *{data['name']}* saqlandi!\n\n{text}", parse_mode="Markdown", reply_markup=main_kb())
        else:
            await msg.answer("❌ Shahar topilmadi. Qaytadan kiriting:")
    except Exception:
        await msg.answer("❌ Xatolik. Qaytadan kiriting:")

@dp.callback_query(F.data.in_({"auto_on", "auto_off"}))
async def callback_auto(call: CallbackQuery):
    enabled = call.data == "auto_on"
    user = get_user(call.message.chat.id)
    if enabled and not user.get("city"):
        await call.answer("❌ Avval shahar tanlang!", show_alert=True)
        return
    set_auto(call.message.chat.id, enabled)
    holat = "✅ Yoqildi! Har kuni 07:00 da yuboriladi ☀️" if enabled else "❌ O'chirildi."
    await call.message.edit_text(holat, reply_markup=auto_kb(enabled))
    await call.answer()

@dp.message()
async def text_handler(msg: Message):
    city = msg.text.strip()
    try:
        data = await get_current(city)
        if data.get("cod") == 200:
            set_city(msg.chat.id, city)
            text = fmt_current(data)
            await msg.answer(f"✅ *{data['name']}* saqlandi!\n\n{text}", parse_mode="Markdown", reply_markup=main_kb())
        else:
            await msg.answer("❓ Shahar topilmadi. Tugmalardan foydalaning.", reply_markup=main_kb())
    except Exception:
        await msg.answer("❌ Xatolik yuz berdi.", reply_markup=main_kb())

# ─── Yordamchi ────────────────────────────────────────────────────────────────

async def send_forecast_msg(msg: Message, days: int):
    user = get_user(msg.chat.id)
    city = user.get("city")
    if not city:
        await msg.answer("📍 Avval shahar kiriting.")
        return
    try:
        data = await get_forecast(city, days)
        text = fmt_forecast(data, days)
        await msg.answer(text or "❌ Prognoz topilmadi.", parse_mode="Markdown", reply_markup=main_kb())
    except Exception:
        await msg.answer("❌ Internet xatoligi.", reply_markup=main_kb())

# ─── Inline query (@obhavottbot Toshkent) ────────────────────────────────────

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    city = query.query.strip()
    if not city:
        user = get_user(query.from_user.id)
        city = user.get("city", "")
    if not city:
        await query.answer(
            results=[],
            switch_pm_text="📍 Avval botda shahar tanlang",
            switch_pm_parameter="start",
            cache_time=1
        )
        return
    try:
        current_data = await get_current(city)
        if current_data.get("cod") != 200:
            await query.answer(results=[
                InlineQueryResultArticle(
                    id="notfound",
                    title="❌ Shahar topilmadi",
                    description=f"'{city}' shahri topilmadi",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ *{city}* shahri topilmadi.",
                        parse_mode="Markdown"
                    )
                )
            ], cache_time=1)
            return

        results = []
        current_text = fmt_current(current_data)
        results.append(InlineQueryResultArticle(
            id="current",
            title=f"🌤 Hozirgi — {current_data['name']}",
            description=f"{round(current_data['main']['temp'])}°C, {current_data['weather'][0]['description'].capitalize()}",
            input_message_content=InputTextMessageContent(
                message_text=current_text, parse_mode="Markdown"
            )
        ))

        forecast5 = await get_forecast(city, 5)
        text5 = fmt_forecast(forecast5, 5)
        if text5:
            results.append(InlineQueryResultArticle(
                id="forecast5",
                title=f"📅 5 kunlik — {current_data['name']}",
                description="5 kunlik ob-havo prognozu",
                input_message_content=InputTextMessageContent(
                    message_text=text5, parse_mode="Markdown"
                )
            ))

        forecast7 = await get_forecast(city, 7)
        text7 = fmt_forecast(forecast7, 7)
        if text7:
            results.append(InlineQueryResultArticle(
                id="forecast7",
                title=f"📆 7 kunlik — {current_data['name']}",
                description="7 kunlik ob-havo prognozu",
                input_message_content=InputTextMessageContent(
                    message_text=text7, parse_mode="Markdown"
                )
            ))

        await query.answer(results=results, cache_time=300)
    except Exception as e:
        print(f"Inline xato: {e}")
        await query.answer(results=[], cache_time=1)

# ─── Avtomatik 07:00 xabar ────────────────────────────────────────────────────

async def morning_task():
    sent_today = set()
    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if now.strftime("%H:%M") == "07:00":
            for uid, udata in list(users_db.items()):
                key = f"{uid}_{today}"
                if udata.get("auto_morning") and udata.get("city") and key not in sent_today:
                    try:
                        data = await get_current(udata["city"])
                        text = fmt_current(data)
                        if text:
                            await bot.send_message(int(uid), f"🌅 *Xayrli tong!*\n\n{text}", parse_mode="Markdown")
                            sent_today.add(key)
                    except Exception as e:
                        print(f"Auto xabar xatosi {uid}: {e}")
            await asyncio.sleep(61)
        else:
            if now.strftime("%H:%M") == "00:01":
                sent_today.clear()
            await asyncio.sleep(20)

# ─── Ishga tushirish ──────────────────────────────────────────────────────────

async def main():
    load_data()
    asyncio.create_task(morning_task())
    print("✅ Bot ishlamoqda (async)...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())