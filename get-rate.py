#!/usr/bin/python3

import pydbus
import time
import logging
from logging import warning, info, debug
from gi.repository import GLib

class DeviceNotFound (Exception): pass
class DeviceConnexionError (Exception): pass

# Setup of device specific values
#DEVICE_ADDR= 'DF:72:CE:8D:FC:CC'
HRM_service_uuid = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_characteristic_uuid = "00002a37-0000-1000-8000-00805f9b34fb"

# DBus object paths
BLUEZ_SERVICE = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'
#DEVICE_PATH = f"{ADAPTER_PATH}/dev_{DEVICE_ADDR.replace(':', '_')}"

def as_uint( bytelist ):
    val=0
    for i in range( len(bytelist) ):
        val += bytelist[i] * pow( 256 , i )
    return val

def generic_signal_handler(*args, **kwargs):
    for i, arg in enumerate(args):
        debug("arg:%d        %s" % (i, str(arg)))
    debug('kwargs:')
    debug(kwargs)
    debug('---end----')

class HR_measurement():
    """ decode a 0x2a37 heart rate measurement frame
    https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/"""
    def __init__( self, data ):
        # extract flags field
        flags = data[0]
        data = data [1:]

        # is hr expressed as UINT8 or UINT16 ?
        if (flags & 0x01): 
            self.HR = as_uint( data[0:2] )
            data=data[2:]
        else:
            self.HR = as_uint( data[0:1] )
            data=data[1:]
        
        # calories
        if( flags & 0x08 ):
            self.EE = as_uint( data[0:2] )
            data=data[2:]
        else:
            self.EE = None

        # RR-interval (peak-to-peak time)
        self.RR = []
        while( len(data) ):
            rr = 60 * 1024 / as_uint( data[0:2] )
            data=data[2:]
            self.RR.append( rr ) 

    def __repr__(self):
        ret = [ "%d bpm" % self.HR ]
        if( self.EE ):
            ret.append( "%d Joules" % self.EE )
        ret.append ( "RR %s" % str(self.RR) )
        return " / ".join(ret)

class HeartRateLoop():
    def __init__(self ):
        # setup dbus
        self.bus     = pydbus.SystemBus()
        self.mngr    = self.bus.get( BLUEZ_SERVICE, '/')
        self.adapter = self.bus.get( BLUEZ_SERVICE, ADAPTER_PATH ) 


    def get_device( self, uuid, retry, discovery_delay ):
        """ Get HR sensor device as a dbus proxy object 
        retry = -1 for infinite discovery"""

        try:
            path = self.get_device_path( uuid )
            if( path ):
                dev = self.bus.get( BLUEZ_SERVICE, path )
            else:
                dev = None
        except (AttributeError, KeyError) :
            if (retry == 0 ):
                raise DeviceNotFound( "No device found with service UUID %s " % uuid )

        if( dev ):
            info("Device found : %s" % path)
            self.device_path = path
            return dev 
        else :
            debug( "Starting bluetooth discovery for %d seconds" % discovery_delay )
            self.adapter.StartDiscovery()
            time.sleep(discovery_delay)
            self.adapter.StopDiscovery()
            debug( "Stopped discovery")
            return self.get_device( uuid, max( -1, retry-1) , discovery_delay )

    def connect_device( self, retry ):
        while( not self.device.Connected ):
            try:
                retry -= 1
                self.device.Connect()
                debug( "Connected to %s" % self.device.Name)
            except Exception as e:
                debug( str(e) )
                if( retry > 0):
                    # disconnect/reconnect sometimes necessary
                    self.device.Disconnect()
                    debug("Retry...")
                else :
                    raise DeviceConnexionError( "Erreur de connexion à %s" % self.device.Name)

    def get_device_path( self, uuid ):
        """Look up DBus path for device with UUID in its announced services"""
        objs = self.mngr.GetManagedObjects()
        for path in objs:
            srv_uuids = objs[path].get('org.bluez.Device1', {}).get('UUIDs')
            if( srv_uuids and uuid.casefold() in srv_uuids ):
                return path


    def get_characteristic_path( self, uuid ):
        """Look up DBus path for characteristic UUID"""
        objs = self.mngr.GetManagedObjects()
        for path in objs:
            chr_uuid = objs[path].get('org.bluez.GattCharacteristic1', {}).get('UUID')
            if path.startswith(self.device_path) and chr_uuid == uuid.casefold():
                return path

    @classmethod
    def notification_handler( cls, interface_name, changed_props, invalidated_props) :
        if( not interface_name == "org.bluez.GattCharacteristic1" ):
            warn( "Unexpected signal from %s interface" % interface_name)
        try:
            data = changed_props['Value']
            hrm = HR_measurement(data)
            print( hrm )
        except KeyError:
            debug ("Ignored signal without 'Value' property")


    def start( self ):
        self.device = self.get_device( uuid = HRM_service_uuid, retry = 2, discovery_delay = 5 )         
        self.connect_device(retry=2)

        # TODO : handle connection failure
        # TODO : add a timeout on ServicesResolved
        while not self.device.ServicesResolved and self.device.Connected :
            time.sleep(0.5)

        hrm_path = self.get_characteristic_path( uuid=HRM_characteristic_uuid)
        # TODO : handle when hrm characteristic is not found

        hrm = self.bus.get( BLUEZ_SERVICE, hrm_path )
        hrm.StartNotify()
        with hrm.PropertiesChanged.connect( self.notification_handler ):
            loop = GLib.MainLoop()
            try :
                loop.run()
            except KeyboardInterrupt:
                loop.quit()
                hrm.StopNotify()
                self.device.Disconnect()

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)
l=HeartRateLoop()
l.start()
