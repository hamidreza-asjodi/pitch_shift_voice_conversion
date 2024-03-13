import os
import threading
import numpy as np
import librosa
import pyaudio
from multiprocessing import Process, Queue
import time as tm
import wmi
MAIN_PID = os.getpid()

audio_instance = pyaudio.PyAudio()

if (True):
    scw, sch = [390, 120]
    scrol_4_width = 50
    scroles_height = 18
    font_size = 8
    paddings = 3
    font_type = "Tahoma"
    pitch_settings_margin = [-5, 5]

class logger():
    def info(x):
        print('%s | %s\n' % ('INFO', x))

    def warn(x):
        print('%s | %s\n' % ('WARN', x))
def flatten(l):
    return [item for sublist in l for item in sublist]

def ps_func(indata_q2, del_, pitch,fade_dur=50):
    """
    pitch shift function
    Args:
        indata_q2: input voice (concatenation of part of latest chunk with new input chunk)
        del_: duration of cropping from processed voice
        pitch: pitch parameter

    Returns:
        pitch shifted cropped faded voice
    """
    proc = librosa.effects.pitch_shift(indata_q2, sr=44100, n_steps=pitch)
    inference = proc[del_:-del_]
    inference[:fade_dur] *= np.linspace(0, 1, fade_dur)
    inference[-fade_dur:] *= np.linspace(1, 0, fade_dur)
    return inference
def input_queue(queue, queue2, process_duration, stop_process):
    """
    a service to manage input stream without drop or overflow using a queue in an multiprocessing structure
    Args:
        queue: we put input chunks from microphone in this queue
        queue2: a flag to start process. cause to sync with process service.
        process_duration: The duration of input chunks.
        stop_process: flag to stop processing with incoming event.
    Returns:
        input recorded queue.
    """
    audio_input_stream = audio_instance.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=44100,
        frames_per_buffer=int(44100 * 0.1),
        input=True,
        input_device_index=audio_instance.get_default_input_device_info()['index'])
    while (True):
        if stop_process.qsize() > 0:
            break
        if queue2.qsize() > 0:
            a = np.frombuffer(audio_input_stream.read(int(44100 * process_duration)), dtype=np.float32)
            queue.put(a)

def processing(inputs_queue, start_ps_flag, overlap_sec, q_p, stop_process_flag):
    """
    processing service with process from input queue and put processed chunks to output queue
    Args:
         inputs_queue: input chunks queue.
         start_ps_flag: flag queue to start put chunks to input queue.
         overlap_sec: overlap duration from last block.
         q_p: real-time change of pitch_shift parameter.
         stop_process_flag: flag to stop processing with incoming event.
    Returns:
         pitch shifted voice.
    """
    audio_output_stream = audio_instance.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=44100,
        output=True,
        output_device_index=audio_instance.get_default_output_device_info()['index'])

    # initialize to solve first delay:
    inference = ps_func(np.zeros(4410, ), 50, 1)
    audio_output_stream.write(inference.tobytes())
    start_ps_flag.put(True)
    # fill for first chunk
    old_block = np.zeros([int(overlap_sec * 44100)], dtype=np.float32).reshape(-1, 1)
    del_ = int(overlap_sec * 44100 / 2)
    logger.info("Conversion started")

    while (True):
        if q_p.qsize() > 0:
            pitch_shift = q_p.get()
        if inputs_queue.qsize() > 0:
            new_block = inputs_queue.get().reshape(-1, 1)
            indata_q2 = np.array(flatten(np.concatenate(
                [
                    old_block.astype(np.float32),
                    new_block.astype(np.float32),
                ])))
            inference = ps_func(indata_q2, del_, pitch_shift)
            old_block = new_block[-del_ * 2:]
            audio_output_stream.write(inference.tobytes())
        if stop_process_flag.qsize() > 0:
            q_p.put(pitch_shift)
            old_block = np.zeros([int(overlap_sec * 44100)], dtype=np.float32).reshape(-1, 1)
            break
        else:
            tm.sleep(0.001)

def doreal():
    import PySimpleGUI as sg
    q_stop = Queue(maxsize=1)
    q_pitch = Queue(maxsize=2)
    sg.set_options(font=(font_type, font_size))

    class GUIConfig:
        def __init__(self) -> None:
            self.pitch: int = 0
            self.samplerate: int = 44100
            self.block_time: float = 0.1  # s

    class GUI:

        def __init__(self) -> None:
            self.config = GUIConfig()
            self.flag_vc = False
            self.launcher()

        def load(self):
            
            data = {
            
                "pitch": "0",
                
            }
            return data

        def launcher(self):
            data = self.load()
            q_pitch.put(data.get("pitch", "0"))
            sg.theme("DarkGrey")
            layout = [

                [

                    sg.Frame(pad=(paddings * 2, 0), layout=[

                        [

                            sg.Slider(range=(pitch_settings_margin[0], pitch_settings_margin[1]), key="pitch",
                                      resolution=1, orientation="h", default_value=data.get("pitch", "0"),
                                      enable_events=True, pad=(paddings, paddings),
                                      size=(scrol_4_width, scroles_height)),
                        ],

                    ], title="Change pitch (per semitone)",
                             ),

                ],

                [sg.Text("")],

                [

                    sg.Button("Start", key="start_vc", pad=(paddings, paddings), size=(12, 2)),
                    sg.Text("                                                      "),
                    sg.Button("Stop", key="stop_vc", pad=(paddings, paddings), size=(12, 2)),

                ],

            ]  # endmainlayout

            self.window = sg.Window("realtime pitch shifter ", layout=layout, finalize=True, no_titlebar=False,
                                    size=(scw, sch), keep_on_top=True)

            self.event_handler()

        def event_handler(self):
            pitch_buf = None
            while True:
                event, values = self.window.read()
                if event == sg.WINDOW_CLOSED:
                    self.flag_vc = False
                    q_stop.put(True)
                    f = wmi.WMI()
                    logger.info("Terminating all python process")
                    for process in f.Win32_Process():
                        if process.id == MAIN_PID:
                            main_process = process
                        if process.name == 'python.exe' and process.id != MAIN_PID:
                            process.Terminate()
                    main_process.Terminate()
                    break

                if event == "start_vc":
                    if q_stop.qsize() > 0:
                        q_stop.get()

                if event == "start_vc" and self.flag_vc == False:
                    self.window['start_vc'].update(button_color=('white', 'red'))
                    if pitch_buf is not None:
                        q_pitch.put(pitch_buf)
                        pitch_buf = None
                    if self.set_values(values) == True:
                        self.window.refresh()
                        self.start_vc()

                if event == "stop_vc" and self.flag_vc == True:
                    q_stop.put(True)
                    self.flag_vc = False
                    self.window['start_vc'].update(button_color=('#FFFFFF', '#475841'))

                if event == "pitch":
                    self.config.pitch = values["pitch"]
                    if self.flag_vc == False:
                        pitch_buf = values['pitch']
                    else:
                        q_pitch.put(values['pitch'])
                    if hasattr(self, "rvc"):
                        self.rvc.change_key(values["pitch"])

                elif event != "start_vc" and self.flag_vc == True:
                    self.flag_vc = False
                    self.window['start_vc'].update(button_color=('#FFFFFF', '#475841'))

        def set_values(self, values):
            self.config.block_time = 0.1
            self.config.pitch = values["pitch"]
            return True

        def start_vc(self):
            self.flag_vc = True
            self.config.samplerate = 44100
            self.zc = 44100 // 100
            thread_vc = threading.Thread(target=self.vc)
            thread_vc.start()


        def vc(self):
            q_inp = Queue(maxsize=100)
            q_flag = Queue(maxsize=3)

            p1 = Process(name='p1', target=input_queue,
                         args=(q_inp, q_flag, self.config.block_time, q_stop))
            p2 = Process(name='p2', target=processing,
                         args=(q_inp, q_flag, 0.05, q_pitch, q_stop))

            p1.start()
            p2.start()
            p1.join()
            p2.join()


    gui = GUI()


if (__name__ == "__main__"):
    doreal()
