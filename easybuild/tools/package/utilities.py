##
# Copyright 2015-2015 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##

"""
Various utilities related to packaging support.

@author: Marc Litherland (Novartis)
@author: Gianluca Santarossa (Novartis)
@author: Robert Schmidt (The Ottawa Hospital, Research Institute)
@author: Fotis Georgatos (Uni.Lu, NTUA)
@author: Kenneth Hoste (Ghent University)
"""
import os
import tempfile
import pprint

from vsc.utils import fancylogger
from vsc.utils.missing import get_subclasses
from vsc.utils.patterns import Singleton

from easybuild.tools.config import PKG_TOOL_FPM, PKG_TYPE_RPM, build_option, \
    get_package_naming_scheme
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import which
from easybuild.tools.package.package_naming_scheme.pns import PackageNamingScheme
from easybuild.tools.run import run_cmd
from easybuild.tools.toolchain import DUMMY_TOOLCHAIN_NAME
from easybuild.tools.utilities import import_available_modules, quote_str


_LOG = fancylogger.getLogger('tools.package')


def avail_package_naming_schemes():
    """
    Returns the list of valed naming schemes
    They are loaded from the easybuild.package.package_naming_scheme namespace
    """
    import_available_modules('easybuild.tools.package.package_naming_scheme')
    class_dict = dict([(x.__name__, x) for x in get_subclasses(PackageNamingScheme)])
    return class_dict


def package(easyblock):
    """
    Package installed software, according to active packaging configuration settings."""
    pkgtool = build_option('package_tool')

    if pkgtool == PKG_TOOL_FPM:
        pkgdir = package_with_fpm(easyblock)
    else:
        raise EasyBuildError("Unknown packaging tool specified: %s", pkgtool)

    return pkgdir


def package_with_fpm(easyblock):
    """
    This function will build a package using fpm and return the directory where the packages are
    """
    workdir = tempfile.mkdtemp(prefix='eb-pkgs-')
    pkgtype = build_option('package_type')
    _LOG.info("Will be creating %s package(s) in %s", pkgtype, workdir)

    try:
        origdir = os.getcwd()
        os.chdir(workdir)
    except OSError, err:
        raise EasyBuildError("Failed to chdir into workdir %s: %s", workdir, err)

    package_naming_scheme = ActivePNS()

    pkgname = package_naming_scheme.name(easyblock.cfg)
    pkgver = package_naming_scheme.version(easyblock.cfg)
    pkgrel = package_naming_scheme.release(easyblock.cfg)

    _LOG.debug("Got the PNS values for (name, version, release): (%s, %s, %s)", pkgname, pkgver, pkgrel)
    deps = []
    if easyblock.toolchain.name != DUMMY_TOOLCHAIN_NAME:
        toolchain_dict = easyblock.toolchain.as_dict()
        deps.extend([toolchain_dict])

    deps.extend(easyblock.cfg.dependencies())

    _LOG.debug("The dependencies to be added to the package are: %s",
               pprint.pformat([easyblock.toolchain.as_dict()] + easyblock.cfg.dependencies()))
    depstring = ''
    for dep in deps:
        _LOG.debug("The dep added looks like %s ", dep)
        dep_pkgname = package_naming_scheme.name(dep)
        depstring += " --depends %s" % quote_str(dep_pkgname)

    cmdlist = [
        PKG_TOOL_FPM,
        '--workdir', workdir,
        '--name', quote_str(pkgname),
        '--provides', quote_str(pkgname),
        '-t', pkgtype,  # target
        '-s', 'dir',  # source
        '--version', pkgver,
        '--iteration', pkgrel,
        '--description', quote_str(easyblock.cfg["description"]),
        '--url', quote_str(easyblock.cfg["homepage"]),
        depstring,
        easyblock.installdir,
        easyblock.module_generator.get_module_filepath(),
    ]
    cmd = ' '.join(cmdlist)
    _LOG.debug("The flattened cmdlist looks like: %s", cmd)
    run_cmd(cmd, log_all=True, simple=True)

    _LOG.info("Created %s package(s) in %s", pkgtype, workdir)

    try:
        os.chdir(origdir)
    except OSError, err:
        raise EasyBuildError("Failed to chdir back to %s: %s", origdir, err)

    return workdir


def check_pkg_support():
    """Check whether packaging is supported, i.e. whether the required dependencies are available."""
    pkgtool = build_option('package_tool')
    pkgtool_path = which(pkgtool)
    if pkgtool_path:
        _LOG.info("Selected packaging tool '%s' found at %s", pkgtool, pkgtool_path)

        # rpmbuild is required for generating RPMs with FPM
        if pkgtool == PKG_TOOL_FPM and build_option('package_type') == PKG_TYPE_RPM:
            rpmbuild_path = which('rpmbuild')
            if rpmbuild_path:
                _LOG.info("Required tool 'rpmbuild' found at %s", rpmbuild_path)
            else:
                raise EasyBuildError("rpmbuild is required when generating RPM packages with FPM, but was not found")

    else:
        raise EasyBuildError("Selected packaging tool '%s' not found", pkgtool)


class ActivePNS(object):
    """
    The wrapper class for Package Naming Schemes.
    """
    __metaclass__ = Singleton

    def __init__(self):
        """Initialize logger and find available PNSes to load"""
        self.log = fancylogger.getLogger(self.__class__.__name__, fname=False)

        avail_pns = avail_package_naming_schemes()
        sel_pns = get_package_naming_scheme()
        if sel_pns in avail_pns:
            self.pns = avail_pns[sel_pns]()
        else:
            raise EasyBuildError("Selected package naming scheme %s could not be found in %s",
                                 sel_pns, avail_pns.keys())

    def name(self, easyconfig):
        """Determine package name"""
        name = self.pns.name(easyconfig)
        return name

    def version(self, easyconfig):
        """Determine package version"""
        version = self.pns.version(easyconfig)
        return version

    def release(self, easyconfig):
        """Determine package release"""
        release = self.pns.release()
        return release
