import argparse
import asyncio
import json
import logging
import os
import platform
import ssl

from aiohttp import web
from multidict import MultiDict

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.rtcrtpsender import RTCRtpSender

ROOT = os.path.dirname(__file__)
# Max number of connections allowed. When this number is exceeded,
# new client connections will force old clients to close
MAX_CONNECTIONS = 5

relay = None
webcam = None
# Storage for RTCPeerConnections
pcs = []


def create_local_tracks(play_from, transcode=True, options=None, device="/dev/video0"):
    global relay, webcam

    if play_from:
        player = MediaPlayer(play_from, transcode=transcode)
        return player.audio, player.video
    else:
        if options is None:
            options = {"framerate": "30", "video_size": "640x480"}
        if relay is None:
            if platform.system() == "Darwin":
                webcam = MediaPlayer(
                    "default:none", format="avfoundation", options=options
                )
            elif platform.system() == "Windows":
                webcam = MediaPlayer(
                    "video=Integrated Camera", format="dshow", options=options
                )
            else:
                webcam = MediaPlayer(device, format="v4l2", transcode=transcode, options=options)

            relay = MediaRelay()
        return None, relay.subscribe(webcam.video, buffered=True)

async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    content = open(os.path.join(ROOT, "client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)

async def offer_options(request):
    return web.Response(
        headers=MultiDict({
            'Access-Control-Allow-Origin': "*",
            'Access-Control-Allow-Methods': "POST",
            'Access-Control-Allow-Headers': "*",
        }),
    )

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.append(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logging.info("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            # May have already been removed if it was force-disconnected
            if pc in pcs:
                pcs.remove(pc)
        elif pc.connectionState == 'connected':
            # Disconnect old clients if we're at our limit
            if (len(pcs) > MAX_CONNECTIONS):
                old_pc = pcs.pop(0)
                logging.warning(f"Force-disconnecting old client {old_pc}")
                await old_pc.close()

    # open media source
    audio, video = create_local_tracks(args.play_from, transcode=args.transcode, options=args.video_options, device=args.device)

    if video:
        pc.addTrack(video)
        if args.preferred_codec:
            # Filter for only for the preferred_codec
            codecs = RTCRtpSender.getCapabilities("video").codecs
            preferences = [codec for codec in codecs if codec.mimeType == args.preferred_codec]
            transceiver = pc.getTransceivers()[0]
            transceiver.setCodecPreferences(preferences)

    await pc.setRemoteDescription(offer)
    for t in pc.getTransceivers():
        if t.kind == "audio" and audio:
            pc.addTrack(audio)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        headers=MultiDict({
            'Access-Control-Allow-Origin': "*",
            'Access-Control-Allow-Methods': "POST",
            'Access-Control-Allow-Headers': "*",
        }),
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC webcam demo")
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    parser.add_argument("--play-from", help="Read the media from a file and sent it."),
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for HTTP server (default: 8080)"
    )
    
    parser.add_argument("--verbose", "-v", action="count")
    parser.add_argument("--preferred-codec", help="Preferred codec to use (e.g. video/H264)")
    parser.add_argument("--video-options", type=json.loads, help="Options to pass into av.open")
    parser.add_argument(
        "--device", default="/dev/video0", help="V4L2 device"
    )
    transcode_parser = parser.add_mutually_exclusive_group(required=False)
    transcode_parser.add_argument('--transcode', dest='transcode', action='store_true')
    transcode_parser.add_argument('--no-transcode', dest='transcode', action='store_false')
    parser.set_defaults(transcode=True)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    app.router.add_options("/offer", offer_options)
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)
