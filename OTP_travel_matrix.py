
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
import org.opentripplanner.routing.error.TrivialPathException as TrivialPathException
import org.opentripplanner.routing.error.PathNotFoundException as PathNotFoundException

import sys

router = otp.getRouter('skane')

# Create a default request for a given time
req = otp.createRequest()
req.setDateTime(2018, 11, 14, 10, 00, 00)
req.setMaxTimeSec(10000)
req.setModes('CAR')
# req.setWalkSpeedMs(2)

# HOME = java.lang.System.getProperty("user.home")
# The file points.csv contains the columns GEOID, X and Y.
file_name = '{}/points.csv'.format(workdir)
log_file = '{}/log'.format(workdir)
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

            dist = 0
            for state, forward_state in zip(path.states[:-1], path.states[1:]):
                if forward_state.getBackEdge() is not None:
                    dist += forward_state.getBackEdge().getDistance()
            # print(dist)
            matrixCsv.addRow([row[0], row[3], path.getDuration(), dist])
        except TrivialPathException as e:
            # print('Trivial path found from {},{} to {},{}. Setting zero length and duration'.format(row[1], row[2], row[4], row[5]))
            matrixCsv.addRow([row[0], row[3], 0, 0])
            if LOG is None:
                LOG = open(log_file, 'a')
            LOG.write('WARNING: Trivial path found from {},{} to {},{}. Setting 0 length and duration\n'
                      .format(str(row[1]), str(row[2]), str(row[4]), str(row[5])))
            # LOG.println('WARNING: Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))
            # log.warn('Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))
            continue
        except PathNotFoundException as e:
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

# Save the result
matrixCsv.save('{}/time_distance_matrix_otp.csv'.format(workdir))
if LOG is not None:
    LOG.close()
