from http.server import HTTPServer, SimpleHTTPRequestHandler
import logging
import os
import tempfile
import threading
import socket
import subprocess

from celery import Celery
from flask import Flask, render_template, redirect, url_for
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.wtf import Form

from flask_bootstrap import Bootstrap

from wtforms.fields import TextField
from wtforms.validators import Required, ValidationError

app = Flask(__name__, instance_relative_config=True)
app.config.from_object('config')
app.config.from_pyfile('config.py')

START_PORT = 4000
HOST_NAME = app.config["HOST"]
SUBMIT_KEY = app.config["SUBMIT_KEY"]

logger = logging.getLogger('hydra')

Bootstrap(app)

db = SQLAlchemy(app)
celery = Celery('app', broker="amqp://localhost")

# Set up application logging
if not app.debug:
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    app.logger.addHandler(stream_handler)


@app.route('/', methods=['GET', 'POST'])
def home():
    form = SubmitForm()
    if form.validate_on_submit():
        i = Instance(repository=form.repository.data,
                     branch=form.branch.data)
        db.session.add(i)
        db.session.commit()

        logger.info("running it...")
        run_it.delay(i.id)

        return redirect(url_for('home'))

    inst = Instance.query.all()

    return render_template('home.html', form=form, inst=inst)

class Instance(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    repository = db.Column(db.String(256))
    branch = db.Column(db.String(64))
    status = db.Column(db.String(64))
    port = db.Column(db.Integer)

    def __str__(self):
        return "{0.repository} - {0.branch}".format(self)

    @property
    def link(self):
        return "http://{0}:{1}/".format(HOST_NAME, self.port)

class SubmitForm(Form):
    repository = TextField('Repository', validators=[Required()])
    branch = TextField('Branch', validators=[Required()])
    key = TextField('Submit Key', validators=[Required()])

    def validate_key(form, field):
        if field.data != SUBMIT_KEY:
            raise ValidationError("Invalid Submission Key")


def print_args(args):
    logger.info("-" * 40)
    logger.info(' '.join(args))
    logger.info("-" * 40)


def find_port():
    """Find an open TCP port, starting at 4000 and working upward"""
    # There's probably a race condition here.
    found = False
    port = START_PORT
    while not found:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex(('127.0.0.1', port))
        logger.debug(result)
        if result in (61, 111):
            logger.info("Port %d is available" % port)
            found = True
        else:
            logger.info("Port %d in use" % port)
            port = port + 1

        s.close()

        if port > START_PORT + 10:
            raise ValueError("No usable port found")
    return port


@celery.task
def run_it(instance_id):
    with app.app_context(), tempfile.TemporaryDirectory() as tmpdirname:
        i = db.session.query(Instance).get(instance_id)
        repository = i.repository.strip()
        branch = i.branch.strip()

        logger.info("Created temporary directory %s" % tmpdirname)
        repo_dir = os.path.join(tmpdirname, 'repo')

        # Clone the repo
        i.status = "Cloning"
        db.session.commit()
        args = ['git', 'clone', repository, repo_dir]
        print_args(args)
        try:
            subprocess.check_call(args)
        except subprocess.CalledProcessError:
            i.status = "Error"
            db.session.commit()
            return

        # Change into the repo directory
        os.chdir(repo_dir)

        # Check out the desired branch
        args = ['git', 'checkout', branch]
        print_args(args)
        try:
            subprocess.check_call(args)
        except subprocess.CalledProcessError:
            i.status = "Error"
            db.session.commit()
            return

        i.status = "Building"
        db.session.commit()
        args = ['jekyll', 'build']
        print_args(args)
        try:
            subprocess.check_call(args)
        except subprocess.CalledProcessError:
            i.status = "Error"
            db.session.commit()
            return

        site_dir = os.path.join(repo_dir, "_site")
        os.chdir(site_dir)
        logger.info(site_dir)

        port = find_port()
        i.port = port
        i.status = "Serving"
        db.session.commit()
        logger.info("Serving using port %d" % port)

        server_address = ('', port)
        httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
        httpd.serve_forever()

# Clear the database
# Instance.query.delete()

# Mark all old session as dead
try:
    db.session.query(Instance).update({'status': "Dead", 'port': None})
    db.session.commit()
except:
    pass

if __name__ == '__main__':
    app.run(debug=True)
