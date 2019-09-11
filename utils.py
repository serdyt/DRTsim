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

    def __init__(self, type_, coord, start_time=None, end_time=None):
        """docstring"""
        if start_time is None and end_time is None:
            raise Exception("Sanity check: both activity times are None")
        self.type = type_
        self.coord = coord
        self.start_time = start_time
        self.end_time = end_time

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
    """
    TODO:assignment of mode as a string is confusing, remove it, or use constant
    """
    def __init__(self):
        self.mode = None
        self.start_coord = None
        self.end_coord = None
        self.distance = None
        self.duration = None
        self.steps = None
        
    # def set_distance(self, distance):
    #     self.distance = distance
    #
    # def set_duration(self, duration):
    #     self.duration = duration
    #
    # def set_start_coord(self, coord):
    #     self.start_coord = coord
    #
    # def set_end_coord(self, coord):
    #     self.end_coord = coord
    #
    # def set_steps(self, steps):
    #     self.steps = steps


class Step(object):
    """Arguments:|
    coord       <Coord>|
    distance    <int>|
    duration    <int>|
    """
    def __init__(self, coord, distance, duration):
        self.end_coord = coord
        self.distance = distance
        self.duration = duration


class Trip(object):
    """A list of legs and a total trip duration
    """
    legs = None  # type: List[Leg]

    def __init__(self):
        self.legs = []
        self.duration = None
        self.distance = None
        self.main_mode = None

    def get_modes(self):
        """Returns a list of modes from the legs"""
        return [l.mode for l in self.legs]

    def set_duration(self, dur):
        self.duration = dur

    def set_main_mode(self, mode):
        self.main_mode = mode
    
    def set_distance(self, dist):
        self.distance = dist
    
    def append_leg(self, leg):
        self.legs.append(leg)
        
    def __str__(self):
        return 'Trip with {} takes {:.0f} distance {:.0f}'.format(self.get_modes(), self.duration, self.distance)

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


class ActType(object):
    PICK_UP = 0
    DROP_OFF = 1
    DELIVERY = 3
    WAIT = 4
    RETURN = 5

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
                ActType.RETURN: 'return',
                }[act_type]


class JspritAct(ActType):

    def __init__(self, type_=None, person_id=None, end_time=None, arrival_time=None):
        super(JspritAct, self).__init__(type_=type_)
        self.person_id = person_id
        self.end_time = end_time
        self.arrival_time = arrival_time


class DrtAct(ActType):

    def __init__(self, type_=None, person=None, duration=None, coord=None, distance=None, steps=None):
        """

        :type person: Person
        :type steps: List[Step]
        """
        super(DrtAct, self).__init__(type_)
        self.person = person
        self.duration = duration
        self.coord = coord
        self.distance = distance
        self.steps = steps

    def get_position_by_time(self, current_time, time):
        if len(self.steps) == 0:
            return self.coord, current_time + self.duration
        else:
            # steps store starting location and duration of a step,
            # so at time current_time + duration vehicle would be at the next step
            for c_step, n_step in zip(self.steps, self.steps[1:] + [self.steps[-1]]):
                current_time += c_step.duration
                if current_time >= time:
                    return n_step.end_coord, current_time
        # as jsprit may send vehicles long before the request time,
        # vehicle could have rode the route and waiting at pickup point
        raise Exception('There is not enough of steps time to fill the act')


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
        
    def __str__(self):
        return str(self.lat) + ',' + str(self.lon)

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


def get_time_of_act_start(acts, index, time):
    """Finds when the previous act ends"""
    # local_time = time
    # for _, act in zip(range(index), acts):
    #     local_time += act.duration
    return time + sum([a.duration for a in acts[:index]])


def seconds_from_str(string):
    """Converts a string of format '%H:%M:%S' into seconds from the beginning of a day
    """
    if string is None:
        return None
    t = datetime.strptime(string, '%H:%M:%S')
    return td(hours=t.hour, minutes=t.minute, seconds=t.second).total_seconds()
