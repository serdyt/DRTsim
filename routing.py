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

from population import *
from const import OtpMode, LegMode
from utils import Trip, Leg, Coord, Step, trunc_microseconds, DrtAct, JspritSolution, otp_time_to_sec
from db_utils import db_conn
from jsprit_utils import jsprit_tdm_interface, jsprit_vrp_interface
from exceptions import *
import population

import logging

log = logging.getLogger(__name__)


class DefaultRouting(object):
    
    def __init__(self, service):

        # self.service = service
        self.env = service.env
        self.url = self.env.config.get("service.router_address")
        self.service = service
        self.coord_to_geoid = {}

    def otp_request(self, person: population.Person, mode: str, attributes={}):

        default_attributes = {'fromPlace': str(person.curr_activity.coord),
                              'toPlace': str(person.next_activity.coord),
                              'time': trunc_microseconds(str(td(seconds=person.next_activity.start_time))),
                              'date': self.env.config.get('date'),
                              'mode': mode,
                              'maxWalkDistance': 2000}
        default_attributes.update(person.otp_parameters)
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
        return Step(coord=Coord(lat=raw_step.get('lat'),
                                lon=raw_step.get('lon')),
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

                leg.start_time = otp_time_to_sec(raw_leg.get('startTime'))
                leg.end_time = otp_time_to_sec(raw_leg.get('endTime'))

                if leg.mode in OtpMode.get_pt_modes():
                    # OTP has id in the following format: 'SE-st:9022012065015001'
                    # we are not interested in the first part
                    leg.from_stop = int(raw_from.get('stopId').split(':')[1])
                    leg.to_stop = int(raw_to.get('stopId').split(':')[1])
                trip.append_leg(leg)

                trip.main_mode = trip.main_mode_from_legs()
            trips.append(trip)

        return trips

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
        try:
            self._calculate_time_distance_matrix(current_vehicle_coords, return_vehicle_coords,
                                                 persons_start_coords, persons_end_coords)
        # TODO: catch the exceptions for TDM
        except:sdfsdf

        jsprit_vrp_interface.write_vrp(self.env.config.get('jsprit.vrp_file'),
                                       self.service.vehicle_types, self.service.vehicles, vehicle_coords_times,
                                       shipment_persons, service_persons, self.coord_to_geoid)
        log.debug('vrp file calculation takes {}'.format(time.time() - start))

        # ***********************************************************
        # ************            Run jsprit              ***********
        # ***********************************************************
        start = time.time()
        jsprit_call = subprocess.call(['/usr/lib/jvm/java-8-openjdk-amd64/bin/java -Dfile.encoding=UTF-8 -classpath /home/ai6644/Malmo/Tools/jsprit/jsprit-examples/target/classes:/home/ai6644/Malmo/Tools/jsprit/jsprit-core/target/classes:/home/ai6644/.m2/repository/org/apache/commons/commons-math3/3.4/commons-math3-3.4.jar:/home/ai6644/.m2/repository/org/slf4j/slf4j-api/1.7.21/slf4j-api-1.7.21.jar:/home/ai6644/Malmo/Tools/jsprit/jsprit-analysis/target/classes:/home/ai6644/.m2/repository/org/jfree/jfreechart/1.0.19/jfreechart-1.0.19.jar:/home/ai6644/.m2/repository/org/jfree/jcommon/1.0.23/jcommon-1.0.23.jar:/home/ai6644/.m2/repository/org/graphstream/gs-core/1.3/gs-core-1.3.jar:/home/ai6644/.m2/repository/org/graphstream/pherd/1.0/pherd-1.0.jar:/home/ai6644/.m2/repository/org/graphstream/mbox2/1.0/mbox2-1.0.jar:/home/ai6644/.m2/repository/org/graphstream/gs-ui/1.3/gs-ui-1.3.jar:/home/ai6644/.m2/repository/org/graphstream/gs-algo/1.3/gs-algo-1.3.jar:/home/ai6644/.m2/repository/org/apache/commons/commons-math/2.1/commons-math-2.1.jar:/home/ai6644/.m2/repository/org/scala-lang/scala-library/2.10.1/scala-library-2.10.1.jar:/home/ai6644/Malmo/Tools/jsprit/jsprit-io/target/classes:/home/ai6644/.m2/repository/commons-configuration/commons-configuration/1.9/commons-configuration-1.9.jar:/home/ai6644/.m2/repository/commons-lang/commons-lang/2.6/commons-lang-2.6.jar:/home/ai6644/.m2/repository/commons-logging/commons-logging/1.1.1/commons-logging-1.1.1.jar:/home/ai6644/.m2/repository/xerces/xercesImpl/2.11.0/xercesImpl-2.11.0.jar:/home/ai6644/.m2/repository/xml-apis/xml-apis/1.4.01/xml-apis-1.4.01.jar:/home/ai6644/.m2/repository/org/apache/logging/log4j/log4j-slf4j-impl/2.0.1/log4j-slf4j-impl-2.0.1.jar:/home/ai6644/.m2/repository/org/apache/logging/log4j/log4j-api/2.0.1/log4j-api-2.0.1.jar:/home/ai6644/.m2/repository/org/apache/logging/log4j/log4j-core/2.0.1/log4j-core-2.0.1.jar com.graphhopper.jsprit.examples.DRT_test'], shell=True)
        if jsprit_call == 1:
            log.error("Jsprit has crashed")
        # os.system('/usr/lib/jvm/java-8-openjdk-amd64/bin/java -Dfile.encoding=UTF-8 -classpath /home/ai6644/Malmo/Tools/jsprit/jsprit-examples/target/classes:/home/ai6644/Malmo/Tools/jsprit/jsprit-core/target/classes:/home/ai6644/.m2/repository/org/apache/commons/commons-math3/3.4/commons-math3-3.4.jar:/home/ai6644/.m2/repository/org/slf4j/slf4j-api/1.7.21/slf4j-api-1.7.21.jar:/home/ai6644/Malmo/Tools/jsprit/jsprit-analysis/target/classes:/home/ai6644/.m2/repository/org/jfree/jfreechart/1.0.19/jfreechart-1.0.19.jar:/home/ai6644/.m2/repository/org/jfree/jcommon/1.0.23/jcommon-1.0.23.jar:/home/ai6644/.m2/repository/org/graphstream/gs-core/1.3/gs-core-1.3.jar:/home/ai6644/.m2/repository/org/graphstream/pherd/1.0/pherd-1.0.jar:/home/ai6644/.m2/repository/org/graphstream/mbox2/1.0/mbox2-1.0.jar:/home/ai6644/.m2/repository/org/graphstream/gs-ui/1.3/gs-ui-1.3.jar:/home/ai6644/.m2/repository/org/graphstream/gs-algo/1.3/gs-algo-1.3.jar:/home/ai6644/.m2/repository/org/apache/commons/commons-math/2.1/commons-math-2.1.jar:/home/ai6644/.m2/repository/org/scala-lang/scala-library/2.10.1/scala-library-2.10.1.jar:/home/ai6644/Malmo/Tools/jsprit/jsprit-io/target/classes:/home/ai6644/.m2/repository/commons-configuration/commons-configuration/1.9/commons-configuration-1.9.jar:/home/ai6644/.m2/repository/commons-lang/commons-lang/2.6/commons-lang-2.6.jar:/home/ai6644/.m2/repository/commons-logging/commons-logging/1.1.1/commons-logging-1.1.1.jar:/home/ai6644/.m2/repository/xerces/xercesImpl/2.11.0/xercesImpl-2.11.0.jar:/home/ai6644/.m2/repository/xml-apis/xml-apis/1.4.01/xml-apis-1.4.01.jar:/home/ai6644/.m2/repository/org/apache/logging/log4j/log4j-slf4j-impl/2.0.1/log4j-slf4j-impl-2.0.1.jar:/home/ai6644/.m2/repository/org/apache/logging/log4j/log4j-api/2.0.1/log4j-api-2.0.1.jar:/home/ai6644/.m2/repository/org/apache/logging/log4j/log4j-core/2.0.1/log4j-core-2.0.1.jar com.graphhopper.jsprit.examples.DRT_test')
        log.debug('jsprit takes {}ms of system time'.format(time.time() - start))

        # ***********************************************************
        # ************       Parse jsprit output          ***********
        # ***********************************************************
        solution = jsprit_vrp_interface.read_vrp_solution(self.env.config.get('jsprit.vrp_solution'))  # type: JspritSolution

        # ***********************************************************
        # ************         Form a DRT trip            ***********
        # ***********************************************************
        if solution is None:
            raise DrtUndeliverable('jsprit returned no solution. It may be the first and impossible request.'
                                   'Check this.\n'
                                   'The person will ignore DRT mode.')
        if person.id in solution.unassigned:
            raise DrtUnassigned('Person {} cannot be delivered by DRT'.format(person.id))

        # TODO: I assume that only one route is changed, i.e. insertion algorithm is used.
        #  If it is not the case, every jsprit_route should be updated
        modified_route = self._get_person_route(person, solution)
        if modified_route is None:
            log.error('Person {} has likely caused jsprit to crash. That may happen if time-windows as screwd.\n'
                      'Time window from {} to {}'.format(person.id, person.get_tw_left(), person.get_tw_right()))
            raise DrtUnassigned('Person {} is not listed in any jsprit routes'.format(person.id))
        solution.routes = None
        solution.modified_route = modified_route
        acts = [act for act in solution.modified_route.acts if act.person_id == person.id]
        # jsprit may route vehicles to pick up travelers long before requested start time,
        # thus we calculate actual trip duration based on the end of pickup event

        person.drt_leg.duration = (acts[-1].arrival_time - acts[0].end_time)
        # TODO: calculate distance for all the changed trips (need to call OTP to extract the distance)
        self.service.pending_drt_requests[person.id] = solution

    @staticmethod
    def find_singles(s):
        """Finds elements that do not repeat"""
        order = []
        counts = {}
        for x in s:
            if x in counts:
                counts[x] += 1
            else:
                counts[x] = 1
                order.append(x)
        singles = []
        for x in order:
            if counts[x] == 1:
                singles.append(x)
        return singles

    @staticmethod
    def _get_person_route(person, solution):
        routes = solution.routes
        for route in routes:
            for act in route.acts:
                if act.person_id == person.id:
                    return route
        return None

    def get_drt_route_details(self, coord_start, coord_end, at_time):
        payload = Payload(attributes={'fromPlace': str(coord_start),
                                      'toPlace': str(coord_end),
                                      'time': trunc_microseconds(str(td(seconds=at_time))),
                                      'date': self.env.config.get('date'),
                                      'mode': OtpMode.CAR},
                          config=self.env.config)

        resp = requests.get(self.url, params=payload.get_payload())
        # If OTP returns more than one route, take the first one
        # TODO: may be we want to take the fastest option
        trips = self.parse_otp_response(resp)
        trip = trips[0]
        trip.set_main_mode(OtpMode.DRT)
        return trip

    def _calculate_time_distance_matrix(self, vehicle_coords, return_coords, persons_start_coords, persons_end_coords):
        """Forms a time-distance matrix for jsprit.

        If a pair of coordinate has been processed previously, time and distance are fetched from the database.
        If it has not been processed, it is added to a file to be processed by OTP.
        OTP calculates time and distance between coordinates and saves them to a file.

        Output from OTP and a local database are merged into a one file.
        """

        # Check which OD pairs are in the database save those to a file for jsprit.
        # The missing pairs saved to coords_to_process_with_otp and sent to OTP
        jsprit_tdm_interface.set_writer(self.env.config.get('jsprit.tdm_file'), 'w')

        start = time.time()
        coords_to_process_with_otp = []
        # TODO: move coords_to_process_with_otp to return of the function instead of a parameter
        # self._process_tdm_in_database(vehicle_coords + return_coords + persons_start_coords + persons_end_coords,
        #                               vehicle_coords + return_coords + persons_start_coords + persons_end_coords,
        #                               coords_to_process_with_otp)

        self._process_tdm_in_database(vehicle_coords, persons_start_coords, coords_to_process_with_otp, reverse=False)
        self._process_tdm_in_database(vehicle_coords, persons_end_coords, coords_to_process_with_otp)
        self._process_tdm_in_database(vehicle_coords, return_coords, coords_to_process_with_otp)

        self._process_tdm_in_database(persons_start_coords, vehicle_coords, coords_to_process_with_otp, reverse=False)
        self._process_tdm_in_database(persons_start_coords, persons_end_coords, coords_to_process_with_otp, reverse=False)
        self._process_tdm_in_database(persons_end_coords, persons_start_coords, coords_to_process_with_otp)
        self._process_tdm_in_database(persons_end_coords, return_coords, coords_to_process_with_otp)

        # self._process_tdm_in_database(persons_start_coords, vehicle_coords, coords_to_process_with_otp)


        # self._process_tdm_in_database(persons_start_coords, persons_end_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(persons_end_coords, persons_start_coords, coords_to_process_with_otp)
        # self._process_tdm_in_database(persons_end_coords, return_coords, coords_to_process_with_otp)
        #
        # self._process_tdm_in_database(return_coords, persons_start_coords, coords_to_process_with_otp)
        log.debug('DB processing time {}'.format(time.time() - start))

        log.debug('TDM to process with OTP: {} out of {}'
                  .format(len(set(coords_to_process_with_otp)),
                  len(vehicle_coords)*len(persons_start_coords) +
                  len(persons_start_coords)*len(persons_end_coords) +
                  len(vehicle_coords)*len(return_coords) +
                  len(persons_end_coords)*len(return_coords) -
                  len(vehicle_coords) - len(persons_start_coords) - len(persons_end_coords) - len(return_coords)))

        start = time.time()
        coords_to_process_with_otp = list(set(coords_to_process_with_otp))
        if len(coords_to_process_with_otp) > 0:
            self._write_input_file_for_otp_script(coords_to_process_with_otp)

            # Call OTP script to calculate OD time-distance missing in the database
            multipart_form_data = {'scriptfile': ('OTP_travel_matrix.py', open('OTP_travel_matrix.py', 'rb'))}
            r = requests.post(url=self.env.config.get('service.router_scripting_address'), files=multipart_form_data)
            # raise an exception if script returned an error
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log.critical('OTP could not build a TDM. {}'.format(e))
                raise OTPException('OTP could not build a TDM.', e)

            log.debug('tdm calculation time {}'.format(time.time() - start))

            # Save OTP time-distance matrix to the database for future use
            otp_tdm_file = open(self.env.config.get('otp.tdm_file'), 'r')
            reader = csv.reader(otp_tdm_file, delimiter=',')
            for coords, row in zip(coords_to_process_with_otp, reader):
                origin = coords[0]
                destination = coords[1]
                at_time = row[2]
                distance = row[3]
                db_conn.insert_tdm_by_od(origin, destination, at_time, distance)
            otp_tdm_file.close()

        jsprit_tdm_interface.close()
        db_conn.commit()

        # merge responses from the database and OTP
        if len(coords_to_process_with_otp) > 0:
            self._merge_tdms()

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

    def _process_tdm_in_database(self, start_coords, end_coords, coords_to_process_with_otp=None, reverse=False):
        """Checks in database if coordinates were already saved in database.

        For each start location check if at_time-distance were already calculated and stored in database.
        If not, add location pairs for processing with OTP.

        :param coords_to_process_with_otp: coordinates missing from database are saved to this list
        """
        for start_coord in start_coords:
            tdm_table = db_conn.select_tdm_by_origin(start_coord)
            # row = [(to_lat, to_lon, time, distance)]
            end_coords_in_db = [Coord(lat=row[0], lon=row[1]) for row in tdm_table]
            for end_coord in end_coords:
                if end_coord == start_coord:
                    continue
                if end_coord in end_coords_in_db:
                    db_row = tdm_table[end_coords_in_db.index(end_coord)]
                    # add existing time to jsprit file
                    jsprit_tdm_interface.add_row_to_tdm(origin=self.coord_to_geoid.get(start_coord),
                                                        destination=self.coord_to_geoid.get(end_coord),
                                                        time=db_row[2], distance=db_row[3])
                    # I think this may cause integrity errors
                    # if reverse:
                    #     jsprit_tdm_interface.add_row_to_tdm(origin=self.coord_to_geoid.get(end_coord),
                    #                                         destination=self.coord_to_geoid.get(start_coord),
                    #                                         time=db_row[2], distance=db_row[3])
                else:
                    # if end_coord not in otp_coords_to_process:
                    if coords_to_process_with_otp is not None:
                        coords_to_process_with_otp.append((start_coord, end_coord))

    def _write_input_file_for_otp_script(self, coords):
        with open(self.env.config.get('otp.input_file'), 'w') as file:
            csvwriter = csv.writer(file, delimiter=',')
            # csvwriter.writerow(['GEOID_from', 'lat_from', 'lon_from', 'GEOID_to', 'lat_to', 'lon_to'])
            for coord in coords:
                csvwriter.writerow([self.coord_to_geoid[coord[0]], coord[0].lat, coord[0].lon,
                                    self.coord_to_geoid[coord[1]], coord[1].lat, coord[1].lon])
            file.close()


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
