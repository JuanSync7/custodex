#!/bin/sh
# Deploy the fixture tool (case-arm switches, no getopts).
while [ $# -gt 0 ]; do
    case "$1" in
        -n|--dry-run) DRY=1 ;;
        --target) TARGET="$2"; shift ;;
    esac
    shift
done
echo "$DRY" "$TARGET"
