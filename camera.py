
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import FileOutput
import time
import threading
import io
import os

# need cv2 to check if the frame is too dark
import cv2

# SEGMENT_LENGTH = 15 * 60 # 15 minutes * 60 seconds
SEGMENT_LENGTH = 10 # 10 seconds
PREVIEW_FRAMERATE = 1.0
RESOLUTION = (1280, 720)
SWITCH_CHECK_INTERVAL = 5 # 60 seconds
DARK_THRESHOLD = 50 # average pixel value below this is considered too dark

day_cam = None
day_cfg = None
night_cam = None
night_cfg = None
use_night = False # True = night, False = day
lock = threading.Lock()
latest_frame_queue = None
latest_frame = None
last_camera_check = 0

def update_frame():
    print("Started update thread")
    global PREVIEW_FRAMERATE, use_night, day_cam, night_cam, lock, latest_frame_queue, latest_frame
    frame = None
    while True:
        with lock:
            data = io.BytesIO()
            if use_night:
                night_cam.capture_file(data, format='jpeg')
                latest_frame = night_cam.capture_array()
            else:
                day_cam.capture_file(data, format='jpeg')
                latest_frame = day_cam.capture_array()
            frame = data.getvalue()
            latest_frame_queue.put(frame)

            # idea: check once per minute to see if the frame looks too dark, and if so, turn on the night camera
            # if time.time() % 60 == 0:
            #     if frame_is_dark(frame):
        time.sleep(1/PREVIEW_FRAMERATE)

def frame_is_dark(frame):
   # do some analysis to see if the frame is too dark
    cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # check if the average pixel value is below a certain threshold
    avg_pixel = cv2.mean(frame)
    # Dark camera is IR, so only use green channel for average pixel value
    avg_pixel = avg_pixel[1]
    print(F"Average: {avg_pixel} | Dark threshold: {DARK_THRESHOLD}")
    if avg_pixel < DARK_THRESHOLD:
        return True
    else:
        return False

# # camera recording function
# def recording_worker():
#     global state, cam, encoder
#     while True:
#         with lock:
#             if state['recording']:
#                 print("Starting recording")
#                 cam.start_encoder(encoder, f"{state['recording_directory']}/video.h264")
#             elif not state['recording']:
#                 print("Stopping recording")
#                 cam.stop_encoder()




def camera_worker(preview_framerate, queue, state):
    print(F"Starting camera worker with preview framerate: {preview_framerate}")
    # Initialize the camera and worker process
    global RESOLUTION, PREVIEW_FRAMERATE, day_cam, day_cfg, lock, latest_frame_queue, encoder, night_cam, night_cfg, latest_frame, use_night, last_camera_check
    PREVIEW_FRAMERATE = preview_framerate
    latest_frame_queue = queue
    day_cam = Picamera2(1) # The USB camera?
    night_cam = Picamera2(0) # the CSI2 camera
    print("Created camera instances")
    day_cfg = day_cam.create_video_configuration(main={"size": RESOLUTION, "format": "YUYV"})
    night_cfg = night_cam.create_video_configuration(main={"size": RESOLUTION})
    print("Created camera configurations")
    day_cam.configure(day_cfg)
    night_cam.configure(night_cfg)
    print("Configured cameras")
    encoder = H264Encoder()
    print("Created encoder")
    day_cam.start()
    night_cam.start()
    print("Started cameras")
    # Start the background thread to update the latest preview frame
    update_thread = threading.Thread(target=update_frame)
    update_thread.daemon = True
    update_thread.start()

    segments = []
    segment_count = 1
    segment_start_time = None
    should_combine = False
    last_camera = use_night
    while True:
        # Check if the camera should be switched
        if time.time() - last_camera_check >= SWITCH_CHECK_INTERVAL and latest_frame is not None:
            # Check latest_frame to see if it's too dark
            if frame_is_dark(latest_frame):
                use_night = True
            else:
                use_night = False
            last_camera_check = time.time()

        if last_camera != use_night and state['recording']: # Camera has switched
            if use_night:
                print("Switching to night camera")
                day_cam.stop_encoder()
                output = FileOutput(f"{state['recording_directory']}/video_{segment_count}.mp4")
                night_cam.start_encoder(encoder, output, quality=Quality.HIGH)
            else:
                print("Switching to day camera")
                night_cam.stop_encoder()
                output = FileOutput(f"{state['recording_directory']}/video_{segment_count}.mp4")
                day_cam.start_encoder(encoder, output, quality=Quality.HIGH)
            segment_start_time = time.time()
            last_camera = use_night

        if state['recording'] and (time.time() - segment_start_time) >= SEGMENT_LENGTH:
            print("Segment length reached")
            # cam.stop_recording()
            if use_night:
                night_cam.stop_encoder()
            else:
                day_cam.stop_encoder()
            print("Encoder stopped")
            segments.append(f"{state['recording_directory']}/video_{segment_count}.mp4")
            segment_count += 1
            output = FileOutput(f"{state['recording_directory']}/video_{segment_count}.mp4")
            if use_night:
                night_cam.start_encoder(encoder, output, quality=Quality.HIGH)
            else:
                day_cam.start_encoder(encoder, output, quality=Quality.HIGH)
            segment_start_time = time.time()
            print(F"Encoder started, recording to {state['recording_directory']}/video_{segment_count}.mp4")

        if should_combine:
            print("Combining segments")
            # Combine segments using ffmpeg
            # ffmpeg -i "concat:input1.mp4|input2.mp4|input3.mp4" -c copy output.mp4
            state['combining'] = True
            os.system(F"ffmpeg -i 'concat:{'|'.join(segments)}' -c copy {state['recording_directory']}/video.mp4")
            # Remove segments
            for segment in segments:
                os.remove(segment)
            segments = []
            segment_count = 1
            should_combine = False
            state['recording_directory'] = None
            print("Combined segments")
            state['combining'] = False
        
        if state['should_record'] and not state['recording']:
            # Wait for the recording directory to be set
            while state['recording_directory'] is None:
                time.sleep(0.1)
            print("Starting recording")
            # Directory for current recording session will have already been created
            # Start recording first segment
            output = FileOutput(f"{state['recording_directory']}/video_{segment_count}.mp4")
            if use_night:
                night_cam.start_encoder(encoder, output, quality=Quality.HIGH)
            else:
                day_cam.start_encoder(encoder, output, quality=Quality.HIGH)
            state['recording_start_time'] = time.time()
            segment_start_time = time.time()
            print(F"Encoder started, recording to {state['recording_directory']}/video_{segment_count}.mp4")
            state['recording'] = True
        elif not state['should_record'] and state['recording']:
            print("Stopping recording")
            if use_night:
                night_cam.stop_encoder()
            else:
                day_cam.stop_encoder()
            print("Encoder stopped")
            segments.append(f"{state['recording_directory']}/video_{segment_count}.mp4")
            state['recording'] = False
            should_combine = True
        time.sleep(0.1)

if __name__ == "__main__":
    print(F"This is the camera worker module, and should not be run directly.")