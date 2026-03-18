import asyncio
import logging
import ssl
import certifi
import os
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import json

# Отключаем предупреждения SSL
os.environ['PYTHONHTTPSVERIFY'] = '0'
requests.packages.urllib3.disable_warnings()

from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Настройки
API_TOKEN =  '8391343876:AAFixdgiO-SFvazFfxNESRBtzbVoqivfx1k'  # <--- ВСТАВЬТЕ СВОЙ ТОКЕН

# Инициализация бота
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Логирование
logging.basicConfig(level=logging.INFO)

# Класс парсера МИФИ
class MephiParser:
    def __init__(self):
        self.base_url = "https://home.mephi.ru"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.verify = False
        
    def search_audiences(self, query):
        """Поиск аудиторий по запросу"""
        try:
            url = f"{self.base_url}/rooms"
            response = self.session.get(url, timeout=10, verify=False)
            
            if response.status_code == 200:
                audiences = self._parse_audiences_list(response.text, query)
                if audiences:
                    return audiences
            return []
        except Exception as e:
            print(f"Ошибка поиска: {e}")
            return []
    
    def _parse_audiences_list(self, html, query):
        """Парсинг списка аудиторий"""
        soup = BeautifulSoup(html, 'html.parser')
        audiences = []
        query = query.lower().replace('-', '').strip()
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            if '/rooms/' in href and text:
                match = re.search(r'/rooms/(\d+)', href)
                if match:
                    audience_id = match.group(1)
                    text_lower = text.lower().replace('-', '')
                    if query in text_lower or query in audience_id:
                        audiences.append({
                            'id': audience_id,
                            'name': text,
                            'url': f"{self.base_url}{href}"
                        })
        
        return audiences
    
    def get_audience_schedule(self, audience_id):
        """Получение расписания аудитории"""
        try:
            url = f"{self.base_url}/rooms/{audience_id}"
            response = self.session.get(url, timeout=10, verify=False)
            
            if response.status_code == 200:
                schedule = self._parse_schedule_page(response.text, audience_id, url)
                if schedule and schedule.get('schedule'):
                    return schedule
            return None
        except Exception as e:
            print(f"Ошибка получения расписания: {e}")
            return None
    
    def _parse_schedule_page(self, html, audience_id, page_url):
        """Парсинг страницы с расписанием"""
        soup = BeautifulSoup(html, 'html.parser')
        
        audience_name = self._extract_audience_name(soup, audience_id)
        
        schedule_data = {
            'audience_id': audience_id,
            'audience_name': audience_name,
            'url': page_url,
            'schedule': []
        }
        
        # Ищем расписание в таблицах
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            current_day = None
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                
                row_text = row.get_text(strip=True).lower()
                
                for day in ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']:
                    if day in row_text and len(row_text) < 30:
                        current_day = day.capitalize()
                        break
                
                if current_day and len(cells) >= 2:
                    lesson_text = row.get_text(strip=True, separator=' ')
                    if self._is_valid_lesson(lesson_text):
                        self._add_lesson_to_schedule(schedule_data, current_day, lesson_text)
        
        return schedule_data if schedule_data['schedule'] else None
    
    def _extract_audience_name(self, soup, audience_id):
        """Извлечение названия аудитории"""
        for tag in soup.find_all(['h1', 'h2', 'h3']):
            text = tag.get_text(strip=True)
            if text and ('ауд' in text.lower() or audience_id in text):
                return text
        return f"Аудитория {audience_id}"
    
    def _add_lesson_to_schedule(self, schedule_data, day, lesson_text):
        """Добавление занятия в расписание"""
        for entry in schedule_data['schedule']:
            if entry['day'].lower() == day.lower():
                if lesson_text not in entry['lessons']:
                    entry['lessons'].append(lesson_text)
                return
        
        schedule_data['schedule'].append({
            'day': day,
            'lessons': [lesson_text]
        })
    
    def _is_valid_lesson(self, text):
        """Проверка валидности занятия"""
        if not text or len(text) < 10:
            return False
        
        text_lower = text.lower()
        exclude_words = ['понедельник', 'вторник', 'среда', 'четверг', 
                        'пятница', 'суббота', 'меню', 'навигация']
        
        for word in exclude_words:
            if word in text_lower and len(text) < 30:
                return False
        
        has_time = bool(re.search(r'\d{1,2}[:.]\d{2}', text))
        lesson_keywords = ['лекция', 'семинар', 'практика', 'лабораторная', 'пара']
        
        return has_time or any(keyword in text_lower for keyword in lesson_keywords)
    
    def calculate_occupancy(self, schedule_data):
        """Расчет загруженности"""
        if not schedule_data or not schedule_data.get('schedule'):
            return {
                'percentage': 0,
                'level': "⚪ Нет данных",
                'occupied_hours': 0,
                'total_hours': 54,
                'days_with_lessons': 0,
                'total_lessons': 0,
                'today_lessons': 0
            }
        
        total_lessons = 0
        days_with_lessons = 0
        today_lessons = 0
        
        today = datetime.now().weekday()
        days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
        today_name = days[today] if today < 6 else 'воскресенье'
        
        for day in schedule_data['schedule']:
            lessons_count = len(day.get('lessons', []))
            if lessons_count > 0:
                days_with_lessons += 1
                total_lessons += lessons_count
                
                if day['day'].lower() == today_name:
                    today_lessons = lessons_count
        
        occupied_hours = total_lessons * 1.5
        total_hours = 54
        occupancy_percentage = min((occupied_hours / total_hours) * 100, 100)
        
        if today_lessons > 0:
            level = "🟢 Низкая" if occupancy_percentage < 30 else "🟡 Средняя" if occupancy_percentage < 70 else "🔴 Высокая"
        else:
            level = "🟡 Есть занятия (не сегодня)" if total_lessons > 0 else "🟢 Нет занятий"
        
        return {
            'percentage': round(occupancy_percentage, 1),
            'level': level,
            'occupied_hours': round(occupied_hours, 1),
            'total_hours': total_hours,
            'days_with_lessons': days_with_lessons,
            'total_lessons': total_lessons,
            'today_lessons': today_lessons
        }
    
    def format_schedule_message(self, audience_name, schedule_data, occupancy_info):
        """Форматирование сообщения"""
        today = datetime.now().weekday()
        days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
        today_name = days[today]
        
        message = f"🏫 <b>{audience_name}</b>\n\n"
        message += f"📊 <b>Загруженность:</b> {occupancy_info['level']}\n"
        
        if occupancy_info['today_lessons'] > 0:
            message += f"   • <b>Сегодня ({today_name.capitalize()}):</b> {occupancy_info['today_lessons']} занятий\n"
        else:
            message += f"   • <b>Сегодня ({today_name.capitalize()}):</b> свободно 🆓\n"
        
        message += f"   • Всего занятий: {occupancy_info['total_lessons']}\n\n"
        
        if schedule_data.get('schedule'):
            message += f"📅 <b>Расписание на неделю:</b>\n\n"
            
            day_order = {'понедельник': 1, 'вторник': 2, 'среда': 3, 'четверг': 4, 'пятница': 5, 'суббота': 6}
            sorted_schedule = sorted(schedule_data['schedule'], 
                                   key=lambda x: day_order.get(x['day'].lower(), 99))
            
            for day in sorted_schedule:
                day_lower = day['day'].lower()
                if day_lower == today_name:
                    day_display = f"🔴 <b>{day['day']} (СЕГОДНЯ)</b>"
                else:
                    day_display = f"📆 <b>{day['day']}</b>"
                
                message += f"{day_display}:\n"
                
                if day.get('lessons'):
                    for i, lesson in enumerate(day['lessons'][:5], 1):
                        clean_lesson = re.sub(r'\s+', ' ', lesson).strip()
                        message += f"   {i}. {clean_lesson}\n"
                else:
                    message += f"   🆓 Свободно\n"
                message += f"\n"
        else:
            message += f"📅 <b>Расписание:</b>\n   📭 Расписание не найдено\n\n"
        
        message += f"🔗 <a href='{schedule_data.get('url', 'https://home.mephi.ru')}'>Открыть на сайте</a>\n"
        message += f"📅 <i>Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
        
        return message

# Инициализация парсера
parser = MephiParser()

# Состояния
class SearchStates(StatesGroup):
    waiting_for_audience = State()

# ========== ОБРАБОТЧИКИ КОМАНД ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    print(f"Получена команда /start от пользователя {message.from_user.id}")
    welcome_text = """
🎓 <b>Добро пожаловать в бот расписания МИФИ!</b>

Я помогу вам узнать расписание занятий в аудиториях.

📌 <b>Примеры запросов:</b>
• Б-100
• А-305
• Г-401

Просто напишите номер аудитории, и я покажу расписание!

🔍 <b>Команды:</b>
/search - поиск аудитории
    """
    await message.answer(welcome_text, parse_mode='HTML')

@dp.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext):
    """Обработчик команды /search"""
    await message.answer("🔍 Введите номер аудитории (например, Б-100):")
    await state.set_state(SearchStates.waiting_for_audience)

@dp.message(SearchStates.waiting_for_audience)
async def process_search(message: Message, state: FSMContext):
    """Обработка поиска после команды /search"""
    query = message.text.strip()
    await state.clear()
    
    loading_msg = await message.answer("🔍 Ищу аудиторию...")
    
    # Ищем аудитории
    audiences = parser.search_audiences(query)
    
    if audiences:
        await loading_msg.delete()
        
        if len(audiences) == 1:
            # Если одна аудитория - показываем сразу
            await show_audience_schedule(message, audiences[0]['id'])
        else:
            # Если несколько - предлагаем выбрать
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            for aud in audiences[:5]:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text=aud['name'], callback_data=f"aud_{aud['id']}")
                ])
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
            ])
            
            await message.answer(
                f"🔍 Найдено аудиторий: {len(audiences)}\nВыберите нужную:",
                reply_markup=keyboard
            )
    else:
        await loading_msg.delete()
        await message.answer(
            f"❌ Аудитория '{query}' не найдена.\n\n"
            f"Попробуйте другой номер или проверьте правильность ввода."
        )

@dp.message()
async def handle_message(message: Message):
    """Обработка обычных сообщений"""
    query = message.text.strip()
    
    # Проверяем, похоже ли сообщение на номер аудитории
    if re.match(r'^[А-ЯA-Z]-?\d', query, re.I):
        loading_msg = await message.answer("🔍 Ищу аудиторию...")
        
        # Ищем аудитории
        audiences = parser.search_audiences(query)
        
        if audiences:
            await loading_msg.delete()
            
            if len(audiences) == 1:
                # Если одна аудитория - показываем сразу
                await show_audience_schedule(message, audiences[0]['id'])
            else:
                # Если несколько - предлагаем выбрать
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                for aud in audiences[:5]:
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(text=aud['name'], callback_data=f"aud_{aud['id']}")
                    ])
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
                ])
                
                await message.answer(
                    f"🔍 Найдено несколько аудиторий. Выберите нужную:",
                    reply_markup=keyboard
                )
        else:
            await loading_msg.delete()
            await message.answer(
                f"❌ Аудитория '{query}' не найдена.\n\n"
                f"Используйте /search для поиска."
            )
    else:
        # Если сообщение не похоже на аудиторию
        await message.answer(
            "❓ Я не понял запрос.\n\n"
            "🔍 Введите номер аудитории (например, Б-100) или используйте команду /search"
        )

@dp.callback_query()
async def process_callback(callback: CallbackQuery):
    """Обработка нажатий на кнопки"""
    await callback.answer()
    
    if callback.data == "cancel":
        await callback.message.delete()
        await callback.message.answer("❌ Поиск отменен")
        return
    
    if callback.data.startswith("aud_"):
        audience_id = callback.data.replace("aud_", "")
        await show_audience_schedule(callback.message, audience_id, callback)

async def show_audience_schedule(message, audience_id, callback=None):
    """Показать расписание аудитории"""
    if callback:
        await callback.message.edit_text("⏳ Загружаю расписание с сайта...")
    else:
        loading_msg = await message.answer("⏳ Загружаю расписание с сайта...")
    
    # Получаем расписание
    schedule = parser.get_audience_schedule(audience_id)
    
    if schedule:
        # Рассчитываем загруженность
        occupancy = parser.calculate_occupancy(schedule)
        
        # Форматируем сообщение
        schedule_text = parser.format_schedule_message(
            schedule['audience_name'],
            schedule,
            occupancy
        )
        
        # Создаем клавиатуру для обновления
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"aud_{audience_id}")],
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search")]
        ])
        
        if callback:
            await callback.message.edit_text(
                schedule_text,
                reply_markup=keyboard,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        else:
            await loading_msg.delete()
            await message.answer(
                schedule_text,
                reply_markup=keyboard,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
    else:
        error_text = f"❌ Не удалось загрузить расписание для аудитории"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search")]
        ])
        
        if callback:
            await callback.message.edit_text(error_text, reply_markup=keyboard)
        else:
            await loading_msg.delete()
            await message.answer(error_text, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == 'new_search')
async def new_search(callback: CallbackQuery, state: FSMContext):
    """Начать новый поиск"""
    await callback.message.delete()
    await callback.message.answer("🔍 Введите номер аудитории:")
    await state.set_state(SearchStates.waiting_for_audience)

# ========== ЗАПУСК БОТА ==========
async def main():
    print("🤖 Бот расписания МИФИ запущен...")
    print(f"✅ Бот @{(await bot.me()).username} готов к работе!")
    print("📡 Используется реальный сайт: https://home.mephi.ru")
    print("✅ Жду команды...")
    
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n❌ Бот остановлен")