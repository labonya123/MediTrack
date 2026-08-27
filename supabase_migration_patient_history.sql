ALTER TABLE patient_diseases
    ADD COLUMN IF NOT EXISTS recorded_by TEXT DEFAULT 'clinical',
    ADD COLUMN IF NOT EXISTS is_deleted  INTEGER DEFAULT 0;

ALTER TABLE patient_allergies
    ADD COLUMN IF NOT EXISTS notes       TEXT,
    ADD COLUMN IF NOT EXISTS recorded_by TEXT DEFAULT 'clinical',
    ADD COLUMN IF NOT EXISTS is_deleted  INTEGER DEFAULT 0;

ALTER TABLE hospitalizations
    ADD COLUMN IF NOT EXISTS recorded_by TEXT DEFAULT 'clinical',
    ADD COLUMN IF NOT EXISTS is_deleted  INTEGER DEFAULT 0;

ALTER TABLE surgeries
    ADD COLUMN IF NOT EXISTS recorded_by TEXT DEFAULT 'clinical',
    ADD COLUMN IF NOT EXISTS is_deleted  INTEGER DEFAULT 0;
