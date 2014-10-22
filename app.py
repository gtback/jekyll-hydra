import os
import tempfile
import threading
import socket
import subprocess

from flask import Flask, render_template, redirect, url_for
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.wtf import Form

from wtforms.fields import TextField
from wtforms.validators import Required

app = Flask(__name__, instance_relative_config=True)
app.config.from_object('config')
app.config.from_pyfile('config.py')

START_PORT = 4000

db = SQLAlchemy(app)

@app.route('/', methods=['GET', 'POST'])
def home():
    form = SubmitForm()
    if form.validate_on_submit():
        i = Instance(repository=form.repository.data,
                     branch=form.branch.data)
        db.session.add(i)
        db.session.commit()

        print("running it...")
        t = threading.Thread(target=run_it, args=[i.repository, i.branch])
        t.start()

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

class SubmitForm(Form):
    repository = TextField('Repository', validators=[Required()])
    branch = TextField('Branch', validators=[Required()])


def print_args(args):
    print("-" * 40)
    print(' '.join(args))
    print("-" * 40)


def find_port():
    """Find an open TCP port, starting at 4000 and working upward"""
    # There's probably a race condition here.
    found = False
    port = START_PORT
    while not found:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex(('127.0.0.1', port))
        print(result)
        if result == 61:
            print("Port %d is available" % port)
            found = True
        else:
            print("Port %d in use" % port)
            port = port + 1

        s.close()

        if port > START_PORT + 10:
            raise ValueError("No usable port found")
    return port


def run_it(repository, branch):
    repository = repository.strip()
    branch = branch.strip()
    with tempfile.TemporaryDirectory() as tmpdirname:
        print("Created temporary directory", tmpdirname)
        repo_dir = os.path.join(tmpdirname, 'repo')

        # Clone the repo
        print("Cloning")
        args = ['git', 'clone', repository, repo_dir]
        print_args(args)
        subprocess.call(args)

        # Change into the repo directory
        os.chdir(repo_dir)

        # Check out the desired branch
        args = ['git', 'checkout', branch]
        print_args(args)
        subprocess.call(args)

        port = find_port()
        print("Serving using port %d" % port)
        args = ['jekyll', 'serve', '-P', str(port)]
        print_args(args)
        subprocess.call(args)


if __name__ == '__main__':
    app.run(debug=True)
