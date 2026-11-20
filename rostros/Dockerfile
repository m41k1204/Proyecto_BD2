FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/rostros

COPY rostros/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY rostros .

EXPOSE 8200

CMD ["sh", "-c", "python -c 'import descargas; descargas.modelos()' && exec uvicorn servidor:app --host 0.0.0.0 --port 8200"]
