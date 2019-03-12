#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Dec 20 15:39:47 2018

@author: ai6644
"""

import xml.etree.ElementTree as ET

# def xml2sqlite():
#
#     et = ET.parse(self.env.config.get('population.input_file'))
#     root = self.ET.getroot()
#
#     person_list = [
#             self.parse_person_record(record)
#             for record in root.findall('person')
#     ]
#
#     def parse_person_record(self, record):
#         """
#         """
#
#         plans = [self.parse_plan(plan) for plan in record.findall('plan')]
#         p = Person(self, index=record.attrib.get('id'))
#         p.init(record.attrib, plans)
#         return p
#
#
#
#
#     def parse_plan(self, plan):
#         return [item for item in plan]