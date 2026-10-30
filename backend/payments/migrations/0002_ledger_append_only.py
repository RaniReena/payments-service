"""Enforce append-only semantics on the ledger at the database level.

A BEFORE UPDATE/DELETE trigger raises an exception, so no code path (ORM, raw
SQL, admin, or a future bug) can mutate or remove a ledger row. This is the
authoritative guarantee; the model-level guards in ``LedgerEntry`` are a
convenience that fail fast in Python.
"""

from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION payments_ledger_block_mutations()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'payments_ledgerentry is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payments_ledger_no_update
    BEFORE UPDATE ON payments_ledgerentry
    FOR EACH ROW EXECUTE FUNCTION payments_ledger_block_mutations();

CREATE TRIGGER payments_ledger_no_delete
    BEFORE DELETE ON payments_ledgerentry
    FOR EACH ROW EXECUTE FUNCTION payments_ledger_block_mutations();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS payments_ledger_no_update ON payments_ledgerentry;
DROP TRIGGER IF EXISTS payments_ledger_no_delete ON payments_ledgerentry;
DROP FUNCTION IF EXISTS payments_ledger_block_mutations();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
