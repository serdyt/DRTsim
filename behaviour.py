#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Dec 21 15:17:18 2018

@author: ai6644
"""

"""If you call each statemachine transaction function as an env.process,
and you need to yield at least once in it. Otherwise simpy trows an error
"""

import logging
from simpy import Event

from statemachine import StateMachine, State

class default_behaviour(StateMachine):

    initial = State('initial', initial=True)
    activity = State('activity')
    planing = State('planing')
    choosing = State('choosing')
    trip = State('trip')
    final = State('final')
    
    activate = initial.to(activity)
    plan = activity.to(planing)
    choose = planing.to(choosing)
    execute_trip = choosing.to(trip)
    finalize = trip.to(final)

    unplannable = planing.to(final)
    trip_exception = trip.to(final)
    activity_exception = activity.to(final)
    
    def __init__(self, person):
        StateMachine.__init__(self)
        self.person = person
        self.env = self.person.env

    def on_activate(self):
        timeout = int((self.person.curr_activity.end_time - self.env.now))
        logging.info('{} activating at {}'.format(self.person.scope, self.person.env.now))
        yield self.person.env.timeout(timeout)
        self.env.process(self.plan())
        
    def on_plan(self):
        yield Event(self.env).succeed()
        if self.person.trip is None:
            alternatives = self.person.serviceProvider.request(self.person)
            if len(alternatives) == 0:
                self.unplannable()
            else:
                self.person.alternatives = alternatives
                self.env.process(self.choose())
        else:
            self.env.process(self.choose())

    def on_choose(self):
        """Chooses one of the alternatives according to config.person.mode_choice
        """
        yield Event(self.env).succeed()
        self.person.mode_choice.choose(self.person.alternatives)
        self.person.serviceProvider.start_trip(self.person)
        self.env.process(self.execute_trip())

    def on_execute_trip(self):
        yield Event(self.env).succeed()
        yield self.person.delivered
        self.env.process(self.finalize())
        # self.finalize()
        
    def on_finalize(self):
        yield Event(self.env).succeed()
        # self.person.log.close()

    def on_unplannable(self):
        yield Event(self.env).succeed()

    def on_trip_exception(self):
        raise NotImplementedError()
        
    def on_activity_exception(self):
        raise NotImplementedError()
