"""Registration, login and logout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from teefinder.accounts import DuplicateEmailError, UserStore
from teefinder.web.deps import get_current_user, get_templates, get_user_store

router = APIRouter()


@router.get("/")
def index(user=Depends(get_current_user)):
    return RedirectResponse("/dashboard" if user else "/login", status_code=303)


@router.get("/register")
def register_form(request: Request, templates=Depends(get_templates), user=Depends(get_current_user)):
    if user is not None:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "register.html")


@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    templates=Depends(get_templates),
    store: UserStore = Depends(get_user_store),
):
    error = None
    if not name.strip():
        error = "Please enter your name."
    elif "@" not in email or "." not in email:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    else:
        try:
            store.create_user(email, password, name.strip())
        except DuplicateEmailError as exc:
            error = str(exc)

    if error:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": error, "name": name, "email": email},
            status_code=400,
        )

    request.session["user_id"] = store.id_for_email(email)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login")
def login_form(request: Request, templates=Depends(get_templates), user=Depends(get_current_user)):
    if user is not None:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    templates=Depends(get_templates),
    store: UserStore = Depends(get_user_store),
):
    user = store.authenticate(email, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password.", "email": email},
            status_code=401,
        )
    request.session["user_id"] = store.id_for_email(email)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
