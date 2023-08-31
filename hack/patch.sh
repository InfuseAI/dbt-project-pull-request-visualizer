#! /bin/bash

# This script is used to patch the source code of the multiprocessing.
PATCH_PATH=$(python -c 'import multiprocessing.synchronize; print(multiprocessing.synchronize.__file__)')
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

# Patch the source code of the multiprocessing.
cat $DIR/multiprocessing_patch.py >> $PATCH_PATH
