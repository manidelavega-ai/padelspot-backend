"""
Routes API pour la gestion des clubs
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, validator
from typing import List, Optional
import httpx
import re
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.models import Club

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clubs", tags=["clubs"])


# === SCHEMAS ===

class ClubAddRequest(BaseModel):
    url: str  # Ex: "https://legarden.doinsport.club" ou "legarden.doinsport.club"
    
    @validator('url')
    def validate_url(cls, v):
        # Nettoyer l'URL
        v = v.strip().lower()
        # Extraire le slug
        pattern = r'(?:https?://)?([a-z0-9-]+)\.doinsport\.club'
        match = re.match(pattern, v)
        if not match:
            raise ValueError("URL invalide. Format attendu: votreclub.doinsport.club")
        return v

class ClubResponse(BaseModel):
    id: str
    name: str
    slug: str
    city: Optional[str]
    address: Optional[str]
    enabled: bool
    
    class Config:
        from_attributes = True

class ClubVerifyResponse(BaseModel):
    valid: bool
    club_name: Optional[str] = None
    club_id: Optional[str] = None
    has_padel: bool = False
    courts_count: int = 0
    message: str


# === HELPERS ===

def extract_slug_from_url(url: str) -> str:
    """Extrait le slug depuis l'URL Doinsport"""
    pattern = r'(?:https?://)?([a-z0-9-]+)\.doinsport\.club'
    match = re.match(pattern, url.lower().strip())
    if match:
        return match.group(1)
    raise ValueError("URL invalide")


async def fetch_club_info_from_doinsport(slug: str) -> dict:
    """
    Récupère les infos du club depuis l'API Doinsport
    """
    # L'API Doinsport utilise le slug pour identifier le club
    # On va chercher les terrains pour une date pour obtenir les infos du club
    
    from datetime import datetime, timedelta
    test_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{settings.DOINSPORT_API_BASE}/clubs/playgrounds/plannings/{test_date}"
    params = {
        "club.slug": slug,
        "activities.id": settings.PADEL_ACTIVITY_ID,
        "bookingType": "unique"
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            # Essayer d'abord avec le slug
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                members = data.get("hydra:member", [])
                
                if members:
                    # Récupérer l'ID du club depuis le premier terrain
                    first_playground = members[0]
                    club_data = first_playground.get("club", {})
                    
                    return {
                        "valid": True,
                        "club_id": club_data.get("id"),
                        "club_name": club_data.get("name", slug.title()),
                        "slug": slug,
                        "has_padel": True,
                        "courts_count": len(members),
                        "city": club_data.get("city"),
                        "address": club_data.get("address")
                    }
                else:
                    # Club trouvé mais pas de terrains de padel
                    return {
                        "valid": True,
                        "club_id": None,
                        "club_name": slug.title(),
                        "slug": slug,
                        "has_padel": False,
                        "courts_count": 0,
                        "message": "Ce club n'a pas de terrains de padel disponibles"
                    }
            else:
                return {
                    "valid": False,
                    "message": "Club non trouvé sur Doinsport"
                }
                
        except httpx.TimeoutException:
            return {
                "valid": False,
                "message": "Timeout - le serveur Doinsport ne répond pas"
            }
        except Exception as e:
            logger.error(f"Erreur fetch club {slug}: {e}")
            return {
                "valid": False,
                "message": f"Erreur: {str(e)}"
            }


# === ROUTES ===

@router.get("", response_model=List[ClubResponse])
async def list_clubs(
    db: AsyncSession = Depends(get_db)
):
    """Liste tous les clubs actifs"""
    result = await db.execute(
        select(Club).where(Club.enabled == True)
    )
    clubs = result.scalars().all()
    
    return [
        ClubResponse(
            id=str(club.id),
            name=club.name,
            slug=club.slug if hasattr(club, 'slug') else "",
            city=club.city,
            address=club.address,
            enabled=club.enabled
        )
        for club in clubs
    ]


@router.post("/verify", response_model=ClubVerifyResponse)
async def verify_club(
    request: ClubAddRequest,
    current_user = Depends(get_current_user)
):
    """
    Vérifie si un club Doinsport existe et a des terrains de padel
    """
    try:
        slug = extract_slug_from_url(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    logger.info(f"🔍 Vérification club: {slug}")
    
    result = await fetch_club_info_from_doinsport(slug)
    
    return ClubVerifyResponse(
        valid=result.get("valid", False),
        club_name=result.get("club_name"),
        club_id=result.get("club_id"),
        has_padel=result.get("has_padel", False),
        courts_count=result.get("courts_count", 0),
        message=result.get("message", "")
    )


@router.post("/add", response_model=ClubResponse)
async def add_club(
    request: ClubAddRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Ajoute un nouveau club après vérification
    """
    try:
        slug = extract_slug_from_url(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Vérifier si le club existe déjà en base
    result = await db.execute(
        select(Club).where(Club.slug == slug)
    )
    existing_club = result.scalar_one_or_none()
    
    if existing_club:
        # Retourner le club existant
        return ClubResponse(
            id=str(existing_club.id),
            name=existing_club.name,
            slug=existing_club.slug if hasattr(existing_club, 'slug') else slug,
            city=existing_club.city,
            address=existing_club.address,
            enabled=existing_club.enabled
        )
    
    # Vérifier sur Doinsport
    club_info = await fetch_club_info_from_doinsport(slug)
    
    if not club_info.get("valid"):
        raise HTTPException(
            status_code=404, 
            detail=club_info.get("message", "Club non trouvé")
        )
    
    if not club_info.get("has_padel"):
        raise HTTPException(
            status_code=400, 
            detail="Ce club n'a pas de terrains de padel"
        )
    
    if not club_info.get("club_id"):
        raise HTTPException(
            status_code=400, 
            detail="Impossible de récupérer l'ID du club"
        )
    
    # Créer le club en base
    new_club = Club(
        doinsport_id=club_info["club_id"],
        name=club_info["club_name"],
        slug=slug,
        city=club_info.get("city"),
        address=club_info.get("address"),
        enabled=True
    )
    
    db.add(new_club)
    await db.commit()
    await db.refresh(new_club)
    
    logger.info(f"✅ Club ajouté: {new_club.name} ({slug})")
    
    return ClubResponse(
        id=str(new_club.id),
        name=new_club.name,
        slug=slug,
        city=new_club.city,
        address=new_club.address,
        enabled=new_club.enabled
    )