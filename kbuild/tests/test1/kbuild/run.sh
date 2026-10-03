#!/bin/bash

cd $(dirname ${0})
python3 ../../utils/run.py ./ "$1" "$2"
