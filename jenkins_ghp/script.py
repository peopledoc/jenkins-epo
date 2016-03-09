# This file is part of jenkins-ghp
#
# jenkins-ghp is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# jenkins-ghp is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# jenkins-ghp.  If not, see <http://www.gnu.org/licenses/>.

import os
import logging
import traceback
import sys


logger = logging.getLogger(__name__)


def entrypoint():
    debug = os.environ.get('GHP_VERBOSE') or os.environ.get('GHP_DEBUG')
    debug = debug not in ('0', '')
    if debug:
        format = '[%(name)-24s %(levelname)8s] %(message)s'
        level = logging.DEBUG
    else:
        format = '[%(levelname)-8s] %(message)s'
        level = logging.INFO

    logging.basicConfig(level=logging.WARNING, format=format)
    logging.getLogger('jenkins_ghp').setLevel(level)

    logger.info("Starting jenkins-ghp")
    logger.debug("Debug mode enabled")

    # Import modules after logging is setup
    from .main import main

    try:
        main()
    except KeyboardInterrupt:
        tb = sys.exc_info()[-1]
        logger.debug("Interrupted at:\n%s", traceback.format_tb(tb)[-1])
        logger.info("Done")


if __name__ == '__main__':
    entrypoint()
