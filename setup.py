#!/usr/bin/env python3
# coding: utf-8
#
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


import os
from setuptools import setup
import sys

setup_kwargs = dict()

if 'install' not in sys.argv or 0 != os.getuid():
    setup_kwargs.update(dict(
        data_files=[
            ('lib/systemd/system', ['jenkins-epo.service']),
            ('/etc', ['jenkins-epo.conf']),
        ],
    ))

setup(
    name='jenkins-epo',
    version='1.60',
    entry_points={
        'console_scripts': ['jenkins-epo=jenkins_epo.script:entrypoint'],
        'jenkins_epo.bot.extensions': [
            'builder = jenkins_epo.extensions:BuilderExtension',
            'canceller = jenkins_epo.extensions:CancellerExtension',
            'createjobs = jenkins_epo.extensions:CreateJobsExtension',
            'error = jenkins_epo.extensions:ErrorExtension',
            'help = jenkins_epo.extensions:HelpExtension',
            'merger = jenkins_epo.extensions:MergerExtension',
            'report = jenkins_epo.extensions:ReportExtension',
            'stages = jenkins_epo.extensions:StagesExtension',
        ],
    },
    extras_require={
        'release': ['wheel'],
        'test': [
            'libfaketime', 'pytest', 'pytest-asyncio', 'pytest-cov',
            'pytest-logging', 'pytest-mock',
        ],
    },
    install_requires=[
        'githubpy',
        'jenkinsapi',
        'jenkins-yml[renderer]',
        'pyyaml',
        'retrying',
    ],
    packages=['jenkins_epo'],
    description='Jenkins EPO',
    author=', '.join([
        'Étienne BERSAC <etienne.bersac@people-doc.com>',
        'James Pic <james.pic@people-doc.com>',
    ]),
    author_email='rd@novapost.fr',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
    ],
    keywords=['jenkins', 'github', 'yml'],
    license='GPL v3 or later',
    url='https://github.com/novafloss/jenkins-epo',
    **setup_kwargs
)
