# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 tw=100 et ai si
#
# Copyright (C) 2020-2023 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#
# Authors: Artem Bityutskiy <artem.bityutskiy@linux.intel.com>
#          Antti Laakso <antti.laakso@linux.intel.com>
#          Niklas Neronin <niklas.neronin@intel.com>

"""
This module provides the base class for classes implementing properties, such as 'PState' and
'CState' classes.

Naming conventions:
 * props - dictionary describing the properties. As an example, check 'PROPS' in 'PStates' and
           'CStates'.
 * pinfo - a properties dictionary in the format returned described in 'PropsClassBase.get_props()'.
 * pname - name of a property.
 * sname - name of a scope from the allowed list of scope names in 'CPUInfo.LEVELS'.
 * <sname> siblings - all CPUs sharing the same <sname>. E.g. "package siblings" means all CPUs
                      sharing the same package, "CPU 6 core siblings" means all CPUs sharing the
                      same core as CPU 6.
"""

import copy
import logging
from pepclibs import CPUInfo
from pepclibs.helperlibs import Human, ClassHelpers, LocalProcessManager
from pepclibs.helperlibs.Exceptions import ErrorNotSupported, Error

_LOG = logging.getLogger()

def _bug_method_not_defined(method_name):
    """Raise an error if the child class did not define the 'method_name' mandatory method."""

    raise Error(f"BUG: '{method_name}()' was not defined by the child class")

class PropsClassBase(ClassHelpers.SimpleCloseContext):
    """
    Base class for higher level classes implementing properties (e.g. 'CStates' or 'PStates').
    """

    def _set_sname(self, pname):
        """
        Set scope "sname" for property 'pname'. This method is useful in cases where property scope
        depends on the platform.
        """

        if self._props[pname]["sname"]:
            return

        _bug_method_not_defined("PropsClassBase._set_sname")

    def get_sname(self, pname):
        """Get scope "sname" for property 'pname'."""

        try:
            if not self._props[pname]["sname"]:
                self._set_sname(pname)

            return self._props[pname]["sname"]
        except KeyError as err:
            raise Error(f"property '{pname}' does not exist") from err

    @staticmethod
    def _normalize_bool_type_value(prop, val):
        """
        Normalize and validate value 'val' of a boolean-type property 'prop'. Returns the boolean
        value corresponding to 'val'.
        """

        if val in (True, False):
            return val

        val = val.lower()
        if val in ("on", "enable"):
            return True

        if val in ("off", "disable"):
            return False

        name = Human.uncapitalize(prop["name"])
        raise Error(f"bad value '{val}' for {name}, use one of: True, False, on, off, enable, "
                    f"disable")

    def _validate_pname(self, pname):
        """Raise an error if a property 'pname' is not supported."""

        if pname not in self._props:
            pnames_str = ", ".join(set(self._props))
            raise ErrorNotSupported(f"property '{pname}' is not supported{self._pman.hostmsg}, use "
                                    f"one of the following: {pnames_str}")

    def _get_cpu_prop_value(self, pname, cpu, prop=None):
        """Returns property value for 'pname' in 'prop' for CPU 'cpu'."""

        # pylint: disable=unused-argument
        return _bug_method_not_defined("PropsClassBase._get_cpu_prop_value")

    def _get_cpu_subprop_value(self, pname, subpname, cpu):
        """Returns sup-property 'subpname' of property 'pname' for CPU 'cpu'."""

        subprop = self._props[pname]["subprops"][subpname]
        return self._get_cpu_prop_value(subpname, cpu, prop=subprop)

    def _get_cpu_props(self, pnames, cpu):
        """Returns all properties in 'pnames' for CPU 'cpu'."""

        pinfo = {}

        for pname in pnames:
            pinfo[pname] = {}

            # Get the 'pname' property.
            pinfo[pname][pname] = self._get_cpu_prop_value(pname, cpu)
            if pinfo[pname][pname] is None:
                _LOG.debug("CPU %d: %s is not supported", cpu, pname)
                continue
            _LOG.debug("CPU %d: %s = %s", cpu, pname, pinfo[pname][pname])

            # Get all the sub-properties.
            for subpname in self._props[pname]["subprops"]:
                if pinfo[pname][pname] is not None:
                    # Get the 'subpname' sub-property.
                    pinfo[pname][subpname] = self._get_cpu_subprop_value(pname, subpname, cpu)
                else:
                    # The property is not supported, so all sub-properties are not supported either.
                    pinfo[pname][subpname] = None
                _LOG.debug("CPU %d: %s = %s", cpu, subpname, pinfo[pname][subpname])

        return pinfo

    def get_props(self, pnames, cpus="all"):
        """
        Read all properties specified in the 'pnames' list for CPUs in 'cpus', and for every CPU
        yield a ('cpu', 'pinfo') tuple, where 'pinfo' is dictionary containing the read values of
        all the properties. The arguments are as follows.
          * pnames - list or an iterable collection of properties to read and yield the values for.
                     These properties will be read for every CPU in 'cpus'.
          * cpus - collection of integer CPU numbers. Special value 'all' means "all CPUs".

        The yielded 'pinfo' dictionaries have the following format.

        { property1_name: { property1_name : property1_value,
                            subprop1_key : subprop1_value,
                            subprop2_key : subprop2_value,
                            ... etc for every key ...},
          property2_name: { property2_name : property2_value,
                            subprop1_key : subprop2_value,
                            ... etc ...},
          ... etc ... }

        So each property has the (main) value, and possibly sub-properties, which provide additional
        read-only information related to the property. For example, the 'governor' property comes
        with the 'governors' sub-property. Most properties have no sub-properties.

        If a property is not supported, its value will be 'None'.

        Properties of "bool" type use the following values:
           * "on" if the feature is enabled.
           * "off" if the feature is disabled.
        """

        for pname in pnames:
            self._validate_pname(pname)

        for cpu in self._cpuinfo.normalize_cpus(cpus):
            yield cpu, self._get_cpu_props(pnames, cpu)

    def get_cpu_props(self, pnames, cpu):
        """Same as 'get_props()', but for a single CPU."""

        pinfo = None
        for _, pinfo in self.get_props(pnames, cpus=(cpu,)):
            pass
        return pinfo

    def get_cpu_prop(self, pname, cpu):
        """Same as 'get_props()', but for a single CPU and a single property."""

        pinfo = None
        for _, pinfo in self.get_props((pname,), cpus=(cpu,)):
            pass
        return pinfo

    def _normalize_inprops(self, inprops):
        """Normalize the 'inprops' argument of the 'set_props()' method and return the result."""

        def _add_prop(pname, val):
            """Add property 'pname' to the 'result' dictionary."""

            self._validate_pname(pname)

            prop = self._props[pname]
            if not prop["writable"]:
                name = Human.uncapitalize(prop["name"])
                raise Error(f"{name} is read-only and can not be modified{self._pman.hostmsg}")

            if pname in result:
                _LOG.warning("duplicate property '%s': dropping value '%s', keeping '%s'",
                             pname, result[pname], val)

            if prop.get("type") == "bool":
                val = self._normalize_bool_type_value(prop, val)

            result[pname] = val

        result = {}
        if hasattr(inprops, "items"):
            for pname, val in inprops.items():
                _add_prop(pname, val)
        else:
            for pname, val in inprops:
                _add_prop(pname, val)

        return result

    def _validate_cpus_vs_scope(self, prop, cpus):
        """Make sure that CPUs in 'cpus' match the scope of a property described by 'prop'."""

        sname = prop["sname"]

        if sname not in {"global", "package", "die", "core", "CPU"}:
            raise Error(f"BUG: unsupported scope name \"{sname}\"")

        if sname == "CPU":
            return

        if sname == "global":
            all_cpus = set(self._cpuinfo.get_cpus())

            if all_cpus.issubset(cpus):
                return

            name = Human.uncapitalize(prop["name"])
            missing_cpus = all_cpus - set(cpus)
            raise Error(f"{name} has {sname} scope, so the list of CPUs must include all CPUs.\n"
                        f"However, the following CPUs are missing from the list: {missing_cpus}")

        _, rem_cpus = getattr(self._cpuinfo, f"cpus_div_{sname}s")(cpus)
        if not rem_cpus:
            return

        mapping = ""
        for pkg in self._cpuinfo.get_packages():
            pkg_cpus = self._cpuinfo.package_to_cpus(pkg)
            pkg_cpus_str = Human.rangify(pkg_cpus)
            mapping += f"\n  * package {pkg}: CPUs: {pkg_cpus_str}"

            if sname in {"core", "die"}:
                # Build the cores or dies to packages map, in order to make the error message more
                # helpful. We use "core" in variable names, but in case of the "die" scope name,
                # they actually mean "die".

                pkg_cores = getattr(self._cpuinfo, f"package_to_{sname}s")(pkg)
                pkg_cores_str = Human.rangify(pkg_cores)
                mapping += f"\n               {sname}s: {pkg_cores_str}"

                # Build the cores to CPUs mapping string.
                clist = []
                for core in pkg_cores:
                    if sname == "core":
                        cpus = self._cpuinfo.cores_to_cpus(cores=(core,), packages=(pkg,))
                    else:
                        cpus = self._cpuinfo.dies_to_cpus(dies=(core,), packages=(pkg,))
                    cpus_str = Human.rangify(cpus)
                    clist.append(f"{core}:{cpus_str}")

                # The core/die->CPU mapping may be very long, wrap it to 100 symbols.
                import textwrap # pylint: disable=import-outside-toplevel

                prefix = f"               {sname}s to CPUs: "
                indent = " " * len(prefix)
                clist_wrapped = textwrap.wrap(", ".join(clist), width=100,
                                              initial_indent=prefix, subsequent_indent=indent)
                clist_str = "\n".join(clist_wrapped)

                mapping += f"\n{clist_str}"

        name = Human.uncapitalize(prop["name"])
        rem_cpus_str = Human.rangify(rem_cpus)

        if sname == "core":
            mapping_name = "relation between CPUs, cores, and packages"
        elif sname == "die":
            mapping_name = "relation between CPUs, dies, and packages"
        else:
            mapping_name = "relation between CPUs and packages"

        errmsg = f"{name} has {sname} scope, so the list of CPUs must include all CPUs " \
                 f"in one or multiple {sname}s.\n" \
                 f"However, the following CPUs do not comprise full {sname}(s): {rem_cpus_str}\n" \
                 f"Here is the {mapping_name}{self._pman.hostmsg}:{mapping}"

        raise Error(errmsg)

    def _set_props(self, inprops, cpus):
        """
        Implements 'set_props()'. The arguments are as follows.
          * inprops - normalized and partially validated version for 'inprops' in passed to
                      'set_props()'.
          * cpus - same as in 'set_props()', but normalized and validated.
        """

        # pylint: disable=unused-argument
        return _bug_method_not_defined("PropsClassBase.set_props")

    def set_props(self, inprops, cpus="all"):
        """
        Set multiple properties described by 'inprops' to values also provided in 'inprops'.
          * inprops - an iterable collection of property names and values.
          * cpus - same as in 'get_props()'.

        This method accepts two 'inprops' formats.

        1. An iterable collection (e.g., list or a tuple) of ('pname', 'val') pairs. For example:
           * [(property1_name, property1_value), (property2_name, property2_value)]
        2. A dictionary with property names as keys. For example:
           * {property1_name : property1_value, property2_name : property2_value}

        Properties of "bool" type accept the following values:
           * True, "on", "enable" for enabling the feature.
           * False, "off", "disable" for disabling the feature.
        """

        inprops = self._normalize_inprops(inprops)
        cpus = self._cpuinfo.normalize_cpus(cpus)

        for pname in inprops:
            self._set_sname(pname)
            self._validate_cpus_vs_scope(self._props[pname], cpus)

        self._set_props(inprops, cpus)

    def set_prop(self, pname, val, cpus):
        """Same as 'set_props()', but for a single property."""

        self.set_props(((pname, val),), cpus=cpus)

    def set_cpu_props(self, inprops, cpu):
        """Same as 'set_props()', but for a single CPU."""

        self.set_props(inprops, cpus=(cpu,))

    def set_cpu_prop(self, pname, val, cpu):
        """Same as 'set_props()', but for a single CPU and a single property."""

        self.set_props(((pname, val),), cpus=(cpu,))

    def _init_props_dict(self, props):
        """Initialize the 'props' dictionary."""

        for pinfo in props.values():
            # Every features should include the 'subprops' sub-dictionary.
            if "subprops" not in pinfo:
                pinfo["subprops"] = {}

            # Propagate the "mechanisms" key to sub-propeties.
            if "mechanisms" in pinfo:
                for subpinfo in pinfo["subprops"].values():
                    subpinfo["mechanisms"] = pinfo["mechanisms"]

        self._props = copy.deepcopy(props)
        self.props = props

    def __init__(self, pman=None, cpuinfo=None, msr=None):
        """
        The class constructor. The arguments are as follows.
          * pman - the process manager object that defines the target system..
          * cpuinfo - CPU information object generated by 'CPUInfo.CPUInfo()'.
          * msr - an 'MSR.MSR()' object which should be used for accessing MSR registers.
        """

        self._pman = pman
        self._cpuinfo = cpuinfo
        self._msr = msr

        self._close_pman = pman is None
        self._close_cpuinfo = cpuinfo is None
        self._close_msr = msr is None

        self.props = None
        # Internal version of 'self.props'. Contains some data which we don't want to expose to the
        # user.
        self._props = None

        if not self._pman:
            self._pman = LocalProcessManager.LocalProcessManager()
        if not self._cpuinfo:
            self._cpuinfo = CPUInfo.CPUInfo(pman=self._pman)

    def close(self):
        """Uninitialize the class object."""

        close_attrs = ("_msr", "_cpuinfo", "_pman")
        ClassHelpers.close(self, close_attrs=close_attrs)
