-- ============================================================
-- TRUST LAYER — Global Business Intelligence Schema
-- ============================================================
-- Four core tables:
-- 1. businesses   — entities we track globally
-- 2. signals      — raw data points from all collectors
-- 3. trust_scores — derived scores, updated as signals grow
-- 4. market_prices — commodity/goods price tracking over time
-- ============================================================

-- Businesses we are tracking
CREATE TABLE IF NOT EXISTS businesses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    registration_number VARCHAR(100),
    jurisdiction VARCHAR(100),        -- country or region
    sector VARCHAR(100),              -- wholesale, pharmacy, logistics, etc.
    city VARCHAR(100),
    country VARCHAR(100),
    source VARCHAR(100),              -- where we first found this business
    source_url TEXT,
    status VARCHAR(50) DEFAULT 'active',  -- active, dissolved, flagged
    first_seen TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    metadata JSONB                    -- flexible extra fields per jurisdiction
);

CREATE INDEX IF NOT EXISTS idx_businesses_country ON businesses(country);
CREATE INDEX IF NOT EXISTS idx_businesses_jurisdiction ON businesses(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_businesses_name ON businesses(name);
CREATE INDEX IF NOT EXISTS idx_businesses_registration ON businesses(registration_number);

-- Raw signals collected from all sources
CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id),
    signal_type VARCHAR(100) NOT NULL,   -- court_filing, gazette_notice, news_mention, price_data, registry_update
    signal_category VARCHAR(50) NOT NULL, -- negative, positive, neutral
    source VARCHAR(100) NOT NULL,         -- kenyalaw, opencorporates, gdelt, companies_house, etc.
    source_url TEXT,
    title TEXT,
    content TEXT,
    signal_date TIMESTAMP,               -- when the signal occurred
    collected_at TIMESTAMP DEFAULT NOW(), -- when we collected it
    weight DECIMAL(4,2) DEFAULT 0.0,     -- algorithmic weight assigned
    processed BOOLEAN DEFAULT FALSE,      -- has scorer processed this yet
    metadata JSONB                        -- flexible extra data per signal type
);

CREATE INDEX IF NOT EXISTS idx_signals_business_id ON signals(business_id);
CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_category ON signals(signal_category);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_processed ON signals(processed);

-- Trust scores per business — updated by scorer algorithm
CREATE TABLE IF NOT EXISTS trust_scores (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id) UNIQUE,
    score DECIMAL(5,2) DEFAULT 50.0,     -- 0-100 scale
    confidence DECIMAL(4,2) DEFAULT 0.0, -- 0-1 how confident we are
    signal_count INTEGER DEFAULT 0,       -- total signals used
    negative_signals INTEGER DEFAULT 0,
    positive_signals INTEGER DEFAULT 0,
    neutral_signals INTEGER DEFAULT 0,
    last_court_filing TIMESTAMP,
    last_gazette_notice TIMESTAMP,
    risk_level VARCHAR(20) DEFAULT 'unknown', -- low, medium, high, critical, unknown
    trend VARCHAR(20) DEFAULT 'stable',       -- improving, declining, stable
    calculated_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_trust_scores_business ON trust_scores(business_id);
CREATE INDEX IF NOT EXISTS idx_trust_scores_score ON trust_scores(score);
CREATE INDEX IF NOT EXISTS idx_trust_scores_risk ON trust_scores(risk_level);

-- Market prices — commodity and goods price tracking globally
CREATE TABLE IF NOT EXISTS market_prices (
    id SERIAL PRIMARY KEY,
    commodity VARCHAR(100) NOT NULL,     -- cooking oil, cement, electronics, etc.
    price DECIMAL(12,2) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    unit VARCHAR(50),                    -- per kg, per box, per unit
    market VARCHAR(100),                 -- Nairobi, Lagos, Jakarta, etc.
    country VARCHAR(100),
    source VARCHAR(100),
    source_url TEXT,
    recorded_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_market_prices_commodity ON market_prices(commodity);
CREATE INDEX IF NOT EXISTS idx_market_prices_country ON market_prices(country);
CREATE INDEX IF NOT EXISTS idx_market_prices_date ON market_prices(recorded_at);

-- Signal weights reference table
-- Defines how much each signal type affects trust score
CREATE TABLE IF NOT EXISTS signal_weights (
    id SERIAL PRIMARY KEY,
    signal_type VARCHAR(100) UNIQUE NOT NULL,
    weight DECIMAL(4,2) NOT NULL,        -- negative = bad, positive = good
    description TEXT
);

-- Seed signal weights
INSERT INTO signal_weights (signal_type, weight, description) VALUES
    ('court_debt_filing',      -0.30, 'Business named in debt court case'),
    ('insolvency_notice',      -0.50, 'Gazette insolvency or liquidation notice'),
    ('dissolution_notice',     -0.40, 'Business being dissolved'),
    ('fraud_allegation',       -0.45, 'Fraud mentioned in news or court filing'),
    ('late_payment_report',    -0.25, 'Reported as late payer'),
    ('default_report',         -0.35, 'Reported as defaulting on payment'),
    ('negative_news',          -0.15, 'Negative news mention'),
    ('regulatory_violation',   -0.30, 'Regulatory or compliance violation'),
    ('registration_active',     0.10, 'Active business registration'),
    ('registration_old',        0.15, 'Business registered more than 3 years'),
    ('directory_listing',       0.05, 'Listed in business directory'),
    ('positive_news',           0.10, 'Positive news mention'),
    ('multiple_jurisdictions',  0.10, 'Operating across multiple jurisdictions'),
    ('price_consistency',       0.10, 'Consistent pricing signals')
ON CONFLICT (signal_type) DO NOTHING;