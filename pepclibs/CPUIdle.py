# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Authors: Antti Laakso <antti.laakso@linux.intel.com>
#          Artem Bityutskiy <artem.bityutskiy@linux.intel.com>

"""
This module provides API for dealing with the Linux "cpuidle" subsystem.
"""

import re
import copy
import logging
from pathlib import Path
from pepclibs.helperlibs import FSHelpers, Procs, Trivial
from pepclibs.helperlibs.Exceptions import Error
from pepclibs import CPUInfo
from pepclibs.msr import PowerCtl, PCStateConfigCtl

_LOG = logging.getLogger()

# The keys in the C-states information dictionary generated by 'get_cstates_info()', along with
# the description.
_KEYS_DESCR = {
    "CPU": "Logical CPU number",
    "cstate_prewake" : "C-state prewake enabled",
    "cstate_prewake_supported" : "C-state prewake support",
    "c1e_autopromote" : "C1E autopromote enabled",
    "pkg_cstate_limit_supported" : "Package C-state limit support",
    "pkg_cstate_limit" : "Package C-state limit",
    "pkg_cstate_limit_locked" : "Package C-state limit locked",
    "pkg_cstate_limits" : "Available package C-state limits",
    "c1_demotion" : "C1 demotion enabled",
    "c1_undemotion" : "C1 un-demotion enabled",
}

# This dictionary describes various CPU properties this module controls.
#
# Note 1: consider using the 'CPUIdle.props' dicionary instead of this one.
# Note 2: the "scope" names have to be the same as "level" names in 'CPUInfo'.
PROPS = {}
PROPS.update(PowerCtl.FEATURES)
PROPS.update(PCStateConfigCtl.FEATURES)

class CPUIdle:
    """This class provides API to the "cpuidle" Linux sybsystem."""

    def _get_cpuinfo(self):
        """Return an instance of 'CPUInfo' class."""

        if not self._cpuinfo:
            self._cpuinfo = CPUInfo.CPUInfo(proc=self._proc)
        return self._cpuinfo

    def _get_powerctl(self):
        """Return an instance of 'PowerCtl' class."""

        if self._powerctl is None:
            cpuinfo = self._get_cpuinfo()
            self._powerctl = PowerCtl.PowerCtl(proc=self._proc, cpuinfo=cpuinfo, msr=self._msr)
        return self._powerctl

    def _get_pcstatectl(self):
        """Return an instance of 'PCStateConfigCtl' class."""

        if self._pcstatectl is None:
            cpuinfo = self._get_cpuinfo()
            self._pcstatectl = PCStateConfigCtl.PCStateConfigCtl(proc=self._proc, cpuinfo=cpuinfo,
                                                                 msr=self._msr)
        return self._pcstatectl

    def _get_cstate_indexes(self, cpu):
        """Yield tuples of of C-state indexes and sysfs paths for cpu number 'cpu'."""

        basedir = self._sysfs_base / f"cpu{cpu}" / "cpuidle"
        name = None
        for name, path, typ in FSHelpers.lsdir(basedir, proc=self._proc):
            errmsg = f"unexpected entry '{name}' in '{basedir}'{self._proc.hostmsg}"
            if typ != "/" or not name.startswith("state"):
                raise Error(errmsg)
            index = name[len("state"):]
            if not Trivial.is_int(index):
                raise Error(errmsg)
            yield int(index), Path(path)

        if name is None:
            raise Error(f"C-states are not supported{self._proc.hostmsg}")

    def _name2idx(self, name, cpu=0):
        """Return C-state index for C-state name 'name'."""

        if cpu in self._name2idx_cache:
            if name in self._name2idx_cache[cpu]:
                return self._name2idx_cache[cpu][name]
        else:
            self._name2idx_cache[cpu] = {}

        names = []
        for index, path in self._get_cstate_indexes(cpu):
            with self._proc.open(path / "name", "r") as fobj:
                val = fobj.read().strip().upper()
            self._name2idx_cache[cpu][val] = index
            if val == name:
                return index
            names.append(val)

        names = ", ".join(names)
        raise Error(f"unkown C-state '{name}', here are the C-states supported"
                    f"{self._proc.hostmsg}:\n{names}")

    def _idx2name(self, index, cpu=0):
        """Return C-state name for C-state index 'index'."""

        if cpu in self._idx2name_cache:
            if index in self._idx2name_cache[cpu]:
                return self._idx2name_cache[cpu][index]

        if cpu not in self._csinfos:
            self._csinfos[cpu] = self.get_cstates_info_dict(cpu)

        self._idx2name_cache[cpu] = {}
        for csinfo in self._csinfos[cpu].values():
            self._idx2name_cache[cpu][csinfo['index']] = csinfo['name']

        if index not in self._idx2name_cache[cpu]:
            indices = ", ".join(f"{idx} ({v['name']})" for idx, v in  self._csinfos[cpu].items())
            raise Error(f"unkown C-state index '{index}', here are the C-state indices supported"
                        f"{self._proc.hostmsg}:\n{indices}") from None

        return self._idx2name_cache[cpu][index]

    def _normalize_cstates(self, cstates):
        """
        Some methods accept the C-states to operate on as a string or a list. This method normalizes
        the C-states 'cstates' and returns a list of integer C-state indices. 'cstates' can be:
          * a C-state name
          * a C-state index as a string or an integer
          * a list containing one or more of the above
          * a string containing comma-separated C-state indices or names
        """

        if cstates in ("all", None):
            return None

        if isinstance(cstates, int):
            cstates = str(cstates)
        if isinstance(cstates, str):
            cstates = Trivial.split_csv_line(cstates, dedup=True)

        indices = []
        for cstate in cstates:
            if not Trivial.is_int(cstate):
                cstate = self._name2idx(cstate.upper())
            idx = int(cstate)
            if idx not in indices:
                indices.append(idx)

        return indices

    def _normalize_cpus(self, cpus):
        """
        Some methods accept CPUs as list or range of CPUs as described in 'get_cstates_info()'.
        Turn this userinput in 'cpus' as list of integers and return it.
        """

        cpuinfo = self._get_cpuinfo()
        return cpuinfo.normalize_cpus(cpus)

    def _toggle_cstate(self, cpu, index, enable):
        """Enable or disable the 'index' C-state for CPU 'cpu'."""

        path = self._sysfs_base / f"cpu{cpu}" / "cpuidle" / f"state{index}" / "disable"
        if enable:
            val = "0"
            action = "enable"
        else:
            val = "1"
            action = "disable"

        msg = f"{action} C-state with index '{index}' for CPU {cpu}"
        _LOG.debug(msg)

        try:
            with self._proc.open(path, "r+") as fobj:
                fobj.write(val + "\n")
        except Error as err:
            raise Error(f"failed to {msg}:\n{err}") from err

        try:
            with self._proc.open(path, "r") as fobj:
                read_val = fobj.read().strip()
        except Error as err:
            raise Error(f"failed to {msg}:\n{err}") from err

        if val != read_val:
            raise Error(f"failed to {msg}:\nfile '{path}' contains '{read_val}', but should "
                        f"contain '{val}'")

    def _do_toggle_cstates(self, cpus, indexes, enable):
        """Implements '_toggle_cstates()'."""

        toggled = {}
        go_cpus = cpus
        go_indexes = indexes

        if cpus is not None:
            cpus = set(cpus)
        if indexes is not None:
            indexes = set(indexes)

        for info in self._get_cstates_info(go_cpus, go_indexes, False):
            cpu = info["CPU"]
            index = info["index"]
            if (cpus is None or cpu in cpus) and (indexes is None or index in indexes):
                self._toggle_cstate(cpu, index, enable)
                if cpu not in toggled:
                    toggled[cpu] = {"cstates" : []}
                toggled[cpu]["cstates"].append(self._idx2name(index, cpu=cpu))

        return toggled

    def _toggle_cstates(self, cpus=None, cstates=None, enable=True):
        """
        Enable or disable C-states 'cstates' on CPUs 'cpus'. The arguments are as follows.
          * cstates - same as in 'get_cstates_info()'.
          * cpus - same as in 'get_cstates_info()'.
          * enabled - if 'True', the specified C-states should be enabled on the specified CPUS,
                      otherwise disabled.
        """

        cpus = self._normalize_cpus(cpus)

        if isinstance(cstates, str) and cstates != "all":
            cstates = Trivial.split_csv_line(cstates, dedup=True)
        indexes = self._normalize_cstates(cstates)

        return self._do_toggle_cstates(cpus, indexes, enable)

    def enable_cstates(self, cpus=None, cstates=None):
        """
        Enable C-states 'cstates' on CPUs 'cpus'. The 'cstates' and 'cpus' arguments are the same as
        in 'get_cstates_info()'. Returns a dictionary of the following format:

        CPU number:
            csates:
                list of C-state names enabled for the CPU
        """
        return self._toggle_cstates(cpus, cstates, True)

    def disable_cstates(self, cpus=None, cstates=None):
        """
        Similarr to 'enable_cstates()', but disables instead of enabling.
        """
        return self._toggle_cstates(cpus, cstates, False)

    def _get_cstates_info(self, cpus, indexes, ordered):
        """Implements 'get_cstates_info()'."""

        indexes_regex = cpus_regex = "[[:digit:]]+"
        if cpus is not None:
            cpus_regex = "|".join([str(cpu) for cpu in cpus])
        if indexes is not None:
            indexes_regex = "|".join([str(index) for index in indexes])

        cmd = fr"find '{self._sysfs_base}' -type f -regextype posix-extended " \
              fr"-regex '.*cpu({cpus_regex})/cpuidle/state({indexes_regex})/[^/]+' " \
              fr"-exec printf '%s' {{}}: \; -exec grep . {{}} \;"

        stdout, _ = self._proc.run_verify(cmd, join=False)
        if not stdout:
            raise Error(f"failed to find C-states information in '{self._sysfs_base}'"
                        f"{self._proc.hostmsg}")

        if ordered:
            stdout = sorted(stdout)

        regex = re.compile(r".+/cpu([0-9]+)/cpuidle/state([0-9]+)/(.+):([^\n]+)")
        info = {}
        index = prev_index = cpu = prev_cpu = None

        for line in stdout:
            matchobj = re.match(regex, line)
            if not matchobj:
                raise Error(f"failed to parse the follwoing line from file in '{self._sysfs_base}'"
                            f"{self._proc.hostmsg}:\n{line.strip()}")

            cpu = int(matchobj.group(1))
            index = int(matchobj.group(2))
            key = matchobj.group(3)
            val = matchobj.group(4)
            if Trivial.is_int(val):
                val = int(val)

            if prev_cpu is None:
                prev_cpu = cpu
            if prev_index is None:
                prev_index = index

            if cpu != prev_cpu or index != prev_index:
                info["CPU"] = prev_cpu
                info["index"] = prev_index
                yield info
                prev_cpu = cpu
                prev_index = index
                info = {}

            info[key] = val

        info["CPU"] = prev_cpu
        info["index"] = prev_index
        yield info

    def get_cstates_info(self, cpus=None, cstates=None, ordered=True):
        """
        Yield information about C-states specified in 'cstate' for CPUs specified in 'cpus'.
          * cpus - list of CPUs and CPU ranges. This can be either a list or a string containing a
                   comma-separated list. For example, "0-4,7,8,10-12" would mean CPUs 0 to 4, CPUs
                   7, 8, and 10 to 12. 'None' and 'all' mean "all CPUs" (default).
          * cstates - the list of C-states to get information about. The list can contain both
                      C-state names and C-state indexes. It can be both a list or a string
                      containing a comma-separated list. 'None' and 'all' mean "all C-states"
                      (default).
          * ordered - if 'True', the yielded C-states will be ordered so that smaller CPU numbers
                      will go first, and for each CPU number shallower C-states will go first.
        """

        cpus = self._normalize_cpus(cpus)
        indexes = self._normalize_cstates(cstates)

        for cpu in cpus:
            if cpu in self._csinfos:
                # We have the C-states info for this CPU cached.
                if indexes is None:
                    indices = self._csinfos[cpu].keys()
                else:
                    indices = indexes
                for idx in indices:
                    yield self._csinfos[cpu][idx]
            else:
                # The C-state info for this CPU is not available in the cache.
                # Current implementation limitation: the C-state cache is a per-CPU dictionary. The
                # dictionary includes all C-states available for this CPU. Therefore, even if user
                # requested only partial information (not all C-states), we read information about
                # all the C-states anyway. This limitation makes this function slower than
                # necessary.
                self._csinfos[cpu] = {}
                for csinfo in self._get_cstates_info([cpu], None, ordered):
                    self._csinfos[cpu][csinfo['index']] = csinfo
                    yield csinfo

    def get_cstates_info_dict(self, cpu, cstates=None, ordered=True):
        """
        Returns a dictionary describing all C-states of CPU 'cpu'. C-state index is used as
        dictionary key. The 'cstates' and 'ordered' arguments are the same as in
        'get_cstates_info()'.
        """

        if not Trivial.is_int(cpu):
            raise Error(f"bad CPU number '{cpu}', should be an integer")

        info_dict = {}
        for info in self.get_cstates_info(cpus=cpu, cstates=cstates, ordered=ordered):
            info_dict[info["index"]] = info
        return info_dict

    def get_cstate_info(self, cpu, cstate):
        """
        Returns information about C-state 'cstate' on CPU number 'cpu'. The C-state can be specified
        both by its index and name.
        """

        return next(self.get_cstates_info(cpu, cstate))

    def get_cstates_config(self, cpus, keys):
        """
        Yield information about CPU C-state configuration. The arguments are as follows.
          * cpus - the CPUs to yield the information for, same as the 'cpus' argument of the
                   'get_cstates_info()' function.
          * keys - by default this generator yields all the information in form of a dictionary,
                   where each key represents a piece of information. For example, the
                   "c1e_autopromote" key contains information if C1E autopromotion is enabled or
                   disabled. However, if only some of the keys are needed, their names can be
                   specified in 'keys'. For example, in order to ask for C1E autopromotion status
                   and nothing else, use 'keys=("c1e_autopromote",)".
        """

        if not keys:
            keys = _KEYS_DESCR
        keys = set(keys)

        powerctl, pcstatectl = None, None

        if keys.intersection(PowerCtl.FEATURES):
            powerctl = self._get_powerctl()

        if keys.intersection(PCStateConfigCtl.FEATURES):
            pcstatectl = self._get_pcstatectl()
        if not pcstatectl:
            for key in keys:
                if key.startswith("pkg_cstate_limit"):
                    pcstatectl = self._get_pcstatectl()
                    break

        cpuinfo = self._get_cpuinfo()
        for cpu in cpus:
            pkg = cpuinfo.cpu_to_package(cpu)
            info = {}

            if "CPU" in keys:
                info["CPU"] = cpu
            if "core" in keys:
                info["core"] = cpuinfo.cpu_to_core(cpu)
            if "package" in keys:
                info["package"] = pkg
            if "cstate_prewake_supported" in keys:
                info["cstate_prewake_supported"] = powerctl.features["cstate_prewake"]["supported"]
            if "cstate_prewake" in keys:
                if powerctl.features["cstate_prewake"]["supported"]:
                    info["cstate_prewake"] = powerctl.get_feature("cstate_prewake", cpu)
            if "c1e_autopromote" in keys:
                info["c1e_autopromote"] = powerctl.get_feature("c1e_autopromote", cpu)
            if "pkg_cstate_limit_supported" in keys:
                info["pkg_cstate_limit_supported"] = \
                                            pcstatectl.features["pkg_cstate_limit"]["supported"]
            if pcstatectl and pcstatectl.features["pkg_cstate_limit"]["supported"]:
                if "pkg_cstate_limit" in keys:
                    limit_info = pcstatectl.get_feature("pkg_cstate_limit", cpu)
                    info["pkg_cstate_limit"] = limit_info["limit"]
                    info["pkg_cstate_limit_locked"] = limit_info["locked"]
                if "pkg_cstate_limits" in keys:
                    info["pkg_cstate_limits"] = limit_info["limits"]
            if "c1_demotion" in keys:
                info["c1_demotion"] = pcstatectl.get_feature("c1_demotion", cpu)
            if "c1_undemotion" in keys:
                info["c1_undemotion"] = pcstatectl.get_feature("c1_undemotion", cpu)

            yield info

    @staticmethod
    def _check_prop(prop):
        """Raise an error if a property 'prop' is not supported."""

        if prop not in PROPS:
            props_str = ", ".join(set(PROPS))
            raise Error(f"property '{prop}' not supported, use one of the following: "
                        f"{props_str}")

    def set_prop(self, prop, val, cpus="all"):
        """
        Set value 'val' for property 'prop' for CPUs 'cpus'. The arguments are as follows.
          * prop - name of the property to set (see 'PROPS' for the full list).
          * val - the value to set for the property.
          * cpus - same as in 'get_cstates_info()'.
        """

        self._check_prop(prop)

        if prop in PowerCtl.FEATURES:
            powerctl = self._get_powerctl()
            powerctl.set_feature(prop, val=="on", cpus)
        elif prop in PCStateConfigCtl.FEATURES:
            pcstatectl = self._get_pcstatectl()
            pcstatectl.set_feature(prop, val, cpus=cpus)
        else:
            raise Error(f"BUG: undefined property '{prop}'")

    @staticmethod
    def get_scope(prop):
        """Get scope of property 'prop'. The 'prop' argument is same as in 'set_prop()'."""

        CPUIdle._check_prop(prop)

        if prop in PowerCtl.FEATURES:
            return PowerCtl.FEATURES[prop]["scope"]
        if prop in PCStateConfigCtl.FEATURES:
            return PCStateConfigCtl.FEATURES[prop]["scope"]

        raise Error(f"BUG: undefined property '{prop}'")

    @staticmethod
    def _create_props_dict():
        """Create an extended version of the 'PROPS' dictionary."""

        props = copy.deepcopy(PROPS)

        for prop in props:
            props[prop]["keys"] = {}

        # Map each property to the list of keys relevant to this property.
        props["c1_undemotion"]["keys"]   = { "c1_undemotion"  : _KEYS_DESCR["c1_undemotion"] }
        props["c1_demotion"]["keys"]     = {"c1_demotion"     : _KEYS_DESCR["c1_demotion"] }
        props["c1e_autopromote"]["keys"] = {"c1e_autopromote" : _KEYS_DESCR["c1e_autopromote"]}
        props["cstate_prewake"]["keys"]  = {
                    "cstate_prewake"           : _KEYS_DESCR["cstate_prewake"],
                    "cstate_prewake_supported" : _KEYS_DESCR["cstate_prewake_supported"],
                }
        props["pkg_cstate_limit"]["keys"] = {
                    "pkg_cstate_limit_supported" : _KEYS_DESCR["pkg_cstate_limit_supported"],
                    "pkg_cstate_limit"           : _KEYS_DESCR["pkg_cstate_limit"],
                    "pkg_cstate_limits"          : _KEYS_DESCR["pkg_cstate_limits"],
                    "pkg_cstate_limit_locked"    : _KEYS_DESCR["pkg_cstate_limit_locked"],
                }

        return props

    def __init__(self, proc=None, cpuinfo=None, msr=None):
        """
        The class constructor. The arguments are as follows.
          * proc - the 'Proc' or 'SSH' object that defines the host to run the measurements on.
          * cpuinfo - CPU information object generated by 'CPUInfo.CPUInfo()'.
          * msr - an 'MSR.MSR()' object which should be used for accessing MSR registers.
        """

        if not proc:
            proc = Procs.Proc()

        self._proc = proc
        self._cpuinfo = cpuinfo
        self._msr = msr

        self._lscpu_info = None
        self._powerctl = None
        self._pcstatectl = None

        self._sysfs_base = Path("/sys/devices/system/cpu")
        self.props = self._create_props_dict()

        # Used for caching the C-state information for each CPU.
        self._csinfos = {}
        # Used for mapping C-state indices to C-state names and vice versa.
        self._name2idx_cache = {}
        self._idx2name_cache = {}

    def close(self):
        """Uninitialize the class object."""

        if getattr(self, "_pcstatectl", None):
            self._pcstatectl.close()
            self._pcstatectl = None

        if getattr(self, "_powerctl", None):
            self._powerctl.close()
            self._powerctl = None

        if getattr(self, "_proc", None):
            self._proc = None

        if getattr(self, "_cpuinfo", None):
            self._cpuinfo.close()
            self._cpuinfo = None

        if getattr(self, "_msr", None):
            self._msr.close()
            self._msr = None

    def __enter__(self):
        """Enter the runtime context."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit the runtime context."""
        self.close()
