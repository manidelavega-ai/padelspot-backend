import asyncio
from app.services.email_service import send_slot_notification

# Test email
result = send_slot_notification(
    to_email="manidelavega@gmail.com",  # TON EMAIL ICI
    user_name="Mani",
    club_name="Le Garden Rennes",
    slot={
        'playground_name': 'Padel 1',
        'date': '2026-01-07',
        'start_time': '20:00',
        'price_total': 36.0,
        'indoor': True
    }
)

print(f"Email envoyé : {result}")
