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
from const import OtpMode, TravelType
from log_utils import TravellerEventType

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
        # self.read_json()
        self.read_split_json()
        log.info('{}: Population of {} persons created.'.format(self.env.now, len(self.person_list)))

    def read_split_json(self):
        """Reads the population file of format

         population = {   'population_within_pt': [],
                          'population_within_other': [],

                          'population_in_pt': [],
                          'population_out_pt': [],

                          'population_in_drtable': [],
                          'population_out_drtable': [],

                          'population_in_other': [],
                          'population_out_other': []
             }
        """
        with open(self.env.config.get('population.input_file'), 'r') as input_file:
            raw_json = json.load(input_file)
            pers_id = 0

            # ['all_within', 'pt_only', 'drtable_all', 'drtable_outside']

            if self.env.config.get('population.scenario') == 'all_within':
                persons = raw_json.get('population_within_pt') + \
                          raw_json.get('population_within_other')
            elif self.env.config.get('population.scenario') == 'pt_only':
                persons = raw_json.get('population_within_pt') + \
                          raw_json.get('population_in_pt') + \
                          raw_json.get('population_out_pt')
            elif self.env.config.get('population.scenario') == 'drtable_all':
                persons = raw_json.get('population_within_pt') + \
                          raw_json.get('population_within_other') + \
                          raw_json.get('population_in_pt') + \
                          raw_json.get('population_out_pt') + \
                          raw_json.get('population_in_drtable') + \
                          raw_json.get('population_out_drtable')
            elif self.env.config.get('population.scenario') == 'drtable_outside':
                persons = raw_json.get('population_in_pt') + \
                          raw_json.get('population_out_pt') + \
                          raw_json.get('population_in_drtable') + \
                          raw_json.get('population_out_drtable')
            elif self.env.config.get('population.scenario') == 'all':
                log.warning("Careful, importing the whole population file, it make take a lot of time!")
                persons = raw_json.get('population_within_pt') + \
                          raw_json.get('population_within_other') + \
                          raw_json.get('population_in_pt') + \
                          raw_json.get('population_out_pt') + \
                          raw_json.get('population_in_drtable') + \
                          raw_json.get('population_out_drtable') + \
                          raw_json.get('population_in_other') + \
                          raw_json.get('population_out_other')
            else:
                log.critical("Input population is configured wrong!."
                             "Use population.scenario "
                             "['all_within', 'pt_only', 'drtable_all', 'drtable_outside', 'all']")
                raise Exception()

            for json_pers in persons:
                if self.env.rand.choices([False, True],
                                         [self.env.config.get('population.input_percentage'),
                                          1 - self.env.config.get('population.input_percentage')])[0]:
                    continue
                else:
                    self.person_list.append(self._person_from_json(json_pers, pers_id))
                pers_id += 1

    def read_json(self):
        """Reads json input file and generates persons to simulate"""
        with open(self.env.config.get('population.input_file'), 'r') as input_file:
            raw_json = json.load(input_file)
            persons = raw_json.get('persons')
            pers_id = 0
            for json_pers in persons:
                pers_id += 1

                pers = self._person_from_json(json_pers, pers_id)

                if pers.activities[0].zone in self.env.config.get('drt.zones') \
                        or pers.activities[1].zone in self.env.config.get('drt.zones'):

                    if self.env.rand.choices([False, True],
                                             [self.env.config.get('population.input_percentage'),
                                              1 - self.env.config.get('population.input_percentage')])[0]:
                        continue

                    self.person_list.append(pers)

    def _person_from_json(self, json_pers, pers_id):
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
        return Person(self, attributes, activities)

    def _random_persons(self):
        """Not used. Generates persons at random geographical points with default parameters"""
        for i in range(50):
            attributes = {'id': i, 'age': 54, 'walking_speed': 5, 'driving_licence': bool(self.env.rand.getrandbits(1)),
                          'dimensions': {CD.SEATS: 1, CD.WHEELCHAIRS: int(self.env.rand.getrandbits(1))}
                          }
            activities = [
                Activity(type_=actType.HOME,
                         coord=Coord(lat=self.env.rand.uniform(minLat, maxLat),
                                     lon=self.env.rand.uniform(minLon, maxLon)),
                         end_time=td(hours=self.env.rand.uniform(0, 10),
                                     minutes=self.env.rand.uniform(0, 59)).total_seconds()
                         ),
                Activity(type_=actType.WORK,
                         coord=Coord(lat=self.env.rand.uniform(minLat, maxLat),
                                     lon=self.env.rand.uniform(minLon, maxLon)),
                         start_time=td(hours=self.env.rand.uniform(11, 23),
                                       minutes=self.env.rand.uniform(0, 59)).total_seconds()
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
        self.time_window_multiplier = 0
        self.time_window_constant = 0
        self.travel_type = None
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

        # has [time, eventType, *args] structure
        self.travel_log = []

        # we need to store that so that drt rerouting would know drt leg coordinates.
        # TODO: move this to a container in ServiceProvider
        self.drt_leg = None

        self.drt_tw_left = None
        self.drt_tw_right = None

        self.delivered = self.env.event()
        self.drt_executed = self.env.event()
        self._set_travel_type_and_time_window_attributes()
        self.add_process(self.behaviour.activate)

    def _set_attributes(self, attributes):
        for attr in attributes.items():
            setattr(self, attr[0], attr[1])

    def is_arrive_by(self):
        """Returns true when next (or current) trip is of 'arrive by' type"""
        if self.next_activity.type == actType.WORK:
            return True
        else:
            return False

    def update_otp_params(self):
        """Sets new otp params for a new trip. Params are deducted from activity"""
        self.otp_parameters.update({'arriveBy': self.is_arrive_by()})

    def _set_travel_type_and_time_window_attributes(self):
        if self.curr_activity.zone in self.env.config.get('drt.zones') and \
                self.next_activity.zone in self.env.config.get('drt.zones'):
            m = self.env.config.get('pt.time_window_multiplier_within')
            c = self.env.config.get('pt.time_window_constant_within')
            t = TravelType.WITHIN
        elif self.curr_activity.zone in self.env.config.get('drt.zones') and \
                self.next_activity.zone not in self.env.config.get('drt.zones'):
            m = self.env.config.get('pt.time_window_multiplier_out')
            c = self.env.config.get('pt.time_window_constant_out')
            t = TravelType.OUT
        elif self.curr_activity.zone not in self.env.config.get('drt.zones') and \
                self.next_activity.zone in self.env.config.get('drt.zones'):
            m = self.env.config.get('pt.time_window_multiplier_in')
            c = self.env.config.get('pt.time_window_constant_in')
            t = TravelType.IN
        else:
            log.error('Cannot determine what time window attributes to assign to a person.'
                      'Assigning default "within".'
                      'Person {}, activities'.format(self.id, self.activities))
            m = self.env.config.get('pt.time_window_multiplier_within')
            c = self.env.config.get('pt.time_window_constant_within')
            t = TravelType.WITHIN

        self.travel_type = t
        self.time_window_multiplier = m
        self.time_window_constant = c

    def save_travel_log(self):
        """Saves travel log to a file."""
        log_folder = self.env.config.get('sim.person_log_folder')
        try:
            with open('{}/person_{}'.format(log_folder, self.id), 'w') as f:
                for record in self.travel_log:
                    if len(record) > 2:
                        f.write(TravellerEventType.to_str(record[0], record[1], *record[2]))
                    else:
                        f.write(TravellerEventType.to_str(record[0], record[1]))
        except OSError as e:
            log.critical(e.strerror)

    def update_travel_log(self, event_type, *args):
        self.travel_log.append([self.env.time(), event_type, [*args]])

    def get_result(self, result):
        """Save trip results to the result dictionary"""
        super(Person, self).get_result(result)
        if 'Persons' not in result.keys():
            result['Persons'] = []

        result['Persons'].append(self)
        self.save_travel_log()

    def init_actual_trip(self):
        """Initiates an empty actual_trip to append executed legs and acts to it"""
        self.actual_trip = Trip()
        self.actual_trip.main_mode = self.planned_trip.main_mode
        self.actual_trip.legs = []

    def init_executed_drt_leg(self):
        self.actual_trip.legs.append(
            Leg(steps=[], duration=0, distance=0, mode=OtpMode.DRT)
        )

    def get_planning_time(self, trip):
        """Calculates a time to wait until the moment a person starts planning a trip
        returns: int in seconds when planning should happen
        :type trip: Trip - direct trip by a car from OSRM
        """

        # pre_trip_time = max(trip.duration * self.env.config.get('drt.planning_in_advance_multiplier'),
        #                     self.env.config.get('drt.planning_in_advance'))

        if self.is_arrive_by():
            pre_trip_time = trip.duration * self.time_window_multiplier + self.time_window_constant +\
                            self.env.config.get('drt.planning_in_advance')
        else:
            pre_trip_time = self.env.config.get('drt.planning_in_advance')

        timeout = int((self.next_activity.start_time - pre_trip_time - self.env.now))

        if timeout < 0:
            log.debug('{}: {} cannot plan {} seconds in advance, resetting timeout to zero'
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
        self.actual_trip = trip.deepcopy()

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
        """Creates the delivery events. These events are used to signal when trip is executed."""
        self.delivered = self.env.event()
        self.drt_executed = self.env.event()

    def __str__(self):
        if self.otp_parameters.get('arriveBy'):
            arr_by = 'arrive by'
            t = self.next_activity.start_time
        else:
            arr_by = 'depart at'
            t = self.curr_activity.end_time

        return 'Person {} going from {} zone {}, to {} zone {}, {} {}' \
            .format(self.id,
                    self.curr_activity.coord, self.curr_activity.zone,
                    self.next_activity.coord, self.next_activity.zone,
                    arr_by,
                    t
                    )

    def log_executed_trip(self):
        """After a trip has been executed, save it and related direct trip"""

        self.planned_trips.append(self.planned_trip)
        self.executed_trips.append(self.actual_trip)
        self.direct_trips.append(self.direct_trip)

    def set_direct_trip(self, trip):
        self.direct_trip = trip

    def set_drt_status(self, status):
        self.drt_status.append(status)

    def update_planned_drt_trip(self, drt_route):
        """Jsprit solution does not provide distances. # TODO: check if it is possible to include this in jsprit
        After service provider reconstructs DRT route with OTP, it calls for this to recalculate actual planned route,
        that will be compared with actual and direct trips.
        """
        drt_acts = [act for act in drt_route if act.person == self]
        start_act_idx = drt_route.index(drt_acts[0])
        end_act_idx = drt_route.index(drt_acts[-1])
        persons_route = drt_route[start_act_idx + 1:end_act_idx + 1]

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

    def set_tw(self, direct_time, single_leg=False, first_leg=False, last_leg=False, drt_leg=None, available_time=None):
        tw = direct_time * self.time_window_multiplier \
             + self.time_window_constant
        if available_time is not None:
            # tw = min(available_time, tw)
            tw = available_time

        if single_leg:
            self.drt_tw_left = self.curr_activity.end_time
            self.drt_tw_right = self.next_activity.start_time + tw

            # I do not even know what is the purpose of this shift any more:
            # self.drt_tw_left = self.curr_activity.end_time - tw * self.env.config.get('drt.time_window_shift_left')
            # self.drt_tw_right = self.next_activity.start_time \
            #     + tw * (1 - self.env.config.get('drt.time_window_shift_left'))
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
        """Returns: time in seconds when the left time window border starts"""
        return self.drt_tw_left

    def get_tw_right(self):

        return self.drt_tw_right

    def dumps(self):
        return {'actual_trips': self.executed_trips,
                'planned_trips': self.planned_trips,
                'direct_trips': self.direct_trips,
                'id': self.id}

    @staticmethod
    def _try_json(o):
        return o.__dict__
