
import logging
import math
import numpy as np

from const import OtpMode, LegMode
from sim_utils import Trip

log = logging.getLogger(__name__)


class TimeWindowsModeChoice(object):
    """Uses travel time to choose
    PT vs DRT - choose the fastest
    PT vs CAR - choose based on PT time window
    """
    def __init__(self, person):
        self.env = person.env
        self.person = person

    def satisfies_hard_restrictions(self, trip):
        if not self.person.driving_license and trip.main_mode in [OtpMode.CAR, OtpMode.PARK_RIDE]:
            log.debug('{} does not have a licence to go by car'.format(self.person.scope))
            return False
        else:
            return True

    def choose(self, alternatives):
        filtered_alternatives = []
        for trip in alternatives:
            if not self.satisfies_hard_restrictions(trip):
                continue
            filtered_alternatives.append(trip)

        if len(filtered_alternatives) != 0:
            return self._choice_model(filtered_alternatives)
        else:
            return None

    def _choice_model(self, alternatives):
        """
        :type alternatives: [Trip]
        """
        times = []
        for alt in alternatives:
            if alt.main_mode in [OtpMode.CAR]:
                times.append(self.person.get_max_trip_duration(self.person.direct_trip.duration))
            else:
                times.append(alt.duration)
        return min(zip(times, alternatives), key=lambda x: x[0])[1]


class DefaultModeChoice(object):
    """MNL model from
    2019 A framework to integrate mode choice in the design of mobility-on-demand systems
    Authors: lYang Liu Prateek Bansal Ricardo Daziano Samitha Samaranayake"""

    def __init__(self, person):
        self.env = person.env
        self.person = person

    def choose(self, alternatives):
        filtered_alternatives = []
        for trip in alternatives:
            if not self.satisfies_hard_restrictions(trip):
                trip.utility = None
                continue
            filtered_alternatives.append(trip)

        pt_alt = [alt for alt in filtered_alternatives
                  if alt.main_mode in [OtpMode.DRT_TRANSIT, OtpMode.DRT, OtpMode.TRANSIT, OtpMode.WALK]]
        car_alt = [alt for alt in filtered_alternatives if alt.main_mode in [OtpMode.CAR, OtpMode.PARK_RIDE]]
        filtered_alternatives = []
        if len(pt_alt) > 0:
            filtered_alternatives.append(min(pt_alt, key=lambda a: a.duration))
        if len(car_alt) > 0:
            filtered_alternatives.append(min(car_alt, key=lambda a: a.duration))

        utilities = []
        for trip in filtered_alternatives:
            utilities.append(self.calc_utility(trip))

        if len(filtered_alternatives) != 0:
            probabilities = self.mnl(utilities)
            return self.montecarlo(filtered_alternatives, probabilities)
        else:
            return None

    def satisfies_hard_restrictions(self, trip):
        if not self.person.driving_license and trip.main_mode in [OtpMode.CAR, OtpMode.PARK_RIDE]:
            log.debug('{} does not have a licence to go by car'.format(self.person.scope))
            return False
        else:
            return True

    def calc_utility(self, trip):
        """Computes utility values.
        TODO: waiting time is treated as out of vehicle time - find a better model
        TODO: transfer time is not in the model
        TODO: initial waiting time (or arriving too early) is not in the model
        TODO: make a model class to be added to config
        """
        vot = {LegMode.CAR: -0.023/60,
               LegMode.BUS: -0.023/60,
               LegMode.RAIL: -0.023/60,
               LegMode.TRAM: -0.023/60,
               LegMode.DRT: -0.023/60,

               LegMode.WALK: -0.032/60,
               }
        asc = {
            OtpMode.CAR: 0,
            OtpMode.TRANSIT: -0.8,
            OtpMode.WALK: -0.8,
            OtpMode.DRT: -0.8,
            OtpMode.DRT_TRANSIT: -0.8
        }
        cost_beta = -0.074/60
        car_cost = 2.79
        if self.person.is_local_trip():
            pt_cost = 27
        else:
            pt_cost = 51
        try:
            s = sum([leg.duration*vot.get(leg.mode) for leg in trip.legs])
            if len(trip.legs) > 1:
                for l1, l2 in zip(trip.legs[0:], trip.legs[1:]):
                    if l1.end_time != l2.start_time:
                        log.debug('Person {}. Trip has waiting time that is not a leg {}'
                                  .format(self.person.id, trip))
                        s += (l2.start_time - l1.end_time)*vot[LegMode.WALK]
            if trip.main_mode == LegMode.CAR:
                car_dist = [leg.distance for leg in trip.legs if leg.mode == LegMode.CAR]
                cost = sum([d/1000*car_cost for d in car_dist])
            else:
                cost = pt_cost
            s += cost_beta*cost
            s += asc.get(trip.main_mode)
            return s
        except:
            print([leg.mode for leg in trip.legs])
            raise Exception('wrong math in MNL')

    @staticmethod
    def mnl(utility):
        s = sum([math.exp(u) for u in utility])
        prob = [math.exp(u) / s for u in utility]
        return prob

    @staticmethod
    def montecarlo(alternatives, prob):
        if sum(prob) < 0.99999998:
            print(alternatives)
            raise Exception('Probability is not 1, but {}'.format(sum(prob)))

        return np.random.choice(alternatives, p=prob)
