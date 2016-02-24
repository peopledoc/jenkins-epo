#!/usr/bin/env python

from setuptools import setup


setup(
    name='jenkins-ghb',
    version='0.1',
    data_files=[
        ('lib/systemd/system', ['jenkins-ghb.service']),
        ('/etc', ['jenkins-ghb.conf']),
    ],
    extras_require={
        'release': ['wheel', 'zest.releaser'],
    },
    install_requires=[
        'argh',
        'githubpy',
        'jenkinsapi',
        'pyyaml',
        'requests',
        'retrying',
    ],
    scripts=['jenkins-ghb'],
    description='GitHub independant builder for Jenkins',
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
    url='https://github.com/novafloss/jenkins-ghb',
)
