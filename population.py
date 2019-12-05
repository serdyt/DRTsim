#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utils to manage population
"""

import logging
from datetime import timedelta as td
import json
from typing import List, Dict

from desmod.component import Component
import behaviour
import mode_choice

from sim_utils import Activity, Coord, seconds_from_str, Trip, Leg, Step
from const import ActivityType as actType
from const import maxLat, minLat, maxLon, minLon
from const import CapacityDimensions as CD
from const import OtpMode

log = logging.getLogger(__name__)


class Population(Component):
    """Population stores all the persons
    """
    
    base_name = 'population'
    
    def __init__(self, *args, **kwargs):
        super(Population, self).__init__(*args, **kwargs)
        self.person_list = []
        self._init_persons()
        
    def _init_persons(self):
        self.read_json()
        log.info('{}: Population of {} persons created.'.format(self.env.now, len(self.person_list)))

    def read_json(self):
        """Reads json input file and generates persons to simulate"""
        with open(self.env.config.get('population.input_file'), 'r') as input_file:
            raw_json = json.load(input_file)
            persons = raw_json.get('persons')
            pers_id = 0
            for json_pers in persons:
                pers_id += 1
                # if self.env.rand.choices([False, True],
                #                          [self.env.config.get('population.input_percentage'),
                #                          1 - self.env.config.get('population.input_percentage')])[0]:
                #     continue

                attributes = {'age': 22, 'id': pers_id, 'otp_parameters': {'arriveBy': True}}

                # TODO: sequence of activities has the same end and start times
                # time window is applied on the planning stage in the behaviour and service

                activities = []
                json_activities = json_pers.get('activities')
                if len(json_activities) == 0:
                    raise Exception('No activities provided for a person.')
                for json_activity in json_activities:
                    type_str = json_activity.get('type')
                    type_ = actType.get_activity(type_str)

                    end_time = seconds_from_str(json_activity.get('end_time'))
                    start_time = seconds_from_str(json_activity.get('start_time'))

                    coord_json = json_activity.get('coord')
                    coord = Coord(lat=float(coord_json.get('lat')), lon=float(coord_json.get('lon')))

                    zone = int(json_activity.get('zone'))

                    activities.append(
                        Activity(type_=type_,
                                 start_time=start_time,
                                 end_time=end_time,
                                 coord=coord,
                                 zone=zone
                                 )
                    )
                if activities[0].zone in self.env.config.get('drt.zones') \
                        or activities[1].zone in self.env.config.get('drt.zones'):

                    if self.env.rand.choices([False, True],
                                             [self.env.config.get('population.input_percentage'),
                                              1 - self.env.config.get('population.input_percentage')])[0]:
                        continue

                    self.person_list.append(Person(self, attributes, activities))

    def _random_persons(self):
        """Not used. Generates persons at random geographical points with default parameters"""
        for i in range(50):
            attributes = {'id': i, 'age': 54, 'walking_speed': 5, 'driving_licence': bool(self.env.rand.getrandbits(1)),
                          'dimensions': {CD.SEATS: 1, CD.WHEELCHAIRS: int(self.env.rand.getrandbits(1))}
                          }
            activities = [
                Activity(type_=actType.HOME,
                         coord=Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon)),
                         end_time=td(hours=self.env.rand.uniform(0, 10), minutes=self.env.rand.uniform(0, 59)).total_seconds()
                         ),
                Activity(type_=actType.WORK,
                         coord=Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon)),
                         start_time=td(hours=self.env.rand.uniform(11, 23), minutes=self.env.rand.uniform(0, 59)).total_seconds()
                         )
            ]
            self.person_list.append(Person(parent=self, attributes=attributes, activities=activities))
        
        log.info("{}: Population size {0}".format(self.env.now, len(self.person_list)))

    def get_person(self, id):
        ids = [p.id for p in self.person_list]
        return self.person_list[ids.index(id)]

    def get_result(self, result):
        super(Population, self).get_result(result)
        result['total_persons'] = len(self.person_list)


class Person(Component):

    serviceProvider = ...  # type: ServiceProvider
    alternatives = ...  # type: List[Trip]
    planned_trip = ...  # type: Trip
    actual_trip = ...  # type: Trip
    curr_activity = ...  # type: Activity
    next_activity = ...  # type: Activity
    base_name = 'person'

    def __init__(self, parent, attributes, activities: List, trip: Trip = None):
        """Person that requests for trips

        Parameters:

        Parent: parent component to get environment
        attributes: dictionary of person's attributes. Must include id.
        activities: list of Activity
        trip: pre-computed trip to execute (Not tested).
        """
        Component.__init__(self, parent=parent, index=attributes.get('id'))
        self.serviceProvider = None
        self.add_connections('serviceProvider')

        self.dimensions = self.env.config.get('person.default_attr.dimensions')
        self.id = None
        self.driving_license = self.env.config.get('person.default_attr.driving_license')
        self.walking_speed = self.env.config.get('person.default_attr.walking_speed')
        self.age = self.env.config.get('person.default_attr.age')
        self.boarding_time = self.env.config.get('person.default_attr.boarding_time')
        self.leaving_time = self.env.config.get('person.default_attr.leaving_time')

        self.otp_parameters = {}
        self.attributes = {}
        self._set_attributes(attributes)

        if len(activities) < 2:
            raise Exception('Person received less than two activities')
        self.activities = activities
        self.curr_activity = self.activities.pop(0)
        self.next_activity = self.activities.pop(0)
        self.planned_trip = trip
        self.direct_trip = None
        # self.time_window = 0
        self.alternatives = []
        self.behaviour = getattr(behaviour, self.env.config.get('person.behaviour'))(self)
        self.mode_choice = getattr(mode_choice, self.env.config.get('person.mode_choice'))(self)

        self.actual_trip = None
        self.executed_trips = []
        self.direct_trips = []
        self.planned_trips = []
        self.drt_status = []

        # we need to store that so that drt rerouting would know drt leg coordinates.
        # TODO: move this to a container in ServiceProvider
        self.drt_leg = None

        self.drt_tw_left = None
        self.drt_tw_right = None

        self.delivered = self.env.event()
        self.drt_executed = self.env.event()
        self.add_process(self.behaviour.activate)

    def _set_attributes(self, attributes):
        for attr in attributes.items():
            setattr(self, attr[0], attr[1])

    def get_arrive_by(self):
        if self.next_activity.type == actType.WORK:
            return 'True'
        else:
            return 'False'

    def update_otp_params(self):
        """Sets new otp params for a new trip. Params are deducted from activity"""
        self.otp_parameters.update({'arriveBy': self.get_arrive_by()})

    def get_result(self, result):
        """Save trip results to the result dictionary"""
        super(Person, self).get_result(result)
        if 'Persons' not in result.keys():
            result['Persons'] = []

        result['Persons'].append(self)

    def init_actual_trip(self):
        """Initiates an empty actual_trip to append executed legs and acts to it"""
        self.actual_trip = Trip()
        self.actual_trip.main_mode = self.planned_trip.main_mode
        self.actual_trip.legs = []

    def init_drt_leg(self):
        self.actual_trip.legs.append(
            Leg(steps=[], duration=0, distance=0, mode=OtpMode.DRT)
        )

    def get_planning_time(self, trip):
        """Calculates a time to wait until the moment a person starts planning a trip
        returns: int in seconds when planning should happen
        """
        timeout = int((self.next_activity.start_time - trip.duration
                       - self.env.config.get('drt.planning_in_advance') - self.env.now))

        # request time relative to direct time
        # timeout = self.direct_trip.legs[0].start_time - self.env.config.get('trip.planning_in_advance_constant') \
        #     - self.direct_trip.duration * self.env.config.get('trip.planning_in_advance_direct_time_coefficient')
        #     - self.env.now

        if timeout < 0:
            log.debug('{}: {} cannot plan {} seconds in advance due to the beginning of the day'
                      .format(self.env.now, self, self.env.config.get('drt.planning_in_advance')))
            timeout = 0
        return timeout

    def update_actual_trip(self, steps: List[Step], end_coord):
        """When a vehicle completes an act or is being rerouted, save executed part to actual trip"""
        self.actual_trip.legs[-1].steps += steps
        self.actual_trip.legs[-1].duration += sum([s.duration for s in steps])
        self.actual_trip.legs[-1].distance += sum([s.distance for s in steps])
        self.actual_trip.legs[-1].end_coord = end_coord

        self.actual_trip.duration = sum([leg.duration for leg in self.actual_trip.legs])
        self.actual_trip.distance = sum([leg.distance for leg in self.actual_trip.legs])

    def set_actual_trip(self, trip):
        self.actual_trip = trip

    def append_pt_legs_to_actual_trip(self, legs):
        for leg in legs:
            self.actual_trip.legs.append(leg)
        # No matter when DRT trip has finished, PT leg would start and end at the same time as planned
        self.actual_trip.duration = sum([leg.duration for leg in self.actual_trip.legs])
        self.actual_trip.distance = sum([leg.distance for leg in self.actual_trip.legs])

    def finish_actual_drt_trip(self, end_time):
        self.actual_trip.legs[-1].end_time = end_time

    def start_actual_drt_trip(self, start_time, start_coord):
        self.actual_trip.legs[-1].start_time = start_time
        self.actual_trip.legs[-1].start_coord = start_coord

    def reset_delivery(self):
        """Create ne delivery events"""
        self.delivered = self.env.event()
        self.drt_executed = self.env.event()

    def __str__(self):
        return 'Person {} going from {} zone {}, to {} zone {}'\
            .format(self.id,
                    self.curr_activity.coord, self.curr_activity.zone,
                    self.next_activity.coord, self.next_activity.zone)

    def log_executed_trip(self):
        """After a trip has been executed, save it and related direct trip"""

        self.planned_trips.append(self.planned_trip)
        self.executed_trips.append(self.actual_trip)
        self.direct_trips.append(self.direct_trip)

    def set_direct_trip(self, trip):
        # modes = [a.main_mode for a in alternatives]
        # if OtpMode.CAR in modes:
        #     self.direct_trip = alternatives[modes.index(OtpMode.CAR)]
        # else:
        #     log.warning('{}: Person {} does not have a car alternative. Taking the fastest one'
        #                 .format(self.env.now, self.id))
        #     times = [a.duration for a in alternatives]
        #     self.direct_trip = alternatives[times.index(max(times))]
        self.direct_trip = trip

    def update_planned_drt_trip(self, drt_route):
        """Jsprit solution does not provide distances. # TODO: check if it is possible to include this in jsprit
        After service provider reconstructs DRT route with OTP, it calls for this to recalculate actual planned route,
        that will be compared with actual and direct trips.
        """
        drt_acts = [act for act in drt_route if act.person == self]
        start_act_idx = drt_route.index(drt_acts[0])
        end_act_idx = drt_route.index(drt_acts[-1])
        persons_route = drt_route[start_act_idx+1:end_act_idx+1]

        # jsprit has no distance and steps
        drt_leg = self.planned_trip.legs[self.planned_trip.get_leg_modes().index(OtpMode.DRT)]
        drt_leg.duration = sum([act.duration for act in persons_route])

        self.planned_trip.set_duration(sum([leg.duration for leg in self.planned_trip.legs]))
        # self.planned_trip.legs[0].duration = self.planned_trip.duration
        # self.planned_trip.legs[0].distance = self.planned_trip.distance

    def change_activity(self):
        """Updates current and next activities from a list of planned activities.
        Returns -1 in case of error
        """

        if len(self.activities) > 0:
            self.curr_activity = self.next_activity
            self.next_activity = self.activities.pop(0)

            self.alternatives = []
            self.planned_trip = None
            self.direct_trip = None

            return 0
        else:
            return -1

    def get_routing_parameters(self):
        return self.otp_parameters

    def set_tw(self, direct_time, single_leg=False, first_leg=False, last_leg=False, drt_leg=None):
        tw = direct_time * self.env.config.get('drt.time_window_multiplier')\
             + self.env.config.get('drt.time_window_constant')
        if single_leg:
            self.drt_tw_left = self.curr_activity.end_time - tw * self.env.config.get('drt.time_window_shift_left')
            self.drt_tw_right = self.next_activity.start_time\
                + tw * (1 - self.env.config.get('drt.time_window_shift_left'))
        elif first_leg:
            self.drt_tw_left = drt_leg.end_time - tw
            self.drt_tw_right = drt_leg.end_time
        elif last_leg:
            self.drt_tw_left = drt_leg.start_time
            self.drt_tw_right = drt_leg.start_time + tw
        else:
            raise Exception('Incorrect input for time window calculation for Person {}.\n{} {} {}'
                            .format(self.id, direct_time, single_leg, first_leg, last_leg, drt_leg))

        if self.drt_tw_left < self.env.now:
            self.drt_tw_left = self.env.now
        if self.drt_tw_right > self.env.config.get('sim.duration_sec'):
            self.drt_tw_right = self.env.config.get('sim.duration_sec')

    def get_tw_left(self):
        """Returns: time in seconds when the left time window border starts
        """
        return self.drt_tw_left

    def get_tw_right(self):

        return self.drt_tw_right
