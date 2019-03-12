#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Constants
@author: ai6644
"""

from enum import Enum

maxLat = 55.84911
maxLon = 14.41956
minLat = 55.36272
minLon = 13.44177


class LegMode(object):
    CAR = 'CAR'
    WALK = 'WALK'
    BUS = 'BUS'
    RAIL = 'RAIL'
    BICYCLE = 'BICYCLE'
    TRAM = 'TRAM'
    SUBWAY = 'SUBWAY'
    CAR_PARK = 'CAR_PARK'
    BICYCLE_PARK = 'BICYCLE_PARK'
    BICYCLE_RENT = 'BICYCLE_RENT'
    DRT = 'DRT'

    _DICT = ['CAR', 'WALK', 'BUS', 'RAIL', 'BICYCLE', 'TRAM', 'SUBWAY',
             'CAR_PARK', 'BICYCLE_PARK', 'BICYCLE_RENT', 'DRT']

    @staticmethod
    def get_all_modes():
        return [LegMode.__dict__.get(item) for item in LegMode._DICT]


class OtpMode(object):
    CAR = 'CAR'
    WALK = 'WALK'
    TRANSIT = 'TRANSIT,WALK'
    BUS = 'BUS,WALK'
    RAIL = 'TRAM,RAIL,SUBWAY,FUNICULAR,GONDOLA,WALK'
    BICYCLE = 'BICYCLE'
    BICYCLE_TRANSIT = 'TRANSIT,BICYCLE'
    PARK_RIDE = 'CAR_PARK,WALK,TRANSIT'
    KISS_RIDE = 'CAR,WALK,TRANSIT'
    BIKE_RIDE = 'BICYCLE_PARK,WALK,TRANSIT'
    RENTED_BICYCLE = 'WALK,BICYCLE_RENT'
    TRANSIT_RENTED_BICYCLE = 'TRANSIT,WALK,BICYCLE_RENT'
    DRT = 'DRT'

    _DICT = ['CAR', 'WALK', 'TRANSIT', 'BUS', 'RAIL', 'BICYCLE', 'BICYCLE_TRANSIT', 'PARK_RIDE', 'KISS_RIDE',
            'BIKE_RIDE', 'RENTED_BICYCLE', 'TRANSIT_RENTED_BICYCLE', 'DRT']

    @staticmethod
    def get_all_modes():
        return [OtpMode.__dict__.get(item) for item in OtpMode._DICT]

    @staticmethod
    def contains(other):
        return other in OtpMode._DICT

    @staticmethod
    def get_mode(string):
        if OtpMode.contains(string):
            return OtpMode
        else:
            raise Exception('unsupported mode {}'.format(string))


class CapacityDimensions(object):
    """jsprit requires capacity dimensions to be integers
    """
    SEATS = 0
    WHEELCHAIRS = 1


class VehicleCost(object):
    DISTANCE = 'distance'
    FIXED = 'fixed'
    TIME = 'time'
    WAIT = 'wait'


class ActivityType(Enum):
    HOME = 'HOME'
    WORK = 'WORK'


class PersAttr(Enum):
    ID = 'ID'
    AGE = 'AGE'


class TripAttr(Enum):
    TIME = 'TIME'
    MODE = 'MODE'
    DIST = 'DIST'