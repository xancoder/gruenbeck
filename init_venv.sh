#!/usr/bin/env bash

# make sure python virtual environment is installed
# install under debian as root
# apt install python3-venv
# ubuntu
# sudo apt install python3-venv

python3 -m venv ./venv
source ./venv/bin/activate
pip install -r requirements.txt
deactivate
