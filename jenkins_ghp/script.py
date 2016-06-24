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
import logging.config
import traceback
import sys


logger = logging.getLogger(__name__)


class SystemdFormatter(logging.Formatter):
    syslog_level_map = {
        logging.NOTSET: 6,
        logging.DEBUG: 7,
        logging.INFO: 6,
        logging.WARNING: 4,
        logging.ERROR: 3,
        logging.CRITICAL: 2,
    }

    def format(self, record):
        msg = super(SystemdFormatter, self).format(record)
        syslog_level = self.syslog_level_map[record.levelno]
        return '<%d>%s' % (syslog_level, msg)


def entrypoint(argv=None):
    argv = argv or sys.argv[1:]

    logging_config = {
        'version': 1,
        'formatters': {
            'debug': {
                'format': '[%(name)-24s %(levelname)8s] %(message)s',
            },
            'info': {
                'format': '[%(levelname)-8s] %(message)s',
            },
            'systemd': {
                '()': __name__ + '.' + SystemdFormatter.__name__,
            }
        },
        'handlers': {'stderr': {
            '()': 'logging.StreamHandler',
            'formatter': 'info',
        }},
        'root': {
            'level': 'WARNING',
            'handlers': ['stderr'],
        },
        'loggers': {'jenkins_ghp': {
            'level': 'INFO',
        }},
    }

    debug = os.environ.get('GHP_VERBOSE') or os.environ.get('GHP_DEBUG')
    debug = debug not in ('0', '', None)
    if debug:
        logging_config['loggers']['jenkins_ghp']['level'] = 'DEBUG'
        logging_config['handlers']['stderr']['formatter'] = 'debug'

    if os.environ.get('SYSTEMD'):
        logging_config['handlers']['stderr']['formatter'] = 'systemd'

    logging.config.dictConfig(logging_config)

    logger.info("Starting jenkins-ghp")
    logger.debug("Debug mode enabled")

    # Import modules after logging is setup
    from jenkins_ghp.main import main

    try:
        logger.debug("Executing %s", ' '.join(argv))
        main(argv)
    except KeyboardInterrupt:
        tb = sys.exc_info()[-1]
        logger.debug("Interrupted at:\n%s", traceback.format_tb(tb)[-1])
        logger.info("Done")


if __name__ == '__main__':
    entrypoint(['bot'])
