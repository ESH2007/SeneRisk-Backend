# SeneRisk Backend

API Django + DRF (Postgres/PostGIS en Supabase, SQLite/SpatiaLite en local) para la app
[SeneRisk Atlas](https://github.com/ESH2007/SeneRisk-Frontend).

Instalación paso a paso (backend, frontend, Supabase y mapas):
**[INSTALL.md del repo frontend](https://github.com/ESH2007/SeneRisk-Frontend/blob/main/INSTALL.md)**

Arranque rápido:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edita DJANGO_SECRET_KEY y, si usas Supabase, DATABASE_URL
set -a; source .env; set +a
python manage.py migrate && python manage.py runserver 127.0.0.1:8000
```

Endpoints en `/api/` (`reportes/`, `reportes/calor/`, `auth/…`, `me/…`, `mapas/manifest/`); admin en `/admin/`.
