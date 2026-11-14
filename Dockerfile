# Imagen del HR Assistant para Render (spec/04-production.md, punto 5).
FROM python:3.12-slim

# Sin archivos .pyc y con la salida sin búfer, para que el log JSON salga al momento
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Primero las dependencias: esta capa se reutiliza mientras requirements.txt no cambie
COPY requirements.txt .
RUN pip install -r requirements.txt

# Solo lo que el producto necesita para correr: el código y los datos
COPY app/ app/
COPY data/ data/

# Usuario sin privilegios: el proceso no corre como root
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Render fija PORT; en local se usa 8000. exec deja a uvicorn como proceso principal
# para que reciba las señales de apagado.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
