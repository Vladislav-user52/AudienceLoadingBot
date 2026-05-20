import traceback
from datetime import datetime, date

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from parser_mephi import (
    get_day_schedule_by_room_name,
    get_week_schedule_by_room_name,
    build_day_chart_base64,
    build_week_chart_base64,
)

app = FastAPI(title="MEPhI Room Schedule")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    room: str | None = Query(default=None),
    target_date: str | None = Query(default=None),
):
    context = {
        "request": request,
        "today": date.today().isoformat(),
        "room": room or "",
        "target_date": target_date or date.today().isoformat(),
        "error": None,
        "room_name": None,
        "day_label": None,
        "day_lessons": [],
        "week_data": [],
        "day_chart": None,
        "week_chart": None,
    }

    if not room:
        return templates.TemplateResponse(request, "index.html", context)

    try:
        parsed_date = datetime.strptime(
            target_date or date.today().isoformat(), "%Y-%m-%d"
        ).date()

        room_name, day_label, day_lessons = get_day_schedule_by_room_name(room, parsed_date)
        _, week_data = get_week_schedule_by_room_name(room, parsed_date)

        context.update(
            {
                "room_name": room_name,
                "day_label": day_label,
                "day_lessons": day_lessons,
                "week_data": week_data,
                "day_chart": build_day_chart_base64(room_name, day_label, day_lessons),
                "week_chart": build_week_chart_base64(room_name, week_data),
            }
        )
    except Exception as e:
        context["error"] = f"{type(e).__name__}: {e}\\n\\n{traceback.format_exc()}"

    return templates.TemplateResponse(request, "index.html", context)