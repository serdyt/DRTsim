#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utils to manage population


@author: ai6644
"""

import logging
from datetime import timedelta as td
import json

from desmod.component import Component
import behaviour
import mode_choice

from utils import Activity, Coord, seconds_from_str
from const import ActivityType as actType
from const import maxLat, minLat, maxLon, minLon
from const import CapacityDimensions as CD

consoleLog = logging.getLogger()
consoleLog.setLevel(level=logging.DEBUG)


class PopulationGenerator(object):
    """TODO: not implemented feature
    Generator stores only currently active persons. Inactive are written
    back to the database to save memory.
    """
    def __init__(self):
        raise NotImplementedError()


class Population(Component):
    """Population stores all the persons
    """
    
    base_name = 'population'
    
    def __init__(self, *args, **kwargs):
        super(Population, self).__init__(*args, **kwargs)
        self.person_list = []
        self._init_persons()
        
    def _init_persons(self):
        self.read_json()
        # self._random_persons()

    def read_json(self):
        with open(self.env.config.get('population.input_file'), 'r') as file:
            raw_json = json.load(file)
            persons = raw_json.get('persons')
            pers_id = 0
            i = 0
            for json_pers in persons:
                if i > 5:
                    break
                i = i+1
                attributes = {'age': 22, 'id': pers_id}
                pers_id = pers_id + 1

                activities = []
                json_activities = json_pers.get('activities')
                if len(json_activities) == 0:
                    raise Exception('No activities provided for a person.')
                for json_activity in json_activities:
                    type_str = json_activity.get('type')
                    type_ = actType.get_activity(type_str)

                    end_time = seconds_from_str(json_activity.get('end_time'))
                    start_time = seconds_from_str(json_activity.get('start_time'))

                    coord_json = json_activity.get('coord')
                    coord = Coord(lat=coord_json.get('lat'), lon=coord_json.get('lon'))

                    activities.append(
                        Activity(type_=type_,
                                 start_time=start_time,
                                 end_time=end_time,
                                 coord=coord
                                 )
                    )

                self.person_list.append(Person(self, attributes, activities))

    def _random_persons(self):
        for i in range(50):
            attributes = {'id': i, 'age': 54, 'walking_speed': 5, 'driving_licence': bool(self.env.rand.getrandbits(1)),
                          'dimensions': {CD.SEATS: 1, CD.WHEELCHAIRS: int(self.env.rand.getrandbits(1))}
                          }
            activities = [
                Activity(type_=actType.HOME,
                         coord=Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon)),
                         end_time=td(hours=self.env.rand.uniform(0, 10), minutes=self.env.rand.uniform(0, 59)).total_seconds()
                         ),
                Activity(type_=actType.WORK,
                         coord=Coord(lat=self.env.rand.uniform(minLat, maxLat), lon=self.env.rand.uniform(minLon, maxLon)),
                         start_time=td(hours=self.env.rand.uniform(11, 23), minutes=self.env.rand.uniform(0, 59)).total_seconds()
                         )
            ]
            self.person_list.append(Person(parent=self, attributes=attributes, activities=activities))
        
        consoleLog.info("Population size {0}".format(len(self.person_list)))


class Person(Component):
    
    base_name = 'person'

    def __init__(self, parent, attributes, activities, trip=None):
        """docstring"""
        Component.__init__(self, parent=parent, index=attributes.get('id'))
        self.add_connections('serviceProvider')

        self.dimensions = self.env.config.get('person.default_attr.dimensions')
        self.id = None
        self.driving_license = self.env.config.get('person.default_attr.driving_license')
        self.walking_speed = self.env.config.get('person.default_attr.walking_speed')
        self.age = self.env.config.get('person.default_attr.age')
        self.boarding_time = self.env.config.get('person.default_attr.boarding_time')
        self.leaving_time = self.env.config.get('person.default_attr.leaving_time')

        self._set_attributes(attributes)
        if len(activities) < 2:
            raise Exception('Person received less than two activities')
        self.activities = activities
        self.curr_activity = self.activities.pop(0)
        self.next_activity = self.activities.pop(0)
        # self.curr_activity = curr_activity
        # self.next_activity = next_activity
        self.trip = trip
        self.alternatives = None
        self.behaviour = getattr(behaviour, self.env.config.get('person.behaviour'))(self)
        self.mode_choice = getattr(mode_choice, self.env.config.get('person.mode_choice'))(self)

        self.delivered = self.env.event()
        self.add_process(self.behaviour.activate)

    def _set_attributes(self, attributes):
        for attr in attributes.items():
            setattr(self, attr[0], attr[1])

