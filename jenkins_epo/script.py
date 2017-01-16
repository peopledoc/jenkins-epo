# This file is part of jenkins-epo
#
# jenkins-epo is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# jenkins-epo is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# jenkins-epo.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import os
import logging.config
import pkg_resources
import traceback
import sys


logger = logging.getLogger(__name__)


class AsyncLogRecord(logging.LogRecord):
    def __init__(self, *a, **kw):
        super(AsyncLogRecord, self).__init__(*a, **kw)
        self.task = 'main'
        if asyncio.get_event_loop_policy()._local._loop:
            task = asyncio.Task.current_task()
            self.task = getattr(task, 'logging_id', 'unknown')


logging.setLogRecordFactory(AsyncLogRecord)


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
            'adebug': {'format': (
                '%(asctime)s =%(task)s= '
                '[%(name)-32s %(levelname)8s] %(message)s'
            )},
            'debug': {'format': (
                '=%(task)s= [%(name)-32s %(levelname)8s] %(message)s'
            )},
            'info': {
                'format': '=%(task)s= [%(levelname)-8s] %(message)s',
            },
            'systemd': {
                '()': __name__ + '.' + SystemdFormatter.__name__,
                'format': '=%(task)s= %(message)s',
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
        'loggers': {
            'jenkins_epo': {
                'level': 'INFO',
            },
            'asyncio': {
                'level': 'INFO',
            },
        },
    }

    adebug = os.environ.get("PYTHONASYNCIODEBUG") == '1'

    names = {p + k for p in ['', 'GHP_', 'EPO_'] for k in ['VERBOSE', 'DEBUG']}
    debug = [os.environ.get(n) for n in names]
    debug = bool([v for v in debug if v not in ('0', '', None)])

    if debug or adebug:
        logging_config['loggers']['jenkins_epo']['level'] = 'DEBUG'
        logging_config['handlers']['stderr']['formatter'] = 'debug'

    if adebug:
        logging_config['loggers']['asyncio']['level'] = 'DEBUG'
        logging_config['handlers']['stderr']['formatter'] = 'adebug'

    if os.environ.get('SYSTEMD'):
        logging_config['handlers']['stderr']['formatter'] = 'systemd'

    logging.config.dictConfig(logging_config)

    distribution = pkg_resources.get_distribution('jenkins-epo')
    logger.info("Starting jenkins-epo %s.", distribution.version)
    logger.debug("Debug mode enabled")

    # Import modules after logging is setup
    from jenkins_epo.main import main

    try:
        logger.debug("Executing %s", ' '.join(argv))
        main(argv)
    except KeyboardInterrupt:
        tb = traceback.format_tb(sys.exc_info()[-1])
        if not debug:
            tb = tb[-2:]
        logger.debug("Interrupted at:\n%s", ''.join(tb).strip())
        logger.info("Done")


if __name__ == '__main__':
    entrypoint(['bot'])
