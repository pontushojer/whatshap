#!/bin/bash
# Build manylinux1 wheels. It is best to run this in a fresh
# clone of the repository!
#
# Run with:
#   docker run --rm -v $(pwd):/io quay.io/pypa/manylinux1_x86_64 /io/buildwheels.sh

set -euo pipefail

yum install -y zlib-devel

PYTHON_BINARIES="/opt/python/cp3*/bin"
for PYBIN in ${PYTHON_BINARIES}; do
    ${PYBIN}/pip install Cython nose
    ${PYBIN}/pip wheel /io/ -w wheelhouse/
done

# Bundle external shared libraries into the wheels
for whl in wheelhouse/*.whl; do
    auditwheel repair $whl -w /io/wheelhouse/
done

# Install packages and test
for PYBIN in ${PYTHON_BINARIES}; do
    ${PYBIN}/pip install whatshap --no-index -f /io/wheelhouse
    (cd $HOME; ${PYBIN}/nosetests --exe --with-doctest -P tests/ whatshap/)
done
