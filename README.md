# DRTsim
Simulator for Demand Responsive Transport

## Dependencies

```bash
python 3.6+
pip install simpy
pip install python-statemachine
conda install -c anaconda pandas
conda install -c anaconda requests
conda install -c anaconda pyyaml
conda install -c anaconda xlsxwriter
```
## installing OSRM

```bash
sudo install docker docker.io

wget http://download.geofabrik.de/europe/sweden-latest.osm.pbf

sudo docker run -t -v "/home/username/osrm:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua /data/sweden-latest.osm.pbf
sudo docker run -t -v "/home/username/osrm:/data" osrm/osrm-backend osrm-partition /data/sweden-latest.osrm
sudo docker run -t -v "/home/username/osrm:/data" osrm/osrm-backend osrm-customize /data/sweden-latest.osrm
sudo docker run  -t -i -p 5000:5000 -v "/home/username/osrm/:/data" osrm/osrm-backend osrm-routed --max-table-size 1000000  --algorithm MLD /data/sweden-latest.osrm
```
## Assumptions for OTP

You have OpenTripPlanner server running at localhost:8080

#TODO: add proper compilation sequence for OTP and jsprit 