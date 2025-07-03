from fastapi import APIRouter, Form
from services.cognito import sign_up_user, login_user, confirm_user

router = APIRouter()

@router.post("/signup")
def signup(
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(...)
):
    return sign_up_user(email, password, name)


@router.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    return login_user(email, password)

@router.post("/confirm")
def confirm_signup(
    email: str = Form(...),
    code: str = Form(...)
):
    return confirm_user(email, code)
