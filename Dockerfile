FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для bleak (libbluetooth)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libbluetooth-dev \
    bluez \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём директорию для БД
RUN mkdir -p data

EXPOSE 8000

CMD ["python", "collector/main.py"]
