#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service provider processes requests from travelers and manages DRT fleet

@author: ai6644
"""

import logging
from typing import List, Dict, Any
import time
import pandas
import copy
from datetime import timedelta as td

import routing

from desmod.component import Component
from simpy import Event

from const import OtpMode, DrtStatus
from const import maxLat, minLat, maxLon, minLon
from const import CapacityDimensions as CD
from sim_utils import Coord, JspritAct, Step, JspritSolution, JspritRoute, UnassignedTrip, trunc_microseconds
from sim_utils import trunc_time_to_hour
from vehicle import Vehicle, VehicleType
from sim_utils import ActType, DrtAct, Trip, Leg, LegMode
from population import Person, Population
from log_utils import TravellerEventType
from exceptions import *

log = logging.getLogger(__name__)


class ServiceProvider(Component):
    pending_drt_requests = None  # type: Dict[int, JspritSolution]
    vehicles = None  # type: List[Vehicle]
    base_name = 'service'

    def __init__(self, *args, **kwargs):
        super(ServiceProvider, self).__init__(*args, **kwargs)
        self.vehicles = []
        self.vehicle_types = {}
        self._zone_pt_stops = []
        self.pending_drt_requests = {}

        self.unassigned_trips = []

        self._drt_undeliverable = 0
        self._drt_unassigned = 0
        self._drt_no_suitable_pt_stop = 0
        self._drt_overnight = 0
        self._drt_one_leg = 0
        self._drt_too_short_trip = 0
        self._drt_too_late_request = 0
        self._drt_too_long_pt_trip = 0

        self._unplannable_persons = 0
        self._unchoosable_persons = 0
        self._unactivatable_persons = 0

        router = self.env.config.get('service.routing')
        log.info('Setting router: {}'.format(router))
        self.router = getattr(routing, router)(self)

        self._set_vehicle_types()
        self._init_vehicles()
        self._init_zone_pt_stops()

        self.add_connections('population')

    def _init_vehicles(self):
        """Should read and initialise vehicles from the database or something
        """
        for i in range(self.env.config.get('drt.number_vehicles')):
            # if you want to change ID assignment method, you should change get_vehicle_by_id() method too
            attrib = {'id': i}
            coord = Coord(lat=54.832973, lon=11.138917)
            v_type = self.vehicle_types.get(0)
            self.vehicles.append(Vehicle(parent=self, attrib=attrib, return_coord=coord, vehicle_type=v_type))

        # for i in range(5, 10):
        #     # if you want to change ID assignment method, you should change get_vehicle_by_id() method too
        #     attrib = {'id': i}
        #     # coord = Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon))
        #     coord = Coord(lat=55.546315, lon=13.949113)
        #     v_type = self.vehicle_types.get(1)
        #     self.vehicles.append(Vehicle(parent=self, attrib=attrib, return_coord=coord, vehicle_type=v_type))

    def get_vehicle_by_id(self, idx):
        """Currently IDs are assigned in order"""
        return self.vehicles[idx]

    def _set_vehicle_types(self):
        """
        :return: a dictionary with ID as a key and object as its value
        """
        for i in range(1):
            self.vehicle_types[i] = VehicleType(attrib={'id': i})

    def _init_zone_pt_stops(self):
        self._zone_pt_stops = pandas.read_csv(self.env.config.get('drt.PT_stops_file'), sep=',')['stop_id'].to_list()
        try:
            with open(self.env.config.get('drt.PT_extra_stops_file')) as f:
                stops = f.read().strip().split(',')
                self._zone_pt_stops.extend(int(x) for x in stops)
        except FileNotFoundError as e:
            log.warning('************************************************************************')
            log.warning('file {} not found'.format(self.env.config.get('drt.PT_extra_stops_file')))
            log.warning('check \'drt.PT_extra_stops_file\' in the config')
            log.warning('************************************************************************')

    def is_stop_in_zone(self, stop_id):
        return stop_id in self._zone_pt_stops

    def request(self, person: Person):
        log.info('Request came at {0} from {1}'.format(self.env.now, person))

        start = time.time()
        traditional_alternatives = self._traditional_request(person)
        log.debug('Web requests took {}'.format(time.time() - start))
        if len(traditional_alternatives) == 0:
            raise OTPUnreachable('No traditional alternatives received')

        traditional_alternatives2 = []
        for trip in traditional_alternatives:
            if self._pt_trip_can_be_accepted(trip, person):
                traditional_alternatives2.append(trip)

        # if not any([True for trip in traditional_alternatives2 if trip.main_mode in [OtpMode.TRANSIT]]):
        start = time.time()
        try:
            drt_alternatives, status = self._drt_request(person)
            person.set_drt_status(status)
        except OTPNoPath as e:
            log.warning('{}\n{}'.format(e.msg, e.context))
            log.warning('Person {} will not consider DRT'.format(person))
            drt_alternatives = []

        log.debug('DRT request took {}'.format(time.time() - start))
        alternatives = traditional_alternatives2 + drt_alternatives
        # else:
        #     alternatives = traditional_alternatives2

        if len(alternatives) == 0:
            log.warning('no alternatives received by {}'.format(person.scope))
        return alternatives

    def _pt_trip_can_be_accepted(self, trip, person):
        """TODO: use local time windows instead of person's.
        Checks if a trip fits into a current day and if it fits into time window.
        """
        if person.is_trip_within_tw(trip) and self._trip_in_current_day(trip) and \
                self._trip_in_max_duration(trip, person):
            return True
        else:
            return False

    def _trip_can_be_accepted(self, trip, person):
        """TODO: use local time windows instead of person's.
        Checks if a trip fits into a current day and if it fits into time window.
        """
        if person.is_trip_within_tw(trip) and self._trip_in_current_day(trip) and \
                self._trip_in_max_duration(trip, person):
            return True
        else:
            return False

    @staticmethod
    def _trip_in_max_duration(trip, person):
        return trip.duration < person.get_max_trip_duration(person.get_direct_trip_duration())

    @staticmethod
    def _trip_in_time_windows(trip, person):
        """TODO: check only start/end of the trip on being within time-window"""
        return person.is_trip_within_tw(trip)
        # if trip.legs[0].start_time < person.get_trip_tw_left() or trip.legs[-1].end_time > person.get_trip_tw_right():
        #     return False
        # else:
        #     return True

    def _trip_in_current_day(self, trip):
        if trip.legs[0].start_time < self.env.now or trip.legs[-1].end_time > self.env.config['sim.duration_sec']:
            return False
        else:
            return True

    def pt_stop_coord_times_for_drt(self, trip: Trip, drt_is_first_leg=True):
        if drt_is_first_leg:
            return [(leg.start_coord, leg.start_time) for leg in trip.legs
                    if leg.mode in OtpMode.get_pt_modes() and self.is_stop_in_zone(leg.from_stop)]
        else:
            return [(leg.end_coord, leg.end_time) for leg in trip.legs
                    if leg.mode in OtpMode.get_pt_modes() and self.is_stop_in_zone(leg.to_stop)]

    def _traditional_request(self, person):
        """
        Tries to route traditional alternatives with the modes defined by config.get('service.modes')
        :param person:
        :return: trip alternatives
        """
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
                attributes = self._prepare_banned_attributes_otp()
                attributes.update(person.get_routing_parameters())
                traditional_alternatives += self.router.otp_request(person.curr_activity.coord,
                                                                    person.next_activity.coord,
                                                                    person.get_trip_departure_with_tw_for_otp(),
                                                                    mode,
                                                                    attributes)
            except OTPNoPath as e:
                log.warning('{}\n{}'.format(e.msg, e.context))
                continue

        if len(traditional_alternatives) == 0:
            raise OTPUnreachable(msg="Person's {} origin or destination are unreachable".format(person.id),
                                 context=str(person))
        else:
            return traditional_alternatives

    def _drt_request(self, person: Person):
        """Calculates a list of DRT possible trips.
        If a person moves within service zones, the whole trip is done wit drt as one leg.

        If a person moves in or out of service zones, drt will perform a first or last mile. DRT leg in this case will
        replace a walking leg, where walk speed is set to the car speed.

        Returns a list of drt trips and a status for logging
        """

        if person.get_direct_trip_distance() < self.env.config.get('drt.min_distance'):
            log.info('Person {} has trip length of {}. Ignoring DRT'.format(person.id, person.get_direct_trip_distance()))
            self._drt_too_short_trip += 1
            return [], DrtStatus.too_short_drt_leg

        if person.is_local_trip():
            drt_trips, status = self._drt_local(person)
        else:
            drt_trips1, status1 = self._drt_transit(person)
            drt_trips2, status2 = self._drt_transit(person, ban_rail=True)
            drt_trips = drt_trips1 + drt_trips2
            if DrtStatus.routed in [status1, status2]:
                status = DrtStatus.routed
            else:
                # TODO: status need to be reworked or removed
                status = DrtStatus.unassigned

        return drt_trips, status

    def _drt_local(self, person: Person):
        drt_trip = Trip()  # type: Trip
        drt_trip.set_empty_trip(OtpMode.DRT, person.curr_activity.coord, person.next_activity.coord)
        drt_leg = Leg(mode=OtpMode.DRT,
                      start_coord=person.curr_activity.coord,
                      end_coord=person.next_activity.coord)
        person.drt_leg = drt_leg.deepcopy()
        person.set_drt_tw(person.get_direct_trip_duration(), single_leg=True)

        try:
            self._drt_request_routine(person)
        except DrtUndeliverable as e:
            log.warning(e.msg)
            self._drt_undeliverable += 1
            return [], DrtStatus.undeliverable
        except DrtUnassigned as e:
            log.warning(e.msg)
            self._drt_unassigned += 1
            return [], DrtStatus.unassigned

        drt_trip.legs[0] = person.drt_leg.deepcopy()
        drt_trip.duration = drt_trip.legs[0].duration
        return [drt_trip], DrtStatus.routed

    def _drt_transit_find_max_pre_transit(self, person, ban_rail: bool = False):
        """Finds preTransitTimes (maximum duration of CAR in kiss and ride)
        so that transfer stops are within service zone

        Gradually decreases maxPreTransitTimes until no trips can be found at all.
        Saves all the valid maxPreTransitTimes.
        """
        mode = self._drt_transit_get_mode(person)
        params = self._prepare_banned_attributes_otp(ban_rail=ban_rail)
        params.update(person.get_routing_parameters())
        max_pre_transit_times = []
        cur_max_pre_transit = self.env.config.get('drt.maxPreTransitTime')
        params.update({'maxPreTransitTime': cur_max_pre_transit})
        request_time = person.get_trip_departure_with_tw_for_otp()
        while True:
            try:
                pt_alt_temp = self.router.otp_request(person.curr_activity.coord,
                                                      person.next_activity.coord,
                                                      request_time,
                                                      mode,
                                                      params
                                                      )
            except OTPNoPath:
                # it will break the loop when no trips can be found with small maxPreTransitTime
                break

            new_max_pre_transit = cur_max_pre_transit
            append = False
            for alt in pt_alt_temp:
                if len(alt.legs) == 1:
                    continue
                if len([True for leg in alt.legs if leg.mode in LegMode.get_pt_modes()]) == 0:
                    continue

                if person.is_in_trip():
                    new_max_pre_transit = min(int(alt.legs[-1].duration), new_max_pre_transit)
                    if alt.legs[-1].duration > cur_max_pre_transit:
                        break
                    if not self.is_stop_in_zone(self._get_bus_leg_for_in_trip(alt).to_stop):
                        continue
                else:
                    new_max_pre_transit = min(int(alt.legs[0].duration), new_max_pre_transit)
                    if alt.legs[0].duration > cur_max_pre_transit:
                        break
                    if not self.is_stop_in_zone(self._get_bus_leg_for_out_trip(alt).from_stop):
                        continue
                append = True
                break
            if append:
                max_pre_transit_times.append(cur_max_pre_transit)
            cur_max_pre_transit = new_max_pre_transit - 60
            if cur_max_pre_transit < 0:
                break
            params.update({'maxPreTransitTime': cur_max_pre_transit})

        return max_pre_transit_times

    @staticmethod
    def _drt_transit_get_waiting_time(alt):
        if alt.legs[0].mode == OtpMode.WALK:
            return alt.legs[1].start_time - alt.legs[0].end_time
        else:
            return 0

    def _prepare_banned_attributes_otp(self, ban_rail: bool = False):
        params = copy.copy(self.env.config.get('otp.always_banned_trips'))
        params['bannedTrips'] = params.get('bannedTrips').strip(',') + ',' + \
                                self.env.config.get('otp.banned_trips').get('bannedTrips')
        if ban_rail:
            params['bannedTrips'] = params.get('bannedTrips').strip(',') + ',' + \
                                    self.env.config.get('otp.banned_rail').get('bannedTrips')
        params.update(self.env.config.get('otp.banned_stops'))
        return params

    def _drt_transit_find_pt_alternatives(self, person, max_pre_transit_times, ban_rail: bool = False):
        """Finds kiss and ride alternatives that satisfy maximum duration and time windows restriction,
        and transfer zone is withing DRT service zone

        Gradually reduces or increases 'arrive by' or 'depart at' parameters to scan through all the time window.
        """
        params = self._prepare_banned_attributes_otp(ban_rail)
        params.update(person.get_routing_parameters())
        pt_alternatives = []
        mode = self._drt_transit_get_mode(person)
        for max_pre_transit in max_pre_transit_times:
            params.update({'maxPreTransitTime': max_pre_transit})
            alt_tw_left = self.env.now
            alt_tw_right = self.env.config.get('sim.duration_sec')
            request_time = person.get_trip_departure_with_tw_for_otp()
            while True:
                try:
                    pt_alt_temp = self.router.otp_request(person.curr_activity.coord,
                                                          person.next_activity.coord,
                                                          request_time,
                                                          mode,
                                                          params
                                                          )
                except OTPNoPath:
                    break

                # OTP makes walk+wait+bus+drt routes. To find later departures,
                # we need to force it to skip the whole waiting 'leg'
                wait_time = 1
                for alt in pt_alt_temp:
                    alt_tw_left = max(alt_tw_left, alt.legs[0].start_time)
                    alt_tw_right = min(alt_tw_right, alt.legs[-1].end_time)
                    if len(alt.legs) == 1:
                        continue
                    if len([True for leg in alt.legs if leg.mode in LegMode.get_pt_modes()]) == 0:
                        continue

                    if person.is_in_trip():
                        wait_time = max(self._drt_transit_get_waiting_time(alt), wait_time)
                    if self._trip_can_be_accepted(alt, person):
                        if person.is_in_trip():
                            if not self.is_stop_in_zone(self._get_bus_leg_for_in_trip(alt).to_stop):
                                continue
                        else:
                            if not self.is_stop_in_zone(self._get_bus_leg_for_out_trip(alt).from_stop):
                                continue
                        pt_alternatives.append(alt)
                # sometimes CAR-WALK trips are generated.
                # The cycle above then shifts it by one second within the whole time window
                if min([len(alt.legs) for alt in pt_alt_temp]) < 3:
                    break

                # this loop can go to infinity if OPT returns trips on the previous day
                if all(not self._trip_in_current_day(trip) for trip in pt_alt_temp):
                    break

                if person.is_arrive_by():
                    alt_tw_right -= 1
                    params.update({'time': trunc_microseconds(str(td(seconds=alt_tw_right)))})
                    if person.get_trip_tw_left() + person.get_max_trip_duration(person.get_direct_trip_duration()) > \
                            alt_tw_right:
                        break
                else:
                    alt_tw_left += wait_time
                    params.update({'time': trunc_microseconds(str(td(seconds=alt_tw_left)))})
                    if alt_tw_left + person.get_max_trip_duration(person.get_direct_trip_duration()) > \
                            person.get_trip_tw_right():
                        break

        return pt_alternatives

    @staticmethod
    def _drt_transit_get_mode(person):
        if person.is_in_trip():
            mode = OtpMode.RIDE_KISS
        elif person.is_out_trip():
            mode = OtpMode.KISS_RIDE
        else:
            raise Exception("Cannot determine if DRT+TRANSIT trip is going in or out service zone \n"
                            "Check person's Origin-Destination \n"
                            "{}".format(person))
        return mode

    def _drt_transit(self, person: Person, ban_rail: bool = False):

        drt_trips = []

        # TODO: currently taking a first trip that fits person's request
        # TODO: check all feasible trips and form alternatives for each
        status_log = {
            DrtStatus.no_stop: 0,
            DrtStatus.undeliverable: 0,
            DrtStatus.unassigned: 0,
            DrtStatus.too_short_drt_leg: 0,
            DrtStatus.overnight_trip: 0,
            DrtStatus.one_leg: 0,
            DrtStatus.too_late_request: 0,
            DrtStatus.too_long_pt_trip: 0}

        start = time.time()
        max_pre_transit_times = self._drt_transit_find_max_pre_transit(person, ban_rail)
        log.debug('len max pre transit times {}'.format(len(max_pre_transit_times)))
        log.debug('took: {}'.format(time.time() - start))

        start = time.time()
        pt_alternatives = self._drt_transit_find_pt_alternatives(person, max_pre_transit_times, ban_rail)
        log.debug('len pt_alternatives {}'.format(len(pt_alternatives)))
        log.debug('took: {}'.format(time.time() - start))

        selected = []
        if len(pt_alternatives) > 10:
            tmp = [t for t in pt_alternatives]
            # fastest
            selected.append(sorted(tmp, key=lambda trip: trip.duration).pop())
            if person.is_arrive_by():
                # latest arrival
                selected.append(sorted(tmp, key=lambda trip: trip.legs[-1].end_time, reverse=True).pop())
                # earliest arrival
                selected.append(sorted(tmp, key=lambda trip: trip.legs[-1].end_time).pop())
                # in the middle
                selected.append(sorted(tmp, key=lambda trip: trip.legs[-1].end_time)[int(len(tmp) / 2)])
            else:
                # earliest start time
                selected.append(sorted(tmp, key=lambda trip: trip.legs[0].start_time).pop())
                # latest start time
                selected.append(sorted(tmp, key=lambda trip: trip.legs[0].start_time, reverse=True).pop())
                # in the middle
                selected.append(sorted(tmp, key=lambda trip: trip.legs[0].start_time)[int(len(tmp) / 2)])

            selected.extend(self.env.rand.sample(tmp, 6))

            pt_alternatives = selected

        for alt in pt_alternatives:
            if alt.legs[0].start_time < 0 or alt.legs[-1].end_time > self.env.config.get('sim.duration_sec'):
                status_log[DrtStatus.overnight_trip] += 1
                continue

            if alt.duration > person.get_max_trip_duration(person.get_direct_trip_duration()):
                status_log[DrtStatus.too_long_pt_trip] += 1
                continue

            drt_trip = alt
            drt_trip.main_mode = OtpMode.DRT_TRANSIT

            # if a PT trip has only one leg or if the last leg is PT - we do not need DRT
            if len(drt_trip.legs) < 2:
                status_log[DrtStatus.one_leg] += 1
                continue

            if len([True for l in alt.legs if l.mode in OtpMode.get_pt_modes()]) == 0:
                status_log[DrtStatus.one_leg] += 1
                continue

            # **************************************************
            # **********         Trip in           *************
            # **************************************************

            # When we have an incoming our outgoing trip, we should calculate a PT trip with a high walking speed
            # to replace a WALK leg with a DRT leg
            if person.is_in_trip():
                # TODO: we can "consume" PT legs by DRT as long as they are inside service zone
                # we can also make DRT alternatives for all of the trip alternatives

                # TODO: take the last possible stop as an alternative
                # That would be the scenario to a central station (most likely)
                try:

                    drt_leg = self._get_leg_for_in_trip(drt_trip, person)
                    available_drt_time = person.get_max_trip_duration(person.get_direct_trip_duration()) - \
                                            (alt.duration - (
                                                drt_leg.duration + person.boarding_time + person.leaving_time))
                    person.set_drt_tw(drt_leg.duration, last_leg=True, drt_leg=drt_leg,
                                      available_time=available_drt_time)
                    pt_car_leg_index = -1
                except PTStopServiceOutsideZone:
                    status_log[DrtStatus.no_stop] += 1
                    continue

            # **************************************************
            # **********          Trip out         *************
            # **************************************************
            elif person.is_out_trip():
                try:
                    drt_leg = self._get_leg_for_out_trip(drt_trip, person)
                    available_drt_time = person.get_max_trip_duration(person.get_direct_trip_duration()) - \
                                         (alt.duration - drt_leg.duration)
                    person.set_drt_tw(drt_leg.duration, first_leg=True, drt_leg=drt_leg,
                                      available_time=available_drt_time)
                    pt_car_leg_index = 0
                except PTStopServiceOutsideZone:
                    status_log[DrtStatus.no_stop] += 1
                    continue

            else:
                log.error('Could not determine where person is going. {}'.format(person.id))
                # TODO: need to use different status here. Undeliverable is when jsprit cannot fit a person
                # in this case it is an input error
                # TODO: check if this ever happens
                self._drt_undeliverable += 1
                return [], DrtStatus.undeliverable

            # **************************************************
            # ********* Common part for in and out *************
            # **************************************************
            if drt_leg.distance < self.env.config.get('drt.min_distance'):
                status_log[DrtStatus.too_short_drt_leg] += 1
                continue

            if person.get_drt_tw_start_right() < self.env.now or \
                    person.get_drt_tw_start_left() > self.env.config.get('sim.duration_sec'):
                status_log[DrtStatus.too_late_request] += 1
                continue

            person.drt_leg = drt_leg.deepcopy()
            try:
                self._drt_request_routine(person)
            except DrtUnassigned:
                status_log[DrtStatus.unassigned] += 1
                continue
            except DrtUndeliverable:
                status_log[DrtStatus.undeliverable] += 1
                continue

            drt_trip.legs[pt_car_leg_index] = person.drt_leg.deepcopy()
            # drt_trip.legs[pt_car_leg_index].start_coord = person.drt_leg.start_coord
            # drt_trip.legs[pt_car_leg_index].end_coord = person.drt_leg.start_coord
            drt_trip.distance = 0
            drt_trip.duration = drt_trip.legs[-1].end_time - drt_trip.legs[0].start_time

            drt_trips += [drt_trip]

            # just take one DRT trip.
            # and do not add more until person.DRT_leg is used.
            break

        status = DrtStatus.routed
        if len(drt_trips) == 0:
            log.warning('Person {} could not be routed by DRT. Undeliverable: {}, Unassigned {},'
                        'PT stops outside: {}, too close PT stops {}, overnight trips {}, one leg journey received {}'
                        .format(person.id,
                                status_log[DrtStatus.undeliverable], status_log[DrtStatus.unassigned],
                                status_log[DrtStatus.no_stop], status_log[DrtStatus.too_short_drt_leg],
                                status_log[DrtStatus.overnight_trip], status_log[DrtStatus.one_leg]
                                ))
            if status_log[DrtStatus.undeliverable] != 0:
                self._drt_undeliverable += 1
                status = DrtStatus.undeliverable
            elif status_log[DrtStatus.unassigned] != 0:
                self._drt_unassigned += 1
                status = DrtStatus.unassigned
            elif status_log[DrtStatus.no_stop] != 0 or status_log[DrtStatus.too_short_drt_leg] != 0:
                self._drt_no_suitable_pt_stop += 1
                status = DrtStatus.no_stop
            elif status_log[DrtStatus.too_long_pt_trip] != 0:
                self._drt_too_long_pt_trip += 1
                status = DrtStatus.too_long_pt_trip
            elif status_log[DrtStatus.overnight_trip] != 0:
                self._drt_overnight += 1
                status = DrtStatus.overnight_trip
            elif status_log[DrtStatus.one_leg] != 0:
                self._drt_one_leg += 1
                status = DrtStatus.one_leg
            elif status_log[DrtStatus.too_late_request] != 0:
                self._drt_too_late_request += 1
                status = DrtStatus.too_late_request
            # else:
            #     log.debug('{} could not be delivered by DRT_TRANSIT, but there are zero errors as well.'
            #               .format(person, ))

        return drt_trips, status

    @staticmethod
    def _get_bus_leg_for_in_trip(drt_trip):
        return [leg for leg in drt_trip.legs if leg.mode in LegMode.get_pt_modes()][-1]
        # if drt_trip.legs[-2].mode == OtpMode.WALK and len(drt_trip.legs) > 3:
        #     leg_bus = drt_trip.legs[-3]
        # else:
        #     leg_bus = drt_trip.legs[-2]
        # return leg_bus

    def _get_leg_for_in_trip(self, drt_trip, person):
        """Extract a walk leg, that should be replaced by DRT, from a PT trip"""
        leg_bus = self._get_bus_leg_for_in_trip(drt_trip)
        if self.is_stop_in_zone(leg_bus.to_stop):
            drt_leg = Leg(mode=OtpMode.DRT,
                          start_coord=drt_trip.legs[-1].start_coord,
                          end_coord=drt_trip.legs[-1].end_coord,
                          start_time=drt_trip.legs[-1].start_time,
                          end_time=drt_trip.legs[-1].end_time,
                          distance=drt_trip.legs[-1].distance,
                          duration=drt_trip.legs[-1].duration)
            return drt_leg
        else:
            # log.info('Person {} has incoming trip, but bus stop {} is not in the zone'
            #          .format(person.id, drt_trip.legs[-2].to_stop))
            raise PTStopServiceOutsideZone('Person {} has incoming trip, but bus stop {} is not in the zone'
                                           .format(person.id, drt_trip.legs[-2].to_stop))

    @staticmethod
    def _get_bus_leg_for_out_trip(drt_trip):
        return [leg for leg in drt_trip.legs if leg.mode in LegMode.get_pt_modes()][0]
        # if drt_trip.legs[1].mode == OtpMode.WALK and len(drt_trip.legs) > 3:
        #     leg_bus = drt_trip.legs[2]
        # else:
        #     leg_bus = drt_trip.legs[1]
        # return leg_bus

    def _get_leg_for_out_trip(self, drt_trip, person):
        leg_bus = self._get_bus_leg_for_out_trip(drt_trip)
        if self.is_stop_in_zone(leg_bus.from_stop):
            drt_leg = Leg(mode=OtpMode.DRT,
                          start_coord=drt_trip.legs[0].start_coord,
                          end_coord=drt_trip.legs[0].end_coord,
                          start_time=drt_trip.legs[0].start_time,
                          end_time=drt_trip.legs[0].end_time,
                          distance=drt_trip.legs[0].distance,
                          duration=drt_trip.legs[0].duration)
            return drt_leg
        else:
            raise PTStopServiceOutsideZone('Person {} has outgoing trip, but bus stop is not in the zone'
                                           .format(person.id, drt_trip.legs[1].from_stop))

    def _drt_request_routine(self, person: Person):
        """Prepares coordinate lists for routing
        NOTE: peron.drt_leg will be updated

        Return : drt leg from router.drt_request
        """

        vehicle_coords_times = self._get_current_vehicle_positions()
        vehicle_return_coords = [vehicle.return_coord for vehicle in self.vehicles]

        # get positions of scheduled requests
        # person.leg.start_coord and .end_coord have that, so get the persons
        persons = self.get_scheduled_travelers()
        service_persons = self.get_onboard_travelers()
        waiting_persons = list(set(persons) - set(service_persons))
        shipment_persons = waiting_persons
        shipment_persons += [person]

        # remove persons that are in the process of boarding or leaving a vehicle

        self.router.drt_request(person, vehicle_coords_times, vehicle_return_coords,
                                shipment_persons, service_persons)

    def standalone_osrm_request(self, person):
        return self.router.osrm_route_request(person.curr_activity.coord, person.next_activity.coord)

    def fastest_pt_trip_within_hour_otp_request(self, person):
        """returns the fastest PT alternative with the same attribute as for normal OTP request"""

        mode = 'TRANSIT,WALK'
        traditional_alternatives = []

        attributes = copy.copy(self.env.config.get('otp.always_banned_trips'))
        attributes.update(person.get_routing_parameters())

        try:
            traditional_alternatives += self.router.otp_request(person.curr_activity.coord,
                                                                person.next_activity.coord,
                                                                # this is the important line. Remove minutes.
                                                                # trunc_time_to_hour(person.next_activity.start_time),
                                                                person.get_trip_departure_with_tw_for_otp(),
                                                                mode,
                                                                attributes)
        except OTPNoPath as e:
            log.warning('{}\n{}'.format(e.msg, e.context))

        if len(traditional_alternatives) == 0:
            raise OTPUnreachable(msg="Person's {} origin or destination are unreachable".format(person.id),
                                 context=str(person))

        traditional_alternatives = [alt for alt in traditional_alternatives if alt.main_mode not in ('CAR', 'WALK')]
        traditional_alternatives = [trip for trip in traditional_alternatives
                                    if person.is_trip_within_default_tw(trip) and self._trip_in_current_day(trip)]
        if len(traditional_alternatives) == 0:
            return None
        return min(traditional_alternatives, key=lambda x: x.duration)

    def _get_current_vehicle_positions(self):
        coords_times = []
        for vehicle in self.vehicles:
            coords_times.append(vehicle.get_current_coord_time())
        return coords_times

    def start_trip(self, person: Person):
        if person.planned_trip.main_mode == OtpMode.DRT:
            self._start_drt_trip(person)
        elif person.planned_trip.main_mode == OtpMode.DRT_TRANSIT:
            self._start_drt_trip(person)
        else:
            self._start_traditional_trip(person)

    def get_route_details(self, vehicle):
        """Requests steps for the next act from OSRM.
        """
        if vehicle.get_route_len() == 0:
            raise Exception('Cannot request DRT trip for vehicle with no route')

        act = vehicle.get_act(0)  # type: DrtAct

        # no need to find route when there is no movement
        if act.type in [DrtAct.PICK_UP, DrtAct.DROP_OFF, DrtAct.DELIVERY, DrtAct.WAIT]:
            return

        try:
            trip = self.router.get_drt_route_details(coord_start=act.start_coord,
                                                     coord_end=act.end_coord,
                                                     at_time=act.start_time)  # type: Trip
        except OTPTrivialPath as e:
            log.warning('Trivial path found for DRT routing. That can happen.\n{}\n{}'.format(e.msg, e.context))
            trip = Trip()
            trip.set_empty_trip(OtpMode.DRT, act.start_coord, act.end_coord)
        except OTPNoPath as e:
            log.error(e.msg + str(e.context))
            log.error('Trying to create a trip with a single leg and a single step.')
            trip = Trip()
            trip.duration = act.duration
            trip.distance = act.distance
            trip.main_mode = OtpMode.DRT
            trip.legs = [Leg(mode=OtpMode.DRT,
                             start_coord=act.start_coord,
                             end_coord=act.end_coord,
                             start_time=act.start_time,
                             end_time=act.end_time,
                             distance=act.distance,
                             duration=act.duration,
                             steps=[Step(start_coord=act.start_coord,
                                         end_coord=act.end_coord,
                                         distance=act.distance,
                                         duration=act.duration)])]

        if len(trip.legs) > 1:
            log.error('OTP returned multiple legs for DRT trip from {} to {}.'.format(act.start_coord, act.end_coord))
            raise Exception()

        if act.steps is not None:
            act.distance = trip.distance + act.steps[0].distance
            act.duration = trip.duration + act.steps[0].duration
            act.start_time -= act.steps[0].duration
            act.start_coord = act.steps[0].start_coord
            act.steps += trip.legs[0].steps
        else:
            act.distance = trip.distance
            act.duration = trip.duration
            act.steps = trip.legs[0].steps
            if act.end_time is None:
                act.end_time = act.start_time + act.duration

        extra_time = act.duration - (act.end_time - act.start_time)
        if extra_time != 0:
            if abs(extra_time) > 1:
                log.error('Act\'s end time does not correspond to its planned duration. '
                          'Vehicle\'s {} route need to be moved by {} seconds (ratio {}).'
                          .format(extra_time, vehicle.id, act.duration / (act.end_time - act.start_time)))

            for a in vehicle.get_route_with_return():
                a.start_time += extra_time
                a.end_time += extra_time
            # do not change start time of current act
            vehicle.get_act(0).start_time -= extra_time

    def _jsprit_to_drt(self, vehicle, jsprit_route: JspritRoute):
        """Translates jsprit output into vehicle route.
        Also merges current act of the vehicle into the route.
        """
        drt_acts = []  # type: List[DrtAct]

        first_act = JspritAct(type_=DrtAct.DRIVE, person_id=None, end_time=jsprit_route.start_time)
        last_act = JspritAct(type_=DrtAct.RETURN, person_id=None, end_time=None, arrival_time=jsprit_route.end_time)

        for i, (pjact, njact) in enumerate(zip([first_act] + jsprit_route.acts, jsprit_route.acts + [last_act])):
            if i == len(jsprit_route.acts):
                person = None
            else:
                person = self.population.get_person(njact.person_id)  # type: Person
                # drt_leg = person.planned_trip.legs[person.planned_trip.get_leg_modes().index(OtpMode.DRT)]
                drt_leg = person.drt_leg

            # *************************************************************
            # **********         Moving to an activity           **********
            # *************************************************************
            if i == 0:
                coord_start = vehicle.get_current_coord_time()[0]
            else:
                coord_start = drt_acts[-1].end_coord

            if njact.type == ActType.PICK_UP:
                coord_end = drt_leg.start_coord
            elif njact.type in [ActType.DROP_OFF, ActType.DELIVERY]:
                coord_end = drt_leg.end_coord
            elif njact.type == ActType.RETURN:
                coord_end = vehicle.return_coord
            else:
                raise Exception('Unexpected act type {}'.format(njact.type))

            move_act = DrtAct(type_=DrtAct.DRIVE, person=None,
                              duration=njact.arrival_time - pjact.end_time,
                              end_coord=coord_end, start_coord=coord_start,
                              start_time=pjact.end_time, end_time=njact.arrival_time)

            # *************************************************************
            # ******   Merge current act of vehicle into new route   ******
            # *************************************************************

            # Vehicle is likely to be doing some step, but we cannot reroute it at any given point,
            # only after it finishes its current step
            if i == 0 and self.env.now != jsprit_route.start_time and vehicle.get_route_len() > 0:
                curr_v_act = vehicle.get_act(0)  # type: DrtAct
                # if a vehicle is picking up or delivering a person, just save this act in a new route
                if curr_v_act.type in [DrtAct.PICK_UP, DrtAct.DROP_OFF, DrtAct.DELIVERY]:
                    drt_acts.append(curr_v_act)
                # if vehicle is on the move, append its current step to the plan
                elif curr_v_act.type in [DrtAct.DRIVE, DrtAct.RETURN]:
                    curr_v_step = vehicle.get_current_step()
                    # passed_steps = vehicle.get_passed_steps()
                    if curr_v_step is not None:
                        move_act.steps = [curr_v_step]
                        # Current step of a vehicle is appended here to be processed by the replanner

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
                            start_time=njact.end_time - duration, end_time=njact.end_time)
            action.steps = [
                Step(start_coord=action.start_coord, end_coord=action.end_coord, distance=0, duration=duration)]

            # *************************************************************
            # **********        Waiting before an activity       **********
            # *************************************************************
            if action.duration != (njact.end_time - njact.arrival_time):
                wait_act = DrtAct(type_=ActType.WAIT, person=person,
                                  duration=njact.end_time - njact.arrival_time - duration,
                                  end_coord=drt_acts[-1].end_coord, start_coord=drt_acts[-1].end_coord,
                                  distance=0,
                                  start_time=njact.arrival_time, end_time=njact.end_time - duration)
                wait_act.steps = [Step(start_coord=wait_act.start_coord, end_coord=wait_act.end_coord, distance=0,
                                       duration=wait_act.duration)]
                drt_acts.append(wait_act)

            drt_acts.append(action)

        if drt_acts[-1].type == DrtAct.DRIVE:
            drt_acts[-1].type = DrtAct.RETURN
        return drt_acts

    def _start_drt_trip(self, person):
        jsprit_solution = self.pending_drt_requests.pop(person.id)
        if jsprit_solution is None:
            raise Exception('Trying to rerouted drt vehicle for {}, but no jsprit solution found for this'
                            .format(person))
        jsprit_route = jsprit_solution.modified_route  # type: JspritRoute

        vehicle = self.get_vehicle_by_id(jsprit_route.vehicle_id)  # type: Vehicle

        new_route = self._jsprit_to_drt(vehicle=vehicle, jsprit_route=jsprit_route)
        vehicle.update_partially_executed_trips()
        person.update_planned_drt_trip(new_route)
        vehicle.set_route(new_route)

        # If several request come at the same time, the same event will be triggered several times
        # which is an exception in simpy
        if not vehicle.rerouted.triggered:
            vehicle.rerouted.succeed()

    def _start_traditional_trip(self, person: Person):
        """Does nothing"""
        pass

    def execute_trip(self, person: Person):
        person.init_actual_trip()
        if person.planned_trip.main_mode == OtpMode.DRT:
            person.init_executed_drt_leg()
            yield person.drt_executed
            person.delivered.succeed()
        elif person.planned_trip.main_mode == OtpMode.DRT_TRANSIT:
            if person.planned_trip.legs[0].mode == OtpMode.DRT:
                # if DRT is first leg - wait for it to be executed and teleport a person to its destination after PT
                person.init_executed_drt_leg()
                person.update_travel_log(TravellerEventType.LEG_STARTED, person.planned_trip.legs[0].deepcopy())
                yield person.drt_executed
                person.update_travel_log(TravellerEventType.LEG_FINISHED, person.actual_trip.legs[0].deepcopy())
                for leg in person.planned_trip.legs[1:]:
                    person.update_travel_log(TravellerEventType.LEG_STARTED, leg)
                    timeout = person.planned_trip.legs[-1].end_time - self.env.now
                    if timeout < 0:
                        log.error('{}: PT leg of DRT_TRANSIT should have already ended by now, setting it to zero\n'
                                  'Should have started {} and ended {}.\n'
                                  'Planned {}\nActual{}'
                                  .format(self.env.now, person.planned_trip.legs[1].start_time,
                                          person.planned_trip.legs[-1].end_time,
                                          person.planned_trip, person.actual_trip))
                        timeout = 0
                    yield self.env.timeout(timeout)
                    person.update_travel_log(TravellerEventType.LEG_FINISHED, leg)
                person.append_pt_legs_to_actual_trip([leg.deepcopy() for leg in person.planned_trip.legs[1:]])
                person.delivered.succeed()
            else:
                # if DRT is a last leg, just assume that PT part is executed correctly
                person.append_pt_legs_to_actual_trip([leg.deepcopy() for leg in person.planned_trip.legs[:-1]])
                person.init_executed_drt_leg()
                yield person.drt_executed
                person.delivered.succeed()
        else:
            yield self.env.timeout(person.planned_trip.duration)
            person.set_actual_trip(person.planned_trip)
            person.delivered.succeed()

        self.env.results['total_trips'] += 1
        self.env.results['{}_trips'.format(person.planned_trip.main_mode)] += 1
        for leg in person.planned_trip.legs:
            self.env.results['{}_legs'.format(leg.mode)] += 1

    def get_scheduled_travelers(self):
        """Returns a list of persons who are scheduled for DRT transportation.
        This list includes onboard persons as well.

        NOTE: persons currently leaving a vehicle are excluded from this list. So that jsprit would not serve them twice.
        """
        persons = []
        for vehicle in self.vehicles:
            for i, act in enumerate(vehicle.get_route_without_return()):  # type: DrtAct
                if i == 0 and act.type in [DrtAct.DROP_OFF, DrtAct.DELIVERY]:
                    continue
                else:
                    persons.append(act.person)
        return [a for a in set(persons) if a is not None]

    def get_onboard_travelers(self):
        """Returns a list of persons that are currently on a vehicle.

        NOTE: persons currently leaving a vehicle are excluded from this list.
        So that jsprit would not drop them off twice.

        NOTE: persons boarding a vehicle are also added to this list, so that jsprit would treat them as DELIVERY
        """
        persons = []
        for vehicle in self.vehicles:
            if vehicle.route_not_empty():
                if vehicle.get_act(0).type in [DrtAct.DROP_OFF, DrtAct.DELIVERY]:
                    persons += [person for person in vehicle.passengers if person != vehicle.get_act(0).person]
                else:
                    persons += vehicle.passengers

                if vehicle.get_act(0).type == DrtAct.PICK_UP:
                    persons += [vehicle.get_act(0).person]

        return persons

    def log_unassigned_trip(self, person):
        self.unassigned_trips.append(UnassignedTrip(person))

    def log_unplannable(self, person):
        self._unplannable_persons += 1

    def log_unchoosable(self, person):
        self._unchoosable_persons += 1

    def log_unactivatable(self, person):
        self._unactivatable_persons += 1

    def log_unreactivatable(self, person):
        self.log_unactivatable(person)

    def get_result(self, result):
        super(ServiceProvider, self).get_result(result)
        # result['no_unassigned_drt_trips'] = len(self.unassigned_trips)
        # result['unassigned_drt_trips'] = self.unassigned_trips

        result['undeliverable_drt'] = self._drt_undeliverable
        result['unassigned_drt_trips'] = self._drt_unassigned
        result['no_suitable_pt_stop'] = self._drt_no_suitable_pt_stop
        result['drt_overnight'] = self._drt_overnight
        result['too_short_direct_trip'] = self._drt_too_short_trip
        result['drt_one_leg'] = self._drt_one_leg
        result['too_late_request'] = self._drt_too_late_request
        result['too_long_pt_trip'] = self._drt_too_long_pt_trip

        result['unplannable_persons'] = self._unplannable_persons
        result['unchoosable_persons'] = self._unchoosable_persons
        result['unactivatable_persons'] = self._unactivatable_persons
