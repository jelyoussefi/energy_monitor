import sys
import numpy as np
from datetime import datetime, timedelta
import time
from threading import Condition
from flask import Flask, Response, json, request, render_template, jsonify
from flask_bootstrap import Bootstrap
from flask_wtf import Form
from wtforms.fields import StringField, DateField, SubmitField
from flask import session

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Table, Column, Float, DateTime, MetaData
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


class EnergyMonitor():
	def __init__(self, config_path=None):
		with open(config_path) as json_file:
			self.config = json.load(json_file)
		
		self.cv = Condition()

		self.app = Flask(__name__)
		self.app.config['SESSION_TYPE'] = 'memcached'
		self.app.secret_key = 'My secret key?'

		engine = create_engine(self.config['database'], connect_args={'check_same_thread': False}, echo = False)
		meta.create_all(engine)
		self.session = sessionmaker(bind=engine)();

		self.interval = 24*60*60

		self.startTime = self.endTime = None
		self.max_samples = 32
		self.refresh_time = 10
		self.k = 1
		if 'max_samples' in self.config:
			self.max_samples = self.config['max_samples']

		if 'refresh_time' in self.config:
			self.refresh_time = self.config['refresh_time']

		if 'k' in self.config:
			self.k = self.config['k']

		self.columns = [ col.name for col in energy.c ]
			
		self.colors = ["rgb(250,0,0)", "rgb(0,255,0)", "rgb(0,0,255)", "rgb(0,0,0)", "rgb(253,108,158",
					"rgb(0,255,255)", "rgb(255,255,0)", "rgb(255,0,255)", "rgb(127,0,255)", "rgb(248,152,85)"]

	def start(self):
		class DatePickerForm(Form):
			startTime = StringField("Start", id='startDatePicker')
			endTime = StringField("Stop", id='endDatePicker')
			submit = SubmitField('Submit')

		app = self.app
		Bootstrap(app)
		@app.route('/', methods=['GET', 'POST'])
		def index():
			form = DatePickerForm()
			if request.method == "POST" and form.validate():
				self.cv.acquire()
				startTime = None
				endTime = None
				if form.startTime.data:
					startTime = datetime.strptime(form.startTime.data, '%m/%d/%Y %H:%M %p')
				if form.endTime.data:
					endTime = datetime.strptime(form.endTime.data, '%m/%d/%Y %H:%M %p')

				self.endTime = endTime

				if self.endTime is not None:
					if startTime is not None:
						self.integral = (self.endTime-startTime).total_seconds()
				self.cv.notify()
				self.cv.release()

				return ('', 204)

			return render_template('index.html', form=form)

		@app.route('/data')
		def data():
			return Response(self.dataHandler(), mimetype='text/event-stream')

		@app.route('/handle_command', methods = ['POST'])
		def handle_command():
			if request.method == 'POST':
				self.cv.acquire()
				if self.endTime is not None:
					cmd = request.get_json()
					if cmd['type'] == 'scroll_left':
						self.endTime -= timedelta(seconds=3600)
					elif cmd['type'] == 'scroll_right':
						self.endTime += timedelta(seconds=3600)
					
					self.cv.notify()
				self.cv.release()

			return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 	

		self.app.run(host='0.0.0.0', port=str(self.config['port']))

	def getData(self):

		
		endTime = self.endTime
		if endTime is None:
			rows = self.session.query(energy).all();
			endTime = rows[-1][0]

			
		startTime = endTime -  timedelta(seconds=self.interval)

		print("\n\t Interval {} -> {}".format(startTime, self.endTime))
		rows = self.session.query(energy).filter(energy.c.Date>=startTime).all()
		return (rows,endTime)

	def getDataByLabel(self, datasets, label):
		for ds in datasets:
			if 'label' in ds and ds['label'] == label:
				return ds
		return None

	def dataHandler(self): 
		self.cv.acquire()
		while True:
			data = {}
			data['labels'] = []
			data['datasets'] = []
			data['title'] = ""
			rows,endTime = self.getData()
			if len(rows) > 0:
				
				for c in range(1, len(self.columns)):
					data['datasets'].append({'label':self.columns[c], 'borderColor' : self.colors[c], 'data': []})

				for row in rows:
					data['labels'].append(row[0])
					for c in range(1, len(self.columns)):
						data['datasets'][c-1]['data'].append(row[c])
				

			else:
				data['labels'].append(self.endTime - timedelta(seconds=self.interval))
				data['labels'].append(self.endTime)
				data['datasets'].append({'label': 'Empty', 'data' : [0,0]})
			if endTime is not None:
				data['endTime'] = endTime;
				data['startTime'] = endTime - timedelta(seconds=self.interval)
			self.cv.release()

			yield f"data:{json.dumps(data)}\n\n"
			self.cv.acquire()

			self.cv.wait(self.refresh_time)
		
		self.cv.release()

	def getScale(self, column):
		scale = 1
		if 'scales' in self.config and column in self.config['scales']:
			scale = self.config['scales'][column]
		return scale;


	def subsample(self, data, sample_size):
		samples = list(zip(*[iter(data)]*sample_size)) 
		return list(map(lambda x:sum(x)/float(len(x)), samples))


if __name__ == "__main__":
	config_path = "./config.js"
	if len(sys.argv) == 2:
		config_path = sys.argv[1]
	energyMonitor = EnergyMonitor(config_path)
	energyMonitor.start()
