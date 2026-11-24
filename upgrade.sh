cd ..
tar -xvzf ../cinema-kios*5*.tar.gz 
cd cinema-kiosk
docker compose up -d --build updater && docker compose exec updater python updater.py --once
rm ../preview/* && docker compose cp "updater:/data/$(docker compose exec -T updater readlink /data/current)/." ../preview

