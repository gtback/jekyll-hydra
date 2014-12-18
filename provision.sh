#!/bin/bash

# Modified from
# https://github.com/andrewyoung1991/python-3.4.1-vagrant-bootstrap/blob/master/provision/bootstrap.sh

# This script is called directly from the Vagrantfile
su vagrant
## general config ##

#vagrant config?
export DEBIAN_FRONTEND=noninteractive
set -e # Exit script immediately on first error.
set -x # Print commands and their arguments as they are executed.

#update package manager resources
sudo apt-get update -y

#set time zone
area="Etc"
zone="UTC"
sudo echo "$area/$zone" > /tmp/timezone
sudo cp -f /tmp/timezone /etc/timezone
sudo cp -f /usr/share/zoneinfo/$area/$zone /etc/localtime


## end general config ##

## main server installs ##

#basics
sudo apt-get install -y build-essential
sudo apt-get install -y libc6-dev libreadline-dev libz-dev libncursesw5-dev libssl-dev libgdbm-dev libsqlite3-dev libbz2-dev liblzma-dev tk-dev

sudo apt-get install -y git-core mercurial vim screen wget curl raptor-utils unzip ack-grep
#sudo apt-get install -y tree vim-gnome

#apache, xvfb and firefox for selenium functional testing
#sudo apt-get install -y apache2 xvfb firefox 
sudo apt-get install -y nginx

#postgres
# sudo apt-get update -y
# sudo apt-get install -y libpq-dev postgresql postgresql-contrib

#sudo apt-get purge -y python-pip
sudo apt-get install -y python-pip
sudo pip install virtualenv virtualenvwrapper
sudo apt-get update -y

## end main server installs ##

## virtualenv work ##

grep WORKON /home/vagrant/.bashrc || {
sudo echo """ 
export WORKON_HOME=~/.virtualenvs
export PROJECT_HOME=~/dev
export DJANGO_SETTINGS_MODULE=settings
export SOME_SECRET_KEY=d0nt-t0uch-my-1ce-cr34m
source /usr/local/bin/virtualenvwrapper.sh
""" >> /home/vagrant/.bashrc
source /home/vagrant/.bashrc
}

hash python3.4 2>/dev/null || {
    #Install Python 3.4 for to run in a virtual environment
    cd /home/vagrant/
    sudo wget https://www.python.org/ftp/python/3.4.1/Python-3.4.1.tar.xz
    sudo tar -xvf Python-3.4.1.tar.xz
    cd Python-3.4.1
    sudo ./configure
    make && sudo make install
}


sudo aptitude install -y python-pip python-dev build-essential
sudo pip install -r /vagrant/requirements.txt
sudo pip install -r /vagrant/prod_requirements.txt
