import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import json

class RealMephiParser:
    """Реальный парсер расписания аудиторий МИФИ"""
    
    def __init__(self):
        self.base_url = "https://home.mephi.ru"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    
    def get_all_audiences(self):
        """Получение списка всех аудиторий"""
        try:
            url = f"{self.base_url}/rooms?organization_id=1&term_id=21"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                return self._parse_audiences_list(soup)
            else:
                print(f"Ошибка HTTP {response.status_code}")
                return []
                
        except Exception as e:
            print(f"Ошибка при получении списка аудиторий: {e}")
            return []
    
    def _parse_audiences_list(self, soup):
        """Парсинг списка аудиторий"""
        audiences = []
        
        # Ищем таблицу с аудиториями
        table = soup.find('table')
        if table:
            # Ищем строки таблицы
            rows = table.find_all('tr')
            
            for row in rows[1:]:  # Пропускаем заголовок
                cells = row.find_all('td')
                if len(cells) >= 2:
                    # Первая ячейка - ссылка на аудиторию
                    link_cell = cells[0]
                    link = link_cell.find('a')
                    
                    if link:
                        href = link.get('href', '')
                        text = link.get_text(strip=True)
                        
                        if href and text:
                            # Извлекаем ID аудитории из ссылки
                            match = re.search(r'/rooms/(\d+)', href)
                            if match:
                                audience_id = match.group(1)
                                audiences.append({
                                    'id': audience_id,
                                    'name': text,
                                    'url': f"{self.base_url}{href}"
                                })
        
        return audiences
    
    def search_audiences(self, query):
        """Поиск аудиторий по запросу"""
        all_audiences = self.get_all_audiences()
        query = query.lower().strip()
        
        results = []
        for audience in all_audiences:
            if (query in audience['name'].lower() or 
                query in audience['id']):
                results.append(audience)
        
        return results[:20]  # Ограничиваем результаты
    
    def get_audience_schedule(self, audience_id):
        """Получение расписания конкретной аудитории"""
        try:
            url = f"{self.base_url}/rooms/{audience_id}?organization_id=1&term_id=21"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                return self._parse_schedule_page(response.text, audience_id)
            else:
                print(f"Ошибка HTTP {response.status_code} для аудитории {audience_id}")
                return None
                
        except Exception as e:
            print(f"Ошибка при получении расписания: {e}")
            return None
    
    def _parse_schedule_page(self, html, audience_id):
        """Парсинг страницы с расписанием аудитории"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Получаем название аудитории
        audience_name = f"Аудитория {audience_id}"
        title = soup.find('h1')
        if title:
            audience_name = title.get_text(strip=True)
        
        # Собираем данные
        schedule_data = {
            'audience_id': audience_id,
            'audience_name': audience_name,
            'url': f"{self.base_url}/rooms/{audience_id}",
            'schedule': []
        }
        
        # Ищем расписание по дням
        # На сайте МИФИ расписание обычно в div с классами
        schedule_divs = soup.find_all('div', class_=re.compile(r'list-group|schedule|raspisanie'))
        
        for div in schedule_divs:
            # Пытаемся найти день недели
            day_header = div.find(['h2', 'h3', 'h4', 'strong', 'b'])
            if day_header:
                day_name = day_header.get_text(strip=True)
                
                # Ищем занятия в этом дне
                lessons = []
                lesson_items = div.find_all(['div', 'tr', 'li'], class_=re.compile(r'lesson|item|row'))
                
                for item in lesson_items:
                    lesson_text = item.get_text(strip=True, separator=' ')
                    if lesson_text and len(lesson_text) > 10:  # Фильтруем короткий текст
                        lessons.append(lesson_text)
                
                if day_name and lessons:
                    schedule_data['schedule'].append({
                        'day': day_name,
                        'lessons': lessons
                    })
        
        # Если не нашли структурированно, ищем любые данные о занятиях
        if not schedule_data['schedule']:
            # Ищем любой текст, похожий на расписание
            all_text = soup.get_text()
            lines = [line.strip() for line in all_text.split('\n') if line.strip()]
            
            current_day = None
            current_lessons = []
            
            for line in lines:
                # Если строка похожа на день недели
                if any(day in line.lower() for day in ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']):
                    if current_day and current_lessons:
                        schedule_data['schedule'].append({
                            'day': current_day,
                            'lessons': current_lessons
                        })
                    current_day = line
                    current_lessons = []
                elif line and current_day and len(line) > 5:
                    # Проверяем, похожа ли строка на описание занятия
                    if any(keyword in line.lower() for keyword in ['лекция', 'семинар', 'практика', 'лабораторная', 'пара', 'занятие', 'ауд.', 'группа']):
                        current_lessons.append(line)
            
            if current_day and current_lessons:
                schedule_data['schedule'].append({
                    'day': current_day,
                    'lessons': current_lessons
                })
        
        return schedule_data
    
    def calculate_occupancy(self, schedule_data):
        """Расчет загруженности аудитории"""
        if not schedule_data or not schedule_data.get('schedule'):
            return {
                'percentage': 0,
                'level': "🟢 Нет данных",
                'occupied_hours': 0,
                'total_hours': 45,
                'days_with_lessons': 0,
                'total_lessons': 0
            }
        
        # Простая оценка: каждая запись = ~1.5 часа
        total_lessons = 0
        days_with_lessons = len(schedule_data['schedule'])
        
        for day in schedule_data['schedule']:
            total_lessons += len(day.get('lessons', []))
        
        # Примерная оценка часов (1 занятие ≈ 1.5 часа)
        occupied_hours = total_lessons * 1.5
        total_hours = 45  # 5 дней × 9 часов
        
        occupancy_percentage = (occupied_hours / total_hours) * 100
        
        if occupancy_percentage < 30:
            level = "🟢 Низкая"
        elif occupancy_percentage < 70:
            level = "🟡 Средняя"
        else:
            level = "🔴 Высокая"
        
        return {
            'percentage': round(occupancy_percentage, 1),
            'level': level,
            'occupied_hours': round(occupied_hours, 1),
            'total_hours': total_hours,
            'days_with_lessons': days_with_lessons,
            'total_lessons': total_lessons
        }
    
    def format_schedule_message(self, audience_name, schedule_data, occupancy_info):
        """Форматирование сообщения с расписанием"""
        message = f"🏫 <b>{audience_name}</b>\n\n"
        
        message += f"📊 <b>Загруженность:</b> {occupancy_info['level']}\n"
        message += f"   • {occupancy_info['occupied_hours']} ч. из {occupancy_info['total_hours']} ч.\n"
        message += f"   • {occupancy_info['percentage']}% занято\n"
        message += f"   • Занятий: {occupancy_info['total_lessons']}\n"
        message += f"   • Дней с занятиями: {occupancy_info['days_with_lessons']}/5\n\n"
        
        if schedule_data.get('schedule'):
            message += f"📅 <b>Расписание:</b>\n\n"
            
            for day in schedule_data['schedule']:
                message += f"<b>{day['day']}:</b>\n"
                
                for i, lesson in enumerate(day.get('lessons', [])[:5]):  # Ограничиваем 5 занятиями в день
                    message += f"   {i+1}. {lesson}\n"
                
                if not day.get('lessons'):
                    message += f"   🆓 Нет занятий\n"
                
                message += f"   ────────\n\n"
        else:
            message += f"📅 <b>Расписание:</b>\n"
            message += f"   📭 Данные о расписании не найдены\n\n"
        
        message += f"\n🔗 <a href='{schedule_data.get('url', self.base_url)}'>Ссылка на расписание</a>"
        message += f"\n🔄 <i>Данные с home.mephi.ru</i>"
        message += f"\n📅 <i>Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
        
        return message

# Тестируем парсер
if __name__ == '__main__':
    parser = RealMephiParser()
    
    print("🔍 Тестируем парсер МИФИ...")
    
    # 1. Получаем список всех аудиторий
    print("\n1. Получаем список аудиторий...")
    audiences = parser.get_all_audiences()
    print(f"   Найдено аудиторий: {len(audiences)}")
    
    if audiences:
        # Показываем первые 5
        print("   Первые 5 аудиторий:")
        for i, aud in enumerate(audiences[:5]):
            print(f"     {i+1}. {aud['name']} (ID: {aud['id']})")
    
    # 2. Ищем конкретную аудиторию
    print("\n2. Ищем аудиторию 'Б-100'...")
    search_results = parser.search_audiences('Б-100')
    print(f"   Найдено результатов: {len(search_results)}")
    
    if search_results:
        for aud in search_results:
            print(f"     • {aud['name']} (ID: {aud['id']})")
            
            # 3. Получаем расписание
            print(f"\n3. Получаем расписание для {aud['name']}...")
            schedule = parser.get_audience_schedule(aud['id'])
            
            if schedule:
                occupancy = parser.calculate_occupancy(schedule)
                print(f"   Загруженность: {occupancy['level']}")
                print(f"   Дней с занятиями: {occupancy['days_with_lessons']}")
                print(f"   Всего занятий: {occupancy['total_lessons']}")
                
                # Форматируем сообщение
                message = parser.format_schedule_message(aud['name'], schedule, occupancy)
                print(f"\n4. Пример сообщения (первые 500 символов):")
                print("-" * 50)
                print(message[:500] + "..." if len(message) > 500 else message)
                print("-" * 50)
            else:
                print("   ❌ Не удалось получить расписание")
    else:
        print("   ❌ Аудитория не найдена")
        
        # Показываем какие аудитории вообще есть
        print("\n   Попробуйте поискать по этим номерам:")
        sample_names = [aud['name'] for aud in audiences[:10]]
        for name in sample_names:
            print(f"     • {name}")