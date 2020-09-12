from datetime import datetime, timedelta
import time
from threading import Condition
from flask import Flask, Response, json, request, render_template, jsonify
from flask import Markup
from flaskext.mysql import MySQL
#from werkzeug import generate_password_hash, check_password_hash
from flask import session


mysql = MySQL()
app = Flask(__name__)
app.config['SESSION_TYPE'] = 'memcached'
app.secret_key = 'My secret key?'

# MySQL configurations
app.config['MYSQL_DATABASE_USER'] = 'jamal'
app.config['MYSQL_DATABASE_PASSWORD'] = 'Jamal$1969'
app.config['MYSQL_DATABASE_DB'] = 'awahid_db'
app.config['MYSQL_DATABASE_HOST'] = 'localhost'
mysql.init_app(app)

startTime = None
interval = 5*60
cv = Condition()


@app.route('/')
def index():
	return render_template('index.html')

@app.route('/data')
def data():
	return Response(dataHandler(), mimetype='text/event-stream')

@app.route('/handle_command', methods = ['POST'])
def handle_command():
	if request.method == 'POST':
		global startTime, interval, cv
		cv.acquire()
		cmd = request.get_json()
		if cmd['type'] == 'scroll_left':
			startTime -= timedelta(seconds=interval)
		elif cmd['type'] == 'scroll_right':
			startTime += timedelta(seconds=interval)

		cv.notify()
		cv.release()

	return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 


def getData(cursor, startTime, interval):
	endTime = startTime +  timedelta(seconds=interval)
	print("--------- data {} : {}".format(startTime, endTime))
	cursor.execute("SELECT * FROM `energie10` WHERE date between timestamp \""+ str(startTime) + "\" and timestamp \""+str(endTime)+"\"")
	return cursor.fetchall()

def dataHandler(): 
	global startTime, interval, cv
	conn = mysql.connect()
	cursor = conn.cursor()

	#yield f"data:{json.dumps({'reset': 'on'})}\n\n"
	cursor.execute("SELECT * FROM `energie10`")
	rows = cursor.fetchall()
	startTime = rows[0][1]

	cursor.execute("SHOW columns FROM `energie10`")

	columns = cursor.fetchall()

	while True:
		cv.acquire()
		data = {}
		print("-------------------------- New Data ")
		rows = getData(cursor, startTime, interval)
		labels = list()
		for row in rows:
			labels.append(row[1])

		data['labels'] = labels;
		data['datasets'] = []
		for c in range(2, len(columns)):
			data['datasets'].append({'label':columns[c][0], 'data': []})

		for row in rows:
			for c in range(2, len(columns)):
				value = row[c];
				data['datasets'][c-2]['data'].append(value)
       	
		yield f"data:{json.dumps(data)}\n\n"
		cv.wait()
		cv.release()

	cursor.close()
	conn.close()
        

if __name__ == "__main__":
    app.run(port=5002)
