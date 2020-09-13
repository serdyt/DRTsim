import logging

from enum import Enum, auto
from sim_utils import Activity, Leg, Trip

log = logging.getLogger(__name__)


class Event(list):
    """Event subscription.

    A list of callable objects. Calling an instance of this will cause a
    call to each item in the list in ascending order by index.

    Example Usage:
    >>> def f(x):
    ...     print 'f(%s)' % x
    >>> def g(x):
    ...     print 'g(%s)' % x
    >>> e = Event()
    >>> e()
    >>> e.append(f)
    >>> e(123)
    f(123)
    >>> e.remove(f)
    >>> e()
    >>> e += (f, g)
    >>> e(10)
    f(10)
    g(10)
    >>> del e[0]
    >>> e(2)
    g(2)

    """
    def __call__(self, *args, **kwargs):
        for f in self:
            f(*args, **kwargs)

    def __repr__(self):
        return "Event(%s)" % list.__repr__(self)


class VehicleEventType(Enum):
    VEHICLE_AT_DEPOT_IDLE = auto()
    VEHICLE_AT_DEPOT_WAIT = auto()
    VEHICLE_STARTED_ROUTE = auto()
    VEHICLE_STOP_ROUTE = auto()

    VEHICLE_REROUTED = auto()
    VEHICLE_REROUTED_ON_ROUTE = auto()

    VEHICLE_AT_STOP_PICKING = auto()
    VEHICLE_AT_STOP_DROPPING = auto()

    @staticmethod
    def to_str(cur_time, event_type, *args):
        if event_type == VehicleEventType.VEHICLE_AT_DEPOT_IDLE:
            record = '{}: idling at depot\n'.format(cur_time)
            return record
        if event_type == VehicleEventType.VEHICLE_AT_DEPOT_WAIT:
            record = '{}: waiting at depot\n'.format(cur_time)
            return record
        if event_type == VehicleEventType.VEHICLE_STARTED_ROUTE:
            passengers = args[0]
            record = '{}: starting a route with {} passengers\n'.format(cur_time, passengers)
            return record

        if event_type == VehicleEventType.VEHICLE_REROUTED:
            record = '{}: waiting at depot\n'.format(cur_time)
            return record
        if event_type == VehicleEventType.VEHICLE_REROUTED_ON_ROUTE:
            passengers = args[0]
            record = '{}: starting a route with {} passengers\n'.format(cur_time, passengers)
            return record

        if event_type == VehicleEventType.VEHICLE_AT_STOP_PICKING:
            passengers = args[0]
            record = '{}: at stop picking up {}\n'.format(cur_time, passengers)
            return record
        if event_type == VehicleEventType.VEHICLE_AT_STOP_DROPPING:
            passengers = args[0]
            record = '{}: at stop dropping off {}\n'.format(cur_time, passengers)
            return record


class TravellerEventType(Enum):
    ACT_STARTED = auto()
    ACT_FINISHED = auto()

    TRIP_REQUEST_SUBMITTED = auto()
    TRIP_ALTERNATIVES_RECEIVED = auto() 
    TRIP_CHOSEN = auto()
    TRIP_STARTED = auto()
    TRIP_FINISHED = auto()

    PRE_TRIP_WAIT_STARTED = auto()
    LEG_STARTED = auto()
    LEG_FINISHED = auto()

    DRT_STOP_STARTED = auto()
    DRT_STOP_FINISHED = auto()
    DRT_ON_ROUTE_REROUTED = auto()

    PLAN_FINISHED = auto()

    NO_RUTE = auto()

    @staticmethod
    def to_str(cur_time, event_type, *args):
        if event_type == TravellerEventType.ACT_STARTED:
            activity: Activity = args[0]
            record = '{}: started ACTIVITY {}\n'.format(cur_time, activity.type)
            if cur_time != activity.start_time:
                record += 'WARN: activity started not in the planned time\n'
            return record
        elif event_type == TravellerEventType.ACT_FINISHED:
            activity: Activity = args[0]
            record = '{}: finished ACTIVITY {}\n'.format(cur_time, activity.type)
            if cur_time != activity.end_time:
                record += 'WARN: activity finished not in the planned time\n'
            return record

        elif event_type == TravellerEventType.TRIP_REQUEST_SUBMITTED:
            record = '{}: trip request submitted\n'.format(cur_time)
            return record
        elif event_type == TravellerEventType.TRIP_ALTERNATIVES_RECEIVED:
            record = '{}: trip alternative received\n'.format(cur_time)
            return record
        elif event_type == TravellerEventType.TRIP_CHOSEN:
            trip: Trip = args[0]
            record = '{}: trip alternative chosen: {}\n'.format(cur_time, trip)
            return record
        elif event_type == TravellerEventType.TRIP_STARTED:
            record = '{}: trip started\n'.format(cur_time)
            return record
        elif event_type == TravellerEventType.TRIP_FINISHED:
            record = '{}: trip finished\n'.format(cur_time)
            return record

        elif event_type == TravellerEventType.PRE_TRIP_WAIT_STARTED:
            record = '{}: pre-trip waiting started\n'.format(cur_time)
            return record
        elif event_type == TravellerEventType.LEG_STARTED:
            leg: Leg = args[0]
            record = '{}: started leg {}\n'.format(cur_time, leg)
            if cur_time != leg.end_time:
                record += 'WARN: leg started not in the planned time\n'
            return record
        elif event_type == TravellerEventType.LEG_FINISHED:
            leg: Leg = args[0]
            record = '{}: finished leg {}'.format(cur_time, leg)
            if cur_time != leg.end_time:
                record += 'WARN: leg finished not in the planned time\n'
            return record

        elif event_type == TravellerEventType.DRT_STOP_STARTED:
            record = '{}: DRT stop started\n'.format(cur_time)
            return record
        elif event_type == TravellerEventType.DRT_STOP_FINISHED:
            record = '{}: DRT stop finished\n'.format(cur_time)
            return record
        elif event_type == TravellerEventType.DRT_ON_ROUTE_REROUTED:
            record = '{}: DRT vehicle rerouted\n'.format(cur_time)
            return record

        elif event_type == TravellerEventType.NO_RUTE:
            record = '{}: No route found for a person\n'.format(cur_time)
            return record

        elif event_type == TravellerEventType.PLAN_FINISHED:
            record = '{}: Activity plan carried out successfully\n'.format(cur_time)
            return record

