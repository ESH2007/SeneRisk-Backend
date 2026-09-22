FROM python:3.12-slim
# GDAL/GEOS para django.contrib.gis
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD sh -c "python manage.py migrate && gunicorn config.wsgi --bind 0.0.0.0:${PORT:-10000}"
