"""
Routes API pour les clubs
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Club
from app.schemas.schemas import ClubResponse
from typing import List

router = APIRouter(prefix="/api/clubs", tags=["clubs"])

@router.get("", response_model=List[ClubResponse])
async def list_clubs(db: AsyncSession = Depends(get_db)):
    """Liste tous les clubs disponibles"""
    
    result = await db.execute(
        select(Club).where(Club.enabled == True)
    )
    clubs = result.scalars().all()
    return clubs
