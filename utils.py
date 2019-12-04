from sim_utils import Coord, Trip
import json


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
