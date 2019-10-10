
import copy
from typing import List
import logging

from desmod.component import Component
from simpy import Event
from simpy.events import Event, Timeout
from simpy.core import Environment

from utils import DrtAct, Coord, Step
from population import Person

from const import CapacityDimensions as CD
from const import VehicleCost as VC
from exceptions import *

log = logging.getLogger(__name__)


class VehicleType(object):

    def __init__(self, attrib):
        """
        Parameters
        ----------
        attrib: dictionary that should provide at least 'id'. But also non-default capacity_dimensions and costs
        """
        if 'id' not in attrib.keys():
            raise Exception('vehicle type should have id')

        self.id = attrib.get('id')
        self.capacity_dimensions = attrib.setdefault('capacity_dimensions', {CD.SEATS: 8, CD.WHEELCHAIRS: 1})
        self.costs = attrib.setdefault('costs', {VC.DISTANCE: 1.0, VC.FIXED: 500, VC.TIME: 0.5, VC.WAIT: 0.5})


class Vehicle(Component):

    base_name = 'vehicle'

    return_coord = None  # type: Coord
    _route = None  # type: List[DrtAct]
    passengers = None  # type: List[Person]

    def __init__(self, parent, attrib, coord, vehicle_type):
        """
        route: list[DrtAct] to follow
        """
        Component.__init__(self, parent=parent, index=attrib.get('id'))
        self.service = parent

        self.coord = coord
        # TODO: add possibilities to return to different depot
        self.return_coord = coord
        self.vehicle_type = vehicle_type
        self.id = attrib.get('id')
        self.capacity_dimensions = copy.deepcopy(vehicle_type.capacity_dimensions)
        self.passengers = []
        # TODO: implement Act or Activity for vehicles with route, start_time, end_time similar to Jsprit_route
        self._route = []
        self.vehicle_kilometers = 0
        self.ride_time = 0
        self.delivered_travelers = 0

        self.rerouted = self.env.event()

        self.add_process(self.run)

    def set_route(self, route):
        self._route = route

    # def create_return_act(self):
    #     self._route.append(DrtAct(type_=DrtAct.RETURN, person=None, coord=self.return_coord))

    def get_route_without_return(self):
        return self._route[:-1]

    def get_acts_for_initial_route(self):
        """Returns only traveler related acts: Pick_up, drop_off and delivery
        Also ignores current act"""
        initial_route = []
        if self.get_route_len() == 0:
            return []
        else:
            return [act for act in self._route[1:] if act.type not in [DrtAct.DRIVE, DrtAct.WAIT, DrtAct.RETURN]]

    def get_route_with_return(self):
        return self._route

    def get_act(self, i=None):
        if self.get_route_len() == 0:
            raise Exception('Vehicle {} has no route\n{}'.format(self.id, self.flush()))
        return self._route[i]

    def pop_act(self):
        return self._route.pop(0)

    def get_route_len(self):
        return len(self._route)

    def print_route(self):
        print('Vehicle {}'.format(self.id))
        for act in self._route:
            print(act)

    def get_return_act(self):
        if self.get_route_len() != 0:
            if self.get_act(-1).type == DrtAct.RETURN:
                return self.get_act(-1)
        return None

    def get_result(self, result):
        if 'delivered_travelers' not in result.keys():
            result['delivered_travelers'] = []
        if 'vehicle_kilometers' not in result.keys():
            result['vehicle_kilometers'] = []
        if 'ride_time' not in result.keys():
            result['ride_time'] = []

        result['delivered_travelers'] = result.get('delivered_travelers') + [self.delivered_travelers]
        result['vehicle_kilometers'] = result.get('vehicle_kilometers') + [self.vehicle_kilometers]
        result['ride_time'] = result.get('ride_time') + [self.ride_time]

    def flush(self):
        return 'Vehicle {}\n Onboard persons: {}\nRoute: {}'.format(self.id, self.passengers, self._route)

    def run(self):
        """
        When a vehicle is created, it does not have any route, so it should wait until first request comes.
        Then vehicle executes the self.route

        Note that self.route can receive updates while vehicle is moving, in this case
        """
        while True:
            if self.get_route_len() == 0:
                yield self.rerouted
                self.rerouted = self.env.event()

            if self.get_route_len() != 0:
                if self.get_act(0).type in [DrtAct.DRIVE, DrtAct.RETURN]:
                    self.service.get_route_details(self)

            # wait for the end of current action or for a rerouted event
            act_executed = self.env.timeout(self.get_act(0).end_time - self.env.now)  # type: Timeout
            yield self.rerouted | act_executed

            if self.rerouted.triggered:
                self.rerouted = self.env.event()
                # all the rerouting happens in the service provider

            elif act_executed.triggered:
                # if a new request came at exactly the same time as a vehicle reached a destination,
                # request should be processed first
                # TODO: try to do it with priority resource in a service
                if self.env.peek() == self.env.now:
                    yield self.env.timeout(0.5)
                act = self.pop_act()  # type: DrtAct
                # TODO: add vehicle kilometers when first act is rerouted
                self.vehicle_kilometers += act.distance
                self.ride_time += act.duration
                self.coord = act.end_coord

                if len(self.passengers) != 0:
                    self.update_executed_passengers_routes(act.steps, act.end_coord)

                if act.type == act.DRIVE:
                    if self.get_route_len() == 0:
                        log.error('Vehicle {} drove to no action. Probably to depot. Check if this happen'.format(self.id))
                        continue
                    else:
                        log.info('Vehicle {} drove to serve {} at {}'.format(self.id, self._route[0].person, self.env.now))

                    new_act = self.get_act(0)
                    if new_act.type == new_act.DROP_OFF or new_act.type == new_act.DELIVERY:
                        log.info('Vehicle {} delivering person {} at {}'.format(self.id, new_act.person.id, self.env.now))
                        # self._drop_off_travelers([new_act.person])
                    elif new_act.type == new_act.PICK_UP:
                        log.info('Vehicle {} picking up person {} at {}'.format(self.id, new_act.person.id, self.env.now))
                        self._pickup_travelers([new_act.person])
                        # When a person request a trip, person is a shipment with PICK_UP and DROP_OFF acts
                        # When a person boards we need to change it to delivery act for jsprit to reroute it correctly
                        drop_offs = [a for a in self.get_route_without_return() if a.type == DrtAct.DROP_OFF]
                        delivery_act = [a for a in drop_offs if a.person.id == new_act.person.id]
                        delivery_act[0].type = DrtAct.DELIVERY

                elif act.type == act.DROP_OFF or act.type == act.DELIVERY:
                    log.info('Vehicle {} delivered person {} at {}'.format(self.id, act.person.id, self.env.now))
                    self._drop_off_travelers([act.person])
                elif act.type == act.PICK_UP:
                    log.info('Vehicle {} picked up person {} at {}'.format(self.id, act.person.id, self.env.now))
                elif act.type == act.WAIT:
                    log.info('Vehicle {} ended waiting after picking up a person at {}'.format(self.id, self.env.now))
                elif act.type == act.RETURN:
                    log.info('Vehicle {} returned to depot'.format(self.id))
                else:
                    log.error('Unexpected act type happened {}'.format(act))

    def _drop_off_travelers(self, persons):
        """Remove person from the list of current passengers and calculate statistics"""
        self.passengers = [p for p in self.passengers if p not in persons]

        for person in persons:
            for dimension in person.dimensions.items():
                self.capacity_dimensions[dimension[0]] += dimension[1]
            if person.drt_executed is None:
                log.error('{} drt_executed event has not been created'.format(person))
            person.drt_executed.succeed()

        n = len(persons)
        self.delivered_travelers += n

    def _pickup_travelers(self, persons):
        """Append persons to the list of current passengers
        and reduce capacity dimensions according to traveler's attributes"""
        self.passengers += persons
        for person in persons:
            for dimension in person.dimensions.items():
                self.capacity_dimensions[dimension[0]] -= dimension[1]
                if self.capacity_dimensions[dimension[0]] < 0:
                    raise Exception('Person has boarded to a vehicle while it has not enough space')

    def update_partially_executed_trips(self):
        """When a vehicle is rerouted in the middle of a route, save the executed steps of trips"""
        if len(self._route) > 0:
            passed_steps = self.get_passed_steps()
            if len(passed_steps) > 0:
                self.update_executed_passengers_routes(passed_steps, self.get_current_coord_time()[0])
                self.vehicle_kilometers += sum([step.distance for step in passed_steps])
                self.ride_time += sum([step.duration for step in passed_steps])

    def update_executed_passengers_routes(self, executed_steps, end_coord):
        for person in self.passengers:
            person.update_actual_trip(executed_steps, end_coord)

    def get_current_act(self):
        """Finds an act at at_time after which a vehicle can be rerouted

        :return: act
        """
        # TODO: calculate euclidean distance between previous and next steps coordinates to find a current position
        if len(self.get_route_with_return()) == 0:
            return None

        # if vehicle is on the route, go through all the acts to find where it should be at the specified time
        passed_time = self.get_act(0).start_time
        for act in self._route:
            if passed_time + act.duration >= self.env.now:
                return act
            else:
                passed_time += act.duration
        # if vehicle has no activity at `at_time`, return its latest activity
        return None

    def get_current_coord_time(self):
        """Finds a position and time where a vehicle can be rerouted
        :return: coord, at_time
        """
        # TODO: calculate euclidean distance between previous and next steps coordinates to find a current position

        # if vehicle has no activity, return its current position
        if self.get_route_len() == 0:
            return self.coord, self.env.now

        act = self._route[0]
        if act.type == act.WAIT:
            return act.end_coord, self.env.now
        elif act.type in [act.PICK_UP, act.DROP_OFF, act.DELIVERY]:
            return act.end_coord, act.end_time
        else:
            return self.get_current_coord_time_from_step()

    def get_current_coord_time_from_step(self):
        act = self._route[0]
        current_time = act.start_time
        if act.start_time is None:
            print('debugg')
        if len(act.steps) == 0:
            log.error('Getting current vehicle position, vehicle {} got no steps in {}\n'
                      'Returning end position of the act'.format(self.id, act))
            return act.end_coord, act.end_time

        if current_time == self.env.now:
            return act.start_coord, self.env.now

        for cstep, nstep in zip(act.steps, act.steps[1:]):
            current_time += cstep.duration
            if current_time >= self.env.now:
                return nstep.start_coord, current_time
            else:
                pass

        current_time += act.steps[-1].duration
        if current_time > self.env.now:
            return act.end_coord, current_time
        else:
            raise Exception('There is not enough of steps at_time to fill the act')

    def get_current_step(self) -> Step:
        """Finds current step of a vehicle route

        Returns A step after which a vehicle can be rerouted.
        """
        act = self.get_act(0)
        current_time = act.start_time
        if len(act.steps) == 0:
            raise Exception('Vehicle {} has an empty act\n{}'.format(self.id, self.flush()))

        if current_time == self.env.now:
            return None

        for step in act.steps:
            current_time += step.duration
            if current_time == self.env.now:
                return None
            elif current_time >= self.env.now:
                return step
            else:
                pass
        raise Exception('There is not enough of steps at_time to fill the act')

    def get_passed_steps(self):
        """Returns steps which vehicle has executed by now. DOES NOT include current step"""
        steps = []
        act = self.get_act(0)
        current_time = act.start_time

        if len(act.steps) == 0:
            raise Exception('Vehicle {} has an empty act\n{}'.format(self.id, self.flush()))
        if current_time == self.env.now:
            return []

        for step in act.steps:
            current_time += step.duration
            if current_time >= self.env.now:
                return steps
            else:
                steps.append(step)

            # for c_step, n_step in zip(self.steps, self.steps[1:] + [self.steps[-1]]):
            #     current_time += c_step.duration
            #     steps.append(c_step)
            #     if current_time >= by_time:
            #         return steps
        raise Exception('Vehicle {} has an empty act\n{}'.format(self.id, self.flush()))
