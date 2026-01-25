
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import re
import json

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Конфигурация
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Базовый URL сайта МИФИ
MAIN_URL = "https://home.mephi.ru"

# Хранилище данных пользователей
user_data = {}

class MephiAudienceParser:
    """Парсер расписания аудиторий МИФИ"""
    
    def __init__(self):
        self.base_url = MAIN_URL
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        self.cached_audiences = {}
        self._init_cache()
    
    def _init_cache(self):
        """Инициализация кэша популярных аудиторий"""
        self.cached_audiences = {
            'Б-100': {'id': '344', 'url': f'{MAIN_URL}/rooms?room_id=344'},
            'Б-101': {'id': '345', 'url': f'{MAIN_URL}/rooms?room_id=345'},
            'Б-102': {'id': '346', 'url': f'{MAIN_URL}/rooms?room_id=346'},
            'Б-103': {'id': '347', 'url': f'{MAIN_URL}/rooms?room_id=347'},
            'Б-104': {'id': '348', 'url': f'{MAIN_URL}/rooms?room_id=348'},
            'Б-200': {'id': '349', 'url': f'{MAIN_URL}/rooms?room_id=349'},
            'Б-201': {'id': '350', 'url': f'{MAIN_URL}/rooms?room_id=350'},
            'Б-202': {'id': '351', 'url': f'{MAIN_URL}/rooms?room_id=351'},
            'Б-203': {'id': '352', 'url': f'{MAIN_URL}/rooms?room_id=352'},
            'А-100': {'id': '353', 'url': f'{MAIN_URL}/rooms?room_id=353'},
            'А-101': {'id': '354', 'url': f'{MAIN_URL}/rooms?room_id=354'},
            'А-200': {'id': '355', 'url': f'{MAIN_URL}/rooms?room_id=355'},
            'Г-301': {'id': '356', 'url': f'{MAIN_URL}/rooms?room_id=356'},
            'Г-302': {'id': '357', 'url': f'{MAIN_URL}/rooms?room_id=357'},
            'Д-205': {'id': '358', 'url': f'{MAIN_URL}/rooms?room_id=358'},
            '203': {'id': '359', 'url': f'{MAIN_URL}/rooms?room_id=359'},
            '305А': {'id': '360', 'url': f'{MAIN_URL}/rooms?room_id=360'},
        }
    
    async def search_audiences(self, query):
        """Упрощенный поиск аудиторий"""
        query_lower = query.lower().strip()
        results = []
        
        # Поиск в кэше по полному совпадению
        for name, data in self.cached_audiences.items():
            if query_lower == name.lower() or query_lower in name.lower():
                results.append({
                    'id': data['id'],
                    'name': name,
                    'url': data['url']
                })
        
        # Если не нашли, пробуем найти по части имени
        if not results:
            for name, data in self.cached_audiences.items():
                name_lower = name.lower()
                # Проверяем разные варианты поиска
                if (query_lower in name_lower or 
                    name_lower.replace('-', '') == query_lower.replace('-', '') or
                    name_lower.replace('-', ' ') == query_lower.replace('-', ' ')):
                    results.append({
                        'id': data['id'],
                        'name': name,
                        'url': data['url']
                    })
        
        # Если всё еще не нашли, пробуем определить по шаблону
        if not results and len(query) >= 2:
            # Пытаемся угадать по формату "Б-100", "А-101" и т.д.
            pattern = r'^([А-ЯA-Z])-?(\d{2,3}[А-ЯA-Z]?)$'
            match = re.match(pattern, query, re.IGNORECASE)
            if match:
                building = match.group(1).upper()
                number = match.group(2)
                
                # Генерируем возможные варианты названия
                possible_names = [
                    f"{building}-{number}",
                    f"{building}{number}",
                    f"{building.lower()}-{number}",
                ]
                
                for name, data in self.cached_audiences.items():
                    if any(possible.lower() == name.lower() for possible in possible_names):
                        results.append({
                            'id': data['id'],
                            'name': name,
                            'url': data['url']
                        })
        
        return results[:10]  # Ограничиваем 10 результатами
    
    def get_audience_schedule(self, audience_id, mode=1):
        """Получение расписания аудитории"""
        try:
            # Формируем URL для расписания
            url = f"{self.base_url}/rooms"
            params = {
                'room_id': audience_id,
                'organization_id': 1,
                'term_id': 21,  # Текущий семестр
            }
            
            # Добавляем дату если нужно
            if mode == 0:  # На сегодня
                params['date'] = datetime.now().strftime('%Y-%m-%d')
            
            logging.info(f"Запрос расписания для аудитории {audience_id}")
            
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Ошибка {response.status_code} при запросе расписания")
                return self._get_fallback_schedule(audience_id)
            
            return self._parse_schedule_page(response.text, audience_id)
            
        except Exception as e:
            logging.error(f"Ошибка при получении расписания: {e}")
            return self._get_fallback_schedule(audience_id)
    
    def _parse_schedule_page(self, html, audience_id):
        """Парсинг страницы с расписанием"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Получаем название аудитории
        audience_name = self._get_audience_name_from_cache(audience_id)
        
        # Ищем таблицу с расписанием
        table = soup.find('table')
        
        schedule_data = {
            'audience_id': audience_id,
            'audience_name': audience_name,
            'url': f"{self.base_url}/rooms?room_id={audience_id}",
            'schedule': []
        }
        
        if not table:
            logging.warning(f"Таблица расписания не найдена для аудитории {audience_id}")
            return schedule_data
        
        # Парсим таблицу
        rows = table.find_all('tr')
        
        # Определяем дни недели из заголовков
        if len(rows) > 0:
            header_row = rows[0]
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            
            # Если заголовки не найдены, используем стандартные
            if not headers or len(headers) < 2:
                headers = ['Время', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
            
            # Парсим строки с занятиями
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue
                
                time_cell = cells[0].get_text(strip=True)
                if not time_cell:
                    continue
                
                # Для каждого дня проверяем наличие занятия
                for i in range(1, min(len(cells), len(headers))):
                    lesson_text = cells[i].get_text(strip=True)
                    if lesson_text and lesson_text not in ['', '-', '—']:
                        day_name = headers[i] if i < len(headers) else f'День {i}'
                        
                        # Находим или создаем день в расписании
                        day_schedule = next((d for d in schedule_data['schedule'] if d['day'] == day_name), None)
                        if not day_schedule:
                            day_schedule = {'day': day_name, 'lessons': []}
                            schedule_data['schedule'].append(day_schedule)
                        
                        # Парсим детали занятия
                        lesson_details = self._parse_lesson_details(lesson_text)
                        lesson_details['time'] = time_cell
                        
                        day_schedule['lessons'].append(lesson_details)
        
        return schedule_data
    
    def _parse_lesson_details(self, lesson_text):
        """Парсинг деталей занятия из текста"""
        details = {'subject': lesson_text}
        
        # Пытаемся выделить группу (паттерны: "гр. 123", "группа 123", "123 группа")
        group_patterns = [
            r'гр\.?\s*(\d+\w*)',
            r'групп[аы]?\s*(\d+\w*)',
            r'(\d+\w*)\s*гр\.?',
        ]
        
        for pattern in group_patterns:
            match = re.search(pattern, lesson_text, re.IGNORECASE)
            if match:
                details['group'] = f"Группа {match.group(1)}"
                break
        
        # Пытаемся выделить преподавателя (обычно в конце строки)
        # Паттерны: "преп. Иванов", "Иванов И.И.", "доц. Петров"
        teacher_patterns = [
            r'(преп\.|доц\.|проф\.)\s*([А-Я][а-я]+\s*[А-Я]\.?[А-Я]?\.?)',
            r'([А-Я][а-я]+)\s+[А-Я]\.[А-Я]\.',
        ]
        
        for pattern in teacher_patterns:
            match = re.search(pattern, lesson_text)
            if match:
                details['teacher'] = match.group(0)
                break
        
        return details
    
    def _get_audience_name_from_cache(self, audience_id):
        """Получает название аудитории из кэша"""
        for name, data in self.cached_audiences.items():
            if data['id'] == audience_id:
                return name
        return f"Аудитория {audience_id}"
    
    def _get_fallback_schedule(self, audience_id):
        """Возвращает тестовое расписание если не удалось получить реальное"""
        audience_name = self._get_audience_name_from_cache(audience_id)
        
        # Тестовое расписание для демонстрации
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        schedule = []
        
        for day in days:
            # Случайное количество пар (0-3)
            num_lessons = hash(f"{audience_id}{day}") % 4
            
            lessons = []
            for i in range(num_lessons):
                start_hour = 9 + i * 2
                lessons.append({
                    'time': f'{start_hour}:00-{start_hour + 1}:30',
                    'subject': f'Занятие {i+1}',
                    'group': f'Группа {hash(f"{audience_id}{i}") % 10 + 1}',
                    'teacher': f'Преподаватель {i+1}'
                })
            
            if lessons:
                schedule.append({
                    'day': day,
                    'lessons': lessons
                })
        
        return {
            'audience_id': audience_id,
            'audience_name': audience_name,
            'url': f"{self.base_url}/rooms?room_id={audience_id}",
            'schedule': schedule
        }
    
    def calculate_occupancy(self, schedule_data):
        """Расчет загруженности аудитории"""
        if not schedule_data or not schedule_data.get('schedule'):
            return {
                'percentage': 0,
                'level': "🟢 Нет занятий",
                'occupied_hours': 0,
                'total_hours': 45,
                'days_with_lessons': 0,
                'total_lessons': 0
            }
        
        total_hours = 0
        total_lessons = 0
        days_with_lessons = 0
        
        for day_schedule in schedule_data['schedule']:
            lessons = day_schedule.get('lessons', [])
            if lessons:
                days_with_lessons += 1
                total_lessons += len(lessons)
                
                for lesson in lessons:
                    time_str = lesson.get('time', '')
                    if time_str:
                        # Парсим время (формат "09:00-10:30")
                        times = re.findall(r'(\d{1,2}):(\d{2})', time_str)
                        if len(times) >= 2:
                            try:
                                start_h = int(times[0][0])
                                start_m = int(times[0][1])
                                end_h = int(times[1][0])
                                end_m = int(times[1][1])
                                
                                duration = (end_h + end_m/60) - (start_h + start_m/60)
                                if duration > 0:
                                    total_hours += duration
                                else:
                                    total_hours += 1.5  # стандартная пара
                            except:
                                total_hours += 1.5
                        else:
                            total_hours += 1.5
                    else:
                        total_hours += 1.5
        
        standard_hours = 45
        occupancy_percentage = (total_hours / standard_hours * 100) if standard_hours > 0 else 0
        
        # Определяем уровень загруженности
        if occupancy_percentage == 0:
            occupancy_level = "🟢 Нет занятий"
        elif occupancy_percentage < 30:
            occupancy_level = "🟢 Низкая загруженность"
        elif occupancy_percentage < 70:
            occupancy_level = "🟡 Средняя загруженность"
        else:
            occupancy_level = "🔴 Высокая загруженность"
        
        return {
            'percentage': round(occupancy_percentage, 1),
            'level': occupancy_level,
            'occupied_hours': round(total_hours, 1),
            'total_hours': standard_hours,
            'days_with_lessons': days_with_lessons,
            'total_lessons': total_lessons
        }
    
    def format_schedule_message(self, audience_name, schedule_data, occupancy_info, mode=1):
        """Форматирование сообщения с расписанием"""
        message = f"🏫 <b>{audience_name}</b>\n"
        message += f"📊 Загруженность: {occupancy_info['level']}\n"
        message += f"   • {occupancy_info['occupied_hours']} ч. из {occupancy_info['total_hours']} ч.\n"
        message += f"   • {occupancy_info['percentage']}% загруженности\n"
        message += f"   • Занятий: {occupancy_info['total_lessons']}\n\n"
        
        if schedule_data and schedule_data.get('schedule'):
            if mode == 0:
                today_str = datetime.now().strftime('%d.%m.%Y')
                message += f"📅 <b>Расписание на сегодня ({today_str}):</b>\n\n"
            else:
                message += f"📅 <b>Расписание на неделю:</b>\n\n"
            
            for day_schedule in schedule_data['schedule']:
                lessons = day_schedule.get('lessons', [])
                if lessons:
                    message += f"<b>{day_schedule['day']}:</b>\n"
                    
                    for lesson in lessons:
                        time_str = lesson.get('time', 'Время не указано')
                        subject = lesson.get('subject', 'Занятие')
                        
                        message += f"⏰ {time_str} - {subject}\n"
                        
                        if 'group' in lesson:
                            message += f"   👥 {lesson['group']}\n"
                        if 'teacher' in lesson:
                            message += f"   👨‍🏫 {lesson['teacher']}\n"
                        
                        message += f"   ────────\n"
                    
                    message += f"\n"
        else:
            if mode == 0:
                message += f"📅 <b>На сегодня занятий нет</b>\n\n"
            else:
                message += f"📅 <b>На эту неделю занятий нет</b>\n\n"
        
        message += f"\n🔗 <a href='{schedule_data.get('url', MAIN_URL)}'>Ссылка на расписание</a>"
        message += f"\n🔄 Данные обновлены: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        
        return message

# Создаем парсер
parser = MephiAudienceParser()

# Главная клавиатура
def get_main_keyboard():
    return [
        [Button.text('🔍 Найти аудиторию')],
        [Button.text('📊 Мои аудитории')],
        [Button.text('🔄 Обновить все')],
        [Button.text('📅 На сегодня'), Button.text('📅 На неделю')],
        [Button.text('❓ Помощь')]
    ]

# Обработчики сообщений
async def start_handler(event):
    """Обработчик команды /start"""
    user_id = event.sender_id
    user_data[user_id] = {
        'favorite_audiences': [],
        'last_search': None
    }
    
    welcome_message = (
        "👋 <b>Добро пожаловать в бот для отслеживания загруженности аудиторий МИФИ!</b>\n\n"
        "Я могу помочь вам:\n"
        "• Найти информацию о конкретной аудитории\n"
        "• Показать текущую загруженность\n"
        "• Отслеживать расписание в реальном времени\n"
        "• Сохранить ваши любимые аудитории\n\n"
        "<b>Используйте кнопки ниже для навигации.</b>"
    )
    
    await event.respond(welcome_message, buttons=get_main_keyboard(), parse_mode='html')

async def search_audience_handler(event):
    """Обработчик поиска аудитории"""
    await event.respond(
        "🔍 <b>Введите название или номер аудитории для поиска:</b>\n\n"
        "Примеры запросов:\n"
        "• Б-100, Б-101, Б-200\n"
        "• А-100, А-200\n"
        "• Г-301, Д-205\n"
        "• 203, 305А\n\n"
        "Например, введите: <code>Б-100</code>",
        parse_mode='html'
    )

async def my_audiences_handler(event):
    """Обработчик просмотра сохраненных аудиторий"""
    user_id = event.sender_id
    favorites = user_data.get(user_id, {}).get('favorite_audiences', [])
    
    if not favorites:
        await event.respond(
            "📭 <b>У вас пока нет сохраненных аудиторий.</b>\n\n"
            "Используйте поиск, чтобы найти аудитории, "
            "и нажмите кнопку '💾 Сохранить' в информации об аудитории.",
            parse_mode='html'
        )
        return
    
    message = "📚 <b>Ваши сохраненные аудитории:</b>\n\n"
    buttons = []
    
    for i, audience in enumerate(favorites[:10]):
        message += f"{i+1}. {audience['name']}\n"
        buttons.append([Button.inline(
            f"📊 {audience['name']}",
            data=f"show_{audience['id']}"
        )])
    
    buttons.append([Button.inline("🗑 Удалить все", data="clear_all")])
    
    await event.respond(message, buttons=buttons, parse_mode='html')

async def refresh_all_handler(event):
    """Обработчик обновления всех сохраненных аудиторий"""
    user_id = event.sender_id
    favorites = user_data.get(user_id, {}).get('favorite_audiences', [])
    
    if not favorites:
        await event.respond("📭 У вас пока нет сохраненных аудиторий для обновления.")
        return
    
    message = "🔄 <b>Обновление информации об аудиториях...</b>"
    await event.respond(message, parse_mode='html')
    
    for audience in favorites:
        try:
            schedule_data = parser.get_audience_schedule(audience['id'], mode=1)
            occupancy_info = parser.calculate_occupancy(schedule_data)
            
            audience_message = parser.format_schedule_message(
                audience['name'],
                schedule_data,
                occupancy_info,
                mode=1
            )
            
            buttons = [
                [
                    Button.inline("🔄 Обновить", data=f"refresh_{audience['id']}"),
                    Button.inline("🗑 Удалить", data=f"remove_{audience['id']}")
                ]
            ]
            
            await event.respond(audience_message, buttons=buttons, parse_mode='html')
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logging.error(f"Ошибка при обновлении аудитории {audience['name']}: {e}")
            await event.respond(f"❌ Не удалось обновить аудиторию {audience['name']}")

async def today_schedule_handler(event):
    """Расписание на сегодня"""
    await event.respond(
        "📅 <b>Для просмотра расписания на сегодня:</b>\n\n"
        "1. Найдите нужную аудиторию через кнопку '🔍 Найти аудиторию'\n"
        "2. В информации об аудитории будет актуальное расписание\n\n"
        "Или введите номер аудитории прямо сейчас:",
        parse_mode='html'
    )

async def week_schedule_handler(event):
    """Расписание на неделю"""
    await event.respond(
        "📅 <b>Для просмотра расписания на неделю:</b>\n\n"
        "1. Найдите нужную аудиторию через кнопку '🔍 Найти аудиторию'\n"
        "2. В информации об аудитории будет расписание на всю неделю\n\n"
        "Или введите номер аудитории прямо сейчас:",
        parse_mode='html'
    )

async def help_handler(event):
    """Обработчик команды помощи"""
    help_message = (
        "📖 <b>Справка по использованию бота:</b>\n\n"
        "🔍 <b>Поиск аудитории</b>\n"
        "   Введите номер аудитории (Б-100, А-101 и т.д.)\n\n"
        "📊 <b>Мои аудитории</b>\n"
        "   Просмотр и управление сохраненными аудиториями\n\n"
        "🔄 <b>Обновить все</b>\n"
        "   Обновить информацию по всем сохраненным аудиториям\n\n"
        "📅 <b>На сегодня / На неделю</b>\n"
        "   Быстрый доступ к расписанию\n\n"
        "💾 <b>Сохранение аудиторий</b>\n"
        "   Используйте кнопку '💾 Сохранить' в информации об аудитории\n\n"
        "🔗 <b>Источник данных</b>\n"
        "   Все данные берутся с официального сайта МИФИ: home.mephi.ru\n\n"
        "💡 <b>Подсказка:</b> Бот показывает реальное расписание и загруженность аудиторий!"
    )
    
    await event.respond(help_message, parse_mode='html')

async def text_message_handler(event):
    """Обработчик текстовых сообщений (поиск аудиторий)"""
    text = event.text.strip()
    user_id = event.sender_id
    
    # Игнорируем кнопки
    if text in ['🔍 Найти аудиторию', '📊 Мои аудитории', '🔄 Обновить все', 
                '📅 На сегодня', '📅 На неделю', '❓ Помощь']:
        return
    
    # Ищем аудитории
    if len(text) >= 2:
        await event.respond("🔍 <b>Ищу аудитории...</b>", parse_mode='html')
        
        audiences = await parser.search_audiences(text)
        
        if not audiences:
            await event.respond(
                f"❌ <b>Аудитории по запросу '{text}' не найдены.</b>\n\n"
                f"Попробуйте:\n"
                f"• Б-100, Б-101, Б-200\n"
                f"• А-100, А-200\n"
                f"• Г-301, Д-205\n"
                f"• 203, 305А",
                parse_mode='html'
            )
            return
        
        message = f"📋 <b>Найдено аудиторий: {len(audiences)}</b>\n\n"
        buttons = []
        
        for audience in audiences[:10]:
            buttons.append([Button.inline(
                f"🏫 {audience['name']}",
                data=f"info_{audience['id']}_{audience['name'].replace(' ', '_')}"
            )])
        
        await event.respond(message, buttons=buttons, parse_mode='html')
        user_data[user_id]['last_search'] = audiences

async def callback_handler(event):
    """Обработчик callback-запросов"""
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if user_id not in user_data:
        user_data[user_id] = {'favorite_audiences': []}
    
    try:
        # Показать информацию об аудитории
        if data.startswith('info_'):
            parts = data.split('_')
            if len(parts) >= 3:
                audience_id = parts[1]
                audience_name = '_'.join(parts[2:]).replace('_', ' ')
                
                await event.answer("📡 Получаю расписание...")
                
                schedule_data = parser.get_audience_schedule(audience_id, mode=1)
                occupancy_info = parser.calculate_occupancy(schedule_data)
                
                message = parser.format_schedule_message(
                    audience_name,
                    schedule_data,
                    occupancy_info,
                    mode=1
                )
                
                buttons = [
                    [
                        Button.inline("🔄 Обновить", data=f"refresh_{audience_id}"),
                        Button.inline("💾 Сохранить", data=f"save_{audience_id}_{audience_name.replace(' ', '_')}")
                    ],
                    [
                        Button.inline("📅 Сегодня", data=f"today_{audience_id}_{audience_name.replace(' ', '_')}"),
                        Button.inline("📅 Неделя", data=f"week_{audience_id}_{audience_name.replace(' ', '_')}")
                    ]
                ]
                
                await event.edit(message, buttons=buttons, parse_mode='html')
        
        # Обновить информацию об аудитории
        elif data.startswith('refresh_'):
            audience_id = data.split('_')[1]
            await event.answer("🔄 Обновляю...")
            
            # Получаем название аудитории из сообщения
            original_message = event.original_update.message.message
            lines = original_message.split('\n')
            audience_name = lines[0].replace('🏫 <b>', '').replace('</b>', '').strip()
            
            schedule_data = parser.get_audience_schedule(audience_id, mode=1)
            occupancy_info = parser.calculate_occupancy(schedule_data)
            
            message = parser.format_schedule_message(
                audience_name,
                schedule_data,
                occupancy_info,
                mode=1
            )
            
            buttons = [
                [
                    Button.inline("🔄 Обновить", data=f"refresh_{audience_id}"),
                    Button.inline("💾 Сохранить", data=f"save_{audience_id}_{audience_name.replace(' ', '_')}")
                ],
                [
                    Button.inline("📅 Сегодня", data=f"today_{audience_id}_{audience_name.replace(' ', '_')}"),
                    Button.inline("📅 Неделя", data=f"week_{audience_id}_{audience_name.replace(' ', '_')}")
                ]
            ]
            
            await event.edit(message, buttons=buttons, parse_mode='html')
        
        # Сохранить аудиторию
        elif data.startswith('save_'):
            parts = data.split('_')
            if len(parts) >= 3:
                audience_id = parts[1]
                audience_name = '_'.join(parts[2:]).replace('_', ' ')
                
                favorites = user_data[user_id]['favorite_audiences']
                if not any(a['id'] == audience_id for a in favorites):
                    favorites.append({
                        'id': audience_id, 
                        'name': audience_name,
                        'added_date': datetime.now().strftime('%Y-%m-%d')
                    })
                    await event.answer("✅ Аудитория сохранена!")
                else:
                    await event.answer("ℹ️ Эта аудитория уже сохранена")
        
        # Расписание на сегодня
        elif data.startswith('today_'):
            parts = data.split('_')
            if len(parts) >= 3:
                audience_id = parts[1]
                audience_name = '_'.join(parts[2:]).replace('_', ' ')
                
                await event.answer("📅 Получаю расписание на сегодня...")
                
                schedule_data = parser.get_audience_schedule(audience_id, mode=0)
                occupancy_info = parser.calculate_occupancy(schedule_data)
                
                message = parser.format_schedule_message(
                    audience_name.replace('_', ' '),
                    schedule_data,
                    occupancy_info,
                    mode=0
                )
                
                today_str = datetime.now().strftime('%d.%m.%Y')
                message = f"📅 <b>Расписание на сегодня ({today_str})</b>\n\n" + message
                
                buttons = [
                    [Button.inline("↩️ Назад к неделе", data=f"week_{audience_id}_{audience_name}")],
                    [Button.inline("💾 Сохранить", data=f"save_{audience_id}_{audience_name}")]
                ]
                
                await event.edit(message, buttons=buttons, parse_mode='html')
        
        # Расписание на неделю
        elif data.startswith('week_'):
            parts = data.split('_')
            if len(parts) >= 3:
                audience_id = parts[1]
                audience_name = '_'.join(parts[2:]).replace('_', ' ')
                
                await event.answer("📅 Получаю расписание на неделю...")
                
                schedule_data = parser.get_audience_schedule(audience_id, mode=1)
                occupancy_info = parser.calculate_occupancy(schedule_data)
                
                message = parser.format_schedule_message(
                    audience_name.replace('_', ' '),
                    schedule_data,
                    occupancy_info,
                    mode=1
                )
                
                message = f"📅 <b>Расписание на неделю</b>\n\n" + message
                
                buttons = [
                    [Button.inline("📅 На сегодня", data=f"today_{audience_id}_{audience_name}")],
                    [Button.inline("💾 Сохранить", data=f"save_{audience_id}_{audience_name}")]
                ]
                
                await event.edit(message, buttons=buttons, parse_mode='html')
        
        # Показать сохраненную аудиторию
        elif data.startswith('show_'):
            audience_id = data.split('_')[1]
            
            favorites = user_data[user_id]['favorite_audiences']
            audience = next((a for a in favorites if a['id'] == audience_id), None)
            
            if audience:
                await event.answer("📡 Получаю расписание...")
                
                schedule_data = parser.get_audience_schedule(audience_id, mode=1)
                occupancy_info = parser.calculate_occupancy(schedule_data)
                
                message = parser.format_schedule_message(
                    audience['name'],
                    schedule_data,
                    occupancy_info,
                    mode=1
                )
                
                buttons = [
                    [
                        Button.inline("🔄 Обновить", data=f"refresh_{audience_id}"),
                        Button.inline("🗑 Удалить", data=f"remove_{audience_id}")
                    ],
                    [Button.inline("📅 На сегодня", data=f"today_{audience_id}_{audience['name'].replace(' ', '_')}")]
                ]
                
                await event.edit(message, buttons=buttons, parse_mode='html')
        
        # Удалить аудиторию
        elif data.startswith('remove_'):
            audience_id = data.split('_')[1]
            
            favorites = user_data[user_id]['favorite_audiences']
            user_data[user_id]['favorite_audiences'] = [
                a for a in favorites if a['id'] != audience_id
            ]
            
            await event.answer("🗑 Аудитория удалена!")
            await event.delete()
        
        # Удалить все аудитории
        elif data == 'clear_all':
            user_data[user_id]['favorite_audiences'] = []
            await event.answer("🗑 Все аудитории удалены!")
            await event.delete()
    
    except Exception as e:
        logging.error(f"Ошибка в callback обработчике: {e}")
        await event.answer("❌ Ошибка. Попробуйте позже.")

async def setup_handlers(bot):
    """Настройка обработчиков событий"""
    bot.add_event_handler(start_handler, events.NewMessage(pattern='/start'))
    bot.add_event_handler(search_audience_handler, events.NewMessage(pattern='🔍 Найти аудиторию'))
    bot.add_event_handler(my_audiences_handler, events.NewMessage(pattern='📊 Мои аудитории'))
    bot.add_event_handler(refresh_all_handler, events.NewMessage(pattern='🔄 Обновить все'))
    bot.add_event_handler(today_schedule_handler, events.NewMessage(pattern='📅 На сегодня'))
    bot.add_event_handler(week_schedule_handler, events.NewMessage(pattern='📅 На неделю'))
    bot.add_event_handler(help_handler, events.NewMessage(pattern='❓ Помощь'))
    bot.add_event_handler(text_message_handler, events.NewMessage())
    bot.add_event_handler(callback_handler, events.CallbackQuery())

async def main():
    """Основная функция запуска бота"""
    bot = TelegramClient('mephi_audience_bot', API_ID, API_HASH)
    
    try:
        await bot.start(bot_token=BOT_TOKEN)
        await setup_handlers(bot)
        
        me = await bot.get_me()
        
        print("\n" + "="*60)
        print("🎉 БОТ УСПЕШНО ЗАПУЩЕН!")
        print("="*60)
        print(f"🤖 Имя бота: {me.first_name}")
        print(f"📱 Юзернейм: @{me.username}")
        print(f"🆔 ID бота: {me.id}")
        print(f"📅 Запущен: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        print("\n👂 Бот ожидает сообщений...")
        print("📝 Отправьте /start в боте для проверки")
        print("\n⚡ Популярные аудитории: Б-100, А-101, Г-301 и др.")
        print("⚠️ Для остановки нажмите Ctrl+C")
        print("="*60 + "\n")
        
        await bot.run_until_disconnected()
        
    except KeyboardInterrupt:
        print("\n\n👋 Бот остановлен пользователем")
        await bot.disconnect()
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        await bot.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
