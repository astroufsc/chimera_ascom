
#! /usr/bin/env python
# -*- coding: iso-8859-1 -*-

# chimera - observatory automation system
# Copyright (C) 2007  P. Henrique Silva <henrique@astro.ufsc.br>

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

import sys
import threading
import subprocess
import logging
import time

from chimera.core.exceptions import ChimeraException
from chimera.core.lock import lock

from chimera.util.coord import Coord
from chimera.util.position import Position

from chimera.instruments.telescope import TelescopeBase
from chimera.interfaces.telescope import PositionOutsideLimitsException, TelescopeStatus

log = logging.getLogger(__name__)

if sys.platform == "win32":
    # handle COM multithread support
    # see: Python Programming On Win32, Mark Hammond and Andy Robinson, Appendix D
    #      http://support.microsoft.com/kb/q150777/
    sys.coinit_flags = 0  # pythoncom.COINIT_MULTITHREAD
    #import pythoncom

    from win32com.client import Dispatch
    from pywintypes import com_error

else:
    log.warning("Not on win32. ASCOM  Telescope will not work.")
    #raise ChimeraException("Not on win32. ASCOM Telescope will not work.")


def com(func):
    """
    Wrapper decorator used to handle COM objects errors.
    Every method that use COM method should be decorated.
    """
    def com_wrapper(*args, **kwargs):

        try:
            return func(*args, **kwargs)
        except com_error, e:
            raise ChimeraException(str(e))

    return com_wrapper


class ASCOMTelescope (TelescopeBase):

    __config__ = {"telescope_id": "ScopeSim.Telescope"}

    def __init__(self):
        TelescopeBase.__init__(self)

        self._abort = threading.Event()

        self._ascom = None
        self._ascom = None
        self._idle_time = 0.2
        self._target = None

    @com
    def __start__(self):
        self.open()
        super(ASCOMTelescope, self).__start__()
        return True

    @com
    def __stop__(self):
        self.close()
        super(ASCOMTelescope, self).__stop__()
        return True

    @com
    def open(self):

        try:
            self._ascom = Dispatch(self['telescope_id'])
            self._ascom.Connected = True
        except com_error:
            self.log.error(
                "Couldn't instantiate ASCOM %d COM objects." % self["telescope_id"])
            return False

        return self.unpark()

    @com
    def close(self):
        try:
            # self._ascom.Disconnect()
            # self._ascom.DisconnectTelescope()
            # self._ascom.Disconnect()
            self._ascom.Quit()
        except com_error:
            self.log.error("Couldn't disconnect to ASCOM.")
            return False
    @com
    def getRa(self):
        return Coord.fromH(self._ascom.RightAscension)

    @com
    def getDec(self):
        return Coord.fromD(self._ascom.Declination)

    @com
    def getAz(self):
        return Coord.fromD(self._ascom.Azimuth)

    @com
    def getAlt(self):
        self._ascom.GetAzAlt()
        return Coord.fromD(self._ascom.Altitude)

    @com
    def getPositionRaDec(self):
        return Position.fromRaDec(
            Coord.fromH(self._ascom.RightAscension), Coord.fromD(self._ascom.Declination))

    @com
    def getPositionAltAz(self):
        return Position.fromAltAz(
            Coord.fromD(self._ascom.Altitude), Coord.fromD(self._ascom.Azimuth))

    @com
    def getTargetRaDec(self):
        if not self._target:
            return self.getPositionRaDec()
        return self._target

    @com
    def slewToRaDec(self, position):

        if self.isSlewing():
            return False

        self._target = position
        self._abort.clear()

        try:
            if self._ascom.CanSlewAsync:

                position_now = self._getFinalPosition(position)

                self.slewBegin(position_now)
                self._ascom.SlewToCoordinatesAsync(position_now.ra.H, position_now.dec.D)

                status = TelescopeStatus.OK

                while not self._ascom.IsSlewComplete:

                    # [ABORT POINT]
                    if self._abort.isSet():
                        status = TelescopeStatus.ABORTED
                        break

                    time.sleep(self._idle_time)

                self.slewComplete(self.getPositionRaDec(), status)

            # except com_error:
            #     raise PositionOutsideLimitsException("Position outside limits.")
        except:
            print 'FIXME:'
            NotImplementedError()

        return True

#    @com
#    def slewToAltAz (self, position):
#
#        if self.isSlewing ():
#            return False
#
# self._target = position
#        self._term.clear ()
#
#        try:
#            self._ascom.Asynchronous = 1
#            self.slewBegin((position.ra, position.dec))
#            self._ascom.SlewToAltAz (position.alt.D, position.az.D, "chimera")
#
#            while not self._ascom.IsSlewComplete:
#
#                if self._term.isSet ():
#                    return True
#
#                time.sleep (self._idle_time)
#
#            self.slewComplete(self.getPositionRaDec())
#
#        except com_error:
#            raise PositionOutsideLimitsException("Position outside limits.")
#
#        return True

    @com
    def abortSlew(self):
        if self.isSlewing():
            self._abort.set()
            time.sleep(self._idle_time)
            self._ascom.AbortSlew()
            return True

        return False

    @com
    def isSlewing(self):
        return self._ascom.Slewing == 0

    @com
    def isTracking(self):
        return self._ascom.Tracking == 1

    @com
    def park(self):
        self._ascom.Park()

    @com
    def unpark(self):
        self._ascom.FindHome()
        self.startTracking()

    @com
    def isParked(self):
        return self._ascom.AtPark

    @com
    def startTracking(self):
        if self._ascom.CanSetTracking:
            self._ascom.Tracking = True

    @com
    def stopTracking(self):
        if self._ascom.CanSetTracking:
            self._ascom.Tracking = False

    # @com
    # def moveEast(self, offset, slewRate=None):
    #     self._ascom.Asynchronous = 0
    #     self._ascom.Jog(offset.AS / 60.0, 'East')
    #     self._ascom.Asynchronous = 1
    #
    # @com
    # def moveWest(self, offset, slewRate=None):
    #     self._ascom.Asynchronous = 0
    #     self._ascom.Jog(offset.AS / 60.0, 'West')
    #     self._ascom.Asynchronous = 1
    #
    # @com
    # def moveNorth(self, offset, slewRate=None):
    #     self._ascom.Asynchronous = 0
    #     self._ascom.Jog(offset.AS / 60.0, 'North')
    #     self._ascom.Asynchronous = 1
    #
    # @com
    # def moveSouth(self, offset, slewRate=None):
    #     self._ascom.Asynchronous = 0
    #     self._ascom.Jog(offset.AS / 60.0, 'South')
    #     self._ascom.Asynchronous = 1
    #
    # @lock
    # def syncRaDec(self, position):
    #     self._ascom.Sync(position.ra.H, position.dec.D, "chimera")
    #     self.syncComplete(position)
