# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2020-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Authors: Antti Laakso <antti.laakso@linux.intel.com>
#          Artem Bityutskiy <artem.bityutskiy@linux.intel.com>
#
# Parts of the code was contributed by Len Brown <len.brown@intel.com>.

"""
This module provides a capability of reading and changing EPB (Energy Performance Bias) on Intel
CPUs.
"""

from pepclibs.helperlibs.Exceptions import Error, ErrorNotSupported
from pepclibs.helperlibs import LocalProcessManager, Trivial, ClassHelpers
from pepclibs import CPUInfo
from pepclibs.msr import MSR, EnergyPerfBias

# EPB policy to EPB value map. The names are from the following Linux kernel header file:
#   arch/x86/include/asm/msr-index.h
#
# Note, we do not expose the values to the user because they are platform-specific (not in current
# implementation, but this may change in the future).
_EPB_POLICIES = {"performance": 0,
                 "balance-performance": 4,
                 "normal": 6,
                 "balance-power": 8,
                 "power": 15}

# The minimum and maximum EPB values.
_EPB_MIN, _EPB_MAX = 0, 15

class EPB(ClassHelpers.SimpleCloseContext):
    """
    This class provides a capability of reading and changing EPB (Energy Performance Bias) on Intel
    CPUs.

    Public methods overview.

    1. Multiple CPUs.
        * Get/set EPB through MSR: 'get_epb_hw()', 'set_epb_hw()'.
    2. Single CPU.
        * Get/set EPB through MSR: 'get_cpu_epb_hw()', 'set_cpu_epb_hw()'.
    """

    def _get_msrobj(self):
        """Returns an 'MSR.MSR()' object."""

        if not self._msr:
            self._msr = MSR.MSR(self._pman, cpuinfo=self._cpuinfo, enable_cache=self._enable_cache)
        return self._msr

    def _get_epbobj(self):
        """Returns an 'EnergyPerfBias.EnergyPerfBias()' object."""

        if not self._epb_msr:
            msr = self._get_msrobj()
            self._epb_msr = EnergyPerfBias.EnergyPerfBias(pman=self._pman, cpuinfo=self._cpuinfo,
                                                          msr=msr)
        return self._epb_msr

# ------------------------------------------------------------------------------------------------ #
# Get EPB through MSR (OS bypass).
# ------------------------------------------------------------------------------------------------ #

    def _get_cpu_epb_from_msr(self, cpu):
        """Get EPB for CPU 'cpu' from MSR."""

        _epb = self._get_epbobj()

        try:
            return _epb.read_cpu_feature("epb", cpu)
        except ErrorNotSupported:
            return None

    def get_epb_hw(self, cpus="all"):
        """
        Yield (CPU number, EPB value) pairs for CPUs in 'cpus'. The EPB value is read via MSR.
        The arguments are as follows.
          * cpus - list of CPUs and CPU ranges. This can be either a list or a string containing a
                   comma-separated list. For example, "0-4,7,8,10-12" would mean CPUs 0 to 4, CPUs
                   7, 8, and 10 to 12. 'None' and 'all' mean "all CPUs" (default).
        """

        for cpu in self._cpuinfo.normalize_cpus(cpus):
            yield (cpu, self._get_cpu_epb_from_msr(cpu))

    def get_cpu_epb_hw(self, cpu):
        """Similar to 'get_epb_hw()', but for a single CPU 'cpu'."""

        cpu = self._cpuinfo.normalize_cpu(cpu)
        return self._get_cpu_epb_from_msr(cpu)

# ------------------------------------------------------------------------------------------------ #
# Set EPB through MSR (OS bypass).
# ------------------------------------------------------------------------------------------------ #

    def set_epb_hw(self, epb, cpus="all"):
        """
        Set EPB for CPUs in 'cpus'. The arguments are as follows.
          * epb - the EPB value to set. Can be an integer, a string representing an integer, or one
                  of the EPB policy names.
          * cpus - list of CPUs and CPU ranges. This can be either a list or a string containing a
                   comma-separated list. For example, "0-4,7,8,10-12" would mean CPUs 0 to 4, CPUs
                   7, 8, and 10 to 12. 'None' and 'all' mean "all CPUs" (default).
        """

        if Trivial.is_int(epb):
            Trivial.validate_value_in_range(int(epb), _EPB_MIN, _EPB_MAX, what="EPB value")
        else:
            epb_policy = epb.lower()
            if epb_policy not in _EPB_POLICIES:
                policy_names = ", ".join(_EPB_POLICIES)
                raise Error(f"EPB policy '{epb}' is not supported{self._pman.hostmsg}, please "
                            f"provide one of the following EPB policy names: {policy_names}")
            epb = _EPB_POLICIES[epb_policy]

        self._get_epbobj().write_feature("epb", int(epb), cpus=cpus)

    def set_cpu_epb_hw(self, epb, cpu):
        """Similar to 'set_epb_hw()', but for a single CPU 'cpu'."""

        self.set_epb_hw(epb, cpus=(cpu,))

# ------------------------------------------------------------------------------------------------ #

    def __init__(self, pman=None, cpuinfo=None, msr=None, enable_cache=True):
        """
        The class constructor. The argument are as follows.
          * pman - the process manager object that defines the host to manage EPB for.
          * cpuinfo - CPU information object generated by 'CPUInfo.CPUInfo()'.
          * msr - an 'MSR.MSR()' object which should be used for accessing MSR registers.
          * enable_cache - this argument can be used to disable caching.
        """

        self._pman = pman
        self._cpuinfo = cpuinfo
        self._msr = msr
        self._enable_cache = enable_cache

        self._close_pman = pman is None
        self._close_cpuinfo = cpuinfo is None
        self._close_msr = msr is None

        self._epb_msr = None

        if not self._pman:
            self._pman = LocalProcessManager.LocalProcessManager()

        if not self._cpuinfo:
            self._cpuinfo = CPUInfo.CPUInfo(pman=self._pman)

        if self._cpuinfo.info["vendor"] != "GenuineIntel":
            raise ErrorNotSupported(f"unsupported vendor {cpuinfo.info['vendor']}{pman.hostmsg}. "
                                    f"Only Intel CPUs are supported.")

    def close(self):
        """Uninitialize the class object."""

        close_attrs = ("_epb_msr", "_msr", "_cpuinfo", "_pman")
        ClassHelpers.close(self, close_attrs=close_attrs)
