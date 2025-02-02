import cv2
import time
import numpy
import ctypes
import win32api
import threading
import bettercam
from multiprocessing import Pipe, Process
from ctypes import windll
import os
import json
import math

ascii_art = r"""
 /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\ 
( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )
 > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ < 
  /\_/\   __    __     ______     _____     ______              ______     __  __     /\_/\ 
 ( o.o ) /\ "-./  \   /\  __ \   /\  __-.  /\  ___\            /\  == \   /\ \_\ \   ( o.o )
  > ^ <  \ \ \-./\ \  \ \  __ \  \ \ \/\ \ \ \  __\            \ \  __<   \ \____ \   > ^ < 
  /\_/\   \ \_\ \ \_\  \ \_\ \_\  \ \____-  \ \_____\           \ \_____\  \/\_____\  /\_/\ 
 ( o.o )   \/_/  \/_/   \/_/\/_/   \/____/   \/_____/            \/_____/   \/_____/ ( o.o )
  > ^ <                                                                               > ^ < 
  /\_/\            ______     __  __     __   __     ______     __  __     __         /\_/\ 
 ( o.o )          /\  ___\   /\ \/\ \   /\ "-.\ \   /\  __ \   /\ \/ /    /\ \       ( o.o )
  > ^ <           \ \___  \  \ \ \_\ \  \ \ \-.  \  \ \ \/\ \  \ \  _"-.  \ \ \       > ^ < 
  /\_/\            \/\_____\  \ \_____\  \ \_\\"\_\  \ \_____\  \ \_\ \_\  \ \_\      /\_/\ 
 ( o.o )            \/_____/   \/_____/   \/_/ \/_/   \/_____/   \/_/\/_/   \/_/     ( o.o )
  > ^ <                                                                               > ^ < 
 /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\  /\_/\ 
( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )( o.o )
 > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ <  > ^ < 
"""

def cls():
    os.system('cls' if os.name == 'nt' else 'clear')

def bypass(pipe):
    keybd_event = windll.user32.keybd_event
    while True:
        try:
            key = pipe.recv()
            if key == b'\x01':
                keybd_event(0x4F, 0, 0, 0)  # O key press
                keybd_event(0x4F, 0, 2, 0)  # O key release
        except EOFError:
            break

def send_key_multiprocessing(pipe):
    pipe.send(b'\x01')

class Triggerbot:
    def __init__(self, pipe, keybind, fov, hsv_range, shooting_rate, fps):
        # fov is the shoot FOV (half-size of the shoot region)
        self.shoot_fov = int(fov)
        self.check_fov = int(fov * 2)  # check FOV is twice the shoot FOV

        user32 = windll.user32
        self.WIDTH, self.HEIGHT = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        center_x = int(self.WIDTH / 2)
        center_y = int(self.HEIGHT / 2)
        # All region coordinates are cast to integers.
        self.check_region = (
            int(center_x - self.check_fov),
            int(center_y - self.check_fov),
            int(center_x + self.check_fov),
            int(center_y + self.check_fov),
        )
        # The shoot region is the centered sub-region within the check region.
        # In the captured frame, the center is at (self.check_fov, self.check_fov)
        # and the shoot region spans from:
        # (check_fov - shoot_fov, check_fov - shoot_fov) to (check_fov + shoot_fov, check_fov + shoot_fov).

        # Initialize the camera with the check region.
        self.camera = bettercam.create(output_idx=0, region=self.check_region)
        self.frame = None
        self.keybind = keybind
        self.pipe = pipe

        # Convert the HSV range values to numpy arrays.
        self.cmin = numpy.array(hsv_range[0], dtype=numpy.uint8)
        self.cmax = numpy.array(hsv_range[1], dtype=numpy.uint8)

        self.shooting_rate = shooting_rate  # maximum shooting delay in ms
        self.frame_duration = 1 / fps  # seconds per frame

        # For tracking target movement
        self.prev_centroid = None
        self.prev_time = time.time()
        # Maximum expected speed in pixels per second (adjust as needed)
        self.MAX_SPEED = 750

    def Capture(self):
        while True:
            self.frame = self.camera.grab()
            time.sleep(self.frame_duration)

    def analyze_frame(self):

        if self.frame is None:
            return False, 0

        hsv = cv2.cvtColor(self.frame, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, self.cmin, self.cmax)

        # --- Analyze the shoot region (central sub-image) ---
        c = self.check_fov  # center coordinate in the captured frame
        x1 = int(c - self.shoot_fov)
        y1 = int(c - self.shoot_fov)
        x2 = int(c + self.shoot_fov)
        y2 = int(c + self.shoot_fov)
        shoot_mask = mask[y1:y2, x1:x2]

        # Divide the shoot region into four subregions.
        h_mask, w_mask = shoot_mask.shape
        margin_x = int(w_mask * 0.1)
        margin_y = int(h_mask * 0.1)
        mid_x = int(w_mask / 2)
        mid_y = int(h_mask / 2)

        regions_triggered = 0
        if numpy.count_nonzero(shoot_mask[margin_y:h_mask - margin_y, 0:mid_x]):
            regions_triggered += 1
        if numpy.count_nonzero(shoot_mask[margin_y:h_mask - margin_y, mid_x:w_mask]):
            regions_triggered += 1
        if numpy.count_nonzero(shoot_mask[0:mid_y, margin_x:w_mask - margin_x]):
            regions_triggered += 1
        if numpy.count_nonzero(shoot_mask[mid_y:h_mask, margin_x:w_mask - margin_x]):
            regions_triggered += 1

        shoot_trigger = regions_triggered >= 2

        # --- Analyze the check region for target centroid and movement ---
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Initialize speed to 0 (if no previous centroid)
        speed = 0
        if contours:
            largest = max(contours, key=cv2.contourArea)
            M = cv2.moments(largest)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                current_time = time.time()
                # Calculate speed if previous centroid exists.
                if self.prev_centroid is not None:
                    dt = current_time - self.prev_time
                    if dt > 0:
                        dx = cx - self.prev_centroid[0]
                        dy = cy - self.prev_centroid[1]
                        speed = math.hypot(dx, dy) / dt
                # Update previous centroid and time.
                self.prev_centroid = (cx, cy)
                self.prev_time = current_time

                # normalized distance from center.
                center = (self.check_fov, self.check_fov)
                distance = math.hypot(cx - center[0], cy - center[1])
                max_distance = self.check_fov * math.sqrt(2)
                normalized_distance = min(distance / max_distance, 1.0)

                # speed factor:
                # When speed is high, the factor tends toward 0 (less delay).
                # When speed is low, the factor is closer to 1.
                speed_factor = 1 - min(speed / self.MAX_SPEED, 1)

                # final delay:
                # It is proportional to the normalized distance and scaled by the speed factor.
                delay = normalized_distance * (70 / 1000) * speed_factor

                # Dynamically adjust the acceptable off-center threshold.
                # If moving fast, the threshold is smaller; if moving slow, a larger error is tolerated.
                acceptable_threshold = 0.25 * speed_factor + 0.1  # Adjust these constants as needed

                # Only allow shooting if the normalized distance is within the acceptable threshold.
                if normalized_distance > acceptable_threshold:
                    shoot_trigger = False

        return shoot_trigger, delay

    def Main(self):
        while True:
            if win32api.GetAsyncKeyState(self.keybind) < 0:
                trigger, delay = self.analyze_frame()
                if trigger:
                    time.sleep(delay)
                    send_key_multiprocessing(self.pipe)
                    time.sleep(self.shooting_rate / 1000)
            time.sleep(0.001)

def save_config(config):
    with open('config.json', 'w') as config_file:
        json.dump(config, config_file, indent=4)

def load_config():
    with open('config.json', 'r') as config_file:
        return json.load(config_file)

if __name__ == "__main__":
    print(ascii_art)
    parent_conn, child_conn = Pipe()
    p = Process(target=bypass, args=(child_conn,))
    p.start()

    # Config file handling (no new options; "fov" is the shoot FOV)
    config = {}
    if os.path.exists('config.json'):
        cls()
        print(ascii_art)
        print("Config file found. Do you want to load (1) or update (2) the config?")
        choice = int(input("Choice: "))
        cls()
        if choice == 1:
            config = load_config()
            print(ascii_art)
            print("Config loaded:")
            print(json.dumps(config, indent=4))
        else:
            config['fov'] = float(input("Enter FOV (this is the shoot FOV half-size): "))
            cls()
            print(ascii_art)
            config['keybind'] = int(input("Enter keybind (hex): "), 16)
            cls()
            print(ascii_art)
            config['shooting_rate'] = float(input("Enter maximum shooting delay (ms): "))
            cls()
            print(ascii_art)
            config['fps'] = float(input("Enter desired FPS: "))
            cls()
            print(ascii_art)
            hsv_choice = int(input("Use default HSV range (1) or custom (2)? "))
            cls()
            print(ascii_art)
            if hsv_choice == 1:
                config['hsv_range'] = [(30, 125, 150), (30, 255, 255)]
            else:
                config['hsv_range'] = [
                    [int(input("Enter lower Hue: ")), int(input("Enter lower Saturation: ")), int(input("Enter lower Value: "))],
                    [int(input("Enter upper Hue: ")), int(input("Enter upper Saturation: ")), int(input("Enter upper Value: "))]
                ]
            cls()
            print(ascii_art)
            save_config(config)
            print("Config updated:")
            print(json.dumps(config, indent=4))
    else:
        config['fov'] = float(input("Enter FOV (this is the shoot FOV half-size): "))
        cls()
        print(ascii_art)
        config['keybind'] = int(input("Enter keybind (hex): "), 16)
        cls()
        print(ascii_art)
        config['shooting_rate'] = float(input("Enter maximum shooting delay (ms): "))
        cls()
        print(ascii_art)
        config['fps'] = float(input("Enter desired FPS: "))
        cls()
        print(ascii_art)
        hsv_choice = int(input("Use default HSV range (1) or custom (2)? "))
        cls()
        print(ascii_art)
        if hsv_choice == 1:
            config['hsv_range'] = [(30, 125, 150), (30, 255, 255)]
        else:
            config['hsv_range'] = [
                [int(input("Enter lower Hue: ")), int(input("Enter lower Saturation: ")), int(input("Enter lower Value: "))],
                [int(input("Enter upper Hue: ")), int(input("Enter upper Saturation: ")), int(input("Enter upper Value: "))]
            ]
        cls()
        print(ascii_art)
        save_config(config)
        print("Config created:")
        print(json.dumps(config, indent=4))

    # Use config['fov'] as the shoot FOV; check FOV is computed as fov*2.
    triggerbot = Triggerbot(parent_conn, config['keybind'], config['fov'], config['hsv_range'], config['shooting_rate'], config['fps'])
    threading.Thread(target=triggerbot.Capture, daemon=True).start()
    threading.Thread(target=triggerbot.Main, daemon=True).start()
    p.join()
