#!/bin/bash

git pull

cd cinema-kiosk

vi .env

docker compose up -d --build

docker compose exec updater python updater.py --once
docker compose logs -f
