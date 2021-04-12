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
from db_utils import db_conn
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
    'sim.purpose': 'All pt test',

    'person.behaviour': 'DefaultBehaviour',
    # 'person.mode_choice': 'DefaultModeChoice',
    'person.mode_choice': 'TimeWindowsModeChoice',
    'service.routing': 'DefaultRouting',
    'service.router_address': 'http://0.0.0.0:8080/otp/routers/lolland/plan',
    # 'service.router_scripting_address': 'http://localhost:8080/otp/scripting/run',
    'service.osrm_route': 'http://0.0.0.0:5000/route/v1/driving/',
    'service.osrm_tdm': 'http://0.0.0.0:5000/table/v1/driving/',
    'service.modes': 'main_modes',  # ['main_modes','all_modes']
    'date': '11-17-2020',
    # 'date.unix_epoch': 1542150000,  # 1542153600 - is one hour earlier!
    'date.unix_epoch': 1605567600,  # 1605571200,
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

    # maximum of these two will be taken as pre-booking time
    'drt.planning_in_advance': td(hours=0.5).total_seconds(),
    # 'drt.planning_in_advance_multiplier': 2,

    # # Parameters that determine maximum travel time for DRT leg
    'pt.drt_time_window_multiplier_in': 1.8,
    'pt.drt_time_window_constant_in': 0,
    'pt.drt_time_window_multiplier_out': 1.8,
    'pt.drt_time_window_constant_out': 0,
    'pt.drt_time_window_multiplier_within': 1.8,
    'pt.drt_time_window_constant_within': 0,

    'pt.trip_time_window_multiplier': 1,
    'pt.trip_time_window_constant': td(hours=1.0).total_seconds(),

    'drt.PT_stops_file': 'data/lolland_stops_left.csv',
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
    'otp.banned_trips': {
        'bannedTrips':
            '1:78040452,1:78040449,1:78040451,1:78040475,1:78040473,1:78040448,1:78040472,1:78040474,1:78040450,'
            '1:78040453,1:78040434,1:78040431,1:78040432,1:78040430,1:78040428,1:78040429,1:78040479,1:78040426,'
            '1:78040447,1:78040477,1:78040427,1:78040445,1:78040420,1:78040419,1:78040421,1:78040418,1:78040462,'
            '1:78040459,1:78040461,1:78040458,1:78040464,1:78040457,1:78040463,1:78040456,1:78040460,1:78040454,'
            '1:78040435,1:78040441,1:78040437,1:78040440,1:78040438,1:78040439,1:78040525,1:78040526,1:78040536,'
            '1:78040524,1:78040521,1:78040523,1:78040535,1:78040537,1:78040534,1:78040520,1:78040522,1:78040502,'
            '1:78040504,1:78040506,1:78040501,1:78040498,1:78040500,1:78040505,1:78040507,1:78040503,1:78040497,'
            '1:78040499,1:78040509,1:78040514,1:78040510,1:78040529,1:78040519,1:78040513,1:78040518,1:78040528,'
            '1:78040533,1:78040527,1:78040512,1:78040517,1:78040487,1:78040480,1:78040485,1:78040496,1:78040484,'
            '1:78040495,1:78040483,1:78040494,1:78040481,1:78040482,1:78040493,1:78040508,1:78040585,1:78040584,'
            '1:78040583,1:78040600,1:78040599,1:78040598,1:78040597,1:78040596,1:78040595,1:78040569,1:78040568,'
            '1:78040567,1:78040566,1:78040550,1:78040563,1:78040549,1:78040548,1:78040547,1:78040546,1:78040582,'
            '1:78040581,1:78040580,1:78040565,1:78040564,1:78040588,1:78040587,1:78040586,1:78040606,1:78040605,'
            '1:78040604,1:78040603,1:78040602,1:78040601,1:78040573,1:78040572,1:78040571,1:78040570,1:78040556,'
            '1:78040555,1:78040554,1:78040553,1:78040552,1:78040551,1:78042379,1:78042377,1:78042380,1:78042378,'
            '1:78042376,1:78042796,1:78042799,1:78042798,1:78042797,1:78042375,1:78042372,1:78042374,1:78042373,'
            '1:78042367,1:78042371,1:78042370,1:78042369,1:78042368,1:78042362,1:78042361,1:78042360,1:78042359,'
            '1:78042800,1:78042803,1:78042802,1:78042801,1:78042804'}

}

folder = '-p-{}-pre-{}-dwc-{}-dwm-{}-twc-{}-twm-{}-nv-{}'.\
    format([config.get('population.scenario'),
            config.get('population.input_percentage')],
            config.get('drt.planning_in_advance'),
            [
                config.get('pt.drt_time_window_constant_within'),
                config.get('pt.drt_time_window_constant_in'),
                config.get('pt.drt_time_window_constant_out')
            ],
            [
                config.get('pt.drt_time_window_multiplier_within'),
                config.get('pt.drt_time_window_multiplier_in'),
                config.get('pt.drt_time_window_multiplier_out')
            ],
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
