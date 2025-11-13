# build all services
build:
    docker compose build

# start all services
start:
    docker compose up -d

# stop all services
stop:
    docker compose stop

# stop and remove all services
rm:
    docker compose down

# restart all services
restart: 
    docker compose restart

# remove, build and start services
rebuild: rm build start

# get logs from any service
logs service="":
    docker compose logs -f {{ service }} --tail=1000

# get status for all services
status:
    docker compose ps

# clean up the data folder
clean:
    ./scripts/clean.sh

# stop, remove, clean up data and start
reset: rm clean rebuild

    
