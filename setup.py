#!/usr/bin/env python3
# coding: utf-8
#
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
from setuptools import setup

setup_kwargs = dict()

if 0 == os.getuid():
    setup_kwargs.update(dict(
        data_files=[
            ('lib/systemd/system', ['jenkins-ghp.service']),
            ('/etc', ['jenkins-ghp.conf']),
        ],
    ))

setup(
    name='jenkins-ghp',
    version='1.30.dev0',
    entry_points={
        'console_scripts': ['jenkins-ghp=jenkins_ghp.script:entrypoint'],
        'jenkins_ghp.bot.extensions': [
            'builder = jenkins_ghp.extensions:BuilderExtension',
            'error = jenkins_ghp.extensions:ErrorExtension',
            'fix = jenkins_ghp.extensions:FixStatusExtension',
            'help = jenkins_ghp.extensions:HelpExtension',
            'merger = jenkins_ghp.extensions:MergerExtension',
            'report = jenkins_ghp.extensions:ReportExtension',
        ],
    },
    extras_require={
        'release': ['wheel', 'zest.releaser[recommended]'],
        'test': ['freezegun', 'pytest', 'pytest-cov', 'pytest-logging'],
    },
    install_requires=[
        'githubpy',
        'jenkinsapi',
        'jenkins-yml[renderer]',
        'pyyaml',
        'retrying',
    ],
    packages=['jenkins_ghp'],
    description='Jenkins GitHub Poller',
    author=', '.join([
        'James Pic <james.pic@people-doc.com>',
        'Étienne BERSAC <etienne.bersac@people-doc.com>',
    ]),
    author_email='rd@novapost.fr',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
    ],
    keywords=['jenkins', 'github'],
    license='GPL v3 or later',
    url='https://github.com/novafloss/jenkins-github-poller',
    **setup_kwargs
)
