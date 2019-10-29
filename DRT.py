#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@author: ai6644
"""

# TODO: add logging through Component.setup_logger()
# or remove it from there =)
import logging
import logging.handlers
from datetime import timedelta as td
from typing import Any, Union

import simpy
import os
import sys
from typing import List

from desmod.simulation import simulate
from desmod.component import Component

from population import Population
from service import ServiceProvider
from const import OtpMode, LegMode
from jsprit_utils import jsprit_tdm_interface
from db_utils import db_conn
from const import CapacityDimensions as CD
from utils import Trip

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
            
    def post_simulate(self):
        print('Total {} persons'.format(len(self.population.person_list)))
        print('Mode share :')
        if self.env.config.get('service.modes') == 'main_modes':
            mode_list = OtpMode.get_main_modes()
            leg_list = LegMode.get_main_modes()
        else:
            mode_list = OtpMode.get_all_modes()
            leg_list = LegMode.get_all_modes()

        for mode in mode_list:
            print(mode, self.env.results.get('{}_trips'.format(mode)))
        print('DRT_trips', self.env.results.get('DRT_trips'))

        print('*******')
        print('Leg share :')
        for leg in leg_list:
            print(leg, self.env.results.get('{}_legs'.format(leg)))
        print('DRT_legs', self.env.results.get('DRT_trips'))

        print('********************************************')
        # print(self.population.get_result())

    def _init_results(self):
        self.env.results = {'total_trips': 0,
                            'unrouted_trips': 0
                            }
        for mode in OtpMode.get_all_modes():
            self.env.results['{}_trips'.format(mode)] = 0
        for leg in LegMode.get_all_modes():
            self.env.results['{}_legs'.format(leg)] = 0

        self.env.results['DRT_trips'] = 0
        self.env.results['DRT_legs'] = 0


def send_email(subject, text, files):
    from os.path import basename
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import COMMASPACE, formatdate

    msg = MIMEMultipart()
    msg['From'] = 'drt.simulator@gmail.com'
    msg['To'] = 'sergei.dytckov@mau.se'
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    msg.attach(MIMEText(text))

    for f in files or []:
        with open(f, "rb") as fil:
            part = MIMEApplication(fil.read(), Name=basename(f))
        # After the file is closed
        part['Content-Disposition'] = 'attachment; filename="%s"' % basename(f)
        msg.attach(part)

    server = smtplib.SMTP('smtp.gmail.com',587)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login('drt.simulator@gmail.com', 'drtMalmoSweden')
    server.sendmail("drt.simulator@gmail.com", to_addrs="sergei.dytckov@mau.se", msg=msg.as_string())
    server.close()


config = {
    'sim.duration': '86400 s',
    'sim.duration_sec': 86400,
    'sim.seed': 43,
    'sim.log': 'output/log',
    'sim.email_notification': False,

    'person.behaviour': 'DefaultBehaviour',
    'person.mode_choice': 'DefaultModeChoice',
    'service.routing': 'DefaultRouting',
    'service.router_address': 'http://localhost:8080/otp/routers/skane/plan',
    'service.router_scripting_address': 'http://localhost:8080/otp/scripting/run',
    'service.modes': 'main_modes',  # ['main_modes','all_modes']
    'date': '11-14-2018',
    'jsprit.tdm_file': 'data/time_distance_matrix.csv',
    'jsprit.vrp_file': 'data/vrp.xml',
    'jsprit.vrp_solution': 'data/problem-with-solution.xml',
    'db.file': 'data/time_distance_matrix.db',
    'otp.input_file': 'data/points.csv',
    'otp.tdm_file': 'data/time_distance_matrix_otp.csv',

    'person.default_attr.walking_speed': 1.2,
    'person.default_attr.dimensions': {CD.SEATS: 1},
    'person.default_attr.driving_license': True,
    'person.default_attr.boarding_time': 30,
    'person.default_attr.leaving_time': 10,
    'person.default_attr.maxWalkDistance': 10,

    'traditional_transport.planning_in_advance': td(minutes=10).total_seconds(),

    'population.input_file': 'data/population.json',

    'drt.zones': [z for z in range(12650001, 12650018)] + [z for z in range(12700001, 12700021)],
    'drt.default_tw_left': td(minutes=30).total_seconds(),
    'drt.default_tw_right': td(minutes=60).total_seconds(),
    'drt.planning_in_advance': td(minutes=120).total_seconds(),
    'drt.time_window_constant': td(minutes=10).total_seconds(),
    'drt.time_window_multiplier': 1.5,
    'drt.time_window_shift_left': 1./4,
    'drt.PT_stops_file': 'data/zone_stops.csv',
    'drt.min_distance': 2000,
    'drt.walkCarSpeed': 16.6667,
    'drt.max_fake_walk': 1000000,

    'trip.planning_in_advance_direct_time_coefficient': 2,
    'trip.planning_in_advance_constant': td(minutes=30).total_seconds(),
    }


"""Desmod takes responsibility for instantiating and elaborating the model,
we only need to pass the configuration dict and the top-level
Component class (Top) to simulate().
"""
if __name__ == '__main__':
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
        if config.get('sim.email_notification'):
            send_email(subject='Simulation failed', text=str(e.args), files=[config.get('sim.log')])
        log.error(e.args)
        print(e)
        raise
    else:
        if config.get('sim.email_notification'):
            send_email(subject='Simulation success', text='congratulations', files=[config.get('sim.log')])

    print('elapsed at_time ', time.time() - start)

    print(res)

    print(res.get('planned_trips'))
    print(res.get('executed_trips'))
    print(res.get('direct_trips'))
    
    executed_trips = res.get('executed_trips')  # type: List[Trip]
    drt_trips = [trip for trip in executed_trips if trip.main_mode == OtpMode.DRT]

    print('Total trips: {}'.format(len(executed_trips)))
    print('DRT trips: {}'.format(len(drt_trips)))

    delivered_travelers = res.get('delivered_travelers')  # type: List[int]
    vehicle_kilometers = res.get('vehicle_kilometers')  # type: List[int]

    print('delivered travelers per vehicle {}'.format(sum(delivered_travelers) / len(delivered_travelers)))
    print('Vehicle kilometers {}'.format(sum(vehicle_kilometers) / 1000))
    try:
        print('delivered travelers per Vehicle kilometers {}'
              .format(sum(delivered_travelers) / (sum(vehicle_kilometers) / 1000)))
    except ZeroDivisionError:
        pass

    print(delivered_travelers)
    print(vehicle_kilometers)

# if __name__ == '__main__':
#     import cProfile
#     pr = cProfile.Profile()
#     pr.enable()
#     simulate(config, Top)
#     pr.disable()
#     pr.print_stats()
#     pr.dump_stats("profile.prof")
