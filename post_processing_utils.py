from sim_utils import Coord, Trip, Step, Leg
from const import OtpMode
import json
import requests
import logging
import pprint
import os

from const import OtpMode, LegMode, DrtStatus
from xls_utils import xls_create_occupancy_charts
from const import CapacityDimensions as CD

log = logging.getLogger(__name__)


def _try(o):
    return o.__dict__


class VisualTripWrapper(object):

    def __init__(self, l):
        self.trips = l

    def to_json(self):
        return json.dumps(self, default=lambda o: _try(o), sort_keys=False, indent=4, separators=(',', ':'))


# TODO: find a better name
class VisualTrip(object):

    def __init__(self, trip: Trip, person_id, status):
        self.coord_start = trip.legs[0].start_coord
        self.coord_end = trip.legs[0].end_coord
        self.time_start = trip.legs[0].start_time
        self.time_end = trip.legs[0].end_time
        self.person_id = person_id
        self.status = status

    def __str__(self):
        return '[(({}),({})),({},{})]'.format(self.coord_start, self.coord_end, self.time_start, self.time_end)

    def __repr__(self):
        return str(self)


def _try_json_pop(o):
    try:
        return o.dumps()
    except:
        return o.__dict__


class PopulationWrapper(object):
    '''
    Wraps population object to serialize it to json
    '''

    def __init__(self, l):
        self.person = l

    def to_json(self):
        return json.dumps(self, default=lambda o: _try_json_pop(o), sort_keys=False, indent=4, separators=(',', ':'))


# TODO: refactor Default_routing so that it could be usable directly without service
def osrm_route_request(config, from_place, to_place):
    url_coords = '{}{},{};{},{}' \
        .format(config.get('service.osrm_route'),
                from_place.lon, from_place.lat, to_place.lon, to_place.lat)
    url_full = url_coords + '?annotations=true&geometries=geojson&steps=true'
    resp = requests.get(url=url_full)
    return _parse_osrm_response(resp)


def _parse_osrm_response(resp):
    # if resp.status_code != requests.codes.ok:
    #     resp.raise_for_status()

    jresp = resp.json()
    # if jresp.get('code') != 'Ok':
    #     log.error(jresp.get('code'))
    #     log.error(jresp.get('message'))
    #     resp.raise_for_status()

    trip = Trip()
    trip.legs = [Leg()]
    trip.legs[0].steps = []

    legs = jresp.get('routes')[0].get('legs')
    for leg in legs:
        steps = leg.get('steps')
        for step in steps:
            new_step = Step(distance=step.get('distance'),
                            duration=step.get('duration'),
                            start_coord=Coord(lon=step.get('geometry').get('coordinates')[0][0],
                                              lat=step.get('geometry').get('coordinates')[0][1]),
                            end_coord=Coord(lon=step.get('geometry').get('coordinates')[-1][0],
                                            lat=step.get('geometry').get('coordinates')[-1][1]))
            # OSRM makes circles on roundabouts. And makes empty step in the end. Exclude these cases from a route
            if new_step.start_coord != new_step.end_coord:
                trip.legs[0].steps.append(new_step)
        if len(trip.legs[0].steps) == 0:
            waypoints = jresp.get('waypoints')
            trip.legs[0].steps.append(Step(distance=0,
                                           duration=0,
                                           start_coord=Coord(lon=waypoints[0].get('location')[0],
                                                             lat=waypoints[0].get('location')[1]),
                                           end_coord=Coord(lon=waypoints[1].get('location')[0],
                                                           lat=waypoints[1].get('location')[1])
                                           )
                                      )
    trip.legs[0].start_coord = trip.legs[0].steps[0].start_coord
    trip.legs[0].end_coord = trip.legs[0].steps[-1].end_coord
    trip.legs[0].duration = sum([step.duration for step in trip.legs[0].steps])
    trip.legs[0].distance = sum([step.distance for step in trip.legs[0].steps])
    trip.legs[0].mode = OtpMode.DRT

    trip.distance = trip.legs[0].distance
    trip.duration = trip.legs[0].duration
    trip.main_mode = OtpMode.CAR
    return trip


def send_email(subject, text, zip_file):
    '''
    Sends an email to Sergei when simulation is done.
    If it is not working, check Google settings "login from untrusted device"

    :param subject: Subject in the email
    :param text: Body of the email
    :param zip_file: Path to a zip file that will be attached to the email
    '''
    from os.path import basename
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formatdate

    msg = MIMEMultipart()
    msg['From'] = 'drt.simulator@gmail.com'
    msg['To'] = 'sergei.dytckov@mau.se'
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    msg.attach(MIMEText(text))

    zf = open(zip_file, 'rb')
    part = MIMEApplication(zf.read(), Name=basename(zf.name))
    # After the file is closed
    part['Content-Disposition'] = 'attachment; filename={}'.format(basename(zf.name))
    msg.attach(part)

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login('drt.simulator@gmail.com', 'drtMalmoSweden')
    server.sendmail("drt.simulator@gmail.com", to_addrs="sergei.dytckov@mau.se", msg=msg.as_string())
    server.close()


def zipdir(path, ziph):
    # ziph is zipfile handle
    for root, dirs, files in os.walk(path):
        for file in files:
            ziph.write(os.path.join(root, file))


def gather_logs(config, folder, res):

    log.info('Total {} persons'.format(res.get('total_persons')))
    persons = res.get('Persons')  # List(Person)
    executed_trips = [trip for person in persons for trip in person.executed_trips]
    log.info('Executed trips: {}'.format(len(executed_trips)))
    log.info('Excluded persons due to none or a trivial path {}'
             .format(res.get('unactivatable_persons') +
                     res.get('unchoosable_persons') +
                     res.get('unplannable_persons')))
    log.info('********************************************')
    log.info('Mode share :')
    if config.get('service.modes') == 'main_modes':
        mode_list = OtpMode.get_main_modes()
        leg_list = LegMode.get_main_modes()
    else:
        mode_list = OtpMode.get_all_modes()
        leg_list = LegMode.get_all_modes()

    for mode in mode_list:
        log.info('{} {}'.format(mode, res.get('{}_trips'.format(mode))))
    log.info('DRT_trips {}'.format(res.get('DRT_trips')))
    log.info('DRT_TRANSIT_trips {}'.format(res.get('DRT_TRANSIT_trips')))

    log.info('********************************************')
    log.info('Unassigned DRT trips {}'.format(res.get('unassigned_drt_trips')))
    log.info('Undeliverable DRT trips {}'.format(res.get('undeliverable_drt')))
    log.info('Overnight DRT trips {}'.format(res.get('drt_overnight')))
    log.info('To late request to be served by DRT {}'.format(res.get('too_late_request')))
    log.info('No suitable PT stops for extra-zonal DRT trips {}'.format(res.get('no_suitable_pt_stop')))
    log.info('Too short trip for intra-zonal trip {}'.format(res.get('too_short_direct_trip')))
    log.info('No walking leg to replace {}'.format(res.get('no_suitable_pt_connection')))
    log.info('Too long DRT_PT trip comparing to whole direct trip {}'.format(res.get('too_long_pt_trip')))

    log.info('********************************************')
    log.info('Leg share :')
    for leg in leg_list:
        log.info('{} {}'.format(leg, res.get('{}_legs'.format(leg))))
    log.info('DRT_legs {}'.format(res.get('DRT_legs')))

    log.info('********************************************')

    drt_trips = []
    drt_routed = []
    drt_unassigned = []
    for person in persons:
        for ex, pl, stat in zip(person.executed_trips, person.planned_trips, person.drt_status):
            if stat == DrtStatus.routed:
                drt_trips.append((ex, person.id, stat))
            else:
                drt_trips.append((pl, person.id, stat))

    drt_vis = VisualTripWrapper([VisualTrip(trip, pid, stat.value) for trip, pid, stat in drt_trips])
    # drt_vis_unassigned = VisualTripWrapper([VisualTrip(trip, pid) for trip, pid in drt_unassigned])

    json_drt = json.loads(drt_vis.to_json())
    with open('{}/drt_routed.json'.format(folder), 'w') as outfile:
        json.dump(json_drt, outfile)

    delivered_travelers = res.get('delivered_travelers')  # type: List[int]
    vehicle_meters = res.get('vehicle_meters')  # type: List[int]

    log.info('delivered travelers per vehicle {}'.format(sum(delivered_travelers) / len(delivered_travelers)))
    log.info('Vehicle kilometers {}'.format(sum(vehicle_meters) / 1000))
    try:
        log.info('delivered travelers per Vehicle kilometers {}'
                 .format(sum(delivered_travelers) / (sum(vehicle_meters) / 1000)))
    except ZeroDivisionError:
        pass
    log.info('delivered travelers per vehicle kilometer {}'
             .format(sum(delivered_travelers) / (sum(vehicle_meters) / 1000)))

    log.info('Delivered travelers: {}'.format(delivered_travelers))
    log.info('Vehicle kilometers: {}'.format([int(vm / 1000) for vm in vehicle_meters]))

    log.info('********************************************')

    # The problem now is that I take all the direct trips even if CAR was used
    direct_trips = []
    drt_trips = []
    for person in persons:
        for drt_trip, direct_trip in zip(person.executed_trips, person.direct_trips):
            if drt_trip.main_mode in [OtpMode.DRT, OtpMode.DRT_TRANSIT]:
                direct_trips.append(direct_trip)
                drt_trips.append(drt_trip)

    direct_trips = [trip for person in persons for trip in person.direct_trips]
    direct_seconds = [trip.duration for trip in direct_trips]
    log.info('Direct minutes: {}'.format(sum(direct_seconds) / 60))
    log.info('Service hours: {}'.format(24 * config.get('drt.number_vehicles')))
    log.info('Direct minutes per service hour: {}'
             .format((sum(direct_seconds) / 60) / (24 * config.get('drt.number_vehicles'))))
    log.info(
        'Vehicle kilometer per direct minute: {}'.format((sum(vehicle_meters) / 1000) / (sum(direct_seconds) / 60)))
    travel_times = [trip.duration for trip in executed_trips]
    deviation_times = [tt - dt for tt, dt in zip(travel_times, direct_seconds)]
    log.info('Deviation time per total travel time: {}'.format(sum(deviation_times) / sum(travel_times)))

    try:
        drt_legs = [leg for trip in person.executed_trips for leg in trip.legs if leg.mode == OtpMode.DRT]
        direct_seconds_drt_only = sum([osrm_route_request(config, leg.start_coord, leg.end_coord).duration for leg in drt_legs])
        # direct_legs = [leg for trip in direct_trips for leg in trip.legs if leg.mode == OtpMode.DRT]
        # direct_seconds_drt_only = sum([leg.duration for leg in direct_legs])
        log.info('Direct minutes drt only: {}'.format(direct_seconds_drt_only / 60))
        log.info('Direct minutes drt only per service hour: {}'
                 .format((direct_seconds_drt_only / 60) / (24 * config.get('drt.number_vehicles'))))
        log.info(
            'Vehicle kilometer per direct minute drt only: {}'.format((sum(vehicle_meters) / 1000) / (direct_seconds_drt_only / 60)))

        travel_times_drt_only = sum([leg.duration for trip in executed_trips for leg in trip.legs if leg.mode == OtpMode.DRT])
        deviation_times_drt_only = travel_times_drt_only - direct_seconds_drt_only
        log.info('Deviation time per total travel time drt only: {}'.format(deviation_times_drt_only / travel_times_drt_only))
    except:
        log.error('Direct DRT minutes are probably screwed')

    pp = pprint.PrettyPrinter()
    log.info(pp.pformat(config))

    files = [config.get('sim.log')]

    if config.get('sim.create_excel'):
        try:
            xls_create_occupancy_charts(res, folder,
                                        config.get('drt.vehicle_types')
                                        .get(config.get('drt.vehicle_type'))
                                        .get('capacity_dimensions')
                                        .get(CD.SEATS))
            files.append('{}/occupancy.xlsx'.format(folder))
        except Exception as e:
            log.error('Failed to create excel file')
            log.error(e)

    files.append('{}/drt_routed.json'.format(folder))

    trip_dump = json.loads(PopulationWrapper(persons).to_json())
    with open('{}/trip_dump.json'.format(folder), 'w') as outfile:
        json.dump(trip_dump, outfile)

    files.append('{}/trip_dump.json'.format(folder))

    return files
