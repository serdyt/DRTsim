#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

@author: ai6644

Key assumptions:
    All the input data are in the database
    Separate script would be used to transfer input data to the database
    
"""

# TODO: add logging through Component.setup_logger()
import logging
import sqlite3
import simpy

from desmod.simulation import simulate
from desmod.component import Component

from population import Population
from service import ServiceProvider
from const import OtpMode, LegMode
from jsprit_utils import jsprit_tdm_interface
from db_utils import db_conn


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
            
    def post_simulate(self):
        print('Routed {} pesrons'.format(len(self.population.person_list)))
        print('Mode share :')
        for item in self.env.results.items():
            print(item)

    def _init_results(self):
        self.env.results = {'total_trips': 0,
                            'unrouted_trips': 0
                            }
        for mode in OtpMode.get_all_modes():
            self.env.results['{}_trips'.format(mode)] = 0
        for leg in LegMode.get_all_modes():
            self.env.results['{}_legs'.format(leg)] = 0
        # print(self.env.results.items())


config = {
    'sim.duration': '100000 s',
    'sim.seed': 1,
    'person.behaviour': 'default_behaviour',
    'person.mode_choice': 'default_mode_choice',
    'service.routing': 'default_routing',
    'service.router_address': 'http://localhost:8080/otp/routers/skane/plan',
    'service.router_scripting_address': 'http://localhost:8080/otp/scripting/run',
    'date': '11-14-2018',
    'jsprit.tdm_file': '/home/ai6644/Malmo/Tools/DRTsim/data/time_distance_matrix.csv',
    'jsprit.vrp_file': '/home/ai6644/Malmo/Tools/DRTsim/data/vrp.xml',
    'jsprit.vrp_solution': '/home/ai6644/Malmo/Tools/DRTsim/data/problem-with-solution.xml',
    'db.file': '/home/ai6644/Malmo/Tools/DRTsim/data/time_distance_matrix.db',
    'otp.input_file': '/home/ai6644/Malmo/Tools/DRTsim/data/points.csv',
    'otp.tdm_file': '/home/ai6644/Malmo/Tools/DRTsim/data/time_distance_matrix_otp.csv',

    'person.default_attr.walking_speed': 1.2,
    'person.default_attr.dimensions': {'seats': 1},
    'person.default_attr.driving_license': True,
    'person.default_attr.boarding_time': 30,
    'person.default_attr.leaving_time': 10,
    'person.default_attr.maxWalkDistance': 10,
    }
# consoleHandler = logging.StreamHandler()
consoleLog = logging.getLogger()
# consoleLog.addHandler(consoleHandler)
consoleLog.setLevel(level=logging.DEBUG)
consoleLog.info("Starting the process")

"""Desmod takes responsibility for instantiating and elaborating the model,
thus we only need to pass the configuration dict and the top-level
Component class (Top) to simulate().
"""
if __name__ == '__main__':
    import time
    start = time.time()
    simulate(config, Top)
    print('elapsed time ', time.time() - start)

# if __name__ == '__main__':
#     import cProfile
#     pr = cProfile.Profile()
#     pr.enable()
#     simulate(config, Top)
#     pr.disable()
#     pr.print_stats()
#     pr.dump_stats("profile.prof")
