#!/usr/bin/env python3
#
# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Author: Antti Laakso <antti.laakso@linux.intel.com>

"""Test module for 'pepc' project 'cpu-hotplug' command."""

from common import run_pepc, get_pman
# Fixtures need to be imported explicitly
from common import build_params, get_params # pylint: disable=unused-import
from pepclibs.helperlibs.Exceptions import Error

def test_cpuhotplug_info(params):
    """Test 'pepc cpu-hotplug info' command."""

    pman = get_pman(params["hostname"], params["dataset"], modules="CPUOnline")
    run_pepc("cpu-hotplug info", pman)

def test_cpuhotplug_online(params):
    """Test 'pepc cpu-hotplug online' command."""

    good_options = ["--cpus all"]
    if len(params["cpus"]) > 2:
        good_options += ["--cpus 1"]
    if len(params["cpus"]) > 3:
        good_options += ["--cpus 1-2"]

    pman = get_pman(params["hostname"], params["dataset"], modules="CPUOnline")

    for option in good_options:
        run_pepc(f"cpu-hotplug online {option}", pman)

    bad_options = [
        "",
        "--siblings",
        "--packages 0 --cores all",
        f"--packages 0 --cores {params['cores'][0][0]}",
        f"--packages 0 --cores {params['cores'][0][-1]}",
        f"--packages {params['packages'][-1]}"]

    if len(params["cores"][0]) > 2:
        bad_options += [f"--packages 0 --cores {params['cores'][0][1]}"]
    if len(params["cores"][0]) > 3:
        bad_options += [f"--packages 0 --cores {params['cores'][0][1]}-{params['cores'][0][2]}"]

    for option in bad_options:
        run_pepc(f"cpu-hotplug online {option}", pman, exp_exc=Error)

def test_cpuhotplug_offline(params):
    """Test 'pepc cpu-hotplug offline' command."""

    pman = get_pman(params["hostname"], params["dataset"], modules="CPUOnline")

    good_options = [
        "--cpus all",
        f"--cpus {params['cpus'][-1]}",
        f"--cpus all --cores {params['cores'][0][0]} --packages 0",
        "--packages 0",
        "--packages 0 --cores all",
        f"--packages {params['packages'][-1]}",
        f"--packages 0 --cores {params['cores'][0][0]}",
        f"--packages 0 --cores {params['cores'][0][-1]}"]

    if len(params["cpus"]) > 2:
        good_options += ["--cpus 1"]
    if len(params["cpus"]) > 3:
        good_options += ["--cpus 1-2"]
    if len(params["cores"][0]) > 2:
        good_options += [f"--packages 0 --cores {params['cores'][0][1]}"]
    if len(params["cores"][0]) > 3:
        good_options += [f"--packages 0 --cores {params['cores'][0][1]}-{params['cores'][0][2]}"]

    for option in good_options:
        run_pepc(f"cpu-hotplug offline {option}", pman)
        run_pepc(f"cpu-hotplug offline {option} --siblings", pman)

    bad_options = ["--cpus 0"]
    if len(params["cpus"]) > 5:
        bad_options += ["--cpus 0-4"]

    for option in bad_options:
        run_pepc(f"cpu-hotplug offline {option}", pman, exp_exc=Error)

    for option in bad_options:
        # With '--siblings' CPU 0 will be excluded and all these "bad" options become OK.
        run_pepc(f"cpu-hotplug offline {option} --siblings", pman)
