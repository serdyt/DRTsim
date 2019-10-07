#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from simpy import Event
from statemachine import StateMachine, State
from exceptions import *
import population

log = logging.getLogger(__name__)

"""If you call each statemachine transaction function as an env.process,
and you need to yield at least once in it. Otherwise simpy trows an error
"""


class DefaultBehaviour(StateMachine):

    person = ...  #: population.Person
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
    reactivate = trip.to(activity)
    finalize = trip.to(final)

    unplannable = planing.to(final)
    trip_exception = trip.to(final)
    activity_exception = activity.to(final)
    
    def __init__(self, person):
        StateMachine.__init__(self)
        self.person = person
        self.env = self.person.env

    def on_activate(self):
        timeout = self.person.get_planning_time()
        # log.info('{} activating at {}'.format(self.person.scope, self.person.env.now))
        yield self.person.env.timeout(timeout)
        self.env.process(self.plan())
        
    def on_plan(self):
        yield Event(self.env).succeed()
        if self.person.planned_trip is None:
            try:
                alternatives = self.person.serviceProvider.request(self.person)
                self.person.alternatives = alternatives
            except (OTPTrivialPath, OTPUnreachable) as e:
                log.error('{}'.format(e.msg))
                log.error('Excluding person from simulation. {}'.format(self.person))
                self.env.process(self.unplannable())
        self.env.process(self.choose())

    def on_choose(self):
        """Chooses one of the alternatives according to config.person.mode_choice
        """
        yield Event(self.env).succeed()
        self.person.planned_trip = self.person.mode_choice.choose(self.person.alternatives)
        self.person.init_actual_trip()
        self.person.serviceProvider.start_trip(self.person)
        # TODO: after choosing, a traveler should wait for beginning of a trip
        # But that would break the current routing as start tim may be updated by other requests
        self.env.process(self.execute_trip())

    def on_execute_trip(self):
        self.env.process(self.person.serviceProvider.execute_trip(self.person))
        yield self.person.delivered
        self.person.reset_delivery()
        self.person.log_executed_trip()
        if self.person.change_activity() == -1:
            self.env.process(self.finalize())
        else:
            self.env.process(self.reactivate())

    def on_reactivate(self):
        yield Event(self.env).succeed()
        timeout = self.person.get_planning_time()
        # log.info('{} activating at {}'.format(self.person.scope, self.person.env.now))
        yield self.person.env.timeout(timeout)
        self.env.process(self.plan())
        # self.finalize()
        
    def on_finalize(self):
        yield Event(self.env).succeed()
        # self.person.log.close()

    def on_unplannable(self):
        yield Event(self.env).succeed()
        log.critical('{} going from {} to {} received none alternatives. Ignoring the person.'
                     .format(self.person, self.person.curr_activity.coord, self.person.next_activity.coord))

    def on_trip_exception(self):
        raise NotImplementedError()
        
    def on_activity_exception(self):
        raise NotImplementedError()
