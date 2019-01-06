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
import socket
import sys
import threading
import time

import yaml

import smbus

##  Implements the thread that wakes up the main thread every duration seconds.
class WaiterThread():
    def __init__(self, duration, event, sock):
        self.__duration = duration
        self.__socket = sock
        self.__event = event

    ## Send data over the socket every self.__duration seconds
    # @param self Pointer to object.
    def run(self):
        while True:
            # thread exits when sendall fails, because the socket was closed by the main thread.
            # That happens when it exits because of the signalhandler. That is fine.
            logging.debug("Start of a loop in the waiter thread.")
            logging.debug("duration: %s", self.__duration)
            try:
                self.__socket.sendall(b'a')
                self.__event.wait(self.__duration)
                if self.__event.is_set():
                    logging.debug("Waiter thread was told to exit.")
                    return
            except Exception as e:
                logging.debug("Encountered an exception: %s", e)
                return
            logging.debug("End of a loop in the waiter thread.")
        logging.debug("Reached end WaiterThread.run().")

## Implements the signal handler for SIGINT and SIGTERM.
class SignalHandler():
    ## Initialize the signal handler
    # @param self Pointer to object.
    # @param event An object of type threading.Event that is notified when a signal is received
    # @param sock An object of type socket over which data is sent when a signal is received
    def __init__(self, event, sock):
        self.__event = event
        self.__sock = sock
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
    
    ## The signal handler method. It sends data over the socket when a signal is received.
    # @param self Pointer to Object.
    # @param signum The signal number.
    # @param frame The stack frame.
    def exit_gracefully(self, signum, frame):
        self.__sock.sendall(b'a')
        self.__event.set()

## Implements the methods to communicate over I2C to a specific address over a specific bus.
class OpenElectronsI2cFixed():
    ## Initialize the object
    ## @param self Pointer to object.
    # @param i2c_address The address of the I2C device.
    # @param bus The number of the bus over which the I2C device can be reached.
    def __init__(self, i2c_address, bus=0):
        self.address = i2c_address
        self.bus = smbus.SMBus(bus)

    ## Write a byte to your I2C device at a given location
    #  @param self The object pointer.
    #  @param reg the register to write value at.
    #  @param value value to write.
    def write_byte(self, reg, value):
        self.bus.write_byte_data(self.address, reg, value)

    ## Read byte from the register of the I2C device
    # @param self The object pointer.
    # @param reg The register to read from.
    def read_byte(self, reg):
        result = self.bus.read_byte_data(self.address, reg)
        return (result)
     
    # for read_i2c_block_data and write_i2c_block_data to work correctly,
    # ensure that I2C speed is set correctly on your pi:
    # ensure following file with contents as follows:
    #    /etc/modprobe.d/i2c.conf
    # options i2c_bcm2708 baudrate=50000
    # (without the first # and space on line above)
    #
    ## Read a variable amount of bytes starting at reg, increasing linearly.
    # @param self Pointer to object.
    # @param reg The register to read from.
    # @param length The length of the array to read from.
    def read_array(self, reg, length):
        results = self.bus.read_i2c_block_data(self.address, reg, length)
        return results

    ## Write the given array to the given register. It uses smbus.write_i2c_block_data.
    # @param reg The register at which to start writing the array to
    # @param arr The array that is to be written
    def write_array(self, reg, arr):
        self.bus.write_i2c_block_data(self.address, reg, arr)

    ## Write the given array to the given register. It uses smbus.write_byte_data
    # to write one byte at a time.
    # @param self Pointer to object.
    # @param reg The register at which to start writing the array to
    # @param arr The array that is to be written
    def write_array_byte_at_a_time(self, reg, arr):
        x = 0
        for y in arr:
            self.write_byte(reg+x, y)
            x+=1
        return
    ## Read a string of the given length starting at the given register, increasing linearly.
    # @param self Pointer to object.
    # @param reg The register at which to start reading from
    # @param length The length of the string to read from the registers.
    def read_string(self, reg, length):
        ss = ''
        for x in range(0, length):
            ss = ''.join([ss, chr(self.read_byte(reg+x))])
        return ss


    def read_array_byte_at_a_time(self, reg, length):
        ss = []
        for x in range(0, length):
            w=self.read_byte(reg+x)
            ss.append(w)
        return ss

    def read_integer(self, reg):
        b0 = self.read_byte(reg)
        b1 = self.read_byte(reg+1)
        r = b0 + (b1<<8)
        return r

    def read_integer_signed(self, reg):
        a = self.read_integer(reg)
        signed_a = ctypes.c_int(a).value
        return signed_a

    def read_long(self, reg):
        b0 = self.read_byte(reg)
        b1 = self.read_byte(reg+1)
        b2 = self.read_byte(reg+2)
        b3 = self.read_byte(reg+3)
        r = b0 + (b1<<8) + (b2<<16) + (b3<<24)
        return r

    def read_long_signed(self, reg):
        a = self.read_long(reg)
        signed_a = ctypes.c_long(a).value
        return signed_a

    ##  Read the firmware version of the i2c device
    def get_firmware_version(self):
        ver = self.read_string(0x00, 8)
        return ver

    ##  Read the vendor name of the i2c device
    def get_vendor_name(self):
        vendor = self.read_string(0x08, 8)
        return vendor

    ##  Read the i2c device id
    def get_device_id(self):
        device = self.read_string(0x10, 8)
        return device

## SmartUPS: this class provides functions for SmartUPS
#  for read and write operations.
class SmartUPS(OpenElectronsI2cFixed):
    #"""Class for the SmartUPS"""

    # Minimal constants required by library

    I2C_ADDRESS = (0x24)

    SMARTUPS_WHO_AM_I = 0x10
    SMARTUPS_VERSION = 0x00
    SMARTUPS_VENDOR = 0x08

    SMARTUPS_COMMAND = 0x41
    SMARTUPS_RESTART_OPTION = 0x42
    SMARTUPS_BUTTON_CLICK = 0x43
    SMARTUPS_RESTART_TIME = 0x44
    SMARTUPS_STATE = 0x46
    SMARTUPS_BAT_CURRENT = 0x48
    SMARTUPS_BAT_VOLTAGE = 0x4a
    SMARTUPS_BAT_CAPACITY = 0x4c
    SMARTUPS_TIME = 0x4e
    SMARTUPS_BAT_TEMPERATURE = 0x50
    SMARTUPS_BAT_HEALTH = 0x51
    SMARTUPS_OUT_VOLTAGE = 0x52
    SMARTUPS_OUT_CURRENT = 0x54
    SMARTUPS_MAX_CAPACITY = 0x56
    SMARTUPS_SECONDS = 0x58

    ## Initialize the class with the i2c address of the SmartUPS
    #  @param self The object pointer.
    #  @param i2c_address Address of your SmartUPS.
    def __init__(self, address=I2C_ADDRESS, bus=1):
        OpenElectronsI2cFixed.__init__(self, address, bus)
        try:
            ret = self.get_device_id()
            if not ret:
                logging.error("Could not connect to UPS!")
        except Exception as e:
            logging.error("Could not connect to UPS!")
            raise e

    ## Reads the SmartUPS battery voltage values
    #  @param self The object pointer.
    def read_batt_voltage(self):
        try:
            value = self.read_integer(self.SMARTUPS_BAT_VOLTAGE)
            return value   
        except:
            logging.error("Could not read battery voltage")
            return ""

    ## Reads the SmartUPS battery current values
    #  @param self The object pointer.
    def read_batt_current(self):
        try:
            value = self.read_integer_signed(self.SMARTUPS_BAT_CURRENT)
            return value
        except:
            logging.error("Could not read battery current")
            return ""

    ## Reads the SmartUPS battery temperature values in Celsius.
    ## The temperature is an integer like 41.
    #  @param self The object pointer.
    def read_batt_temperature(self):
        try:
            value = self.read_byte(self.SMARTUPS_BAT_TEMPERATURE)
            return value
        except:
            logging.error("Could not read battery temperature")
            return ""

    ## Reads the SmartUPS battery capacity values
    #  @param self The object pointer.
    def read_batt_capacity(self):
        try:
            value = self.read_integer(self.SMARTUPS_BAT_CAPACITY)
            return value
        except:
            logging.error("Could not read battery capacity")
            return ""        

    ## Reads the SmartUPS battery estimated time values
    #  @param self The object pointer.
    def read_batt_estimated_time(self):
        try:
            value = self.read_integer(self.SMARTUPS_TIME)
            return value
        except:
            logging.error("Could not read battery estimated time")
            return 0

    ## Reads the SmartUPS battery health values
    #  @param self The object pointer.
    def read_batt_health(self):
        try:
            value = self.read_byte(self.SMARTUPS_BAT_HEALTH)
            return value
        except:
            logging.error("Could not read battery health")
            return 0

    ## Reads the SmartUPS battery state
    #  @param self The object pointer.
    def read_batt_state(self):
        try:
            state = ["IDLE", "PRECHARG", "CHARGING", "TOPUP", "CHARGED", "DISCHARGING",
                     "CRITICAL", "DISCHARGED", "FAULT", "SHUTDOWN"]
            value = self.read_byte(self.SMARTUPS_STATE)
            return state[value]
        except:
            logging.error("Could not read battery state")
            return "FAULT"

    ## Reads the SmartUPS button click status values
    ## 1 is a short button click, 10 is a long one
    #  @param self The object pointer.
    def read_button_click(self):
        try:
            value = self.read_byte(self.SMARTUPS_BUTTON_CLICK)
            return value
        except:
            logging.error("Could not read button click")
            return 0

    ## Reads the SmartUPS output voltage values
    #  @param self The object pointer.
    def read_output_voltage(self):
        try:
            value = self.read_integer(self.SMARTUPS_OUT_VOLTAGE)
            return value
        except:
            logging.error("Could not read output voltage")
            return 0

    ## Reads the SmartUPS output current values
    #  @param self The object pointer.
    def read_output_current(self):
        try:
            value = self.read_integer_signed(self.SMARTUPS_OUT_CURRENT)
            return value
        except:
            logging.error("Could not read output current")
            return 0    

    ## Reads the SmartUPS battery maximum capacity values
    #  @param self The object pointer.
    def read_max_capacity(self):
        try:
            value = self.read_integer(self.SMARTUPS_MAX_CAPACITY)
            return value
        except:
            logging.error("Could not read maximum capacity")
            return 0

    ## Reads the SmartUPS time in seconds
    #  @param self The object pointer.
    def read_seconds(self):
        try:
            value = self.read_long(self.SMARTUPS_SECONDS)
            return value
        except:
            logging.error("Could not read seconds")
            return 0

    ## Reads the SmartUPS charged values
    #  @param self The object pointer.
    def read_charge(self):
        try:
            value = self.read_integer(self.SMARTUPS_BAT_CAPACITY)*100/(1+self.read_integer(self.SMARTUPS_MAX_CAPACITY))
            return value
        except:
            logging.error("Could not read battery charged value")
            return 0

    ## Read the version of the PSU
    # @param self The object pointer.
    def read_version(self):
        try:
            value = self.get_firmware_version()
            return value
        except:
            print("Error: Could not read version")
            return ""
        
    ## Read the vendor of the UPS. It is likely "Opnelctn"
    # @param self The object pointer.
    def read_vendor(self):
        try:
            value = self.get_vendor_name()
            return value
        except:
            print("Error: Could not read vendor")
            return ""

    ## Read the Device ID of the UPS. It is likely "SmartUPS".
    # @param self The object pointer.
    def read_device_id(self):
        try:
            value = self.get_device_id()
            return value
        except:
            print("Error: Could not read device ID")
            return ""

    ## Set the command to execute
    # @param self The object pointer.
    # @param command The hex of the command. Can only be "0x53" for "Shutdown in 50 seconds" right now
    def write_command(self, command):
        try:
            self.write_byte(self.SMARTUPS_COMMAND, command)
        except:
            print("Error: Could not write command")

    ## Write the restart option
    # @param self The object pointer.
    # @param option The option to write
    def write_restart_option(self, option):
        try:
            self.write_byte(self.SMARTUPS_RESTART_OPTION, option)
        except:
            print("Error: Could not write restart option")

    ## Read the restart time (time until the UPS shuts down)
    # @param self The object pointer.
    def read_restart_time(self):
        try:
            value = self.read_byte(self.SMARTUPS_RESTART_TIME)
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
        self.__battery_threshold = 0
        self.__battery_temperature_threshold = 60
        self.__input_voltage_threshold = 3.3
        self.__restart_option = 1
        self.__print_values = False
        self.__parse_config()

    def __parse_config(self):
        config_file = None
        try:
            with open(self.__config, "r") as f:
                config_file = yaml.safe_load(f)
        except FileNotFoundError:
            logging.warning("No config file found at %s. Continuing without reading configuration.", self.__config)
            return True
        except Exception:
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
                "batteryThreshold", "battery_temperatureThreshold", "input_voltageThreshold",
                "restartOption"]:
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
                            help="Enable debug mode. Overwrites verbose mode. "
                            "Prints out DEBUG level messages.",
                            action="store_true",
                            default=False)

        parser.add_argument("--test",
                            help="Enable test mode. Disables upsmon from taking any action "
                            "except monitoring the UPS",
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

        parser.add_argument("--print-values",
                            help="Print out all settings of the UPS",
                            default=False,
                            action="store_true")

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
        if "--print-values" in sys.argv:
            self.__print_values = args.print_values

        level = logging.WARNING
        if self.__debug:
            level = logging.DEBUG
        elif self.__verbose:
            level = logging.INFO

        logging.root.setLevel(level)

    def __print_all_values(self):
        print("battery voltage: %s" % self.__ups.read_batt_voltage())
        print("battery amperage: %s" % self.__ups.read_batt_current())
        print("battery temperature: %s" % self.__ups.read_batt_temperature())
        print("battery capacity: %s" % self.__ups.read_batt_capacity())
        print("battery estimated run time: %s" % self.__ups.read_batt_estimated_time())
        print("battery health: %s" % self.__ups.read_batt_health())
        print("battery state: %s" % self.__ups.read_batt_state())
        print("battery button click: %s" % self.__ups.read_button_click())
        print("battery output voltage: %s" % self.__ups.read_output_voltage())
        print("battery output amperage: %s" % self.__ups.read_output_current())
        print("battery max capacity: %s" % self.__ups.read_max_capacity())
        print("battery seconds: %s" % self.__ups.read_seconds())
        print("battery charge: %s" % self.__ups.read_charge())
        print("battery version: %s" % self.__ups.read_version())
        print("battery vendor: %s" % self.__ups.read_vendor())
        print("battery device id: %s" % self.__ups.read_device_id())
        print("battery command: %s" % self.__ups.read_byte(self.__ups.SMARTUPS_COMMAND))
        print("battery restart option: %s" % self.__ups.read_byte(self.__ups.SMARTUPS_RESTART_OPTION))
        print("battery restart time: %s" % self.__ups.read_byte(self.__ups.SMARTUPS_RESTART_TIME))

    def __check_ups(self):
        ups = self.__ups
        # read the battery voltage
        battery_voltage = float(ups.read_output_voltage())
        if battery_voltage < self.__battery_threshold:
            logging.warning("Battery voltage %s is below threshold %s",
                            battery_voltage/1000, self.__battery_threshold)
        else:
            logging.info("Battery voltage is %s V", battery_voltage/1000)

        # read the battery temperature
        battery_temperature = ups.read_batt_temperature()
        if battery_temperature > self.__battery_temperature_threshold:
            logging.warning("Battery (%s) is over the temperature threshold (%s)!",
                            battery_temperature, self.__battery_temperature_threshold)
        else:
            logging.info("Battery temperature is %s °C", battery_temperature)

        # read the input voltage
        input_voltage = float(ups.read_batt_voltage())
        if input_voltage/1000 < self.__input_voltage_threshold:
            logging.warning("Input voltage %s V is below threshold %s", input_voltage/1000,
                            self.__input_voltage_threshold)
        else:
            logging.info("Input voltage is %s V", input_voltage/1000)

        # check the charge as percentage.
        # If the PSU is draining and below 25% or the runtime is below a minute, # issue a warning.
        battery_state = ups.read_batt_state()
        battery_charge = ups.read_charge()
        if battery_state in ["DISCHARGING", "CRITICAL", "DISCHARGED", "FAULT"] and battery_charge < 0.25:
            logging.error("Battery is %s and below 25%% charge at %s.", battery_state, battery_charge)
            self.__shut_down()
        else:
            logging.info("Battery state is %s and charge is at %s", battery_state, battery_charge)

        # Then if the estimated runtime is below a minute, issue an error and shut down.
        # Tell it to start the system again
        # when the PSU has power again
        battery_estimated_runtime = ups.read_batt_estimated_time()
        if battery_estimated_runtime < 60:
            logging.error("battery runtime %s is below a minute", battery_estimated_runtime)
            self.__shut_down()
        else:
            logging.info("Battery runtime is at %s", battery_estimated_runtime)

        restart_time = ups.read_restart_time()
        if restart_time > 0 and not self.__inhibited:
            logging.critical("UPS indicated restart time %s. Shutting down.", restart_time)
            self.__shut_down()
        logging.debug("End of __check_ups.")

    ## Shut down the system
    # @param self The object pointer.
    # @param ups Whether to shut down the UPS as well.
    def __shut_down(self, ups=False):
        # issue shut down
        logging.critical("Received shutdown signal")
        if not self.__inhibited and not self.__test:
            if ups:
                self.__ups.write_command(0x53)
            self.__inhibited = True
            # issue shutdown command
            os.system("shutdown now")


    def __main(self):
        try:
            self.__ups = SmartUPS(self.__address, self.__bus)
        except Exception as exception:
            logging.error("Failed to create I2C object to monitor PSU: %s", exception)
            sys.exit(1)

        if self.__print_values:
            self.__print_all_values()
        else:
            # write the restart option
            self.__ups.write_restart_option(self.__restart_option)

            event = threading.Event()
            local_signal_handler_sock, remote_signal_hander_sock = socket.socketpair(type=socket.SOCK_DGRAM)

            handler = SignalHandler(event, remote_signal_hander_sock)
            handler_fd = local_signal_handler_sock.fileno()

            local_waiter_sock, remote_waiter_sock = socket.socketpair(type=socket.SOCK_DGRAM)  
            waiter_fd = local_waiter_sock.fileno()
            waiter = WaiterThread(self.__sleep, event, remote_waiter_sock)
            waiter_thread = threading.Thread(target=waiter.run)
            waiter_thread.start()
            polling_object = select.poll()
            polling_object.register(local_waiter_sock, select.POLLIN | select.POLLHUP)
            polling_object.register(local_signal_handler_sock, select.POLLIN | select.POLLHUP)
            break_out = False
            while not event.is_set():
                logging.debug("Beginning of main loop")
                fds_and_flags = polling_object.poll()
                for fd, flag_set in fds_and_flags:
                    if fd == handler_fd:
                        if select.POLLIN == flag_set or select.POLLIN in flag_set:
                            logging.warning("Received shutdown signal. Shutting down.")
                            logging.debug("local_signal_handler_sock.recv(9000): %s",
                                          local_signal_handler_sock.recv(9000))
                            local_signal_handler_sock.sendall(b'a')
                        if select.POLLIN != flag_set:
                            logging.debug("Got flag set %s with other flags than POLLIN", flag_set)
                    elif fd == waiter_fd:
                        if select.POLLIN == flag_set or select.POLLIN in flag_set:
                            logging.debug("Received wake up signal from waiter thread")
                            self.__check_ups()
                            logging.debug("local_waiter_sock.recv(9000): %s",
                                          local_waiter_sock.recv(9000))
                        if select.POLLIN != flag_set:
                            logging.debug("Got flag set %s with other flags than POLLIN", flag_set)
                    else:
                        logging.warning("Received socket from unknown fd %s", fd)
                logging.debug("Reached end of loop. Waiting for new wake up via poll")
            logging.debug("Exited main loop")

    ## Initialize the loggin system
    # @param self The object pointer.
    def __logging_config(self):
        logging.basicConfig(datefmt="%H:%M:%S",
                            stream=sys.stderr)

    def run(self):
        self.__logging_config()
        self.parse_args()
        self.__main()

if __name__ == '__main__':
    MONITOR = SmartUpsMonitor()
    MONITOR.run()
