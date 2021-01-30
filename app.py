import sys
from datetime import datetime, timedelta
import time
from threading import Condition
from flask import Flask, Response, json, request, render_template, jsonify
from flask_bootstrap import Bootstrap
from flask_wtf import Form
from wtforms.fields import StringField, DateField, SubmitField
from flaskext.mysql import MySQL
from flask import session
import numpy as np
import requests
from json2html import *


class EnergyMonitor():
	def __init__(self, config_path=None):
		with open(config_path) as json_file:
			self.config = json.load(json_file)
		
		self.cv = Condition()

		self.mysql = MySQL()
		self.app = Flask(__name__)
		self.app.config['SESSION_TYPE'] = 'memcached'
		self.app.secret_key = 'My secret key?'

		self.app.config['MYSQL_DATABASE_USER'] = self.config['user']
		self.app.config['MYSQL_DATABASE_PASSWORD'] = self.config['password']
		self.app.config['MYSQL_DATABASE_DB'] = self.config['database']
		self.app.config['MYSQL_DATABASE_HOST'] = self.config['server']
		self.mysql.init_app(self.app)

		self.interval = 24*60*60

		self.conn = self.mysql.connect()
		self.cursor = self.conn.cursor()
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

		self.cursor.execute("SHOW columns FROM `"+self.config['table']+"`")
		self.columns = self.cursor.fetchall()
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

		@app.route('/production', methods=['GET', 'POST'])
		def production():
			if request.method == 'GET':
				prod_url = "http://{}/production.json".format(self.config['ip'])
				production = requests.get(prod_url)
				production_json = json2html.convert(json=json.loads(production.text))

				return render_template("json_template.html", json_data=production_json)

		self.app.run(host='0.0.0.0', port=str(self.config['port']), threaded=True)

		


	def getData(self):
		endTime = self.endTime
		if endTime is None:
			self.cursor.execute("SELECT * FROM `"+self.config['table']+"`")
			rows = self.cursor.fetchall()
			endTime = rows[-1][1]
		startTime = endTime -  timedelta(seconds=self.interval)

		print("\n\t Interval {} -> {}".format(startTime, self.endTime))
		self.cursor.execute("SELECT * FROM `"+self.config['table']+"` WHERE date between timestamp \""+ str(startTime) + "\" and timestamp \""+str(endTime)+"\"")
		return (self.cursor.fetchall(),endTime)

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
				
				for c in range(2, len(self.columns)):
					data['datasets'].append({'label':self.columns[c][0], 'data': []})
				for row in rows:
					for c in range(2, len(self.columns)):
						data['datasets'][c-2]['data'].append(row[c]/self.getScale(self.columns[c][0]))
				
				u_data = self.getDataByLabel(data['datasets'], 'U')
				if u_data is not None:
					u_data['borderColor'] = self.colors[0]
					dt = (self.interval)/3600.0
					u_scale = self.getScale("U")
					if u_scale != 1:
						u_data['label'] = "{}: 1/{}".format(u_data['label'], u_scale)
					for i in range(0, len(data['datasets'])):
						i_data = self.getDataByLabel(data['datasets'], "I"+str(i))
						c_data = self.getDataByLabel(data['datasets'], "C"+str(i))
						if i_data is not None and c_data is not None:
							color = self.colors[i+1]
							i_data['borderColor'] = c_data['borderColor'] = color
							c_data['borderDash'] = [10,5]
							power = [abs(u * i * c * self.k) for u, i, c in zip(u_data['data'], i_data['data'], c_data['data'])]
							integral = (np.trapz(power, dx=dt/len(power))*u_scale)/1000
							integral = (int(integral*100)/100)
							label = ' P'+str(i)
							if integral > 0:
								label += ": {:.2f} kWh ".format(integral)
								data['datasets'].append({'label': label, 'data': power, 
									  'borderColor': color, 'borderDash': [0,10], 'borderCapStyle' : 'round'})
							
				samples_step = int(len(rows)/self.max_samples) if len(rows) > self.max_samples else 1

				labels = list()
				for r in range(0, len(rows), samples_step):
					labels.append(rows[r][1])
				data['labels'] = labels;

				if samples_step > 1:
					for ds in data['datasets']:
						ds['data'] = self.subsample(ds['data'], samples_step)
					

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
