# Web server worker for recording device
# Uses Flask to serve a web interface for the recording device and display a preview of the camera

from flask import Flask, jsonify, render_template, Response
import time
import threading
import logging

PREVIEW_FRAMERATE = 1.0
preview_queue = None
device_state = None
preview_frame = None

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

def web_worker(preview_framerate, queue, state):
    print(F"Starting web worker with preview framerate: {preview_framerate}")
    global PREVIEW_FRAMERATE, preview_queue, device_state, app
    PREVIEW_FRAMERATE = preview_framerate
    preview_queue = queue
    device_state = state

    # Start the background thread to update the latest preview frame
    preview_thread = threading.Thread(target=get_preview_frame)
    preview_thread.daemon = True
    preview_thread.start()
    app.run(host='0.0.0.0', port='80', use_reloader=False, debug=False)


def get_preview_frame():
    print(F"Started preview thread")
    global preview_frame, preview_queue
    while True:
        if (not preview_queue.empty()):
            preview_frame = preview_queue.get()


def gen_frame(preview_framerate, queue):  # generate frames for video streaming
    global preview_frame
    while True and not (preview_frame is None):
        time.sleep(1/preview_framerate)
        frame = queue.get()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route('/video_feed')
def video_feed():
    global PREVIEW_FRAMERATE, preview_queue
    return Response(gen_frame(PREVIEW_FRAMERATE, preview_queue), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    return render_template('index.html')

should_record = False

@app.route('/start_recording')
def start_recording():
    global device_state
    device_state['should_record'] = True
    return jsonify(device_state.copy())

@app.route('/stop_recording')
def stop_recording():
    global device_state
    device_state['should_record'] = False
    return jsonify(device_state.copy())

@app.route('/status')
def get_status():
    global device_state
    return jsonify(device_state.copy())

if __name__ == '__main__':
    print("This is the web worker module, and should not be run directly.")
