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

log = logging.getLogger(__name__)

router = otp.getRouter('skane')

# Create a default request for a given time
req = otp.createRequest()
req.setDateTime(2018, 11, 14, 10, 00, 00)
req.setMaxTimeSec(10000)
req.setModes('CAR')
# req.setWalkSpeedMs(2)

# The file points.csv contains the columns GEOID, X and Y.
file_name = '/home/ai6644/Malmo/Tools/DRTsim/data/points.csv'
points = []
matrixCsv = otp.createCSVOutput()
population = otp.createEmptyPopulation()
# matrixCsv.setHeader(['Origin', 'Destination', 'Travel_time', 'Walk_distance'])
# first_line = True
with open(file_name, 'r') as file:
    csvreader = csv.reader(file, delimiter=',')
    # row = ['GEOID_from', 'lat_from', 'lon_from', 'GEOID_to', 'lat_to', 'lon_to']
    for row in csvreader:
        # print(row)
        # if first_line:
        #     first_line = False
        #     continue
        req.setOrigin(float(row[1]), float(row[2]))
        req.setDestination(float(row[4]), float(row[5]))
        path = router.plan2(req)
        if path is None:
            print('Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))
            matrixCsv.addRow([row[0], row[3], 0, 0])
            continue
            # matrixCsv.addRow([row[0], row[3], 0, 0])
            # log.warning('Trivial path found from {},{} to {},{}. Setting 0 length and duration'.format(row[1], row[2], row[4], row[5]))


        # if path is None:
        #     print(row[0], row[3], 'Cannot be routed')
        #     matrixCsv.addRow([row[0], row[3], sys.float_info.max, sys.float_info.max])
        #     continue
        dist = 0
        for state, forward_state in zip(path.states[:-1], path.states[1:]):
            if forward_state.getBackEdge() is not None:
                #              print(state.getBackEdge().getDistance())
                dist += forward_state.getBackEdge().getDistance()
        # print(dist)
        matrixCsv.addRow([row[0], row[3], path.getDuration(), dist])

# Save the result
matrixCsv.save('/home/ai6644/Malmo/Tools/DRTsim/data/time_distance_matrix_otp.csv')
