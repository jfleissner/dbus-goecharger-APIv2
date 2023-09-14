#!/usr/bin/env python
 
# import normal packages
import platform 
import logging
import sys
import os
import sys
if sys.version_info.major == 2.1:
    import gobject
else:
    from gi.repository import GLib as gobject
import sys
import time
import requests # for http GET
import configparser # for config/ini file
 
# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

globalConfig = 0
 

class DbusGoeChargerService:
  def __init__(self, servicename, paths, productname='go-eCharger', connection='go-eCharger HTTP JSON service'):
    print("_init_")
    config = self._getConfig()
    deviceinstance = int(config['DEFAULT']['Deviceinstance'])
    hardwareVersion = int(config['DEFAULT']['HardwareVersion'])

    self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
    self._paths = paths
    
    logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))
    
    paths_wo_unit = [
      '/Status',  # value 'car_state' 1: Ladestation bereit - kein Fahrzeug 2: Fahrzeug lädt 3: Warten aufs Fahrzeug 4: Laden beendet - Fahrzeug noch verbunden
      '/EnableDisplay',
      '/Autostart',
    ]
    #time.sleep(1)
    #print("sleep")

    #get data from go-eCharger
    data = self._getGoeChargerData()
    time.sleep(1)
    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', connection)
    
    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', deviceinstance)
    self._dbusservice.add_path('/ProductId', 0xFFFF) # 
    #self._dbusservice.add_path('/ProductName', productname)
    self._dbusservice.add_path('/ProductName', data['typ'])
    self._dbusservice.add_path('/CustomName', productname)    
    self._dbusservice.add_path('/FirmwareVersion', int(data['fwv'].replace('.', '')))
    self._dbusservice.add_path('/HardwareVersion', hardwareVersion)
    self._dbusservice.add_path('/Serial', data['sse'])
    self._dbusservice.add_path('/Connected', 1)
    self._dbusservice.add_path('/UpdateIndex', 0)
    self._dbusservice.add_path('/Position',  int(config['DEFAULT']['Position']))
    #self._dbusservice.add_path('/EnableDisplay', 0)
    #self._dbusservice.add_path('/AutoStart', 1)

    # add paths without units
    for path in paths_wo_unit:
      self._dbusservice.add_path(path, None)
    
    # add path values to dbus
    for path, settings in self._paths.items():
      self._dbusservice.add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

    # last update
    self._lastUpdate = 0
    
    # charging time in float
    self._chargingTime = 0.0

    # add _update function 'timer'
    gobject.timeout_add(2500, self._update) # pause 2500ms before the next request
    
    # add _signOfLife 'timer' to get feedback in log every 5minutes
    gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)
    
  def _getConfig(self):
    global globalConfig     
    if globalConfig == 0:
        config = configparser.ConfigParser()
        print("configparser.ConfigParser ausgeführt")
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        print("config.read ausgeführt")
        globalConfig = config
    
    return globalConfig
 
 
  def _getSignOfLifeInterval(self):
    config = self._getConfig()
    value = config['DEFAULT']['SignOfLifeLog']
   
    if not value: 
        value = 0
    
    return int(value)

  def _getGoeChargerStatusUrl(self):
    config = self._getConfig()
    accessType = config['DEFAULT']['AccessType']
    
    if accessType == 'OnPremise': 
        URL = "http://%s/api/status" % (config['ONPREMISE']['Host'])
    else:
        raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))
    
    return URL
  
#Set-Funktion für API v2 *****
  def _setGoeChargerValue(self, parameter, value):
    print("setGoeChargerValue")
    config = self._getConfig()
    accessType = config['DEFAULT']['AccessType']
    print("Funktion aufgerufen")
    print(parameter, str(value))
    print(config['ONPREMISE']['Host'])
    URL = "http://%s/api/set?%s=%s" % (config['ONPREMISE']['Host'], parameter, str(value))    
    print(URL)
    request_data = requests.get(url = URL)

    # check for response
    if not request_data:
      raise ConnectionError("No response from go-eCharger - %s" % (URL))
    
    json_data = request_data.json()
    
    # check for Json
    if not json_data:
        raise ValueError("Converting response to JSON failed")
    
    if json_data[parameter] == str(value):
      return True
    else:
      logging.warning("go-eCharger parameter %s not set to %s" % (parameter, str(value)))
      return False
    
 
  def _getGoeChargerData(self):
    print("getGoeChargerData")
    URL = self._getGoeChargerStatusUrl()
    request_data = requests.get(url = URL)
    
    # check for response
    if not request_data:
        raise ConnectionError("No response from go-eCharger - %s" % (URL))
    
    json_data = request_data.json()     
    #time.sleep(1)
    print("sleeping is pointless")
    # check for Json
    if not json_data:
        raise ValueError("Converting response to JSON failed")
    
    
    return json_data
 
 
  def _signOfLife(self):
    logging.info("--- Start: sign of life ---")
    logging.info("Last _update() call: %s" % (self._lastUpdate))
    logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
    logging.info("--- End: sign of life ---")
    return True
 
  def _update(self):
    print("update")   
    try:
       #get data from go-eCharger
       data = self._getGoeChargerData()
       print("update got charger data")   
       
       #send data to DBus
       self._dbusservice['/Ac/L1/Power'] = int(data['nrg'][7] * 0.01 * 100)
       self._dbusservice['/Ac/L2/Power'] = int(data['nrg'][8] * 0.01 * 100)
       self._dbusservice['/Ac/L3/Power'] = int(data['nrg'][9] * 0.01 * 100)
       self._dbusservice['/Ac/Power'] = int(data['nrg'][11] * 0.01 * 100)
       self._dbusservice['/Ac/Voltage'] = int(data['nrg'][0])
       self._dbusservice['/Current'] = max(data['nrg'][4] * 1, data['nrg'][5] * 1, data['nrg'][6] * 1)
       self._dbusservice['/Ac/Energy/Forward'] = int(float(data['eto']) / 1000.0)
       self._dbusservice['/StartStop'] = int(data['alw'])
       self._dbusservice['/SetCurrent'] = int(data['amp'])
       self._dbusservice['/MaxCurrent'] = int(data['ama'])
       print("updated dbus")   
 
       # update chargingTime, increment charge time only on active charging (2), reset when no car connected (1)
       timeDelta = time.time() - self._lastUpdate
       if int(data['car']) == 2 and self._lastUpdate > 0:  # vehicle loads
         self._chargingTime += timeDelta
       elif int(data['car']) == 1:  # charging station ready, no vehicle
         self._chargingTime = 0
       self._dbusservice['/ChargingTime'] = int(self._chargingTime)

       self._dbusservice['/Mode'] = int(lademodus_to_victron(data['lmo']))  # 0=Manual, no control 1=Automatic

       print("updated dbus2")   
       config = self._getConfig()
       hardwareVersion = int(config['DEFAULT']['HardwareVersion'])

       # value 'car' 1: charging station ready, no vehicle 2: vehicle loads 3: Waiting for vehicle 4: Charge finished, vehicle still connected
       status = 0
       if int(data['car']) == 1:
         status = 0
       elif int(data['car']) == 2:
         status = 2
       elif int(data['car']) == 3:
         status = 6
       elif int(data['car']) == 4:
         status = 3
       self._dbusservice['/Status'] = status
       print("updated dbus3")

       #logging
       logging.debug("Wallbox Consumption (/Ac/Power): %s" % (self._dbusservice['/Ac/Power']))
       logging.debug("Wallbox Forward (/Ac/Energy/Forward): %s" % (self._dbusservice['/Ac/Energy/Forward']))
       logging.debug("---")
       print("update logged")
       
       # increment UpdateIndex - to show that new data is available
       index = self._dbusservice['/UpdateIndex'] + 1  # increment index
       if index > 255:   # maximum value of the index
         index = 0       # overflow from 255 to 0
       self._dbusservice['/UpdateIndex'] = index
       print("updated updateIndex")

       #update lastupdate vars
       self._lastUpdate = time.time()
    except Exception as e:
       print("Update exception '%s'" % (e))
       logging.critical('Error at %s', '_update', exc_info=e)
       
    # return true, otherwise add_timeout will be removed from GObject - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
    return True
 
  def _handlechangedvalue(self, path, value):
    logging.info("someone else updated %s to %s" % (path, value))
    print("handlechangedvalue")
    if path == '/SetCurrent':
      return self._setGoeChargerValue('amp', value)
    elif path == '/StartStop':
      return self._setGoeChargerValue('frc', forcestate_to_goe(value))
    elif path == '/MaxCurrent':
      return self._setGoeChargerValue('ama', value)
    elif path == '/Mode':
      print("/Mode")
      return self._setGoeChargerValue('lmo', lademodus_to_goe(value))
    else:
      print("mapping for evcharger path %s does not exist" % (path))
      logging.info("mapping for evcharger path %s does not exist" % (path))
      return False

#Funktionen zur Übersetzung der Werte zwischen Virctron und GoE*****
def lademodus_to_victron(lmo_wert):
    if lmo_wert == 4:
        return 1
    else:
        return 0

def lademodus_to_goe(goe_wert):
    if goe_wert == 1:
        return 4
    else:
        return 3

def forcestate_to_goe(goe_wert):
    if goe_wert == 0:
        return 1
    else:
        return 2


def main():
  #configure logging
  print("main")
  logging.basicConfig(      format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging.INFO,
                            handlers=[
                                logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                                logging.StreamHandler()
                            ])
  try:
      logging.info("Start")
  
      from dbus.mainloop.glib import DBusGMainLoop
      # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
      DBusGMainLoop(set_as_default=True)
     
      #formatting 
      _kwh = lambda p, v: (str(round(v, 2)) + 'kWh')
      _a = lambda p, v: (str(round(v, 1)) + 'A')
      _w = lambda p, v: (str(round(v, 1)) + 'W')
      _v = lambda p, v: (str(round(v, 1)) + 'V')
      _degC = lambda p, v: (str(v) + '°C')
      _s = lambda p, v: (str(v) + 's')
     
      #start our main-service
      pvac_output = DbusGoeChargerService(
        servicename='com.victronenergy.evcharger',
        paths={
          '/Ac/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L1/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L2/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L3/Power': {'initial': 0, 'textformat': _w},
          '/Ac/Energy/Forward': {'initial': 0, 'textformat': _kwh},
          '/ChargingTime': {'initial': 0, 'textformat': _s},
          
          '/Ac/Voltage': {'initial': 0, 'textformat': _v},
          '/Current': {'initial': 0, 'textformat': _a},
          '/SetCurrent': {'initial': 0, 'textformat': _a},
          '/MaxCurrent': {'initial': 0, 'textformat': _a},
          '/StartStop': {'initial': 0, 'textformat': lambda p, v: (str(v))},
          '/Mode': {'initial': 0, 'textformat': lambda p, v: (str(v))},
          #'/AutoStart': {'initial': 0, 'textformat': lambda p, v: (str(v))},
          #'/EnableDisplay': {'initial': 0, 'textformat': lambda p, v: (str(v))},
	}
        )
     
      logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
      mainloop = gobject.MainLoop()
      mainloop.run()
  except Exception as e:
    logging.critical('Error at %s', 'main', exc_info=e)
if __name__ == "__main__":
 
   main()
