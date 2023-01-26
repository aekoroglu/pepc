# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Authors: Niklas Neronin <niklas.neronin@intel.com>

"""
This module includes the "topology" 'pepc' command implementation.
"""

import logging
from pepclibs.helperlibs import Trivial
from pepclibs.helperlibs.Exceptions import Error
from pepclibs import CPUInfo
from pepctool import _PepcCommon

_LOG = logging.getLogger()

def _format_row(tline, colnames):
    """Format and return a list of 'colnames' values from 'tline' dictionary."""

    res = []
    for name in colnames:
        if tline[name] is not None:
            res.append(str(tline[name]))
        else:
            res.append("?")

    return res

def topology_info_command(args, pman):
    """Implements the 'topology info' command."""

    if args.columns is None:
        colnames = CPUInfo.LEVELS
    else:
        colnames = []
        for colname in Trivial.split_csv_line(args.columns):
            for key in CPUInfo.LEVELS:
                if colname.lower() == key.lower():
                    colnames.append(key)
                    break
            else:
                columns = ", ".join(CPUInfo.LEVELS)
                raise Error(f"invalid colname '{colname}', use one of: {columns}")

    order = args.order
    for lvl in CPUInfo.LEVELS:
        if order.lower() == lvl.lower():
            order = lvl
            break
    else:
        raise Error(f"invalid order '{order}', use one of: {', '.join(CPUInfo.LEVELS)}")

    offlined_ok = not args.online_only
    if offlined_ok and args.core_siblings:
        raise Error("'--core-siblings' must be used with '--online-only'")

    # Create format string, example: '%7s    %3s    %4s    %4s    %3s'.
    fmt = "    ".join([f"%{len(name)}s" for name in colnames])

    # Create list of level names with the first letter capitalized. Example:
    # ["CPU", "Core", "Node", "Die", "Package"]
    headers = [name[0].upper() + name[1:] for name in colnames]

    with CPUInfo.CPUInfo(pman=pman) as cpuinfo:
        cpus = _PepcCommon.get_cpus(args, cpuinfo, offlined_ok=offlined_ok)

        _LOG.info(fmt, *headers)
        for tline in cpuinfo.get_topology(order=order):
            if tline["CPU"] in cpus:
                _LOG.info(fmt, *_format_row(tline, colnames))
