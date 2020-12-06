#!/usr/bin/python3
# Author: Stanislav Jakubek
# Date: 10-Dec-2020

import json
import logging
import smbus
import sqlite3
import threading
import time
import Pi7SegPy
import RPi.GPIO as GPIO
from bottle import request, route, run

# Thermometer variables
therm_base_dir = "/sys/bus/w1/devices/"
therm1_name = "28-00000c07d6c0" # TO-92
therm2_name = "28-3c01d607d003" # Waterproof
therm_device_file = "/w1_slave"
therm1_file_path = therm_base_dir + therm1_name + therm_device_file
therm2_file_path = therm_base_dir + therm2_name + therm_device_file

# Light sensor variables
# Continuous measurement modes
ls_cont_low_res_mode = 0x13 # 4lx resolution. Time typically 16ms
ls_cont_high_res_mode_1 = 0x10 # 1lx resolution. Time typically 120ms
ls_cont_high_res_mode_2 = 0x11 # 0.5lx resolution. Time typically 120ms
# One time measurement modes.
# Device automatically set to power down after measurement.
ls_one_time_low_res_mode = 0x23 # 4lx resolution. Time typically 16ms
ls_one_time_high_res_mode_1 = 0x20 # 1lx resolution. Time typically 120ms
ls_one_time_high_res_mode_2 = 0x21 # 0.5lx resolution. Time typically 120ms
# Other light sensor variables
ls_i2c_address = 0x23
ls_bus = smbus.SMBus(1)

# 7-segment display variables (GPIO in BCM numbering)
disp_data = 18 # GPIO pin connected to DIO
disp_clock = 23 # GPIO pin connected to SCLK
disp_latch = 24 # GPIO pin connected to RCLK
disp_chain = 2 # Number of 595 shift registers driving the display
disp_displays = 4 # Number of individual 7-segment displays
disp_initialized = False

# Button variables
btn_data_pin = 26
btn_initialized = False

# RGB LED variables (GPIO in BCM numbering)
led_red_pin = 21 # GPIO pin connected to R
led_green_pin = 20 # GPIO pin connected to G
led_blue_pin = 16 # GPIO connected to B
led_initialized = False

# Database variables
db_con = sqlite3.connect("jakubek_vnos.db", check_same_thread = False)
db_cur = db_con.cursor()

# Display modes
water_temp_mode = True
room_temp_mode = False
light_level_mode = False

# Thread variables
stop_threads = False

# Current temperature and light level data
temp1 = 0.0
temp2 = 0.0
ll = 0.0

# Button initialization
def init_button():
    logging.debug("Initializing button ...")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(btn_data_pin, GPIO.IN)
    GPIO.add_event_detect(btn_data_pin, GPIO.RISING, callback = switch_display_mode)
    global btn_initialized
    btn_initialized = True

# Database initialization
def init_database():
    logging.debug("Initializing databse ...")
    
    # Check if the table 'measurements' already exists, if not, create it
    db_cur.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='measurements' ''')
    if db_cur.fetchone()[0] != 1:
        db_cur.execute("CREATE TABLE measurements(datetime TEXT, room_temp REAL, water_temp REAL, light_level REAL)")

# 7-segment display initialization
def init_display():
    logging.debug("Initializing display ...")
    Pi7SegPy.init(disp_data, disp_clock, disp_latch, disp_chain, disp_displays)
    global disp_initialized
    disp_initialized = True

# RGB LED initialization
def init_led():
    logging.debug("Initializing RGB LED ...")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(led_red_pin, GPIO.OUT)
    GPIO.setup(led_green_pin, GPIO.OUT)
    GPIO.setup(led_blue_pin, GPIO.OUT)
    global led_initialized
    led_initialized = True

# Convert 2 bytes of data into a decimal number
def convert_to_number(data):
    result = (data[1] + (256 * data[0])) / 1.2
    return result

# Save measurements into the database in an infinite loop
def db_loop(name):
    logging.debug("Thread %s starting ...", name)
    
    # Wait until initial measurements are taken
    time.sleep(5)
    
    while not stop_threads:
        logging.debug("Inserting into a database ...")
        with db_con:
            db_cur.execute("INSERT INTO measurements (datetime, room_temp, water_temp, light_level) VALUES (datetime('now', 'localtime'), ?, ?, ?)",
                           (temp1, temp2, ll))
        time.sleep(5) # Update only once every 5 seconds

# Display in an infinite loop
def disp_loop(name):
    logging.debug("Thread %s starting ...", name)
    
    # Wait until initial measurements are taken
    time.sleep(5)
    
    while not stop_threads:
        temp_str = format(temp2, ".2f").zfill(2)
        Pi7SegPy.show([
            int(temp_str[0]),
            int(temp_str[1]),
            int(temp_str[3]),
            int(temp_str[4])], [3])

@route("/get_data")
def get_data():
    return { "items": [
        {"name": "Room temperature", "value": format(temp1, ".2f")},
        {"name": "Water temperature", "value": format(temp2, ".2f")},
        {"name": "Light level", "value": format(ll, ".2f")}
        ]}

@route("/get_all_data")
def get_all_data():
    start = request.query.start
    end = request.query.end
    
    if start != "" and end != "":
        print(start)
        print(end)
        db_cur.execute("SELECT * FROM measurements WHERE datetime BETWEEN ? AND ?",
                       (start, end))
    elif start != "":
        print(start)
        db_cur.execute("SELECT * FROM measurements WHERE datetime >= ?",
                       (start,))
    elif end != "":
        print(end)
        db_cur.execute("SELECT * FROM measurements WHERE datetime <= ?",
                       (end,))
    else:
        db_cur.execute("SELECT * FROM measurements")
    
    data = db_cur.fetchall()
    return json.dumps(data)

# Update RGB LED color in an infinite loop
def led_loop(name):
    logging.debug("Thread %s starting ...", name)
    global temp2
    
    while not stop_threads:
        if temp2 < 20.0:
            # Cold, show blue LED
            GPIO.output(led_red_pin, GPIO.LOW)
            GPIO.output(led_green_pin, GPIO.LOW)
            GPIO.output(led_blue_pin, GPIO.HIGH)
        elif temp2 < 26.0:
            # Ideal, show green LED
            GPIO.output(led_red_pin, GPIO.LOW)
            GPIO.output(led_green_pin, GPIO.HIGH)
            GPIO.output(led_blue_pin, GPIO.LOW)
        else:
            # Hot, show red LED
            GPIO.output(led_red_pin, GPIO.HIGH)
            GPIO.output(led_green_pin, GPIO.LOW)
            GPIO.output(led_blue_pin, GPIO.LOW)
        time.sleep(1) # Update only once a second

# Return contents of the specified file in lines
def read_file(file_path):
    f = open(file_path, 'r')
    lines = f.readlines()
    f.close()
    return lines

# Read light level from the light sensor at addr
def read_light(addr = ls_i2c_address):
    logging.debug("Reading values from light sensor ...")
    data = ls_bus.read_i2c_block_data(addr, ls_one_time_high_res_mode_2)
    return convert_to_number(data)

# Read measured values in an infinite loop
def read_loop(name):
    logging.debug("Thread %s starting ...", name)
    global temp1
    global temp2
    global ll
    
    while not stop_threads:
        temp1 = read_temp(1)
        temp2 = read_temp(2)
        ll = read_light()

# Read temperature from thermometer therm
def read_temp(therm):
    if therm == 1:
        logging.debug("Reading values from thermometer 1 ...")
        lines = read_file(therm1_file_path)
        
        # If CRC failed, repeat measurements
        while lines[0].strip()[-3:] != "YES":
            logging.debug("Thermometer 1 CRC failed!")
            lines = read_file(therm1_file_path)
    elif therm == 2:
        logging.debug("Reading values from thermometer 2 ...")
        lines = read_file(therm2_file_path)
        
        # If CRC failed, repeat measurements
        while lines[0].strip()[-3:] != "YES":
            logging.debug("Thermometer 2 CRC failed!")
            lines = read_file(therm2_file_path)
    else:
        logging.error("Invalid thermometer number!")
        return 99.99
    
    temp_position = lines[1].find("t=")
    
    if temp_position != -1:
        temp_string = lines[1][temp_position+2:]
        temp_celsius = float(temp_string) / 1000.0
        return temp_celsius
    else:
        logging.error("String 't=' not found!")
        return 99.99

# Print measured values to the console
def print_values():
    print("Room temperature: " + str(temp1) + " °C")
    print("Water temperature: " + str(temp2) + " °C")
    print("Light Level: " + format(ll, '.2f') + " lx")

# Switch between display modes
def switch_display_mode(channel):
    logging.debug("Switching display modes ...")
    global water_temp_mode
    global room_temp_mode
    global light_level_mode
    
    if water_temp_mode:
        # Switch to room temperature mode
        room_temp_mode = True
        water_temp_mode = False
    elif room_temp_mode:
        # Switch to light level mode
        light_level_mode = True
        room_temp_mode = False
    elif light_level_mode:
        # Switch to water temperature mode
        water_temp_mode = True
        light_level_mode = False
    else:
        # Fallback to water temperature mode (this shouldn't happen)
        water_temp_mode = True
        room_temp_mode = False
        light_level_mode = False

def cleanup():
    logging.debug("Cleaning up ...")
    if disp_initialized:
        # Empty out the 7-segment display
        Pi7SegPy.show([' ',' ',' ',' '])
    if btn_initialized or led_initialized:
        GPIO.cleanup()

def main():
    logging.debug("Starting program ...")
    
    # Initialize components
    init_button()
    init_display()
    init_led()
    init_database()
    
    # Start taking measurements
    msr_thr = threading.Thread(target = read_loop, args = (1,), daemon = True)
    msr_thr.start()
    # Start updating the RGB LED
    led_thr = threading.Thread(target = led_loop, args = (2,), daemon = True)
    led_thr.start()
    # Start saving measurements into the database
    db_thr = threading.Thread(target = db_loop, args = (3,), daemon = True)
    db_thr.start()
    # Start displaying
    disp_thr = threading.Thread(target = disp_loop, args = (4,), daemon = True)
    disp_thr.start()
    
    # Start a HTTP server (0.0.0.0 to listen on all interfaces)
    run(host = "0.0.0.0", port = 8080)
    
    # Stop executing threads
    global stop_threads
    stop_threads = True
    
    print_values()
    cleanup()

if __name__ == "__main__":
    logging.basicConfig(level = logging.WARNING) # Set logging level
    main()
