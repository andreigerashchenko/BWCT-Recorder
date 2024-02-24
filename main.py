"""
Main python file for the Bike Walk Census Tool Recording Device
Built for the purposes of our ENGS 89/90 Bike Walk Census Tool to record
video at both daytime and nighttime using two separate cameras, one without
an IR filter to capture infrared wavelengths. Nighttime video is meant to be
paired with our infrared spotlight for active illumination purposes.

This file controls all the GPIO and spins off separate threads
to control the camera logic and web UI.

The features of this program include:
- The ability to turn the Pi off
- The ability to start and stop the recording
- The ability to mount and unmount the SD Card

Expected Hardware:
- Raspberry Pi 4 B
- Andrei's custom PCB with 3 buttons, 3 LEDs
- USB Flash Storage Device (64GB or more recommended)
- One USB Camera (used as daytime, we chose ELP 5 MP OV5640 sensor)
- One CSI 15 Pin Camera (used as nighttime camera, 5 MP OV5647 sensor w/o IR filter)

Software Dependencies:
- Picamera2
- OpenCV
- Flask

Authors:
- Andrei Gerashchenko
- Raif Olson
- Wending Wu
"""

import multiprocessing
import time
import os
import json
import RPi.GPIO as GPIO

import camera
import webui

## CONSTANTS 
### LED Pins
POWER_LED_PIN = 18
RECORDING_LED_PIN = 12
MOUNT_LED_PIN = 13

### BUTTON Pins
POWER_BTN_PIN = 3
RECORDING_BTN_PIN = 22
MOUNT_BTN_PIN = 23

## SETTINGS
PREVIEW_FRAMERATE = 30.0
FAST_LED_BLINK_INTERVAL = 0.1
SLOW_LED_BLINK_INTERVAL = 1.0
DEBOUNCE_TIME = 0.25
RECORDING_MAIN_DIRECTORY = "/recordings"

def get_mount_point():
    """
    Get a list of all storage devices and find the mount point path of the first removable media
    Input: None
    Returns: None if no SD card is found, otherwise returns the mount point path as a string
    """
    
    # Get list of storage devices and the partitions on them
    # using terminal command `lsblk --json -o NAME,MOUNTPOINT`
    devices = os.popen("lsblk --json -o NAME,MOUNTPOINT").read()
    # Parse the JSON output
    devices = json.loads(devices)
    # Find the first device with a mount point and sd in the name
    # when you mount any removable media (SD card/flash drive) onto Linux Pi, it will have
    # a naming convention of "sd*" where * is some letter.
    for device in devices['blockdevices']:
        # Check if device is sd* and has children
        # The children are the partitions on the drive
        if device['name'][:2] == "sd" and 'children' in device:
            # Check if any children have a mount point
            for child in device['children']:
                if 'mountpoint' in child:
                    return child['mountpoint']
    return None

# Main Thread
if __name__ == '__main__':
    # STATES
    power_led_time = 0
    power_led_state = GPIO.HIGH
    recording_led_time = 0
    recording_led_state = GPIO.LOW
    mount_led_time = 0
    mount_led_state = GPIO.LOW
    power_btn_time = 0
    recording_btn_time = 0
    mount_btn_time = 0

    # GPIO PIN SETUP
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(POWER_LED_PIN, GPIO.OUT)
    GPIO.setup(RECORDING_LED_PIN, GPIO.OUT)
    GPIO.setup(MOUNT_LED_PIN, GPIO.OUT)
    GPIO.setup(POWER_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(RECORDING_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(MOUNT_BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Initialize status LEDs with their initial states
    GPIO.output(POWER_LED_PIN, power_led_state)
    GPIO.output(RECORDING_LED_PIN, recording_led_state)
    GPIO.output(MOUNT_LED_PIN, mount_led_state)

    # Threading manager
    preview_queue = multiprocessing.Queue()
    manager = multiprocessing.Manager()

    # Use shared dictionary to store device state
    state = manager.dict()
    state['should_record'] = False
    state['recording'] = False
    state['recording_start_time'] = None
    state['recording_duration'] = None
    state['recording_directory'] = None
    state['combining'] = False
    state['night'] = False
    state['error'] = None
    state['cam_heartbeat'] = False
    state['web_heartbeat'] = False
    last_should_record = state['should_record']

    # Start camera.camera_worker in a separate process
    camera_process = multiprocessing.Process(
        target=camera.camera_worker, args=(PREVIEW_FRAMERATE, preview_queue, state))
    camera_process.start()
    camera_worker_running = True

    # Start webui.web_worker in a separate process
    web_process = multiprocessing.Process(
        target=webui.web_worker, args=(PREVIEW_FRAMERATE, preview_queue, state))
    web_process.start()
    web_worker_running = True

    print("Started worker processes")

    # TODO check whether this variable is even used.
    mounted = False
    # string to the path of the mount point directory
    mount_point = None
    print("Looking for mount point")
    while mount_point is None:
        mount_point = get_mount_point()
        if mount_led_state == GPIO.HIGH:
            mount_led_state = GPIO.LOW
        else:
            mount_led_state = GPIO.HIGH
        GPIO.output(MOUNT_LED_PIN, mount_led_state)
        time.sleep(FAST_LED_BLINK_INTERVAL)
        if GPIO.input(POWER_BTN_PIN) == GPIO.LOW:
                state['should_record'] = False
                GPIO.output(POWER_LED_PIN, GPIO.HIGH)
                os.system("poweroff")
    print(F"Found mount point: {mount_point}")
    mounted = True
    mount_led_state = GPIO.HIGH
    GPIO.output(MOUNT_LED_PIN, mount_led_state)

    # Set the recording directory to the first SD card mount point
    RECORDING_MAIN_DIRECTORY = mount_point + RECORDING_MAIN_DIRECTORY

    # Create the recording directory if it doesn't exist
    if not os.path.exists(RECORDING_MAIN_DIRECTORY):
        os.makedirs(RECORDING_MAIN_DIRECTORY)

    # MAIN WHILE LOOP
    while True:
        # if camera_worker_running and state['cam_heartbeat']:
        #     last_cam_heartbeat = time.time()
        #     state['cam_heartbeat'] = False
        #     print("Set false")

        # if camera_worker_running and int(time.time() - last_cam_heartbeat) >= 5:
        #     camera_worker_running = False

        # if not camera_worker_running:
        #     state['should_record'] = False
        #     state['recording'] = False
        #     state['recording_duration'] = 0
        #     state['error'] = "Camera worker process stopped unexpectedly, video segments may not have been merged. Please restart recording device."

        # Control for Power Button
        if GPIO.input(POWER_BTN_PIN) == GPIO.LOW:
            if power_led_state == GPIO.HIGH:
                state['should_record'] = False
                while (state['recording'] == True or state['combining'] == True) and camera_worker_running and web_worker_running:
                    if power_led_state == GPIO.HIGH:
                        power_led_state = GPIO.LOW
                    else:
                        power_led_state = GPIO.HIGH
                    time.sleep(FAST_LED_BLINK_INTERVAL)
                    GPIO.output(POWER_LED_PIN, power_led_state)
                GPIO.output(POWER_LED_PIN, GPIO.HIGH)
                os.system("poweroff")

        # Control for Recording Button
        if GPIO.input(RECORDING_BTN_PIN) == GPIO.LOW:
            if time.time() - recording_btn_time >= DEBOUNCE_TIME:
                recording_btn_time = time.time()
                state['should_record'] = not state['should_record']

        # Control for Mount Button
        if GPIO.input(MOUNT_BTN_PIN) == GPIO.LOW:
            if time.time() - mount_btn_time >= DEBOUNCE_TIME:
                mount_btn_time = time.time()

                # Unmount SD card if mounted
                if mounted:
                    print("Unmounting SD card")
                    # Stop recording if recording
                    state['should_record'] = False
                    while state['recording'] == True:
                        time.sleep(0.1)
                    while mounted:
                        if mount_led_state == GPIO.HIGH:
                            mount_led_state = GPIO.LOW
                        else:
                            mount_led_state = GPIO.HIGH
                        GPIO.output(MOUNT_LED_PIN, mount_led_state)   
                        time.sleep(FAST_LED_BLINK_INTERVAL) 
                        # Unmount with umount, checking to see whether it was successful
                        # os.system(f"partprobe {mount_point}")
                        if os.system(F"umount {mount_point}") == 0:
                            print("Unmounted SD card")
                            mounted = False
                            mount_point = None
                            mount_led_state = GPIO.LOW
                            GPIO.output(MOUNT_LED_PIN, mount_led_state)
                else:
                    # Mount SD card if not mounted
                    while not mounted:
                        if mount_led_state == GPIO.HIGH:
                            mount_led_state = GPIO.LOW
                        else:
                            mount_led_state = GPIO.HIGH
                        GPIO.output(MOUNT_LED_PIN, mount_led_state)
                        time.sleep(FAST_LED_BLINK_INTERVAL)
                        if mount_point is None:
                            mount_point = get_mount_point()
                        else:
                            print("Mounted SD card")
                            mounted = True
                            mount_led_state = GPIO.HIGH
                            GPIO.output(MOUNT_LED_PIN, mount_led_state)


        if state['recording'] == True:
            if time.time() - recording_led_time >= SLOW_LED_BLINK_INTERVAL:
                state['recording_duration'] += SLOW_LED_BLINK_INTERVAL
                recording_led_time = time.time()
                if recording_led_state == GPIO.HIGH:
                    recording_led_state = GPIO.LOW
                else:
                    recording_led_state = GPIO.HIGH
                GPIO.output(RECORDING_LED_PIN, recording_led_state)
        # Detected that recording must be started but we're not recording yet. Start up stuff
        if state['should_record'] == True and state['recording'] == False:
            # Make a new directory for this set of recordings
            os.makedirs(
                F"{RECORDING_MAIN_DIRECTORY}/{time.strftime('%Y%m%d-%H%M%S')}")

            state['recording_directory'] = F"{RECORDING_MAIN_DIRECTORY}/{time.strftime('%Y%m%d-%H%M%S')}"
            for i in range(10):
                if recording_led_state == GPIO.HIGH:
                    recording_led_state = GPIO.LOW
                else:
                    recording_led_state = GPIO.HIGH
                GPIO.output(RECORDING_LED_PIN, recording_led_state)
                time.sleep(FAST_LED_BLINK_INTERVAL)
            recording_led_state = GPIO.HIGH
            GPIO.output(RECORDING_LED_PIN, recording_led_state)
            state['recording_duration'] = 0
        # Detected that recording must be stopped but we're still recording, clean up
        elif state['should_record'] == False and state['recording'] == True:
            for i in range(10):
                if recording_led_state == GPIO.HIGH:
                    recording_led_state = GPIO.LOW
                else:
                    recording_led_state = GPIO.HIGH
                GPIO.output(RECORDING_LED_PIN, recording_led_state)
                time.sleep(FAST_LED_BLINK_INTERVAL)
            recording_led_state = GPIO.LOW
            GPIO.output(RECORDING_LED_PIN, recording_led_state)
            state['recording_duration'] = 0
            state['recording_directory'] = None
        time.sleep(0.1)
