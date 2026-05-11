import psycopg2

conn = psycopg2.connect('postgresql://aiserver@localhost/avito_parser')
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS prian_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id VARCHAR(100) UNIQUE,
    company_name TEXT,
    company_url TEXT,
    total_objects INTEGER DEFAULT 0,
    countries TEXT[],
    manager_name TEXT,
    manager_position TEXT,
    manager_languages TEXT,
    phones TEXT[],
    emails TEXT[],
    whatsapp TEXT,
    telegram TEXT,
    description TEXT,
    status VARCHAR(20) DEFAULT 'new',
    priority VARCHAR(10) DEFAULT 'medium',
    source VARCHAR(20) DEFAULT 'prian',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS prian_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES prian_contacts(id),
    channel VARCHAR(20) NOT NULL,
    external_id TEXT,
    stage VARCHAR(30) DEFAULT 'initial',
    status VARCHAR(20) DEFAULT 'pending',
    last_message_at TIMESTAMPTZ,
    next_followup TIMESTAMPTZ,
    followup_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS prian_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES prian_conversations(id),
    direction VARCHAR(10) NOT NULL,
    text TEXT NOT NULL,
    template_name VARCHAR(100),
    ai_generated BOOLEAN DEFAULT FALSE,
    twilio_sid TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);
""")

conn.commit()
print("Tables created successfully")

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'prian_%'")
tables = [r[0] for r in cur.fetchall()]
print("Prian tables:", tables)

conn.close()