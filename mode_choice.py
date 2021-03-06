
import logging
import math

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
                times.append(alt.duration * self.person.time_window_multiplier + self.person.time_window_constant)
            else:
                times.append(alt.duration)
        return min(zip(times, alternatives), key=lambda x: x[0])[1]


class DefaultModeChoice(object):
    """Supposed to be using MNL, but takes DRT if possible with 99.9%"""

    def __init__(self, person):
        self.env = person.env
        self.person = person

    def choose(self, alternatives):
        filtered_alternatives = []
        for trip in alternatives:
            if not self.satisfies_hard_restrictions(trip):
                trip.utility = None
                continue
            trip.utility = self.calc_utility(trip)
            filtered_alternatives.append(trip)

        if len(filtered_alternatives) != 0:
            self.mnl(filtered_alternatives)
            return self.montecarlo(filtered_alternatives)
        else:
            return None

    def satisfies_hard_restrictions(self, trip):
        if not self.person.driving_license and trip.main_mode in [OtpMode.CAR, OtpMode.PARK_RIDE]:
            log.debug('{} does not have a licence to go by car'.format(self.person.scope))
            return False
        else:
            return True

    @staticmethod
    def calc_utility(trip):
        """Pretty much random numbers so far
        TODO: make a model class to be added to config
        """
        vot = {LegMode.CAR: 0.010,
               LegMode.BUS: 0.005,
               LegMode.RAIL: 0.005,
               LegMode.TRAM: 0.005,
               LegMode.WALK: 0.0005,
               LegMode.BICYCLE: 0.0007,
               LegMode.SUBWAY: 0.005,
               LegMode.BICYCLE_RENT: 0.004,
               LegMode.DRT: 10
               }
        try:
            if len(trip.legs) > 0:
                s = sum([leg.duration/1000*vot.get(leg.mode) for leg in trip.legs])
            else:
                s = trip.duration/1000*vot.get(trip.main_mode)
        except RuntimeError:
            print([leg.mode for leg in trip.legs])
            raise Exception('wrong math in MNL')
        return s

    @staticmethod
    def mnl(alternatives):
        s = sum([math.exp(trip.utility) for trip in alternatives])
        for trip in alternatives:
            trip.prob = math.exp(trip.utility) / s

    def montecarlo(self, alternatives):
        # use numpy random choice
        if sum([trip.prob for trip in alternatives]) < 0.99999998:
            print(alternatives)
            raise Exception('Probability is not 1, but {}'.format(sum([trip.prob for trip in alternatives])))
        r = self.env.rand.uniform(0, 1)
        c = 0.0

        for a in alternatives:
            if a.main_mode in OtpMode.get_drt_modes():
                return a
        for a in alternatives:
            if a.main_mode == OtpMode.CAR:
                return a

        for trip in alternatives:
            c += trip.prob
            if c > r:
                return trip
        raise Exception('Montecarlo failed')
