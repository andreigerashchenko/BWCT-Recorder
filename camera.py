
import sys
sys.path.extend([
    "/usr/lib/python3/dist-packages"
])

# from picamera2 import Picamera2
# from picamera2.encoders import H264Encoder, Quality, MJPEGEncoder
# from picamera2.outputs import FileOutput, FfmpegOutput

from vidgear.gears import PiGear, CamGear
from vidgear.gears import WriteGear

import time
import threading
import io
import os
import subprocess

# need cv2 to check if the frame is too dark
import cv2

DEBUG = False

SEGMENT_CHUNKS = 5 # Segments to merge at a time

# Segment lengths of our chunks, in seconds. variety for testing
SEGMENT_LENGTH = 15 * 60 # 15 minutes * 60 seconds
# SEGMENT_LENGTH = 3 * 60 # 3 minutes * 60 seconds
# SEGMENT_LENGTH = 20 # in seconds

# This can only the framerate the usb camera supports at the set resolution.
RECORD_FRAMERATE = 20
# This can only be a resolution supported by the usb camera.
RESOLUTION = (800, 600)
# SWITCH_CHECK_INTERVAL = SEGMENT_LENGTH / 3
SWITCH_CHECK_INTERVAL = 5
DARK_THRESHOLD = 50 # average pixel value below this is considered too dark

state = None

day_cam = None
day_cfg = None
night_cam = None
night_cfg = None
use_night = False # True = night, False = day
lock = threading.Lock()
latest_frame_queue = None
latest_frame = None
last_camera_check = 0
fourcc = None
frame_id = 0

output_params = {
                    "-vcodec": "h264_v4l2m2m",
                    # "-vcodec": "libx264",
                    # "-crf": 0,
                    "-b:v": "6000k",
                    "-preset": "medium",
                    "-input_framerate": RECORD_FRAMERATE,
                    # "-tune": "film",
                    # "-fourcc": "MJPG"
                }

class DayCam:
    def __init__(self, device_index=0, resolution=(1280, 720), framerate=30):
        print("before day cam init")
        # self.cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
        options = {
            # "queue": True,
            # "buffer_count": 4,
            "THREADED_QUEUE_MODE": True,
            "CAP_PROP_FRAME_WIDTH": int(resolution[0]),
            "CAP_PROP_FRAME_HEIGHT": int(resolution[1]),
            "CAP_PROP_FPS": int(framerate),
            # "CAP_PROP_FOURCC": cv2.VideoWriter_fourcc(*'MJPG')
            "CAP_PROP_FOURCC": cv2.VideoWriter_fourcc(*'YUYV')

        }
        self.cap = CamGear(source=device_index, logging=True, **options)
        print("after day cam init")
        # self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
        # self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
        # self.cap.set(cv2.CAP_PROP_FPS, framerate)
        # fourcc = cv2.VideoWriter_fourcc(*'MJPG')

        # self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        print("configured day cam")
        self.is_recording = False
        self.is_capturing = False
        self.frame = None
        self.video_writer = None
        self.capture_thread = threading.Thread(target=self.capture_loop)
        self.capture_thread.daemon = True
        self.busy = False
        self.frame_id = 0
        
    def capture_loop(self):
        while self.is_capturing:
            frame = self.cap.read()
            # print(frame)
            if frame is not None:

                self.frame = frame
                if self.is_recording and self.video_writer is not None:
                    self.busy = True
                    self.video_writer.write(frame)
                    self.busy = False
                    # increment the global recording frame id
                    self.frame_id += 1
                else:
                    self.frame_id = 0
                
    def start_capture(self):
        self.is_capturing = True
        print("start capture")
        self.cap.start()
        # print(self.cap.read())
        if not self.capture_thread.is_alive():
            self.capture_thread = threading.Thread(target=self.capture_loop)
            self.capture_thread.start()
            
    def stop_capture(self):
        self.is_capturing = False
    
    def start_recording(self, video_writer):
        self.video_writer = video_writer
        self.is_recording = True
            
    def stop_recording(self):
        self.is_recording = False
        if self.video_writer is not None:
            while self.busy:
                pass
            # self.video_writer.release()  # Properly close the video file for opencv
            self.video_writer.close() # Properly close the video file for vidGear
            print("released video writer")

        self.video_writer = None  # Reset the videoWriter object



    def get_latest_frame(self):
        # Return the latest frame captured by the capture thread
        return self.frame
    
    def get_frame_id(self):
        # Return he current recording frame count
        return self.frame_id


class NightCam:
    def __init__(self, device_index=0, resolution=(1280, 720), framerate=30):
        print("before night cam init")
        # self.cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
        night_cfg = {
            "queue": True,
            "buffer_count": 4,
        }
        self.cap = PiGear(camera_num=device_index, resolution=resolution, framerate=framerate, logging=True, **night_cfg) # the CSI2 camera

        print("after night cam init")
        # self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
        # self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
        # self.cap.set(cv2.CAP_PROP_FPS, framerate)
        # fourcc = cv2.VideoWriter_fourcc(*'MJPG')

        # self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)


        print("configured night cam")
        self.is_recording = False
        self.is_capturing = False
        self.frame = None
        self.video_writer = None
        self.capture_thread = threading.Thread(target=self.capture_loop)
        self.capture_thread.daemon = True
        self.busy = False
        self.frame_id = 0
        
    def capture_loop(self):
        while self.is_capturing:
            frame = self.cap.read()
            if frame is not None:
                # print(frame)
                self.frame = frame
                if self.is_recording and self.video_writer is not None:
                    self.busy = True
                    self.video_writer.write(frame)
                    self.busy = False
                    # increment the global recording frame id
                    self.frame_id += 1
                else:
                    self.frame_id = 0
                
    def start_capture(self):
        self.is_capturing = True
        if not self.capture_thread.is_alive():
            self.cap.start()
            self.capture_thread = threading.Thread(target=self.capture_loop)
            self.capture_thread.start()
            
    def stop_capture(self):
        self.is_capturing = False
    
    def start_recording(self, video_writer):
        self.video_writer = video_writer
        self.is_recording = True
            
    def stop_recording(self):
        self.is_recording = False
        if self.video_writer is not None:
            while self.busy:
                pass
            self.video_writer.close()  # Properly close the video file
            print("released video writer")

        self.video_writer = None  # Reset the videoWriter object



    def get_latest_frame(self):
        # Return the latest frame captured by the capture thread
        return self.frame
    
    def get_frame_id(self):
        # Return he current recording frame count
        return self.frame_id


# def update_frame():
#     print("Started update thread")
#     global PREVIEW_FRAMERATE, use_night, day_cam, night_cam, lock, latest_frame_queue, latest_frame
#     frame = None
#     while True:
#         with lock:
#             data = io.BytesIO()
#             if use_night:
#                 night_cam.capture_file(data, format='jpeg')
#                 latest_frame = night_cam.capture_array()
#             else:
#                 day_cam.capture_file(data, format='jpeg')
#                 latest_frame = day_cam.capture_array()
#             frame = data.getvalue()
#             latest_frame_queue.put(frame)
# 
#             # idea: check once per minute to see if the frame looks too dark, and if so, turn on the night camera
#             # if time.time() % 60 == 0:
#             #     if frame_is_dark(frame):
#         time.sleep(1/PREVIEW_FRAMERATE)

def update_frame():
    global PREVIEW_FRAMERATE, use_night, day_cam, night_cam, lock, latest_frame_queue, latest_frame
    while True:
        with lock:
            if use_night:
                # Assuming night_cam still uses Picamera2 methods
                # Adjust accordingly if you also replace night_cam with a similar class to DayCam
                # data = io.BytesIO()
                # night_cam.capture_file(data, format='jpeg')
                # latest_frame = night_cam.capture_array()
                latest_frame = night_cam.get_latest_frame()
                if latest_frame is not None:
                    latest_frame = cv2.cvtColor(latest_frame, cv2.COLOR_BGR2RGB)
                    frame = cv2.imencode('.jpg', latest_frame)[1].tobytes()
                    latest_frame_queue.put(frame)
            else:
                # Use DayCam's method to get the latest frame
                latest_frame = day_cam.get_latest_frame()
                if latest_frame is not None:
                    frame = cv2.imencode('.jpg', latest_frame)[1].tobytes()
                    latest_frame_queue.put(frame)
        time.sleep(1/PREVIEW_FRAMERATE)

def frame_is_dark(frame):
    """This function checks if the green channel of the image is below a certain threshold"""
    # check if the average pixel value is below a certain threshold
    avg_pixel = cv2.mean(frame)
    # Dark camera is IR, so only use green channel for average pixel value
    avg_pixel = avg_pixel[1]
    # print(F"Average: {avg_pixel} | Dark threshold: {DARK_THRESHOLD}")
    if avg_pixel < DARK_THRESHOLD:
        return True
    else:
        return False

def night_camera_callback(request):
    """Checks if the night camera encoder is running and if it is, increments the frame count"""
    global night_encoder_running, frame_id
    if night_encoder_running:
        frame_id += 1

def camera_init():
    global RESOLUTION, PREVIEW_FRAMERATE, day_cam, day_cfg, lock, latest_frame_queue, encoder, night_cam, night_cfg, latest_frame, use_night, last_camera_check, fourcc, night_output_params
    # night_cam = Picamera2() # the CSI2 camera
    print("Created camera instance")
    # night_cfg = night_cam.create_video_configuration(main={"size": RESOLUTION})

    print("Created camera configuration")
    # night_cam.configure(night_cfg)
    print("Configured camera")

    # encoder = MJPEGEncoder()

    # Set up VideoWriter for recording with the same resolution and framerate as DayCam
    # fourcc = cv2.VideoWriter_fourcc(*'MJPG') # try with h264 fourcc
    print("Created encoder")
    # Attach the frame counter callback to the night camera.
    # night_cam.pre_callback = night_camera_callback

    # night_cam.start()
    print("Started camera")
    index = 0
    try:
        day_cam = DayCam(device_index=index, resolution=RESOLUTION, framerate=RECORD_FRAMERATE)  # Adjust device_index as needed
    except:
        print(F"Day cam index {index} failed")
        index=1
        try:
            day_cam = DayCam(device_index=index, resolution=RESOLUTION, framerate=RECORD_FRAMERATE)  # Adjust device_index as needed
        except:
            print(F"Day cam index {index} failed")

        # print(F"Day cam started on index {index}")

    print(F"Day cam started on index {index}")
    day_cam.start_capture()

    night_cam = NightCam(device_index=0, resolution=RESOLUTION, framerate=RECORD_FRAMERATE) # Adjut device_index as needed
    print("started night cam")

    # if day_cam.cap.read() is not None:
    #     print(F"Day cam index {index} failed")
    #     index = 1
    #     day_cam = DayCam(device_index=index, resolution=RESOLUTION, framerate=RECORD_FRAMERATE)  # Adjust device_index as needed
    #     if day_cam.cap.read() is not None:
    #         print(F"Day cam index {index} failed")
    #     else:
    #         print(F"Day cam started on index {index}")
    #         day_cam.start_capture()
    # else:
    #     print(F"Day cam started on index {index}")
    #     day_cam.start_capture()

# def heartbeat():
#     global state
#     if not state['cam_heartbeat']:
#         state['cam_hearbeat'] = True
#         print("Set true")




def camera_worker(preview_framerate, queue, state_arg):
    print(F"Starting camera worker with preview framerate: {preview_framerate}")
    # Initialize the camera and worker process
    global RESOLUTION, PREVIEW_FRAMERATE, day_cam, day_cfg, lock, latest_frame_queue, encoder, night_cam, night_cfg, latest_frame, use_night, last_camera_check, fourcc, state, night_encoder_running, frame_id, output_params
    PREVIEW_FRAMERATE = preview_framerate
    latest_frame_queue = queue
    state = state_arg

    camera_init()

    # Start heartbeat thread
    # heartbeat_thread = threading.Thread(target=heartbeat)
    # heartbeat_thread.daemon = True
    # heartbeat_thread.start()
    # print("camera heartbeat thread started")

    # Start the background thread to update the latest preview frame
    update_thread = threading.Thread(target=update_frame)
    update_thread.daemon = True
    update_thread.start()
    print("update thread started")

    segments = []
    segment_count = 1
    segment_start_time = None
    should_combine = False
    last_camera = use_night
    night_encoder_running = False
    frame_id = 0


    while True:
        # Check if the camera should be switched
        # print(day_cam.get_latest_frame())
        if time.time() - last_camera_check >= SWITCH_CHECK_INTERVAL and latest_frame is not None:
            # Check latest_frame to see if it's too dark

            if frame_is_dark(latest_frame):
                use_night = True
                state['night'] = True
            else:
                use_night = False
                state['night'] = False
                
            last_camera_check = time.time()

        if last_camera != use_night and state['recording']: # Camera has switched
            segments.append(f"{state['recording_directory']}/video_{segment_count}.mp4")

            segment_count += 1

            if use_night:
                print("Switching to night camera")
                frame_id += day_cam.get_frame_id()
                day_cam.stop_recording()
                # for the vidGear

                output_video_name = f"{state['recording_directory']}/video_{segment_count}.mp4"
                night_video_writer = WriteGear(output=output_video_name, compression_mode=True, logging=True, **output_params)

                # output = FfmpegOutput(f"{state['recording_directory']}/video_{segment_count}.avi")
                # print("created new encoder")
                if not night_encoder_running:
                    # night_cam.start_encoder(encoder, output, quality=Quality.HIGH)
                    night_encoder_running = True
                night_cam.start_recording(night_video_writer)
                print(f"night time camera recording started: {output_video_name}")

            else:
                print("Switching to day camera")
                # night_cam.stop_encoder()
                night_encoder_running = False
                frame_id += night_cam.get_frame_id()
                night_cam.stop_recording()

                # Set up VideoWriter for recording with the same resolution and framerate as DayCam


                # video_writer = cv2.VideoWriter(f"{state['recording_directory']}/video_{segment_count}.avi", fourcc, RECORD_FRAMERATE, RESOLUTION)  # Adjust filename, codec, and parameters as needed
                # video_writer.set(cv2.CAP_PROP_FPS, RECORD_FRAMERATE)
                output_video_name = f"{state['recording_directory']}/video_{segment_count}.mp4"
                video_writer = WriteGear(output=output_video_name, compression_mode=True, logging=True, **output_params)
                print(f"daytime camera recording started: {output_video_name}")
                day_cam.start_recording(video_writer)

            # TODO when you change from dark to light, write to a file that records the frame ID of the switch so Raif's script knows when to switch color processing
            # TODO you have to add a counter to keep track of frame ID. can't use timestamp bc that assumes constant frame times which is not guaranteed
            """
            TODO: File Format Definition
            Each column is defined as: frameID, state after this frame (night/day)
            The first line should always be frame 0, day/night.
            Then whenever we do a switch, write a new line to this file with the frame id and the state.
            """
            if state['recording']:
                with open(day_night_file_path, "a") as f:
                    f.write(f"{frame_id},{use_night}\n")

            segment_start_time = time.time()
            last_camera = use_night

        if state['recording'] and (time.time() - segment_start_time) >= SEGMENT_LENGTH:
            print("Segment length reached")
            # cam.stop_recording()
            if use_night:
                # night_cam.stop_encoder()
                night_cam.stop_recording()
                night_encoder_running = False
            else:
                day_cam.stop_recording()
            print("Encoder stopped")
            segments.append(f"{state['recording_directory']}/video_{segment_count}.mp4")
            segment_count += 1
            if use_night:
                output_video_name = f"{state['recording_directory']}/video_{segment_count}.mp4"
                night_video_writer = WriteGear(output=output_video_name, compression_mode=True, logging=True, **output_params)

                # output = FfmpegOutput(f"{state['recording_directory']}/video_{segment_count}.avi")
                # print("created new encoder")
                # if not night_encoder_running:
                    # night_cam.start_encoder(encoder, output, quality=Quality.HIGH)
                    # night_encoder_running = True
                night_cam.start_recording(night_video_writer)

            else:
                # Set up VideoWriter for recording with the same resolution and framerate as DayCam

                # video_writer = cv2.VideoWriter(f"{state['recording_directory']}/video_{segment_count}.avi", fourcc, RECORD_FRAMERATE, RESOLUTION)  # Adjust filename, codec, and parameters as needed
                # video_writer.set(cv2.CAP_PROP_FPS, RECORD_FRAMERATE)
                output_video_name = f"{state['recording_directory']}/video_{segment_count}.mp4"
                video_writer = WriteGear(output=output_video_name, compression_mode=True, logging=True, **output_params)
                print(f"daytime camera recording started: {output_video_name}")
                day_cam.start_recording(video_writer)
            segment_start_time = time.time()
            print(F"Encoder started, recording to {state['recording_directory']}/video_{segment_count}.mp4")

        if should_combine:
            print("Combining segments")
            # Combine segments using ffmpeg
            # ffmpeg -i "concat:input1.mp4|input2.mp4|input3.mp4" -c copy output.mp4
            state['combining'] = True

            
            # Concatenate segments in chunks
            # Keep iterating through segment list, concatenating chunks of SEGMENT_CHUNKS segments at a time
            # If there are less than SEGMENT_CHUNKS segments left, concatenate the remaining segments and name the output video "video_full.avi"
            # to_delete = segments
            # segment_names = []
            # merge_stage = 1
            # while len(segments) > SEGMENT_CHUNKS:
            #     chunk = []
            #     for i in range(0, len(segments)):
            #         if len(chunk) < SEGMENT_CHUNKS and i < len(segments):
            #             chunk.append(segments[i])
            #         else:
            #             chunk_concatenated = "|".join(chunk)
            #             chunk_output = f"{state['recording_directory']}/chunk{merge_stage}_{i//SEGMENT_CHUNKS}.avi"
            #             cmd = [
            #                 "ffmpeg",
            #                 "-i",
            #                 f"concat:{chunk_concatenated}",
            #                 "-c", "copy", chunk_output]
            #             print(f"cmd: {cmd}")
            #             # os.system(f"ffmpeg -i 'concat:{chunk_concatenated}' -c copy {state['recording_directory']}/video_full.avi")
            #             subprocess.call(
            #                 cmd
            #             )
            #             segment_names.append(chunk_output)
            #             to_delete.append(chunk_output)
            #             chunk = []
            #     segments = segment_names
            #     merge_stage += 1
            # # os.system(f"ffmpeg -i 'concat:{'|'.join(segment_names)}' -c copy {state['recording_directory']}/video_full.avi")
            # chunk_concatenated = "|".join(segment_names)

            # videoListFile = "videoList.txt"
            # with open(videoListFile, "w") as f:
            #     for videoFile in segments:
            #         f.write(f"file '{videoFile}'\n")
            # cmd = [
            #     "ffmpeg",
            #     "-f", "concat",
            #     "-safe", "0"
            #     "-i", "videoList.txt",
            #     "-c", "copy", f"{state['recording_directory']}/video_full.avi"]
            # print(f"cmd: {cmd}")
            # subprocess.call(
            #     cmd
            # )
            # for segment in segments:
            #     os.remove(segment)

            # segment_names = []
            # for i in range(1, segment_count + 1):
            #     segment_names.append(f"{state['recording_directory']}/video_ffmpeged{i}.mp4")
            #     os.system(f"ffmpeg -y -r {RECORD_FRAMERATE} -i {state['recording_directory']}/video_{i}.mp4 {segment_names[i-1]}") # maybe fix framerate?
            # os.system(F"ffmpeg -i concat:{'|'.join(segment_names)} -c copy {state['recording_directory']}/video.mp4")
            # os.system(f"ffmpeg -i 'concat:{'|'.join(segments)}' -c copy {state['recording_directory']}/video_full.avi")

            # Remove segments
            # for segment in segments:
            #     os.remove(segment)
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
            # Reset the frame_id so when starting new recording
            frame_id = 0
            # Setup new day/night file
            day_night_file_path = f"{state['recording_directory']}/day_night.csv"
            with open(day_night_file_path, "w") as f:
                f.write("frame_id,night_true\n")
                f.write(f"{frame_id},{use_night}\n")
            # Directory for current recording session will have already been created
            # Start recording first segment
            if use_night:

                output_video_name = f"{state['recording_directory']}/video_{segment_count}.mp4"
                night_video_writer = WriteGear(output=output_video_name, compression_mode=True, logging=True, **output_params)

                # output = FfmpegOutput(f"{state['recording_directory']}/video_{segment_count}.avi")
                # print("created new encoder")
                # if not night_encoder_running:
                    # night_cam.start_encoder(encoder, output, quality=Quality.HIGH)
                    # night_encoder_running = True
                night_cam.start_recording(night_video_writer)
            else:
                # Set up VideoWriter for recording with the same resolution and framerate as DayCam

                # video_writer = cv2.VideoWriter(f"{state['recording_directory']}/video_{segment_count}.avi", fourcc, RECORD_FRAMERATE, RESOLUTION)  # Adjust filename, codec, and parameters as needed
                # video_writer.set(cv2.CAP_PROP_FPS, RECORD_FRAMERATE)
                output_video_name = f"{state['recording_directory']}/video_{segment_count}.mp4"
                video_writer = WriteGear(output=output_video_name, compression_mode=True, logging=True, **output_params)
                print(f"daytime camera recording started: {output_video_name}")
                day_cam.start_recording(video_writer)
            state['recording_start_time'] = time.time()
            segment_start_time = time.time()
            print(F"Encoder started, recording to {state['recording_directory']}/video_{segment_count}.mp4")
            state['recording'] = True
            last_camera = use_night
        elif not state['should_record'] and state['recording']:
            print("Stopping recording")
            output = None
            if use_night:
                # night_cam.stop_encoder()
                night_cam.stop_recording()
                night_encoder_running = False
            else:
                day_cam.stop_recording()
            print("Encoder stopped")
            segments.append(f"{state['recording_directory']}/video_{segment_count}.mp4")
            state['recording'] = False
            state['recording_directory'] = None # set it only once we're finished writing to that directory
            should_combine = True
        time.sleep(0.1)

if __name__ == "__main__":
    print(F"This is the camera worker module, and should not be run directly.")

    if DEBUG:
        import multiprocessing
        preview_queue = multiprocessing.Queue()
        manager = multiprocessing.Manager()
        # Use shared dictionary to store device state
        state = manager.dict()
        state['should_record'] = False
        state['recording'] = False
        state['recording_start_time'] = None
        state['recording_directory'] = None
        state['combining'] = False
        state['night'] = False
        state['error'] = None
        state['cam_heartbeat'] = False
        camera_worker(PREVIEW_FRAMERATE, preview_queue, state)