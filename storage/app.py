import sys
from datetime import datetime, timedelta
import time 
import json
from threading import Thread, Condition
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from json2html import *

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Table, Column, String, Integer, Float, MetaData
from sqlalchemy.orm import sessionmaker

meta = MetaData()

energy = Table(
   'energy', meta, 
   Column('Us', Float), 
   Column('Ub', Float),
   Column('Ui', Float),
   Column('Is', Float), 
   Column('Ib', Float),
   Column('Ii', Float),
)


class EnergyMonitorStorage():
	def __init__(self, config_path=None):
		with open(config_path) as json_file:
			self.config = json.load(json_file)
		
		self.cv = Condition()
		self.running = False
		self.interval = 5
		if 'interval' in self.config:
			self.interval = self.config['interval']

		self.engine = create_engine('sqlite:///energy_monitoring.db', echo = True)
		meta.create_all(self.engine)
		self.conn = self.engine.connect()
	
	def start(self):
		self.cv.acquire()
		self.running = True
		while (self.running):
			self.cv.wait(self.interval)
			url ="http://{}".format(self.config['arduino']['ip'])
			results = requests.get(url)
			ins = energy.insert().values(
								  		Us=results['Tensions']['Us'],Ub=results['Tensions']['Ub'], Ui=results['Tensions']['Ui'],
								  		Is=results['Courants']['Is'],Ub=results['Courants']['Ib'], Ui=results['Courants']['Ii'],
										)
			result = self.conn.execute(ins)

		self.cv.release()

	def stop(self):
		self.cv.acquire()
		if self.running:
			self.running = False;
			self.cv.notify()
		self.cv.release()

if __name__ == "__main__":
	config_path = "./config.js"
	if len(sys.argv) == 2:
		config_path = sys.argv[1]
	energyMonitorStorage = EnergyMonitorStorage(config_path)
	energyMonitorStorage.start()
