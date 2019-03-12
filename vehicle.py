
import copy
from typing import List
import logging

from desmod.component import Component

from utils import DrtAct, Coord
from population import Person

from const import CapacityDimensions as CD
from const import VehicleCost as VC


class VehicleType(object):

    def __init__(self, attrib):
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
        route: list of utils.Act to follow
        """
        Component.__init__(self, parent=parent, index=attrib.get('id'))
        self.coord = coord
        # TODO: add possibilities to return to different depot
        self.return_coord = coord
        self.vehicle_type = vehicle_type
        self.id = attrib.get('id')
        self.capacity_dimensions = copy.deepcopy(vehicle_type.capacity_dimensions)
        self.passengers = []
        self._route = []
        # Stores when vehicle has began an act (part of a route). It is used to calculate position with act's steps
        self.act_start_time = 0

        self.vehicle_kilometers = 0
        self.delivered_travelers = 0

        self.rerouted = self.env.event()

        self.add_process(self.run)

    def set_route(self, route):
        self._route = route

    def create_return_act(self):
        self._route.append(DrtAct(type_=DrtAct.RETURN, person=None, coord=self.return_coord))

    def get_route_without_return(self):
        return self._route[:-1]

    def get_route_with_return(self):
        return self._route

    def get_act(self, i=None):
        return self._route[i]

    def pop_act(self):
        return self._route.pop(0)

    def get_route_len(self):
        return len(self._route)

    def get_return_act(self):
        if self.get_route_len() != 0:
            if self.get_act(-1).type == DrtAct.RETURN:
                return self.get_act(-1)
        return None


    def run(self):
        """
        When a vehicle is created, it does not have any route, so it should wait until first request comes.
        Then vehicle executes the self.route

        Note that self.route can receive updates while vehicle is moving, in this case
        """
        while True:
            if self.get_route_len() == 0:
                yield self.rerouted

            # wait for the end of current action or for a rerouted event
            reached_destination = self.env.timeout(self.get_act(0).duration)
            yield self.rerouted | reached_destination

            if self.rerouted.triggered:
                self.rerouted = self.env.event()
                # TODO: rerouted routine, assuming that route is already modified

            elif reached_destination.triggered:
                # TODO: log the event
                act = self.pop_act()
                self.vehicle_kilometers += act.distance
                self.coord = act.coord

                if act.type == act.DROP_OFF or act.type == act.DELIVERY:
                    logging.info('Vehicle {} delivered person {} at {}'.format(self.id, act.person.id, self.env.now))
                    self._drop_off_travelers([act.person])
                elif act.type == act.PICK_UP:
                    logging.info('Vehicle {} picked up person {} at {}'.format(self.id, act.person.id, self.env.now))
                    self._pickup_travelers([act.person])
                    # Change the related delivery act type, so that it is rerouted correctly
                    delivery_act = [a for a in self.get_route_without_return() if a.person.id == act.person.id]
                    delivery_act[0].type = DrtAct.DELIVERY

    def _drop_off_travelers(self, persons):
        """Remove person from the list of current passengers and calculate statistics"""
        self.passengers = [p for p in self.passengers if p not in persons]
        for person in persons:
            for dimension in person.dimensions.items():
                self.capacity_dimensions[dimension[0]] += dimension[1]
            person.delivered.succeed()
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

    def get_coord_time(self, time):
        """Finds a position and time where a vehicle can be rerouted after param: time
        :return: coord, time
        """
        # TODO: calculate euclidean distance between previous and next steps coordinates to find a current position

        # if vehicle has no route, return its current position
        if len(self.get_route_with_return()) == 0:
            return self.coord, time

        # if vehicle is on the route, go through all the steps to find where it should be at the specified time
        passed_time = self.act_start_time
        for act in self._route:
            if passed_time + act.duration >= time:
                return act.get_position_by_time(passed_time, time)
            else:
                passed_time += act.duration
        # if vehicle has no activity at `time`, return coord,time pair from its latest activity
        return self.get_act(-1).coord, time
