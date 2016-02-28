#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
    version='0.1',
    entry_points={
        'console_scripts': ['jenkins-ghp=jenkins_ghp.script:entrypoint'],
    },
    extras_require={
        'release': ['wheel', 'zest.releaser'],
        'test': ['mock', 'pytest', 'pytest-logging'],
    },
    install_requires=[
        'githubpy',
        'jenkinsapi',
        'pyyaml',
        'requests',
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
    license='MIT',
    url='https://github.com/novafloss/jenkins-github-poller',
    **setup_kwargs
)
