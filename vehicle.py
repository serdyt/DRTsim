
import copy
from typing import List
import logging
import csv

from desmod.component import Component
from simpy.events import Event, Timeout

from sim_utils import DrtAct, Coord, Step
from population import Person

from const import CapacityDimensions as CD
from const import VehicleCost as VC
from log_utils import Event, TravellerEventType, VehicleEventType
import service

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
        self.costs = attrib.setdefault('costs', {VC.DISTANCE: 1.0, VC.FIXED: 5000, VC.TIME: 0.5, VC.WAIT: 0.5})


class Vehicle(Component):

    base_name = 'vehicle'

    return_coord = None  # type: Coord
    _route = None  # type: List[DrtAct]
    passengers = None  # type: List[Person]
    service = ...  # type: service.ServiceProvider

    def __init__(self, parent, attrib, return_coord, vehicle_type):
        """
        route: list[DrtAct] to follow
        """
        Component.__init__(self, parent=parent, index=attrib.get('id'))
        # service: ServiceProvider
        self.service = parent

        self.coord = return_coord
        # TODO: add possibilities to return to different depot
        self.return_coord = return_coord
        self.return_time = self.env.config.get('sim.duration_sec')
        self.vehicle_type = vehicle_type
        self.id = attrib.get('id')
        self.capacity_dimensions = copy.deepcopy(vehicle_type.capacity_dimensions)
        self.passengers = []
        self._route = []
        self.vehicle_kilometers = 0
        self.ride_time = 0

        # TODO: implement this properly with enums or different logging
        self.occupancy_stamps = []  # format[(time, number of passenger)] -1 = idle
        self.status_stamps = []
        self.meters_by_occupancy = [0 for _ in range(self.capacity_dimensions.get(CD.SEATS) + 1)]
        self.delivered_travelers = 0
        self.travel_log = []

        self.rerouted = self.env.event()

        # Vehicle publishes an event
        # Travellers subscribe to it
        self.event = Event()

        self.add_process(self.run)

    def set_route(self, route):
        self._route = route

    def get_route_without_return(self):
        return self._route[:-1]

    def get_acts_for_initial_route(self):
        """Returns only traveler related acts: Pick_up, drop_off and delivery
        Also ignores current act"""
        initial_route = []
        if self.route_not_empty():
            return [act for act in self._route[1:] if act.type in [DrtAct.PICK_UP, DrtAct.DROP_OFF, DrtAct.DELIVERY]]
        else:
            return []

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

    def route_not_empty(self):
        if self.get_route_len() != 0:
            return True
        else:
            return False

    def print_route(self):
        log.info('{}: Vehicle {} route'.format(self.env.now, self.id))
        for act in self._route:
            log.info(act)

    def get_return_act(self):
        if self.get_route_len() != 0:
            if self.get_act(-1).type == DrtAct.RETURN:
                return self.get_act(-1)
        return None

    # def post_simulate(self):
    #     self.occupancy_stamps.append((self.env.config.get('sim.duration_sec')-1, -1))

    def get_result(self, result):
        super(Vehicle, self).get_result(result)
        if 'delivered_travelers' not in result.keys():
            result['delivered_travelers'] = []
        if 'vehicle_meters' not in result.keys():
            result['vehicle_meters'] = []
        if 'ride_time' not in result.keys():
            result['ride_time'] = []
        if 'occupancy' not in result.keys():
            result['occupancy'] = []
        if 'meters_by_occupancy' not in result.keys():
            result['meters_by_occupancy'] = []

        result['delivered_travelers'] = result.get('delivered_travelers') + [self.delivered_travelers]
        result['vehicle_meters'] = result.get('vehicle_meters') + [self.vehicle_kilometers]
        result['ride_time'] = result.get('ride_time') + [self.ride_time]
        result['occupancy'] = result.get('occupancy') + [self.occupancy_stamps]
        result['meters_by_occupancy'] = result.get('meters_by_occupancy') + [self.meters_by_occupancy]
        self._save_vehicle_travel_logs()

    def _save_vehicle_travel_logs(self):
        log_folder = self.env.config.get('sim.vehicle_log_folder')
        try:
            with open('{}/vehicle_{}'.format(log_folder, self.id), 'w') as f:
                for record in self.travel_log:
                    if len(record) > 2:
                        f.write(VehicleEventType.to_str(record[0], record[1], *record[2]))
                    else:
                        f.write(VehicleEventType.to_str(record[0], record[1]))

            with open('{}/vehicle_occupancy_{}'.format(log_folder, self.id), 'w') as f:
                spam_writer = csv.writer(f, delimiter=',',
                                         quotechar='|', quoting=csv.QUOTE_MINIMAL)
                spam_writer.writerow(("time", "#passengers"))
                spam_writer.writerows(self.occupancy_stamps)

            with open('{}/vehicle_status_{}'.format(log_folder, self.id), 'w') as f:
                spam_writer = csv.writer(f, delimiter=',',
                                         quotechar='|', quoting=csv.QUOTE_MINIMAL)
                spam_writer.writerow(("time", "status (PICK_UP={}, DELIVERY={}, DRIVE={},"
                                              "WAIT={}, RETURN={}, IDLE={})"
                                      .format(DrtAct.PICK_UP, DrtAct.DELIVERY, DrtAct.DRIVE,
                                              DrtAct.WAIT, DrtAct.RETURN, DrtAct.IDLE)))
                spam_writer.writerows(self.status_stamps)

        except OSError as e:
            log.critical(e.strerror)

    def _update_travel_log(self, event_type, *args):
        self.travel_log.append([self.env.time(), event_type, [*args]])

    def _update_occupancy_log(self):
        self.occupancy_stamps.append((self.env.time(), len(self.passengers)))

    def _update_status_log(self):
        if self.route_not_empty():
            self.status_stamps.append((self.env.time(), self.get_act(0).type))
        else:
            self.status_stamps.append((self.env.time(), DrtAct.IDLE))

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
                self._update_travel_logs()
                yield self.rerouted
                self.rerouted = self.env.event()

            if self.get_route_len() != 0:
                # if self.get_act(0).type in [DrtAct.DRIVE, DrtAct.RETURN]:
                self.service.get_route_details(self)

            self._update_travel_logs()

            # wait for the end of current action or for a rerouted event
            timeout = self.get_act(0).end_time - self.env.now
            if timeout < 0:
                log.error('Vehicle {}:{}: Negative delay of {} is encountered. Resetting it to zero,'
                          .format(self.id, self.env.now, timeout))
                timeout = 0
            act_executed = self.env.timeout(timeout)  # type: Timeout
            yield self.rerouted | act_executed

            if self.rerouted.triggered:
                self.rerouted = self.env.event()

                # self._update_travel_log(VehicleEventType.VEHICLE_REROUTED_ON_ROUTE, len(self.passengers))
                # all the rerouting happens in the service provider

            elif act_executed.triggered:
                # if a new request came at exactly the same time as a vehicle reached a destination,
                # request should be processed first
                # TODO: try to do it with priority resource in a service
                if self.env.peek() == self.env.now:
                    yield self.env.timeout(0.0001)
                act = self.pop_act()  # type: DrtAct
                # TODO: add vehicle kilometers when first act is rerouted
                if act.distance is None:
                    log.error('{}:Vehicle {} executed an act with None distance'.format(self.env.now, self.id))
                else:
                    self.vehicle_kilometers += act.distance

                self.ride_time += act.duration
                self.coord = act.end_coord

                # if len(self.passengers) != 0:
                self._update_executed_passengers_routes(act.steps, act.end_coord)
                self._update_passengers_travel_log(TravellerEventType.DRT_STOP_FINISHED)

                if act.type == DrtAct.DRIVE or act.type == DrtAct.WAIT:
                    if self.get_route_len() == 0:
                        log.error('{}: Vehicle {} drove to no action. Probably to depot. Check if this happen'
                                  .format(self.env.now, self.id))
                        continue
                    else:
                        if act.type == DrtAct.DRIVE:
                            log.info('{}: Vehicle {} drove to serve {}'
                                     .format(self.env.now, self.id, self._route[0].person))
                        else:
                            log.info('{}: Vehicle {} waited to serve {}'
                                     .format(self.env.now, self.id, self._route[0].person))

                    new_act = self.get_act(0)
                    if new_act.type == DrtAct.DROP_OFF or new_act.type == DrtAct.DELIVERY:
                        log.info('{}: Vehicle {} starts delivering person {}'
                                 .format(self.env.now, self.id, new_act.person.id))
                        self._start_drop_off(new_act)

                    elif new_act.type == DrtAct.PICK_UP:
                        log.info('{}: Vehicle {} starts picking up person {}'
                                 .format(self.env.now, self.id, new_act.person.id))
                        self._pickup_travelers([new_act.person])
                        # When a person request a trip, person is a shipment with PICK_UP and DROP_OFF acts
                        # When a person boards we need to change it to delivery act for jsprit to reroute it correctly
                        drop_offs = [a for a in self.get_route_without_return() if a.type == DrtAct.DROP_OFF]
                        delivery_act = [a for a in drop_offs if a.person.id == new_act.person.id]
                        delivery_act[0].type = DrtAct.DELIVERY

                    elif new_act.type == DrtAct.WAIT:
                        log.info('{}: Vehicle {} starts waiting person {}'
                                 .format(self.env.now, self.id, new_act.person.id))

                elif act.type == DrtAct.DROP_OFF or act.type == DrtAct.DELIVERY:
                    log.info('{}: Vehicle {} delivered person {}'.format(self.env.now, self.id, act.person.id))
                    # self._update_travel_log(VehicleEventType.VEHICLE_AT_STOP_DROPPING, [act.person.id])
                    self._drop_off_travelers([act.person])
                elif act.type == DrtAct.PICK_UP:
                    # self._update_travel_log(VehicleEventType.VEHICLE_AT_STOP_PICKING, [act.person.id])
                    log.info('{}: Vehicle {} picked up person {}'.format(self.env.now, self.id, act.person.id))
                elif act.type == DrtAct.WAIT:
                    # self._update_travel_log(VehicleEventType.VEHICLE_AT_DEPOT_WAIT)
                    log.info('{}: Vehicle {} ended waiting before picking up a person'
                             .format(self.env.now, self.id))
                elif act.type == DrtAct.RETURN:
                    # self._update_travel_log(VehicleEventType.VEHICLE_AT_DEPOT_IDLE)
                    log.info('{}: Vehicle {} returned to depot'.format(self.env.now, self.id))
                else:
                    log.error('{}: Unexpected act type happened {}'.format(self.env.now, act))

    def set_empty_return_route(self):
        if self.get_act(0).type == DrtAct.RETURN:
            return
        if self.get_act(0).start_time < self.env.now:
            coord_time = self.get_current_coord_time()
            act = DrtAct(type_=DrtAct.RETURN, person=None,
                         duration=None,
                         end_coord=self.return_coord, start_coord=coord_time[0],
                         start_time=coord_time[1], end_time=None)
            self.set_route([act])
        else:
            self.set_route([])

    def _drop_off_travelers(self, persons):
        """Remove person from the list of current passengers and calculate statistics"""
        self.passengers = [p for p in self.passengers if p not in persons]

        for person in persons:
            person.finish_actual_drt_trip(self.env.now)
            for dimension in person.dimensions.items():
                self.capacity_dimensions[dimension[0]] += dimension[1]
            if person.drt_executed is None:
                log.error('{} drt_executed event has not been created'.format(person))
            person.drt_executed.succeed()

            self._is_person_served_within_tw(person)

        n = len(persons)
        self.delivered_travelers += n

    def _update_travel_logs(self):
        self._update_occupancy_log()
        self._update_status_log()

        if self.get_route_len() == 0:
            self._update_travel_log(VehicleEventType.VEHICLE_AT_DEPOT_IDLE)
        elif self.get_act(0).type == DrtAct.DRIVE:
            self._update_travel_log(VehicleEventType.VEHICLE_DRIVING)
        elif self.get_act(0).type == DrtAct.PICK_UP:
            self._update_travel_log(VehicleEventType.VEHICLE_AT_STOP_PICKING, [self.get_act(0).person.id])
        elif self.get_act(0).type == DrtAct.DELIVERY:
            self._update_travel_log(VehicleEventType.VEHICLE_AT_STOP_DROPPING, [self.get_act(0).person.id])
        elif self.get_act(0).type == DrtAct.RETURN:
            self._update_travel_log(VehicleEventType.VEHICLE_DRIVING)
        elif self.get_act(0).type == DrtAct.WAIT:
            self._update_travel_log(VehicleEventType.VEHICLE_AT_STOP_WAIT)
        else:
            raise Exception('unsupported activity type {}, cannot make a log'.format(self.get_act(0).type))

    def _pickup_travelers(self, persons):
        """Append persons to the list of current passengers
        and reduce capacity dimensions according to traveler's attributes"""
        self.passengers += persons
        for person in persons:
            person.start_actual_drt_trip(self.env.now, self.coord)
            for dimension in person.dimensions.items():
                self.capacity_dimensions[dimension[0]] -= dimension[1]
                if self.capacity_dimensions[dimension[0]] < 0:
                    raise Exception('Person has boarded to a vehicle while it has not enough space')

            self._is_person_served_within_tw(person)

    def _start_drop_off(self, act):
        act.person

    def _is_person_served_within_tw(self, person):
        if person.get_drt_tw_left() <= self.env.now <= person.get_drt_tw_right():
            return True
        else:
            log.error('{}: Person {} has been served  outside the requested time window: {} - {}'
                      .format(self.env.now, person.id, person.get_drt_tw_left(), person.get_drt_tw_right()))
            return False

    def _update_passengers_travel_log(self, travel_event_type):
        for person in self.passengers:
            person.update_travel_log(travel_event_type)

    def update_partially_executed_trips(self):
        """When a vehicle is rerouted in the middle of a route, save the executed steps of trips"""
        if len(self._route) > 0:
            self._update_passengers_travel_log(TravellerEventType.DRT_ON_ROUTE_REROUTED)
            passed_steps = self.get_passed_steps()
            if len(passed_steps) > 0:
                self._update_executed_passengers_routes(passed_steps, self.get_current_coord_time()[0])
                self.vehicle_kilometers += sum([step.distance for step in passed_steps])
                self.ride_time += sum([step.duration for step in passed_steps])

    def _update_executed_passengers_routes(self, executed_steps, end_coord):
        # log.debug('Vehicle {} has {} passengers'.format(self.id, len(self.passengers)))
        self.meters_by_occupancy[len(self.passengers)] += \
            sum([step.distance for step in executed_steps])
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

        act = self.get_act(0)
        if act.type == act.WAIT:
            return act.end_coord, self.env.now
        elif act.type in [act.PICK_UP, act.DROP_OFF, act.DELIVERY]:
            return act.end_coord, self.env.now
        else:
            return self.get_current_coord_time_from_step()

    def get_current_coord_time_from_step(self):
        act = self._route[0]
        current_time = act.start_time
        if act.steps is None:
            log.warning('{}:{}:No steps in act, probably two request at the same time came\n{}'.format(self.id, self.env.now, act))
            return act.start_coord, act.start_time

        if len(act.steps) == 0:
            log.error('{}: Getting current vehicle position, vehicle {} got no steps in {}\n'
                      'Returning end position of the act'.format(self.env.now, self.id, act))
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
        if current_time >= self.env.now:
            return act.end_coord, current_time
        else:
            log.error('{}:{}: There is not enough of steps at_time to fill the act, returning end of a current act.\n{}'
                      .format(self.id, self.env.now, act.flush()))
            return act.end_coord, current_time
            # raise Exception('There is not enough of steps at_time to fill the act')

    def get_current_step(self) -> Step:
        """Finds current step of a vehicle route

        Returns A step after which a vehicle can be rerouted.
        """
        act = self.get_act(0)
        current_time = act.start_time
        if len(act.steps) == 0:
            log.error('Vehicle {} has an empty act. Trying to fill act with one step'.format(self.id))
            act.steps.append(Step(start_coord=act.start_coord, end_coord=act.end_coord,
                                  distance=act.distance, duration=act.duration))

            return act.steps[-1]
            # raise Exception('Vehicle {} has an empty act\n{}'.format(self.id, self.flush()))

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

        log.error('{}: There is not enough of steps at_time to fill the act, returning the last step.\n{}'
                  .format(self.env.now, act.flush()))
        return act.steps[-1]
        # raise Exception('There is not enough of steps at_time to fill the act')

    def get_passed_steps(self):
        """Returns steps which vehicle has executed by now. DOES NOT include current step"""
        steps = []
        act = self.get_act(0)
        current_time = act.start_time

        if current_time == self.env.now:
            return []
        if len(act.steps) == 0:
            log.error('{}: Vehicle {} has an empty act. Returning empty passed step'.format(self.env.now, self.id))
            return Step(start_coord=act.start_coord, end_coord=act.end_coord,
                        duration=0, distance=0)
            # raise Exception('{}: Vehicle {} has an empty act\n{}'.format(self.env.now, self.id, self.flush()))

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

        log.error('{}: Vehicle {} has an act that do not sums up to a current time.'
                  'Filling missing time with a single step of zero length'.format(self.env.now, self.id))
        steps.append(Step(start_coord=steps[-1].end_coord, end_coord=act.end_coord,
                          duration=0, distance=0))
        return steps
        # raise Exception('Vehicle {} has an empty act\n{}'.format(self.id, self.flush()))
