#!/bin/bash
# Build manylinux1 wheels.  Based on the example at
# <https://github.com/pypa/python-manylinux-demo>
#
# Run this within the repository root:
#   docker run --rm -v $(pwd):/io quay.io/pypa/manylinux1_x86_64 /io/buildwheels.sh
#
# The wheels will be put into the wheelhouse/ subdirectory.
#
# For interactive tests:
#   docker run -it -v $(pwd):/io quay.io/pypa/manylinux1_x86_64 /bin/bash

set -xeuo pipefail

# For convenience, if this script is called from outside of a docker container,
# it starts a container and runs itself inside of it.
if ! grep -q docker /proc/1/cgroup; then
  # We are not inside a container
  exec docker run --rm -v $(pwd):/io quay.io/pypa/manylinux1_x86_64 /io/$0
fi

yum install -y zlib-devel
git clone /io/ $HOME/project
cd $HOME/project

PYTHON_BINARIES="/opt/python/cp35*/bin"
for PYBIN in ${PYTHON_BINARIES}; do
    ${PYBIN}/pip install Cython nose
    ${PYBIN}/pip wheel -w wheelhouse/ .
done

# Bundle external shared libraries into the wheels
for whl in wheelhouse/whatshap-*.whl; do
    auditwheel repair $whl -w /io/wheelhouse/
done

# Created files are owned by root, so fix permissions.
chown -R --reference=/io/setup.py /io/wheelhouse/

# Install packages and test
for PYBIN in ${PYTHON_BINARIES}; do
    ${PYBIN}/pip install whatshap --no-index -f /io/wheelhouse -f wheelhouse/
    (cd $HOME/project; ${PYBIN}/nosetests --exe --with-doctest -P tests/ whatshap/)
done
