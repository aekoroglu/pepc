# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2023 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Authors: Tero Kristo <tero.kristo@linux.intel.com>

"""
This module provides API for managing platform settings related to power.
"""

import logging
from pepclibs import _PropsClassBase
from pepclibs.helperlibs import ClassHelpers
from pepclibs.helperlibs.Exceptions import Error, ErrorNotSupported

_LOG = logging.getLogger()

# This dictionary describes the CPU properties this module supports.
#
# While this dictionary is user-visible and can be used, it is not recommended, because it is not
# complete. This dictionary is extended by 'Power' objects. Use the full dictionary via
# 'Power.props'.
PROPS = {
    "tdp" : {
        "name" : "TDP",
        "unit" : "W",
        "type" : "float",
        "sname": "package",
        "writable" : False,
        "mechanisms" : ("msr", ),
    },
    "ppl1" : {
        "name" : "RAPL PPL1",
        "unit" : "W",
        "type" : "float",
        "sname": "package",
        "writable" : True,
        "mechanisms" : ("msr", ),
    },
    "ppl1_enable" : {
        "name" : "RAPL PPL1",
        "type" : "bool",
        "sname": "package",
        "writable" : True,
        "mechanisms" : ("msr", ),
    },
    "ppl1_clamp" : {
        "name" : "RAPL PPL1 clamping",
        "type" : "bool",
        "sname": "package",
        "writable" : True,
        "mechanisms" : ("msr", ),
    },
    "ppl1_window" : {
        "name" : "RAPL PPL1 time window",
        "unit" : "s",
        "type" : "float",
        "sname": "package",
        "writable" : False,
        "mechanisms" : ("msr", ),
    },
    "ppl2" : {
        "name" : "RAPL PPL2",
        "unit" : "W",
        "type" : "float",
        "sname": "package",
        "writable" : True,
        "mechanisms" : ("msr", ),
    },
    "ppl2_enable" : {
        "name" : "RAPL PPL2",
        "type" : "bool",
        "sname": "package",
        "writable" : True,
        "mechanisms" : ("msr", ),
    },
    "ppl2_clamp" : {
        "name" : "RAPL PPL2 clamping",
        "type" : "bool",
        "sname": "package",
        "writable" : True,
        "mechanisms" : ("msr", ),
    },
    "ppl2_window" : {
        "name" : "RAPL PPL2 time window",
        "unit" : "s",
        "type" : "float",
        "sname": "package",
        "writable" : False,
        "mechanisms" : ("msr", ),
    },
}

class Power(_PropsClassBase.PropsClassBase):
    """
    This class provides API for managing platform settings related to power. Refer to
    '_PropsClassBase.PropsClassBase' docstring for public methods overvew.
    """

    def _get_msr(self):
        """Returns an 'MSR.MSR()' object."""

        if not self._msr:
            from pepclibs.msr import MSR # pylint: disable=import-outside-toplevel

            self._msr = MSR.MSR(self._pman, cpuinfo=self._cpuinfo, enable_cache=self._enable_cache)

        return self._msr

    def _get_pplobj(self):
        """Returns a 'PackagePowerLimit.PackagePowerLimit()' object."""

        if not self._pplobj:
            from pepclibs.msr import PackagePowerLimit # pylint: disable=import-outside-toplevel

            msr = self._get_msr()
            self._pplobj = PackagePowerLimit.PackagePowerLimit(pman=self._pman,
                                                               cpuinfo=self._cpuinfo, msr=msr)

        return self._pplobj

    def _get_ppiobj(self):
        """Returns a 'PackagePowerInfo.PackagePowerInfo()' object."""

        if not self._ppiobj:
            from pepclibs.msr import PackagePowerInfo # pylint: disable=import-outside-toplevel

            msr = self._get_msr()
            self._ppiobj = PackagePowerInfo.PackagePowerInfo(pman=self._pman,
                                                             cpuinfo=self._cpuinfo, msr=msr)

        return self._ppiobj

    @staticmethod
    def _pname2fname(pname):
        """Get 'PackagePowerLimit' class feature name by property name."""

        return pname.replace("ppl", "limit")

    def _get_cpu_prop_value(self, pname, cpu, prop=None):
        """Returns property value for 'pname' in 'prop' for CPU 'cpu'."""

        if prop is None:
            prop = self._props[pname]

        _LOG.debug("getting '%s' (%s) for CPU %d%s", pname, prop["name"], cpu, self._pman.hostmsg)

        try:
            if pname.startswith("ppl"):
                fname = self._pname2fname(pname)
                return self._get_pplobj().read_cpu_feature(fname, cpu)

            return self._get_ppiobj().read_cpu_feature(pname, cpu)
        except ErrorNotSupported:
            return None

    def _set_prop_value(self, pname, val, cpus):
        """Sets user-provided property 'pname' to value 'val' for CPUs 'cpus'."""

        fname = self._pname2fname(pname)
        for cpu in cpus:
            self._get_pplobj().write_cpu_feature(fname, val, cpu)

    def _set_props(self, inprops, cpus):
        """Refer to '_set_props() in '_PropsClassBase' class."""

        for pname, val in inprops.items():
            self._set_prop_value(pname, val, cpus)

    def _set_sname(self, pname):
        """Set scope "sname" for property 'pname'."""

        if self._props[pname]["sname"]:
            return

        raise Error(f"BUG: scope for property '{pname}' not defined.")

    def __init__(self, pman=None, cpuinfo=None, msr=None, enable_cache=True):
        """
        The class constructor. The arguments are as follows.
          * pman - the process manager object that defines the target host.
          * cpuinfo - CPU information object generated by 'CPUInfo.CPUInfo()'.
          * msr - an 'MSR.MSR()' object which should be used for accessing MSR registers.
          * enable_cache - this argument can be used to disable caching.
        """

        super().__init__(pman=pman, cpuinfo=cpuinfo, msr=msr)
        self._pplobj = None
        self._ppiobj = None
        self._enable_cache = enable_cache

        self._init_props_dict(PROPS)

    def close(self):
        """Uninitialize the class object."""

        ClassHelpers.close(self, close_attrs=("_pplobj", "_ppiobj",))

        super().close()
