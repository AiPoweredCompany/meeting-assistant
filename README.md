# meeting-assistant
assistant to physical meeting that take notes and generate summary

This repo is aimed to set an assistant on a RPI5 with 16 GB of RAM in order to take quasi real-time transcriptions and then perform a summary of it. To perform this one will use three identical microphones connected to the RPI5 through USB.

The RPI5 will perform at start using systemd: 
1. a hotspot where a mobile device can connect
2. run a simple webpage to perform the meeting related actions such as:
    a. start / stop the transcription
    b. send the transcription and summary by emails


