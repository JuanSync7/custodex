#!/bin/bash
# greet-batch: greet many names read from a file (the subject: shell getopts).
usage() { echo "usage: greet-batch -f FILE [-n COUNT] [-v] [-h]"; exit 1; }

FILE="" COUNT=1 VERBOSE=0
while getopts f:n:vh opt; do
  case ${opt} in
    f) FILE=$OPTARG ;;
    n) COUNT=$OPTARG ;;
    v) VERBOSE=1 ;;
    h) usage ;;
    *) usage ;;
  esac
done
