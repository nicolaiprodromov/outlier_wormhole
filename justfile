build:
    docker compose build

start:
    docker compose up -d

stop:
    docker compose stop

rm:
    docker compose down

restart: 
    docker compose restart

rebuild: rm build start

logs service="":
    docker compose logs -f {{ service }} --tail=1000

status:
    docker compose ps

    
