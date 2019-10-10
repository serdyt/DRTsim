#!/usr/bin/env jython
"""
Created on Thu Feb  7 11:21:49 2019

@author: ai6644
"""

"""See multithread version as well
https://github.com/rafapereirabr/otp-travel-time-matrix/blob/master/python_script_loopHM_parallel.py
"""

"""
use it on server with OTP_script_test.py
"""

import csv
import sys
import logging
import java.lang.Exception
import org.opentripplanner.routing.error.TrivialPathException
import org.opentripplanner.routing.core.RoutingRequest
import org.opentripplanner.routing.impl.GraphPathFinder
import org.slf4j.LoggerFactory

# log = logging.getLogger(__name__)
# handler = logging.handlers.WatchedFileHandler('/home/ai6644/Malmo/tools/DRTsim/output/log')
# formatter = logging.Formatter(logging.BASIC_FORMAT)
# handler.setFormatter(formatter)
# log.setLevel(logging.DEBUG)
# log.addHandler(handler)

# log = org.slf4j.LoggerFactory.getLogger(org.opentripplanner.scripting.api.OtpsRouter)

router = otp.getRouter('skane')

# Create a default request for a given time
req = otp.createRequest()
req.setDateTime(2018, 11, 14, 10, 00, 00)
req.setMaxTimeSec(10000)
req.setModes('CAR')
# req.setWalkSpeedMs(2)

# The file points.csv contains the columns GEOID, X and Y.
file_name = '/home/ai6644/Malmo/Tools/DRTsim/data/points.csv'
log_file = '/home/ai6644/Malmo/Tools/DRTsim/output/log'
LOG = None
points = []
matrixCsv = otp.createCSVOutput()
population = otp.createEmptyPopulation()
# matrixCsv.setHeader(['Origin', 'Destination', 'Travel_time', 'Walk_distance'])
with open(file_name, 'r') as file:
    csvreader = csv.reader(file, delimiter=',')
    # row = ['GEOID_from', 'lat_from', 'lon_from', 'GEOID_to', 'lat_to', 'lon_to']
    for row in csvreader:
        req.setOrigin(float(row[1]), float(row[2]))
        req.setDestination(float(row[4]), float(row[5]))
        try:
            path = router.plan2(req)
            # this guy is protected
            # req2 = req.req.clone()
            # req2.batch = False
            # req2.setRoutingContext(router.graph)
            # gpFinder = GraphPathFinder(router)
            # newPaths = gpFinder.getPaths(req2)
            # if newPaths.isEmpty():
            #     path = None
            # else:
            #     path = newPaths.get(0)

            dist = 0
            for state, forward_state in zip(path.states[:-1], path.states[1:]):
                if forward_state.getBackEdge() is not None:
                    #              print(state.getBackEdge().getDistance())
                    dist += forward_state.getBackEdge().getDistance()
            # print(dist)
            matrixCsv.addRow([row[0], row[3], path.getDuration(), dist])
        except org.opentripplanner.routing.error.TrivialPathException as e:
            # print('Trivial path found from {},{} to {},{}. Setting zero length and duration'.format(row[1], row[2], row[4], row[5]))
            matrixCsv.addRow([row[0], row[3], 0, 0])
            if LOG is None:
                LOG = open(log_file, 'a')
            LOG.write('WARNING: Trivial path found from {},{} to {},{}. Setting 0 length and duration\n'
                      .format(str(row[1]), str(row[2]), str(row[4]), str(row[5])))
            # LOG.println('WARNING: Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))
            # log.warn('Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))
            continue
        except org.opentripplanner.routing.error.PathNotFoundException as e:
            # print('No path found from {},{} to {},{}. Setting infinite length and duration'.format(row[1], row[2], row[4], row[5]))
            if LOG is None:
                LOG = open(log_file, 'a')
            LOG.write('WARNING: No path found from {},{} to {},{}. Setting infinite length and duration\n'
                      .format(str(row[1]), str(row[2]), str(row[4]), str(row[5])))
            # log.warn('No path found from {},{} to {},{}. Setting infinite length and duration'.format(row[1], row[2], row[4], row[5]))
            matrixCsv.addRow([row[0], row[3], sys.maxint, sys.maxint])
        except Exception as e:
            print('Unexpected error')
            print(e)
            print(e.args)
            raise

        # if path is None:
        #     print('Trivial path found from {},{} to {},{}. Setting zero length and duration'.format(row[1], row[2], row[4], row[5]))
        #     matrixCsv.addRow([row[0], row[3], 0, 0])
        #     # log.warning('Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))
        #     continue

        # if path is None:
        #     print(row[0], row[3], 'Cannot be routed')
        #     matrixCsv.addRow([row[0], row[3], sys.float_info.max, sys.float_info.max])
        #     continue

# Save the result
matrixCsv.save('/home/ai6644/Malmo/Tools/DRTsim/data/time_distance_matrix_otp.csv')
if LOG is not None:
    LOG.close()
