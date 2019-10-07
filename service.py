#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 19 13:24:35 2018

@author: ai6644
"""

import logging
from typing import List, Dict, Any
import time
import copy

import routing
from itertools import compress

from desmod.component import Component
from simpy import Event

from const import OtpMode
from const import maxLat, minLat, maxLon, minLon
from const import CapacityDimensions as CD
from utils import Coord, JspritAct, Step, JspritSolution, JspritRoute
from vehicle import Vehicle, VehicleType
from utils import ActType, DrtAct, Trip
from population import Person
from exceptions import *

log = logging.getLogger(__name__)


class ServiceProvider(Component):

    pending_drt_requests = ...  # type: Dict[int, JspritSolution]
    vehicles = ...  # type: List[Vehicle]
    base_name = 'service'
    
    def __init__(self, *args, **kwargs):
        super(ServiceProvider, self).__init__(*args, **kwargs)
        self.vehicles = []
        self.vehicle_types = {}
        self.pending_drt_requests = {}
        router = self.env.config.get('service.routing')
        log.info('Setting router: {}'.format(router))
        self.router = getattr(routing, router)(self)

        self._set_vehicle_types()
        self._init_vehicles()

        self.add_connections('population')

    def _init_vehicles(self):
        """Should read and initialise vehicles from the database or something
        """
        for i in range(5):
            # if you want to change ID assignment method, you should change get_vehicle_by_id() method too
            attrib = {'id': i}
            # coord = Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon))
            coord = Coord(lat=55.630995, lon=13.701037)
            v_type = self.vehicle_types.get(1)
            self.vehicles.append(Vehicle(parent=self, attrib=attrib, coord=coord, vehicle_type=v_type))

        for i in range(5,10):
            # if you want to change ID assignment method, you should change get_vehicle_by_id() method too
            attrib = {'id': i}
            # coord = Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon))
            coord = Coord(lat=55.546315, lon=13.949113)
            v_type = self.vehicle_types.get(1)
            self.vehicles.append(Vehicle(parent=self, attrib=attrib, coord=coord, vehicle_type=v_type))

    def get_vehicle_by_id(self, idx):
        """Currently IDs are assigned in order"""
        return self.vehicles[idx]

    def _set_vehicle_types(self):
        """
        :return: a dictionary with ID as a key and object as its value
        """
        for i in range(5):
            self.vehicle_types[i] = VehicleType(attrib={'id': i})
            # self.vehicle_types[i] = VehicleType(attrib={
            #         'id': i,
            #         # TODO: vehicle capacity should be defined in config files
            #         'capacity_dimensions': {CD.SEATS: 8, CD.WHEELCHAIRS: 1}
            #         })

    def request(self, person: Person):
        log.info('Request came at {0} from {1}'.format(self.env.now, person))

        start = time.time()
        traditional_alternatives = self._traditional_request(person)
        log.debug('Web requests took {}'.format(time.time() - start))
        start = time.time()
        drt_alternatives = self._drt_request(person)
        log.debug('DRT request took {}'.format(time.time() - start))
        alternatives = traditional_alternatives + drt_alternatives

        if len(alternatives) == 0:
            log.warning('no alternatives received by {}'.format(person.scope))
        return alternatives

    def _traditional_request(self, person):
        traditional_alternatives = []
        modes_config = self.env.config.get('service.modes')
        if modes_config == 'main_modes':
            modes = OtpMode.get_main_modes()
        elif modes_config == 'all_modes':
            modes = OtpMode.get_all_modes()
        else:
            raise Exception('service.modes configured incorrectly')

        for mode in modes:
            if mode in ['DRT']:
                continue
            try:
                traditional_alternatives += self.router.otp_request(person, mode)
            except OTPNoPath:
                continue

        if len(traditional_alternatives) is 0:
            raise OTPUnreachable(msg='Person origin or destination are unreachable', context=str(person))
        else:
            return traditional_alternatives

    def _drt_request(self, person: Person):
        if person.curr_activity.zone not in self.env.config.get('drt.zones') \
           or person.next_activity.zone not in self.env.config.get('drt.zones'):
            log.info('{} requests a trip from {} to {}, ignoring DRT mode.'
                     .format(person, person.curr_activity.zone, person.next_activity.zone))
            return []

        vehicle_coords_times = self._get_current_vehicle_positions()
        vehicle_return_coords = [vehicle.return_coord for vehicle in self.vehicles]

        # get positions of scheduled requests
        # person.leg.start_coord and .end_coord have that, so get the persons
        persons = self.get_scheduled_travelers()
        onboard_persons = self.get_onboard_travelers()
        waiting_persons = list(set(persons) - set(onboard_persons))
        shipment_persons = waiting_persons + [person]
        service_persons = onboard_persons
        # TODO: OTP may return WALK+CAR trip, find exactly DRT leg in the trip (assuming there could be more)
        # persons_coords = [pers.planned_trip.legs[0].start_coord for pers in persons]
        persons_coords = [pers.curr_activity.coord for pers in persons]
        persons_coords += [person.curr_activity.coord]
        # persons_coords += [pers.planned_trip.legs[0].end_coord for pers in persons]
        persons_coords += [pers.next_activity.coord for pers in persons]
        persons_coords += [person.next_activity.coord]

        return self.router.drt_request(person, vehicle_coords_times, vehicle_return_coords, persons_coords,
                                       shipment_persons, service_persons)

    def _get_current_vehicle_positions(self):
        coords_times = []
        for vehicle in self.vehicles:
            coords_times.append(vehicle.get_current_coord_time())
        return coords_times

    def start_trip(self, person: Person):
        # TODO: this should not be the case. If it is, person should be explicitly removed from the simulation
        if person.planned_trip is None:
            self.env.results['unrouted_trips'] += 1
            log.warning('{} received no feasible trip options'.format(person.scope))
        elif person.planned_trip.main_mode == OtpMode.DRT:
            self._start_drt_trip2(person)
        else:
            self._start_traditional_trip(person)

    def _jsprit_act_to_drt_act(self, start_time, njact: JspritAct, coord_start, coord_end, act_type) -> DrtAct:
        drt_act = DrtAct(type_=act_type, person=None,
                         duration=njact.arrival_time - start_time,
                         end_coord=coord_end, start_coord=coord_start, start_time=start_time, end_time=njact.arrival_time)

        # TODO: This calls for OTP to recalculate all the routes. Move this to Vehicle, so that only the next trip is
        # recalculated to save time on OTP requests
        try:
            trip = self.router.get_drt_route_details(coord_start=coord_start,
                                                     coord_end=coord_end,
                                                     at_time=start_time)  # type: Trip
        except OTPTrivialPath as e:
            log.warning('Trivial path found for DRT routing. That can happen.\n{}\n{}'.format(e.msg, e.context))
            trip = Trip()
            trip.set_empty_trip(OtpMode.DRT, coord_start, coord_end)

        if len(trip.legs) > 1:
            log.error('OTP returned multiple legs for DRT trip from {} to {}.'.format(coord_start, drt_act.end_coord))
            raise Exception()

        drt_act.steps = trip.legs[0].steps
        drt_act.distance = trip.distance
        if drt_act.duration != sum([s.duration for s in drt_act.steps]):
            log.error('Time is lost during jsprit route conversion')
        if drt_act.start_time + drt_act.duration != drt_act.end_time:
            log.error('Act end time does not correspond to its duration')

        return drt_act

    def _get_drt_return_act(self, drt_act, coord_start):
        try:
            trip = self.router.get_drt_route_details(coord_start=coord_start,
                                                     coord_end=drt_act.end_coord,
                                                     at_time=drt_act.start_time)  # type: Trip
        except OTPTrivialPath as e:
            log.warning('Trivial path found for DRT routing. That can happen.\n{}\n{}'.format(e.msg, e.context))
            trip = Trip()
            trip.set_empty_trip(OtpMode.DRT, coord_start, drt_act.end_coord)
            return trip

        if len(trip.legs) > 1:
            log.error('OTP returned multiple legs for DRT trip from {} to {}.'.format(coord_start, drt_act.end_coord))
            raise Exception()

        drt_act.steps = trip.legs[0].steps
        drt_act.distance = trip.distance
        if drt_act.duration != sum([s.duration for s in drt_act.steps]):
            log.error('Time is lost during jsprit route conversion')

    def _jsprit_to_drt2(self, vehicle, jsprit_route: JspritRoute):
        drt_acts = []  # type: List[DrtAct]

        first_act = JspritAct(type_=DrtAct.DRIVE, person_id=None, end_time=jsprit_route.start_time)
        last_act = JspritAct(type_=DrtAct.RETURN, person_id=None, end_time=None, arrival_time=jsprit_route.end_time)

        for i, (pjact, njact) in enumerate(zip([first_act] + jsprit_route.acts, jsprit_route.acts + [last_act])):
            if i == len(jsprit_route.acts):
                person = None
            else:
                person = self.population.get_person(njact.person_id)  # type: Person

                if person.id == 6709:
                    print('debugging!')

            # *************************************************************
            # **********         Moving to an activity           **********
            # *************************************************************
            if i == 0:
                if person.id == 6709:
                    print('debugging2!')
                coord_start = vehicle.get_current_coord_time()[0]
            else:
                coord_start = drt_acts[-1].end_coord

            if njact.type == ActType.PICK_UP:
                coord_end = person.curr_activity.coord
            elif njact.type in [ActType.DROP_OFF, ActType.DELIVERY]:
                coord_end = person.next_activity.coord
            elif njact.type == ActType.RETURN:
                coord_end = vehicle.return_coord
            else:
                raise Exception('Unexpected act type {}'.format(njact.type))

            move_act = self._jsprit_act_to_drt_act(start_time=pjact.end_time,
                                                   njact=njact,
                                                   coord_start=coord_start,
                                                   coord_end=coord_end,
                                                   act_type=DrtAct.DRIVE)

            # Vehicle is likely to be doing some step, but we cannot reroute it at any given point,
            # only after it finishes its current step
            if i == 0 and self.env.now != jsprit_route.start_time and vehicle.get_route_len() > 0:
                curr_v_act = vehicle.get_act(0)  # type: DrtAct

                # if a vehicle is picking up or delivering a person, just save this act in a new route
                if curr_v_act.type in [DrtAct.PICK_UP, DrtAct.DROP_OFF, DrtAct.DELIVERY]:
                    drt_acts.append(curr_v_act)
                # if vehicle is on the move, append its current step to a plan
                if curr_v_act.type == DrtAct.DRIVE:
                    curr_v_step = vehicle.get_current_step()
                    if curr_v_step is not None:
                        move_act.steps.insert(0, curr_v_step)
                        move_act.duration += curr_v_step.duration
                        move_act.start_time -= curr_v_step.duration
                        move_act.distance += curr_v_step.distance

            # OTP returns a route that stops at road tile, not exact destination coordinate
            move_act.steps[-1].end_coord = move_act.end_coord
            drt_acts.append(move_act)

            if njact.type == ActType.RETURN:
                break

            # *************************************************************
            # **********        Performing an activity           **********
            # *************************************************************
            if njact.type == ActType.PICK_UP:
                duration = person.boarding_time
            else:
                duration = person.leaving_time
            action = DrtAct(type_=njact.type, person=person, duration=duration, distance=0,
                            end_coord=drt_acts[-1].end_coord, start_coord=drt_acts[-1].end_coord,
                            start_time=drt_acts[-1].end_time, end_time=drt_acts[-1].end_time + duration)
            action.steps = [Step(coord=action.end_coord, distance=0, duration=duration)]
            drt_acts.append(action)

            # *************************************************************
            # **********        Waiting after an activity        **********
            # *************************************************************
            if action.end_time != njact.end_time:
                wait_act = DrtAct(type_=ActType.WAIT, person=None, duration=njact.end_time - drt_acts[-1].end_time,
                                  end_coord=drt_acts[-1].end_coord, start_coord=drt_acts[-1].end_coord,
                                  distance=0, start_time=drt_acts[-1].end_time, end_time=njact.end_time)
                wait_act.steps = [Step(coord=wait_act.end_coord, distance=0, duration=wait_act.duration)]
                drt_acts.append(wait_act)

        if drt_acts[-1].type == DrtAct.DRIVE:
            drt_acts[-1].type = DrtAct.RETURN
        return drt_acts

    def _start_drt_trip2(self, person):
        jsprit_solution = self.pending_drt_requests.pop(person.id)
        if jsprit_solution is None:
            raise Exception('Trying to rerouted drt vehicle for {}, but no jsprit solution found for this')
        jsprit_route = jsprit_solution.modified_route  # type: JspritRoute

        vehicle = self.get_vehicle_by_id(jsprit_route.vehicle_id)  # type: Vehicle

        if person.id == 6730:
            print('very debug3!')

        new_route = self._jsprit_to_drt2(vehicle=vehicle, jsprit_route=jsprit_route)
        vehicle.update_partially_executed_trips()
        person.update_planned_drt_trip(new_route)
        vehicle.set_route(new_route)

        # If several request come at the same time, the same event will be triggered several times
        # which is an exception in simpy
        if not vehicle.rerouted.triggered:
            vehicle.rerouted.succeed()

    def _start_traditional_trip(self, person: Person):
        """
        Currently just add values to the environment variable
        """
        pass

    def execute_trip(self, person: Person):
        if person.planned_trip.main_mode == OtpMode.DRT:
            yield person.drt_executed
            person.delivered.succeed()
        else:
            yield self.env.timeout(person.planned_trip.duration)
            person.delivered.succeed()
            person.actual_trip = person.planned_trip

        self.env.results['total_trips'] += 1
        self.env.results['{}_trips'.format(person.planned_trip.main_mode)] += 1
        for leg in person.planned_trip.legs:
            self.env.results['{}_legs'.format(leg.mode)] += 1

    @staticmethod
    def _add_dummy_acts(drt_acts, jsprit_acts, person):
        # TODO: move this method to vehicles?
        """Finds where drt_acts differ from jsprit and injects new DrtAct elements

        We know what person is needed to be routed, thus there is no need to search person by ID

        returns: list with indexes of new elements, they should be routed with OTP
        :type jsprit_acts: List[JspritAct]
        """
        drt_iter = iter(drt_acts)
        new_acts_index = []

        for jsprit_act in jsprit_acts:
            try:
                drt_act = next(drt_iter)
                if drt_act.person.id == jsprit_act.person_id and drt_act.type == jsprit_act.type:
                    continue
                else:
                    # when we find a position where acts differ, insert a new act to vehicle
                    index = drt_acts.index(drt_act)
            except StopIteration:
                # If new acts come to the last position, or if current vehicle act list is empty
                # insert new act to the end of the list
                index = len(drt_acts)
            coord = person.curr_activity.coord if jsprit_act.type == ActType.PICK_UP else person.next_activity.coord
            new_act = DrtAct(type_=jsprit_act.type, person=person, end_coord=coord)
            drt_acts.insert(index, new_act)
            new_acts_index.append(index)

        return drt_acts, new_acts_index

    def get_scheduled_travelers(self):
        """Scans through vehicle routes and combines attached persons in a list.

        Returns: list of not None persons"""
        persons = []
        for vehicle in self.vehicles:
            for act in vehicle.get_route_without_return():  # type: DrtAct
                persons.append(act.person)
        return [a for a in set(persons) if a is not None]

    def get_onboard_travelers(self):
        persons = []
        for vehicle in self.vehicles:
            persons += vehicle.passengers
        return persons
