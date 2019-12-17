from sim_utils import Coord, Trip, Step, Leg
from const import OtpMode
import json
import requests


def _try(o):
    return o.__dict__


class VisualTripWrapper(object):

    def __init__(self, l):
        self.trips = l

    def to_json(self):
        return json.dumps(self, default=lambda o: _try(o), sort_keys=False, indent=4, separators=(',', ':'))


class VisualTrip(object):

    def __init__(self, trip: Trip, person_id, status):
        self.coord_start = trip.legs[0].start_coord
        self.coord_end = trip.legs[0].end_coord
        self.time_start = trip.legs[0].start_time
        self.time_end = trip.legs[0].end_time
        self.person_id = person_id
        self.status = status

    def __str__(self):
        return '[(({}),({})),({},{})]'.format(self.coord_start, self.coord_end, self.time_start, self.time_end)

    def __repr__(self):
        return str(self)


def _try_json_pop(o):
    try:
        return o.dumps()
    except:
        return o.__dict__


class PopulationWrapper(object):

    def __init__(self, l):
        self.person = l

    def to_json(self):
        return json.dumps(self, default=lambda o: _try_json_pop(o), sort_keys=False, indent=4, separators=(',', ':'))


def osrm_route_request(config, from_place, to_place):
    url_coords = '{}{},{};{},{}' \
        .format(config.get('service.osrm_route'),
                from_place.lon, from_place.lat, to_place.lon, to_place.lat)
    url_full = url_coords + '?annotations=true&geometries=geojson&steps=true'
    resp = requests.get(url=url_full)
    return _parse_osrm_response(resp)


def _parse_osrm_response(resp):
    # if resp.status_code != requests.codes.ok:
    #     resp.raise_for_status()

    jresp = resp.json()
    # if jresp.get('code') != 'Ok':
    #     log.error(jresp.get('code'))
    #     log.error(jresp.get('message'))
    #     resp.raise_for_status()

    trip = Trip()
    trip.legs = [Leg()]
    trip.legs[0].steps = []

    legs = jresp.get('routes')[0].get('legs')
    for leg in legs:
        steps = leg.get('steps')
        for step in steps:
            new_step = Step(distance=step.get('distance'),
                            duration=step.get('duration'),
                            start_coord=Coord(lon=step.get('geometry').get('coordinates')[0][0],
                                              lat=step.get('geometry').get('coordinates')[0][1]),
                            end_coord=Coord(lon=step.get('geometry').get('coordinates')[-1][0],
                                            lat=step.get('geometry').get('coordinates')[-1][1]))
            # OSRM makes circles on roundabouts. And makes empty step in the end. Exclude these cases from a route
            if new_step.start_coord != new_step.end_coord:
                trip.legs[0].steps.append(new_step)
        if len(trip.legs[0].steps) == 0:
            waypoints = jresp.get('waypoints')
            trip.legs[0].steps.append(Step(distance=0,
                                           duration=0,
                                           start_coord=Coord(lon=waypoints[0].get('location')[0],
                                                             lat=waypoints[0].get('location')[1]),
                                           end_coord=Coord(lon=waypoints[1].get('location')[0],
                                                           lat=waypoints[1].get('location')[1])
                                           )
                                      )
    trip.legs[0].start_coord = trip.legs[0].steps[0].start_coord
    trip.legs[0].end_coord = trip.legs[0].steps[-1].end_coord
    trip.legs[0].duration = sum([step.duration for step in trip.legs[0].steps])
    trip.legs[0].distance = sum([step.distance for step in trip.legs[0].steps])
    trip.legs[0].mode = OtpMode.DRT

    trip.distance = trip.legs[0].distance
    trip.duration = trip.legs[0].duration
    trip.main_mode = OtpMode.CAR
    return trip
