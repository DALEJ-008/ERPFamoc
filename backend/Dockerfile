FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Estáticos del admin (/admin/) que sirve WhiteNoise. No necesita base de datos.
RUN python manage.py collectstatic --noinput

# No ejecutar como root dentro del contenedor.
RUN useradd --system --no-create-home --uid 10001 famoc \
    && chmod +x /app/entrypoint.sh \
    && chown -R famoc:famoc /app
USER famoc

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "erpfamoc.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
