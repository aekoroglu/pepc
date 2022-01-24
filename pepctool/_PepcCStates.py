#!/usr/bin/python3
#
# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Author: Artem Bityutskiy <artem.bityutskiy@linux.intel.com>

"""
This module includes the "cstates" 'pepc' command implementation.
"""

import logging
from pepclibs.helperlibs import Human
from pepclibs.helperlibs.Exceptions import Error
from pepclibs.msr import MSR
from pepclibs import CStates, CPUInfo
from pepctool import _PepcCommon

_LOG = logging.getLogger()

def _fmt_cstates(cstates):
    """Fromats and returns the C-states list string, which can be used in messages."""

    if cstates in ("all", None):
        msg = "all C-states"
    else:
        if len(cstates) == 1:
            msg = "C-state "
        else:
            msg = "C-states "
        msg += ",".join(cstates)

    return msg

def _fmt_cpus(cpus):
    """Fromats and returns the CPU numbers string, which can be used in messages."""

    if len(cpus) == 1:
        msg = "CPU "
    else:
        msg = "CPUs "

    return msg + Human.rangify(cpus)

def _print_cstate_prop_msg(pname, action, val, cpus):
    """Format an print a message about a C-state property 'pname'."""

    cpus = _fmt_cpus(cpus)

    if val is None:
        msg = f"{pname}: not supported on {cpus}"
    elif action:
        msg = f"{pname}: {action} '{val}' on {cpus}"
    else:
        msg = f"{pname}: '{val}' on {cpus}"

    _LOG.info(msg)

def _handle_cstate_config_opt(optname, optval, cpus, cstates):
    """
    Handle a C-state configuration option 'optname'.

    Most options can be used with and without a value. In the former case, this function sets the
    corresponding C-state property to the value provided. Otherwise this function reads the current
    value of the C-state priperty and prints it.
    """

    if optname in cstates.props:
        cstates.set_prop(optname, optval, cpus)

        name = cstates.props[optname]["name"]
        _print_cstate_prop_msg(name, "set to", optval, cpus)
    else:
        method = getattr(cstates, f"{optname}_cstates")
        toggled = method(cpus=cpus, cstates=optval)

        # The 'toggled' dictionary is indexed with CPU number. But we want to print a single line
        # for all CPU numbers that have the same toggled C-states list (the assumption here is that
        # the system may be hybrid and different CPUs have different C-states). Therefore, built a
        # "revered" verion of the 'toggled' dictionary.
        revdict = {}
        for cpu, csinfo in toggled.items():
            key = ",".join(csinfo["cstates"])
            if key not in revdict:
                revdict[key] = []
            revdict[key].append(cpu)

        for cstnames, cpunums in revdict.items():
            cstnames = cstnames.split(",")
            _LOG.info("%sd %s on %s", optname.title(), _fmt_cstates(cstnames), _fmt_cpus(cpunums))

def _print_cstate_prop(aggr_pinfo, pname, cstates):
    """Print about C-state properties in 'aggr_pinfo'."""

    for key, kinfo in aggr_pinfo[pname].items():
        for val, cpus in kinfo.items():
            # Distinguish between properties and sub-properties.
            if key in cstates.props:
                name = cstates.props[pname]["name"]
            else:
                name = cstates.props[pname]["subprops"][key]["name"]
                if val is None:
                    # Just skip unsupported sub-property instead of printing something like
                    # "Package C-state limit aliases: not supported on CPUs 0-11".
                    continue
            _print_cstate_prop_msg(name, "", val, cpus)

def _build_aggregate_pinfo(props, cpus, cstates):
    """
    Build the aggregated properties dictionary for proparties in the 'props' list. The dictionary
    has the following format.

    { property1_name: { key1_name: { key1_value1 : [ list of CPUs having key1_value1],
                                     key1_value2 : [ list of CPUs having key1_value2],
                                     key1_value3 : [ list of CPUs having key1_value3]},
                        key2_name: { key2_value1 : [ list of CPUs having key2_value1],
                                     key2_value2 : [ list of CPUs having key2_value2],
                                    key2_value3 : [ list of CPUs having key2_value3]}},
      property2_name: { key1_name: { key1_value1 : [ list of CPUs having key1_value1],
      ... and so on ... }

      * property1_name, property2_name, etc are the property names (e.g., 'pkg_cstate_limit').
      * key1_name, key2_name, etc are key names of the corresponding property (e.g.,
        'pkg_cstate_limit', 'pkg_cstate_limit_locked').
      * key1_value1, key1_value2, etc are all the different values for 'key1_name' (e.g., 'False' or
        'True')

    In other words, for every property and every key of the property, this aggregate properties info
    dictionary provides all values and the list of CPUs for every value. This way we can later
    easily print something like:
        C1 demotion enabled: 'off' on CPUs 0,1,10,11,12
    """

    aggr_pinfo = {}

    for all_props_info in cstates.get_props(props, cpus=cpus):
        for pname, pinfo in all_props_info.items():
            if pname not in aggr_pinfo:
                aggr_pinfo[pname] = {}
            for key, val in pinfo.items():
                if key == "CPU":
                    continue

                # Make sure 'val' is "hashable" and can be used as a dictionary key.
                if isinstance(val, list):
                    if not val:
                        continue
                    val = ", ".join(val)
                elif isinstance(val, dict):
                    if not val:
                        continue
                    val = ", ".join(f"{k}={v}" for k, v in val.items())

                if key not in aggr_pinfo[pname]:
                    aggr_pinfo[pname][key] = {}
                if val not in aggr_pinfo[pname][key]:
                    aggr_pinfo[pname][key][val] = []

                aggr_pinfo[pname][key][val].append(pinfo["CPU"])

    return aggr_pinfo

def _print_scope_warnings(args, cstates):
    """
    Check that the the '--packages', '--cores', and '--cpus' options provided by the user to match
    the scope of all the options.
    """

    pkg_warn, core_warn = [], []

    for pname in cstates.props:
        if not getattr(args, pname, None):
            continue

        scope = cstates.get_scope(pname)
        if scope == "package" and (getattr(args, "cpus") or getattr(args, "cores")):
            pkg_warn.append(pname)
        elif scope == "core" and getattr(args, "cpus"):
            core_warn.append(pname)

    if pkg_warn:
        opts = ", ".join([f"'--{opt.replace('_', '-')}'" for opt in pkg_warn])
        _LOG.warning("the following option(s) have package scope: %s, but '--cpus' or '--cores' "
                     "were used.\n\tInstead, it is recommented to specify all CPUs in a package,"
                     "totherwise the result may be undexpected and platform-dependent.", opts)
    if core_warn:
        opts = ", ".join([f"'--{opt.replace('_', '-')}'" for opt in core_warn])
        _LOG.warning("the following option(s) have core scope: %s, but '--cpus' was used."
                     "\n\tInstead, it is recommented to specify all CPUs in a core,"
                     "totherwise the result may be undexpected and platform-dependent.", opts)

def cstates_config_command(args, proc):
    """Implements the 'cstates config' command."""

    if not hasattr(args, "oargs"):
        raise Error("please, provide a configuration option")

    _PepcCommon.check_tuned_presence(proc)

    # The C-state properties to print about.
    print_props = []

    with CPUInfo.CPUInfo(proc=proc) as cpuinfo, MSR.MSR(proc=proc, cpuinfo=cpuinfo) as msr:
        # Start a transaction, which will delay and aggregate MSR writes until the transaction
        # is committed.
        msr.start_transaction()

        with CStates.CStates(proc=proc, cpuinfo=cpuinfo, msr=msr) as cstates:

            _print_scope_warnings(args, cstates)

            # Find all properties we'll need to print about, and get their values.
            for optname, optval in args.oargs.items():
                if not optval:
                    print_props.append(optname)

            # Build the aggregate properties information dictionary for all options we are going to
            # print about.
            cpus = _PepcCommon.get_cpus(args, cpuinfo, default_cpus="all")
            aggr_pinfo = _build_aggregate_pinfo(print_props, cpus, cstates)

            # Now handle the options one by one, in the same order as they go in the command line.
            for optname, optval in args.oargs.items():
                if not optval:
                    _print_cstate_prop(aggr_pinfo, optname, cstates)
                else:
                    _handle_cstate_config_opt(optname, optval, cpus, cstates)

        # Commit the transaction. This will flush all the change MSRs (if there were any).
        msr.commit_transaction()

def cstates_info_command(args, proc):
    """Implements the 'cstates info' command."""

    with CPUInfo.CPUInfo(proc=proc) as cpuinfo, \
         CStates.CStates(proc=proc, cpuinfo=cpuinfo) as cstates:
        cpus = _PepcCommon.get_cpus(args, cpuinfo, default_cpus=0,)

        first = True
        for info in cstates.get_cstates_info(cpus=cpus, cstates=args.cstates):
            if not first:
                _LOG.info("")
            first = False

            _LOG.info("CPU: %d", info["CPU"])
            _LOG.info("Name: %s", info["name"])
            _LOG.info("Index: %d", info["index"])
            _LOG.info("Description: %s", info["desc"])
            _LOG.info("Status: %s", "disabled" if info["disable"] else "enabled")
            _LOG.info("Expected latency: %d μs", info["latency"])
            _LOG.info("Target residency: %d μs", info["residency"])
            _LOG.info("Requested: %d times", info["usage"])
