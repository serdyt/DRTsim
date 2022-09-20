#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utils to manage population
"""

import logging
from datetime import timedelta as td
import json
from typing import List, Dict
from math import floor, ceil

from desmod.component import Component
import behaviour
import mode_choice
from exceptions import PersonNotRelatedToStudyZones

from sim_utils import Activity, Coord, Trip, Leg, Step, ActType
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
        self.read_json()
        log.info('{}: Population of {} persons created.'.format(self.env.now, len(self.person_list)))

    def read_json(self):
        """Reads json input file and generates persons to simulate"""
        with open(self.env.config.get('population.input_file'), 'r') as input_file:
            raw_json = json.load(input_file)
            persons = raw_json.get('persons')
            pers_id = 0
            for json_pers in persons:

                if self.env.rand.choices([False, True],
                                         [self.env.config.get('population.input_percentage'),
                                          1 - self.env.config.get('population.input_percentage')])[0]:
                    continue

                try:
                    pers = self._person_from_json(json_pers, pers_id)
                except PersonNotRelatedToStudyZones:
                    continue
                finally:
                    pers_id += 1

                # if pers.activities[0].zone in self.env.config.get('drt.zones') \
                #         or pers.activities[1].zone in self.env.config.get('drt.zones'):



                self.person_list.append(pers)

    def _person_from_json(self, json_pers, pers_id=None):
        # if self.env.rand.choices([False, True],
        #                          [self.env.config.get('population.input_percentage'),
        #                          1 - self.env.config.get('population.input_percentage')])[0]:
        #     continue
        if pers_id is not None:
            attributes = {'age': 22, 'id': pers_id, 'otp_parameters': {'arriveBy': True}}
        else:
            attributes = {'age': 22, 'id': json_pers['id'], 'otp_parameters': {'arriveBy': True}}

        # TODO: sequence of activities has the same end and start times
        # time window is applied on the planning stage in the behaviour and service

        activities = []
        json_activities = json_pers.get('activities')
        if len(json_activities) == 0:
            raise Exception('No activities provided for a person.')
        for json_activity in json_activities:
            type_str = json_activity.get('type')
            # type_ = actType.get_activity(type_str)
            type_ = int(type_str)

            start_time = int(json_activity.get('start_time'))
            end_time = int(json_activity.get('end_time'))

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

        self.dimensions = self.env.config.get('person.default_attr.dimensions')
        self.id = None
        self.driving_license = self.env.config.get('person.default_attr.driving_license')
        self.walking_speed = self.env.config.get('person.default_attr.walking_speed')
        self.age = self.env.config.get('person.default_attr.age')
        self.boarding_time = self.env.config.get('person.default_attr.boarding_time')
        self.leaving_time = self.env.config.get('person.default_attr.leaving_time')

        self.otp_parameters = {}
        self.attributes = {}
        self.max_trip_duration_multiplier = 0
        self.max_trip_duration_constant = 0
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

        # self.drt_tw_left = None
        # self.drt_tw_right = None
        self.trip_tw_left = None
        self.trip_tw_right = None

        self.drt_tw_start_left = None
        self.drt_tw_start_right = None
        self.drt_tw_end_left = None
        self.drt_tw_end_right = None

        self.max_drt_duration = None

        self.delivered = self.env.event()
        self.drt_executed = self.env.event()
        try:
            self._set_travel_type_and_time_window_attributes()
            self.add_process(self.behaviour.activate)
        except PersonNotRelatedToStudyZones as e:
            raise PersonNotRelatedToStudyZones(e)

        self.serviceProvider = None
        self.add_connections('serviceProvider')

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
        self.get_routing_parameters().update({'arriveBy': self.is_arrive_by()})

    def _set_travel_type_and_time_window_attributes(self):
        if self.curr_activity.zone in self.env.config.get('drt.zones') and \
                self.next_activity.zone in self.env.config.get('drt.zones'):
            wm = self.env.config.get('pt.trip_time_window_multiplier_within')
            wc = self.env.config.get('pt.max_trip_duration_constant_within')
            tm = self.env.config.get('pt.max_trip_duration_multiplier_within')
            tc = self.env.config.get('pt.max_trip_duration_constant_within')
            t = TravelType.WITHIN
        elif self.curr_activity.zone in self.env.config.get('drt.zones') and \
                self.next_activity.zone not in self.env.config.get('drt.zones'):
            wm = self.env.config.get('pt.trip_time_window_multiplier_out')
            wc = self.env.config.get('pt.max_trip_duration_constant_out')
            tm = self.env.config.get('pt.max_trip_duration_multiplier_out')
            tc = self.env.config.get('pt.max_trip_duration_constant_out')
            t = TravelType.OUT
        elif self.curr_activity.zone not in self.env.config.get('drt.zones') and \
                self.next_activity.zone in self.env.config.get('drt.zones'):
            wm = self.env.config.get('pt.trip_time_window_multiplier_in')
            wc = self.env.config.get('pt.max_trip_duration_constant_in')
            tm = self.env.config.get('pt.max_trip_duration_multiplier_in')
            tc = self.env.config.get('pt.max_trip_duration_constant_in')
            t = TravelType.IN
        else:
            log.error('Person does not seem to be related to  "drt.zones".'
                      'Excluding.'
                      'Person {}, activities'.format(self.id, self.activities))
            raise PersonNotRelatedToStudyZones('Person {}, activities'.format(self.id, self.activities))

        self.trip_time_window_multiplier = self.env.config.get('pt.trip_time_window_multiplier')
        self.trip_time_window_constant = self.env.config.get('pt.trip_time_window_constant')

        self.travel_type = t

        self.time_window_multiplier = wm
        self.time_window_constant = wc

        self.max_trip_duration_multiplier = tm
        self.max_trip_duration_constant = tc

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
            pre_trip_time = self.get_max_trip_duration(trip.duration) + self.env.config.get('drt.planning_in_advance')
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
        # self.actual_trip.duration = sum([leg.duration for leg in self.actual_trip.legs])
        # OTP and DRT both do not include 'WAIT' legs
        self.actual_trip.duration = self.actual_trip.legs[-1].end_time - self.actual_trip.legs[0].start_time
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
        if self.get_routing_parameters().get('arriveBy'):
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

    def get_direct_trip_duration(self):
        return self.get_direct_trip().duration

    def get_direct_trip_distance(self):
        return self.get_direct_trip().distance

    def get_direct_trip(self):
        return self.direct_trip

    def set_drt_status(self, status):
        self.drt_status.append(status)

    def update_planned_drt_trip(self, drt_route):
        """Jsprit solution does not provide distances. # TODO: check if it is possible to include this in jsprit
        After service provider reconstructs DRT route with OTP, it calls for this to recalculate actual planned route,
        that will be compared with actual and direct trips.
        """
        drt_acts = [act for act in drt_route if act.person == self and
                    act.type in [ActType.PICK_UP, ActType.DROP_OFF, ActType.DELIVERY]]

        # jsprit has no distance and steps
        drt_leg = self.get_planned_drt_leg()
        if drt_acts[-1].type == ActType.DELIVERY:
            drt_leg.duration = drt_acts[-1].end_time - drt_leg.start_time
            drt_leg.end_time = drt_acts[-1].end_time
        else:
            drt_leg.duration = drt_acts[-1].end_time - drt_acts[-1].start_time
            drt_leg.end_time = drt_acts[-1].end_time
            drt_leg.start_time = drt_acts[-1].start_time

        self.planned_trip.set_duration(self.planned_trip.legs[-1].end_time - self.planned_trip.legs[0].start_time)
        # self.planned_trip.legs[0].duration = self.planned_trip.duration
        # self.planned_trip.legs[0].distance = self.planned_trip.distance

    def get_planned_drt_leg(self):
        return self.planned_trip.legs[self.planned_trip.get_leg_modes().index(OtpMode.DRT)]

    def change_activity(self):
        """Updates current and next activities from a list of planned activities.
        Returns -1 in case of error
        """

        if len(self.activities) > 0:
            self.curr_activity = self.next_activity
            self.next_activity = self.activities.pop(0)

            self.alternatives = []
            # noinspection PyTypeChecker
            self.planned_trip = None
            self.direct_trip = None

            return 0
        else:
            return -1

    def get_routing_parameters(self):
        return self.otp_parameters

    def is_local_trip(self):
        return self.curr_activity.zone in self.env.config.get('drt.zones') \
               and self.next_activity.zone in self.env.config.get('drt.zones')

    def is_in_trip(self):
        return self.curr_activity.zone not in self.env.config.get('drt.zones') \
               and self.next_activity.zone in self.env.config.get('drt.zones')

    def is_out_trip(self):
        return self.curr_activity.zone in self.env.config.get('drt.zones') \
               and self.next_activity.zone not in self.env.config.get('drt.zones')

    def is_trip_within_tw(self, trip):
        if self.is_arrive_by():
            if self.get_trip_tw_end_left() <= trip.legs[-1].end_time <= self.get_trip_tw_end_right():
                return True
            else:
                return False
        else:
            if self.get_trip_tw_start_left() <= trip.legs[0].start_time <= self.get_trip_tw_start_right():
                return True
            else:
                return False

    def is_trip_within_default_tw(self, trip):
        if self.is_arrive_by():
            if self.get_trip_tw_end_right() - self.env.config.get('pt.default_trip_time_window_constant') \
                    <= trip.legs[-1].end_time <= self.get_trip_tw_end_right():
                return True
            else:
                return False
        else:
            if self.get_trip_tw_start_left() <= trip.legs[0].start_time <= \
                    self.get_trip_tw_start_left() + self.env.config.get('pt.default_trip_time_window_constant'):
                return True
            else:
                return False

    def get_max_drt_duration(self):
        if self.is_local_trip():
            return self.get_max_trip_duration(self.get_direct_trip_duration())
        else:
            return self.max_drt_duration

    def get_rest_drt_duration(self):
        if self.actual_trip is None:
            return self.get_max_drt_duration()
        elif self.actual_trip.legs is None:
            return self.get_max_drt_duration()

        if self.is_local_trip():
            t = self.get_max_drt_duration() - (self.env.now - self.actual_trip.legs[0].start_time)
        elif self.is_in_trip():
            t = self.get_max_drt_duration() - (self.env.now - self.actual_trip.legs[-1].start_time)
        else:
            t = self.get_max_drt_duration() - (self.env.now - self.actual_trip.legs[0].start_time)

        if t < 0:
            log.error("Person {} max trip length of {}, but left {}, tw [{}-{},{}-{}]".
                      format(self.id, self.get_max_drt_duration(), t,
                             self.get_drt_tw_start_left(), self.get_drt_tw_start_right(),
                             self.get_drt_tw_end_left(), self.get_drt_tw_end_right()))
            t = 0
        return t

    def get_time_window(self):
        return self.time_window_constant + self.time_window_multiplier * self.get_direct_trip_duration()

    def get_max_trip_duration(self, direct_time):
        """Computes maximum trip duration according to direct_time*dtm + dtc"""
        return direct_time * self.max_trip_duration_multiplier + self.max_trip_duration_constant + \
               self.boarding_time + self.leaving_time

    def get_default_time_window(self):
        return self.env.config.get('pt.default_trip_time_window_constant') + \
               self.env.config.get('pt.default_trip_time_window_multiplier') * self.get_direct_trip_duration()

    def set_default_trip_tw(self):
        if self.is_arrive_by():
            self.trip_tw_right = self.next_activity.start_time + ceil(self.get_default_time_window() / 2)
            self.trip_tw_left = self.next_activity.start_time - \
                                self.get_max_trip_duration(self.get_direct_trip_duration()) - \
                                ceil(self.get_default_time_window() / 2)
        else:
            self.trip_tw_left = self.curr_activity.end_time - ceil(self.get_default_time_window() / 2)
            self.trip_tw_right = self.curr_activity.end_time + \
                                 self.get_max_trip_duration(self.get_direct_trip_duration()) + \
                                 ceil(self.get_default_time_window() / 2)

        if self.trip_tw_left < self.env.now:
            self.trip_tw_left = self.env.now
        if self.trip_tw_right > self.env.config.get('sim.duration_sec'):
            self.trip_tw_right = self.env.config.get('sim.duration_sec')

    def set_trip_tw(self):
        """
        TODO: replace this with start/end time window and max trip duration
        Time windows are set around the desired departure/arrival time
        This time window includes THE WHOLE trip!
        """
        if self.is_arrive_by():
            self.trip_tw_right = self.next_activity.start_time + ceil(self.get_time_window() / 2)
            self.trip_tw_left = self.next_activity.start_time - \
                                self.get_max_trip_duration(self.get_direct_trip_duration()) - \
                                ceil(self.get_time_window() / 2)
        else:
            self.trip_tw_left = self.curr_activity.end_time - ceil(self.get_time_window() / 2)
            self.trip_tw_right = self.curr_activity.end_time + \
                                 self.get_max_trip_duration(self.get_direct_trip_duration()) + \
                                 ceil(self.get_time_window() / 2)

        if self.trip_tw_left < self.env.now:
            self.trip_tw_left = self.env.now
        if self.trip_tw_right > self.env.config.get('sim.duration_sec'):
            self.trip_tw_right = self.env.config.get('sim.duration_sec')

    def set_drt_tw(self, drt_direct_time, single_leg=False, first_leg=False, last_leg=False, drt_leg=None,
                   available_time=None):
        """
        drt_tw_end - is the time window for the departure
        Currently it is equal to trip_tw. Should we remove it?
        """
        if single_leg:
            if self.is_arrive_by():
                self.drt_tw_start_left = self.next_activity.start_time - ceil(self.get_time_window() / 2) - \
                                         self.get_max_trip_duration(self.get_direct_trip_duration())
                self.drt_tw_start_right = self.next_activity.start_time + ceil(self.get_time_window() / 2) - \
                                          self.get_max_trip_duration(self.get_direct_trip_duration())
                self.drt_tw_end_left = self.drt_tw_start_left
                self.drt_tw_end_right = self.get_trip_tw_right()
            else:
                self.drt_tw_start_left = self.next_activity.start_time - ceil(self.get_time_window() / 2)
                self.drt_tw_start_right = self.next_activity.start_time + ceil(self.get_time_window() / 2)
                self.drt_tw_end_left = self.drt_tw_start_left
                self.drt_tw_end_right = self.get_trip_tw_right()

        elif first_leg:
            self.drt_tw_start_left = drt_leg.end_time - available_time
            self.drt_tw_start_right = drt_leg.end_time
            self.drt_tw_end_left = self.drt_tw_start_left
            self.drt_tw_end_right = self.drt_tw_start_right
        elif last_leg:
            self.drt_tw_start_left = drt_leg.start_time
            self.drt_tw_start_right = drt_leg.start_time + available_time
            self.drt_tw_end_left = self.drt_tw_start_left
            self.drt_tw_end_right = self.drt_tw_start_right
        else:
            raise Exception('Incorrect input for time window calculation for Person {}.\n{} {} {}'
                            .format(self.id, drt_direct_time, single_leg, first_leg, last_leg, drt_leg))

        if self.drt_tw_start_left < self.env.now:
            self.drt_tw_start_left = self.env.now
        if self.drt_tw_start_right > self.env.config.get('sim.duration_sec'):
            self.drt_tw_start_right = self.env.config.get('sim.duration_sec')
        if self.drt_tw_end_left is not None:
            if self.drt_tw_end_left < self.env.now:
                self.drt_tw_end_left = self.env.now
        if self.drt_tw_end_right is not None:
            if self.drt_tw_end_right > self.env.config.get('sim.duration_sec'):
                self.drt_tw_end_right = self.env.config.get('sim.duration_sec')

        self.set_max_drt_duration(available_time)

    def set_max_drt_duration(self, duration):
        self.max_drt_duration = duration

    def get_trip_departure_with_tw_for_otp(self):
        """Returns a time for OTP time parameter"""
        if self.is_arrive_by():
            return self.get_trip_tw_end_right()
        else:
            return self.get_trip_tw_start_left()

    def get_drt_tw_end_left(self):
        return self.drt_tw_end_left

    def get_drt_tw_end_right(self):
        return self.drt_tw_end_right

    def get_drt_tw_start_left(self):
        return self.drt_tw_start_left

    def get_drt_tw_start_right(self):
        return self.drt_tw_start_right

    def get_trip_tw_left(self):
        return self.trip_tw_left

    def get_trip_tw_right(self):
        return self.trip_tw_right

    def get_trip_tw_start_left(self):
        return self.trip_tw_left

    def get_trip_tw_start_right(self):
        return self.trip_tw_left + self.get_time_window()

    def get_trip_tw_end_left(self):
        return self.trip_tw_right - self.get_time_window()

    def get_trip_tw_end_right(self):
        return self.trip_tw_right

    def dumps(self):
        return {'actual_trips': self.executed_trips,
                'planned_trips': self.planned_trips,
                'direct_trips': self.direct_trips,
                'id': self.id}

    @staticmethod
    def _try_json(o):
        return o.__dict__
