import streamlit as st
import numpy as np
import sys
import os
import tempfile
import torch
sys.path.append(os.getcwd())
import cv2 
from PIL import Image
import time
import utils.SessionState as SessionState
from random import randint
from streamlit.server.server import Server

from models.experimental import attempt_load
from utils.general import non_max_suppression
from utils.torch_utils import select_device


device = select_device('')

@st.cache(
    hash_funcs={
        st.delta_generator.DeltaGenerator: lambda x: None,
        "_regex.Pattern": lambda x: None,
    },
    allow_output_mutation=True,
)

def trigger_rerun():
    """
    mechanism in place to force resets and update widget states
    """
    session_infos = Server.get_current()._session_info_by_id.values() 
    for session_info in session_infos:
        this_session = session_info.session
    # this_session.request_rerun()
    st.experimental_rerun()

def DetermineBoxCenter(box):
    cx = int(box[0] + (box[2]/2))
    cy = int(box[1] + (box[3]/2))

    return [cx, cy] 

def drawBoxes(frame, pred, thres = 0.2): # thres 조절 추가 예정
    pred = pred.to('cpu')
    boxColor = (128, 255, 0) # very light green
    boxColor = {
        0: (128, 255, 0), # 헬멧O 혼자O 초록색
        1: (255, 255, 0), # 헬멧X 혼자O 하늘색
        2: (0, 0, 255), # 헬멧O 혼자X 빨간색
        3: (255, 0, 0), # 헬멧X 혼자X 파란색
    }
    className = {
        0: "Helmet",
        1: "NoHelmet",
        2: "SharingHelmet",
        3: "Sharing",
    }
    TextColor = (255, 255, 255) # white
    boxThickness = 3 

    for x1, y1, x2, y2, conf, lbl in pred:
        if conf < thres:
            break
        lbl = int(lbl)
        if lbl not in [0,1,2,3]:
            continue
        x1, y1, x2, y2, conf = int(x1), int(y1), int(x2), int(y2), float(conf) # tensor to int or float
        start_coord = (x1, y1)
        end_coord = (x2, y2)
        # text to be included to the output image
        txt = f'{className[lbl]} ({round(conf, 3)})'
        frame = cv2.rectangle(frame, start_coord, end_coord, boxColor[lbl], boxThickness)
        frame = cv2.putText(frame, txt, start_coord, cv2.FONT_HERSHEY_SIMPLEX, 0.5, TextColor, 2)

    return frame
    
def lookup_checkpoint_files():

    flie_list = list(os.listdir('/content/drive/MyDrive/web/'))
    flie_list.sort()
    checkpoint_flie_list = []
    for file in flie_list:
        if file[-3:] == '.pt':
            checkpoint_flie_list.append(file)

    return tuple(checkpoint_flie_list)

def np_to_tensor(image):
    
    image_tensor = np.transpose(image, (2, 0, 1))
    image_tensor = torch.from_numpy(image_tensor).to(device)
    image_tensor = image_tensor.float()  # uint8 to fp16/32
    image_tensor /= 255.0  # 0 - 255 to 0.0 - 1.0
    if image_tensor.ndimension() == 3:
        image_tensor = image_tensor.unsqueeze(0)

    return image_tensor

def main():
    st.set_page_config(page_title = "안전모 미착용, 승차인원 초과 멈춰~!", 
    page_icon=":scooter:")

    state = SessionState.get(upload_key = None, enabled = True, start = False, conf = 70, nms = 50, run = False)

    upload = st.empty()
    start_button = st.empty()
    stop_button = st.empty()


    with upload:
        f = st.file_uploader('Upload Image or Video file', key = state.upload_key)

        ckpt_files = lookup_checkpoint_files()

        ckpt_file = st.sidebar.radio(
            "select checkpoint file",
            ckpt_files
        )

        confidence_threshold = st.sidebar.slider("Confidence score threshold", 
            min_value=0.1,
            max_value=1.0,
            value=0.7,
            step=0.05,
            )
        
        result_resolution = st.sidebar.radio(
            "select result video resolution",
            ("1280 x 960",)
        )

        if result_resolution == "1280 x 960":
            width, height = 1280, 960
        elif result_resolution == "640 x 480":
            width, height = 640, 480
    
    filepath = '/content/drive/MyDrive/web/result.mp4'
    filepath_h264 = '/content/drive/MyDrive/web/result_h264.mp4'

    if f is not None:

        tfile = tempfile.NamedTemporaryFile(delete = False)
        tfile.write(f.read())  
        upload.empty()
        if f.type.split('/')[0].lower() == 'image':
            vf = Image.open(tfile.name)
            st.image(vf)
        else:
            vf = cv2.VideoCapture(tfile.name)
        print(type(vf))

        if not state.run:
            start = start_button.button("start")
            state.start = start

        if state.start:
            start_button.empty()
            #state.upload_key = str(randint(1000, int(1e6)))
            state.enabled = False
            if state.run:
                tfile.close()
                f.close()
                state.upload_key = str(randint(1000, int(1e6)))
                state.enabled = True
                state.run = False
                
                if os.path.exists(filepath):
                    os.remove(filepath)
                if os.path.exists(filepath_h264):
                    os.remove(filepath_h264)

                model = attempt_load(f'/content/drive/MyDrive/web/{ckpt_file}', map_location=device)

                if isinstance(vf, cv2.VideoCapture):                       
                    ProcessFrames(vf, model, stop_button, confidence_threshold, width, height)
                else:
                    ProcessImage(vf, model, confidence_threshold, width, height)
            else:
                state.run = True
                trigger_rerun()

    # ######## TEST MODE #######
    # vf = cv2.VideoCapture('/opt/ml/video/GOPR1300.MP4')
    # ProcessFrames(vf, model, stop_button)
    # ######## TEST MODE #######


def ProcessImage(image, obj_detector, confidence_threshold, width, height):
    image = np.array(image) #pil to cv
    image = cv2.resize(image, (width, height))
    
    image_tensor = np_to_tensor(image)

    pred = obj_detector(image_tensor)[0]
    pred = non_max_suppression(pred)[0]
    image = drawBoxes(image, pred, confidence_threshold) 
    st.image(image)

def ProcessFrames(vf, obj_detector, stop, confidence_threshold, width, height): 
    """
        main loop for processing video file:
        Params
        vf = VideoCapture Object
        obj_detector = Object detector (model and some properties) 
    """
    try:
        num_frames = int(vf.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = int(vf.get(cv2.CAP_PROP_FPS)) 
        print('Total number of frames to be processed:', num_frames,
        '\nFrame rate (frames per second):', fps)
    except:
        print('We cannot determine number of frames and FPS!')


    frame_counter = 0
    _stop = stop.button("stop")
    # new_car_count_txt = st.empty()
    fps_meas_txt = st.empty()
    bar = st.progress(frame_counter)
    start = time.time()
    fourcc = cv2.VideoWriter_fourcc(*'mp4v') # output video codec
    video_writer = cv2.VideoWriter(
                            "/content/drive/MyDrive/web/result.mp4", fourcc, fps, (width, height)
                        ) # Warning: 마지막 파라미터(이미지 크기 예:(1280, 960))가 안 맞으면 동영상이 저장이 안 됨!

    while vf.isOpened():
        # if frame is read correctly ret is True
        ret, frame = vf.read()
        try:
            frame = cv2.resize(frame, (width, height)) # 추후 조절하는 기능 추가할 예정
        except: 
            print('resize failed :', frame_counter)
            if frame_counter/num_frames == 1:
                break
            continue

        if _stop:
            break
        if not ret:
            print("Can't receive frame (stream end?). Exiting ...")
        frame_tensor = np_to_tensor(frame)
        pred = obj_detector(frame_tensor)[0]
        pred = non_max_suppression(pred)[0]
        frame = drawBoxes(frame, pred, confidence_threshold) 

        end = time.time()

        frame_counter += 1
        fps_measurement = frame_counter/(end - start)
        fps_meas_txt.markdown(f'**Frames per second:** {fps_measurement:.2f}')
        bar.progress(frame_counter/num_frames)        
        video_writer.write(frame)

    video_writer.release()    
    print('finish!')
    with st.spinner(text="Detecting Finished! Converting Video Codec..."):
        os.system("ffmpeg -i /content/drive/MyDrive/web/result.mp4 -vcodec libx264 /content/drive/MyDrive/web/result_h264.mp4")
    # 서버에 저장된 동영상 파일을 불러와 페이지에 띄우는 부분
    video_file = open("/content/drive/MyDrive/web/result_h264.mp4", 'rb')
    video_bytes = video_file.read()
    st.video(video_bytes)


main()