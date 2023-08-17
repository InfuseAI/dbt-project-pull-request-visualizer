#! /usr/bin/env python3
from distutils.core import setup

from setuptools import find_packages  # type: ignore

with open('requirements.txt', 'r') as f:
    install_requires = f.read().splitlines()

setup(
    name='dbt-project-visualizer',
    version='0.1.0',
    description='Visualize dbt project',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='InfuseAI Dev Team',
    author_email='dev@infuseai.io',
    url='https://piperider.io',
    entry_points={
        'console_scripts': ['dbt-project-visualizer = core.cli:cli']
    },
    python_requires=">=3.8",
    packages=find_packages(),
    include_package_data=True,
    install_requires=install_requires,
    classifiers=[
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent'
    ],
    tests_require=['pytest']
)
