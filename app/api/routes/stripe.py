"""
Routes Stripe (checkout, webhooks, customer portal)
"""
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import Subscription
import stripe
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["stripe"])

stripe.api_key = settings.STRIPE_SECRET_KEY

@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook Stripe pour gérer les événements d'abonnement
    URL à configurer dans Stripe Dashboard:
    https://api.padelspot.com/api/webhooks/stripe
    """
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        # Vérifier la signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error("❌ Webhook: Invalid payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.error("❌ Webhook: Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Gérer les événements
    event_type = event["type"]
    data = event["data"]["object"]
    
    logger.info(f"📨 Stripe webhook received: {event_type}")
    
    # === ÉVÉNEMENTS GÉRÉS ===
    
    if event_type == "checkout.session.completed":
        # Utilisateur a complété le paiement
        session = data
        user_id = session["client_reference_id"]  # On passera le user_id ici
        customer_id = session["customer"]
        subscription_id = session["subscription"]
        
        # Créer ou update subscription
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.stripe_customer_id = customer_id
            subscription.stripe_subscription_id = subscription_id
            subscription.plan = "premium"
            subscription.status = "active"
        else:
            subscription = Subscription(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                plan="premium",
                status="active"
            )
            db.add(subscription)
        
        await db.commit()
        logger.info(f"✅ Subscription created/updated for user {user_id}")
    
    elif event_type == "customer.subscription.updated":
        # Abonnement mis à jour (renouvellement, etc.)
        sub = data
        
        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == sub["id"]
            )
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.status = sub["status"]
            subscription.current_period_end = sub["current_period_end"]
            await db.commit()
            logger.info(f"✅ Subscription updated: {sub['id']}")
    
    elif event_type == "customer.subscription.deleted":
        # Abonnement annulé
        sub = data
        
        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == sub["id"]
            )
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.status = "canceled"
            subscription.plan = "free"
            await db.commit()
            logger.info(f"🚫 Subscription canceled: {sub['id']}")
    
    elif event_type == "invoice.payment_failed":
        # Paiement échoué
        invoice = data
        subscription_id = invoice["subscription"]
        
        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.status = "past_due"
            await db.commit()
            logger.warning(f"⚠️ Payment failed for subscription: {subscription_id}")
    
    return JSONResponse(content={"status": "success"})


@router.post("/subscription/checkout")
async def create_checkout_session(
    current_user = Depends(get_current_user)
):
    """
    Créer une session Stripe Checkout pour upgrade Premium
    """
    
    try:
        checkout_session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            client_reference_id=str(current_user.id),  # Important: pour lier au webhook
            payment_method_types=["card"],
            line_items=[
                {
                    "price": settings.STRIPE_PRICE_ID_PREMIUM,
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url=f"{settings.FRONTEND_URL}/dashboard?success=true",
            cancel_url=f"{settings.FRONTEND_URL}/pricing?canceled=true",
            metadata={
                "user_id": str(current_user.id)
            }
        )
        
        return {"url": checkout_session.url}
    
    except Exception as e:
        logger.error(f"❌ Checkout error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subscription/portal")
async def create_customer_portal(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Créer un lien vers le Customer Portal Stripe
    Pour gérer abonnement, annulation, facturation
    """
    
    # Récupérer le customer_id Stripe
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(
            status_code=404, 
            detail="Aucun abonnement trouvé"
        )
    
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=f"{settings.FRONTEND_URL}/dashboard",
        )
        
        return {"url": portal_session.url}
    
    except Exception as e:
        logger.error(f"❌ Portal error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
