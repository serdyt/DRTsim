#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@author: ai6644
"""

# TODO: add logging through Component.setup_logger()
import logging
import logging.handlers
from datetime import timedelta as td
import shutil

import os
import sys
from typing import List, Any, Union
import pprint
import time

from desmod.simulation import simulate
from desmod.component import Component

from population import Population
from service import ServiceProvider
from const import OtpMode, LegMode, DrtStatus
from jsprit_utils import jsprit_tdm_interface
from db_utils import db_conn
from const import CapacityDimensions as CD
from sim_utils import Trip
from xls_utils import xls_create_occupancy_charts

log = logging.getLogger(__name__)


class Top(Component):

    def __init__(self, *args, **kwargs):
        super(Top, self).__init__(*args, **kwargs)

        self.population = Population(self)

        self.serviceProvider = ServiceProvider(self)

        self._init_results()

        jsprit_tdm_interface.set_writer(self.env.config.get('jsprit.tdm_file'), 'w')
        db_conn.connect(self.env.config.get('db.file'))

    def connect_children(self):
        for person in self.population.person_list:
            self.connect(person, 'serviceProvider')
        self.connect(self.serviceProvider, 'population')

    def get_result(self, result):
        super(Top, self).get_result(result)
        result.update(self.env.results)

    def _init_results(self):
        self.env.results = {'total_trips': 0}
        for mode in OtpMode.get_all_modes():
            self.env.results['{}_trips'.format(mode)] = 0
        for leg in LegMode.get_all_modes():
            self.env.results['{}_legs'.format(leg)] = 0

        self.env.results['DRT_trips'] = 0
        self.env.results['DRT_legs'] = 0
        #
        # self.env.results['undeliverable_drt'] = 0
        # self.env.results['unassigned_drt_trips'] = 0
        # self.env.results['no_suitable_pt_stop'] = 0


def send_email(subject, text, files, zip_file):
    from os.path import basename
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formatdate
    import zipfile

    msg = MIMEMultipart()
    msg['From'] = 'drt.simulator@gmail.com'
    msg['To'] = 'sergei.dytckov@mau.se'
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    msg.attach(MIMEText(text))

    with zipfile.ZipFile(zip_file, 'w', compression=zipfile.ZIP_BZIP2, compresslevel=5) as log_zip:
        for f in files or []:
            log_zip.write(f)
    zf = open(zip_file, 'rb')
    part = MIMEApplication(zf.read(), Name=basename(zf.name))
    # After the file is closed
    part['Content-Disposition'] = 'attachment; filename={}'.format(basename(zf.name))
    msg.attach(part)

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login('drt.simulator@gmail.com', 'drtMalmoSweden')
    server.sendmail("drt.simulator@gmail.com", to_addrs="sergei.dytckov@mau.se", msg=msg.as_string())
    server.close()


os.environ['TZ'] = 'Sweden'
time.tzset()
config = {
    'sim.duration': '86400 s',
    'sim.duration_sec': 86400,
    'sim.seed': 42,
    'sim.email_notification': True,
    'sim.create_excel': True,
    'sim.purpose': 'Testing overnight trips',

    'person.behaviour': 'DefaultBehaviour',
    'person.mode_choice': 'DefaultModeChoice',
    'service.routing': 'DefaultRouting',
    'service.router_address': 'http://localhost:8080/otp/routers/skane/plan',
    'service.router_scripting_address': 'http://localhost:8080/otp/scripting/run',
    'service.osrm_route': 'http://0.0.0.0:5000/route/v1/driving/',
    'service.osrm_tdm': 'http://0.0.0.0:5000/table/v1/driving/',
    'service.modes': 'main_modes',  # ['main_modes','all_modes']
    'date': '11-14-2018',
    'date.struct_time': time.localtime(1542153600),
    'date.unix_epoch': 1542153600,

    'db.file': 'data/time_distance_matrix.db',

    'person.default_attr.walking_speed': 1.2,
    'person.default_attr.dimensions': {CD.SEATS: 1},
    'person.default_attr.driving_license': True,
    'person.default_attr.boarding_time': 30,
    'person.default_attr.leaving_time': 10,
    'person.default_attr.maxWalkDistance': 10,

    'traditional_transport.planning_in_advance': td(minutes=10).total_seconds(),

    'population.input_file': 'data/population_fake_od.json',
    'population.input_percentage': 0.005,

    # 'drt.zones': [z for z in range(12650001, 12650018)] + [z for z in range(12700001, 12700021)],
    'drt.zones': [z for z in range(12650001, 12650018)],
    'drt.planning_in_advance': td(hours=2).total_seconds(),
    'drt.time_window_constant': td(minutes=15).total_seconds(),
    'drt.time_window_multiplier': 1.5,
    'drt.time_window_shift_left': 1. / 4,
    'drt.PT_stops_file': 'data/zone_stops.csv',
    'drt.min_distance': 2000,
    'drt.walkCarSpeed': 16.6667,
    'drt.max_fake_walk': 1000000,
    'drt.visualize_routes': 'false',  # should be a string
    'drt.picture_folder': 'pictures/',
    'drt.number_vehicles': 30,
    'drt.vehicle_type': 'minibus',

    'drt.vehicle_types': {
        'minibus': {
            'capacity_dimensions': {CD.SEATS: 8, CD.WHEELCHAIRS: 1}
        },
        'taxi': {
            'capacity_dimensions': {CD.SEATS: 4}
        }
    },

}

folder = '-p-{}-pre-{}-twc-{}-twm-{}-nv-{}'.format(config.get('population.input_percentage'),
                                                   config.get('drt.planning_in_advance'),
                                                   config.get('drt.time_window_constant'),
                                                   config.get('drt.time_window_multiplier'),
                                                   config.get('drt.number_vehicles'))
try:
    shutil.rmtree(folder)
except (FileNotFoundError, OSError) as e:
    log.error(e)
os.mkdir(folder)

config.update({
    'jsprit.tdm_file': '{}/time_distance_matrix.csv'.format(folder),
    'jsprit.vrp_file': '{}/vrp.xml'.format(folder),
    'jsprit.vrp_solution': '{}/problem-with-solution.xml'.format(folder),
    'jsprit.debug_folder': '{}/jsprit_debug'.format(folder),

    'otp.input_file': '{}/points.csv'.format(folder),
    'otp.tdm_file': '{}/time_distance_matrix_otp.csv'.format(folder),
    'otp.script_file': '{}/OTP_travel_matrix.py'.format(folder),

    'sim.log': '{}/log'.format(folder),
    'sim.log_zip': '{}/log.zip'.format(folder),
    'sim.folder': folder,

    'drt.picture_folder': '{}/pictures/'.format(folder),
})
os.mkdir(config.get('jsprit.debug_folder'))
if config.get('drt.visualize_routes') == 'true':
    try:
        os.mkdir(config.get('drt.picture_folder'))
    except OSError:
        pass

orig_script = open('OTP_travel_matrix.py', 'r')
data = orig_script.read()
orig_script.close()
script = open("{}/OTP_travel_matrix.py".format(folder), 'w')
workdir = '../../DRTsim'
script.write('workdir = "{}/{}"'.format(workdir, folder) + data)
script.close()

"""Desmod takes responsibility for instantiating and elaborating the model,
we only need to pass the configuration dict and the top-level
Component class (Top) to simulate().
"""
if __name__ == '__main__':

    message = config.get('sim.purpose')
    log.info(message)

    try:
        os.remove(config.get('sim.log'))
    except FileNotFoundError:
        pass
    open(config.get('sim.log'), 'a').close()

    root = logging.getLogger()
    handler = logging.handlers.WatchedFileHandler(config.get('sim.log'))
    formatter = logging.Formatter(logging.BASIC_FORMAT)
    handler.setFormatter(formatter)
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # suppress the log of http request library
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    log.info("Starting the simulation")

    import time

    start = time.time()
    try:
        res = simulate(config, Top)
    except Exception as e:
        import zipfile

        if config.get('sim.email_notification'):
            send_email(subject='Simulation failed', text='{}\n{}'.format(message, str(e.args)),
                       files=[config.get('sim.log')], zip_file=config.get('sim.log_zip'))
        log.error(e)
        log.error(e.args)
        raise

    log.info('Total {} persons'.format(res.get('total_persons')))
    persons = res.get('Persons')  # List(Person)
    executed_trips = [trip for person in persons for trip in person.executed_trips]
    log.info('Executed trips: {}'.format(len(executed_trips)))
    log.info('Excluded persons due to none or a trivial path {}'
             .format(res.get('unactivatable_persons') +
                     res.get('unchoosable_persons') +
                     res.get('unplannable_persons')))
    log.info('********************************************')
    log.info('Mode share :')
    if config.get('service.modes') == 'main_modes':
        mode_list = OtpMode.get_main_modes()
        leg_list = LegMode.get_main_modes()
    else:
        mode_list = OtpMode.get_all_modes()
        leg_list = LegMode.get_all_modes()

    for mode in mode_list:
        log.info('{} {}'.format(mode, res.get('{}_trips'.format(mode))))
    log.info('DRT_trips {}'.format(res.get('DRT_trips')))
    log.info('DRT_TRANSIT_trips {}'.format(res.get('DRT_TRANSIT_trips')))

    log.info('********************************************')
    log.info('Unassigned DRT trips {}'.format(res.get('unassigned_drt_trips')))
    log.info('Undeliverable DRT trips {}'.format(res.get('undeliverable_drt')))
    log.info('Overnight DRT trips {}'.format(res.get('drt_overnight')))
    log.info('To late request to be served by DRT {}'.format(res.get('too_late_request')))
    log.info('No suitable PT stops for extra-zonal DRT trips {}'.format(res.get('no_suitable_pt_stop')))
    log.info('Too short trip for intra-zonal trip {}'.format(res.get('too_short_direct_trip')))
    log.info('No walking leg to replace {}'.format(res.get('no_suitable_pt_connection')))

    log.info('********************************************')
    log.info('Leg share :')
    for leg in leg_list:
        log.info('{} {}'.format(leg, res.get('{}_legs'.format(leg))))
    log.info('DRT_legs {}'.format(res.get('DRT_legs')))

    log.info('********************************************')

    log.info('elapsed at_time {}'.format(time.time() - start))

    from utils import VisualTrip, VisualTripWrapper, PopulationWrapper, osrm_route_request
    import json

    drt_trips = []
    drt_routed = []
    drt_unassigned = []
    for person in persons:
        for ex, pl, st in zip(person.executed_trips, person.planned_trips, person.drt_status):
            if st == DrtStatus.routed:
                drt_trips.append((ex, person.id, st))
            else:
                drt_trips.append((pl, person.id, st))

    drt_vis = VisualTripWrapper([VisualTrip(trip, pid, st.value) for trip, pid, st in drt_trips])
    # drt_vis_unassigned = VisualTripWrapper([VisualTrip(trip, pid) for trip, pid in drt_unassigned])

    json_drt = json.loads(drt_vis.to_json())
    with open('{}/drt_routed.json'.format(folder), 'w') as outfile:
        json.dump(json_drt, outfile)

    delivered_travelers = res.get('delivered_travelers')  # type: List[int]
    vehicle_meters = res.get('vehicle_meters')  # type: List[int]

    log.info('delivered travelers per vehicle {}'.format(sum(delivered_travelers) / len(delivered_travelers)))
    log.info('Vehicle kilometers {}'.format(sum(vehicle_meters) / 1000))
    try:
        log.info('delivered travelers per Vehicle kilometers {}'
                 .format(sum(delivered_travelers) / (sum(vehicle_meters) / 1000)))
    except ZeroDivisionError:
        pass
    log.info('delivered travelers per vehicle kilometer {}'
             .format(sum(delivered_travelers) / (sum(vehicle_meters) / 1000)))

    log.info('Delivered travelers: {}'.format(delivered_travelers))
    log.info('Vehicle kilometers: {}'.format([int(vm / 1000) for vm in vehicle_meters]))

    log.info('********************************************')

    direct_trips = [trip for person in persons for trip in person.direct_trips]
    direct_seconds = [trip.duration for trip in direct_trips]
    log.info('Direct minutes: {}'.format(sum(direct_seconds) / 60))
    log.info('Service hours: {}'.format(24 * config.get('drt.number_vehicles')))
    log.info('Direct minutes per service hour: {}'
             .format((sum(direct_seconds) / 60) / (24 * config.get('drt.number_vehicles'))))
    log.info(
        'Vehicle kilometer per direct minute: {}'.format((sum(vehicle_meters) / 1000) / (sum(direct_seconds) / 60)))
    travel_times = [trip.duration for trip in executed_trips]
    deviation_times = [tt - dt for tt, dt in zip(travel_times, direct_seconds)]
    log.info('Deviation time per total travel time: {}'.format(sum(deviation_times) / sum(travel_times)))

    try:
        drt_legs = [leg for trip in person.executed_trips for leg in trip.legs if leg.mode == OtpMode.DRT]
        direct_seconds_drt_only = sum([osrm_route_request(config, leg.start_coord, leg.end_coord).duration for leg in drt_legs])
        # direct_legs = [leg for trip in direct_trips for leg in trip.legs if leg.mode == OtpMode.DRT]
        # direct_seconds_drt_only = sum([leg.duration for leg in direct_legs])
        log.info('Direct minutes drt only: {}'.format(direct_seconds_drt_only / 60))
        log.info('Direct minutes drt only per service hour: {}'
                 .format((direct_seconds_drt_only / 60) / (24 * config.get('drt.number_vehicles'))))
        log.info(
            'Vehicle kilometer per direct minute drt only: {}'.format((sum(vehicle_meters) / 1000) / (direct_seconds_drt_only / 60)))

        travel_times_drt_only = sum([leg.duration for trip in executed_trips for leg in trip.legs if leg.mode == OtpMode.DRT])
        deviation_times_drt_only = travel_times_drt_only - direct_seconds_drt_only
        log.info('Deviation time per total travel time drt only: {}'.format(deviation_times_drt_only / travel_times_drt_only))
    except:
        log.error('Direct DRT minutes are probably screwd')

    pp = pprint.PrettyPrinter()
    log.info(pp.pformat(config))

    files = [config.get('sim.log')]

    if config.get('sim.create_excel'):
        try:
            xls_create_occupancy_charts(res, folder,
                                        config.get('drt.vehicle_types')
                                        .get(config.get('drt.vehicle_type'))
                                        .get('capacity_dimensions')
                                        .get(CD.SEATS))
            files.append('{}/occupancy.xlsx'.format(folder))
        except Exception as e:
            log.error('Failed to create excel file')
            log.error(e.args)

    files.append('{}/drt_routed.json'.format(folder))

    trip_dump = json.loads(PopulationWrapper(persons).to_json())
    with open('{}/trip_dump.json'.format(folder), 'w') as outfile:
        json.dump(trip_dump, outfile)

    files.append('{}/trip_dump.json'.format(folder))

    if config.get('sim.email_notification'):
        send_email(subject='Simulation success', text='{}\n{}'.format(message, 'congratulations'),
                   files=files, zip_file=config.get('sim.log_zip'))

# if __name__ == '__main__':
#     import cProfile
#     pr = cProfile.Profile()
#     pr.enable()
#     simulate(config, Top)
#     pr.disable()
#     pr.print_stats()
#     pr.dump_stats("profile.prof")
