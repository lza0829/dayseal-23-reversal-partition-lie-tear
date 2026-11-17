from fastapi import APIRouter, Body
from app.services import settings_service as svc

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/business-day")
def get_day():
    return svc.get_day()


@router.put("/business-day")
def set_day(body: dict = Body(...)):
    return svc.set_day(body)


@router.get("/reversal-policy")
def get_reversal_policy():
    return svc.get_reversal_policy()


@router.put("/reversal-policy")
def set_reversal_policy(body: dict = Body(...)):
    return svc.set_reversal_policy(body)
