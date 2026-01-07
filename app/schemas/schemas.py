from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import time, date, datetime, timedelta
from uuid import UUID

# === ALERT SCHEMAS ===

class AlertCreate(BaseModel):
    club_id: UUID
    target_date: date  # NOUVEAU: Date unique ciblée
    time_from: time
    time_to: time
    indoor_only: Optional[bool] = None
    
    @validator('target_date')
    def validate_target_date(cls, v, values):
        """Validation selon le plan (sera vérifié côté backend avec le plan user)"""
        today = date.today()
        
        # Validation minimale: pas dans le passé
        if v < today:
            raise ValueError('target_date ne peut pas être dans le passé')
        
        return v
    
    @validator('time_to')
    def validate_time_range(cls, v, values):
        if 'time_from' in values:
            time_from = values['time_from']
            
            # Calculer la différence en heures
            from_minutes = time_from.hour * 60 + time_from.minute
            to_minutes = v.hour * 60 + v.minute
            diff_hours = (to_minutes - from_minutes) / 60
            
            if diff_hours <= 0:
                raise ValueError('time_to doit être après time_from')
            
            # Validation max 24h (sera affinée côté backend selon plan)
            if diff_hours > 24:
                raise ValueError('La plage horaire ne peut pas dépasser 24 heures')
        
        return v

class AlertUpdate(BaseModel):
    target_date: Optional[date] = None
    time_from: Optional[time] = None
    time_to: Optional[time] = None
    indoor_only: Optional[bool] = None
    is_active: Optional[bool] = None

class AlertResponse(BaseModel):
    id: UUID
    club_id: UUID
    target_date: date
    time_from: time
    time_to: time
    indoor_only: Optional[bool]
    is_active: bool
    check_interval_minutes: int
    baseline_scraped: bool
    last_checked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# === CLUB SCHEMAS ===

class ClubResponse(BaseModel):
    id: UUID
    doinsport_id: UUID
    name: str
    city: Optional[str]
    address: Optional[str]
    enabled: bool
    
    class Config:
        from_attributes = True

# === SLOT SCHEMAS ===

class DetectedSlotResponse(BaseModel):
    id: UUID
    playground_name: str
    date: date
    start_time: time
    duration_minutes: Optional[int]
    price_total: Optional[float]
    indoor: Optional[bool]
    email_sent: bool
    detected_at: datetime
    
    class Config:
        from_attributes = True
