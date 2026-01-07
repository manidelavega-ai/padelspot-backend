"""
Service de scraping de l'API Doinsport
"""
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class DoinsportScraper:
    BASE_URL = settings.DOINSPORT_API_BASE
    PADEL_ACTIVITY_ID = settings.PADEL_ACTIVITY_ID
    
    def __init__(self, timeout: int = 30):
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def get_available_slots(
        self,
        club_id: str,
        date: str,
        time_from: str = "00:00:00",
        time_to: str = "23:59:59",
        indoor_only: Optional[bool] = None
    ) -> List[Dict]:
        """
        Récupère les créneaux disponibles pour une date donnée
        """
        url = f"{self.BASE_URL}/clubs/playgrounds/plannings/{date}"
        params = {
            "club.id": club_id,
            "from": time_from,
            "to": time_to,
            "activities.id": self.PADEL_ACTIVITY_ID,
            "bookingType": "unique"
        }
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Vérification que data est bien un dict
            if not isinstance(data, dict):
                logger.error(f"❌ API returned {type(data)} instead of dict")
                return []
            
            available_slots = []
            
            for playground in data.get("hydra:member", []):
                logger.info(f"🔍 DEBUG: Playground '{playground.get('name')}' - Indoor={playground.get('indoor')} - Filter={indoor_only}")
                # Vérification que playground est un dict
                if not isinstance(playground, dict):
                    logger.warning(f"⚠️ Playground is {type(playground)}, skipping")
                    continue
                
                # ✅ LOGIQUE DE FILTRAGE INDOOR/OUTDOOR
                # indoor_only=None  → Tous les terrains
                # indoor_only=True  → Seulement intérieur
                # indoor_only=False → Seulement extérieur
                if indoor_only is True and not playground.get("indoor"):
                    logger.info(f"  ⏭️ SKIP (filter indoor=True, terrain={playground.get('indoor')})")
                    continue  # Skip terrains extérieurs
                elif indoor_only is False and playground.get("indoor"):
                    logger.info(f"  ⏭️ SKIP (filter indoor=False, terrain={playground.get('indoor')})")
                    continue  # Skip terrains intérieurs
                    logger.info(f"  ✅ PASS filter - Processing slots...")
                
                for activity in playground.get("activities", []):
                    if not isinstance(activity, dict):
                        continue
                    
                    if activity.get("id") != self.PADEL_ACTIVITY_ID:
                        continue
                    
                    for slot in activity.get("slots", []):
                        if not isinstance(slot, dict):
                            continue
                        
                        for price in slot.get("prices", []):
                            if not isinstance(price, dict):
                                continue
                            
                            # FLAG CRITIQUE: bookable
                            if not price.get("bookable"):
                                continue
                            
                            # Calcul prix
                            price_per_person = price.get("pricePerParticipant", 0) / 100
                            price_total = price_per_person * price.get("participantCount", 4)
                            duration_minutes = price.get("duration", 5400) // 60
                            
                            surface_data = playground.get("surface", {})
                            surface_name = surface_data.get("name", "Unknown") if isinstance(surface_data, dict) else str(surface_data)

                            available_slots.append({
                                "playground_id": playground.get("id"),
                                "playground_name": playground.get("name", "Unknown"),
                                "indoor": playground.get("indoor", False),
                                "surface": surface_name,  # ✅ Gestion robuste
                                "start_time": slot.get("startAt", "00:00"),
                                "duration_minutes": duration_minutes,
                                "price_total": round(price_total, 2),
                                "price_per_person": round(price_per_person, 2),
                                "participant_count": price.get("participantCount", 4),
                                "date": date
                            })
            
            logger.info(f"✅ Club {club_id} - {date}: {len(available_slots)} créneaux disponibles")
            return available_slots
        
        except httpx.HTTPError as e:
            logger.error(f"❌ Erreur HTTP scraping {club_id} - {date}: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Erreur inattendue scraping {club_id} - {date}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def scan_multiple_days(
        self,
        club_id: str,
        days_ahead: int,
        time_from: str,
        time_to: str,
        indoor_only: Optional[bool] = None,
        days_of_week: Optional[List[int]] = None,
        start_offset: int = 0 
    ) -> List[Dict]:
        """
        Scanne plusieurs jours à l'avance avec filtre jour de semaine
        days_of_week: [1,2,3,4,5,6,7] pour Lun-Dim
        """
        all_slots = []
        
        for day_offset in range(start_offset, days_ahead):
            check_date = datetime.now() + timedelta(days=day_offset)
            
            # Filtre jour de semaine (1=Lundi, 7=Dimanche)
            if days_of_week and check_date.isoweekday() not in days_of_week:
                logger.debug(f"⏭️ Skipping {check_date.strftime('%Y-%m-%d')} (day {check_date.isoweekday()} not in {days_of_week})")
                continue
            
            date_str = check_date.strftime("%Y-%m-%d")
            
            slots = await self.get_available_slots(
                club_id=club_id,
                date=date_str,
                time_from=time_from,
                time_to=time_to,
                indoor_only=indoor_only
            )
            
            # Vérification type
            if not isinstance(slots, list):
                logger.error(f"❌ get_available_slots returned {type(slots)} instead of list for {date_str}")
                continue
            
            all_slots.extend(slots)
            
            # Rate limiting respectueux
            await asyncio.sleep(1)
        
        logger.info(f"📊 Total scan: {len(all_slots)} créneaux sur {days_ahead} jour(s)")
        return all_slots
    
    async def close(self):
        await self.client.aclose()


# Fonction helper pour tests
async def test_scraper():
    scraper = DoinsportScraper()
    
    # ✅ UTILISER LA MÊME DATE POUR TOUS LES TESTS
    test_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    
    print("🎾 Test scraping Le Garden Rennes...")
    print(f"📅 Date de test: {test_date}")
    print(f"🏢 Club ID: {settings.LE_GARDEN_CLUB_ID}")
    print("\n")
    
    try:
        # Test 1: TOUS les terrains
        slots = await scraper.get_available_slots(
            club_id=settings.LE_GARDEN_CLUB_ID,
            date=test_date,  # ← MÊME DATE
            time_from="18:00:00",
            time_to="23:59:59",
            indoor_only=None
        )
        
        print(f"✅ {len(slots)} créneaux trouvés (TOUS terrains):\n")
        
        if slots:
            print("=" * 70)
            for i, slot in enumerate(slots[:10], 1):
                print(f"{i}. {slot['playground_name']}")
                print(f"   📅 {slot['date']} à {slot['start_time']}")
                print(f"   💰 {slot['price_total']}€ total ({slot['price_per_person']}€/personne)")
                print(f"   ⏱️ Durée: {slot['duration_minutes']} min")
                print(f"   🏠 {'Intérieur' if slot['indoor'] else 'Extérieur'} - {slot['surface']}")
                print()
            
            if len(slots) > 10:
                print(f"... et {len(slots) - 10} autres créneaux")
        else:
            print("❌ Aucun créneau disponible")
        
        print("=" * 70)
        
        # Test 2: INTÉRIEURS uniquement
        print("🔍 Test terrains INTÉRIEURS uniquement:")
        slots_indoor = await scraper.get_available_slots(
            club_id=settings.LE_GARDEN_CLUB_ID,
            date=test_date,  # ← MÊME DATE
            time_from="18:00:00",
            time_to="23:59:59",
            indoor_only=True
        )
        print(f"✅ {len(slots_indoor)} créneaux intérieurs trouvés\n")
        
        # Test 3: EXTÉRIEURS uniquement
        print("🔍 Test terrains EXTÉRIEURS uniquement:")
        slots_outdoor = await scraper.get_available_slots(
            club_id=settings.LE_GARDEN_CLUB_ID,
            date=test_date,  # ← MÊME DATE
            time_from="18:00:00",
            time_to="23:59:59",
            indoor_only=False
        )
        print(f"✅ {len(slots_outdoor)} créneaux extérieurs trouvés\n")
        
        # Vérification logique
        print(f"📊 Vérification: {len(slots_indoor)} + {len(slots_outdoor)} = {len(slots_indoor) + len(slots_outdoor)} (attendu: {len(slots)})")
        
        if len(slots_indoor) + len(slots_outdoor) != len(slots):
            print("⚠️ ATTENTION: Le total ne correspond pas!")
            print("\n🔍 Détails des créneaux TOUS:")
            for slot in slots:
                print(f"  - {slot['playground_name']}: indoor={slot['indoor']}")
        
    except Exception as e:
        print(f"❌ Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await scraper.close()
    
    print("\n✅ Test terminé")


if __name__ == "__main__":
    asyncio.run(test_scraper())
