# Internal Research Strain Database (Django)

## Tailwind CSS integration
```bash
npm install
npm run build:css
# or during development
npm run watch:css
```

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## PostgreSQL environment
```bash
export POSTGRES_DB=strain_db
export POSTGRES_USER=strain_user
export POSTGRES_PASSWORD='strong-password'
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
```

## Linux HTTPS deployment notes
- Run Django behind Gunicorn (`gunicorn strain_db.wsgi:application`) and terminate TLS at Nginx.
- Forward `X-Forwarded-Proto https` from Nginx so `SECURE_PROXY_SSL_HEADER` works.
- Keep `DJANGO_DEBUG=False`, define `DJANGO_SECRET_KEY`, and set `DJANGO_ALLOWED_HOSTS`.
- Collect static assets with `python manage.py collectstatic --noinput` and serve `/static/` via Nginx.
- Only admins create accounts: use Django admin at `/admin/` and do not expose any signup route.
