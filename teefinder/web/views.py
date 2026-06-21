"""Authenticated pages: the tee-time dashboard and the preferences editor."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from teefinder.accounts import UserStore
from teefinder.config import WEEKDAY_NAMES, Config, UserConfig
from teefinder.matching import available_matching_for_user
from teefinder.storage import Storage
from teefinder.web.deps import get_config, get_storage, get_templates, get_user_store, require_user

router = APIRouter()

MAX_PREF_ROWS = 6  # preference rows shown in the editor (each = days + one time range)


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: UserConfig = Depends(require_user),
    config: Config = Depends(get_config),
    storage: Storage = Depends(get_storage),
    templates=Depends(get_templates),
):
    matches = available_matching_for_user(config, storage, user)
    club_names = {c.id: c.name for c in config.clubs}

    grouped: dict[str, list] = {}
    for tee in matches:
        grouped.setdefault(tee.club_id, []).append(tee)
    groups = [(club_names.get(cid, cid), slots) for cid, slots in grouped.items()]
    groups.sort(key=lambda g: g[0])

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "groups": groups,
            "count": len(matches),
            "day_names": WEEKDAY_NAMES,
        },
    )


def _prefs_to_rows(user: UserConfig) -> list[dict]:
    """Flatten a user's preference blocks into editor rows (days + one range)."""
    rows: list[dict] = []
    for pref in user.preferences:
        for tr in pref.time_ranges:
            rows.append(
                {
                    "days": list(pref.days),
                    "start": tr.start.strftime("%H:%M"),
                    "end": tr.end.strftime("%H:%M"),
                    "start_date": pref.start_date.isoformat() if pref.start_date else "",
                    "end_date": pref.end_date.isoformat() if pref.end_date else "",
                }
            )
    while len(rows) < MAX_PREF_ROWS:
        rows.append({"days": [], "start": "", "end": "", "start_date": "", "end_date": ""})
    return rows[:MAX_PREF_ROWS]


@router.get("/preferences")
def preferences_form(
    request: Request,
    saved: bool = False,
    user: UserConfig = Depends(require_user),
    config: Config = Depends(get_config),
    templates=Depends(get_templates),
):
    return templates.TemplateResponse(
        request,
        "preferences.html",
        {
            "user": user,
            "clubs": config.clubs,
            "selected_clubs": set(user.clubs),
            "min_players": user.min_players,
            "weekdays": WEEKDAY_NAMES,
            "rows": _prefs_to_rows(user),
            "saved": saved,
            "error": None,
        },
    )


@router.post("/preferences")
async def preferences_save(
    request: Request,
    user: UserConfig = Depends(require_user),
    config: Config = Depends(get_config),
    store: UserStore = Depends(get_user_store),
    templates=Depends(get_templates),
):
    form = await request.form()
    name = (form.get("name") or user.name).strip()
    valid_club_ids = {c.id for c in config.clubs}
    clubs = [c for c in form.getlist("clubs") if c in valid_club_ids]

    rows: list[dict] = []
    display_rows: list[dict] = []
    for i in range(MAX_PREF_ROWS):
        day_names = form.getlist(f"days_{i}")
        start = form.get(f"start_{i}") or ""
        end = form.get(f"end_{i}") or ""
        start_date = form.get(f"start_date_{i}") or ""
        end_date = form.get(f"end_date_{i}") or ""
        display_rows.append(
            {"days": [WEEKDAY_NAMES.index(d) for d in day_names if d in WEEKDAY_NAMES],
             "start": start, "end": end, "start_date": start_date, "end_date": end_date}
        )
        if day_names and start and end:
            rows.append({
                "days": day_names,
                "time_ranges": [{"start": start, "end": end}],
                "start_date": start_date,  # "" -> None via the Preference validator
                "end_date": end_date,
            })

    try:
        min_players = int(form.get("min_players", user.min_players))
    except (TypeError, ValueError):
        min_players = user.min_players

    error = None
    try:
        store.update_profile(
            store.id_for_email(user.email),
            name=name,
            min_players=min_players,
            clubs=clubs,
            preferences=rows,
        )
    except Exception as exc:  # validation error from UserConfig -> show it
        error = f"Could not save: {exc}"

    if error:
        return templates.TemplateResponse(
            request,
            "preferences.html",
            {
                "user": user,
                "clubs": config.clubs,
                "selected_clubs": set(clubs),
                "min_players": min_players,
                "weekdays": WEEKDAY_NAMES,
                "rows": display_rows,
                "saved": False,
                "error": error,
            },
            status_code=400,
        )

    return RedirectResponse("/preferences?saved=1", status_code=303)
