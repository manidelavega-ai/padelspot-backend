"""
Service d'envoi d'emails avec Resend
"""
import resend
from app.core.config import settings
from typing import Dict
import logging

logger = logging.getLogger(__name__)
resend.api_key = settings.RESEND_API_KEY

def send_slot_notification(
    to_email: str,
    user_name: str,
    club_name: str,
    slot: Dict
) -> bool:
    """
    Envoie un email de notification pour un nouveau créneau
    """
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
        <h1 style="color: white; margin: 0;">🎾 Créneau disponible !</h1>
      </div>
      
      <div style="padding: 30px; background: #f9fafb;">
        <p style="font-size: 18px; color: #111827;">
          Bonjour {user_name},
        </p>
        
        <p style="font-size: 16px; color: #374151;">
          Un créneau vient de se libérer sur <strong>{club_name}</strong> !
        </p>
        
        <div style="background: white; border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid #667eea;">
          <p style="margin: 5px 0;"><strong>🏟️ Terrain :</strong> {slot['playground_name']}</p>
          <p style="margin: 5px 0;"><strong>📅 Date :</strong> {slot['date']}</p>
          <p style="margin: 5px 0;"><strong>🕐 Horaire :</strong> {slot['start_time']}</p>
          <p style="margin: 5px 0;"><strong>💰 Prix :</strong> {slot['price_total']}€</p>
          <p style="margin: 5px 0;"><strong>🏠 Type :</strong> {'Intérieur' if slot.get('indoor') else 'Extérieur'}</p>
        </div>
        
        <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
          Dépêche-toi, les créneaux partent vite ! ⚡
        </p>
      </div>
      
      <div style="padding: 20px; text-align: center; color: #9ca3af; font-size: 12px;">
        <p>Tu reçois cet email car tu as créé une alerte sur PadelSpot</p>
        <a href="{settings.FRONTEND_URL}/dashboard" style="color: #667eea;">Gérer mes alertes</a>
      </div>
    </body>
    </html>
    """
    
    try:
        params = {
            "from": settings.FROM_EMAIL,
            "to": [to_email],
            "subject": f"🎾 Nouveau créneau padel disponible - {club_name}",
            "html": html_content
        }
        
        response = resend.Emails.send(params)
        logger.info(f"✅ Email envoyé à {to_email} - ID: {response['id']}")
        return True
    
    except Exception as e:
        logger.error(f"❌ Erreur envoi email à {to_email}: {e}")
        return False
