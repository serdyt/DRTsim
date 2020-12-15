#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module to form input XML files for jsprit and parse XML output from it

@author: ai6644
"""

import csv
import xml.etree.ElementTree as ET
# from lxml import etree as ET
import logging

from sim_utils import JspritSolution, JspritAct, JspritRoute
from sim_utils import DrtAct

log = logging.getLogger(__name__)


class TDMReadWrite(object):

    def __init__(self):
        self.matrix_writer = None
        self.matrix_file = None

    def set_writer(self, file_name, mode):
        if self.matrix_file is not None:
            if not self.matrix_file.closed:
                self.matrix_file.close()
        self.matrix_file = open(file_name, mode)
        self.matrix_writer = csv.writer(self.matrix_file, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)

    def add_row_to_tdm(self, origin, destination, time, distance):
        if self.matrix_writer is not None:
            self.matrix_writer.writerow([origin, destination, time, distance])
        else:
            raise Exception('writing to a closed file')

    def get_reader(self, file_name):
        if self.matrix_file is not None:
            if not self.matrix_file.closed:
                raise Exception('get_reader() failed as file is still in use')
        self.matrix_file = open(file_name, 'r')
        return csv.reader(self.matrix_file)

    def close(self):
        self.matrix_file.close()
        self.matrix_writer = None


jsprit_tdm_interface = TDMReadWrite()


class VRPReadWriter(object):

    def __init__(self):
        self.vrp_file = None
        self.vrp_writer = None

    def reset(self):
        if self.vrp_file is not None:
            if not self.vrp_file.closed:
                self.vrp_file.close()
                self.vrp_writer = None

    # TODO: write end time as well (from the last act)
    def write_vrp(self, vrp_file, vehicle_types, vehicles, vehicle_coords_times, shipment_persons,
                  service_persons, coord_to_geoid):
        """Creates XML file with Vehicle Routing Problem in jsprit format

        :type vehicle_coords_times: List[(Coord, int)]

        :param vrp_file: file name to create
        :param vehicle_types: list of VehicleType, holds most of vehicle parameters
        :param vehicles: list of Vehicle to route
        :param vehicle_coords_times: current (coordinates, time) pairs of vehicles
        :param shipment_persons: list of Person that are not in the vehicle yet
        :param service_persons: list of Person in vehicles
        :param coord_to_geoid: a dictionary that translates coordinates to id
        """

        self.vrp_file = open(vrp_file, 'wb')
        root = ET.Element('problem', attrib={'xmlns': "http://www.w3schools.com",
                                             'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
                                             'xsi:schemaLocation': "http://www.w3schools.com vrp_xml_schema.xsd"})

        # root = ET.Element('problem')

        problem_type = ET.SubElement(root, 'problemType')
        ET.SubElement(problem_type, 'fleetSize').text = 'FINITE'

        # Writing vehicles
        vehicles_element = ET.SubElement(root, 'vehicles')
        for vehicle, coord_time in zip(vehicles, vehicle_coords_times):
            vehicle_element = ET.SubElement(vehicles_element, 'vehicle')
            ET.SubElement(vehicle_element, 'id').text = str(vehicle.id)
            ET.SubElement(vehicle_element, 'typeId').text = str(vehicle.vehicle_type.id)
            self._write_coord(vehicle_element, 'startLocation',
                              coord_time[0], geoid=coord_to_geoid.get(coord_time[0]))
            self._write_coord(vehicle_element, 'endLocation',
                              vehicle.return_coord, geoid=coord_to_geoid.get(vehicle.return_coord))
            time_element = ET.SubElement(vehicle_element, 'timeSchedule')
            ET.SubElement(time_element, 'start').text = str(coord_time[1])
            # working time form 0 to infinity
            ET.SubElement(time_element, 'end').text = '1.7976931348623157E308'
            ET.SubElement(vehicle_element, 'returnToDepot').text = 'true'

        # Writing vehicle types
        vehicle_types_element = ET.SubElement(root, 'vehicleTypes')
        # service.vehicle_types is a dictionary {id: VehicleType}
        for v_type in vehicle_types.items():
            type_element = ET.SubElement(vehicle_types_element, 'type')
            ET.SubElement(type_element, 'id').text = str(v_type[0])
            self._write_capacity_dimensions(type_element, v_type[1].capacity_dimensions.items())
            costs_element = ET.SubElement(type_element, 'costs')
            for cost in v_type[1].costs.items():
                ET.SubElement(costs_element, str(cost[0])).text = str(cost[1])

        # Writing services
        services_element = ET.SubElement(root, 'services')
        for person in service_persons:
            # if a person is in a vehicle, it must be delivered
            service_element = ET.SubElement(services_element, 'service', attrib={
                                                                                 'id': str(person.id),
                                                                                 'type': 'delivery'
                                                                                })
            self._write_coord(service_element, 'location', person.drt_leg.end_coord,
                              coord_to_geoid.get(person.drt_leg.end_coord))
            ET.SubElement(service_element, 'duration').text = str(person.leaving_time)
            self._write_capacity_dimensions(service_element, person.dimensions.items())
            self._write_time_windows(service_element,
                                     person.get_drt_tw_left(),
                                     person.get_drt_tw_right())
            self._write_max_in_vehicle_time(service_element, person, service=True)

        # Writing shipments
        shipments_element = ET.SubElement(root, 'shipments')
        for person in shipment_persons:
            shipment_element = ET.SubElement(shipments_element, 'shipment', attrib={'id': str(person.id)})
            self._write_shipment_step(shipment_element, 'pickup', person.drt_leg.start_coord,
                                      coord_to_geoid.get(person.drt_leg.start_coord),
                                      person.boarding_time,
                                      person.get_drt_tw_left(), person.get_drt_tw_right()
                                      )
            self._write_shipment_step(shipment_element, 'delivery', person.drt_leg.end_coord,
                                      coord_to_geoid.get(person.drt_leg.end_coord),
                                      person.leaving_time,
                                      person.get_drt_tw_left(), person.get_drt_tw_right()
                                      )
            self._write_capacity_dimensions(shipment_element, person.dimensions.items())
            self._write_max_in_vehicle_time(shipment_element, person)

        # Write initial routes
        initial_routes_element = ET.SubElement(root, 'initialRoutes')
        for vehicle, coord_time in zip(vehicles, vehicle_coords_times):
            if vehicle.get_route_len == 0:
                continue
            route_element = ET.SubElement(initial_routes_element, 'route')
            ET.SubElement(route_element, 'driverId').text = 'noDriver'
            ET.SubElement(route_element, 'vehicleId').text = str(vehicle.id)
            ET.SubElement(route_element, 'start').text = str(coord_time[1])
            for act in vehicle.get_acts_for_initial_route():  # type: DrtAct
                if act.type == DrtAct.DELIVERY:
                    id_tag = 'serviceId'
                elif act.type in [DrtAct.PICK_UP, DrtAct.DROP_OFF]:
                    # id_tag = 'shipmentId'
                    continue
                else:
                    log.error('Got unexpected act.type {} during the conversion for jsprit vrp.xml'.format(act.type))
                    raise Exception('Got unexpected act.type {} for jsprit vrp.xml'.format(act.type))
                act_element = ET.SubElement(route_element, 'act',
                                            attrib={'type': DrtAct.get_string_from_type(act.type)})
                ET.SubElement(act_element, id_tag).text = str(int(act.person.id))
            ET.SubElement(route_element, 'end').text = '0.0'

        tree = ET.ElementTree(root)
        # tree.write(vrp_file, xml_declaration=True, pretty_print=True)
        tree.write(vrp_file, xml_declaration=True)

    def _write_shipment_step(self, parent, shipment_type, coord, geoid, execution_time, tw_start, tw_end):
        shipment_type_element = ET.SubElement(parent, shipment_type)
        self._write_coord(shipment_type_element, 'location', coord, geoid)
        ET.SubElement(shipment_type_element, 'duration').text = str(execution_time)
        self._write_time_windows(shipment_type_element, tw_start, tw_end)

    @staticmethod
    def _write_time_windows(parent, tw_start, tw_end):
        time_windows_element = ET.SubElement(parent, 'timeWindows')
        time_window_element = ET.SubElement(time_windows_element, 'timeWindow')
        ET.SubElement(time_window_element, 'start').text = str(tw_start)
        ET.SubElement(time_window_element, 'end').text = str(tw_end)

    @staticmethod
    def _write_capacity_dimensions(parent, dimensions):
        capacity_element = ET.SubElement(parent, 'capacity-dimensions')
        for dimension in dimensions:
            ET.SubElement(capacity_element, 'dimension', attrib={'index': str(dimension[0])}).text = str(dimension[1])

    @staticmethod
    def _write_max_in_vehicle_time(parent, person, service=False):
        if service:
            text = str(person.get_rest_drt_duration())
        else:
            text = str(person.get_max_drt_duration())
        ET.SubElement(parent, 'maxInVehicleTime').text = text

    @staticmethod
    def _write_coord(parent, location_type, coord, geoid):
        """Writes coordinates to XML.

        jsprit can make graphs with vrp solution, but it requires actual coordinates to do this
        """
        location_element = ET.SubElement(parent, location_type)
        # index is mandatory when solving VRP based on time-distance matrix
        ET.SubElement(location_element, 'index').text = str(geoid)
        # other elements are optional
        ET.SubElement(location_element, 'id').text = str(geoid)
        ET.SubElement(location_element, 'coord', attrib={
            'x': str(coord.lon), 'y': str(coord.lat)
        })

    def read_vrp_solution(self, file_name):
        """Reads solution from output XML file of jsprit
        :return:  JspritSolution
        """
        self.reset()
        tree = ET.parse(file_name)
        root = tree.getroot()
        namespace = {'xmlns': 'http://www.w3schools.com'}
        solutions_element = root.find('xmlns:solutions', namespace)
        solution_element = solutions_element.find('xmlns:solution', namespace)
        routes = []
        routes_element = solution_element.find('xmlns:routes', namespace)
        # Theoretically there could be situation when no traveler can be routed
        if routes_element is None:
            return None
        for route_element in routes_element.findall('xmlns:route', namespace):
            acts = []
            for act_element in route_element.findall('xmlns:act', namespace):
                person_id_element = act_element.find('xmlns:shipmentId', namespace)
                if person_id_element is None:
                    person_id_element = act_element.find('xmlns:serviceId', namespace)
                act = JspritAct(type_=JspritAct.get_type_from_string(act_element.attrib.get('type')),
                                person_id=int(person_id_element.text),
                                end_time=float(act_element.find('xmlns:endTime', namespace).text),
                                arrival_time=float(act_element.find('xmlns:arrTime', namespace).text)
                                )
                acts.append(act)
            route = JspritRoute(vehicle_id=int(route_element.find('xmlns:vehicleId', namespace).text),
                                start_time=float(route_element.find('xmlns:start', namespace).text),
                                end_time=float(route_element.find('xmlns:end', namespace).text),
                                acts=acts
                                )
            routes.append(route)
        unassigned_jobs_elements = solution_element.findall('xmlns:unassignedJobs', namespace)
        unassigned_job_ids = []
        # there could be unroutable or undeliverable requests
        if unassigned_jobs_elements is not None:
            for unassigned_jobs_element in unassigned_jobs_elements:
                unassigned_job_ids.append(int(unassigned_jobs_element.find('xmlns:job', namespace).attrib.get('id')))

        solution = JspritSolution(cost=float(solution_element.find('xmlns:cost', namespace).text),
                                  routes=routes,
                                  unassigned=unassigned_job_ids)
        return solution


jsprit_vrp_interface = VRPReadWriter()
