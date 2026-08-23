# Face Detection Model

The deployment uses `yunet.onnx`: OpenCV Zoo's YuNet face **detection** model
(MIT License). The vision worker only outputs face boxes, five landmarks and
confidence. It has no identity matching, facial embeddings, reference-photo
gallery, or person search capability.

Model source and licence:
<https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet>

Do not put photographs of people in this folder.
