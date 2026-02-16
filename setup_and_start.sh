#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[setup_and_start] $1"
}

# ----------------------------------------
# Check prerequisites
# ----------------------------------------
log "Checking prerequisites (Python 3, Node.js, npm)..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is not installed." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Error: node is not installed." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is not installed." >&2
  exit 1
fi

# ----------------------------------------
# Setup virtual environment
# ----------------------------------------
log "Setting up Python virtual environment (.venv)..."

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
  log "Created virtual environment"
else
  log "Reusing existing .venv"
fi

source .venv/bin/activate
log "Virtual environment activated: $(python --version)"

# ----------------------------------------
# Install Python dependencies
# ----------------------------------------
log "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# ----------------------------------------
# Dev environment variables
# ----------------------------------------
log "Exporting development environment variables..."

export SQLITE_NAME="db.sqlite3"
export DJANGO_DEBUG="True"

# ----------------------------------------
# Ensure static directory exists
# ----------------------------------------
log "Ensuring static/css directory exists..."
mkdir -p static/css

# ----------------------------------------
# Install and build Tailwind
# ----------------------------------------
log "Installing Tailwind dependencies..."
npm install

log "Building Tailwind CSS..."
npm run build:css

# ----------------------------------------
# Django migrations
# ----------------------------------------
log "Running Django migrations..."
python manage.py makemigrations research || true
python manage.py migrate

# ----------------------------------------
# Superuser setup
# ----------------------------------------
log "Ensuring Django superuser exists..."

read -r -p "Superuser username: " SUPERUSER_NAME
read -r -p "Superuser email: " SUPERUSER_EMAIL
read -r -s -p "Superuser password: " SUPERUSER_PASS
echo

export DJANGO_SUPERUSER_USERNAME="$SUPERUSER_NAME"
export DJANGO_SUPERUSER_EMAIL="$SUPERUSER_EMAIL"
export DJANGO_SUPERUSER_PASSWORD="$SUPERUSER_PASS"

python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()

username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ["DJANGO_SUPERUSER_EMAIL"]
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]

user, created = User.objects.get_or_create(username=username, defaults={"email": email})

if created:
    print("Creating new superuser...")
    user.is_staff = True
    user.is_superuser = True

user.email = email
user.set_password(password)
user.is_staff = True
user.is_superuser = True
user.save()

print(f"Superuser '{username}' is ready.")
PY

# ----------------------------------------
# Start server
# ----------------------------------------
log "Starting Django development server on 0.0.0.0:8000..."
python manage.py runserver 0.0.0.0:8000
