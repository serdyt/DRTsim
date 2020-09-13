#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 19 14:58:25 2018

@author: ai6644
"""

from typing import List
from datetime import timedelta as td
from datetime import datetime
import logging
import copy
import json

from const import OtpMode, LegMode

log = logging.getLogger(__name__)


class Plan(object):
    def __init__(self):
        raise NotImplementedError


class Activity(object):
    """Activity that is performed by a person.
    Person moves to a next activity after end_time is reached.

    Parameters
    ----------
    type_ : <ActivityType>
    coord : <Coord>
    start_time : <int> seconds from 00:00
    end_time : <int> seconds from 00:00
    """

    def __init__(self, type_, coord, start_time=None, end_time=None, zone=None):
        """docstring"""
        if start_time is None and end_time is None:
            raise Exception("Sanity check: both activity times are None")
        self.type = type_
        self.coord = coord
        self.start_time = start_time
        self.end_time = end_time
        self.zone = zone

    def __str__(self):
        return 'An ' + str(self.type) + ' at ' + str(self.coord)


class Leg(object):
    """Leg of a trip. For example, "walk - bus - walk" trip has three legs.
    Used to store trip legs from OTP.

    Parameters
    ----------
    mode : <str> mode of transport
    start_coord : <coord> coordinate of an origin
    end_coord : <coord> coordinate of a destination
    distance : <int> meters
    duration : <int> seconds
    steps : <list> of utils.Step
    """

    # TODO:assignment of mode as a string is confusing, remove it, or use constant
    def __init__(self, mode=None, start_coord=None, from_stop=None, end_coord=None, to_stop=None,
                 start_time=None, end_time=None,
                 distance=None, duration=None, steps=None):
        self.mode = mode
        self.start_coord = start_coord
        self.end_coord = end_coord
        self.distance = distance
        self.duration = duration
        self.steps = steps
        # The two below only used for PT legs
        self.from_stop = from_stop
        self.to_stop = to_stop

        self.start_time = start_time
        self.end_time = end_time

    def deepcopy(self):
        if self.steps is None:
            steps = []
        else:
            steps = [step.deepcopy() for step in self.steps if step is not None]
        return Leg(mode=copy.copy(self.mode),
                   start_coord=copy.copy(self.start_coord),
                   from_stop=copy.copy(self.from_stop),
                   end_coord=copy.copy(self.end_coord),
                   to_stop=copy.copy(self.to_stop),
                   start_time=copy.copy(self.start_time),
                   end_time=copy.copy(self.end_time),
                   distance=copy.copy(self.distance),
                   duration=copy.copy(self.duration),
                   steps=steps)


class Step(object):
    """Arguments:|
    start_coord       <Coord>|
    distance    <int>|
    duration    <int>|
    """
    def __init__(self, start_coord, end_coord, distance, duration):
        self.start_coord = start_coord
        self.end_coord = end_coord
        self.distance = distance
        self.duration = duration

    @staticmethod
    def get_empty_step(coord):
        return Step(start_coord=coord, end_coord=coord, distance=0, duration=0)

    def deepcopy(self):
        return Step(start_coord=copy.copy(self.start_coord),
                    end_coord=copy.copy(self.end_coord),
                    distance=copy.copy(self.distance),
                    duration=copy.copy(self.duration),
                    )

    def dumps(self):
        return self.__dict__

    def __str__(self):
        return 'Step distance {:.1f}, duration {:.1f}'.format(self.distance, self.duration)

    def __repr__(self):
        return self.__str__()


class Trip(object):
    """A list of legs and a total trip duration
    """
    legs = ...  # type: List[Leg]

    def __init__(self):
        self.legs = []
        self.duration = None
        self.distance = None
        self.main_mode = None

    def set_empty_trip(self, mode, coord_start, coord_end):
        """Sets a dummy trip between two coordinates with zero distance, duration and one empty leg"""
        self.set_duration(0)
        self.set_distance(0)
        self.main_mode = mode
        self.legs = [Leg(mode=mode, start_coord=coord_start, end_coord=coord_end, distance=0, duration=0,
                         steps=[Step(coord_start, coord_end, 0, 0)])]

    def dumps(self):
        return self.__dict__

    def get_leg_modes(self):
        """Returns a list of modes from the legs"""
        return [l.mode for l in self.legs]

    def deepcopy(self):
        nt = Trip()
        nt.duration = copy.copy(self.duration)
        nt.distance = copy.copy(self.distance)
        nt.main_mode = copy.copy(self.main_mode)
        nt.legs = [leg.deepcopy() for leg in self.legs]
        return nt

    def main_mode_from_legs(self):
        leg_modes = self.get_leg_modes()

        if LegMode.CAR in leg_modes:
            return OtpMode.CAR
        elif LegMode.BUS in leg_modes or LegMode.SUBWAY in leg_modes or \
                LegMode.TRAM in leg_modes or LegMode.RAIL in leg_modes:
            return OtpMode.TRANSIT
        elif LegMode.BICYCLE in leg_modes:
            return OtpMode.BICYCLE
        elif LegMode.WALK in leg_modes:
            return OtpMode.BICYCLE
        else:
            log.error('Main mode unrecognized. Returning None. Kick the developer to make a proper function.')
            return None

    def set_duration(self, dur):
        self.duration = dur

    def set_main_mode(self, mode):
        self.main_mode = mode
    
    def set_distance(self, dist):
        self.distance = dist
    
    def append_leg(self, leg):
        self.legs.append(leg)
        
    def __str__(self):
        return '{} trip, takes {} distance {}'\
            .format(self.main_mode, self.duration, self.distance)

    def __repr__(self):
        return str(self)

    # def find_main_mode(self):
    #     modes = [leg.mode for leg in self.legs]
        # if Mode.CAR in modes:
        #     self.main_mode = Mode.CAR
        # elif Mode.TRANSIT in modes:
        #     self.main_mode = Mode.TRANSIT
        # elif Mode.BUS in modes:
        #     self.main_mode = Mode.BUS
        # elif Mode.TRAIN in modes:
        #     self.main_mode = Mode.TRAIN
        # elif Mode.BICYCLE in modes:
        #     self.main_mode = Mode.BICYCLE


class UnassignedTrip(object):
    def __init__(self, person):
        self.person = person
        self.start_activity = person.curr_activity
        self.end_activity = person.next_activity
        self.tw_left = person.get_tw_left()
        self.tw_right = person.get_tw_right()

    def __str__(self):
        return 'Person {} tried to go from {} to {} in interval [{} - {}]'\
            .format(self.person.id, self.start_activity, self.end_activity,
                    get_sec(self.tw_left), get_sec(self.tw_right))


class ActType(object):
    PICK_UP = 0
    DROP_OFF = 1
    DELIVERY = 2
    DRIVE = 3
    WAIT = 4
    RETURN = 5
    IDLE = 6

    def __init__(self, type_=None):
        self.type = type_

    @staticmethod
    def get_type_from_string(act_string):
        return {'pickupShipment': ActType.PICK_UP,
                'deliverShipment': ActType.DROP_OFF,
                'delivery': ActType.DELIVERY
                }[act_string]

    @staticmethod
    def get_string_from_type(act_type):
        return {ActType.PICK_UP: 'pickupShipment',
                ActType.DROP_OFF: 'deliverShipment',
                ActType.DELIVERY: 'delivery',
                ActType.RETURN: 'drive',
                ActType.WAIT: 'wait',
                ActType.DRIVE: 'return',
                ActType.IDLE: 'idle',
                }[act_type]

    def __str__(self):
        return self.get_string_from_type(self.type)

    def __repr__(self):
        return self.__str__()


class JspritAct(ActType):

    def __init__(self, type_=None, person_id=None, end_time=None, arrival_time=None):
        super(JspritAct, self).__init__(type_=type_)
        self.person_id = person_id
        self.end_time = end_time
        self.arrival_time = arrival_time

    def get_duration(self):
        return self.end_time - self.arrival_time

    def __str__(self):
        return 'Person{}, end_time {}, arrival_time {}' \
            .format(self.person_id, self.end_time, self.arrival_time)

    def __repr__(self):
        return self.__str__()


class DrtAct(ActType):

    def __init__(self, start_coord=None, type_=None, person=None, duration=None, end_coord=None, distance=None,
                 start_time=None, end_time=None, steps=None):
        """

        :type person: Person
        :type steps: List[Step]
        """
        super(DrtAct, self).__init__(type_)
        self.person = person
        self.duration = duration
        self.end_coord = end_coord
        self.distance = distance
        self.start_time = start_time
        self.start_coord = start_coord
        self.end_time = end_time
        self.steps = steps

    def __str__(self):
        return '{}, type {}, duration {}, distance {}, start_time {}, end_time {}'\
            .format(self.person, self.type, self.duration, self.distance, self.start_time, self.end_time)

    def __repr__(self):
        return self.__str__()

    def flush(self):
        return '{}\n{}'.format(self.__str__(), [s.__str__() for s in self.steps])

    def get_deep_copy(self):
        return DrtAct(type_=copy.deepcopy(self.type),
                      person=self.person,
                      duration=copy.deepcopy(self.duration),
                      end_coord=copy.deepcopy(self.end_coord),
                      distance=copy.deepcopy(self.distance),
                      start_time=copy.deepcopy(self.start_time),
                      start_coord=copy.deepcopy(self.start_coord),
                      end_time=copy.deepcopy(self.end_time),
                      steps=copy.deepcopy(self.steps)
                      )

    def remove_disembark_step(self):
        """Removes boarding or getting of step from an act
        If the last step of an act has zero distance, it is boarding or getting off a vehicle.
        Opposite to also add_embark_step
        """
        if self.steps[-1].distance == 0 and self.steps[-1].duration != 0:
            self.duration -= self.steps[-1].duration
            self.steps.pop(-1)

    def remove_embark_step(self):
        """Removes boarding or getting of step from an act
        If the last step of an act has zero distance, it is boarding or getting off a vehicle.
        Opposite to also add_embark_step
        """
        if self.steps[0].distance == 0 and self.steps[0].duration != 0:
            self.duration -= self.steps[0].duration
            self.steps.pop(0)

    def add_disembark_step(self, embark_time):
        """Adds a step for boarding or getting off a vehicle. Step has zero distance.
         Opposite to remove_embark_step
        """
        self.duration += embark_time
        self.steps.append(Step(self.steps[-1].start_coord, self.steps[-1].end_coord, 0, embark_time))

    def add_embark_step(self, embark_time, embark_coord):
        """Adds a step for boarding or getting off a vehicle. Step has zero distance.
         Opposite to remove_embark_step
        """
        self.duration += embark_time
        self.steps = [Step(embark_coord, embark_coord, 0, embark_time)] + self.steps

    def add_wait_step(self, duration):
        self.steps.append(Step(self.steps[-1].start_coord, self.steps[-1].start_coord, 0, duration))


class JspritRoute(object):
    acts = None  # type: List[JspritAct]

    def __init__(self, vehicle_id=None, start_time=None, end_time=None, acts=None):
        self.vehicle_id = vehicle_id
        self.start_time = start_time
        self.end_time = end_time
        self.acts = acts


class Coord(object):
    """Coordinate.

    Parameters
    ----------
    lat : <float> latitude
    lon : <float> longitude
    latlon : <list> list with both lat and long. Latitude first!
    """
    def __init__(self, lat=None, lon=None, latlon=None):
        if latlon is not None:
            if len(latlon) != 2:
                raise Exception("Wrong coordinate latlon format. Should be a list of two floats.")
            self.lat = latlon[0]
            self.lon = latlon[1]
        elif lat is None or lon is None:
            raise Exception("Coordinates not provided")
        else:
            self.lat = lat
            self.lon = lon

    def to_json(self):
        return json.dumps(self, default=lambda o: self._try(o), sort_keys=True, indent=4, separators=(',', ':'))

    @staticmethod
    def _try(o):
        try:
            if o.__class__ == Coord:
                raise Exception()
            return o.__dict__
        except:
            return str(o)
        
    def __str__(self):
        return str(self.lat) + ',' + str(self.lon)

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        return self.lat == other.lat and self.lon == other.lon

    def __hash__(self):
        return hash((self.lat, self.lon))


class JspritSolution(object):
    def __init__(self, cost, routes=None, unassigned=None):
        self.cost = cost
        self.routes = routes
        self.unassigned = unassigned
        self.modified_route = None


def trunc_microseconds(time_str):
    if '.' in time_str:
        time, _ = time_str.split('.')
        return time
    else:
        return time_str


def get_sec(time_str):
    print(time_str)
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def otp_time_to_sec(otp_time):
    return seconds_from_str(datetime.fromtimestamp(otp_time/1000).strftime('%H:%M:%S'))


def seconds_from_str(string):
    """Converts a string of format '%H:%M:%S' into seconds from the beginning of a day
    """
    if string is None:
        return None
    t = datetime.strptime(string, '%H:%M:%S')
    return int(td(hours=t.hour, minutes=t.minute, seconds=t.second).total_seconds())
