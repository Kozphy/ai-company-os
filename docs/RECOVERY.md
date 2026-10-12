# Local recovery, backup and rollback

## SQLite

Stop API, worker and scheduler before copying `runtime/company.db` and WAL companions. Store the backup outside the repository. Restore with services stopped by replacing the database files, then restart. SQLite is for local evaluation.

## Compose PostgreSQL

The `pgdata` volume is not a backup. Create a protected logical dump with `docker compose exec -T db pg_dump -U company_os company_os` and redirect it to a secure external path. Restore into a compatible PostgreSQL instance with services stopped. Rehearse restoration before relying on records. Never commit database dumps.

`docker compose down` preserves the volume. `docker compose down -v` deletes it. Before an upgrade, take a dump and record the source revision. Alembic migration runs before API startup. If migration fails, stop services, restore the pre-migration dump, and run the previous revision; automated downgrade is not promised.

This recovery process has not been exercised against a deployed service.
