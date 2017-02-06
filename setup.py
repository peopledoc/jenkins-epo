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
from setuptools import find_packages, setup
import subprocess
import sys

setup_kwargs = dict()

if 'install' not in sys.argv or 0 != os.getuid():
    setup_kwargs.update(dict(
        data_files=[
            ('lib/systemd/system', ['jenkins-epo.service']),
            ('/etc', ['jenkins-epo.conf']),
        ],
    ))

try:
    # Release mode
    VERSION = (
        subprocess.check_output(["git", "describe", "--tags"])
        .strip().decode()
    )
except subprocess.CalledProcessError:
    # pip install mode
    with open('PKG-INFO') as fo:
        for line in fo:
            if not line.startswith('Version: '):
                continue
            VERSION = line.replace('Version: ', '').strip()
            break

if __name__ == '__main__':
    setup(
        name='jenkins-epo',
        version=VERSION,
        entry_points={
            'console_scripts': ['jenkins-epo=jenkins_epo.script:entrypoint'],
            'jenkins_epo.bot.extensions': [
                'security = jenkins_epo.extensions.core:SecurityExtension',
                'error = jenkins_epo.extensions.core:ErrorExtension',
                'help = jenkins_epo.extensions.core:HelpExtension',
                'autocancel = jenkins_epo.extensions.core:AutoCancelExtension',
                'jenkins-autocancel = jenkins_epo.extensions.jenkins:AutoCancelExtension',  # noqa
                'jenkins-builder = jenkins_epo.extensions.jenkins:BuilderExtension',  # noqa
                'jenkins-canceller = jenkins_epo.extensions.jenkins:CancellerExtension',  # noqa
                'jenkins-createjobs = jenkins_epo.extensions.jenkins:CreateJobsExtension',  # noqa
                'jenkins-stages = jenkins_epo.extensions.jenkins:StagesExtension',  # noqa
                'merger = jenkins_epo.extensions.core:MergerExtension',
                'outdated = jenkins_epo.extensions.core:OutdatedExtension',
                'report = jenkins_epo.extensions.core:ReportExtension',
                'skip = jenkins_epo.extensions.core:SkipExtension',
                'yaml = jenkins_epo.extensions.core:YamlExtension'
            ],
        },
        extras_require={
            'release': ['wheel'],
            'test': [
                'asynctest', 'libfaketime', 'pytest', 'pytest-asyncio',
                'pytest-cov', 'pytest-logging', 'pytest-mock',
            ],
        },
        install_requires=[
            'aiohttp',
            'githubpy',
            'jenkinsapi',
            'jenkins-yml[renderer]',
            'pyyaml',
            'tenacity',
            'setuptools>11.3',
        ],
        packages=find_packages(exclude=('tests',)),
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
