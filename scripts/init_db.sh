#!/bin/bash
# JuniperAI Database Initialization Script
# Usage: ./scripts/init_db.sh [--docker | --local]

set -e

DB_NAME="juniper_ai"
DB_USER="${POSTGRES_USER:-postgres}"
DB_PASS="${POSTGRES_PASSWORD:-postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

echo "=== JuniperAI Database Initialization ==="
echo ""

MODE="${1:---local}"

if [ "$MODE" = "--docker" ]; then
    echo "1. Starting PostgreSQL via Docker Compose..."
    docker-compose up -d db
    echo "   Waiting for PostgreSQL to be ready..."
    sleep 3
    until docker-compose exec -T db pg_isready -U "$DB_USER" 2>/dev/null; do
        sleep 1
    done
    echo "   PostgreSQL is ready."
    echo ""
fi

echo "2. Creating database (if not exists)..."
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -tc \
    "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 \
    || PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c \
    "CREATE DATABASE $DB_NAME"
echo "   Database '$DB_NAME' ready."
echo ""

echo "3. Running initialization SQL..."
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -f scripts/init_db.sql
echo "   Tables created successfully."
echo ""

echo "=== Initialization Complete ==="
echo ""
echo "Database: $DB_NAME"
echo "Host: $DB_HOST:$DB_PORT"
echo "User: $DB_USER"
echo ""
echo "Connection string:"
echo "  postgresql+asyncpg://$DB_USER:$DB_PASS@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env and fill in API keys"
echo "  2. Run: uvicorn juniper_ai.app.main:app --reload"
echo "  3. Test: curl http://localhost:8000/api/v1/health"
