import os
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt

router = APIRouter()

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_ISSUER = os.getenv("SUPABASE_ISSUER")  # optional

if not SUPABASE_JWT_SECRET:
    raise RuntimeError("SUPABASE_JWT_SECRET is not set")

def require_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            issuer=SUPABASE_ISSUER if SUPABASE_ISSUER else None,
            audience="authenticated",
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/me")
def me(user=Depends(require_user)):
    return {"user": user}
