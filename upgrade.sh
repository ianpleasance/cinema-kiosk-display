cd ..
tar -xvzf ../cinema-kiosk.tar.gz 
cd cinema-kiosk
docker compose up -d --build updater && docker compose exec updater python updater.py --once
rm ../preview/* && docker compose cp "updater:/data/$(docker compose exec -T updater readlink /data/current)/." ../preview

