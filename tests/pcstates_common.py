#!/usr/bin/env python3
#
# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Author: Niklas Neronin <niklas.neronin@intel.com>

"""Common functions for the 'CStates' and 'PStates' class tests."""

from common import is_prop_supported

def get_fellows(params, cpuinfo, cpu=0):
    """
    Return a dict where keys are scope names and values are all fellow CPUs (CPUs sharing the same
    scope as a CPU) to the CPU 'cpu'. The dict is used when running tests with function calls that
    require a list of CPUs with the same scope as the CPU that we are changing the value of.

    The argument are as follows.
     * params - Various common parameters for running the tests.
     * cpuinfo - CPU information object generated by 'CPUInfo.CPUInfo()'.
     * cpu - the CPU whose fellows we return.
    """

    levels = cpuinfo.get_cpu_levels(cpu)

    fellows = {}
    fellows["global"] = params["cpus"]
    fellows["package"] = cpuinfo.package_to_cpus(levels["package"])
    fellows["die"] = cpuinfo.dies_to_cpus(dies=levels["die"], packages=levels["package"])
    # No fellows['node'], because there is currently no property with 'node' scope.
    fellows["core"] = cpuinfo.cores_to_cpus(cores=levels["core"], packages=levels["package"])
    fellows["CPU"] = cpu

    return fellows

def set_and_verify(pcobj, pname, value, cpus):
    """
    Set property 'pname' to value 'value' for CPUs in 'cpus', then read it back and verify that the
    read value is 'value'.

    The argument are as follows.
     * pcobj - 'CStates' or 'PStates' object.
     * pname - name of the property.
     * value - the new value.
     * cpus - list of CPUs.
    """

    pcobj.set_prop(pname, value, cpus)

    for cpu, pinfo in pcobj.get_props((pname, ), cpus):
        if pinfo[pname][pname] != value:
            assert False, f"Failed to set property '{pname}' for CPU {cpu}\nSet to '{value}' and " \
                          f"received '{pinfo[pname][pname]}'."

def _verify_value_type(pname, ptype, value):
    """
    This function verifies that the value 'value' type matches the type 'ptype' for property
    'pname'.
    """

    if ptype == "int":
        ret = isinstance(value, int)
    elif ptype == "str":
        ret = isinstance(value, str)
    elif ptype == "list[str]":
        ret = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif ptype == "bool":
        ret = value in ("on", "off")
    elif ptype == "dict[str,str]":
        ret = isinstance(value, dict) and all(isinstance(key, str) and isinstance(val, str) \
                                              for key, val in value.items())
    else:
        assert False, f"Unknown '{pname}' property datatype: {ptype}"

    assert ret, f"Property '{pname}' value '{value}' has the wrong datatype. Should be " \
                  f"'{ptype}' but returns type '{type(value)}'"

def verify_props_value_type(props, pinfo):
    """
    This function test 'get_props()' return type for all supported properties and subproperties
    on the system.

    The argument are as follows.
     * props - dictionary describing the properties.
     * pinfo - dictionary returned by 'get_props()' with format {'property': 'value', ...}
    """

    for pname in props:
        if not is_prop_supported(pname, pinfo):
            continue

        _verify_value_type(pname, props[pname]["type"], pinfo[pname][pname])

        for subpname in props[pname]["subprops"]:
            _verify_value_type(subpname, props[pname]["subprops"][subpname]["type"],
                               pinfo[pname][subpname])
