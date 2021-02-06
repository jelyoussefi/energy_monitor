import sys
from datetime import datetime
import time 
import json
from threading import Thread, Condition
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from json2html import *

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Table, Column, String, Integer, Float, DateTime, MetaData
from sqlalchemy.orm import sessionmaker

meta = MetaData()

energy = Table(
   'energy', meta, 
   Column('Date', DateTime),
   Column('Us', Float), 
   Column('Ub', Float),
   Column('Ui', Float),
   Column('Is', Float), 
   Column('Ib', Float),
   Column('Ii', Float),
   Column('PInv_0', Float),
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

		self.engine = create_engine(config['database'], echo = True)
		meta.create_all(self.engine)
		self.conn = self.engine.connect()
	
	def get(self, url, auth=None):
			if auth is None:
				results = requests.get(url)
			else:
				results = requests.get(url, auth=auth)
			return json.loads(results.text)

	def start(self):
		self.cv.acquire()
		self.running = True
		while (self.running):
			self.cv.wait(self.interval)
			res_arduino = get("http://{}".format(self.config['arduino']['ip']))
			res_envoy = get("http://{}/api/v1/production/inverters".format(self.config['envoy']['ip']),
							HTTPDigestAuth('envoy', self.config['envoy']['sid']))
			print(res_envoy)	
			ins = energy.insert().values(
										Date=datetime.now(),
								  		Us=res_arduino['Us'],Ub=res_arduino['Ub'], Ui=res_arduino['Ui'],
								  		Is=res_arduino['Is'],Ib=res_arduino['Ib'], Ii=res_arduino['Ii'],
										PInv_0=res_envoy[0]['lastReportWatts']
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
