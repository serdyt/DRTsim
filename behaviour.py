#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Implements person's behaviour as a finite state machine.

If you call each statemachine transaction function as an env.process, you need to yield at least once in it.
Otherwise simpy trows an error.

@author: ai6644
"""

import logging
from simpy import Event
from statemachine import StateMachine, State
from exceptions import *
import population

from sim_utils import OtpMode

log = logging.getLogger(__name__)


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

    unchoosable = choosing.to(final)
    unplannable = planing.to(final)
    unactivatable = activity.to(final)
    unreactivatable = activity.to(final)
    trip_exception = trip.to(final)
    activity_exception = activity.to(final)

    def __init__(self, person):
        StateMachine.__init__(self)
        self.person = person
        self.env = self.person.env

    def on_activate(self):
        otp_attributes = {'walkSpeed': self.env.config.get('drt.walkCarSpeed'),
                          'maxWalkDistance': self.env.config.get('drt.max_fake_walk'),
                          'numItineraries': 1}
        self.person.update_otp_params()
        try:
            direct_trip = self.person.serviceProvider.standalone_osrm_request(self.person)
            self.person.set_direct_trip(direct_trip)
            transit_trip = self.person.serviceProvider.standalone_otp_request(self.person, OtpMode.TRANSIT,
                                                                              otp_attributes)
            timeout = self.person.get_planning_time(transit_trip[0])

            yield self.person.env.timeout(timeout)
            self.env.process(self.plan())
        except (OTPNoPath, OTPTrivialPath) as e:
            log.warning('{}: {}\n{}'.format(self.env.now, e.msg, e.context))
            log.warning('{}: Person {} will be excluded from the simulation'.format(self.env.now, self.person))
            yield Event(self.env).succeed()
            self.env.process(self.unactivatable())

    def on_plan(self):
        yield Event(self.env).succeed()
        while self.env.peek() == self.env.now:
            # TODO: this makes sure that a request-replan sequence for a person is not broken
            # if it is, we must save multiple requests and have some policy to merge them
            yield self.person.env.timeout(0.000001)
        if self.person.planned_trip is None:
            try:
                alternatives = self.person.serviceProvider.request(self.person)
                self.person.alternatives = alternatives
                self.env.process(self.choose())
            except (OTPTrivialPath, OTPUnreachable) as e:
                log.warning('{}'.format(e.msg))
                log.warning('{}: Excluding person from simulation. {}'.format(self.env.now, self.person))
                self.env.process(self.unplannable())

    def on_choose(self):
        """Chooses one of the alternatives according to config.person.mode_choice
        """
        yield Event(self.env).succeed()
        chosen_trip = self.person.mode_choice.choose(self.person.alternatives)
        if chosen_trip is None:
            log.warning('{}: Trip could not be selected for Person {}.'
                        'It is possibly because there is no PT and person has no driving license.\n'
                        'Person will be excluded from simulation.'
                        .format(self.env.now, self.person.id))
            log.debug('{}\n{}'.format(self.person, self.person.alternatives))
            self.env.process()
        else:
            log.info('{}: Person {} have chosen trip {}'.format(self.env.now, self.person.id, chosen_trip))
            self.person.planned_trip = chosen_trip.deepcopy()
            self.person.init_actual_trip()
            self.person.serviceProvider.start_trip(self.person)
            # TODO: after choosing, a traveler should wait for beginning of a trip
            # But that would break the current routing as start tim may be updated by other requests
            self.env.process(self.execute_trip())

    def on_execute_trip(self):
        self.env.process(self.person.serviceProvider.execute_trip(self.person))
        yield self.person.delivered
        log.info('{}: Person {} has finished trip {}'.format(self.env.now, self.person.id, self.person.actual_trip))
        self.person.reset_delivery()
        self.person.log_executed_trip()
        if self.person.change_activity() == -1:
            self.env.process(self.finalize())
        else:
            self.env.process(self.reactivate())

    def on_reactivate(self):
        yield Event(self.env).succeed()
        otp_attributes = {'walkSpeed': self.env.config.get('drt.walkCarSpeed'),
                          'maxWalkDistance': self.env.config.get('drt.max_fake_walk'),
                          'numItineraries': 1}
        self.person.update_otp_params()
        try:
            direct_trip = self.person.serviceProvider.standalone_osrm_request(self.person)
            self.person.set_direct_trip(direct_trip)
            transit_trip = self.person.serviceProvider.standalone_otp_request(self.person, OtpMode.TRANSIT,
                                                                              otp_attributes)
            timeout = self.person.get_planning_time(transit_trip[0])
            yield self.person.env.timeout(timeout)
            self.env.process(self.plan())
        except OTPNoPath as e:
            log.warning('{}\n{}'.format(e.msg, e.context))
            log.warning('{}: Person {} will be excluded from the simulation'.format(self.env.now, self.person))
            self.env.process(self.unreactivatable())

    def on_finalize(self):
        yield Event(self.env).succeed()
        # self.person.log.close()

    def on_unplannable(self):
        yield Event(self.env).succeed()
        log.warning('{}: {} going from {} to {} received none alternatives. Ignoring the person.'
                    .format(self.env.now, self.person, self.person.curr_activity.coord,
                            self.person.next_activity.coord))
        self.person.serviceProvider.log_unplannable(self.person)

    def on_unchoosable(self):
        yield Event(self.env).succeed()
        log.warning('{}: {} going from {} to {} received none alternatives. Ignoring the person.'
                    .format(self.env.now, self.person, self.person.curr_activity.coord,
                            self.person.next_activity.coord))
        self.person.serviceProvider.log_unchoosable(self.person)

    def on_unactivatable(self):
        yield Event(self.env).succeed()
        log.warning('{}: {} going from {} to {} cannot reach the destination. Ignoring the person.'
                    .format(self.env.now, self.person, self.person.curr_activity.coord,
                            self.person.next_activity.coord))
        self.person.serviceProvider.log_unactivatable(self.person)

    def on_unreactivatable(self):
        yield Event(self.env).succeed()
        log.warning('{}: {} going from {} to {} cannot reach the destination. Ignoring the person.'
                    .format(self.env.now, self.person, self.person.curr_activity.coord,
                            self.person.next_activity.coord))
        self.person.serviceProvider.log_unactivatable(self.person)

    def on_trip_exception(self):
        raise NotImplementedError()

    def on_activity_exception(self):
        raise NotImplementedError()
