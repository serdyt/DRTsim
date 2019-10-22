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

from utils import Activity, Coord, seconds_from_str, Trip, Leg, Step
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
        log.info('Population of {} persons created.'.format(len(self.person_list)))

    def read_json(self):
        """Reads json input file and generates persons to simulate"""
        with open(self.env.config.get('population.input_file'), 'r') as file:
            local_person_list = []
            raw_json = json.load(file)
            persons = raw_json.get('persons')
            pers_id = 0
            # i = 0
            for json_pers in persons:
                # if i > 100:
                #     break
                attributes = {'age': 22, 'id': pers_id, 'otp_parameters': {'arriveBy': True}}
                pers_id = pers_id + 1

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

                # take only trips within target zones
                # if activities[0].zone not in self.env.config.get('drt.zones') or \
                #    activities[1].zone not in self.env.config.get('drt.zones'):
                #     continue

                # local_person_list.append(Person(self, attributes, activities))
                # take 1% of the tours
                if self.env.rand.randint(0, 1000) < 10:
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
        
        log.info("Population size {0}".format(len(self.person_list)))

    def get_person(self, id):
        ids = [p.id for p in self.person_list]
        return self.person_list[ids.index(id)]


class Person(Component):

    serviceProvider = ...  # type: ServiceProvider
    alternatives = ...  # type: List[Trip]
    planned_trip = ...  # type: Trip
    actual_trip = ...  # type: Trip
    curr_activity = ...  # type: Activity
    next_activity = ...  # type: Activity
    base_name = 'person'

    def __init__(self, parent, attributes, activities: Dict, trip: Trip = None):
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
        self.time_window = 0
        self.alternatives = []
        self.behaviour = getattr(behaviour, self.env.config.get('person.behaviour'))(self)
        self.mode_choice = getattr(mode_choice, self.env.config.get('person.mode_choice'))(self)

        self.actual_trip = None
        self.executed_trips = []
        self.direct_trips = []
        self.planned_trips = []

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

    def get_result(self, result):
        """Save trip results to the result dictionary"""
        super(Person, self).get_result(result)
        if 'executed_trips' not in result.keys():
            result['executed_trips'] = []
        if 'direct_trips' not in result.keys():
            result['direct_trips'] = []
        if 'planned_trips' not in result.keys():
            result['planned_trips'] = []

        result['executed_trips'] = result.get('executed_trips') + self.executed_trips
        result['planned_trips'] = result.get('planned_trips') + self.planned_trips
        result['direct_trips'] = result.get('direct_trips') + self.direct_trips

    def init_actual_trip(self):
        """Inits an empty actual_trip to append executed acts to it"""
        self.actual_trip = Trip()
        self.actual_trip.main_mode = self.planned_trip.main_mode
        self.actual_trip.legs = []
        # TODO: should create trip legs during the trip also
        for planned_leg in self.planned_trip.legs:
            leg = Leg(steps=[], duration=0, distance=0, start_coord=planned_leg.start_coord, mode=planned_leg.mode)
            self.actual_trip.legs.append(leg)

    def get_planning_time(self):
        """Calculates a time to wait until the moment a person starts planning a trip
        returns: int in seconds when planning should happen
        """
        timeout = int((self.curr_activity.end_time - self.env.now -
                       self.env.config.get('drt.planning_in_advance')))
        if timeout < 0:
            log.debug('{} cannot plan {} seconds in advance due to the beginning of the day'
                      .format(self, self.env.config.get('drt.planning_in_advance')))
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
            # if leg.mode == OtpMode.DRT:
            #     break
            # else:
            self.actual_trip.legs.append(leg)
        self.actual_trip.duration = sum([leg.duration for leg in self.actual_trip.legs])
        self.actual_trip.distance = sum([leg.distance for leg in self.actual_trip.legs])

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

    def set_direct_trip(self, alternatives):
        modes = [a.main_mode for a in alternatives]
        if OtpMode.CAR in modes:
            self.direct_trip = alternatives[modes.index(OtpMode.CAR)]
        else:
            log.warning('Person {} does not have a car alternative. Taking the fastest one'.format(self.id))
            times = [a.duration for a in alternatives]
            self.direct_trip = alternatives[times.index(max(times))]

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
        """
        # TODO: apply time-windows based on direct distance
        Returns: time in seconds when the left time window border starts
        """

        return self.drt_tw_left

        # calc_tw = self.curr_activity.end_time - self.time_window * self.env.config.get('drt.time_window_shift_left')
        # if calc_tw < self.env.now:
        #     return self.env.now
        # else:
        #     return calc_tw

    def get_tw_right(self):
        # TODO: time window should be bound to something else rather than next activity

        return self.drt_tw_right

        # calc_tw = self.next_activity.start_time + \
        #           self.time_window * (1 - self.env.config.get('drt.time_window_shift_left'))
        # if calc_tw > self.env.config.get('sim.duration_sec'):
        #     return self.env.config.get('sim.duration_sec')
        # else:
        #     return calc_tw
