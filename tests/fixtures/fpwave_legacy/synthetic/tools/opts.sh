#!/bin/sh
# Options for the fixture tool. The optstring below outranks the case arms,
# and its leading colon is silent-error mode, not an option.
while getopts ":vo:" opt; do
    case "$opt" in
        v) VERBOSE=1 ;;
        o) OUT="$OPTARG" ;;
    esac
done
case "$1" in
    --help) echo usage ;;
esac
echo "$VERBOSE" "$OUT"
