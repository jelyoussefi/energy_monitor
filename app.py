import sys
from datetime import datetime, timedelta
import time
from threading import Condition
from flask import Flask, Response, json, request, render_template, jsonify
from flaskext.mysql import MySQL
from flask import session


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

		self.interval = 12*60*60

		self.conn = self.mysql.connect()
		self.cursor = self.conn.cursor()
		self.cursor.execute("SELECT * FROM `"+self.config['table']+"`")
		rows = self.cursor.fetchall()
		self.startTime = rows[-1][1] - timedelta(seconds=self.interval)
		self.max_samples = 32
		if 'max_samples' in self.config:
			self.max_samples = self.config['max_samples']

		self.cursor.execute("SHOW columns FROM `"+self.config['table']+"`")
		self.columns = self.cursor.fetchall()

	def start(self):
		app = self.app
		@app.route('/')
		def index():
			return render_template('index.html')

		@app.route('/data')
		def data():
			return Response(self.dataHandler(), mimetype='text/event-stream')

		@app.route('/handle_command', methods = ['POST'])
		def handle_command():
			if request.method == 'POST':
				self.cv.acquire()
				
				cmd = request.get_json()
				if cmd['type'] == 'scroll_left':
					self.startTime -= timedelta(seconds=self.interval)
				elif cmd['type'] == 'scroll_right':
					self.startTime += timedelta(seconds=self.interval)
				elif cmd['type'] == 'interval':
					self.interval = cmd['value']*60

				self.cv.notify()
				self.cv.release()

			return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 

		self.app.run(host='0.0.0.0', port=str(self.config['port']), threaded=True)

	def getData(self):
		endTime = self.startTime +  timedelta(seconds=self.interval)
		print("\n\t Interval {} -> {}\n".format(self.startTime, endTime))
		self.cursor.execute("SELECT * FROM `"+self.config['table']+"` WHERE date between timestamp \""+ str(self.startTime) + "\" and timestamp \""+str(endTime)+"\"")
		return self.cursor.fetchall()

	def getDataByLabel(self, datasets, label):
		for ds in datasets:
			if 'label' in ds and ds['label'] == label:
				return ds['data']
		return None

	def dataHandler(self): 
		self.cv.acquire()
		while True:
			data = {}
			print("\n--------------------------------------------------------------------->")
			rows = self.getData()
			if len(rows) > 0:
				samples_step = int(len(rows)/self.max_samples) if len(rows) > self.max_samples else 1

				labels = list()
				for r in range(0, len(rows), samples_step):
					labels.append(rows[r][1])

				data['labels'] = labels;
				data['datasets'] = []

				for c in range(2, len(self.columns)):
					data['datasets'].append({'label':self.columns[c][0], 'data': [], 'dotted': False})
				for row in rows:
					for c in range(2, len(self.columns)):
						data['datasets'][c-2]['data'].append(row[c]/self.getScale(self.columns[c][0]))
				if samples_step > 1:
					for c in range(2, len(self.columns)):
						data['datasets'][c-2]['data'] = self.subsample(data['datasets'][c-2]['data'], samples_step)
				u_data = self.getDataByLabel(data['datasets'], 'I1')
				if u_data is not None:
					for i in range(0, len(data['datasets'])):
						i_data = self.getDataByLabel(data['datasets'], "I"+str(i))
						c_data = self.getDataByLabel(data['datasets'], "C"+str(i))
						if i_data is not None and c_data is not None:
							power = [abs(u * i * c) for u, i, c in zip(u_data, i_data, c_data)]
							data['datasets'].append({'label': 'P'+str(i), 'data': power, 'borderDash': [10,10]})
							
				yield f"data:{json.dumps(data)}\n\n"
				time.sleep(0.5)
			else:
				print("------------------------- Empty -------------------")

			self.cv.wait()
		
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
