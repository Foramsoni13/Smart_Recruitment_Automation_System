*** Settings ***
Documentation     AI Facial Recognition Video Stream Telemetry Automation Test Suite
Library           ../../resources/proctoring_keywords.py
Library           OperatingSystem

*** Variables ***
${WEBRTC_STREAM_MOCK}    chrome://use-fake-device-for-media-stream

*** Test Cases ***
Verify WebRTC Camera AI Facial Recognition And Telemetry Anomalies
    [Documentation]    Verifies automated WebRTC stream canvas frame capture, MediaPipe 468 face mesh landmarks, and head pose anomaly detection.
    Log    Starting AI Facial Recognition Video Stream Telemetry Test...
    ${telemetry}=    Analyze Facial Video Stream    ${WEBRTC_STREAM_MOCK}
    Log    WebRTC Face Mesh Telemetry: ${telemetry}
    Assert Proctoring Telemetry    ${telemetry}
    Should Be Equal As Integers    ${telemetry['faces_detected']}    1
    Should Be True    ${telemetry['confidence_score']} >= 0.90
    Log    AI Facial Recognition Video Stream Telemetry Test PASSED cleanly!
