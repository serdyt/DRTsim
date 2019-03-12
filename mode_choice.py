
import logging
import math
import random

from const import OtpMode, LegMode


class default_mode_choice(object):

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
            self.person.trip = self.montecarlo(filtered_alternatives)

    def satisfies_hard_restrictions(self, trip):
        if not self.person.driving_license and trip.main_mode in [OtpMode.CAR, OtpMode.PARK_RIDE]:
            logging.debug('{} does not have a licence to go by car'.format(self.person.scope))
            return False
        else:
            return True

    def calc_utility(self, trip):
        """Pretty much random numbers so far
        TODO: make a model class to be added to config
        """
        VOT = {LegMode.CAR: 0.010,
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
                s = sum([leg.duration/1000*VOT.get(leg.mode) for leg in trip.legs])
            else:
                s = trip.duration/1000*VOT.get(trip.main_mode)
        except RuntimeError:
            print([leg.mode for leg in trip.legs])
            raise Exception('wrong math')
        return s

    def mnl(self, alternatives):
        s = sum([math.exp(trip.utility) for trip in alternatives])
        for trip in alternatives:
            trip.prob = math.exp(trip.utility) / s

    def montecarlo(self, alternatives):
        # use numpy random choice
        if sum([trip.prob for trip in alternatives]) < 0.99999998:
            print(alternatives)
            raise Exception('Probability is not 1, but {}'.format(sum([trip.prob for trip in alternatives])))
        r = random.uniform(0, 1)
        c = 0.0
        for trip in alternatives:
            c += trip.prob
            if c > r:
                return trip
        raise Exception('Montecarlo failed')
