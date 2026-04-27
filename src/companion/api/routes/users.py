from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from companion import service
from companion.api.deps import get_current_user_id, get_db_conn
from companion.api.schemas.users import UpdateMeIn

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def me(user_id: int = Depends(get_current_user_id), conn: psycopg.Connection = Depends(get_db_conn)):
    return service.get_me(user_id, conn=conn)  # type: ignore


@router.patch("/me")
def update_me_route(
    payload: UpdateMeIn,
    user_id: int = Depends(get_current_user_id),
    conn: psycopg.Connection = Depends(get_db_conn),
):
    fields = payload.model_fields_set
    try:
        return service.update_me(
            user_id,
            display_name=payload.display_name,
            avatar_data_url=payload.avatar_data_url,
            update_display_name="display_name" in fields,
            update_avatar="avatar_data_url" in fields,
            conn=conn,  # type: ignore
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
