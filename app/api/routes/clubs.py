"""
Routes API pour la gestion des clubs - VERSION CORRIGÉE
Utilise l'endpoint /clubs/{club_id} via le slug
"""
from fastapi import APIRouter, Depends, HTTPException
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
    url: str
    
    @validator('url')
    def validate_url(cls, v):
        v = v.strip().lower()
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
    message: str = ""


# === HELPERS ===

def extract_slug_from_url(url: str) -> str:
    """Extrait le slug depuis l'URL Doinsport"""
    pattern = r'(?:https?://)?([a-z0-9-]+)\.doinsport\.club'
    match = re.match(pattern, url.lower().strip())
    if match:
        return match.group(1)
    raise ValueError("URL invalide")


async def get_club_id_from_slug(slug: str) -> Optional[dict]:
    """
    Récupère le club_id à partir du slug en appelant l'API Doinsport.
    L'API /clubs accepte un paramètre de recherche.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        # Méthode 1: Chercher le club via l'endpoint /clubs avec search
        try:
            url = f"{settings.DOINSPORT_API_BASE}/clubs"
            params = {"search": slug, "itemsPerPage": 50}
            
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                members = data.get("hydra:member", [])
                
                # Chercher un club dont le nom contient le slug
                for club in members:
                    club_name = club.get("name", "").lower()
                    # Normaliser le slug pour la comparaison
                    slug_normalized = slug.replace("-", " ").replace("padel", "").strip()
                    
                    if slug_normalized in club_name.lower() or slug in club_name.lower().replace(" ", ""):
                        club_id = club.get("@id", "").split("/")[-1] or club.get("id")
                        if club_id:
                            logger.info(f"✅ Club trouvé via search: {club.get('name')} (ID: {club_id})")
                            return {
                                "id": club_id,
                                "name": club.get("name"),
                                "city": club.get("city"),
                                "address": club.get("address", [""])[0] if isinstance(club.get("address"), list) else club.get("address")
                            }
        except Exception as e:
            logger.warning(f"Méthode search échouée: {e}")
        
        # Méthode 2: Essayer d'accéder directement à l'API du club via son subdomain
        # Les sites Doinsport font un appel à /clubs/{id} - on peut essayer de récupérer
        # le club_id via une recherche plus large
        try:
            # Chercher dans tous les clubs de padel
            from datetime import datetime, timedelta
            test_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            
            url = f"{settings.DOINSPORT_API_BASE}/clubs/playgrounds/plannings/{test_date}"
            params = {
                "activities.id": settings.PADEL_ACTIVITY_ID,
                "bookingType": "unique",
                "itemsPerPage": 200
            }
            
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                members = data.get("hydra:member", [])
                
                # Grouper par club et chercher celui qui correspond au slug
                for pg in members:
                    club_data = pg.get("club", {})
                    if isinstance(club_data, dict):
                        club_name = club_data.get("name", "").lower()
                        club_slug_api = club_data.get("slug", "").lower()
                        
                        # Vérifier si le nom ou slug correspond
                        slug_parts = slug.replace("-", " ").split()
                        name_match = all(part in club_name for part in slug_parts)
                        slug_match = slug == club_slug_api or slug in club_slug_api
                        
                        if name_match or slug_match:
                            club_id = club_data.get("id")
                            if club_id:
                                logger.info(f"✅ Club trouvé via playgrounds: {club_data.get('name')} (ID: {club_id})")
                                return {
                                    "id": club_id,
                                    "name": club_data.get("name"),
                                    "city": club_data.get("city"),
                                    "address": None
                                }
        except Exception as e:
            logger.warning(f"Méthode playgrounds échouée: {e}")
        
        return None


async def fetch_club_info_from_doinsport(slug: str) -> dict:
    """
    Récupère les infos du club depuis l'API Doinsport.
    1. D'abord récupère le club_id depuis le slug
    2. Ensuite compte les terrains de padel avec club.id
    """
    from datetime import datetime, timedelta
    
    # Étape 1: Récupérer le club_id
    club_info = await get_club_id_from_slug(slug)
    
    if not club_info or not club_info.get("id"):
        logger.warning(f"❌ Club ID non trouvé pour slug: {slug}")
        return {
            "valid": False,
            "message": f"Club '{slug}' non trouvé. Vérifiez l'URL du club."
        }
    
    club_id = club_info["id"]
    logger.info(f"🔍 Club ID trouvé: {club_id} pour {slug}")
    
    # Étape 2: Compter les terrains de padel avec club.id
    async with httpx.AsyncClient(timeout=15) as client:
        test_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        url = f"{settings.DOINSPORT_API_BASE}/clubs/playgrounds/plannings/{test_date}"
        params = {
            "club.id": club_id,  # ✅ Utiliser club.id, pas club.slug !
            "activities.id": settings.PADEL_ACTIVITY_ID,
            "bookingType": "unique"
        }
        
        try:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                members = data.get("hydra:member", [])
                
                # Compter les terrains uniques (par ID)
                padel_courts = set()
                for pg in members:
                    pg_id = pg.get("id")
                    if pg_id:
                        # Vérifier que c'est bien du padel
                        activities = pg.get("activities", [])
                        has_padel = any(
                            act.get("id") == settings.PADEL_ACTIVITY_ID
                            for act in activities
                            if isinstance(act, dict)
                        )
                        if has_padel:
                            padel_courts.add(pg_id)
                
                courts_count = len(padel_courts)
                logger.info(f"🎾 {courts_count} terrain(s) de padel pour {club_info['name']}")
                
                if courts_count > 0:
                    return {
                        "valid": True,
                        "club_id": club_id,
                        "club_name": club_info.get("name", slug.replace("-", " ").title()),
                        "slug": slug,
                        "has_padel": True,
                        "courts_count": courts_count,
                        "city": club_info.get("city"),
                        "address": club_info.get("address")
                    }
                else:
                    return {
                        "valid": True,
                        "club_id": club_id,
                        "club_name": club_info.get("name"),
                        "slug": slug,
                        "has_padel": False,
                        "courts_count": 0,
                        "message": "Ce club n'a pas de terrains de padel disponibles"
                    }
            else:
                logger.error(f"❌ API error: {response.status_code}")
                return {
                    "valid": False,
                    "message": f"Erreur API Doinsport: {response.status_code}"
                }
                
        except httpx.TimeoutException:
            return {"valid": False, "message": "Timeout - Doinsport ne répond pas"}
        except Exception as e:
            logger.error(f"❌ Erreur: {e}")
            return {"valid": False, "message": f"Erreur: {str(e)}"}


# === ROUTES ===

@router.get("", response_model=List[ClubResponse])
async def list_clubs(db: AsyncSession = Depends(get_db)):
    """Liste tous les clubs actifs"""
    result = await db.execute(select(Club).where(Club.enabled == True))
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
    """Vérifie si un club Doinsport existe et a des terrains de padel"""
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
    """Ajoute un nouveau club après vérification"""
    try:
        slug = extract_slug_from_url(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Vérifier si le club existe déjà
    result = await db.execute(select(Club).where(Club.slug == slug))
    existing_club = result.scalar_one_or_none()
    
    if existing_club:
        return ClubResponse(
            id=str(existing_club.id),
            name=existing_club.name,
            slug=existing_club.slug,
            city=existing_club.city,
            address=existing_club.address,
            enabled=existing_club.enabled
        )
    
    # Vérifier sur Doinsport
    club_info = await fetch_club_info_from_doinsport(slug)
    
    if not club_info.get("valid"):
        raise HTTPException(status_code=404, detail=club_info.get("message", "Club non trouvé"))
    
    if not club_info.get("has_padel"):
        raise HTTPException(status_code=400, detail="Ce club n'a pas de terrains de padel")
    
    if not club_info.get("club_id"):
        raise HTTPException(status_code=400, detail="Impossible de récupérer l'ID du club")
    
    # Créer le club
    address = club_info.get("address")
    if isinstance(address, list):
        address = ", ".join(address) if address else None
    
    new_club = Club(
        doinsport_id=club_info["club_id"],
        name=club_info["club_name"],
        slug=slug,
        city=club_info.get("city"),
        address=address,
        enabled=True
    )
    
    db.add(new_club)
    await db.commit()
    await db.refresh(new_club)
    
    logger.info(f"✅ Club ajouté: {new_club.name} ({slug}) - {club_info['courts_count']} terrains")
    
    return ClubResponse(
        id=str(new_club.id),
        name=new_club.name,
        slug=slug,
        city=new_club.city,
        address=new_club.address,
        enabled=new_club.enabled
    )