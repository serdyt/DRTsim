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

    _MAIN_MODES = ['CAR', 'BICYCLE', 'BUS', 'RAIL', 'WALK']

    _PT_MODES = ['BUS', 'RAIL', 'TRAM', 'SUBWAY']

    @staticmethod
    def get_all_modes():
        return [LegMode.__dict__.get(item) for item in LegMode._DICT]

    @staticmethod
    def get_main_modes():
        return [LegMode.__dict__.get(item) for item in LegMode._MAIN_MODES]

    @staticmethod
    def get_pt_modes():
        return [LegMode.__dict__.get(item) for item in LegMode._PT_MODES]

    @staticmethod
    def contains(other):
        return other in LegMode._DICT

    @staticmethod
    def get_mode(string):
        if LegMode.contains(string):
            return LegMode
        else:
            raise Exception('unsupported mode {}'.format(string))


class OtpMode(object):
    CAR = 'CAR'
    WALK = 'WALK'
    TRANSIT = 'TRANSIT,WALK'
    BUS = 'BUS,WALK'
    RAIL = 'TRAM,RAIL,SUBWAY,FUNICULAR,GONDOLA,WALK'
    BICYCLE = 'BICYCLE'
    BICYCLE_TRANSIT = 'TRANSIT,BICYCLE'
    PARK_RIDE = 'CAR_PARK,WALK,TRANSIT'
    KISS_RIDE = 'CAR_DROPOFF,WALK,TRANSIT'
    RIDE_KISS = 'TRANSIT,WALK,CAR_PICKUP'
    BIKE_RIDE = 'BICYCLE_PARK,WALK,TRANSIT'
    RENTED_BICYCLE = 'WALK,BICYCLE_RENT'
    TRANSIT_RENTED_BICYCLE = 'TRANSIT,WALK,BICYCLE_RENT'
    DRT = 'DRT'
    DRT_TRANSIT = 'DRT_TRANSIT'

    _DICT = ['CAR', 'WALK', 'TRANSIT', 'BUS', 'RAIL', 'BICYCLE', 'BICYCLE_TRANSIT', 'PARK_RIDE', 'KISS_RIDE',
             'RIDE_KISS', 'BIKE_RIDE', 'RENTED_BICYCLE', 'TRANSIT_RENTED_BICYCLE', 'DRT', 'DRT_TRANSIT']

    _MAIN_MODES = ['CAR', 'TRANSIT', 'WALK']

    _DRT_MODES = ['DRT', 'DRT_TRANSIT']

    _PT_MODES = ['TRANSIT', 'BUS', 'RAIL']

    @staticmethod
    def get_all_modes():
        return [OtpMode.__dict__.get(item) for item in OtpMode._DICT]

    @staticmethod
    def get_main_modes():
        return [OtpMode.__dict__.get(item) for item in OtpMode._MAIN_MODES]

    @staticmethod
    def contains(other):
        return other in OtpMode._DICT

    @staticmethod
    def get_pt_modes():
        return OtpMode._PT_MODES

    @staticmethod
    def get_drt_modes():
        return OtpMode._DRT_MODES

    @staticmethod
    def get_mode(string):
        if OtpMode.contains(string):
            return OtpMode.__getattribute__(OtpMode(), string)
        else:
            raise Exception('unsupported mode {}'.format(string))


class TravelType(Enum):
    WITHIN = 'within'
    IN = 'in'
    OUT = 'out'


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

    def __str__(self):
        return self.name

    @staticmethod
    def contains(other):
        return other in ActivityType.__dict__

    @staticmethod
    def get_activity(string):
        if ActivityType.contains(string):
            return ActivityType.__getitem__(string)
        else:
            raise Exception('unsupported mode {}'.format(string))


class PersAttr(Enum):
    ID = 'ID'
    AGE = 'AGE'


class TripAttr(Enum):
    TIME = 'TIME'
    MODE = 'MODE'
    DIST = 'DIST'


# TODO: The whole idea need to be reworked or removed
# we have multiple cycles of finding DRT trip, they all have their own statuses
# it is meaningless to save them all
class DrtStatus(Enum):
    routed = 'routed'  # normal DRT operation, currently all routed trips are executed
    undeliverable = 'undeliverable'  # request cannot be delivered due to OTP errors (if no path found)
    unassigned = 'unassigned'  # request went to jsprit, but it was unable to route it
    overnight_trip = 'overnight_trip'
    no_stop = 'no_stop'  # no stop for extra-zonal DRT trip found (either too close, or outside of DRT boundaries)
    one_leg = 'one_leg'  # only one leg returned by DRT, most likely OD coordinates are close to PT stops
    too_short_drt_leg = 'too_short_local'
    too_late_request = 'too_late_request'
    too_long_pt_trip = 'too_long_pt_trip'  # when the whole DRT_TRANSIT trip is more than max time window (direct*1.5)
