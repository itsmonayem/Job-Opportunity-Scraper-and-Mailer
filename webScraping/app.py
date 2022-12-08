from crypt import methods
from datetime import datetime
from email import message
from email.policy import default
from xmlrpc.client import DateTime
from bs4 import BeautifulSoup
from celery.contrib.abortable import AbortableTask
from time import sleep
from flask import Flask,render_template, request
from flask_sqlalchemy import SQLAlchemy
from celery import Celery
import requests
from sqlalchemy import null
from flask_mail import Mail, Message

app = Flask(__name__)

#database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///tasks.db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# Database class
class Task(db.Model):
    sno = db.Column(db.Integer,primary_key=True)
    name = db.Column(db.String(100),nullable=False)
    skill = db.Column(db.String(200),nullable=False)
    email = db.Column(db.String(200),nullable=False)
    id = db.Column(db.String(100),nullable=False)
    date_created = db.Column(db.String(100), default=str(datetime.now().strftime('%B %d %Y - %H:%M')))

# Celery Initialization
def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

# redis settings
flask_app = Flask(__name__)
flask_app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379',
    CELERY_RESULT_BACKEND='redis://localhost:6379'
)
celery = make_celery(flask_app)


#SMTP settings
app.config.update(dict(
    MAIL_SERVER = 'smtp.gmail.com',
    MAIL_PORT = 587,
    MAIL_USERNAME = 'jobreminderapp@gmail.com',
    MAIL_PASSWORD = 'pfkmismdxraomxvf',
    MAIL_USE_TLS = True,
    MAIL_USE_SSL = False,
))
mail = Mail(app)


# Home Page
@app.route('/')
def home():
	return render_template('index.html')



# Get the inputs from user and send these data to 
@app.route('/scheduled',methods=['GET','POST'])
def scheduled():
    if request.method == 'POST':
        name = request.form['Name']
        email = request.form['email']
        skills = request.form['skills']
        unf_skills = request.form['unf_skills']
        location = request.form['location']
        day = request.form['day']
        hour = request.form['hour']
        minute = request.form['minute']
    skills.replace(' ','')
    skills.replace(',','+')
    unf_skills.replace(' ','')
    unf_skills = unf_skills.split(',')
    if day == "":
        day = "0"
    if hour == "":
        hour = "0"
    if minute == "":
        minute = "0"
    day = int(day)
    hour = int(hour)
    minute = int(minute)

    time_in_seconds = day*24*60*60 + hour*60*60 + minute*60
    if(time_in_seconds == 0):
        time_in_seconds = 24*60*60

    #Start the task and store current task_id
    task_id = scrap_and_mail.delay(name,email,skills,unf_skills,location,time_in_seconds)

    #add the task queries to the databse
    new_task = Task(name=name,skill=skills,email=email,id=str(task_id))
    db.session.add(new_task)
    db.session.commit()

    message='Scraping has been started for this query'
    return render_template('index.html',message=message)


#To cancel a running task
@app.route('/cancel/<task_id>')
def cancel(task_id):

    #get the task by task_id and delete from database
    task = Task.query.filter_by(id=task_id).first()
    db.session.delete(task)
    db.session.commit()

    #stops the runnig tasks
    task = scrap_and_mail.AsyncResult(task_id)
    task.abort()

    #pass all data from database to html
    allTasks = Task.query.all()
    message='Scraping is turned off for the particular query'
    return render_template('show.html',allTasks=allTasks,message=message)


# To show currently Running Tasks from database
@app.route('/show')
def show():
    allTasks = Task.query.all()
    return render_template('show.html',allTasks=allTasks)


# To show about section
@app.route('/about')
def about():
    return render_template('about.html',)


#To handle every task in background and mail the tasks to the certail email
@celery.task(bind=True,base=AbortableTask)
def scrap_and_mail(self,name,email,skills,unf_skills,location,time_in_seconds):
    while True:
        if self.is_aborted():
            return "task Stopped"
        
        #Scrap for a query
        html_text = requests.get('https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&from=submit&txtKeywords='+skills+'&txtLocation='+location).text
        soup = BeautifulSoup(html_text, 'lxml')
        jobs = soup.find_all('li', class_ = 'clearfix job-bx wht-shd-bx')

        job_details = 'Dear '+name+',<br>'
        job_details += 'Here some job oppourtunity for you<br><br>'
        if(len(unf_skills)==1):
            if unf_skills[0] == '':
                unf_skills.clear()

        for job in jobs:
            company_name = job.find('h3', class_ = 'joblist-comp-name').next.text
            req_skills = job.find('span', class_ = 'srp-skills').text.replace(' ','')
            published_date = job.find('span', class_ = 'sim-posted').text
            more_info = job.header.h2.a['href']
            experiance_time = job.ul.li.i.next_sibling

            #because of some location attribute can be none
            job_location = getattr(job.ul.findAll('li')[1].find('span'),'text',None)

            if len(unf_skills)!=0 and any(unf in req_skills for unf in unf_skills):
                continue
            else:
                job_details += (f'''
Company Name     : <b>{company_name.strip()}</b><br>
Required Skills  : {req_skills.strip()}<br>
Experiance Time  : {experiance_time}<br>
Location         : {job_location}<br>
Published Date   : {published_date.strip()}<br>
More Info        : {more_info}<br><br><br>
''')
        print("Scrap Done")

        # mail send
        with app.app_context():
            msg = Message('New Job Reminder', sender = 'monayem.chp@gmail.com', recipients = [email])
            msg.html = job_details
            mail.send(msg)
        print("Mail send")
        sleep(time_in_seconds)
    return "Done"


if __name__ == "__main__":
	app.run(debug=False)