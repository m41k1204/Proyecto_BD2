FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/ecommerce

COPY ecommerce/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# visuales.py reutiliza SIFT, vocabulario y TF-IDF del motor para el modelo k=4096 (solo numpy y OpenCV).
COPY backend/engine/__init__.py /app/backend/engine/__init__.py
COPY backend/engine/multimedia /app/backend/engine/multimedia
COPY ecommerce .

EXPOSE 8300

CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8300"]
