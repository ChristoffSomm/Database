# HelixMapr

Modern Research Strain Management Platform

## Tailwind CSS integration
```bash
npm install
npm run build:css
# or during development
npm run watch:css
```

## 🚀 Running HelixMapr (Development)

This project includes an automated setup script.

### First-time setup

```bash
chmod +x setup_and_start.sh
./setup_and_start.sh
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

## Railway deploy command
Use this Railway deploy command:

```bash
python manage.py migrate && python manage.py collectstatic --noinput && gunicorn strain_db.wsgi:application --bind 0.0.0.0:$PORT
```

## 🚀 Railway Deployment Guide

### 1️⃣ Create Railway Project
- Create a new Railway project.
- Add the PostgreSQL plugin.
- Deploy from your GitHub repository.

### 2️⃣ Add Environment Variables
Set these in Railway → Variables:

```bash
DJANGO_SECRET_KEY=your-generated-secret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-app-name.up.railway.app
DJANGO_SECURE_SSL_REDIRECT=True

ADMIN_USER_1=ChrisS
ADMIN_PASS_1=NotAHardPassword0
ADMIN_USER_2=JacobG
ADMIN_PASS_2=NotAHardPassword1
```

Do **NOT** manually set `DATABASE_URL` — Railway injects it automatically.

### 3️⃣ Deployment Command
Railway will automatically run:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn strain_db.wsgi:application --bind 0.0.0.0:$PORT
```

### 4️⃣ Tailwind Note
Tailwind CSS must be built locally:

```bash
npm install
npm run build:css
git add static/css/styles.css
git commit -m "Build production CSS"
git push
```

Production does **NOT** run npm.

### 5️⃣ Accessing the App
Railway will provide:

`https://your-app-name.up.railway.app`
