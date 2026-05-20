import base64
import difflib
import io
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup, Tag, NavigableString


BASE_URL = "https://home.mephi.ru"
ROOMS_URL = f"{BASE_URL}/rooms?organization_id=1&term_id=22"

HEADERS = {"User-Agent": "Mozilla/5.0"}

TIME_RE = re.compile(r"^\d{2}:\d{2}\s*[—–-]\s*\d{2}:\d{2}$")
WEEKDAY_RE = re.compile(
    r"^(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\b",
    re.IGNORECASE,
)
ROOM_TITLE_RE = re.compile(
    r"Расписание занятий в аудитории\s+(.+?)(?:\s+Корпус\s+.+)?$",
    re.IGNORECASE,
)
LESSON_TYPES = {"Лек", "Пр", "Лаб", "Конс", "СР", "Экз", "Зач", "КСР", "НИР"}


@dataclass
class Lesson:
    start: str
    end: str
    lesson_type: Optional[str]
    description: str


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(tag_or_text) -> str:
    if isinstance(tag_or_text, Tag):
        text = tag_or_text.get_text(" ", strip=True)
    else:
        text = str(tag_or_text)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def normalize_room_name(name: str) -> str:
    latin_to_cyrillic = str.maketrans({
        "A": "А", "a": "а",
        "B": "В", "E": "Е", "e": "е",
        "K": "К", "k": "к",
        "M": "М", "H": "Н",
        "O": "О", "o": "о",
        "P": "Р", "p": "р",
        "C": "С", "c": "с",
        "T": "Т", "X": "Х", "x": "х",
        "Y": "У", "y": "у",
    })

    name = clean_text(name)
    name = name.translate(latin_to_cyrillic)
    name = name.replace("—", "-").replace("–", "-").replace("−", "-")
    return name.casefold()


def get_all_rooms() -> List[dict]:
    soup = get_soup(ROOMS_URL)
    rooms = []

    for a in soup.select('a[href^="/rooms/"]'):
        href = a.get("href", "")
        text = clean_text(a)

        if re.fullmatch(r"/rooms/\d+", href):
            rooms.append(
                {
                    "name": text,
                    "normalized": normalize_room_name(text),
                    "url": urljoin(BASE_URL, href),
                }
            )

    return rooms


def get_all_room_names() -> List[str]:
    return [room["name"] for room in get_all_rooms()]


def find_room_url(room_name: str) -> str:
    target = normalize_room_name(room_name)
    rooms = get_all_rooms()

    # 1. Точное совпадение
    for room in rooms:
        if room["normalized"] == target:
            return room["url"]

    # 2. Частичное совпадение
    partial_matches = [
        room["name"]
        for room in rooms
        if target in room["normalized"] or room["normalized"] in target
    ]

    if partial_matches:
        raise ValueError(
            f'Аудитория "{room_name}" не найдена точно. '
            f'Возможно, имелось в виду: {", ".join(partial_matches[:10])}'
        )

    # 3. Похожие варианты
    normalized_to_original = {room["normalized"]: room["name"] for room in rooms}

    close_normalized = difflib.get_close_matches(
        target,
        list(normalized_to_original.keys()),
        n=10,
        cutoff=0.6,
    )

    close_names = [normalized_to_original[name] for name in close_normalized]

    if close_names:
        raise ValueError(
            f'Аудитория "{room_name}" не найдена. '
            f'Похожие варианты: {", ".join(close_names)}'
        )

    raise ValueError(
        f'Аудитория "{room_name}" не найдена на текущей странице списка аудиторий'
    )


def extract_room_name(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if not h1:
        return "Неизвестная аудитория"

    title = clean_text(h1)
    match = ROOM_TITLE_RE.search(title)
    if match:
        return match.group(1).strip()

    return title


def is_day_header_tag(tag: Tag) -> bool:
    return tag.name == "h3" and bool(WEEKDAY_RE.match(clean_text(tag)))


def iter_day_headers(soup: BeautifulSoup):
    root = soup.find("main") or soup.find("body") or soup

    for h3 in root.find_all("h3"):
        if is_day_header_tag(h3):
            yield h3, clean_text(h3)


def is_time_interval(text: str) -> bool:
    return bool(TIME_RE.fullmatch(text))


def finish_current_lesson(
    current: Optional[Lesson],
    description_parts: List[str],
    lessons: List[Lesson],
) -> None:
    if current is None:
        return

    current.description = " ".join(description_parts).strip()
    lessons.append(current)


def parse_lessons_after_day_header(day_header: Tag) -> List[Lesson]:
    lessons: List[Lesson] = []
    current: Optional[Lesson] = None
    description_parts: List[str] = []

    for node in day_header.next_elements:
        if node is day_header:
            continue

        if isinstance(node, Tag):
            if is_day_header_tag(node):
                break
            continue

        if not isinstance(node, NavigableString):
            continue

        text = clean_text(node)
        if not text:
            continue

        if node.parent == day_header:
            continue

        if text == "Занятий не найдено":
            return []

        if is_time_interval(text):
            finish_current_lesson(current, description_parts, lessons)

            start, end = re.split(r"\s*[—–-]\s*", text)
            current = Lesson(
                start=start.strip(),
                end=end.strip(),
                lesson_type=None,
                description="",
            )
            description_parts = []
            continue

        if current is None:
            continue

        if current.lesson_type is None and text in LESSON_TYPES:
            current.lesson_type = text
        else:
            description_parts.append(text)

    finish_current_lesson(current, description_parts, lessons)
    return lessons


def parse_schedule_page(
    room_url: str,
    target_date: date,
    mode: str,
) -> Tuple[str, List[Tuple[str, List[Lesson]]]]:
    page_url = f"{room_url}/{mode}?date={target_date.isoformat()}"
    soup = get_soup(page_url)

    room_name = extract_room_name(soup)
    schedule_data: List[Tuple[str, List[Lesson]]] = []

    for header_tag, day_label in iter_day_headers(soup):
        lessons = parse_lessons_after_day_header(header_tag)
        schedule_data.append((day_label, lessons))

        if mode == "day":
            break

    if mode == "day" and not schedule_data:
        schedule_data.append((target_date.strftime("%d.%m.%Y"), []))

    return room_name, schedule_data


def parse_day_schedule(room_url: str, target_date: date) -> Tuple[str, str, List[Lesson]]:
    room_name, schedule_data = parse_schedule_page(room_url, target_date, "day")
    day_label, lessons = schedule_data[0]
    return room_name, day_label, lessons


def parse_week_schedule(room_url: str, target_date: date) -> Tuple[str, List[Tuple[str, List[Lesson]]]]:
    return parse_schedule_page(room_url, target_date, "week")


def get_day_schedule_by_room_name(room_name_input: str, target_date: date):
    room_url = find_room_url(room_name_input)
    room_name, day_label, lessons = parse_day_schedule(room_url, target_date)
    return room_name, day_label, [asdict(lesson) for lesson in lessons]


def get_week_schedule_by_room_name(room_name_input: str, target_date: date):
    room_url = find_room_url(room_name_input)
    room_name, week_data = parse_week_schedule(room_url, target_date)
    result = []

    for day_label, lessons in week_data:
        result.append((day_label, [asdict(lesson) for lesson in lessons]))

    return room_name, result


def time_to_minutes(time_str: str) -> int:
    hours, minutes = map(int, time_str.split(":"))
    return hours * 60 + minutes


def minutes_to_time_label(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def fig_to_base64(fig) -> str:
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def build_day_chart_base64(room_name: str, day_label: str, lessons: List[dict]) -> str:
    fig, ax = plt.subplots(figsize=(12, 2.8))

    if not lessons:
        ax.text(0.5, 0.5, "Аудитория свободна весь день", ha="center", va="center", fontsize=12)
        ax.set_title(f"{room_name}: {day_label}")
        ax.set_xticks([])
        ax.set_yticks([])
        return fig_to_base64(fig)

    for lesson in lessons:
        start = time_to_minutes(lesson["start"])
        end = time_to_minutes(lesson["end"])
        duration = end - start

        ax.broken_barh([(start, duration)], (5, 8))
        label = lesson.get("lesson_type") or "Занято"
        ax.text(start + duration / 2, 9, label, ha="center", va="center", fontsize=9)

    min_time = min(time_to_minutes(lesson["start"]) for lesson in lessons) - 15
    max_time = max(time_to_minutes(lesson["end"]) for lesson in lessons) + 15

    step = 30
    ticks = list(range((min_time // step) * step, ((max_time + step - 1) // step) * step + 1, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([minutes_to_time_label(t) for t in ticks], rotation=45)
    ax.set_ylim(0, 20)
    ax.set_yticks([9])
    ax.set_yticklabels(["Занятость"])
    ax.set_xlabel("Время")
    ax.set_title(f"{room_name}: {day_label}")
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    return fig_to_base64(fig)


def build_week_chart_base64(room_name: str, week_data: List[tuple]) -> str:
    fig, ax = plt.subplots(figsize=(13, 6))

    if not week_data:
        ax.text(0.5, 0.5, "Нет данных за неделю", ha="center", va="center", fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])
        return fig_to_base64(fig)

    day_start = 8 * 60
    day_end = 20 * 60
    y_positions = []
    y_labels = []

    for idx, (day_label, lessons) in enumerate(week_data):
        y = idx * 10
        y_positions.append(y + 4)
        y_labels.append(day_label)

        for lesson in lessons:
            start = time_to_minutes(lesson["start"])
            end = time_to_minutes(lesson["end"])
            duration = end - start

            ax.broken_barh([(start, duration)], (y, 8))
            short_label = lesson.get("lesson_type") or "Занято"
            ax.text(start + duration / 2, y + 4, short_label, ha="center", va="center", fontsize=8)

    ticks = list(range(day_start, day_end + 1, 30))
    ax.set_xticks(ticks)
    ax.set_xticklabels([minutes_to_time_label(t) for t in ticks], rotation=45)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(y_labels)
    ax.set_xlim(day_start, day_end)
    ax.set_xlabel("Время")
    ax.set_title(f"Недельная занятость аудитории {room_name}")
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    return fig_to_base64(fig)