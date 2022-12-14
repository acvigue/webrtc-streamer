FROM ubuntu:22.04
WORKDIR /build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update
RUN apt install -y git

RUN git clone https://github.com/johnboiles/aiortc.git

WORKDIR /build/aiortc

RUN git checkout octoprint-webrtc-support

RUN apt install -y python3-venv libavdevice-dev libavfilter-dev libopus-dev libvpx-dev pkg-config libsrtp2-dev python3 python3-dev python3-setuptools python3-pip libffi-dev

RUN pip3 install --upgrade pip
RUN pip3 install aiohttp crc32c
RUN pip3 install .

WORKDIR /build/aiortc/examples/webcam
COPY --chown=1000:1000 index.html ./
COPY --chown=1000:1000 webcam.py ./
COPY --chown=1000:1000 client.js ./

ENV VIDEO_DEVICE=/dev/video0
ENV VIDEO_PREF_CODEC=video/H264
ENV VIDEO_OPTIONS='{"video_size": "1280x720", "framerate": "30", "input_format": "h264"}'

EXPOSE 8080
ENTRYPOINT ['/bin/bash','python3','webcam.py','--no-transcode','--preferred-codec=$VIDEO_PREF_CODEC','--video-options=$VIDEO_OPTIONS','--device=$VIDEO_DEVICE']
