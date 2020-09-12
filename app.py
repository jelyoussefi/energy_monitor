from datetime import datetime, timedelta
import time
from threading import Condition
from flask import Flask, Response, json, request, render_template, jsonify
from flaskext.mysql import MySQL
from flask import session


class EnergyMonitor():
	def __init__(self, config_path=None):
		with open('./config.js') as json_file:
			self.config = json.load(json_file)
		
		self.cv = Condition()

		self.mysql = MySQL()
		self.app = Flask(__name__)
		self.app.config['SESSION_TYPE'] = 'memcached'
		self.app.secret_key = 'My secret key?'

		self.app.config['MYSQL_DATABASE_USER'] = self.config['user']
		self.app.config['MYSQL_DATABASE_PASSWORD'] = self.config['password']
		self.app.config['MYSQL_DATABASE_DB'] = self.config['database']
		self.app.config['MYSQL_DATABASE_HOST'] = 'localhost'
		self.mysql.init_app(self.app)

		self.conn = self.mysql.connect()
		self.cursor = self.conn.cursor()
		self.cursor.execute("SELECT * FROM `"+self.config['table']+"`")
		rows = self.cursor.fetchall()
		self.startTime = rows[0][1]
		self.interval = 5*60

		self.cursor.execute("SHOW columns FROM `energie10`")
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
					self.interval = cmd['value']

				self.cv.notify()
				self.cv.release()

			return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 

		self.app.run(host='0.0.0.0', port=str(self.config['port']), threaded=True)

	def getData(self):
		endTime = self.startTime +  timedelta(seconds=self.interval)
		print("\n\t Interval {} -> {}\n".format(self.startTime, endTime))
		self.cursor.execute("SELECT * FROM `"+self.config['table']+"` WHERE date between timestamp \""+ str(self.startTime) + "\" and timestamp \""+str(endTime)+"\"")
		return self.cursor.fetchall()

	def dataHandler(self): 
		self.cv.acquire()
		while True:
			data = {}
			print("\n--------------------------> Processing New Data ... ")
			rows = self.getData()

			labels = list()
			for row in rows:
				labels.append(row[1])

			data['labels'] = labels;
			data['datasets'] = []
			for c in range(2, len(self.columns)):
				data['datasets'].append({'label':self.columns[c][0], 'data': []})

			for row in rows:
				for c in range(2, len(self.columns)):
					value = row[c];
					data['datasets'][c-2]['data'].append(value)
	       	
			yield f"data:{json.dumps(data)}\n\n"
			print("--------------------------> New Data submitted ")
			self.cv.wait()
		
		self.cv.release()
	        

if __name__ == "__main__":
    energyMonitor = EnergyMonitor()
    energyMonitor.start()
