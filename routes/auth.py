# routes/auth.py
import os
from fastapi import APIRouter, Depends, HTTPException, Header
from jose import jwt, JWTError

router = APIRouter()

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_ISSUER = os.getenv("SUPABASE_ISSUER")  # https://<ref>.supabase.co/auth/v1

def require_user(authorization: str = Header(None)):
  if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="Missing bearer token")

  token = authorization.split(" ", 1)[1]
  try:
    payload = jwt.decode(
      token,
      SUPABASE_JWT_SECRET,
      algorithms=["HS256"],
      issuer=SUPABASE_ISSUER,
      audience="authenticated",
    )
    return payload  # contains sub, email, role, etc.
  except JWTError:
    raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/auth/me")
def me(user=Depends(require_user)):
  return {"user": user}
