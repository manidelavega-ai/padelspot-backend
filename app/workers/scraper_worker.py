"""
Worker pour scraping automatique
"""
import asyncio
from app.core.config import settings
from app.services.doinsport_scraper import DoinsportScraper
from app.services.email_service import send_slot_notification
from app.core.database import AsyncSessionLocal
from app.models.models import UserAlert, DetectedSlot, Club
from sqlalchemy import select
from datetime import timezone, datetime, timedelta, time as time_type, date as date_type
import logging
from supabase import create_client

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def process_alert(alert_id: str):
    """
    Traite une alerte: scrape Doinsport et notifie si nouveaux créneaux
    AVEC gestion baseline (premier scan sans notification)
    """
    async with AsyncSessionLocal() as db:
        # Récupérer l'alerte
        result = await db.execute(
            select(UserAlert).where(UserAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        
        if not alert or not alert.is_active:
            logger.warning(f"⚠️ Alerte {alert_id} non trouvée ou inactive")
            return
        
        # Vérifier si la date cible est passée
        if alert.target_date < datetime.now().date():
            logger.info(f"⏭️ Alert {alert_id} date passée, désactivation")
            alert.is_active = False
            await db.commit()
            return
        
        # Récupérer le club
        result = await db.execute(
            select(Club).where(Club.id == alert.club_id)
        )
        club = result.scalar_one()
        
        is_baseline = not alert.baseline_scraped
        
        logger.info(f"🔍 Processing alert {alert_id} - Club: {club.name} - Date: {alert.target_date} - Baseline: {is_baseline}")
        
        # Scraper Doinsport pour la date cible uniquement
        scraper = DoinsportScraper()
        
        slots = await scraper.get_available_slots(
            club_id=str(club.doinsport_id),
            date=alert.target_date.strftime("%Y-%m-%d"),
            time_from=alert.time_from.strftime("%H:%M:%S"),
            time_to=alert.time_to.strftime("%H:%M:%S"),
            indoor_only=alert.indoor_only
        )
        
        await scraper.close()
        
        # Détecter nouveaux créneaux
        new_slots_count = 0
        for slot in slots:
            # CORRECTION: Convertir les strings en objets date/time
            from datetime import datetime as dt
            slot_date = dt.strptime(slot['date'], "%Y-%m-%d").date()
            slot_time = dt.strptime(slot['start_time'], "%H:%M").time()
            
            # Vérifier si déjà en DB
            existing = await db.execute(
                select(DetectedSlot).where(
                    DetectedSlot.alert_id == alert.id,
                    DetectedSlot.playground_id == slot['playground_id'],
                    DetectedSlot.date == slot_date,  # Utilise l'objet date
                    DetectedSlot.start_time == slot_time  # Utilise l'objet time
                )
            )
            
            if existing.scalar_one_or_none():
                continue  # Déjà enregistré
            
            # Nouveau créneau détecté !
            detected_slot = DetectedSlot(
                alert_id=alert.id,
                club_id=club.id,
                playground_id=slot['playground_id'],
                playground_name=slot['playground_name'],
                date=slot_date,  # Objet date
                start_time=slot_time,  # Objet time
                duration_minutes=slot['duration_minutes'],
                price_total=slot['price_total'],
                indoor=slot['indoor']
            )
            
            db.add(detected_slot)
            new_slots_count += 1
            
            # LOGIQUE BASELINE: Ne notifier QUE si baseline déjà faite
            if not is_baseline:
                # Récupérer l'email de l'utilisateur
                supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
                user_data = supabase.auth.admin.get_user_by_id(str(alert.user_id))
                
                if user_data and user_data.user:
                    user_email = user_data.user.email
                    user_name = user_data.user.email.split('@')[0]  # Ou user_data.user.user_metadata.get('name')
                    
                    # Envoyer email
                    email_sent = send_slot_notification(
                        to_email=user_email,
                        user_name=user_name,
                        club_name=club.name,
                        slot=slot
                    )
                    
                    if email_sent:
                        detected_slot.email_sent = True
                        detected_slot.email_sent_at = datetime.now()
                        logger.info(f"📧 Email envoyé à {user_email}")
                
                logger.info(f"🆕 Nouveau créneau: {slot['playground_name']} - {slot['date']} {slot['start_time']}")
            else:
                logger.info(f"📋 Baseline: {slot['playground_name']} - {slot['date']} {slot['start_time']} (pas de notif)")

        
        # Marquer baseline comme fait au premier scan
        if is_baseline:
            alert.baseline_scraped = True
            logger.info(f"✅ Baseline établie pour alert {alert_id} - {len(slots)} créneaux")
        
        # Update last_checked_at
        alert.last_checked_at = datetime.now()
        await db.commit()
        
        logger.info(f"✅ Alert {alert_id} processed - {new_slots_count} nouveaux créneaux")



async def scheduler_loop():
    """
    Boucle infinie qui schedule les jobs périodiquement
    """
    logger.info("🚀 Scheduler started")
    
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # Récupérer toutes les alertes actives
                result = await db.execute(
                    select(UserAlert).where(UserAlert.is_active == True)
                )
                alerts = result.scalars().all()
                
                logger.info(f"📋 {len(alerts)} alerte(s) active(s)")
                
                for alert in alerts:
                    # Vérifier si besoin de check (selon interval)
                    if alert.last_checked_at:
                        minutes_since = (datetime.now(timezone.utc) - alert.last_checked_at).total_seconds() / 60
                        if minutes_since < alert.check_interval_minutes:
                            continue
                    
                    # Process directement (pas de Redis Queue pour MVP)
                    await process_alert(str(alert.id))
            
            logger.info(f"💤 Sleeping {settings.WORKER_CHECK_INTERVAL}s...")
            await asyncio.sleep(settings.WORKER_CHECK_INTERVAL)
        
        except Exception as e:
            logger.error(f"❌ Scheduler error: {e}")
            await asyncio.sleep(10)  # Retry après 10s

if __name__ == "__main__":
    asyncio.run(scheduler_loop())
