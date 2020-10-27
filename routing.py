#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Dec 30 13:49:45 2018

@author: ai6644
"""
from typing import Optional

import requests
from datetime import timedelta as td
import csv
import os
import subprocess
import time
import json
from shutil import copyfile

from population import *
from const import OtpMode, LegMode
from sim_utils import Trip, Leg, Coord, Step, trunc_microseconds, DrtAct, JspritSolution, otp_time_to_sec
from db_utils import db_conn
from jsprit_utils import jsprit_tdm_interface, jsprit_vrp_interface
from exceptions import *
import population

import logging

log = logging.getLogger(__name__)


# TODO: refactor Default_routing so that it could be usable directly without service
class DefaultRouting(object):
    
    def __init__(self, service):
        self.env = service.env
        self.url = self.env.config.get("service.router_address")
        # TODO: should remove this connection
        self.service = service
        self.coord_to_geoid = {}

    def otp_request(self,
                    from_place,
                    to_place,
                    at_time,
                    mode: str,
                    attributes=None):
        """Performs a web request to OTP and parses the output to a list of Trips
        Tries to repeat request if OTP exception has occured
        """

        try:
            return self._otp_request(from_place, to_place, at_time, mode, attributes)
        except OTPGeneralRouting as e:
            return self._otp_request(from_place, to_place, at_time, mode, attributes)

    def _otp_request(self,
                     from_place,
                     to_place,
                     at_time,
                     mode: str,
                     attributes=None):
        default_attributes = {'fromPlace': str(from_place),
                              'toPlace': str(to_place),
                              'time': trunc_microseconds(str(td(seconds=at_time))),
                              'date': self.env.config.get('date'),
                              'mode': mode,
                              'arriveBy': 'True',
                              'maxWalkDistance': 2000}
        if attributes is not None:
            default_attributes.update(attributes)
        resp = requests.get(self.url, params=default_attributes)
        # payload = Payload(attributes=default_attributes, config=self.env.config)

        # resp = requests.get(self.url, params=payload.get_payload())

        parsed_trips = self.parse_otp_response(resp)

        for trip in parsed_trips:
            trip.set_main_mode(mode)

        return parsed_trips

    @staticmethod
    def step_from_raw(raw_step):
        return Step(start_coord=Coord(lat=raw_step.get('lat'),
                                      lon=raw_step.get('lon')),
                    end_coord=None,
                    distance=raw_step.get('distance'),
                    duration=raw_step.get('duration')
                    )

    def parse_otp_response(self, resp):
        if resp.status_code != requests.codes.ok:
            resp.raise_for_status()

        jresp = resp.json()
        if 'error' in jresp.keys():
            if jresp.get('error').get('id') == 409:
                raise OTPTrivialPath(jresp.get('error').get('msg'), jresp.get('requestParameters'))
            elif jresp.get('error').get('id') == 404:
                raise OTPNoPath(jresp.get('error').get('msg'), jresp.get('requestParameters'))
            else:
                raise OTPGeneralRouting('Unexpected error. Shutting simulation down.', jresp)

        itineraries = jresp.get('plan').get('itineraries')

        trips = []
        for itinerary in itineraries:
            trip = Trip()
            trip.set_duration(itinerary.get('duration'))
            trip.set_distance(sum([leg.get('distance') for leg in itinerary.get('legs')]))
            for raw_leg in itinerary.get('legs'):
                leg = Leg()
                leg.distance = raw_leg.get('distance')
                leg.duration = raw_leg.get('duration')
                raw_from = raw_leg.get('from')
                leg.start_coord = Coord(lat=raw_from.get('lat'),
                                        lon=raw_from.get('lon'))
                raw_to = raw_leg.get('to')
                leg.end_coord = Coord(lat=raw_to.get('lat'),
                                      lon=raw_to.get('lon'))
                leg.mode = raw_leg.get('mode')
                leg.steps = [self.step_from_raw(s) for s in raw_leg.get('steps')]

                leg.start_time = int(raw_leg.get('startTime'))/1000 - self.env.config.get('date.unix_epoch')
                leg.end_time = int(raw_leg.get('endTime'))/1000 - self.env.config.get('date.unix_epoch')

                if leg.mode in OtpMode.get_pt_modes():
                    # OTP has id in the following format: 'SE-st:9022012065015001'
                    # we are not interested in the first part
                    leg.from_stop = int(raw_from.get('stopId').split(':')[1])
                    leg.to_stop = int(raw_to.get('stopId').split(':')[1])
                trip.append_leg(leg)

                trip.main_mode = trip.main_mode_from_legs()
            trips.append(trip)

        return trips

    def osrm_route_request(self, from_place, to_place):
        '''
        Requests and parses a Trip from OSRM between from_place and to_place
        '''

        url_coords = '{}{},{};{},{}' \
            .format(self.env.config.get('service.osrm_route'),
                    from_place.lon, from_place.lat, to_place.lon, to_place.lat)
        url_full = url_coords + '?annotations=true&geometries=geojson&steps=true'
        resp = requests.get(url=url_full)
        return self._parse_osrm_response(resp)

    def _osrm_tdm_request(self, coords):
        url_coords = ';'.join([str(coord.lon) + ',' + str(coord.lat) for coord in coords])
        url_server = self.env.config.get('service.osrm_tdm')
        url_options = 'fallback_speed=9999999999&annotations=duration,distance'
        url_full = '{}{}?{}'.format(url_server, url_coords, url_options)
        resp = requests.get(url=url_full)

        jresp = resp.json()
        if jresp.get('code') != 'Ok':
            log.error(jresp.get('code'))
            log.error(jresp.get('message'))
            resp.raise_for_status()

        return jresp.get('durations'), jresp.get('distances')

    @staticmethod
    def _parse_osrm_response(resp):
        # if resp.status_code != requests.codes.ok:
        #     resp.raise_for_status()

        jresp = resp.json()
        if jresp.get('code') != 'Ok':
            log.error(jresp.get('code'))
            log.error(jresp.get('message'))
            resp.raise_for_status()

        trip = Trip()
        trip.legs = [Leg()]
        trip.legs[0].steps = []

        legs = jresp.get('routes')[0].get('legs')
        for leg in legs:
            steps = leg.get('steps')
            for step in steps:
                new_step = Step(distance=step.get('distance'),
                                duration=step.get('duration'),
                                start_coord=Coord(lon=step.get('geometry').get('coordinates')[0][0],
                                                  lat=step.get('geometry').get('coordinates')[0][1]),
                                end_coord=Coord(lon=step.get('geometry').get('coordinates')[-1][0],
                                                lat=step.get('geometry').get('coordinates')[-1][1]))
                # OSRM makes circles on roundabouts. And makes empty step in the end. Exclude these cases from a route
                if new_step.start_coord != new_step.end_coord:
                    trip.legs[0].steps.append(new_step)
            if len(trip.legs[0].steps) == 0:
                waypoints = jresp.get('waypoints')
                trip.legs[0].steps.append(Step(distance=0,
                                               duration=0,
                                               start_coord=Coord(lon=waypoints[0].get('location')[0],
                                                                 lat=waypoints[0].get('location')[1]),
                                               end_coord=Coord(lon=waypoints[1].get('location')[0],
                                                               lat=waypoints[1].get('location')[1])
                                               )
                                          )
        trip.legs[0].start_coord = trip.legs[0].steps[0].start_coord
        trip.legs[0].end_coord = trip.legs[0].steps[-1].end_coord
        trip.legs[0].duration = sum([step.duration for step in trip.legs[0].steps])
        trip.legs[0].distance = sum([step.distance for step in trip.legs[0].steps])
        trip.legs[0].mode = OtpMode.DRT

        trip.distance = trip.legs[0].distance
        trip.duration = trip.legs[0].duration
        trip.main_mode = OtpMode.CAR
        return trip

    def drt_request(self, person, vehicle_coords_times, return_vehicle_coords,
                    shipment_persons, service_persons):
        """NOTE: person.drt_leg will be updated"""

        # ***********************************************************
        # ************  Calculate time-distance matrix    ***********
        # ***********************************************************
        # get positions of vehicles and update internal vehicle coordinate
        current_vehicle_coords = list(set([ct[0] for ct in vehicle_coords_times]))
        return_vehicle_coords = list(set(return_vehicle_coords))

        # TODO: separate coordinates of onboard(service) and waiting(shipment) travelers
        persons_start_coords = [pers.drt_leg.start_coord for pers in shipment_persons]
        persons_start_coords += [pers.drt_leg.end_coord for pers in service_persons]

        persons_end_coords = [pers.drt_leg.end_coord for pers in shipment_persons + service_persons]

        # jsprit ignores actual coordinates when it uses tdm. we need to assign a unique ID to each coordinate
        self._prepare_geoid(current_vehicle_coords +
                            persons_start_coords + persons_end_coords + return_vehicle_coords)

        start = time.time()
        shipment_start_coords = [pers.drt_leg.start_coord for pers in shipment_persons]
        shipment_end_coords = [pers.drt_leg.end_coord for pers in shipment_persons]
        delivery_end_coord = [pers.drt_leg.end_coord for pers in service_persons]

        # TODO: catch the exceptions for TDM
        self._calculate_time_distance_matrix(current_vehicle_coords, list(set(return_vehicle_coords)),
                                             shipment_start_coords, shipment_end_coords, delivery_end_coord)

        jsprit_vrp_interface.write_vrp(self.env.config.get('jsprit.vrp_file'),
                                       self.service.vehicle_types, self.service.vehicles, vehicle_coords_times,
                                       shipment_persons, service_persons, self.coord_to_geoid)
        log.debug('vrp file calculation takes {}'.format(time.time() - start))

        # ***********************************************************
        # ************            Run jsprit              ***********
        # ***********************************************************
        start = time.time()
        rstate = self.env.rand.getstate()

        jsprit_call = subprocess.run(['java', '-Xmx1g', '-cp', 'jsprit.jar',
                                      'com.graphhopper.jsprit.examples.DRT_test',
                                      '-printSolution', self.env.config.get('drt.visualize_routes'),
                                      '-vrpFile', self.env.config.get('jsprit.vrp_file'),
                                      '-tdmFile', self.env.config.get('jsprit.tdm_file'),
                                      '-outFile', self.env.config.get('jsprit.vrp_solution'),
                                      '-simLog', self.env.config.get('sim.log'),
                                      '-picFolder', self.env.config.get('drt.picture_folder'),
                                      ],
                                     capture_output=True)

        if self.env.rand.getstate() != rstate:
            log.warning('Random state has been changed by jsprit: {} to {}'.format(self.env.rand.getstate(), rstate))
        self.env.rand.setstate(rstate)

        if jsprit_call.returncode != 0:
            file_id = 'vrp.xml' + str(time.time())
            log.error("Jsprit has crashed. Saving input vrp to {}/{}"
                      .format(self.env.config.get('jsprit.debug_folder'), file_id))
            log.error(jsprit_call.stderr.decode("utf-8") .replace('\\n', '\n'))
            copyfile(self.env.config.get('jsprit.vrp_file'), self.env.config.get('jsprit.debug_folder')+'/'+file_id)
        log.debug('jsprit takes {}ms of system time'.format(time.time() - start))

        # ***********************************************************
        # ************       Parse jsprit output          ***********
        # ***********************************************************
        solution = jsprit_vrp_interface.read_vrp_solution(self.env.config.get('jsprit.vrp_solution'))
        # type: JspritSolution

        # ***********************************************************
        # ************         Form a DRT trip            ***********
        # ***********************************************************
        if solution is None:
            raise DrtUndeliverable('jsprit returned no solution. It may be the first and impossible request.'
                                   'Check this.\n'
                                   'The person will ignore DRT mode.')
        if person.id in solution.unassigned:
            file_id = 'vrp_{}_{}.xml'.format(str(time.time()), person.id)
            copyfile(self.env.config.get('jsprit.vrp_file'), self.env.config.get('jsprit.debug_folder')+'/'+file_id)
            log.debug('Person {} cannot be delivered by DRT. Arrive by {}, tw left {}, tw right {}'
                      .format(person.id, person.next_activity.start_time, person.get_drt_tw_left(), person.get_drt_tw_right()))
            raise DrtUnassigned('Person {} cannot be delivered by DRT'.format(person.id))

        # TODO: I assume that only one route is changed, i.e. insertion algorithm is used.
        #  If it is not the case, every jsprit_route should be updated
        modified_route = self._get_person_route(person, solution)
        if modified_route is None:
            log.error('Person {} has likely caused jsprit to crash. That may happen if time-windows as screwd.\n'
                      'Time window from {} to {}'.format(person.id, person.get_drt_tw_left(), person.get_drt_tw_right()))
            # raise DrtUnassigned('Person {} is not listed in any jsprit routes'.format(person.id))
        solution.routes = None
        solution.modified_route = modified_route
        acts = [act for act in solution.modified_route.acts if act.person_id == person.id]
        # jsprit may route vehicles to pick up travelers long before requested start time,
        # thus we calculate actual trip duration based on the end of pickup event

        person.drt_leg.duration = (acts[-1].arrival_time - acts[0].end_time)
        # TODO: calculate distance for all the changed trips (need to call OTP to extract the distance)
        self.service.pending_drt_requests[person.id] = solution

    @staticmethod
    def _get_person_route(person, solution):
        routes = solution.routes
        for route in routes:
            for act in route.acts:
                if act.person_id == person.id:
                    return route
        return None

    def get_drt_route_details(self, coord_start, coord_end, at_time):
        # Gets a direct trip from OSRM
        # TODO: what is a good name for this function?
        return self.osrm_route_request(coord_start, coord_end)

    def _calculate_time_distance_matrix(self, vehicle_coords, return_coords,
                                        shipment_start_coords, shipment_end_coords, delivery_end_coord):
        """Forms a time-distance matrix for jsprit.

        If a pair of coordinate has been processed previously, time and distance are fetched from the database.
        If it has not been processed, it is added to a file to be processed by OTP.
        OTP calculates time and distance between coordinates and saves them to a file.

        Output from OTP and a local database are merged into a one file.
        """
        jsprit_tdm_interface.set_writer(self.env.config.get('jsprit.tdm_file'), 'w')

        # start = time.time()
        # coords_to_process_with_router = []
        #
        # vehicle_coords = set(vehicle_coords)
        # return_coords = set(return_coords)
        # shipment_start_coords = set(shipment_start_coords)
        # shipment_end_coords = set(shipment_end_coords)
        # delivery_end_coord = set(delivery_end_coord)
        #
        # self._process_tdm_in_database(vehicle_coords, shipment_start_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(vehicle_coords, delivery_end_coord, coords_to_process_with_otp)
        # self._process_tdm_in_database(vehicle_coords, return_coords, coords_to_process_with_otp)
        #
        # self._process_tdm_in_database(shipment_start_coords, vehicle_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(shipment_end_coords, vehicle_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(delivery_end_coord, vehicle_coords, coords_to_process_with_otp)
        #
        # self._process_tdm_in_database(shipment_start_coords, shipment_end_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(shipment_start_coords, shipment_start_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(shipment_start_coords, delivery_end_coord, coords_to_process_with_otp)
        #
        # self._process_tdm_in_database(shipment_end_coords, shipment_start_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(shipment_end_coords, delivery_end_coord, coords_to_process_with_otp)
        # self._process_tdm_in_database(shipment_end_coords, shipment_end_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(shipment_end_coords, return_coords, coords_to_process_with_otp)
        #
        # self._process_tdm_in_database(delivery_end_coord, return_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(delivery_end_coord, shipment_start_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(delivery_end_coord, shipment_end_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(delivery_end_coord, delivery_end_coord, coords_to_process_with_otp)
        #
        # log.debug('DB processing time {}'.format(time.time() - start))
        # log.debug('TDM to process with OTP: {} out of {}'
        #           .format(len(set(coords_to_process_with_otp)),
        #                   len(vehicle_coords)*len(shipment_start_coords) +
        #                   len(vehicle_coords)*len(delivery_end_coord) +
        #                   len(vehicle_coords)*len(return_coords) +
        #
        #                   len(shipment_start_coords)*len(vehicle_coords) +
        #                   len(delivery_end_coord)*len(vehicle_coords) +
        #
        #                   len(shipment_start_coords)*len(shipment_end_coords) +
        #                   len(shipment_start_coords)*len(shipment_start_coords) +
        #                   len(shipment_start_coords)*len(delivery_end_coord) +
        #
        #                   len(shipment_end_coords)*len(shipment_start_coords) +
        #                   len(shipment_end_coords)*len(delivery_end_coord) +
        #                   len(shipment_end_coords)*len(shipment_end_coords) +
        #                   len(shipment_end_coords)*len(return_coords) +
        #
        #                   len(delivery_end_coord)*len(return_coords) +
        #                   len(delivery_end_coord)*len(shipment_start_coords) +
        #                   len(delivery_end_coord)*len(shipment_end_coords) +
        #                   len(delivery_end_coord)*len(delivery_end_coord)
        #                   ))
        #
        # log.debug('saved tdm records {}'.format(
        #     len(vehicle_coords)*len(shipment_end_coords) +
        #
        #     len(shipment_start_coords)*len(return_coords) +
        #     len(shipment_start_coords)*len(return_coords) +
        #
        #     len(return_coords)*len(vehicle_coords) +
        #     len(return_coords)*len(shipment_start_coords) +
        #     len(return_coords)*len(shipment_end_coords) +
        #     len(return_coords)*len(delivery_end_coord)+
        #
        #     len(shipment_end_coords)*len(vehicle_coords)
        # ))
        #
        # coords_to_process_with_otp = list(set(coords_to_process_with_otp))

        coords_to_process_with_router = set(vehicle_coords + return_coords +
                                            shipment_start_coords + shipment_end_coords + delivery_end_coord)
        if len(coords_to_process_with_router) > 0:
            start = time.time()

            durations, distances = self._osrm_tdm_request(coords_to_process_with_router)

            log.debug('osrm tdm time {}'.format(time.time() - start))

            # start = time.time()
            # db_conn.insert_tdm_many(
            #     [(coords[0].lat, coords[0].lon,
            #       coords[1].lat, coords[1].lon,
            #       row[2], row[3]) for source, destination in zip(coords_to_process_with_router, reader)])
            # db_conn.commit()

            to_db = []
            for source, duration_row, distance_row in zip(coords_to_process_with_router, durations, distances):
                for destination, duration, distance in zip(coords_to_process_with_router, duration_row, distance_row):
                    # to_db.append((source.lat, source.lon,
                    #               destination.lat, destination.lon,
                    #               duration, distance))
                    jsprit_tdm_interface.add_row_to_tdm(origin=self.coord_to_geoid.get(source),
                                                        destination=self.coord_to_geoid.get(destination),
                                                        time=duration, distance=distance)
            # db_conn.insert_tdm_many(to_db)
            # db_conn.commit()
            # log.debug('saving to database time {}'.format(time.time() - start))

        jsprit_tdm_interface.close()

    def _add_zero_length_connections(self, coords):
        """There may be requests from exactly the same points
        so we should allow jsprit to execute those sequentially"""
        jsprit_tdm_interface.set_writer(self.env.config.get('jsprit.tdm_file'), 'a')

        for coord_start in coords:
            # for coord_end in coords:
            #     if coord_start == coord_end:
            coord_id = self.coord_to_geoid[coord_start]
            jsprit_tdm_interface.matrix_writer.writerow([coord_id, coord_id, 0, 0])
        jsprit_tdm_interface.close()

    def _prepare_geoid(self, coords):
        geoid = 0
        self.coord_to_geoid = {}
        for coord in set(coords):
            self.coord_to_geoid[coord] = geoid
            geoid += 1

    def _merge_tdms(self):
        jsprit_tdm_interface.set_writer(self.env.config.get('jsprit.tdm_file'), 'a')
        otp_tdm_file = open(self.env.config.get('otp.tdm_file'), 'r')
        otp_reader = csv.reader(otp_tdm_file, delimiter=',')
        for row in otp_reader:
            jsprit_tdm_interface.matrix_writer.writerow(row)
        otp_tdm_file.close()
        jsprit_tdm_interface.close()

    def _process_tdm_in_database(self, start_coords, end_coords, coords_to_process_with_otp=None):
        """Checks in database if coordinates were already saved in database.

        For each start location check if at_time-distance were already calculated and stored in database.
        If not, add location pairs for processing with OTP.

        :param coords_to_process_with_otp: coordinates missing from database are saved to this list
        """
        for start_coord in start_coords:
            for end_coord in end_coords:
                if start_coord == end_coord:
                    continue
                td = db_conn.select_from_tdm_by_pair(start_coord, end_coord)
                if td is not None:
                    jsprit_tdm_interface.add_row_to_tdm(origin=self.coord_to_geoid.get(start_coord),
                                                        destination=self.coord_to_geoid.get(end_coord),
                                                        time=td[0], distance=td[1])
                else:
                    if coords_to_process_with_otp is not None:
                        coords_to_process_with_otp.append((start_coord, end_coord))


class Payload(object):
    def __init__(self, attributes, config):
        self.fromPlace = attributes.get('fromPlace'),
        self.toPlace = attributes.get('toPlace'),
        self.time = attributes.get('time'),
        self.mode = attributes.get('mode'),

        self.date = attributes.setdefault('date', config.get('date')),
        self.maxWalkDistance = attributes.setdefault('maxWalkDistance', config.get('maxWalkDistance'))

        for attr in attributes.items():
            if attr[0] in self.__dict__:
                continue
            self.__dict__[attr[0]] = attr[1]

    def get_payload(self):
        return self.__dict__
