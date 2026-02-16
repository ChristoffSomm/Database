#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[setup_and_start] $1"
}

is_sourced=0
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  is_sourced=1
fi

log "Checking prerequisites (Python 3, Node.js, npm)..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is not installed. Please install Python 3 and re-run." >&2
  [[ $is_sourced -eq 1 ]] && return 1 || exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Error: node is not installed. Please install Node.js and re-run." >&2
  [[ $is_sourced -eq 1 ]] && return 1 || exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is not installed. Please install npm and re-run." >&2
  [[ $is_sourced -eq 1 ]] && return 1 || exit 1
fi

log "Setting up Python virtual environment (.venv)..."
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
  log "Created virtual environment in .venv"
else
  log "Reusing existing .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
log "Virtual environment activated: $(python --version)"

log "Installing Python dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

log "Exporting environment variables..."
export SQLITE_NAME="db.sqlite3"
# Preserve superuser variables if already provided by user/session.
export SUPERUSER_NAME="${SUPERUSER_NAME:-}"
export SUPERUSER_EMAIL="${SUPERUSER_EMAIL:-}"
export SUPERUSER_PASS="${SUPERUSER_PASS:-}"

log "Installing Tailwind dependencies (npm install)..."
npm install

log "Evaluating whether Tailwind CSS rebuild is needed..."
TAILWIND_STAMP=".tailwind_build.stamp"
TAILWIND_SOURCES=(
  "package.json"
  "tailwind.config.js"
  "postcss.config.js"
)
if [[ -d "tailwind/src" ]]; then
  while IFS= read -r f; do
    TAILWIND_SOURCES+=("$f")
  done < <(find tailwind/src -type f | sort)
fi

needs_build=0
if [[ ! -f "$TAILWIND_STAMP" ]]; then
  needs_build=1
else
  for src in "${TAILWIND_SOURCES[@]}"; do
    if [[ -f "$src" && "$src" -nt "$TAILWIND_STAMP" ]]; then
      needs_build=1
      break
    fi
  done
fi

if [[ $needs_build -eq 1 ]]; then
  log "Building Tailwind CSS (npm run build:css)..."
  npm run build:css
  touch "$TAILWIND_STAMP"
else
  log "Tailwind build is up to date; skipping npm run build:css"
fi

log "Running Django migrations..."
python manage.py makemigrations research
python manage.py migrate

log "Ensuring Django superuser exists..."
if [[ -n "${SUPERUSER_NAME}" && -n "${SUPERUSER_EMAIL}" && -n "${SUPERUSER_PASS}" ]]; then
  log "Creating/updating superuser non-interactively from environment variables..."
else
  log "Superuser environment variables not fully set; prompting for details..."
  read -r -p "Superuser username: " SUPERUSER_NAME
  read -r -p "Superuser email: " SUPERUSER_EMAIL
  read -r -s -p "Superuser password: " SUPERUSER_PASS
  echo
fi

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
    user.is_staff = True
    user.is_superuser = True

if email and user.email != email:
    user.email = email

if not user.is_staff:
    user.is_staff = True
if not user.is_superuser:
    user.is_superuser = True

user.set_password(password)
user.save()

print(f"Superuser '{username}' is ready.")
PY

log "Starting Django development server on 0.0.0.0:8000..."
python manage.py runserver 0.0.0.0:8000
