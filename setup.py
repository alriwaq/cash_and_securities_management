from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# get version from __version__ variable in cash_and_securities_management/__init__.py
from cash_and_securities_management import __version__ as version

setup(
    name="cash_and_securities_management",
    version=version,
    description="Custom ERPNext module for managing employee custody requests, accountant custody records, and procurement cycle integration.",
    author="Your Company",
    author_email="admin@yourcompany.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
