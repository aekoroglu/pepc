#!/usr/bin/env python3
#
# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Author: Antti Laakso <antti.laakso@linux.intel.com>

"""Common bits for the 'pepc' tests."""

import os
import sys
import logging
from pathlib import Path
import pytest
from pepclibs import CPUInfo
from pepclibs.helperlibs import ProcessManager
from pepctool import _Pepc

logging.basicConfig(level=logging.DEBUG)
_LOG = logging.getLogger()

def _get_datapath(dataset):
    """Return path to test data for the dataset 'dataset'."""
    return Path(__file__).parent.resolve() / "data" / dataset

def get_pman(hostname, dataset, modules=None):
    """
    Create and return process manager, the arguments are as follows.
      * hostname - the hostn name to create a process manager object for.
      * dataset - the name of the dataset used to emulate the real hardware.
      * modules - the list of python module names to be initialized before testing. Refer to
                  'EmulProcessManager.init_testdata()' for more information.
    """

    datapath = None
    username = None
    if hostname == "emulation":
        datapath = _get_datapath(dataset)
    elif hostname != "localhost":
        username = "root"

    pman = ProcessManager.get_pman(hostname, username=username, datapath=datapath)

    if hostname == "emulation" and modules is not None:
        if not isinstance(modules, list):
            modules = [modules]

        for module in modules:
            pman.init_testdata(module, datapath)

    return pman

def get_datasets():
    """Find all directories in 'tests/data' directory and yield the directory name."""

    basepath = Path(__file__).parent.resolve() / "data"
    for dirname in os.listdir(basepath):
        if not Path(f"{basepath}/{dirname}").is_dir():
            continue
        yield dirname

def build_params(hostname, dataset, pman):
    """Implements the 'get_params()' fixture."""

    params = {}
    params["hostname"] = hostname
    params["dataset"] = dataset

    if hostname == "emulation":
        datapath = _get_datapath(dataset)
        pman.init_testdata("CPUInfo", datapath)

    with CPUInfo.CPUInfo(pman=pman) as cpuinfo:
        allcpus = cpuinfo.get_cpus()
        medidx = int(len(allcpus)/2)
        params["testcpus"] = [allcpus[0], allcpus[medidx], allcpus[-1]]
        params["cpus"] = allcpus
        params["packages"] = cpuinfo.get_packages()
        params["cores"] = {}
        for pkg in params["packages"]:
            params["cores"][pkg] = cpuinfo.get_cores(package=pkg)
        params["cpumodel"] = cpuinfo.info["model"]

    return params

@pytest.fixture(name="params", scope="module", params=get_datasets())
def get_params(hostname, request):
    """
    Yield a dictionary with information we need for testing. For example, to optimize the test
    duration, use only subset of all CPUs available on target system to run tests on.
    """

    dataset = request.param
    with get_pman(hostname, dataset) as pman:
        yield build_params(hostname, dataset, pman)

def run_pepc(arguments, pman, exp_exc=None):
    """
    Run the 'pepc' command with arguments 'arguments' and with process manager 'pman'. The 'exp_exc'
    is expected exception type. By default, any exception is considered to be a failure.
    """

    cmd = f"{_Pepc.__file__} {arguments}"
    _LOG.debug("running: %s", cmd)
    sys.argv = cmd.split()
    try:
        args = _Pepc.parse_arguments()
        ret = args.func(args, pman)
    except Exception as err: # pylint: disable=broad-except
        if exp_exc is None:
            assert False, f"command '{cmd}' raised the following exception:\n\t" \
                          f"type: {type(err)}\n\tmessage: {err}"

        if isinstance(err, exp_exc):
            return None

        assert False, f"command '{cmd}' raised the following exception:\n\t" \
                      f"type: {type(err)}\n\tmessage: {err}\n" \
                      f"but it was expected to raise the following exception type: {type(exp_exc)}"

    return ret
