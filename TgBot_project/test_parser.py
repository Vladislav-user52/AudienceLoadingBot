# test_parser.py
import requests
from bs4 import BeautifulSoup
import re

def explore_mephi_site():
    """Исследуем структуру сайта МИФИ"""
    base_url = "https://home.mephi.ru"
    
    # Пробуем разные URL
    test_urls = [
        f"{base_url}/study",
        f"{base_url}/schedule",
        f"{base_url}/timetable", 
        f"{base_url}/raspisanie",
        f"{base_url}/rooms",
        f"{base_url}/audience",
        f"{base_url}/study/rooms",
        f"{base_url}/api/schedule",
    ]
    
    for url in test_urls:
        print(f"\n🔍 Проверяю: {url}")
        try:
            response = requests.get(url, timeout=10)
            print(f"   Статус: {response.status_code}")
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Ищем ссылки на расписание
                schedule_links = []
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    text = link.get_text(strip=True)
                    
                    if any(keyword in href.lower() or keyword in text.lower() 
                           for keyword in ['schedule', 'расписание', 'timetable', 'ауд', 'room']):
                        schedule_links.append((text, href))
                
                if schedule_links:
                    print(f"   Найдено ссылок на расписание: {len(schedule_links)}")
                    for text, href in schedule_links[:5]:  # Покажем первые 5
                        print(f"     - {text}: {href}")
                        
                # Ищем формы
                forms = soup.find_all('form')
                if forms:
                    print(f"   Найдено форм: {len(forms)}")
                    
        except Exception as e:
            print(f"   Ошибка: {e}")

if __name__ == '__main__':
    explore_mephi_site()