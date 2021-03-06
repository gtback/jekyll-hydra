from http.server import HTTPServer, SimpleHTTPRequestHandler
import logging
import os
import tempfile
import threading
import shutil
import socket
import subprocess

from celery import Celery
from flask import Flask, render_template, redirect, url_for
from flask.ext.security import (login_required, RoleMixin, Security,
                                SQLAlchemyUserDatastore, UserMixin)
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.wtf import Form

from flask_bootstrap import Bootstrap

from sqlalchemy.sql.expression import asc
from wtforms.fields import TextField
from wtforms.validators import Required, ValidationError

app = Flask(__name__, instance_relative_config=True)
app.config.from_object('config')
app.config.from_pyfile('config.py')

START_PORT = 4000
HOST_NAME = app.config["HOST"]
OUTPUT_BASE_DIR = "/var/hydra/build/"

logger = logging.getLogger('hydra')

Bootstrap(app)

db = SQLAlchemy(app)
celery = Celery('app', broker="amqp://localhost")

# Set up application logging
if not app.debug:
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    app.logger.addHandler(stream_handler)


@app.route('/', methods=['GET'])
def home():
    sites = Instance.query.filter(Instance.port != None,
                                  Instance.status == "Running").order_by(
                                          asc(Instance.port))

    return render_template('home.html', sites=sites, editable=False)


@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    form = SubmitForm()
    if form.validate_on_submit():
        i = Instance(repository=form.repository.data,
                     branch=form.branch.data)
        i.status = "Submitted"
        db.session.add(i)
        db.session.commit()

        logger.info("running it...")
        run_it.delay(i.id)

        return redirect(url_for('home'))

    sites = Instance.query.all()

    return render_template('home.html', form=form, sites=sites, editable=True)


@app.route('/kill/<id>', methods=['POST'])
@login_required
def kill(id):
    logger.info("Killing instance " + str(id))
    i = db.session.query(Instance).get(id)
    # Save port for after database is updated.
    port = i.port
    i.port = None
    i.status = "Killed"
    db.session.commit()

    shutil.rmtree(os.path.join(OUTPUT_BASE_DIR, str(port)))

    return redirect(url_for('home'))


@app.route('/rebuild/<id>', methods=['POST'])
@login_required
def rebuild(id):
    logger.info("Rebuilding instance" + str(id))
    i = db.session.query(Instance).get(id)
    i.status = "Resubmitted"
    db.session.commit()
    run_it.delay(i.id)

    return redirect(url_for('home'))


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


roles_users = db.Table('roles_users',
        db.Column('user_id', db.Integer(), db.ForeignKey('user.id')),
        db.Column('role_id', db.Integer(), db.ForeignKey('role.id')))


class Role(db.Model, RoleMixin):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True)
    password = db.Column(db.String(255))
    active = db.Column(db.Boolean())
    confirmed_at = db.Column(db.DateTime())
    roles = db.relationship('Role', secondary=roles_users,
                            backref=db.backref('users', lazy='dynamic'))


user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security = Security(app, user_datastore)


def print_args(args):
    logger.info("-" * 40)
    logger.info(' '.join(args))
    logger.info("-" * 40)


def find_port():
    """Find an open TCP port, starting at 4000 and working upward"""
    ports = db.session.query(Instance.port).filter(Instance.port.isnot(None))
    ports = set([x[0] for x in ports.all()])

    logger.info("-" * 40)
    logger.info(ports)
    logger.info("-" * 40)

    for x in range(START_PORT, START_PORT + 10):
        if x not in ports:
            return x

    raise ValueError("No usable port found")


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

        curdir = os.getcwd()
        logger.info("Current Directory: {}".format(curdir))
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

        port = find_port()
        outdir = os.path.join(OUTPUT_BASE_DIR, str(port))
        i.port = port
        i.status = "Building"

        db.session.commit()
        args = ['jekyll', 'build', '-d', outdir]
        print_args(args)
        try:
            subprocess.check_call(args)
        except subprocess.CalledProcessError:
            i.status = "Error"
            db.session.commit()
            return

        logger.info("Site output to " + outdir)

        # Change back to original directory (else git gets cranky)
        os.chdir(curdir)

        i.status = "Running"
        db.session.commit()
        logger.info("Serving using port %d" % port)

# Clear the database
# Instance.query.delete()

if __name__ == '__main__':
    app.run(debug=True)
