#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 19 13:24:35 2018

@author: ai6644
"""

import logging
from typing import List, Dict
import time

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


class ServiceProvider(Component):
    
    pending_drt_requests = None  # type: Dict[int, JspritSolution]
    vehicles = None  # type: List[Vehicle]
    base_name = 'service'
    
    def __init__(self, *args, **kwargs):
        super(ServiceProvider, self).__init__(*args, **kwargs)
        self.vehicles = []
        self.vehicle_types = {}
        self.pending_drt_requests = {}
        router = self.env.config.get('service.routing')
        logging.info('Setting router: {}'.format(router))
        self.router = getattr(routing, router)(self)

        self._get_vehicle_types()
        self._init_vehicles()

    def _init_vehicles(self):
        """Should read and initialise vehicles from the database or something
        """
        for i in range(2):
            # if you want to change ID assignment method, you should change get_vehicle_by_id() method too
            attrib = {'id': i}
            coord = Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon))
            v_type = self.vehicle_types.get(1)
            self.vehicles.append(Vehicle(parent=self, attrib=attrib, coord=coord, vehicle_type=v_type))

    def get_vehicle_by_id(self, id):
        """Currently IDs are assigned in order"""
        return self.vehicles[id]

    def _get_vehicle_types(self):
        """
        :return: a dictionary with ID as a key and object as its value
        """
        for i in range(5):
            self.vehicle_types[i] = VehicleType(attrib={
                    'id': i,
                    'capacity_dimensions': {CD.SEATS: 8, CD.WHEELCHAIRS: 1}
                    })

    def request(self, person):
        logging.info('Request came at {0} from {1}'.format(
                self.env.now,
                person.scope
                ))

        start = time.time()
        traditional_alternatives = self._traditional_request(person)
        print('{} Web requests took {}, that is {} per one'.format(12, time.time() - start, (time.time() - start) / 12))
        start = time.time()
        drt_alternatives = self._drt_request(person)
        print('DRT request took {}'.format(time.time() - start))
        alternatives = traditional_alternatives + drt_alternatives

        if len(alternatives) == 0:
            logging.warning('no alternatives received by {}'.format(person.scope))
        return alternatives

    def _traditional_request(self, person):
        traditional_alternatives = []
        for mode in OtpMode.get_all_modes():
            if mode in ['DRT']:
                continue
            traditional_alternatives += self.router.otp_request(person, mode)
        return traditional_alternatives

    def _drt_request(self, person):
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
        persons_coords = [pers.trip.legs[0].start_coord for pers in persons]
        persons_coords += [person.curr_activity.coord]
        persons_coords += [pers.trip.legs[0].end_coord for pers in persons]
        persons_coords += [person.next_activity.coord]

        return self.router.drt_request(person, vehicle_coords_times, return_vehicle_coords, persons_coords,
                                       shipment_persons, service_persons)

    def _get_vehicle_positions(self, time):
        coords_times = []
        for vehicle in self.vehicles:
            # coord, time = vehicle.get_coord_time()
            # coords_times.append((coord, time))
            coords_times.append(vehicle.get_coord_time(time))
        return coords_times

    def start_trip(self, person):
        if person.trip is None:
            self.env.results['unrouted_trips'] += 1
            logging.warning('{} received no feasible trip options'.format(person.scope))
        elif person.trip.main_mode == OtpMode.DRT:
            self._start_drt_trip(person)
        else:
            self._start_traditional_trip(person)

    def _start_drt_trip(self, person):
        """

        :type person: Person
        """
        jsprit_solution = self.pending_drt_requests.pop(person.id)
        if jsprit_solution is None:
            raise Exception('Trying to rerouted drt vehicle for {}, but no jsprit solution found for this')
        jsprit_route = jsprit_solution.modified_route  # type: JspritRoute

        vehicle = self.get_vehicle_by_id(jsprit_route.vehicle_id)  # type: Vehicle
        vehicle_coord_time = vehicle.get_coord_time(self.env.now)
        vehicle.coord = vehicle_coord_time[0]
        new_route, new_acts_index = self._add_dummy_acts(vehicle.get_route_without_return(), jsprit_route.acts, person)
        if vehicle.get_return_act() is not None:
            new_route.append(vehicle.get_return_act())
        vehicle.set_route(new_route)

        # If it is a very first act for a vehicle, add an act to return to depot
        if vehicle.get_act(-1).type != DrtAct.RETURN:
            vehicle.create_return_act()
        if vehicle.get_act(-1).duration is None:
            print('wow')

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
                time = vehicle_coord_time[1]
            # elif i == vehicle.get_route_len()-1:
            #     coord_start = vehicle.get_act(i-1).coord
            #     time = jsprit_route.acts[-1].end_time
            else:
                coord_start = vehicle.get_act(i-1).coord
                time = jsprit_route.acts[i-1].end_time
            coord_end = vehicle.get_act(i).coord

            trip = self.router.get_drt_route_details(coord_start=coord_start,
                                                     coord_end=coord_end,
                                                     time=time)  # type: Trip
            if len(trip.legs) > 1:
                logging.WARNING('OTP returned multiple legs for DRT trip from {} to {}'.format(coord_start, coord_end))
            act = vehicle.get_act(i)
            act.steps = trip.legs[0].steps
            act.distance = trip.legs[0].distance
            act.duration = trip.legs[0].duration
            # stop_time_step_duration = 0
            if act.type != ActType.RETURN:
                if act.type == ActType.PICK_UP:
                    act.duration += act.person.boarding_time
                    stop_time_step_duration = act.person.boarding_time
                elif act.type == ActType.DROP_OFF or act.type == ActType.DELIVERY:
                    act.duration += act.person.leaving_time
                    stop_time_step_duration = act.person.leaving_time
                else:
                    raise Exception('Unspecified act type')
                act.steps.append(Step(coord=act.steps[-1].end_coord, distance=0, duration=stop_time_step_duration))

        vehicle.act_start_time = vehicle_coord_time[1]
        if not vehicle.rerouted.triggered:
            vehicle.rerouted.succeed()

    def _start_traditional_trip(self, person):
        """TODO: Should save executed trip to a database

        Currently just add values to the environment variable
        """
        self.env.results['total_trips'] += 1
        self.env.results['{}_trips'.format(person.trip.main_mode)] += 1

        for leg in person.trip.legs:
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
