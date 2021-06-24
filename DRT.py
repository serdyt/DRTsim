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
import zipfile

import os
import sys
from typing import List, Any, Union
import time

from desmod.simulation import simulate
from desmod.component import Component

from population import Population
from service import ServiceProvider
from const import OtpMode, LegMode, DrtStatus
from jsprit_utils import jsprit_tdm_interface
# from db_utils import db_conn
from sim_utils import Coord
from const import CapacityDimensions as CD


from post_processing_utils import send_email, gather_logs, zipdir

log = logging.getLogger(__name__)


class Top(Component):

    def __init__(self, *args, **kwargs):
        super(Top, self).__init__(*args, **kwargs)

        self.population = Population(self)

        self.serviceProvider = ServiceProvider(self)

        self._init_results()

        jsprit_tdm_interface.set_writer(self.env.config.get('jsprit.tdm_file'), 'w')
        # db_conn.connect(self.env.config.get('db.file'))

    def connect_children(self):
        for person in self.population.person_list:
            self.connect(person, 'serviceProvider')
        self.connect(self.serviceProvider, 'population')

    def get_result(self, result):
        super(Top, self).get_result(result)
        result.update(self.env.results)

    def _init_results(self):
        self.env.results = {'total_trips': 0}
        for otpmode in OtpMode.get_all_modes():
            self.env.results['{}_trips'.format(otpmode)] = 0
        for otpleg in LegMode.get_all_modes():
            self.env.results['{}_legs'.format(otpleg)] = 0

        self.env.results['DRT_trips'] = 0
        self.env.results['DRT_legs'] = 0
        #
        # self.env.results['undeliverable_drt'] = 0
        # self.env.results['unassigned_drt_trips'] = 0
        # self.env.results['no_suitable_pt_stop'] = 0


# os.environ['TZ'] = 'Denmark'
time.tzset()
config = {
    'sim.duration': '86400 s',
    'sim.duration_sec': 86400,
    'sim.seed': 42,
    'sim.email_notification': True,
    'sim.create_excel': True,
    'sim.purpose': 'debugging',

    'person.behaviour': 'DefaultBehaviour',
    # 'person.mode_choice': 'DefaultModeChoice',
    'person.mode_choice': 'TimeWindowsModeChoice',
    'service.routing': 'DefaultRouting',
    'service.router_address': 'http://0.0.0.0:8080/otp/routers/lolland/plan',
    # 'service.router_scripting_address': 'http://localhost:8080/otp/scripting/run',
    'service.osrm_route': 'http://0.0.0.0:5000/route/v1/driving/',
    'service.osrm_tdm': 'http://0.0.0.0:5000/table/v1/driving/',
    'service.modes': 'main_modes',  # ['main_modes','all_modes']
    'date': '11-12-2019',
    'date.unix_epoch': 1573513200,
    # 'db.file': 'data/time_distance_matrix.db',

    'person.default_attr.walking_speed': 1.2,
    'person.default_attr.dimensions': {CD.SEATS: 1},
    'person.default_attr.driving_license': True,
    'person.default_attr.boarding_time': 60,
    'person.default_attr.leaving_time': 60,
    # 'person.default_attr.maxWalkDistance': 2000,

    'population.input_file': 'data/population_lolland_4500.json',
    'population.input_percentage': 1.0,
    # ['all_within', 'pt_only', 'drtable_all', 'drtable_outside', 'all']
    'population.scenario': 'drtable_all',

    # 'drt.zones': [z for z in range(12650001, 12650018)] + [z for z in range(12700001, 12700021)],  # Sjöbo + Tomelilla
    # 'drt.zones': [360110, 360120, 360130, 360140, 360210, 360230, 360240, 360250],
    'drt.zones': [360250, 360240, 360230, 360210],
    # trips near (see Coord.is_near()) this location are considered local
    #
    'drt.transfer_points': [Coord(lat=54.837899, lon=11.365052),
                            Coord(lat=54.881666504245416, lon=11.358272981013629),
                            Coord(lat=54.75995263251924, lon=11.332806322256774)],

    # maximum of these two will be taken as pre-booking time
    'drt.planning_in_advance': td(hours=1.01).total_seconds(),
    # 'drt.planning_in_advance_multiplier': 2,

    # # Parameters that determine maximum travel time for DRT leg

    'pt.max_trip_duration_multiplier': 1.4,
    'pt.max_trip_duration_constant': 0,

    'pt.trip_time_window_multiplier': 1,
    'pt.trip_time_window_constant': td(hours=1.0).total_seconds(),

    # these two files define at which stops are eligible for DRT to perform transfers
    'drt.PT_stops_file': 'data/lolland_stops_left.csv',
    'drt.PT_extra_stops_file': 'data/extra_drt_transfer_stops lines [780,717,725].txt',

    'drt.min_distance': 500,
    'drt.maxPreTransitTime': 1500,  # max time of car leg in kiss_&_ride
    'drt.default_max_walk': 3000,
    'drt.visualize_routes': 'false',  # should be a string
    'drt.picture_folder': 'pictures/',
    'drt.number_vehicles': 30,

    # not actually in use:
    'drt.vehicle_type': 'minibus',
    'drt.vehicle_types': {
        'minibus': {
            'capacity_dimensions': {CD.SEATS: 8, CD.WHEELCHAIRS: 1}
        },
        'taxi': {
            'capacity_dimensions': {CD.SEATS: 4}
        }
    },
    'otp.default_attributes': {
        'arriveBy': 'False',
        'maxWalkDistance': 2000,
        'maxTransfers': 10
    },
    'otp.banned_trips': {'bannedTrips': ''},
    'otp.banned_trips_file': 'data/banned trips lines [780,717,725].txt',
    'otp.banned_stops': {'bannedStops': ''},
    'otp.banned_stops_file': 'data/banned stops.txt'

}

folder = '{}-p-{}-pre-{}-dwc-{}-dwm-{}-twc-{}-twm-{}-nv-{}'.\
    format(config.get('sim.purpose'),
           [
            config.get('population.scenario'),
            config.get('population.input_percentage')
           ],
           config.get('drt.planning_in_advance'),

           config.get('pt.drt_time_window_constant'),
           config.get('pt.drt_time_window_multiplier'),
           config.get('pt.trip_time_window_constant'),
           config.get('pt.trip_time_window_multiplier'),

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

    'sim.person_log_folder': '{}/person_logs'.format(folder),
    'sim.vehicle_log_folder': '{}/vehicle_logs'.format(folder),
    'sim.log': '{}/log'.format(folder),
    'sim_summary.log': '{}/log_summary.log'.format(folder),
    'sim.log_zip': '{}/log.zip'.format(folder),
    'sim.folder': folder,

    'drt.picture_folder': '{}/pictures/'.format(folder),
})

with open(config.get('otp.banned_trips_file')) as f:
    txt = f.read().rstrip() + ',' + config.get('otp.banned_trips').get('bannedTrips')
    txt = txt.strip(',')
    print(txt)
    config.update({'otp.banned_trips': {'bannedTrips': txt}})
    f.close()

with open(config.get('otp.banned_stops_file')) as f:
    txt = f.read().rstrip() + ',' + config.get('otp.banned_stops').get('bannedStops')
    txt = txt.strip(',')
    print(txt)
    config.update({'otp.banned_stops': {'bannedStops': txt}})
    f.close()

os.mkdir(config.get('jsprit.debug_folder'))
os.mkdir(config.get('sim.person_log_folder'))
os.mkdir(config.get('sim.vehicle_log_folder'))
if config.get('drt.visualize_routes') == 'true':
    try:
        os.mkdir(config.get('drt.picture_folder'))
    except OSError:
        pass

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

    start = time.time()
    try:
        res = simulate(config, Top)
    except Exception as e:
        import zipfile

        if config.get('sim.email_notification'):
            send_email(subject='Simulation failed', text='{}\n{}'.format(message, str(e.args)),
                       zip_file=config.get('sim.log_zip'))
        log.error(e)
        log.error(e.args)
        raise

    log.info('elapsed at_time {}'.format(time.time() - start))

    files = gather_logs(config, folder, res)

    zip_file = config.get('sim.log_zip')
    with zipfile.ZipFile(zip_file, 'w', compression=zipfile.ZIP_BZIP2, compresslevel=5) as log_zip:
        for f in files or []:
            log_zip.write(f)
        zipdir(config.get('sim.person_log_folder'), log_zip)
        zipdir(config.get('sim.vehicle_log_folder'), log_zip)

    if config.get('sim.email_notification'):
        send_email(subject='Simulation success', text='{}\n{}'.format(message, 'congratulations'),
                   zip_file=config.get('sim_summary.log'))

# if __name__ == '__main__':
#     import cProfile
#     pr = cProfile.Profile()
#     pr.enable()
#     simulate(config, Top)
#     pr.disable()
#     pr.print_stats()
#     pr.dump_stats("profile.prof")
