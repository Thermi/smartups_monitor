#! /bin/env python3

## smartups monitor
# written on the basis of OpenElectron's i2c module
# Rest of the code and all changes are under the GPLv3
# Author Noel Kuntze <noel.kuntze+github@thermi.consulting>

import argparse
import ctypes
import logging
import os
import select
import signal
import smbus
import socket
import sys
import threading
import time
import yaml

class WaiterThread(object):
    def __init__(self, duration, sock):
        self.__duration = duration
        self.__socket = sock

    def run(self):
        while True:
            # thread exits when sendall fails, because the socket was closed by the main thread.
            # That happens when it exits because of the signalhandler. That is fine.
            try:
                self.__socket.sendall(b'a')
                time.sleep(self.__duration)
            except:
                return


class SignalHandler(object):
    def __init__(self, condition, sock):
        self.__condition = condition
        self.__sock = sock
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
    
    def exit_gracefully(self, signum, frame):
        with self.__condition:
            self.__sock.sendall(b'a')
            self.__condition.notify_all()

class OpenElectrons_i2c_fixed(object):
    def __init__(self, i2c_address, bus = 0):
        self.address = i2c_address
        self.bus = smbus.SMBus(bus)

    ## Write a byte to your i2c device at a given location
    #  @param self The object pointer.
    #  @param reg the register to write value at.
    #  @param value value to write.
    def writeByte(self, reg, value):
        self.bus.write_byte_data(self.address, reg, value)

    def readByte(self, reg):
        result = self.bus.read_byte_data(self.address, reg)
        return (result)
     
    # for read_i2c_block_data and write_i2c_block_data to work correctly,
    # ensure that i2c speed is set correctly on your pi:
    # ensure following file with contents as follows:
    #    /etc/modprobe.d/i2c.conf
    # options i2c_bcm2708 baudrate=50000
    # (without the first # and space on line above)
    #
    def readArray(self, reg, length):
        results = self.bus.read_i2c_block_data(self.address, reg, length)
        return results

    def writeArray(self, reg, arr):
        self.bus.write_i2c_block_data(self.address, reg, arr)

    def writeArray_byte_at_a_time(self, reg, arr):
        x=0
        for y in arr:
            self.writeByte(reg+x, y)
            x+=1
        return

    def readString(self, reg, length):
        ss = ''
        for x in range(0, length):
            ss = ''.join([ss, chr(self.readByte(reg+x))])
        return ss

    def readArray_byte_at_a_time(self, reg, length):
        ss = []
        for x in range(0, length):
            w=self.readByte(reg+x)
            ss.append(w)
        return ss

    def readInteger(self, reg):
        b0 = self.readByte(reg)
        b1 = self.readByte(reg+1)
        r = b0 + (b1<<8)
        return r

    def readIntegerSigned(self, reg):
        a = self.readInteger(reg)
        signed_a = ctypes.c_int(a).value
        return signed_a

    def readLong(self, reg):
        b0 = self.readByte(reg)
        b1 = self.readByte(reg+1)
        b2 = self.readByte(reg+2)
        b3 = self.readByte(reg+3)
        r = b0 + (b1<<8) + (b2<<16) + (b3<<24)
        return r

    def readLongSigned(self, reg):
        a = self.readLong(reg)
        signed_a = ctypes.c_long(a).value
        return signed_a

    ##  Read the firmware version of the i2c device
    def GetFirmwareVersion(self):
        ver = self.readString(0x00, 8)
        return ver

    ##  Read the vendor name of the i2c device
    def GetVendorName(self):
        vendor = self.readString(0x08, 8)
        return vendor

    ##  Read the i2c device id
    def GetDeviceId(self):
        device = self.readString(0x10, 8)
        return device

## SmartUPS: this class provides functions for SmartUPS
#  for read and write operations.
class SmartUPS(OpenElectrons_i2c_fixed):
    #"""Class for the SmartUPS"""

    # Minimal constants required by library
    
    I2C_ADDRESS = (0x24)
    
    SmartUPS_WHO_AM_I    =  0x10
    SmartUPS_VERSION    =  0x00
    SmartUPS_VENDOR    =  0x08
    
    SmartUPS_COMMAND  = 0x41
    SmartUPS_RESTART_OPTION  =  0x42
    SmartUPS_BUTTON_CLICK   =  0x43
    SmartUPS_RESTART_TIME   =  0x44
    SmartUPS_STATE   =  0x46
    SmartUPS_BAT_CURRENT   =  0x48
    SmartUPS_BAT_VOLTAGE   =  0x4a
    SmartUPS_BAT_CAPACITY   =  0x4c
    SmartUPS_TIME   =  0x4e
    SmartUPS_BAT_TEMPERATURE   =  0x50
    SmartUPS_BAT_HEALTH   =  0x51
    SmartUPS_OUT_VOLTAGE   =  0x52
    SmartUPS_OUT_CURRENT   =  0x54
    SmartUPS_MAX_CAPACITY   =  0x56
    SmartUPS_SECONDS   = 0x58 
    
    ## Initialize the class with the i2c address of the SmartUPS
    #  @param self The object pointer.
    #  @param i2c_address Address of your SmartUPS.
    def __init__(self, address = I2C_ADDRESS, bus = 1):
        OpenElectrons_i2c_fixed.__init__(self, address, bus)  
    
    ## Reads the SmartUPS battery voltage values
    #  @param self The object pointer.
    def readBattVoltage(self):
        try:
            value = self.readInteger(self.SmartUPS_BAT_VOLTAGE)
            return value   
        except:
            logging.error("Could not read battery voltage")
            return ""
        
    ## Reads the SmartUPS battery current values
    #  @param self The object pointer.
    def readBattCurrent(self):
        try:
            value = self.readIntegerSigned(self.SmartUPS_BAT_CURRENT)
            return value
        except:
            logging.error("Could not read battery current")
            return ""
    
    ## Reads the SmartUPS battery temperature values in Celsius.
    ## The temperature is an integer like 41.
    #  @param self The object pointer.
    def readBattTemperature(self):
        try:
            value = self.readByte(self.SmartUPS_BAT_TEMPERATURE)
            return value
        except:
            logging.error("Could not read battery temperature")
            return ""
    
    ## Reads the SmartUPS battery capacity values
    #  @param self The object pointer.
    def readBattCapacity(self):
        try:
            value = self.readInteger(self.SmartUPS_BAT_CAPACITY)
            return value
        except:
            logging.error("Could not read battery capacity")
            return ""        
    
    ## Reads the SmartUPS battery estimated time values
    #  @param self The object pointer.
    def readBattEstimatedTime(self):
        try:
            value = self.readInteger(self.SmartUPS_TIME)
            return value
        except:
            logging.error("Could not read battery estimated time")
            return 0
        
    ## Reads the SmartUPS battery health values
    #  @param self The object pointer.
    def readBattHealth(self):
        try:
            value = self.readByte(self.SmartUPS_BAT_HEALTH)
            return value
        except:
            logging.error("Could not read battery health")
            return 0
    
    ## Reads the SmartUPS battery state
    #  @param self The object pointer.
    def readBattState(self):
        try:
            state = ["IDLE", "PRECHARG", "CHARGING", "TOPUP", "CHARGED", "DISCHARGING", "CRITICAL", "DISCHARGED", "FAULT", "SHUTDOWN"]
            value = self.readByte(self.SmartUPS_STATE)
            return state[value]
        except:
            logging.error("Could not read battery state")
            return "FAULT"
        
    ## Reads the SmartUPS button click status values
    ## 1 is a short button click, 10 is a long one
    #  @param self The object pointer.
    def readButtonClick(self):
        try:
            value = self.readByte(self.SmartUPS_BUTTON_CLICK)
            if value != 0:
                return str(value)
            else:
                return ""
        except:
            logging.error("Could not read button click")
            return ""
            
    ## Reads the SmartUPS output voltage values
    #  @param self The object pointer.
    def readOutputVoltage(self):
        try: 
            value = self.readInteger(self.SmartUPS_OUT_VOLTAGE)
            return value
        except:
            logging.error("Could not read output voltage")
            return 0        
        
    ## Reads the SmartUPS output current values
    #  @param self The object pointer.
    def readOutputCurrent(self):
        try:
            value = self.readIntegerSigned(self.SmartUPS_OUT_CURRENT)
            return value
        except:
            logging.error("Could not read output current")
            return 0        
    
    ## Reads the SmartUPS battery maximum capacity values
    #  @param self The object pointer.
    def readMaxCapacity(self):
        try:
            value = self.readInteger(self.SmartUPS_MAX_CAPACITY)
            return value 
        except:
            logging.error("Could not read maximum capacity")
            return 0        

    ## Reads the SmartUPS time in seconds
    #  @param self The object pointer.
    def readSeconds(self):
        try:
            value = self.readLong(self.SmartUPS_SECONDS)
            return value
        except:
            logging.error("Could not read seconds")
            return 0

    ## Reads the SmartUPS charged values
    #  @param self The object pointer.
    def readCharge(self):
        try: 
            value = self.readInteger(self.SmartUPS_BAT_CAPACITY)*100/(1+self.readInteger(self.SmartUPS_MAX_CAPACITY))
            return value
        except:
            logging.error("Could not read battery charged value")
            return 0

    ## Read the version of the PSU
    # @param self The object pointer.
    def readVersion(self):
        try:
            value = self.GetFirmwareVersion()
            return value
        except:
            print("Error: Could not read version")
            return ""
        
    ## Read the vendor of the UPS. It is likely "Opnelctn"
    # @param self The object pointer.
    def readVendor(self):
        try:
            value = self.GetVendorName()
            return value
        except:
            print("Error: Could not read vendor")
            return ""

    ## Read the Device ID of the UPS. It is likely "SmartUPS".
    # @param self The object pointer.
    def readDeviceId(self):
        try:
            value = self.GetDeviceId()
            return value
        except:
            print("Error: Could not read device ID")
            return ""

    ## Set the command to execute
    # @param self The object pointer.
    # @param command The hex of the command. Can only be "0x53" for "Shutdown in 50 seconds" right now
    def writeCommand(self, command):
        try:
            self.writeByte(self.SmartUPS_COMMAND, command)
        except:
            print("Error: Could not write command")

    ## Write the restart option
    # @param self The object pointer.
    # @param option The option to write
    def writeRestartOption(self, option):
        try:
            self.writeByte(self.SmartUPS_RESTART_OPTION, option)
        except:
            print("Error: Could not write restart option")

    ## Read the restart time (time until the UPS shuts down)
    # @param self The object pointer.
    def readRestartTime(self):
        try:
            value = self.readByte(self.SmartUPS_RESTART_TIME)
            return value
        except:
            print("Error: Could not read button status")
            return ""

## SmartUpsMonitor implements a monitor class for FreeElectron's smart UPS
class SmartUpsMonitor():
    def __init__(self):
        self.__sleep = 5
        self.__bus = 0
        self.__address = 0x12
        self.__debug = False
        self.__verbose = False
        self.__test = False
        self.__config = "/etc/upsmon.yml"
        self.__ups = None
        self.__inhibited = False
        # broken in the FW
        self.__batteryThreshold = 0
        self.__battery_temperatureThreshold = 60
        self.__input_voltage_threshold = 4.0
        self.__restartOption = 1
        self.__parse_config()

    def __parse_config(self):
        config_file = None
        try:
            with open(self.__config, "r") as f:
                config_file = yaml.safe_load(f)
        except FileNotFoundError as exception:
            logging.warning("No config file found at %s. Continuing without reading configuration.", self.__config)
            return True
        except Exception as exception:
            logging.critical("Exception occured while trying to read config: %s", Exception)
            return False

        occured = {}
        exit_with_error = False
        for key, value in config_file.values():
            if key not in occured:
                occured[key] = None
            else:
                logging.error("Duplicate key %s in config file!", key)
                exit_with_error = True
            if key == "sleep":
                self.sleep = value            
            elif key in ["bus", "address", "debug", "verbose", "test",
                "batteryThreshold", "battery_temperatureThreshold", "input_voltageThreshold", "restartOption"]:
                self.__dict__["__%s" % key] = value
            else:
                logging.error("Unknown key %s found", key)
                exit_with_error = True
        if exit_with_error:
            sys.exit(1)

        return True

    ## Parse arguments and apply them, if they were passed (don't apply any of the defaults)
    # @param self Pointer to object.
    def parse_args(self):
        parser = argparse.ArgumentParser(description="Monitor for SmartUPS from OpenElectrons")
        parser.add_argument("-c", "--config",
            help="Sets the path to the config. Defaults to /etc/upsmon.yml.",
            default="/etc/upsmon.yml")

        parser.add_argument("-v", "--verbose",
            help="Enable verbose mode, prints out INFO level messages.",
            action="store_true",
            default=False)

        parser.add_argument("--debug",
            help="Enable debug mode. Overwrites verbose mode. Prints out DEBUG level messages.",
            action="store_true",
            default=False)

        parser.add_argument("--test",
            help="Enable test mode. Disables upsmon from taking any action except monitoring the UPS",
            action="store_true",
            default=False)

        parser.add_argument("--bus",
            help="The bus number that the device is on. Defaults to 0 (/dev/i2c-0)",
            default=0,
            type=int)

        parser.add_argument("--address",
            help="The address of the UPS. Defaults to 0x12",
            default=0x12,
            type=int)

        args = parser.parse_args()

        if "-c" or "--config" in sys.argv:
            self.__config = args.config
        if "-v" or "--verbose" in sys.argv:
            self.__verbose = args.verbose
        if "--debug" in sys.argv:
            self.__debug = args.debug
        if "--test" in sys.argv:
            self.__test = args.test
        if "--bus" in sys.argv:
            self.__bus = args.bus
        if "--address" in sys.argv:
            self.__address = args.address

        print(args)

    def __check_ups(self):
        ups = self.__ups
        # check the estimated runtime. If it's below one minute, log a warning
        batt_run_time = ups.readBattEstimatedTime()
        if time < 60:
            logging.warning("Estimated battery runtime %s is below 60 seconds!", batt_run_time)
        else:
            logging.info("Runtime is %s", batt_run_time)
        
        # read the battery voltage
        battery_voltage = float(ups.readOutputVoltage())
        if battery_voltage < self.__batteryThreshold:
            logging.warning("Battery voltage %s is below threshold %s", battery_voltage/1000, self.__batteryThreshold)
        else:
            logging.info("Battery voltage is %s V", battery_voltage/1000)

        # read the battery temperature
        battery_temperature = ups.readBattTemperature()
        if battery_temperature > self.__battery_temperatureThreshold:
            logging.warning("Battery (%s) is over the temperature threshold (%s)!", battery_temperature, self.__battery_temperatureThreshold)
        else:
            logging.info("Battery temperature is %s", battery_temperature)

        # read the input voltage
        input_voltage = float(ups.readBattVoltage())
        if input_voltage/1000 < self.__input_voltage_threshold:
            logging.warning("Input voltage %s V is below threshold %s", input_voltage/1000, self.__input_voltage_threshold)
        else:
            logging.info("Input voltage is %s V", input_voltage/1000)

        # check the charge as percentage. If the PSU is draining and below 25% or the runtime is below a minue,
        # issue a warning.
        battery_state = ups.readBattState()
        battery_charge = ups.readCharge()
        if battery_state in [ "DISCHARGING","CRITICAL","DISCHARGED","FAULT" ] and battery_charge < 0.25:
            logging.error("Battery is %s and below 25%% charge at %s.", battery_state, battery_charge)
            self.__shut_down()
        else:
            logging.info("Battery state is %s and charge is at %s", battery_state, battery_charge)

        # Then if the estimated runtime is below a minute, issue an error and shut down. Tell it to start the system again
        # when the PSU has power again
        battery_estimated_runtime = ups.readBattEstimatedTime()
        if battery_estimated_runtime < 60:
            logging.error("battery runtime %s is below a minute", battery_estimated_runtime)
            self.__shut_down()
        else:
            logging.info("Battery runtime is at %s", battery_estimated_runtime)

        restartTime = ups.readRestartTime()
        if restartTime > 0 and not self.__inhibited:
            logging.critical("UPS indicated restart time %s. Shutting down.", restartTime)
            self.__shut_down()
    ## Shut down the system
    # @param self The object pointer.
    def __shut_down(self, ups=False):
        # issue shut down
        logging.critical("Received shutdown signal")
        if not self.__inhibited and not self.__test:
            if ups:
                self.__ups.writeCommand(0x53)
            self.__inhibited = True
            # issue shutdown command
            os.system("shutdown now")


    def __main(self):
        try:
            self.__ups = SmartUPS(self.__address, self.__bus)
        except Exception as exception:
            logging.error("Failed to create I2C object to monitor PSU: %s", exception)
            sys.exit(1)
        # write the restart option
        self.__ups.writeRestartOption(self.__restartOption)

        condition = threading.Condition()
        handler_sock, remote_sock = socket.socketpair(type=socket.SOCK_DGRAM)

        handler = SignalHandler(condition, handler_sock)
        handler_fd = handler_sock.fileno()

        waiter_sock, remote_sock = socket.socketpair(type=socket.SOCK_DGRAM)  
        waiter_fd = waiter_sock.fileno()
        waiter = WaiterThread(self.__sleep, remote_sock)
        waiter_thread = threading.Thread(target=waiter.run)
        waiter_thread.start()
        polling_object = select.poll()
        polling_object.register(waiter_sock, select.POLLIN)
        polling_object.register(handler_sock, select.POLLIN)

        while True:
            fds_and_flags = polling_object.poll()
            for fd, flag_set in fds_and_flags:
                if fd == handler_fd:
                    logging.warning("Received shutdown signal. Shutting down.")
                    handler_sock.recvmsg()
                    with condition:
                        condition.notify_all()
                    break
                    break
                elif fd == waiter_fd:
                    logging.debug("Received wake up signal from waiter thread")
                    self.__check_ups()
                    waiter_sock.recvmsg()
                else:
                    logging.error("Received socket from unknown fd %s", fd)

    def __loggingConfig(self):
        level = None
        if self.__debug:
            level = logging.DEBUG
        elif self.__verbose:
            level = logging.INFO

        logging.basicConfig(level=level,
                            datefmt="%H:%M:%S",
                            stream=sys.stdout)

    def run(self):
        self.__loggingConfig()
        self.parse_args()
        self.__main()

if __name__ == '__main__':
    monitor = SmartUpsMonitor()
    monitor.run()