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

    def _init_vehicles(self):
        """Should read and initialise vehicles from the database or something
        """
        for i in range(10):
            # if you want to change ID assignment method, you should change get_vehicle_by_id() method too
            attrib = {'id': i}
            coord = Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon))
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
        log.info('Request came at {0} from {1}'.format(
                self.env.now,
                person
                ))

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
            traditional_alternatives += self.router.otp_request(person, mode)
        return traditional_alternatives

    def _drt_request(self, person: Person):
        if person.curr_activity.zone not in self.env.config.get('drt.zones') \
           or person.next_activity.zone not in self.env.config.get('drt.zones'):
            log.info('{} requests a trip from {} to {}, ignoring DRT mode.'
                     .format(person, person.curr_activity.zone, person.next_activity.zone))
            return []

        vehicle_coords_times = self._get_vehicle_positions(self.env.now)
        return_vehicle_coords = [vehicle.return_coord for vehicle in self.vehicles]

        # get positions of scheduled requests
        # person.leg.start_coord and .end_coord have that, so get the persons
        persons = list(set(self.get_scheduled_travelers()))
        onboard_persons = self.get_onboard_travelers()
        waiting_persons = list(set(persons) - set(onboard_persons))
        shipment_persons = waiting_persons + [person]
        service_persons = onboard_persons
        # TODO: OTP may return WALK+CAR trip, find exactly DRT leg in the trip (assuming there could be more)
        persons_coords = [pers.planned_trip.legs[0].start_coord for pers in persons]
        persons_coords += [person.curr_activity.coord]
        persons_coords += [pers.planned_trip.legs[0].end_coord for pers in persons]
        persons_coords += [person.next_activity.coord]

        return self.router.drt_request(person, vehicle_coords_times, return_vehicle_coords, persons_coords,
                                       shipment_persons, service_persons)

    def _get_vehicle_positions(self, at_time):
        coords_times = []
        for vehicle in self.vehicles:
            # coord, time = vehicle.get_coord_time()
            # coords_times.append((coord, time))
            coords_times.append(vehicle.get_coord_time(at_time))
        return coords_times

    def start_trip(self, person: Person):
        if person.planned_trip is None:
            self.env.results['unrouted_trips'] += 1
            log.warning('{} received no feasible trip options'.format(person.scope))
        elif person.planned_trip.main_mode == OtpMode.DRT:
            self._start_drt_trip(person)
        else:
            self._start_traditional_trip(person)

    def _start_drt_trip(self, person):
        """
        :type person: Person
        """
        # TODO: check if jsprit_solution can affect multiple vehicles
        # TODO: this is a huge spaghetti function, put more functions for clarity

        jsprit_solution = self.pending_drt_requests.pop(person.id)
        if jsprit_solution is None:
            raise Exception('Trying to rerouted drt vehicle for {}, but no jsprit solution found for this')
        jsprit_route = jsprit_solution.modified_route  # type: JspritRoute

        vehicle = self.get_vehicle_by_id(jsprit_route.vehicle_id)  # type: Vehicle
        vehicle_coord_time = vehicle.get_coord_time(self.env.now)
        vehicle.coord = vehicle_coord_time[0]

        # when we modify a first act, we need to save it to actual route of persons
        original_route = vehicle.get_route_with_return()
        if len(original_route) == 0:
            original_first_act = None
        else:
            original_first_act = original_route[0].get_deep_copy()

        new_route, new_acts_index = self._add_dummy_acts(vehicle.get_route_without_return(), jsprit_route.acts, person)
        if vehicle.get_return_act() is not None:
            new_route.append(vehicle.get_return_act())
        vehicle.set_route(new_route)

        # If it is a very first act for a vehicle, add an act to return to depot
        if vehicle.get_act(-1).type != DrtAct.RETURN:
            vehicle.create_return_act()
        if vehicle.get_act(-1).duration is None:
            pass
            # TODO: what the hell should happen here? I have no idea.
            # It is ok for it to be empty, as it is staying at depot
            # raise Exception('Vehicle act list is empty. Return to depot should be the last act.')
            # print('wow')

        # We need to recalculate the routes (time, distance and steps) for neighbours of newly added acts
        index_to_recalc = set()
        # Normally, a vehicle should be in route. So we need to recalculate remaining time to finish current act
        # TODO: calculate it internally with act.steps
        # TODO: filter out vehicles that do not move
        if 0 not in new_acts_index:
            index_to_recalc.add(0)

        for index in new_acts_index:
            index_to_recalc.add(index)
            index_to_recalc.add(index+1)

        for i in index_to_recalc:
            if i == 0:
                coord_start = vehicle_coord_time[0]
                at_time = vehicle_coord_time[1]
            else:
                coord_start = vehicle.get_act(i-1).coord
                at_time = jsprit_route.acts[i-1].end_time
            coord_end = vehicle.get_act(i).coord

            trip = self.router.get_drt_route_details(coord_start=coord_start,
                                                     coord_end=coord_end,
                                                     at_time=at_time)  # type: Trip
            if len(trip.legs) > 1:
                log.error('OTP returned multiple legs for DRT trip from {} to {}'.format(coord_start, coord_end))
            act = vehicle.get_act(i)

            # when we reroute a current act of a vehicle, we need to update trip for persons as well
            if i == 0 and original_first_act is not None:
                passed_steps = original_first_act.get_passed_steps(vehicle.act_start_time, self.env.now)
                vehicle.update_executed_passengers_routes(passed_steps)
                vehicle.vehicle_kilometers += sum([step.distance for step in passed_steps])
                vehicle.ride_time += sum([step.duration for step in passed_steps])

            act.steps = trip.legs[0].steps
            act.distance = trip.legs[0].distance
            act.duration = trip.legs[0].duration

        for i in index_to_recalc:
            act = vehicle.get_act(i)
            # append an extra step (to pick up or drop off a person) to vehicle act
            if act.type != ActType.RETURN:
                if act.type == ActType.PICK_UP:
                    next_act = vehicle.get_act(i+1)
                    next_act.remove_embark_step()
                    next_act.add_embark_step(act.person.boarding_time, act.steps[-1].end_coord)
                elif act.type == ActType.DROP_OFF or act.type == ActType.DELIVERY:
                    act.remove_disembark_step()
                    act.add_disembark_step(act.person.leaving_time)
                else:
                    raise Exception('Unspecified act type')

        vehicle.act_start_time = vehicle_coord_time[1]

        person.update_planned_drt_trip(vehicle.get_route_without_return())

        if not vehicle.rerouted.triggered:
            # TODO: is there a reason to check this here?
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
        # TODO: move this method to vehicles
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
            new_act = DrtAct(type_=jsprit_act.type, person=person, coord=coord)
            drt_acts.insert(index, new_act)
            new_acts_index.append(index)

        return drt_acts, new_acts_index

    def get_scheduled_travelers(self):
        """Scans through vehicle routes and combines attached persons in a list. NOTE: persons may appear twice"""
        persons = []
        for vehicle in self.vehicles:
            # last act is a return act, it has no person
            for act in vehicle.get_route_without_return():  # type: DrtAct
                persons.append(act.person)
        return persons

    def get_onboard_travelers(self):
        persons = []
        for vehicle in self.vehicles:
            persons += vehicle.passengers
        return persons
