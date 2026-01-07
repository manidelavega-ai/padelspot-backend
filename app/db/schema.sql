-- ============================================
-- PADELSPOT - DATABASE SCHEMA
-- ============================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- TABLES
-- ============================================

-- Subscriptions (lié à auth.users de Supabase)
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_customer_id VARCHAR(255) UNIQUE,
    stripe_subscription_id VARCHAR(255) UNIQUE,
    plan VARCHAR(20) NOT NULL CHECK (plan IN ('free', 'premium')),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'canceled', 'past_due', 'trialing')),
    current_period_end TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Clubs Doinsport
CREATE TABLE IF NOT EXISTS clubs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doinsport_id UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    address TEXT,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User Alerts
CREATE TABLE IF NOT EXISTS user_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    club_id UUID NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
    
    -- Préférences
    time_from TIME NOT NULL,
    time_to TIME NOT NULL,
    days_of_week INTEGER[] NOT NULL,
    indoor_only BOOLEAN DEFAULT NULL,
    
    -- Metadata
    is_active BOOLEAN DEFAULT true,
    check_interval_minutes INTEGER NOT NULL DEFAULT 15,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Contraintes
    CONSTRAINT valid_time_range CHECK (time_to > time_from),
    CONSTRAINT valid_days CHECK (array_length(days_of_week, 1) > 0 AND array_length(days_of_week, 1) <= 7)
);

-- Detected Slots (historique)
CREATE TABLE IF NOT EXISTS detected_slots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_id UUID NOT NULL REFERENCES user_alerts(id) ON DELETE CASCADE,
    club_id UUID NOT NULL REFERENCES clubs(id),
    
    -- Données slot
    playground_id UUID NOT NULL,
    playground_name VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    start_time TIME NOT NULL,
    duration_minutes INTEGER,
    price_total NUMERIC(6,2),
    indoor BOOLEAN,
    
    -- Notification
    email_sent BOOLEAN DEFAULT false,
    email_sent_at TIMESTAMP WITH TIME ZONE,
    
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Éviter doublons
    UNIQUE(alert_id, playground_id, date, start_time)
);

-- ============================================
-- INDEXES
-- ============================================

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe ON subscriptions(stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_clubs_doinsport ON clubs(doinsport_id);
CREATE INDEX IF NOT EXISTS idx_clubs_enabled ON clubs(enabled) WHERE enabled = true;

CREATE INDEX IF NOT EXISTS idx_alerts_user ON user_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON user_alerts(is_active, last_checked_at) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_alerts_club ON user_alerts(club_id);

CREATE INDEX IF NOT EXISTS idx_slots_alert ON detected_slots(alert_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_slots_date ON detected_slots(date, start_time);
CREATE INDEX IF NOT EXISTS idx_slots_email ON detected_slots(email_sent) WHERE email_sent = false;

-- ============================================
-- INITIAL DATA
-- ============================================

-- Insert Le Garden Rennes
INSERT INTO clubs (doinsport_id, name, city, address) 
VALUES (
    'a126b4d4-a2ee-4f30-bee3-6596368368fb',
    'Le Garden Rennes',
    'Rennes',
    'À compléter'
) ON CONFLICT (doinsport_id) DO NOTHING;

-- ============================================
-- FUNCTIONS & TRIGGERS
-- ============================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_subscriptions_updated_at BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_alerts_updated_at BEFORE UPDATE ON user_alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- VIEWS
-- ============================================

CREATE OR REPLACE VIEW user_dashboard AS
SELECT 
    u.id as user_id,
    u.email,
    COALESCE(s.plan, 'free') as plan,
    COUNT(DISTINCT a.id) FILTER (WHERE a.is_active = true) as active_alerts,
    COUNT(DISTINCT ds.id) as total_slots_detected,
    COUNT(DISTINCT ds.id) FILTER (WHERE ds.detected_at > NOW() - INTERVAL '7 days') as slots_last_week,
    COUNT(DISTINCT ds.id) FILTER (WHERE ds.detected_at > NOW() - INTERVAL '30 days') as slots_last_month
FROM auth.users u
LEFT JOIN subscriptions s ON u.id = s.user_id
LEFT JOIN user_alerts a ON u.id = a.user_id
LEFT JOIN detected_slots ds ON a.id = ds.alert_id
GROUP BY u.id, u.email, s.plan;

-- ============================================
-- RLS POLICIES (Row Level Security)
-- ============================================

-- Enable RLS
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE detected_slots ENABLE ROW LEVEL SECURITY;

-- Subscriptions: Users can only see their own
CREATE POLICY subscriptions_user_policy ON subscriptions
    FOR ALL USING (auth.uid() = user_id);

-- User Alerts: Users can only manage their own
CREATE POLICY alerts_user_policy ON user_alerts
    FOR ALL USING (auth.uid() = user_id);

-- Detected Slots: Users can only see their own
CREATE POLICY slots_user_policy ON detected_slots
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM user_alerts 
            WHERE user_alerts.id = detected_slots.alert_id 
            AND user_alerts.user_id = auth.uid()
        )
    );

-- Clubs: Public read access
ALTER TABLE clubs ENABLE ROW LEVEL SECURITY;
CREATE POLICY clubs_public_read ON clubs
    FOR SELECT USING (true);
